#!/usr/bin/env python3
"""Generate the demo replay transcript by actually running the protocol.

The transcript is NOT hand-written. A hand-written one would drift from the
protocol the moment either changed, and the request digests it carries would
be fiction. This drives the real protocol with a scripted model, captures
what the protocol actually asked for, and writes that out — so the recording
is correct by construction and `rhoform_eval replay` reproduces it exactly.

The scenario is synthetic but shaped like a real bake-off arm: two arms over
a shared seed set, a mix of first-shot passes and repair-loop recoveries, one
response with no fenced code block, and two outright failures per arm. It
exists to exercise every path in the protocol, not to represent any real
measurement — nothing here is evidence about any model or grammar.

    python3 eval/fixtures/make_demo_transcript.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rhoform_eval.gates import Diagnostic, GateResult  # noqa: E402
from rhoform_eval.models import ModelResponse, Usage, request_digest  # noqa: E402
from rhoform_eval.protocol import TrialConfig, run_trial  # noqa: E402

SEEDS = list(range(1, 11))

SYSTEM_CONTEXT = (
    "You are emitting a circuit description in a small declarative DSL. "
    "Nouns: module, interface, component. Instantiate with `new`. Connect "
    "with `~`. Blocks are newline and indentation delimited."
)
TASK_PROMPT = (
    "Emit a 9 V 555 astable blinker: a 555 timer, timing resistors and "
    "capacitor, an LED with a ballast resistor. Assert the oscillation "
    "frequency is between 0.93 Hz and 1.05 Hz."
)

GOOD_SOURCE = """module Blinker:
    u1 = new NE555
    ra = new Resistor(resistance=100kohm)
    rb = new Resistor(resistance=680kohm)
    ct = new Capacitor(capacitance=1uF)
    assert frequency(u1.OUT) within 0.93Hz to 1.05Hz
"""

BAD_SOURCE = """module Blinker:
    u1 = new NE555
    ra = new Resistor(100kohm)
    assert frequency(u1.OUT) == 1Hz
"""

FAIL_DIAGS = [
    Diagnostic(
        code="RHO0201",
        message="positional argument to component constructor; parameters are named",
        span={"line": 3, "column": 22},
        params={"severity": "error", "parameter": "resistance"},
    ),
    Diagnostic(
        code="RHO0410",
        message="assertion uses '==' on a dimensioned quantity; use a tolerance interval",
        span={"line": 4, "column": 5},
        params={"severity": "error", "suggested": "within ... to ..."},
    ),
]


def scripted_arm(pass_seeds, first_shot_seeds, no_fence_seeds):
    """Build a per-seed script: list of (text, gate_passed) per cycle."""

    def script_for(seed):
        steps = []
        if seed in no_fence_seeds:
            # A response with no fenced block at all: exercises the
            # emission-failure path, costs a cycle, then recovers.
            steps.append(("Here is the design, described in prose only.", None))
        if seed in pass_seeds:
            if seed in first_shot_seeds and seed not in no_fence_seeds:
                steps.append((f"```rhoform\n{GOOD_SOURCE}```", True))
            else:
                steps.append((f"```rhoform\n{BAD_SOURCE}```", False))
                steps.append((f"```rhoform\n{GOOD_SOURCE}```", True))
        else:
            steps.append((f"```rhoform\n{BAD_SOURCE}```", False))
            steps.append((f"```rhoform\n{BAD_SOURCE}```", False))
            steps.append((f"```rhoform\n{BAD_SOURCE}```", False))
        return steps

    return {seed: script_for(seed) for seed in SEEDS}


class RecordingModel:
    """Returns scripted text while recording the exact request digest."""

    def __init__(self, script):
        self.script = script
        self.cursor = 0
        self.turns = []

    def complete(self, system, messages):
        text, _ = self.script[self.cursor]
        self.cursor += 1
        usage = Usage(input_tokens=1800 + 400 * (self.cursor - 1), output_tokens=320)
        self.turns.append(
            {
                "request_digest": request_digest(system, messages),
                "text": text,
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                },
                "stop_reason": "end_turn",
            }
        )
        return ModelResponse(text=text, usage=usage, stop_reason="end_turn")

    def identity(self):
        return {"kind": "scripted"}


class RecordingGate:
    """Returns scripted verdicts while recording them."""

    def __init__(self, script):
        self.script = script
        self.cursor = 0
        self.results = []

    def check(self, source, workdir=None):
        # Advance to the next step that actually reaches the gate; steps
        # with a None verdict never got here (no fenced block).
        while self.script[self.cursor][1] is None:
            self.cursor += 1
        passed = self.script[self.cursor][1]
        self.cursor += 1
        result = GateResult(
            passed=passed,
            diagnostics=[] if passed else list(FAIL_DIAGS),
            stage="check",
            exit_code=0 if passed else 1,
        )
        self.results.append(result.as_dict())
        return result

    def identity(self):
        return {"kind": "scripted"}


def build_arm(pass_seeds, first_shot_seeds, no_fence_seeds, config):
    scripts = scripted_arm(pass_seeds, first_shot_seeds, no_fence_seeds)
    turns, gate_results = [], []
    for seed in SEEDS:
        model = RecordingModel(scripts[seed])
        gate = RecordingGate(scripts[seed])
        run_trial(config, model, gate, seed)
        turns.extend(model.turns)
        gate_results.extend(gate.results)
    return {"turns": turns, "gate_results": gate_results}


def main() -> int:
    config = TrialConfig(
        benchmark_id="blinker-555",
        task_prompt=TASK_PROMPT,
        system_context=SYSTEM_CONTEXT,
        max_iterations=3,
        iteration_semantics="total_write_check_cycles",
        token_budget=150_000,
    )

    transcript = {
        "run_id": "demo-replay-0",
        "purpose": "harness demonstration and offline regression fixture",
        "benchmark_id": "blinker-555",
        "model": "scripted-demo-model",
        "sampling": {"temperature": 0.0, "max_tokens": 4096},
        "seeds": SEEDS,
        "task_prompt": TASK_PROMPT,
        "system_context": SYSTEM_CONTEXT,
        "max_iterations": 3,
        "iteration_semantics": "total_write_check_cycles",
        "token_budget": 150_000,
        "primary_arm": "grammar_a",
        "baseline_arm": "starlark_baseline",
        "notes": (
            "SYNTHETIC FIXTURE. The responses and verdicts are scripted to "
            "exercise every path in the protocol - first-shot pass, repair-loop "
            "recovery, a response with no fenced code block, and exhaustion of "
            "the iteration budget. It is NOT a measurement, and no conclusion "
            "about any model or grammar may be drawn from it."
        ),
        "arms": {
            "grammar_a": build_arm(
                pass_seeds={1, 2, 3, 4, 5, 6, 7, 8},
                first_shot_seeds={1, 2, 3, 4},
                no_fence_seeds={5},
                config=config,
            ),
            "starlark_baseline": build_arm(
                pass_seeds={1, 2, 3, 4, 5, 6},
                first_shot_seeds={1, 2},
                no_fence_seeds=set(),
                config=config,
            ),
        },
    }

    out = Path(__file__).resolve().parent / "demo-replay.json"
    out.write_text(
        json.dumps(transcript, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    total_turns = sum(len(a["turns"]) for a in transcript["arms"].values())
    print(f"wrote {out} ({total_turns} recorded model turns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
