"""``dhis2.metadata_export``: read several metadata collections in one ``GET /api/metadata``."""

import time
from typing import Annotated, Any, ClassVar, Final, cast

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.metadata import RESOURCE_PATTERN, resource_accessor
from dirigent_dhis2.web import Dhis2Operator, query_terms, refuse
from dirigent_plugin import ConnectionRef, OperatorSpec, StepContext

#: Where metadata is exported, several collections in one answer.
METADATA_PATH: Final = "/api/metadata"

#: A DHIS2 collection name, as a key or an item of ``resources``.
ResourceName = Annotated[str, Field(pattern=RESOURCE_PATTERN)]


class Dhis2MetadataSelection(BlockModel):
    """How one collection of an export is narrowed, in place of the export's shared terms."""

    fields: str | list[str] | None = None
    """This collection's ``fields=`` selector, in place of the shared one: one string such as
    ``id,name`` or a list sent comma-joined."""

    filter: str | list[str] | None = None
    """This collection's ``filter=`` expressions, in place of the shared ones: one string such as
    ``level:le:2`` or a list sent as one filter each and ANDed."""

    order: str | list[str] | None = None
    """This collection's ``order=`` terms, in place of the shared ones: one string such as
    ``name:asc`` or a list sent comma-joined."""


class Dhis2MetadataExportConfig(BlockModel):
    """Which metadata collections to read together, and how each is narrowed.

    Several collections in one ``GET /api/metadata`` request, answered as one object keyed by
    collection. ``/api/metadata`` has no pager and answers with every row that matches, so a step
    that only wants how many rows a collection holds reads it with ``dhis2.metadata``,
    ``paging: true`` and ``page_size: 1`` and takes ``pager.total`` instead. One collection on its
    own, or one page of it, is also ``dhis2.metadata``.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    resources: list[ResourceName] | dict[ResourceName, Dhis2MetadataSelection] = Field(min_length=1)
    """The DHIS2 collection names to read, as they appear in the API path: a list such as
    ``[dataSets, programs]`` that each take the shared terms, or a mapping from a name to its own
    ``fields``, ``filter`` and ``order``, where a term a collection leaves unset falls back to the
    shared one and ``{}`` takes them all."""

    fields: str | list[str] | None = None
    """The ``fields=`` selector every collection is read with unless it names its own: one string
    such as ``id,name`` or a list sent comma-joined; DHIS2's own ``:owner`` when unset."""

    filter: str | list[str] | None = None
    """The ``filter=`` expressions every collection is narrowed by unless it names its own: one
    string such as ``name:like:ANC`` or a list sent as one filter each and ANDed."""

    order: str | list[str] | None = None
    """The ``order=`` terms every collection is sorted by unless it names its own: one string such
    as ``name:asc`` or a list sent comma-joined."""


class Dhis2MetadataExportOutput(BlockModel):
    """The collections the export answered, each under its own name."""

    collections: dict[str, list[JsonValue]]
    """Every collection asked for, keyed by its name, holding the rows the instance answered
    with; an empty list for a collection with no row that matched."""

    counts: dict[str, int]
    """How many rows each collection holds in ``collections``, keyed by its name."""

    duration_ms: int
    """How long the export took."""


def selections(config: Dhis2MetadataExportConfig) -> dict[str, Dhis2MetadataSelection]:
    """Resolve each collection's own terms, a term it leaves unset taken from the shared one."""
    named = (
        config.resources
        if isinstance(config.resources, dict)
        else {resource: Dhis2MetadataSelection() for resource in config.resources}
    )
    return {
        resource: Dhis2MetadataSelection(
            fields=own.fields if own.fields is not None else config.fields,
            filter=own.filter if own.filter is not None else config.filter,
            order=own.order if own.order is not None else config.order,
        )
        for resource, own in named.items()
    }


def export_params(chosen: dict[str, Dhis2MetadataSelection]) -> dict[str, Any]:
    """Build the ``/api/metadata`` query: ``<resource>=true`` and its ``<resource>:<term>`` each.

    Every term is sent scoped to its collection, never as a bare ``fields``, ``filter`` or
    ``order`` that DHIS2 would apply to all of them.
    """
    params: dict[str, Any] = {}
    for resource, selection in chosen.items():
        params[resource] = "true"
        terms = query_terms(fields=selection.fields, filter=selection.filter, order=selection.order)
        if terms.fields is not None:
            params[f"{resource}:fields"] = terms.fields
        if terms.filter is not None:
            params[f"{resource}:filter"] = terms.filter
        if terms.order is not None:
            params[f"{resource}:order"] = terms.order
    return params


class Dhis2MetadataExportOperator(Dhis2Operator[Dhis2MetadataExportConfig, Dhis2MetadataExportOutput]):
    """Reads several metadata collections in one request and hands each on under its name."""

    spec = OperatorSpec(
        id="dhis2.metadata_export",
        summary="Read several DHIS2 metadata collections, every row of each, in one request.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2MetadataExportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2MetadataExportOutput

    async def execute(self, config: Dhis2MetadataExportConfig, ctx: StepContext) -> Dhis2MetadataExportOutput:
        """Check every name against the bound version, then read them all in one export."""
        started = time.monotonic()
        chosen = selections(config)
        async with client_for(ctx, config.connection) as client:
            for resource in chosen:
                resource_accessor(client, resource)
            try:
                body = await client.get_raw(METADATA_PATH, params=export_params(chosen))
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {METADATA_PATH}") from error
        collections: dict[str, list[JsonValue]] = {}
        for resource in chosen:
            rows = body.get(resource)
            collections[resource] = cast("list[JsonValue]", rows) if isinstance(rows, list) else []
        duration = round((time.monotonic() - started) * 1000)
        counts = {resource: len(rows) for resource, rows in collections.items()}
        logged: dict[str, JsonValue] = {resource: count for resource, count in counts.items()}
        ctx.log.info("metadata exported", counts=logged, duration_ms=duration)
        return Dhis2MetadataExportOutput(collections=collections, counts=counts, duration_ms=duration)
