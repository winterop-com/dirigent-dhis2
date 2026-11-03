"""``dhis2.analytics_run``: run the analytics tables job, submitted once and then probed."""

from datetime import timedelta
from typing import ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.jobs import JOINED, NOTIFIER, fetch_task, probe_task, running_job, submitted, task_handle
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import ConnectionRef, OperatorSpec, ProbeResult, RemoteHandle, StepContext

#: Where the analytics tables job is submitted.
ANALYTICS_PATH: Final = "/api/resourceTables/analytics"

#: The job type DHIS2 files an analytics tables run under.
ANALYTICS_JOB_TYPE: Final = "ANALYTICS_TABLE"


class Dhis2AnalyticsRunConfig(BlockModel):
    """What one analytics tables run asks of the instance."""

    connection: ConnectionRef
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

    join_running: bool = True
    """Whether an analytics job already running on the instance is followed instead of a second
    one being submitted. The joined job runs with the options it was started with, not these."""


class Dhis2AnalyticsRunOutput(BlockModel):
    """What the finished analytics job reported."""

    task_id: str
    """The id the instance gave the job."""

    completed_at: str | None = None
    """When the task said it was done, in the instance's own timestamp."""

    messages: list[str]
    """The last few notification messages, oldest first."""

    joined: bool = False
    """Whether the step followed a job already running rather than submitting its own."""


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
        """Join a running job, or submit one, and hand back the task reference the engine probes."""
        async with client_for(ctx, config.connection) as client:
            if config.join_running:
                running = await running_job(client, ctx, ANALYTICS_JOB_TYPE)
                if running is not None:
                    handle = task_handle(self.spec.id, ANALYTICS_JOB_TYPE, running, joined=True)
                    ctx.log.info("analytics job already running, following it", notifier=handle.meta[NOTIFIER])
                    return handle
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
        handle = submitted(self.spec.id, envelope)
        ctx.log.info("analytics job submitted", notifier=handle.meta[NOTIFIER])
        return handle

    async def probe(self, handle: RemoteHandle, config: Dhis2AnalyticsRunConfig, ctx: StepContext) -> ProbeResult:
        """Poll the task once, stream what is new into the run's log, and map its state."""
        return await probe_task(handle, config.connection, ctx)

    async def fetch(
        self, handle: RemoteHandle, config: Dhis2AnalyticsRunConfig, ctx: StepContext
    ) -> Dhis2AnalyticsRunOutput:
        """Collect the finished task's story; safe to call again."""
        story = await fetch_task(handle, config.connection, ctx)
        return Dhis2AnalyticsRunOutput(
            task_id=handle.ref,
            completed_at=story.completed_at,
            messages=story.messages,
            joined=handle.meta.get(JOINED) == "true",
        )

    async def cancel(self, handle: RemoteHandle, config: Dhis2AnalyticsRunConfig, ctx: StepContext) -> bool:
        """Report that the job could not be told: DHIS2 offers no way to stop a running analytics job."""
        return False
