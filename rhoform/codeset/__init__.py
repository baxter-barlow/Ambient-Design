"""Per-owner diagnostic code sets: who may number what, and where.

Twice a block has been numbered by two tracks at once, each taking "the
next free number": the standard library and the imports both took RHO2048
in PR #18 (the library code became RHO2067 at integration), and
not-canonical became RHO1017 because syntax 0.2 already held RHO1016.
Both renumbers were legal only because nothing had shipped. M2 lands its
checkers in parallel, so every code it adds is declared in the file of
the owner that emits it, `rhoform/codeset/<owner>.py`, inside a range
`rhoform.codes.RANGES` gives that owner alone. Two landings then never
edit one registry file, and the registry gate refuses a code outside its
owner's range.

`rhoform.codes` assembles the registry from the core blocks it declares
itself (0-2, as they stood at M1) and every owner's `CODES`, and it is
still the one place a reader looks a code up. `CodeDef` lives here, not
there, so an owner file can import it without importing the registry
that imports the owner files.
"""

from dataclasses import dataclass
import importlib
import json
import re

# Every owner file, one per M2 workstream (plan.json "code_allocation").
# An owner declares codes only inside its ranges in rhoform.codes.RANGES;
# `core` is rhoform/codes.py itself and is not listed here.
OWNERS = ("budget", "check", "domains", "elaboration", "erc", "ground",
          "interfaces", "lockfile", "parts", "quantities", "syntax",
          "waivers")

_CODE_RE = re.compile(r"^RHO[0-9]{4}$")


def default_waivable(code: str, severity: str) -> bool:
    """Whether a T6 waiver may downgrade a code its owner did not decide
    for: errors of the checking blocks (3 types, 4 ground architecture,
    5 verification) are, nothing else is. Syntax, elaboration and part
    resolution errors are defects of the source, not judgments a design
    can overrule, and a warning or note has nothing to downgrade."""
    return (severity == "error" and bool(_CODE_RE.match(code))
            and code[3] in "345")


@dataclass(frozen=True)
class CodeDef:
    """One diagnostic code. `reserved=True` means the shape is published but
    no pass emits it yet — the GA catalog's state until its checker lands.

    `waivable` says whether a T6 waiver may downgrade it; left None it takes
    `default_waivable`, and an owner may set False on its own codes. A code
    no source text can trigger sets `source_triggered=False` and says why
    in `trigger_reason`; the conformance gate requires a reject case for
    every other active code of blocks 1-4 and 6."""

    code: str
    slug: str
    severity: str
    message: str
    params: tuple[str, ...] = ()
    rule: str | None = None  # traceability: a GA-* / requirement id
    reserved: bool = False
    waivable: bool | None = None
    source_triggered: bool = True
    trigger_reason: str | None = None

    def __post_init__(self):
        if self.waivable is None:
            object.__setattr__(self, "waivable",
                               default_waivable(self.code, self.severity))

    @property
    def category(self) -> str:
        from ..codes import BLOCKS

        return BLOCKS[int(self.code[3])][0]

    def render(self, values: dict) -> str:
        """The human message, from the template and structured params.

        Values render deterministically: strings verbatim, everything else
        as key-sorted compact JSON, so a list-valued param (RHO4002's cycle)
        cannot render differently between two runs over the same input.
        """

        def show(value):
            return value if isinstance(value, str) else json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                allow_nan=False)

        return self.message.format(**{k: show(v) for k, v in values.items()})


def owned() -> tuple:
    """(owner, its CODES) for every owner file, in OWNERS order. Imported
    here, on first use, rather than at the top of this package: an owner
    file imports CodeDef from this package, so the package must be whole
    before any of them runs."""
    return tuple(
        (name, importlib.import_module(f"{__name__}.{name}").CODES)
        for name in OWNERS)
