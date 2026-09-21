"""Every refusal the DHIS2 pack makes, catalogued under the ``dhis2`` prefix."""

from dirigent_common import Catalogue

DHIS2 = Catalogue("dhis2")

ANSWERED = DHIS2.define("answered", "{where} answered {status}: {remote}")

ANALYTICS_NO_TASK_REFERENCE = DHIS2.define(
    "analytics.no_task_reference",
    "the analytics job submission answered without a task reference to follow",
)

ANALYTICS_TASK_DISAPPEARED = DHIS2.define(
    "analytics.task_disappeared",
    "task {task} disappeared before its result could be collected",
)

ANALYTICS_NO_RESULT = DHIS2.define(
    "analytics.no_result",
    "task {task} has no result to collect: the instance holds no terminal notification for it",
)

IMPORT_NO_SUMMARY = DHIS2.define(
    "import.no_summary",
    "{where} answered without an import summary, so nothing says the import took",
)

IMPORT_REFUSED = DHIS2.define("import.refused", "the import was refused: {detail}")

IMPORT_TOOK_NOTHING = DHIS2.define("import.took_nothing", "the import took nothing: {detail}")

IMPORT_PARTIAL = DHIS2.define(
    "import.partial",
    "the import took {taken} values and refused {ignored} despite atomic_mode ALL: {detail}",
)

METADATA_UNKNOWN_RESOURCE = DHIS2.define(
    "metadata.unknown_resource",
    "the instance's version knows no metadata resource named '{resource}'",
)


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

NO_PROGRAM = DHIS2.define("analytics_query.no_program", "a {mode} analytics query needs a program to read under")

BOTH_CREDENTIALS = DHIS2.define(
    "connection.both_credentials",
    "a dhis2 connection takes an api_token or basic credentials, not both",
)

NO_CREDENTIAL = DHIS2.define(
    "connection.no_credential",
    "a dhis2 connection needs an api_token or basic credentials",
)

NO_BASIC_PASSWORD = DHIS2.define(
    "connection.no_basic_password",
    "basic credentials need a basic_password beside the basic_username",
)
