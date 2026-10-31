"""What a connection does when ``base_url`` redirects: where the credential goes, and where it does not."""

import httpx2
import pytest
from pydantic import SecretStr

from dhis2server import CONNECTION, Dhis2Server, json, serve
from dirigent_dhis2 import connection as kind
from dirigent_dhis2.connection import Dhis2ConnectionConfig, Dhis2ConnectionKind
from dirigent_dhis2.metadata import Dhis2MetadataOperator
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

#: Hosts that share only their last labels, each pair answered by different registrants.
ANOTHER_REGISTRANT = [
    pytest.param("dhis2.health.co.uk", "attacker.co.uk", id="public-suffix"),
    pytest.param("health.co.uk", "attacker.co.uk", id="registrable-under-public-suffix"),
    pytest.param("one.azurewebsites.net", "other.azurewebsites.net", id="shared-platform"),
    pytest.param("one.github.io", "other.github.io", id="shared-pages"),
    pytest.param("dhis2.example.org", "hmis.example.org", id="sibling"),
    pytest.param("dhis2.example.org", "example.org", id="parent"),
]


def _redirecting(monkeypatch: pytest.MonkeyPatch, configured: str, target: str) -> Dhis2Server:
    """Script a root that redirects to a host answering like DHIS2 on every path a client may read."""
    dhis2 = serve(monkeypatch, base_url=f"https://{target}", version="2.43.0")
    dhis2.instance(base_url=f"https://{configured}", version="2.43.0")
    dhis2.get(f"https://{configured}/").answers(httpx2.Response(302, headers={"location": f"https://{target}/"}))
    for host in (configured, target):
        dhis2.get(f"https://{host}/api/organisationUnits").answers(json(200, {"organisationUnits": []}))
    return dhis2


def _credentialed_at(dhis2: Dhis2Server, host: str) -> list[str]:
    """Every path on one host that received the Authorization header."""
    return [
        request.url.path
        for route in dhis2.routes.values()
        for request in route.requests
        if request.url.host == host and "authorization" in request.headers
    ]


def _token(host: str) -> Dhis2ConnectionConfig:
    return Dhis2ConnectionConfig(base_url=f"https://{host}", api_token=SecretStr("DUMMYTOKEN4567"))


@pytest.mark.parametrize(("configured", "target"), ANOTHER_REGISTRANT)
async def test_a_check_never_sends_the_credential_to_another_registrant(
    monkeypatch: pytest.MonkeyPatch, configured: str, target: str
) -> None:
    dhis2 = _redirecting(monkeypatch, configured, target)
    await Dhis2ConnectionKind().check(_token(configured))
    assert _credentialed_at(dhis2, target) == []


@pytest.mark.parametrize(("configured", "target"), ANOTHER_REGISTRANT)
async def test_a_block_never_sends_the_credential_to_another_registrant(
    monkeypatch: pytest.MonkeyPatch, ctx: FakeContext, configured: str, target: str
) -> None:
    dhis2 = _redirecting(monkeypatch, configured, target)
    ctx.connections[CONNECTION] = _token(configured)
    try:
        await call_block(Dhis2MetadataOperator(), {"connection": CONNECTION, "resource": "organisationUnits"}, ctx)
    except BlockFailure as refused:
        assert refused.code == "dhis2.connection.redirect_refused"
        assert refused.error_class is ErrorClass.REJECTED
    assert _credentialed_at(dhis2, target) == []


@pytest.mark.parametrize(
    ("configured", "target"),
    [
        pytest.param("play.dhis2.org", "play.im.dhis2.org", id="the-play-alias"),
        pytest.param("example.org", "dhis2.example.org", id="a-subdomain"),
        pytest.param("dhis2.example.org", "eu.dhis2.example.org", id="a-deeper-subdomain"),
    ],
)
async def test_a_host_the_configured_host_answers_for_is_followed_with_the_credential(
    monkeypatch: pytest.MonkeyPatch, configured: str, target: str
) -> None:
    dhis2 = _redirecting(monkeypatch, configured, target)
    report = await Dhis2ConnectionKind().check(_token(configured))
    assert report.healthy is True
    assert _credentialed_at(dhis2, target) == ["/api/system/info"]


async def test_following_redirects_with_auth_still_goes_anywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    dhis2 = _redirecting(monkeypatch, "dhis2.health.co.uk", "attacker.co.uk")
    config = Dhis2ConnectionConfig(
        base_url="https://dhis2.health.co.uk", api_token=SecretStr("t"), follow_redirects_with_auth=True
    )
    report = await Dhis2ConnectionKind().check(config)
    assert report.healthy is True
    assert _credentialed_at(dhis2, "attacker.co.uk") == ["/api/system/info"]


async def test_a_refused_host_is_named_with_a_code_and_never_retried() -> None:
    guard = kind.stays_on_the_instance(_token("dhis2.health.co.uk"))
    with pytest.raises(BlockFailure) as refused:
        await guard(httpx2.Request("GET", "https://attacker.co.uk/api/system/info"))
    assert refused.value.code == "dhis2.connection.redirect_refused"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert "attacker.co.uk" in refused.value.message
    await guard(httpx2.Request("GET", "https://dhis2.health.co.uk/api/system/info"))


@pytest.mark.parametrize(
    ("configured", "host", "allowed"),
    [
        ("dhis2.example.org", "dhis2.example.org", True),
        ("dhis2.example.org.", "dhis2.example.org", True),
        ("127.0.0.1", "127.0.0.1", True),
        ("example.org", "a.b.example.org", True),
        ("play.dhis2.org", "play.im.dhis2.org", True),
        ("dhis2.org", "play.im.dhis2.org", True),
        ("dhis2.example.org", "xdhis2.example.org", False),
        ("evil-dhis2.org", "play.dhis2.org", False),
        ("play.dhis2.org", "dhis2.org.attacker.example", False),
        ("127.0.0.1", "127.0.0.2", False),
    ],
)
def test_the_rule_on_the_host(configured: str, host: str, allowed: bool) -> None:
    assert kind.answers_for(configured, host) is allowed
