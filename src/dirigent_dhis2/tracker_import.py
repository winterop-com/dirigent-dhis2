"""``dhis2.tracker_import``: write tracker objects with ``POST /api/tracker``, as a job the engine follows."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Final, Literal

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.imports import Dhis2ImportCounts
from dirigent_dhis2.messages import (
    TRACKER_IMPORT_NO_JOB,
    TRACKER_IMPORT_NO_REPORT,
    TRACKER_IMPORT_NOT_A_BUNDLE,
    TRACKER_IMPORT_REFUSED,
)
from dirigent_dhis2.reports import (
    as_list,
    as_object,
    body_of,
    document_kind,
    import_counts,
    named_first,
    sent,
    text,
)
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import (
    BlockFailure,
    ConnectionRef,
    ErrorClass,
    OperatorSpec,
    ProbeResult,
    ProbeStatus,
    RemoteHandle,
    StepContext,
)

#: Where tracker objects are imported.
TRACKER_PATH: Final = "/api/tracker"

#: A job id as it may sit in the job's path: one segment, nothing to escape.
JOB_SEGMENT: Final = re.compile(r"[A-Za-z0-9_-]+")

#: How long a job may stay silent from the attempt's start before it is taken to be lost.
GONE_AFTER: Final = timedelta(minutes=15)

#: The lists a tracker bundle holds its objects in.
TRACKER_COLLECTIONS: Final = ("trackedEntities", "enrollments", "events", "relationships")

#: What the import may do to objects already there.
TrackerImportStrategy = Literal["CREATE_AND_UPDATE", "CREATE", "UPDATE", "DELETE"]

#: Whether one refused object refuses the whole bundle, or only itself.
TrackerAtomicMode = Literal["ALL", "OBJECT"]


class Dhis2TrackerImportConfig(BlockModel):
    """What one tracker import sends, and how the instance is told to take it.

    One ``POST /api/tracker`` with a bundle of ``trackedEntities``, ``enrollments``, ``events``
    and ``relationships`` in DHIS2's own tracker shape. By default the instance runs it as a
    background job, and the step hands the job to the engine to follow rather than holding a
    worker: each probe reads ``/api/tracker/jobs/{id}``, and the finished job's report is read
    from ``/api/tracker/jobs/{id}/report``.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    tracker: JsonValue
    """The tracker bundle to send: an object of ``trackedEntities``, ``enrollments``, ``events``
    and ``relationships`` lists, written in the step or referenced from an upstream output."""

    dry_run: bool = False
    """Whether the instance validates the bundle without writing anything, sent as
    ``importMode=VALIDATE``."""

    import_strategy: TrackerImportStrategy = "CREATE_AND_UPDATE"
    """What the import may do to existing objects: CREATE_AND_UPDATE, CREATE, UPDATE, or DELETE."""

    atomic_mode: TrackerAtomicMode = "ALL"
    """ALL refuses the whole bundle when any object is refused; OBJECT writes every object that
    passes on its own."""

    async_mode: bool = True
    """Whether the instance runs the import as a job the engine follows, as DHIS2 does by
    default; off, one request is held open until the report is in."""

    fail_on_error: bool = True
    """Whether a report whose status is ERROR fails the step; off, the step succeeds and the
    output carries the errors."""


class Dhis2TrackerObject(BlockModel):
    """One object the report names."""

    tracker_type: str
    """DHIS2's name for what the object is: TRACKED_ENTITY, ENROLLMENT, EVENT or RELATIONSHIP."""

    uid: str | None = None
    """The object's uid, including one the instance generated for an object sent without one."""

    index: int | None = None
    """Where the object sits in its list in the bundle that was sent, counted from zero."""


class Dhis2TrackerConflict(BlockModel):
    """One error or warning the validation report names, in the instance's own words."""

    tracker_type: str
    """What the object it is about is: TRACKED_ENTITY, ENROLLMENT, EVENT or RELATIONSHIP."""

    uid: str | None = None
    """The uid of the object it is about."""

    error_code: str | None = None
    """The instance's code for it, such as E1000."""

    value: str
    """What the instance said, in its own words."""


class Dhis2TrackerImportOutput(BlockModel):
    """What the import report said."""

    status: str
    """The report's own word: OK, WARNING, or ERROR when ``fail_on_error`` is off."""

    dry_run: bool
    """Whether this was a validation only, with nothing written."""

    job_id: str | None = None
    """The id of the job the instance ran the import as, when it ran as one."""

    sent: int
    """How many objects the bundle held, across its four lists."""

    counts: Dhis2ImportCounts
    """What happened to the objects: imported (DHIS2's created), updated, ignored and deleted."""

    by_tracker_type: dict[str, Dhis2ImportCounts]
    """The same counts for each tracker type in the bundle, such as TRACKED_ENTITY or EVENT."""

    objects: list[Dhis2TrackerObject]
    """Every object the report names, with its uid."""

    conflicts: list[Dhis2TrackerConflict]
    """Every error the validation report names, empty when the import was clean."""

    warnings: list[Dhis2TrackerConflict]
    """Every warning the validation report names."""


