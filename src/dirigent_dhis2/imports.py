"""``dhis2.data_value_set_import``: write data values into the instance, reading its summary honestly."""

import json
from typing import ClassVar, Literal

from dhis2w_client import WebMessageResponse
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.export import DATA_VALUE_SETS_PATH
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ErrorClass, OperatorSpec, RemoteHandle, StepContext

#: How many conflicts a refusal names before pointing at the rest.
NAMED_CONFLICTS = 3

#: What the import may do to values already there.
ImportStrategy = Literal["CREATE", "UPDATE", "CREATE_AND_UPDATE", "DELETE"]

#: Whether one refused value refuses the whole import.
AtomicMode = Literal["ALL", "NONE"]


class Dhis2ImportConflict(BlockModel):
    """One value the import refused, in the instance's own words."""

    object: str = ""
    value: str = ""


class Dhis2DataValueSetImportConfig(BlockModel):
    """What one import sends, and how the instance is told to take it."""

    connection: str
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
    """The summary's own word: SUCCESS, WARNING, or ERROR."""

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
    """Whether the envelope carries an import summary: a typed count or the summary's own type."""
    summary = envelope.response or {}
    return summary.get("responseType") == "ImportSummary" or envelope.import_count() is not None


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


def _status(envelope: WebMessageResponse) -> str:
    """Read the summary's status, falling back to the envelope's own when the summary has none."""
    inner = (envelope.response or {}).get("status")
    if inner:
        return str(inner)
    outer = envelope.status
    return str(getattr(outer, "value", outer) or "")


def _counts(envelope: WebMessageResponse) -> dict[str, int]:
    """Read the summary's counts off the typed envelope, defaulting what a version left out."""
    counted = envelope.import_count()
    read: dict[str, int] = {}
    for name in ("imported", "updated", "ignored", "deleted"):
        value = getattr(counted, name, None) if counted is not None else None
        read[name] = value if isinstance(value, int) else 0
    return read


def _conflicts(envelope: WebMessageResponse) -> list[Dhis2ImportConflict]:
    """Read the summary's conflicts off the typed envelope, empty when the import was clean."""
    return [Dhis2ImportConflict(object=item.object or "", value=item.value or "") for item in envelope.conflicts()]


def _refusal(conflicts: list[Dhis2ImportConflict], counts: dict[str, int]) -> str:
    """Say what the instance refused, naming the first conflicts and the counts."""
    named = "; ".join(f"{conflict.object}: {conflict.value}" for conflict in conflicts[:NAMED_CONFLICTS])
    more = len(conflicts) - NAMED_CONFLICTS
    tail = f" (and {more} more)" if more > 0 else ""
    return f"{named}{tail}" if named else f"{counts['ignored']} values ignored"


def _taken(counts: dict[str, int]) -> int:
    """How many values the summary says landed: imported, updated or deleted."""
    return counts["imported"] + counts["updated"] + counts["deleted"]


def _partial(conflicts: list[Dhis2ImportConflict], counts: dict[str, int]) -> str:
    """Say what an import asked to be atomic did, honestly: what it took and what it refused.

    DHIS2 commits the good values beside the conflicts under ``atomicMode=ALL`` on every
    supported major, so a WARNING under ALL is not the rollback the mode promises. The
    failure names the values that landed so the step's reader knows the instance changed.
    """
    taken = _taken(counts)
    if taken == 0:
        return f"the import took nothing: {_refusal(conflicts, counts)}"
    return (
        f"the import took {taken} values and refused {counts['ignored']} despite atomic_mode ALL: "
        f"{_refusal(conflicts, counts)}"
    )


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
            raise BlockFailure(
                f"POST {DATA_VALUE_SETS_PATH} answered without an import summary, so nothing says the import took",
                error_class=ErrorClass.REJECTED,
            )
        status = _status(envelope)
        counts = _counts(envelope)
        conflicts = _conflicts(envelope)
        ctx.log.info("import summary", status=status, **counts, conflict_count=len(conflicts))
        if status == "ERROR":
            raise BlockFailure(
                f"the import was refused: {_refusal(conflicts, counts)}",
                error_class=ErrorClass.REJECTED,
            )
        if status == "WARNING" and counts["ignored"] > 0 and config.atomic_mode == "ALL":
            raise BlockFailure(_partial(conflicts, counts), error_class=ErrorClass.REJECTED)
        return Dhis2DataValueSetImportOutput(status=status, conflicts=conflicts, **counts)
