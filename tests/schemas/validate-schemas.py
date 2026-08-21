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


def negative_control_floor_problems(root, controls, failures, minimum=None):
    """The control population may not shrink by accident.

    Reported through `failures` like every other check here, and taking its
    floor as an argument. Both matter: reporting through a bare
    `print(...); return 1` put this site outside the coverage meta-gate's
    measured population, and testing `root == DEFAULT_ROOT` inline meant no
    self-test case could ever reach it -- the self-test drives main() over
    temp roots. The floor that exists to stop 31% of the controls being
    deleted was itself deletable with every gate green (round 20)."""
    if minimum is None:
        if root != DEFAULT_ROOT:
            # A floor is a statement about THIS tree's population, not a
            # minimum any tree must meet.
            return
        minimum = MINIMUM_NEGATIVE_CONTROLS
    if controls < minimum:
        failures.append(
            f"{controls} negative control(s), below the floor of {minimum}. "
            "Controls are the only evidence these schemas reject anything; "
            "losing them silently shrinks that evidence.")

# The negative-control population may not shrink by accident. Failing only at
# ZERO meant 31% of the controls could be deleted with `make all` green — and
# the JSON count still cleared check-layout.sh's own floor. Raise this in the
# same change that legitimately removes one.
MINIMUM_NEGATIVE_CONTROLS = 49

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


