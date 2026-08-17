#!/usr/bin/env python3
"""Validate Rhoform JSON Schemas and their examples.

Contract, applied independently to every root declared in SCHEMA_ROOTS:
  - every <root>/**/*.schema.json (outside <root>/examples/) must parse as
    JSON and be a well-formed JSON Schema under its own declared metaschema;
  - example JSON lives FLAT under <root>/examples/ and is routed to its
    schema by an explicit suffix mapping declared per root:
        ir/    *.ir.json        -> netlist-ir.schema.json
               *.sourcemap.json -> source-map.schema.json
        parts/ *.part.json      -> part-data.schema.json
        eval/  *.run.json       -> run-result.schema.json
        lang/  *.design.json    -> design-model.schema.json
  - files under <root>/examples/negative/ are expected-INVALID controls:
    each must parse as JSON and then FAIL schema validation; a negative
    control that validates is an error;
  - every other JSON file under <root>/examples/ must validate against its
    mapped schema;
  - any *.json under <root>/examples/ matched by no mapping rule is a hard
    failure, so a new example layout cannot be silently skipped;
  - a root that declares schemas but ships no negative controls is a hard
    failure: a schema never shown to reject anything is an untested schema;
  - files are processed in sorted order and failures are collected, so
    output is deterministic and complete rather than first-error-only.

Adding a schema root is a one-line change to SCHEMA_ROOTS below. Declared
roots that do not exist yet are skipped, so the table may lead the tree.

Exit codes: 0 pass (including "no schemas yet"), 1 validation failure,
2 environment failure (jsonschema missing while schemas exist — an
unavailable gate is not a pass).

Usage: validate-schemas.py [repo-root]
  repo-root defaults to the repository containing this script; passing
  it lets the gate run against a staged tree.

Requires the pinned jsonschema from toolchain/versions.yaml:
    python3 -m pip install jsonschema==4.26.0
"""

import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent

# Declared schema roots: top-level directory -> example-filename suffixes
# it recognises and the schema each routes to. Extend this table in the
# same change that introduces a new schema or example suffix; unmatched
# JSON under any examples/ directory fails the gate rather than being
# skipped.
SCHEMA_ROOTS = {
    "ir": (
        (".ir.json", "netlist-ir.schema.json"),
        (".sourcemap.json", "source-map.schema.json"),
    ),
    "parts": ((".part.json", "part-data.schema.json"),),
    "eval": ((".run.json", "run-result.schema.json"),),
    "lang": ((".design.json", "design-model.schema.json"),),
}

NEGATIVE_DIR_NAME = "negative"

# Every negative fixture carries its own statement of what it proves, in this
# member, and the statement is machine-checked.
#
# WHY. A negative control earns its keep only if the guarantee it names is the
# reason it is rejected. Asserting merely "≥1 error" does not establish that,
# and the difference is not academic: all 16 part-data controls carried an
# `x_negative_control` OBJECT while that schema's extension rule caps `x_`
# members at scalars, so every one of them failed on its own metadata as well
# as on its subject — and 15 of the 15 guarantees they name could be deleted
# with the gate green. Every `lang/` control was missing the required `anchor`,
# and five `eval/` controls carried `e03`'s missing-power defect: same disease,
# three more roots, found only once this check existed.
#
# The declaration also documents the fixture. A reader sees the exact pointer
# the defect lives at without running anything, and a defect that legitimately
# spans several fields (a cross-field consistency rule) says so explicitly
# rather than being waved through by a loosened threshold.
CONTROL_KEY = "x_negative_control"
CONTROL_PREFIX = re.compile(r"^REJECTED at (?P<locs>[^:]+):")


def declared_locations(example):
    """The JSON Pointers a negative control says it fails at, or None."""
    if not isinstance(example, dict):
        return None
    control = example.get(CONTROL_KEY)
    if not isinstance(control, str):
        return None
    match = CONTROL_PREFIX.match(control.strip())
    if not match:
        return None
    return {loc.strip() for loc in match.group("locs").split("+") if loc.strip()}


def load_json(path, rel, failures):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        failures.append(f"{rel}: does not parse as JSON: {exc}")
        return None


