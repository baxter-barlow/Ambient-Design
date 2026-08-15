#!/usr/bin/env python3
"""Validate AED typed-netlist IR schemas and their examples.

Contract:
  - every ir/**/*.schema.json (outside ir/examples/) must parse as JSON
    and be a well-formed JSON Schema under its own declared metaschema;
  - example JSON lives FLAT under ir/examples/ and is routed to its
    schema by an explicit suffix mapping:
        *.ir.json        -> netlist-ir.schema.json
        *.sourcemap.json -> source-map.schema.json
  - files under ir/examples/negative/ are expected-INVALID controls:
    each must parse as JSON and then FAIL schema validation; a negative
    control that validates is an error;
  - every other JSON file under ir/examples/ must validate against its
    mapped schema;
  - any *.json under ir/examples/ matched by no mapping rule is a hard
    failure, so a new example layout cannot be silently skipped;
  - files are processed in sorted order and failures are collected, so
    output is deterministic and complete rather than first-error-only.

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
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent

# Explicit example-to-schema routing. Extend this mapping in the same
# change that introduces a new schema or example suffix; unmatched JSON
# under ir/examples/ fails the gate rather than being skipped.
SUFFIX_TO_SCHEMA = (
    (".ir.json", "netlist-ir.schema.json"),
    (".sourcemap.json", "source-map.schema.json"),
)

NEGATIVE_DIR_NAME = "negative"


def load_json(path, rel, failures):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        failures.append(f"{rel}: does not parse as JSON: {exc}")
        return None


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_ROOT
    ir_dir = root / "ir"
    examples_dir = ir_dir / "examples"

    if not ir_dir.is_dir():
        print("schemas: no ir/ directory yet; nothing to validate.")
        return 0

    schema_paths = sorted(
        p for p in ir_dir.rglob("*.schema.json") if examples_dir not in p.parents
    )
    if not schema_paths:
        print("schemas: no *.schema.json files under ir/; nothing to validate.")
        return 0

    try:
        import jsonschema
    except ImportError:
        print(
            "schemas: FAIL: ir/ contains schemas but the jsonschema package "
            "is unavailable; install the pin from toolchain/versions.yaml "
            "(python3 -m pip install jsonschema==4.26.0).",
            file=sys.stderr,
        )
        return 2

    failures = []
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
            (s for suffix, s in SUFFIX_TO_SCHEMA if example_path.name.endswith(suffix)),
            None,
        )
        if schema_name is None:
            known = ", ".join(suffix for suffix, _ in SUFFIX_TO_SCHEMA)
            failures.append(
                f"{rel}: matched by no example-to-schema mapping rule "
                f"(known suffixes: {known}); rename the file to one of "
                "those suffixes, extend SUFFIX_TO_SCHEMA, or remove it. "
                "This applies to negative controls too: a file under "
                "examples/negative/ still needs a mapped suffix so the "
                "gate knows which schema it must fail against."
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
            else:
                print(f"schemas: {rel}: invalid as expected ({len(errors)} error(s)).")
        else:
            positive_count += 1
            for error in errors:
                path = "/".join(str(part) for part in error.absolute_path) or "<root>"
                failures.append(f"{rel}: at {path}: {error.message}")
            if not errors:
                print(f"schemas: {rel}: valid against {schema_name}.")

    if failures:
        for failure in failures:
            print(f"schemas: FAIL: {failure}", file=sys.stderr)
        print(f"schemas: {len(failures)} failure(s).", file=sys.stderr)
        return 1

    print(
        f"schemas: PASS: {len(schema_paths)} schema(s), "
        f"{positive_count} valid example(s), "
        f"{negative_count} negative control(s) rejected as expected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
