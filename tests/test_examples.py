"""The pack's native examples must conform to its own contribution, checked by the kit.

``check_pack_examples`` re-derives the structural half of the engine's preflight over the
pack's own ``Contribution`` and its ``examples/dhis2`` documents: each is a ``dirigent/v1``
pipeline coded after its file, every block a step names is one the pack contributes, each
config fits that block's published schema, and a named connection is carried. The
``examples/dhis2-http`` shelf is deliberately built from generic ``http.*`` blocks this pack
does not contribute, so it is out of scope for a single-pack conformance check.

``examples/dhis2-compose`` mixes the two: ``dhis2.*`` steps beside engine blocks such as
``transform.jq`` and ``validate.schema``. Its ``dhis2.*`` steps are held to the same catalog
as the native shelf by checking each document with its foreign steps removed.

``examples/validate`` names engine blocks only, so removing its foreign steps leaves the
document's own identity -- format, kind, code and description -- which is the half a
single-pack check can answer for.
"""

from pathlib import Path
from typing import Any, cast

import yaml

from dirigent_dhis2 import Dhis2Plugin
from dirigent_testing import assert_contribution_conforms, check_pack_examples

#: The native shelf: the documents built from the ``dhis2.*`` blocks this pack contributes.
EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "dhis2"

#: The composed shelf: ``dhis2.*`` steps beside the engine's own blocks.
COMPOSE_DIR = Path(__file__).resolve().parents[1] / "examples" / "dhis2-compose"

#: The validation shelf: a metadata read gated on the engine's own ``validate.schema``.
VALIDATE_DIR = Path(__file__).resolve().parents[1] / "examples" / "validate"

#: What the pack itself puts in the catalog, checked once and reused by both tests.
CONTRIBUTION = Dhis2Plugin().contribute()


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
