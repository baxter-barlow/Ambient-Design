"""Seeded emission defects: the repair-loop half of the bake-off, offline.

P2 is the project's central bet — "the loop is the unit of design", diagnostics
decide convergence — and §8-Q1 is choosing a grammar under it. At M0 there is
no model in the loop (that is AMB-33 running the AC5 protocol with AMB-31's
rig), so the loop's other half is measured here instead: given a design with
ONE deliberate defect, what does each candidate tell the author?

Three numbers per defect, and they are not the same question:

  DETECTED    the arm rejects the file at all. An arm that accepts a broken
              design has not made a small mistake; it has silently produced a
              wrong netlist, which is worse than any diagnostic.
  LOCALISED   some diagnostic points at the line the defect was injected on.
              This is where candidate B is expected to pay for block scoping,
              and the number decides whether it does.
  NOISE       how many diagnostics come back for one defect. Olausson et al.
              measured a 1.58x repair lift from better failure explanations;
              twelve cascade errors from one typo is the opposite of that.

DEFECTS ARE APPLIED TO RENDERED SOURCE, NOT TO EACH ARM SEPARATELY. Each
operator is described by what it does to the text — corrupt a unit, remove an
indent, drop a bracket — and the same operator runs against every arm's
rendering of the same design. An arm whose rendering does not contain the
construct records `not_applicable`, never a silent pass: a defect class that
quietly skipped an arm would flatter it in exactly the comparison it is in.
"""

import re
from dataclasses import dataclass

from .diagnostics import ParseFailure


@dataclass(frozen=True)
class Defect:
    key: str
    description: str
    # (source) -> (mutated source, 1-based line of the injected defect) or None
    # when the arm's rendering does not contain the construct.
    apply: object


def _replace_first(source: str, needle: str, replacement: str, *, must_follow: str = ""):
    """Replace the first occurrence of `needle`, reporting the line it was on."""
    for index, line in enumerate(source.splitlines(), start=1):
        if must_follow and must_follow not in line:
            continue
        position = line.find(needle)
        if position == -1:
            continue
        mutated = line[:position] + replacement + line[position + len(needle):]
        lines = source.splitlines()
        lines[index - 1] = mutated
        return "\n".join(lines) + "\n", index
    return None


def _corrupt_unit(source):
    return _replace_first(source, "kohm", "kOhm")


def _remove_indent(source):
    """Dedent the first line that opens a block's body.

    Layout languages live or die on this error, and it is the one a model
    makes most often when it edits a file it did not write.
    """
    lines = source.splitlines()
    for index in range(1, len(lines)):
        previous, current = lines[index - 1], lines[index]
        if previous.rstrip().endswith(":") and current.startswith(" ") and current.strip():
            lines[index] = current.lstrip()
            return "\n".join(lines) + "\n", index + 1
    return None


_ENDPOINT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")
_BARE_ENDPOINT_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\Z")


def _connection_lines(source):
    """Lines that state connectivity, in every arm's spelling.

    Anchoring here matters: corrupting the first `x.y` anywhere in the file
    hits `aed.lib.timer.Ne555` — a DEFINITION path — and seeds an
    unknown-component defect that then gets scored as an unknown-instance one.
    """
    for index, line in enumerate(source.splitlines()):
        stripped = line.strip()
        if " ~ " in stripped or "m.link(" in stripped or "m.net(" in stripped:
            yield index, line
        elif _BARE_ENDPOINT_RE.match(stripped):
            yield index, line


def _endpoint_match(line: str):
    """The first `x.y` on a connection line that is really an ENDPOINT.

    In the candidate grammars an endpoint is bare text; in the baseline it is a
    quoted string and the first bare `\w+\.\w+` on the line is the builder
    call itself. Mutating that produced `mz.net(...)` and `m.netz(...)` — an
    undefined-name defect scored as an unknown-instance one, in four of the
    baseline's sixteen cells. So a quoted match wins whenever the line has one.
    """
    quoted = set(range(len(line))) - set(_outside_strings(line))
    matches = list(_ENDPOINT_RE.finditer(line))
    inside = [m for m in matches if m.start() in quoted]
    return (inside or matches or [None])[0]


