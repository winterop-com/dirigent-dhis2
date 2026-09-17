"""What the DHIS2 blocks share: how a dhis2w-client failure is classified, and how a query is shaped.

Every block in the pack inherits its classification from the base classes here: a DHIS2
refusal carries its status, and anything else falls to the plugin contract's default rule.
Every block that narrows a read hands its ``fields``, ``filter`` and ``order`` to
:func:`query_terms` before the request is built.

The status helper duplicates the one in ``dirigent-blocks`` on purpose: an adapter pack may
not depend on that package, and the roadmap lifts a helper into ``common`` only once a
second pack has duplicated it.
"""

from dataclasses import dataclass

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError, UnsupportedVersionError
from pydantic import BaseModel

from dirigent_plugin import BlockFailure, ErrorClass, Operator, Sensor, classify_default


def status_class(status: int) -> ErrorClass:
    """Classify an HTTP status the way retry policy needs it classified.

    A 429 is the one client error that asks to be retried: the instance is rate limiting,
    and the same call succeeds once the window has passed.
    """
    if status >= 500 or status == 429:
        return ErrorClass.TRANSIENT
    if 400 <= status < 500:
        return ErrorClass.REJECTED
    return ErrorClass.UNKNOWN


def describe(error: Dhis2ApiError | AuthenticationError) -> str:
    """Say what the instance said, in its own words when it gave any.

    A DHIS2 refusal usually carries a web message whose ``message`` is the actual reason;
    the reason phrase is what is left when the body is not one.
    """
    if isinstance(error, AuthenticationError):
        return str(error)
    envelope = error.web_message
    if envelope is not None and envelope.message:
        return envelope.message
    return error.message


def refuse(error: Dhis2ApiError | AuthenticationError, where: str) -> BlockFailure:
    """Turn a dhis2w-client HTTP failure into a classified BlockFailure the engine can act on."""
    status = error.status_code if isinstance(error, Dhis2ApiError) else 401
    return BlockFailure(f"{where} answered {status}: {describe(error)}", error_class=status_class(status))


def classify(error: Exception) -> ErrorClass:
    """Classify a failure raised through dhis2w-client, so the engine knows whether to retry.

    An instance whose version the client does not speak is a configuration problem and is
    never retried.
    """
    match error:
        case BlockFailure():
            return error.error_class
        case Dhis2ApiError():
            return status_class(error.status_code)
        case AuthenticationError() | UnsupportedVersionError():
            return ErrorClass.REJECTED
        case _:
            return classify_default(error)


@dataclass(frozen=True, slots=True)
class QueryTerms:
    """A read's ``fields``, ``filter`` and ``order``, in the shape DHIS2 reads them off the wire."""

    fields: str | None
    """The one ``fields=`` value, its selectors comma-joined."""

    filter: list[str] | None
    """The ``filter=`` expressions, sent as one query parameter each."""

    order: str | None
    """The one ``order=`` value, its terms comma-joined."""


def query_terms(
    *,
    fields: str | list[str] | None = None,
    filter: str | list[str] | None = None,
    order: str | list[str] | None = None,
) -> QueryTerms:
    """Put a document's query terms into the shape DHIS2 reads them in.

    A document writes each term as one string or as a list. DHIS2 reads ``fields`` and
    ``order`` as a single parameter whose terms are comma-joined, and takes ``filter`` once per
    expression, so a list is joined for the first two and repeated for the third. A string is
    one term and passes through unchanged; an empty list is no term at all.
    """
    return QueryTerms(fields=_joined(fields), filter=_repeated(filter), order=_joined(order))


def _joined(terms: str | list[str] | None) -> str | None:
    """Join a ``fields`` or ``order`` list into the one comma-joined value DHIS2 reads."""
    if terms is None or isinstance(terms, str):
        return terms
    return ",".join(terms) or None


def _repeated(terms: str | list[str] | None) -> list[str] | None:
    """Spread a ``filter`` into the expressions it is sent as, one parameter each."""
    if terms is None:
        return None
    if isinstance(terms, str):
        return [terms]
    return list(terms) or None


class Dhis2Operator[ConfigT: BaseModel, OutputT: BaseModel](Operator[ConfigT, OutputT]):
    """An operator whose failures are classified the dhis2w-client way."""

    def classify_error(self, error: Exception) -> ErrorClass:
        """Classify a failure raised by this operator."""
        return classify(error)


class Dhis2Sensor[ConfigT: BaseModel, OutputT: BaseModel](Sensor[ConfigT, OutputT]):
    """A sensor whose failures are classified the dhis2w-client way."""

    def classify_error(self, error: Exception) -> ErrorClass:
        """Classify a failure raised by this sensor."""
        return classify(error)