def check_root(root, root_name, suffix_map, jsonschema, failures):
    """Validate one schema root. Returns (schemas, positives, negatives)."""
    root_dir = root / root_name
    examples_dir = root_dir / "examples"

    schema_paths = sorted(
        p for p in root_dir.rglob("*.schema.json") if examples_dir not in p.parents
    )
    if not schema_paths:
        # A root that has examples but no schema is a DELETED or RENAMED
        # schema, not an empty root. Reporting "nothing to validate" and
        # exiting 0 would mean removing a schema file silently disables its
        # entire root — every example and every negative control with it.
        stray = sorted(examples_dir.rglob("*.json")) if examples_dir.is_dir() else []
        if stray:
            failures.append(
                f"{root_name}/: {len(stray)} example file(s) exist under "
                f"{root_name}/examples/ but the root declares NO *.schema.json. "
                "A schema was deleted or renamed, which would otherwise switch "
                "off this root's validation silently."
            )
            return 0, 0, 0
        print(f"schemas: {root_name}/: no *.schema.json files; nothing to validate.")
        return 0, 0, 0

    validators = {}
    for schema_path in schema_paths:
        rel = schema_path.relative_to(root)
        schema = load_json(schema_path, rel, failures)
        if schema is None:
            continue
        validator_cls = jsonschema.validators.validator_for(schema)
        try:
            validator_cls.check_schema(schema)
        except jsonschema.SchemaError as exc:
            failures.append(f"{rel}: not a well-formed JSON Schema: {exc.message}")
            continue
        validators[schema_path.name] = validator_cls(schema)
        print(f"schemas: {rel}: well-formed.")

    positive_count = 0
    negative_count = 0

    example_paths = sorted(examples_dir.rglob("*.json")) if examples_dir.is_dir() else []
    for example_path in example_paths:
        rel = example_path.relative_to(root)
        rel_to_examples = example_path.relative_to(examples_dir)
        expect_invalid = NEGATIVE_DIR_NAME in rel_to_examples.parts[:-1]

        schema_name = next(
            (s for suffix, s in suffix_map if example_path.name.endswith(suffix)),
            None,
        )
        if schema_name is None:
            known = ", ".join(suffix for suffix, _ in suffix_map)
            failures.append(
                f"{rel}: matched by no example-to-schema mapping rule for root "
                f"{root_name}/ (known suffixes: {known}); rename the file to "
                "one of those suffixes, extend SCHEMA_ROOTS, or remove it. "
                "This applies to negative controls too: a file under "
                "examples/negative/ still needs a mapped suffix so the gate "
                "knows which schema it must fail against."
            )
            continue

        validator = validators.get(schema_name)
        if validator is None:
            failures.append(
                f"{rel}: cannot validate: mapped schema {schema_name} is "
                "missing or malformed."
            )
            continue

        example = load_json(example_path, rel, failures)
        if example is None:
            continue

        errors = sorted(validator.iter_errors(example), key=str)
        if expect_invalid:
            negative_count += 1
            if not errors:
                failures.append(
                    f"{rel}: negative control unexpectedly VALIDATES against "
                    f"{schema_name}; expected-invalid examples must fail."
                )
            elif (declared := declared_locations(example)) is None:
                failures.append(
                    f"{rel}: negative control does not declare where it fails. "
                    f"Its `{CONTROL_KEY}` must be a string starting "
                    f"`REJECTED at <json-pointer>[ + <json-pointer>...]: ` so "
                    "the gate can check that the fixture fails THERE and only "
                    "there."
                )
            elif declared != (actual := {
                "/" + "/".join(str(p) for p in e.absolute_path) for e in errors
            }):
                failures.append(
                    f"{rel}: negative control declares it fails at "
                    f"{sorted(declared)} but actually fails at {sorted(actual)}. "
                    "A control that fails somewhere it does not name would "
                    "still be rejected with its guarantee removed, so it stops "
                    "testing that guarantee and nothing says so."
                )
            else:
                print(f"schemas: {rel}: invalid as expected, at the {len(declared)} location(s) it declares: {', '.join(sorted(declared))}.")
        else:
            positive_count += 1
            for error in errors:
                path = "/".join(str(part) for part in error.absolute_path) or "<root>"
                failures.append(f"{rel}: at {path}: {error.message}")
            if not errors:
                print(f"schemas: {rel}: valid against {schema_name}.")

    # A schema whose rejections are never exercised is an untested schema.
    if negative_count == 0:
        failures.append(
            f"{root_name}/: declares {len(schema_paths)} schema(s) but ships no "
            f"negative controls under {root_name}/examples/negative/. A schema "
            "never shown to reject anything is untested; add at least one "
            "expected-invalid fixture."
        )

    return len(schema_paths), positive_count, negative_count


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_ROOT

    present = [name for name in sorted(SCHEMA_ROOTS) if (root / name).is_dir()]
    if not present:
        print("schemas: no declared schema roots present yet; nothing to validate.")
        return 0

    try:
        import jsonschema
    except ImportError:
        print(
            "schemas: FAIL: schema roots exist but the jsonschema package is "
            "unavailable; install the pin from toolchain/versions.yaml "
            "(python3 -m pip install jsonschema==4.26.0).",
            file=sys.stderr,
        )
        return 2

    failures = []
    totals = [0, 0, 0]

    # A file carrying a mapped example suffix but living outside any
    # declared examples/ directory is validated by nothing. `make check`
    # would pass over a whole part library sitting one directory to the
    # left, which is the failure mode most likely to happen in practice as
    # the seed library grows.
    mapped_suffixes = sorted(
        {suffix for suffixes in SCHEMA_ROOTS.values() for suffix, _ in suffixes}
    )
    known_example_dirs = [root / name / "examples" for name in SCHEMA_ROOTS]
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv"}
    for path in sorted(root.rglob("*.json")):
        if skip_dirs & set(path.parts):
            continue
        if not any(path.name.endswith(suffix) for suffix in mapped_suffixes):
            continue
        if any(d in path.parents for d in known_example_dirs):
            continue
        failures.append(
            f"{path.relative_to(root)}: carries a mapped example suffix but sits "
            "outside every declared <root>/examples/ directory, so no gate "
            "validates it. Move it under the right examples/ directory or "
            "rename it."
        )

    for root_name in present:
        counts = check_root(
            root, root_name, SCHEMA_ROOTS[root_name], jsonschema, failures
        )
        totals = [a + b for a, b in zip(totals, counts)]

    if failures:
        for failure in failures:
            print(f"schemas: FAIL: {failure}", file=sys.stderr)
        print(f"schemas: {len(failures)} failure(s).", file=sys.stderr)
        return 1

    print(
        f"schemas: PASS: {totals[0]} schema(s) across {len(present)} root(s), "
        f"{totals[1]} valid example(s), "
        f"{totals[2]} negative control(s) rejected as expected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
