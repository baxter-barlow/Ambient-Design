"""The AC5 trial protocol: emit, check, repair, judge.

AC5a states the bar as: a pinned frontier model, given ONLY the <=12K-token
A4 context, produces design (a) passing compile/type-check/export "within
<=3 repair iterations (1 iteration = one write + one `aed check`) and <=150K
tokens, in >=7/10 independent trials".

A SPEC AMBIGUITY THIS MODULE MAKES EXPLICIT RATHER THAN GUESSES AT.
"<=3 repair iterations" and "1 iteration = one write + one check" do not
determine the same budget. Two readings survive:

  total_write_check_cycles  - 3 write+check cycles in total, i.e. the first
                              emission plus at most 2 repairs.
  initial_plus_repairs      - the first emission, plus 3 further repair
                              cycles, i.e. 4 write+check cycles.

The second is roughly 33% more generous and would make a marginal grammar
look better. Rather than pick silently, both are expressible, the STRICTER
one is the default, and the choice is recorded in every result so no run's
numbers can be compared against another's under a different reading. The
requirements document should settle this; until it does, the strict reading
is the safe one because it cannot manufacture a pass.

BUDGETS ARE CONJUNCTIVE. A trial passes only if the gate passed AND the
trial stayed inside both the iteration budget and the 150K token budget. A
run that passed on iteration 3 having spent 200K tokens is a failure, and
recording it as a pass with a footnote would quietly move the bar.

NO RETRIES. A failed API call fails its trial. Retrying until a trial
succeeds is the same "retry to green" pathology the project prohibits for
simulation, and it would bias the pass rate that AC5a gates on.
"""

import hashlib
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

from .gates import GateResult
from .models import HarnessIntegrityError, ModelResponse

ITERATION_SEMANTICS = ("total_write_check_cycles", "initial_plus_repairs")

# Matches a fenced code block, optionally tagged with a language.
_FENCE = re.compile(r"```[A-Za-z0-9_.-]*\n(.*?)```", re.DOTALL)


def extract_source(text: str) -> str | None:
    """Pull the emitted design out of a model response.

    Returns the LAST COMPLETE fenced block: models commonly quote the
    failing snippet before presenting the corrected file, so taking the
    first block would grade the wrong artifact.

    Returns None when there is no usable block. Two cases:

    1. No fenced block at all — the model answered in prose. A real
       emission failure, recorded as one, never silently treated as the
       whole response body.

    2. An UNTERMINATED trailing fence, which means the response hit the
       token limit mid-block. This case is the subtle one: the truncated
       reply typically still contains an earlier, complete, deliberately-
       quoted BROKEN snippet, so "last complete block" would happily grade
       the model's quotation of its own bug and score a truncation as a
       content failure. Since a truncated emission is a budget problem
       rather than a language problem, conflating them would quietly bias
       the bake-off against whichever grammar is more verbose — precisely
       the thing being measured.
    """
    if text.count("```") % 2 == 1:
        return None
    blocks = _FENCE.findall(text)
    if not blocks:
        return None
    return blocks[-1].strip("\n")


@dataclass
class TrialConfig:
    benchmark_id: str
    task_prompt: str
    system_context: str
    max_iterations: int = 3
    iteration_semantics: str = "total_write_check_cycles"
    token_budget: int = 150_000
    source_filename: str = "design.aed"

    def __post_init__(self):
        if self.iteration_semantics not in ITERATION_SEMANTICS:
            raise ValueError(
                f"iteration_semantics must be one of {ITERATION_SEMANTICS}, "
                f"got {self.iteration_semantics!r}"
            )
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")

    @property
    def max_cycles(self) -> int:
        """Write+check cycles permitted, under the configured reading."""
        if self.iteration_semantics == "total_write_check_cycles":
            return self.max_iterations
        return self.max_iterations + 1

    def as_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "max_iterations": self.max_iterations,
            "iteration_semantics": self.iteration_semantics,
            "max_write_check_cycles": self.max_cycles,
            "token_budget": self.token_budget,
        }


@dataclass
class Iteration:
    index: int
    response: ModelResponse
    source_extracted: bool
    gate: GateResult | None
    cumulative_tokens: int

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "response": self.response.as_dict(),
            "source_extracted": self.source_extracted,
            "gate": self.gate.as_dict() if self.gate else None,
            "cumulative_tokens": self.cumulative_tokens,
        }


