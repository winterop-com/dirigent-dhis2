"""An instance or proxy quoting the Authorization it was sent never puts the credential in text a reader sees."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from pydantic import SecretStr

from dhis2server import CONNECTION
from dirigent_dhis2.connection import Dhis2ConnectionConfig, Dhis2ConnectionKind
from dirigent_dhis2.metadata import Dhis2MetadataOperator
from dirigent_plugin import BlockFailure
from dirigent_testing import FakeContext, call_block

INFO = "/api/system/info"
ORG_UNITS = "/api/organisationUnits"

BASIC_TOKEN = base64.b64encode(b"dummyuser:dummy-basic-pw").decode()
CREDENTIALS = [
    pytest.param(
        {"basic_username": "dummyuser", "basic_password": SecretStr("dummy-basic-pw")},
        [f"Basic {BASIC_TOKEN}", BASIC_TOKEN, "dummyuser:dummy-basic-pw"],
        id="basic",
    ),
    pytest.param(
        {"api_token": SecretStr("d2pat_DUMMYTOKEN4567")},
        ["ApiToken d2pat_DUMMYTOKEN4567", "d2pat_DUMMYTOKEN4567"],
        id="pat",
    ),
]


class Quoting:
    """A loopback instance that answers ``quoting`` with a DHIS2 error quoting the Authorization it was sent."""

    def __init__(self, quoting: str, status: str) -> None:
        """Quote on one path, with one status, and answer the version probe otherwise."""
        self.quoting = quoting
        self.status = status
        self.url = ""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Answer one request and close."""
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode()
            lines = head.split("\r\n")
            headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
            path = lines[0].split(" ")[1].split("?")[0]
            if path == self.quoting:
                code = int(self.status.split(" ")[0])
                said = f"the proxy refused Authorization: {headers.get('Authorization')}"
                body = json.dumps(
                    {"httpStatus": self.status, "httpStatusCode": code, "status": "ERROR", "message": said}
                )
                status = self.status
            else:
                body, status = json.dumps({"version": "2.42.0"}), "200 OK"
            encoded = body.encode()
            head_out = [f"HTTP/1.1 {status}", "Content-Type: application/json", f"Content-Length: {len(encoded)}"]
            writer.write(("\r\n".join([*head_out, "Connection: close"]) + "\r\n\r\n").encode() + encoded)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def connection(self, credential: dict[str, Any]) -> Dhis2ConnectionConfig:
        """A connection to this instance carrying the credential."""
        return Dhis2ConnectionConfig.model_validate({"base_url": self.url, **credential})


@pytest_asyncio.fixture(params=["500 Internal Server Error", "409 Conflict"])
async def quoting(request: pytest.FixtureRequest) -> AsyncIterator[Quoting]:
    served = Quoting(INFO, request.param)
    listening = await asyncio.start_server(served.handle, "127.0.0.1", 0)
    served.url = f"http://127.0.0.1:{listening.sockets[0].getsockname()[1]}"
    try:
        yield served
    finally:
        listening.close()


@pytest.mark.parametrize(("credential", "spelled"), CREDENTIALS)
async def test_a_quoted_credential_never_reaches_the_health_detail(
    quoting: Quoting, credential: dict[str, Any], spelled: list[str]
) -> None:
    report = await Dhis2ConnectionKind().check(quoting.connection(credential))
    assert report.healthy is False
    assert report.detail is not None and "Authorization: ***" in report.detail
    for one in spelled:
        assert one not in report.detail


@pytest.mark.parametrize(("credential", "spelled"), CREDENTIALS)
async def test_a_quoted_credential_never_reaches_a_refusal(
    ctx: FakeContext, quoting: Quoting, credential: dict[str, Any], spelled: list[str]
) -> None:
    quoting.quoting = ORG_UNITS
    ctx.connections[CONNECTION] = quoting.connection(credential)
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2MetadataOperator(), {"connection": CONNECTION, "resource": "organisationUnits"}, ctx)
    text = f"{refused.value.message} {refused.value.params}"
    assert "Authorization: ***" in text
    for one in spelled:
        assert one not in text
