"""The pack's native examples must conform to its own contribution, checked by the kit.

``check_pack_examples`` re-derives the structural half of the engine's preflight over the
pack's own ``Contribution`` and its ``dhis2`` shelf's documents: each is a ``dirigent/v1``
pipeline coded after its file, every block a step names is one the pack contributes, each
config fits that block's published schema, and a named connection is carried. The
``dhis2-http`` shelf is deliberately built from generic ``http.*`` blocks this pack
does not contribute, so it is out of scope for a single-pack conformance check.

``dhis2-compose`` mixes the two: ``dhis2.*`` steps beside engine blocks such as
``transform.jq`` and ``validate.schema``. Its ``dhis2.*`` steps are held to the same catalog
as the native shelf by checking each document with its foreign steps removed.

``validate`` names engine blocks only, so removing its foreign steps leaves the
document's own identity -- format, kind, code and description -- which is the half a
single-pack check can answer for.
"""

from pathlib import Path
from typing import Any, cast

import yaml

from dirigent_dhis2 import Dhis2Plugin
from dirigent_testing import assert_contribution_conforms, check_pack_examples

#: The shelves root, taken from the hook the pack ships them through.
SHELVES = Path(str(Dhis2Plugin().examples()[0]))

#: The native shelf: the documents built from the ``dhis2.*`` blocks this pack contributes.
EXAMPLES_DIR = SHELVES / "dhis2"

#: The composed shelf: ``dhis2.*`` steps beside the engine's own blocks.
COMPOSE_DIR = SHELVES / "dhis2-compose"

#: The validation shelf: a metadata read gated on the engine's own ``validate.schema``.
VALIDATE_DIR = SHELVES / "validate"

#: The starter shelf: the same flows written the way an instance accepts them, naming a
#: connection rather than carrying one.
STARTERS_DIR = SHELVES / "starters"

#: The connection every starter names, and the kind it is.
STARTER_CONNECTION = "dhis2"

#: What the pack itself puts in the catalog, checked once and reused by both tests.
CONTRIBUTION = Dhis2Plugin().contribute()


def test_the_shelves_the_hook_answers_with_are_the_ones_in_the_package() -> None:
    assert SHELVES.is_dir(), f"the shelves directory {SHELVES} does not exist"
    assert SHELVES.name == "shelves" and SHELVES.parent.name == "dirigent_dhis2"


def test_there_are_native_examples_to_check() -> None:
    assert list(EXAMPLES_DIR.rglob("*.yaml")), "there are no native dhis2 examples to check"


def test_every_native_example_conforms_to_the_pack_catalog() -> None:
    issues = check_pack_examples(CONTRIBUTION, EXAMPLES_DIR)
    assert issues == [], "\n".join(issues)


def test_every_composed_example_uses_the_pack_blocks_correctly(tmp_path: Path) -> None:
    documents = sorted(COMPOSE_DIR.rglob("*.yaml"))
    assert documents, "there are no composed dhis2 examples to check"
    for path in documents:
        (tmp_path / path.name).write_text(yaml.safe_dump(_only_pack_steps(path), sort_keys=False))
    issues = check_pack_examples(CONTRIBUTION, tmp_path)
    assert issues == [], "\n".join(issues)


def test_every_validation_example_carries_the_identity_a_document_needs(tmp_path: Path) -> None:
    documents = sorted(VALIDATE_DIR.rglob("*.yaml"))
    assert documents, "there are no validation examples to check"
    for path in documents:
        (tmp_path / path.name).write_text(yaml.safe_dump(_only_pack_steps(path), sort_keys=False))
    issues = check_pack_examples(CONTRIBUTION, tmp_path)
    assert issues == [], "\n".join(issues)


