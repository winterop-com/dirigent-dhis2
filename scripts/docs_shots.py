"""Photograph the tutorial's catalog pictures from a local instance with this pack installed.

The Blocks and Examples screens are dirigent's own UI reading the pack's catalog and corpus, so
neither needs a DHIS2: a throwaway ``dg dev`` with the pack beside it is the whole subject.
Chromium is driven through Playwright, layered in at call time like ``docs_pdf.py``'s:

    uv run --with dirigent-cli --with playwright playwright install chromium
    uv run --with dirigent-cli --with playwright python scripts/docs_shots.py

It writes ``docs/images/tutorial/blocks.png`` and ``docs/images/tutorial/examples-starters.png``.
The instance binds ``--port`` (3376 unless told otherwise) on loopback, keeps its state in a
temporary directory, and is stopped on the way out.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

#: The project root, one level above this script.
ROOT = Path(__file__).resolve().parent.parent

#: Where the pictures land, beside the page that renders them.
OUT = ROOT / "docs" / "images" / "tutorial"

#: The frame every picture is taken in.
WIDTH, HEIGHT = 1280, 800

#: The account ``dg dev`` creates on an empty instance.
USERNAME = PASSWORD = "admin"


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


def _shoot(url: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.goto(f"{url}/login")
        page.get_by_label("Username").fill(USERNAME)
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url(f"{url}/")
        # Light, in the dirigent palette, like the tutorial's other pictures.
        page.evaluate(
            "() => { localStorage.setItem('theme', 'light');"
            " localStorage.setItem('dirigent.palette', 'dirigent');"
            " localStorage.setItem('dirigent.terminalOpen', 'false') }"
        )

        page.goto(f"{url}/blocks")
        page.get_by_role("heading", name="Blocks").wait_for()
        page.get_by_label("Search blocks by id or summary").fill("dhis2")
        page.get_by_text("dhis2.tracker", exact=True).first.wait_for()
        # The counts come from a second read, of the corpus, which lands after the catalog.
        page.get_by_text(re.compile(r"^\d+ examples?$")).first.wait_for()
        _settle(page)
        page.screenshot(path=OUT / "blocks.png")

        page.goto(f"{url}/examples?plugin=dhis2&starter=true")
        page.get_by_role("heading", name="Examples").wait_for()
        page.get_by_text("dhis2-rehearse-import", exact=True).first.wait_for()
        _settle(page)
        page.screenshot(path=OUT / "examples-starters.png")

        browser.close()


def _settle(page: Page) -> None:
    """Wait until the corner has read the instance, so the topbar in the frame is the settled one."""
    page.get_by_role("button", name=re.compile(r"^Instance: (healthy|degraded|unhealthy)")).wait_for()
    page.wait_for_timeout(900)


def main() -> int:
    """Start an instance with the pack installed, photograph it, and stop it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=3376, help="The loopback port the instance binds.")
    arguments = parser.parse_args()
    if not _free(arguments.port):
        raise SystemExit(f"port {arguments.port} is in use; name another with --port")

    url = f"http://127.0.0.1:{arguments.port}"
    with tempfile.TemporaryDirectory(prefix="dirigent-dhis2-shots-") as state:
        environment = {**os.environ, "DIRIGENT_WORKER_NAME": "worker-1"}
        instance = subprocess.Popen(
            [str(Path(sys.executable).parent / "dg"), "dev", "--host", "127.0.0.1", "--port", str(arguments.port)],
            cwd=state,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for(url, time.monotonic() + 120)
            _shoot(url)
        finally:
            instance.terminate()
            instance.wait(timeout=30)
    print(f"wrote {OUT / 'blocks.png'} and {OUT / 'examples-starters.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
