"""Tests for dhis2.analytics_run: submit, follow the notifications, settle honestly."""

import json as jsonlib
from datetime import UTC, datetime, timedelta

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, notification, submitted, task_feed
from dirigent_dhis2.analytics import (
    CURSOR,
    GONE_AFTER,
    JOB_TYPE,
    NOTIFIER,
    Dhis2AnalyticsRunConfig,
    Dhis2AnalyticsRunOperator,
    Dhis2AnalyticsRunOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block

SUBMIT = f"{BASE_URL}/api/resourceTables/analytics"
JOB = "ANALYTICS_TABLE"
NOTIFIER_PATH = f"/api/system/tasks/{JOB}/tk123"
TASK_URL = f"{BASE_URL}{NOTIFIER_PATH}"

T1 = "2026-09-04T07:26:19"
T2 = "2026-09-04T07:26:20"
T3 = "2026-09-04T07:26:21"


def handle(meta: dict[str, str] | None = None) -> RemoteHandle:
    base = {NOTIFIER: NOTIFIER_PATH, JOB_TYPE: JOB}
    return RemoteHandle(block_id="dhis2.analytics_run", ref="tk123", meta={**base, **(meta or {})})


def cursor(*identifiers: str) -> dict[str, str]:
    """Seed a handle's cursor with the notification identifiers already streamed in."""
    return {CURSOR: jsonlib.dumps(list(identifiers))}


async def test_submitting_hands_back_the_task_reference_to_probe(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(SUBMIT).answers(json(200, submitted()))
    returned = await call_block(
        Dhis2AnalyticsRunOperator(), {"connection": CONNECTION, "last_years": 2, "skip_events": True}, ctx
    )
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "tk123"
    assert returned.meta[NOTIFIER] == NOTIFIER_PATH
    assert returned.meta[JOB_TYPE] == JOB
    request = route.last
    assert request.url.params["lastYears"] == "2"
    assert request.url.params["skipEvents"] == "true"
    assert "skipAggregate" not in request.url.params


async def test_a_submission_without_a_task_reference_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(SUBMIT).answers(json(200, {"status": "OK", "response": {}}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_refused_submission_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(SUBMIT).answers(json(503, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_probe_streams_the_new_notifications_and_advances(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(
        json(
            200,
            task_feed(
                notification("resource tables built", time=T2, uid="n2"),
                notification("started", time=T1, uid="n1"),
            ),
        )
    )
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(cursor("n1")), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING
    assert probed.meta is not None
    assert set(jsonlib.loads(probed.meta[CURSOR])) == {"n1", "n2"}
    assert ctx.log.messages() == ["resource tables built"]


async def test_a_probe_reads_the_instance_wire_extras_and_all(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """A live 2.43.1 answers with ids, categories, LOOP levels and a parameter echo.

    The payload here is the shape play.im.dhis2.org actually returned, and reading it must
    not be broken by any field this block does not use.
    """
    dhis2.get(TASK_URL).answers(
        json(
            200,
            task_feed(
                {
                    "level": "LOOP",
                    "category": "ANALYTICS_TABLE",
                    "message": "[0/1] analytics_2026_temp",
                    "completed": False,
                    "id": "uF2aW6mMN2a",
                    "time": "2026-09-04T07:26:20.499",
                    "uid": "uF2aW6mMN2a",
                },
                {
                    "level": "INFO",
                    "category": "ANALYTICS_TABLE",
                    "message": "Analytics table update process",
                    "completed": False,
                    "dataType": "PARAMETERS",
                    "data": {"lastYears": 1, "skipTableTypes": ["ENROLLMENT"]},
                    "time": "2026-09-04T07:26:19.000",
                },
            ),
        )
    )
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING
    assert "[0/1] analytics_2026_temp" in ctx.log.messages()


async def test_a_completed_task_probes_as_succeeded(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(
        json(
            200,
            task_feed(
                notification("analytics tables updated", time=T3, completed=True, uid="n3"),
                notification("started", time=T1, uid="n1"),
            ),
        )
    )
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(cursor("n1")), config, ctx.as_context())
    assert probed.status is ProbeStatus.SUCCEEDED
    assert probed.message == "analytics tables updated"


async def test_a_task_ending_in_error_probes_as_failed(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(
        json(200, task_feed(notification("out of memory", time=T2, level="ERROR", completed=True, uid="e1")))
    )
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(), config, ctx.as_context())
    assert probed.status is ProbeStatus.FAILED
    assert "out of memory" in (probed.message or "")


async def test_a_task_the_instance_forgot_probes_as_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(json(404, {}))
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(), config, ctx.as_context())
    assert probed.status is ProbeStatus.GONE


async def test_fetch_collects_the_story(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(
        json(
            200,
            task_feed(
                notification("analytics tables updated", time=T3, completed=True, uid="n3"),
                notification("building", time=T2, uid="n2"),
                notification("started", time=T1, uid="n1"),
            ),
        )
    )
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    output = await Dhis2AnalyticsRunOperator().fetch(handle(), config, ctx.as_context())
    assert isinstance(output, Dhis2AnalyticsRunOutput)
    assert output.task_id == "tk123"
    assert output.completed_at == T3
    assert output.messages == ["started", "building", "analytics tables updated"]


async def test_fetch_on_a_task_that_vanished_is_transient(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(json(404, {}))
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    with pytest.raises(BlockFailure) as refused:
        await Dhis2AnalyticsRunOperator().fetch(handle(), config, ctx.as_context())
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_cancel_reports_that_the_job_cannot_be_told(ctx: FakeContext) -> None:
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    assert await Dhis2AnalyticsRunOperator().cancel(handle(), config, ctx.as_context()) is False


async def test_a_task_that_has_not_reported_yet_probes_as_running(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """A just-submitted job answers the same empty feed an unknown task does; time tells them apart."""
    dhis2.get(TASK_URL).answers(json(200, []))
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING


async def test_a_task_silent_since_submission_probes_as_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """The live instance answers an unknown task with 200 and an empty list, never a 404."""
    dhis2.get(TASK_URL).answers(json(200, []))
    ctx.started_at = datetime.now(UTC) - GONE_AFTER - timedelta(seconds=1)
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(), config, ctx.as_context())
    assert probed.status is ProbeStatus.GONE
    assert "reported nothing" in (probed.message or "")


async def test_a_task_that_once_reported_is_never_taken_for_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(json(200, task_feed(notification("started", time=T1, uid="n1"))))
    ctx.started_at = datetime.now(UTC) - GONE_AFTER * 4
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(cursor("n1")), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING
