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


# Which assertion input is a transcription of which voltage_at_ldo_input row.
# Named, not counted: a binding that can be deleted without a failure is not
# a binding. Extend this when a new assertion copies a propagated voltage.
# Every numeric input of every mechanised assertion, and where it comes
# from. Three hand-kept lists used to cover the transcriptions someone had
# noticed -- a list of today's known cases, not the population of them --
# and four more inputs (A1's rail interval, A3's worst rail load, A6's PTC
# hold current, A7's predicted deep-sleep current) were transcriptions of
# tree rows that answered to nothing (round 21). Every input is now
# classified as bound or explicitly not-from-tree, so a new one cannot
# arrive unclassified.
#
# A tree path is a dotted path into power-tree.yaml: a numeric leaf, a
# {min,max} pair for an interval input, or `<path>#<n>` for the n-th `= X`
# tail of a shown-work row.
REQUIRED_TREE_BINDINGS = {
    "esp32s3-devboard": {
        "A1_rail_voltage_containment/ldo_vout_v": "edges[3].vout_v",
        "A2_vbus_budget_t10/capability_a":
            "sources.usb_host.current_capability_a",
        "A2_vbus_budget_t10/sum_worst_a":
            "summary_per_mode.wifi_tx_peak.vbus_total_a#1",
        "A3_3v3_source_capability/ldo_rating_a": "edges[3].i_rating_a",
        "A3_3v3_source_capability/worst_rail_a":
            "summary_per_mode.wifi_tx_peak.p3v3_total_a#1",
        "A4_ldo_dropout_at_min_vbus/i_load_a":
            "summary_per_mode.wifi_tx_peak.p3v3_total_a#1",
        "A4_ldo_dropout_at_min_vbus/v_ldo_in_min_v":
            "voltage_at_ldo_input.worst_min#1",
        "A4_ldo_dropout_at_min_vbus/vdo_typ_v_per_a":
            "edges[3].dropout_v.typ_at_1a",
        "A4_ldo_dropout_at_min_vbus/vdo_guardband_v_per_a":
            "edges[3].dropout_v.guardband_v_per_a",
        "A4_ldo_dropout_at_min_vbus/vout_max_v": "edges[3].vout_v.max",
        "A5_ldo_thermal_at_wifi_tx/iq_a": "edges[3].iq_a",
        "A5_ldo_thermal_at_wifi_tx/typ.iout_a":
            "summary_per_mode.wifi_tx_peak.p3v3_total_a#0",
        "A5_ldo_thermal_at_wifi_tx/typ.vin_v":
            "voltage_at_ldo_input.nominal#0",
        "A5_ldo_thermal_at_wifi_tx/typ.vout_v": "edges[3].vout_v.nom",
        "A5_ldo_thermal_at_wifi_tx/worst.iout_a":
            "summary_per_mode.wifi_tx_peak.p3v3_total_a#1",
        "A5_ldo_thermal_at_wifi_tx/worst.vin_v":
            "voltage_at_ldo_input.max#1",
        "A5_ldo_thermal_at_wifi_tx/worst.vout_v": "edges[3].vout_v.min",
        "A6_ptc_hold_margin/hold_derated_a": "edges[0].hold_derated_50c_a",
        "A6_ptc_hold_margin/worst_a":
            "summary_per_mode.wifi_tx_peak.vbus_total_a#1",
        "A7_deep_sleep_rail_current/predicted_a":
            "summary_per_mode.deep_sleep.p3v3_total_a#0",
    },
}

# The rest, each with the source it does come from. Being on this list is a
# statement, not an exemption: it says a human checked that power-tree.yaml
# is not where this number lives.
INPUTS_NOT_FROM_TREE = {
    "esp32s3-devboard": {
        "A1_rail_voltage_containment/module_vdd33_v":
            "ESP32-S3-WROOM-1 datasheet VDD33 operating range",
        "A3_3v3_source_capability/module_required_a":
            "module datasheet Table 6-2 I_VDD min, a requirement on the "
            "supply rather than a tree quantity",
        "A5_ldo_thermal_at_wifi_tx/theta_ja_datasheet_c_w":
            "AP7361C DS37274 thermal table, minimum recommended pad",
        "A5_ldo_thermal_at_wifi_tx/tj_gate_c":
            "the design's own gate, below the datasheet limit",
        "A5_ldo_thermal_at_wifi_tx/typ.ta_c": "the typical ambient condition",
        "A5_ldo_thermal_at_wifi_tx/worst.ta_c": "the worst ambient condition",
        "A5_ldo_thermal_at_wifi_tx/worst.theta_ja_c_w":
            "the ~1 in^2 pour ASSUMPTION, stated as such in A5's caveat",
        "A7_deep_sleep_rail_current/gate_a": "the design's own sleep gate",
        "A8_usb_inrush_capacitance/c1_f": "parts.yaml C1 nominal",
        "A8_usb_inrush_capacitance/c2_f": "parts.yaml C2 nominal",
        "A8_usb_inrush_capacitance/c3_f": "parts.yaml C3 nominal",
        "A8_usb_inrush_capacitance/limit_f":
            "USB 2.0 downstream-port inrush limit",
    },
}

# The same binding for propagated voltages that a spec carries as the opening
# literal of a shown-work row rather than as an `inputs` key.
REQUIRED_TREE_ROW_HEADS = {
    "esp32s3-devboard": (
        ("A4_ldo_dropout_at_min_vbus",
         "secondary_rows.usbc_min_4p75_guardband", "usbc_min"),
        ("A4_ldo_dropout_at_min_vbus",
         "secondary_rows.nominal_5p00_typ_vdo", "nominal"),
    ),
}

# Every shown-work row that must be arithmetically true. A4's guardband row
# published `3.818 - 3.562 = +0.257 V` for two rounds after the current it
# derives from moved (the answer is 0.256), because shown work had no reader
# at all -- the "published number nothing checks" shape this audit keeps
# finding. Named rows, so deleting one is a failure, not a smaller check.
#
# The number beside each row is how many `A = B` claims it publishes. A row
# is allowed to go unread only in prose form, so a claim added in a form
# this cannot evaluate would otherwise arrive unchecked and invisible; the
# count makes that arrival a failure, the way the report-site counts do in
# the meta-gate. Re-derive it in the same commit that edits a row.
REQUIRED_SHOWN_WORK_ROWS = {
    "esp32s3-devboard": {
        "A10_single_pin_nets_l9b/inputs": 0,
        "A10_single_pin_nets_l9b/kind": 0,
        "A10_single_pin_nets_l9b/not_mechanisable": 0,
        "A10_single_pin_nets_l9b/result": 0,
        "A1_rail_voltage_containment/check_inputs_from.outer": 0,
        "A1_rail_voltage_containment/margin": 0,
        "A1_rail_voltage_containment/result": 0,
        "A2_vbus_budget_t10/calc": 1,
        "A2_vbus_budget_t10/kind": 0,
        "A2_vbus_budget_t10/margin": 0,
        "A3_3v3_source_capability/kind": 0,
        "A3_3v3_source_capability/margin": 0,
        "A3_3v3_source_capability/note": 0,
        "A4_ldo_dropout_at_min_vbus/calc_rows.datasheet_typ": 3,
        "A4_ldo_dropout_at_min_vbus/calc_rows.inhouse_guardband": 3,
        "A4_ldo_dropout_at_min_vbus/caveat": 0,
        "A4_ldo_dropout_at_min_vbus/secondary_rows.nominal_5p00_typ_vdo": 2,
        "A4_ldo_dropout_at_min_vbus/secondary_rows.usbc_min_4p75_guardband": 1,
        "A5_ldo_thermal_at_wifi_tx/calc_typ": 2,
        "A5_ldo_thermal_at_wifi_tx/calc_worst": 2,
        "A5_ldo_thermal_at_wifi_tx/calc_worst_datasheet_theta": 2,
        "A5_ldo_thermal_at_wifi_tx/caveat": 2,
        "A5_ldo_thermal_at_wifi_tx/inputs_not_gated.worst.theta_ja_c_w": 0,
        "A5_ldo_thermal_at_wifi_tx/margin": 0,
        "A6_ptc_hold_margin/margin": 0,
        "A7_deep_sleep_rail_current/kind": 0,
        "A7_deep_sleep_rail_current/margin": 0,
        "A8_usb_inrush_capacitance/caveat": 0,
        "A8_usb_inrush_capacitance/check_inputs_from.parts[0]": 0,
        "A8_usb_inrush_capacitance/check_inputs_from.parts[1]": 0,
        "A8_usb_inrush_capacitance/check_inputs_from.parts[2]": 0,
        "A8_usb_inrush_capacitance/note": 0,
        "A9_strapping_dc_state/inputs.gpio0": 0,
        "A9_strapping_dc_state/inputs.gpio45": 0,
        "A9_strapping_dc_state/not_mechanisable": 0,
        "A9_strapping_dc_state/result": 0,
    },
}

