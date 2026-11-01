"""Photograph the tutorial's pictures from a local instance with this pack installed.

Two sets, both of dirigent's own UI on a throwaway ``dg dev`` with the pack beside it:

- ``catalog``: the Blocks and Examples screens, which read the pack's catalog and corpus and
  need no DHIS2 at all.
- ``walk``: the rest, taken by walking the tutorial against the public play demo with its
  published login, as the tutorial itself does. The documents are read out of
  ``docs/tutorial.md``, so the pictures are of the page's own documents. Every DHIS2 call the
  page makes reads, or imports with ``dry_run: true``; nothing is written to the shared demo,
  and a document on the page that would write stops this script before it runs.

Chromium is driven through Playwright, layered in at call time like ``docs_pdf.py``'s:

    uv run --with dirigent-cli --with playwright playwright install chromium
    uv run --with dirigent-cli --with playwright python scripts/docs_shots.py [catalog|walk]

With no set named it takes both. The pictures land in ``docs/images/tutorial/``. The instance
binds ``--port`` (3376 unless told otherwise) on loopback, keeps its state in a temporary
directory, and is stopped on the way out.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from dirigent_client import Dirigent
    from playwright.sync_api import Page

#: The project root, one level above this script.
ROOT = Path(__file__).resolve().parent.parent

#: Where the pictures land, beside the page that renders them.
OUT = ROOT / "docs" / "images" / "tutorial"

#: The page the walk reads its documents out of.
TUTORIAL = ROOT / "docs" / "tutorial.md"

#: The frame every picture is taken in.
WIDTH, HEIGHT = 1280, 800

#: The account ``dg dev`` creates on an empty instance.
USERNAME = PASSWORD = "admin"

#: The pipeline and the schema the tutorial builds.
PIPELINE = "dhis2-tutorial"
SCHEMA = "tutorial-org-units"

#: The connection section 2 creates: the play demo, with the login it publishes for anyone.
CONNECTION: dict[str, Any] = {
    "code": "play",
    "kind": "dhis2",
    "name": "DHIS2 play demo",
    "config": {
        "base_url": "https://play.dhis2.org/2.43",
        "basic_username": "admin",
        "basic_password": "district",
    },
}

#: The block that imports, allowed in the walk only with ``dry_run: true``.
IMPORTS = "dhis2.data_value_set_import"

#: Blocks that write to DHIS2 with no dry run, refused in the walk outright.
WRITERS = frozenset({"dhis2.message"})

Json = dict[str, Any]


def _free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _wait_for(url: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"no instance answered at {url}")


def _token(log: Path, deadline: float) -> str:
    """The token ``dg dev`` mints on an empty instance, off the starting record it writes once."""
    while time.monotonic() < deadline:
        for line in log.read_text().splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("kind") == "process" and record.get("token"):
                return str(record["token"])
        time.sleep(0.5)
    raise SystemExit("the instance wrote no token on its starting record")


def _blocks(language: str) -> list[str]:
    fence = re.compile(r"^```" + language + r"\n(.*?)^```", re.MULTILINE | re.DOTALL)
    return fence.findall(TUTORIAL.read_text())


def _refuse_writes(document: Json) -> None:
    for code, step in document["steps"].items():
        block = step.get("block")
        if block in WRITERS or (block == IMPORTS and step.get("config", {}).get("dry_run") is not True):
            raise SystemExit(f"{code} would write to the shared play demo; the walk runs reads and dry runs only")


def _documents() -> dict[str, Json]:
    """The page's documents: the first read, the gate, the full pipeline and the broken read."""
    versions = [text for text in _blocks("yaml") if f"code: {PIPELINE}" in text]
    if len(versions) < 2:
        raise SystemExit(f"docs/tutorial.md writes {PIPELINE} out fewer than twice")
    first: Json = yaml.safe_load(versions[0])
    full: Json = yaml.safe_load(versions[-1])
    if list(full["steps"]) != ["read", "check", "rehearse"]:
        raise SystemExit("the document in full is no longer read, check and rehearse")
    gated: Json = json.loads(json.dumps(full))
    del gated["steps"]["rehearse"]
    broken: Json = json.loads(json.dumps(full))
    broken["steps"]["read"]["config"]["resource"] = "organisationUnit"
    documents = {"first": first, "gated": gated, "full": full, "broken": broken}
    for document in documents.values():
        _refuse_writes(document)
    return documents


