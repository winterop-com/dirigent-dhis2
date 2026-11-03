"""``dhis2.data_value_set_import``: write data values into the instance, reading its summary honestly."""

import json
import re
from typing import ClassVar, Final, Literal

from dhis2w_client import Dhis2Client, WebMessageResponse
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.export import CONTENT_TYPES, ID_SCHEME_PATTERN, DataValueSetFormat
from dirigent_dhis2.messages import (
    IMPORT_CONFLICTS_AND_MORE,
    IMPORT_NO_DATA_VALUES,
    IMPORT_NO_SUMMARY,
    IMPORT_NO_VALUES_TAKEN,
    IMPORT_NOT_TEXT,
    IMPORT_PARTIAL,
    IMPORT_REFUSED,
    IMPORT_TOOK_NOTHING,
    IMPORT_TWO_SOURCES,
    IMPORT_UNKNOWN_STATUS,
    IMPORT_VALUES_IGNORED,
)
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, RemoteHandle, StepContext

#: Where data value sets are imported, in every form.
DATA_VALUE_SETS_PATH: Final = "/api/dataValueSets"

#: A ``completeDate`` attribute in an XML or ADX document, which a dry run leaves out.
COMPLETE_DATE_ATTRIBUTE: Final = re.compile(r"""\s+completeDate\s*=\s*("[^"]*"|'[^']*')""")

#: One value in an XML or ADX document.
XML_VALUE: Final = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?dataValue[\s/>]")

#: The id scheme ADX is written in, which 2.43 and later no longer assume.
ADX_ID_SCHEME: Final = "CODE"

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


class Dhis2ImportCounts(BlockModel):
    """What an import summary counted, by what happened to each value."""

    imported: int = 0
    """How many values were created."""

    updated: int = 0
    """How many values were revised."""

    ignored: int = 0
    """How many values the instance did not take."""

    deleted: int = 0
    """How many values were removed."""


class Dhis2DataValueSetImportConfig(BlockModel):
    """What one import sends, and how the instance is told to take it."""

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    data_values: JsonValue = None
    """The data value set to send, written in the step or referenced from one. For ``json`` an
    object with a ``dataValues`` list: an export's document is ``${steps.<step>.output.body}``,
    and a document with no ``dataValues`` list fails the step before anything is sent. For
    ``csv``, ``xml`` and ``adx`` the document's text, such as an export's
    ``${steps.<step>.output.text}`` when it was not truncated."""

    data_values_uri: str | None = None
    """A storage URI holding the document to send, read in place of ``data_values``: an export's
    ``${steps.<step>.output.uri}``, or a file a ``storage.write`` left."""

    format: DataValueSetFormat = "json"
    """The form the document is written in: ``json``, ``csv``, ``xml`` or ``adx``. DHIS2 2.41
    to 2.44 import all four."""

    id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How every identifier in the document is written: ``UID``, ``CODE``, ``NAME``, ``ID`` or
    ``ATTRIBUTE:<uid>``; UID when unset, except for ``adx``, which is sent as ``CODE`` unless
    this says otherwise."""

    data_element_id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How data elements are written, in place of ``id_scheme``."""

    org_unit_id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How org units are written, in place of ``id_scheme``."""

    category_option_combo_id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How category option combos are written, in place of ``id_scheme``."""

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

    require_values: bool = False
    """Whether the step fails when the instance took no value at all: none imported, updated or
    deleted. Off, an empty ``dataValues`` list is sent and answers zero counts."""

    @model_validator(mode="after")
    def _one_source(self) -> "Dhis2DataValueSetImportConfig":
        """Refuse a document named twice, inline and by URI."""
        if self.data_values_uri is not None and self.data_values is not None:
            raise ValueError(IMPORT_TWO_SOURCES.render())
        return self


class Dhis2DataValueSetImportOutput(BlockModel):
    """What the import sent, and what its summary counted."""

    status: str
    """The summary's own word: SUCCESS or WARNING."""

    sent: int
    """How many values the document held; zero says nothing was there to import."""

    counts: Dhis2ImportCounts
    """What happened to the values: imported, updated, ignored and deleted."""

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


def _values_in(document: JsonValue) -> int:
    """Count the values a document holds, refusing one that is not a data value set before it is sent."""
    if not isinstance(document, dict):
        if isinstance(document, list):
            found = "is a list"
        elif isinstance(document, str):
            found = "is a string"
        else:
            found = "is null" if document is None else "is not an object"
        raise BlockFailure(IMPORT_NO_DATA_VALUES, error_class=ErrorClass.REJECTED, found=found)
    values = document.get("dataValues")
    if isinstance(values, list):
        return len(values)
    if "dataValues" in document:
        found = "holds a dataValues that is not a list"
    else:
        keys = ", ".join(sorted(document)[:5]) or "nothing"
        found = f"holds no dataValues (its keys: {keys})"
    raise BlockFailure(IMPORT_NO_DATA_VALUES, error_class=ErrorClass.REJECTED, found=found)


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