# Every power-tree row that publishes arithmetic, and how many claims it
# publishes. Both directions are enforced, so a new row cannot arrive
# unchecked and an old one cannot leave unnoticed. Re-derive a count in the
# same commit that edits its row.
REQUIRED_TREE_SHOWN_WORK = {
    "esp32s3-devboard": {
        "edges[0].id": 0,
        "edges[1].id": 0,
        "edges[2].id": 0,
        "edges[2].to": 0,
        "edges[3].from": 0,
        "edges[3].id": 0,
        "edges[3].to": 0,
        "edges[4].from": 0,
        "edges[4].id": 0,
        "edges[4].to": 0,
        "loads.esp32s3_module.modes.deep_sleep.source": 0,
        "loads.esp32s3_module.modes.idle_modem_sleep.source": 0,
        "loads.esp32s3_module.modes.light_sleep.source": 0,
        "loads.esp32s3_module.modes.wifi_rx.source": 0,
        "loads.esp32s3_module.modes.wifi_tx_peak.source": 0,
        "loads.esp32s3_module.node": 0,
        "loads.ldo_ground_current.node": 0,
        "loads.pullup_leakage.node": 0,
        "loads.pwr_led_d4.node": 0,
        "loads.status_led_d5.node": 0,
        "meta.guardband_policy": 0,
        "sources.usb_host.budget_assumption": 0,
        "sources.usb_host.note": 0,
        "sources.usb_host.type_c_vsafe5v_corner.p_ldo": 1,
        "sources.usb_host.type_c_vsafe5v_corner.tj_min_pad": 1,
        "sources.usb_host.type_c_vsafe5v_corner.tj_pour_62": 1,
        "sources.usb_host.type_c_vsafe5v_corner.v_ldo_in_max": 1,
        "sources.usb_host.voltage_max_basis": 0,
        "summary_per_mode.deep_sleep.margin_vs_500mA": 1,
        "summary_per_mode.deep_sleep.p3v3_total_a": 1,
        "summary_per_mode.deep_sleep.vbus_total_a": 1,
        "summary_per_mode.idle_modem_sleep.margin_vs_500mA": 0,
        "summary_per_mode.idle_modem_sleep.p3v3_total_a": 2,
        "summary_per_mode.idle_modem_sleep.vbus_total_a": 2,
        "summary_per_mode.light_sleep.margin_vs_500mA": 0,
        "summary_per_mode.light_sleep.p3v3_total_a": 1,
        "summary_per_mode.light_sleep.vbus_total_a": 1,
        "summary_per_mode.wifi_rx.margin_vs_500mA": 0,
        "summary_per_mode.wifi_rx.p3v3_total_a": 1,
        "summary_per_mode.wifi_rx.vbus_total_a": 1,
        "summary_per_mode.wifi_tx_peak.ldo_input_a": 1,
        "summary_per_mode.wifi_tx_peak.margin_vs_500mA": 0,
        "summary_per_mode.wifi_tx_peak.p3v3_total_a": 2,
        "summary_per_mode.wifi_tx_peak.vbus_total_a": 2,
        "voltage_at_ldo_input.max": 1,
        "voltage_at_ldo_input.nominal": 1,
        "voltage_at_ldo_input.usbc_min": 1,
        "voltage_at_ldo_input.worst_min": 1,
    },
}

# The unit tokens these documents write beside their numbers. Dropped
# wherever they appear so `0.500 A - 0.39531 A` is arithmetic; anything not
# on this list keeps its fragment unevaluable, which is the conservative
# direction -- a name this does not know stays prose rather than becoming a
# number by accident.
# ANY string carrying a number joins the checked population, not only one
# carrying an `=`. Four of the five T10 margin rows publish a derived
# headroom with no `=` in sight, so they could not even join, and the
# joining-direction guard never saw them (round 21). Prose rows sit at zero
# claims, which is the point: arithmetic cannot arrive in one unnoticed.
_DIGIT = re.compile(r"[0-9]")

_UNIT_TOKEN = re.compile(
    r"(?<=[\s(])(?:[munpk]?[AVWFHs]|ohm|R|C|K|Hz|kHz|MHz|ppm|%|dB|dBm)"
    r"(?=[\s)])")

_ARITHMETIC = re.compile(r"[\s()+\-*/.0-9eE]+")
_INNER_CLAIM = re.compile(r"\(([^()]*=[^()]*)\)")
_ANNOTATION = re.compile(r"\([^()]*\)")


def _tree_voltage_rows(power_text):
    """Each voltage_at_ldo_input row by name, from its shown work's `= X V`."""
    block = re.search(r"^voltage_at_ldo_input:\n((?:[ \t]+\S[^\n]*\n)+)",
                      power_text, re.M)
    rows = {}
    if block is None:
        return rows
    for name, shown in re.findall(r"^[ \t]+(\w+):\s*\"([^\"]*)\"",
                                  block.group(1), re.M):
        tail = re.search(r"=\s*([0-9.]+)\s*V\s*$", shown.strip())
        if tail:
            rows[name] = float(tail.group(1))
    return rows


def _eval_arith(text):
    """A shown-work fragment as a number, or None if it is not pure arithmetic.

    `x` is the multiplication sign these documents use; unit tokens are
    dropped WHEREVER they appear, not only at the end. Only at the end was
    enough to make `0.500 A - 0.39531 A = 9.99 A` unevaluable, and an
    unevaluable claim was a silent skip -- so writing units inside the
    expression, the style these documents already use, hid a falsehood in a
    row whose recorded claim count asserted full coverage (round 21).
    Nothing beyond numbers, the four operators and those units is accepted,
    so a fragment carrying prose still goes unchecked rather than guessed at.
    """
    import ast
    candidate = _UNIT_TOKEN.sub(" ", f" {text.strip()} ")
    candidate = candidate.replace(" x ", " * ").strip()
    if not candidate or not _ARITHMETIC.fullmatch(candidate):
        return None
    try:
        tree = ast.parse(candidate, mode="eval")
    except SyntaxError:
        return None
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub,
               ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Constant)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return None
        if isinstance(node, ast.Constant) and not isinstance(
                node.value, (int, float)):
            return None
    try:
        return float(eval(compile(tree, "<shown-work>", "eval"),
                          {"__builtins__": {}}, {}))
    except ArithmeticError:
        return None


def _split_top_level(text, sep="="):
    """Split on `sep` outside parentheses, so nested claims stay whole."""
    parts, depth, current = [], 0, []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _split_pieces(text):
    """Independent chains within one row: `;`, `->` and newlines, OUTSIDE
    parentheses. Splitting on a `;` inside a parenthesised sub-claim left an
    unbalanced `(` that swallowed every later `=` into one prose segment, so
    A5's published breach condition went unread (round 20)."""
    parts, depth, current, index = [], 0, [], 0
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (char in ";\n" or text[index:index + 2] == "->"):
            parts.append("".join(current))
            current = []
            index += 2 if text[index:index + 2] == "->" else 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _half_ulp(text):
    """Half the last significant digit of the value the fragment states.

    `+0.257` claims three decimals, so 0.256 is a different number; `90.5`
    claims one, so 90.548 is not. THE EXPONENT COUNTS: this read decimals
    off the mantissa alone and returned the tolerance in mantissa units
    while the compared value was scaled by 10^exp, so `281e-6` was checked
    to +/-0.5 A and `9.0e-6` to +/-0.05 A -- 15 of the 40 claims were being
    compared at between 1% and 555,556% of their own value once the power
    tree's engineering notation entered the population, and a 1400x error
    in a mode total passed (round 21)."""
    last = None
    for match in re.finditer(
            r"([0-9]+)(?:\.([0-9]+))?(?:[eE]([-+]?[0-9]+))?", text):
        if match.group(0):
            last = match
    if last is None:
        return 0.5
    decimals = len(last.group(2) or "")
    exponent = int(last.group(3) or 0)
    return 0.5 * 10 ** (exponent - decimals)


def _chain_problems(where, chain, problems):
    """One `A = B = C` chain. Every fragment that IS arithmetic must agree
    with the last one, to the precision the last one publishes."""
    fragments = _split_top_level(chain)
    values = [(text, _eval_arith(text)) for text in fragments]
    values = [(text, value) for text, value in values if value is not None]
    if len(values) < 2:
        return 0
    stated_text, stated = values[-1]
    tolerance = _half_ulp(stated_text)
    for text, value in values[:-1]:
        if abs(value - stated) > tolerance:
            problems.append(
                f"{where}: shown work states `{text.strip()} = "
                f"{stated_text.strip()}`, but {text.strip()} is "
                f"{value:.6g}, which does not round to {stated:g} at the "
                "precision the row publishes. A shown-work row that no "
                "longer follows from its own operands is a stale number.")
            return 0
    return 1


