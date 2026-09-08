"""``dhis2.data_set_complete``: wait for a data set registration to be marked complete."""

from typing import ClassVar, Final

from dhis2w_client import CompleteDataSetRegistration, CompleteDataSetRegistrations
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.web import Dhis2Sensor, refuse
from dirigent_plugin import NotYet, SensorSpec, StepContext

#: Where completion registrations are read.
REGISTRATIONS_PATH: Final = "/api/completeDataSetRegistrations"


class Dhis2DataSetCompleteConfig(BlockModel):
    """Which data set window the run is waiting on."""

    connection: str
    """The code of the dhis2 connection naming the instance."""

    data_set: str
    """The uid of the data set."""

    period: str
    """An ISO period identifier, such as 2026Q1."""

    org_unit: str
    """The uid of the organisation unit."""


class Dhis2DataSetCompleteOutput(BlockModel):
    """The registration that ended the wait."""

    completed_at: str | None = None
    """When the registration was made, in the instance's own timestamp."""

    stored_by: str | None = None
    """Who marked the data set complete."""


class Dhis2DataSetCompleteSensor(Dhis2Sensor[Dhis2DataSetCompleteConfig, Dhis2DataSetCompleteOutput]):
    """Waits for the registration; each poke is one short, read-only GET."""

    spec = SensorSpec(id="dhis2.data_set_complete", summary="Wait for a DHIS2 data set to be marked complete.")
    config_model: ClassVar[type[BaseModel]] = Dhis2DataSetCompleteConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataSetCompleteOutput

    async def poke(self, config: Dhis2DataSetCompleteConfig, ctx: StepContext) -> Dhis2DataSetCompleteOutput | NotYet:
        """Observe once. A window nobody has closed yet is the condition, not an error."""
        async with client_for(ctx, config.connection) as client:
            try:
                registrations = await client.complete_data_set_registrations.export(
                    data_set=config.data_set,
                    period=config.period,
                    org_unit=config.org_unit,
                )
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {REGISTRATIONS_PATH}") from error
        registration = _completed(registrations)
        if registration is None:
            return NotYet(
                message=f"data set {config.data_set} for {config.period} at {config.org_unit} is not complete"
            )
        return Dhis2DataSetCompleteOutput(completed_at=registration.date, stored_by=registration.storedBy)


def _completed(envelope: CompleteDataSetRegistrations) -> CompleteDataSetRegistration | None:
    """Find a completed registration in the endpoint's answer, or nothing while there is none.

    A registration can be unmade, so one carrying ``completed: false`` is a window that was
    reopened and the wait goes on. Older instances answer without the flag at all, and there
    a registration's existence is the completion.
    """
    for registration in envelope.completeDataSetRegistrations:
        if registration.completed is True or registration.completed is None:
            return registration
    return None
