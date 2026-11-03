"""Tests for dhis2.data_store: one key read, written or removed, and a namespace listed."""

import json as jsonlib

import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json
from dirigent_dhis2.data_store import Dhis2DataStoreConfig, Dhis2DataStoreOperator, Dhis2DataStoreOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

NAMESPACE = f"{BASE_URL}/api/dataStore/sync-state"
KEY = f"{NAMESPACE}/last-run"
NOT_FOUND = {"httpStatus": "Not Found", "httpStatusCode": 404, "status": "ERROR", "message": "Key not found"}


async def run(ctx: FakeContext, **config: object) -> Dhis2DataStoreOutput:
    output = await call_block(
        Dhis2DataStoreOperator(), {"connection": CONNECTION, "namespace": "sync-state", **config}, ctx
    )
    assert isinstance(output, Dhis2DataStoreOutput)
    return output


async def test_a_get_answers_the_value_as_it_is_stored(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(200, ["2026-01-01", 3]))
    output = await run(ctx, key="last-run")
    assert output.found is True
    assert output.value == ["2026-01-01", 3]


async def test_a_get_of_a_key_that_is_not_there_answers_not_found(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(404, NOT_FOUND))
    output = await run(ctx, key="last-run")
    assert output.found is False
    assert output.value is None


async def test_a_set_of_a_new_key_creates_it(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(404, NOT_FOUND))
    created = dhis2.post(KEY).answers(json(201, {"status": "OK"}))
    output = await run(ctx, action="set", key="last-run", value={"at": "2026-01-01"}, encrypt=True)
    assert output.created is True
    assert output.value == {"at": "2026-01-01"}
    assert jsonlib.loads(created.last.content) == {"at": "2026-01-01"}
    assert created.last.url.params["encrypt"] == "true"


async def test_a_set_of_a_key_already_there_replaces_it(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(200, {"at": "2025-12-01"}))
    replaced = dhis2.put(KEY).answers(json(200, {"status": "OK"}))
    output = await run(ctx, action="set", key="last-run", value={"at": "2026-01-01"})
    assert output.created is False
    assert output.found is True
    assert jsonlib.loads(replaced.last.content) == {"at": "2026-01-01"}


async def test_a_delete_of_a_key_that_is_not_there_sends_nothing(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(404, NOT_FOUND))
    removed = dhis2.delete(KEY).answers(json(200, {}))
    output = await run(ctx, action="delete", key="last-run")
    assert output.found is False
    assert removed.requests == []


async def test_a_delete_removes_the_key(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(200, 1))
    removed = dhis2.delete(KEY).answers(json(200, {}))
    output = await run(ctx, action="delete", key="last-run")
    assert output.found is True
    assert len(removed.requests) == 1


async def test_keys_lists_the_namespace_as_rows(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(NAMESPACE).answers(json(200, ["a", "b"]))
    output = await run(ctx, action="keys")
    assert output.rows == ["a", "b"]
    assert output.found is True
    assert output.key is None


async def test_the_user_store_is_addressed_on_its_own_root(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(f"{BASE_URL}/api/userDataStore/sync-state").answers(json(200, []))
    output = await run(ctx, action="keys", user_store=True)
    assert output.rows == []
    assert len(route.requests) == 1


async def test_a_key_is_escaped_into_one_path_segment(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.get(f"{NAMESPACE}/a%20b").answers(json(200, "x"))
    output = await run(ctx, key="a b")
    assert output.value == "x"
    assert len(route.requests) == 1


async def test_a_refused_read_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(KEY).answers(json(403, {"message": "no access"}))
    with pytest.raises(BlockFailure) as refused:
        await run(ctx, key="last-run")
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "no access" in refused.value.message


async def test_a_key_action_without_a_key_is_refused(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    with pytest.raises(BlockFailure) as refused:
        await run(ctx, action="get")
    assert refused.value.code == "dhis2.data_store.no_key"


def test_the_refusals_surface_at_apply() -> None:
    operator = Dhis2DataStoreOperator()
    config = Dhis2DataStoreConfig.model_validate(
        {"connection": CONNECTION, "namespace": "n", "action": "set", "key": "k"}
    )
    assert [issue.code for issue in operator.check_config(config)] == ["dhis2.data_store.no_value"]


def test_a_namespace_holding_a_slash_is_refused() -> None:
    with pytest.raises(ValidationError):
        Dhis2DataStoreConfig.model_validate({"connection": CONNECTION, "namespace": "a/b"})
