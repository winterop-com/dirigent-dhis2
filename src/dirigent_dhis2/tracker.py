"""``dhis2.tracker``: read tracked entities, enrollments, or events out of ``/api/tracker``."""

import json
import time
from typing import Any, ClassVar, Final, Literal, NoReturn, cast

from dhis2w_client import TrackerAccessor
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_common import BlockModel, Size
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.messages import TRACKER_CAP_REACHED, TRACKER_PAGE_WITH_ALL_PAGES
from dirigent_dhis2.reads import Dhis2Pager, pager_of, require_known
from dirigent_dhis2.web import Dhis2Operator, query_terms, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: The tracker export root the three object kinds hang off.
TRACKER_PATH: Final = "/api/tracker"

#: The tracker collections this block reads, keyed by the ``kind`` a document names.
TrackerKind = Literal["trackedEntities", "enrollments", "events"]

#: How DHIS2 reads the org unit a tracker query names.
OrgUnitMode = Literal["SELECTED", "CHILDREN", "DESCENDANTS", "ACCESSIBLE", "CAPTURE", "ALL"]

#: How many rows a page holds when every page is read and the step names no page size.
ALL_PAGES_PAGE_SIZE: Final = 500


class Dhis2TrackerConfig(BlockModel):
    """Which tracker collection to read, and how it is scoped."""

    connection: ConnectionRef
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

    fields: str | list[str] | None = None
    """The DHIS2 ``fields=`` selector, as one string such as ``event,status`` or a list such as
    ``[event, status]`` that is sent comma-joined; the instance's own default when unset.
    Inside a YAML flow list a nested selector such as ``dataValues[dataElement,value]`` must be
    quoted, as in ``[event, "dataValues[dataElement,value]"]``, because YAML refuses an
    unquoted bracket or comma in a flow item."""

    filter: str | list[str] | None = None
    """One or more DHIS2 ``filter=`` expressions on the collection's attributes: one string
    such as ``w75KJ2mc4zz:like:Anna``, or a list such as
    ``[w75KJ2mc4zz:like:Anna, zDhUuAYrxNC:like:Kelly]`` that is sent as one ``filter=`` each.
    Tracked entities and events take one; the enrollments collection has no attribute filter of
    its own, so a filter given for it rides through as a plain query parameter the instance may
    ignore."""

    status: str | None = None
    """The status to read, where the collection has one: an enrollment or event ``status``."""

    updated_after: str | None = None
    """Read only rows changed at or after this ISO instant."""

    page: int | None = Field(default=None, ge=1)
    """The 1-based page to read; the first when unset. The output's ``pager.more`` says whether
    more pages follow it."""

    page_size: int | None = Field(default=None, ge=1)
    """How many rows a page holds: the instance's own default, 50, for one page, and 500 when
    every page is read."""

    all_pages: bool = False
    """Whether every page is read, from the first until the instance has no more, and answered
    as one list. The read is bounded by ``max_rows``, ``max_pages`` and ``max_total``, and fails
    rather than answering part of the collection when one is reached."""

    total: bool = False
    """Whether the instance counts every matching row (``totalPages=true``), so that
    ``pager.total`` and ``pager.page_count`` are known. Counting costs the instance a query of
    its own."""

    max_rows: int = Field(default=100_000, ge=1)
    """The most rows reading every page may gather before the step fails."""

    max_pages: int = Field(default=1_000, ge=1)
    """The most pages reading every page may request before the step fails."""

    max_total: Size = Field(default=256 * 1024 * 1024, ge=1)
    """The most the gathered rows may come to, as JSON, before reading every page fails."""

    require_known: bool = True
    """Whether the step fails when the named program or org unit is unknown to the instance,
    rather than answering no rows for it. One metadata lookup asks for both before the read."""

    @model_validator(mode="after")
    def _all_pages_starts_at_the_first(self) -> "Dhis2TrackerConfig":
        """Refuse a page beside all_pages, which reads from the first page on its own."""
        if self.all_pages and self.page is not None:
            raise ValueError(TRACKER_PAGE_WITH_ALL_PAGES.render())
        return self


class Dhis2TrackerOutput(BlockModel):
    """The tracker rows the read answered, and where the read stands in the collection."""

    rows: list[JsonValue]
    """The tracked entities, enrollments or events read, every page's in order when every page was read."""

    pager: Dhis2Pager
    """The page the rows came from, the page size, the totals when counted, and whether more
    pages follow."""

    duration_ms: int
    """How long the read took."""


