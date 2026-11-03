"""Tests for the job blocks beside analytics: the resource tables run, and the wait on any task."""

import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, notification, submitted, task_feed
from dirigent_dhis2.jobs import JOB_TYPE, JOINED, NOTIFIER
from dirigent_dhis2.resource_tables import (
    Dhis2ResourceTablesRunConfig,
    Dhis2ResourceTablesRunOperator,
    Dhis2ResourceTablesRunOutput,
)
from dirigent_dhis2.task_wait import Dhis2TaskWaitConfig, Dhis2TaskWaitOperator, Dhis2TaskWaitOutput
from dirigent_plugin import BlockFailure, ProbeStatus, RemoteHandle
from dirigent_testing import FakeContext, call_block

JOBS = f"{BASE_URL}/api/jobConfigurations"
SUBMIT = f"{BASE_URL}/api/resourceTables"
FEED = f"{BASE_URL}/api/system/tasks/RESOURCE_TABLE/rt123"

T1 = "2026-09-04T07:26:19"
T2 = "2026-09-04T07:26:20"


async def test_a_resource_tables_run_hands_back_the_task_to_probe(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOBS).answers(json(200, {"jobConfigurations": []}))
    route = dhis2.post(SUBMIT).answers(json(200, submitted(job_type="RESOURCE_TABLE", task_uid="rt123")))
    returned = await call_block(Dhis2ResourceTablesRunOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "rt123"
    assert returned.meta[JOB_TYPE] == "RESOURCE_TABLE"
    assert returned.meta[NOTIFIER] == "/api/system/tasks/RESOURCE_TABLE/rt123"
    assert len(route.requests) == 1
    assert dhis2.get(JOBS).last.url.params.get_list("filter")[0] == "jobType:eq:RESOURCE_TABLE"


async def test_a_resource_tables_job_already_running_is_joined(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(JOBS).answers(json(200, {"jobConfigurations": [{"id": "run9"}]}))
    submit = dhis2.post(SUBMIT).answers(json(200, submitted(job_type="RESOURCE_TABLE")))
    returned = await call_block(Dhis2ResourceTablesRunOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "run9"
    assert returned.meta[JOINED] == "true"
    assert submit.requests == []


async def test_a_finished_resource_tables_job_reports_its_story(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(FEED).answers(
        json(
            200,
            task_feed(
                notification("Resource tables generated", time=T2, uid="n2", completed=True),
                notification("started", time=T1, uid="n1"),
            ),
        )
    )
    handle = RemoteHandle(
        block_id="dhis2.resource_tables_run",
        ref="rt123",
        meta={NOTIFIER: "/api/system/tasks/RESOURCE_TABLE/rt123", JOB_TYPE: "RESOURCE_TABLE"},
    )
    config = Dhis2ResourceTablesRunConfig.model_validate({"connection": CONNECTION})
    operator = Dhis2ResourceTablesRunOperator()
    probed = await operator.probe(handle, config, ctx.as_context())
    assert probed.status is ProbeStatus.SUCCEEDED
    output = await operator.fetch(handle, config, ctx.as_context())
    assert isinstance(output, Dhis2ResourceTablesRunOutput)
    assert output.messages == ["started", "Resource tables generated"]
    assert output.joined is False


async def test_a_task_wait_follows_the_named_task(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    returned = await call_block(
        Dhis2TaskWaitOperator(), {"connection": CONNECTION, "job_type": "DATAVALUE_IMPORT", "task_id": "imp42"}, ctx
    )
    assert isinstance(returned, RemoteHandle)
    assert returned.ref == "imp42"
    assert returned.meta[NOTIFIER] == "/api/system/tasks/DATAVALUE_IMPORT/imp42"
    feed = f"{BASE_URL}/api/system/tasks/DATAVALUE_IMPORT/imp42"
    dhis2.get(feed).answers(json(200, task_feed(notification("Import done", time=T2, uid="n2", completed=True))))
    config = Dhis2TaskWaitConfig.model_validate(
        {"connection": CONNECTION, "job_type": "DATAVALUE_IMPORT", "task_id": "imp42"}
    )
    output = await Dhis2TaskWaitOperator().fetch(returned, config, ctx.as_context())
    assert isinstance(output, Dhis2TaskWaitOutput)
    assert output.job_type == "DATAVALUE_IMPORT"
    assert output.messages == ["Import done"]


async def test_a_waited_task_that_ends_in_error_fails(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    feed = f"{BASE_URL}/api/system/tasks/DATAVALUE_IMPORT/imp42"
    dhis2.get(feed).answers(
        json(200, task_feed(notification("Import failed", time=T2, uid="n2", completed=True, level="ERROR")))
    )
    config = Dhis2TaskWaitConfig.model_validate(
        {"connection": CONNECTION, "job_type": "DATAVALUE_IMPORT", "task_id": "imp42"}
    )
    handle = RemoteHandle(
        block_id="dhis2.task_wait",
        ref="imp42",
        meta={NOTIFIER: "/api/system/tasks/DATAVALUE_IMPORT/imp42", JOB_TYPE: "DATAVALUE_IMPORT"},
    )
    probed = await Dhis2TaskWaitOperator().probe(handle, config, ctx.as_context())
    assert probed.status is ProbeStatus.FAILED
    assert "Import failed" in (probed.message or "")


async def test_a_waited_task_the_instance_never_had_is_gone(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    feed = f"{BASE_URL}/api/system/tasks/DATAVALUE_IMPORT/imp42"
    dhis2.get(feed).answers(json(404, {"message": "not found"}))
    config = Dhis2TaskWaitConfig.model_validate(
        {"connection": CONNECTION, "job_type": "DATAVALUE_IMPORT", "task_id": "imp42"}
    )
    handle = RemoteHandle(
        block_id="dhis2.task_wait",
        ref="imp42",
        meta={NOTIFIER: "/api/system/tasks/DATAVALUE_IMPORT/imp42", JOB_TYPE: "DATAVALUE_IMPORT"},
    )
    probed = await Dhis2TaskWaitOperator().probe(handle, config, ctx.as_context())
    assert probed.status is ProbeStatus.GONE
    with pytest.raises(BlockFailure) as refused:
        await Dhis2TaskWaitOperator().fetch(handle, config, ctx.as_context())
    assert refused.value.code == "dhis2.task.disappeared"


@pytest.mark.parametrize("task_id", ["../me", "a b", "x?y", ""])
def test_a_task_id_that_is_no_path_segment_is_refused(task_id: str) -> None:
    with pytest.raises(ValidationError):
        Dhis2TaskWaitConfig.model_validate(
            {"connection": CONNECTION, "job_type": "DATAVALUE_IMPORT", "task_id": task_id}
        )
