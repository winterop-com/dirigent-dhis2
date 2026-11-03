"""Tests for dhis2.data_set_completion: one registration posted, its summary read as the verdict."""

import json as jsonlib
from typing import Any

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, summary
from dirigent_dhis2.data_set_completion import Dhis2DataSetCompletionOperator, Dhis2DataSetCompletionOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

REGISTRATIONS = f"{BASE_URL}/api/completeDataSetRegistrations"
WINDOW = {"data_set": "BfMAe6Itzgt", "period": "202607", "org_unit": "DiszpKrYNg8"}


def step(**config: Any) -> dict[str, Any]:
    return {"connection": CONNECTION, **WINDOW, **config}


async def test_a_window_is_marked_complete(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(REGISTRATIONS).answers(json(200, summary("SUCCESS", imported=1)))
    output = await call_block(Dhis2DataSetCompletionOperator(), step(), ctx)
    assert isinstance(output, Dhis2DataSetCompletionOutput)
    assert (output.status, output.completed, output.dry_run, output.imported) == ("SUCCESS", True, False, 1)
    request = route.last
    assert request.url.params["dryRun"] == "false"
    assert jsonlib.loads(request.content) == {
        "completeDataSetRegistrations": [
            {"dataSet": "BfMAe6Itzgt", "period": "202607", "organisationUnit": "DiszpKrYNg8", "completed": True}
        ]
    }


async def test_a_window_is_reopened_as_a_dry_run(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(REGISTRATIONS).answers(json(200, summary("SUCCESS", updated=1)))
    output = await call_block(
        Dhis2DataSetCompletionOperator(),
        step(completed=False, dry_run=True, attribute_option_combo="HllvX50cXC0"),
        ctx,
    )
    assert isinstance(output, Dhis2DataSetCompletionOutput)
    assert (output.completed, output.dry_run, output.updated) == (False, True, 1)
    request = route.last
    assert request.url.params["dryRun"] == "true"
    [entry] = jsonlib.loads(request.content)["completeDataSetRegistrations"]
    assert entry["completed"] is False
    assert entry["attributeOptionCombo"] == "HllvX50cXC0"


async def test_a_refused_registration_fails_the_step_naming_why(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    conflicts = [{"object": "DiszpKrYNg8", "value": "Organisation unit not assigned to data set"}]
    dhis2.post(REGISTRATIONS).answers(json(409, summary("ERROR", ignored=1, conflicts=conflicts)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataSetCompletionOperator(), step(), ctx)
    assert refused.value.code == "dhis2.data_set_completion.refused"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "DiszpKrYNg8: Organisation unit not assigned to data set" in refused.value.message


async def test_a_registration_ignored_without_conflicts_is_refused_by_count(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.post(REGISTRATIONS).answers(json(200, summary("WARNING", ignored=1)))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataSetCompletionOperator(), step(), ctx)
    assert "1 values ignored" in refused.value.message


async def test_an_answer_without_a_summary_fails_the_step(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(REGISTRATIONS).answers(json(200, {"status": "OK"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataSetCompletionOperator(), step(), ctx)
    assert refused.value.code == "dhis2.import.no_summary"


async def test_a_refusal_without_a_summary_is_classified_by_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(REGISTRATIONS).answers(json(401, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataSetCompletionOperator(), step(), ctx)
    assert refused.value.code == "dhis2.answered"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "district" not in refused.value.message


async def test_a_data_set_that_is_not_a_uid_is_refused_by_the_schema(ctx: FakeContext) -> None:
    with pytest.raises(ValueError, match="data_set"):
        await call_block(Dhis2DataSetCompletionOperator(), step(data_set="nope"), ctx)
