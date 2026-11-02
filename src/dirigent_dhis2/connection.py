"""The ``dhis2`` connection kind: one DHIS2 instance, its credential, and the client that talks to it."""

import base64
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import ClassVar, Final

import httpx2
from dhis2w_client import Dhis2Client, Profile, build_auth_provider
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from dirigent_common import BlockModel, Duration, HealthReport, Size, scrub, spellings
from dirigent_dhis2.messages import (
    BAD_API_TOKEN,
    BOTH_CREDENTIALS,
    CONNECTION_UNREACHABLE,
    NO_BASIC_PASSWORD,
    NO_CREDENTIAL,
    REDIRECT_REFUSED,
)
from dirigent_dhis2.web import SENT_CREDENTIAL, describe
from dirigent_plugin import BlockFailure, ConnectionKind, ErrorClass, StepContext

#: The domains ``base_url``'s redirect may move within, between any two hosts under them.
ADOPTABLE_DOMAINS: Final = ("dhis2.org",)

#: What an API token may hold: visible ASCII, the only text a header value carries unchanged.
API_TOKEN: Final = re.compile(r"[\x21-\x7e]+")


class Dhis2ConnectionConfig(BlockModel):
    """Everything needed to talk to one DHIS2 instance, credentials included."""

    model_config = ConfigDict(hide_input_in_errors=True)

    base_url: str = Field(min_length=1)
    """The instance root every request path is resolved against, version pin included.

    A root that redirects is followed once, without the credential, and the target is used
    when it keeps the scheme, answers like DHIS2, and is this host, a subdomain of it, or
    under ``dhis2.org`` beside it.
    """

    api_token: SecretStr | None = None
    """A personal access token, sent as ``Authorization: ApiToken``: visible ASCII with no whitespace."""

    basic_username: str | None = None
    """The user half of HTTP basic authentication."""

    basic_password: SecretStr | None = None
    """The secret half of HTTP basic authentication."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    follow_redirects_with_auth: bool = False
    """Whether the URL ``base_url`` redirects to is used whatever its host or scheme, credential and all."""

    timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The timeout applied to each read of every request through this connection."""

    request_deadline: Duration = Field(default=timedelta(minutes=10), gt=timedelta(0))
    """The longest one request through this connection may take, start to last byte."""

    max_response: Size = Field(default=64 * 1024 * 1024, ge=1)
    """The most one response through this connection may decode to; a larger one is refused."""

    @field_validator("api_token")
    @classmethod
    def _token_fits_a_header(cls, token: SecretStr | None) -> SecretStr | None:
        """Reject a token that cannot be sent as a header value, without saying what it held."""
        if token is not None and API_TOKEN.fullmatch(token.get_secret_value()) is None:
            raise ValueError(BAD_API_TOKEN.render())
        return token

    @model_validator(mode="after")
    def _require_one_credential(self) -> "Dhis2ConnectionConfig":
        """Reject a config carrying both credential kinds, neither, or half of the basic pair."""
        if self.api_token is not None and (self.basic_username or self.basic_password is not None):
            raise ValueError(BOTH_CREDENTIALS.render())
        if self.api_token is None and not self.basic_username:
            raise ValueError(NO_CREDENTIAL.render())
        if self.basic_username and self.basic_password is None:
            raise ValueError(NO_BASIC_PASSWORD.render())
        return self


def _profile(config: Dhis2ConnectionConfig) -> Profile:
    """Map the connection's credential onto the profile dhis2w-client authenticates from."""
    if config.api_token is not None:
        return Profile(base_url=config.base_url, auth="pat", token=config.api_token.get_secret_value())
    password = config.basic_password.get_secret_value() if config.basic_password else ""
    return Profile(base_url=config.base_url, auth="basic", username=config.basic_username, password=password)


def credential_spellings(config: Dhis2ConnectionConfig) -> frozenset[str]:
    """Every spelling of the credential the connection sends that an instance or a proxy may quote back.

    That is the ``Authorization`` value, the credential after its scheme, and a basic pair as
    the user and password it encodes.
    """
    if config.api_token is not None:
        token = config.api_token.get_secret_value()
        written = {f"ApiToken {token}", token}
    else:
        pair = f"{config.basic_username}:{config.basic_password.get_secret_value() if config.basic_password else ''}"
        encoded = base64.b64encode(pair.encode()).decode()
        written = {f"Basic {encoded}", encoded, pair}
    return frozenset(spelled for one in written for spelled in spellings(one))


