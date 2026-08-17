#!/usr/bin/env python3
"""Derive benchmark (a)'s timing windows from the transcribed NE555 record.

WHY THIS EXISTS. The duty-cycle window was hand-derived four times and was
wrong four times, each time in a new way: the first omitted timing-pin bias
current entirely; the second modelled a negative-bias corner with no mechanism
and rounded out its own stated corner; the third halved the bias bound by an
argument about a datasheet guideline; and all three omitted the comparator
threshold tolerance, which `design.md` itself names as a dominant term.

The common cause is that every one was arithmetic done by hand against a
datasheet the repository does not transcribe. So this derives the windows
MECHANICALLY, from `parts/examples/ti-ne555p.part.json` — the values this
project actually stands behind — and prints both models, because the difference
between them is the thing four revisions kept eliding.

TWO MODELS, and they answer different questions.

  guaranteed   Every corner the part record permits: R, C and bias current, plus
               the comparator levels. The record's spread is NOT symmetric:
               the divider scale k runs 0.720..1.260, i.e. -28.0%/+26.0%, and
               "roughly +/-26%" quietly understated the side that WIDENS the
               window. The number printed is computed from the record, so it
               cannot drift from this comment again.

               THRES and TRIG are modelled as taps on ONE internal divider, so
               their errors are correlated. That is a MODELLING CHOICE, not a
               fact about the part. Under it t_low is invariant ONLY AT
               ib = 0 (ln2*RB*C = 0.47134 s at k = 0.72, 1.00, 1.26 alike);
               the model sweeps ib in [0, 250 nA], and at the top of that range
               t_low runs 0.446069 / 0.452858 / 0.456547 s across the same
               three k values -- a 2.35% spread. So the guaranteed duty spread
               is MOSTLY, not wholly, carried by t_high. An earlier revision of
               this docstring stated the invariance without the ib = 0
               qualifier, which made it false for the model this file
               implements. The real NE555's threshold
               spread is dominated by comparator input offset, which is
               INDEPENDENT between the two comparators. An earlier revision of
               this docstring asserted as fact that modelling them independently
               "overstates the spread further still"; the direction is not
               obvious and nothing here establishes it, so the claim is
               withdrawn rather than restated.

               This is the honest answer to "what will any conforming NE555 do",
               and it is far too wide to gate on: duty lands near [38, 71]%.
               That is a fact about the part, not a defect in the benchmark.

  typical      Passive tolerance and bias current at nominal comparator levels.
               This is what a real board with a typical part does, and what the
               rung-0 macromodel measures — its B-sources implement exactly the
               nominal divider and draw zero input current.

WHAT IS GATED. The `typical` model, and only it. The deck cannot measure the
guaranteed corners: it has no comparator tolerance, so an assertion against
them would be untestable by construction — a window nothing
can fail is not an assertion, which is the defect this repository has now found
in its own gates several times over.

The guaranteed range is published beside it as a design limit, explicitly not
gated, so nobody reads the narrow window as a claim about the part.

    python3 tests/benchmarks/derive-555-windows.py            # print both
    python3 tests/benchmarks/derive-555-windows.py --check    # gate the file
"""

import itertools
import json
import sys
from math import log
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "parts" / "examples" / "ti-ne555p.part.json"
ASSERTIONS = ROOT / "benchmarks" / "blinker-555" / "assertions.yaml"

VCC = 9.0
RA, RA_TOL = 100e3, 0.01
RB, RB_TOL = 680e3, 0.01
C, C_TOL = 1e-6, 0.05


def _record():
    doc = json.loads(RECORD.read_text(encoding="utf-8"))
    ch = {p["name"]: (p.get("characteristics") or {}) for p in doc["pins"]}
    thr = ch["THRES"]["threshold_voltage_level"]
    trg = ch["TRIG"]["trigger_voltage_level"]
    spec_vcc = thr["conditions"]["vcc"]["typ"]
    # BOTH timing-node currents. TRIG and THRES are the same node in an
    # astable, so both load the capacitor; the model read only THRES and the
    # docstring claimed it covered "bias current". TRIG's max is specified at
    # `vtrig: 0 V` -- an operating point the timing node never sits at while
    # oscillating -- so the record does NOT bound TRIG at the relevant point.
    # That is reported, not silently dropped: see `unbounded` below.
    trig_i = ch["TRIG"]["input_current"]
    trig_at = (trig_i.get("conditions") or {}).get("vtrig", {})
    return {
        "ib_max": ch["THRES"]["input_current"]["max"] * 1e-9,
        "trig_i_max": trig_i["max"] * 1e-6,
        "trig_conditions": trig_at,
        # As a multiple of the nominal 2/3 and 1/3 ratios. The tighter of the
        # two bounds the common divider scale, since one divider produces both.
        "k_lo": max(thr["min"] / spec_vcc / (2 / 3), trg["min"] / spec_vcc / (1 / 3)),
        "k_hi": min(thr["max"] / spec_vcc / (2 / 3), trg["max"] / spec_vcc / (1 / 3)),
    }


def _halves(ra, rb, c, ib, k):
    v_trig, v_thr = k * VCC / 3, k * 2 * VCC / 3
    high = (ra + rb) * c * log(
        (VCC - ib * (ra + rb) - v_trig) / (VCC - ib * (ra + rb) - v_thr)
    )
    low = rb * c * log((v_thr + ib * rb) / (v_trig + ib * rb))
    return high, low


