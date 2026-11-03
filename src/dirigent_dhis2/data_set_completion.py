"""``dhis2.data_set_completion``: mark a data set complete, or reopen it, for one period and org unit."""

from typing import Annotated, Any, ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.messages import COMPLETION_REFUSED, IMPORT_NO_SUMMARY, IMPORT_VALUES_IGNORED
from dirigent_dhis2.reports import as_list, as_object, body_of, count, import_summary, named_first, text
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: Where completion registrations are written, on every supported version.
REGISTRATIONS_PATH: Final = "/api/completeDataSetRegistrations"

#: One metadata object, named by its DHIS2 uid.
Uid = Annotated[str, Field(pattern=UID_PATTERN)]


class Dhis2DataSetCompletionConfig(BlockModel):
    """Which data set window the step signs off, or reopens.

    One completion registration, posted to ``/api/completeDataSetRegistrations``: the record that
    a data set's period at an organisation unit is finished, which completeness reporting rates
    count and ``dhis2.data_set_complete`` waits for. ``completed: false`` reopens the window.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    data_set: Uid
    """The uid of the data set."""

    period: str = Field(min_length=1)
    """An ISO period identifier, such as 202607 or 2026Q1."""

    org_unit: Uid
    """The uid of the organisation unit."""

    attribute_option_combo: Uid | None = None
    """The uid of the attribute option combo, for a data set with an attribute category combo;
    the default combo when unset."""

    completed: bool = True
    """Whether the window is marked complete; false reopens it."""

    dry_run: bool = False
    """Whether the instance validates the registration without writing anything."""


class Dhis2CompletionConflict(BlockModel):
    """One refusal the summary names, in the instance's own words."""

    object: str = ""
    """What the instance named as refused."""

    value: str = ""
    """Why, in the instance's own words."""

    error_code: str | None = None
    """The instance's code for the refusal."""

    indexes: list[int] = Field(default_factory=list[int])
    """Where the refused registrations sit in the document that was sent, counted from zero."""


class Dhis2DataSetCompletionOutput(BlockModel):
    """What the registration's import summary said."""

    status: str
    """The summary's own word: SUCCESS or WARNING."""

    completed: bool
    """Whether the window was marked complete, or reopened."""

    dry_run: bool
    """Whether this was a validation only, with nothing written."""

    imported: int
    """How many registrations were created."""

    updated: int
    """How many registrations were revised."""

    ignored: int
    """How many registrations the instance did not take."""

    deleted: int
    """How many registrations were removed."""

    conflicts: list[Dhis2CompletionConflict]
    """Every refusal the summary names, empty when the registration was taken."""


def registration(config: Dhis2DataSetCompletionConfig) -> dict[str, Any]:
    """The registrations document the step sends: one entry, for the one window."""
    entry: dict[str, Any] = {
        "dataSet": config.data_set,
        "period": config.period,
        "organisationUnit": config.org_unit,
        "completed": config.completed,
    }
    if config.attribute_option_combo is not None:
        entry["attributeOptionCombo"] = config.attribute_option_combo
    return {"completeDataSetRegistrations": [entry]}


def _conflicts(summary: dict[str, Any]) -> list[Dhis2CompletionConflict]:
    """The summary's conflicts."""
    return [
        Dhis2CompletionConflict(
            object=text(conflict.get("object")) or "",
            value=text(conflict.get("value")) or "",
            error_code=text(conflict.get("errorCode")),
            indexes=[index for index in as_list(conflict.get("indexes")) if isinstance(index, int)],
        )
        for conflict in map(as_object, as_list(summary.get("conflicts")))
        if conflict is not None
    ]


class Dhis2DataSetCompletionOperator(Dhis2Operator[Dhis2DataSetCompletionConfig, Dhis2DataSetCompletionOutput]):
    """Posts one completion registration and fails the step when the instance did not take it."""

    spec = OperatorSpec(
        id="dhis2.data_set_completion",
        summary="Mark a DHIS2 data set complete, or reopen it, for a period and org unit.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataSetCompletionConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataSetCompletionOutput

    async def execute(self, config: Dhis2DataSetCompletionConfig, ctx: StepContext) -> Dhis2DataSetCompletionOutput:
        """Send the registration and read the summary as the instance's verdict on it."""
        where = f"POST {REGISTRATIONS_PATH}"
        params = {"dryRun": "true" if config.dry_run else "false"}
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.post_raw(REGISTRATIONS_PATH, registration(config), params=params)
            except Dhis2ApiError as error:
                refused = body_of(error)
                if refused is None or import_summary(refused) is None:
                    raise refuse(error, where) from error
                body = refused
            except AuthenticationError as error:
                raise refuse(error, where) from error
        summary = import_summary(body)
        if summary is None:
            raise BlockFailure(IMPORT_NO_SUMMARY, error_class=ErrorClass.REJECTED, where=where)
        status = str(summary.get("status") or body.get("status") or "")
        counted = as_object(summary.get("importCount"))
        counts = {name: count(counted, name) for name in ("imported", "updated", "ignored", "deleted")}
        conflicts = _conflicts(summary)
        ctx.log.info("completion registration", status=status, completed=config.completed, **counts)
        if status == "ERROR" or counts["ignored"]:
            named = [f"{conflict.object or config.data_set}: {conflict.value}" for conflict in conflicts]
            detail = named_first(named) or IMPORT_VALUES_IGNORED.render(ignored=counts["ignored"])
            raise BlockFailure(COMPLETION_REFUSED, error_class=ErrorClass.REJECTED, detail=detail, **counts)
        return Dhis2DataSetCompletionOutput(
            status=status, completed=config.completed, dry_run=config.dry_run, conflicts=conflicts, **counts
        )
