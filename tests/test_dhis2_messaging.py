"""Tests for dhis2.message: the conversation it starts, its recipients, and its refusals."""

import json as jsonlib
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, serve
from dirigent_dhis2.messaging import Dhis2MessageConfig, Dhis2MessageOperator, Dhis2MessageOutput
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

CONVERSATIONS = f"{BASE_URL}/api/messageConversations"
CONVERSATION_ID = "lQtpMU8ChLW"
CREATED = f"{CONVERSATIONS}/{CONVERSATION_ID}"
ASKED: dict[str, Any] = {
    "connection": CONNECTION,
    "subject": "ANC coverage below target",
    "text": "Kono: 53.81\nKoinadugu: 68.31",
    "user_groups": ["ZoHNWQajIoe"],
}


def created(location: str = CREATED) -> httpx2.Response:
    """The 201 DHIS2 2.42 and 2.43 answer a new conversation with: the uid is only on Location."""
    envelope = {
        "httpStatus": "Created",
        "httpStatusCode": 201,
        "status": "OK",
        "message": "Message conversation created",
    }
    return httpx2.Response(201, json=envelope, headers={"Location": location})


def sent(dhis2: Dhis2Server) -> None:
    """Script a send the instance takes, and the conversation it is read back as."""
    dhis2.post(CONVERSATIONS).answers(created())
    dhis2.get(CREATED).answers(json(200, {"id": CONVERSATION_ID, "subject": ASKED["subject"]}))


@pytest.mark.parametrize("version", ["2.42.7", "2.43.2"])
async def test_a_message_starts_a_conversation(ctx: FakeContext, monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    dhis2 = serve(monkeypatch, version=version)
    sent(dhis2)
    output = await call_block(
        Dhis2MessageOperator(),
        {**ASKED, "users": ["xE7jOejl9FI"], "org_units": ["O6uvpzGd5pu", "fdc6uOvgoji"]},
        ctx,
    )
    assert isinstance(output, Dhis2MessageOutput)
    assert output.model_dump() == {
        "conversation_id": CONVERSATION_ID,
        "user_count": 1,
        "user_group_count": 1,
        "org_unit_count": 2,
    }
    assert jsonlib.loads(dhis2.routes[("POST", CONVERSATIONS)].last.content) == {
        "subject": ASKED["subject"],
        "text": ASKED["text"],
        "users": [{"id": "xE7jOejl9FI"}],
        "userGroups": [{"id": "ZoHNWQajIoe"}],
        "organisationUnits": [{"id": "O6uvpzGd5pu"}, {"id": "fdc6uOvgoji"}],
    }


async def test_a_recipient_kind_left_empty_is_not_sent(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    sent(dhis2)
    output = await call_block(Dhis2MessageOperator(), ASKED, ctx)
    assert output.model_dump()["user_count"] == 0
    body = jsonlib.loads(dhis2.routes[("POST", CONVERSATIONS)].last.content)
    assert set(body) == {"subject", "text", "userGroups"}


async def test_a_long_text_is_sent_whole(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    sent(dhis2)
    text = "\n".join(f"district {n}: below target" for n in range(2000))
    await call_block(Dhis2MessageOperator(), {**ASKED, "text": text}, ctx)
    assert jsonlib.loads(dhis2.routes[("POST", CONVERSATIONS)].last.content)["text"] == text


@pytest.mark.parametrize("status", [400, 409])
async def test_a_refused_message_is_rejected(ctx: FakeContext, dhis2: Dhis2Server, status: int) -> None:
    dhis2.post(CONVERSATIONS).answers(
        json(status, {"httpStatus": "Conflict", "status": "ERROR", "message": "No recipients selected."})
    )
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MessageOperator(), ASKED, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.answered"
    assert refused.value.params["where"] == "POST /api/messageConversations"
    assert refused.value.params["status"] == status
    assert "No recipients selected." in refused.value.message


async def test_a_failing_instance_is_transient(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(CONVERSATIONS).answers(json(503, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MessageOperator(), ASKED, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


async def test_a_refused_credential_is_rejected(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.post(CONVERSATIONS).answers(json(401, {}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MessageOperator(), ASKED, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED


async def test_a_send_without_a_location_is_rejected_rather_than_sent_again(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    dhis2.post(CONVERSATIONS).answers(json(201, {"httpStatus": "Created", "status": "OK"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MessageOperator(), ASKED, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.message.no_conversation"


def test_a_message_addressed_to_nobody_is_refused_at_apply() -> None:
    config = Dhis2MessageConfig.model_validate({**ASKED, "user_groups": []})
    assert [issue.code for issue in Dhis2MessageOperator().check_config(config)] == ["dhis2.message.no_recipient"]


@pytest.mark.parametrize("kind", ["users", "user_groups", "org_units"])
def test_any_one_recipient_kind_is_enough(kind: str) -> None:
    config = Dhis2MessageConfig.model_validate({**ASKED, "user_groups": [], kind: ["ZoHNWQajIoe"]})
    assert Dhis2MessageOperator().check_config(config) == []


async def test_a_message_resolved_to_nobody_is_refused_at_run(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    """A config holding a reference is not checked at apply, so the run checks it again."""
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MessageOperator(), {**ASKED, "user_groups": []}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
    assert refused.value.code == "dhis2.message.no_recipient"
    assert ("POST", CONVERSATIONS) not in dhis2.routes


@pytest.mark.parametrize("uid", ["ZoHNWQajIo", "ZoHNWQajIoeX", "1oHNWQajIoe", "ZoHNWQ-jIoe", ""])
@pytest.mark.parametrize("kind", ["users", "user_groups", "org_units"])
def test_a_recipient_must_be_a_dhis2_uid(kind: str, uid: str) -> None:
    with pytest.raises(ValidationError):
        Dhis2MessageConfig.model_validate({**ASKED, kind: [uid]})


@pytest.mark.parametrize("field", ["subject", "text"])
def test_a_message_needs_a_subject_and_a_text(field: str) -> None:
    with pytest.raises(ValidationError):
        Dhis2MessageConfig.model_validate({**ASKED, field: ""})
    without = {key: value for key, value in ASKED.items() if key != field}
    with pytest.raises(ValidationError):
        Dhis2MessageConfig.model_validate(without)


def test_a_subject_is_held_to_what_dhis2_stores() -> None:
    with pytest.raises(ValidationError):
        Dhis2MessageConfig.model_validate({**ASKED, "subject": "x" * 256})