def _schema() -> Json:
    found = [text for text in _blocks("json") if f'"$id": "{SCHEMA}"' in text]
    if len(found) != 1:
        raise SystemExit(f"docs/tutorial.md holds {len(found)} JSON blocks with $id {SCHEMA}")
    body: Json = json.loads(found[0])
    return body


def _settle(page: Page) -> None:
    """Wait until the corner has read the instance, so the topbar in the frame is the settled one."""
    page.get_by_role("button", name=re.compile(r"^Instance: (healthy|degraded|unhealthy)")).wait_for()
    page.wait_for_timeout(900)


def _signed_in(page: Page, url: str) -> None:
    page.goto(f"{url}/login")
    page.get_by_label("Username").fill(USERNAME)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url(f"{url}/")
    # Light, in the dirigent palette, as every picture on the page is.
    page.evaluate(
        "() => { localStorage.setItem('theme', 'light');"
        " localStorage.setItem('dirigent.palette', 'dirigent');"
        " localStorage.setItem('dirigent.terminalOpen', 'false') }"
    )


def _shot(page: Page, name: str) -> None:
    _settle(page)
    page.screenshot(path=OUT / f"{name}.png")


def _run_on_step(page: Page, url: str, run_id: str, step: str) -> None:
    """A run's screen with one step chosen, which is what opens its panel."""
    page.goto(f"{url}/runs/{run_id}")
    node = page.locator(".react-flow__node").filter(has_text=step)
    node.first.wait_for(timeout=30_000)
    node.get_by_text(step, exact=True).first.click()
    page.get_by_role("tab", name="Step", exact=True).wait_for()


def _output_at(page: Page, key: str) -> None:
    """Scroll a step's output to one key, past what comes before it."""
    line = page.get_by_text(f'"{key}"', exact=True).first
    line.wait_for()
    line.evaluate("(line) => line.scrollIntoView({ block: 'start' })")


def catalog(page: Page, url: str) -> None:
    """The Blocks screen narrowed to the pack, and the Examples screen on its templates."""
    page.goto(f"{url}/blocks")
    page.get_by_role("heading", name="Blocks").wait_for()
    page.get_by_label("Search blocks by id or summary").fill("dhis2")
    page.get_by_text("dhis2.tracker", exact=True).first.wait_for()
    # The counts come from a second read, of the corpus, which lands after the catalog.
    page.get_by_text(re.compile(r"^\d+ examples?$")).first.wait_for()
    _shot(page, "blocks")

    page.goto(f"{url}/examples?plugin=dhis2&starter=true")
    page.get_by_role("heading", name="Examples").wait_for()
    page.get_by_text("dhis2-rehearse-import", exact=True).first.wait_for()
    _shot(page, "examples-starters")


