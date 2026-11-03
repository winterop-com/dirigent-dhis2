"""Tests for dhis2.system_info: the instance's own description, its common fields lifted by name."""

import pytest

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.system_info import Dhis2SystemInfoOperator, Dhis2SystemInfoOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

SYSTEM_INFO = f"{BASE_URL}/api/system/info"
ANSWER = {
    "version": "2.42.1",
    "revision": "a1b2c3d",
    "buildTime": "2025-01-15T10:23:00.000",
    "systemId": "eed3d451-4ff5-4193-b951-ffcc68954299",
    "systemName": "Sierra Leone",
    "instanceBaseUrl": "https://dhis2.test",
    "serverDate": "2026-11-03T08:00:00.000",
    "serverTimeZoneId": "Etc/UTC",
    "calendar": "iso8601",
    "dateFormat": "yyyy-mm-dd",
    "lastAnalyticsTableSuccess": "2026-11-02T23:10:00.000",
    "lastAnalyticsTableRuntime": "12 m, 4 s",
    "intervalSinceLastAnalyticsTableSuccess": "8 h, 50 m",
    "databaseInfo": {"name": "dhis2", "databaseVersion": "PostgreSQL 16"},
    "cpuCores": 8,
}


async def test_system_info_lifts_the_fields_a_report_reads(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(SYSTEM_INFO).answers(json(200, ANSWER))
    output = await call_block(Dhis2SystemInfoOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, Dhis2SystemInfoOutput)
    assert output.version == "2.42.1"
    assert output.revision == "a1b2c3d"
    assert output.build_time == "2025-01-15T10:23:00.000"
    assert output.system_id == "eed3d451-4ff5-4193-b951-ffcc68954299"
    assert output.system_name == "Sierra Leone"
    assert output.instance_base_url == "https://dhis2.test"
    assert output.server_date == "2026-11-03T08:00:00.000"
    assert output.server_time_zone_id == "Etc/UTC"
    assert output.calendar == "iso8601"
    assert output.date_format == "yyyy-mm-dd"
    assert output.last_analytics_table_success == "2026-11-02T23:10:00.000"
    assert output.last_analytics_table_runtime == "12 m, 4 s"
    assert output.interval_since_last_analytics_table_success == "8 h, 50 m"
    assert output.other == {"databaseInfo": ANSWER["databaseInfo"], "cpuCores": 8}
    assert output.duration_ms >= 0


async def test_a_named_key_that_is_not_a_string_stays_in_other(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(SYSTEM_INFO).answers(json(200, {"version": "2.42.1", "buildTime": 1736936580000}))
    output = await call_block(Dhis2SystemInfoOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, Dhis2SystemInfoOutput)
    assert output.build_time is None
    assert output.other == {"buildTime": 1736936580000}


async def test_an_instance_that_never_ran_analytics_leaves_those_fields_unset(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.get(SYSTEM_INFO).answers(json(200, {"version": "2.42.1"}))
    output = await call_block(Dhis2SystemInfoOperator(), {"connection": CONNECTION}, ctx)
    assert isinstance(output, Dhis2SystemInfoOutput)
    assert output.last_analytics_table_success is None
    assert output.other == {}


@pytest.mark.parametrize(("status", "error_class"), [(403, ErrorClass.REJECTED), (503, ErrorClass.TRANSIENT)])
async def test_a_refused_read_is_classified_by_its_status(
    ctx: FakeContext, dhis2: Dhis2Server, status: int, error_class: ErrorClass
) -> None:
    """The connect probe reads the same path, so the refusal is the second answer it gives."""
    dhis2.get(SYSTEM_INFO).answers_in_turn(json(200, {"version": "2.42.1"}), json(status, {"message": "no"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2SystemInfoOperator(), {"connection": CONNECTION}, ctx)
    assert refused.value.error_class is error_class
    assert refused.value.params["where"] == "GET /api/system/info"