def import_params(config: Dhis2TrackerImportConfig) -> dict[str, str]:
    """Build the ``/api/tracker`` query the config asks for, every object reported."""
    return {
        "importStrategy": config.import_strategy,
        "atomicMode": config.atomic_mode,
        "importMode": "VALIDATE" if config.dry_run else "COMMIT",
        "reportMode": "FULL",
        "async": "true" if config.async_mode else "false",
    }


def _report(body: dict[str, Any]) -> dict[str, Any] | None:
    """Find the import report in an answer: at the top on current versions, else under ``response``."""
    for candidate in (body, as_object(body.get("response"))):
        if candidate is not None and ("stats" in candidate or "validationReport" in candidate):
            return candidate
    return None


def _entries(report: dict[str, Any], key: str) -> list[Dhis2TrackerConflict]:
    """The validation report's errors or warnings."""
    validation = as_object(report.get("validationReport")) or {}
    return [
        Dhis2TrackerConflict(
            tracker_type=str(entry.get("trackerType") or ""),
            uid=text(entry.get("uid")),
            error_code=text(entry.get("errorCode")),
            value=text(entry.get("message")) or "",
        )
        for entry in map(as_object, as_list(validation.get(key)))
        if entry is not None
    ]


def _type_reports(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The persistence report's per-type reports, under the name 2.41 gave it or the older one."""
    persisted = as_object(report.get("persistenceReport")) or as_object(report.get("bundleReport")) or {}
    reports = as_object(persisted.get("typeReportMap")) or {}
    return {name: entry for name, value in reports.items() if (entry := as_object(value)) is not None}


def _objects(report: dict[str, Any]) -> list[Dhis2TrackerObject]:
    """Every object the per-type reports name."""
    found: list[Dhis2TrackerObject] = []
    for name, type_report in _type_reports(report).items():
        for entry in map(as_object, as_list(type_report.get("objectReports"))):
            if entry is None:
                continue
            index = entry.get("index")
            found.append(
                Dhis2TrackerObject(
                    tracker_type=str(entry.get("trackerType") or name),
                    uid=text(entry.get("uid")),
                    index=index if isinstance(index, int) else None,
                )
            )
    return found


def _settle(
    body: dict[str, Any], config: Dhis2TrackerImportConfig, ctx: StepContext, *, where: str, job_id: str | None
) -> Dhis2TrackerImportOutput:
    """Turn the report into an output, or into the refusal its ERROR status calls for."""
    report = _report(body)
    if report is None:
        raise BlockFailure(TRACKER_IMPORT_NO_REPORT, error_class=ErrorClass.REJECTED, where=where)
    status = str(report.get("status") or "")
    counts = import_counts(as_object(report.get("stats")))
    conflicts = _entries(report, "errorReports")
    ctx.log.info(
        "tracker import report", status=status, dry_run=config.dry_run, **counts.model_dump(), conflicts=len(conflicts)
    )
    if status == "ERROR" and config.fail_on_error:
        named = [f"{conflict.tracker_type} {conflict.uid or '?'}: {conflict.value}" for conflict in conflicts]
        detail = named_first(named) or str(report.get("message") or "the report named no object")
        raise BlockFailure(
            TRACKER_IMPORT_REFUSED, error_class=ErrorClass.REJECTED, detail=detail, **counts.model_dump()
        )
    return Dhis2TrackerImportOutput(
        status=status,
        dry_run=config.dry_run,
        job_id=job_id,
        sent=sent(as_object(config.tracker) or {}, TRACKER_COLLECTIONS),
        counts=counts,
        by_tracker_type={
            name: import_counts(as_object(entry.get("stats"))) for name, entry in _type_reports(report).items()
        },
        objects=_objects(report),
        conflicts=conflicts,
        warnings=_entries(report, "warningReports"),
    )


def _silent_for(ctx: StepContext) -> timedelta:
    """How long this attempt has been waiting on the job, measured from its first start."""
    started = ctx.started_at if ctx.started_at.tzinfo is not None else ctx.started_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - started


async def _post(client: Dhis2Client, config: Dhis2TrackerImportConfig, where: str) -> dict[str, Any]:
    """Send the bundle, reading a 409 that carries a report as the instance's verdict."""
    try:
        return await client.post_raw(TRACKER_PATH, config.tracker, params=import_params(config))
    except Dhis2ApiError as error:
        refused = body_of(error)
        if refused is None or _report(refused) is None:
            raise refuse(error, where) from error
        return refused
    except AuthenticationError as error:
        raise refuse(error, where) from error


class Dhis2TrackerImportOperator(Dhis2Operator[Dhis2TrackerImportConfig, Dhis2TrackerImportOutput]):
    """Sends one tracker bundle, follows the import job, and fails the step when its report says ERROR."""

    spec = OperatorSpec(
        id="dhis2.tracker_import",
        summary="Create, update or delete DHIS2 tracked entities, enrollments, events and relationships.",
        default_poll=timedelta(seconds=10),
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2TrackerImportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2TrackerImportOutput

    async def execute(
        self, config: Dhis2TrackerImportConfig, ctx: StepContext
    ) -> Dhis2TrackerImportOutput | RemoteHandle:
        """Send the bundle: hand back the job to follow, or read the report a synchronous import answers with."""
        where = f"POST {TRACKER_PATH}"
        if not isinstance(config.tracker, dict):
            raise BlockFailure(
                TRACKER_IMPORT_NOT_A_BUNDLE, error_class=ErrorClass.REJECTED, got=document_kind(config.tracker)
            )
        async with client_for(ctx, config.connection) as client:
            body = await _post(client, config, where)
        if not config.async_mode or _report(body) is not None:
            return _settle(body, config, ctx, where=where, job_id=None)
        job_id = text((as_object(body.get("response")) or {}).get("id"))
        if job_id is None or not JOB_SEGMENT.fullmatch(job_id):
            raise BlockFailure(TRACKER_IMPORT_NO_JOB, error_class=ErrorClass.REJECTED, where=where)
        ctx.log.info("tracker import job submitted", job=job_id, dry_run=config.dry_run)
        return RemoteHandle(block_id=self.spec.id, ref=job_id)

    async def probe(self, handle: RemoteHandle, config: Dhis2TrackerImportConfig, ctx: StepContext) -> ProbeResult:
        """Read the job's notifications once and say whether it has finished."""
        path = f"{TRACKER_PATH}/jobs/{handle.ref}"
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.get_raw(path)
            except Dhis2ApiError as error:
                if error.status_code == 404:
                    return ProbeResult(
                        status=ProbeStatus.GONE, message=f"the instance no longer knows job {handle.ref}"
                    )
                raise refuse(error, f"GET {path}") from error
            except AuthenticationError as error:
                raise refuse(error, f"GET {path}") from error
        notifications = [entry for entry in map(as_object, as_list(body.get("data"))) if entry is not None]
        finished = next((entry for entry in notifications if entry.get("completed") is True), None)
        if finished is None:
            if not notifications and _silent_for(ctx) >= GONE_AFTER:
                return ProbeResult(
                    status=ProbeStatus.GONE,
                    message=f"the instance has reported nothing for job {handle.ref} since it was submitted",
                )
            return ProbeResult(status=ProbeStatus.RUNNING, message="the import is still running")
        said = text(finished.get("message"))
        if str(finished.get("level") or "").upper() == "ERROR":
            return ProbeResult(status=ProbeStatus.FAILED, message=f"the import job failed: {said or ''}")
        return ProbeResult(status=ProbeStatus.SUCCEEDED, message=said)

    async def fetch(
        self, handle: RemoteHandle, config: Dhis2TrackerImportConfig, ctx: StepContext
    ) -> Dhis2TrackerImportOutput:
        """Read the finished job's report; safe to call again."""
        path = f"{TRACKER_PATH}/jobs/{handle.ref}/report"
        where = f"GET {path}"
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.get_raw(path, params={"reportMode": "FULL"})
            except Dhis2ApiError as error:
                refused = body_of(error)
                if refused is None or _report(refused) is None:
                    if error.status_code == 404:
                        raise BlockFailure(
                            TRACKER_IMPORT_NO_REPORT, error_class=ErrorClass.TRANSIENT, where=where
                        ) from error
                    raise refuse(error, where) from error
                body = refused
            except AuthenticationError as error:
                raise refuse(error, where) from error
        return _settle(body, config, ctx, where=where, job_id=handle.ref)

    async def cancel(self, handle: RemoteHandle, config: Dhis2TrackerImportConfig, ctx: StepContext) -> bool:
        """Report that the job could not be told: the tracker importer offers no way to stop a running import."""
        return False
