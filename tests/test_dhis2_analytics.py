"""Tests for dhis2.analytics_run: submit, follow the notifications, settle honestly."""

import json as jsonlib
from datetime import UTC, datetime, timedelta

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, notification, submitted, task_feed
from dirigent_dhis2.analytics import (
    CURSOR,
    GONE_AFTER,
    JOB_TYPE,
    JOINED,
    NOTIFIER,
    Dhis2AnalyticsRunConfig,
    Dhis2AnalyticsRunOperator,
    Dhis2AnalyticsRunOutput,
)
from dirigent_plugin import BlockFailure, ErrorClass, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block

SUBMIT = f"{BASE_URL}/api/resourceTables/analytics"
JOBS = f"{BASE_URL}/api/jobConfigurations"
JOB = "ANALYTICS_TABLE"
NOTIFIER_PATH = f"/api/system/tasks/{JOB}/tk123"
TASK_URL = f"{BASE_URL}{NOTIFIER_PATH}"

T1 = "2026-09-04T07:26:19"
T2 = "2026-09-04T07:26:20"
T3 = "2026-09-04T07:26:21"


def handle(meta: dict[str, str] | None = None) -> RemoteHandle:
    base = {NOTIFIER: NOTIFIER_PATH, JOB_TYPE: JOB}
    return RemoteHandle(block_id="dhis2.analytics_run", ref="tk123", meta={**base, **(meta or {})})


def running(dhis2: Dhis2Server, *uids: str) -> None:
    """Script the job configurations listing: the analytics jobs the instance is running now."""
    dhis2.get(JOBS).answers(json(200, {"jobConfigurations": [{"id": uid} for uid in uids]}))


def cursor(*identifiers: str) -> dict[str, str]:
    """Seed a handle's cursor with the notification identifiers already streamed in."""
    return {CURSOR: jsonlib.dumps(list(identifiers))}


async def test_submitting_hands_back_the_task_reference_to_probe(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    running(dhis2)
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


async def test_a_job_already_running_is_joined_rather_than_submitted_again(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    running(dhis2, "run9")
    submit = dhis2.post(SUBMIT).answers(json(200, submitted()))
    returned = await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "run9"
    assert returned.meta[NOTIFIER] == f"/api/system/tasks/{JOB}/run9"
    assert returned.meta[JOB_TYPE] == JOB
    assert returned.meta[JOINED] == "true"
    assert submit.requests == []
    listing = dhis2.get(JOBS).last
    assert listing.url.params.get_list("filter") == [f"jobType:eq:{JOB}", "jobStatus:eq:RUNNING"]


async def test_join_running_off_submits_without_asking(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(SUBMIT).answers(json(200, submitted()))
    returned = await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION, "join_running": False}, ctx)
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "tk123"
    assert JOINED not in returned.meta
    assert ("GET", JOBS) not in dhis2.routes


async def test_a_forbidden_job_listing_submits_instead(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOBS).answers(json(403, {}))
    submit = dhis2.post(SUBMIT).answers(json(200, submitted()))
    returned = await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "tk123"
    assert JOINED not in returned.meta
    assert len(submit.requests) == 1


async def test_a_failed_job_listing_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOBS).answers(json(503, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_submission_without_a_task_reference_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    running(dhis2)
    dhis2.post(SUBMIT).answers(json(200, {"status": "OK", "response": {}}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2AnalyticsRunOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.analytics.no_task_reference"


async def test_a_refused_submission_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    running(dhis2)
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


async def test_a_succeeded_probe_leaves_the_cursor_so_a_re_probe_settles_again(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """The client reports completion only for a terminal row it has not seen, so the cursor stops short of it."""
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
    operator = Dhis2AnalyticsRunOperator()
    first = await operator.probe(handle(cursor("n1")), config, ctx.as_context())
    assert first.status is ProbeStatus.SUCCEEDED
    assert first.meta is None
    again = await operator.probe(handle(cursor("n1")), config, ctx.as_context())
    assert again.status is ProbeStatus.SUCCEEDED


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
    assert output.joined is False

    joined = await Dhis2AnalyticsRunOperator().fetch(handle({JOINED: "true"}), config, ctx.as_context())
    assert joined.joined is True


async def test_fetch_on_a_task_that_vanished_is_transient(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(json(404, {}))
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    with pytest.raises(BlockFailure) as refused:
        await Dhis2AnalyticsRunOperator().fetch(handle(), config, ctx.as_context())
    assert refused.value.error_class is ErrorClass.TRANSIENT
    assert refused.value.code == "dhis2.analytics.task_disappeared"


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


async def test_a_feed_that_empties_after_it_had_reported_probes_as_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """An instance restart drops every task's notifications; a feed empty after a row was seen is lost."""
    dhis2.get(TASK_URL).answers(json(200, []))
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(cursor("n1")), config, ctx.as_context())
    assert probed.status is ProbeStatus.GONE
    assert "dropped the feed" in (probed.message or "")


async def test_a_probe_streams_only_the_rows_the_cursor_has_not_seen(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(
        json(200, task_feed(notification("building", time=T2, uid="n2"), notification("started", time=T1, uid="n1")))
    )
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    probed = await Dhis2AnalyticsRunOperator().probe(handle(cursor("n1")), config, ctx.as_context())
    assert probed.status is ProbeStatus.RUNNING
    assert ctx.log.messages() == ["building"]
    assert probed.meta is not None
    assert jsonlib.loads(probed.meta[CURSOR]) == ["n1", "n2"]


async def test_fetch_refuses_a_feed_without_a_terminal_row(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(TASK_URL).answers(json(200, []))
    config = Dhis2AnalyticsRunConfig.model_validate({"connection": CONNECTION})
    with pytest.raises(BlockFailure) as refused:
        await Dhis2AnalyticsRunOperator().fetch(handle(), config, ctx.as_context())
    assert refused.value.error_class is ErrorClass.TRANSIENT
    assert refused.value.code == "dhis2.analytics.no_result"
    assert "no result to collect" in refused.value.message
