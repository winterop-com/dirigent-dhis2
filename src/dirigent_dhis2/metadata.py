"""``dhis2.metadata``: read one metadata resource through the version-bound generic accessor."""

import re
import time
from typing import Any, ClassVar, Final

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ErrorClass, OperatorSpec, StepContext

#: A DHIS2 collection name as it appears in the API path: lower camel case, letters and digits.
RESOURCE_PATTERN: Final = r"^[a-z][A-Za-z0-9]*$"

#: The boundary before each capital in a camel-case name, where snake case puts its underscore.
_CAMEL_BOUNDARY: Final = re.compile(r"(?<!^)(?=[A-Z])")


class Dhis2MetadataConfig(BlockModel):
    """Which metadata resource to read, and how the collection is narrowed."""

    connection: str
    """The code of the dhis2 connection naming the instance."""

    resource: str = Field(pattern=RESOURCE_PATTERN)
    """The DHIS2 collection name, as it appears in the API path: ``organisationUnits``,
    ``dataElements``, ``dataSets``, ``indicators``, ``programs``, ``optionSets``,
    ``trackedEntityTypes``, and the rest the version-bound client knows."""

    fields: str | None = None
    """The DHIS2 ``fields=`` selector, such as ``id,name,valueType``; the instance's own
    default when unset."""

    filter: str | list[str] | None = None
    """One or more DHIS2 ``filter=`` expressions, such as ``level:eq:2``. A single string is
    one filter; a list is several, ANDed unless the resource is told otherwise."""

    paging: bool = False
    """Whether the read is paged. Off by default: a metadata read wants the whole collection,
    not the first page of it."""

    order: list[str] | None = None
    """The DHIS2 ``order=`` terms, such as ``name:asc``."""

    page: int | None = None
    """The 1-based page to read, when ``paging`` is on."""

    page_size: int | None = None
    """How many rows a page holds, when ``paging`` is on."""


class Dhis2MetadataOutput(BlockModel):
    """The collection the read answered, for a downstream step to reference by field."""

    json_body: JsonValue | None = None
    """The parsed response: the collection under its own key, and a ``pager`` when paged."""

    duration_ms: int


def accessor_name(resource: str) -> str:
    """Name the accessor a DHIS2 collection is published under: ``dataElements`` is ``data_elements``."""
    return _CAMEL_BOUNDARY.sub("_", resource).lower()


def _accessor(client: Dhis2Client, resource: str) -> Any:
    """Find the generic resource accessor whose DHIS2 collection name is ``resource``.

    The version-bound ``client.resources`` publishes one accessor per collection, named
    after the collection in snake case, so the lookup is by that public name rather than by
    anything the generated code keeps to itself. A name the bound version does not publish
    is rejected rather than retried.
    """
    candidate = getattr(client.resources, accessor_name(resource), None)
    if candidate is None or not callable(getattr(candidate, "list_raw", None)):
        raise BlockFailure(
            f"the instance's version knows no metadata resource named {resource!r}",
            error_class=ErrorClass.REJECTED,
        )
    return candidate


class Dhis2MetadataOperator(Dhis2Operator[Dhis2MetadataConfig, Dhis2MetadataOutput]):
    """Reads one metadata collection and hands the parsed response on."""

    spec = OperatorSpec(
        id="dhis2.metadata",
        summary="Read a DHIS2 metadata resource.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2MetadataConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2MetadataOutput

    async def execute(self, config: Dhis2MetadataConfig, ctx: StepContext) -> Dhis2MetadataOutput:
        """Read the collection through the version-bound accessor, classifying an HTTP refusal."""
        started = time.monotonic()
        filters = [config.filter] if isinstance(config.filter, str) else config.filter
        async with client_for(ctx, config.connection) as client:
            resource = _accessor(client, config.resource)
            try:
                body = await resource.list_raw(
                    fields=config.fields,
                    filters=filters,
                    order=config.order,
                    page=config.page,
                    page_size=config.page_size,
                    paging=config.paging,
                )
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET /api/{config.resource}") from error
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info("metadata read", resource=config.resource, duration_ms=duration)
        return Dhis2MetadataOutput(json_body=body, duration_ms=duration)
