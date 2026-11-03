"""``dhis2.metadata``: read one metadata resource through the version-bound generic accessor."""

import re
import time
from typing import Any, ClassVar, Final, cast

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.messages import METADATA_UNKNOWN_RESOURCE
from dirigent_dhis2.reads import Dhis2Pager, pager_of
from dirigent_dhis2.web import Dhis2Operator, query_terms, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: A DHIS2 collection name as it appears in the API path: lower camel case, letters and digits.
RESOURCE_PATTERN: Final = r"^[a-z][A-Za-z0-9]*$"

#: The boundary before each capital in a camel-case name, where snake case puts its underscore.
_CAMEL_BOUNDARY: Final = re.compile(r"(?<!^)(?=[A-Z])")


class Dhis2MetadataConfig(BlockModel):
    """Which metadata resource to read, and how the collection is narrowed.

    One collection per step. Several collections at once are one ``dhis2.metadata_export``
    step instead. Counting a collection is this block with ``paging: true`` and
    ``page_size: 1``: the output's ``pager.total`` is the count, and one row is all that is sent.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    resource: str = Field(pattern=RESOURCE_PATTERN)
    """The DHIS2 collection name, as it appears in the API path: ``organisationUnits``,
    ``dataElements``, ``dataSets``, ``indicators``, ``programs``, ``optionSets``,
    ``trackedEntityTypes``, and the rest the version-bound client knows."""

    fields: str | list[str] | None = None
    """The DHIS2 ``fields=`` selector, as one string such as ``id,name,valueType`` or a list
    such as ``[id, name, valueType]`` that is sent comma-joined; the instance's own default
    when unset. Inside a YAML flow list a nested selector such as ``parent[id,code]`` must be
    quoted, as in ``[id, "parent[id,code]"]``, because YAML refuses an unquoted bracket or
    comma in a flow item."""

    filter: str | list[str] | None = None
    """One or more DHIS2 ``filter=`` expressions: one string such as ``level:eq:2``, or a list
    such as ``[level:eq:2, name:like:Bo]`` that is sent as one ``filter=`` each, ANDed unless
    the resource is told otherwise."""

    paging: bool = False
    """Whether the read is paged. Off by default: a metadata read wants the whole collection,
    not the first page of it."""

    order: str | list[str] | None = None
    """The DHIS2 ``order=`` terms: one string such as ``name:asc``, or a list such as
    ``[level:asc, name:asc]`` that is sent comma-joined, the first term sorting first."""

    page: int | None = None
    """The 1-based page to read, when ``paging`` is on."""

    page_size: int | None = None
    """How many rows a page holds, when ``paging`` is on."""


class Dhis2MetadataOutput(BlockModel):
    """The rows the read answered, and where a paged read stands in the collection."""

    rows: list[JsonValue]
    """The collection's rows, each with the fields ``fields`` selected."""

    pager: Dhis2Pager | None = None
    """The page read, the page size, the collection's total, and whether more pages follow;
    null when the read is not paged and so answered every row."""

    duration_ms: int
    """How long the read took."""


def accessor_name(resource: str) -> str:
    """Name the accessor a DHIS2 collection is published under: ``dataElements`` is ``data_elements``."""
    return _CAMEL_BOUNDARY.sub("_", resource).lower()


def resource_accessor(client: Dhis2Client, resource: str) -> Any:
    """Find the generic resource accessor whose DHIS2 collection name is ``resource``.

    The version-bound ``client.resources`` publishes one accessor per collection, named
    after the collection in snake case, so the lookup is by that public name rather than by
    anything the generated code keeps to itself. A name the bound version does not publish
    is rejected rather than retried.
    """
    candidate = getattr(client.resources, accessor_name(resource), None)
    if candidate is None or not callable(getattr(candidate, "list_raw", None)):
        raise BlockFailure(METADATA_UNKNOWN_RESOURCE, error_class=ErrorClass.REJECTED, resource=resource)
    return candidate


class Dhis2MetadataOperator(Dhis2Operator[Dhis2MetadataConfig, Dhis2MetadataOutput]):
    """Reads one metadata collection and hands the parsed response on."""

    spec = OperatorSpec(
        id="dhis2.metadata",
        summary="Read one DHIS2 metadata collection, whole or one page of it.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2MetadataConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2MetadataOutput

    async def execute(self, config: Dhis2MetadataConfig, ctx: StepContext) -> Dhis2MetadataOutput:
        """Read the collection through the version-bound accessor, classifying an HTTP refusal."""
        started = time.monotonic()
        terms = query_terms(fields=config.fields, filter=config.filter, order=config.order)
        async with client_for(ctx, config.connection) as client:
            resource = resource_accessor(client, config.resource)
            try:
                body = await resource.list_raw(
                    fields=terms.fields,
                    filters=terms.filter,
                    # The accessor repeats what it is given, so the joined order rides as its one item.
                    order=None if terms.order is None else [terms.order],
                    page=config.page,
                    page_size=config.page_size,
                    paging=config.paging,
                )
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET /api/{config.resource}") from error
        duration = round((time.monotonic() - started) * 1000)
        answer: dict[str, Any] = cast("dict[str, Any]", body) if isinstance(body, dict) else {}
        listed = answer.get(config.resource)
        rows = cast("list[JsonValue]", listed) if isinstance(listed, list) else []
        pager = pager_of(answer, len(rows)) if config.paging else None
        ctx.log.info("metadata read", resource=config.resource, rows=len(rows), duration_ms=duration)
        return Dhis2MetadataOutput(rows=rows, pager=pager, duration_ms=duration)
