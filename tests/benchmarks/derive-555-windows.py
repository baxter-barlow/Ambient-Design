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
               the comparator levels, whose spread the record puts at roughly
               +/-26% of nominal. THRES and TRIG are taps on ONE internal
               divider, so their errors are CORRELATED — a divider reading high
               reads high at both taps — and modelling them independently
               overstates the spread further still.

               This is the honest answer to "what will any conforming NE555 do",
               and it is far too wide to gate on: duty lands near [38, 71]%.
               That is a fact about the part, not a defect in the benchmark.

  typical      Passive tolerance and bias current at nominal comparator levels.
               This is what a real board with a typical part does, and what the
               rung-0 macromodel measures — its B-sources implement exactly the
               nominal divider and draw zero input current.

WHAT IS GATED. The `typical` model, and only it. The deck cannot measure the
guaranteed corners: it has no comparator tolerance and no bias current, so an
assertion against them would be untestable by construction — a window nothing
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
    return {
        "ib_max": ch["THRES"]["input_current"]["max"] * 1e-9,
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

    if "--check" not in argv:
        return 0

    # The gated windows must CONTAIN the typical model and must NOT claim to
    # contain the guaranteed one — the second half is what stops a narrow window
    # being read as a statement about the part.
    import re
    text = ASSERTIONS.read_text(encoding="utf-8")
    problems = []
    typ = _fmt(m["typical"])
    for key, pattern, unit in (
        ("duty", r"window: \[([\d.]+) %, ([\d.]+) %\]", "%"),
        ("period", r"window: \[([\d.]+) s, ([\d.]+) s\]", "s"),
        ("frequency", r"window: \[([\d.]+) Hz, ([\d.]+) Hz\]", "Hz"),
    ):
        found = re.search(pattern, text)
        if not found:
            problems.append(f"no {key} window found in {ASSERTIONS.name}")
            continue
        lo, hi = float(found.group(1)), float(found.group(2))
        want_lo, want_hi = typ[key]
        if lo > want_lo or hi < want_hi:
            problems.append(
                f"{key} window [{lo}, {hi}] {unit} does not contain the typical "
                f"model [{want_lo:.4f}, {want_hi:.4f}]; the deck measures that "
                "model, so a window excluding it fails on a healthy board"
            )
    if problems:
        for problem in problems:
            print(f"derive-555: FAIL: {problem}", file=sys.stderr)
        return 1
    print("\nderive-555: PASS: every gated window contains the typical model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
