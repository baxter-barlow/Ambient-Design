#!/usr/bin/env python3
"""Re-evaluate the hand-computed assertions of a deck-less benchmark.

Benchmark (c) has no ngspice deck by design — its gate is a hand-computed T10
power budget plus assertions A1..A10 — and `run-sim.sh` therefore skips it
entirely, so `check-assertions.py` never sees it. That left ten assertions the
file calls "the gating checks" read by no code at all: an auditor rewrote A3's
inputs to `{ldo_rating_a: 0.001, worst_rail_a: 99.0}`, leaving the expression
and `status: PASS` intact, and `make sim` stayed green. It is the same
"assertions.yaml was read by no code in the repository" condition that
check-assertions.py was written to close, still live for one of the three
benchmarks.

WHAT THIS CHECKS. Each assertion records `inputs`, a relation, and a `status`.
This recomputes the relation FROM the inputs and compares the verdict to the
recorded one. It cannot re-derive the inputs — those come from datasheets and
from power-tree.yaml, and checking them is a human job — but it does mean the
recorded PASS has to follow from the recorded numbers, so an input edited to an
absurd value stops agreeing with its own verdict.

Relations are matched on the `check:` key each assertion declares, not parsed
out of prose: a checker that guessed at English would fail open the first time
someone rephrased a line.

STATED LIMIT. benchmark (c) has no deck, so its `validation.log` carries no
`.meas` lines and `check-assertions.py`'s transcript comparison has nothing to
reconcile it against. Of the five committed transcripts, two are mechanically
checked and this one is not; it is a record of hand computation, and the
computation itself is what this file gates. Saying so here because "checked by
nothing" reads identically to "checked" from outside.

Exit codes: 0 pass, 1 an assertion whose verdict does not follow, 2 environment
failure.

    python3 tests/benchmarks/check-hand-assertions.py --self-test
    python3 tests/benchmarks/check-hand-assertions.py <benchmark-dir>
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def _interval(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    raise ValueError(f"{value!r} is not a two-element interval")


def _leaf_numbers(mapping, prefix=""):
    """Every numeric leaf in `inputs`, keyed by dotted path."""
    out = {}
    if isinstance(mapping, dict):
        for k, v in mapping.items():
            out.update(_leaf_numbers(v, f"{prefix}{k}." if prefix == "" else f"{prefix}{k}."))
        return {k.rstrip("."): v for k, v in out.items()} if prefix else out
    return out


def _numeric_string(value):
    """A number written as a string is still a number.

    `worst_rail_a: "99.0"` was invisible to this walk, so it was not an orphan,
    needed no `inputs_not_gated` entry, and could be set to anything.
    """
    if not isinstance(value, str):
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _flatten(value, path, out):
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{path}.{k}" if path else k, out)
    elif isinstance(value, (list, tuple)):
        if value and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                         for v in value):
            out[path] = list(value)
        else:
            # A list of DICTS is a table of corner values and was dropped
            # whole: `corners: [{ta_c: 500, i_a: 99.0}]` was completely
            # invisible, which is the "500 C ambient" case by another route.
            for index, item in enumerate(value):
                _flatten(item, f"{path}[{index}]", out)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[path] = value
    else:
        number = _numeric_string(value)
        if number is not None:
            out[path] = number


def _resolve(inputs, name):
    flat = {}
    _flatten(inputs, "", flat)
    if name not in flat:
        raise KeyError(f"`inputs` has no numeric key {name!r} (has: {sorted(flat)})")
    return flat[name]


_ALLOWED = None


def _perturb(mapping, dotted, new_value):
    """Return a copy of `mapping` with one dotted key replaced. None if absent."""
    import copy
    out = copy.deepcopy(mapping)
    parts = dotted.replace("]", "").replace("[", ".").split(".")
    node = out
    for part in parts[:-1]:
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    last = parts[-1]
    if isinstance(node, dict) and last in node:
        node[last] = new_value
        return out
    return None


def evaluate_formula(expr, inputs):
    """Arithmetic over `inputs` keys only. No calls, no attributes, no names
    beyond the input keys themselves."""
    import ast
    flat = {}
    _flatten(inputs, "", flat)
    tree = ast.parse(expr, mode="eval")
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            a, b = walk(node.left), walk(node.right)
            # Branch, do not build a dict: a dict literal evaluates ALL FOUR
            # operations, so `a ** b` overflowed on a plain multiply and the
            # gate crashed instead of reporting the finding it had found.
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            return a ** b
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = walk(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in flat:
                raise ValueError(f"formula names {node.id!r}, which is not an input key")
            return float(flat[node.id])
        if isinstance(node, ast.Attribute):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if not isinstance(cur, ast.Name):
                raise ValueError("unsupported expression")
            parts.append(cur.id)
            key = ".".join(reversed(parts))
            if key not in flat:
                raise ValueError(f"formula names {key!r}, which is not an input key")
            return float(flat[key])
        raise ValueError(f"unsupported expression element {type(node).__name__}")
    return walk(tree)


def evaluate(check, inputs):
    """Return (holds, explanation) for one declared relation."""
    if check == "interval-within":
        inner, outer = _interval(inputs["inner"]), _interval(inputs["outer"])
        holds = outer[0] <= inner[0] and inner[1] <= outer[1]
        return holds, f"[{inner[0]}, {inner[1]}] within [{outer[0]}, {outer[1]}]"
    if check == "at-least":
        have, need = float(inputs["have"]), float(inputs["need"])
        return have >= need, f"{have} >= {need}"
    if check == "at-most":
        have, limit = float(inputs["have"]), float(inputs["limit"])
        return have <= limit, f"{have} <= {limit}"
    if check == "sum-at-most":
        parts = [float(v) for v in inputs["parts"]]
        limit = float(inputs["limit"])
        return sum(parts) <= limit, f"sum({parts}) = {sum(parts):.6g} <= {limit}"
    if check == "at-least-all":
        have = float(inputs["have"])
        needs = [float(v) for v in inputs["needs"]]
        return all(have >= n for n in needs), f"{have} >= max({needs})"
    raise ValueError(
        f"unknown check {check!r}; declare one of interval-within, at-least, at-least-all, "
        "at-most, sum-at-most, or add it here with its arithmetic"
    )


# At least this many assertions must actually be evaluated. Without a floor,
# relabelling every `check:` as `not_mechanisable` reported "0 assertion(s)
# follow from their inputs" and exited 0 — the set that "cannot grow quietly"
# growing to everything.
MINIMUM_MECHANISED = 8

# The assertion IDs that MUST be mechanised. A bare count let A3 be relabelled
# `not_mechanisable` and a filler assertion appended, keeping `checked` at 8
# while the one with the interesting inputs left the gate.
# Keyed BY BENCHMARK: this is a statement about one real population, not about
# every spec this function is ever handed. Applying it globally tripped the
# self-test's own fixture -- the fourth time in this audit a floor has been
# written as if fixtures were benchmarks.
MUST_MECHANISE = {
    "esp32s3-devboard": (
        "A1_rail_voltage_containment", "A2_vbus_budget_t10",
        "A3_3v3_source_capability", "A4_ldo_dropout_at_min_vbus",
        "A5_ldo_thermal_at_wifi_tx", "A6_ptc_hold_margin",
        "A7_deep_sleep_rail_current", "A8_usb_inrush_capacitance",
    ),
}


def structure_hash(assertions):
    """Content hash over WHICH INPUT PLAYS WHICH ROLE, per assertion.

    The reconciliation proves each operand equals some named input. It cannot
    know that the author named the RIGHT one: swapping the mapping alongside
    the values restored round 5's finding exactly --

        check_inputs: {have: 99.0, needs: [0.001, 0.500]}
        check_inputs_from: {have: worst_rail_a, needs: [ldo_rating_a, ...]}
        inputs: {ldo_rating_a: 0.001, worst_rail_a: 99.0, ...}

    -- which is arithmetically true, electrically meaningless, and green. No
    amount of arithmetic catches that, because the arithmetic is correct. What
    a gate CAN do is refuse to let the binding change quietly: this is the same
    device corpus/classification.yaml uses for `decision_hash`. Changing which
    input feeds which operand is a real engineering decision and now has to be
    a deliberate, reviewed commit rather than an edited line.
    """
    import hashlib, json
    shape = []
    for assertion in sorted(assertions, key=lambda a: str(a.get("id"))):
        shape.append({
            "id": assertion.get("id"),
            "check": assertion.get("check"),
            "from": assertion.get("check_inputs_from"),
            "derived": assertion.get("check_inputs_derived"),
            "not_gated": sorted((assertion.get("inputs_not_gated") or {})),
            "not_mechanisable": bool(assertion.get("not_mechanisable")),
        })
    payload = json.dumps(shape, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_spec(spec, label, problems, minimum=None, gate_structure=True):
    assertions = spec.get("assertions") or []
    if gate_structure and assertions:
        committed = spec.get("check_inputs_structure_hash")
        actual = structure_hash(assertions)
        if committed is None:
            problems.append(
                f"{label}: records no `check_inputs_structure_hash`. Which "
                "input feeds which operand is an engineering decision that "
                "arithmetic cannot check; it is pinned so changing it is a "
                f"reviewed commit. Add: check_inputs_structure_hash: {actual}")
        elif committed != actual:
            problems.append(
                f"{label}: check_inputs_structure_hash is {committed}, but the "
                f"operand-to-input bindings hash to {actual}. A binding changed. "
                "That is allowed and sometimes right -- but swapping `have` and "
                "`need` between two inputs is arithmetically valid and "
                "electrically meaningless, so it must be deliberate. Update the "
                "hash in the same commit and say why.")
    if not assertions:
        problems.append(f"{label}: declares no assertions")
        return 0
    checked = 0
    unmechanised = 0
    for assertion in assertions:
        name = assertion.get("id") or assertion.get("name") or "<unnamed>"
        check = assertion.get("check")
        if check is None and assertion.get("not_mechanisable"):
            # Declared unmechanisable, with a stated reason. Counted and printed
            # so the set cannot grow quietly.
            print(f"hand-assert: not mechanisable: {label}/{name}: "
                  f"{assertion['not_mechanisable'].strip()}")
            unmechanised += 1
            continue
        if check is None:
            # Not yet machine-checkable. Reported, never skipped: an assertion
            # nothing evaluates is the condition this file exists to end.
            problems.append(
                f"{label}/{name}: declares no `check:` key, so its recorded "
                "verdict is re-derived by nothing. Add one of the declared "
                "relations, or state in the file why this assertion cannot be "
                "mechanised."
            )
            continue
        try:
            holds, shown = evaluate(check, assertion.get("check_inputs") or {})
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{label}/{name}: {exc}")
            continue
        checked += 1
        status = assertion.get("status")
        if status is None:
            # Absent status read as "not PASS", so a relation that does NOT hold
            # and records no verdict was silently accepted.
            problems.append(
                f"{label}/{name}: records no `status:`, so there is no verdict "
                "for the recomputed relation to agree or disagree with.")
            continue
        recorded = str(status).upper().startswith("PASS")
        if holds != recorded:
            problems.append(
                f"{label}/{name}: recorded status {assertion.get('status')!r} but "
                f"the inputs give {shown} -> {'PASS' if holds else 'FAIL'}. The "
                "verdict does not follow from the numbers beside it."
            )
    if minimum is None:
        missing = [i for i in MUST_MECHANISE.get(label, ())
                   if not any(a.get("id") == i and a.get("check") for a in assertions)]
        if missing:
            problems.append(
                f"{label}: assertion(s) {missing} must be mechanised and are "
                "not. A bare count let the one with the interesting inputs be "
                "relabelled unmechanisable and replaced with filler.")
    floor = MINIMUM_MECHANISED if minimum is None else minimum
    if checked < floor:
        problems.append(
            f"{label}: only {checked} of {len(assertions)} assertion(s) were "
            f"evaluated ({unmechanised} declared unmechanisable), below the "
            f"floor of {floor}. Lowering the floor is a deliberate "
            "decision; drifting under it is not."
        )
    # THE RECONCILIATION, rebuilt. It used to compare SETS OF NUMBERS between
    # `check_inputs` and `inputs`, which means (i) swapping the operands was
    # invisible -- one auditor asserted a 0.001 A LDO supplies a 99 A rail with
    # the gate green -- and (ii) it only required check_inputs SUBSET inputs, so
    # every input the operands did not happen to use could be set to physical
    # nonsense. Now each operand names the input key it comes from, and every
    # numeric input must be either used or declared ungated with a reason.
    for assertion in assertions:
        name = assertion.get("id") or assertion.get("name") or "<unnamed>"
        declared = assertion.get("check_inputs")
        if not declared:
            continue
        recorded = assertion.get("inputs")
        if not isinstance(recorded, dict):
            problems.append(
                f"{label}/{name}: has `check_inputs` but no `inputs` mapping to "
                "reconcile them against.")
            continue
        origin = assertion.get("check_inputs_from")
        formulas = assertion.get("check_inputs_derived") or {}
        if not isinstance(origin, dict):
            problems.append(
                f"{label}/{name}: declares no `check_inputs_from`, so its "
                "operands are a copy of the inputs that nothing reconciles. "
                "Name the `inputs` key each operand comes from.")
            continue
        # OPERANDS THE RELATION ACTUALLY CONSUMES. `used` was filled from every
        # key in check_inputs, so adding `decorative: 99999` with
        # `check_inputs_from: {decorative: worst.theta_ja_c_w}` marked that
        # input read while nothing read it -- reopening the 500 C ambient by a
        # third route. evaluate() takes fixed operand names per relation.
        RELATION_OPERANDS = {
            "interval-within": {"inner", "outer"},
            "at-least": {"have", "need"},
            "at-least-all": {"have", "needs"},
            "at-most": {"have", "limit"},
            "sum-at-most": {"parts", "limit"},
        }
        consumed = RELATION_OPERANDS.get(assertion.get("check"))
        if consumed is not None:
            extra = sorted(set(declared) - consumed)
            if extra:
                problems.append(
                    f"{label}/{name}: declares operand(s) {extra}, which "
                    f"`{assertion.get('check')}` does not read. An operand the "
                    "relation never consumes still marks its input used, so a "
                    "decorative mapping launders an unread input.")
        used = set()
        for operand, value in declared.items():
            if operand in formulas:
                try:
                    got = evaluate_formula(formulas[operand], recorded)
                except (ValueError, KeyError, SyntaxError, ArithmeticError) as exc:
                    problems.append(f"{label}/{name}: {operand}: {exc}")
                    continue
                import ast as _ast
                this_formula = set()
                for node in _ast.walk(_ast.parse(formulas[operand], mode="eval")):
                    if isinstance(node, _ast.Name):
                        this_formula.add(node.id)
                    elif isinstance(node, _ast.Attribute):
                        parts, cur = [], node
                        while isinstance(cur, _ast.Attribute):
                            parts.append(cur.attr); cur = cur.value
                        if isinstance(cur, _ast.Name):
                            parts.append(cur.id); this_formula.add(".".join(reversed(parts)))
                used.update(this_formula)
                # NaN compares false against everything, so `(1e308*1e308 -
                # 1e308*1e308)` reconciled with ANY operand. A formula that
                # does not produce a finite number has not derived anything.
                import math as _math
                if not _math.isfinite(got):
                    problems.append(
                        f"{label}/{name}: formula for {operand} evaluates to "
                        f"{got!r}, which is not a finite number. A non-finite "
                        "result compares equal to nothing and unequal to "
                        "nothing, so it reconciles with any operand at all.")
                    continue
                # EVERY NAMED INPUT MUST MATTER. `used` was filled from the
                # names appearing in the expression, so `0*worst.ta_c` marked
                # ta_c used while removing it from the arithmetic -- a 500 C
                # ambient and a 39 A load, gate green. Each name is perturbed;
                # one that does not move the result is not an input to it.
                for name_used in sorted(this_formula):
                    probe = dict(recorded)
                    flat_probe = {}
                    _flatten(probe, "", flat_probe)
                    base = flat_probe.get(name_used)
                    if not isinstance(base, (int, float)):
                        continue
                    bumped = _perturb(probe, name_used, base * 2.0 + 1.0)
                    if bumped is None:
                        # NOT a silent skip. `_perturb` returns None for a
                        # dotted key that `inputs` spells flat rather than
                        # nested -- and reshaping `inputs` that way does not
                        # move check_inputs_structure_hash, so it silently
                        # disabled this whole defence for every affected name.
                        problems.append(
                            f"{label}/{name}: formula for {operand} names "
                            f"`{name_used}`, which this gate cannot perturb to "
                            "check that it matters. Spell the input nested "
                            "(worst: {ta_c: ...}) rather than flat "
                            "('worst.ta_c: ...'), or the inert-term check "
                            "does not run for it.")
                        continue
                    try:
                        moved = evaluate_formula(formulas[operand], bumped)
                    except (ValueError, KeyError, SyntaxError, ArithmeticError):
                        continue
                    # MATERIAL, not merely nonzero. Exact equality meant a
                    # coefficient of 1e-12 counted as "this input matters":
                    # the result moved by ~1e-12 while the operand is compared
                    # at 1e-3 relative, nine orders of magnitude coarser. So a
                    # 500 C worst-case ambient sat in the record with the gate
                    # green. An input has to move the result by at least as
                    # much as the comparison can see.
                    # Against the perturbation's own size, not the operand's.
                    # `abs(value)*1e-3` is a 0.1%-of-operand floor, so a
                    # coefficient of 0.0025 on a 500 C ambient counted as
                    # material while contributing 0.1% of the physics: A5
                    # reported Tj = 123.05 C against a true 571.9 C, above the
                    # part's 150 C absolute maximum. A term that matters moves
                    # the result by an amount comparable to the term itself.
                    tolerance = abs(got) * 1e-9 + 1e-12
                    if _math.isfinite(moved) and abs(moved - got) <= tolerance:
                        problems.append(
                            f"{label}/{name}: formula for {operand} names "
                            f"`{name_used}` but changing it does not change the "
                            "result, so the input is declared used and is not. "
                            "Multiplying a term by zero satisfies the "
                            "reconciliation while removing it from the physics.")
                if abs(got - float(value)) > abs(float(value)) * 1e-3 + 1e-12:
                    problems.append(
                        f"{label}/{name}: operand {operand}={value} but its own "
                        f"formula over `inputs` gives {got:.6g}. The gated number "
                        "is not the number the inputs produce.")
                continue
            if operand not in origin:
                problems.append(
                    f"{label}/{name}: operand {operand!r} is not in "
                    "`check_inputs_from`, so nothing ties it to an input.")
                continue
            keys = origin[operand]
            keys = keys if isinstance(keys, list) else [keys]
            used.update(keys)
            try:
                resolved = [_resolve(recorded, k) for k in keys]
            except KeyError as exc:
                problems.append(f"{label}/{name}: {operand}: {exc}")
                continue
            got = resolved[0] if len(resolved) == 1 else resolved
            if isinstance(value, list):
                flatv = [float(v) for v in value]
                flatg = [float(v) for v in (got if isinstance(got, list) else [got])]
                if len(flatg) == 1 and isinstance(resolved[0], list):
                    flatg = [float(v) for v in resolved[0]]
                ok = len(flatv) == len(flatg) and all(
                    abs(a - b) <= abs(b) * 1e-9 + 1e-15 for a, b in zip(flatv, flatg))
            else:
                ok = (not isinstance(got, list)
                      and abs(float(value) - float(got)) <= abs(float(got)) * 1e-9 + 1e-15)
            if not ok:
                problems.append(
                    f"{label}/{name}: operand {operand}={value!r} does not equal "
                    f"`inputs.{'+'.join(map(str, keys))}`={got!r}. The gate is "
                    "re-deriving the verdict from a copy nobody maintains.")
        flat = {}
        _flatten(recorded, "", flat)
        ungated = assertion.get("inputs_not_gated") or {}
        orphans = sorted(set(flat) - used - set(ungated))
        if orphans:
            problems.append(
                f"{label}/{name}: numeric input(s) {orphans} feed no operand and "
                "are not listed in `inputs_not_gated`. An input nothing reads can "
                "be set to anything, which is how a 500 C ambient passed.")
        for key, reason in ungated.items():
            if key not in flat:
                problems.append(
                    f"{label}/{name}: `inputs_not_gated` names {key!r}, which is "
                    "not a numeric input.")
            elif not str(reason).strip():
                problems.append(
                    f"{label}/{name}: `inputs_not_gated[{key}]` states no reason.")
    return checked


def load_yaml(path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise GateUnavailable(
            "PyYAML is required; install the pin (python3 -m pip install pyyaml==6.0.2)."
        ) from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateUnavailable(f"{path} is not readable as YAML: {exc}") from exc


def _must_mechanise_probe():
    """MUST_MECHANISE is keyed by benchmark, so it is exercised with a real
    name rather than with a fixture label -- the scoping mistake that tripped
    four earlier floors in this repository."""
    problems = []
    check_spec({"assertions": [
        {"id": "filler", "check": "at-least",
         "check_inputs": {"have": 1.0, "need": 0.5},
         "check_inputs_from": {"have": "h", "need": "n"},
         "inputs": {"h": 1.0, "n": 0.5}, "status": "PASS"}]},
        "esp32s3-devboard", problems, gate_structure=False)
    return problems


def self_test():
    cases = []

    def probe(assertion):
        # The arithmetic probes predate `check_inputs_from`; they exist to test
        # the RELATIONS, so the reconciliation wiring is synthesised for them
        # and tested separately by the three cases at the end of this list.
        if "check_inputs" in assertion and "inputs" not in assertion:
            ci = assertion["check_inputs"]
            assertion = dict(assertion,
                             inputs={f"in_{k}": v for k, v in ci.items()},
                             check_inputs_from={k: f"in_{k}" for k in ci})
        problems = []
        check_spec({"assertions": [assertion]}, "probe", problems, minimum=0,
                   gate_structure=False)
        return problems

    cases.append(("a true interval containment passes", not probe(
        {"id": "a", "check": "interval-within",
         "check_inputs": {"inner": [3.234, 3.366], "outer": [3.0, 3.6]}, "status": "PASS"})))
    cases.append(("a false containment recorded PASS is caught", any(
        "does not follow" in p for p in probe(
            {"id": "a", "check": "interval-within",
             "check_inputs": {"inner": [2.0, 4.0], "outer": [3.0, 3.6]}, "status": "PASS"}))))
    cases.append(("the auditor's A3 mutation is caught", any(
        "does not follow" in p for p in probe(
            {"id": "a3", "check": "at-least",
             "check_inputs": {"have": 0.001, "need": 99.0}, "status": "PASS"}))))
    cases.append(("a true at-most passes", not probe(
        {"id": "a", "check": "at-most",
         "check_inputs": {"have": 0.3916, "limit": 0.5}, "status": "PASS"})))
    cases.append(("a false at-most recorded PASS is caught", any(
        "does not follow" in p for p in probe(
            {"id": "a", "check": "at-most",
             "check_inputs": {"have": 9.0, "limit": 0.5}, "status": "PASS"}))))
    cases.append(("sum-at-most adds its parts", any(
        "does not follow" in p for p in probe(
            {"id": "a", "check": "sum-at-most",
             "check_inputs": {"parts": [4.7, 4.7, 0.1], "limit": 9.0}, "status": "PASS"}))))
    cases.append(("an assertion with no check key is reported", any(
        "declares no `check:`" in p for p in probe(
            {"id": "a", "check_inputs": {}, "status": "PASS"}))))
    cases.append(("an unknown relation is rejected, not assumed true", any(
        "unknown check" in p for p in probe(
            {"id": "a", "check": "vibes", "check_inputs": {}, "status": "PASS"}))))
    cases.append(("a recorded FAIL that really fails is consistent", not probe(
        {"id": "a", "check": "at-least",
         "check_inputs": {"have": 1.0, "need": 2.0}, "status": "FAIL"})))

    # THE RECONCILIATION CONTRACT itself, which the arithmetic probes above
    # synthesise past. These are the two attacks both round-5 auditors landed.
    cases.append(("an operand tied to no input key is caught", any(
        "check_inputs_from" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
             "inputs": {"rating_a": 1.0, "need_a": 0.5}, "status": "PASS"}))))
    cases.append(("swapped operands are caught even though the numbers all appear", any(
        "does not equal" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 99.0, "need": 0.001},
             "check_inputs_from": {"have": "rating_a", "need": "need_a"},
             "inputs": {"rating_a": 0.001, "need_a": 99.0}, "status": "PASS"}))))
    cases.append(("an input feeding no operand is caught", any(
        "feed no operand" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
             "check_inputs_from": {"have": "rating_a", "need": "need_a"},
             "inputs": {"rating_a": 1.0, "need_a": 0.5, "ta_c": 500}, "status": "PASS"}))))
    cases.append(("a derived operand that the inputs do not produce is caught", any(
        "not the number the inputs produce" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 3.8, "need": 3.5618},
             "check_inputs_from": {"have": "v_in"},
             "check_inputs_derived": {"need": "v_out + k * i"},
             "inputs": {"v_in": 3.8, "v_out": 99.0, "k": 0.5, "i": 0.3916},
             "status": "PASS"}))))
    cases.append(("an ungated input with no stated reason is caught", any(
        "states no reason" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
             "check_inputs_from": {"have": "rating_a", "need": "need_a"},
             "inputs": {"rating_a": 1.0, "need_a": 0.5, "spare": 1.0},
             "inputs_not_gated": {"spare": ""}, "status": "PASS"}))))

    # The floor and the missing-`status:` branch, both uncovered: the probes
    # all pass minimum=0, so no case could reach the floor.
    floor_problems = []
    check_spec({"assertions": [
        {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
         "check_inputs_from": {"have": "h", "need": "n"},
         "inputs": {"h": 1.0, "n": 0.5}, "status": "PASS"}]}, "probe",
        floor_problems, gate_structure=False)
    cases.append(("the mechanised-assertion floor fires on a short spec", any(
        "floor" in p for p in floor_problems)))
    cases.append(("an assertion recording no status is caught", any(
        "records no `status:`" in p for p in probe(
            {"id": "a", "check": "at-least",
             "check_inputs": {"have": 0.001, "need": 99.0}}))))

    # THE THREE DEFENCES THAT WERE PINNED BY NOTHING. An auditor deleted each
    # in turn with `--self-test` green and the real run green, restoring both
    # forgeries this file was written to close.
    STRUCT2 = structure_hash([
        {"id": "a", "check": "at-least",
         "check_inputs_from": {"have": "h", "need": "n"}}])
    def spec_probe(spec_extra, assertion, label="probe"):
        problems = []
        spec = {"assertions": [assertion]}
        spec.update(spec_extra)
        check_spec(spec, label, problems, minimum=0)
        return problems

    base_assertion = {
        "id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
        "check_inputs_from": {"have": "h", "need": "n"},
        "inputs": {"h": 1.0, "n": 0.5}, "status": "PASS"}
    cases.append(("a spec with no structure hash is caught", any(
        "records no `check_inputs_structure_hash`" in p
        for p in spec_probe({}, base_assertion))))
    cases.append(("a structure hash that does not match is caught", any(
        "A binding changed" in p for p in spec_probe(
            {"check_inputs_structure_hash": "sha256:" + "0" * 64},
            base_assertion))))
    cases.append(("a correct structure hash passes", not spec_probe(
        {"check_inputs_structure_hash": STRUCT2}, base_assertion)))
    cases.append(("a benchmark missing a MUST_MECHANISE assertion is caught", any(
        "must be mechanised" in p for p in _must_mechanise_probe())))
    # STATED LIMIT, not a case. An auditor scaled a term to 0.0025 * ta_c so a
    # 500 C ambient reported Tj = 123.05 C against a true 571.9 C. Perturbation
    # cannot catch that: the term DOES move the result, by about 1%, and a
    # gate cannot tell "small coefficient" from "legitimately small
    # contribution" without knowing the physics. What covers it is
    # `check_inputs_derived` being inside `structure_hash` -- editing the
    # formula moves the hash and needs a reviewed commit. The perturbation loop
    # catches inert terms (0*x, x-x); the hash catches rewritten ones. Tying
    # the tolerance to the operand rather than the result was still wrong and
    # is fixed, but it was never what stood between the tree and this attack.

    # WIRING, over the real entry point. Eight assertions because main() applies
    # MINIMUM_MECHANISED, and a wiring case that dodged the floor would not be
    # driving the shipped path.
    import contextlib, io, tempfile

    STRUCT = structure_hash([
        {"id": f"a{i}", "check": "at-least",
         "check_inputs_from": {"have": "h", "need": "n"}} for i in range(8)])

    def drive(have, need):
        body = f"check_inputs_structure_hash: {STRUCT}\n\nassertions:\n" + "".join(
            f"  - id: a{i}\n    check: at-least\n"
            f"    check_inputs: {{have: {have}, need: {need}}}\n"
            f"    check_inputs_from: {{have: h, need: n}}\n"
            f"    inputs: {{h: {have}, n: {need}}}\n    status: PASS\n"
            for i in range(8))
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            (case / "assertions.yaml").write_text(body, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return main([str(case)])

    planted, clean = drive(0.001, 99.0), drive(99.0, 0.001)
    cases.append(("main() exits 1 when a verdict does not follow", planted == 1))
    cases.append(("main() exits 0 when every verdict follows", clean == 0))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"hand-assert: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"hand-assert: self-test PASS: {len(cases)} cases.")
    return 0


# design.md figures that must equal an assertion operand. benchmark (c)'s
# design.md was ENTIRELY ungated -- an auditor changed every number in it at
# once with `make all` green, and it published `4.7 + 4.7 = 9.5` (dropping C2
# from the left side while keeping the sum) for as long as it existed. These
# are the load-bearing ones: each is a number the document offers as the
# margin a reader would act on.
DOC_FIGURES = {
    "esp32s3-devboard": (
        # (regex capturing the published number, assertion id, operand path)
        (r"VBUS-visible bulk capacitance[^=]*=\s*[\d.\s+]*=\s*\*\*([\d.]+) uF",
         "A8_usb_inrush_capacitance", "sum_parts", 1e-6),
        (r"Tj = \*\*([\d.]+) C\*\*", "A5_ldo_thermal_at_wifi_tx", "have", 1.0),
        (r"1 A rating gives ([\d.]+) mA margin", "A3_3v3_source_capability",
         "rating_margin_mA", 1.0),
    ),
}


def doc_problems(case_dir, spec, problems):
    """Hold design.md's published margins to the assertions that compute them."""
    figures = DOC_FIGURES.get(case_dir.name)
    if not figures:
        return 0
    doc = case_dir / "design.md"
    if not doc.is_file():
        problems.append(f"{case_dir.name}: has no design.md to reconcile")
        return 0
    text = doc.read_text(encoding="utf-8")
    by_id = {a.get("id"): a for a in (spec.get("assertions") or [])}
    checked = 0
    for pattern, assertion_id, operand, scale in figures:
        assertion = by_id.get(assertion_id)
        if assertion is None:
            problems.append(
                f"{case_dir.name}/design.md: cites {assertion_id}, which "
                "assertions.yaml no longer declares.")
            continue
        ci = assertion.get("check_inputs") or {}
        if operand == "sum_parts":
            want = sum(float(v) for v in ci.get("parts") or [])
        elif operand == "rating_margin_mA":
            # Margin over the WORST PEAK -- needs[0], worst_rail_a -- which is
            # what the sentence says ("608 mA margin over worst peak and 2x the
            # module's required"). My first version used max(needs), the
            # module's 0.5 A requirement, and reported the correct document as
            # wrong. The gate was the defect.
            want = (float(ci.get("have")) - float(ci.get("needs")[0])) * 1000.0
        else:
            want = float(ci.get(operand))
        found = re.search(pattern, text)
        if found is None:
            problems.append(
                f"{case_dir.name}/design.md: the figure for {assertion_id} is "
                "gone or reshaped, so it is checked by nothing. This document "
                "was entirely ungated until AMB-123.")
            continue
        shown = float(found.group(1)) * scale
        if abs(shown - want) > abs(want) * 1e-3 + 1e-12:
            problems.append(
                f"{case_dir.name}/design.md: publishes {found.group(1)} for "
                f"{assertion_id}, but the assertion's own inputs give "
                f"{want / scale:.6g}.")
            continue
        checked += 1
    if checked < len(figures):
        problems.append(
            f"{case_dir.name}/design.md: reconciled {checked} of "
            f"{len(figures)} published figure(s).")
    return checked


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    if argv and argv[0] == "--write":
        # The spec file documents this as the reviewed way to regenerate
        # check_inputs_structure_hash -- and it did not exist, so the stated
        # procedure for the freeze's own regeneration was a command that
        # printed usage and exited 2.
        if len(argv) != 2:
            print("usage: check-hand-assertions.py --write <benchmark-dir>",
                  file=sys.stderr)
            return 2
        case_dir = Path(argv[1])
        spec_path = case_dir / "assertions.yaml"
        try:
            spec = load_yaml(spec_path)
        except GateUnavailable as exc:
            print(f"hand-assert: UNAVAILABLE: {exc}", file=sys.stderr)
            return 2
        # VALIDATE BEFORE BLESSING. `--write` recomputed and rewrote the hash
        # without running check_spec, so it blessed specs the gate rejects --
        # including round 5's binding swap, a 1 mA LDO "supplying" a 99 A rail,
        # laundered into the committed hash in one command. That turns the
        # "deliberate, reviewed commit" defence into an edited line, which is
        # the exact thing structure_hash exists to prevent.
        problems = []
        check_spec(spec, case_dir.name, problems, gate_structure=False)
        if problems:
            print("hand-assert: REFUSING to write: the spec does not pass its "
                  "own checks, so blessing it would launder a defect into the "
                  "committed hash:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        digest = structure_hash(spec.get("assertions") or [])
        text = spec_path.read_text(encoding="utf-8")
        # SHOW WHAT CHANGED. A swap like `have: worst_rail_a` for
        # `have: ldo_rating_a` is arithmetically valid -- 99 >= max(0.001, 0.5)
        # is true -- so no check can call it wrong. What this tool must not do
        # is make it invisible. The bindings are printed so the reviewer of the
        # commit sees exactly which operand moved to which input.
        import re as _re
        previous = _re.search(r"check_inputs_structure_hash: (\S+)", text)
        if previous and previous.group(1) != digest:
            print(f"hand-assert: the operand-to-input bindings CHANGED "
                  f"({previous.group(1)[:23]}... -> {digest[:23]}...). Review "
                  "these before committing:")
            for assertion in spec.get("assertions") or []:
                origin = assertion.get("check_inputs_from")
                if origin:
                    print(f"  {assertion.get('id')}: {origin}")
                for operand, formula in (assertion.get("check_inputs_derived")
                                         or {}).items():
                    print(f"  {assertion.get('id')}: {operand} = {formula}")
        import re as _re
        if "check_inputs_structure_hash:" in text:
            text = _re.sub(r"check_inputs_structure_hash: \S+",
                           f"check_inputs_structure_hash: {digest}", text, count=1)
        else:
            text = f"check_inputs_structure_hash: {digest}\n\n" + text
        spec_path.write_text(text, encoding="utf-8")
        print(f"hand-assert: wrote check_inputs_structure_hash: {digest}")
        return 0
    if len(argv) != 1:
        print("usage: check-hand-assertions.py <benchmark-dir>", file=sys.stderr)
        return 2
    case_dir = Path(argv[0])
    spec_path = case_dir / "assertions.yaml"
    if not spec_path.is_file():
        print(f"hand-assert: FAIL: {case_dir.name} has no assertions.yaml", file=sys.stderr)
        return 1
    problems = []
    try:
        spec = load_yaml(spec_path)
        # TWO POPULATIONS, COUNTED SEPARATELY. These used to be summed into one
        # `checked` printed as "N assertion(s)", which was wrong twice over: 3
        # of the 11 were design.md figure reconciliations, not assertions, and a
        # single total means a new figure pays for a deleted assertion. That is
        # the increment-counting shape this audit has found repeatedly.
        asserts_checked = check_spec(spec, case_dir.name, problems)
        figures_checked = doc_problems(case_dir, spec, problems)
    except GateUnavailable as exc:
        print(f"hand-assert: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print(f"hand-assert: FAIL: {case_dir.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"hand-assert: PASS: {case_dir.name}: {asserts_checked} assertion(s) "
          f"follow from their inputs; {figures_checked} design.md figure(s) "
          "reconcile against them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
