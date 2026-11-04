"""Tests for dhis2.metadata_export: several collections in one /api/metadata request."""

import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.metadata_export import (
    Dhis2MetadataExportConfig,
    Dhis2MetadataExportOperator,
    Dhis2MetadataExportOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

METADATA = f"{BASE_URL}/api/metadata"
ANSWER = {
    "system": {"id": "eed3d451", "version": "2.42.1"},
    "dataSets": [{"id": "BfMAe6Itzgt", "name": "Child Health"}, {"id": "QX4ZTUbOt3a", "name": "Reproductive"}],
    "programs": [{"id": "IpHINAT79UW", "name": "Child Programme"}],
}


async def test_an_export_answers_each_collection_under_its_name(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(METADATA).answers(json(200, ANSWER))
    output = await call_block(
        Dhis2MetadataExportOperator(),
        {"connection": CONNECTION, "resources": ["dataSets", "programs", "indicators"], "fields": "id,name"},
        ctx,
    )
    assert isinstance(output, Dhis2MetadataExportOutput)
    assert output.collections == {"dataSets": ANSWER["dataSets"], "programs": ANSWER["programs"], "indicators": []}
    assert output.totals == {"dataSets": 2, "programs": 1, "indicators": 0}
    assert len(route.requests) == 1
    params = route.last.url.params
    assert [params[name] for name in ("dataSets", "programs", "indicators")] == ["true", "true", "true"]
    assert [params[f"{name}:fields"] for name in ("dataSets", "programs", "indicators")] == ["id,name"] * 3
    assert "fields" not in params


async def test_a_collection_of_its_own_overrides_the_shared_terms(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(METADATA).answers(json(200, ANSWER))
    await call_block(
        Dhis2MetadataExportOperator(),
        {
            "connection": CONNECTION,
            "fields": ["id", "name"],
            "filter": "name:like:Child",
            "order": "name:asc",
            "resources": {
                "dataSets": {"fields": ["id", "periodType"], "filter": ["periodType:eq:Monthly", "name:like:C"]},
                "organisationUnits": {"filter": "level:le:2", "order": ["level:asc", "name:asc"]},
                "programs": {},
            },
        },
        ctx,
    )
    params = route.last.url.params
    assert params["dataSets:fields"] == "id,periodType"
    assert params.get_list("dataSets:filter") == ["periodType:eq:Monthly", "name:like:C"]
    assert params["dataSets:order"] == "name:asc"
    assert params["organisationUnits:fields"] == "id,name"
    assert params.get_list("organisationUnits:filter") == ["level:le:2"]
    assert params["organisationUnits:order"] == "level:asc,name:asc"
    assert params["programs:fields"] == "id,name"
    assert params.get_list("programs:filter") == ["name:like:Child"]
    assert not {"fields", "filter", "order"} & set(params.keys())


async def test_an_export_with_no_terms_sends_only_the_collections(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(METADATA).answers(json(200, ANSWER))
    await call_block(Dhis2MetadataExportOperator(), {"connection": CONNECTION, "resources": ["dataSets"]}, ctx)
    assert dict(route.last.url.params) == {"dataSets": "true"}


async def test_a_resource_the_version_does_not_know_is_rejected_before_the_export(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    route = dhis2.get(METADATA).answers(json(200, ANSWER))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2MetadataExportOperator(),
            {"connection": CONNECTION, "resources": ["dataSets", "notAResource"]},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.metadata.unknown_resource"
    assert refused.value.params["resource"] == "notAResource"
    assert route.requests == []


async def test_a_refused_export_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(METADATA).answers(json(409, {"message": "no"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MetadataExportOperator(), {"connection": CONNECTION, "resources": ["dataSets"]}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.params["where"] == "GET /api/metadata"


@pytest.mark.parametrize("resources", [[], {}, ["data-sets"], {"data-sets": {}}], ids=["list", "map", "name", "key"])
def test_no_collection_or_a_name_that_is_not_one_is_refused_at_config(resources: object) -> None:
    with pytest.raises(ValidationError):
        Dhis2MetadataExportConfig.model_validate({"connection": "c", "resources": resources})


def test_a_collection_term_outside_fields_filter_and_order_is_refused_at_config() -> None:
    with pytest.raises(ValidationError):
        Dhis2MetadataExportConfig.model_validate({"connection": "c", "resources": {"dataSets": {"paging": True}}})
