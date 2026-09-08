"""Tests for dhis2.analytics_query: aggregate through the accessor, event through the path."""

import pytest
import respx
from pydantic import JsonValue, ValidationError

from dhis2server import BASE_URL, CONNECTION, json
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


async def test_an_aggregate_query_reads_the_grid(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(ANALYTICS).mock(return_value=json(200, GRID))
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
    assert isinstance(output.json_body, dict)
    assert output.json_body["rows"] == [["fbfJHSPpUQD", "12"]]
    assert output.duration_ms >= 0
    params = route.calls.last.request.url.params
    assert params.get_list("dimension") == ["dx:fbfJHSPpUQD", "pe:LAST_12_MONTHS"]
    assert params.get_list("filter") == ["ou:ImspTQPwCqd"]


async def test_an_event_query_reads_under_the_program(ctx: FakeContext, dhis2: respx.Router) -> None:
    body: dict[str, JsonValue] = {"headers": [], "rows": [], "width": 0, "height": 0}
    route = dhis2.get(f"{BASE_URL}/api/analytics/events/query/IpHINAT79UW.json").mock(return_value=json(200, body))
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
    assert output.json_body == body
    assert route.calls.last.request.url.path == "/api/analytics/events/query/IpHINAT79UW.json"


async def test_an_aggregate_refusal_is_classified_by_its_status(ctx: FakeContext, dhis2: respx.Router) -> None:
    dhis2.get(ANALYTICS).mock(return_value=json(409, {"message": "no"}))
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