def _row_problems(where, text, problems):
    """A shown-work row: `;`, `->` and newlines separate independent chains;
    a parenthesised sub-claim is checked and then substituted by its value;
    a parenthesised annotation that is not arithmetic is dropped."""
    verified = 0
    for piece in _split_pieces(text):
        # A leading `typ:` / `worst:` / `max:` label is a name for the chain,
        # not part of it. The power tree writes its branches that way, and
        # leaving the label in made the whole chain unreadable -- an
        # unreadable chain is an unchecked one (round 20).
        working = re.sub(r"^\s*[A-Za-z_][A-Za-z0-9_ .-]*:\s*", "", piece)
        resolved = True
        while True:
            match = _INNER_CLAIM.search(working)
            if match is None:
                break
            # RECURSE, do not chain: a parenthesised claim can carry its
            # own `;`-separated branches, and treating the whole group as
            # one chain compared a Ta_max from one branch against the other
            # branch's answer.
            verified += _row_problems(f"{where} (sub-claim)",
                                      match.group(1), problems)
            stated = _eval_arith(_split_top_level(match.group(1))[-1])
            if stated is None:
                resolved = False
                break
            working = (f"{working[:match.start()]} {stated!r} "
                       f"{working[match.end():]}")
        if not resolved:
            continue
        working = _ANNOTATION.sub(
            lambda m: m.group(0) if _eval_arith(m.group(0)) is not None else " ",
            working)
        verified += _chain_problems(where, working, problems)
    return verified


# Every `margin:` an assertion publishes, and how it reconciles. "prose"
# says the figure is not a single slack this gate can recompute (a two-sided
# interval, a ratio, a pair of thermal bases) -- declared, not silently
# unread. Round 20 found every margin here replaceable with an arbitrary
# number, `make sim` green: the headroom figure a reader acts on.
REQUIRED_MARGINS = {
    "esp32s3-devboard": {
        "A1_rail_voltage_containment": "prose",
        "A2_vbus_budget_t10": "slack:limit:mA",
        "A3_3v3_source_capability": "slack:needs0:mA",
        "A5_ldo_thermal_at_wifi_tx": "prose",
        "A6_ptc_hold_margin": "slack:need:mA",
        "A7_deep_sleep_rail_current": "prose",
    },
}

_MARGIN_UNITS = {"uA": 1e-6, "mA": 1e-3, "A": 1.0, "mV": 1e-3, "V": 1.0,
                 "C": 1.0, "uF": 1e-6}


def margin_problems(spec, label, problems):
    """A published margin must be the slack the gate itself computes."""
    required = REQUIRED_MARGINS.get(label, {})
    published = {a.get("id"): a for a in spec.get("assertions") or []
                 if isinstance(a.get("margin"), str)}
    checked = 0
    for assertion_id, mode in required.items():
        assertion = published.get(assertion_id)
        if assertion is None:
            problems.append(
                f"{label}: {assertion_id} is named as publishing a margin "
                "and no longer does. Margins leave this population by "
                "review, not by being deleted.")
            continue
        if mode == "prose":
            continue
        _, operand, unit = mode.split(":")
        ci = assertion.get("check_inputs") or {}
        try:
            have = float(ci["have"])
            other = (float(ci["needs"][0]) if operand == "needs0"
                     else float(ci[operand]))
        except (KeyError, IndexError, TypeError, ValueError):
            problems.append(
                f"{label}/{assertion_id}: its margin is named as the slack "
                f"between have and {operand}, which check_inputs no longer "
                "records in a form this can read.")
            continue
        head = re.match(r"\s*([+-]?[0-9]*\.?[0-9]+)", assertion["margin"])
        if head is None:
            problems.append(
                f"{label}/{assertion_id}: margin no longer opens with a "
                "number, so the headroom it publishes reconciles against "
                "nothing.")
            continue
        stated = float(head.group(1)) * _MARGIN_UNITS[unit]
        slack = abs(have - other)
        if abs(stated - slack) > _half_ulp(head.group(1)) * _MARGIN_UNITS[unit]:
            problems.append(
                f"{label}/{assertion_id}: publishes a margin of "
                f"{head.group(1)} {unit}, but its own check_inputs give a "
                f"slack of {slack / _MARGIN_UNITS[unit]:.4g} {unit}. The "
                "headroom a reader acts on has to be the headroom the gate "
                "computes.")
        else:
            checked += 1
    for assertion_id in sorted(set(published) - set(required)):
        problems.append(
            f"{label}: {assertion_id} publishes a margin and is not in the "
            "checked population, so nothing reconciles it. Add it with how "
            "it reconciles, or as prose.")
    return checked


def _named_rows_problems(rows, required, label, where, problems):
    """Hold a set of shown-work rows to a named population, both directions.

    Leaving: a named row that is gone is a failure. Joining: a row that
    appears and is not named is a failure -- round 20's population closed
    the leaving direction only, so a new row could arrive unchecked, which
    is the same list-not-world shape as the deck-parameter floor. The count
    beside each name is how many `A = B` claims the row publishes, so a
    claim added in a form this cannot evaluate is a failure rather than a
    silent skip."""
    checked = 0
    for name, expected in required.items():
        if name not in rows:
            problems.append(
                f"{label}: {where} row {name} is named as checked arithmetic "
                "and is not in the file. Rows leave this population by "
                "review, not by being deleted.")
            continue
        verified = _row_problems(f"{label}/{name}", rows[name], problems)
        if verified != expected:
            problems.append(
                f"{label}: {where} row {name} publishes {verified} readable "
                f"claim(s), not the recorded {expected}. A claim this gate "
                "cannot evaluate is a claim nothing checks; re-derive the "
                "count in the commit that edits the row.")
        checked += verified
    for name in sorted(set(rows) - set(required)):
        problems.append(
            f"{label}: {where} row {name} publishes arithmetic and is not in "
            "the checked population, so nothing recomputes it. Add it with "
            "its claim count.")
    return checked


def shown_work_problems(spec, label, problems):
    """Every shown-work row in the spec, held to the named population."""
    # ANY string field that carries arithmetic, not a key-prefix list:
    # `caveat:` published a full equation (`Ta_max = 125 - 0.654 x 110 =
    # 53.1 C`) that the calc*/secondary_rows population could not see
    # (round 20). Same walk as the power tree's.
    rows = {}
    for assertion in spec.get("assertions") or []:
        ident = assertion.get("id")

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{path}.{key}" if path else str(key))
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")
            elif isinstance(node, str) and _DIGIT.search(node):
                rows[f"{ident}/{path}"] = node

        for key, value in sorted(assertion.items()):
            if key in ("id", "expr", "check_inputs_derived"):
                # `expr` is the relation itself, re-evaluated by check_spec;
                # check_inputs_derived is a formula over input NAMES, not
                # arithmetic over literals.
                continue
            walk(value, key)
    return _named_rows_problems(
        rows, REQUIRED_SHOWN_WORK_ROWS.get(label, {}), label, "shown-work",
        problems)


def tree_shown_work_problems(tree, label, problems):
    """The power tree's OWN derivations, not just their `= X V` tails.

    Round 19 gave assertions.yaml's shown work a reader and stopped one file
    short: power-tree.yaml publishes the same kind of derivation -- the mode
    totals and the voltage propagation validation.log calls this benchmark's
    original evidence -- and only the trailing result was read, so a row
    could state work its own operands do not produce (round 20). Same
    machinery, same named-population discipline."""
    rows = {}

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and _DIGIT.search(node):
            rows[path] = node

    walk(tree, "")
    return _named_rows_problems(
        rows, REQUIRED_TREE_SHOWN_WORK.get(label, {}), label, "power-tree",
        problems)


# Every mode whose power-tree row publishes a T10 margin, and how many
# figures that row publishes. Round 20 closed "every margin is replaceable
# with any number" for assertions.yaml and stopped at that file; the tree
# publishes the same headroom, including the benchmark's own "-> T10 PASS"
# verdict, and none of it was read (round 21). Four of the five rows carry
# no `=` at all, so they could not even join the shown-work population.
REQUIRED_TREE_MARGINS = {
    "esp32s3-devboard": {
        "deep_sleep": 1,
        "light_sleep": 1,
        "idle_modem_sleep": 2,
        "wifi_rx": 1,
        "wifi_tx_peak": 2,
    },
}


# What each summation row's operands ARE, term by term. The data layer
# (loads/edges/sources) was read by nothing: every summation restated the
# declared currents as bare literals, so the table and the arithmetic that
# claims to sum it could contradict each other with every gate green (round
# 21). A term is either a dotted path into the tree, or an explicit
# (value, reason) pair for a figure that deliberately differs from the
# declared load -- there are three, and each says why here.
_LED_AT_VBUS = (0.00325, "the P5V0 LED taken at VBUS max instead of at the "
                         "node where it is declared; conservative by "
                         "~0.35 mA and the basis A2's margin is quoted "
                         "against")
