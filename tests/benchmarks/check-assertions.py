#!/usr/bin/env python3
"""Compare a benchmark's measured .meas values against its declared windows.

`run-sim.sh` proves a deck RAN. This proves it produced the right numbers, and
until it existed nothing did: `assertions.yaml` was referenced by no code in
the repository at all. An audit set `RB 680k -> 68k` and `RL 560 -> 56` in
benchmark (a) — 6.1 Hz against a 0.932-1.051 Hz window, 74 mA through a 0.25 W
resistor — and `make sim` printed PASS. Widening a window to something absurd,
or tightening one until nothing could satisfy it, was equally invisible.

AMB-39's acceptance criterion calls the benchmarks "gate-load-bearing" and says
(b)'s assertion values were hand-validated in raw ngspice "so AC3 surprises
surface now, not M6". They cannot surface if nothing compares them.

WHAT THIS CHECKS, per benchmark:

  - every declared assertion names a `.meas` id that the deck actually emits;
  - that measurement produced a NUMBER, not ngspice's `failed` sentinel;
  - the number lies inside the declared window;
  - the `measured:` value recorded in the YAML still matches what the deck
    produces now, within a tolerance that catches transcription drift without
    failing on last-digit formatting;
  - a benchmark declares whether it has a deck at all, so a deleted deck is a
    failure rather than a silently shorter run.

THE `failed` SENTINEL is called out separately because it is the specific hole
this file was written around. ngspice prints `f_osc = failed` for a derived
`PARAM` measure whose inputs did not resolve — it does not omit the line, and
it does not exit non-zero. `run-sim.sh` checked that each name appeared in the
log with an `=` after it, which `failed` satisfies. Both of benchmark (a)'s
headline assertions are that exact class.

TWO YAML SHAPES are accepted because the two benchmarks were authored
independently and both are frozen M0 artifacts:

  window: [0.952 s, 1.073 s]        # (a): unit-suffixed strings
  expected: {min: 3.201, max: 3.399, unit: V}   # (b): base units, explicit

Units are resolved through an explicit table. An unrecognised unit is a hard
failure, never a silent 1.0 — a gate that guesses a scale factor is worse than
no gate, because `8.0 mA` read as `8.0 A` passes everything forever.

Exit codes: 0 pass, 1 assertion failure, 2 environment failure (PyYAML absent
or a log missing — an unavailable gate is not a pass).

Usage: check-assertions.py <benchmark-dir> <ngspice-log>
       check-assertions.py --self-test
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Explicit, because guessing is how `8.0 mA` becomes `8.0 A`. The value maps a
# declared unit onto the unit ngspice actually reports for that measurement:
# base SI, except that a `.meas` computing a percentage already reports
# percent, so `%` is 1.0 rather than 0.01.
UNIT_SCALE = {
    "s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9,
    "V": 1.0, "mV": 1e-3, "uV": 1e-6,
    "A": 1.0, "mA": 1e-3, "uA": 1e-6,
    "Hz": 1.0, "kHz": 1e3, "MHz": 1e6,
    "W": 1.0, "mW": 1e-3,
    "%": 1.0, "percent": 1.0, "ratio": 1.0, "": 1.0,
}

# The unit a measurement is REPORTED in, where that differs from the unit its
# bounds are written in. Defaults to the bound's own unit, i.e. no conversion.
#
# The two benchmarks genuinely differ here and neither is wrong. Benchmark (a)
# measures raw SPICE quantities, so `i_led_on` comes back in amps while its
# window is written `8.0 mA`. Benchmark (b)'s `t_settle_us` is a PARAM that
# multiplies by 1e6, so it comes back already in microseconds and a `us` bound
# must NOT be scaled again — doing so compared 16.02 against 0.0005 and failed
# a healthy converter. So the conversion is per-assertion and explicit:
#
#     scale = UNIT_SCALE[bound unit] / UNIT_SCALE[reported_unit]
#
# and an assertion that says nothing converts nothing.
REPORTED_UNIT_KEY = "reported_unit"

# `name = value` as ngspice batch mode prints it, including the `failed`
# sentinel so this file can reject it explicitly rather than fail to match it.
MEAS_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>failed|[-+0-9.eE]+)",
    re.MULTILINE,
)

QUANTITY = re.compile(r"^\s*(?P<number>-?[0-9.]+(?:[eE][-+]?[0-9]+)?)\s*(?P<unit>[A-Za-z%]*)\s*$")

# The recorded `measured:` values are rounded transcriptions of a real run, and
# they are rounded to DIFFERENT precisions: `0.112` claims three significant
# figures, `1.01191` claims six. A flat relative tolerance therefore either
# rejects the three-figure records or waves through a real change in the
# six-figure ones. So the comparison is made at the precision the value was
# written to: round this run's result to the recorded number of significant
# figures and require equality. A record that claims more digits than it can
# support is held to all of them, which is the right incentive.
# How wide a two-sided window may be, as a multiple of the value it brackets,
# and how far a one-sided bound may sit from it. Loose on purpose: a real
# tolerance stack is rarely wider, and this must not fight engineering. It
# exists to catch a window that has stopped asserting anything at all.
# How many assertions each deck benchmark must carry. Every sibling gate has a
# floor; these two did not, so 8 of the 10 declared assertions could be deleted
# with `make sim` green.
MINIMUM_ASSERTIONS = 5

MAX_RELATIVE_WINDOW = 3.0
# A one-sided bound is a SPEC LIMIT, not a tolerance: "ripple below 50 mV" on a
# converter measuring 3.6 mV is a 14x margin and is exactly what good design
# looks like, and "overshoot under 5%" against 0.048% is 100x. Holding those to
# the two-sided ratio would have failed a healthy benchmark, which is how a
# gate teaches people to widen its own thresholds. The number here is chosen to
# catch absurdity — a limit six orders of magnitude away asserts nothing — and
# nothing tighter, because anything tighter is a judgement about the design
# rather than about the assertion.
MAX_ONE_SIDED_RATIO = 200.0

SIGNIFICANT = re.compile(r"[1-9][0-9]*(?:\.[0-9]*)?|0\.0*[1-9][0-9]*")


def significant_figures(text):
    """How many significant digits a written number claims."""
    digits = SIGNIFICANT.search(str(text).strip().lstrip("+-").split("e")[0].split("E")[0])
    if not digits:
        return 1
    return max(1, len(digits.group(0).replace(".", "").lstrip("0")))


def round_to_significant(value, figures):
    if value == 0:
        return 0.0
    from math import floor, log10
    return round(value, -int(floor(log10(abs(value)))) + (figures - 1))


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def parse_quantity(raw, where):
    """`"8.0 mA"` or `8.0` -> (number, unit), UNSCALED.

    Scaling happens in `to_reported`, once, against the assertion's declared
    `reported_unit`. Doing it here instead made the two YAML shapes convert
    differently — `window:` to base SI and `expected:` not at all — which
    happened to suit the two files as authored and would have been a trap for
    the third.
    """
    if isinstance(raw, (int, float)):
        return float(raw), ""
    match = QUANTITY.match(str(raw))
    if not match:
        raise ValueError(f"{where}: {raw!r} is not a number with an optional unit")
    unit = match.group("unit")
    if unit not in UNIT_SCALE:
        raise ValueError(
            f"{where}: unit {unit!r} is not in UNIT_SCALE. Add it with its scale "
            "rather than letting the comparison guess: a unit read at the wrong "
            "scale passes every window forever."
        )
    return float(match.group("number")), unit


def to_reported(raw, assertion, where):
    """A declared bound, converted into the unit the measurement comes back in."""
    number, unit = parse_quantity(raw, where)
    reported = assertion.get(REPORTED_UNIT_KEY, unit)
    if reported not in UNIT_SCALE:
        raise ValueError(f"{where}: {REPORTED_UNIT_KEY} {reported!r} is not in UNIT_SCALE")
    return number * UNIT_SCALE[unit] / UNIT_SCALE[reported]


def parse_log(text):
    """Every `.meas` result in an ngspice batch log: name -> float or 'failed'."""
    out = {}
    for match in MEAS_LINE.finditer(text):
        value = match.group("value")
        out[match.group("name").lower()] = (
            "failed" if value == "failed" else float(value)
        )
    return out


def bounds_of(assertion, name):
    """(low, high) in the unit the measurement is reported in."""
    if "window" in assertion:
        window = assertion["window"]
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError(f"{name}: `window` must be a two-element list")
        return (to_reported(window[0], assertion, f"{name}.window[0]"),
                to_reported(window[1], assertion, f"{name}.window[1]"))
    expected = assertion.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(
            f"{name}: needs either `window: [low, high]` or "
            "`expected: {min/max, unit}`; an assertion with no bound "
            "cannot fail and so is not an assertion"
        )
    unit = expected.get("unit", "")
    probe = dict(assertion)
    low = (to_reported(f"{float(expected['min'])} {unit}".strip(), probe, f"{name}.min")
           if "min" in expected else float("-inf"))
    high = (to_reported(f"{float(expected['max'])} {unit}".strip(), probe, f"{name}.max")
            if "max" in expected else float("inf"))
    if low == float("-inf") and high == float("inf"):
        raise ValueError(f"{name}: `expected` declares neither min nor max")
    return low, high


def meas_id_of(assertion, name):
    """The `.meas` name backing an assertion.

    Explicit `meas_id` wins; otherwise the assertion's own name must be the
    measurement's name. Guessing beyond that is how an assertion silently
    stops being connected to anything.
    """
    return str(assertion.get("meas_id") or name).lower()


def check_benchmark(case, spec, log_text, problems, minimum=None):
    """One benchmark's assertions against one ngspice log."""
    measured = parse_log(log_text)
    assertions = spec.get("assertions") or []
    if not assertions:
        problems.append(f"{case}: declares no assertions; a benchmark must assert something")
        return 0
    floor = MINIMUM_ASSERTIONS if minimum is None else minimum
    if len(assertions) < floor:
        problems.append(
            f"{case}: declares {len(assertions)} assertion(s), below the floor "
            f"of {floor}. Lowering it is a decision; drifting under it is not."
        )

    checked = 0
    for assertion in assertions:
        name = assertion.get("name") or "<unnamed>"
        label = f"{case}/{name}"
        try:
            meas_id = meas_id_of(assertion, name)
            low, high = bounds_of(assertion, label)
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{label}: {exc}")
            continue

        if meas_id not in measured:
            problems.append(
                f"{label}: no `.meas` named {meas_id!r} in the run log. The "
                "assertion names a measurement the deck does not emit, so it "
                "has never been evaluated."
            )
            continue

        value = measured[meas_id]
        if value == "failed":
            problems.append(
                f"{label}: `.meas {meas_id}` reported ngspice's `failed` "
                "sentinel. ngspice prints this and still exits 0, so a check "
                "that only looks for the name in the log counts it as a value."
            )
            continue

        checked += 1

        # A WINDOW MUST BE A CLAIM. Comparing a measurement to a bound the same
        # author wrote in the same file checks YAML-against-deck agreement, not
        # engineering: widening `[0.932 Hz, 1.051 Hz]` to
        # `[0.000001 Hz, 1000000 Hz]` passed, so the gate could not fail on a
        # value in either direction once both files moved together.
        #
        # The floor is deliberately loose — 3x around the expected value, or
        # 200x for a one-sided bound (MAX_ONE_SIDED_RATIO; this comment said
        # 10x, a threshold twenty times tighter than the one applied) —
        # because a legitimate tolerance stack is rarely
        # wider than that and this must not fight real engineering. It exists to
        # catch the window that has stopped asserting anything at all.
        # THE MEASURED VALUE, always. It used to be `expected:` for shape (a),
        # which the same author writes in the same file — so a coordinated edit
        # to deck, window and expected passed, which is the exact attack this
        # docstring says the guard exists to catch. The run's own output is the
        # only centre not under the author's control.
        centre = value
        if centre is not None and centre != 0:
            if low > float("-inf") and high < float("inf"):
                span = (high - low) / abs(centre)
                if span > MAX_RELATIVE_WINDOW:
                    problems.append(
                        f"{label}: window [{low:.6g}, {high:.6g}] spans "
                        f"{span:.1f}x its expected value {centre:.6g}. A "
                        "window that wide asserts nothing; state a real "
                        f"tolerance or raise MAX_RELATIVE_WINDOW "
                        f"(currently {MAX_RELATIVE_WINDOW}) deliberately."
                    )
                    continue
            else:
                # A `max:` is meaningless when far ABOVE the value; a
                # `min:` when far BELOW it. Testing `bound/centre > ratio`
                # only caught the first, so `efficiency min=1e-30` passed —
                # and `bound == 0` was skipped outright, so `min=0.0` did
                # too. The slack is measured in the direction the bound
                # actually constrains.
                if high < float("inf"):
                    bound, slack = high, (abs(high / centre) if centre else 0.0)
                else:
                    bound = low
                    slack = (abs(centre / low) if low else float("inf"))
                if slack > MAX_ONE_SIDED_RATIO:
                    problems.append(
                        f"{label}: one-sided bound {bound:.6g} leaves "
                        f"{slack:.1f}x slack against its expected value "
                        f"{centre:.6g}, so it cannot fail."
                    )
                    continue
        if not (low <= value <= high):
            problems.append(
                f"{label}: measured {value:.6g} is outside the declared window "
                f"[{low:.6g}, {high:.6g}]"
            )
            continue

        recorded = assertion.get("measured")
        if recorded is not None:
            try:
                expected_value = to_reported(recorded, assertion, f"{label}.measured")
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
                continue
            figures = significant_figures(recorded)
            if round_to_significant(value, figures) != round_to_significant(
                expected_value, figures
            ):
                problems.append(
                    f"{label}: the recorded `measured:` value {expected_value:.6g} "
                    f"no longer matches this run's {value:.6g}. Either the deck "
                    "changed and the record is stale, or the record was never "
                    "taken from a real run."
                )
    return checked


