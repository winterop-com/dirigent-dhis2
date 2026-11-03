"""What the write blocks share: reading the report DHIS2 answers a write with, and naming what it refused.

DHIS2 answers a write it did not take with 409 and the same report a taken one gets on 200,
so a refusal's body is read the way a success is. The reports differ per endpoint, and each
block reads its own; what they share is the plumbing below.
"""

from collections.abc import Iterable
from typing import Any, Final, cast

from dhis2w_client.errors import Dhis2ApiError
from pydantic import JsonValue

from dirigent_dhis2.imports import Dhis2ImportCounts
from dirigent_dhis2.messages import IMPORT_CONFLICTS_AND_MORE

#: How many refused objects a failure names before counting the rest.
NAMED_ERRORS: Final = 3


def as_object(value: object) -> dict[str, Any] | None:
    """The value as a JSON object, or None when it is anything else."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[Any]:
    """The value as a JSON array, empty when it is anything else."""
    return list(cast("Iterable[Any]", value)) if isinstance(value, list) else []


def body_of(error: Dhis2ApiError) -> dict[str, Any] | None:
    """The JSON object a refusal carried, when it carried one."""
    return as_object(error.body)


def count(stats: dict[str, Any] | None, name: str) -> int:
    """Read one count off a report's stats, zero when a version left it out."""
    value = (stats or {}).get(name)
    return value if isinstance(value, int) else 0


def import_counts(stats: dict[str, Any] | None) -> Dhis2ImportCounts:
    """Read a report's stats as the pack's import counts: what DHIS2 counts as created is imported."""
    return Dhis2ImportCounts(
        imported=count(stats, "created"),
        updated=count(stats, "updated"),
        ignored=count(stats, "ignored"),
        deleted=count(stats, "deleted"),
    )


def sent(bundle: dict[str, Any], collections: tuple[str, ...] | None = None) -> int:
    """How many objects a bundle holds: the items of each list in it, or of the named lists only."""
    return sum(len(as_list(value)) for name, value in bundle.items() if collections is None or name in collections)


def text(value: object) -> str | None:
    """The value as a string, or None when it is not one or is empty."""
    return value if isinstance(value, str) and value else None


def short_class(klass: object) -> str:
    """Name a DHIS2 Java class by its simple name: ``org.hisp.dhis.dataelement.DataElement`` is ``DataElement``."""
    return str(klass).rsplit(".", 1)[-1] if isinstance(klass, str) and klass else ""


def coded(code: str | None) -> str:
    """The instance's code for a refusal as a suffix to its words, such as `` (E1303)``, or nothing."""
    return f" ({code})" if code else ""


def import_summary(body: dict[str, Any]) -> dict[str, Any] | None:
    """Find an import summary in an answer: under ``response`` on current versions, else at the top."""
    for candidate in (as_object(body.get("response")), body):
        if candidate is not None and ("importCount" in candidate or "conflicts" in candidate):
            return candidate
    return None


def named_first(named: list[str]) -> str:
    """Name the first few refusals and count the rest."""
    shown = "; ".join(named[:NAMED_ERRORS])
    more = len(named) - NAMED_ERRORS
    return IMPORT_CONFLICTS_AND_MORE.render(named=shown, more=more) if more > 0 else shown


def document_kind(document: JsonValue) -> str:
    """Say what a document that should be an object is instead, for a refusal to name."""
    match document:
        case None:
            return "empty"
        case list():
            return "a list"
        case str():
            return "a string"
        case bool():
            return "a boolean"
        case int() | float():
            return "a number"
        case _:
            return "an object"
