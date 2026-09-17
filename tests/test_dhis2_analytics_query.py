"""Tests for dhis2.analytics_query: aggregate, event and enrollment, all through the analytics accessor."""

import httpx2
import pytest
from pydantic import JsonValue, ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, Route, json
from dirigent_dhis2.analytics_query import (
    Dhis2AnalyticsQueryConfig,
    Dhis2AnalyticsQueryOperator,
    Dhis2AnalyticsQueryOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

ANALYTICS = f"{BASE_URL}/api/analytics.json"
GRID: dict[str, JsonValue] = {
    "headers": [{"name": "dx", "column": "Data"}, {"name": "value", "column": "Value"}],
    "metaData": {"items": {}, "dimensions": {}},
    "rows": [["fbfJHSPpUQD", "12"]],
    "width": 2,
    "height": 1,
}

#: Each query mode, as the URL it reads and the scoping it needs: aggregate goes through the
#: accessor's own query, event and enrollment through the program-scoped one.
MODES = [
    pytest.param(ANALYTICS, {"mode": "aggregate", "dimension": ["dx:fbfJHSPpUQD"]}, id="aggregate"),
    pytest.param(
        f"{BASE_URL}/api/analytics/events/query/IpHINAT79UW.json",
        {"mode": "event", "program": "IpHINAT79UW", "dimension": ["pe:LAST_MONTH"]},
        id="event",
    ),
    pytest.param(
        f"{BASE_URL}/api/analytics/enrollments/query/IpHINAT79UW.json",
        {"mode": "enrollment", "program": "IpHINAT79UW", "dimension": ["pe:LAST_MONTH"]},
        id="enrollment",
    ),
]


async def test_an_aggregate_query_reads_the_grid(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(ANALYTICS).answers(json(200, GRID))
    output = await call_block(
        Dhis2AnalyticsQueryOperator(),
        {
            "connection": CONNECTION,
            "mode": "aggregate",
            "dimension": ["dx:fbfJHSPpUQD", "pe:LAST_12_MONTHS"],
            "filter": ["ou:ImspTQPwCqd"],
        },
        ctx,
    )
    assert isinstance(output, Dhis2AnalyticsQueryOutput)
    assert isinstance(output.body, dict)
    assert output.body["rows"] == [["fbfJHSPpUQD", "12"]]
    assert output.duration_ms >= 0
    params = route.last.url.params
    assert params.get_list("dimension") == ["dx:fbfJHSPpUQD", "pe:LAST_12_MONTHS"]
    assert params.get_list("filter") == ["ou:ImspTQPwCqd"]


async def test_an_event_query_reads_under_the_program(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    body: dict[str, JsonValue] = {"headers": [], "rows": [], "width": 0, "height": 0}
    route = dhis2.get(f"{BASE_URL}/api/analytics/events/query/IpHINAT79UW.json").answers(json(200, body))
    output = await call_block(
        Dhis2AnalyticsQueryOperator(),
        {
            "connection": CONNECTION,
            "mode": "event",
            "program": "IpHINAT79UW",
            "dimension": ["pe:LAST_MONTH"],
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        ctx,
    )
    assert isinstance(output, Dhis2AnalyticsQueryOutput)
    assert output.body == body
    assert route.last.url.path == "/api/analytics/events/query/IpHINAT79UW.json"


async def _sent(ctx: FakeContext, route: Route, query: dict[str, JsonValue], filters: JsonValue) -> httpx2.URL:
    """Run the query with these filter axes, and give back the URL the instance was asked."""
    await call_block(Dhis2AnalyticsQueryOperator(), {"connection": CONNECTION, **query, "filter": filters}, ctx)
    return route.last.url


@pytest.mark.parametrize(("url", "query"), MODES)
async def test_a_filter_sends_the_same_request_as_a_string_or_a_list(
    ctx: FakeContext, dhis2: Dhis2Server, url: str, query: dict[str, JsonValue]
) -> None:
    route = dhis2.get(url).answers(json(200, GRID))
    as_string = await _sent(ctx, route, query, "ou:ImspTQPwCqd")
    as_list = await _sent(ctx, route, query, ["ou:ImspTQPwCqd"])
    assert as_list.query == as_string.query
    assert as_list.params.get_list("filter") == ["ou:ImspTQPwCqd"]


@pytest.mark.parametrize(("url", "query"), MODES)
async def test_a_filter_pair_is_sent_as_the_two_filters_it_holds(
    ctx: FakeContext, dhis2: Dhis2Server, url: str, query: dict[str, JsonValue]
) -> None:
    """A filter list repeats ``filter=`` rather than joining it: each axis is fixed on its own."""
    route = dhis2.get(url).answers(json(200, GRID))
    org_unit = await _sent(ctx, route, query, "ou:ImspTQPwCqd")
    period = await _sent(ctx, route, query, "pe:2026Q1")
    pair = await _sent(ctx, route, query, ["ou:ImspTQPwCqd", "pe:2026Q1"])
    assert pair.params.get_list("filter") == [*org_unit.params.get_list("filter"), *period.params.get_list("filter")]
    assert pair.params.get_list("filter") == ["ou:ImspTQPwCqd", "pe:2026Q1"]


@pytest.mark.parametrize(("url", "query"), MODES)
async def test_no_filter_sends_no_filter_axis(
    ctx: FakeContext, dhis2: Dhis2Server, url: str, query: dict[str, JsonValue]
) -> None:
    route = dhis2.get(url).answers(json(200, GRID))
    await call_block(Dhis2AnalyticsQueryOperator(), {"connection": CONNECTION, **query}, ctx)
    assert "filter" not in route.last.url.params


@pytest.mark.parametrize("listed", [[1, 2], [["ou:ImspTQPwCqd"]], [None]], ids=["numbers", "nested-list", "null"])
def test_a_filter_list_of_anything_but_strings_is_refused_at_config(listed: list[object]) -> None:
    with pytest.raises(ValidationError):
        Dhis2AnalyticsQueryConfig.model_validate({"connection": "c", "mode": "aggregate", "filter": listed})


async def test_an_aggregate_refusal_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(ANALYTICS).answers(json(409, {"message": "no"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2AnalyticsQueryOperator(),
            {"connection": CONNECTION, "mode": "aggregate", "dimension": ["dx:x"]},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED


def test_an_event_query_without_a_program_is_refused_at_config() -> None:
    with pytest.raises(ValidationError):
        Dhis2AnalyticsQueryConfig(connection=CONNECTION, mode="event", dimension=["pe:LAST_MONTH"])
