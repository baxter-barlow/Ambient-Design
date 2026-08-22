"""The A1 diagnostics framework: everything downstream emits through this.

One diagnostic is one line of newline-delimited JSON (rustc's shape, A1's
requirement), carrying:

  - a stable code from rhoform/codes.py — the registry is the only place a
    code may be declared, and construction refuses undeclared codes and
    parameter sets that do not match the declaration exactly;
  - byte spans in the source-map schema's own vocabulary (`byte_start`,
    `byte_end`, `line_start`, `col_start`, `line_end`, `col_end`): byte
    offsets are authoritative, line/col are denormalized for renderers,
    exactly as ir/source-map.schema.json states;
  - structured params separate from the message string — the message is
    RENDERED from the registry template and the params, so it cannot say
    something the params do not;
  - fix-its with applicability levels and structured byte-span edits;
  - an optional IR entity identity. The source-map schema's diagnostic-anchor
    rule says post-elaboration diagnostics reference an IR entity and
    resolve to spans through the map — `entity_spans` below is that
    resolution — while pre-IR stages (the lexer and parser have no IR to
    anchor to) carry raw spans, which is why `entity` is optional rather
    than the span being optional.

DETERMINISM. Emission is canonically ordered by (file, primary span, code,
message, params): source order first, because P2 optimizes the repair loop
and a model reads a file top to bottom. The GA checker notes sketched
"(code, then primary span)" before this framework existed; the framework is
the single owner of the order now, and the language spec records the
decision (spec/language/06-diagnostics.md).

THE CAP IS STATED, NEVER SILENT. Output is capped at OUTPUT_CAP diagnostics,
errors retained before warnings before notes; when anything is suppressed,
the stream's last line is an RHO0001 note carrying the exact counts. A
truncation the reader cannot see is a truncation that changes a repair run's
difficulty invisibly (the eval harness's build_repair_message learned this
first, and states its cap too).
"""

from bisect import bisect_right
from dataclasses import dataclass
import json
import re

from . import codes

APPLICABILITY = ("machine-applicable", "needs-review", "has-placeholders")

# One diagnostic line's schema discriminator, mirrored by
# rhoform/diagnostic.schema.json which validates a single line-object.
SCHEMA = "rhoform-diagnostic/0"

# The deterministic output cap (A1). 100 is a decision, not a measurement:
# large enough that all diagnostics of any benchmark-scale repair loop fit
# (the bake-off's worst seeded defect produced 3), small enough that a
# pathological input cannot flood an agent's context. Changing it changes
# what every consumer sees and belongs in the spec's changelog.
OUTPUT_CAP = 100

_SEVERITY_RANK = {"error": 0, "warning": 1, "note": 2}
_PLACEHOLDER_IN_TEXT = re.compile(r"<([a-z][a-z0-9_-]*)>")


@dataclass(frozen=True)
class Span:
    """A contiguous region of one source file, byte offsets authoritative.

    Field names are the source-map schema's, so the two artifacts cannot
    drift into synonyms; the one divergence is `file`, a repository-relative
    path here where the source map holds an index into its own file table
    (a diagnostic line must stand alone; an NDJSON stream has no header to
    carry a table).
    """

    file: str
    byte_start: int
    byte_end: int
    line_start: int
    col_start: int
    line_end: int
    col_end: int

    def __post_init__(self):
        if self.byte_start < 0 or self.byte_end < self.byte_start:
            raise ValueError(
                f"span bytes out of order: [{self.byte_start}, {self.byte_end})"
            )
        if self.line_start < 1 or self.col_start < 1 \
                or self.line_end < self.line_start or self.col_end < 1:
            raise ValueError("span line/col fields are 1-based")

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "line_start": self.line_start,
            "col_start": self.col_start,
            "line_end": self.line_end,
            "col_end": self.col_end,
        }


