"""The ``dhis2`` connection kind: one DHIS2 instance, its credential, and the client that talks to it."""

from datetime import timedelta
from typing import ClassVar

from dhis2w_client import Dhis2Client, Profile, build_auth_provider
from pydantic import BaseModel, Field, SecretStr, model_validator

from dirigent_common import BlockModel, Duration, HealthReport
from dirigent_plugin import ConnectionKind, StepContext


class Dhis2ConnectionConfig(BlockModel):
    """Everything needed to talk to one DHIS2 instance, credentials included."""

    base_url: str = Field(min_length=1)
    """The instance root every request path is resolved against, version pin included.

    Name the host the instance actually answers on: a redirect to another origin arrives
    without the credential, because the client drops the Authorization header when the
    origin changes.
    """

    api_token: SecretStr | None = None
    """A personal access token, sent as ``Authorization: ApiToken``."""

    basic_username: str | None = None
    """The user half of HTTP basic authentication."""

    basic_password: SecretStr | None = None
    """The secret half of HTTP basic authentication."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The timeout applied to every request through this connection."""

    @model_validator(mode="after")
    def _require_one_credential(self) -> "Dhis2ConnectionConfig":
        """Reject a config carrying both credential kinds, neither, or half of the basic pair."""
        if self.api_token is not None and self.basic_username:
            raise ValueError("a dhis2 connection takes an api_token or basic credentials, not both")
        if self.api_token is None and not self.basic_username:
            raise ValueError("a dhis2 connection needs an api_token or basic credentials")
        if self.basic_username and self.basic_password is None:
            raise ValueError("basic credentials need a basic_password beside the basic_username")
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
    )


def client_for(ctx: StepContext, ref: str) -> Dhis2Client:
    """Build the dhis2w-client one block call uses, from the named connection's own config."""
    return build_client(ctx.connection(ref, Dhis2ConnectionConfig))


def settings_of(config: BaseModel) -> Dhis2ConnectionConfig:
    """Read a connection's config as this kind's own model, whichever model the caller held."""
    if isinstance(config, Dhis2ConnectionConfig):
        return config
    return Dhis2ConnectionConfig.model_validate(config.model_dump())


class Dhis2ConnectionKind(ConnectionKind):
    """The connection kind every block in this pack resolves its instance and credential through."""

    id: ClassVar[str] = "dhis2"
    config_model: ClassVar[type[BaseModel]] = Dhis2ConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Ask the instance what it is, proving the credential works, never raising.

        Connecting reads ``/api/system/info`` with the credential attached, so a healthy report
        means the credential is good and the version is the instance's own word for itself.
        """
        try:
            async with build_client(settings_of(config)) as client:
                version = client.raw_version
        except Exception as error:  # noqa: BLE001 - a health check reports its verdict, it never raises
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        return HealthReport(healthy=True, version=version or None)
