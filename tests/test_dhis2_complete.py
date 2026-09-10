"""Tests for dhis2.data_set_complete: the wait, and the registration that ends it."""

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.complete import Dhis2DataSetCompleteOutput, Dhis2DataSetCompleteSensor
from dirigent_plugin import BlockFailure, ErrorClass, NotYet
from dirigent_testing import FakeContext, call_block

REGISTRATIONS = f"{BASE_URL}/api/completeDataSetRegistrations"
ASKED = {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "ImspTQPwCqd"}


async def test_a_completed_registration_ends_the_wait(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(REGISTRATIONS).answers(
        json(
            200,
            {
                "completeDataSetRegistrations": [
                    {"period": "2026Q1", "date": "2026-04-02", "storedBy": "admin", "completed": True}
                ]
            },
        )
    )
    output = await call_block(Dhis2DataSetCompleteSensor(), ASKED, ctx)
    assert isinstance(output, Dhis2DataSetCompleteOutput)
    assert output.completed_at == "2026-04-02"
    assert output.stored_by == "admin"
    request = route.last
    assert request.url.params["dataSet"] == "pBOMPrpg1QX"
    assert request.url.params["period"] == "2026Q1"
    assert request.url.params["orgUnit"] == "ImspTQPwCqd"


async def test_an_unclosed_window_is_not_yet(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REGISTRATIONS).answers(json(200, {}))
    waited = await call_block(Dhis2DataSetCompleteSensor(), ASKED, ctx)
    assert isinstance(waited, NotYet)
    assert "is not complete" in (waited.message or "")


async def test_a_reopened_registration_keeps_waiting(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REGISTRATIONS).answers(
        json(200, {"completeDataSetRegistrations": [{"period": "2026Q1", "completed": False}]})
    )
    waited = await call_block(Dhis2DataSetCompleteSensor(), ASKED, ctx)
    assert isinstance(waited, NotYet)


async def test_an_old_instance_without_the_flag_counts_the_registration(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REGISTRATIONS).answers(
        json(200, {"completeDataSetRegistrations": [{"period": "2026Q1", "date": "2026-04-02"}]})
    )
    output = await call_block(Dhis2DataSetCompleteSensor(), ASKED, ctx)
    assert isinstance(output, Dhis2DataSetCompleteOutput)
    assert output.completed_at == "2026-04-02"
    assert output.stored_by is None


async def test_a_refused_poke_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(REGISTRATIONS).answers(json(500, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataSetCompleteSensor(), ASKED, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT
