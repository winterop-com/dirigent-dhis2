"""``dhis2.data_value_set_export``: read data values out of the instance as one data value set."""

import time
from datetime import timedelta
from typing import Any, ClassVar, Final, Literal, cast

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue, model_validator

from dirigent_common import BlockModel, Duration
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.messages import (
    EXPORT_EMPTY_ANSWER,
    EXPORT_FORMAT_UNSUPPORTED,
    EXPORT_HALF_RANGE,
    EXPORT_NO_DATA,
    EXPORT_NO_ORG_UNIT,
    EXPORT_NO_PERIOD,
)
from dirigent_dhis2.reads import require_known
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import (
    BlockFailure,
    ByteSink,
    ConnectionRef,
    ErrorClass,
    OperatorSpec,
    RemoteHandle,
    StepContext,
)

#: Where data value sets are read and written.
DATA_VALUE_SETS_PATH: Final = "/api/dataValueSets.json"

#: The document-level org unit, which an import applies to every value over the value's own.
DOCUMENT_ORG_UNIT: Final = "orgUnit"

#: The fields DHIS2 2.43 writes once on the set when every value shares them, and 2.42 on every value.
SHARED_FIELDS: Final = ("period", DOCUMENT_ORG_UNIT, "attributeOptionCombo")


#: How DHIS2 writes an identifier: by uid, code, name or database id, or by an attribute's value.
ID_SCHEME_PATTERN: Final = r"^(UID|CODE|NAME|ID|ATTRIBUTE:[A-Za-z][A-Za-z0-9]{10})$"

#: One identifier, or several, written as one string or a list.
Uids = str | list[str] | None

#: The forms a data value set is written in on the wire.
DataValueSetFormat = Literal["json", "csv", "xml", "adx"]

#: The media type each form is sent and asked for as.
CONTENT_TYPES: Final[dict[str, str]] = {
    "json": "application/json",
    "csv": "application/csv",
    "xml": "application/xml",
    "adx": "application/adx+xml",
}

#: The first DHIS2 minor whose export answers JSON when asked for ADX.
NO_ADX_EXPORT_FROM: Final = 43

#: Where a data value set is exported in a form other than JSON. ADX has no extension of its
#: own and is asked for by ``Accept``.
TEXT_EXPORT_PATHS: Final[dict[str, str]] = {
    "csv": "/api/dataValueSets.csv",
    "xml": "/api/dataValueSets.xml",
    "adx": "/api/dataValueSets",
}


