"""The one pipeline: load, elaborate, check.

Four callers composed these stages by hand -- the command line, the
conformance suite's elaboration and package legs, and the benchmark test
-- so a stage added to one was invisible to the others. `compile` is the
only composition now, and each caller names the stage it stops after:

  load       the package layer: the entry file, its import closure and the
             manifests that govern them, parsed, with the file-local checks
             (rhoform/package.py);
  elaborate  then the elaborator, when the package layer reported no error;
  check      then the static stage (rhoform.check), when elaboration
             produced a design with no error.

The elaboration and package conformance legs stop after `elaborate`, so
what they pin stays the elaborator's; the check leg and the benchmark test
stop after `check`, and so does the command line. Nothing here writes, and
`sink` receives every diagnostic of every stage that ran.
"""

from dataclasses import dataclass

from . import check as checker
from . import elaborate as elaborator
from . import package

STAGES = ("load", "elaborate", "check")


@dataclass
class Compilation:
    """What the stages that ran produced. `design` is set when elaboration
    succeeded, whatever the check stage then found: the IR of a design
    that elaborates is always emittable."""

    loaded: package.Compilation
    design: object | None = None  # rhoform.elaborate.ElaboratedDesign
    analysis: object | None = None  # rhoform.check.Analysis
    report: object | None = None  # rhoform.check.report.Report


def compile(entry: str, root, *, sink, stage: str = "check",
            root_module: str | None = None,
            through: str | None = None) -> Compilation:
    """Compile the entry file `entry` (its key, relative to the compile
    root `root`) up to and including `stage`. `root_module` names the root
    module explicitly; `through` stops the check stage after the named pass
    (rhoform.check.pass_names()). Raises package.ReadFailure when a file
    that exists cannot be read."""
    if stage not in STAGES:
        raise ValueError(f"stage {stage!r} is not one of {STAGES}")
    loaded = package.load(entry, root, sink)
    result = Compilation(loaded)
    if stage == "load" or not loaded.ok:
        return result
    elaboration = elaborator.elaborate(
        loaded.results, root=root_module, sink=sink,
        imports=loaded.imports, modules=loaded.modules)
    if not elaboration.ok:
        return result
    result.design = elaboration.design
    if stage == "check":
        context = checker.parts.load_context(root, loaded)
        result.analysis, result.report = checker.check(
            result.design, context, sink, through=through)
    return result
