"""Tests for dhis2.data_value_set_import: the summary read honestly, the refusals classified."""

import json as jsonlib

import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, summary
from dirigent_dhis2.imports import Dhis2DataValueSetImportConfig, Dhis2DataValueSetImportOperator
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

IMPORT = f"{BASE_URL}/api/dataValueSets"
DOCUMENT = {"dataSet": "pBOMPrpg1QX", "period": "2026Q1", "dataValues": [{"dataElement": "de1", "value": "7"}]}


async def test_a_clean_import_reports_its_counts(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=12, updated=3)))
    output = await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values": DOCUMENT, "dry_run": True},
        ctx,
    )
    assert output.model_dump() == {
        "status": "SUCCESS",
        "imported": 12,
        "updated": 3,
        "ignored": 0,
        "deleted": 0,
        "conflicts": [],
    }
    request = route.last
    assert request.url.params["dryRun"] == "true"
    assert request.url.params["importStrategy"] == "CREATE_AND_UPDATE"
    assert request.url.params["atomicMode"] == "ALL"
    assert jsonlib.loads(request.content) == DOCUMENT


async def test_a_refused_import_answers_409_with_the_summary_and_is_rejected(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """DHIS2 refuses an import with 409 Conflict and the summary in the body, not with a 200."""
    conflicts = [{"object": "de9", "value": "data element not found"}]
    dhis2.post(IMPORT).answers(json(409, summary("ERROR", ignored=1, conflicts=conflicts)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "data element not found" in refused.value.message


async def test_a_summary_of_error_on_200_is_rejected_the_same_way(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    conflicts = [{"object": "de9", "value": "data element not found"}]
    dhis2.post(IMPORT).answers(json(200, summary("ERROR", ignored=1, conflicts=conflicts)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "data element not found" in refused.value.message


async def test_an_atomic_import_that_ignored_values_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(409, summary("WARNING", imported=2, ignored=5)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "took nothing" in refused.value.message


async def test_a_tolerant_import_that_ignored_values_still_settles(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(409, summary("WARNING", imported=2, ignored=5)))
    output = await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values": DOCUMENT, "atomic_mode": "NONE"},
        ctx,
    )
    assert output.model_dump()["status"] == "WARNING"
    assert output.model_dump()["ignored"] == 5


async def test_a_409_without_a_summary_is_an_ordinary_refusal(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(409, {"httpStatus": "Conflict", "message": "Import already in progress"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "Import already in progress" in refused.value.message


async def test_a_refused_transport_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(503, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_an_import_reads_its_document_back_from_storage(local_ctx: FakeContext, dhis2: Dhis2Server) -> None:
    uri = f"{local_ctx.scratch_uri}/dhis2/export.json"
    local_ctx.storage.path_for(uri).parent.mkdir(parents=True, exist_ok=True)
    local_ctx.storage.path_for(uri).write_bytes(jsonlib.dumps(DOCUMENT).encode())
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=1)))
    output = await call_block(
        Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "source_uri": uri}, local_ctx
    )
    assert output.model_dump()["status"] == "SUCCESS"
    assert jsonlib.loads(route.last.content) == DOCUMENT


async def test_a_source_that_is_not_json_is_rejected(local_ctx: FakeContext, dhis2: Dhis2Server) -> None:
    uri = f"{local_ctx.scratch_uri}/dhis2/broken.json"
    local_ctx.storage.path_for(uri).parent.mkdir(parents=True, exist_ok=True)
    local_ctx.storage.path_for(uri).write_bytes(b"not json")
    dhis2.post(IMPORT).answers(json(200, summary("SUCCESS")))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "source_uri": uri}, local_ctx)
    assert refused.value.error_class is ErrorClass.REJECTED


def test_check_config_refuses_both_sources_and_neither() -> None:
    operator = Dhis2DataValueSetImportOperator()
    both = Dhis2DataValueSetImportConfig(connection="c", data_values={}, source_uri="file:///x")
    neither = Dhis2DataValueSetImportConfig(connection="c")
    one = Dhis2DataValueSetImportConfig(connection="c", data_values={})
    assert operator.check_config(both) == ["an import takes data_values or source_uri, not both"]
    assert operator.check_config(neither) == ["an import needs data_values or a source_uri to send"]
    assert operator.check_config(one) == []


@pytest.mark.parametrize("field", ["import_strategy", "atomic_mode"])
def test_an_import_mode_dhis2_does_not_know_is_refused_at_config(field: str) -> None:
    with pytest.raises(ValidationError):
        Dhis2DataValueSetImportConfig.model_validate({"connection": "c", "data_values": {}, field: "MAYBE"})
