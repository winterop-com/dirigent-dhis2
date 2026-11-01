"""What one answer may cost through a connection, against a hostile instance on loopback."""

import asyncio
import gzip
import json
import tracemalloc
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import pytest
import pytest_asyncio
from dhis2w_client.errors import RequestDeadlineError, ResponseTooLargeError
from pydantic import SecretStr, ValidationError

from dhis2server import CONNECTION
from dirigent_dhis2.complete import Dhis2DataSetCompleteSensor
from dirigent_dhis2.connection import Dhis2ConnectionConfig, Dhis2ConnectionKind
from dirigent_dhis2.imports import Dhis2DataValueSetImportOperator
from dirigent_dhis2.metadata import Dhis2MetadataOperator
from dirigent_dhis2.web import classify
from dirigent_plugin import ErrorClass, NotYet
from dirigent_testing import FakeContext, call_block

MIB = 1024 * 1024
ROOT = "/"
INFO = "/api/system/info"
ORG_UNITS = "/api/organisationUnits"
IMPORT = "/api/dataValueSets"
REGISTRATIONS = "/api/completeDataSetRegistrations"

Handler = Callable[[asyncio.StreamWriter], Awaitable[None]]


def _bomb(decoded_bytes: int) -> bytes:
    """A JSON object of about that many decoded bytes, gzipped twice: well under a KiB per MiB on the wire."""
    document = json.dumps({"version": "2.43.0", "pad": "x" * decoded_bytes}).encode()
    return gzip.compress(gzip.compress(document))


def _answer(body: bytes, *headers: str) -> Handler:
    """A handler that writes one complete 200."""

    async def write(writer: asyncio.StreamWriter) -> None:
        head = ["HTTP/1.1 200 OK", f"Content-Length: {len(body)}", "Connection: close", *headers]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
        await writer.drain()

    return write


def _double_gzip(decoded_bytes: int) -> Handler:
    return _answer(_bomb(decoded_bytes), "Content-Encoding: gzip, gzip", "Content-Type: application/json")


async def _drip(writer: asyncio.StreamWriter) -> None:
    """A handler that never finishes its body, sending a byte well inside any read timeout."""
    writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
    while True:
        writer.write(b"1\r\nx\r\n")
        await writer.drain()
        await asyncio.sleep(0.01)


