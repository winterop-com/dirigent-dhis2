"""``dhis2.data_value_set_import``: write data values into the instance, reading its summary honestly."""

import json
from typing import ClassVar, Final, Literal

from dhis2w_client import WebMessageResponse
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.export import DATA_VALUE_SETS_PATH
from dirigent_dhis2.messages import (
    IMPORT_CONFLICTS_AND_MORE,
    IMPORT_NO_SUMMARY,
    IMPORT_PARTIAL,
    IMPORT_REFUSED,
    IMPORT_TOOK_NOTHING,
    IMPORT_UNKNOWN_STATUS,
    IMPORT_VALUES_IGNORED,
)
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, RemoteHandle, StepContext

#: How many conflicts a refusal names before pointing at the rest.
NAMED_CONFLICTS = 3

#: The counts an import summary carries, under ``importCount`` or inline.
COUNT_NAMES: Final = ("imported", "updated", "ignored", "deleted")

#: The summary statuses an import stands on; every other word fails the step.
STANDING_STATUSES: Final = ("SUCCESS", "WARNING")

#: What the import may do to values already there.
ImportStrategy = Literal["CREATE", "UPDATE", "CREATE_AND_UPDATE", "DELETE"]

#: Whether one refused value refuses the whole import.
AtomicMode = Literal["ALL", "NONE"]


class Dhis2ImportConflict(BlockModel):
    """One value the import refused, in the instance's own words."""

    object: str = ""
    """What the instance named as refused, a data element's uid on 2.42; 2.43 leaves it empty."""

    value: str = ""
    """Why, in the instance's own words."""

    error_code: str | None = None
    """The instance's code for the refusal, such as E7619."""

    indexes: list[int] = Field(default_factory=list[int])
    """Where the refused values sit in the document that was sent, counted from zero."""


class Dhis2DataValueSetImportConfig(BlockModel):
    """What one import sends, and how the instance is told to take it."""

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    data_values: JsonValue
    """The data value set document to send, written in the step or referenced from one; a set
    held in storage comes in through storage.read."""

    dry_run: bool = False
    """Whether the instance validates the import without writing anything. A `completeDate`
    in the document is left out of a dry run: DHIS2 2.41 and 2.42 register the data set
    complete even under dryRun, and a rehearsal must persist nothing."""

    import_strategy: ImportStrategy = "CREATE_AND_UPDATE"
    """What the import may do to existing values: CREATE, UPDATE, CREATE_AND_UPDATE, or DELETE."""

    atomic_mode: AtomicMode = "ALL"
    """ALL asks the instance to refuse the whole import on any conflict; NONE takes what it can.
    DHIS2 does not always honour ALL and may commit the good values beside the conflicts, so
    a failure under ALL names what landed."""


class Dhis2DataValueSetImportOutput(BlockModel):
    """What the import summary counted."""

    status: str
    """The summary's own word: SUCCESS or WARNING."""

    imported: int
    """How many values were created."""

    updated: int
    """How many values were revised."""

    ignored: int
    """How many values the instance did not take."""

    deleted: int
    """How many values were removed."""

    conflicts: list[Dhis2ImportConflict]
    """Every value the instance refused, empty when the import was clean."""


def _has_summary(envelope: WebMessageResponse) -> bool:
    """Whether the envelope carries an import summary: the summary's own type, or its counts."""
    summary = envelope.response or {}
    if summary.get("responseType") == "ImportSummary" or isinstance(summary.get("importCount"), dict):
        return True
    return any(isinstance(summary.get(name), int) for name in COUNT_NAMES)


def _summary_in(error: Dhis2ApiError) -> WebMessageResponse | None:
    """The import summary a refusal carries, when the instance refused the import with one.

    An import DHIS2 did not take answers 409 Conflict with the same envelope a taken one gets
    on 200: the summary's status, its counts, and the conflicts. That is the instance's
    verdict on the document rather than a transport failure, so it is read the way a 200 is.
    A 409 without a summary in it is an ordinary refusal.
    """
    if error.status_code != 409:
        return None
    envelope = error.web_message
    if envelope is None or not _has_summary(envelope):
        return None
    return envelope


def _outer_status(envelope: WebMessageResponse) -> str:
    """Read the envelope's own status."""
    outer = envelope.status
    return str(getattr(outer, "value", outer) or "")


def _status(envelope: WebMessageResponse) -> str:
    """Read the summary's status, falling back to the envelope's own when the summary has none."""
    inner = (envelope.response or {}).get("status")
    return str(inner) if inner else _outer_status(envelope)


def _counts(envelope: WebMessageResponse) -> dict[str, int]:
    """Read the summary's counts off the typed envelope, defaulting what a version left out."""
    counted = envelope.import_count()
    read: dict[str, int] = {}
    for name in COUNT_NAMES:
        value = getattr(counted, name, None) if counted is not None else None
        read[name] = value if isinstance(value, int) else 0
    return read


