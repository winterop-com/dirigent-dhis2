"""Every refusal the DHIS2 pack makes, catalogued under the ``dhis2`` prefix."""

from dirigent_common import Catalogue

DHIS2 = Catalogue("dhis2")

ANSWERED = DHIS2.define("answered", "{where} answered {status}: {remote}")

EXPORT_EMPTY_ANSWER = DHIS2.define(
    "export.empty_answer",
    "{where} answered with an empty body rather than a data value set, which DHIS2 does when "
    "{org_unit} is outside the account's data scope; nothing was exported",
)

UNKNOWN_UIDS = DHIS2.define(
    "unknown_uids",
    "{where} is scoped to uids the instance knows no object by: {unknown}; the read would answer "
    "nothing for them, so it was not made. Check the uids, or set require_known: false to read anyway",
)

TRACKER_CAP_REACHED = DHIS2.define(
    "tracker.cap_reached",
    "reading every page of {kind} reached {cap} ({limit}) with rows still to read; nothing is "
    "answered rather than a part of the collection. Raise {cap} or narrow the read",
)

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

IMPORT_NO_DATA_VALUES = DHIS2.define(
    "import.no_data_values",
    "data_values {found}, not a data value set with a dataValues list, so nothing was sent. A step's "
    "whole output passed where its document was meant is the usual cause: an export's document is "
    "steps.<step>.output.body, not steps.<step>.output",
)

IMPORT_NO_VALUES_TAKEN = DHIS2.define(
    "import.no_values_taken",
    "the instance took none of the {sent} values sent, and require_values asks for at least one: {detail}",
)

IMPORT_NO_SUMMARY = DHIS2.define(
    "import.no_summary",
    "{where} answered without an import summary, so nothing says the import took",
)

IMPORT_UNKNOWN_STATUS = DHIS2.define(
    "import.unknown_status",
    "{where} answered a summary whose status is '{status}', so nothing says the import took",
)

IMPORT_REFUSED = DHIS2.define("import.refused", "the import was refused: {detail}")

IMPORT_TOOK_NOTHING = DHIS2.define("import.took_nothing", "the import took nothing: {detail}")

IMPORT_PARTIAL = DHIS2.define(
    "import.partial",
    "the import took {taken} values and refused {ignored} despite atomic_mode ALL: {detail}",
)

# What the three refusals above render as their {detail}: the instance's own conflicts, or
# the count when it named none.

IMPORT_CONFLICTS_AND_MORE = DHIS2.define("import.conflicts_and_more", "{named} (and {more} more)")

IMPORT_VALUES_IGNORED = DHIS2.define("import.values_ignored", "{ignored} values ignored")

CONNECTION_UNREACHABLE = DHIS2.define("connection.unreachable", "the instance did not answer: {detail}")

REDIRECT_REFUSED = DHIS2.define(
    "connection.redirect_refused",
    "base_url on {configured} redirects to {target}, which is neither that host, a subdomain of it, nor under "
    "dhis2.org beside it, so the credential was not sent; set base_url to the target if it is yours",
)

METADATA_UNKNOWN_RESOURCE = DHIS2.define(
    "metadata.unknown_resource",
    "the instance's version knows no metadata resource named '{resource}'",
)

MESSAGE_NO_RECIPIENT = DHIS2.define(
    "message.no_recipient",
    "a message needs at least one recipient in users, user_groups or org_units",
)

MESSAGE_NO_CONVERSATION = DHIS2.define(
    "message.no_conversation",
    "{where} took the message but answered without the conversation it created",
)


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

NO_PROGRAM = DHIS2.define("analytics_query.no_program", "a {mode} analytics query needs a program to read under")

EXPORT_NO_DATA = DHIS2.define(
    "export.no_data",
    "a data value set export names what to read: a data_set, data_element or data_element_group",
)

EXPORT_NO_ORG_UNIT = DHIS2.define(
    "export.no_org_unit",
    "a data value set export names where to read: an org_unit or org_unit_group",
)

EXPORT_NO_PERIOD = DHIS2.define(
    "export.no_period",
    "a data value set export names when to read: a period, a start_date with an end_date, "
    "last_updated or last_updated_duration",
)

EXPORT_HALF_RANGE = DHIS2.define(
    "export.half_range",
    "start_date and end_date bound one range, so a data value set export takes both or neither",
)

TRACKER_PAGE_WITH_ALL_PAGES = DHIS2.define(
    "tracker.page_with_all_pages",
    "all_pages reads every page from the first, so it takes no page",
)

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

BASE_URL_HOLDS_MORE = DHIS2.define(
    "connection.base_url_holds_more",
    "base_url says where the instance is and nothing else: a user, a password, a query or a fragment in it is refused, "
    "because it is stored as written; a credential goes in api_token or basic_password",
)

BAD_API_TOKEN = DHIS2.define(
    "connection.bad_api_token",
    "an api_token must be visible ASCII with no whitespace, or it cannot be sent as a header value",
)
