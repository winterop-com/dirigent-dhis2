"""Tests for dhis2.validation_run: the analysis run once, each violation answered, a gate on request."""

import json as jsonlib

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.validation_run import Dhis2ValidationRunOperator, Dhis2ValidationRunOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

ANALYSIS = f"{BASE_URL}/api/dataAnalysis/validationRules"
RANGE = {"connection": CONNECTION, "org_unit": "DiszpKrYNg8", "start_date": "2025-01-01", "end_date": "2025-12-31"}
VIOLATION = {
    "validationRuleId": "kgh54Xb9LSE",
    "validationRuleDescription": "Malaria outbreak",
    "organisationUnitId": "DiszpKrYNg8",
    "organisationUnitDisplayName": "Ngelehun CHC",
    "periodId": "202504",
    "attributeOptionComboId": "HllvX50cXC0",
    "importance": "MEDIUM",
    "leftSideValue": 10.0,
    "operator": ">",
    "rightSideValue": 12.0,
}


async def test_the_analysis_answers_each_violation(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(ANALYSIS).answers(json(200, [VIOLATION]))
    output = await call_block(
        Dhis2ValidationRunOperator(), {**RANGE, "validation_rule_group": "RAFwYAr0yBl", "max_results": 50}, ctx
    )
    assert isinstance(output, Dhis2ValidationRunOutput)
    assert output.count == 1
    violation = output.violations[0]
    assert violation.validation_rule == "kgh54Xb9LSE"
    assert violation.org_unit_name == "Ngelehun CHC"
    assert violation.period == "202504"
    assert violation.left_side_value == 10.0
    assert violation.operator == ">"
    assert jsonlib.loads(route.last.content) == {
        "ou": "DiszpKrYNg8",
        "startDate": "2025-01-01",
        "endDate": "2025-12-31",
        "persist": False,
        "notification": False,
        "vrg": "RAFwYAr0yBl",
        "maxResults": 50,
    }


async def test_no_violation_answers_an_empty_list(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(ANALYSIS).answers(json(200, []))
    output = await call_block(Dhis2ValidationRunOperator(), RANGE, ctx)
    assert isinstance(output, Dhis2ValidationRunOutput)
    assert output.violations == []
    assert output.count == 0


async def test_fail_on_violations_turns_one_into_a_refusal(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(ANALYSIS).answers(json(200, [VIOLATION]))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2ValidationRunOperator(), {**RANGE, "fail_on_violations": True}, ctx)
    assert refused.value.code == "dhis2.validation.violated"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "Malaria outbreak at Ngelehun CHC in 202504" in refused.value.message


async def test_a_refused_analysis_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(ANALYSIS).answers(json(409, {"message": "Start date is after end date"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2ValidationRunOperator(), RANGE, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
