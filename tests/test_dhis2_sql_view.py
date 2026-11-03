"""Tests for dhis2.sql_view: a stored view run by uid, its grid answered as rows keyed by column."""

import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.sql_view import Dhis2SqlViewConfig, Dhis2SqlViewOperator, Dhis2SqlViewOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

VIEW = "qMYMT0iUGkG"
DATA = f"{BASE_URL}/api/sqlViews/{VIEW}/data.json"
GRID = {
    "listGrid": {
        "title": "Data element by value type",
        "headers": [
            {"name": "uid", "column": "uid", "type": "java.lang.String"},
            {"name": "name", "column": "name", "type": "java.lang.String"},
        ],
        "rows": [["fbfJHSPpUQD", "ANC 1st visit"], ["cYeuwXTCPkU", "ANC 2nd visit"]],
        "height": 2,
        "width": 2,
    }
}


async def test_a_view_answers_rows_keyed_by_column(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(DATA).answers(json(200, GRID))
    output = await call_block(
        Dhis2SqlViewOperator(),
        {"connection": CONNECTION, "sql_view": VIEW, "variables": {"valueType": "TEXT"}, "criteria": {"name": "x"}},
        ctx,
    )
    assert isinstance(output, Dhis2SqlViewOutput)
    assert output.rows == [
        {"uid": "fbfJHSPpUQD", "name": "ANC 1st visit"},
        {"uid": "cYeuwXTCPkU", "name": "ANC 2nd visit"},
    ]
    assert [column.name for column in output.columns] == ["uid", "name"]
    assert output.columns[0].value_type == "java.lang.String"
    assert output.title == "Data element by value type"
    assert output.pager is None
    params = route.last.url.params
    assert params.get_list("var") == ["valueType:TEXT"]
    assert params.get_list("criteria") == ["name:x"]
    assert params["paging"] == "false"


async def test_several_variables_are_each_sent(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(DATA).answers(json(200, GRID))
    await call_block(
        Dhis2SqlViewOperator(),
        {"connection": CONNECTION, "sql_view": VIEW, "variables": {"a": "1", "b": "2"}},
        ctx,
    )
    assert route.last.url.params.get_list("var") == ["a:1", "b:2"]


async def test_a_paged_read_answers_the_pager(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(DATA).answers(
        json(200, {**GRID, "pager": {"page": 1, "pageSize": 2, "total": 161, "pageCount": 81}})
    )
    output = await call_block(
        Dhis2SqlViewOperator(),
        {"connection": CONNECTION, "sql_view": VIEW, "paging": True, "page": 1, "page_size": 2},
        ctx,
    )
    assert isinstance(output, Dhis2SqlViewOutput)
    assert output.pager is not None
    assert output.pager.total == 161
    assert output.pager.more is True
    assert route.last.url.params["pageSize"] == "2"


async def test_an_unknown_view_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(DATA).answers(json(404, {"message": "SqlView with id qMYMT0iUGkG could not be found."}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2SqlViewOperator(), {"connection": CONNECTION, "sql_view": VIEW}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "could not be found" in refused.value.message


def test_a_variable_name_the_view_could_not_hold_is_refused() -> None:
    with pytest.raises(ValidationError):
        Dhis2SqlViewConfig.model_validate({"connection": CONNECTION, "sql_view": VIEW, "variables": {"a:b": "1"}})
