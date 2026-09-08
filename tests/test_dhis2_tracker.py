"""Tests for dhis2.tracker: reading each collection and how the query is scoped."""

import pytest
import respx
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, json
from dirigent_dhis2.tracker import Dhis2TrackerConfig, Dhis2TrackerOperator, Dhis2TrackerOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

EVENTS = f"{BASE_URL}/api/tracker/events"
PAGE = {"instances": [{"event": "evt1", "programStage": "stage1"}], "page": 1, "pageSize": 50}


async def test_a_tracker_read_carries_the_page(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(EVENTS).mock(return_value=json(200, PAGE))
    output = await call_block(
        Dhis2TrackerOperator(),
        {
            "connection": CONNECTION,
            "kind": "events",
            "program": "IpHINAT79UW",
            "org_unit": "DiszpKrYNg8",
            "ou_mode": "DESCENDANTS",
        },
        ctx,
    )
    assert isinstance(output, Dhis2TrackerOutput)
    assert output.json_body == PAGE
    assert output.duration_ms >= 0
    params = route.calls.last.request.url.params
    assert params["program"] == "IpHINAT79UW"
    assert params["orgUnit"] == "DiszpKrYNg8"
    assert params["orgUnitMode"] == "DESCENDANTS"


async def test_the_kind_names_the_collection_path(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(f"{BASE_URL}/api/tracker/trackedEntities").mock(return_value=json(200, {"instances": []}))
    await call_block(
        Dhis2TrackerOperator(),
        {"connection": CONNECTION, "kind": "trackedEntities", "filter": ["w75KJ2mc4zz:like:Anna"]},
        ctx,
    )
    assert route.calls.last.request.url.path == "/api/tracker/trackedEntities"
    assert route.calls.last.request.url.params.get_list("filter") == ["w75KJ2mc4zz:like:Anna"]


async def test_a_refused_read_is_classified_by_its_status(ctx: FakeContext, dhis2: respx.Router) -> None:
    dhis2.get(EVENTS).mock(return_value=json(500, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2TrackerOperator(),
            {"connection": CONNECTION, "kind": "events", "program": "IpHINAT79UW"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.TRANSIENT


def test_an_org_unit_mode_dhis2_does_not_know_is_refused_at_config() -> None:
    with pytest.raises(ValidationError):
        Dhis2TrackerConfig(connection="c", kind="events", ou_mode="NEARBY")  # pyright: ignore[reportArgumentType]
