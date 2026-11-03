"""``dhis2.metadata_import``: write a metadata bundle with ``POST /api/metadata`` and read its import report."""

from typing import Any, ClassVar, Final, Literal

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.imports import Dhis2ImportCounts
from dirigent_dhis2.messages import METADATA_IMPORT_NO_REPORT, METADATA_IMPORT_NOT_A_BUNDLE, METADATA_IMPORT_REFUSED
from dirigent_dhis2.reports import (
    as_list,
    as_object,
    body_of,
    document_kind,
    import_counts,
    named_first,
    sent,
    short_class,
    text,
)
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: Where a metadata bundle is imported.
METADATA_PATH: Final = "/api/metadata"

#: What the import may do to objects already there.
MetadataImportStrategy = Literal["CREATE_AND_UPDATE", "CREATE", "UPDATE", "DELETE"]

#: Whether one refused object refuses the whole bundle; the metadata importer knows no OBJECT.
MetadataAtomicMode = Literal["ALL", "NONE"]

#: Which property of an object, and of every reference in it, the instance matches it by.
MetadataIdentifier = Literal["UID", "CODE", "AUTO"]

#: How an update meets the object it updates.
MetadataMergeMode = Literal["REPLACE", "MERGE"]


class Dhis2MetadataImportConfig(BlockModel):
    """What one metadata import sends, and how the instance is told to take it.

    One ``POST /api/metadata`` with a bundle: an object keyed by collection, each holding the
    objects to write, the shape ``dhis2.metadata_export`` answers under ``collections`` and
    DHIS2's own metadata export produces. One object is a bundle of one, such as
    ``{dataElements: [{name: ..., shortName: ..., valueType: NUMBER, ...}]}``; deleting one is
    the same bundle with only its ``id`` and ``import_strategy: DELETE``, and changing a few
    fields of one is ``import_strategy: UPDATE`` with ``merge_mode: MERGE``.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    metadata: JsonValue
    """The metadata bundle to send: an object keyed by collection name, such as
    ``{dataElements: [...], dataSets: [...]}``, written in the step or referenced from an
    upstream output."""

    dry_run: bool = False
    """Whether the instance validates the bundle without writing anything, sent as
    ``importMode=VALIDATE``: DHIS2's metadata importer ignores ``dryRun`` and commits."""

    import_strategy: MetadataImportStrategy = "CREATE_AND_UPDATE"
    """What the import may do to existing objects: CREATE_AND_UPDATE, CREATE, UPDATE, or DELETE."""

    atomic_mode: MetadataAtomicMode = "ALL"
    """ALL refuses the whole bundle when any object is refused; NONE writes what it can."""

    identifier: MetadataIdentifier = "UID"
    """Which property objects and references are matched by: UID, CODE, or AUTO for either."""

    merge_mode: MetadataMergeMode | None = None
    """How an update meets the stored object: REPLACE overwrites every field, MERGE keeps the
    fields the bundle leaves out; the instance's own default, REPLACE, when unset."""

    skip_sharing: bool = False
    """Whether the sharing settings in the bundle are left out of the import."""

    fail_on_error: bool = True
    """Whether a report whose status is ERROR fails the step; off, the step succeeds and the
    output carries the errors."""


class Dhis2MetadataObject(BlockModel):
    """One object the report names."""

    object_class: str
    """The DHIS2 class the object is, such as DataElement."""

    uid: str | None = None
    """The object's uid, including one the instance generated for an object sent without one."""

    index: int | None = None
    """Where the object sits in its collection in the bundle that was sent, counted from zero."""


class Dhis2MetadataConflict(BlockModel):
    """One object the report refused, in the instance's own words."""

    object_class: str
    """The DHIS2 class of the refused object, such as DataElement."""

    uid: str | None = None
    """The refused object's uid, when it had one."""

    index: int | None = None
    """Where the refused object sits in its collection in the bundle, counted from zero."""

    error_code: str | None = None
    """The instance's code for the refusal, such as E4000."""

    value: str
    """Why, in the instance's own words."""

    property: str | None = None
    """The property the refusal is about, when the instance named one."""


class Dhis2MetadataImportOutput(BlockModel):
    """What the import report said."""

    status: str
    """The report's own word: OK, WARNING, or ERROR when ``fail_on_error`` is off."""

    dry_run: bool
    """Whether this was a validation only, with nothing written."""

    sent: int
    """How many objects the bundle held, across its collections."""

    counts: Dhis2ImportCounts
    """What happened to the objects: imported (DHIS2's created), updated, ignored and deleted."""

    by_class: dict[str, Dhis2ImportCounts]
    """The same counts for each class of object in the bundle, keyed by class, such as DataElement."""

    objects: list[Dhis2MetadataObject]
    """Every object the report names, with its uid."""

    conflicts: list[Dhis2MetadataConflict]
    """Every object the report refused, empty when the import was clean."""


def _report(body: dict[str, Any]) -> dict[str, Any] | None:
    """Find the import report in an answer: under ``response`` on current versions, else at the top."""
    for candidate in (as_object(body.get("response")), body):
        if candidate is not None and ("stats" in candidate or "typeReports" in candidate):
            return candidate
    return None