def _unknown_instance(source):
    """Point a connection at an instance that was never declared."""
    lines = source.splitlines()
    for index, line in _connection_lines(source):
        match = _endpoint_match(line)
        if match is None:
            continue
        lines[index] = (
            line[: match.start(1)] + match.group(1) + "z" + line[match.end(1):]
        )
        return "\n".join(lines) + "\n", index + 1
    return None


def _unknown_port(source):
    """Name a port the component does not have, on a connection line."""
    lines = source.splitlines()
    for index, line in _connection_lines(source):
        match = _endpoint_match(line)
        if match is None:
            continue
        lines[index] = (
            line[: match.start(2)] + match.group(2) + "z" + line[match.end(2):]
        )
        return "\n".join(lines) + "\n", index + 1
    return None


_ROLE_WORDS = ("passive", "power_in", "power_out", "bidirectional", "input", "output")


def _bad_role(source):
    """Corrupt a role WHERE A ROLE IS WRITTEN, not wherever the word appears.

    An earlier version matched the first "passive" in the file, which in the
    `inferred` cell is inside `aed.lib.passive.Capacitor` — so it was seeding
    an unknown-component defect and scoring it as a bad-role defect. The
    lesson generalises: a mutation operator that is not anchored to the
    construct it names measures something else and says nothing about it.
    """
    lines = source.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        for role in _ROLE_WORDS:
            if stripped.startswith(("pin ", "port ")) and f" {role}" in line:
                position = line.index(f" {role}")
                lines[index] = line[: position + 1 + len(role)] + "z" + line[position + 1 + len(role):]
                return "\n".join(lines) + "\n", index + 1
            if f'"{role}"' in line:
                lines[index] = line.replace(f'"{role}"', f'"{role}z"', 1)
                return "\n".join(lines) + "\n", index + 1
    return None


def _unterminated_string(source):
    """Drop the closing quote of the first string literal."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        # Skip the pragma and comments: corrupting `#pragma language "0.1.0"`
        # seeds a bad-pragma defect, not a bad-string one.
        if line.lstrip().startswith("#"):
            continue
        first = line.find('"')
        if first == -1:
            continue
        second = line.find('"', first + 1)
        if second == -1:
            continue
        lines[index] = line[:second] + line[second + 1:]
        return "\n".join(lines) + "\n", index + 1
    return None


def _outside_strings(line: str):
    """Indices of `line` that are not inside a double-quoted literal."""
    inside = False
    for index, char in enumerate(line):
        if char == '"':
            inside = not inside
            continue
        if not inside:
            yield index


def _dropped_bracket(source):
    """Delete a closing bracket - a real one, not one inside a string.

    The third operator to need anchoring. Benchmark (c)'s D1 carries the
    package `"SMA (DO-214AC)"` straight out of parts.yaml, and deleting that
    `)` leaves a perfectly good string literal: the arm accepted it, correctly,
    and the table scored it as a candidate accepting a defective design.
    """
    lines = source.splitlines()
    for index, line in enumerate(lines):
        positions = [i for i in _outside_strings(line) if line[i] == ")"]
        if not positions:
            continue
        position = positions[-1]
        lines[index] = line[:position] + line[position + 1:]
        return "\n".join(lines) + "\n", index + 1
    return None


def _unknown_measurement(source):
    return _replace_first(source, "duty_cycle", "dutycycle")


def _duplicate_name(source):
    """Repeat a declaration line, which every arm must reject as a redeclaration."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        # A declaration that opens a block cannot be duplicated on its own —
        # the copy would orphan the block and seed an indentation defect
        # instead of a redeclaration one.
        if stripped.endswith(":"):
            continue
        if " = new " in stripped or " = m.part(" in stripped or " = m.sub(" in stripped:
            lines.insert(index + 1, line)
            return "\n".join(lines) + "\n", index + 2
    return None


