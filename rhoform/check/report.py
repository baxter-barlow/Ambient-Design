"""The reporter: buffered findings, coverage rows, and the check report.

FINDINGS are diagnostics a pass reports about one IR entity. They are
buffered here, never written straight to the sink, so the waiver layer
can see every one before anything is emitted (T6). Three rules hold at
the point of report, and a violation is a checker bug (an AssertionError,
which the command line reports as INTERNAL, exit 2):

  - a pass reports only codes inside its owner's ranges (rhoform.codes
    .RANGES), so parallel landings cannot collide on a number at run time
    either;
  - the entity is an IR entity with a source-map node -- an instance path,
    a net name or an assertion path -- and the primary span defaults to its
    declaration; a port-level finding names its instance or net and
    carries the port in params;
  - after dedup, one finding per (code, entity): member sets go in array
    params, so a 61-instance board cannot hit the output cap.

Dedup mirrors the elaborator's (RHO2026-2028): findings that agree on code,
params, spans and fix-its are one, keeping the entity only when every copy
names the same one.

COVERAGE ROWS say what a pass could and could not decide, per entity,
into the pass's section of the check report (`rhoform-check-report`,
version 0, rhoform/check-report.schema.json). A row is ACTIONABLE when the
author or the toolchain can close the gap it records; every other row is
an inherent limit and lives in the report only. Any actionable row raises
the one RHO3901 note of the compilation, whose params count the actionable
rows by class (the row's reason) -- coverage is never silent, and never
one diagnostic per gap (amendment OD1).

The report is canonical JSON (rhoform-canonical-json/1, the IR's encoder)
and never part of design_hash.
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json
import re

from .. import codes
from .. import ir
from ..diagnostics import Diagnostic, frozen_value

REPORT_VERSION = 0
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "check-report.schema.json"

# What a row says about its entity. Spec 05 section 1 restates the list.
STATUSES = ("pass", "fail", "undecided", "no-data", "not-run",
            "not-implemented", "interim")

_REASON = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Row:
    entity: str
    status: str
    reason: str
    actionable: bool
    detail: tuple  # sorted (name, frozen value) pairs

    def as_dict(self) -> dict:
        return {
            "entity": self.entity,
            "status": self.status,
            "reason": self.reason,
            "actionable": self.actionable,
            "detail": {name: list(value) if isinstance(value, tuple)
                       else value for name, value in self.detail},
        }

    def sort_key(self) -> tuple:
        return (self.entity, self.status, self.reason, self.actionable,
                json.dumps(self.as_dict()["detail"], sort_keys=True,
                           allow_nan=False))


class Report:
    """One compilation's findings and rows. The driver opens a section per
    pass; findings and rows go to whichever is open."""

    def __init__(self, model):
        self.model = model
        self.findings: list[Diagnostic] = []
        self.sections: dict[str, dict] = {}  # name -> implemented, rows
        self.section: str | None = None
        self.owner: str | None = None

    def open(self, section: str, owner: str, implemented: bool) -> None:
        """Make `section` the section rows go to, and `owner` the codeset
        whose ranges findings must lie in."""
        self.sections.setdefault(section, {"implemented": implemented,
                                           "rows": []})
        self.section, self.owner = section, owner

    def finding(self, code: str, params: dict | None = None, *,
                entity: str, primary=None, primary_label=None,
                secondary=(), fixits=(), tier=None) -> Diagnostic:
        holder = codes.owner_of(code)
        if holder is None:
            raise AssertionError(
                f"{code} lies in no range of rhoform.codes.RANGES")
        if holder != self.owner:
            raise AssertionError(
                f"{code} is {holder}'s to report, not {self.owner}'s; a "
                "pass reports only the codes of its owner's ranges")
        if entity not in self.model.entities:
            raise AssertionError(
                f"{entity!r} has no source-map node; a finding is about an "
                "instance path, a net name or an assertion path")
        if primary is None:
            primary = self.model.declaration(entity)
        found = Diagnostic.new(code, params, primary=primary,
                               primary_label=primary_label,
                               secondary=tuple(secondary),
                               fixits=tuple(fixits), entity=entity,
                               tier=tier)
        self.findings.append(found)
        return found

    def row(self, entity: str, status: str, reason: str, *,
            actionable: bool = False, detail: dict | None = None) -> Row:
        if self.section is None:
            raise AssertionError("a row needs an open section")
        if status not in STATUSES:
            raise ValueError(f"row status {status!r} is not one of "
                             f"{STATUSES}")
        if not _REASON.match(reason):
            raise ValueError(f"row reason {reason!r} is not kebab-case")
        if entity not in self.model.entities:
            raise AssertionError(
                f"{entity!r} has no source-map node; a row is about an "
                "instance path, a net name or an assertion path")
        frozen = tuple((name, frozen_value(value))
                       for name, value in sorted((detail or {}).items()))
        made = Row(entity, status, reason, bool(actionable), frozen)
        self.sections[self.section]["rows"].append(made)
        return made

    def actionable(self) -> list[tuple[str, Row]]:
        """Every actionable row with its section, in section order."""
        return [(name, row) for name, section in self.sections.items()
                for row in sorted(set(section["rows"]), key=Row.sort_key)
                if row.actionable]

    def summarize(self, owner: str,
                  sections: tuple | None = None) -> Diagnostic | None:
        """The compilation's one RHO3901, when any row is actionable;
        when `sections` is given (an area's run), any row of those."""
        rows = [(name, row) for name, row in self.actionable()
                if sections is None or name in sections]
        if not rows:
            return None
        by_class = Counter(row.reason for _section, row in rows)
        sections = []
        for name, _row in rows:
            if name not in sections:
                sections.append(name)
        self.owner = owner
        return self.finding(
            "RHO3901",
            {"actionable": len(rows),
             "classes": [f"{reason}: {count}" for reason, count
                         in sorted(by_class.items())],
             "sections": sections},
            entity="/")

    def flush(self, sink) -> None:
        """Dedup, check the one-per-(code, entity) rule, and emit."""
        groups: dict[tuple, list[Diagnostic]] = {}
        for found in self.findings:
            key = (found.code, found.params, found.primary,
                   found.primary_label, found.secondary, found.fixits,
                   found.tier)
            groups.setdefault(key, []).append(found)
        emitted = []
        for copies in groups.values():
            entities = {found.entity for found in copies}
            entity = entities.pop() if len(entities) == 1 else None
            emitted.append((copies[0], entity))
        seen = set()
        for found, entity in emitted:
            if entity is None:
                continue
            if (found.code, entity) in seen:
                raise AssertionError(
                    f"two {found.code} findings about {entity}; aggregate "
                    "a member set into an array param instead")
            seen.add((found.code, entity))
        for found, entity in emitted:
            sink.add(found.code,
                     {name: list(value) if isinstance(value, tuple)
                      else value for name, value in found.params},
                     primary=found.primary,
                     primary_label=found.primary_label,
                     secondary=found.secondary, fixits=found.fixits,
                     entity=entity, tier=found.tier)

    def document(self, design_hash: str) -> dict:
        """The check report, `rhoform-check-report` version 0."""
        return {
            "report_version": REPORT_VERSION,
            "design_hash": design_hash,
            "generator": dict(ir.GENERATOR),
            "sections": {
                name: {"implemented": section["implemented"],
                       "rows": [row.as_dict() for row in
                                sorted(set(section["rows"]),
                                       key=Row.sort_key)]}
                for name, section in self.sections.items()},
            "waivers": [],
            "safety": [],
        }

    def canonical(self, design_hash: str) -> bytes:
        """The report's bytes, in the IR's canonical encoding."""
        return ir.canonical_bytes(self.document(design_hash))


_VALIDATOR = None


def schema_problem(document: dict) -> str | None:
    """Why `document` is not a valid check report, or None. Raises
    ImportError when the pinned jsonschema is missing: an unavailable
    check, never a pass."""
    global _VALIDATOR
    import jsonschema

    if _VALIDATOR is None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = jsonschema.validators.validator_for(schema)(schema)
    error = jsonschema.exceptions.best_match(_VALIDATOR.iter_errors(document))
    if error is None:
        return None
    where = "/".join(str(part) for part in error.absolute_path)
    return f"{error.message} (at /{where})"