def _status(report: dict[str, Any], body: dict[str, Any]) -> str:
    """Read the report's status, falling back to the envelope's own."""
    return str(report.get("status") or body.get("status") or "")


def _type_reports(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The report's per-class reports, whichever objects among them are objects."""
    return [entry for entry in map(as_object, as_list(report.get("typeReports"))) if entry is not None]


def _objects(report: dict[str, Any]) -> list[Dhis2MetadataObject]:
    """Every object the per-class reports name."""
    found: list[Dhis2MetadataObject] = []
    for type_report in _type_reports(report):
        for entry in map(as_object, as_list(type_report.get("objectReports"))):
            if entry is None:
                continue
            index = entry.get("index")
            found.append(
                Dhis2MetadataObject(
                    object_class=short_class(entry.get("klass") or type_report.get("klass")),
                    uid=text(entry.get("uid")),
                    index=index if isinstance(index, int) else None,
                )
            )
    return found


def _errors(report: dict[str, Any]) -> list[Dhis2MetadataConflict]:
    """Every error report the per-class reports carry, with the object each is about."""
    found: list[Dhis2MetadataConflict] = []
    for type_report in _type_reports(report):
        for entry in map(as_object, as_list(type_report.get("objectReports"))):
            if entry is None:
                continue
            index = entry.get("index")
            for error in map(as_object, as_list(entry.get("errorReports"))):
                if error is None:
                    continue
                found.append(
                    Dhis2MetadataConflict(
                        object_class=short_class(error.get("mainKlass") or entry.get("klass")),
                        uid=text(entry.get("uid")) or text(error.get("mainId")),
                        index=index if isinstance(index, int) else None,
                        error_code=text(error.get("errorCode")),
                        value=text(error.get("message")) or "",
                        property=text(error.get("errorProperty")),
                    )
                )
    return found


def _by_class(report: dict[str, Any]) -> dict[str, Dhis2ImportCounts]:
    """The counts each per-class report carries, keyed by the class's simple name."""
    return {
        short_class(entry.get("klass")): import_counts(as_object(entry.get("stats")))
        for entry in _type_reports(report)
        if short_class(entry.get("klass"))
    }


def _subject(error: Dhis2MetadataConflict) -> str:
    """Name a refused object: its class and uid, or its class and place in the bundle."""
    if error.uid:
        return f"{error.object_class} {error.uid}"
    if error.index is not None:
        return f"{error.object_class} #{error.index}"
    return error.object_class or "the bundle"


def import_params(config: Dhis2MetadataImportConfig) -> dict[str, str]:
    """Build the ``/api/metadata`` query the config asks for, every object reported."""
    params = {
        "importStrategy": config.import_strategy,
        "atomicMode": config.atomic_mode,
        "identifier": config.identifier,
        "importMode": "VALIDATE" if config.dry_run else "COMMIT",
        "importReportMode": "FULL",
    }
    if config.merge_mode is not None:
        params["mergeMode"] = config.merge_mode
    if config.skip_sharing:
        params["skipSharing"] = "true"
    return params


class Dhis2MetadataImportOperator(Dhis2Operator[Dhis2MetadataImportConfig, Dhis2MetadataImportOutput]):
    """Sends one metadata bundle and fails the step when the instance's report says ERROR."""

    spec = OperatorSpec(
        id="dhis2.metadata_import",
        summary="Create, update or delete DHIS2 metadata from a bundle, one object or many.",
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2MetadataImportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2MetadataImportOutput

    async def execute(self, config: Dhis2MetadataImportConfig, ctx: StepContext) -> Dhis2MetadataImportOutput:
        """Send the bundle and turn the import report into an output, or into a classified refusal."""
        where = f"POST {METADATA_PATH}"
        if not isinstance(config.metadata, dict):
            raise BlockFailure(
                METADATA_IMPORT_NOT_A_BUNDLE, error_class=ErrorClass.REJECTED, got=document_kind(config.metadata)
            )
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.post_raw(METADATA_PATH, config.metadata, params=import_params(config))
            except Dhis2ApiError as error:
                refused = body_of(error)
                if refused is None or _report(refused) is None:
                    raise refuse(error, where) from error
                body = refused
            except AuthenticationError as error:
                raise refuse(error, where) from error
        report = _report(body)
        if report is None:
            raise BlockFailure(METADATA_IMPORT_NO_REPORT, error_class=ErrorClass.REJECTED, where=where)
        status = _status(report, body)
        counts = import_counts(as_object(report.get("stats")))
        conflicts = _errors(report)
        ctx.log.info(
            "metadata import report",
            status=status,
            dry_run=config.dry_run,
            **counts.model_dump(),
            conflicts=len(conflicts),
        )
        if status == "ERROR" and config.fail_on_error:
            named = [f"{_subject(conflict)}: {conflict.value}" for conflict in conflicts]
            detail = named_first(named) or str(body.get("message") or "the report named no object")
            raise BlockFailure(
                METADATA_IMPORT_REFUSED, error_class=ErrorClass.REJECTED, detail=detail, **counts.model_dump()
            )
        return Dhis2MetadataImportOutput(
            status=status,
            dry_run=config.dry_run,
            sent=sent(config.metadata),
            counts=counts,
            by_class=_by_class(report),
            objects=_objects(report),
            conflicts=conflicts,
        )