def span_from_bytes(file: str, data: bytes, byte_start: int,
                    byte_end: int) -> Span:
    """A Span over `data` with line/col denormalized from the byte offsets.

    Lines are 1-based over LF boundaries; columns are 1-based and counted in
    Unicode scalar values per the source-map schema. The language is ASCII
    (bytes and scalars coincide), but the offsets this is called with most
    often BELONG to non-ASCII defects, so the counting is done on a decoded
    prefix with invalid sequences replaced rather than assumed away.

    A zero-length span is an insertion point: line_end/col_end equal
    line_start/col_start. Otherwise col_end is one past the last character,
    which for a span ending at a line break is one past the line's last
    column — the schema's "just past the last character".
    """
    if byte_end > len(data) or byte_end < byte_start or byte_start < 0:
        raise ValueError(
            f"span [{byte_start}, {byte_end}) outside 0..{len(data)}"
        )
    starts = [0]
    for i, byte in enumerate(data):
        if byte == 0x0A:
            starts.append(i + 1)

    def locate(offset: int) -> tuple[int, int]:
        line_index = bisect_right(starts, offset) - 1
        prefix = data[starts[line_index]:offset]
        return line_index + 1, len(prefix.decode("utf-8", "replace")) + 1

    line_start, col_start = locate(byte_start)
    if byte_end == byte_start:
        return Span(file, byte_start, byte_end,
                    line_start, col_start, line_start, col_start)
    line_end, _ = locate(byte_end - 1)
    end_prefix = data[starts[line_end - 1]:byte_end]
    col_end = len(end_prefix.decode("utf-8", "replace")) + 1
    return Span(file, byte_start, byte_end,
                line_start, col_start, line_end, col_end)


@dataclass(frozen=True)
class Edit:
    """One textual change: replace the span's bytes with `replacement`.

    An insertion is a zero-length span; a deletion is an empty replacement.
    This is the capability the GA checker notes flagged as a requirement —
    a fix-it that INSERTS a component is an insertion edit whose replacement
    carries a `<placeholder>` for the synthesized name, under the
    has-placeholders applicability.
    """

    span: Span
    replacement: str


@dataclass(frozen=True)
class FixIt:
    """A suggested fix with its applicability level (A1).

    `machine-applicable`: applying the edits verbatim is believed correct.
    `needs-review`: the edits are concrete but a human/agent must judge them.
    `has-placeholders`: the edits contain `<name>` markers the author must
    fill; every marker is DECLARED in `placeholders` so the distinction
    between a marker and literal angle-bracket text is stated, not guessed.
    """

    message: str
    applicability: str
    edits: tuple[Edit, ...]
    placeholders: tuple[str, ...] = ()

    def __post_init__(self):
        if self.applicability not in APPLICABILITY:
            raise ValueError(
                f"applicability {self.applicability!r} is not one of "
                f"{APPLICABILITY}"
            )
        if not self.edits:
            raise ValueError(
                "a fix-it must carry at least one edit; a fix with no edit "
                "is a message, and messages belong in the diagnostic"
            )
        declared = set(self.placeholders)
        if len(self.placeholders) != len(declared):
            raise ValueError("duplicate placeholder name")
        present = set()
        for edit in self.edits:
            present |= set(_PLACEHOLDER_IN_TEXT.findall(edit.replacement))
        missing = declared - present
        if missing:
            raise ValueError(
                f"placeholders {sorted(missing)} declared but appear in no "
                "edit's replacement text"
            )
        if declared and self.applicability != "has-placeholders":
            raise ValueError(
                "a fix-it with declared placeholders must be has-placeholders"
            )
        if not declared and self.applicability == "has-placeholders":
            raise ValueError(
                "has-placeholders requires at least one declared placeholder"
            )

    def as_dict(self) -> dict:
        return {
            "message": self.message,
            "applicability": self.applicability,
            "placeholders": list(self.placeholders),
            "edits": [
                dict(edit.span.as_dict(), replacement=edit.replacement)
                for edit in self.edits
            ],
        }


@dataclass(frozen=True)
class Diagnostic:
    """One emitted diagnostic. Construct through `new()`, which is where the
    registry contract is enforced; the dataclass itself is dumb storage."""

    code: str
    slug: str
    severity: str
    category: str
    message: str
    params: tuple[tuple[str, object], ...]
    primary: Span
    primary_label: str | None
    secondary: tuple[tuple[Span, str], ...]
    fixits: tuple[FixIt, ...]
    entity: str | None
    tier: str | None

    @staticmethod
    def new(code: str, params: dict | None = None, *, primary: Span,
            primary_label: str | None = None,
            secondary: tuple[tuple[Span, str], ...] = (),
            fixits: tuple[FixIt, ...] = (),
            entity: str | None = None,
            tier: str | None = None) -> "Diagnostic":
        entry = codes.lookup(code)
        given = dict(params or {})
        if set(given) != set(entry.params):
            raise ValueError(
                f"{code} declares params {sorted(entry.params)}; "
                f"got {sorted(given)}. The structured params ARE the "
                "contract; a mismatch is a bug at the emission site."
            )
        if tier not in (None, "static", "dynamic"):
            raise ValueError(f"tier {tier!r} is not static/dynamic/None")
        message = entry.render(given)  # raises on unserializable values
        return Diagnostic(
            code=code,
            slug=entry.slug,
            severity=entry.severity,
            category=entry.category,
            message=message,
            params=tuple(sorted(given.items())),
            primary=primary,
            primary_label=primary_label,
            secondary=tuple(secondary),
            fixits=tuple(fixits),
            entity=entity,
            tier=tier,
        )

    def as_dict(self) -> dict:
        spans = [dict(self.primary.as_dict(), primary=True,
                      label=self.primary_label)]
        for span, label in self.secondary:
            spans.append(dict(span.as_dict(), primary=False, label=label))
        return {
            "schema": SCHEMA,
            "code": self.code,
            "slug": self.slug,
            "severity": self.severity,
            "category": self.category,
            "tier": self.tier,
            "message": self.message,
            "params": dict(self.params),
            "entity": self.entity,
            "spans": spans,
            "fixits": [fixit.as_dict() for fixit in self.fixits],
        }

    def sort_key(self) -> tuple:
        return (
            self.primary.file,
            self.primary.byte_start,
            self.primary.byte_end,
            self.code,
            self.message,
            json.dumps(dict(self.params), sort_keys=True),
        )


