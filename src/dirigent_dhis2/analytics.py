"""``dhis2.analytics_run``: run the analytics tables job, submitted once and then probed."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import (
    BlockFailure,
    ErrorClass,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    StepContext,
)

#: Where the analytics tables job is submitted.
ANALYTICS_PATH: Final = "/api/resourceTables/analytics"

#: The handle key holding the notifier endpoint the submission answered with.
NOTIFIER = "notifier"

#: The handle key holding the job type the task poll is keyed by, beside the handle's task uid.
JOB_TYPE = "job_type"

#: The handle key holding the poll cursor: the notification identifiers already streamed in.
CURSOR = "cursor"

#: How many notification messages the output keeps, from the end of the task's story.
MESSAGE_TAIL = 10

#: How long a task may stay silent from the attempt's start before it is taken to be lost.
#:
#: DHIS2 answers a task it has never heard of exactly the way it answers one that has not
#: written its first notification yet: 200 and an empty feed. The two are told apart by time.
#: A submitted job writes its first line within seconds of starting, so a feed still empty
#: this long after the submission is a task the instance lost, restarted away, or never had.
GONE_AFTER: Final = timedelta(minutes=15)


class Dhis2AnalyticsRunConfig(BlockModel):
    """What one analytics tables run asks of the instance."""

    connection: str
    """The code of the dhis2 connection naming the instance."""

    last_years: int | None = None
    """Limit the tables to this many years back, or leave unset to build them all."""

    skip_resource_tables: bool = False
    """Whether the resource tables are left as they are."""

    skip_aggregate: bool = False
    """Whether aggregate data analytics tables are left as they are."""

    skip_events: bool = False
    """Whether event analytics tables are left as they are."""

    skip_enrollment: bool = False
    """Whether enrollment analytics tables are left as they are."""

    skip_org_unit_ownership: bool = False
    """Whether the org unit ownership table is left as it is."""


class Dhis2AnalyticsRunOutput(BlockModel):
    """What the finished analytics job reported."""

    task_id: str
    """The id the instance gave the job."""

    completed_at: str | None = None
    """When the task said it was done, in the instance's own timestamp."""

    messages: list[str]
    """The last few notification messages, oldest first."""


def _level(entry: Any) -> str:
    """Read a notification's level, defaulting the one a version left unset."""
    return (entry.level or "INFO").upper()


def _completed_at(entry: Any) -> str | None:
    """Read the completing notification's timestamp as the instance's own ISO instant."""
    return entry.time.isoformat() if entry is not None and entry.time is not None else None


def _silent_for(ctx: StepContext) -> timedelta:
    """How long this attempt has been waiting on the task, measured from its first start."""
    started = ctx.started_at if ctx.started_at.tzinfo is not None else ctx.started_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - started


class Dhis2AnalyticsRunOperator(Dhis2Operator[Dhis2AnalyticsRunConfig, Dhis2AnalyticsRunOutput]):
    """Submits the analytics tables job and follows its notifications until it settles."""

    spec = OperatorSpec(
        id="dhis2.analytics_run",
        summary="Run the DHIS2 analytics tables job.",
        default_poll=timedelta(minutes=1),
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2AnalyticsRunConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2AnalyticsRunOutput

    async def execute(self, config: Dhis2AnalyticsRunConfig, ctx: StepContext) -> RemoteHandle:
        """Submit the job and hand back the task reference the engine probes."""
        async with client_for(ctx, config.connection) as client:
            try:
                envelope = await client.maintenance.run_analytics_tables(
                    last_years=config.last_years,
                    skip_resource_tables=config.skip_resource_tables,
                    skip_aggregate=config.skip_aggregate,
                    skip_events=config.skip_events,
                    skip_enrollment=config.skip_enrollment,
                    skip_org_unit_ownership=config.skip_org_unit_ownership,
                )
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"POST {ANALYTICS_PATH}") from error
        task_ref = envelope.task_ref()
        endpoint = envelope.notifier_endpoint()
        if task_ref is None or endpoint is None:
            raise BlockFailure(
                "the analytics job submission answered without a task reference to follow",
                error_class=ErrorClass.REJECTED,
            )
        job_type, task_uid = task_ref
        ctx.log.info("analytics job submitted", notifier=endpoint)
        return RemoteHandle(block_id=self.spec.id, ref=task_uid, meta={NOTIFIER: endpoint, JOB_TYPE: job_type})

    async def probe(self, handle: RemoteHandle, config: Dhis2AnalyticsRunConfig, ctx: StepContext) -> ProbeResult:
        """Poll the task once, stream the notifications new since the cursor, and map its state."""
        task_ref = (handle.meta[JOB_TYPE], handle.ref)
        cursor = json.loads(handle.meta.get(CURSOR, "[]"))
        async with client_for(ctx, config.connection) as client:
            try:
                poll = await client.tasks.poll_once(task_ref, cursor=cursor)
            except Dhis2ApiError as error:
                if error.status_code == 404:
                    return ProbeResult(
                        status=ProbeStatus.GONE, message=f"the instance no longer knows task {handle.ref}"
                    )
                raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
            except AuthenticationError as error:
                raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
        for entry in poll.new:
            log = ctx.log.warning if _level(entry) == "ERROR" else ctx.log.info
            log(entry.message or "", level=_level(entry))
        advanced = {**handle.meta, CURSOR: json.dumps(sorted(poll.cursor))}
        if not poll.completed:
            if not poll.cursor and _silent_for(ctx) >= GONE_AFTER:
                return ProbeResult(
                    status=ProbeStatus.GONE,
                    message=f"the instance has reported nothing for task {handle.ref} since it was submitted",
                )
            return ProbeResult(status=ProbeStatus.RUNNING, message="the task is still running", meta=advanced)
        terminal = poll.new[-1] if poll.new else None
        if terminal is not None and _level(terminal) == "ERROR":
            return ProbeResult(status=ProbeStatus.FAILED, message=f"the task failed: {terminal.message or ''}")
        return ProbeResult(
            status=ProbeStatus.SUCCEEDED,
            message=terminal.message if terminal is not None else None,
            meta=advanced,
        )

    async def fetch(
        self, handle: RemoteHandle, config: Dhis2AnalyticsRunConfig, ctx: StepContext
    ) -> Dhis2AnalyticsRunOutput:
        """Collect the finished task's story; safe to call again."""
        task_ref = (handle.meta[JOB_TYPE], handle.ref)
        async with client_for(ctx, config.connection) as client:
            try:
                poll = await client.tasks.poll_once(task_ref)
            except Dhis2ApiError as error:
                if error.status_code == 404:
                    raise BlockFailure(
                        f"task {handle.ref} disappeared before its result could be collected",
                        error_class=ErrorClass.TRANSIENT,
                    ) from error
                raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
            except AuthenticationError as error:
                raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
        story = poll.new
        terminal = story[-1] if story and story[-1].completed else None
        return Dhis2AnalyticsRunOutput(
            task_id=handle.ref,
            completed_at=_completed_at(terminal),
            messages=[entry.message or "" for entry in story][-MESSAGE_TAIL:],
        )

    async def cancel(self, handle: RemoteHandle, config: Dhis2AnalyticsRunConfig, ctx: StepContext) -> bool:
        """Report that the job could not be told: DHIS2 offers no way to stop a running analytics job."""
        return False
