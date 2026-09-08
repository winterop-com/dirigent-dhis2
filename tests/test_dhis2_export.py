"""Tests for dhis2.data_value_set_export: inline answers and stored artifacts."""

import json as jsonlib

import pytest
import respx

from dhis2server import BASE_URL, CONNECTION, json
from dirigent_dhis2.export import Dhis2DataValueSetExportOperator, Dhis2DataValueSetExportOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

EXPORT = f"{BASE_URL}/api/dataValueSets"
EXPORT_STREAM = f"{BASE_URL}/api/dataValueSets.json"
EXPORTED = {"dataSet": "pBOMPrpg1QX", "period": "2026Q1", "dataValues": [{"dataElement": "de1", "value": "7"}]}


async def test_an_export_carries_the_set_inline(ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(EXPORT).mock(return_value=json(200, EXPORTED))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "ImspTQPwCqd"},
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.json_body == EXPORTED
    assert output.body_uri is None
    assert output.duration_ms >= 0
    request = route.calls.last.request
    assert request.url.params["dataSet"] == "pBOMPrpg1QX"
    assert request.url.params["period"] == "2026Q1"
    assert request.url.params["orgUnit"] == "ImspTQPwCqd"
    assert "children" not in request.url.params


async def test_an_export_is_saved_to_storage_when_asked(local_ctx: FakeContext, dhis2: respx.Router) -> None:
    route = dhis2.get(EXPORT_STREAM).mock(return_value=json(200, EXPORTED))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": "pBOMPrpg1QX",
            "period": "2026Q1",
            "org_unit": "ImspTQPwCqd",
            "children": True,
            "save_to": f"{local_ctx.scratch_uri}/dhis2/2026Q1.json",
        },
        local_ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.json_body is None
    uri = output.body_uri
    assert uri == f"{local_ctx.scratch_uri}/dhis2/2026Q1.json"
    assert output.body_bytes is not None and output.body_bytes > 0
    assert uri is not None
    saved = local_ctx.storage.path_for(uri).read_bytes()
    assert jsonlib.loads(saved) == EXPORTED
    assert route.calls.last.request.url.params["children"] == "true"


async def test_a_refused_export_is_classified_by_its_status(ctx: FakeContext, dhis2: respx.Router) -> None:
    dhis2.get(EXPORT).mock(return_value=json(404, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {"connection": CONNECTION, "data_set": "x", "period": "2026Q1", "org_unit": "y"},
            ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_refused_export_leaves_nothing_at_save_to(local_ctx: FakeContext, dhis2: respx.Router) -> None:
    dhis2.get(EXPORT_STREAM).mock(return_value=json(404, {"message": "no such data set"}))
    uri = f"{local_ctx.scratch_uri}/dhis2/missing.json"
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {"connection": CONNECTION, "data_set": "x", "period": "2026Q1", "org_unit": "y", "save_to": uri},
            local_ctx,
        )
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "no such data set" in refused.value.message
    assert not local_ctx.storage.path_for(uri).exists()