class Dhis2DataValueSetExportConfig(BlockModel):
    """Which data values to read: what, where and when, each named once or several times.

    DHIS2 needs at least one selector of each: a data set, data element or data element group;
    an org unit or org unit group; and a period, a date range, or a last-updated bound.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    data_set: Uids = None
    """The uid of a data set to export, or a list of them."""

    data_element: Uids = None
    """The uid of a data element to export, or a list of them."""

    data_element_group: Uids = None
    """The uid of a data element group whose members are exported, or a list of them."""

    period: Uids = None
    """An ISO period identifier such as 2026Q1, or a list of them."""

    start_date: str | None = None
    """The ISO start of a date range read in place of periods, taken with ``end_date``."""

    end_date: str | None = None
    """The ISO end of a date range read in place of periods, taken with ``start_date``."""

    last_updated: str | None = None
    """Read only values changed at or after this ISO date or instant, for an incremental sync."""

    last_updated_duration: Duration | None = None
    """Read only values changed within this long before now, such as ``1d`` or ``2h``."""

    org_unit: Uids = None
    """The uid of an organisation unit to export for, or a list of them."""

    org_unit_group: Uids = None
    """The uid of an organisation unit group whose members are exported for, or a list of them."""

    children: bool = False
    """Whether the org units' descendants are included. The exported document then carries no
    document-level `orgUnit`, and each value keeps its own."""

    include_deleted: bool = False
    """Whether values deleted on the instance are exported too, each marked ``deleted``."""

    id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How every identifier in the document is written: ``UID``, ``CODE``, ``NAME``, ``ID`` or
    ``ATTRIBUTE:<uid>``; the instance's own default, UID, when unset."""

    data_element_id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How data elements are written, in place of ``id_scheme``."""

    org_unit_id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How org units are written, in place of ``id_scheme``."""

    category_option_combo_id_scheme: str | None = Field(default=None, pattern=ID_SCHEME_PATTERN)
    """How category option combos are written, in place of ``id_scheme``."""

    format: DataValueSetFormat = "json"
    """The form the set is exported in: ``json``, parsed into ``body``; or ``csv``, ``xml`` or
    ``adx``, written whole to storage at ``uri`` with its head inlined as ``text``. ADX is
    exported by 2.41 and 2.42 only."""

    require_known: bool = True
    """Whether the step fails when a named data set, data element, group or org unit is unknown
    to the instance, rather than answering an empty set for it. One metadata lookup asks for
    every named uid before the export."""

    @model_validator(mode="after")
    def _names_what_where_and_when(self) -> "Dhis2DataValueSetExportConfig":
        """Refuse an export DHIS2 would refuse: one missing what, where or when, or half a range."""
        if not (self.data_set or self.data_element or self.data_element_group):
            raise ValueError(EXPORT_NO_DATA.render())
        if not (self.org_unit or self.org_unit_group):
            raise ValueError(EXPORT_NO_ORG_UNIT.render())
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError(EXPORT_HALF_RANGE.render())
        if not (self.period or self.start_date or self.last_updated or self.last_updated_duration):
            raise ValueError(EXPORT_NO_PERIOD.render())
        return self


class Dhis2DataValueSetExportOutput(BlockModel):
    """The data value set the export answered, which an import takes as it is."""

    format: DataValueSetFormat = "json"
    """The form the set was exported in."""

    body: JsonValue | None = None
    """The exported data value set, for ``json``: the document a ``dhis2.data_value_set_import``
    takes whole as its ``data_values``. Every value carries its own period, org unit and
    attribute option combo, whichever version answered. Null for every other form."""

    text: str | None = None
    """The head of the exported text, for ``csv``, ``xml`` and ``adx``, cut at the instance's
    inline capture size; null for ``json``."""

    uri: str | None = None
    """Where the whole exported text was written, for ``csv``, ``xml`` and ``adx``; never cut,
    and what an import's ``data_values_uri`` takes. Null for ``json``."""

    content_bytes: int | None = None
    """How large the exported text is, inlined or not; null for ``json``."""

    truncated: bool = False
    """Whether ``text`` is short of the export. Only the inline copy is ever cut."""

    duration_ms: int
    """How long the export took."""


def _complete_values(body: dict[str, Any]) -> None:
    """Give every value the shared fields the set carries for it, so a value reads the same from 2.42 and 2.43.

    A value's own field is never replaced: only one the set holds and the value lacks is copied
    down, which is exactly what DHIS2 means by writing it on the set.
    """
    shared = {field: body[field] for field in SHARED_FIELDS if isinstance(body.get(field), str)}
    values: list[Any] = body.get("dataValues") or []
    for value in values if shared else []:
        if isinstance(value, dict):
            for field, held in shared.items():
                cast("dict[str, Any]", value).setdefault(field, held)


def _listed(uids: Uids) -> list[str]:
    """Spread one identifier or several into the list DHIS2 repeats a parameter for."""
    if uids is None:
        return []
    return [uids] if isinstance(uids, str) else list(uids)


def dhis2_duration(duration: timedelta) -> str:
    """Write a duration the way ``lastUpdatedDuration`` reads one: whole days, hours, minutes or seconds."""
    seconds = max(round(duration.total_seconds()), 1)
    for unit, length in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % length == 0:
            return f"{seconds // length}{unit}"
    return f"{seconds}s"


