"""Every version the documentation names as the current one is the pack's own version.

A mention is a pinned dirigent package (``dirigent-dhis2==0.30.0``), the dirigent image tag, a
``dg 0.30.0`` line, or the ``version=`` of a captured ``dg init`` record. ``docs/releases.md``
is left out, since its versions are history.
"""

import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[1]

with (ROOT / "pyproject.toml").open("rb") as _handle:
    VERSION: Final = str(tomllib.load(_handle)["project"]["version"])

_V: Final = r"(\d+\.\d+\.\d+)"

#: Each pattern's first group is the version it names.
MENTIONS: Final = (
    re.compile(rf"\bdirigent(?:-[a-z0-9]+)*=={_V}"),
    re.compile(rf"ghcr\.io/winterop-com/dirigent:v?{_V}"),
    re.compile(rf"\bdg {_V}\b"),
    re.compile(rf"\[(?:instance\.initialised|project\.scaffolded)\].*?\bversion={_V}"),
)

PAGES: Final = [
    path
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    if path.is_file() and path != ROOT / "docs" / "releases.md"
]


def _mentions(path: Path) -> list[tuple[int, str]]:
    """Each version the page names, with its line number."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern in MENTIONS:
            found += [(number, match.group(1)) for match in pattern.finditer(line)]
    return found


def test_the_tutorial_names_a_version() -> None:
    assert _mentions(ROOT / "docs" / "tutorial.md")


@pytest.mark.parametrize("page", PAGES, ids=lambda page: str(page.relative_to(ROOT)))
def test_every_named_version_is_the_packs(page: Path) -> None:
    stale = [f"line {number}: {version}" for number, version in _mentions(page) if version != VERSION]
    assert not stale, f"{page.relative_to(ROOT)} names another version than {VERSION}: {stale}"
