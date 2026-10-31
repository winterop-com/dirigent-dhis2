"""The ``dhis2`` connection kind: one DHIS2 instance, its credential, and the client that talks to it."""

import re
from datetime import timedelta
from typing import ClassVar, Final

from dhis2w_client import Dhis2Client, Profile, build_auth_provider
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from dirigent_common import BlockModel, Duration, HealthReport
from dirigent_dhis2.messages import (
    BAD_API_TOKEN,
    BOTH_CREDENTIALS,
    CONNECTION_UNREACHABLE,
    NO_BASIC_PASSWORD,
    NO_CREDENTIAL,
)
from dirigent_dhis2.web import describe
from dirigent_plugin import ConnectionKind, StepContext

#: What an API token may hold: visible ASCII, the only text a header value carries unchanged.
API_TOKEN: Final = re.compile(r"[\x21-\x7e]+")


class Dhis2ConnectionConfig(BlockModel):
    """Everything needed to talk to one DHIS2 instance, credentials included."""

    model_config = ConfigDict(hide_input_in_errors=True)

    base_url: str = Field(min_length=1)
    """The instance root every request path is resolved against, version pin included.

    A root that redirects is followed once, without the credential, and the target is used
    when it keeps the scheme, shares the registrable domain and answers like DHIS2.
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
    """The timeout applied to every request through this connection."""

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


def build_client(config: Dhis2ConnectionConfig) -> Dhis2Client:
    """Build a dhis2w-client bound to the connection's URL, credential, TLS setting, and timeout.

    The client is returned unconnected: entering it as an async context manager opens the pool
    and detects the instance's version from ``/api/system/info`` the dhis2w way.
    """
    return Dhis2Client(
        config.base_url,
        auth=build_auth_provider(_profile(config)),
        timeout=config.timeout.total_seconds(),
        verify=config.verify_tls,
        follow_redirects_with_auth=config.follow_redirects_with_auth,
    )


def client_for(ctx: StepContext, ref: str) -> Dhis2Client:
    """Build the dhis2w-client one block call uses, from the named connection's own config."""
    return build_client(ctx.connection(ref, Dhis2ConnectionConfig))


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
        try:
            async with build_client(settings_of(config)) as client:
                version = client.raw_version
        except Exception as error:  # noqa: BLE001 - a health check reports its verdict, it never raises
            return HealthReport(healthy=False, detail=CONNECTION_UNREACHABLE.render(detail=_reason(error)))
        return HealthReport(healthy=True, version=version or None)


def _reason(error: Exception) -> str:
    """Say why a check failed, in the instance's own words when it gave any.

    A transport failure has no words of its own, and some carry an empty ``str``: the class is
    the last thing left to say rather than the first thing said.
    """
    if isinstance(error, Dhis2ApiError | AuthenticationError):
        return describe(error)
    return str(error) or type(error).__name__