def test_every_validation_example_names_the_schema_it_gates_on() -> None:
    """A gate names a schema by code, and a code the instance holds is declared in requires."""
    for path in sorted(VALIDATE_DIR.rglob("*.yaml")):
        document = cast("dict[str, Any]", yaml.safe_load(path.read_text()))
        steps = cast("dict[str, Any]", document.get("steps", {}))
        gates = [step for step in steps.values() if step.get("block") == "validate.schema"]
        assert gates, f"{path.name}: has no validate.schema step"
        carried = set(cast("dict[str, Any]", document.get("schemas", {})))
        declared = set(cast("dict[str, Any]", document.get("requires", {})).get("schemas", []))
        for gate in gates:
            code = cast("dict[str, Any]", gate.get("config", {})).get("schema")
            assert code in carried | declared, f"{path.name}: gate names schema {code!r}, neither carried nor required"


def test_the_contribution_blocks_are_well_formed() -> None:
    issues = assert_contribution_conforms(CONTRIBUTION)
    assert issues == [], "\n".join(issues)


def _only_pack_steps(path: Path) -> dict[str, Any]:
    """Read a document with every step naming a block outside this pack dropped.

    ``check_pack_examples`` is a single-pack check and reports a step naming another
    plugin's block as an unknown one. Dropping those leaves the ``dhis2.*`` steps and the
    document around them, which is exactly the half this pack answers for.
    """
    document = cast("dict[str, Any]", yaml.safe_load(path.read_text()))
    steps = cast("dict[str, Any]", document.get("steps", {}))
    document["steps"] = {
        name: step
        for name, step in steps.items()
        if isinstance(step, dict) and str(cast("dict[str, Any]", step).get("block", "")).startswith("dhis2.")
    }
    return document


#: The floor under the pack's starter set: fewer than this and the menu is not worth opening.
STARTERS_AT_LEAST = 6


def _starters() -> list[Path]:
    """The documents that opted into being copied by ``dg pipeline new``."""
    found: list[Path] = []
    for path in sorted(SHELVES.rglob("*.yaml")):
        document = cast("dict[str, Any]", yaml.safe_load(path.read_text()))
        if "starter" in cast("list[str]", document.get("tags", [])):
            found.append(path)
    return found


def test_the_pack_carries_a_curated_set_of_starters() -> None:
    starters = _starters()
    assert len(starters) >= STARTERS_AT_LEAST, f"only {len(starters)} documents are tagged starter"


def test_a_starter_clears_the_bar_for_being_copied() -> None:
    for path in _starters():
        document = cast("dict[str, Any]", yaml.safe_load(path.read_text()))
        assert len(cast("dict[str, Any]", document.get("steps", {}))) >= 2, f"{path.name}: a starter is a flow"
        assert not document.get("connections"), f"{path.name}: a starter names its connections, it does not carry them"
        assert not document.get("schemas"), f"{path.name}: a starter names its schemas, it does not carry them"
        assert document.get("description"), f"{path.name}: a starter says what it is for"
        required = cast("dict[str, Any]", document.get("requires", {}))
        assert STARTER_CONNECTION in cast("list[str]", required.get("connections", [])), (
            f"{path.name}: a starter declares the connection it names in requires.connections"
        )


def test_every_starter_is_on_the_starter_shelf() -> None:
    for path in _starters():
        assert path.parent == STARTERS_DIR, f"{path.name}: a starter belongs on the starters shelf"


def test_every_starter_uses_the_pack_blocks_correctly(tmp_path: Path) -> None:
    """A starter names its connection, so the single-pack check is given one to find.

    ``check_pack_examples`` insists a step's connection is carried by the document, which is
    the one thing a starter must not do. Writing the connection in on the way to the check
    holds the starters to the same catalog as every other shelf.
    """
    documents = sorted(STARTERS_DIR.rglob("*.yaml"))
    assert documents, "there are no starters to check"
    for path in documents:
        document = _only_pack_steps(path)
        document["connections"] = {STARTER_CONNECTION: {"kind": "dhis2", "config": {"base_url": "https://example.org"}}}
        (tmp_path / path.name).write_text(yaml.safe_dump(document, sort_keys=False))
    issues = check_pack_examples(CONTRIBUTION, tmp_path)
    assert issues == [], "\n".join(issues)
