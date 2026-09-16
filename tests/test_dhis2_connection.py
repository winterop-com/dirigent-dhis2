"""Tests for the dhis2 connection kind and the clients built from it."""

import base64
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from dhis2server import serve
from dirigent_dhis2.connection import Dhis2ConnectionConfig, Dhis2ConnectionKind, build_client, settings_of


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


async def test_the_timeout_and_tls_setting_reach_the_pooled_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the connection says about time and certificates is what the client on the wire is built with."""
    serve(monkeypatch, base_url="http://x")
    patched = httpx2.AsyncClient
    built: list[dict[str, Any]] = []

    def record(**kwargs: Any) -> httpx2.AsyncClient:
        built.append(kwargs)
        return patched(**kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", record)
    config = Dhis2ConnectionConfig(
        base_url="http://x", api_token=SecretStr("t"), verify_tls=False, timeout=timedelta(seconds=7)
    )
    async with build_client(config):
        pass
    pooled = [kwargs for kwargs in built if kwargs.get("base_url") == "http://x"]
    assert pooled, "no client was bound to the instance"
    assert pooled[-1]["verify"] is False
    assert pooled[-1]["timeout"].read == 7.0


def test_settings_of_reads_a_foreign_model_as_this_kind() -> None:
    """A caller holding the row under another model still gets this kind's config, secret and all."""

    class Row(BaseModel):
        base_url: str
        api_token: SecretStr

    settings = settings_of(Row(base_url="http://x", api_token=SecretStr("t")))
    assert isinstance(settings, Dhis2ConnectionConfig)
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "t"
    assert settings.timeout == timedelta(seconds=30)


def test_settings_of_hands_its_own_model_back() -> None:
    config = Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t"))
    assert settings_of(config) is config


def test_a_connection_with_both_credentials_is_refused() -> None:
    with pytest.raises(ValidationError, match="not both"):
        Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t"), basic_username="u")


def test_a_token_beside_a_basic_password_is_refused() -> None:
    """The password would be silently ignored, which is the kind of config that hides a mistake."""
    with pytest.raises(ValidationError, match="not both"):
        Dhis2ConnectionConfig(base_url="http://x", api_token=SecretStr("t"), basic_password=SecretStr("p"))


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
