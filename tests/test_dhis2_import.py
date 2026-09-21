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
    assert refused.value.code == "dhis2.import.refused"
    assert refused.value.params["ignored"] == 1
    assert "data element not found" in refused.value.message


async def test_a_refusal_names_the_first_conflicts_and_counts_the_rest(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    conflicts = [{"object": f"de{n}", "value": f"reason {n}"} for n in range(5)]
    dhis2.post(IMPORT).answers(json(409, summary("ERROR", ignored=5, conflicts=conflicts)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert "de0: reason 0; de1: reason 1; de2: reason 2 (and 2 more)" in refused.value.message
    assert "de3" not in refused.value.message


async def test_a_refusal_without_conflicts_counts_the_ignored_values(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(409, summary("ERROR", ignored=4)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert "4 values ignored" in refused.value.message


async def test_a_summary_of_error_on_200_is_rejected_the_same_way(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    conflicts = [{"object": "de9", "value": "data element not found"}]
    dhis2.post(IMPORT).answers(json(200, summary("ERROR", ignored=1, conflicts=conflicts)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "data element not found" in refused.value.message


async def test_an_atomic_import_that_ignored_values_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(409, summary("WARNING", ignored=5)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.import.took_nothing"
    assert "took nothing" in refused.value.message


async def test_an_atomic_import_the_instance_took_half_of_names_what_landed(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """DHIS2 commits the good values beside the conflicts under ALL, so the failure must say so."""
    dhis2.post(IMPORT).answers(json(409, summary("WARNING", updated=1, ignored=1)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.import.partial"
    assert "took 1 values and refused 1" in refused.value.message
    assert "took nothing" not in refused.value.message


async def test_a_dry_run_leaves_the_completeness_claim_out(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """DHIS2 2.41 and 2.42 register the data set complete even under dryRun, so a rehearsal must not ask."""
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=1)))
    document = {**DOCUMENT, "orgUnit": "ou1", "completeDate": "2026-04-01"}
    await call_block(
        Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": document, "dry_run": True}, ctx
    )
    sent = jsonlib.loads(route.last.content)
    assert "completeDate" not in sent
    assert sent == {**DOCUMENT, "orgUnit": "ou1"}
    assert any(level == "warning" and "completeDate" in message for level, message, _ in ctx.log.entries)


async def test_a_real_import_sends_the_completeness_claim(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=1)))
    document = {**DOCUMENT, "orgUnit": "ou1", "completeDate": "2026-04-01"}
    await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": document}, ctx)
    assert jsonlib.loads(route.last.content)["completeDate"] == "2026-04-01"


@pytest.mark.parametrize("body", [{}, {"httpStatus": "OK", "status": "OK"}], ids=["empty", "no-summary"])
async def test_a_200_without_an_import_summary_is_not_a_success(
    ctx: FakeContext, dhis2: Dhis2Server, body: dict[str, str]
) -> None:
    dhis2.post(IMPORT).answers(json(200, body))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.import.no_summary"
    assert "without an import summary" in refused.value.message


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
    assert refused.value.code == "dhis2.answered"
    assert "Import already in progress" in refused.value.message


async def test_a_refused_transport_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(IMPORT).answers(json(503, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": DOCUMENT}, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


@pytest.mark.parametrize("field", ["import_strategy", "atomic_mode"])
def test_an_import_mode_dhis2_does_not_know_is_refused_at_config(field: str) -> None:
    with pytest.raises(ValidationError):
        Dhis2DataValueSetImportConfig.model_validate({"connection": "c", "data_values": {}, field: "MAYBE"})
