"""The DHIS2 format checkers accept valid values, reject invalid ones, and gate a schema."""

import pytest
from jsonschema import Draft202012Validator

from dirigent_dhis2 import DHIS2_FORMATS
from dirigent_dhis2.formats import is_period, is_uid
from dirigent_testing import FakeContext


@pytest.mark.parametrize("value", ["abc123DEF45", "Abcdefghijk", "a0000000000", "Z9y8x7w6v54"])
def test_a_dhis2_uid_is_a_letter_then_ten_alphanumerics(value: str) -> None:
    assert is_uid(value)


@pytest.mark.parametrize(
    "value",
    ["1abcdefghij", "abc123DEF4", "abc123DEF456", "abc-123DEF4", "", "abc 123DEF4", 123],
)
def test_a_bad_dhis2_uid_is_rejected(value: object) -> None:
    assert not is_uid(value)


@pytest.mark.parametrize("value", ["2024", "202401", "20240115", "2024Q1", "2024W1", "2024W53"])
def test_a_dhis2_period_of_a_common_type_is_accepted(value: str) -> None:
    assert is_period(value)


@pytest.mark.parametrize(
    "value",
    ["2024Q5", "202413", "20240132", "2024W54", "24Q1", "2024-01", "notaperiod", 202401],
)
def test_a_bad_dhis2_period_is_rejected(value: object) -> None:
    assert not is_period(value)


#: A shape a validate.schema gate would carry, asserting the pack's formats on the id and period.
_SCHEMA = {
    "type": "object",
    "required": ["dataElement", "period"],
    "properties": {
        "dataElement": {"type": "string", "format": "dhis2-uid"},
        "period": {"type": "string", "format": "dhis2-period"},
    },
}


def _errors(context: FakeContext, payload: dict[str, str]) -> list[object]:
    """Validate a payload the way validate.schema does: the draft with the context's checker."""
    validator = Draft202012Validator(_SCHEMA, format_checker=context.format_checker())
    return list(validator.iter_errors(payload))  # pyright: ignore[reportUnknownMemberType]


def test_a_good_payload_passes_the_gate_where_the_pack_is_installed(block_ctx: FakeContext) -> None:
    block_ctx.formats = DHIS2_FORMATS
    assert _errors(block_ctx, {"dataElement": "fbfJHSPpUQD", "period": "202401"}) == []


def test_a_bad_dhis2_uid_fails_the_gate_where_the_pack_is_installed(block_ctx: FakeContext) -> None:
    block_ctx.formats = DHIS2_FORMATS
    assert _errors(block_ctx, {"dataElement": "not-a-uid", "period": "202401"})


def test_a_bad_dhis2_period_fails_the_gate_where_the_pack_is_installed(block_ctx: FakeContext) -> None:
    block_ctx.formats = DHIS2_FORMATS
    assert _errors(block_ctx, {"dataElement": "fbfJHSPpUQD", "period": "2024-01"})


def test_the_format_is_a_passing_annotation_where_the_pack_is_not_installed(block_ctx: FakeContext) -> None:
    assert _errors(block_ctx, {"dataElement": "not-a-uid", "period": "2024-01"}) == []