def answers_for(configured: str, host: str) -> bool:
    """Whether a credentialed request may go to ``host`` for a ``base_url`` on ``configured``.

    That is the same host, a subdomain of it, or both under a domain in ``ADOPTABLE_DOMAINS``.
    Sharing their last labels does not qualify two hosts, as ``dhis2.health.co.uk`` and
    ``attacker.co.uk`` do.
    """
    configured, host = configured.rstrip("."), host.rstrip(".")
    if host == configured or host.endswith(f".{configured}"):
        return True
    return any(configured.endswith(f".{domain}") and host.endswith(f".{domain}") for domain in ADOPTABLE_DOMAINS)


def stays_on_the_instance(config: Dhis2ConnectionConfig) -> Callable[[httpx2.Request], Awaitable[None]]:
    """Build the request hook that refuses a credentialed request ``answers_for`` does not allow."""
    configured = httpx2.URL(config.base_url).host

    async def refuse_another_host(request: httpx2.Request) -> None:
        if not answers_for(configured, request.url.host):
            raise BlockFailure(
                REDIRECT_REFUSED, error_class=ErrorClass.REJECTED, configured=configured, target=request.url.host
            )

    return refuse_another_host


def build_client(config: Dhis2ConnectionConfig) -> Dhis2Client:
    """Build a dhis2w-client bound to the connection's URL, credential, TLS setting, and limits.

    The client is returned unconnected: entering it as an async context manager opens the pool
    and detects the instance's version from ``/api/system/info`` the dhis2w way. Its pool sends
    the credential only where ``answers_for`` allows, unless ``follow_redirects_with_auth`` is on.
    """
    return Dhis2Client(
        config.base_url,
        auth=build_auth_provider(_profile(config)),
        timeout=config.timeout.total_seconds(),
        verify=config.verify_tls,
        follow_redirects_with_auth=config.follow_redirects_with_auth,
        event_hooks=None if config.follow_redirects_with_auth else {"request": [stays_on_the_instance(config)]},
        max_response_bytes=config.max_response,
        deadline=config.request_deadline.total_seconds(),
    )


def client_for(ctx: StepContext, ref: str) -> Dhis2Client:
    """Build the dhis2w-client one block call uses, from the named connection's own config.

    What the instance says through it is described without the credential it sends.
    """
    config = ctx.connection(ref, Dhis2ConnectionConfig)
    SENT_CREDENTIAL.set(credential_spellings(config))
    return build_client(config)


def settings_of(config: BaseModel) -> Dhis2ConnectionConfig:
    """Read a connection's config as this kind's own model, whichever model the caller held."""
    if isinstance(config, Dhis2ConnectionConfig):
        return config
    return Dhis2ConnectionConfig.model_validate(config.model_dump())


#: A ring with a health cross in it, drawn on the 24-unit grid every kind's mark is drawn on.
DHIS2_MARK = (
    "M2 12a10 10 0 1 0 20 0a10 10 0 1 0-20 0Z"
    "M4 12a8 8 0 1 1 16 0a8 8 0 1 1-16 0Z"
    "M10.5 7h3v3.5H17v3h-3.5V17h-3v-3.5H7v-3h3.5Z"
)


class Dhis2ConnectionKind(ConnectionKind):
    """The connection kind every block in this pack resolves its instance and credential through."""

    id: ClassVar[str] = "dhis2"
    config_model: ClassVar[type[BaseModel]] = Dhis2ConnectionConfig
    mark: ClassVar[str | None] = DHIS2_MARK

    async def check(self, config: BaseModel) -> HealthReport:
        """Ask the instance what it is, proving the credential works, never raising.

        Connecting reads ``/api/system/info`` with the credential attached, so a healthy report
        means the credential is good and the version is the instance's own word for itself.
        """
        secrets: frozenset[str] = frozenset()
        try:
            settings = settings_of(config)
            secrets = credential_spellings(settings)
            SENT_CREDENTIAL.set(secrets)
            async with build_client(settings) as client:
                version = client.raw_version
        except Exception as error:  # noqa: BLE001 - a health check reports its verdict, it never raises
            detail = scrub(_reason(error), secrets)
            return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=detail))
        return HealthReport(healthy=True, version=version or None)


def _reason(error: Exception) -> str:
    """Say why a check failed, in the instance's own words when it gave any.

    A transport failure has no words of its own, and some carry an empty ``str``: the class is
    the last thing left to say rather than the first thing said.
    """
    if isinstance(error, Dhis2ApiError | AuthenticationError):
        return describe(error)
    return str(error) or type(error).__name__
