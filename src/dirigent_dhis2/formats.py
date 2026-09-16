"""DHIS2-specific JSON Schema format checkers this pack contributes.

Each predicate is pure: it matches a string against a pattern and returns a bool. The host
assembles these onto the base checker, so a schema that writes ``format: dhis2-uid`` asserts
wherever this pack is installed and stays a passing annotation on an instance without it.
"""

import re

from dhis2w_client import UID_RE

from dirigent_plugin import FormatCheck

#: DHIS2's 11-character UID: a letter, then ten alphanumerics, as dhis2w-client spells it.
_UID = UID_RE

#: DHIS2 ISO period strings, common types only: yearly YYYY, monthly YYYYMM, daily YYYYMMDD,
#: quarterly YYYYQn, and weekly YYYYWn with the week zero-padded or not, the way DHIS2 itself
#: reads it. The rarer types -- bi-weekly (YYYYBiWn), the weekly variants (YYYYWedWn,
#: YYYYThuWn, YYYYSatWn, YYYYSunWn), bi-monthly (YYYYMMB), six-monthly (YYYYSn), and the
#: financial-year variants (YYYYApril, YYYYJuly, YYYYOct) -- are not covered.
_PERIOD = re.compile(
    r"""
    \d{4}                                              # YYYY yearly
    | \d{4}(0[1-9]|1[0-2])                             # YYYYMM monthly
    | \d{4}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])        # YYYYMMDD daily
    | \d{4}Q[1-4]                                      # YYYYQn quarterly
    | \d{4}W(0?[1-9]|[1-4]\d|5[0-3])                   # YYYYWn weekly, 1-53, zero-padded or not
    """,
    re.VERBOSE,
)


def is_uid(value: object) -> bool:
    """Whether the value is a DHIS2 UID: a letter followed by ten alphanumerics."""
    return isinstance(value, str) and _UID.fullmatch(value) is not None


def is_period(value: object) -> bool:
    """Whether the value is a DHIS2 ISO period of one of the common types."""
    return isinstance(value, str) and _PERIOD.fullmatch(value) is not None


#: The format checkers this pack contributes, by the name a schema writes in ``format``.
DHIS2_FORMATS: dict[str, FormatCheck] = {
    "dhis2-uid": is_uid,
    "dhis2-period": is_period,
}
