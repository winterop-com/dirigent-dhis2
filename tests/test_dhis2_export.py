"""Tests for dhis2.data_value_set_export: the document it answers with, and its refusals."""

from typing import Any, cast

import httpx2
import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.export import Dhis2DataValueSetExportOperator, Dhis2DataValueSetExportOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

EXPORT = f"{BASE_URL}/api/dataValueSets"
EXPORTED = {
    "dataSet": "pBOMPrpg1QX",
    "period": "2026Q1",
    "dataValues": [{"dataElement": "de1", "period": "2026Q1", "value": "7"}],
}


async def test_an_export_carries_the_set_as_its_body(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(EXPORT).answers(json(200, EXPORTED))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "ImspTQPwCqd"},
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.body == EXPORTED
    assert output.duration_ms >= 0
    request = route.last
    assert request.url.params["dataSet"] == "pBOMPrpg1QX"
    assert request.url.params["period"] == "2026Q1"
    assert request.url.params["orgUnit"] == "ImspTQPwCqd"
    assert "children" not in request.url.params


async def test_an_export_asks_for_the_descendants_when_told_to(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(EXPORT).answers(json(200, EXPORTED))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": "pBOMPrpg1QX",
            "period": "2026Q1",
            "org_unit": "ImspTQPwCqd",
            "children": True,
        },
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.body == EXPORTED
    assert route.last.url.params["children"] == "true"


async def test_an_export_with_descendants_leaves_out_the_document_org_unit(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    values = [
        {"dataElement": "de1", "orgUnit": "DiszpKrYNg8", "value": "7"},
        {"dataElement": "de1", "orgUnit": "Rp268JB6Ne4", "value": "3"},
    ]
    dhis2.get(EXPORT).answers(json(200, {**EXPORTED, "orgUnit": "ImspTQPwCqd", "dataValues": values}))
    config = {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "ImspTQPwCqd"}
    output = await call_block(Dhis2DataValueSetExportOperator(), {**config, "children": True}, ctx)
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    completed = [{**value, "period": "2026Q1"} for value in values]
    assert output.body == {"dataSet": "pBOMPrpg1QX", "period": "2026Q1", "dataValues": completed}


async def test_an_export_of_one_org_unit_keeps_the_document_org_unit(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    exported = {**EXPORTED, "orgUnit": "DiszpKrYNg8"}
    dhis2.get(EXPORT).answers(json(200, exported))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "DiszpKrYNg8"},
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.body == {
        **exported,
        "dataValues": [{"dataElement": "de1", "period": "2026Q1", "orgUnit": "DiszpKrYNg8", "value": "7"}],
    }


async def test_a_refused_export_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(EXPORT).answers(json(404, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {"connection": CONNECTION, "data_set": "x", "period": "2026Q1", "org_unit": "y"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_refusal_carries_the_instance_message(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(EXPORT).answers(json(404, {"message": "no such data set"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {"connection": CONNECTION, "data_set": "x", "period": "2026Q1", "org_unit": "y"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "no such data set" in refused.value.message


async def test_an_empty_answer_fails_rather_than_exporting_nothing(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """DHIS2 answers 200 with no body at all for an org unit outside the account's scope."""
    dhis2.get(EXPORT).answers(httpx2.Response(200, content=b""))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "202507", "org_unit": "ImspTQPwCqd"},
            ctx,
        )
    assert refused.value.code == "dhis2.export.empty_answer"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "ImspTQPwCqd" in refused.value.message


async def test_an_export_with_no_values_is_still_an_export(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    empty: dict[str, object] = {
        "dataSet": "pBOMPrpg1QX",
        "period": "190001",
        "orgUnit": "DiszpKrYNg8",
        "dataValues": [],
    }
    dhis2.get(EXPORT).answers(json(200, empty))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "190001", "org_unit": "DiszpKrYNg8"},
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.body == empty


#: A one-unit export as DHIS2 2.43.2 answers it: the shared fields once on the set, none on the values.
COMPACT_43 = {
    "dataSet": "pBOMPrpg1QX",
    "period": "202507",
    "orgUnit": "DiszpKrYNg8",
    "attributeOptionCombo": "HllvX50cXC0",
    "dataValues": [
        {"dataElement": "eY5ehpbEsB7", "categoryOptionCombo": "HllvX50cXC0", "value": "7"},
        {"dataElement": "s46m5MS0hxu", "categoryOptionCombo": "Prlt0C1RF0s", "value": "23"},
    ],
}

#: The same export as DHIS2 2.42.7 answers it: every value carrying its own.
FULL_42 = {
    "dataSet": "pBOMPrpg1QX",
    "period": "202507",
    "orgUnit": "DiszpKrYNg8",
    "dataValues": [
        {
            "dataElement": "eY5ehpbEsB7",
            "period": "202507",
            "orgUnit": "DiszpKrYNg8",
            "categoryOptionCombo": "HllvX50cXC0",
            "attributeOptionCombo": "HllvX50cXC0",
            "value": "7",
        },
        {
            "dataElement": "s46m5MS0hxu",
            "period": "202507",
            "orgUnit": "DiszpKrYNg8",
            "categoryOptionCombo": "Prlt0C1RF0s",
            "attributeOptionCombo": "HllvX50cXC0",
            "value": "23",
        },
    ],
}

ONE_UNIT = {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "202507", "org_unit": "DiszpKrYNg8"}


async def test_a_243_value_gets_the_fields_the_set_holds_for_it(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(EXPORT).answers(json(200, COMPACT_43))
    output = await call_block(Dhis2DataValueSetExportOperator(), ONE_UNIT, ctx)
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    body = cast("dict[str, Any]", output.body)
    assert [(one["period"], one["orgUnit"], one["attributeOptionCombo"]) for one in body["dataValues"]] == [
        ("202507", "DiszpKrYNg8", "HllvX50cXC0"),
        ("202507", "DiszpKrYNg8", "HllvX50cXC0"),
    ]
    assert body["period"] == "202507", "the set keeps what it carried"


async def test_a_value_reads_the_same_whichever_version_answered(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """The values a 2.43 export holds are the values a 2.42 export holds, field for field."""
    read: list[list[dict[str, Any]]] = []
    for answer in (COMPACT_43, FULL_42):
        dhis2.get(EXPORT).answers(json(200, answer))
        output = await call_block(Dhis2DataValueSetExportOperator(), ONE_UNIT, ctx)
        assert isinstance(output, Dhis2DataValueSetExportOutput)
        values = cast("dict[str, Any]", output.body)["dataValues"]
        read.append([{field: one[field] for field in sorted(one)} for one in values])
    assert read[0] == read[1]


async def test_a_value_keeps_its_own_field_over_the_sets(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    ranged = {**COMPACT_43, "dataValues": [{"dataElement": "de1", "period": "202508", "value": "1"}]}
    dhis2.get(EXPORT).answers(json(200, ranged))
    output = await call_block(Dhis2DataValueSetExportOperator(), ONE_UNIT, ctx)
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert cast("dict[str, Any]", output.body)["dataValues"][0]["period"] == "202508"