def _extra_params(config: Dhis2DataValueSetExportConfig) -> dict[str, Any]:
    """The query terms the client takes no argument for, in DHIS2's own names."""
    params: dict[str, Any] = {}
    for name, uids in (
        ("dataElement", config.data_element),
        ("dataElementGroup", config.data_element_group),
        ("orgUnitGroup", config.org_unit_group),
    ):
        if listed := _listed(uids):
            params[name] = listed
    if config.include_deleted:
        params["includeDeleted"] = "true"
    for name, scheme in (
        ("idScheme", config.id_scheme),
        ("dataElementIdScheme", config.data_element_id_scheme),
        ("orgUnitIdScheme", config.org_unit_id_scheme),
        ("categoryOptionComboIdScheme", config.category_option_combo_id_scheme),
    ):
        if scheme is not None:
            params[name] = scheme
    return params


def export_params(config: Dhis2DataValueSetExportConfig) -> dict[str, Any]:
    """The whole query an export sends, in DHIS2's own names."""
    params: dict[str, Any] = {}
    for name, uids in (("dataSet", config.data_set), ("period", config.period), ("orgUnit", config.org_unit)):
        if listed := _listed(uids):
            params[name] = listed
    if config.children:
        params["children"] = "true"
    for name, value in (
        ("startDate", config.start_date),
        ("endDate", config.end_date),
        ("lastUpdated", config.last_updated),
    ):
        if value is not None:
            params[name] = value
    if config.last_updated_duration is not None:
        params["lastUpdatedDuration"] = dhis2_duration(config.last_updated_duration)
    return {**params, **_extra_params(config)}


def _minor(client: Dhis2Client) -> int:
    """The DHIS2 minor the client speaks, 42 for 2.42."""
    return int(client.version_key.removeprefix("v"))


class _Head:
    """The write end an export streams into: storage gets every byte, the head is kept to inline."""

    def __init__(self, sink: ByteSink, limit: int) -> None:
        """Write through to the sink, keeping at most this much of the beginning."""
        self._sink = sink
        self._limit = limit
        self.head = bytearray()
        self.total = 0

    async def write(self, chunk: bytes) -> None:
        """Take one piece of the body."""
        if len(self.head) < self._limit:
            self.head.extend(chunk[: self._limit - len(self.head)])
        self.total += len(chunk)
        await self._sink.write(chunk)


async def _export_text(
    client: Dhis2Client, config: Dhis2DataValueSetExportConfig, ctx: StepContext
) -> Dhis2DataValueSetExportOutput:
    """Stream a CSV, XML or ADX export into storage, keeping its head to inline."""
    if config.format == "adx" and _minor(client) >= NO_ADX_EXPORT_FROM:
        raise BlockFailure(
            EXPORT_FORMAT_UNSUPPORTED, error_class=ErrorClass.REJECTED, version=client.raw_version, format="adx"
        )
    path = TEXT_EXPORT_PATHS[config.format]
    content_type = CONTENT_TYPES[config.format]
    async with ctx.capture(f"data-value-set.{config.format}", content_type=content_type) as sink:
        written = _Head(sink, ctx.inline_capture)
        try:
            await client.stream(
                "GET", path, written.write, params=export_params(config), extra_headers={"Accept": content_type}
            )
        except (Dhis2ApiError, AuthenticationError) as error:
            raise refuse(error, f"GET {path}") from error
    if not written.total:
        raise _scope_refusal(config)
    if config.format == "adx" and bytes(written.head).lstrip().startswith(b"{"):
        raise BlockFailure(
            EXPORT_FORMAT_UNSUPPORTED, error_class=ErrorClass.REJECTED, version=client.raw_version, format="adx"
        )
    return Dhis2DataValueSetExportOutput(
        format=config.format,
        text=bytes(written.head).decode("utf-8", errors="replace"),
        uri=sink.uri,
        content_bytes=written.total,
        truncated=written.total > len(written.head),
        duration_ms=0,
    )


