"""``dhis2.data_value_set_export``: read one data value set out of the instance."""

import time
from typing import Any, ClassVar, Final

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel, StorageUri
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import OperatorSpec, RemoteHandle, StepContext

#: Where data value sets are read and written.
DATA_VALUE_SETS_PATH: Final = "/api/dataValueSets.json"


class Dhis2DataValueSetExportConfig(BlockModel):
    """Which data value set to read, and where the answer goes."""

    connection: str
    """The code of the dhis2 connection naming the instance."""

    data_set: str
    """The uid of the data set to export."""

    period: str
    """An ISO period identifier, such as 2026Q1."""

    org_unit: str
    """The uid of the organisation unit to export for."""

    children: bool = False
    """Whether the org unit's descendants are included."""

    save_to: StorageUri | None = None
    """A storage URI to stream the export to, instead of carrying it inline.

    An export worth saving is one the next step reads from storage; without this the parsed
    document rides in the output.
    """


class Dhis2DataValueSetExportOutput(BlockModel):
    """What the export answered, which downstream steps reference by field."""

    json_body: JsonValue | None = None
    """The exported data value set, when it was not streamed to storage."""

    body_uri: str | None = None
    """Where the export was written, when ``save_to`` asked for it."""

    body_bytes: int | None = None
    """How many bytes were written there."""

    duration_ms: int


class Dhis2DataValueSetExportOperator(Dhis2Operator[Dhis2DataValueSetExportConfig, Dhis2DataValueSetExportOutput]):
    """Reads one data value set and hands it on, inline or as a stored artifact."""

    spec = OperatorSpec(
        id="dhis2.data_value_set_export",
        summary="Export a DHIS2 data value set.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetExportConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataValueSetExportOutput

    async def execute(
        self, config: Dhis2DataValueSetExportConfig, ctx: StepContext
    ) -> Dhis2DataValueSetExportOutput | RemoteHandle:
        """Read the set once, streaming to storage when the step asked for a file."""
        started = time.monotonic()
        json_body: JsonValue | None = None
        written: int | None = None
        async with client_for(ctx, config.connection) as client:
            try:
                if config.save_to:
                    written = await _save(client, config, ctx, config.save_to)
                else:
                    exported = await client.data_values.export(
                        data_set=config.data_set,
                        period=config.period,
                        org_unit=config.org_unit,
                        children=config.children,
                    )
                    json_body = exported.model_dump(mode="json", by_alias=True, exclude_none=True)
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {DATA_VALUE_SETS_PATH}") from error
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "data value set exported",
            data_set=config.data_set,
            period=config.period,
            org_unit=config.org_unit,
            bytes=written,
            duration_ms=duration,
        )
        return Dhis2DataValueSetExportOutput(
            json_body=json_body,
            body_uri=config.save_to if written is not None else None,
            body_bytes=written,
            duration_ms=duration,
        )


async def _save(client: Dhis2Client, config: Dhis2DataValueSetExportConfig, ctx: StepContext, uri: str) -> int:
    """Stream the export straight to storage and say how many bytes landed there.

    The writer has to be open before the instance answers, so a refusal would leave an empty
    object where the export was meant to be; a failed export leaves nothing at ``save_to``.
    """
    query: dict[str, Any] = {"dataSet": config.data_set, "period": config.period, "orgUnit": config.org_unit}
    if config.children:
        query["children"] = "true"
    try:
        async with ctx.storage.open_write(uri) as sink:
            written = await client.stream("GET", DATA_VALUE_SETS_PATH, sink, params=query)
    except (Dhis2ApiError, AuthenticationError):
        await ctx.storage.delete(uri)
        raise
    return written
