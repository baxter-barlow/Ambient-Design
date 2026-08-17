"""Structured diagnostics for the prototype parsers.

P2 makes feedback quality the repair-loop bottleneck, and §8-Q1 is choosing a
grammar for a loop, not for a pretty listing. So a prototype that reported
"syntax error" would leave the most decision-relevant property of a candidate
unmeasured. These carry a stable code, a byte-accurate span, and structured
parameters, shaped after the A1 contract so that `lang/bakeoff/measure.py`
can score them and `rhoform check` can later emit the same shape.

CODES ARE PER-ARM AND STABLE. `RHOA0101` is arm A's "expected an indented
block"; `RHOB0101` is arm B's. Shared failures — a bad quantity literal, an
unknown unit — use the `RHOX` prefix, because charging one candidate for a
diagnostic every arm emits identically would be measuring the shared layer.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Span:
    """One-based line and column, plus a zero-based byte offset.

    All three, because they answer different questions: a model reads the
    line, a test asserts on the offset, and a renderer of caret listings needs
    the column. I9 requires the byte offset specifically.
    """

    line: int
    column: int
    offset: int
    length: int = 1

    def as_dict(self) -> dict:
        return {
            "line": self.line,
            "column": self.column,
            "offset": self.offset,
            "length": self.length,
        }


@dataclass(frozen=True)
class Diag:
    code: str
    message: str
    span: Span | None = None
    severity: str = "error"
    params: dict = field(default_factory=dict)
    fixit: str | None = None

    def as_dict(self) -> dict:
        out = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "params": dict(sorted(self.params.items())),
        }
        if self.span is not None:
            out["span"] = self.span.as_dict()
        if self.fixit is not None:
            out["fixit"] = self.fixit
        return out


class ParseFailure(Exception):
    """Parsing stopped. Carries every diagnostic produced, not just the last.

    A prototype that raised on the first error would report one problem per
    round trip through the repair loop, which is precisely the behaviour P2
    says makes loops converge badly — and it would flatter every candidate
    equally, hiding the difference the bake-off exists to find.
    """

    def __init__(self, diagnostics: list[Diag]):
        self.diagnostics = list(diagnostics)
        first = self.diagnostics[0] if self.diagnostics else None
        super().__init__(first.message if first else "parse failed")
