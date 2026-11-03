"""``dhis2.predictor_run``: run predictors over a date range, writing the values they predict."""

import re
from typing import ClassVar, Final

from dhis2w_client import WebMessageResponse
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, model_validator

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.messages import PREDICTOR_BOTH_TARGETS
from dirigent_dhis2.reports import count
from dirigent_dhis2.validation_run import ISO_DATE
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import ConnectionRef, OperatorSpec, StepContext

#: How the instance says how many values a run predicted.
GENERATED: Final = re.compile(r"Generated (\d+) predictions?")


class Dhis2PredictorRunConfig(BlockModel):
    """Which predictors to run, and over which dates.

    A predictor computes a value from other data, such as a moving average or a target, and
    writes it as an ordinary data value. One predictor, one predictor group, or every predictor
    on the instance runs, for every period of each predictor's own type that falls in the range.
    DHIS2 has no dry run for this: the predicted values are written.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    start_date: str = Field(pattern=ISO_DATE)
    """The ISO date the range starts on, such as 2026-01-01."""

    end_date: str = Field(pattern=ISO_DATE)
    """The ISO date the range ends on, such as 2026-03-31."""

    predictor: str | None = Field(default=None, pattern=UID_PATTERN)
    """The uid of one predictor to run."""

    predictor_group: str | None = Field(default=None, pattern=UID_PATTERN)
    """The uid of a predictor group whose members run. With neither this nor ``predictor``,
    every predictor on the instance runs."""

    @model_validator(mode="after")
    def _one_target(self) -> "Dhis2PredictorRunConfig":
        """Refuse a run naming both a predictor and a group."""
        if self.predictor is not None and self.predictor_group is not None:
            raise ValueError(PREDICTOR_BOTH_TARGETS.render())
        return self


class Dhis2PredictorRunOutput(BlockModel):
    """What the run said it predicted."""

    predictions: int
    """How many values the run predicted, as the instance counted them."""

    inserted: int | None = None
    """How many predicted values were new, where the instance reported it."""

    updated: int | None = None
    """How many replaced a value predicted before, where the instance reported it."""

    deleted: int | None = None
    """How many earlier predictions were removed, where the instance reported it."""

    unchanged: int | None = None
    """How many matched what was already there, where the instance reported it."""

    message: str | None = None
    """What the instance said, in its own words."""


def _path(config: Dhis2PredictorRunConfig) -> str:
    """Where the run is sent: the one predictor, the group, or every predictor."""
    if config.predictor is not None:
        return f"/api/predictors/{config.predictor}/run"
    if config.predictor_group is not None:
        return f"/api/predictorGroups/{config.predictor_group}/run"
    return "/api/predictors/run"


def _reported(summary: dict[str, object] | None, name: str) -> int | None:
    """One count off the prediction summary, or None when the version wrote none."""
    if summary is None or not isinstance(summary.get(name), int):
        return None
    return count(summary, name)


class Dhis2PredictorRunOperator(Dhis2Operator[Dhis2PredictorRunConfig, Dhis2PredictorRunOutput]):
    """Runs the named predictors in one request and reads how many values they predicted."""

    spec = OperatorSpec(
        id="dhis2.predictor_run",
        summary="Run DHIS2 predictors over a date range.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2PredictorRunConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2PredictorRunOutput

    async def execute(self, config: Dhis2PredictorRunConfig, ctx: StepContext) -> Dhis2PredictorRunOutput:
        """Run the predictors and read the instance's count of what they predicted."""
        path = _path(config)
        params = {"startDate": config.start_date, "endDate": config.end_date}
        async with client_for(ctx, config.connection) as client:
            try:
                envelope = await client.post(path, None, params=params, model=WebMessageResponse)
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"POST {path}") from error
        said = envelope.message or None
        generated = GENERATED.search(said or "")
        summary = envelope.response
        inserted = _reported(summary, "inserted")
        predictions = int(generated.group(1)) if generated else (inserted or 0) + (_reported(summary, "updated") or 0)
        ctx.log.info("predictors run", predictions=predictions, path=path)
        return Dhis2PredictorRunOutput(
            predictions=predictions,
            inserted=inserted,
            updated=_reported(summary, "updated"),
            deleted=_reported(summary, "deleted"),
            unchanged=_reported(summary, "unchanged"),
            message=said,
        )