DEFECTS = (
    Defect("corrupt_unit", "a unit is misspelled (kohm -> kOhm)", _corrupt_unit),
    Defect("remove_indent", "the first line of a block body loses its indent", _remove_indent),
    Defect("unknown_instance", "a connection names an undeclared instance", _unknown_instance),
    Defect("unknown_port", "a connection names a port the component lacks", _unknown_port),
    Defect("bad_role", "a pin role is not in the T2 lattice", _bad_role),
    Defect("unterminated_string", "a string literal loses its closing quote", _unterminated_string),
    Defect("dropped_bracket", "a closing bracket is deleted", _dropped_bracket),
    Defect("unknown_measurement", "an assertion names a measurement outside V2 v1", _unknown_measurement),
    Defect("duplicate_name", "a declaration is repeated", _duplicate_name),
)


def score(arm, variant: str, model, design_id: str) -> list[dict]:
    """Run every defect against one arm's rendering of one design."""
    from .model import diff

    source = arm.render(model, variant)
    results = []
    for defect in DEFECTS:
        injected = defect.apply(source)
        if injected is None:
            results.append(
                {
                    "design": design_id,
                    "arm": arm.key,
                    "variant": variant,
                    "defect": defect.key,
                    "status": "not_applicable",
                }
            )
            continue
        mutated, line = injected
        record = {
            "design": design_id,
            "arm": arm.key,
            "variant": variant,
            "defect": defect.key,
            "line": line,
        }
        try:
            arm.parse(mutated, variant)
        except ParseFailure as failure:
            lines = {d.span.line for d in failure.diagnostics if d.span is not None}
            record.update(
                status="detected",
                localised=line in lines,
                diagnostics=len(failure.diagnostics),
                first_code=failure.diagnostics[0].code if failure.diagnostics else None,
                reported_lines=sorted(lines),
            )
        except RecursionError:
            # A prototype that blows the stack on malformed input is a
            # detection, but a bad one, and recording it as an ordinary
            # rejection would hide that.
            record.update(status="crashed", localised=False, diagnostics=0)
        else:
            # THE WORST OUTCOME. The arm accepted a design containing a known
            # defect. Whether the resulting netlist DIFFERS from the intended
            # one is recorded too: accepting a mutation that changed nothing is
            # bad, and accepting one that silently changed the circuit is the
            # failure this whole exercise is built to catch.
            parsed = arm.parse(mutated, variant)
            record.update(
                status="accepted",
                localised=False,
                diagnostics=0,
                changed_the_design=bool(diff(model, parsed)),
            )
        results.append(record)
    return results


def summarise(rows: list[dict]) -> dict:
    """Per-arm totals over the raw rows."""
    summary: dict[str, dict] = {}
    for row in rows:
        bucket = summary.setdefault(
            row["arm"],
            {"applicable": 0, "detected": 0, "localised": 0, "accepted": 0,
             "crashed": 0, "diagnostics": 0},
        )
        if row["status"] == "not_applicable":
            continue
        bucket["applicable"] += 1
        if row["status"] == "detected":
            bucket["detected"] += 1
            bucket["localised"] += 1 if row["localised"] else 0
            bucket["diagnostics"] += row["diagnostics"]
        elif row["status"] == "accepted":
            bucket["accepted"] += 1
        elif row["status"] == "crashed":
            bucket["crashed"] += 1
    for bucket in summary.values():
        detected = bucket["detected"]
        bucket["detection_rate"] = detected / bucket["applicable"] if bucket["applicable"] else None
        bucket["localisation_rate"] = bucket["localised"] / detected if detected else None
        bucket["diagnostics_per_defect"] = bucket["diagnostics"] / detected if detected else None
    return summary
