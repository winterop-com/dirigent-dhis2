"""Tests for dhis2.data_value_set_export: the document it answers with, and its refusals."""

from datetime import timedelta
from typing import Any, cast

import httpx2
import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, knowing
from dirigent_dhis2.export import (
    Dhis2DataValueSetExportConfig,
    Dhis2DataValueSetExportOperator,
    Dhis2DataValueSetExportOutput,
    dhis2_duration,
)
from dirigent_dhis2.messages import DHIS2
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


async def test_a_page_standing_in_for_the_api_is_not_taken_for_the_empty_answer(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """A 200 carrying HTML, such as a login page in front of the API, is refused as what it is."""
    dhis2.get(EXPORT).answers(httpx2.Response(200, content=b"<html>sign in</html>"))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "202507", "org_unit": "ImspTQPwCqd"},
            ctx,
        )
    assert refused.value.code == "dhis2.answered"


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


METADATA = f"{BASE_URL}/api/metadata"


async def test_an_export_repeats_every_selector_it_names(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(EXPORT).answers(json(200, {"dataValues": []}))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": ["pBOMPrpg1QX", "BfMAe6Itzgt"],
            "data_element": "fbfJHSPpUQD",
            "data_element_group": ["qfxEYY9xAl6"],
            "period": ["202601", "202602"],
            "org_unit": ["DiszpKrYNg8", "g8upMTyEZGZ"],
            "org_unit_group": "CXw2yu5fodb",
            "children": True,
            "include_deleted": True,
            "id_scheme": "CODE",
            "data_element_id_scheme": "NAME",
            "org_unit_id_scheme": "ATTRIBUTE:n2xYlNbsfko",
            "category_option_combo_id_scheme": "UID",
        },
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    params = route.last.url.params
    assert params.get_list("dataSet") == ["pBOMPrpg1QX", "BfMAe6Itzgt"]
    assert params.get_list("dataElement") == ["fbfJHSPpUQD"]
    assert params.get_list("dataElementGroup") == ["qfxEYY9xAl6"]
    assert params.get_list("period") == ["202601", "202602"]
    assert params.get_list("orgUnit") == ["DiszpKrYNg8", "g8upMTyEZGZ"]
    assert params.get_list("orgUnitGroup") == ["CXw2yu5fodb"]
    assert params["children"] == "true"
    assert params["includeDeleted"] == "true"
    assert params["idScheme"] == "CODE"
    assert params["dataElementIdScheme"] == "NAME"
    assert params["orgUnitIdScheme"] == "ATTRIBUTE:n2xYlNbsfko"
    assert params["categoryOptionComboIdScheme"] == "UID"


async def test_an_incremental_export_sends_its_window(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(EXPORT).answers(json(200, EXPORTED))
    await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": "pBOMPrpg1QX",
            "org_unit": "ImspTQPwCqd",
            "children": True,
            "last_updated_duration": "1d",
        },
        ctx,
    )
    params = route.last.url.params
    assert params["lastUpdatedDuration"] == "1d"
    assert "period" not in params


async def test_a_date_range_and_last_updated_ride_as_dhis2_names_them(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(EXPORT).answers(json(200, EXPORTED))
    await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": "pBOMPrpg1QX",
            "org_unit": "ImspTQPwCqd",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "last_updated": "2026-02-01",
        },
        ctx,
    )
    params = route.last.url.params
    assert (params["startDate"], params["endDate"], params["lastUpdated"]) == ("2026-01-01", "2026-03-31", "2026-02-01")


@pytest.mark.parametrize(
    ("duration", "written"),
    [
        (timedelta(days=2), "2d"),
        (timedelta(hours=36), "36h"),
        (timedelta(minutes=90), "90m"),
        (timedelta(seconds=45), "45s"),
    ],
)
def test_a_duration_is_written_in_the_largest_whole_unit(duration: timedelta, written: str) -> None:
    assert dhis2_duration(duration) == written


