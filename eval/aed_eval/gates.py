"""Gate adapters: the thing a trial's emission is judged against.

THIS INDIRECTION IS THE POINT OF THE ISSUE. The harness has two consumers
about nine months apart with different gates. At M0 the bake-off judges
candidate grammars with a throwaway prototype parser. At AC5a the gate is
the real `aed check` plus export, which does not exist yet. Writing the
harness against a concrete `aed check` today would guarantee a rewrite when
that day comes, and "reused verbatim by the AC5a gate run - build once" is
the requirement.

So a gate is anything that can look at emitted source and return a verdict
plus diagnostics. Three implementations ship:

  CallableGate  - in-process; wraps a prototype parser (M0 bake-off) or a
                  test double.
  CommandGate   - subprocess; how `aed check` plugs in later with no change
                  to the protocol, results, or statistics.
  ReplayGate    - returns recorded verdicts, so a whole run replays offline
                  in CI with no compiler and no API spend.

DIAGNOSTIC QUALITY IS MEASURED, NOT ASSUMED. P2 says feedback quality is the
repair-loop bottleneck, so GateResult keeps structured diagnostics rather
than a pass/fail bit: a bare FAIL gives the loop nothing to converge on, and
a harness that discarded the diagnostics could not tell a good gate from a
bad one.
"""

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Diagnostic:
    """One structured diagnostic, shaped after the A1 contract."""

    code: str
    message: str
    span: dict | None = None
    params: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResult:
    passed: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Which stage decided the verdict: a parse failure and an export failure
    # are very different signals about a grammar.
    stage: str = "check"
    exit_code: int | None = None
    stderr_excerpt: str | None = None

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "stage": self.stage,
            "exit_code": self.exit_code,
            "diagnostics": [d.as_dict() for d in self.diagnostics],
            "diagnostic_count": len(self.diagnostics),
            "stderr_excerpt": self.stderr_excerpt,
        }


class CallableGate:
    """Wrap a Python callable `fn(source: str) -> GateResult`."""

    def __init__(self, fn, name: str, version: str = "0"):
        self._fn = fn
        self.name = name
        self.version = version

    def check(self, source: str, workdir: Path | None = None) -> GateResult:
        return self._fn(source)

    def identity(self) -> dict:
        return {"kind": "callable", "name": self.name, "version": self.version}


