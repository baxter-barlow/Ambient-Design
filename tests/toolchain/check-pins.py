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
    # These two are read from the manifest AT RUNTIME by measure.py rather than
    # copied into it, which is the strongest relationship a consumer can have
    # with a pin -- there is no second copy to drift. So the needle is the parse
    # itself, not the value. Spelled as the bare words `encoding` and
    # `fingerprint` it matched read_text(encoding="utf-8") and an argparse help
    # string, so both consumers could stop reading the manifest entirely and
    # still count as verified agreements.
    ("evaluation", "tokenizer", "fingerprint"): (
        lambda v: 'startswith("fingerprint:")', [MEASURE]),
    ("evaluation", "tokenizer", "encoding"): (
        lambda v: 'startswith("encoding:")', [MEASURE]),
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
# 17 without the optional behavioural fingerprint check, which is the number CI
# sees. Fitting this to a local venv that happens to carry tiktoken made the
# floor itself environment-dependent.
# 14, not the 17 this was. Three of those "agreements" were bare-word matches
# counted as verified: `encoding` satisfied by read_text(encoding="utf-8"),
# `fingerprint` by an argparse help string, ngspice's version by the word
# appearing anywhere. Read-by-key pins are reported and NOT counted now, so the
# floor is the number of pins whose VALUE a consumer is actually held to.
MINIMUM_AGREEMENTS = 14
# Actions are counted SEPARATELY. Folding them into one number meant the floor
# was 30 of which 16 were `uses:` occurrences, so deleting the `lark:` pin (the
# gate then compares its consumer to nothing) and duplicating one checkout step
# put the total back at 30 and passed.
# PER FILE, not one total. A single number let an entire deleted job be paid
# for by a duplicated checkout step elsewhere; the totals matched and the gate
# passed. These are the real per-workflow counts.
MINIMUM_ACTION_REFS = {"checks.yml": 14, "dco.yml": 1, "repository-policy.yml": 1}

# The JOBS each workflow must define. Counting action references stopped
# cross-file compensation and not within-file: an auditor deleted the whole
# eval-harness job from checks.yml, added two redundant `uses:` steps to
# another job, and the count matched at 14 with `make all` green and
# check-run-records running nowhere in CI. A job is what runs a gate; the
# count of steps is not.
REQUIRED_JOBS = {
    "checks.yml": ("bakeoff", "benchmarks-sim", "eval-harness", "golden",
                   "grammar", "schemas", "structure", "toolchain-pins"),
    "dco.yml": ("signoff",),
    "repository-policy.yml": ("agent-layout",),
}

# THE COMMANDS each gate must actually run in CI. Requiring the job NAME tested
# the shape of the previous defect (a job key disappearing) rather than the
# property (the gate runs). A job kept with `if: false`, or with every gate step
# replaced by `run: true`, satisfied the name check while check-run-records ran
# nowhere in CI -- the identical outcome deleting the job produced.
REQUIRED_CI_COMMANDS = (
    "tests/structure/check-layout.sh",
    "tests/schemas/validate-schemas.py",
    "tests/corpus/check-corpus.py",
    "tests/corpus/check-classification.py",
    "tests/toolchain/check-pins.py",
    "tests/ir/check-hashes.py",
    "tests/eval/check-run-records.py",
    "tests/benchmarks/run-sim.sh",
    "tests/benchmarks/check-corners.py",
    "tests/benchmarks/check-design-docs.py",
    "lang/tests/check_readme_numbers.py",
    "parts/lint-part-data.py",
)


