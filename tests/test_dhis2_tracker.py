"""Tests for dhis2.tracker: reading each collection and how the query is scoped."""

import httpx2
import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, Route, json, knowing
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
    assert output.rows == PAGE["instances"]
    assert output.pager.model_dump() == {"page": 1, "page_size": 50, "total": None, "page_count": None, "more": False}
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


def _page(number: int, size: int, events: int, *, next_page: bool) -> dict[str, object]:
    """One page of events the way 2.41 and later answer it, the pager nested."""
    pager: dict[str, object] = {"page": number, "pageSize": size}
    if next_page:
        pager["nextPage"] = f"{EVENTS}?page={number + 1}"
    return {"pager": pager, "instances": [{"event": f"e{number}-{index}"} for index in range(events)]}


async def test_a_single_page_says_when_more_pages_follow(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(EVENTS).answers(json(200, _page(1, 2, 2, next_page=True)))
    output = await call_block(Dhis2TrackerOperator(), {"connection": CONNECTION, "kind": "events", "page_size": 2}, ctx)
    assert isinstance(output, Dhis2TrackerOutput)
    assert len(output.rows) == 2
    assert output.pager.more is True


async def test_a_full_page_the_instance_said_nothing_more_about_counts_as_more(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """A version that sends neither nextPage nor a total leaves a full page as the only sign."""
    rows = [{"event": f"e{index}"} for index in range(50)]
    dhis2.get(EVENTS).answers(json(200, {"page": 1, "pageSize": 50, "instances": rows}))
    output = await call_block(Dhis2TrackerOperator(), {"connection": CONNECTION, "kind": "events"}, ctx)
    assert isinstance(output, Dhis2TrackerOutput)
    assert output.pager.more is True


async def test_total_asks_the_instance_to_count(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    counted: dict[str, object] = {"pager": {"page": 1, "pageSize": 50, "total": 120, "pageCount": 3}, "instances": []}
    route = dhis2.get(EVENTS).answers(json(200, counted))
    output = await call_block(Dhis2TrackerOperator(), {"connection": CONNECTION, "kind": "events", "total": True}, ctx)
    assert isinstance(output, Dhis2TrackerOutput)
    assert route.last.url.params["totalPages"] == "true"
    assert output.pager.total == 120
    assert output.pager.page_count == 3
    assert output.pager.more is True


@pytest.mark.parametrize("kind", KINDS)
async def test_every_page_is_read_and_answered_as_one_list(ctx: FakeContext, dhis2: Dhis2Server, kind: str) -> None:
    route = dhis2.get(f"{BASE_URL}/api/tracker/{kind}").answers_in_turn(
        json(200, _page(1, 2, 2, next_page=True)),
        json(200, _page(2, 2, 2, next_page=True)),
        json(200, _page(3, 2, 1, next_page=False)),
    )
    output = await call_block(
        Dhis2TrackerOperator(), {"connection": CONNECTION, "kind": kind, "all_pages": True, "page_size": 2}, ctx
    )
    assert isinstance(output, Dhis2TrackerOutput)
    assert [row["event"] for row in output.rows if isinstance(row, dict)] == ["e1-0", "e1-1", "e2-0", "e2-1", "e3-0"]
    assert [request.url.params["page"] for request in route.requests] == ["1", "2", "3"]
    assert {request.url.params["pageSize"] for request in route.requests} == {"2"}
    assert output.pager.model_dump() == {"page": 3, "page_size": 2, "total": None, "page_count": None, "more": False}


async def test_every_page_stops_at_an_empty_page(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """A version that reports no next page leaves a full page ambiguous, and the empty one after it settles it."""
    route = dhis2.get(EVENTS).answers_in_turn(
        json(200, {"page": 1, "pageSize": 2, "instances": [{"event": "a"}, {"event": "b"}]}),
        json(200, {"page": 2, "pageSize": 2, "instances": []}),
    )
    output = await call_block(
        Dhis2TrackerOperator(), {"connection": CONNECTION, "kind": "events", "all_pages": True, "page_size": 2}, ctx
    )
    assert isinstance(output, Dhis2TrackerOutput)
    assert len(output.rows) == 2
    assert len(route.requests) == 2


@pytest.mark.parametrize(
    ("cap", "limit"),
    [
        pytest.param("max_pages", 2, id="pages"),
        pytest.param("max_rows", 3, id="rows"),
        pytest.param("max_total", 40, id="size"),
    ],
)
async def test_reading_every_page_fails_at_a_cap_rather_than_answering_part(
    ctx: FakeContext, dhis2: Dhis2Server, cap: str, limit: int
) -> None:
    dhis2.get(EVENTS).answers_in_turn(
        json(200, _page(1, 2, 2, next_page=True)),
        json(200, _page(2, 2, 2, next_page=True)),
        json(200, _page(3, 2, 2, next_page=True)),
    )
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2TrackerOperator(),
            {"connection": CONNECTION, "kind": "events", "all_pages": True, "page_size": 2, cap: limit},
            ctx,
        )
    assert refused.value.code == "dhis2.tracker.cap_reached"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert cap in refused.value.message


def test_a_page_beside_all_pages_is_refused_at_config() -> None:
    with pytest.raises(ValidationError, match="all_pages"):
        Dhis2TrackerConfig.model_validate({"connection": "c", "kind": "events", "all_pages": True, "page": 2})


async def test_an_unknown_program_is_refused_before_the_read(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    lookup = dhis2.get(f"{BASE_URL}/api/metadata").responds(knowing("IpHINAT79UW"))
    route = dhis2.get(EVENTS).answers(json(200, PAGE))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2TrackerOperator(),
            {"connection": CONNECTION, "kind": "events", "program": "IpHINAT79UW", "org_unit": "DiszpKrYNg8"},
            ctx,
        )
    assert refused.value.code == "dhis2.unknown_uids"
    assert "programs IpHINAT79UW" in refused.value.message
    assert "DiszpKrYNg8" not in refused.value.message
    assert route.requests == []
    assert len(lookup.requests) == 1


async def test_require_known_off_reads_without_the_lookup(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    lookup = dhis2.get(f"{BASE_URL}/api/metadata").responds(knowing("IpHINAT79UW"))
    dhis2.get(EVENTS).answers(json(200, PAGE))
    await call_block(
        Dhis2TrackerOperator(),
        {"connection": CONNECTION, "kind": "events", "program": "IpHINAT79UW", "require_known": False},
        ctx,
    )
    assert lookup.requests == []
