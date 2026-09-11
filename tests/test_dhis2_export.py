"""Tests for dhis2.data_value_set_export: the document it answers with, and its refusals."""

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.export import Dhis2DataValueSetExportOperator, Dhis2DataValueSetExportOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

EXPORT = f"{BASE_URL}/api/dataValueSets"
EXPORTED = {"dataSet": "pBOMPrpg1QX", "period": "2026Q1", "dataValues": [{"dataElement": "de1", "value": "7"}]}


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