def entity_spans(sourcemap: dict, entity: str) -> tuple[Span, ...]:
    """Resolve an IR entity identity to source spans through the source map.

    Returns the declaration span first, then the instantiation trace
    innermost-first, exactly as the map stores them. This is the
    diagnostic-anchor rule's resolution leg: a post-elaboration diagnostic
    names the entity, and the spans on the wire come from here, so a
    reformat that moves the declaration moves every diagnostic with it.
    """
    node = sourcemap["nodes"][entity]
    files = [entry["path"] for entry in sourcemap["files"]]

    def build(raw: dict) -> Span:
        return Span(
            file=files[raw["file"]],
            byte_start=raw["byte_start"],
            byte_end=raw["byte_end"],
            line_start=raw["line_start"],
            col_start=raw["col_start"],
            line_end=raw["line_end"],
            col_end=raw["col_end"],
        )

    return (build(node["declaration"]),) + tuple(
        build(raw) for raw in node["instantiation_trace"]
    )


class Diagnostics:
    """The collector every pass reports into, and the only emission path.

    `add` validates through Diagnostic.new; `render` applies the canonical
    order and the stated cap and returns the NDJSON text. There is no
    unsorted or uncapped emission method on purpose — a second path is how
    determinism promises rot.
    """

    def __init__(self, cap: int = OUTPUT_CAP):
        if cap < 1:
            raise ValueError("the cap must retain at least one diagnostic")
        self._cap = cap
        self._items: list[Diagnostic] = []

    def add(self, code: str, params: dict | None = None, **kwargs) -> Diagnostic:
        diagnostic = Diagnostic.new(code, params, **kwargs)
        self._items.append(diagnostic)
        return diagnostic

    def extend(self, other: "Diagnostics") -> None:
        self._items.extend(other._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(sorted(self._items, key=Diagnostic.sort_key))

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self._items)

    def counts(self) -> dict:
        out = {"error": 0, "warning": 0, "note": 0}
        for diagnostic in self._items:
            out[diagnostic.severity] += 1
        return out

    def capped(self) -> list[Diagnostic]:
        """The emission list: canonical order, cap applied, truncation stated.

        Retention under the cap prefers errors over warnings over notes —
        dropping an error to keep a note would hide exactly what gates —
        and is deterministic: within a severity, canonical order decides.
        The emitted list is then re-sorted canonically so the reader still
        sees source order, and the truncation note is appended last with
        the counts of what was suppressed, per severity.
        """
        ordered = sorted(self._items, key=Diagnostic.sort_key)
        if len(ordered) <= self._cap:
            return ordered
        by_retention = sorted(
            ordered, key=lambda d: (_SEVERITY_RANK[d.severity],
                                    Diagnostic.sort_key(d))
        )
        retained = set(map(id, by_retention[:self._cap]))
        kept = [d for d in ordered if id(d) in retained]
        suppressed = [d for d in ordered if id(d) not in retained]
        tallies = {"error": 0, "warning": 0, "note": 0}
        for diagnostic in suppressed:
            tallies[diagnostic.severity] += 1
        note = Diagnostic.new(
            "RHO0001",
            {
                "shown": self._cap,
                "total": len(ordered),
                "suppressed": len(suppressed),
                "suppressed_errors": tallies["error"],
                "suppressed_warnings": tallies["warning"],
                "suppressed_notes": tallies["note"],
            },
            primary=suppressed[0].primary,
            primary_label="first suppressed diagnostic was here",
        )
        return kept + [note]

    def render(self) -> str:
        """The NDJSON stream: one key-sorted compact object per line."""
        return "".join(
            json.dumps(d.as_dict(), sort_keys=True, separators=(",", ":"))
            + "\n"
            for d in self.capped()
        )