@dataclass
class TrialResult:
    seed: int
    passed: bool
    outcome: str
    iterations: list[Iteration] = field(default_factory=list)
    total_tokens: int = 0
    error: str | None = None

    @property
    def cycles_used(self) -> int:
        return len(self.iterations)

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "passed": self.passed,
            "outcome": self.outcome,
            "cycles_used": self.cycles_used,
            "total_tokens": self.total_tokens,
            "error": self.error,
            "iterations": [i.as_dict() for i in self.iterations],
        }


def build_repair_message(gate: GateResult, max_diagnostics: int = 20) -> str:
    """The feedback the model gets after a failed check.

    P2 makes this load-bearing: repair-loop convergence is what the language
    is optimised for, and a bare "it failed" gives the loop nothing to work
    with. Structured diagnostics are passed through with their codes and
    spans intact.

    The diagnostic list is capped and the truncation is STATED. Silently
    dropping diagnostics would let a run's difficulty depend on an invisible
    limit, and telling the model the list was cut is strictly more useful
    than letting it assume it saw everything.
    """
    if not gate.diagnostics:
        detail = (
            f"The check failed at stage '{gate.stage}' with no structured "
            "diagnostics. Treat this as an unexplained failure."
        )
        if gate.stderr_excerpt:
            detail += f"\n\nStandard error:\n{gate.stderr_excerpt}"
        return detail

    shown = gate.diagnostics[:max_diagnostics]
    lines = [f"The check failed with {len(gate.diagnostics)} diagnostic(s)."]
    if len(gate.diagnostics) > len(shown):
        lines.append(
            f"Showing the first {len(shown)}; {len(gate.diagnostics) - len(shown)} "
            "further diagnostic(s) were omitted."
        )
    lines.append("")
    for d in shown:
        location = ""
        if d.span:
            line = d.span.get("line")
            col = d.span.get("column")
            if line is not None:
                location = f" at line {line}" + (f", column {col}" if col is not None else "")
        lines.append(f"[{d.code}]{location}: {d.message}")
        if d.params:
            # Rendered as key-sorted JSON, never as a Python dict repr.
            # The repr's key order follows insertion order, so an identical
            # diagnostic that has been round-tripped through JSON renders
            # differently, which changes the prompt and therefore changes
            # the run. The replay digest check caught exactly that.
            lines.append(f"    parameters: {json.dumps(d.params, sort_keys=True)}")
    lines.append("")
    lines.append("Emit the complete corrected file in a single fenced code block.")
    return "\n".join(lines)


def run_trial(config: TrialConfig, model, gate, seed: int, workdir=None) -> TrialResult:
    """Run one independent AC5 trial."""
    messages = [{"role": "user", "content": config.task_prompt}]
    iterations: list[Iteration] = []
    cumulative = 0

    for cycle in range(config.max_cycles):
        try:
            response = model.complete(config.system_context, messages)
        except HarnessIntegrityError:
            # A broken instrument, not a failed measurement. Replay
            # divergence and transcript exhaustion mean the recording no
            # longer describes this protocol, so every number downstream
            # would be for a run that never happened. Recording that as an
            # ordinary trial failure made the CI replay job incapable of
            # failing at all.
            raise
        except Exception as exc:  # noqa: BLE001 - recorded, never retried
            return TrialResult(
                seed=seed,
                passed=False,
                outcome="model_error",
                iterations=iterations,
                total_tokens=cumulative,
                error=f"{type(exc).__name__}: {exc}",
            )

        cumulative += response.usage.total
        # A max_tokens stop means the reply was cut off. Even when the
        # fences happen to balance - truncation after a complete block -
        # what follows was never written, so grading the last complete
        # block grades a file the model did not propose. `stop_reason` was
        # recorded but never read, which let a truncation be scored as a
        # PASS and biased the headline rate upward.
        truncated = str(response.stop_reason or "").lower() == "max_tokens"
        source = None if truncated else extract_source(response.text)

        if source is None:
            iterations.append(
                Iteration(cycle, response, False, None, cumulative)
            )
            # An unparseable response still consumed budget and still counts
            # as a cycle; the model is told what went wrong and may retry
            # within the remaining budget.
            messages.append({"role": "assistant", "content": response.text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "No fenced code block was found in that response. Emit the "
                        "complete file in a single fenced code block and nothing else."
                    ),
                }
            )
            if cumulative > config.token_budget:
                return TrialResult(
                    seed, False, "token_budget_exceeded", iterations, cumulative
                )
            continue

        gate_result = gate.check(source, workdir)
        iterations.append(Iteration(cycle, response, True, gate_result, cumulative))

        # Conjunctive budget: passing the gate is necessary, not sufficient.
        if cumulative > config.token_budget:
            return TrialResult(
                seed, False, "token_budget_exceeded", iterations, cumulative
            )

        if gate_result.passed:
            return TrialResult(seed, True, "passed", iterations, cumulative)

        messages.append({"role": "assistant", "content": response.text})
        messages.append({"role": "user", "content": build_repair_message(gate_result)})

    return TrialResult(
        seed, False, "iteration_budget_exhausted", iterations, cumulative
    )


