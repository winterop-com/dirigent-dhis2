"""What the blocks that follow a DHIS2 job share: the task reference, the poll, and the story it tells.

A DHIS2 job is followed through its notification feed at ``/api/system/tasks/{job type}/{id}``.
Every block that hands the engine a job to probe -- the analytics and resource table runs, and
the wait on an arbitrary task -- reads that feed the same way, through :func:`probe_task` and
:func:`fetch_task`, so a task lost to a restart or never heard of settles the same in each.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Final, NamedTuple

from dhis2w_client import Dhis2Client, WebMessageResponse
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError

from dirigent_dhis2.connection import client_for
from dirigent_dhis2.messages import TASK_DISAPPEARED, TASK_NO_REFERENCE, TASK_NO_RESULT
from dirigent_dhis2.web import refuse
from dirigent_plugin import (
    BlockFailure,
    ConnectionRef,
    ErrorClass,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    StepContext,
)

#: The handle key holding the notifier endpoint the task is read from.
NOTIFIER = "notifier"

#: The handle key holding the job type the task poll is keyed by, beside the handle's task uid.
JOB_TYPE = "job_type"

#: The handle key marking a job this step joined rather than submitted.
JOINED = "joined"

#: The handle key holding the poll cursor: the notification identifiers already streamed in.
#:
#: It holds every identifier seen so far, because the client's poll tells new rows from old
#: by membership. A job's story is a few hundred rows at most, so the handle stays small; it
#: is not trimmed.
CURSOR = "cursor"

#: A job type or task uid as it may sit in the task poll's path: one segment, nothing to escape.
TASK_SEGMENT: Final = re.compile(r"[A-Za-z0-9_-]+")

#: The same segment as a pattern a config field holds its value to.
TASK_SEGMENT_PATTERN: Final = r"^[A-Za-z0-9_-]+$"

#: The status an instance answers the job listing with for a user not allowed to read it.
FORBIDDEN: Final = 403

#: Where the instance's job configurations are listed, a running job among them.
JOB_CONFIGURATIONS_PATH: Final = "/api/jobConfigurations"

#: How many notification messages an output keeps, from the end of the task's story.
MESSAGE_TAIL = 10

#: How long a task may stay silent from the attempt's start before it is taken to be lost.
#:
#: DHIS2 answers a task it has never heard of exactly the way it answers one that has not
#: written its first notification yet: 200 and an empty feed. The two are told apart by time.
#: A submitted job writes its first line within seconds of starting, so a feed still empty
#: this long after the submission is a task the instance lost, restarted away, or never had.
GONE_AFTER: Final = timedelta(minutes=15)


class TaskStory(NamedTuple):
    """What a finished task's feed said: when it ended, and its last few messages."""

    completed_at: str | None
    """When the task said it was done, in the instance's own timestamp."""

    messages: list[str]
    """The last few notification messages, oldest first."""


def notifier_path(job_type: str, task_uid: str) -> str:
    """The notification feed a task is read from."""
    return f"/api/system/tasks/{job_type}/{task_uid}"


def _level(entry: Any) -> str:
    """Read a notification's level, defaulting the one a version left unset."""
    return (entry.level or "INFO").upper()


def _completed_at(entry: Any) -> str | None:
    """Read the completing notification's timestamp as the instance's own ISO instant."""
    return entry.time.isoformat() if entry is not None and entry.time is not None else None


def _identity(entry: Any) -> str:
    """The identifier a notification is told from the others by, the way the client tells them.

    A row without one is streamed on every poll, which is what the client does too.
    """
    time = getattr(entry, "time", None)
    return str(getattr(entry, "uid", None) or getattr(entry, "id", None) or (time.isoformat() if time else ""))


def followable(job_type: str, task_uid: str) -> bool:
    """Whether both halves of a task reference can name one poll path."""
    return all(TASK_SEGMENT.fullmatch(part) for part in (job_type, task_uid))


def _silent_for(ctx: StepContext) -> timedelta:
    """How long this attempt has been waiting on the task, measured from its first start."""
    started = ctx.started_at if ctx.started_at.tzinfo is not None else ctx.started_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - started


def task_handle(block_id: str, job_type: str, task_uid: str, *, joined: bool = False) -> RemoteHandle:
    """The handle the engine probes a task through, refusing a reference that names no one path."""
    if not followable(job_type, task_uid):
        raise BlockFailure(TASK_NO_REFERENCE, error_class=ErrorClass.REJECTED)
    meta = {NOTIFIER: notifier_path(job_type, task_uid), JOB_TYPE: job_type}
    if joined:
        meta[JOINED] = "true"
    return RemoteHandle(block_id=block_id, ref=task_uid, meta=meta)