def _conflicts(envelope: WebMessageResponse) -> list[Dhis2ImportConflict]:
    """Read the summary's conflicts off the typed envelope, empty when the import was clean."""
    return [
        Dhis2ImportConflict(
            object=item.object or "",
            value=item.value or "",
            error_code=item.errorCode,
            indexes=list(item.indexes or []),
        )
        for item in envelope.conflicts()
    ]


def _detail(conflicts: list[Dhis2ImportConflict], counts: dict[str, int]) -> str:
    """Say what the instance refused, naming the first conflicts and counting the rest."""
    named = "; ".join(f"{_subject(conflict)}: {conflict.value}" for conflict in conflicts[:NAMED_CONFLICTS])
    more = len(conflicts) - NAMED_CONFLICTS
    if not named:
        return IMPORT_VALUES_IGNORED.render(ignored=counts["ignored"])
    return IMPORT_CONFLICTS_AND_MORE.render(named=named, more=more) if more > 0 else named


def _subject(conflict: Dhis2ImportConflict) -> str:
    """Name what a conflict refused: the object the instance named, else the values by position."""
    if conflict.object:
        return conflict.object
    if conflict.indexes:
        return "value " + ", ".join(f"#{index}" for index in conflict.indexes)
    return "the import"


def _taken(counts: dict[str, int]) -> int:
    """How many values the summary says landed: imported, updated or deleted."""
    return counts["imported"] + counts["updated"] + counts["deleted"]


def _rehearsal(document: JsonValue, ctx: StepContext) -> JsonValue:
    """The document a dry run sends: the same one, without the completeness claim.

    DHIS2 2.41 and 2.42 store the complete-data-set registration a ``completeDate`` asks for
    even under ``dryRun=true``, so a rehearsal carrying one is not a rehearsal. The claim is
    left out and said so; a real import sends the document whole.
    """
    if not isinstance(document, dict) or "completeDate" not in document:
        return document
    ctx.log.warning(
        "completeDate left out of the dry run: DHIS2 2.41 and 2.42 register completeness under dryRun",
        complete_date=str(document["completeDate"]),
    )
    return {key: value for key, value in document.items() if key != "completeDate"}


class Dhis2DataValueSetImportOperator(Dhis2Operator[Dhis2DataValueSetImportConfig, Dhis2DataValueSetImportOutput]):
    """Sends one data value set and fails the step when the instance did not take it."""

    spec = OperatorSpec(
        id="dhis2.data_value_set_import",
        summary="Import a data value set into DHIS2.",
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetImportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetImportOutput

    async def execute(
        self, config: Dhis2DataValueSetImportConfig, ctx: StepContext
    ) -> Dhis2DataValueSetImportOutput | RemoteHandle:
        """Send the document and turn the summary into an output, or into a classified refusal."""
        document = _rehearsal(config.data_values, ctx) if config.dry_run else config.data_values
        payload = json.dumps(document).encode()
        async with client_for(ctx, config.connection) as client:
            try:
                envelope = await client.data_values.stream(
                    payload,
                    import_strategy=config.import_strategy,
                    atomic_mode=config.atomic_mode,
                    dry_run=config.dry_run,
                )
            except Dhis2ApiError as error:
                refused = _summary_in(error)
                if refused is None:
                    raise refuse(error, f"POST {DATA_VALUE_SETS_PATH}") from error
                envelope = refused
            except AuthenticationError as error:
                raise refuse(error, f"POST {DATA_VALUE_SETS_PATH}") from error
        if not _has_summary(envelope):
            raise BlockFailure(IMPORT_NO_SUMMARY, error_class=ErrorClass.REJECTED, where=f"POST {DATA_VALUE_SETS_PATH}")
        status = _status(envelope)
        counts = _counts(envelope)
        conflicts = _conflicts(envelope)
        ctx.log.info("import summary", status=status, **counts, conflict_count=len(conflicts))
        if "ERROR" in (status, _outer_status(envelope)):
            raise BlockFailure(
                IMPORT_REFUSED, error_class=ErrorClass.REJECTED, detail=_detail(conflicts, counts), **counts
            )
        if status not in STANDING_STATUSES:
            raise BlockFailure(
                IMPORT_UNKNOWN_STATUS,
                error_class=ErrorClass.REJECTED,
                where=f"POST {DATA_VALUE_SETS_PATH}",
                status=status,
            )
        if status == "WARNING" and counts["ignored"] > 0 and config.atomic_mode == "ALL":
            # DHIS2 commits the good values beside the conflicts under atomicMode=ALL on every
            # supported major, so the refusal names how many landed.
            taken = _taken(counts)
            raise BlockFailure(
                IMPORT_PARTIAL if taken else IMPORT_TOOK_NOTHING,
                error_class=ErrorClass.REJECTED,
                detail=_detail(conflicts, counts),
                taken=taken,
                **counts,
            )
        return Dhis2DataValueSetImportOutput(status=status, conflicts=conflicts, **counts)
