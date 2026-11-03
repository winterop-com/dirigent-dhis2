"""What the read blocks share: the pager they answer with, and the check that a named uid exists."""

from typing import Any, Final, cast

from dhis2w_client import Dhis2Client
from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.messages import UNKNOWN_UIDS
from dirigent_dhis2.web import refuse
from dirigent_plugin import BlockFailure, ErrorClass

#: Where the existence of named uids is looked up, every collection in one request.
METADATA_PATH: Final = "/api/metadata"


class Dhis2Pager(BlockModel):
    """Where a paged read stands: the page it answered, and whether more pages follow it."""

    page: int | None = None
    """The 1-based page the rows came from; the last page read when every page was read."""

    page_size: int | None = None
    """How many rows a page holds."""

    total: int | None = None
    """How many rows match in all, when the instance counted them; null when it was not asked to."""

    page_count: int | None = None
    """How many pages the matching rows fill, when the instance counted them."""

    more: bool
    """Whether more rows match than were read. A full page the instance said nothing more about
    counts as more."""


def _int(value: object) -> int | None:
    """Read a pager number the instance may have written as a number or left out."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def pager_of(body: dict[str, Any], rows: int) -> Dhis2Pager:
    """Read the pager DHIS2 answered with, nested under ``pager`` or beside the rows.

    Metadata reads and tracker reads from 2.41 nest it under ``pager``; older tracker reads
    put ``page``, ``pageSize``, ``total`` and ``pageCount`` beside the rows. ``nextPage`` is
    present exactly when another page follows, and an analytics query's ``isLastPage`` says the
    same the other way round.
    """
    nested = body.get("pager")
    held: dict[str, Any] = {**body, **cast("dict[str, Any]", nested)} if isinstance(nested, dict) else body
    page, size = _int(held.get("page")), _int(held.get("pageSize"))
    total, count = _int(held.get("total")), _int(held.get("pageCount"))
    if isinstance(held.get("isLastPage"), bool):
        more = not held["isLastPage"]
    elif held.get("nextPage"):
        more = True
    elif page is not None and count is not None:
        more = page < count
    elif page is not None and size is not None and total is not None:
        more = page * size < total
    else:
        more = size is not None and rows >= size > 0
    return Dhis2Pager(page=page, page_size=size, total=total, page_count=count, more=more)


def _named(uids: str | list[str] | None) -> list[str]:
    """Spread a config's one uid or several into a list, empty when none was named."""
    if uids is None:
        return []
    return [uids] if isinstance(uids, str) else list(uids)


async def require_known(client: Dhis2Client, named: dict[str, str | list[str] | None], where: str) -> None:
    """Refuse the read when the instance knows no object by a uid it was scoped to.

    ``named`` maps a metadata collection such as ``dataSets`` to the uids the step named in it.
    Every collection is looked up in one ``GET /api/metadata``, asking for ids only, so a uid
    nothing answers to fails the step instead of narrowing the read to nothing.
    """
    wanted = {collection: sorted(set(_named(uids))) for collection, uids in named.items() if _named(uids)}
    if not wanted:
        return
    params: dict[str, Any] = {}
    for collection, uids in wanted.items():
        params[collection] = "true"
        params[f"{collection}:fields"] = "id"
        params[f"{collection}:filter"] = f"id:in:[{','.join(uids)}]"
    try:
        body = await client.get_raw(METADATA_PATH, params=params)
    except (Dhis2ApiError, AuthenticationError) as error:
        raise refuse(error, f"GET {METADATA_PATH}") from error
    unknown: list[str] = []
    for collection, uids in wanted.items():
        rows = body.get(collection)
        listed = cast("list[JsonValue]", rows) if isinstance(rows, list) else []
        found = {str(row.get("id")) for row in listed if isinstance(row, dict)}
        missing = [uid for uid in uids if uid not in found]
        if missing:
            unknown.append(f"{collection} {', '.join(missing)}")
    if unknown:
        raise BlockFailure(UNKNOWN_UIDS, error_class=ErrorClass.REJECTED, where=where, unknown="; ".join(unknown))