def walk(page: Page, url: str, token: str) -> None:
    """The tutorial's sections 2 to 7 against the play demo, photographed where the page does."""
    from dirigent_client import Dirigent

    documents = _documents()

    def call(work: Callable[[Dirigent], Awaitable[Any]]) -> Any:
        async def once() -> Any:
            async with Dirigent(url=url, token=token) as dg:
                return await work(dg)

        # Playwright's sync API holds an event loop on this thread, so the client gets its own.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, once()).result()

    def run(document: Json, expected: str) -> str:
        async def work(dg: Dirigent) -> str:
            await dg.pipelines.apply(document)
            accepted = await dg.pipelines.run(PIPELINE)
            if accepted.run_id is None:
                raise SystemExit(f"{PIPELINE} was not accepted")
            final = await dg.runs.wait(accepted.run_id)
            if final.status != expected:
                raise SystemExit(f"{PIPELINE} ended {final.status}, not {expected}: is the play demo answering?")
            return str(accepted.run_id)

        result: str = call(work)
        return result

    # Section 2: the connection, checked.
    call(lambda dg: dg.connections.create(**CONNECTION))
    report = call(lambda dg: dg.connections.check(CONNECTION["code"]))
    if report.healthy is not True:
        raise SystemExit(f"the play demo did not answer healthy: {report}")
    page.goto(f"{url}/connections")
    page.get_by_role("heading", name="Connections").wait_for()
    page.get_by_text(CONNECTION["code"], exact=True).first.wait_for()
    _shot(page, "connections")

    # Section 3: the first read.
    first = run(documents["first"], "succeeded")
    _run_on_step(page, url, first, "read")
    _output_at(page, "organisationUnits")
    _shot(page, "run-first")

    # Section 4: the schema handed to the instance, and the gate naming it.
    call(lambda dg: dg.schemas.create(_schema()))
    run(documents["gated"], "succeeded")
    page.goto(f"{url}/schemas/{SCHEMA}")
    page.get_by_role("heading", name="Schemas").wait_for()
    _shot(page, "schema")

    page.goto(f"{url}/pipelines/{PIPELINE}/edit")
    page.locator(".react-flow__node").get_by_text("check", exact=True).click()
    page.locator("aside").get_by_role("heading", name="Config").wait_for()
    page.locator("aside").get_by_text(str(_schema()["title"]), exact=True).first.click()
    page.get_by_text("Open in Schemas").wait_for()
    page.get_by_text("Open in Schemas").scroll_into_view_if_needed()
    _shot(page, "step-check")

    # Section 5: the rehearsed import, a dry run.
    rehearsed = run(documents["full"], "succeeded")
    _run_on_step(page, url, rehearsed, "rehearse")
    _shot(page, "run-import-summary")

    page.goto(f"{url}/pipelines/{PIPELINE}")
    page.locator(".react-flow__node").get_by_text("rehearse", exact=True).wait_for()
    _shot(page, "pipeline")

    # Section 6: a refusal, then the document put right again.
    refused = run(documents["broken"], "failed")
    _run_on_step(page, url, refused, "read")
    _shot(page, "run-rejected")
    call(lambda dg: dg.pipelines.apply(documents["full"]))

    # Section 7: what the page leaves behind.
    page.goto(f"{url}/")
    page.get_by_role("heading", name="Dashboard").wait_for()
    _shot(page, "dashboard")


def main() -> int:
    """Start an instance with the pack installed, photograph it, and stop it."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("sets", nargs="*", choices=["catalog", "walk"], help="Which pictures; both when omitted.")
    parser.add_argument("--port", type=int, default=3376, help="The loopback port the instance binds.")
    arguments = parser.parse_args()
    sets = arguments.sets or ["catalog", "walk"]
    if not _free(arguments.port):
        raise SystemExit(f"port {arguments.port} is in use; name another with --port")

    from playwright.sync_api import sync_playwright

    url = f"http://127.0.0.1:{arguments.port}"
    with tempfile.TemporaryDirectory(prefix="dirigent-dhis2-shots-") as state:
        log = Path(state) / "dev.ndjson"
        dg = str(Path(sys.executable).parent / "dg")
        # A connection's secret is sealed under the instance's key, so the walk's instance needs one.
        key = subprocess.run([dg, "secret-key"], check=True, capture_output=True, text=True).stdout.strip()
        environment = {**os.environ, "DIRIGENT_WORKER_NAME": "worker-1", "DIRIGENT_SECRET_KEY": key}
        with log.open("w") as sink:
            instance = subprocess.Popen(
                [dg, "dev", "--host", "127.0.0.1", "--port", str(arguments.port)],
                cwd=state,
                env=environment,
                stdout=sink,
                stderr=subprocess.DEVNULL,
            )
        try:
            _wait_for(url, time.monotonic() + 120)
            token = _token(log, time.monotonic() + 30)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
                _signed_in(page, url)
                if "catalog" in sets:
                    catalog(page, url)
                if "walk" in sets:
                    walk(page, url, token)
                browser.close()
        finally:
            instance.terminate()
            instance.wait(timeout=30)
    print(f"wrote the {' and '.join(sets)} pictures into {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