def load_yaml(path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment failure
        raise GateUnavailable(
            "PyYAML is required to read benchmark assertions; install the pin "
            "from toolchain/versions.yaml (python3 -m pip install pyyaml==6.0.2)."
        ) from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateUnavailable(f"{path} is not readable as YAML: {exc}") from exc


# Benchmarks whose transcript MUST exist. Named rather than inferred, because
# "no validation.log" and "this directory is a self-test fixture" are otherwise
# the same observation.
MUST_HAVE_TRANSCRIPT = frozenset({"blinker-555", "buck-3v3", "esp32s3-devboard"})


def transcript_problems(case_dir, fresh_text, problems, minimum_measurements=None):
    """Hold validation.log to the run it claims to be a capture of.

    Five `validation.log` files are cited as committed evidence by nine tracked
    documents, and NOTHING read them -- the same defect design.md had. It bit
    immediately: correcting SBAND moved t_settle_us and left the transcript
    recording the old value, with every gate green.

    A transcript is a verbatim capture, so every `.meas` value in it must equal
    the value a fresh run produces, at the precision the transcript states.
    Returns the number of measurements reconciled.
    """
    log_path = case_dir / "validation.log"
    if not log_path.is_file():
        if case_dir.name in MUST_HAVE_TRANSCRIPT:
            problems.append(
                f"{case_dir.name}: has no validation.log. Nine tracked "
                "documents cite these files as committed evidence; a missing "
                "one used to return 0 and let the gate print PASS, which is "
                "the same 'reduce the number of things checked' failure the IR "
                "pairing forbids.")
        return 0
    # ngspice's own `exit` status line matches the meas shape and is not a
    # measurement. Anything the deck does not declare with `.meas` is excluded
    # by name rather than by guessing at the format.
    NOT_A_MEASUREMENT = {"exit"}
    fresh = {}
    for line in fresh_text.splitlines():
        found = MEAS_LINE.match(line)
        if found:
            fresh.setdefault(found.group("name").lower(), found.group("value"))
    reconciled = 0
    seen = set()
    lines_seen = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        found = MEAS_LINE.match(line)
        if not found:
            continue
        name = found.group("name").lower()
        if name in NOT_A_MEASUREMENT:
            continue
        # EVERY occurrence, not the first. blinker-555's transcript already
        # ships a duplicated `.meas results` block, so deduping meant a correct
        # six-line header made the whole ngspice capture below it -- 6.1 Hz,
        # 74 mA -- invisible to this comparison.
        seen.add(name)
        if name not in fresh:
            problems.append(
                f"{case_dir.name}/validation.log: records `{name}`, which this "
                "deck no longer emits. A transcript naming a measurement that "
                "does not exist is not evidence of anything.")
            continue
        recorded, now = float(found.group("value")), float(fresh[name])
        figures = min(significant_figures(found.group("value")),
                      significant_figures(fresh[name]))
        if round_to_significant(recorded, figures) != round_to_significant(now, figures):
            problems.append(
                f"{case_dir.name}/validation.log: records {name} = {recorded:.6g}, "
                f"but this deck now produces {now:.6g}. The file the documents "
                "cite as evidence describes a deck that no longer exists.")
            continue
        reconciled += 1
    # A FLOOR. Truncating the file to one correct line reported "1 transcript
    # measurement matched" and exited 0; an empty file reported 0 and did the
    # same. The count of `.meas` names the deck declares is the right bar.
    if minimum_measurements is not None and len(seen) < minimum_measurements:
        problems.append(
            f"{case_dir.name}/validation.log: reconciles {len(seen)} distinct "
            f"measurement(s), but this deck declares {minimum_measurements}. A "
            "truncated or emptied transcript is not evidence.")
    return reconciled


# THE DECK MUST BE THE CIRCUIT THE BOM DECLARES. Nothing compared them. An
# auditor changed the blinker deck's RB from 680k to 700k -- not an E24 or E96
# value, and absent from parts.yaml, design.md, the IR and the DSL model, all
# of which still said 680k -- re-recorded the five measured values, and
# `make all` exited 0. `measured:` pins a number; nothing pinned the property
# that the number came from the declared circuit. Both benchmarks' parts.yaml
# were read by no code at all.
# benchmark -> how many deck passives MUST carry their parts.yaml value.
#
# buck-3v3 is 0 here ON PURPOSE, and the zero is declared rather than arrived
# at silently: its deck is an averaged behavioural model whose passives are
# `.param`s and whose divider refdes differ from the BOM's, so a REFDES match
# is a correspondence the deck never asserts. The `.param`-level
# correspondence its comments DO assert is enforced by DECK_PARAM_RULES
# below -- an earlier revision of this comment said "nothing in the deck
# claims to be a realisation of that BOM", which the deck's own .param
# comments contradicted line by line (round 16).
MINIMUM_BOM_PASSIVES = {"blinker-555": 6, "buck-3v3": 0}

# benchmark -> deck parameter/instance -> how the BOM pins it. The buck deck's
# .param block claims a per-part correspondence in its own comments (RON cites
# the BSC059N04LS6 max, DCR the XGL6060 max, CEFF the derated output pair,
# LVAL the inductor), and round 16 replayed the blinker's coordinated
# re-record attack at exactly that level: retime LVAL, mechanically re-record
# every measured value, and no gate read the buck's parts.yaml at all.
# Rule kinds:
#   "value"    spice_value of the part's `value:` field, exact
#   "regex"    a number extracted from value+notes by pattern, times scale,
#              exact
#   "roundup"  like "regex", but the deck may round UP by at most 5% (the
#              deck's own stated convention for Rds(on))
DECK_PARAM_RULES = {
    "buck-3v3": (
        ("LVAL",   "L1", "value",   None,                        1),
        ("DCR",    "L1", "regex",   r"([\d.]+)\s*mOhm max",      1e-3),
        ("RON_HS", "Q1", "roundup", r"([\d.]+)\s*mOhm max",      1e-3),
        ("RON_LS", "Q2", "roundup", r"([\d.]+)\s*mOhm max",      1e-3),
        ("CEFF",   "C2", "regex",   r"~([\d.]+)\s*uF effective", 1e-6),
        ("RESR",   "C2", "regex",   r"net ESR ~([\d.]+)\s*mOhm", 1e-3),
        ("RFB1",   "R1", "value",   None,                        1),
        ("RFB2",   "R2", "value",   None,                        1),
    ),
    # The blinker instantiates its passives at component level under the
    # BOM's own refdes -- deck_bom_problems reconciles those directly -- and
    # its deck declares no .param at all.
    "blinker-555": (),
}


def deck_param_problems(case_dir, problems, rules=None,
                        deck_text=None, bom_text=None):
    """Every deck parameter the rule table names must trace to the BOM."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_derive555p", Path(__file__).with_name("derive-555-windows.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if rules is None:
        # Mirror deck_bom_problems: a case with no deck at all is run-sim's
        # missing-deck failure, not a rule-table complaint.
        if deck_text is None and not (case_dir / "netlist.cir").is_file():
            return 0
        if case_dir.name not in DECK_PARAM_RULES:
            problems.append(
                f"{case_dir.name}: no deck-parameter rule table is declared "
                "for this benchmark. A parameterised deck with no declared "
                "correspondence is the state the buck was in when its LVAL "
                "could be retimed and re-recorded with everything green.")
            return 0
        rules = DECK_PARAM_RULES[case_dir.name]
    if deck_text is None:
        deck = case_dir / "netlist.cir"
        deck_text = deck.read_text(encoding="utf-8", errors="replace") \
            if deck.is_file() else ""
    if bom_text is None:
        bom = case_dir / "parts.yaml"
        bom_text = bom.read_text(encoding="utf-8", errors="replace") \
            if bom.is_file() else ""

    values = {ref.upper(): got
              for ref, got in module.passives_from_deck(deck_text).items()}
    for line in deck_text.splitlines():
        found = re.match(r"\s*\.param\s+(\w+)=(\S+)", line)
        if not found:
            continue
        try:
            values[found.group(1).upper()] = module.spice_value(found.group(2))
        except (ValueError, IndexError):
            continue  # computed parameters like {1/FSW} pin nothing here

    import yaml as _yaml
    declared = {str(p.get("ref") or "").upper(): p
                for p in (_yaml.safe_load(bom_text) or {}).get("parts") or []}

    reconciled = 0
    for name, ref, kind, pattern, scale in rules:
        part = declared.get(ref.upper())
        if part is None:
            problems.append(
                f"{case_dir.name}: the rule table pins deck parameter {name} "
                f"to BOM ref {ref}, which parts.yaml no longer declares.")
            continue
        if name.upper() not in values:
            problems.append(
                f"{case_dir.name}: netlist.cir no longer carries {name}, "
                f"which the rule table pins to {ref}. A parameter cannot "
                "leave the correspondence by being renamed.")
            continue
        got = values[name.upper()]
        source = f"{part.get('value') or ''} {part.get('notes') or ''}"
        if kind == "value":
            try:
                want = module.spice_value(str(part.get("value") or ""))
            except ValueError:
                problems.append(
                    f"{case_dir.name}/parts.yaml: {ref} declares no number "
                    f"for deck parameter {name} to be compared against.")
                continue
        else:
            found = re.search(pattern, source)
            if not found:
                problems.append(
                    f"{case_dir.name}/parts.yaml: {ref} no longer states the "
                    f"figure matching {pattern!r}, so deck parameter {name} "
                    "is compared to nothing.")
                continue
            want = float(found.group(1)) * scale
        if kind == "roundup":
            if got < want * (1 - 1e-9) or got > want * 1.05:
                problems.append(
                    f"{case_dir.name}: deck parameter {name}={got:g} must "
                    f"round UP from {ref}'s {want:g} by at most 5%; it does "
                    "not. The deck's own comment states the convention.")
                continue
        elif abs(got - want) > 1e-9 * max(abs(want), 1.0):
            problems.append(
                f"{case_dir.name}: deck parameter {name}={got:g} but "
                f"parts.yaml's {ref} gives {want:g}. The averaged model's "
                "parameters are the BOM's values by the deck's own claim; a "
                "retimed parameter with re-recorded measurements gates a "
                "circuit nobody specified.")
            continue
        reconciled += 1
    return reconciled


def deck_bom_problems(case_dir, problems, minimum=None):
    """Every passive the deck instantiates must carry the BOM's value."""
    deck = case_dir / "netlist.cir"
    bom = case_dir / "parts.yaml"
    if not deck.is_file() or not bom.is_file():
        return 0
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_derive555", Path(__file__).with_name("derive-555-windows.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    declared = load_yaml(bom).get("parts") or []
    deck_values = module.passives_from_deck(
        deck.read_text(encoding="utf-8", errors="replace"))
    reconciled = 0
    for part in declared:
        ref = str(part.get("ref") or "").upper()
        raw = str(part.get("value") or "")
        if ref not in deck_values or not raw:
            continue
        try:
            want = module.spice_value(raw)
        except ValueError:
            problems.append(
                f"{case_dir.name}/parts.yaml: {ref} declares value {raw!r}, "
                "which carries no number the deck could be compared against.")
            continue
        got = deck_values[ref]
        if abs(got - want) > 1e-9 * max(abs(want), 1.0):
            problems.append(
                f"{case_dir.name}: netlist.cir instantiates {ref} at {got:g} "
                f"but parts.yaml declares {raw!r} ({want:g}). The deck is "
                "supposed to be the simulated realisation of the declared "
                "design; a value in one and not the other means the "
                "measurements gate a circuit nobody specified.")
            continue
        reconciled += 1
    if minimum is None and case_dir.name not in MINIMUM_BOM_PASSIVES:
        problems.append(
            f"{case_dir.name}: no deck/BOM reconciliation floor is declared "
            "for this benchmark. A new benchmark whose refdes happen not to "
            "match would reconcile zero and pass, which is the state both "
            "parts.yaml files were in when nothing read them.")
        return reconciled
    floor = (MINIMUM_BOM_PASSIVES.get(case_dir.name) if minimum is None
             else minimum)
    if floor is not None and reconciled < floor:
        problems.append(
            f"{case_dir.name}: reconciled {reconciled} deck passive(s) against "
            f"parts.yaml, below the floor of {floor}. A refdes that stops "
            "matching leaves the comparison silently, which is how parts.yaml "
            "came to be read by nothing at all.")
    return reconciled


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2

    case_dir, log_path = Path(argv[0]), Path(argv[1])
    spec_path = case_dir / "assertions.yaml"
    if not spec_path.is_file():
        print(f"sim-assert: FAIL: {case_dir.name} has no assertions.yaml", file=sys.stderr)
        return 1
    if not log_path.is_file():
        print(f"sim-assert: FAIL: {log_path} does not exist", file=sys.stderr)
        return 2

    problems = []
    try:
        spec = load_yaml(spec_path)
        checked = check_benchmark(
            case_dir.name, spec, log_path.read_text(encoding="utf-8", errors="replace"),
            problems,
        )
        fresh_text = log_path.read_text(encoding="utf-8", errors="replace")
        # The floor is the number of distinct .meas names the DECK declares,
        # read from the deck itself so it cannot drift from the benchmark.
        deck = case_dir / "netlist.cir"
        declared = set()
        if deck.is_file():
            for line in deck.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip().lower()
                if stripped.startswith(".meas"):
                    parts = stripped.split()
                    if len(parts) >= 3:
                        declared.add(parts[2])
        transcript = transcript_problems(
            case_dir, fresh_text, problems,
            minimum_measurements=len(declared) or None)
        passives = deck_bom_problems(case_dir, problems)
        params = deck_param_problems(case_dir, problems)
    except GateUnavailable as exc:
        print(f"sim-assert: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    if problems:
        print(f"sim-assert: FAIL: {case_dir.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"sim-assert: PASS: {case_dir.name}: {checked} assertion(s) inside "
          f"their windows; {transcript} transcript measurement(s) match a fresh "
          f"run; {passives} deck passive(s) carry their parts.yaml value; "
          f"{params} deck parameter(s) trace to the BOM.")
    return 0


def _floor_probe():
    """Drive check_benchmark with the SHIPPED floor, not the probes' minimum=0.

    MINIMUM_ASSERTIONS had no case either: deleting it left 17/17 green. The
    probes all pass minimum=0 by design, so a case using `run` could never
    reach the floor -- which is how three floors in this repository ended up
    tripping their own fixtures instead of being tested.
    """
    problems = []
    check_benchmark("case", {"assertions": [
        {"name": "osc_period", "meas_id": "t_period",
         "window": ["0.952 s", "1.073 s"], "measured": "1.01191 s"}]},
        "t_period   =  1.01191e+00\n", problems)
    return problems


def self_test():
    """Prove each rejection fires. A checker nobody has watched fail is prose."""
    log = "t_period   =  1.01191e+00\nf_osc      =   failed\ni_led_on   =  9.25678e-03\n"
    base = {"assertions": [
        {"name": "osc_period", "meas_id": "t_period",
         "window": ["0.952 s", "1.073 s"], "measured": "1.01191 s"},
    ]}

    def run(spec, text=log):
        problems = []
        # minimum=0: these probes are single assertions by design; the floor is
        # a statement about a real benchmark's population, not about a fixture.
        check_benchmark("case", spec, text, problems, minimum=0)
        return problems

    cases = [
        ("a passing assertion reports no problem", not run(base)),
        ("the `failed` sentinel is rejected", any(
            "failed" in p for p in run({"assertions": [
                {"name": "osc_frequency", "meas_id": "f_osc", "window": ["0.932 Hz", "1.051 Hz"]}]}))),
        ("a value outside its window is rejected", any(
            "outside the declared window" in p for p in run({"assertions": [
                {"name": "osc_period", "meas_id": "t_period", "window": ["2.0 s", "3.0 s"]}]}))),
        ("a meas the deck never emits is rejected", any(
            "does not emit" in p for p in run({"assertions": [
                {"name": "ghost", "meas_id": "nope", "window": ["0 s", "1 s"]}]}))),
        ("a stale recorded value is rejected", any(
            "no longer matches" in p for p in run({"assertions": [
                {"name": "osc_period", "meas_id": "t_period",
                 "window": ["0.952 s", "1.073 s"], "measured": "0.5 s"}]}))),
        # A record rounded to three figures must not be failed by a run that
        # agrees to three figures, and a record claiming six must be held to six.
        ("a 3-figure record matches a run that agrees to 3 figures",
         significant_figures("0.112") == 3
         and round_to_significant(0.111646, 3) == 0.112),
        ("a 6-figure record is held to all six",
         significant_figures("1.01191") == 6
         and round_to_significant(1.011995, 6) != 1.01191),
        ("an assertion with no bound is rejected", any(
            "cannot fail" in p for p in run({"assertions": [
                {"name": "unbounded", "meas_id": "t_period"}]}))),
        ("an unknown unit is rejected, not assumed to be 1.0", any(
            "UNIT_SCALE" in p for p in run({"assertions": [
                {"name": "bad_unit", "meas_id": "t_period", "window": ["1 furlong", "2 furlong"]}]}))),
        ("a benchmark with no assertions is rejected", any(
            "must assert something" in p for p in run({"assertions": []}))),
        # The unit table is the whole comparison. `8.0 mA` read as amps would
        # put every current window a thousand times too wide, forever.
        ("mA converts to amps when the meas reports amps", abs(
            to_reported("8.0 mA", {"reported_unit": "A"}, "x") - 0.008) < 1e-15),
        ("a us bound is NOT rescaled when the meas already reports us", abs(
            to_reported("500 us", {}, "x") - 500.0) < 1e-12),
        ("a percentage is not rescaled", to_reported("53.4 %", {}, "x") == 53.4),
        ("the buck shape resolves", bounds_of(
            {"expected": {"min": 3.201, "max": 3.399, "unit": "V"}}, "x") == (3.201, 3.399)),
        ("a min-only bound has an open top", bounds_of(
            {"expected": {"min": 0.85, "unit": "ratio"}}, "x")[1] == float("inf")),
    ]

    # THE WIDTH GUARD, which had no case at all: deleting the entire block left
    # 17/17 green, so nothing stopped a window from asserting nothing. The
    # one-sided ratio was 1000x, which let a 3.5 V bound stand against a 3.6 mV
    # ripple; the loosest bound any shipped benchmark needs is 107x.
    cases.append(("a two-sided window far wider than its value is caught", any(
        "spans" in p for p in run({"assertions": [
            {"name": "osc_period", "meas_id": "t_period",
             "window": ["0.001 s", "9.8 s"], "measured": "1.01191 s"}]}))))
    cases.append(("a one-sided max with absurd slack is caught", any(
        "cannot fail" in p for p in run({"assertions": [
            {"name": "osc_period", "meas_id": "t_period",
             "expected": {"max": 500.0, "unit": "s"}, "measured": 1.01191}]}))))
    cases.append(("a one-sided min far BELOW its value is caught", any(
        "cannot fail" in p for p in run({"assertions": [
            {"name": "osc_period", "meas_id": "t_period",
             "expected": {"min": 0.001, "unit": "s"}, "measured": 1.01191}]}))))
    cases.append(("the assertion floor fires on a one-assertion benchmark", any(
        "floor" in p for p in _floor_probe())))

    # THE TRANSCRIPT LEG. validation.log is cited as evidence by nine tracked
    # documents and was read by nothing, which is how correcting SBAND left it
    # recording a settling time the deck no longer produces.
    import tempfile as _tf
    def transcript_probe(recorded, fresh):
        with _tf.TemporaryDirectory() as tmp:
            case = Path(tmp)
            (case / "validation.log").write_text(recorded, encoding="utf-8")
            ps = []
            transcript_problems(case, fresh, ps)
            return ps

    cases.append(("a transcript matching a fresh run reports nothing", not
        transcript_probe("t_period   =  1.01191e+00\n", "t_period   =  1.01191e+00\n")))
    cases.append(("a stale transcript value is caught", any(
        "no longer exists" in p for p in transcript_probe(
            "t_period   =  1.01191e+00\n", "t_period   =  2.00000e+00\n"))))
    cases.append(("a transcript naming a meas the deck dropped is caught", any(
        "no longer emits" in p for p in transcript_probe(
            "t_ghost    =  1.00000e+00\n", "t_period   =  1.01191e+00\n"))))
    cases.append(("ngspice's own exit line is not read as a measurement", not
        transcript_probe("exit       =  0.00000e+00\n", "t_period   =  1.01191e+00\n")))
    cases.append(("a transcript rounded to fewer figures is not failed", not
        transcript_probe("t_period   =  1.012e+00\n", "t_period   =  1.01191e+00\n")))

    # WIRING, as above: main() must turn a finding into a non-zero exit. This
    # drives the real entry point over a benchmark directory whose deck output
    # is planted, rather than over `check_benchmark` alone.
    import contextlib as _ctx, io as _io, tempfile as _tmp
    with _tmp.TemporaryDirectory() as _d:
        _case = Path(_d) / "probe"
        _case.mkdir()
        _five = "".join(
            f"  - name: osc_period{i}\n    meas_id: t_period\n"
            "    window: [2.0 s, 3.0 s]\n" for i in range(MINIMUM_ASSERTIONS))
        (_case / "assertions.yaml").write_text(
            "deck: netlist.cir\nassertions:\n" + _five, encoding="utf-8")
        _log = Path(_d) / "ng.log"
        _log.write_text("t_period   =  1.01191e+00\n", encoding="utf-8")
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            _planted = main([str(_case), str(_log)])
        _ok = "".join(
            f"  - name: osc_period{i}\n    meas_id: t_period\n"
            "    window: [0.9 s, 1.1 s]\n" for i in range(MINIMUM_ASSERTIONS))
        (_case / "assertions.yaml").write_text(
            "deck: netlist.cir\nassertions:\n" + _ok, encoding="utf-8")
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            _clean = main([str(_case), str(_log)])
    cases.append(("main() exits 1 on a value outside its window", _planted == 1))
    cases.append(("main() exits 0 on a value inside it", _clean == 0))

    # THE DECK MUST BE THE CIRCUIT THE BOM DECLARES. Nothing compared them, and
    # an auditor retimed the blinker by changing its dominant resistor to a
    # value no document in the repository names.
    import tempfile as _tempfile

    def bom_probe(deck_text, bom_text, minimum=0):
        with _tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "case"
            case.mkdir()
            (case / "netlist.cir").write_text(deck_text, encoding="utf-8")
            (case / "parts.yaml").write_text(bom_text, encoding="utf-8")
            problems = []
            count = deck_bom_problems(case, problems, minimum=minimum)
            return problems, count

    DECK = "RA vcc disch 100k\nRB disch nct 680k\nCT nct 0 1u\n"
    BOM = ("parts:\n"
           "  - ref: RA\n    value: 100k 1% 0.25W\n"
           "  - ref: RB\n    value: 680k 1% 0.25W\n"
           "  - ref: CT\n    value: 1uF 5% 63V\n")
    agreeing, agreed_count = bom_probe(DECK, BOM)
    cases.append(("a deck matching its BOM reconciles every passive",
                  not agreeing and agreed_count == 3))
    retimed, _ = bom_probe(DECK.replace("680k", "700k"), BOM)
    cases.append(("a deck value the BOM does not declare is caught", any(
        "instantiates RB" in p for p in retimed)))
    rescaled, _ = bom_probe(DECK.replace("1u", "1n"), BOM)
    cases.append(("a wrong magnitude suffix is caught", any(
        "instantiates CT" in p for p in rescaled)))
    short_problems, short_count = bom_probe("RA vcc disch 100k\n", BOM)
    cases.append(("only the refdes present in the deck are compared",
                  not short_problems and short_count == 1))
    cases.append(("a benchmark reconciling fewer than its floor is caught", any(
        "below the floor" in p for p in bom_probe(
            "RA vcc disch 100k\n", BOM, minimum=3)[0])))
    # A space before the unit is the BOM's other spelling, and reading only the
    # first token made `10 uF` ten farads -- a 1e6 error in the direction that
    # passes every comparison.
    spaced, spaced_count = bom_probe(
        "C1 a b 10u\n", "parts:\n  - ref: C1\n    value: 10 uF +/-10%, 25 V\n")
    cases.append(("a BOM value with a space before its unit is read",
                  not spaced and spaced_count == 1))
    unnamed, _ = bom_probe(DECK, "parts:\n  - ref: RA\n    value: a resistor\n")
    cases.append(("a BOM value with no number is caught", any(
        "carries no number" in p for p in unnamed)))
    # And a benchmark with no declared floor at all must not pass by
    # reconciling nothing, which is how both parts.yaml came to be unread.
    with _tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "unknown-benchmark"
        case.mkdir()
        (case / "netlist.cir").write_text("RX a b 1k\n", encoding="utf-8")
        (case / "parts.yaml").write_text("parts: []\n", encoding="utf-8")
        undeclared = []
        deck_bom_problems(case, undeclared)
    cases.append(("a benchmark with no declared floor is caught", any(
        "no deck/BOM reconciliation floor" in p for p in undeclared)))

    # DECK PARAMETER RULES, every direction. The buck's averaged model claims
    # a per-.param correspondence to the BOM in its own comments; round 16
    # retimed LVAL and re-recorded every measurement with everything green.
    PDECK = (".param LVAL=10u\n.param DCR=20.4m\n.param RON_HS=6m\n"
             ".param TSW={1/FSW}\nRfb1 out fb 31.2k\n")
    PBOM = ("parts:\n"
            "  - ref: L1\n    value: 10 uH +/-20%\n"
            "    notes: DCR 18.5 mOhm typ / 20.4 mOhm max\n"
            "  - ref: Q1\n    value: NMOS 40 V, 5.9 mOhm max @ Vgs=10V\n"
            "  - ref: R1\n    value: 31.2 kOhm, 1%\n")
    PRULES = (("LVAL", "L1", "value", None, 1),
              ("DCR", "L1", "regex", r"([\d.]+)\s*mOhm max", 1e-3),
              ("RON_HS", "Q1", "roundup", r"([\d.]+)\s*mOhm max", 1e-3),
              ("RFB1", "R1", "value", None, 1))

    def param_probe(deck=PDECK, bom=PBOM, rules=PRULES):
        out = []
        count = deck_param_problems(Path("/nonexistent"), out, rules=rules,
                                    deck_text=deck, bom_text=bom)
        return count, out

    pcount, pclean = param_probe()
    cases.append(("a deck whose parameters trace to the BOM reconciles",
                  pcount == 4 and not pclean))
    cases.append(("a retimed parameter is caught", any(
        "gates a circuit nobody specified" in p for p in param_probe(
            deck=PDECK.replace("LVAL=10u", "LVAL=12u"))[1])))
    cases.append(("a drifted extracted figure is caught", any(
        "gates a circuit nobody specified" in p for p in param_probe(
            deck=PDECK.replace("DCR=20.4m", "DCR=18.5m"))[1])))
    cases.append(("a round-up parameter below its source is caught", any(
        "must round UP" in p for p in param_probe(
            deck=PDECK.replace("RON_HS=6m", "RON_HS=5.8m"))[1])))
    cases.append(("a round-up parameter more than 5% above is caught", any(
        "must round UP" in p for p in param_probe(
            deck=PDECK.replace("RON_HS=6m", "RON_HS=6.3m"))[1])))
    cases.append(("a renamed parameter cannot leave the correspondence", any(
        "cannot leave the correspondence" in p for p in param_probe(
            deck=PDECK.replace("LVAL=", "LSOMETHINGELSE="))[1])))
    cases.append(("a BOM ref the table pins must keep existing", any(
        "no longer declares" in p for p in param_probe(
            bom=PBOM.replace("ref: Q1", "ref: Q9"))[1])))
    cases.append(("a value-kind source with no parsable number is caught", any(
        "declares no number" in p for p in param_probe(
            bom=PBOM.replace("value: 31.2 kOhm, 1%", "value: an E192 resistor"))[1])))
    cases.append(("a vanished source figure is caught", any(
        "compared to nothing" in p for p in param_probe(
            bom=PBOM.replace("    notes: DCR 18.5 mOhm typ / 20.4 mOhm max\n",
                             ""))[1])))
    with _tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "mystery-benchmark"
        case.mkdir()
        (case / "netlist.cir").write_text(".param X=1\n", encoding="utf-8")
        (case / "parts.yaml").write_text("parts: []\n", encoding="utf-8")
        untabled = []
        deck_param_problems(case, untabled)
    cases.append(("a benchmark with no parameter rule table is caught", any(
        "no deck-parameter rule table" in p for p in untabled)))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"sim-assert: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"sim-assert: self-test PASS: {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
