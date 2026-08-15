"""Plug the prototypes into the AC5 harness as gates.

AMB-31 built the harness "against gate and model adapters so the syntax
bake-off and the later AC5a gate run share one rig", and its README records
that "the bake-off's candidate-grammar parsers are AMB-32's scope. They plug
in as `CallableGate` or `CommandGate`." This is that plug.

The gate is a PIPELINE, not a single verdict, and deliberately so. AC5a's bar
is "compile/type-check/export gates" — plural — and `CompositeGate` short-
circuits on the first failure with the failing stage's name on the result. So
a grammar that fails to parse stays distinguishable from one that parses and
then describes the wrong circuit, which is the distinction the bake-off is
made of:

    parse     the source is a well-formed design in this grammar
    netlist   the design it describes is the one that was asked for

Without the second stage the measurement would be "did it parse", and a model
that emitted a syntactically perfect resistor divider instead of a 555 blinker
would score a pass.
"""

import sys

from .arms import Arm
from .diagnostics import ParseFailure
from .model import REPO_ROOT, DesignModel, diff

sys.path.insert(0, str(REPO_ROOT / "eval"))


def _harness():
    from aed_eval.gates import CallableGate, CompositeGate, Diagnostic, GateResult

    return CallableGate, CompositeGate, Diagnostic, GateResult


def _to_harness_diagnostics(diagnostics, Diagnostic):
    """Carry our structured diagnostics across into the harness's shape.

    Severity travels in `params` AND at the top level because A1 does not pin
    down which one a tool uses, and `CommandGate` reads both — a gate that
    filled in only one would look clean to half the harness.
    """
    return [
        Diagnostic(
            code=d.code,
            message=d.message,
            span=None if d.span is None else d.span.as_dict(),
            params={**d.params, "severity": d.severity, **({"fixit": d.fixit} if d.fixit else {})},
            top_level_severity=d.severity,
        )
        for d in diagnostics
    ]


def parse_gate(arm: Arm, variant: str = "inferred"):
    """Stage 1: does this source parse as a design in this grammar?"""
    CallableGate, _, Diagnostic, GateResult = _harness()

    def check(source: str) -> GateResult:
        try:
            arm.parse(source, variant)
        except ParseFailure as failure:
            return GateResult(
                passed=False,
                diagnostics=_to_harness_diagnostics(failure.diagnostics, Diagnostic),
                stage="parse",
                exit_code=1,
            )
        except RecursionError:
            # Reported rather than propagated: a prototype that overflows on
            # adversarial input is a defect in the prototype, and a trial that
            # died with a traceback would be scored as a harness failure
            # instead of as the grammar's problem.
            return GateResult(
                passed=False,
                diagnostics=[
                    Diagnostic(
                        code=f"{arm.code_prefix}9000",
                        message="the prototype parser exhausted the Python stack",
                        params={"severity": "error"},
                        top_level_severity="error",
                    )
                ],
                stage="parse:crash",
                exit_code=1,
            )
        return GateResult(passed=True, stage="parse", exit_code=0)

    return CallableGate(check, name=f"{arm.key}:parse", version="prototype-0")


def netlist_gate(arm: Arm, reference: DesignModel, variant: str = "inferred"):
    """Stage 2: is the design it describes the one that was asked for?"""
    CallableGate, _, Diagnostic, GateResult = _harness()

    def check(source: str) -> GateResult:
        try:
            parsed = arm.parse(source, variant)
        except (ParseFailure, RecursionError):
            # Stage 1 owns this verdict. Reaching here means the pipeline was
            # assembled without it, so say that rather than reporting a
            # netlist mismatch for a file that never parsed.
            return GateResult(
                passed=False,
                diagnostics=[
                    Diagnostic(
                        code=f"{arm.code_prefix}9001",
                        message="source does not parse; run the parse stage first",
                        params={"severity": "error"},
                        top_level_severity="error",
                    )
                ],
                stage="netlist:unreachable",
                exit_code=1,
            )
        differences = diff(reference, parsed)
        if differences:
            return GateResult(
                passed=False,
                diagnostics=[
                    Diagnostic(
                        code=f"{arm.code_prefix}8000",
                        message=note,
                        params={"severity": "error", "kind": "netlist-mismatch"},
                        top_level_severity="error",
                    )
                    for note in differences
                ],
                stage="netlist",
                exit_code=1,
            )
        return GateResult(passed=True, stage="netlist", exit_code=0)

    return CallableGate(check, name=f"{arm.key}:netlist", version="prototype-0")


def bakeoff_gate(arm: Arm, reference: DesignModel, variant: str = "inferred"):
    """The gate an AC5-protocol trial is judged by: parse, then netlist."""
    _, CompositeGate, _, _ = _harness()
    return CompositeGate(
        [parse_gate(arm, variant), netlist_gate(arm, reference, variant)],
        name=f"{arm.key}:{variant}",
    )


def trial_config(design_id: str, arm: Arm, variant: str = "inferred"):
    """A `TrialConfig` for one arm, with the arm's own language card as context.

    The card is the model-facing context an AC5 trial gets, so each candidate
    is taught its own grammar and nothing else. Iteration semantics are left
    at the strict reading and stated in the record; AMB-119 is open on which
    reading AC5 actually means.
    """
    from aed_eval.protocol import TrialConfig

    return TrialConfig(
        benchmark_id=f"{design_id}:{arm.key}:{variant}",
        task_prompt=(
            f"Emit the design `{design_id}` in the language described by the "
            "context above. Return one fenced code block containing the whole "
            "file and nothing else."
        ),
        system_context=arm.language_card(),
        max_iterations=3,
        iteration_semantics="total_write_check_cycles",
        token_budget=150_000,
    )
