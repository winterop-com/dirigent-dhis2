"""Tests for dhis2.metadata: the generic resource read and how it narrows the collection."""

import importlib
from typing import Any, cast

import httpx2
import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, Route, json
from dirigent_dhis2.metadata import Dhis2MetadataConfig, Dhis2MetadataOperator, Dhis2MetadataOutput, accessor_name
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

DATA_ELEMENTS = f"{BASE_URL}/api/dataElements"
ORG_UNITS = f"{BASE_URL}/api/organisationUnits"
READ = {
    "pager": {"page": 1, "pageCount": 1, "total": 1},
    "dataElements": [{"id": "fbfJHSPpUQD", "name": "BCG doses", "valueType": "NUMBER"}],
}


async def test_a_metadata_read_carries_the_collection(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(DATA_ELEMENTS).answers(json(200, READ))
    output = await call_block(
        Dhis2MetadataOperator(),
        {"connection": CONNECTION, "resource": "dataElements", "fields": "id,name,valueType"},
        ctx,
    )
    assert isinstance(output, Dhis2MetadataOutput)
    assert output.body == READ
    assert output.duration_ms >= 0
    params = route.last.url.params
    assert params["fields"] == "id,name,valueType"
    assert params["paging"] == "false"


async def _sent(ctx: FakeContext, route: Route, terms: dict[str, str | list[str]]) -> httpx2.URL:
    """Read the org units narrowed by these terms, and give back the URL the instance was asked."""
    await call_block(Dhis2MetadataOperator(), {"connection": CONNECTION, "resource": "organisationUnits", **terms}, ctx)
    return route.last.url


@pytest.mark.parametrize(
    ("term", "written", "listed", "wire"),
    [
        pytest.param(
            "fields",
            "id,name,parent[id,code]",
            ["id", "name", "parent[id,code]"],
            ["id,name,parent[id,code]"],
            id="nested-fields",
        ),
        pytest.param("filter", "level:eq:2", ["level:eq:2"], ["level:eq:2"], id="filter"),
        pytest.param(
            "order", "level:asc,name:asc", ["level:asc", "name:asc"], ["level:asc,name:asc"], id="two-term-order"
        ),
    ],
)
async def test_a_query_term_sends_the_same_request_as_a_string_or_a_list(
    ctx: FakeContext, dhis2: Dhis2Server, term: str, written: str, listed: list[str], wire: list[str]
) -> None:
    route = dhis2.get(ORG_UNITS).answers(json(200, {"organisationUnits": []}))
    as_string = await _sent(ctx, route, {term: written})
    as_list = await _sent(ctx, route, {term: listed})
    assert as_list.query == as_string.query
    assert as_list.params.get_list(term) == wire


async def test_a_filter_pair_is_sent_as_the_two_filters_it_holds(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """A filter list repeats ``filter=`` rather than joining it, and DHIS2 ANDs what is repeated."""
    route = dhis2.get(ORG_UNITS).answers(json(200, {"organisationUnits": []}))
    level = await _sent(ctx, route, {"filter": "level:eq:2"})
    name = await _sent(ctx, route, {"filter": "name:like:Bo"})
    pair = await _sent(ctx, route, {"filter": ["level:eq:2", "name:like:Bo"]})
    assert pair.params.get_list("filter") == [*level.params.get_list("filter"), *name.params.get_list("filter")]
    assert pair.params.get_list("filter") == ["level:eq:2", "name:like:Bo"]
    assert "rootJunction" not in pair.params


@pytest.mark.parametrize("term", ["fields", "filter", "order"])
@pytest.mark.parametrize("listed", [[1, 2], [["id"]], [None]], ids=["numbers", "nested-list", "null"])
def test_a_query_term_list_of_anything_but_strings_is_refused_at_config(term: str, listed: list[object]) -> None:
    with pytest.raises(ValidationError):
        Dhis2MetadataConfig.model_validate({"connection": "c", "resource": "dataElements", term: listed})


async def test_paging_sends_the_page_and_size(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(ORG_UNITS).answers(json(200, {"organisationUnits": []}))
    await call_block(
        Dhis2MetadataOperator(),
        {"connection": CONNECTION, "resource": "organisationUnits", "paging": True, "page": 2, "page_size": 50},
        ctx,
    )
    params = route.last.url.params
    assert params["paging"] == "true"
    assert params["page"] == "2"
    assert params["pageSize"] == "50"


async def test_a_resource_the_version_does_not_know_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2MetadataOperator(),
            {"connection": CONNECTION, "resource": "notAResource"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.metadata.unknown_resource"
    assert refused.value.params["resource"] == "notAResource"


async def test_a_refused_read_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(DATA_ELEMENTS).answers(json(409, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2MetadataOperator(),
            {"connection": CONNECTION, "resource": "dataElements"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED


def _resources(version: str) -> object:
    """The generated accessor bundle for one version, built without a client."""
    module: Any = importlib.import_module(f"dhis2w_client.generated.{version}.resources")
    return cast("object", module.Resources(object()))


def _generated_accessors(version: str) -> dict[str, object]:
    """Every accessor the generated tree publishes for a version, keyed by its DHIS2 collection name."""
    published: dict[str, object] = {}
    for accessor in cast("dict[str, object]", vars(_resources(version))).values():
        key = getattr(accessor, "_plural_key", None)
        if isinstance(key, str):
            published[key] = accessor
    return published


@pytest.mark.parametrize("version", ["v41", "v42", "v43"])
def test_every_generated_collection_is_reachable_by_its_dhis2_name(version: str) -> None:
    """The lookup goes by public accessor name, so it must hold for every collection a version publishes."""
    published = _generated_accessors(version)
    assert len(published) > 50
    resources = _resources(version)
    for collection, accessor in published.items():
        assert type(getattr(resources, accessor_name(collection))) is type(accessor), collection


def test_a_resource_name_that_is_not_a_collection_name_is_refused_at_config() -> None:
    with pytest.raises(ValidationError):
        Dhis2MetadataConfig(connection="c", resource="data-elements")
