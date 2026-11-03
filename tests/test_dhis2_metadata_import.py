"""Tests for dhis2.metadata_import: the bundle sent as configured, the import report read honestly."""

import json as jsonlib
from typing import Any

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.metadata_import import Dhis2MetadataImportOperator, Dhis2MetadataImportOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

METADATA = f"{BASE_URL}/api/metadata"
DATA_ELEMENT = {"name": "ANC visits", "shortName": "ANC visits", "valueType": "NUMBER", "domainType": "AGGREGATE"}
BUNDLE = {"dataElements": [DATA_ELEMENT]}
KLASS = "org.hisp.dhis.dataelement.DataElement"


def stats(created: int = 0, updated: int = 0, deleted: int = 0, ignored: int = 0) -> dict[str, int]:
    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "ignored": ignored,
        "total": created + updated + deleted + ignored,
    }


def report(status: str, object_reports: list[dict[str, Any]], **counts: int) -> dict[str, Any]:
    """An /api/metadata answer: the import report wrapped in ``response``, as 2.41 and later answer."""
    return {
        "httpStatus": "OK" if status != "ERROR" else "Conflict",
        "status": status,
        "response": {
            "responseType": "ImportReport",
            "status": status,
            "stats": stats(**counts),
            "typeReports": [{"klass": KLASS, "stats": stats(**counts), "objectReports": object_reports}],
        },
    }


async def test_one_data_element_is_created_and_its_uid_reported(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(METADATA).answers(
        json(200, report("OK", [{"klass": KLASS, "index": 0, "uid": "deNew000001"}], created=1))
    )
    output = await call_block(Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": BUNDLE}, ctx)
    assert isinstance(output, Dhis2MetadataImportOutput)
    assert output.status == "OK"
    assert output.dry_run is False
    assert output.sent == 1
    assert output.counts.model_dump() == {"imported": 1, "updated": 0, "ignored": 0, "deleted": 0}
    assert output.by_class["DataElement"].imported == 1
    assert [(item.object_class, item.uid, item.index) for item in output.objects] == [("DataElement", "deNew000001", 0)]
    assert output.conflicts == []
    request = route.last
    assert jsonlib.loads(request.content) == BUNDLE
    assert dict(request.url.params) == {
        "importStrategy": "CREATE_AND_UPDATE",
        "atomicMode": "ALL",
        "identifier": "UID",
        "importMode": "COMMIT",
        "importReportMode": "FULL",
    }


async def test_a_dry_run_validates_with_import_mode_and_never_sends_dry_run(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """DHIS2's metadata importer ignores dryRun and commits, so VALIDATE is the only rehearsal."""
    route = dhis2.post(METADATA).answers(json(200, report("OK", [], created=1)))
    output = await call_block(
        Dhis2MetadataImportOperator(),
        {
            "connection": CONNECTION,
            "metadata": BUNDLE,
            "dry_run": True,
            "import_strategy": "UPDATE",
            "merge_mode": "MERGE",
            "atomic_mode": "NONE",
            "identifier": "CODE",
            "skip_sharing": True,
        },
        ctx,
    )
    assert isinstance(output, Dhis2MetadataImportOutput)
    assert output.dry_run is True
    params = route.last.url.params
    assert params["importMode"] == "VALIDATE"
    assert "dryRun" not in params
    assert params["importStrategy"] == "UPDATE"
    assert params["mergeMode"] == "MERGE"
    assert params["atomicMode"] == "NONE"
    assert params["identifier"] == "CODE"
    assert params["skipSharing"] == "true"


ERRORED = [
    {
        "klass": KLASS,
        "index": 0,
        "errorReports": [
            {
                "message": "Missing required property `shortName`",
                "mainKlass": KLASS,
                "errorCode": "E4000",
                "errorProperty": "shortName",
            }
        ],
    }
]


async def test_a_report_of_error_on_409_fails_the_step_naming_the_object(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(METADATA).answers(json(409, report("ERROR", ERRORED, ignored=1)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": BUNDLE}, ctx)
    assert refused.value.code == "dhis2.metadata_import.refused"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "DataElement #0: Missing required property `shortName`" in refused.value.message
    assert refused.value.params["ignored"] == 1


async def test_fail_on_error_off_reports_the_errors_as_output(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(METADATA).answers(json(409, report("ERROR", ERRORED, ignored=1)))
    output = await call_block(
        Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": BUNDLE, "fail_on_error": False}, ctx
    )
    assert isinstance(output, Dhis2MetadataImportOutput)
    assert output.status == "ERROR"
    assert output.counts.ignored == 1
    [error] = output.conflicts
    assert (error.object_class, error.index, error.error_code, error.property) == (
        "DataElement",
        0,
        "E4000",
        "shortName",
    )


async def test_a_report_at_the_top_of_the_answer_is_read_too(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    unwrapped = report("OK", [], updated=2)["response"]
    dhis2.post(METADATA).answers(json(200, unwrapped))
    output = await call_block(Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": BUNDLE}, ctx)
    assert isinstance(output, Dhis2MetadataImportOutput)
    assert output.counts.updated == 2


async def test_an_answer_without_a_report_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(METADATA).answers(json(200, {"status": "OK"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": BUNDLE}, ctx)
    assert refused.value.code == "dhis2.metadata_import.no_report"


async def test_a_refusal_without_a_report_is_classified_by_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(METADATA).answers(json(403, {"status": "ERROR", "message": "Access denied"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": BUNDLE}, ctx)
    assert refused.value.code == "dhis2.answered"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "Access denied" in refused.value.message
    assert "district" not in refused.value.message


@pytest.mark.parametrize("metadata", [[DATA_ELEMENT], "dataElements", None])
async def test_a_bundle_that_is_not_an_object_is_refused_before_sending(
    ctx: FakeContext, dhis2: Dhis2Server, metadata: Any
) -> None:
    route = dhis2.post(METADATA)
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MetadataImportOperator(), {"connection": CONNECTION, "metadata": metadata}, ctx)
    assert refused.value.code == "dhis2.metadata_import.not_a_bundle"
    assert route.requests == []


async def test_an_unknown_strategy_is_refused_by_the_schema(ctx: FakeContext) -> None:
    with pytest.raises(ValueError, match="import_strategy"):
        await call_block(
            Dhis2MetadataImportOperator(),
            {"connection": CONNECTION, "metadata": BUNDLE, "import_strategy": "UPSERT"},
            ctx,
        )


async def test_object_atomicity_is_not_a_metadata_mode(ctx: FakeContext) -> None:
    """The metadata importer takes ALL or NONE and reads OBJECT as ALL without a word."""
    with pytest.raises(ValueError, match="atomic_mode"):
        await call_block(
            Dhis2MetadataImportOperator(),
            {"connection": CONNECTION, "metadata": BUNDLE, "atomic_mode": "OBJECT"},
            ctx,
        )
