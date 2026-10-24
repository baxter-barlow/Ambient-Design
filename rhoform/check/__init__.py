"""The static stage (M2): every check that needs a whole, elaborated design.

`check(design, context, sink)` runs after an error-free elaboration and
never after an elaboration error (spec 05 section 1). It reads the
in-memory ElaboratedDesign -- exact Decimals and every source fact, where
the IR has doubles -- through a CheckedDesign view, and a CheckContext that
holds everything else a check may read: the compile root's rhoform.lock and
the part records the design's picks name (L2b fills it; nothing more is
ever read, and nothing is written). It changes no IR byte and no hash.

THE PASSES run in a fixed order, each a module exposing NAME, OWNER (the
codeset whose ranges it reports in), IMPLEMENTED and
`run(model, analysis, report)`:

  parts       picks and part records                     (L2b)
  dimensions  T3/T4 quantity dimensions and the lint     (L1c)
  ground      GA passes 1-4, which the rest of T5 needs  (L2c)
  erc         T2 pin roles and L9b                       (L1b)
  domains     T5 origins, rails, envelopes, abs-max      (L3)
  budget      T10 current and power budgets              (L4)
  domains_refine  T5 sites that depend on current        (L4)
  assertions  the V1 static tier                         (L5a)

then the driver applies waivers (T6), raises the coverage summary and
flushes the findings. A pass reads only the Analysis slots earlier passes
set, and a defect is reported once, by the earliest pass that sees it;
later passes treat what it touches as unknown and record a row with the
reason `upstream-defect`. A pass that is not implemented yet still runs,
and its section records it as an actionable row, so an unimplemented
check is never a silent pass.
Until the assertions pass is implemented, the driver reports, in its
place, every declared static-tier assertion as RHO3553: a declared
assertion that cannot be measured gates (V1, amendment OD1).

`through` makes the run an AREA's, as the conformance suite's check leg
runs it: it names the last pass to run (or `model`, the model build
alone), and the coverage note then counts only the actionable rows of
`model` and of that pass's own section (the report keeps every row as
written). An area's stream therefore moves with its own pass's rows and
with the findings of the passes it runs, never with which other passes
are still stubs, nor with any pass after it. The command line never
passes `through`: it runs every pass, and its note counts every section.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckContext:
    """Everything a check reads besides the design. Built by
    `parts.load_context`: until L2b, that is the compile root alone."""

    root: Path | None = None
    lockfile: object | None = None
    parts: object | None = None


@dataclass
class Analysis:
    """The blackboard: one slot per pass, set by that pass alone and read
    only by later ones."""

    parts: object | None = None
    values: object | None = None
    ground: object | None = None
    erc: object | None = None
    domains: object | None = None
    budget: object | None = None
    assertions: object | None = None


from . import (assertions, budget, dimensions, domains,  # noqa: E402
               erc, ground, parts, waivers)
from .model import CheckedDesign  # noqa: E402
from .report import Report  # noqa: E402

PASSES = (parts, dimensions, ground, erc, domains, budget, budget.Refine,
          assertions)
MODEL = "model"
OWNER = "check"

# RHO3553's reason while no static-tier evaluator exists.
NO_STATIC_EVALUATOR = "this toolchain has no static-tier evaluator yet"


def pass_names() -> tuple[str, ...]:
    """`model`, then every pass's NAME, in the order they run."""
    return (MODEL,) + tuple(step.NAME for step in PASSES)


def check(design, context: CheckContext | None = None, sink=None, *,
          through: str | None = None):
    """Check one elaborated design: (Analysis, Report). Findings reach
    `sink` (a rhoform.diagnostics.Diagnostics) when one is given."""
    names = pass_names()
    scope = None if through is None else (MODEL, through)
    through = names[-1] if through is None else through
    if through not in names:
        raise ValueError(f"no pass is named {through!r}; the passes are "
                         f"{', '.join(names)}")
    model = CheckedDesign(design)
    report = Report(model)
    analysis = Analysis()
    report.open(MODEL, OWNER, True)
    for path in model.pinless_components():
        report.row(path, "no-data", "component-without-pins",
                   actionable=True)
    for step in PASSES[:names.index(through)]:
        report.open(step.NAME, step.OWNER, step.IMPLEMENTED)
        step.run(model, analysis, report)
        if not step.IMPLEMENTED:
            report.row("/", "not-implemented", "pass-not-implemented",
                       actionable=True)
            if step.NAME == assertions.NAME:
                # In the stub's place, so only a run that reaches the
                # assertions pass reports it.
                for assertion in model.static_assertions():
                    report.finding(
                        "RHO3553",
                        {"assertion": assertion.path,
                         "measurement": assertion.measurement,
                         "reason": NO_STATIC_EVALUATOR},
                        entity=assertion.path, tier="static")
    report.findings = waivers.apply(model, report.findings)
    report.summarize(OWNER, scope)
    if sink is not None:
        report.flush(sink)
    return analysis, report