def _text_values(document: str, form: str) -> int:
    """Count the values a CSV, XML or ADX document holds: its rows past the header, or its value elements."""
    if form == "csv":
        rows = [line for line in document.splitlines() if line.strip()]
        return max(len(rows) - 1, 0)
    return len(XML_VALUE.findall(document))


def _text_rehearsal(document: str, ctx: StepContext) -> str:
    """The XML or ADX a dry run sends: the same text, without a ``completeDate`` attribute."""
    rehearsed, left_out = COMPLETE_DATE_ATTRIBUTE.subn("", document)
    if left_out:
        ctx.log.warning(
            "completeDate left out of the dry run: DHIS2 2.41 and 2.42 register completeness under dryRun",
            left_out=left_out,
        )
    return rehearsed


async def _source(config: Dhis2DataValueSetImportConfig, ctx: StepContext) -> JsonValue:
    """The document the import sends: inline, or read whole from storage and parsed when it is JSON."""
    if config.data_values_uri is None:
        return config.data_values
    held = bytearray()
    async for chunk in ctx.storage.open_read(config.data_values_uri):
        held.extend(chunk)
    text = bytes(held).decode("utf-8")
    if config.format != "json":
        return text
    try:
        parsed: JsonValue = json.loads(text)
    except ValueError:
        return text
    return parsed


def _payload(document: JsonValue, config: Dhis2DataValueSetImportConfig, ctx: StepContext) -> tuple[bytes, int]:
    """The bytes the import sends and how many values they hold, refusing a document of the wrong kind."""
    if config.format == "json":
        sent = _values_in(document)
        sent_document = _rehearsal(document, ctx) if config.dry_run else document
        return json.dumps(sent_document).encode(), sent
    if not isinstance(document, str):
        found = "an object" if isinstance(document, dict) else "a list" if isinstance(document, list) else "not text"
        raise BlockFailure(IMPORT_NOT_TEXT, error_class=ErrorClass.REJECTED, format=config.format, found=found)
    if config.dry_run and config.format != "csv":
        document = _text_rehearsal(document, ctx)
    return document.encode(), _text_values(document, config.format)


def import_params(config: Dhis2DataValueSetImportConfig) -> dict[str, str]:
    """The query an import sends: the strategy, the atomic mode, the dry run and the id schemes."""
    params: dict[str, str] = {"importStrategy": config.import_strategy, "atomicMode": config.atomic_mode}
    if config.dry_run:
        params["dryRun"] = "true"
    id_scheme = config.id_scheme or (ADX_ID_SCHEME if config.format == "adx" else None)
    for name, scheme in (
        ("idScheme", id_scheme),
        ("dataElementIdScheme", config.data_element_id_scheme),
        ("orgUnitIdScheme", config.org_unit_id_scheme),
        ("categoryOptionComboIdScheme", config.category_option_combo_id_scheme),
    ):
        if scheme is not None:
            params[name] = scheme
    return params


async def _send(client: Dhis2Client, payload: bytes, config: Dhis2DataValueSetImportConfig) -> WebMessageResponse:
    """Post the document in its own media type and read the envelope DHIS2 answers with.

    The client's data value stream takes no ``categoryOptionComboIdScheme``, so the request is
    made through the client's own dispatch, which still applies its auth, pool and limits.
    """
    response = await client._request(  # pyright: ignore[reportPrivateUsage]
        "POST",
        DATA_VALUE_SETS_PATH,
        params=import_params(config),
        content=payload,
        extra_headers={"Content-Type": CONTENT_TYPES[config.format], "Accept": "application/json"},
    )
    return WebMessageResponse.model_validate(response.json() if response.content.strip() else {})


class Dhis2DataValueSetImportOperator(Dhis2Operator[Dhis2DataValueSetImportConfig, Dhis2DataValueSetImportOutput]):
    """Sends one data value set and fails the step when the instance did not take it."""

    spec = OperatorSpec(
        id="dhis2.data_value_set_import",
        summary="Import a data value set into DHIS2, as JSON, CSV, XML or ADX.",
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetImportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetImportOutput

    async def execute(
        self, config: Dhis2DataValueSetImportConfig, ctx: StepContext
    ) -> Dhis2DataValueSetImportOutput | RemoteHandle:
        """Send the document and turn the summary into an output, or into a classified refusal."""
        payload, sent = _payload(await _source(config, ctx), config, ctx)
        if not sent:
            ctx.log.warning("the document holds no data values, so the import has none to take")
        async with client_for(ctx, config.connection) as client:
            try:
                envelope = await _send(client, payload, config)
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
        if config.require_values and not _taken(counts):
            raise BlockFailure(
                IMPORT_NO_VALUES_TAKEN,
                error_class=ErrorClass.REJECTED,
                sent=sent,
                detail=_detail(conflicts, counts),
                **counts,
            )
        return Dhis2DataValueSetImportOutput(
            status=status, sent=sent, counts=Dhis2ImportCounts(**counts), conflicts=conflicts
        )
