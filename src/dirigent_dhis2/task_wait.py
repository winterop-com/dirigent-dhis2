"""``dhis2.task_wait``: follow any DHIS2 job by its job type and id until it settles."""

from datetime import timedelta
from typing import ClassVar

from pydantic import BaseModel, Field

from dirigent_common import BlockModel
from dirigent_dhis2.jobs import TASK_SEGMENT_PATTERN, fetch_task, probe_task, task_handle
from dirigent_dhis2.web import Dhis2Operator
from dirigent_plugin import ConnectionRef, OperatorSpec, ProbeResult, RemoteHandle, StepContext


class Dhis2TaskWaitConfig(BlockModel):
    """Which job to wait on: the job type DHIS2 files it under, and the id it gave it.

    Any job DHIS2 runs in the background reports through the same notification feed, so this
    follows one another step or another system started: an asynchronous data value set
    import, a metadata import with ``async=true``, a job configuration run from the
    scheduler, or a job a ``http.request`` step submitted. The submission's answer names both
    halves, as ``response.jobType`` and ``response.id``.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    job_type: str = Field(pattern=TASK_SEGMENT_PATTERN)
    """The job type the task is filed under, such as ``DATAVALUE_IMPORT``, ``METADATA_IMPORT``,
    ``ANALYTICS_TABLE``, ``RESOURCE_TABLE``, ``PREDICTOR`` or ``DATA_INTEGRITY``."""

    task_id: str = Field(pattern=TASK_SEGMENT_PATTERN)
    """The id the instance gave the job, the ``response.id`` its submission answered with."""


class Dhis2TaskWaitOutput(BlockModel):
    """What the finished job reported."""

    task_id: str
    """The id of the job that was followed."""

    job_type: str
    """The job type it is filed under."""

    completed_at: str | None = None
    """When the task said it was done, in the instance's own timestamp."""

    messages: list[str]
    """The last few notification messages, oldest first."""


class Dhis2TaskWaitOperator(Dhis2Operator[Dhis2TaskWaitConfig, Dhis2TaskWaitOutput]):
    """Follows one DHIS2 job's notification feed until its terminal notification arrives."""

    spec = OperatorSpec(
        id="dhis2.task_wait",
        summary="Wait on a DHIS2 background job by its job type and id.",
        idempotent=True,
        default_poll=timedelta(seconds=10),
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2TaskWaitConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2TaskWaitOutput

    async def execute(self, config: Dhis2TaskWaitConfig, ctx: StepContext) -> RemoteHandle:
        """Hand the engine the task to probe; nothing is sent until the first probe reads its feed."""
        handle = task_handle(self.spec.id, config.job_type, config.task_id)
        ctx.log.info("following a job", job_type=config.job_type, task=config.task_id)
        return handle

    async def probe(self, handle: RemoteHandle, config: Dhis2TaskWaitConfig, ctx: StepContext) -> ProbeResult:
        """Poll the task once, stream what is new into the run's log, and map its state."""
        return await probe_task(handle, config.connection, ctx)

    async def fetch(self, handle: RemoteHandle, config: Dhis2TaskWaitConfig, ctx: StepContext) -> Dhis2TaskWaitOutput:
        """Collect the finished task's story; safe to call again."""
        story = await fetch_task(handle, config.connection, ctx)
        return Dhis2TaskWaitOutput(
            task_id=handle.ref,
            job_type=config.job_type,
            completed_at=story.completed_at,
            messages=story.messages,
        )

    async def cancel(self, handle: RemoteHandle, config: Dhis2TaskWaitConfig, ctx: StepContext) -> bool:
        """Report that the job was left alone: waiting on a job is not owning it."""
        return False