class _SkipFingerprint(Exception):
    """Internal: the behavioural fingerprint cannot be checked offline."""


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
    # Only DOUBLE quotes open a string for this purpose. An apostrophe in prose
    # — `echo don't  # jsonschema==4.26.0` — used to open a quote that never
    # closed, so the `#` was never seen and the comment survived as a consumer,
    # reopening the exact hole this function was written to close. YAML and
    # shell both allow `#` inside double quotes, which is the case worth
    # handling; an unpaired apostrophe is far more common than a single-quoted
    # string containing a hash.
    in_string = False
    for index, char in enumerate(line):
        if char == '"':
            in_string = not in_string
        elif char == "#" and not in_string:
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
    # `=` last, after `==`, so `jsonschema==4.26.0` still keys on `jsonschema==`
    # while `ngspice=46+ds-1` keys on `ngspice=` instead of falling through to
    # the read-by-key path — where it was reported as "the value itself is not
    # compared here", which was false, and where it lost the every-occurrence
    # rule that a second `ngspice=47+ds-1` line would otherwise trip.
    for separator in ("@", "==", ": ", ":", "="):
        head, found, _ = needle.partition(separator)
        if found:
            return head + found
    # No separator: the needle IS the key, so "every occurrence must agree" is
    # trivially true and the pin's VALUE is unconstrained. That is how the
    # tokenizer fingerprint could be replaced with 64 zeros, and ngspice's
    # version hard-coded away from the manifest, with the gate green. These are
    # pins a consumer READS rather than copies, so they are reported as such
    # instead of being counted as verified agreements.
    return None


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
        if not isinstance(block, dict) or not block.get("image"):
            continue
        if not block.get("digest"):
            # An image with no digest is a MUTABLE TAG, which versions.yaml's
            # own comment says must never exist ("a mutable tag re-points on
            # every patch release, which would change export output under our
            # feet"). Emitted with a sentinel so it fails rather than vanishing.
            pins.append((("ci", "containers", name, "digest"),
                         "<missing: pinned by mutable tag>"))
            continue
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
    "manifest_schema", "boundary", "name", "provider", "probe_corpus",
    "not_yet_consumed", "version_note",
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


# Pins whose consumer reads the manifest rather than copying a value. Recorded
# so they are reported rather than silently counted as verified.
READ_BY_KEY: list[str] = []


