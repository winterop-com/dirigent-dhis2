"""``dhis2.sql_view``: run a stored SQL view by uid and read its rows."""

import time
from typing import Annotated, Any, ClassVar, Final, cast

from dhis2w_client.errors import AuthenticationError, Dhis2ApiError
from pydantic import BaseModel, Field, JsonValue

from dirigent_common import BlockModel
from dirigent_dhis2.connection import client_for
from dirigent_dhis2.formats import UID_PATTERN
from dirigent_dhis2.reads import Dhis2Pager, pager_of
from dirigent_dhis2.reports import as_list, as_object, text
from dirigent_dhis2.web import Dhis2Operator, refuse
from dirigent_plugin import ConnectionRef, OperatorSpec, StepContext

#: A variable name as a ``QUERY`` view's ``${name}`` placeholder writes it.
VARIABLE_NAME: Final = r"^[A-Za-z][A-Za-z0-9_]*$"

#: One criterion's column, as the view's own result names it.
COLUMN_NAME: Final = r"^[A-Za-z_][A-Za-z0-9_]*$"


class Dhis2SqlViewConfig(BlockModel):
    """Which SQL view to run, what to fill it in with, and how much of its result to read.

    A view is stored on the instance as metadata, written by someone allowed to write SQL; this
    block runs one by its uid and never sends SQL of its own. A ``QUERY`` view takes
    ``variables`` for its ``${name}`` placeholders; a ``VIEW`` or ``MATERIALIZED_VIEW`` is
    narrowed with ``criteria`` on its result's columns.
    """

    connection: ConnectionRef
    """The code of the dhis2 connection naming the instance."""

    sql_view: str = Field(pattern=UID_PATTERN)
    """The uid of the SQL view to run."""

    variables: dict[Annotated[str, Field(pattern=VARIABLE_NAME)], str] = Field(default_factory=dict[str, str])
    """Values for a ``QUERY`` view's ``${name}`` placeholders, keyed by name. DHIS2 keeps only
    letters and digits of each value, so a wildcard belongs in the view's SQL."""

    criteria: dict[Annotated[str, Field(pattern=COLUMN_NAME)], str] = Field(default_factory=dict[str, str])
    """Column values a ``VIEW`` or ``MATERIALIZED_VIEW`` result is narrowed to, keyed by column,
    every one of them matched."""

    paging: bool = False
    """Whether the read is paged. Off by default: DHIS2 answers a view's first 50 rows unless
    told otherwise, and a view is read for all of its rows."""

    page: int | None = Field(default=None, ge=1)
    """The 1-based page to read, when ``paging`` is on."""

    page_size: int | None = Field(default=None, ge=1)
    """How many rows a page holds, when ``paging`` is on."""


class Dhis2SqlViewColumn(BlockModel):
    """One column of the view's result."""

    name: str
    """The column's name, which is the key every row carries its value under."""

    value_type: str | None = None
    """The type DHIS2 reports for it, a Java class name such as ``java.lang.String``."""


class Dhis2SqlViewOutput(BlockModel):
    """The view's rows, each keyed by column, and where a paged read stands."""

    rows: list[dict[str, JsonValue]]
    """The view's rows, each an object keyed by column name."""

    columns: list[Dhis2SqlViewColumn]
    """The result's columns, in the order the view selects them."""

    title: str | None = None
    """The view's name, as the result carries it."""

    pager: Dhis2Pager | None = None
    """The page read, the page size, the total and whether more pages follow; null when the read
    is not paged and so answered every row."""

    duration_ms: int
    """How long the read took."""


def view_params(config: Dhis2SqlViewConfig) -> dict[str, Any]:
    """The query a run of the view sends: each variable and criterion repeated, and the paging."""
    params: dict[str, Any] = {}
    if config.variables:
        params["var"] = [f"{name}:{value}" for name, value in config.variables.items()]
    if config.criteria:
        params["criteria"] = [f"{column}:{value}" for column, value in config.criteria.items()]
    if config.paging:
        params["paging"] = "true"
        if config.page is not None:
            params["page"] = config.page
        if config.page_size is not None:
            params["pageSize"] = config.page_size
    else:
        params["paging"] = "false"
    return params


class Dhis2SqlViewOperator(Dhis2Operator[Dhis2SqlViewConfig, Dhis2SqlViewOutput]):
    """Runs one stored SQL view and answers its grid as rows keyed by column."""

    spec = OperatorSpec(
        id="dhis2.sql_view",
        summary="Run a DHIS2 SQL view by uid and read its rows.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = Dhis2SqlViewConfig
    output_model: ClassVar[type[BaseModel]] = Dhis2SqlViewOutput

    async def execute(self, config: Dhis2SqlViewConfig, ctx: StepContext) -> Dhis2SqlViewOutput:
        """Run the view once and key each row by the columns the result names."""
        started = time.monotonic()
        path = f"/api/sqlViews/{config.sql_view}/data.json"
        async with client_for(ctx, config.connection) as client:
            try:
                body = await client.get_raw(path, params=view_params(config))
            except (Dhis2ApiError, AuthenticationError) as error:
                raise refuse(error, f"GET {path}") from error
        grid = as_object(body.get("listGrid")) or body
        columns = [
            Dhis2SqlViewColumn(name=name, value_type=text(header.get("type")))
            for header in map(as_object, as_list(grid.get("headers")))
            if header is not None and (name := text(header.get("name")) or text(header.get("column"))) is not None
        ]
        names = [column.name for column in columns]
        rows = [
            dict(zip(names, cast("list[JsonValue]", row), strict=False))
            for row in as_list(grid.get("rows"))
            if isinstance(row, list)
        ]
        pager = pager_of(body, len(rows)) if config.paging else None
        duration = round((time.monotonic() - started) * 1000)
        ctx.log.info("sql view read", sql_view=config.sql_view, rows=len(rows), duration_ms=duration)
        return Dhis2SqlViewOutput(
            rows=rows, columns=columns, title=text(grid.get("title")), pager=pager, duration_ms=duration
        )