def sweep(k_values, ib_values):
    duty = periods = None
    for ra, rb, c, ib, k in itertools.product(
        (RA * (1 - RA_TOL), RA * (1 + RA_TOL)),
        (RB * (1 - RB_TOL), RB * (1 + RB_TOL)),
        (C * (1 - C_TOL), C * (1 + C_TOL)),
        ib_values,
        k_values,
    ):
        high, low = _halves(ra, rb, c, ib, k)
        total = high + low
        d = 100 * high / total
        duty = (d, d) if duty is None else (min(duty[0], d), max(duty[1], d))
        periods = (total, total) if periods is None else (
            min(periods[0], total), max(periods[1], total))
    return duty, periods


def models():
    rec = _record()
    typical = sweep((1.0,), (0.0, rec["ib_max"]))
    guaranteed = sweep((rec["k_lo"], 1.0, rec["k_hi"]), (0.0, rec["ib_max"]))
    return {"typical": typical, "guaranteed": guaranteed, "record": rec}


def _fmt(model):
    (dlo, dhi), (tlo, thi) = model
    return {
        "duty": (dlo, dhi),
        "period": (tlo, thi),
        "frequency": (1 / thi, 1 / tlo),
    }


def main(argv):
    m = models()
    rec = m["record"]
    print(f"NE555 record: THRES bias max {rec['ib_max'] * 1e9:.0f} nA, "
          f"comparator divider scale {rec['k_lo']:.3f}-{rec['k_hi']:.3f}")
    for name in ("typical", "guaranteed"):
        f = _fmt(m[name])
        print(f"\n{name}:")
        print(f"  duty      {f['duty'][0]:8.3f} .. {f['duty'][1]:8.3f} %")
        print(f"  period    {f['period'][0]:8.4f} .. {f['period'][1]:8.4f} s")
        print(f"  frequency {f['frequency'][0]:8.4f} .. {f['frequency'][1]:8.4f} Hz")

    r = _record()
    print(f"\nTHRES input_current.max = {r['ib_max']*1e9:.0f} nA, modelled.")
    print(f"TRIG  input_current.max = {r['trig_i_max']*1e6:.1f} uA at "
          f"{r['trig_conditions']}, NOT modelled: TRIG and THRES are the same\n"
          "  node in an astable, but that figure is specified at a trigger\n"
          "  voltage the timing node never sits at while oscillating, so the\n"
          "  record does not bound this current at the operating point. The\n"
          "  bands below are therefore bounds on the MODEL, not on the part.")

    if "--check" not in argv:
        return 0

    # THE GATED WINDOWS, checked in BOTH directions. Previously this read the
    # file with re.search over raw text: it matched YAML comments, took only the
    # first match per unit, and so a decoy comment above the real window let
    # `[10.0 %, 11.0 %]` pass. It also implemented only half of what this
    # comment claimed -- the "must not claim to contain the guaranteed band"
    # half did not exist, so `[0.0 %, 160.0 %]`, a range a duty cycle cannot
    # leave, passed. Both halves are here now, over parsed YAML keyed by
    # assertion name.
    problems = []
    try:
        import yaml
    except ImportError as exc:
        print(f"derive-555: UNAVAILABLE: PyYAML is required: {exc}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(ASSERTIONS.read_text(encoding="utf-8"))
    by_name = {a.get("name"): a for a in (spec.get("assertions") or [])}
    typ, gtd = _fmt(m["typical"]), _fmt(m["guaranteed"])
    for key, name, unit in (
        ("duty", "duty_cycle_high", "%"),
        ("period", "osc_period", "s"),
        ("frequency", "osc_frequency", "Hz"),
    ):
        assertion = by_name.get(name)
        if assertion is None:
            problems.append(f"{ASSERTIONS.name} declares no assertion named {name!r}")
            continue
        raw = assertion.get("window")
        if not isinstance(raw, list) or len(raw) != 2:
            problems.append(f"{name}: no two-element `window:`")
            continue
        try:
            lo, hi = (float(str(v).split()[0]) for v in raw)
        except ValueError:
            problems.append(f"{name}: window {raw!r} is not two numbers")
            continue
        want_lo, want_hi = typ[key]
        if lo > want_lo or hi < want_hi:
            problems.append(
                f"{key} window [{lo}, {hi}] {unit} does not contain the typical "
                f"model [{want_lo:.4f}, {want_hi:.4f}]; the deck measures that "
                "model, so a window excluding it fails on a healthy board")
        # TOO WIDE is the direction that actually matters: a window wider than
        # the guaranteed band asserts less than the datasheet already
        # guarantees, so it can never fail on any conforming part.
        g_lo, g_hi = gtd[key]
        # PER SIDE. The conjunction only fired when BOTH bounds escaped, so a
        # one-sided vacuous window passed: duty [0.0, 55.8] and [53.3, 100.0]
        # each gate nothing in one direction and both returned 0. A window is a
        # regression check on the deck, so each bound has to be able to fail.
        for side, bound, guaranteed, worse in (
                ("lower", lo, g_lo, lo < g_lo),
                ("upper", hi, g_hi, hi > g_hi)):
            if worse:
                problems.append(
                    f"{key} window's {side} bound {bound} {unit} is outside the "
                    f"guaranteed band ({guaranteed:.4f}), so no conforming part "
                    "can fail on that side and the bound gates nothing. The "
                    "window is a regression check on the deck, not a restatement "
                    "of the datasheet.")
    if problems:
        for problem in problems:
            print(f"derive-555: FAIL: {problem}", file=sys.stderr)
        return 1
    print("\nderive-555: PASS: 3 window(s) contain the typical model and\n            are narrower than the guaranteed band.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