@pytest.mark.parametrize(
    ("config", "code"),
    [
        pytest.param({"period": "2026Q1", "org_unit": "ImspTQPwCqd"}, "export.no_data", id="no-what"),
        pytest.param({"data_set": "pBOMPrpg1QX", "period": "2026Q1"}, "export.no_org_unit", id="no-where"),
        pytest.param({"data_set": "pBOMPrpg1QX", "org_unit": "ImspTQPwCqd"}, "export.no_period", id="no-when"),
        pytest.param(
            {"data_set": "pBOMPrpg1QX", "org_unit": "ImspTQPwCqd", "start_date": "2026-01-01"},
            "export.half_range",
            id="half-a-range",
        ),
        pytest.param(
            {"data_set": [], "data_element": [], "period": "2026Q1", "org_unit": "ImspTQPwCqd"},
            "export.no_data",
            id="empty-lists",
        ),
    ],
)
def test_an_export_dhis2_would_refuse_is_refused_at_config(config: dict[str, object], code: str) -> None:
    with pytest.raises(ValidationError) as refused:
        Dhis2DataValueSetExportConfig.model_validate({"connection": "c", **config})
    assert DHIS2.messages[code].render() in str(refused.value)


def test_an_id_scheme_dhis2_does_not_know_is_refused_at_config() -> None:
    with pytest.raises(ValidationError):
        Dhis2DataValueSetExportConfig.model_validate(
            {"connection": "c", "data_set": "a", "period": "2026Q1", "org_unit": "b", "id_scheme": "SHORT"}
        )


async def test_the_named_uids_are_looked_up_in_one_request(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    lookup = dhis2.get(METADATA).responds(knowing())
    dhis2.get(EXPORT).answers(json(200, EXPORTED))
    await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": ["pBOMPrpg1QX", "BfMAe6Itzgt"],
            "period": "2026Q1",
            "org_unit": "ImspTQPwCqd",
            "org_unit_group": "CXw2yu5fodb",
        },
        ctx,
    )
    assert len(lookup.requests) == 1
    params = lookup.last.url.params
    assert params["dataSets:filter"] == "id:in:[BfMAe6Itzgt,pBOMPrpg1QX]"
    assert params["dataSets:fields"] == "id"
    assert params["organisationUnits:filter"] == "id:in:[ImspTQPwCqd]"
    assert params["organisationUnitGroups:filter"] == "id:in:[CXw2yu5fodb]"
    assert "dataElements" not in params


async def test_an_unknown_uid_is_refused_by_name_before_the_export(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(METADATA).responds(knowing("BfMAe6Itzgx", "Imspxxxxxxx"))
    route = dhis2.get(EXPORT).answers(json(200, EXPORTED))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetExportOperator(),
            {
                "connection": CONNECTION,
                "data_set": ["pBOMPrpg1QX", "BfMAe6Itzgx"],
                "period": "2026Q1",
                "org_unit": "Imspxxxxxxx",
            },
            ctx,
        )
    assert refused.value.code == "dhis2.unknown_uids"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "dataSets BfMAe6Itzgx" in refused.value.message
    assert "organisationUnits Imspxxxxxxx" in refused.value.message
    assert "pBOMPrpg1QX" not in refused.value.message
    assert "require_known: false" in refused.value.message
    assert route.requests == []


async def test_require_known_off_exports_without_the_lookup(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    lookup = dhis2.get(METADATA).responds(knowing("pBOMPrpg1QX"))
    dhis2.get(EXPORT).answers(json(200, EXPORTED))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": "pBOMPrpg1QX",
            "period": "2026Q1",
            "org_unit": "ImspTQPwCqd",
            "require_known": False,
        },
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert lookup.requests == []


async def test_an_export_of_several_data_sets_needs_no_data_set_on_the_document(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    """DHIS2 names the data set on the document only when one was asked for."""
    values = {"dataValues": [{"dataElement": "de1", "period": "2026Q1", "orgUnit": "ImspTQPwCqd", "value": "7"}]}
    dhis2.get(EXPORT).answers(json(200, values))
    output = await call_block(
        Dhis2DataValueSetExportOperator(),
        {
            "connection": CONNECTION,
            "data_set": ["pBOMPrpg1QX", "BfMAe6Itzgt"],
            "period": "2026Q1",
            "org_unit": "ImspTQPwCqd",
        },
        ctx,
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.body == values