def submitted(block_id: str, envelope: WebMessageResponse) -> RemoteHandle:
    """The handle for the job a submission answered with, refusing an answer that names none."""
    task_ref = envelope.task_ref()
    if task_ref is None:
        raise BlockFailure(TASK_NO_REFERENCE, error_class=ErrorClass.REJECTED)
    job_type, task_uid = task_ref
    return task_handle(block_id, job_type, task_uid)


async def running_job(client: Dhis2Client, ctx: StepContext, job_type: str) -> str | None:
    """The uid of the job of this type the instance is running now, or None when it runs none.

    The job configuration's status is read rather than the notification feed, because a feed
    carries the instance's local time and says nothing of whether its job is still alive. A
    user allowed to run the job may still be refused the job listing; that answers None.
    """
    try:
        running = await client.tasks.running(job_type)
    except Dhis2ApiError as error:
        if error.status_code != FORBIDDEN:
            raise refuse(error, f"GET {JOB_CONFIGURATIONS_PATH}") from error
        ctx.log.warning("the job listing was refused, so a running job cannot be joined", job_type=job_type)
        return None
    except AuthenticationError as error:
        raise refuse(error, f"GET {JOB_CONFIGURATIONS_PATH}") from error
    return next((job.id for job in running if job.id), None)


async def probe_task(handle: RemoteHandle, connection: ConnectionRef, ctx: StepContext) -> ProbeResult:
    """Poll the task once, stream the notifications new since the cursor, and map its state.

    The feed is read whole and the cursor applied here rather than in the client, because
    the poll has to know whether the feed is empty: an instance that restarts drops every
    task's notifications, and a feed that is empty after it had spoken is a task the
    instance lost. The client's cursor would hide that, since it reports the rows it has
    seen whether or not the instance still holds them.
    """
    task_ref = (handle.meta[JOB_TYPE], handle.ref)
    seen: set[str] = set(json.loads(handle.meta.get(CURSOR, "[]")))
    async with client_for(ctx, connection) as client:
        try:
            poll = await client.tasks.poll_once(task_ref)
        except Dhis2ApiError as error:
            if error.status_code == 404:
                return ProbeResult(status=ProbeStatus.GONE, message=f"the instance no longer knows task {handle.ref}")
            raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
        except AuthenticationError as error:
            raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
    new = [entry for entry in poll.new if _identity(entry) not in seen]
    for entry in new:
        log = ctx.log.warning if _level(entry) == "ERROR" else ctx.log.info
        log(entry.message or "", level=_level(entry))
    advanced = {**handle.meta, CURSOR: json.dumps(sorted(seen | set(poll.cursor)))}
    if not poll.completed:
        if not poll.new and seen:
            return ProbeResult(
                status=ProbeStatus.GONE,
                message=f"the instance has dropped the feed of task {handle.ref} after it had reported",
            )
        if not poll.new and _silent_for(ctx) >= GONE_AFTER:
            return ProbeResult(
                status=ProbeStatus.GONE,
                message=f"the instance has reported nothing for task {handle.ref} since it was submitted",
            )
        return ProbeResult(status=ProbeStatus.RUNNING, message="the task is still running", meta=advanced)
    # A settled outcome carries no cursor on purpose: a re-probe of the same handle reads
    # the terminal row again and settles again, which is the at-least-once the contract
    # asks for.
    terminal = poll.new[-1] if poll.new else None
    if terminal is not None and _level(terminal) == "ERROR":
        return ProbeResult(status=ProbeStatus.FAILED, message=f"the task failed: {terminal.message or ''}")
    return ProbeResult(status=ProbeStatus.SUCCEEDED, message=terminal.message if terminal is not None else None)


async def fetch_task(handle: RemoteHandle, connection: ConnectionRef, ctx: StepContext) -> TaskStory:
    """Collect the finished task's story; safe to call again.

    The story is the whole feed, ending at the terminal row. A feed without one is not a
    result: the instance restarted and dropped it, or the probe that settled read a feed
    this fetch no longer sees. Either way the step has nothing to report, so it says so
    instead of answering an empty story as a success.
    """
    task_ref = (handle.meta[JOB_TYPE], handle.ref)
    async with client_for(ctx, connection) as client:
        try:
            poll = await client.tasks.poll_once(task_ref)
        except Dhis2ApiError as error:
            if error.status_code == 404:
                raise BlockFailure(TASK_DISAPPEARED, error_class=ErrorClass.TRANSIENT, task=handle.ref) from error
            raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
        except AuthenticationError as error:
            raise refuse(error, f"GET {handle.meta[NOTIFIER]}") from error
    story = poll.new
    terminal = story[-1] if story and story[-1].completed else None
    if terminal is None:
        raise BlockFailure(TASK_NO_RESULT, error_class=ErrorClass.TRANSIENT, task=handle.ref)
    return TaskStory(
        completed_at=_completed_at(terminal),
        messages=[entry.message or "" for entry in story][-MESSAGE_TAIL:],
    )
