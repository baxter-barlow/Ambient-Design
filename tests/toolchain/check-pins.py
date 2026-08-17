#!/usr/bin/env python3
"""Every pin in toolchain/versions.yaml must have a consumer that agrees with it.

README.md calls that file "the single pinned-toolchain manifest every local run
and CI job resolves versions from". It was not: an audit corrupted every pin
except `ngspice.version` — python 3.12 to 2.4, jsonschema to 0.0.1, lark to
9.9.9, the `actions/checkout` SHA to `deadbeef...`, both kicad images and
digests, the Debian image — and `make all` still exited 0. The manifest was
decoration, and the eight `# Keep in sync with toolchain/versions.yaml`
comments scattered through the workflow were the entire enforcement mechanism.

That matters because P5 (determinism) rests on the manifest. A contributor who
bumps jsonschema in the workflow and forgets the manifest leaves the stated
toolchain and the real one disagreeing, with every gate green — and the next
person to reproduce a recorded artifact uses the stated one.

WHAT THIS CHECKS. For every pin: the exact pinned string appears in each of its
declared consumers. `ngspice.version` already had a real consumer that behaved
correctly (`run-sim.sh` reads the manifest and fails on a mismatch), which is
what proved the pattern was achievable rather than aspirational.

A pin with NO consumer is a failure too, and cannot be silenced by deleting the
CONSUMERS entry — an unlisted pin is reported as unknown. That is deliberate:
the kicad pins had no consumer at all, which is how the kicad half of AMB-28's
acceptance criterion ("pinned kicad/kicad + ngspice Docker images in CI") came
to be recorded as delivered while nothing had ever pulled either image. A pin
that is deliberately not yet consumed must say so, in the manifest, with the
issue that will consume it — see `NOT_YET_CONSUMED`.

Exit codes: 0 pass, 1 a pin and its consumer disagree, 2 environment failure.

    python3 tests/toolchain/check-pins.py --self-test
    python3 tests/toolchain/check-pins.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "toolchain" / "versions.yaml"

CHECKS = ROOT / ".github/workflows/checks.yml"
DCO = ROOT / ".github/workflows/dco.yml"
POLICY = ROOT / ".github/workflows/repository-policy.yml"
MAKEFILE = ROOT / "Makefile"
RUN_SIM = ROOT / "tests/benchmarks/run-sim.sh"
EVAL_CLI = ROOT / "eval/rhoform_eval/cli.py"
MEASURE = ROOT / "lang/bakeoff/measure.py"

# pin path -> (how to spell it where it is used, files that must contain it).
#
# The spelling function exists because a pin is not always used verbatim: the
# jsonschema pin appears as `jsonschema==4.26.0` in a pip line, the Debian
# image as `image@digest`. Comparing the raw value would either miss the real
# consumer or match some unrelated occurrence of "4.26.0".
CONSUMERS = {
    ("python", "version"): (lambda v: f'python-version: "{v}"', [CHECKS]),
    # NOT the Makefile: its `python3 -m pip install jsonschema==...` lines are
    # comments telling a human what to install. A comment is documentation, not
    # a consumer — treating it as one is how a stale comment came to satisfy
    # this check for a drifted live command.
    ("python", "packages", "jsonschema"): (lambda v: f"jsonschema=={v}", [CHECKS]),
    ("python", "packages", "pyyaml"): (lambda v: f"PyYAML=={v}", [CHECKS]),
    ("python", "packages", "lark"): (lambda v: f"lark=={v}", [CHECKS]),
    # run-sim.sh READS the manifest and fails on a mismatch, so its consumer is
    # the sed expression that extracts the pin, not a copy of the value. Was
    # `[MANIFEST]`, which asserted only that the manifest contains its own value.
    ("ngspice", "version"): (lambda v: "ngspice.version", [RUN_SIM]),
    ("ngspice", "debian_package"): (lambda v: v, [CHECKS]),
    ("ci", "actions", "checkout", "ref"): (lambda v: f"uses: {v}", [CHECKS, DCO, POLICY]),
    ("ci", "actions", "setup_python", "ref"): (lambda v: f"uses: {v}", [CHECKS]),
    # `image@digest`, so a re-pointed tag cannot pass by matching the tag alone.
    ("ci", "containers", "simulation"): (lambda v: f"image: {v}", [CHECKS]),
    # The kicad images are pinned by AMB-28's acceptance criterion and are
    # verified by the `toolchain-pins` job, which resolves each digest without
    # pulling the (multi-gigabyte) image. Export work that actually RUNS
    # kicad-cli is AMB-66's; a pin nobody has ever resolved is still decoration,
    # which is what these two were.
    # The behavioural tokenizer pin. Both consumers READ the manifest rather
    # than copying the digest, so the needle is the key they read, exactly as
    # for ngspice.version. This pin was invisible to the gate until the walk
    # became generic — which mattered, because the manifest says of it: "NEVER
    # edit the probe corpus: changing it changes every fingerprint and silently
    # invalidates every recorded pin."
    ("evaluation", "tokenizer", "fingerprint"): (
        lambda v: "fingerprint", [EVAL_CLI, MEASURE]),
    ("evaluation", "tokenizer", "encoding"): (
        lambda v: "encoding", [EVAL_CLI, MEASURE]),
    ("kicad", "series", "9.0"): (lambda v: v, [CHECKS]),
    ("kicad", "series", "10.0"): (lambda v: v, [CHECKS]),
}

# Pins whose consumer does not exist yet. Each must name the issue that will
# build it, and the gate re-reads that justification from the manifest itself
# so it cannot rot silently in this file. Empty today, and it should stay that
# way: the entry that used to live here was the kicad pair, which is how the
# kicad half of AMB-28 came to be recorded as delivered while nothing had ever
# resolved either digest.
NOT_YET_CONSUMED = set()

# The number of pin/consumer agreements a healthy tree has. Raise it when a pin
# is added; lower it only in the same change that deliberately removes one.
MINIMUM_AGREEMENTS = 15


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def load_manifest():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment failure
        raise GateUnavailable(
            "PyYAML is required to read toolchain/versions.yaml; install the "
            "pin (python3 -m pip install pyyaml==6.0.2)."
        ) from exc
    if not MANIFEST.is_file():
        raise GateUnavailable(f"{MANIFEST} is missing")
    try:
        return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateUnavailable(f"{MANIFEST} is not readable as YAML: {exc}") from exc


def _strip_comment(line: str) -> str:
    """A YAML/shell line with its comment removed. Comments are not consumers."""
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return line[:index]
    return line


def _key_of(needle: str) -> str:
    """The part of a needle that identifies WHICH lines must carry it.

    `jsonschema==4.26.0` -> `jsonschema==`, so every pip line naming jsonschema
    is compared, not just the ones that already agree.
    """
    # `@` FIRST: `uses: actions/checkout@<sha>` must key on
    # `uses: actions/checkout@`, not on `uses: `, or every action line in the
    # file is compared against one action's pin.
    for separator in ("@", "==", ": ", ":"):
        head, found, _ = needle.partition(separator)
        if found:
            return head + found
    return needle


def dig(tree, path):
    node = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def declared_pins(manifest):
    """Every leaf pin the manifest states, as (path, value)."""
    pins = []
    for group, keys in (
        ("python", [("version",)]),
        ("ngspice", [("version",), ("debian_package",)]),
    ):
        for key in keys:
            value = dig(manifest, (group,) + key)
            if value is not None:
                pins.append(((group,) + key, str(value)))
    for name, value in (dig(manifest, ("python", "packages")) or {}).items():
        pins.append((("python", "packages", name), str(value)))
    for action, block in (dig(manifest, ("ci", "actions")) or {}).items():
        if isinstance(block, dict) and "ref" in block:
            pins.append((("ci", "actions", action, "ref"), str(block["ref"])))
    for entry in dig(manifest, ("kicad", "series")) or []:
        if isinstance(entry, dict) and "name" in entry:
            pins.append((
                ("kicad", "series", str(entry["name"])),
                f"{entry.get('image', '')}@{entry.get('digest', '')}",
            ))
    for name, block in (dig(manifest, ("ci", "containers")) or {}).items():
        if isinstance(block, dict) and block.get("image") and block.get("digest"):
            pins.append((("ci", "containers", name),
                         f"{block['image']}@{block['digest']}"))

    # Anything the five shapes above did not reach. `declared_pins` used to
    # enumerate only those, so a whole new manifest group — `ci.containers.export`,
    # or the entire `evaluation:` block holding the tokenizer fingerprint — was
    # not merely unlisted but INVISIBLE, and this file's docstring claims an
    # unlisted pin is reported as unknown.
    seen = {path for path, _ in pins}
    for path, value in _leaves(manifest):
        if path in seen or any(path[:len(p)] == p for p in seen):
            continue
        if path[-1] in IGNORED_LEAF_KEYS or not isinstance(value, (str, int, float)):
            continue
        pins.append((path, str(value)))
    return pins


# Manifest leaves that are documentation rather than pins.
IGNORED_LEAF_KEYS = frozenset({
    "manifest_schema", "boundary", "name", "encoding", "provider", "probe_corpus",
    "id", "sampling", "not_yet_consumed", "version_note",
    # Always consumed as a composite `image@digest`, which the loops above
    # already emit; re-emitting the halves would ask for a consumer of half a
    # pin. `ref` likewise: actions are emitted whole.
    "image", "digest", "ref",
})


def _leaves(node, path=()):
    """Every scalar leaf in the manifest, as (path, value)."""
    if isinstance(node, dict):
        for key, sub in node.items():
            yield from _leaves(sub, path + (str(key),))
    elif isinstance(node, list):
        for item in node:
            yield from _leaves(item, path)
    else:
        yield path, node


def check(manifest, read=None):
    """Returns a list of problems. `read` is injectable so the self-test can
    drive the real comparison over a fake tree rather than over the repo."""
    read = read or (lambda path: path.read_text(encoding="utf-8") if path.is_file() else None)
    problems = []
    checked = 0

    optional = set((dig(manifest, ("python", "optional_packages")) or {}))

    for path, value in declared_pins(manifest):
        if path in NOT_YET_CONSUMED:
            justification = dig(manifest, path[:1] + ("not_yet_consumed",))
            if not justification:
                problems.append(
                    f"{'.'.join(path)}: has no consumer and the manifest does not "
                    f"say why. Add a `not_yet_consumed:` note under `{path[0]}:` "
                    "naming the issue that will use it, or wire up a consumer. A "
                    "pin nothing reads is decoration, and this is exactly how the "
                    "kicad half of AMB-28 was recorded as delivered."
                )
            continue
        # Was `path[:3] == ("python", "packages")`, comparing a 3-tuple to a
        # 2-tuple: always false, so `optional` was dead and the self-test case
        # naming it passed vacuously.
        if path[:2] == ("python", "packages") and path[2] in optional:
            continue
        # `optional_packages` are for live runs, not for any gate: the harness's
        # own tests are stdlib-only and the Makefile says so. They are declared
        # so a live run is reproducible, and requiring a gating consumer for
        # them would force a fake one.
        if path[:2] == ("python", "optional_packages"):
            continue

        spec = CONSUMERS.get(path)
        if spec is None:
            problems.append(
                f"{'.'.join(path)}: is pinned but this gate does not know who "
                "consumes it. Add it to CONSUMERS with the files that must "
                "agree, or to NOT_YET_CONSUMED with a justification."
            )
            continue

        spell, files = spec
        needle = spell(value)
        for file_path in files:
            text = read(file_path)
            if text is None:
                problems.append(f"{'.'.join(path)}: consumer {file_path} does not exist")
                continue
            # LIVE lines only, and EVERY occurrence of the key must agree.
            #
            # Substring-in-file was two holes at once. A stale comment
            # (`# previously: jsonschema==4.26.0`) satisfied the check for a
            # drifted live command beneath it. And a file with six
            # `python-version:` lines passed with one of them drifted, because
            # the other five still carried the pinned string — which is exactly
            # the corruption this gate's docstring says it exists to catch.
            live = [_strip_comment(line) for line in text.splitlines()]
            live = [line for line in live if line.strip()]
            key = _key_of(needle)
            occurrences = [line for line in live if key and key in line]
            if needle not in "\n".join(live):
                problems.append(
                    f"{'.'.join(path)}: manifest pins {value!r}, but "
                    f"{file_path.relative_to(ROOT) if file_path.is_absolute() else file_path} "
                    f"does not contain {needle!r}. The stated toolchain and the "
                    "real one disagree."
                )
            elif occurrences and any(needle not in line for line in occurrences):
                stray = next(line.strip() for line in occurrences if needle not in line)
                problems.append(
                    f"{'.'.join(path)}: manifest pins {value!r}, and "
                    f"{file_path.name} carries {len(occurrences)} line(s) using "
                    f"{key!r}, but at least one disagrees: {stray!r}. Every "
                    "occurrence must match, or one drifted line hides behind "
                    "the others."
                )
            else:
                checked += 1

    # A `uses:` line pinned to something the manifest never mentions is the
    # same defect from the other direction: an unaudited action inside the
    # trust boundary of every job.
    known_refs = {
        str(block["ref"])
        for block in (dig(manifest, ("ci", "actions")) or {}).values()
        if isinstance(block, dict) and "ref" in block
    }
    for workflow in (CHECKS, DCO, POLICY):
        text = read(workflow)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("uses:"):
                continue
            ref = stripped[len("uses:"):].split("#")[0].strip()
            if ref not in known_refs:
                problems.append(
                    f"{workflow.name}:{lineno}: uses {ref!r}, which "
                    "toolchain/versions.yaml does not pin. Every action runs "
                    "inside the trust boundary of the job that checks out the "
                    "source; an unpinned or unrecorded one is unaudited code."
                )
    return problems, checked


def self_test():
    """Prove each rejection fires over a fake tree."""
    fake = {
        "python": {"version": "3.12",
                   "packages": {"jsonschema": "4.26.0", "pyyaml": "6.0.2", "lark": "1.3.0"},
                   "optional_packages": {"tiktoken": "0.13.0"}},
        "ngspice": {"version": "46", "debian_package": "ngspice=46+ds-1"},
        "ci": {"actions": {"checkout": {"ref": "actions/checkout@abc"},
                           "setup_python": {"ref": "actions/setup-python@def"}},
               "containers": {"simulation": {"image": "debian:x", "digest": "sha256:y"}}},
        "kicad": {"series": [{"name": "9.0", "image": "kicad/kicad:9.0.9",
                              "digest": "sha256:aaa"}]},
    }
    good = {
        CHECKS: ('python-version: "3.12"\njsonschema==4.26.0\nPyYAML==6.0.2\nlark==1.3.0\n'
                 "ngspice=46+ds-1\n  uses: actions/checkout@abc\n  uses: actions/setup-python@def\n"
                 "      image: debian:x@sha256:y\n"
                 "          kicad/kicad:9.0.9@sha256:aaa\n"),
        MANIFEST: 'version: "46"\n',
        RUN_SIM: 'fail_env "could not read ngspice.version from the manifest."\n',
        DCO: "  uses: actions/checkout@abc\n",
        POLICY: "  uses: actions/checkout@abc\n",
    }

    def reader(mapping):
        return lambda path: mapping.get(path)

    problems, checked = check(fake, reader(good))
    cases = [("a consistent manifest reports no problem", not problems and checked > 0)]

    drifted = dict(good)
    drifted[CHECKS] = good[CHECKS].replace("jsonschema==4.26.0", "jsonschema==9.9.9")
    cases.append(("a drifted package pin is caught", any(
        "jsonschema" in p for p in check(fake, reader(drifted))[0])))

    drifted2 = dict(good)
    drifted2[CHECKS] = good[CHECKS].replace("actions/checkout@abc", "actions/checkout@deadbeef")
    caught = check(fake, reader(drifted2))[0]
    cases.append(("a drifted action SHA is caught", any("checkout" in p for p in caught)))
    cases.append(("an action the manifest does not pin is caught", any(
        "does not pin" in p for p in caught)))

    drifted3 = dict(good)
    drifted3[CHECKS] = good[CHECKS].replace('python-version: "3.12"', 'python-version: "2.4"')
    cases.append(("a drifted interpreter series is caught", any(
        "python.version" in p for p in check(fake, reader(drifted3))[0])))

    undigested = dict(good)
    undigested[CHECKS] = good[CHECKS].replace("kicad/kicad:9.0.9@sha256:aaa",
                                              "kicad/kicad:9.0.9")
    cases.append(("a kicad image pinned by tag rather than digest is caught", any(
        "kicad" in p for p in check(fake, reader(undigested))[0])))

    unknown = {**fake, "python": {**fake["python"],
                                  "packages": {**fake["python"]["packages"], "requests": "2.0"}}}
    cases.append(("a pin this gate does not know about is caught", any(
        "does not know who consumes it" in p for p in check(unknown, reader(good))[0])))

    # An optional package is not required to have a consumer: the harness's
    # tiktoken pin is for live runs, not for any gate.
    cases.append(("an optional package needs no consumer", not any(
        "tiktoken" in p for p in check(fake, reader(good))[0])))

    # WIRING. Everything above drives `check()` directly, so the branch that
    # turns a detected problem into a non-zero EXIT is the one part of this
    # gate nothing exercised — and deleting it is indistinguishable from a
    # clean sweep. That is the same seam check-hashes.py's planted-document
    # case was written for, one call level higher, and it was open in every
    # Python gate here.
    import contextlib, io
    real_check, real_load = check, load_manifest
    try:
        globals()["load_manifest"] = lambda: {"python": {"version": "3.12"}}
        globals()["check"] = lambda *_a, **_k: (["planted problem"], 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            planted = main([])
        globals()["check"] = lambda *_a, **_k: ([], MINIMUM_AGREEMENTS)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            clean = main([])
    finally:
        globals()["check"], globals()["load_manifest"] = real_check, real_load
    cases.append(("main() exits non-zero when check() reports a problem", planted == 1))
    cases.append(("main() exits zero when check() reports none", clean == 0))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"toolchain-pins: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"toolchain-pins: self-test PASS: {len(cases)} cases.")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    try:
        manifest = load_manifest()
        problems, checked = check(manifest)
    except GateUnavailable as exc:
        print(f"toolchain-pins: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("toolchain-pins: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    # A self-reported statistic is not an assertion — check-layout.sh's words.
    # This gate reported 14 agreements where a healthy run reports 15 while a
    # pin silently stopped being checked, and nothing noticed.
    if checked < MINIMUM_AGREEMENTS:
        print(
            f"toolchain-pins: FAIL: verified only {checked} pin/consumer "
            f"agreement(s), below the floor of {MINIMUM_AGREEMENTS}. Pins are "
            "not being checked; raise the floor deliberately if one was "
            "legitimately removed.",
            file=sys.stderr,
        )
        return 1
    print(f"toolchain-pins: PASS: {checked} pin/consumer agreement(s) verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