class Instance:
    """A loopback server answering each path with its handler, a small DHIS2 answer by default."""

    def __init__(self) -> None:
        """Script the two reads a client opens with."""
        self.handlers: dict[str, Handler] = {
            ROOT: _answer(b"<html></html>"),
            INFO: _answer(b'{"version": "2.43.0"}', "Content-Type: application/json"),
        }
        self.url = ""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Answer one request and close, reading whatever body it carries."""
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            if b"chunked" in head.lower():
                while size := int((await reader.readline()).strip() or b"0", 16):
                    await reader.readexactly(size + 2)
                await reader.readline()
            path = head.split(b" ", 2)[1].decode().split("?")[0]
            await self.handlers[path](writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def connection(self, **limits: object) -> Dhis2ConnectionConfig:
        """A connection to this instance, with a dummy token."""
        return Dhis2ConnectionConfig.model_validate(
            {"base_url": self.url, "api_token": SecretStr("DUMMYTOKEN4567"), **limits}
        )


@pytest_asyncio.fixture
async def instance() -> AsyncIterator[Instance]:
    served = Instance()
    listening = await asyncio.start_server(served.handle, "127.0.0.1", 0)
    served.url = f"http://127.0.0.1:{listening.sockets[0].getsockname()[1]}"
    try:
        yield served
    finally:
        listening.close()


async def test_a_version_probe_past_the_default_limit_fails_the_check(instance: Instance) -> None:
    """With nothing configured, a few KiB on the wire no longer become 65 MiB in the worker."""
    instance.handlers[INFO] = _double_gzip(65 * MIB)
    report = await Dhis2ConnectionKind().check(instance.connection())
    assert report.healthy is False
    assert INFO in (report.detail or "")


async def test_a_block_read_past_the_limit_is_rejected_at_little_cost(ctx: FakeContext, instance: Instance) -> None:
    ctx.connections[CONNECTION] = instance.connection(max_response="1MB")
    operator = Dhis2MetadataOperator()
    instance.handlers[ORG_UNITS] = _answer(b'{"organisationUnits": []}')
    await call_block(operator, {"connection": CONNECTION, "resource": "organisationUnits"}, ctx)
    instance.handlers[ORG_UNITS] = _double_gzip(40 * MIB)
    tracemalloc.start()
    try:
        with pytest.raises(ResponseTooLargeError) as refused:
            await call_block(operator, {"connection": CONNECTION, "resource": "organisationUnits"}, ctx)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 16 * MIB
    assert classify(refused.value) is ErrorClass.REJECTED
    assert operator.classify_error(refused.value) is ErrorClass.REJECTED
    assert ORG_UNITS in str(refused.value)
    assert "DUMMYTOKEN" not in str(refused.value)


async def test_a_read_within_the_limit_still_answers(ctx: FakeContext, instance: Instance) -> None:
    body = json.dumps({"organisationUnits": [{"id": "ImspTQPwCqd"}]}).encode()
    instance.handlers[ORG_UNITS] = _answer(gzip.compress(body), "Content-Encoding: gzip")
    ctx.connections[CONNECTION] = instance.connection(max_response="1MB")
    output = await call_block(Dhis2MetadataOperator(), {"connection": CONNECTION, "resource": "organisationUnits"}, ctx)
    assert output.model_dump()["body"] == {"organisationUnits": [{"id": "ImspTQPwCqd"}]}


async def test_an_import_answer_past_the_limit_is_held_to_it_too(ctx: FakeContext, instance: Instance) -> None:
    instance.handlers[IMPORT] = _double_gzip(8 * MIB)
    ctx.connections[CONNECTION] = instance.connection(max_response="1MB")
    with pytest.raises(ResponseTooLargeError):
        await call_block(
            Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": {"dataValues": []}}, ctx
        )


async def test_a_sensor_opening_on_a_bomb_is_refused_before_it_reads(ctx: FakeContext, instance: Instance) -> None:
    instance.handlers[INFO] = _double_gzip(8 * MIB)
    instance.handlers[REGISTRATIONS] = _answer(b'{"completeDataSetRegistrations": []}')
    ctx.connections[CONNECTION] = instance.connection(max_response="1MB")
    config = {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "ImspTQPwCqd"}
    with pytest.raises(ResponseTooLargeError):
        await call_block(Dhis2DataSetCompleteSensor(), config, ctx)
    instance.handlers[INFO] = _answer(b'{"version": "2.43.0"}')
    assert isinstance(await call_block(Dhis2DataSetCompleteSensor(), config, ctx), NotYet)


async def test_the_root_probe_reads_no_body_at_any_size(instance: Instance) -> None:
    await Dhis2ConnectionKind().check(instance.connection())
    instance.handlers[ROOT] = _double_gzip(40 * MIB)
    tracemalloc.start()
    try:
        report = await Dhis2ConnectionKind().check(instance.connection())
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert report.healthy is True
    assert peak < 16 * MIB


async def test_a_drip_fails_a_block_at_the_deadline_as_transient(ctx: FakeContext, instance: Instance) -> None:
    instance.handlers[ORG_UNITS] = _drip
    ctx.connections[CONNECTION] = instance.connection(request_deadline=timedelta(milliseconds=200), timeout="1s")
    operator = Dhis2MetadataOperator()
    async with asyncio.timeout(10):
        with pytest.raises(RequestDeadlineError) as refused:
            await call_block(operator, {"connection": CONNECTION, "resource": "organisationUnits"}, ctx)
    assert operator.classify_error(refused.value) is ErrorClass.TRANSIENT


async def test_a_drip_on_the_version_probe_fails_the_check_at_the_deadline(instance: Instance) -> None:
    instance.handlers[INFO] = _drip
    config = instance.connection(request_deadline=timedelta(milliseconds=200), timeout="1s")
    async with asyncio.timeout(10):
        report = await Dhis2ConnectionKind().check(config)
    assert report.healthy is False
    assert INFO in (report.detail or "")


def test_the_limits_read_as_a_size_and_a_duration() -> None:
    config = Dhis2ConnectionConfig.model_validate(
        {"base_url": "http://x", "api_token": "t", "max_response": "16KB", "request_deadline": "2m"}
    )
    assert config.max_response == 16 * 1024
    assert config.request_deadline == timedelta(minutes=2)


def test_the_limits_have_defaults() -> None:
    config = Dhis2ConnectionConfig.model_validate({"base_url": "http://x", "api_token": "t"})
    assert config.max_response == 64 * MIB
    assert config.request_deadline == timedelta(minutes=10)


@pytest.mark.parametrize(("field", "value"), [("max_response", 0), ("request_deadline", "0s")])
def test_a_limit_of_nothing_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Dhis2ConnectionConfig.model_validate({"base_url": "http://x", "api_token": "t", field: value})
