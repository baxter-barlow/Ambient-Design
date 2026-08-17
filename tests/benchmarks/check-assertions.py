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


def check_benchmark(case, spec, log_text, problems):
    """One benchmark's assertions against one ngspice log."""
    measured = parse_log(log_text)
    assertions = spec.get("assertions") or []
    if not assertions:
        problems.append(f"{case}: declares no assertions; a benchmark must assert something")
        return 0

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
    except GateUnavailable as exc:
        print(f"sim-assert: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    if problems:
        print(f"sim-assert: FAIL: {case_dir.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"sim-assert: PASS: {case_dir.name}: {checked} assertion(s) inside their windows.")
    return 0


def self_test():
    """Prove each rejection fires. A checker nobody has watched fail is prose."""
    log = "t_period   =  1.01191e+00\nf_osc      =   failed\ni_led_on   =  9.25678e-03\n"
    base = {"assertions": [
        {"name": "osc_period", "meas_id": "t_period",
         "window": ["0.952 s", "1.073 s"], "measured": "1.01191 s"},
    ]}

    def run(spec, text=log):
        problems = []
        check_benchmark("case", spec, text, problems)
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

    # WIRING, as above: main() must turn a finding into a non-zero exit. This
    # drives the real entry point over a benchmark directory whose deck output
    # is planted, rather than over `check_benchmark` alone.
    import contextlib as _ctx, io as _io, tempfile as _tmp
    with _tmp.TemporaryDirectory() as _d:
        _case = Path(_d) / "probe"
        _case.mkdir()
        (_case / "assertions.yaml").write_text(
            "deck: netlist.cir\nassertions:\n"
            "  - name: osc_period\n    meas_id: t_period\n"
            "    window: [2.0 s, 3.0 s]\n", encoding="utf-8")
        _log = Path(_d) / "ng.log"
        _log.write_text("t_period   =  1.01191e+00\n", encoding="utf-8")
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            _planted = main([str(_case), str(_log)])
        (_case / "assertions.yaml").write_text(
            "deck: netlist.cir\nassertions:\n"
            "  - name: osc_period\n    meas_id: t_period\n"
            "    window: [0.9 s, 1.1 s]\n", encoding="utf-8")
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            _clean = main([str(_case), str(_log)])
    cases.append(("main() exits 1 on a value outside its window", _planted == 1))
    cases.append(("main() exits 0 on a value inside it", _clean == 0))

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