def _empty_answer(error: Dhis2ApiError) -> bool:
    """Say whether the client refused a successful read for answering with no body at all."""
    return 200 <= error.status_code < 300 and error.body is None


def _scope_refusal(config: Dhis2DataValueSetExportConfig) -> BlockFailure:
    """The refusal for an export DHIS2 answered with nothing, as it does outside the account's data scope."""
    return BlockFailure(
        EXPORT_EMPTY_ANSWER,
        error_class=ErrorClass.REJECTED,
        where=f"GET {DATA_VALUE_SETS_PATH}",
        org_unit=", ".join(_listed(config.org_unit) + _listed(config.org_unit_group)),
    )


def _one_data_set(config: Dhis2DataValueSetExportConfig) -> bool:
    """Whether the export asks for exactly one data set and nothing else.

    DHIS2 answers such a read with the data set named or with a ``dataValues`` list, empty or
    not; an answer carrying neither is refused as the empty answer.
    """
    return len(_listed(config.data_set)) == 1 and not (config.data_element or config.data_element_group)


class Dhis2DataValueSetExportOperator(Dhis2Operator[Dhis2DataValueSetExportConfig, Dhis2DataValueSetExportOutput]):
    """Reads the data values a selection names and hands the parsed document on."""

    spec = OperatorSpec(
        id="dhis2.data_value_set_export",
        summary="Export a DHIS2 data value set as JSON, CSV, XML or ADX.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetExportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetExportOutput

    async def execute(
        self, config: Dhis2DataValueSetExportConfig, ctx: StepContext
    ) -> Dhis2DataValueSetExportOutput | RemoteHandle:
        """Check the named uids exist, read the set once, and answer with the document."""
        started = time.monotonic()
        async with client_for(ctx, config.connection) as client:
            if config.require_known:
                await require_known(
                    client,
                    {
                        "dataSets": config.data_set,
                        "dataElements": config.data_element,
                        "dataElementGroups": config.data_element_group,
                        "organisationUnits": config.org_unit,
                        "organisationUnitGroups": config.org_unit_group,
                    },
                    f"GET {DATA_VALUE_SETS_PATH}",
                )
            if config.format != "json":
                exported_text = await _export_text(client, config, ctx)
                elapsed = round((time.monotonic() - started) * 1000)
                ctx.log.info(
                    "data value set exported",
                    format=config.format,
                    content_bytes=exported_text.content_bytes,
                    duration_ms=elapsed,
                )
                return exported_text.model_copy(update={"duration_ms": elapsed})
            duration = config.last_updated_duration
            try:
                exported = await client.data_values.export(
                    data_set=_listed(config.data_set) or None,
                    period=_listed(config.period) or None,
                    org_unit=_listed(config.org_unit) or None,
                    children=config.children,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    last_updated=config.last_updated,
                    last_updated_duration=None if duration is None else dhis2_duration(duration),
                    extra_params=_extra_params(config),
                )
            except Dhis2ApiError as error:
                if _empty_answer(error):
                    raise _scope_refusal(config) from error
                raise refuse(error, f"GET {DATA_VALUE_SETS_PATH}") from error
            except AuthenticationError as error:
                raise refuse(error, f"GET {DATA_VALUE_SETS_PATH}") from error
        body = exported.model_dump(mode="json", by_alias=True, exclude_none=True)
        if _one_data_set(config) and not body.get("dataSet") and "dataValues" not in body:
            raise _scope_refusal(config)
        if config.children:
            body.pop(DOCUMENT_ORG_UNIT, None)
        _complete_values(body)
        elapsed = round((time.monotonic() - started) * 1000)
        values: list[Any] = body.get("dataValues") or []
        ctx.log.info("data value set exported", values=len(values), duration_ms=elapsed)
        return Dhis2DataValueSetExportOutput(body=body, duration_ms=elapsed)
