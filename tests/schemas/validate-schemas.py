#!/usr/bin/env python3
"""Validate Rhoform JSON Schemas and their examples.

Contract, applied independently to every root declared in SCHEMA_ROOTS:
  - every <root>/**/*.schema.json (outside <root>/examples/) must parse as
    JSON and be a well-formed JSON Schema under its own declared metaschema;
  - example JSON lives FLAT under <root>/examples/ and is routed to its
    schema by an explicit suffix mapping declared per root:
        ir/    *.ir.json        -> by header.ir_version: 0 netlist-ir.schema.json,
                                   1 netlist-ir.v1.schema.json,
                                   2 netlist-ir.v2.schema.json
               *.sourcemap.json -> by sourcemap_version: 0 source-map.schema.json,
                                   1 source-map.v1.schema.json,
                                   2 source-map.v2.schema.json
        parts/ *.part.json      -> by schema_version: 0 part-data.schema.json,
                                   1 part-data.v1.schema.json
        eval/  *.run.json       -> run-result.schema.json
        lang/  *.design.json    -> design-model.schema.json
  - a versioned document goes to the schema of the version IT declares
    (ir/README.md: one immutable schema file per version), and one that
    declares no version, or a version no schema describes, is refused
    rather than validated against a neighbouring version's schema;
  - files under <root>/examples/negative/ are expected-INVALID controls:
    each must parse as JSON and then FAIL schema validation; a negative
    control that validates is an error. The one exception is a LINT control
    (its declaration starts `LINT-REJECTED`): it exists to prove a
    cross-reference check the schema cannot express, so it must VALIDATE,
    or it would fail for a reason other than the one it names. The part-data
    linter holds it to its own check, so the exception exists under parts/
    only, and a lint control under any other root is a failure;
  - every other JSON file under <root>/examples/ must validate against its
    mapped schema;
  - any *.json under <root>/examples/ matched by no mapping rule is a hard
    failure, so a new example layout cannot be silently skipped;
  - benchmark goldens, the compiler's committed output for each living
    benchmark source (benchmarks/<id>/<id>.ir.json and
    benchmarks/<id>/<id>.sourcemap.json), are validated as positives of the
    ir/ root, and so is the IR each elaboration or package conformance
    case must produce (spec/conformance/elaborate/accept/<case>
    .expected.ir.json, spec/conformance/packages/accept/<case>/
    expected.ir.json);
  - the bundled part store, rhoform/parts/<vendor>/<slug>.part.json, holds
    records the compiler reads, so each is a positive of the parts/ root,
    routed by its schema_version like any record;
    any other file with a mapped suffix outside an examples/ directory is
    still a failure;
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

# The IR and its source map are versioned, and a schema file is immutable
# per version (ir/README.md, "Versioning policy"): a version bump adds a
# file rather than editing one. So these suffixes route by the version a
# document declares, as (where it is declared, version -> schema file).
# A version missing here is one no backend may accept either, so it is
# refused; add the row in the same change that adds the schema file.
IR_VERSIONS = (("header", "ir_version"),
               {0: "netlist-ir.schema.json", 1: "netlist-ir.v1.schema.json",
                2: "netlist-ir.v2.schema.json"})
SOURCEMAP_VERSIONS = (("sourcemap_version",),
                      {0: "source-map.schema.json",
                       1: "source-map.v1.schema.json",
                       2: "source-map.v2.schema.json"})
# Part data follows the same rule: v0's file is immutable and v1 is a second
# file, so a record goes to the schema of the version it declares.
PART_VERSIONS = (("schema_version",),
                 {0: "part-data.schema.json", 1: "part-data.v1.schema.json"})

# Declared schema roots: top-level directory -> example-filename suffixes
# it recognises and the schema each routes to (a file name, or a version
# table as above). Extend this table in the same change that introduces a
# new schema or example suffix; unmatched JSON under any examples/
# directory fails the gate rather than being skipped.
SCHEMA_ROOTS = {
    "ir": (
        (".ir.json", IR_VERSIONS),
        (".sourcemap.json", SOURCEMAP_VERSIONS),
    ),
    "parts": ((".part.json", PART_VERSIONS),),
    "eval": ((".run.json", "run-result.schema.json"),),
    "lang": ((".design.json", "design-model.schema.json"),),
    "rhoform": ((".diag.json", "diagnostic.schema.json"),),
}

NEGATIVE_DIR_NAME = "negative"

# Goldens: compiler output committed beside the source it was built from,
# directory -> the schema root whose suffix mapping and schemas apply. They
# are not schema examples and do not live under an examples/ directory, but
# nothing else checks their shape, so they are positives of that root. A
# golden is exactly <directory>/<id>/<id><suffix>; tests/ir/check-hashes.py
# uses the same rule, so a misnamed file is a stray here rather than a
# document one gate checks and the other ignores.
GOLDEN_ROOTS = {"benchmarks": "ir"}

# The conformance cases' expected IR: compiler output too. Elaboration
# cases are one flat directory of <case>.expected.ir.json files, package
# cases one directory per case holding expected.ir.json. The conformance
# gate holds each to the compiler byte for byte; here each is held to the IR
# schema like any golden, so no mapped suffix sits outside examples/
# unvalidated. Entries: (directory, schema root, glob).
CONFORMANCE_GOLDENS = (
    ("spec/conformance/elaborate/accept", "ir", "*.expected.ir.json"),
    ("spec/conformance/packages/accept", "ir", "*/expected.ir.json"),
)

# The bundled part store: records the compiler reads, so positives of the
# parts/ root wherever they sit. A record's path is its part_id, exactly two
# segments deep; a file at any other depth is a stray, because no lookup
# would find it. Entries: (directory, schema root, glob).
STORE_RECORDS = (("rhoform/parts", "parts", "*/*.part.json"),)


def store_paths(root):
    """{schema root: [store record paths]}, each list sorted."""
    found = {}
    for directory, schema_root, pattern in STORE_RECORDS:
        for path in sorted((root / directory).glob(pattern)):
            found.setdefault(schema_root, []).append(path)
    return found


def golden_paths(root):
    """{schema root: [golden paths]}, each list sorted."""
    found = {}
    for directory, schema_root in sorted(GOLDEN_ROOTS.items()):
        for suffix, _schema in SCHEMA_ROOTS[schema_root]:
            for path in sorted((root / directory).glob(f"*/*{suffix}")):
                if path.name == path.parent.name + suffix:
                    found.setdefault(schema_root, []).append(path)
    for directory, schema_root, pattern in CONFORMANCE_GOLDENS:
        for path in sorted((root / directory).glob(pattern)):
            found.setdefault(schema_root, []).append(path)
    return {name: sorted(paths) for name, paths in found.items()}


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
# same change that legitimately removes one. 49 -> 59 when the diagnostic
# wire-format schema landed with its ten controls (AMB-48), 59 -> 61 with its
# n11 and n12, 61 -> 64 when D3 v1 added the part-data schema controls
# n17, n23 and n24 (AMB-127; n18-n22 are lint controls, counted by
# parts/lint-part-data.py), and 64 -> 72 when IR version 2 landed with its
# eight (ir/examples/negative/n10-n17). Equal to the population, as measured.
MINIMUM_NEGATIVE_CONTROLS = 72

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
LINT_CONTROL_PREFIX = "LINT-REJECTED"
# The roots whose linter holds each lint control to the check it names. A
# lint control is exempt from schema rejection here because that linter
# checks it; under any other root nothing would, so it fails instead.
LINT_CONTROL_ROOTS = ("parts",)


def is_lint_control(example):
    """True for a control proving a cross-reference check, not the schema.

    Read exactly as parts/lint-part-data.py reads it: the declaration starts
    with the prefix, and nothing is stripped first. With a strip here and
    none there, a declaration with a leading space was exempt from the
    schema in this gate and invisible to the linter, and both passed while
    counting different lint-control populations."""
    control = example.get(CONTROL_KEY) if isinstance(example, dict) else None
    return isinstance(control, str) and control.startswith(LINT_CONTROL_PREFIX)


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


def declared_version(document, pointer):
    """(the integer version `document` declares at `pointer` or None, what
    it declares there in words)."""
    where = ".".join(pointer)
    value = document
    for key in pointer:
        if not isinstance(value, dict) or key not in value:
            return None, f"declares no {where}"
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"declares {where} {value!r}"
    return value, f"declares {where} {value}"


def load_json(path, rel, failures):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        failures.append(f"{rel}: does not parse as JSON: {exc}")
        return None


def check_root(root, root_name, suffix_map, jsonschema, failures, goldens=(),
               store=()):
    """Validate one schema root, plus any goldens and store records routed to
    it. Returns (schemas, positives, negatives, goldens, store records, lint
    controls)."""
    root_dir = root / root_name
    examples_dir = root_dir / "examples"

    schema_paths = sorted(
        p for p in root_dir.rglob("*.schema.json") if examples_dir not in p.parents
    ) if root_dir.is_dir() else []
    if not schema_paths:
        # A root that has examples but no schema is a DELETED or RENAMED
        # schema, not an empty root. Reporting "nothing to validate" and
        # exiting 0 would mean removing a schema file silently disables its
        # entire root — every example and every negative control with it.
        # Goldens routed here are the same case.
        stray = sorted(examples_dir.rglob("*.json")) if examples_dir.is_dir() else []
        stray += list(goldens) + list(store)
        if stray:
            failures.append(
                f"{root_name}/: {len(stray)} example or golden file(s) need "
                f"{root_name}/'s schemas but the root declares NO *.schema.json. "
                "A schema was deleted or renamed, which would otherwise switch "
                "off this root's validation silently."
            )
            return 0, 0, 0, 0, 0, 0
        print(f"schemas: {root_name}/: no *.schema.json files; nothing to validate.")
        return 0, 0, 0, 0, 0, 0

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
    golden_count = 0
    store_count = 0
    lint_control_count = 0
    store_set = set(store)

    example_paths = sorted(examples_dir.rglob("*.json")) if examples_dir.is_dir() else []
    for example_path in example_paths + sorted(goldens) + sorted(store):
        rel = example_path.relative_to(root)
        # A golden or a store record is a positive wherever it sits: it is
        # compiler output or compiler input, never a control.
        is_golden = examples_dir not in example_path.parents
        expect_invalid = not is_golden and NEGATIVE_DIR_NAME in \
            example_path.relative_to(examples_dir).parts[:-1]

        route = next(
            (s for suffix, s in suffix_map if example_path.name.endswith(suffix)),
            None,
        )
        if route is None:
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

        example = load_json(example_path, rel, failures)
        if example is None:
            continue

        schema_name = route
        if not isinstance(route, str):
            pointer, versions = route
            version, declared = declared_version(example, pointer)
            schema_name = versions.get(version)
            if schema_name is None:
                failures.append(
                    f"{rel}: {declared}, and the schemas of {root_name}/ "
                    f"describe versions "
                    f"{', '.join(str(v) for v in sorted(versions))} only. A "
                    "document is validated against the schema of the version "
                    "it declares and no other, and a backend refuses a "
                    "version it does not know, so this gate refuses it too."
                )
                continue

        validator = validators.get(schema_name)
        if validator is None:
            failures.append(
                f"{rel}: cannot validate: mapped schema {schema_name} is "
                "missing or malformed."
            )
            continue

        errors = sorted(validator.iter_errors(example), key=str)
        if expect_invalid and is_lint_control(example) and \
                root_name not in LINT_CONTROL_ROOTS:
            failures.append(
                f"{rel}: declares a lint control, and no linter holds lint "
                f"controls under {root_name}/ (only under "
                f"{', '.join(r + '/' for r in LINT_CONTROL_ROOTS)}). Exempt "
                "from the schema and checked by nothing, it proves nothing; "
                "make it a `REJECTED at` schema control.")
        elif expect_invalid and is_lint_control(example):
            lint_control_count += 1
            for error in errors:
                path = "/".join(str(part) for part in error.absolute_path) or "<root>"
                failures.append(
                    f"{rel}: lint control is not schema-valid (at {path}: "
                    f"{error.message}); it must fail ONLY the cross-reference "
                    "check it names, which the part-data linter verifies.")
            if not errors:
                print(f"schemas: {rel}: lint control, valid against {schema_name} as it must be.")
        elif expect_invalid:
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
            if example_path in store_set:
                store_count += 1
            elif is_golden:
                golden_count += 1
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

    return (len(schema_paths), positive_count, negative_count, golden_count,
            store_count, lint_control_count)


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
        "properties": {"stability": {"const": "unstable"},
                       "schema_version": {"const": 0}},
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

    # Part records route by schema_version, so every planted one declares it.
    good = {"stability": "unstable", "schema_version": 0}
    control = {"stability": "stable", "schema_version": 0,
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
            _json.dumps({"stability": "whatever it likes", "schema_version": 0}))
    code, text = run_raw(_stray)
    cases.append(("a mapped example outside examples/ is caught",
                  code == 1 and "no gate validates it" in text))

    code, text = run(good, {"n1.part.json": {"stability": "stable",
                                             "schema_version": 0}})
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

    code, text = run(dict(good, stability="stable"), {"n1.part.json": control})
    cases.append(("an invalid POSITIVE example is caught", code == 1))

    # PART-DATA VERSIONS. v0's file is immutable and v1 is a second file, each
    # pinning its own version, so a record validated against any schema but
    # its own fails on the version alone.
    def _parts_root(root, *, examples=(), store=(), negatives=()):
        (root / "parts" / "examples" / "negative").mkdir(parents=True,
                                                         exist_ok=True)
        for name, version in (("part-data.schema.json", 0),
                              ("part-data.v1.schema.json", 1)):
            (root / "parts" / name).write_text(_json.dumps(dict(
                SCHEMA, properties=dict(SCHEMA["properties"],
                                        schema_version={"const": version}),
                required=["stability", "schema_version"])))
        if not negatives:
            negatives = (("n1.part.json", control),)
        for name, body in negatives:
            (root / "parts" / "examples" / "negative" / name).write_text(
                _json.dumps(body))
        for name, body in examples:
            (root / "parts" / "examples" / name).write_text(_json.dumps(body))
        for rel, body in store:
            path = root / "rhoform" / "parts" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_json.dumps(body))

    v1_good = dict(good, schema_version=1)
    code, text = run_raw(lambda root: _parts_root(
        root, examples=(("a.part.json", good), ("b.part.json", v1_good))))
    cases.append(("each part record is validated against its own version's schema",
                  code == 0
                  and "parts/examples/a.part.json: valid against "
                  "part-data.schema.json" in text
                  and "parts/examples/b.part.json: valid against "
                  "part-data.v1.schema.json" in text))
    code, text = run_raw(lambda root: _parts_root(
        root, examples=(("a.part.json", dict(good, schema_version=7)),)))
    cases.append(("a part record of a version no schema describes is refused",
                  code == 1
                  and "a.part.json: declares schema_version 7, and the "
                  "schemas of parts/ describe versions 0, 1 only" in text))

    # THE STORE. rhoform/parts/<vendor>/<slug>.part.json is compiler input:
    # before it was routed here the stray rule failed every record in it, and
    # routed wrongly it would pass unvalidated.
    code, text = run_raw(lambda root: _parts_root(
        root, store=(("acme/x.part.json", v1_good),)))
    cases.append(("a store record is validated and counted as one",
                  code == 0
                  and "rhoform/parts/acme/x.part.json: valid against "
                  "part-data.v1.schema.json" in text
                  and "1 valid store record(s)" in text))
    code, text = run_raw(lambda root: _parts_root(
        root, store=(("acme/x.part.json", dict(v1_good, stability="stable")),)))
    cases.append(("an invalid store record is caught",
                  code == 1 and "rhoform/parts/acme/x.part.json: at stability"
                  in text))
    code, text = run_raw(lambda root: _parts_root(
        root, store=(("x.part.json", v1_good),)))
    cases.append(("a store record off the <vendor>/<slug> depth is a stray",
                  code == 1
                  and "rhoform/parts/x.part.json: carries a mapped" in text))

    def _orphan_store(root):
        path = root / "rhoform" / "parts" / "acme" / "x.part.json"
        path.parent.mkdir(parents=True)
        path.write_text(_json.dumps(v1_good))
    code, text = run_raw(_orphan_store)
    cases.append(("store records whose schema root is gone are caught",
                  code == 1 and "1 example or golden file(s)" in text
                  and "declares NO *.schema.json" in text))

    # LINT CONTROLS prove a cross-reference check, so they must pass the
    # schema; one that fails it proves nothing about the check it names.
    lint_control = dict(v1_good, x_negative_control=(
        "LINT-REJECTED by L1 at /x: a cross-reference the schema cannot see"))
    code, text = run_raw(lambda root: _parts_root(
        root, negatives=(("n1.part.json", control),
                         ("n2.part.json", lint_control))))
    cases.append(("a schema-valid lint control is accepted and counted",
                  code == 0 and "1 lint control(s) schema-valid" in text
                  and "1 negative control(s) rejected" in text))
    code, text = run_raw(lambda root: _parts_root(
        root, negatives=(("n1.part.json", control),
                         ("n2.part.json", dict(lint_control,
                                               stability="stable")))))
    cases.append(("a lint control that fails the schema is caught",
                  code == 1 and "n2.part.json: lint control is not "
                  "schema-valid (at stability" in text))
    # One rule in both gates: the linter recognises a declaration that
    # STARTS with the prefix, so a leading space makes this an ordinary
    # schema control, and a schema-valid one of those fails here.
    code, text = run_raw(lambda root: _parts_root(
        root, negatives=(("n1.part.json", control),
                         ("n2.part.json", dict(lint_control, x_negative_control=(
                             " " + lint_control["x_negative_control"]))))))
    cases.append(("a lint declaration with leading space is not exempt",
                  code == 1 and "n2.part.json: negative control "
                  "unexpectedly VALIDATES" in text))


    # GOLDENS: the elaborator's committed output for each benchmark source,
    # which sits outside every examples/ directory by design. Before they
    # were routed here the stray rule failed them; routed wrongly, they
    # would pass unvalidated.
    # The ir root's schemas are versioned: one immutable file per version,
    # each pinning its own version, and a document is routed by the version
    # it declares. The planted schemas pin theirs the same way.
    def _versioned_schema(version):
        return dict(SCHEMA, properties=dict(
            SCHEMA["properties"],
            header={"type": "object",
                    "properties": {"ir_version": {"const": version}}},
            sourcemap_version={"const": version}))

    def _ir_root(root):
        (root / "ir" / "examples" / "negative").mkdir(parents=True)
        for name, version in (("netlist-ir.schema.json", 0),
                              ("netlist-ir.v1.schema.json", 1),
                              ("source-map.schema.json", 0),
                              ("source-map.v1.schema.json", 1)):
            (root / "ir" / name).write_text(
                _json.dumps(_versioned_schema(version)))
        (root / "ir" / "examples" / "negative" / "n1.ir.json").write_text(
            _json.dumps(dict(control, header={"ir_version": 0})))

    ir_good = dict(good, header={"ir_version": 1})
    map_good = dict(good, sourcemap_version=1)
    ir_bad = dict(ir_good, stability="stable")

    # Under a root no linter reads, a lint declaration exempts nothing.
    def _ir_lint_control(root):
        _ir_root(root)
        (root / "ir" / "examples" / "negative" / "n2.ir.json").write_text(
            _json.dumps(dict(good, header={"ir_version": 0},
                             x_negative_control=(
                                 "LINT-REJECTED by L99 at /x: no linter here"))))
    code, text = run_raw(_ir_lint_control)
    cases.append(("a lint control outside parts/ is caught, not exempted",
                  code == 1 and "n2.ir.json: declares a lint control, and no "
                  "linter holds lint controls under ir/" in text
                  and "lint control, valid against" not in text))

    def _golden(root, name, body):
        (root / "benchmarks" / "x").mkdir(parents=True, exist_ok=True)
        (root / "benchmarks" / "x" / name).write_text(_json.dumps(body))

    def _good_goldens(root):
        _ir_root(root)
        _golden(root, "x.ir.json", ir_good)
        _golden(root, "x.sourcemap.json", map_good)
    code, text = run_raw(_good_goldens)
    cases.append(("valid goldens are validated and counted as goldens",
                  code == 0
                  and "benchmarks/x/x.ir.json: valid against "
                  "netlist-ir.v1.schema.json" in text
                  and "benchmarks/x/x.sourcemap.json: valid against "
                  "source-map.v1.schema.json" in text
                  and "0 valid example(s), 2 valid golden(s)" in text))

    def _bad_golden(root):
        _ir_root(root)
        _golden(root, "x.ir.json", ir_bad)
    code, text = run_raw(_bad_golden)
    cases.append(("an invalid golden is caught",
                  code == 1 and "benchmarks/x/x.ir.json: at stability" in text))

    def _misnamed_golden(root):
        _ir_root(root)
        _golden(root, "y.ir.json", ir_good)
    code, text = run_raw(_misnamed_golden)
    cases.append(("a file not named after its benchmark is a stray, not a golden",
                  code == 1 and "benchmarks/x/y.ir.json: carries a mapped" in text))

    def _orphan_goldens(root):
        # No ir/ directory at all: the goldens alone must bring the root
        # into the run, or they would be excused from the stray rule and
        # validated by nothing.
        _golden(root, "x.ir.json", ir_good)
    code, text = run_raw(_orphan_goldens)
    cases.append(("goldens whose schema root is gone are caught, not skipped",
                  code == 1 and "1 example or golden file(s)" in text
                  and "declares NO *.schema.json" in text))

    # An elaboration conformance case's expected IR is a golden of the ir
    # root, validated rather than reported as a stray.
    def _expected_ir(*bodies):
        def plant(root):
            _ir_root(root)
            accept = root / "spec" / "conformance" / "elaborate" / "accept"
            accept.mkdir(parents=True)
            for number, body in enumerate(bodies, 1):
                (accept / f"a0{number}_x.expected.ir.json").write_text(
                    _json.dumps(body))
        return plant
    code, text = run_raw(_expected_ir(ir_good))
    cases.append(("a conformance case's expected IR is validated as a golden",
                  code == 0
                  and "elaborate/accept/a01_x.expected.ir.json: valid against"
                  in text and "1 valid golden(s)" in text))
    code, text = run_raw(_expected_ir(ir_bad))
    cases.append(("an invalid conformance expected IR is caught",
                  code == 1
                  and "a01_x.expected.ir.json: at stability" in text))

    # VERSIONS. Each schema pins its own version, so a document validated
    # against any schema but its own fails on the version alone: both
    # passing proves each went to the schema of the version IT declares.
    code, text = run_raw(_expected_ir(dict(good, header={"ir_version": 0}),
                                      ir_good))
    cases.append(("each document is validated against its own version's schema",
                  code == 0
                  and "a01_x.expected.ir.json: valid against "
                  "netlist-ir.schema.json" in text
                  and "a02_x.expected.ir.json: valid against "
                  "netlist-ir.v1.schema.json" in text))
    code, text = run_raw(_expected_ir(dict(good, header={"ir_version": 7})))
    cases.append(("a document of a version no schema describes is refused",
                  code == 1
                  and "a01_x.expected.ir.json: declares header.ir_version 7, "
                  "and the schemas of ir/ describe versions 0, 1, 2 only"
                  in text))
    code, text = run_raw(_expected_ir(good))
    cases.append(("a document declaring no version is refused",
                  code == 1
                  and "a01_x.expected.ir.json: declares no "
                  "header.ir_version" in text))
    code, text = run_raw(_expected_ir(dict(good, header={"ir_version": True})))
    cases.append(("a version that is not an integer is refused",
                  code == 1
                  and "declares header.ir_version True, and the schemas"
                  in text))

    def _unknown_map(root):
        _ir_root(root)
        _golden(root, "x.ir.json", ir_good)
        _golden(root, "x.sourcemap.json", dict(good, sourcemap_version=9))
    code, text = run_raw(_unknown_map)
    cases.append(("a source map is routed by its own sourcemap_version",
                  code == 1
                  and "x.sourcemap.json: declares sourcemap_version 9, "
                  "and the schemas of ir/ describe" in text))

    # A package case keeps its expected IR inside its own directory.
    def _package_ir(body):
        def plant(root):
            _ir_root(root)
            case = (root / "spec" / "conformance" / "packages" / "accept"
                    / "a01_x")
            case.mkdir(parents=True)
            (case / "expected.ir.json").write_text(_json.dumps(body))
        return plant
    code, text = run_raw(_package_ir(ir_good))
    cases.append(("a package case's expected IR is validated as a golden",
                  code == 0
                  and "packages/accept/a01_x/expected.ir.json: valid "
                  "against" in text and "1 valid golden(s)" in text))
    code, text = run_raw(_package_ir(ir_bad))
    cases.append(("an invalid package expected IR is caught",
                  code == 1
                  and "a01_x/expected.ir.json: at stability" in text))

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

    goldens = golden_paths(root)
    store = store_paths(root)
    # A root that goldens or store records route to is checked even if its
    # directory is gone, so documents with no schema left to validate them
    # fail rather than skip.
    present = [name for name in sorted(SCHEMA_ROOTS)
               if (root / name).is_dir() or name in goldens or name in store]
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
    totals = [0, 0, 0, 0, 0, 0]

    # A file carrying a mapped example suffix but living outside any
    # declared examples/ directory is validated by nothing. `make check`
    # would pass over a whole part library sitting one directory to the
    # left, which is the failure mode most likely to happen in practice as
    # the seed library grows.
    mapped_suffixes = sorted(
        {suffix for suffixes in SCHEMA_ROOTS.values() for suffix, _ in suffixes}
    )
    known_example_dirs = [root / name / "examples" for name in SCHEMA_ROOTS]
    golden_set = {path for paths in list(goldens.values())
                  + list(store.values()) for path in paths}
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv"}
    for path in sorted(root.rglob("*.json")):
        if skip_dirs & set(path.parts):
            continue
        if not any(path.name.endswith(suffix) for suffix in mapped_suffixes):
            continue
        if any(d in path.parents for d in known_example_dirs):
            continue
        if path in golden_set:
            continue
        failures.append(
            f"{path.relative_to(root)}: carries a mapped example suffix but sits "
            "outside every declared <root>/examples/ directory, so no gate "
            "validates it. Move it under the right examples/ directory or "
            "rename it."
        )

    for root_name in present:
        counts = check_root(
            root, root_name, SCHEMA_ROOTS[root_name], jsonschema, failures,
            goldens=goldens.get(root_name, ()), store=store.get(root_name, ()),
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
        f"{totals[1]} valid example(s), {totals[3]} valid golden(s), "
        f"{totals[4]} valid store record(s), "
        f"{totals[2]} negative control(s) rejected as expected, "
        f"{totals[5]} lint control(s) schema-valid as required."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
