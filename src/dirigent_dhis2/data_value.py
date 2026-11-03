"""``dhis2.data_value``: read, set or delete one aggregate data value through ``/api/dataValues``."""

from typing import Annotated, Any, ClassVar, Final, Literal

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field

from dirigent_common import BlockModel, Issue, Message
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.messages import (
    DATA_VALUE_HALF_ATTRIBUTE,
    DATA_VALUE_NO_VALUE,
    DATA_VALUE_REFUSED,
    DATA_VALUE_UNKNOWN_ATTRIBUTE,
    IMPORT_NO_SUMMARY,
    IMPORT_VALUES_IGNORED,
)
from dirigent_dhis2.reports import as_list, as_object, body_of, count, import_summary, named_first, text
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: Where one data value is read, set and deleted.
DATA_VALUES_PATH: Final = "/api/dataValues"

#: Where a dry run is rehearsed: ``/api/dataValues`` takes ``dryRun`` and writes anyway.
DATA_VALUE_SETS_PATH: Final = "/api/dataValueSets"

#: The statuses an answer to a read of a value that is not there carries: 2.42 says 409, later 404.
ABSENT_STATUSES: Final = (404, 409)

#: What 2.42 says, beside its 409, for a value that is not there.
ABSENT_MESSAGE: Final = "does not exist"

#: One metadata object, named by its DHIS2 uid.
Uid = Annotated[str, Field(pattern=UID_PATTERN)]

#: What the step does to the value.
DataValueAction = Literal["get", "set", "delete"]