def self_test() -> int:
    """Prove this gate can fail, over a throwaway tree.

    Every sibling gate runs a self-test first and the Makefile says so four
    times. The gate that owns all 49 negative controls had none, so its
    location comparison could be deleted and a fixture pointed at a location it
    does not fail at with `make check` still green. That is the exact shape the
    declaration mechanism was added to close, one level up.

    Each case builds a minimal root and drives `main()`, so the wiring from
    "problem found" to "non-zero exit" is covered too.
    """
    import contextlib, io, json as _json, tempfile

    SCHEMA = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"stability": {"const": "unstable"}},
        "required": ["stability"],
        "patternProperties": {"^x_": {"type": "string"}},
        "additionalProperties": False,
    }

    def run(positive, negatives):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "parts" / "examples" / "negative").mkdir(parents=True)
            (root / "parts" / "part-data.schema.json").write_text(_json.dumps(SCHEMA))
            (root / "parts" / "examples" / "good.part.json").write_text(_json.dumps(positive))
            for name, body in negatives.items():
                (root / "parts" / "examples" / "negative" / name).write_text(_json.dumps(body))
            argv = sys.argv
            sys.argv = ["validate-schemas.py", str(root)]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out, \
                     contextlib.redirect_stderr(io.StringIO()) as err:
                    code = main()
                return code, out.getvalue() + err.getvalue()
            finally:
                sys.argv = argv

    good = {"stability": "unstable"}
    control = {"stability": "stable",
               "x_negative_control": "REJECTED at /stability: stability is const"}

    cases = []
    code, _ = run(good, {"n1.part.json": control})
    cases.append(("a well-formed root passes", code == 0))

    code, text = run(good, {"n1.part.json": dict(control, stability="unstable")})
    cases.append(("a control that VALIDATES is caught",
                  code == 1 and "unexpectedly VALIDATES" in text))

    code, text = run(good, {"n1.part.json": dict(
        control, x_negative_control="REJECTED at /nowhere: points at nothing")})
    cases.append(("a control declaring a location it does not fail at is caught",
                  code == 1 and "actually fails at" in text))

    code, text = run(good, {"n1.part.json": dict(control, extra_defect=1)})
    cases.append(("a control failing somewhere it does not declare is caught",
                  code == 1 and "actually fails at" in text))

    # THREE BRANCHES an auditor found uncovered. Each fires; none had a case.
    def run_raw(build):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "parts" / "examples" / "negative").mkdir(parents=True)
            build(root)
            argv = sys.argv
            sys.argv = ["validate-schemas.py", str(root)]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out, \
                     contextlib.redirect_stderr(io.StringIO()) as err:
                    return main(), out.getvalue() + err.getvalue()
            finally:
                sys.argv = argv

    def _no_schema(root):
        # examples present, schema deleted: without this branch the root's
        # examples and all its negative controls stop being validated silently.
        (root / "parts" / "examples" / "good.part.json").write_text(_json.dumps(good))
    code, text = run_raw(_no_schema)
    cases.append(("examples with no schema to validate them are caught",
                  code == 1 and "declares NO *.schema.json" in text))

    def _bad_schema(root):
        (root / "parts" / "part-data.schema.json").write_text(
            _json.dumps({"type": "not-a-type"}))
        (root / "parts" / "examples" / "good.part.json").write_text(_json.dumps(good))
    code, text = run_raw(_bad_schema)
    cases.append(("a malformed schema is caught, not skipped",
                  code == 1 and "not a well-formed JSON Schema" in text))

    def _stray(root):
        (root / "parts" / "part-data.schema.json").write_text(_json.dumps(SCHEMA))
        (root / "parts" / "examples" / "good.part.json").write_text(_json.dumps(good))
        (root / "parts" / "examples" / "negative" / "n1.part.json").write_text(
            _json.dumps(control))
        # a mapped suffix outside every declared examples/ directory
        (root / "parts" / "elsewhere").mkdir()
        (root / "parts" / "elsewhere" / "orphan.part.json").write_text(
            _json.dumps({"stability": "whatever it likes"}))
    code, text = run_raw(_stray)
    cases.append(("a mapped example outside examples/ is caught",
                  code == 1 and "no gate validates it" in text))

    code, text = run(good, {"n1.part.json": {"stability": "stable"}})
    cases.append(("a control with no declaration is caught",
                  code == 1 and "does not declare where it fails" in text))

    code, text = run(good, {"n1.txt.json": control})
    cases.append(("an example matched by no suffix rule is caught",
                  code == 1 and "no example-to-schema mapping" in text))

    # THE FLOOR ITSELF. It was written to stop 31% of the controls being
    # deleted, and until round 20 nothing exercised it: it printed straight
    # to stderr (invisible to the coverage meta-gate) behind a
    # `root == DEFAULT_ROOT` test no temp-root case could satisfy.
    _floor = []
    negative_control_floor_problems(Path("/nowhere"), 4, _floor, minimum=5)
    cases.append(("a control population under its floor is caught",
                  any("below the floor of 5" in x for x in _floor)))
    _at_floor = []
    negative_control_floor_problems(Path("/nowhere"), 5, _at_floor, minimum=5)
    cases.append(("a population at its floor passes", _at_floor == []))
    _other_tree = []
    negative_control_floor_problems(Path("/nowhere"), 0, _other_tree)
    cases.append(("this tree's floor is not imposed on another tree",
                  _other_tree == []))
    # WIRING: raise the real floor above the real population and main() --
    # over the real root, the only place the floor applies -- must go red.
    _real_floor = MINIMUM_NEGATIVE_CONTROLS
    _real_argv = sys.argv
    globals()["MINIMUM_NEGATIVE_CONTROLS"] = 10_000
    sys.argv = [_real_argv[0]]
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as _err:
            _wired = main()
    finally:
        globals()["MINIMUM_NEGATIVE_CONTROLS"] = _real_floor
        sys.argv = _real_argv
    cases.append(("the floor is WIRED into main() over the real tree",
                  _wired == 1 and "below the floor of 10000" in _err.getvalue()))

    code, text = run({"stability": "stable"}, {"n1.part.json": control})
    cases.append(("an invalid POSITIVE example is caught", code == 1))

    code, text = run(good, {})
    cases.append(("a root with no negative controls is caught",
                  code == 1 and "ships no negative controls" in text))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"schemas: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"schemas: self-test PASS: {len(cases)} cases.")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        return self_test()
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

    negative_control_floor_problems(root, totals[2], failures)

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
