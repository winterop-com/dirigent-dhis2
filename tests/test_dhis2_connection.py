"""Tests for the dhis2 connection kind and the clients built from it."""

import base64

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from dhis2server import serve
from dirigent_dhis2.connection import Dhis2ConnectionConfig, Dhis2ConnectionKind, build_client


async def _authorization_sent(monkeypatch: pytest.MonkeyPatch, config: Dhis2ConnectionConfig) -> str:
    """Open a client from the config and read the Authorization header it put on the wire."""
    dhis2 = serve(monkeypatch, base_url=config.base_url)
    route = dhis2.get(f"{config.base_url}/api/me").answers(httpx2.Response(200, json={}))
    async with build_client(config) as client:
        await client.get_raw("/api/me")
    return route.last.headers["authorization"]


async def test_an_api_token_connection_sends_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("d2pat_abc"))
    assert await _authorization_sent(monkeypatch, config) == "ApiToken d2pat_abc"


async def test_a_basic_auth_connection_sends_the_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Dhis2ConnectionConfig(base_url="http://x", basic_username="u", basic_password=SecretStr("p"))
    expected = "Basic " + base64.b64encode(b"u:p").decode()
    assert await _authorization_sent(monkeypatch, config) == expected


def test_a_connection_with_both_credentials_is_refused() -> None:
    with pytest.raises(ValidationError, match="not both"):
        Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t"), basic_username="u")


def test_a_connection_with_no_credential_is_refused() -> None:
    with pytest.raises(ValidationError, match="needs an api_token or basic credentials"):
        Dhis2ConnectionConfig(base_url="http://x")


def test_a_basic_username_without_a_password_is_refused() -> None:
    with pytest.raises(ValidationError, match="need a basic_password"):
        Dhis2ConnectionConfig(base_url="http://x", basic_username="u")


async def test_the_connection_check_reports_the_instance_version(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, base_url="http://x", version="2.43.1")
    report = await Dhis2ConnectionKind().check(Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t")))
    assert report.healthy is True
    assert report.version == "2.43.1"


async def test_a_refused_credential_reports_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    dhis2 = serve(monkeypatch, base_url="http://x")
    dhis2.get("http://x/api/system/info").answers(httpx2.Response(401, json={"httpStatus": "Unauthorized"}))
    report = await Dhis2ConnectionKind().check(Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("bad")))
    assert report.healthy is False
    assert "401" in (report.detail or "")


async def test_an_unreachable_instance_reports_rather_than_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    dhis2 = serve(monkeypatch, base_url="http://x")
    dhis2.get("http://x/").raises(httpx2.ConnectError("refused"))
    dhis2.get("http://x/api/system/info").raises(httpx2.ConnectError("refused"))
    report = await Dhis2ConnectionKind().check(Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t")))
    assert report.healthy is False
    assert "ConnectError" in (report.detail or "")


async def test_an_unsupported_instance_version_reports_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, base_url="http://x", version="2.40.0")
    report = await Dhis2ConnectionKind().check(Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t")))
    assert report.healthy is False
    assert "UnsupportedVersionError" in (report.detail or "")