def check(manifest, read=None):
    """Returns a list of problems. `read` is injectable so the self-test can
    drive the real comparison over a fake tree rather than over the repo."""
    read = read or (lambda path: path.read_text(encoding="utf-8") if path.is_file() else None)
    problems = []
    checked = 0
    READ_BY_KEY.clear()

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
            if key is None:
                if needle not in "\n".join(live):
                    problems.append(
                        f"{'.'.join(path)}: {file_path.name} does not mention "
                        f"{needle!r}, so nothing there reads this pin."
                    )
                else:
                    # NOT counted toward MINIMUM_AGREEMENTS. Three of the
                    # seventeen "agreements" were word-presence matches, two of
                    # them satisfied by text with nothing to do with the pin:
                    # `encoding` by read_text(encoding="utf-8"), `fingerprint`
                    # by an argparse help string. A floor made of those numbers
                    # measures nothing.
                    READ_BY_KEY.append(".".join(path))
                continue
            occurrences = [line for line in live if key in line]
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

    # THE TOKENIZER FINGERPRINT. Pinned as a hash over token counts on a fixed
    # probe corpus, so the only real check is to recount and compare.
    #
    # But tiktoken is an OPTIONAL pin — versions.yaml says so, and the CI job
    # that runs this gate installs only PyYAML — and loading the encoding
    # fetches its vocabulary over the network on first use, which a gate that
    # must run offline cannot require. So this leg is best-effort: it verifies
    # when it can and reports read-by-key when it cannot, and it is NOT counted
    # toward MINIMUM_AGREEMENTS, which would otherwise make the floor depend on
    # whether an optional package happened to be installed.
    #
    # Its absence arrives as PinnedTokenizerError, not ImportError, so an
    # `except ImportError` fallback was dead: the gate failed CI while blaming
    # the manifest for drift that did not exist.
    pinned = dig(manifest, ("evaluation", "tokenizer", "fingerprint"))
    encoding = dig(manifest, ("evaluation", "tokenizer", "encoding"))
    if pinned and encoding:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "eval"))
        try:
            try:
                from rhoform_eval.tokenizer import (
                    PinnedTokenizerError,
                    TiktokenTokenizer,
                )
            except ImportError as exc:
                READ_BY_KEY.append(
                    f"evaluation.tokenizer.fingerprint (harness not importable: {exc})"
                )
            else:
                # ONLY IF THE VOCABULARY IS ALREADY LOCAL. tiktoken fetches it
                # on first use, so this leg was initiating an outbound request
                # from a gate whose contract is that it is offline -- the
                # previous fix made that failure non-fatal without making the
                # fetch conditional. Nothing downloaded in testing only because
                # the network happened to be blocked.
                import os as _os
                cache_dir = _os.environ.get("TIKTOKEN_CACHE_DIR") or ""
                cached = bool(cache_dir) and _os.path.isdir(cache_dir) and any(
                    _os.scandir(cache_dir))
                if not cached:
                    READ_BY_KEY.append(
                        "evaluation.tokenizer.fingerprint (tiktoken's encoding "
                        "vocabulary is not in a local cache; loading it would "
                        "fetch over the network, which a gate that must run "
                        "offline cannot do. Set TIKTOKEN_CACHE_DIR to a warmed "
                        "cache to verify this pin behaviourally.)")
                    raise _SkipFingerprint
                try:
                    TiktokenTokenizer(str(encoding), str(pinned))
                except PinnedTokenizerError as exc:
                    # A MISMATCH is a real finding; anything else about LOADING
                    # is not. My previous fix special-cased only "not
                    # installed", so tiktoken present with a cold cache and no
                    # network still turned `make all` red — and with network it
                    # silently fetched 3.6 MB inside a gate that must run
                    # offline. Only the mismatch text is a finding now.
                    if "does not match its pin" in str(exc):
                        problems.append(
                            "evaluation.tokenizer.fingerprint: the pinned "
                            f"encoding {encoding!r} does not reproduce the "
                            f"pinned fingerprint: {exc}"
                        )
                    else:
                        READ_BY_KEY.append(
                            f"evaluation.tokenizer.fingerprint (not verifiable "
                            f"here: {exc})"
                        )
                except Exception as exc:
                    READ_BY_KEY.append(
                        "evaluation.tokenizer.fingerprint (could not be "
                        f"verified here: {exc})"
                    )
        except _SkipFingerprint:
            pass
        finally:
            _sys.path.remove(str(ROOT / "eval"))

    # A `uses:` line pinned to something the manifest never mentions is the
    # same defect from the other direction: an unaudited action inside the
    # trust boundary of every job.
    action_refs = {}
    known_refs = {
        str(block["ref"])
        for block in (dig(manifest, ("ci", "actions")) or {}).values()
        if isinstance(block, dict) and "ref" in block
    }
    # EVERY workflow, discovered rather than listed. Three hard-coded paths
    # meant `uses: attacker/evil-action@main` in a fourth file was invisible —
    # arbitrary third-party code inside the trust boundary of every job, in a
    # gate whose own text says "an unpinned or unrecorded one is unaudited code".
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml")) + \
                sorted((ROOT / ".github" / "workflows").glob("*.yaml")) + \
                sorted(p for p in ROOT.glob("**/action.yml")
                       if ".git/" not in str(p)) + \
                sorted(p for p in ROOT.glob("**/action.yaml")
                       if ".git/" not in str(p))
    for workflow in (workflows or [CHECKS, DCO, POLICY]):
        text = read(workflow)
        if text is None:
            continue
        # PARSED, not scanned. Line-oriented matching missed the flow-mapping
        # form -- `steps: [{uses: attacker/evil-action@main}]` is valid YAML and
        # valid Actions and was invisible. The line scan is kept as a fallback
        # for when PyYAML is absent, and reported as such rather than silently
        # skipped.
        parsed_refs = []
        try:
            import yaml as _yaml
            def _walk_uses(node):
                if isinstance(node, dict):
                    for k, v in node.items():
                        if k == "uses" and isinstance(v, str):
                            parsed_refs.append(v)
                        else:
                            _walk_uses(v)
                elif isinstance(node, list):
                    for item in node:
                        _walk_uses(item)
            _walk_uses(_yaml.safe_load(text))
        except ImportError:
            parsed_refs = None
        except Exception as exc:
            # REPORTED. This used to fall back silently, so a workflow carrying
            # one unparseable tag downgraded the whole file to the line scanner
            # and hid `steps: [{uses: attacker/evil-action@main}]` completely.
            # The comment claiming it was "reported as such" described nothing.
            problems.append(
                f"{workflow.name}: is not parseable as YAML ({exc.__class__.__name__}"
                f": {str(exc).splitlines()[0][:80]}), so this gate falls back to "
                "a line scan that cannot see the flow-mapping form. Fix the file "
                "or this workflow is only partly checked.")
            parsed_refs = None
        if parsed_refs is not None:
            for ref in parsed_refs:
                # `docker://` and `./` were skipped outright. A docker image is
                # third-party code inside the job exactly as an action is, and
                # a local `./tools/evil` composite action was never globbed
                # either -- so `uses: ./tools/evil` containing
                # `uses: attacker/evil-action@main` was invisible end to end.
                if ref.startswith("./"):
                    local = ROOT / ref[2:]
                    candidates = [local / "action.yml", local / "action.yaml"]
                    if not any(c.is_file() for c in candidates):
                        problems.append(
                            f"{workflow.name}: uses local action {ref!r}, which "
                            "has no action.yml. A step pointing at nothing is "
                            "either dead or resolved somewhere this gate cannot "
                            "see.")
                    else:
                        action_refs[workflow.name] = action_refs.get(workflow.name, 0) + 1
                    continue
                if ref not in known_refs:
                    problems.append(
                        f"{workflow.name}: uses {ref!r}, which "
                        "toolchain/versions.yaml does not pin. An unrecorded "
                        "action is unaudited code inside every job.")
                else:
                    action_refs[workflow.name] = action_refs.get(workflow.name, 0) + 1
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # `- uses: x` is the list form and is at least as common as the
            # mapping form. Requiring the line to START with `uses:` made every
            # step written that way invisible — including the one an auditor
            # planted, which is arbitrary third-party code inside every job's
            # trust boundary.
            if stripped.startswith("- "):
                stripped = stripped[2:].lstrip()
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
            else:
                action_refs[workflow.name] = action_refs.get(workflow.name, 0) + 1
    return problems, checked, action_refs


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
        # VALID YAML, because the gate now parses workflows and reports the
        # ones it cannot. A fixture that is only a bag of matching lines was
        # exercising the fallback scanner rather than the shipped path.
        CHECKS: ("on: push\n"
                 "jobs:\n"
                 "  gate:\n"
                 "    runs-on: ubuntu-latest\n"
                 "    container:\n"
                 "      image: debian:x@sha256:y\n"
                 "    steps:\n"
                 "      - uses: actions/checkout@abc\n"
                 "      - uses: actions/setup-python@def\n"
                 "        with:\n"
                 '          python-version: "3.12"\n'
                 "      - run: |\n"
                 "          pip install jsonschema==4.26.0 PyYAML==6.0.2 lark==1.3.0\n"
                 "          apt-get install ngspice=46+ds-1\n"
                 "          docker pull kicad/kicad:9.0.9@sha256:aaa\n"),
        MANIFEST: 'version: "46"\n',
        RUN_SIM: 'fail_env "could not read ngspice.version from the manifest."\n',
        DCO: ("on: push\njobs:\n  d:\n    steps:\n"
              "      - uses: actions/checkout@abc\n"),
        POLICY: ("on: push\njobs:\n  p:\n    steps:\n"
                 "      - uses: actions/checkout@abc\n"),
    }

    def reader(mapping):
        return lambda path: mapping.get(path)

    problems, checked, _refs = check(fake, reader(good))
    cases = [("a consistent manifest reports no problem", not problems and checked > 0)]

    drifted = dict(good)
    drifted[CHECKS] = good[CHECKS].replace("jsonschema==4.26.0", "jsonschema==9.9.9")
    cases.append(("a drifted package pin is caught", any(
        "jsonschema" in p for p in check(fake, reader(drifted))[0])))

    # THE PER-OCCURRENCE RULE, which had no case: every `drifted` fixture above
    # REMOVES the needle entirely, which lands on the "does not contain" branch
    # instead. This is the shape the rule was written for -- a file with several
    # `python-version:` lines, one of them drifted, the rest still correct.
    multi = dict(good)
    multi[CHECKS] = good[CHECKS].replace(
        'python-version: "3.12"\n',
        'python-version: "3.12"\npython-version: "3.12"\npython-version: "3.11"\n')
    cases.append(("one drifted line among several correct ones is caught", any(
        "at least one disagrees" in p for p in check(fake, reader(multi))[0])))

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
        # checked=MINIMUM_AGREEMENTS, NOT 0. With 0 the floor produced the
        # non-zero exit all by itself, so the branch this case is named for
        # could be deleted and the case stayed green -- a floor tripping in
        # place of the check it backstops, which is the exact failure this
        # file's other comments warn about.
        globals()["check"] = lambda *_a, **_k: (
            ["planted problem"], MINIMUM_AGREEMENTS, dict(MINIMUM_ACTION_REFS))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            planted = main([])
        globals()["check"] = lambda *_a, **_k: (
            [], MINIMUM_AGREEMENTS, dict(MINIMUM_ACTION_REFS))
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
        problems, checked, action_refs = check(manifest)
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
    missing_jobs = []
    for workflow_name, jobs in REQUIRED_JOBS.items():
        path = ROOT / ".github" / "workflows" / workflow_name
        if not path.is_file():
            missing_jobs.append(f"{workflow_name}: the workflow file is gone")
            continue
        try:
            import yaml as _yaml
            defined = set((_yaml.safe_load(path.read_text(encoding="utf-8"))
                           or {}).get("jobs") or {})
        except Exception as exc:
            missing_jobs.append(f"{workflow_name}: not parseable ({exc})")
            continue
        for job in jobs:
            if job not in defined:
                missing_jobs.append(f"{workflow_name}: job {job!r} is gone")
    # Every gate command must appear in some workflow, and in a job that is
    # not disabled.
    workflow_text = ""
    live_jobs = 0
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            import yaml as _yaml
            document = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            if str(job.get("if", "")).strip().lower() in ("false", "${{ false }}"):
                missing_jobs.append(
                    f"{path.name}: job {job_name!r} is disabled with `if: false`, "
                    "so it defines steps and runs none of them")
                continue
            live_jobs += 1
            for step in (job.get("steps") or []):
                if isinstance(step, dict) and step.get("run"):
                    workflow_text += "\n" + str(step["run"])
    for command in REQUIRED_CI_COMMANDS:
        if command not in workflow_text:
            missing_jobs.append(
                f"no live CI job runs {command!r}. A gate that runs only in "
                "`make all` is not enforced on a pull request.")
    if missing_jobs:
        print("toolchain-pins: FAIL: CI job(s) removed:", file=sys.stderr)
        for entry in missing_jobs:
            print(f"  {entry}. A job is what runs a gate; counting `uses:` "
                  "steps let a whole deleted job be paid for by duplicated "
                  "steps in the same file.", file=sys.stderr)
        return 1

    short = {name: (action_refs.get(name, 0), floor)
             for name, floor in MINIMUM_ACTION_REFS.items()
             if action_refs.get(name, 0) < floor}
    if short:
        print("toolchain-pins: FAIL: workflow(s) below their action-reference "
              "floor:", file=sys.stderr)
        for name, (found, floor) in sorted(short.items()):
            print(f"  {name}: {found} of {floor}. Counted PER FILE: one total "
                  "let a whole deleted job be paid for by a duplicated step "
                  "elsewhere.", file=sys.stderr)
        return 1
    for pin in sorted(set(READ_BY_KEY)):
        print(f"toolchain-pins: read-by-key: {pin} — its consumer reads this pin "
              "from the manifest rather than copying the value, so agreement is "
              "structural and the value itself is not compared here.")
    print(f"toolchain-pins: PASS: {checked} pin/consumer agreement(s) and "
          f"{sum(action_refs.values())} action reference(s) verified across "
          f"{len(action_refs)} workflow file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
