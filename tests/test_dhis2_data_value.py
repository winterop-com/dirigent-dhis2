"""Tests for dhis2.data_value: one cell read, set or deleted, and a dry run that never touches it."""

import json as jsonlib
from typing import Any

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, summary
from dirigent_dhis2.data_value import Dhis2DataValueConfig, Dhis2DataValueOperator, Dhis2DataValueOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

DATA_VALUES = f"{BASE_URL}/api/dataValues"
DATA_VALUE_SETS = f"{BASE_URL}/api/dataValueSets"
COMBO = f"{BASE_URL}/api/categoryCombos/ccAttr00001"
CELL = {"data_element": "s46m5MS0hxu", "period": "202607", "org_unit": "DiszpKrYNg8"}


def step(**config: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, **CELL, **config}


async def test_a_get_reads_the_value(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(DATA_VALUES).answers(json(200, ["12"]))
    output = await call_block(Dhis2DataValueOperator(), step(category_option_combo="Prlt0C1RF0s"), ctx)
    assert isinstance(output, Dhis2DataValueOutput)
    assert (output.action, output.value, output.found, output.dry_run) == ("get", "12", True, False)
    assert output.category_option_combo == "Prlt0C1RF0s"
    assert dict(route.last.url.params) == {
        "de": "s46m5MS0hxu",
        "pe": "202607",
        "ou": "DiszpKrYNg8",
        "co": "Prlt0C1RF0s",
    }


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"status": "ERROR", "errorCode": "E1005", "message": "Data value does not exist"}),
        (409, {"status": "ERROR", "message": "Data value does not exist"}),
    ],
)
async def test_a_get_of_an_empty_cell_answers_not_found(
    ctx: FakeContext, dhis2: Dhis2Server, status: int, body: dict[str, Any]
) -> None:
    """2.43 and later answer 404 E1005; 2.42 answers 409 with the same words and no code."""
    dhis2.get(DATA_VALUES).answers(json(status, body))
    output = await call_block(Dhis2DataValueOperator(), step(), ctx)
    assert isinstance(output, Dhis2DataValueOutput)
    assert output.found is False
    assert output.value is None


