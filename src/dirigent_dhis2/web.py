"""What the DHIS2 blocks share: turning a dhis2w-client failure into what the engine acts on.

Every block in the pack inherits its classification from the base classes here: a DHIS2
refusal carries its status, and anything else falls to the plugin contract's default rule.

The status helper duplicates the one in ``dirigent-blocks`` on purpose: an adapter pack may
not depend on that package, and the roadmap lifts a helper into ``common`` only once a
second pack has duplicated it.
"""

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError, UnsupportedVersionError
from pydantic import BaseModel

from dirigent_plugin import BlockFailure, ErrorClass, Operator, Sensor, classify_default


def status_class(status: int) -> ErrorClass:
    """Classify an HTTP status the way retry policy needs it classified."""
    if status >= 500:
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