def run_arm(config: TrialConfig, model, gate_factory, seeds: list[int], workdir=None) -> dict:
    """Run one arm of the comparison over a fixed seed set.

    `gate_factory` is a zero-argument callable returning a fresh gate per
    trial, so a stateful gate (notably ReplayGate's cursor) cannot leak
    state between trials that are required to be independent.

    THE SEED SET IS SHARED ACROSS ARMS ON PURPOSE. Running both arms on the
    same seeds makes the comparison paired, and the paired McNemar test
    detects a real difference at a much smaller n than the unpaired one. At
    roughly 150K tokens per trial that is a direct saving, not a nicety.
    """
    trials = []
    for seed in seeds:
        # Each trial gets its own directory. A gate that writes artifacts
        # would otherwise leave them where the next trial can see them,
        # which quietly makes "independent trials" untrue.
        trial_dir = Path(workdir) / f"trial-{seed}" if workdir else None
        trials.append(run_trial(config, model, gate_factory(), seed, trial_dir))
    successes = sum(1 for t in trials if t.passed)
    return {
        "config": config.as_dict(),
        # Pin the model-facing context this arm actually ran with. AC5a is
        # gated on "given ONLY the <=12K-token A4 context", and a record
        # that pins neither the context nor a hash of it leaves that clause
        # unverifiable forever after the run.
        "context": {
            "system_context_sha256": "sha256:"
            + hashlib.sha256(config.system_context.encode("utf-8")).hexdigest(),
            "task_prompt_sha256": "sha256:"
            + hashlib.sha256(config.task_prompt.encode("utf-8")).hexdigest(),
            "system_context_chars": len(config.system_context),
            "task_prompt_chars": len(config.task_prompt),
        },
        "seeds": list(seeds),
        "trials": [t.as_dict() for t in trials],
        "successes": successes,
        "trial_count": len(trials),
        "total_tokens": sum(t.total_tokens for t in trials),
        "outcomes": {
            outcome: sum(1 for t in trials if t.outcome == outcome)
            for outcome in sorted({t.outcome for t in trials})
        },
    }


def pair_discordance(arm_a: dict, arm_b: dict) -> tuple[int, int]:
    """Discordant counts by seed, for the paired test.

    Returns (a_only, b_only): seeds where exactly one arm passed. Raises if
    the arms did not run the same seeds.

    PAIRING IS ONLY VALID WITH A REAL BLOCKING FACTOR, AND MATCHING SEED
    NUMBERS ARE NOT ONE. A paired test assumes trial i of arm A and trial i
    of arm B share something that makes their outcomes correlated. In the
    AC5 protocol as specified, every trial of an arm runs the SAME prompt on
    the SAME benchmark and differs only by the provider's sampling
    randomness — and the seed here labels a trial, it does not seed the
    model. So trial 3 of two arms share nothing but an index, the
    discordant counts carry no blocking information, and McNemar would
    report a precision the design does not earn.

    Pairing becomes legitimate the moment a genuine shared factor exists —
    several distinct benchmark designs, say, with both arms run over each —
    because then trial i really does mean "the same design, both arms".
    That is why `build_run_record` requires the factor to be NAMED before it
    will pair, rather than inferring it from the seed lists lining up.
    """
    seeds_a = [t["seed"] for t in arm_a["trials"]]
    seeds_b = [t["seed"] for t in arm_b["trials"]]
    if seeds_a != seeds_b:
        raise ValueError(
            "arms did not run the same seed set, so results cannot be paired: "
            f"{seeds_a} vs {seeds_b}"
        )
    pass_a = {t["seed"]: t["passed"] for t in arm_a["trials"]}
    pass_b = {t["seed"]: t["passed"] for t in arm_b["trials"]}
    a_only = sum(1 for s in seeds_a if pass_a[s] and not pass_b[s])
    b_only = sum(1 for s in seeds_a if pass_b[s] and not pass_a[s])
    return a_only, b_only
