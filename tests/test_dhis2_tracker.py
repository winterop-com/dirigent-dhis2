"""Tests for dhis2.tracker: reading each collection and how the query is scoped."""

import httpx2
import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, Route, json
from dirigent_dhis2.tracker import Dhis2TrackerConfig, Dhis2TrackerOperator, Dhis2TrackerOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

EVENTS = f"{BASE_URL}/api/tracker/events"
PAGE = {"instances": [{"event": "evt1", "programStage": "stage1"}], "page": 1, "pageSize": 50}

#: The three collections, each read through its own accessor call.
KINDS = ["trackedEntities", "enrollments", "events"]


async def test_a_tracker_read_carries_the_page(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(EVENTS).answers(json(200, PAGE))
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
    assert output.body == PAGE
    assert output.duration_ms >= 0
    params = route.last.url.params
    assert params["program"] == "IpHINAT79UW"
    assert params["orgUnit"] == "DiszpKrYNg8"
    assert params["orgUnitMode"] == "DESCENDANTS"


async def test_the_kind_names_the_collection_path(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(f"{BASE_URL}/api/tracker/trackedEntities").answers(json(200, {"instances": []}))
    await call_block(
        Dhis2TrackerOperator(),
        {"connection": CONNECTION, "kind": "trackedEntities", "filter": ["w75KJ2mc4zz:like:Anna"]},
        ctx,
    )
    assert route.last.url.path == "/api/tracker/trackedEntities"
    assert route.last.url.params.get_list("filter") == ["w75KJ2mc4zz:like:Anna"]


async def test_an_enrollments_filter_rides_through_as_a_query_parameter(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """The enrollments reader has no filter argument, so the block's contract is kept on the wire itself."""
    route = dhis2.get(f"{BASE_URL}/api/tracker/enrollments").answers(json(200, {"instances": []}))
    await call_block(
        Dhis2TrackerOperator(),
        {
            "connection": CONNECTION,
            "kind": "enrollments",
            "program": "IpHINAT79UW",
            "status": "ACTIVE",
            "updated_after": "2026-01-01",
            "filter": "w75KJ2mc4zz:like:Anna",
        },
        ctx,
    )
    params = route.last.url.params
    assert route.last.url.path == "/api/tracker/enrollments"
    assert params.get_list("filter") == ["w75KJ2mc4zz:like:Anna"]
    assert params["programStatus"] == "ACTIVE"
    assert params["updatedAfter"] == "2026-01-01"


async def _sent(ctx: FakeContext, route: Route, kind: str, terms: dict[str, str | list[str]]) -> httpx2.URL:
    """Read one page of the collection narrowed by these terms, and give back the URL the instance was asked."""
    await call_block(Dhis2TrackerOperator(), {"connection": CONNECTION, "kind": kind, **terms}, ctx)
    return route.last.url


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("term", "written", "listed", "wire"),
    [
        pytest.param(
            "fields",
            "orgUnit,updatedAt,relationships[relationship,bidirectional]",
            ["orgUnit", "updatedAt", "relationships[relationship,bidirectional]"],
            ["orgUnit,updatedAt,relationships[relationship,bidirectional]"],
            id="nested-fields",
        ),
        pytest.param(
            "filter", "w75KJ2mc4zz:like:Anna", ["w75KJ2mc4zz:like:Anna"], ["w75KJ2mc4zz:like:Anna"], id="filter"
        ),
    ],
)
async def test_a_query_term_sends_the_same_request_as_a_string_or_a_list(
    ctx: FakeContext, dhis2: Dhis2Server, kind: str, term: str, written: str, listed: list[str], wire: list[str]
) -> None:
    route = dhis2.get(f"{BASE_URL}/api/tracker/{kind}").answers(json(200, {"instances": []}))
    as_string = await _sent(ctx, route, kind, {term: written})
    as_list = await _sent(ctx, route, kind, {term: listed})
    assert as_list.query == as_string.query
    assert as_list.params.get_list(term) == wire


@pytest.mark.parametrize("kind", KINDS)
async def test_a_filter_pair_is_sent_as_the_two_filters_it_holds(
    ctx: FakeContext, dhis2: Dhis2Server, kind: str
) -> None:
    """A filter list repeats ``filter=`` rather than joining it, and DHIS2 ANDs what is repeated."""
    route = dhis2.get(f"{BASE_URL}/api/tracker/{kind}").answers(json(200, {"instances": []}))
    first = await _sent(ctx, route, kind, {"filter": "w75KJ2mc4zz:like:Anna"})
    last = await _sent(ctx, route, kind, {"filter": "zDhUuAYrxNC:like:Kelly"})
    pair = await _sent(ctx, route, kind, {"filter": ["w75KJ2mc4zz:like:Anna", "zDhUuAYrxNC:like:Kelly"]})
    assert pair.params.get_list("filter") == [*first.params.get_list("filter"), *last.params.get_list("filter")]
    assert pair.params.get_list("filter") == ["w75KJ2mc4zz:like:Anna", "zDhUuAYrxNC:like:Kelly"]


@pytest.mark.parametrize("term", ["fields", "filter"])
@pytest.mark.parametrize("listed", [[1, 2], [["event"]], [None]], ids=["numbers", "nested-list", "null"])
def test_a_query_term_list_of_anything_but_strings_is_refused_at_config(term: str, listed: list[object]) -> None:
    with pytest.raises(ValidationError):
        Dhis2TrackerConfig.model_validate({"connection": "c", "kind": "events", term: listed})


async def test_a_refused_read_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(EVENTS).answers(json(500, {}))
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
