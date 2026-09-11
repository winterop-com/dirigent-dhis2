"""``dhis2.analytics_query``: read one analytics query, aggregate or event/enrollment."""

import time
from typing import Any, ClassVar, Final, Literal

from dhis2w_client import AnalyticsAccessor
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue, model_validator

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ErrorClass, OperatorSpec, StepContext

#: The aggregate analytics endpoint the client's analytics accessor reads.
AGGREGATE_ENDPOINT: Final = "/api/analytics.json"

#: The query modes this block runs, keyed by the ``mode`` a document names.
AnalyticsMode = Literal["aggregate", "event", "enrollment"]


class Dhis2AnalyticsQueryConfig(BlockModel):
    """What one analytics query asks of the instance."""

    connection: str
    """The code of the dhis2 connection naming the instance."""

    mode: AnalyticsMode
    """Which analytics query to run: ``aggregate`` over ``/api/analytics``, or an ``event`` or
    ``enrollment`` query over ``/api/analytics/{events,enrollments}/query``."""

    dimension: list[str] = []
    """The DHIS2 ``dimension=`` axes, such as ``dx:fbfJHSPpUQD`` or ``pe:LAST_12_MONTHS``."""

    filter: list[str] = []
    """The DHIS2 ``filter=`` axes, fixing a dimension the result is not broken down by."""

    program: str | None = None
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

    @model_validator(mode="after")
    def _program_scopes_the_query_kinds_that_need_it(self) -> "Dhis2AnalyticsQueryConfig":
        """An event or enrollment query reads under one program, so it must be named."""
        if self.mode in ("event", "enrollment") and not self.program:
            raise ValueError(f"a {self.mode} analytics query needs a program to read under")
        return self


class Dhis2AnalyticsQueryOutput(BlockModel):
    """The query the analytics endpoint answered, for a downstream step to reference by field."""

    body: JsonValue | None = None
    """The parsed response: the analytics grid, its headers, metaData, and rows."""

    duration_ms: int


def _params(config: Dhis2AnalyticsQueryConfig) -> dict[str, Any]:
    """Build the analytics query from the axes and window the step set, in DHIS2's own names."""
    params: dict[str, Any] = {}
    if config.dimension:
        params["dimension"] = config.dimension
    if config.filter:
        params["filter"] = config.filter
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
                body = await self._events(client.analytics, config)
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info("analytics query read", mode=config.mode, duration_ms=duration)
        return Dhis2AnalyticsQueryOutput(body=body, duration_ms=duration)

    async def _aggregate(self, analytics: AnalyticsAccessor, params: dict[str, Any]) -> JsonValue:
        """Read the aggregate grid through the client's analytics accessor."""
        try:
            grid = await analytics.aggregate(endpoint=AGGREGATE_ENDPOINT, extra_params=params)
        except (Dhis2ApiError, AuthenticationError) as error:
            raise refuse(error, f"GET {AGGREGATE_ENDPOINT}") from error
        return grid.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def _events(self, analytics: AnalyticsAccessor, config: Dhis2AnalyticsQueryConfig) -> JsonValue:
        """Read an event or enrollment query grid through the analytics accessor."""
        collection = "events" if config.mode == "event" else "enrollments"
        if config.program is None:
            raise BlockFailure(f"a {config.mode} analytics query needs a program", error_class=ErrorClass.REJECTED)
        extra = {"outputIdScheme": config.output_id_scheme} if config.output_id_scheme is not None else None
        query = analytics.event_query if config.mode == "event" else analytics.enrollment_query
        try:
            grid = await query(
                config.program,
                dimension=config.dimension or None,
                filter=config.filter or None,
                start_date=config.start_date,
                end_date=config.end_date,
                page=config.page,
                page_size=config.page_size,
                extra_params=extra,
            )
        except (Dhis2ApiError, AuthenticationError) as error:
            raise refuse(error, f"GET /api/analytics/{collection}/query/{config.program}") from error
        return grid.model_dump(mode="json", by_alias=True, exclude_none=True)
