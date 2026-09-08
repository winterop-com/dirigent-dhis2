"""Tests for dhis2.metadata: the generic resource read and how it narrows the collection."""

import importlib
from typing import Any, cast

import pytest
import respx
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, json
from dirigent_dhis2.metadata import Dhis2MetadataConfig, Dhis2MetadataOperator, Dhis2MetadataOutput, accessor_name
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

DATA_ELEMENTS = f"{BASE_URL}/api/dataElements"
READ = {
    "pager": {"page": 1, "pageCount": 1, "total": 1},
    "dataElements": [{"id": "fbfJHSPpUQD", "name": "BCG doses", "valueType": "NUMBER"}],
}


async def test_a_metadata_read_carries_the_collection(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(DATA_ELEMENTS).mock(return_value=json(200, READ))
    output = await call_block(
        Dhis2MetadataOperator(),
        {"connection": CONNECTION, "resource": "dataElements", "fields": "id,name,valueType"},
        ctx,
    )
    assert isinstance(output, Dhis2MetadataOutput)
    assert output.json_body == READ
    assert output.duration_ms >= 0
    params = route.calls.last.request.url.params
    assert params["fields"] == "id,name,valueType"
    assert params["paging"] == "false"


async def test_a_single_filter_string_is_sent_as_one_filter(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(DATA_ELEMENTS).mock(return_value=json(200, READ))
    await call_block(
        Dhis2MetadataOperator(),
        {"connection": CONNECTION, "resource": "dataElements", "filter": "domainType:eq:AGGREGATE"},
        ctx,
    )
    assert route.calls.last.request.url.params.get_list("filter") == ["domainType:eq:AGGREGATE"]


async def test_paging_sends_the_page_and_size(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(f"{BASE_URL}/api/organisationUnits").mock(return_value=json(200, {"organisationUnits": []}))
    await call_block(
        Dhis2MetadataOperator(),
        {"connection": CONNECTION, "resource": "organisationUnits", "paging": True, "page": 2, "page_size": 50},
        ctx,
    )
    params = route.calls.last.request.url.params
    assert params["paging"] == "true"
    assert params["page"] == "2"
    assert params["pageSize"] == "50"


async def test_a_resource_the_version_does_not_know_is_rejected(ctx: FakeContext, dhis2: respx.Router) -> None:
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2MetadataOperator(),
            {"connection": CONNECTION, "resource": "notAResource"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_refused_read_is_classified_by_its_status(ctx: FakeContext, dhis2: respx.Router) -> None:
    dhis2.get(DATA_ELEMENTS).mock(return_value=json(409, {}))
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