async def test_a_get_another_409_refuses(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(DATA_VALUES).answers(json(409, {"status": "ERROR", "message": "Period is locked"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueOperator(), step(), ctx)
    assert refused.value.code == "dhis2.answered"


async def test_a_set_posts_the_value_with_the_attribute_option_combo_as_cc_and_cp(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    route = dhis2.post(DATA_VALUES).answers(json(201, {}))
    output = await call_block(
        Dhis2DataValueOperator(),
        step(
            action="set",
            value="15",
            comment="checked",
            attribute_combo="ccAttr00001",
            attribute_options=["coOptA00001", "coOptB00001"],
        ),
        ctx,
    )
    assert isinstance(output, Dhis2DataValueOutput)
    assert (output.action, output.value, output.found) == ("set", "15", True)
    params = route.last.url.params
    assert params["value"] == "15"
    assert params["comment"] == "checked"
    assert params["cc"] == "ccAttr00001"
    assert params["cp"] == "coOptA00001;coOptB00001"
    assert "dryRun" not in params


async def test_a_delete_removes_the_value(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.delete(DATA_VALUES).answers(json(204, {}))
    output = await call_block(Dhis2DataValueOperator(), step(action="delete"), ctx)
    assert isinstance(output, Dhis2DataValueOutput)
    assert (output.action, output.value) == ("delete", None)
    assert route.last.url.params["de"] == "s46m5MS0hxu"


async def test_a_set_the_instance_refuses_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(DATA_VALUES).answers(json(409, {"status": "ERROR", "message": "Value must be a number"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueOperator(), step(action="set", value="many"), ctx)
    assert refused.value.code == "dhis2.answered"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "Value must be a number" in refused.value.message


async def test_a_dry_run_set_rehearses_as_a_data_value_set_and_writes_nothing(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """``/api/dataValues`` takes dryRun and writes anyway, so it is never called on a dry run."""
    write = dhis2.post(DATA_VALUES)
    rehearsal = dhis2.post(DATA_VALUE_SETS).answers(json(200, summary("SUCCESS", imported=1)))
    output = await call_block(Dhis2DataValueOperator(), step(action="set", value="15", dry_run=True), ctx)
    assert isinstance(output, Dhis2DataValueOutput)
    assert (output.value, output.dry_run) == ("15", True)
    assert write.requests == []
    request = rehearsal.last
    assert request.url.params["dryRun"] == "true"
    assert request.url.params["importStrategy"] == "CREATE_AND_UPDATE"
    assert jsonlib.loads(request.content) == {
        "dataValues": [{"dataElement": "s46m5MS0hxu", "period": "202607", "orgUnit": "DiszpKrYNg8", "value": "15"}]
    }


async def test_a_dry_run_delete_rehearses_with_the_delete_strategy(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    rehearsal = dhis2.post(DATA_VALUE_SETS).answers(json(200, summary("SUCCESS", deleted=1)))
    await call_block(Dhis2DataValueOperator(), step(action="delete", dry_run=True), ctx)
    assert rehearsal.last.url.params["importStrategy"] == "DELETE"


async def test_a_dry_run_resolves_the_attribute_option_combo(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(COMBO).answers(
        json(
            200,
            {
                "categoryOptionCombos": [
                    {"id": "aocOther001", "categoryOptions": [{"id": "coOptA00001"}]},
                    {"id": "aocBoth0001", "categoryOptions": [{"id": "coOptB00001"}, {"id": "coOptA00001"}]},
                ]
            },
        )
    )
    rehearsal = dhis2.post(DATA_VALUE_SETS).answers(json(200, summary("SUCCESS", imported=1)))
    output = await call_block(
        Dhis2DataValueOperator(),
        step(
            action="set",
            value="3",
            dry_run=True,
            attribute_combo="ccAttr00001",
            attribute_options=["coOptA00001", "coOptB00001"],
        ),
        ctx,
    )
    assert isinstance(output, Dhis2DataValueOutput)
    assert output.attribute_option_combo == "aocBoth0001"
    [row] = jsonlib.loads(rehearsal.last.content)["dataValues"]
    assert row["attributeOptionCombo"] == "aocBoth0001"


async def test_a_dry_run_with_options_no_combo_holds_is_refused(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(COMBO).answers(json(200, {"categoryOptionCombos": []}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueOperator(),
            step(
                action="set", value="3", dry_run=True, attribute_combo="ccAttr00001", attribute_options=["coOptA00001"]
            ),
            ctx,
        )
    assert refused.value.code == "dhis2.data_value.unknown_attribute"


async def test_a_dry_run_the_instance_would_refuse_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    conflicts = [{"object": "s46m5MS0hxu", "value": "Value must be a number", "errorCode": "E7619"}]
    dhis2.post(DATA_VALUE_SETS).answers(json(409, summary("ERROR", ignored=1, conflicts=conflicts)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueOperator(), step(action="set", value="many", dry_run=True), ctx)
    assert refused.value.code == "dhis2.data_value.refused"
    assert "s46m5MS0hxu: Value must be a number" in refused.value.message


async def test_a_dry_run_that_ignored_the_value_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(DATA_VALUE_SETS).answers(json(200, summary("WARNING", ignored=1)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueOperator(), step(action="set", value="1", dry_run=True), ctx)
    assert refused.value.code == "dhis2.data_value.refused"
    assert "1 values ignored" in refused.value.message


def test_a_set_without_a_value_is_refused_at_apply() -> None:
    config = Dhis2DataValueConfig.model_validate(step(action="set"))
    assert [issue.code for issue in Dhis2DataValueOperator().check_config(config)] == ["dhis2.data_value.no_value"]


def test_half_an_attribute_option_combo_is_refused_at_apply() -> None:
    config = Dhis2DataValueConfig.model_validate(step(attribute_combo="ccAttr00001"))
    assert [issue.code for issue in Dhis2DataValueOperator().check_config(config)] == [
        "dhis2.data_value.half_attribute"
    ]


async def test_a_set_without_a_value_is_refused_at_run_before_sending(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(DATA_VALUES)
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueOperator(), step(action="set"), ctx)
    assert refused.value.code == "dhis2.data_value.no_value"
    assert route.requests == []


async def test_a_data_element_that_is_not_a_uid_is_refused_by_the_schema(ctx: FakeContext) -> None:
    with pytest.raises(ValueError, match="data_element"):
        await call_block(Dhis2DataValueOperator(), step(data_element="../users"), ctx)
