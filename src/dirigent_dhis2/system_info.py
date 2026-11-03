"""``dhis2.system_info``: read what the instance says about itself at ``/api/system/info``."""

import time
from typing import ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import ConnectionRef, OperatorSpec, StepContext

#: Where an instance describes itself.
SYSTEM_INFO_PATH: Final = "/api/system/info"

#: The output field each lifted ``/api/system/info`` key is carried under.
LIFTED: Final = {
    "version": "version",
    "revision": "revision",
    "buildTime": "build_time",
    "systemId": "system_id",
    "systemName": "system_name",
    "instanceBaseUrl": "instance_base_url",
    "serverDate": "server_date",
    "serverTimeZoneId": "server_time_zone_id",
    "calendar": "calendar",
    "dateFormat": "date_format",
    "lastAnalyticsTableSuccess": "last_analytics_table_success",
    "lastAnalyticsTableRuntime": "last_analytics_table_runtime",
    "intervalSinceLastAnalyticsTableSuccess": "interval_since_last_analytics_table_success",
}


class Dhis2SystemInfoConfig(BlockModel):
    """Which instance to describe.

    One read of ``/api/system/info``: the version, build, server clock and analytics state a
    health check or a system report starts from. It follows the connection's redirect rules like
    every other ``dhis2.*`` block, so it needs no ``follow_redirects_with_auth``.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""


class Dhis2SystemInfoOutput(BlockModel):
    """What the instance said about itself, the fields a report reads lifted out by name."""

    version: str | None = None
    """The DHIS2 version, such as ``2.42.1``."""

    revision: str | None = None
    """The source revision the running build was made from."""

    build_time: str | None = None
    """When the running build was made, as the instance writes it."""

    system_id: str | None = None
    """The instance's own system identifier."""

    system_name: str | None = None
    """The name the instance is configured with, its application title."""

    instance_base_url: str | None = None
    """The base URL the instance believes it is served at."""

    server_date: str | None = None
    """The instance's clock at the moment it answered."""

    server_time_zone_id: str | None = None
    """The time zone the server runs in, such as ``Etc/UTC``."""

    calendar: str | None = None
    """The calendar the instance keeps its periods in, such as ``iso8601`` or ``ethiopian``."""

    date_format: str | None = None
    """The date format the instance shows dates in, such as ``yyyy-mm-dd``."""

    last_analytics_table_success: str | None = None
    """When the analytics tables were last generated successfully."""

    last_analytics_table_runtime: str | None = None
    """How long that last successful analytics table generation took, as the instance words it."""

    interval_since_last_analytics_table_success: str | None = None
    """How long ago that was, as the instance words it."""

    other: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    """Every other key of the answer, as the instance wrote it: the database, the Java runtime,
    the memory and processor counts, and any of the named keys that did not hold a string."""

    duration_ms: int
    """How long the read took."""


def describe_system(body: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Split an ``/api/system/info`` answer into the lifted fields and ``other``.

    A named key is lifted only when it holds a string; anything else stays under ``other``
    as written, so no value is lost and no field holds a type it does not declare.
    """
    lifted: dict[str, JsonValue] = {}
    other: dict[str, JsonValue] = {}
    for key, value in body.items():
        field = LIFTED.get(key)
        if field is not None and isinstance(value, str):
            lifted[field] = value
        else:
            other[key] = value
    return {**lifted, "other": other}


class Dhis2SystemInfoOperator(Dhis2Operator[Dhis2SystemInfoConfig, Dhis2SystemInfoOutput]):
    """Reads the instance's system information and hands it on, its common fields by name."""

    spec = OperatorSpec(
        id="dhis2.system_info",
        summary="Read a DHIS2 instance's version, build, server clock and analytics state.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2SystemInfoConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2SystemInfoOutput

    async def execute(self, config: Dhis2SystemInfoConfig, ctx: StepContext) -> Dhis2SystemInfoOutput:
        """Read ``/api/system/info`` once, classifying an HTTP refusal."""
        started = time.monotonic()
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.get_raw(SYSTEM_INFO_PATH)
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {SYSTEM_INFO_PATH}") from error
        duration = round((time.monotonic() - started) * 1000)
        output = Dhis2SystemInfoOutput.model_validate({**describe_system(body), "duration_ms": duration})
        ctx.log.info("system info read", version=output.version, duration_ms=duration)
        return output