def _rows(body: dict[str, Any], kind: str) -> list[JsonValue]:
    """The rows of one page: under ``instances``, or under the collection's own name, as 2.43 keys them."""
    rows = body.get("instances", body.get(kind))
    return cast("list[JsonValue]", rows) if isinstance(rows, list) else []


class Dhis2TrackerOperator(Dhis2Operator[Dhis2TrackerConfig, Dhis2TrackerOutput]):
    """Reads one tracker collection, a page of it or every page, and hands the rows on."""

    spec = OperatorSpec(
        id="dhis2.tracker",
        summary="Read DHIS2 tracker objects.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2TrackerConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2TrackerOutput

    async def execute(self, config: Dhis2TrackerConfig, ctx: StepContext) -> Dhis2TrackerOutput:
        """Read one page, or every page within the caps, classifying an HTTP refusal."""
        started = time.monotonic()
        where = f"GET {TRACKER_PATH}/{config.kind}"
        async with client_for(ctx, config.connection) as client:
            if config.require_known:
                await require_known(client, {"programs": config.program, "organisationUnits": config.org_unit}, where)
            try:
                if config.all_pages:
                    rows, pager = await self._every_page(client.tracker, config)
                else:
                    body = await self._read(client.tracker, config, config.page, config.page_size)
                    rows = _rows(body, config.kind)
                    pager = pager_of(body, len(rows))
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, where) from error
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info("tracker read", kind=config.kind, rows=len(rows), more=pager.more, duration_ms=duration)
        return Dhis2TrackerOutput(rows=rows, pager=pager, duration_ms=duration)

    async def _every_page(
        self, tracker: TrackerAccessor, config: Dhis2TrackerConfig
    ) -> tuple[list[JsonValue], Dhis2Pager]:
        """Read page after page until the instance has no more, failing at the first cap reached."""
        size = config.page_size or ALL_PAGES_PAGE_SIZE
        rows: list[JsonValue] = []
        gathered = 0
        page = 1
        while True:
            body = await self._read(tracker, config, page, size)
            taken = _rows(body, config.kind)
            pager = pager_of(body, len(taken))
            rows.extend(taken)
            gathered += sum(len(json.dumps(row)) for row in taken)
            if len(rows) > config.max_rows:
                self._capped(config, "max_rows", config.max_rows)
            if gathered > config.max_total:
                self._capped(config, "max_total", config.max_total)
            if not taken or not pager.more:
                return rows, pager.model_copy(update={"page": page, "page_size": size, "more": False})
            if page >= config.max_pages:
                self._capped(config, "max_pages", config.max_pages)
            page += 1

    def _capped(self, config: Dhis2TrackerConfig, cap: str, limit: int) -> NoReturn:
        """Fail the read for reaching a cap, rather than answer the part of the collection read so far."""
        raise BlockFailure(TRACKER_CAP_REACHED, error_class=ErrorClass.REJECTED, kind=config.kind, cap=cap, limit=limit)

    async def _read(
        self, tracker: TrackerAccessor, config: Dhis2TrackerConfig, page: int | None, page_size: int | None
    ) -> dict[str, Any]:
        """Dispatch on the collection ``kind`` to the tracker accessor that reads it."""
        terms = query_terms(fields=config.fields, filter=config.filter)
        counted = {"totalPages": "true"} if config.total else {}
        if config.kind == "trackedEntities":
            return await tracker.tracked_entities(
                program=config.program,
                org_unit=config.org_unit,
                ou_mode=config.ou_mode,
                status=config.status,
                fields=terms.fields,
                filter=terms.filter,
                page=page,
                page_size=page_size,
                updated_after=config.updated_after,
                extra_params=counted or None,
            )
        if config.kind == "enrollments":
            # The enrollments reader has no ``filter`` argument; the collection's filter rides
            # through as an extra query param so the block's contract still applies.
            return await tracker.enrollments(
                program=config.program,
                org_unit=config.org_unit,
                ou_mode=config.ou_mode,
                status=config.status,
                fields=terms.fields,
                page=page,
                page_size=page_size,
                updated_after=config.updated_after,
                extra_params={**counted, **({} if terms.filter is None else {"filter": terms.filter})} or None,
            )
        return await tracker.events(
            program=config.program,
            org_unit=config.org_unit,
            ou_mode=config.ou_mode,
            status=config.status,
            fields=terms.fields,
            filter=terms.filter,
            page=page,
            page_size=page_size,
            updated_after=config.updated_after,
            extra_params=counted or None,
        )
