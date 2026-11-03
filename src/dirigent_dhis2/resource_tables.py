"""``dhis2.resource_tables_run``: rebuild the resource tables on their own, as a job the engine follows."""

from datetime import timedelta
from typing import ClassVar, Final

from dhis2w_client import WebMessageResponse
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.jobs import JOINED, NOTIFIER, fetch_task, probe_task, running_job, submitted, task_handle
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import ConnectionRef, OperatorSpec, ProbeResult, RemoteHandle, StepContext

#: Where the resource tables job is submitted.
RESOURCE_TABLES_PATH: Final = "/api/resourceTables"

#: The job type DHIS2 files a resource tables run under.
RESOURCE_TABLE_JOB_TYPE: Final = "RESOURCE_TABLE"


class Dhis2ResourceTablesRunConfig(BlockModel):
    """Which instance's resource tables to rebuild.

    The resource tables are the flattened org unit hierarchy, category structure, period and
    group set tables that analytics and many SQL views read. ``dhis2.analytics_run`` rebuilds
    them first unless told to skip them; this block rebuilds them and nothing else, which is
    what a metadata change needs before a SQL view or the data entry screens read it.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    join_running: bool = True
    """Whether a resource tables job already running on the instance is followed instead of a
    second one being submitted."""


class Dhis2ResourceTablesRunOutput(BlockModel):
    """What the finished resource tables job reported."""

    task_id: str
    """The id the instance gave the job."""

    completed_at: str | None = None
    """When the task said it was done, in the instance's own timestamp."""

    messages: list[str]
    """The last few notification messages, oldest first."""

    joined: bool = False
    """Whether the step followed a job already running rather than submitting its own."""


class Dhis2ResourceTablesRunOperator(Dhis2Operator[Dhis2ResourceTablesRunConfig, Dhis2ResourceTablesRunOutput]):
    """Submits the resource tables job and follows its notifications until it settles."""

    spec = OperatorSpec(
        id="dhis2.resource_tables_run",
        summary="Rebuild the DHIS2 resource tables, without the analytics tables.",
        default_poll=timedelta(seconds=30),
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2ResourceTablesRunConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2ResourceTablesRunOutput

    async def execute(self, config: Dhis2ResourceTablesRunConfig, ctx: StepContext) -> RemoteHandle:
        """Join a running job, or submit one, and hand back the task reference the engine probes."""
        async with client_for(ctx, config.connection) as client:
            if config.join_running:
                running = await running_job(client, ctx, RESOURCE_TABLE_JOB_TYPE)
                if running is not None:
                    handle = task_handle(self.spec.id, RESOURCE_TABLE_JOB_TYPE, running, joined=True)
                    ctx.log.info("resource tables job already running, following it", notifier=handle.meta[NOTIFIER])
                    return handle
            try:
                envelope = await client.post(RESOURCE_TABLES_PATH, None, model=WebMessageResponse)
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"POST {RESOURCE_TABLES_PATH}") from error
        handle = submitted(self.spec.id, envelope)
        ctx.log.info("resource tables job submitted", notifier=handle.meta[NOTIFIER])
        return handle

    async def probe(self, handle: RemoteHandle, config: Dhis2ResourceTablesRunConfig, ctx: StepContext) -> ProbeResult:
        """Poll the task once, stream what is new into the run's log, and map its state."""
        return await probe_task(handle, config.connection, ctx)

    async def fetch(
        self, handle: RemoteHandle, config: Dhis2ResourceTablesRunConfig, ctx: StepContext
    ) -> Dhis2ResourceTablesRunOutput:
        """Collect the finished task's story; safe to call again."""
        story = await fetch_task(handle, config.connection, ctx)
        return Dhis2ResourceTablesRunOutput(
            task_id=handle.ref,
            completed_at=story.completed_at,
            messages=story.messages,
            joined=handle.meta.get(JOINED) == "true",
        )

    async def cancel(self, handle: RemoteHandle, config: Dhis2ResourceTablesRunConfig, ctx: StepContext) -> bool:
        """Report that the job could not be told: DHIS2 offers no way to stop a running resource tables job."""
        return False
