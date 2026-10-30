"""``dhis2.message``: send a DHIS2 message to users, user groups or organisation units."""

from typing import Annotated, ClassVar, Final

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field

from dirigent_common import BlockModel, Issue
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.messages import MESSAGE_NO_CONVERSATION, MESSAGE_NO_RECIPIENT
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: Where message conversations are created.
CONVERSATIONS_PATH: Final = "/api/messageConversations"

#: The longest subject DHIS2 stores.
SUBJECT_MAX_LENGTH: Final = 255

#: One recipient, named by its DHIS2 uid.
Uid = Annotated[str, Field(pattern=UID_PATTERN)]


class Dhis2MessageConfig(BlockModel):
    """What the message says, and who it goes to."""

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    subject: str = Field(min_length=1, max_length=SUBJECT_MAX_LENGTH)
    """The subject line, up to 255 characters."""

    text: str = Field(min_length=1)
    """The body of the message, which may be long and may be built from references."""

    users: list[Uid] = []
    """The uids of the users the message goes to."""

    user_groups: list[Uid] = []
    """The uids of the user groups whose members the message goes to."""

    org_units: list[Uid] = []
    """The uids of the organisation units whose assigned users the message goes to."""


class Dhis2MessageOutput(BlockModel):
    """The conversation the message started, and who it was addressed to."""

    conversation_id: str
    """The uid of the message conversation the instance created."""

    user_count: int
    """How many users the message named."""

    user_group_count: int
    """How many user groups the message named."""

    org_unit_count: int
    """How many organisation units the message named."""


def _addressed(config: Dhis2MessageConfig) -> bool:
    """Whether the message names anyone to send it to."""
    return bool(config.users or config.user_groups or config.org_units)


class Dhis2MessageOperator(Dhis2Operator[Dhis2MessageConfig, Dhis2MessageOutput]):
    """Starts one message conversation, which DHIS2 also sends as email where SMTP is configured."""

    spec = OperatorSpec(id="dhis2.message", summary="Send a DHIS2 message to users, user groups or org units.")
    config_model: ClassVar[type[BaseModel]] = Dhis2MessageConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2MessageOutput

    def check_config(self, config: BaseModel) -> list[Issue]:
        """Refuse a message addressed to nobody before the document is stored."""
        if isinstance(config, Dhis2MessageConfig) and not _addressed(config):
            return [Issue.of(MESSAGE_NO_RECIPIENT)]
        return []

    async def execute(self, config: Dhis2MessageConfig, ctx: StepContext) -> Dhis2MessageOutput:
        """Send the message and read back the conversation it started.

        The recipients are checked again here, because a config holding a reference is not
        checked at apply and may resolve to no one.
        """
        if not _addressed(config):
            raise BlockFailure(MESSAGE_NO_RECIPIENT, error_class=ErrorClass.REJECTED)
        where = f"POST {CONVERSATIONS_PATH}"
        async with client_for(ctx, config.connection) as client:
            try:
                conversation = await client.messaging.send(
                    subject=config.subject,
                    text=config.text,
                    users=config.users,
                    user_groups=config.user_groups,
                    organisation_units=config.org_units,
                )
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, where) from error
            except RuntimeError as error:
                raise BlockFailure(MESSAGE_NO_CONVERSATION, error_class=ErrorClass.REJECTED, where=where) from error
        if not conversation.id:
            raise BlockFailure(MESSAGE_NO_CONVERSATION, error_class=ErrorClass.REJECTED, where=where)
        ctx.log.info("message sent", conversation=conversation.id)
        return Dhis2MessageOutput(
            conversation_id=conversation.id,
            user_count=len(config.users),
            user_group_count=len(config.user_groups),
            org_unit_count=len(config.org_units),
        )
