"""``dhis2.analytics_query``: read one analytics query, aggregate or event/enrollment."""

import time
from typing import Any, ClassVar, Final, Literal, cast

from dhis2w_client import AnalyticsAccessor
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.messages import NO_PROGRAM
from dirigent_dhis2.reads import Dhis2Pager, pager_of, require_known
from dirigent_dhis2.web import Dhis2Operator, query_terms, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: The aggregate analytics endpoint the client's analytics accessor reads.
AGGREGATE_ENDPOINT: Final = "/api/analytics.json"

#: The query modes this block runs, keyed by the ``mode`` a document names.
AnalyticsMode = Literal["aggregate", "event", "enrollment"]


class Dhis2AnalyticsQueryConfig(BlockModel):
    """What one analytics query asks of the instance."""

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    mode: AnalyticsMode
    """Which analytics query to run: ``aggregate`` over ``/api/analytics``, or an ``event`` or
    ``enrollment`` query over ``/api/analytics/{events,enrollments}/query``."""

    dimension: list[str] = []
    """The DHIS2 ``dimension=`` axes, such as ``dx:fbfJHSPpUQD`` or ``pe:LAST_12_MONTHS``."""

    filter: str | list[str] = []
    """The DHIS2 ``filter=`` axes, fixing a dimension the result is not broken down by: one
    string such as ``ou:ImspTQPwCqd``, or a list such as ``[ou:ImspTQPwCqd, pe:2026Q1]`` that
    is sent as one ``filter=`` each."""

    program: str | None = Field(default=None, pattern=UID_PATTERN)
    """The uid of the program an ``event`` or ``enrollment`` query reads; unused for aggregate."""

    start_date: str | None = None
    """The ISO start of the query window, for the query kinds that take one."""

    end_date: str | None = None
    """The ISO end of the query window, for the query kinds that take one."""

    output_id_scheme: str | None = None
    """The DHIS2 ``outputIdScheme``, such as ``UID`` or ``NAME``, applied to the answer."""

    page: int | None = None
    """The 1-based page to read, for the event and enrollment queries that page."""

    page_size: int | None = None
    """How many rows a page holds, for the event and enrollment queries that page."""

    require_known: bool = True
    """Whether an ``event`` or ``enrollment`` query fails when its program is unknown to the
    instance, rather than answering an empty grid. One metadata lookup asks for it first."""

    @model_validator(mode="after")
    def _program_scopes_the_query_kinds_that_need_it(self) -> "Dhis2AnalyticsQueryConfig":
        """An event or enrollment query reads under one program, so it must be named."""
        if self.mode in ("event", "enrollment") and not self.program:
            raise ValueError(NO_PROGRAM.render(mode=self.mode))
        return self


class Dhis2AnalyticsQueryOutput(BlockModel):
    """The grid the analytics endpoint answered, its rows as objects and as DHIS2 sent them."""

    rows: list[dict[str, JsonValue]]
    """The grid's rows, each an object keyed by its header's name, such as ``dx``, ``pe``, ``ou``
    and ``value``."""

    pager: Dhis2Pager | None = None
    """The page an event or enrollment query read and whether more follow; null for a grid
    that is not paged."""

    body: JsonValue | None = None
    """The grid as DHIS2 answered it: ``headers``, ``metaData`` with the names of every item,
    ``rows`` as lists, ``height`` and ``width``."""

    duration_ms: int
    """How long the query took."""


def _params(config: Dhis2AnalyticsQueryConfig) -> dict[str, Any]:
    """Build the analytics query from the axes and window the step set, in DHIS2's own names."""
    params: dict[str, Any] = {}
    if config.dimension:
        params["dimension"] = config.dimension
    filters = query_terms(filter=config.filter).filter
    if filters is not None:
        params["filter"] = filters
    if config.start_date is not None:
        params["startDate"] = config.start_date
    if config.end_date is not None:
        params["endDate"] = config.end_date
    if config.output_id_scheme is not None:
        params["outputIdScheme"] = config.output_id_scheme
    if config.page is not None:
        params["page"] = config.page
    if config.page_size is not None:
        params["pageSize"] = config.page_size
    return params


