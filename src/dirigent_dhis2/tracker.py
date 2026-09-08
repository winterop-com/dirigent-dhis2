"""``dhis2.tracker``: read tracked entities, enrollments, or events out of ``/api/tracker``."""

import time
from typing import ClassVar, Final, Literal

from dhis2w_client import TrackerAccessor
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import OperatorSpec, StepContext

#: The tracker export root the three object kinds hang off.
TRACKER_PATH: Final = "/api/tracker"

#: The tracker collections this block reads, keyed by the ``kind`` a document names.
TrackerKind = Literal["trackedEntities", "enrollments", "events"]

#: How DHIS2 reads the org unit a tracker query names.
OrgUnitMode = Literal["SELECTED", "CHILDREN", "DESCENDANTS", "ACCESSIBLE", "CAPTURE", "ALL"]


class Dhis2TrackerConfig(BlockModel):
    """Which tracker collection to read, and how it is scoped."""

    connection: str
    """The code of the dhis2 connection naming the instance."""

    kind: TrackerKind
    """The tracker collection to read: ``trackedEntities``, ``enrollments``, or ``events``."""

    program: str | None = None
    """The uid of the program to scope the read to."""

    org_unit: str | None = None
    """The uid of the organisation unit to read within."""

    ou_mode: OrgUnitMode | None = None
    """How the org unit is interpreted: ``SELECTED``, ``CHILDREN``, ``DESCENDANTS``,
    ``ACCESSIBLE``, ``CAPTURE``, or ``ALL``."""

    fields: str | None = None
    """The DHIS2 ``fields=`` selector; the instance's own default when unset."""

    filter: str | list[str] | None = None
    """One or more DHIS2 ``filter=`` expressions on the collection's attributes."""

    status: str | None = None
    """The status to read, where the collection has one: an enrollment or event ``status``."""

    updated_after: str | None = None
    """Read only rows changed at or after this ISO instant."""

    page: int | None = None
    """The 1-based page to read."""

    page_size: int | None = None
    """How many rows a page holds."""


class Dhis2TrackerOutput(BlockModel):
    """The tracker page the read answered, for a downstream step to reference by field."""

    json_body: JsonValue | None = None
    """The parsed response: the objects under ``instances`` and the ``page`` block DHIS2 sends."""

    duration_ms: int


class Dhis2TrackerOperator(Dhis2Operator[Dhis2TrackerConfig, Dhis2TrackerOutput]):
    """Reads one tracker collection and hands the parsed page on."""

    spec = OperatorSpec(
        id="dhis2.tracker",
        summary="Read DHIS2 tracker objects.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2TrackerConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2TrackerOutput

    async def execute(self, config: Dhis2TrackerConfig, ctx: StepContext) -> Dhis2TrackerOutput:
        """Read the collection once through its tracker reader, classifying an HTTP refusal."""
        started = time.monotonic()
        async with client_for(ctx, config.connection) as client:
            try:
                body = await self._read(client.tracker, config)
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {TRACKER_PATH}/{config.kind}") from error
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info("tracker read", kind=config.kind, duration_ms=duration)
        return Dhis2TrackerOutput(json_body=body, duration_ms=duration)

    async def _read(self, tracker: TrackerAccessor, config: Dhis2TrackerConfig) -> JsonValue:
        """Dispatch on the collection ``kind`` to the tracker accessor that reads it."""
        if config.kind == "trackedEntities":
            return await tracker.tracked_entities(
                program=config.program,
                org_unit=config.org_unit,
                ou_mode=config.ou_mode,
                status=config.status,
                fields=config.fields,
                filter=config.filter,
                page=config.page,
                page_size=config.page_size,
                updated_after=config.updated_after,
            )
        if config.kind == "enrollments":
            # The enrollments reader has no ``filter`` argument; the collection's filter rides
            # through as an extra query param so the block's contract still applies.
            filter_param = None
            if config.filter is not None:
                values = [config.filter] if isinstance(config.filter, str) else config.filter
                filter_param = {"filter": values}
            return await tracker.enrollments(
                program=config.program,
                org_unit=config.org_unit,
                ou_mode=config.ou_mode,
                status=config.status,
                fields=config.fields,
                page=config.page,
                page_size=config.page_size,
                updated_after=config.updated_after,
                extra_params=filter_param,
            )
        return await tracker.events(
            program=config.program,
            org_unit=config.org_unit,
            ou_mode=config.ou_mode,
            status=config.status,
            fields=config.fields,
            filter=config.filter,
            page=config.page,
            page_size=config.page_size,
            updated_after=config.updated_after,
        )