_NO_PULLUP = "the 1 uA pull-up leakage is dropped at this magnitude"
REQUIRED_TREE_SUMMATIONS = {
    "esp32s3-devboard": {
        "deep_sleep.p3v3_total_a#0": (
            "loads.esp32s3_module.modes.deep_sleep.i_a",
            "loads.status_led_d5.modes.deep_sleep.i_a",
            "loads.pullup_leakage.modes.all.i_a"),
        "light_sleep.p3v3_total_a#0": (
            "loads.esp32s3_module.modes.light_sleep.i_a",
            "loads.status_led_d5.modes.light_sleep.i_a",
            "loads.pullup_leakage.modes.all.i_a"),
        "idle_modem_sleep.p3v3_total_a#0": (
            "loads.esp32s3_module.modes.idle_modem_sleep.i_a.typ",
            "loads.status_led_d5.modes.idle_modem_sleep.i_a",
            "loads.pullup_leakage.modes.all.i_a"),
        "idle_modem_sleep.p3v3_total_a#1": (
            "loads.esp32s3_module.modes.idle_modem_sleep.i_a.max",
            "loads.status_led_d5.modes.idle_modem_sleep.i_a"),
        "wifi_rx.p3v3_total_a#0": (
            "loads.esp32s3_module.modes.wifi_rx.i_a",
            "loads.status_led_d5.modes.wifi_rx.i_a",
            "loads.pullup_leakage.modes.all.i_a"),
        "wifi_tx_peak.p3v3_total_a#0": (
            "loads.esp32s3_module.modes.wifi_tx_peak.i_a.typ",
            "loads.status_led_d5.modes.wifi_tx_peak.i_a",
            "loads.pullup_leakage.modes.all.i_a"),
        "wifi_tx_peak.p3v3_total_a#1": (
            "loads.esp32s3_module.modes.wifi_tx_peak.i_a.worst",
            "loads.status_led_d5.modes.wifi_tx_peak.i_a"),
        "deep_sleep.vbus_total_a#0": (
            "@deep_sleep.p3v3_total_a#0",
            "loads.ldo_ground_current.modes.all.i_a",
            "loads.pwr_led_d4.modes.all.i_a",
            "loads.tvs_esd_leakage.modes.all.i_a"),
        "light_sleep.vbus_total_a#0": (
            "@light_sleep.p3v3_total_a#0",
            "loads.ldo_ground_current.modes.all.i_a",
            "loads.pwr_led_d4.modes.all.i_a",
            "loads.tvs_esd_leakage.modes.all.i_a"),
        "idle_modem_sleep.vbus_total_a#0": (
            "@idle_modem_sleep.p3v3_total_a#0",
            "loads.ldo_ground_current.modes.all.i_a",
            "loads.pwr_led_d4.modes.all.i_a",
            "loads.tvs_esd_leakage.modes.all.i_a"),
        "idle_modem_sleep.vbus_total_a#1": (
            "@idle_modem_sleep.p3v3_total_a#1",
            "loads.ldo_ground_current.modes.all.i_a",
            _LED_AT_VBUS,
            "loads.tvs_esd_leakage.modes.all.i_a"),
        "wifi_rx.vbus_total_a#0": (
            "@wifi_rx.p3v3_total_a#0",
            "loads.ldo_ground_current.modes.all.i_a",
            "loads.pwr_led_d4.modes.all.i_a",
            "loads.tvs_esd_leakage.modes.all.i_a"),
        "wifi_tx_peak.ldo_input_a#0": (
            "@wifi_tx_peak.p3v3_total_a#0",
            "loads.ldo_ground_current.modes.all.i_a"),
        "wifi_tx_peak.vbus_total_a#0": (
            "@wifi_tx_peak.ldo_input_a#0",
            "loads.pwr_led_d4.modes.all.i_a",
            "loads.tvs_esd_leakage.modes.all.i_a"),
        "wifi_tx_peak.vbus_total_a#1": (
            "@wifi_tx_peak.ldo_input_a#1",
            _LED_AT_VBUS,
            "loads.tvs_esd_leakage.modes.all.i_a"),
    },
}
# Branches whose operand list is a single carried-forward result, with
# nothing to sum: named so they are declared rather than silently skipped.
_CARRIED_FORWARD = {
    "wifi_tx_peak.ldo_input_a#1",
    # A margin, not a summation: tree_margin_problems reconciles it against
    # the mode's own total and the declared source capability.
    "deep_sleep.margin_vs_500mA#0",
}


def tree_summation_problems(tree, label, problems):
    """Each summation's terms must BE the loads the data layer declares."""
    required = REQUIRED_TREE_SUMMATIONS.get(label, {})
    modes = tree.get("summary_per_mode") or {}
    rows = {}
    for mode, row in modes.items():
        if not isinstance(row, dict):
            continue
        for key, text in row.items():
            if not isinstance(text, str) or "=" not in text:
                continue
            for index, branch in enumerate(text.split(";")):
                rows[f"{mode}.{key}#{index}"] = branch
    checked = 0
    for name, terms in required.items():
        branch = rows.get(name)
        if branch is None:
            problems.append(
                f"{label}: summation {name} is named as summing declared "
                "loads and is no longer in the tree.")
            continue
        want = []
        for term in terms:
            if isinstance(term, tuple):
                want.append(float(term[0]))
            elif term.startswith("@"):
                carried = rows.get(term[1:])
                if carried is None:
                    problems.append(
                        f"{label}: {name} carries forward {term[1:]}, which "
                        "is not in the tree.")
                    want = None
                    break
                # A branch that only carries a value forward -- `worst:
                # 391.66e-3` -- states it without an `=`; its result is the
                # number itself.
                tail = re.findall(
                    r"=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)", carried) or \
                    re.findall(r"[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?",
                               carried)
                want.append(float(tail[-1]))
            else:
                try:
                    want.append(_tree_value(tree, term))
                except (KeyError, IndexError, ValueError) as exc:
                    problems.append(
                        f"{label}: {name} sums {term}, which no longer "
                        f"resolves ({exc}).")
                    want = None
                    break
        if want is None:
            continue
        shown = [float(x) for x in re.findall(
            r"[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?",
            re.sub(r"^\s*\w+:\s*", "", branch.split("=")[0]))]
        if len(shown) != len(want) or any(
                abs(a - b) > max(5e-4 * abs(b), 5e-9)
                for a, b in zip(shown, want)):
            problems.append(
                f"{label}: summation {name} shows terms {shown} where the "
                f"loads it is declared to sum are {want}. A total that "
                "restates its inputs as literals can drift from the table "
                "it claims to sum.")
        else:
            checked += 1
    for name in sorted(set(rows) - set(required) - _CARRIED_FORWARD):
        problems.append(
            f"{label}: summation {name} is not declared as summing anything, "
            "so its terms answer to no load in the data layer.")
    return checked


def tree_margin_problems(tree, label, problems):
    """Each published T10 margin must be capability minus that mode's total.

    Both the milliamp figure and the percentage, branch by branch, against
    the mode's own vbus_total_a row and the source's declared capability --
    so a re-derived total has to move the margin beside it, and the verdict
    the row states has to follow from the numbers in it."""
    required = REQUIRED_TREE_MARGINS.get(label, {})
    modes = (tree.get("summary_per_mode") or {})
    published = {name: row["margin_vs_500mA"]
                 for name, row in modes.items()
                 if isinstance(row, dict)
                 and isinstance(row.get("margin_vs_500mA"), str)}
    capability = (((tree.get("sources") or {}).get("usb_host") or {})
                  .get("current_capability_a"))
    if capability is None:
        problems.append(
            f"{label}: power-tree.yaml no longer declares the source's "
            "current_capability_a, so every published margin is measured "
            "against nothing.")
        return 0
    capability_ma = float(capability) * 1000.0
    checked = 0
    for mode, expected in required.items():
        text = published.get(mode)
        if text is None:
            problems.append(
                f"{label}: {mode} is named as publishing a T10 margin and "
                "no longer does. Margins leave this population by review, "
                "not by being deleted.")
            continue
        totals = [float(x) for x in re.findall(
            r"=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)",
            (modes[mode] or {}).get("vbus_total_a") or "")]
        figures = re.findall(
            r"([-+]?[0-9.]+)\s*mA\s*\(([-+]?[0-9.]+)\s*%\)", text)
        if len(figures) != expected:
            problems.append(
                f"{label}/{mode}: publishes {len(figures)} margin figure(s), "
                f"not the recorded {expected}. A figure this gate cannot "
                "read is a figure nothing checks.")
            continue
        if len(totals) != len(figures):
            problems.append(
                f"{label}/{mode}: publishes {len(figures)} margin figure(s) "
                f"against {len(totals)} VBUS total(s); they are branch for "
                "branch, so a total without its margin is drift waiting to "
                "happen.")
            continue
        for (stated_ma, stated_pct), total in zip(figures, totals):
            want_ma = capability_ma - total * 1000.0
            want_pct = 100.0 * want_ma / capability_ma
            if abs(float(stated_ma) - want_ma) > _half_ulp(stated_ma):
                problems.append(
                    f"{label}/{mode}: publishes a margin of {stated_ma} mA "
                    f"where its own VBUS total of {total * 1000:.4g} mA "
                    f"against {capability_ma:g} mA leaves {want_ma:.4g} mA.")
            elif abs(float(stated_pct) - want_pct) > _half_ulp(stated_pct):
                problems.append(
                    f"{label}/{mode}: publishes {stated_pct}% where "
                    f"{want_ma:.4g} mA of {capability_ma:g} mA is "
                    f"{want_pct:.4g}%.")
            else:
                checked += 1
        if "T10 PASS" in text and any(
                capability_ma - total * 1000.0 <= 0 for total in totals):
            problems.append(
                f"{label}/{mode}: states T10 PASS while one of its own "
                "totals leaves no margin against the source capability.")
    for mode in sorted(set(published) - set(required)):
        problems.append(
            f"{label}/{mode}: publishes a T10 margin and is not in the "
            "checked population, so nothing reconciles it.")
    return checked


