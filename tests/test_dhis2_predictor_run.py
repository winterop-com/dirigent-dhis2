"""Tests for dhis2.predictor_run: the run sent to the right target, and its count read."""

import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.predictor_run import Dhis2PredictorRunConfig, Dhis2PredictorRunOperator, Dhis2PredictorRunOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

RANGE = {"connection": CONNECTION, "start_date": "2026-01-01", "end_date": "2026-03-31"}


def generated(n: int, response: dict[str, object] | None = None) -> dict[str, object]:
    body: dict[str, object] = {"httpStatus": "OK", "status": "OK", "message": f"Generated {n} predictions"}
    if response is not None:
        body["response"] = response
    return body


async def test_every_predictor_runs_when_none_is_named(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(f"{BASE_URL}/api/predictors/run").answers(json(200, generated(12)))
    output = await call_block(Dhis2PredictorRunOperator(), RANGE, ctx)
    assert isinstance(output, Dhis2PredictorRunOutput)
    assert output.predictions == 12
    assert output.message == "Generated 12 predictions"
    assert output.inserted is None
    assert route.last.url.params["startDate"] == "2026-01-01"
    assert route.last.url.params["endDate"] == "2026-03-31"


async def test_one_predictor_runs_on_its_own_path(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    summary: dict[str, object] = {
        "responseType": "PredictionSummary",
        "inserted": 3,
        "updated": 1,
        "deleted": 0,
        "unchanged": 2,
    }
    dhis2.post(f"{BASE_URL}/api/predictors/AG2Z7C0dbKz/run").answers(json(200, generated(4, summary)))
    output = await call_block(Dhis2PredictorRunOperator(), {**RANGE, "predictor": "AG2Z7C0dbKz"}, ctx)
    assert isinstance(output, Dhis2PredictorRunOutput)
    assert (output.predictions, output.inserted, output.updated, output.unchanged) == (4, 3, 1, 2)


async def test_a_group_runs_on_its_own_path(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(f"{BASE_URL}/api/predictorGroups/HhJSbVrbDgW/run").answers(json(200, generated(0)))
    output = await call_block(Dhis2PredictorRunOperator(), {**RANGE, "predictor_group": "HhJSbVrbDgW"}, ctx)
    assert isinstance(output, Dhis2PredictorRunOutput)
    assert output.predictions == 0
    assert len(route.requests) == 1


async def test_a_refused_run_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(f"{BASE_URL}/api/predictors/run").answers(json(500, {"message": "boom"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2PredictorRunOperator(), RANGE, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


def test_a_run_naming_a_predictor_and_a_group_is_refused() -> None:
    with pytest.raises(ValidationError, match="not both"):
        Dhis2PredictorRunConfig.model_validate({**RANGE, "predictor": "AG2Z7C0dbKz", "predictor_group": "HhJSbVrbDgW"})
