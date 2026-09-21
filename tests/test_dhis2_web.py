"""Tests for what the blocks share: classifying a dhis2w-client failure, and shaping a query's terms."""

import httpx2
import pytest
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError, UnsupportedVersionError, VersionPinMismatchError

from dhis2server import BASE_URL, CONNECTION, serve
from dirigent_dhis2 import Dhis2Plugin
from dirigent_dhis2.messages import ANSWERED
from dirigent_dhis2.metadata import Dhis2MetadataOperator
from dirigent_dhis2.web import QueryTerms, classify, query_terms, refuse
from dirigent_plugin import AnyOperator, AnySensor, BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx2.ConnectError("refused"), ErrorClass.TRANSIENT),
        (httpx2.ReadTimeout("slow"), ErrorClass.TRANSIENT),
        (Dhis2ApiError(503, "Service Unavailable"), ErrorClass.TRANSIENT),
        (Dhis2ApiError(429, "Too Many Requests"), ErrorClass.TRANSIENT),
        (Dhis2ApiError(409, "Conflict"), ErrorClass.REJECTED),
        (AuthenticationError("401 Unauthorized at GET /api/x"), ErrorClass.REJECTED),
        (UnsupportedVersionError("2.40.0", ["v41", "v42", "v43"]), ErrorClass.REJECTED),
        (VersionPinMismatchError("v43", "2.41.0"), ErrorClass.REJECTED),
        (
            BlockFailure(ANSWERED, error_class=ErrorClass.TRANSIENT, where="GET /api/x", status=503, remote="mine"),
            ErrorClass.TRANSIENT,
        ),
        (RuntimeError("something else"), ErrorClass.UNKNOWN),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, Exception) else str(value),
)
def test_a_failure_is_classified_the_dhis2w_way(error: Exception, expected: ErrorClass) -> None:
    assert classify(error) is expected


def test_every_contributed_block_classifies_through_the_shared_rule() -> None:
    contribution = Dhis2Plugin().contribute()
    blocks: list[AnyOperator | AnySensor] = [*contribution.operators, *contribution.sensors]
    assert blocks
    for block in blocks:
        assert block.classify_error(httpx2.ConnectError("refused")) is ErrorClass.TRANSIENT, block.spec.id
        assert block.classify_error(UnsupportedVersionError("2.40.0", ["v42"])) is ErrorClass.REJECTED, block.spec.id


def test_a_refusal_carries_the_instance_message() -> None:
    body = {"httpStatus": "Conflict", "status": "ERROR", "message": "Import already in progress"}
    failure = refuse(Dhis2ApiError(409, "Conflict", body=body), "POST /api/dataValueSets")
    assert failure.message == "POST /api/dataValueSets answered 409: Import already in progress"
    assert failure.code == "dhis2.answered"
    assert failure.params == {"where": "POST /api/dataValueSets", "status": 409, "remote": "Import already in progress"}
    assert failure.error_class is ErrorClass.REJECTED


def test_a_refusal_without_a_web_message_carries_the_reason_phrase() -> None:
    failure = refuse(Dhis2ApiError(502, "Bad Gateway", body="<html>"), "GET /api/x")
    assert failure.message == "GET /api/x answered 502: Bad Gateway"
    assert failure.error_class is ErrorClass.TRANSIENT


async def test_an_unreachable_instance_is_a_transient_failure(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    dhis2 = serve(monkeypatch)
    dhis2.get(f"{BASE_URL}/").raises(httpx2.ConnectError("refused"))
    dhis2.get(f"{BASE_URL}/api/system/info").raises(httpx2.ConnectError("refused"))
    operator = Dhis2MetadataOperator()
    with pytest.raises(httpx2.ConnectError) as raised:
        await call_block(operator, {"connection": CONNECTION, "resource": "dataElements"}, ctx)
    assert operator.classify_error(raised.value) is ErrorClass.TRANSIENT


async def test_an_instance_version_the_client_cannot_speak_is_rejected(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, version="2.40.0")
    operator = Dhis2MetadataOperator()
    with pytest.raises(UnsupportedVersionError) as raised:
        await call_block(operator, {"connection": CONNECTION, "resource": "dataElements"}, ctx)
    assert operator.classify_error(raised.value) is ErrorClass.REJECTED


def test_a_list_is_joined_for_fields_and_order_and_repeated_for_filter() -> None:
    terms = query_terms(
        fields=["id", "parent[id,code]"],
        filter=["level:eq:2", "name:like:Bo"],
        order=["level:asc", "name:asc"],
    )
    assert terms == QueryTerms(
        fields="id,parent[id,code]",
        filter=["level:eq:2", "name:like:Bo"],
        order="level:asc,name:asc",
    )


def test_a_string_is_one_term_passed_through_unchanged() -> None:
    terms = query_terms(fields="id,parent[id,code]", filter="level:eq:2", order="level:asc,name:asc")
    assert terms == QueryTerms(fields="id,parent[id,code]", filter=["level:eq:2"], order="level:asc,name:asc")


@pytest.mark.parametrize("absent", [None, []], ids=["unset", "empty"])
def test_an_unset_or_empty_term_is_no_term(absent: list[str] | None) -> None:
    assert query_terms(fields=absent, filter=absent, order=absent) == QueryTerms(fields=None, filter=None, order=None)