def rows_as_objects(grid: dict[str, Any]) -> list[dict[str, JsonValue]]:
    """Map each grid row onto its headers' names, so a value is read by name rather than by position."""
    headers: list[Any] = grid.get("headers") or []
    names: list[str] = []
    for index, header in enumerate(headers):
        named = cast("dict[str, Any]", header).get("name") if isinstance(header, dict) else None
        names.append(str(named) if named is not None else str(index))
    rows: list[Any] = grid.get("rows") or []
    return [dict(zip(names, cast("list[JsonValue]", row), strict=False)) for row in rows if isinstance(row, list)]


class Dhis2AnalyticsQueryOperator(Dhis2Operator[Dhis2AnalyticsQueryConfig, Dhis2AnalyticsQueryOutput]):
    """Runs one analytics query -- aggregate, event, or enrollment -- and hands the grid on."""

    spec = OperatorSpec(
        id="dhis2.analytics_query",
        summary="Run a DHIS2 analytics query.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2AnalyticsQueryConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2AnalyticsQueryOutput

    async def execute(self, config: Dhis2AnalyticsQueryConfig, ctx: StepContext) -> Dhis2AnalyticsQueryOutput:
        """Read the query once through the accessor for aggregate, the request path otherwise."""
        started = time.monotonic()
        async with client_for(ctx, config.connection) as client:
            if config.mode == "aggregate":
                body = await self._aggregate(client.analytics, _params(config))
            else:
                if config.require_known:
                    await require_known(
                        client, {"programs": config.program}, f"GET /api/analytics/{config.mode}s/query"
                    )
                body = await self._events(client.analytics, config)
        duration = round((time.monotonic() - started) * 1000)
        rows = rows_as_objects(body)
        meta = body.get("metaData")
        paged = cast("dict[str, Any]", meta).get("pager") if isinstance(meta, dict) else None
        pager = pager_of(cast("dict[str, Any]", paged), len(rows)) if isinstance(paged, dict) else None
        ctx.log.info("analytics query read", mode=config.mode, rows=len(rows), duration_ms=duration)
        return Dhis2AnalyticsQueryOutput(rows=rows, pager=pager, body=body, duration_ms=duration)

    async def _aggregate(self, analytics: AnalyticsAccessor, params: dict[str, Any]) -> dict[str, Any]:
        """Read the aggregate grid through the client's analytics accessor."""
        try:
            grid = await analytics.aggregate(endpoint=AGGREGATE_ENDPOINT, extra_params=params)
        except (Dhis2ApiError, AuthenticationError) as error:
            raise refuse(error, f"GET {AGGREGATE_ENDPOINT}") from error
        return grid.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def _events(self, analytics: AnalyticsAccessor, config: Dhis2AnalyticsQueryConfig) -> dict[str, Any]:
        """Read an event or enrollment query grid through the analytics accessor."""
        collection = "events" if config.mode == "event" else "enrollments"
        if config.program is None:
            raise BlockFailure(NO_PROGRAM, error_class=ErrorClass.REJECTED, mode=config.mode)
        extra = {"outputIdScheme": config.output_id_scheme} if config.output_id_scheme is not None else None
        query = analytics.event_query if config.mode == "event" else analytics.enrollment_query
        try:
            grid = await query(
                config.program,
                dimension=config.dimension or None,
                filter=query_terms(filter=config.filter).filter,
                start_date=config.start_date,
                end_date=config.end_date,
                page=config.page,
                page_size=config.page_size,
                extra_params=extra,
            )
        except (Dhis2ApiError, AuthenticationError) as error:
            raise refuse(error, f"GET /api/analytics/{collection}/query/{config.program}") from error
        return grid.model_dump(mode="json", by_alias=True, exclude_none=True)