def _tree_value(tree, path):
    """A numeric leaf, a {min,max} interval, or the n-th `= X` tail of a
    shown-work row, addressed by dotted path with `[i]` for list members and
    a trailing `#n` for a row's n-th derived result."""
    row_index = None
    if "#" in path:
        path, _, index = path.partition("#")
        row_index = int(index)
    node = tree
    for part in path.split("."):
        while "[" in part:
            head, _, rest = part.partition("[")
            if head:
                node = node[head]
            index, _, part = rest.partition("]")
            node = node[int(index)]
        if part:
            node = node[part]
    if row_index is not None:
        if not isinstance(node, str):
            raise ValueError(f"{path} is not a shown-work row")
        tails = re.findall(r"=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)", node)
        return float(tails[row_index])
    if isinstance(node, dict) and "min" in node and "max" in node:
        return [float(node["min"]), float(node["max"])]
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return float(node)
    raise ValueError(f"{path} is not a number, interval or shown-work row")


def power_tree_problems(spec, power_text, label, problems, tree=None):
    """The power tree's own summary arithmetic must agree with A2/A6.

    check_spec holds each assertion to its recorded inputs; the inputs come
    from power-tree.yaml, and nothing held the two files together -- round 18
    changed the tree's TVS leakage and this gate stayed green while A2 still
    carried the old sum. The tree's wifi_tx_peak worst VBUS total (the `=`
    tail of its own shown-work string) must equal the sum A2 and A6 gate on.
    Returns the number of cross-file agreements verified."""
    found = re.search(
        r"wifi_tx_peak:.*?vbus_total_a:[^\n]*worst:[^=\n]*=\s*([0-9.eE+-]+)",
        power_text, re.S)
    if found is None:
        problems.append(
            f"{label}: power-tree.yaml no longer shows the wifi_tx_peak "
            "worst VBUS total in the form this gate reads, so the tree and "
            "the assertions can drift apart silently.")
        return 0
    tree_total = float(found.group(1))
    checked = 0
    for assertion in spec.get("assertions") or []:
        inputs = assertion.get("inputs") or {}
        for key in ("sum_worst_a", "worst_a"):
            if key in inputs:
                recorded = float(inputs[key])
                if abs(recorded - tree_total) > 1e-9:
                    problems.append(
                        f"{label}/{assertion.get('id')}: records "
                        f"{key} = {recorded:g} but power-tree.yaml's own "
                        f"summary computes {tree_total:g}. Two files "
                        "publishing the same quantity must agree; this is "
                        "the drift the round-18 TVS correction exposed.")
                else:
                    checked += 1
    if checked == 0:
        problems.append(
            f"{label}: no assertion records sum_worst_a/worst_a for the "
            "power tree's total to reconcile against; the cross-file check "
            "is comparing nothing.")
    # EVERY INPUT, CLASSIFIED. Not a list of the transcriptions someone
    # noticed: each numeric input is either bound to the tree path it copies
    # or named as coming from somewhere else, so a new input arrives
    # unclassified and fails rather than arriving unchecked.
    bindings = REQUIRED_TREE_BINDINGS.get(label, {})
    exempt = INPUTS_NOT_FROM_TREE.get(label, {})
    for assertion in spec.get("assertions") or []:
        ident = assertion.get("id")
        if ident not in MUST_MECHANISE.get(label, ()):
            continue
        flat = {}
        _flatten(assertion.get("inputs") or {}, "", flat)
        for key in sorted(flat):
            name = f"{ident}/{key}"
            if name in exempt:
                continue
            if name not in bindings:
                problems.append(
                    f"{label}: input {name} is classified neither as a copy "
                    "of a power-tree.yaml value nor as coming from "
                    "elsewhere. Every input is one or the other; an "
                    "unclassified one is a transcription nothing checks.")
                continue
            try:
                want = _tree_value(tree, bindings[name])
            except (KeyError, IndexError, ValueError) as exc:
                problems.append(
                    f"{label}: {name} is bound to power-tree.yaml's "
                    f"{bindings[name]}, which no longer resolves ({exc}).")
                continue
            recorded = flat[key]
            if isinstance(recorded, list) or isinstance(want, list):
                pair = want if isinstance(want, list) else [want]
                got = recorded if isinstance(recorded, list) else [recorded]
                agree = (len(pair) == len(got)
                         and all(abs(a - b) <= 5e-4 for a, b in zip(got, pair)))
            else:
                agree = abs(recorded - want) <= 5e-4
            if not agree:
                problems.append(
                    f"{label}/{ident}: records {key} = {recorded!r} but "
                    f"power-tree.yaml's {bindings[name]} is {want!r}. Two "
                    "files publishing one quantity must agree.")
            else:
                checked += 1
    for name in sorted(set(bindings) & set(exempt)):
        problems.append(
            f"{label}: input {name} is both bound to the tree and named as "
            "coming from elsewhere; it is one or the other.")

    rows = _tree_voltage_rows(power_text)
    # THE SAME BINDING FOR VOLTAGES THAT LIVE IN SHOWN WORK RATHER THAN IN
    # `inputs`. A4's secondary rows open with usbc_min and nominal as bare
    # literals; the shown-work reader proves each row is self-consistent,
    # which is exactly why a re-derived usbc_min left A4 publishing a
    # perfectly consistent margin computed from a voltage the tree no longer
    # derives (round 20) -- the fourth of the four propagated voltages, in
    # the fix written to close the first three.
    for assertion_id, row_key, row_name in REQUIRED_TREE_ROW_HEADS.get(
            label, ()):
        assertion = next((a for a in spec.get("assertions") or []
                          if a.get("id") == assertion_id), None)
        family, _, member = row_key.partition(".")
        text = ((assertion or {}).get(family) or {}).get(member)
        if not isinstance(text, str):
            problems.append(
                f"{label}: {assertion_id}'s {row_key} is named as opening "
                f"with power-tree.yaml's {row_name} voltage and is not in "
                "the spec; a cross-file binding cannot be dropped by "
                "deleting one side.")
            continue
        if row_name not in rows:
            problems.append(
                f"{label}: power-tree.yaml no longer derives a "
                f"voltage_at_ldo_input {row_name} row in the form this gate "
                f"reads, so {assertion_id}'s {row_key} can drift from the "
                "tree silently.")
            continue
        head = re.match(r"\s*([0-9]*\.?[0-9]+)", text)
        if head is None:
            problems.append(
                f"{label}/{assertion_id}: {row_key} no longer opens with a "
                f"number, so its copy of the {row_name} voltage is "
                "unreadable and reconciles against nothing.")
            continue
        if abs(float(head.group(1)) - rows[row_name]) > 5e-4:
            problems.append(
                f"{label}/{assertion_id}: {row_key} opens at "
                f"{float(head.group(1)):g} V but power-tree.yaml's "
                f"{row_name} propagation derives {rows[row_name]:g} V. A "
                "self-consistent row computed from a superseded voltage is "
                "the drift this binding exists to catch.")
        else:
            checked += 1
    return checked


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

    # THE CROSS-FILE LEG, each direction. Round 18 changed the power tree's
    # TVS leakage and this gate stayed green while A2 carried the old sum.
    TREE = ('summary_per_mode:\n  wifi_tx_peak:\n'
            '    vbus_total_a:  "typ: 1 = 2 ; worst: 3 + 4 = 0.395"\n')
    TSPEC = {"assertions": [{"id": "A2", "inputs": {"sum_worst_a": 0.395}}]}
    agree = []
    agreed = power_tree_problems(TSPEC, TREE, "probe", agree)
    cases.append(("a tree total agreeing with the assertions reconciles",
                  agreed == 1 and not agree))
    drift = []
    power_tree_problems({"assertions": [{"id": "A2", "inputs":
                                         {"sum_worst_a": 0.394}}]},
                        TREE, "probe", drift)
    cases.append(("a tree total the assertions no longer match is caught",
                  any("must agree" in x for x in drift)))
    gone = []
    power_tree_problems(TSPEC, "no summary here", "probe", gone)
    cases.append(("a tree that stops showing its total is caught",
                  any("form this gate reads" in x for x in gone)))
    orphan = []
    power_tree_problems({"assertions": [{"id": "A1", "inputs": {}}]},
                        TREE, "probe", orphan)
    cases.append(("a spec with nothing to reconcile is caught",
                  any("comparing nothing" in x for x in orphan)))
    # EVERY INPUT CLASSIFIED, and the tree paths they copy. Three
    # hand-kept lists covered the transcriptions someone had noticed; four
    # more inputs were transcriptions of tree rows answering to nothing.
    VTREE = TREE + ('voltage_at_ldo_input:\n'
                    '  worst_min: "4.4 - 0.1 - 0.1 = 4.4 - 0.2 = 4.200 V"\n'
                    '  max:       "5.25 - 0.05 = 5.200 V"\n')
    PTREE = {"edges": [{"vout_v": {"min": 3.2, "max": 3.4, "nom": 3.3}}],
             "voltage_at_ldo_input": {"worst_min": "4.4 - 0.2 = 4.200 V"},
             "sources": {"usb_host": {"current_capability_a": 0.5}}}
    cases.append(("a tree numeric leaf resolves",
                  _tree_value(PTREE, "edges[0].vout_v.max") == 3.4))
    cases.append(("a min/max pair resolves as an interval",
                  _tree_value(PTREE, "edges[0].vout_v") == [3.2, 3.4]))
    cases.append(("a shown-work row's n-th result resolves",
                  _tree_value(PTREE, "voltage_at_ldo_input.worst_min#0")
                  == 4.2))
    _real_bind, _real_exempt = REQUIRED_TREE_BINDINGS, INPUTS_NOT_FROM_TREE
    _real_must = MUST_MECHANISE
    globals()["MUST_MECHANISE"] = {"probe": ("A4",)}
    globals()["REQUIRED_TREE_BINDINGS"] = {"probe": {
        "A4/v_ldo_in_min_v": "voltage_at_ldo_input.worst_min#0"}}
    globals()["INPUTS_NOT_FROM_TREE"] = {"probe": {
        "A4/vout_max_v": "the LDO datasheet"}}
    try:
        BSPEC = {"assertions": [
            {"id": "A2", "inputs": {"sum_worst_a": 0.395}},
            {"id": "A4", "inputs": {"v_ldo_in_min_v": 4.200,
                                    "vout_max_v": 3.366}}]}
        b_ok = []
        b_n = power_tree_problems(BSPEC, VTREE, "probe", b_ok, tree=PTREE)
        cases.append(("a bound input agreeing with the tree reconciles",
                      b_n == 2 and not b_ok))
        b_drift = []
        power_tree_problems(
            {"assertions": [{"id": "A2", "inputs": {"sum_worst_a": 0.395}},
                            {"id": "A4", "inputs": {"v_ldo_in_min_v": 4.100,
                                                    "vout_max_v": 3.366}}]},
            VTREE, "probe", b_drift, tree=PTREE)
        cases.append(("a bound input the tree contradicts is caught",
                      any("must agree" in x for x in b_drift)))
        b_new = []
        power_tree_problems(
            {"assertions": [{"id": "A2", "inputs": {"sum_worst_a": 0.395}},
                            {"id": "A4", "inputs": {"v_ldo_in_min_v": 4.200,
                                                    "vout_max_v": 3.366,
                                                    "surprise_a": 1.0}}]},
            VTREE, "probe", b_new, tree=PTREE)
        cases.append(("an UNCLASSIFIED input is caught",
                      any("classified neither" in x for x in b_new)))
        b_gone = []
        power_tree_problems(BSPEC, VTREE, "probe", b_gone, tree={"edges": []})
        cases.append(("a binding whose tree path vanished is caught",
                      any("no longer resolves" in x for x in b_gone)))
        globals()["INPUTS_NOT_FROM_TREE"] = {"probe": {
            "A4/vout_max_v": "the LDO datasheet",
            "A4/v_ldo_in_min_v": "both at once"}}
        b_both = []
        power_tree_problems(BSPEC, VTREE, "probe", b_both, tree=PTREE)
        cases.append(("an input both bound and exempt is caught",
                      any("it is one or the other" in x for x in b_both)))
    finally:
        globals()["REQUIRED_TREE_BINDINGS"] = _real_bind
        globals()["INPUTS_NOT_FROM_TREE"] = _real_exempt
        globals()["MUST_MECHANISE"] = _real_must

    # A PROPAGATED VOLTAGE CARRIED AS A SHOWN-WORK ROW'S OPENING LITERAL
    # rather than as an input: usbc_min was the fourth of the four and
    # answered to nothing, so re-deriving it left A4 publishing a
    # self-consistent margin from a superseded voltage.
    _real_heads = REQUIRED_TREE_ROW_HEADS
    _real_must2 = MUST_MECHANISE
    globals()["MUST_MECHANISE"] = {"probe": ()}
    globals()["REQUIRED_TREE_ROW_HEADS"] = {
        "probe": (("A4", "secondary_rows.u", "max"),)}
    try:
        HTREE = TREE + ('voltage_at_ldo_input:\n'
                        '  max:       "5.25 - 0.05 = 5.200 V"\n')
        HSPEC = {"assertions": [
            {"id": "A2", "inputs": {"sum_worst_a": 0.395}},
            {"id": "A4", "secondary_rows": {"u": "5.200 - 1.0 = +4.200 V"}}]}
        h_ok = []
        cases.append(("a row head matching its tree row reconciles",
                      power_tree_problems(HSPEC, HTREE, "probe", h_ok) == 2
                      and not h_ok))
        h_drift = []
        power_tree_problems(
            {"assertions": [
                {"id": "A2", "inputs": {"sum_worst_a": 0.395}},
                {"id": "A4",
                 "secondary_rows": {"u": "5.100 - 1.0 = +4.100 V"}}]},
            HTREE, "probe", h_drift)
        cases.append(("a row head the tree no longer derives is caught",
                      any("superseded voltage" in x for x in h_drift)))
        h_gone = []
        power_tree_problems(
            {"assertions": [{"id": "A2", "inputs": {"sum_worst_a": 0.395}},
                            {"id": "A4"}]}, HTREE, "probe", h_gone)
        cases.append(("deleting the row a head binding names is caught",
                      any("is named as opening with" in x for x in h_gone)))
        h_prose = []
        power_tree_problems(
            {"assertions": [
                {"id": "A2", "inputs": {"sum_worst_a": 0.395}},
                {"id": "A4", "secondary_rows": {"u": "about five volts"}}]},
            HTREE, "probe", h_prose)
        cases.append(("a row head that stops being a number is caught",
                      any("no longer opens with a number" in x
                          for x in h_prose)))
        h_norow = []
        power_tree_problems(HSPEC, TREE, "probe", h_norow)
        cases.append(("a tree that stops deriving a head's row is caught",
                      any("can drift from the tree silently" in x
                          for x in h_norow)))
    finally:
        globals()["REQUIRED_TREE_ROW_HEADS"] = _real_heads
        globals()["MUST_MECHANISE"] = _real_must2

    # SHOWN WORK. A4's guardband row published an answer its own operands
    # stopped producing; nothing read shown work at all until round 19.
    _real_rows = REQUIRED_SHOWN_WORK_ROWS
    globals()["REQUIRED_SHOWN_WORK_ROWS"] = {"probe": {"A4/calc_rows.g": 1}}
    try:
        good = []
        n_good = shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "margin = 3.818 - 3.562 = +0.256 V"}}]}, "probe", good)
        cases.append(("a shown-work row that recomputes is counted",
                      n_good == 1 and not good))
        stale = []
        shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "margin = 3.818 - 3.562 = +0.257 V"}}]}, "probe", stale)
        cases.append(("the exact stale margin round 19 found is caught",
                      any("does not round to 0.257" in x for x in stale)))
        coarse = []
        n_coarse = shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "Tj = 50 + 0.654 x 62 = 90.5 C"}}]}, "probe", coarse)
        cases.append(("a row rounds at the precision IT publishes, not more",
                      n_coarse == 1 and not coarse))
        annotated = []
        n_annot = shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "0.39166 (LDO in) + 0.00325 (PWR LED @5.25V) + 400e-6 "
                     "(TVS IR max) = 0.39531 A"}}]}, "probe", annotated)
        cases.append(("parenthesised prose is dropped, not guessed at",
                      n_annot == 1 and not annotated))
        inner = []
        shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "4.585 - (3.300 + 0.34 x 0.356 = 3.521) = +1.064 V"}}]},
            "probe", inner)
        cases.append(("a false sub-claim inside parentheses is caught",
                      any("(sub-claim)" in x for x in inner)))
        prose = []
        shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "the 3 mV margin = comfortable"}}]}, "probe", prose)
        cases.append(("a named row that stops being readable is caught",
                      any("publishes 0 readable claim(s)" in x
                          for x in prose)))
        gained = []
        shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "margin = 3.818 - 3.562 = +0.256 V; and a second "
                     "claim = 1 + 1 = 2"}}]}, "probe", gained)
        cases.append(("a row that GAINS a claim past its recorded count "
                      "is caught",
                      any("not the recorded 1" in x for x in gained)))
        absent = []
        shown_work_problems({"assertions": [{"id": "A4"}]}, "probe", absent)
        cases.append(("deleting a named shown-work row is caught",
                      any("named as checked arithmetic" in x
                          for x in absent)))
        joined = []
        shown_work_problems(
            {"assertions": [{"id": "A4", "calc_rows": {
                "g": "margin = 3.818 - 3.562 = +0.256 V",
                "sneaky": "1 + 1 = 3 V"}}]}, "probe", joined)
        cases.append(("a row JOINING outside the population is caught",
                      any("not in the checked population" in x
                          for x in joined)))
    finally:
        globals()["REQUIRED_SHOWN_WORK_ROWS"] = _real_rows

    # THE POWER TREE'S OWN DERIVATIONS. Round 19 gave assertions.yaml a
    # reader and stopped one file short; the tree publishes the same kind of
    # work and only its `= X V` tail was read.
    _real_tree_rows = REQUIRED_TREE_SHOWN_WORK
    globals()["REQUIRED_TREE_SHOWN_WORK"] = {"probe": {"v.worst_min": 1}}
    try:
        tree_ok = []
        n_tree = tree_shown_work_problems(
            {"v": {"worst_min": "4.40 - 0.20 - 0.40 = 3.80 V"}},
            "probe", tree_ok)
        cases.append(("a true power-tree derivation is counted",
                      n_tree == 1 and not tree_ok))
        tree_bad = []
        tree_shown_work_problems(
            {"v": {"worst_min": "4.40 - 0.90 - 0.40 = 3.80 V"}},
            "probe", tree_bad)
        cases.append(("a power-tree row its own operands refute is caught",
                      any("does not round to 3.8" in x for x in tree_bad)))
        tree_joined = []
        tree_shown_work_problems(
            {"v": {"worst_min": "4.40 - 0.20 - 0.40 = 3.80 V",
                   "bonus": "1 + 1 = 3 V"}}, "probe", tree_joined)
        cases.append(("a power-tree row JOINING unnamed is caught",
                      any("not in the checked population" in x
                          for x in tree_joined)))
        # A `typ:` / `worst:` label names the chain; leaving it in made the
        # whole chain unreadable, and an unreadable chain is unchecked.
        globals()["REQUIRED_TREE_SHOWN_WORK"] = {"probe": {"v.worst_min": 2}}
        labelled = []
        n_labelled = tree_shown_work_problems(
            {"v": {"worst_min": "typ: 1.0 + 2.0 = 3.0 A ; worst: 2.0 + 2.0 "
                                "= 4.0 A"}}, "probe", labelled)
        cases.append(("labelled typ/worst branches are BOTH read",
                      n_labelled == 2 and not labelled))
        half_read = []
        tree_shown_work_problems(
            {"v": {"worst_min": "typ: 1.0 + 2.0 = 3.0 A ; worst: about 4 A"}},
            "probe", half_read)
        cases.append(("a branch that stops being readable is caught",
                      any("not the recorded 2" in x for x in half_read)))
    finally:
        globals()["REQUIRED_TREE_SHOWN_WORK"] = _real_tree_rows

    # PUBLISHED MARGINS. Every one of these was replaceable with an
    # arbitrary number, `make sim` green, until round 20.
    _real_margins = REQUIRED_MARGINS
    globals()["REQUIRED_MARGINS"] = {"probe": {"A2": "slack:limit:mA",
                                               "A5": "prose"}}
    try:
        m_ok = []
        n_m = margin_problems(
            {"assertions": [
                {"id": "A2", "check_inputs": {"have": 0.39531, "limit": 0.5},
                 "margin": "+104.7 mA (20.9%)"},
                {"id": "A5", "margin": "worst +34.5 C at 62 C/W"}]},
            "probe", m_ok)
        cases.append(("a margin that is the gate's own slack reconciles",
                      n_m == 1 and not m_ok))
        m_bad = []
        margin_problems(
            {"assertions": [
                {"id": "A2", "check_inputs": {"have": 0.39531, "limit": 0.5},
                 "margin": "+999.7 mA (99.9%)"},
                {"id": "A5", "margin": "prose"}]}, "probe", m_bad)
        cases.append(("a margin that is not the computed slack is caught",
                      any("headroom a reader acts on" in x for x in m_bad)))
        m_gone = []
        margin_problems({"assertions": [{"id": "A5", "margin": "prose"}]},
                        "probe", m_gone)
        cases.append(("deleting a named margin is caught",
                      any("no longer does" in x for x in m_gone)))
        m_unreadable = []
        margin_problems(
            {"assertions": [
                {"id": "A2", "check_inputs": {"have": 0.39531, "limit": 0.5},
                 "margin": "comfortable"},
                {"id": "A5", "margin": "prose"}]}, "probe", m_unreadable)
        cases.append(("a margin that stops opening with a number is caught",
                      any("reconciles against nothing" in x
                          for x in m_unreadable)))
        m_operand = []
        margin_problems(
            {"assertions": [
                {"id": "A2", "check_inputs": {"have": 0.39531},
                 "margin": "+104.7 mA"},
                {"id": "A5", "margin": "prose"}]}, "probe", m_operand)
        cases.append(("a margin whose operand the spec dropped is caught",
                      any("no longer records in a form this can read" in x
                          for x in m_operand)))
        m_new = []
        margin_problems(
            {"assertions": [
                {"id": "A2", "check_inputs": {"have": 0.39531, "limit": 0.5},
                 "margin": "+104.7 mA"},
                {"id": "A5", "margin": "prose"},
                {"id": "A9", "margin": "+1 mA"}]}, "probe", m_new)
        cases.append(("a margin JOINING outside the population is caught",
                      any("not in the checked population" in x
                          for x in m_new)))
    finally:
        globals()["REQUIRED_MARGINS"] = _real_margins

    # T10 MARGINS in the power tree: capability minus that mode's own total,
    # both the milliamps and the percentage, plus the verdict the row states.
    _real_tm = REQUIRED_TREE_MARGINS
    globals()["REQUIRED_TREE_MARGINS"] = {"probe": {"m": 1}}
    try:
        MTREE = {"sources": {"usb_host": {"current_capability_a": 0.5}},
                 "summary_per_mode": {"m": {
                     "vbus_total_a": "1 + 2 = 99.56e-3",
                     "margin_vs_500mA": "400.4 mA (80.1%)"}}}
        tm_ok = []
        cases.append(("a T10 margin that is capability minus the total agrees",
                      tree_margin_problems(MTREE, "probe", tm_ok) == 1
                      and not tm_ok))
        tm_ma = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {"m": {
                 "vbus_total_a": "1 + 2 = 99.56e-3",
                 "margin_vs_500mA": "999.9 mA (80.1%)"}}}, "probe", tm_ma)
        cases.append(("a falsified margin figure is caught",
                      any("leaves 400.4 mA" in x for x in tm_ma)))
        tm_pct = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {"m": {
                 "vbus_total_a": "1 + 2 = 99.56e-3",
                 "margin_vs_500mA": "400.4 mA (10.1%)"}}}, "probe", tm_pct)
        cases.append(("a falsified margin PERCENTAGE is caught",
                      any("is 80.09%" in x for x in tm_pct)))
        tm_count = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {"m": {
                 "vbus_total_a": "1 + 2 = 99.56e-3",
                 "margin_vs_500mA": "comfortable"}}}, "probe", tm_count)
        cases.append(("a margin row with no readable figure is caught",
                      any("publishes 0 margin figure(s)" in x
                          for x in tm_count)))
        tm_verdict = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {"m": {
                 "vbus_total_a": "1 + 2 = 600e-3",
                 "margin_vs_500mA": "-100.0 mA (-20.0%) -> T10 PASS"}}},
            "probe", tm_verdict)
        cases.append(("a T10 PASS with no margin left is caught",
                      any("leaves no margin" in x for x in tm_verdict)))
        tm_cap = []
        tree_margin_problems(
            {"summary_per_mode": {"m": {
                "vbus_total_a": "1 = 0.1", "margin_vs_500mA": "400 mA (80%)"}}},
            "probe", tm_cap)
        cases.append(("a tree with no declared capability is caught",
                      any("measured against nothing" in x for x in tm_cap)))
        tm_gone = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {}}, "probe", tm_gone)
        cases.append(("deleting a named mode's T10 margin is caught",
                      any("no longer does" in x for x in tm_gone)))
        tm_branch = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {"m": {
                 "vbus_total_a": "1 = 0.1 ; 2 = 0.2",
                 "margin_vs_500mA": "400.4 mA (80.1%)"}}}, "probe", tm_branch)
        cases.append(("a total without its own margin branch is caught",
                      any("branch for branch" in x for x in tm_branch)))
        tm_join = []
        tree_margin_problems(
            {"sources": {"usb_host": {"current_capability_a": 0.5}},
             "summary_per_mode": {
                 "m": {"vbus_total_a": "1 + 2 = 99.56e-3",
                       "margin_vs_500mA": "400.4 mA (80.1%)"},
                 "other": {"margin_vs_500mA": "1 mA (2%)"}}}, "probe", tm_join)
        cases.append(("a mode JOINING with a margin is caught",
                      any("not in the checked population" in x
                          for x in tm_join)))
    finally:
        globals()["REQUIRED_TREE_MARGINS"] = _real_tm

    # THE DATA LAYER. Every summation term must BE a declared load: the
    # totals restated the load table as bare literals, so the two could
    # contradict each other with every gate green.
    _real_sum, _real_carry = REQUIRED_TREE_SUMMATIONS, _CARRIED_FORWARD
    globals()["REQUIRED_TREE_SUMMATIONS"] = {"probe": {
        "m.p3v3_total_a#0": ("loads.a.modes.m.i_a", "loads.b.modes.m.i_a"),
        "m.vbus_total_a#0": ("@m.p3v3_total_a#0", (0.002, "a stated basis")),
    }}
    globals()["_CARRIED_FORWARD"] = set()
    try:
        STREE = {"loads": {"a": {"modes": {"m": {"i_a": 0.095}}},
                           "b": {"modes": {"m": {"i_a": 0.0011}}}},
                 "summary_per_mode": {"m": {
                     "p3v3_total_a": "0.095 + 0.0011 = 0.0961",
                     "vbus_total_a": "0.0961 + 0.002 = 0.0981"}}}
        s_ok = []
        cases.append(("summations that sum the declared loads reconcile",
                      tree_summation_problems(STREE, "probe", s_ok) == 2
                      and not s_ok))
        s_drift = []
        drifted = {"loads": {"a": {"modes": {"m": {"i_a": 0.150}}},
                             "b": {"modes": {"m": {"i_a": 0.0011}}}},
                   "summary_per_mode": STREE["summary_per_mode"]}
        tree_summation_problems(drifted, "probe", s_drift)
        cases.append(("a declared load the summation no longer sums is "
                      "caught",
                      any("declared to sum are" in x for x in s_drift)))
        s_gone = []
        tree_summation_problems(
            {"loads": {"b": {"modes": {"m": {"i_a": 0.0011}}}},
             "summary_per_mode": STREE["summary_per_mode"]}, "probe", s_gone)
        cases.append(("a summed load that vanished from the table is caught",
                      any("no longer resolves" in x for x in s_gone)))
        s_new = []
        tree_summation_problems(
            {"loads": STREE["loads"],
             "summary_per_mode": {"m": dict(STREE["summary_per_mode"]["m"],
                                            extra_total_a="1 + 1 = 2")}},
            "probe", s_new)
        cases.append(("a summation JOINING undeclared is caught",
                      any("answer to no load" in x for x in s_new)))
        s_row = []
        tree_summation_problems({"loads": STREE["loads"],
                                 "summary_per_mode": {}}, "probe", s_row)
        cases.append(("deleting a named summation is caught",
                      any("no longer in the tree" in x for x in s_row)))
        s_carry = []
        tree_summation_problems(
            {"loads": STREE["loads"],
             "summary_per_mode": {"m": {
                 "vbus_total_a": "0.0961 + 0.002 = 0.0981"}}},
            "probe", s_carry)
        cases.append(("a summation carrying forward a row that is gone is "
                      "caught",
                      any("carries forward" in x for x in s_carry)))
    finally:
        globals()["REQUIRED_TREE_SUMMATIONS"] = _real_sum
        globals()["_CARRIED_FORWARD"] = _real_carry

    # THE EXPONENT COUNTS in the published precision: `281e-6` is not
    # checked to +/-0.5 A.
    cases.append(("engineering notation is checked at its own precision",
                  _half_ulp("281e-6") == 0.5e-6
                  and _half_ulp("9.0e-6") == 0.5e-7
                  and _half_ulp("+0.257") == 0.0005))
    cases.append(("a unit INSIDE the expression is still arithmetic",
                  _eval_arith(" 0.500 A - 0.39531 A ") is not None
                  and _eval_arith(" 121.9 C at Ta ") is None))

    # WIRING: a planted problem from each cross-file leg must reach main().
    for leg in ("shown_work_problems", "power_tree_problems",
                "margin_problems", "tree_shown_work_problems",
                "tree_margin_problems", "tree_summation_problems"):
        _real_leg = globals()[leg]

        def _planted(*args, _leg=leg, **kwargs):
            args[-1].append(f"planted-{_leg}")
            return 0
        globals()[leg] = _planted
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                wired = main([str(ROOT / "benchmarks" / "esp32s3-devboard")])
        finally:
            globals()[leg] = _real_leg
        cases.append((f"{leg} is WIRED into main()", wired == 1))

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
        # THE MARGINS A4 EXISTS TO PUBLISH. Round 20 found the two dropout
        # margins -- the numbers a reader acts on -- outside this population
        # while the comment above claimed it held the load-bearing ones, so
        # design.md could contradict the assertion that computes them.
        (r"\(0\.34 V/A\),\s+required V_in = [\d.]+ V -> \*\*\+([\d.]+) mV "
         r"margin\*\*", "A4_ldo_dropout_at_min_vbus", "a4_typ_margin_mV",
         1.0),
        (r"guardband,\s+required V_in = [\d.]+ V -> \*\*\+([\d.]+) mV "
         r"margin\*\*", "A4_ldo_dropout_at_min_vbus",
         "a4_guardband_margin_mV", 1.0),
        # The peak rail demand every current row derives from, and the
        # dissipation that is the direct operand of the gated 121.9 C.
        (r"= \*\*([\d.]+) mA\*\*; module datasheet",
         "A4_ldo_dropout_at_min_vbus", "i_load_mA", 1.0),
        (r"Ta = 50 C, VBUS 5\.25 V: P = ([\d.]+) W",
         "A5_ldo_thermal_at_wifi_tx", "a5_power_W", 1.0),
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
        elif operand == "a4_typ_margin_mV":
            inputs = assertion.get("inputs") or {}
            want = (float(ci.get("have"))
                    - (float(inputs["vout_max_v"])
                       + float(inputs["vdo_typ_v_per_a"])
                       * float(inputs["i_load_a"]))) * 1000.0
        elif operand == "a4_guardband_margin_mV":
            want = (float(ci.get("have")) - float(ci.get("need"))) * 1000.0
        elif operand == "i_load_mA":
            want = float((assertion.get("inputs") or {})["i_load_a"]) * 1000.0
        elif operand == "a5_power_W":
            worst = (assertion.get("inputs") or {})["worst"]
            want = ((float(worst["vin_v"]) - float(worst["vout_v"]))
                    * float(worst["iout_a"])
                    + float(worst["vin_v"])
                    * float((assertion.get("inputs") or {})["iq_a"]))
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
        claims_checked = shown_work_problems(spec, case_dir.name, problems)
        margins_checked = margin_problems(spec, case_dir.name, problems)
        tree_path = case_dir / "power-tree.yaml"
        tree_checked = 0
        if tree_path.is_file():
            tree_spec = load_yaml(tree_path)
            tree_checked = power_tree_problems(
                spec, tree_path.read_text(encoding="utf-8"),
                case_dir.name, problems, tree=tree_spec)
            claims_checked += tree_shown_work_problems(
                tree_spec, case_dir.name, problems)
            tree_checked += tree_summation_problems(
                tree_spec, case_dir.name, problems)
            margins_checked += tree_margin_problems(
                tree_spec, case_dir.name, problems)
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
          f"reconcile against them; {margins_checked} published margin(s) are "
          f"the gate's own slack; {tree_checked} power-tree figure(s) agree; "
          f"{claims_checked} shown-work claim(s) recompute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
