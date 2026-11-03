"""``dhis2.data_store``: read, write or remove one key in a data store namespace, or list a namespace's keys."""

import json
from typing import ClassVar, Final, Literal
from urllib.parse import quote

import httpx2
from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel, Issue, Message
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.messages import DATA_STORE_NO_KEY, DATA_STORE_NO_VALUE
from dirigent_dhis2.reports import as_object
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import BlockFailure, ConnectionRef, ErrorClass, OperatorSpec, StepContext

#: The shared store, which apps and integrations read under sharing.
SHARED_STORE: Final = "/api/dataStore"

#: The store each user holds for themselves.
USER_STORE: Final = "/api/userDataStore"

#: A namespace or key as one path segment: anything but a slash.
SEGMENT_PATTERN: Final = r"^[^/]+$"

#: What the step does in the namespace.
DataStoreAction = Literal["get", "set", "delete", "keys"]


class Dhis2DataStoreConfig(BlockModel):
    """Which namespace, which key, and what the step does there.

    The data store holds arbitrary JSON under a namespace and a key: app configuration,
    integration state, a sync's high-water mark. ``keys`` lists a namespace; ``get``, ``set``
    and ``delete`` address one key in it.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    action: DataStoreAction = "get"
    """What the step does: ``get`` reads the key, ``set`` writes ``value`` to it, creating or
    replacing it, ``delete`` removes it, and ``keys`` lists the namespace's keys."""

    namespace: str = Field(min_length=1, pattern=SEGMENT_PATTERN)
    """The namespace, such as an app's own or one an integration keeps its state in."""

    key: str | None = Field(default=None, min_length=1, pattern=SEGMENT_PATTERN)
    """The key in the namespace; every action but ``keys`` needs one."""

    value: JsonValue = None
    """The JSON to store, for ``set``: an object, a list, a string, a number or a boolean."""

    encrypt: bool = False
    """Whether ``set`` asks the instance to store the value encrypted."""

    user_store: bool = False
    """Whether the step addresses the signed-in user's own store, ``/api/userDataStore``, rather
    than the shared one."""


class Dhis2DataStoreOutput(BlockModel):
    """What the step found or did in the namespace."""

    action: DataStoreAction
    """What the step did."""

    namespace: str
    """The namespace addressed."""

    key: str | None = None
    """The key addressed; null for ``keys``."""

    found: bool
    """Whether the key, or for ``keys`` the namespace, was there before the step: a ``get`` of a
    key that is not there answers false rather than failing, and so does a ``delete``."""

    value: JsonValue = None
    """The value read, or the value written; null for ``delete``, for ``keys``, and for a key
    that was not there."""

    rows: list[str] = Field(default_factory=list[str])
    """The namespace's keys, for ``keys``; empty for every other action."""

    created: bool = False
    """Whether ``set`` made a new key rather than replacing one."""


def _refusals(config: Dhis2DataStoreConfig) -> list[Message]:
    """What the config asks for that the store cannot do."""
    if config.action != "keys" and config.key is None:
        return [DATA_STORE_NO_KEY]
    if config.action == "set" and config.value is None:
        return [DATA_STORE_NO_VALUE]
    return []


def _path(config: Dhis2DataStoreConfig, *, with_key: bool) -> str:
    """The path of the namespace, or of the key in it, each segment escaped."""
    root = USER_STORE if config.user_store else SHARED_STORE
    path = f"{root}/{quote(config.namespace, safe='')}"
    return f"{path}/{quote(config.key or '', safe='')}" if with_key else path


def _refusal(response: httpx2.Response) -> Dhis2ApiError:
    """The error a refused store request is classified as, carrying what the instance said."""
    body: object
    try:
        body = response.json()
    except ValueError:
        body = response.text
    said = (as_object(body) or {}).get("message")
    return Dhis2ApiError(response.status_code, str(said or response.reason_phrase or "refused"), body=body)


async def _read(client: Dhis2Client, path: str) -> tuple[bool, JsonValue]:
    """Read the JSON at a path as it is stored, answering not found for a 404 rather than failing.

    The response is read whole rather than through the client's JSON helper, which wraps a
    stored list or scalar under ``data``.
    """
    try:
        response = await client.get_response(path)
    except AuthenticationError as error:
        raise refuse(error, f"GET {path}") from error
    if response.status_code == 404:
        return False, None
    if not response.is_success:
        raise refuse(_refusal(response), f"GET {path}")
    stored: JsonValue = json.loads(response.content) if response.content.strip() else None
    return True, stored


class Dhis2DataStoreOperator(Dhis2Operator[Dhis2DataStoreConfig, Dhis2DataStoreOutput]):
    """Reads, writes or removes one data store key, or lists a namespace."""

    spec = OperatorSpec(
        id="dhis2.data_store",
        summary="Get, set or delete a DHIS2 data store key, or list a namespace's keys.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2DataStoreConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2DataStoreOutput

    def check_config(self, config: BaseModel) -> list[Issue]:
        """Refuse a key action with no key, or a set with no value, before the document is stored."""
        if not isinstance(config, Dhis2DataStoreConfig):
            return []
        return [Issue.of(refusal) for refusal in _refusals(config)]

    async def execute(self, config: Dhis2DataStoreConfig, ctx: StepContext) -> Dhis2DataStoreOutput:
        """Do what the action says in the namespace."""
        refusals = _refusals(config)
        if refusals:
            raise BlockFailure(refusals[0], error_class=ErrorClass.REJECTED)
        output = Dhis2DataStoreOutput(action=config.action, namespace=config.namespace, key=config.key, found=False)
        async with client_for(ctx, config.connection) as client:
            if config.action == "keys":
                found, listed = await _read(client, _path(config, with_key=False))
                rows = [str(key) for key in listed] if isinstance(listed, list) else []
                ctx.log.info("data store keys read", namespace=config.namespace, keys=len(rows))
                return output.model_copy(update={"found": found, "rows": rows})
            path = _path(config, with_key=True)
            found, stored = await _read(client, path)
            if config.action == "get":
                ctx.log.info("data store key read", namespace=config.namespace, key=config.key, found=found)
                return output.model_copy(update={"found": found, "value": stored})
            try:
                if config.action == "delete":
                    if found:
                        await client.delete_raw(path)
                    ctx.log.info("data store key deleted", namespace=config.namespace, key=config.key, found=found)
                    return output.model_copy(update={"found": found})
                params = {"encrypt": "true"} if config.encrypt else None
                if found:
                    await client.put_raw(path, config.value, params=params)
                else:
                    await client.post_raw(path, config.value, params=params)
            except (Dhis2ApiError, AuthenticationError) as error:
                verb = "DELETE" if config.action == "delete" else "PUT" if found else "POST"
                raise refuse(error, f"{verb} {path}") from error
        ctx.log.info("data store key written", namespace=config.namespace, key=config.key, created=not found)
        return output.model_copy(update={"found": found, "value": config.value, "created": not found})
