"""``dhis2.validation_run``: run validation rule analysis over an org unit and a date range, answering violations."""

import time
from typing import ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.messages import VALIDATION_VIOLATED
from dirigent_dhis2.reports import as_list, as_object, named_first, text
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: Where validation rule analysis is run.
VALIDATION_PATH: Final = "/api/dataAnalysis/validationRules"

#: An ISO date, the way the analysis reads its range.
ISO_DATE: Final = r"^\d{4}-\d{2}-\d{2}$"


class Dhis2ValidationRunConfig(BlockModel):
    """Which rules to evaluate, where, and over which dates.

    DHIS2 evaluates the rules over the org unit and every unit below it, for every period that
    falls in the range, and answers each place a rule does not hold. The analysis answers in
    the one request: DHIS2 runs it in the foreground and has no job to follow for it.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    org_unit: str = Field(pattern=UID_PATTERN)
    """The uid of the org unit the analysis covers, with every unit below it."""

    start_date: str = Field(pattern=ISO_DATE)
    """The ISO date the range starts on, such as 2026-01-01."""

    end_date: str = Field(pattern=ISO_DATE)
    """The ISO date the range ends on, such as 2026-03-31."""

    validation_rule_group: str | None = Field(default=None, pattern=UID_PATTERN)
    """The uid of a validation rule group to evaluate alone; every rule when unset."""

    max_results: int | None = Field(default=None, ge=1)
    """The most violations the instance answers with; its own cap, 500, when unset."""

    persist: bool = False
    """Whether the instance also stores each violation as a validation result, a write to
    ``/api/validationResults``. Off, the analysis writes nothing."""

    notification: bool = False
    """Whether the instance also sends the notifications the violated rules are set up with."""

    fail_on_violations: bool = False
    """Whether the step fails when any rule is violated, so a later step runs only on data that
    holds. Off, the violations are the output."""


class Dhis2Violation(BlockModel):
    """One place a rule does not hold: the rule, the org unit, the period and the two sides."""

    validation_rule: str
    """The uid of the violated rule."""

    validation_rule_description: str | None = None
    """The rule's description, or its name where it has none."""

    importance: str | None = None
    """The rule's importance: HIGH, MEDIUM or LOW."""

    org_unit: str
    """The uid of the org unit the rule does not hold at."""

    org_unit_name: str | None = None
    """The org unit's display name."""

    period: str
    """The ISO period the rule does not hold for."""

    attribute_option_combo: str | None = None
    """The uid of the attribute option combo the sides were evaluated for."""

    left_side_value: float | None = None
    """What the rule's left side evaluated to; null where it had no data."""

    operator: str | None = None
    """How the sides are compared, such as ``<=`` or ``==``."""

    right_side_value: float | None = None
    """What the rule's right side evaluated to; null where it had no data."""


class Dhis2ValidationRunOutput(BlockModel):
    """Every violation the analysis found."""

    violations: list[Dhis2Violation]
    """Each place a rule does not hold, empty when every rule held."""

    count: int
    """How many violations the analysis answered, at most ``max_results``."""

    duration_ms: int
    """How long the analysis took."""


def _number(value: object) -> float | None:
    """Read a side's value, which the instance writes as a number or leaves out."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def violations_in(body: dict[str, object]) -> list[Dhis2Violation]:
    """Read the analysis's answer: a list, which the client hands over under ``data``."""
    listed = as_list(body.get("data")) or as_list(body.get("validationResults"))
    found: list[Dhis2Violation] = []
    for entry in map(as_object, listed):
        if entry is None:
            continue
        found.append(
            Dhis2Violation(
                validation_rule=text(entry.get("validationRuleId")) or "",
                validation_rule_description=text(entry.get("validationRuleDescription")),
                importance=text(entry.get("importance")),
                org_unit=text(entry.get("organisationUnitId")) or "",
                org_unit_name=text(entry.get("organisationUnitDisplayName")),
                period=text(entry.get("periodId")) or "",
                attribute_option_combo=text(entry.get("attributeOptionComboId")),
                left_side_value=_number(entry.get("leftSideValue")),
                operator=text(entry.get("operator")),
                right_side_value=_number(entry.get("rightSideValue")),
            )
        )
    return found


class Dhis2ValidationRunOperator(Dhis2Operator[Dhis2ValidationRunConfig, Dhis2ValidationRunOutput]):
    """Runs validation rule analysis once and answers each violation it found."""

    spec = OperatorSpec(
        id="dhis2.validation_run",
        summary="Run DHIS2 validation rule analysis and answer the violations.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2ValidationRunConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2ValidationRunOutput

    async def execute(self, config: Dhis2ValidationRunConfig, ctx: StepContext) -> Dhis2ValidationRunOutput:
        """Run the analysis, and fail on a violation when the step asks to."""
        started = time.monotonic()
        request: dict[str, object] = {
            "ou": config.org_unit,
            "startDate": config.start_date,
            "endDate": config.end_date,
            "persist": config.persist,
            "notification": config.notification,
        }
        if config.validation_rule_group is not None:
            request["vrg"] = config.validation_rule_group
        if config.max_results is not None:
            request["maxResults"] = config.max_results
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.post_raw(VALIDATION_PATH, request)
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"POST {VALIDATION_PATH}") from error
        violations = violations_in(body)
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info("validation rule analysis run", violations=len(violations), duration_ms=duration)
        if violations and config.fail_on_violations:
            named = [
                f"{violation.validation_rule_description or violation.validation_rule} at "
                f"{violation.org_unit_name or violation.org_unit} in {violation.period}"
                for violation in violations
            ]
            raise BlockFailure(
                VALIDATION_VIOLATED, error_class=ErrorClass.REJECTED, count=len(violations), detail=named_first(named)
            )
        return Dhis2ValidationRunOutput(violations=violations, count=len(violations), duration_ms=duration)
