"""``dhis2.data_value_set_export``: read one data value set out of the instance."""

import time
from typing import ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import OperatorSpec, RemoteHandle, StepContext

#: Where data value sets are read and written.
DATA_VALUE_SETS_PATH: Final = "/api/dataValueSets.json"


class Dhis2DataValueSetExportConfig(BlockModel):
    """Which data value set to read."""

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


class Dhis2DataValueSetExportOutput(BlockModel):
    """What the export answered, which downstream steps reference by field."""

    body: JsonValue | None = None
    """The exported data value set, the value the next step works on."""

    duration_ms: int


class Dhis2DataValueSetExportOperator(Dhis2Operator[Dhis2DataValueSetExportConfig, Dhis2DataValueSetExportOutput]):
    """Reads one data value set and hands the parsed document on."""

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
        """Read the set once and answer with the document."""
        started = time.monotonic()
        async with client_for(ctx, config.connection) as client:
            try:
                exported = await client.data_values.export(
                    data_set=config.data_set,
                    period=config.period,
                    org_unit=config.org_unit,
                    children=config.children,
                )
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {DATA_VALUE_SETS_PATH}") from error
        body: JsonValue = exported.model_dump(mode="json", by_alias=True, exclude_none=True)
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info(
            "data value set exported",
            data_set=config.data_set,
            period=config.period,
            org_unit=config.org_unit,
            duration_ms=duration,
        )
        return Dhis2DataValueSetExportOutput(body=body, duration_ms=duration)