class Dhis2DataValueConfig(BlockModel):
    """Which data value the step addresses, and what it does to it.

    One cell: a data element, a period and an organisation unit, narrowed by a category option
    combo, and by an attribute option combo named the way ``/api/dataValues`` names one, as its
    attribute category combo and options. A whole data value set is
    ``dhis2.data_value_set_import`` and ``dhis2.data_value_set_export`` instead.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    action: DataValueAction = "get"
    """What the step does: ``get`` reads the value, ``set`` writes ``value``, ``delete`` removes it."""

    data_element: Uid
    """The uid of the data element."""

    period: str = Field(min_length=1)
    """An ISO period identifier, such as 202607 or 2026Q1."""

    org_unit: Uid
    """The uid of the organisation unit."""

    category_option_combo: Uid | None = None
    """The uid of the category option combo, the disaggregation; the default combo when unset."""

    attribute_combo: Uid | None = None
    """The uid of the attribute category combo, given together with ``attribute_options``; the
    default attribute option combo when both are unset."""

    attribute_options: list[Uid] = []
    """The uids of the attribute category options that, with ``attribute_combo``, name the
    attribute option combo."""

    value: str | None = None
    """The value to write, always a string on the wire whatever the value type; ``set`` needs one."""

    comment: str | None = None
    """A comment to store with the value, for ``set``."""

    dry_run: bool = False
    """Whether a ``set`` or ``delete`` is only validated, with nothing written. It is sent as a
    one-value ``/api/dataValueSets`` import with ``dryRun=true``, because ``/api/dataValues``
    accepts ``dryRun`` and writes the value anyway."""


class Dhis2DataValueOutput(BlockModel):
    """The value the step read, wrote or removed, and the cell it sits in."""

    action: DataValueAction
    """What the step did."""

    data_element: str
    """The uid of the data element."""

    period: str
    """The ISO period."""

    org_unit: str
    """The uid of the organisation unit."""

    category_option_combo: str | None = None
    """The uid of the category option combo, when one was named."""

    attribute_option_combo: str | None = None
    """The uid of the attribute option combo a dry run resolved, when one was named."""

    value: str | None = None
    """The value read or written; null when a read found none, and for a delete."""

    found: bool
    """Whether the value exists: for ``get`` whether one is stored, otherwise whether the write
    was taken."""

    dry_run: bool
    """Whether this was a validation only, with nothing written."""


def _refusals(config: Dhis2DataValueConfig) -> list[Message]:
    """What the config asks for that the endpoint cannot do."""
    refusals: list[Message] = []
    if config.action == "set" and config.value is None:
        refusals.append(DATA_VALUE_NO_VALUE)
    if (config.attribute_combo is None) != (not config.attribute_options):
        refusals.append(DATA_VALUE_HALF_ATTRIBUTE)
    return refusals


def address(config: Dhis2DataValueConfig) -> dict[str, str]:
    """The query naming the cell the way ``/api/dataValues`` reads it, ``de`` through ``cp``."""
    params = {"de": config.data_element, "pe": config.period, "ou": config.org_unit}
    if config.category_option_combo is not None:
        params["co"] = config.category_option_combo
    if config.attribute_combo is not None:
        params["cc"] = config.attribute_combo
        params["cp"] = ";".join(config.attribute_options)
    return params


def _absent(error: Dhis2ApiError) -> bool:
    """Whether a refused read is the instance saying there is no such value."""
    if error.status_code == 404:
        return True
    envelope = body_of(error) or {}
    said = str(envelope.get("message") or error.message or "")
    return error.status_code in ABSENT_STATUSES and ABSENT_MESSAGE in said


async def _attribute_option_combo(client: Dhis2Client, config: Dhis2DataValueConfig) -> str | None:
    """Resolve the attribute combo and options into the option combo uid a data value set names."""
    if config.attribute_combo is None:
        return None
    path = f"/api/categoryCombos/{config.attribute_combo}"
    try:
        body = await client.get_raw(path, params={"fields": "categoryOptionCombos[id,categoryOptions[id]]"})
    except (Dhis2ApiError, AuthenticationError) as error:
        raise refuse(error, f"GET {path}") from error
    wanted = set(config.attribute_options)
    for combo in map(as_object, as_list(body.get("categoryOptionCombos"))):
        if combo is None:
            continue
        options = {text(option.get("id")) for option in map(as_object, as_list(combo.get("categoryOptions"))) if option}
        if options == wanted and text(combo.get("id")):
            return text(combo.get("id"))
    raise BlockFailure(
        DATA_VALUE_UNKNOWN_ATTRIBUTE,
        error_class=ErrorClass.REJECTED,
        combo=config.attribute_combo,
        options=", ".join(config.attribute_options),
    )


def _rehearsal(config: Dhis2DataValueConfig, attribute_option_combo: str | None) -> dict[str, Any]:
    """The one-value data value set a dry run sends in place of the write."""
    row: dict[str, Any] = {"dataElement": config.data_element, "period": config.period, "orgUnit": config.org_unit}
    if config.category_option_combo is not None:
        row["categoryOptionCombo"] = config.category_option_combo
    if attribute_option_combo is not None:
        row["attributeOptionCombo"] = attribute_option_combo
    if config.action == "set":
        row["value"] = config.value
        if config.comment is not None:
            row["comment"] = config.comment
    return {"dataValues": [row]}


async def _rehearse(client: Dhis2Client, config: Dhis2DataValueConfig) -> str | None:
    """Validate the write as a one-value import with ``dryRun=true``, refusing what the instance would refuse."""
    where = f"POST {DATA_VALUE_SETS_PATH}"
    attribute_option_combo = await _attribute_option_combo(client, config)
    params = {"dryRun": "true", "importStrategy": "DELETE" if config.action == "delete" else "CREATE_AND_UPDATE"}
    try:
        body = await client.post_raw(DATA_VALUE_SETS_PATH, _rehearsal(config, attribute_option_combo), params=params)
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
    counts = as_object(summary.get("importCount"))
    ignored = count(counts, "ignored")
    if str(summary.get("status") or "") == "ERROR" or ignored:
        named = [
            f"{text(conflict.get('object')) or config.data_element}: {text(conflict.get('value')) or ''}"
            for conflict in map(as_object, as_list(summary.get("conflicts")))
            if conflict is not None
        ]
        detail = named_first(named) or IMPORT_VALUES_IGNORED.render(ignored=ignored)
        raise BlockFailure(DATA_VALUE_REFUSED, error_class=ErrorClass.REJECTED, detail=detail)
    return attribute_option_combo


class Dhis2DataValueOperator(Dhis2Operator[Dhis2DataValueConfig, Dhis2DataValueOutput]):
    """Reads, writes or removes one data value, rehearsing a write through a data value set dry run."""

    spec = OperatorSpec(
        id="dhis2.data_value",
        summary="Get, set or delete one DHIS2 data value by data element, period and org unit.",
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataValueConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataValueOutput

    def check_config(self, config: BaseModel) -> list[Issue]:
        """Refuse a set with no value, or half an attribute option combo, before the document is stored."""
        if not isinstance(config, Dhis2DataValueConfig):
            return []
        return [Issue.of(refusal) for refusal in _refusals(config)]

    async def execute(self, config: Dhis2DataValueConfig, ctx: StepContext) -> Dhis2DataValueOutput:
        """Do what the action says to the one value, or validate it on a dry run.

        The config is checked again here, because one holding a reference is not checked at
        apply and may resolve to a set without a value.
        """
        refusals = _refusals(config)
        if refusals:
            raise BlockFailure(refusals[0], error_class=ErrorClass.REJECTED)
        output = Dhis2DataValueOutput(
            action=config.action,
            data_element=config.data_element,
            period=config.period,
            org_unit=config.org_unit,
            category_option_combo=config.category_option_combo,
            found=True,
            dry_run=config.dry_run and config.action != "get",
        )
        async with client_for(ctx, config.connection) as client:
            if config.action == "get":
                return await self._get(client, config, output)
            if config.dry_run:
                resolved = await _rehearse(client, config)
                ctx.log.info("data value rehearsed", action=config.action)
                value = config.value if config.action == "set" else None
                return output.model_copy(update={"attribute_option_combo": resolved, "value": value})
            params = address(config)
            try:
                if config.action == "set":
                    if config.comment is not None:
                        params["comment"] = config.comment
                    await client.post_raw(DATA_VALUES_PATH, None, params={**params, "value": config.value or ""})
                else:
                    await client.delete_raw(DATA_VALUES_PATH, params=params)
            except (Dhis2ApiError, AuthenticationError) as error:
                verb = "POST" if config.action == "set" else "DELETE"
                raise refuse(error, f"{verb} {DATA_VALUES_PATH}") from error
        ctx.log.info("data value written", action=config.action)
        return output.model_copy(update={"value": config.value if config.action == "set" else None})

    async def _get(
        self, client: Dhis2Client, config: Dhis2DataValueConfig, output: Dhis2DataValueOutput
    ) -> Dhis2DataValueOutput:
        """Read the value, answering found false for a cell that holds none."""
        try:
            body = await client.get_raw(DATA_VALUES_PATH, params=address(config))
        except Dhis2ApiError as error:
            if _absent(error):
                return output.model_copy(update={"found": False})
            raise refuse(error, f"GET {DATA_VALUES_PATH}") from error
        except AuthenticationError as error:
            raise refuse(error, f"GET {DATA_VALUES_PATH}") from error
        values = as_list(body.get("data"))
        if not values:
            return output.model_copy(update={"found": False})
        return output.model_copy(update={"value": str(values[0])})
