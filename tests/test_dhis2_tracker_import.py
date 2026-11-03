"""Tests for dhis2.tracker_import: submitted as a job the engine follows, the report read honestly."""

import json as jsonlib
from datetime import UTC, datetime
from typing import Any

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.tracker_import import (
    GONE_AFTER,
    Dhis2TrackerImportConfig,
    Dhis2TrackerImportOperator,
    Dhis2TrackerImportOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block

TRACKER = f"{BASE_URL}/api/tracker"
JOB = "jb1234567AB"
JOB_URL = f"{TRACKER}/jobs/{JOB}"
REPORT_URL = f"{JOB_URL}/report"
EVENT: dict[str, Any] = {
    "program": "eBAyeGv0exc",
    "orgUnit": "DiszpKrYNg8",
    "occurredAt": "2026-07-01",
    "dataValues": [],
}
BUNDLE: dict[str, Any] = {"events": [EVENT]}


def accepted(job: str = JOB) -> dict[str, Any]:
    """What /api/tracker answers an import run as a job with: the job's id and where to follow it."""
    return {
        "httpStatus": "OK",
        "status": "OK",
        "message": "Tracker job added",
        "response": {"responseType": "TrackerJobWebMessageResponse", "id": job, "location": f"{JOB_URL}"},
    }


def import_report(
    status: str, *, created: int = 0, ignored: int = 0, errors: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """A tracker import report, at the top of the answer the way 2.41 and later give it."""
    counts = {"created": created, "updated": 0, "deleted": 0, "ignored": ignored, "total": created + ignored}
    return {
        "status": status,
        "stats": counts,
        "validationReport": {"errorReports": errors or [], "warningReports": []},
        "persistenceReport": {
            "status": status,
            "typeReportMap": {
                "EVENT": {
                    "trackerType": "EVENT",
                    "stats": counts,
                    "objectReports": [{"trackerType": "EVENT", "uid": "evNew000001", "index": 0}] if created else [],
                }
            },
        },
    }


def handle() -> RemoteHandle:
    return RemoteHandle(block_id="dhis2.tracker_import", ref=JOB)


def config(**overrides: Any) -> Dhis2TrackerImportConfig:
    return Dhis2TrackerImportConfig.model_validate({"connection": CONNECTION, "tracker": BUNDLE, **overrides})


async def test_an_import_is_submitted_as_a_job_and_handed_to_the_engine(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(TRACKER).answers(json(200, accepted()))
    returned = await call_block(Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE}, ctx)
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == JOB
    request = route.last
    assert jsonlib.loads(request.content) == BUNDLE
    assert dict(request.url.params) == {
        "importStrategy": "CREATE_AND_UPDATE",
        "atomicMode": "ALL",
        "importMode": "COMMIT",
        "reportMode": "FULL",
        "async": "true",
    }


async def test_a_dry_run_validates_with_import_mode(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(TRACKER).answers(json(200, accepted()))
    await call_block(
        Dhis2TrackerImportOperator(),
        {
            "connection": CONNECTION,
            "tracker": BUNDLE,
            "dry_run": True,
            "import_strategy": "DELETE",
            "atomic_mode": "OBJECT",
        },
        ctx,
    )
    params = route.last.url.params
    assert params["importMode"] == "VALIDATE"
    assert params["importStrategy"] == "DELETE"
    assert params["atomicMode"] == "OBJECT"


async def test_a_running_job_is_probed_as_running(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOB_URL).answers(json(200, [{"level": "INFO", "message": "Import started", "completed": False}]))
    probed = await Dhis2TrackerImportOperator().probe(handle(), config(), ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING


async def test_a_finished_job_is_probed_as_succeeded(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOB_URL).answers(
        json(
            200,
            [
                {"level": "INFO", "message": "Import complete", "completed": True},
                {"level": "INFO", "message": "Import started", "completed": False},
            ],
        )
    )
    probed = await Dhis2TrackerImportOperator().probe(handle(), config(), ctx.as_context())
    assert probed.status is ProbeStatus.SUCCEEDED


#: The notification DHIS2 2.42.7 ends a job with when its report refused an object.
ENDED_IN_ERROR = {
    "level": "ERROR",
    "category": "TRACKER_IMPORT_JOB",
    "message": "Import complete with status ERROR, 0 created, 0 updated, 0 deleted, 1 ignored",
    "completed": True,
}

#: The report DHIS2 2.42.7 answers for an event missing its stage's compulsory data elements,
#: at /api/tracker/jobs/{id}/report after a job, and on 409 to a synchronous import.
COMPULSORY_MISSING = {
    "status": "ERROR",
    "validationReport": {
        "errorReports": [
            {
                "message": f"Mandatory DataElement `{element}` is not present.",
                "errorCode": "E1303",
                "trackerType": "EVENT",
                "uid": "o1eUeutWZrJ",
                "args": [f"MetadataIdentifier(idScheme=UID, identifier={element}, attributeValue=null)"],
            }
            for element in ("eMyVanycQSC", "K6uUAvq500H")
        ],
        "warningReports": [],
    },
    "stats": {"created": 0, "updated": 0, "deleted": 0, "ignored": 1, "total": 1},
}


async def test_a_job_that_ended_in_error_is_finished_so_its_report_is_read(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.get(JOB_URL).answers(json(200, [ENDED_IN_ERROR, {"level": "INFO", "message": "Running Validation"}]))
    probed = await Dhis2TrackerImportOperator().probe(handle(), config(), ctx.as_context())
    assert probed.status is ProbeStatus.SUCCEEDED
    assert probed.meta == {"job_error": ENDED_IN_ERROR["message"]}


async def test_a_job_refused_for_missing_compulsory_values_fails_saying_why(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.get(REPORT_URL).answers(json(200, COMPULSORY_MISSING))
    errored = RemoteHandle(block_id="dhis2.tracker_import", ref=JOB, meta={"job_error": "Import complete"})
    with pytest.raises(BlockFailure) as refused:
        await Dhis2TrackerImportOperator().fetch(errored, config(), ctx.as_context())
    assert refused.value.code == "dhis2.tracker_import.refused"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "EVENT o1eUeutWZrJ: Mandatory DataElement `eMyVanycQSC` is not present." in refused.value.message
    assert refused.value.params["ignored"] == 1


async def test_a_job_refused_with_fail_on_error_off_answers_the_conflicts(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REPORT_URL).answers(json(200, COMPULSORY_MISSING))
    errored = RemoteHandle(block_id="dhis2.tracker_import", ref=JOB, meta={"job_error": "Import complete"})
    output = await Dhis2TrackerImportOperator().fetch(errored, config(fail_on_error=False), ctx.as_context())
    assert output.status == "ERROR"
    assert output.counts.ignored == 1
    assert [(item.tracker_type, item.uid, item.error_code) for item in output.conflicts] == [
        ("EVENT", "o1eUeutWZrJ", "E1303"),
        ("EVENT", "o1eUeutWZrJ", "E1303"),
    ]
    assert output.conflicts[1].value == "Mandatory DataElement `K6uUAvq500H` is not present."


async def test_a_synchronous_refusal_for_missing_compulsory_values_says_why(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.post(TRACKER).answers(json(409, COMPULSORY_MISSING))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE, "async_mode": False}, ctx
        )
    assert refused.value.code == "dhis2.tracker_import.refused"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "EVENT o1eUeutWZrJ: Mandatory DataElement `eMyVanycQSC` is not present. (E1303)" in refused.value.message


async def test_a_job_that_ended_in_error_with_no_report_fails_with_its_words(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.get(REPORT_URL).answers(json(404, {"status": "ERROR", "message": "not found"}))
    errored = RemoteHandle(block_id="dhis2.tracker_import", ref=JOB, meta={"job_error": "Import failed: boom"})
    with pytest.raises(BlockFailure) as refused:
        await Dhis2TrackerImportOperator().fetch(errored, config(), ctx.as_context())
    assert refused.value.code == "dhis2.tracker_import.job_failed"
    assert "Import failed: boom" in refused.value.message


async def test_a_job_the_instance_does_not_know_is_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOB_URL).answers(json(404, {"status": "ERROR", "message": "not found"}))
    probed = await Dhis2TrackerImportOperator().probe(handle(), config(), ctx.as_context())
    assert probed.status is ProbeStatus.GONE


async def test_a_job_silent_too_long_is_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOB_URL).answers(json(200, []))
    ctx.started_at = datetime.now(UTC) - GONE_AFTER
    probed = await Dhis2TrackerImportOperator().probe(handle(), config(), ctx.as_context())
    assert probed.status is ProbeStatus.GONE


async def test_the_finished_report_is_fetched_into_the_output(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(REPORT_URL).answers(json(200, import_report("OK", created=1)))
    output = await Dhis2TrackerImportOperator().fetch(handle(), config(), ctx.as_context())
    assert isinstance(output, Dhis2TrackerImportOutput)
    assert output.status == "OK"
    assert output.job_id == JOB
    assert output.sent == 1
    assert output.counts.imported == 1
    assert output.by_tracker_type["EVENT"].imported == 1
    assert [(item.tracker_type, item.uid) for item in output.objects] == [("EVENT", "evNew000001")]
    assert route.last.url.params["reportMode"] == "FULL"


ERRORS = [{"message": "Event: `xx`, organisation unit is not part of the program", "errorCode": "E1029",
           "trackerType": "EVENT", "uid": "evBad000001"}]  # fmt: skip


async def test_a_fetched_report_of_error_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REPORT_URL).answers(json(200, import_report("ERROR", ignored=1, errors=ERRORS)))
    with pytest.raises(BlockFailure) as refused:
        await Dhis2TrackerImportOperator().fetch(handle(), config(), ctx.as_context())
    assert refused.value.code == "dhis2.tracker_import.refused"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "EVENT evBad000001: Event:" in refused.value.message


async def test_a_report_not_there_yet_is_transient(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REPORT_URL).answers(json(404, {"status": "ERROR", "message": "not found"}))
    with pytest.raises(BlockFailure) as refused:
        await Dhis2TrackerImportOperator().fetch(handle(), config(), ctx.as_context())
    assert refused.value.code == "dhis2.tracker_import.no_report"
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_synchronous_import_reads_the_report_it_answers_with(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(TRACKER).answers(json(200, import_report("OK", created=1)))
    output = await call_block(
        Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE, "async_mode": False}, ctx
    )
    assert isinstance(output, Dhis2TrackerImportOutput)
    assert output.job_id is None
    assert output.counts.imported == 1
    assert route.last.url.params["async"] == "false"


async def test_a_synchronous_refusal_on_409_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(TRACKER).answers(json(409, import_report("ERROR", ignored=1, errors=ERRORS)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE, "async_mode": False}, ctx
        )
    assert refused.value.code == "dhis2.tracker_import.refused"


async def test_fail_on_error_off_reports_the_errors(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(TRACKER).answers(json(409, import_report("ERROR", ignored=1, errors=ERRORS)))
    output = await call_block(
        Dhis2TrackerImportOperator(),
        {"connection": CONNECTION, "tracker": BUNDLE, "async_mode": False, "fail_on_error": False},
        ctx,
    )
    assert isinstance(output, Dhis2TrackerImportOutput)
    assert output.status == "ERROR"
    assert [(error.error_code, error.uid) for error in output.conflicts] == [("E1029", "evBad000001")]


async def test_a_job_answer_without_an_id_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(TRACKER).answers(json(200, {"status": "OK", "response": {}}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE}, ctx)
    assert refused.value.code == "dhis2.tracker_import.no_job"


async def test_a_job_id_that_would_leave_its_path_is_refused(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(TRACKER).answers(json(200, accepted(job="../../users")))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE}, ctx)
    assert refused.value.code == "dhis2.tracker_import.no_job"


async def test_a_bundle_that_is_not_an_object_is_refused_before_sending(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(TRACKER)
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": [EVENT]}, ctx)
    assert refused.value.code == "dhis2.tracker_import.not_a_bundle"
    assert route.requests == []


async def test_a_refusal_without_a_report_is_classified_by_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(TRACKER).answers(json(503, {"status": "ERROR", "message": "unavailable"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2TrackerImportOperator(), {"connection": CONNECTION, "tracker": BUNDLE}, ctx)
    assert refused.value.code == "dhis2.answered"
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_the_job_cannot_be_cancelled(ctx: FakeContext) -> None:
    assert await Dhis2TrackerImportOperator().cancel(handle(), config(), ctx.as_context()) is False