class CommandGate:
    """Run an external command over a written source file.

    This is the adapter `aed check` will use. It expects the A1 diagnostic
    contract — newline-delimited JSON objects on stdout — and treats a
    non-zero exit as failure.

    NEVER TRUSTS EXIT 0 ALONE: a zero exit accompanied by error-severity
    diagnostics is reported as a failure, matching the posture V4 takes with
    ngspice. A tool that exits 0 while emitting errors is a tool whose exit
    code cannot be believed, and silently accepting it would let a broken
    gate pass every trial.
    """

    def __init__(
        self,
        argv: list[str],
        name: str,
        version: str = "unknown",
        source_filename: str = "design.aed",
        timeout_s: int = 120,
        stage: str = "check",
    ):
        self.argv = argv
        self.name = name
        self.version = version
        self.source_filename = source_filename
        self.timeout_s = timeout_s
        # Which pipeline stage this command represents. Load-bearing: a
        # parse failure and an export failure say very different things
        # about a grammar, and a harness that labelled both "check" would
        # make the bake-off unable to tell them apart.
        self.stage = stage

    def check(self, source: str, workdir: Path | None = None) -> GateResult:
        if workdir is None:
            raise ValueError("CommandGate requires a workdir to write the source into")
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        path = workdir / self.source_filename
        path.write_text(source, encoding="utf-8")

        argv = [arg.replace("{source}", str(path)) for arg in self.argv]
        try:
            proc = subprocess.run(
                argv,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return GateResult(
                passed=False,
                stage=f"{self.stage}:timeout",
                exit_code=None,
                stderr_excerpt=f"gate exceeded {self.timeout_s}s",
            )
        except FileNotFoundError as exc:
            return GateResult(
                passed=False,
                stage=f"{self.stage}:gate-unavailable",
                stderr_excerpt=str(exc),
            )

        diagnostics = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            diagnostics.append(
                Diagnostic(
                    code=str(obj.get("code", "UNKNOWN")),
                    message=str(obj.get("message", "")),
                    span=obj.get("span"),
                    params=obj.get("params", {}) or {},
                )
            )

        has_errors = any(
            str(d.params.get("severity", "error")).lower() == "error" for d in diagnostics
        )
        passed = proc.returncode == 0 and not has_errors

        return GateResult(
            passed=passed,
            diagnostics=diagnostics,
            stage=self.stage,
            exit_code=proc.returncode,
            stderr_excerpt=(proc.stderr or "")[:2000] or None,
        )

    def identity(self) -> dict:
        return {
            "kind": "command",
            "name": self.name,
            "version": self.version,
            "stage": self.stage,
            "argv": self.argv,
        }


class CompositeGate:
    """Run several gates in order as one pipeline stage-set.

    AC5a's bar is passing "compile/type-check/export gates" — plural. If
    `aed` ends up exposing those as separate invocations rather than one
    command, a single-command gate cannot express the bar at all, and the
    "reused verbatim by the AC5a gate run" promise would quietly fail at
    exactly the moment it was supposed to pay off. This composes them.

    SHORT-CIRCUITS ON FIRST FAILURE, deliberately. Running export against a
    design that failed type-checking produces cascade noise, and P2 makes
    diagnostic quality the thing the repair loop converges on — feeding the
    model a pile of downstream errors caused by one upstream mistake makes
    the loop worse, not better. The failing stage's name travels out on
    GateResult.stage, so a bake-off can still distinguish a grammar that
    fails to parse from one that parses and fails to export.
    """

    def __init__(self, stages: list, name: str = "pipeline"):
        if not stages:
            raise ValueError("a composite gate needs at least one stage")
        self.stages = stages
        self.name = name

    def check(self, source: str, workdir: Path | None = None) -> GateResult:
        passed_stages = []
        for gate in self.stages:
            result = gate.check(source, workdir)
            if not result.passed:
                # Record what already succeeded, so a failure late in the
                # pipeline is distinguishable from one at the first hurdle.
                result.stage = (
                    f"{result.stage} (after {', '.join(passed_stages)})"
                    if passed_stages
                    else result.stage
                )
                return result
            passed_stages.append(result.stage)
        return GateResult(
            passed=True,
            stage=" -> ".join(passed_stages),
            exit_code=0,
        )

    def identity(self) -> dict:
        return {
            "kind": "composite",
            "name": self.name,
            "stages": [g.identity() for g in self.stages],
        }


class ReplayGate:
    """Replay recorded gate verdicts in order.

    Lets a full run be re-executed from a transcript with no compiler
    present, which is what makes the harness testable in CI. Running past
    the end of the recording is an error rather than a default verdict: a
    replay that silently invented a result would make a regression in the
    protocol invisible.
    """

    def __init__(self, recorded: list[dict], name: str = "replay"):
        self._recorded = list(recorded)
        self._cursor = 0
        self.name = name

    def check(self, source: str, workdir: Path | None = None) -> GateResult:
        if self._cursor >= len(self._recorded):
            raise IndexError(
                "replay transcript exhausted: the protocol asked for more gate "
                "invocations than were recorded. The recording and the protocol "
                "have diverged; re-record rather than padding the transcript."
            )
        entry = self._recorded[self._cursor]
        self._cursor += 1
        return GateResult(
            passed=bool(entry["passed"]),
            diagnostics=[
                Diagnostic(
                    code=d.get("code", "UNKNOWN"),
                    message=d.get("message", ""),
                    span=d.get("span"),
                    params=d.get("params", {}) or {},
                )
                for d in entry.get("diagnostics", [])
            ],
            stage=entry.get("stage", "check"),
            exit_code=entry.get("exit_code"),
        )

    def identity(self) -> dict:
        return {"kind": "replay", "name": self.name, "entries": len(self._recorded)}
