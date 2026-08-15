"""Tests for the §8-Q1 bake-off prototypes.

Stdlib unittest only, like eval/tests: this gate must never be weakened by a
dependency-resolution problem, and the one optional package it can use
(tiktoken) is checked for explicitly and reported as skipped rather than
silently passed.

The tests are organised around the three properties the measurement rests on —
round trip, cross-arm agreement, external anchoring — plus the restriction set
the Starlark baseline claims to enforce, which is worth nothing unless
something tries to break it.
"""

import json
import re
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "lang"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from bakeoff import library  # noqa: E402
from bakeoff.arms import ARMS, CANDIDATES  # noqa: E402
from bakeoff.arms import starlark as starlark_arm  # noqa: E402
from bakeoff.defects import DEFECTS, score  # noqa: E402
from bakeoff.diagnostics import ParseFailure  # noqa: E402
from bakeoff.elaborate import AnchorError, check_anchor, flatten  # noqa: E402
from bakeoff.layout import tokenize  # noqa: E402
from bakeoff.model import (  # noqa: E402
    HARDWARE_KINDS,
    MEASUREMENT_KINDS,
    PIN_ROLES,
    ModelError,
    diff,
    load_corpus,
    model_from_json,
    model_to_json,
)
from bakeoff.quantities import QuantityError, parse_quantity  # noqa: E402

CORPUS = load_corpus()
LANG = REPO_ROOT / "lang"


def _schema(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class VocabularyConformance(unittest.TestCase):
    """The bake-off's vocabularies must not drift from the IR's.

    Three hand-maintained copies of the T2 lattice would agree on the day they
    were written and diverge quietly afterwards, and a divergence here means
    the bake-off is measuring a language the compiler will not accept.
    """

    def setUp(self):
        self.design_model = _schema(LANG / "design-model.schema.json")
        self.ir = _schema(REPO_ROOT / "ir" / "netlist-ir.schema.json")

    def test_pin_roles_match_the_ir(self):
        self.assertEqual(
            list(PIN_ROLES), self.ir["$defs"]["PinRole"]["enum"]
        )
        self.assertEqual(
            list(PIN_ROLES), self.design_model["$defs"]["PinRole"]["enum"]
        )

    def test_hardware_kinds_match_the_ir(self):
        ir_kinds = self.ir["$defs"]["Instance"]["properties"]["hardware_kind"]["enum"]
        self.assertEqual(list(HARDWARE_KINDS), ir_kinds)
        self.assertEqual(
            list(HARDWARE_KINDS), self.design_model["$defs"]["HardwareKind"]["enum"]
        )

    def test_measurement_kinds_match_the_ir(self):
        self.assertEqual(
            list(MEASUREMENT_KINDS), self.ir["$defs"]["MeasurementKind"]["enum"]
        )
        self.assertEqual(
            list(MEASUREMENT_KINDS),
            self.design_model["$defs"]["MeasurementKind"]["enum"],
        )

    def test_static_tier_subset_matches_the_ir(self):
        from bakeoff.model import STATIC_MEASUREMENTS

        ir_subset = self.ir["$defs"]["Assertion"]["allOf"][0]["then"]["properties"][
            "measurement"
        ]["enum"]
        self.assertEqual(sorted(STATIC_MEASUREMENTS), sorted(ir_subset))


class Quantities(unittest.TestCase):
    def test_percent_tolerance_is_exact(self):
        quantity = parse_quantity("560ohm +/- 1%")
        self.assertEqual(quantity.lower, Decimal("554.4"))
        self.assertEqual(quantity.upper, Decimal("565.6"))

    def test_units_normalise_for_comparison(self):
        self.assertEqual(parse_quantity("100kohm"), parse_quantity("100000ohm"))
        self.assertEqual(parse_quantity("1uF"), parse_quantity("0.000001F"))

    def test_different_dimensions_never_compare_equal(self):
        self.assertNotEqual(parse_quantity("1V"), parse_quantity("1A"))

    def test_absolute_tolerance_is_converted_to_the_value_unit(self):
        quantity = parse_quantity("1V +/- 50mV")
        self.assertEqual(quantity.lower, Decimal("0.950"))
        self.assertEqual(quantity.upper, Decimal("1.050"))

    def test_asymmetric_interval_keeps_its_nominal(self):
        quantity = parse_quantity("9.5mA (8.0mA to 10.5mA)")
        self.assertEqual(quantity.nominal, Decimal("9.5"))
        self.assertEqual(quantity.lower, Decimal("8.0"))

    def test_bare_interval_has_no_nominal(self):
        self.assertIsNone(parse_quantity("3.0V to 3.6V").nominal)

    def test_nominal_outside_its_own_interval_is_rejected(self):
        with self.assertRaises(QuantityError):
            parse_quantity("9.5mA (10.0mA to 10.5mA)")

    def test_unknown_unit_is_rejected(self):
        with self.assertRaises(QuantityError):
            parse_quantity("10kOhm")

    def test_mismatched_tolerance_dimension_is_rejected(self):
        with self.assertRaises(QuantityError):
            parse_quantity("1V +/- 5mA")

    def test_non_ascii_sign_is_rejected(self):
        with self.assertRaises(QuantityError):
            parse_quantity("3.3V \u00b1 5%")

    def test_float_repr_never_leaks_in(self):
        # 0.1 + 0.2 territory: the whole reason bounds are decimal text.
        quantity = parse_quantity("0.1V +/- 0.2V")
        self.assertEqual(quantity.upper, Decimal("0.3"))


class Layout(unittest.TestCase):
    def test_tab_is_rejected(self):
        with self.assertRaises(ParseFailure) as caught:
            tokenize("module M:\n\tx = 1\n")
        self.assertTrue(any(d.code == "AEDX0002" for d in caught.exception.diagnostics))

    def test_non_ascii_is_rejected(self):
        with self.assertRaises(ParseFailure) as caught:
            tokenize("module M:\n    x = 3.3V \u00b1 5%\n")
        self.assertTrue(any(d.code == "AEDX0001" for d in caught.exception.diagnostics))

    def test_blank_and_comment_lines_carry_no_layout(self):
        kinds = [t.kind for t in tokenize("module M:\n    a\n\n# note\n    b\n")]
        self.assertEqual(kinds.count("DEDENT"), 1)

    def test_brackets_join_lines(self):
        kinds = [t.kind for t in tokenize("x = f(\n  1,\n  2)\n")]
        self.assertEqual(kinds.count("NEWLINE"), 1)

    def test_unclosed_bracket_reports_where_it_opened(self):
        with self.assertRaises(ParseFailure) as caught:
            tokenize("a = f(1\nb = 2\nc = 3\nd = 4\n")
        diagnostic = next(
            d for d in caught.exception.diagnostics if d.code == "AEDX0007"
        )
        self.assertEqual(diagnostic.span.line, 1)

    def test_quantity_is_one_token(self):
        quantities = [t.text for t in tokenize("x = 9.5mA (8.0mA to 10.5mA)\n") if t.kind == "QUANTITY"]
        self.assertEqual(quantities, ["9.5mA (8.0mA to 10.5mA)"])

    def test_bare_decimal_is_one_number_token(self):
        numbers = [t.text for t in tokenize("x 0.524\n") if t.kind == "NUMBER"]
        self.assertEqual(numbers, ["0.524"])


class CorpusIntegrity(unittest.TestCase):
    def test_corpus_is_not_empty(self):
        self.assertTrue(CORPUS)

    def test_every_design_declares_an_anchor(self):
        for design_id, model in CORPUS.items():
            with self.subTest(design=design_id):
                self.assertIsNotNone(
                    model.anchor,
                    "a reference design nothing external agrees with is an opinion",
                )

    def test_every_anchor_holds(self):
        for design_id, model in CORPUS.items():
            with self.subTest(design=design_id):
                check_anchor(model)

    def test_blinker_reproduces_the_committed_ir(self):
        summary = check_anchor(CORPUS["blinker-555"])
        self.assertEqual(summary["anchor"], "ir/examples/blinker.ir.json")
        self.assertEqual(summary["connections"], 25)

    def test_esp32_matches_the_committed_bom(self):
        summary = check_anchor(CORPUS["esp32s3-devboard"])
        self.assertEqual(summary["placements"], 60)
        self.assertEqual(summary["dnp"], 3)

    def test_model_json_round_trips(self):
        for design_id, model in CORPUS.items():
            with self.subTest(design=design_id):
                self.assertEqual(model_from_json(model_to_json(model)), model)

    def test_esp32_generator_is_deterministic(self):
        """Regenerating must reproduce the committed bytes exactly."""
        target = LANG / "examples" / "esp32s3-devboard.design.json"
        before = target.read_bytes()
        subprocess.run(
            [sys.executable, str(LANG / "examples" / "make_esp32_model.py")],
            check=True,
            capture_output=True,
        )
        self.assertEqual(before, target.read_bytes())


class RoundTrip(unittest.TestCase):
    """Every arm must read back exactly what it wrote, in every variant."""

    def test_round_trip(self):
        for design_id, model in CORPUS.items():
            for arm in ARMS.values():
                for variant in arm.variants:
                    with self.subTest(design=design_id, arm=arm.key, variant=variant):
                        source = arm.render(model, variant)
                        parsed = arm.parse(source, variant)
                        self.assertEqual(diff(model, parsed), [])

    def test_rendering_is_deterministic(self):
        for design_id, model in CORPUS.items():
            for arm in ARMS.values():
                with self.subTest(design=design_id, arm=arm.key):
                    self.assertEqual(
                        arm.render(model, "inferred"), arm.render(model, "inferred")
                    )

    def test_arms_agree_with_each_other(self):
        """The point of the whole exercise: same design, different spellings."""
        for design_id, model in CORPUS.items():
            parsed = {
                arm.key: arm.parse(arm.render(model, "inferred"), "inferred")
                for arm in ARMS.values()
            }
            reference = parsed["candidate_a"]
            for key, other in parsed.items():
                with self.subTest(design=design_id, arm=key):
                    self.assertEqual(diff(reference, other), [])

    def test_explicit_costs_more_than_inferred(self):
        """The T9 tax is positive, or the inference rules do nothing."""
        for design_id, model in CORPUS.items():
            for arm in ARMS.values():
                with self.subTest(design=design_id, arm=arm.key):
                    self.assertGreater(
                        len(arm.render(model, "explicit")),
                        len(arm.render(model, "inferred")),
                    )

    def test_columnar_helps_the_large_design_and_not_the_small_one(self):
        model = CORPUS["esp32s3-devboard"]
        for arm in CANDIDATES:
            with self.subTest(arm=arm.key):
                self.assertLess(
                    len(arm.render(model, "inferred+columnar")),
                    len(arm.render(model, "inferred")),
                )
        blinker = CORPUS["blinker-555"]
        for arm in CANDIDATES:
            with self.subTest(arm=arm.key, design="blinker-555"):
                # Nothing in a 555 blinker repeats three times with the same
                # shape, so a table would be a header with nothing under it.
                self.assertEqual(
                    arm.render(blinker, "inferred+columnar"),
                    arm.render(blinker, "inferred"),
                )


class Inference(unittest.TestCase):
    def test_inference_is_lossless_on_the_corpus(self):
        for design_id, model in CORPUS.items():
            for module in model.modules:
                for inst in module.instances:
                    if inst.kind != "component":
                        continue
                    with self.subTest(design=design_id, instance=inst.name):
                        self.assertEqual(library.apply_inference(inst), inst)

    def test_library_covers_every_definition_the_corpus_uses(self):
        for design_id, model in CORPUS.items():
            for module in model.modules:
                for inst in module.instances:
                    if inst.kind == "component":
                        with self.subTest(design=design_id, instance=inst.name):
                            library.lookup(inst.definition)

    def test_unknown_definition_is_an_error_not_an_empty_component(self):
        with self.assertRaises(library.LibraryError):
            library.lookup("aed.lib.passive.Resistorr")

    def test_constraint_inference_does_not_invent_constraints(self):
        """The bug this rule was rewritten for.

        An LED's `forward_voltage` is a parameter and not a part constraint,
        so a blanket "every parameter is a constraint" rule would add one on
        the way back in.
        """
        model = CORPUS["blinker-555"]
        led = model.module("LedIndicator").instance("d1")
        self.assertNotIn("forward_voltage", library.inferable_constraints(led))
        self.assertIn("color", library.inferable_constraints(led))


class ModelValidation(unittest.TestCase):
    """Rejections the schema cannot express."""

    def _model(self, **overrides):
        document = json.loads(
            json.dumps(model_to_json(CORPUS["blinker-555"]))
        )
        for path, value in overrides.items():
            document[path] = value
        return document

    def test_port_on_two_nets_is_rejected(self):
        document = self._model()
        root = next(m for m in document["modules"] if m["name"] == "Blinker555")
        root["nets"].append({"name": "STRAY", "members": ["timer.out", "r_a.a"]})
        with self.assertRaises(ModelError) as caught:
            model_from_json(document)
        self.assertIn("already on net", str(caught.exception))

    def test_connection_to_an_unknown_port_is_rejected(self):
        document = self._model()
        root = next(m for m in document["modules"] if m["name"] == "Blinker555")
        root["nets"][0]["members"] = ["timer.nonexistent"]
        with self.assertRaises(ModelError):
            model_from_json(document)

    def test_unreachable_module_is_rejected(self):
        document = self._model()
        document["modules"].append(
            {"name": "Orphan", "qualified_name": "x.Orphan", "ports": [],
             "instances": [], "nets": []}
        )
        with self.assertRaises(ModelError) as caught:
            model_from_json(document)
        self.assertIn("never instantiated", str(caught.exception))

    def test_static_tier_with_a_dynamic_measurement_is_rejected(self):
        document = self._model()
        document["assertions"][0]["tier"] = "static"
        with self.assertRaises(ModelError) as caught:
            model_from_json(document)
        self.assertIn("interval-arithmetic", str(caught.exception))

    def test_assertion_probing_an_unlabelled_net_is_rejected(self):
        document = self._model()
        document["assertions"][0]["subject"] = "NOT_A_NET"
        with self.assertRaises(ModelError):
            model_from_json(document)

    def test_nc_port_joining_a_net_is_rejected(self):
        document = self._model()
        root = next(m for m in document["modules"] if m["name"] == "Blinker555")
        timer = next(i for i in root["instances"] if i["name"] == "timer")
        next(p for p in timer["ports"] if p["name"] == "ctl")["role"] = "nc"
        with self.assertRaises(ModelError) as caught:
            model_from_json(document)
        self.assertIn("nc", str(caught.exception))


class StarlarkRestrictions(unittest.TestCase):
    """The baseline's restriction set, exercised rather than asserted."""

    PREFIX = "def M(m):\n    m.port('p', 'passive')\n"
    SUFFIX = "\nDESIGN = design(M)\n"

    def _reject(self, snippet: str) -> ParseFailure:
        with self.assertRaises(ParseFailure) as caught:
            starlark_arm.parse(self.PREFIX + snippet + self.SUFFIX)
        return caught.exception

    def test_import_is_rejected(self):
        self._reject("import os\n")

    def test_from_import_is_rejected(self):
        self._reject("from os import path\n")

    def test_while_is_rejected(self):
        self._reject("def f(x):\n    while x:\n        x = 0\n")

    def test_class_is_rejected(self):
        self._reject("class C:\n    pass\n")

    def test_lambda_is_rejected(self):
        self._reject("f = lambda x: x\n")

    def test_comprehension_is_rejected(self):
        self._reject("xs = [i for i in [1, 2]]\n")

    def test_global_is_rejected(self):
        self._reject("def f(x):\n    global M\n    return x\n")

    def test_try_is_rejected(self):
        self._reject("def f(x):\n    try:\n        return x\n    except:\n        return 0\n")

    def test_fstring_is_rejected(self):
        self._reject("x = f'{1}'\n")

    def test_walrus_is_rejected(self):
        self._reject("def f(x):\n    return (y := x)\n")

    def test_private_attribute_is_rejected(self):
        self._reject("def f(m):\n    return m._record\n")

    def test_star_args_is_rejected(self):
        self._reject("def f(x):\n    return M(*x)\n")

    def test_direct_recursion_is_rejected_statically(self):
        failure = self._reject("def f(x):\n    return f(x)\n")
        self.assertTrue(any("recursive" in d.message for d in failure.diagnostics))

    def test_mutual_recursion_is_rejected_statically(self):
        failure = self._reject("def f(x):\n    return g(x)\n\ndef g(x):\n    return f(x)\n")
        self.assertTrue(any("recursive" in d.message for d in failure.diagnostics))

    def test_undefined_name_is_rejected(self):
        self._reject("x = nowhere\n")

    def test_the_evaluator_never_calls_exec_or_eval(self):
        """Mutation-proof: the restriction rests on not running the source.

        A future 'simplification' that reached for `exec` with restricted
        globals would look like it still worked — every test above would pass
        — while quietly reinstating exactly the arbitrary-code-execution
        objection §6 rejects the embedded path for.
        """
        source = (LANG / "bakeoff" / "arms" / "starlark.py").read_text(encoding="utf-8")
        # Anchored so the evaluator's own `self.eval(...)` method does not
        # trip it: what must be absent is a CALL to the builtin.
        for forbidden in ("exec", "eval", "compile", "__import__"):
            with self.subTest(construct=forbidden):
                self.assertIsNone(
                    re.search(rf"(?<![.\w]){forbidden}\s*\(", source),
                    f"{forbidden}() would reinstate arbitrary code execution",
                )

    def test_a_conforming_program_still_runs(self):
        model = starlark_arm.parse(
            "def M(m):\n"
            "    m.port('p', 'passive')\n"
            "    for name in ['r1', 'r2']:\n"
            "        r = m.part(name, 'aed.lib.passive.Resistor', resistance='1kohm')\n"
            "        r.pins(('a', 'passive'), ('b', 'passive'))\n"
            "        r.part(package='0402')\n"
            "    m.net('N', 'r1.a', 'r2.a')\n"
            "    m.link('p', 'r1.b')\n"
            "    m.link('r2.b', 'p')\n" + "\nDESIGN = design(M)\n",
            "explicit",
        )
        self.assertEqual(len(model.root().instances), 2)


class DefectCorpus(unittest.TestCase):
    def test_every_defect_applies_somewhere(self):
        applied = set()
        for design_id, model in CORPUS.items():
            for arm in ARMS.values():
                for row in score(arm, "inferred", model, design_id):
                    if row["status"] != "not_applicable":
                        applied.add(row["defect"])
        self.assertEqual(applied, {defect.key for defect in DEFECTS})

    def test_candidates_never_accept_a_defective_design(self):
        for design_id, model in CORPUS.items():
            for arm in CANDIDATES:
                for row in score(arm, "inferred", model, design_id):
                    with self.subTest(design=design_id, arm=arm.key, defect=row["defect"]):
                        self.assertNotEqual(
                            row["status"],
                            "accepted",
                            "a candidate grammar accepted a design with a known "
                            "defect, so it produced a netlist nobody asked for",
                        )

    def test_the_baseline_accepts_a_corrupted_unit(self):
        """A finding, pinned so it cannot vanish unnoticed.

        `"10kOhm"` is not a quantity, so the baseline's `_as_value` reads it as
        a symbolic string and the design elaborates with a resistance that is
        text. This is §6's "SKiDL's stringly values" criticism reproduced, and
        it is the sharpest result the bake-off has. If a later change makes the
        baseline reject it, this test fails and the finding gets rewritten
        rather than quietly disappearing from the record.
        """
        rows = score(ARMS["starlark"], "inferred", CORPUS["blinker-555"], "blinker-555")
        row = next(r for r in rows if r["defect"] == "corrupt_unit")
        self.assertEqual(row["status"], "accepted")

    def test_candidates_localise_most_defects(self):
        for arm in CANDIDATES:
            detected = localised = 0
            for design_id, model in CORPUS.items():
                for row in score(arm, "inferred", model, design_id):
                    if row["status"] == "detected":
                        detected += 1
                        localised += 1 if row["localised"] else 0
            with self.subTest(arm=arm.key):
                self.assertGreater(detected, 0)
                self.assertGreaterEqual(
                    localised / detected,
                    0.8,
                    "a diagnostic that points at the wrong line is what P2 says "
                    "makes repair loops fail to converge",
                )


class ReservedWords(unittest.TestCase):
    """A keyword used as a name must say so, not blame the next token."""

    SOURCES = {
        "candidate_a": '#pragma language "0.1.0"\n\nmodule M:\n'
        "    signal = new aed.lib.passive.Resistor\n",
        "candidate_b": '#pragma language "0.1.0"\n\nmodule M:\n'
        "    net = new aed.lib.passive.Resistor(resistance = 1kohm)\n",
    }

    def test_reserved_word_as_an_instance_name_is_named_as_such(self):
        for key, source in self.SOURCES.items():
            with self.subTest(arm=key):
                with self.assertRaises(ParseFailure) as caught:
                    ARMS[key].parse(source, "inferred")
                diagnostic = caught.exception.diagnostics[0]
                self.assertTrue(diagnostic.code.endswith("0212"))
                self.assertIn("reserved word", diagnostic.message)
                self.assertEqual(diagnostic.span.line, 4)

    def test_both_candidates_reserve_the_same_words(self):
        """A word reserved by one and not the other would break agreement."""
        from bakeoff.arms.base import RESERVED

        for word in ("module", "net", "signal", "table", "part", "abstract"):
            with self.subTest(word=word):
                self.assertIn(word, RESERVED)

    def test_the_cards_list_the_reserved_words(self):
        from bakeoff.arms.base import RESERVED

        for arm in CANDIDATES:
            card = arm.language_card()
            with self.subTest(arm=arm.key):
                self.assertIn("Reserved words", card)
                for word in sorted(RESERVED):
                    self.assertIn(word, card)


class Gates(unittest.TestCase):
    """The adapters AMB-33 drives through the AC5 protocol."""

    def setUp(self):
        from bakeoff.gate import bakeoff_gate

        self.model = CORPUS["blinker-555"]
        self.arm = ARMS["candidate_a"]
        self.gate = bakeoff_gate(self.arm, self.model, "inferred")

    def test_correct_source_passes_both_stages(self):
        result = self.gate.check(self.arm.render(self.model, "inferred"))
        self.assertTrue(result.passed)
        self.assertIn("parse", result.stage)
        self.assertIn("netlist", result.stage)

    def test_unparseable_source_fails_at_the_parse_stage(self):
        result = self.gate.check("this is not a design\n")
        self.assertFalse(result.passed)
        self.assertTrue(result.stage.startswith("parse"))
        self.assertTrue(result.diagnostics)

    def test_a_different_design_fails_at_the_netlist_stage(self):
        """Parsing is not passing: the gate checks WHICH design was emitted."""
        other = self.arm.render(CORPUS["esp32s3-devboard"], "inferred")
        result = self.gate.check(other)
        self.assertFalse(result.passed)
        self.assertIn("netlist", result.stage)

    def test_diagnostics_carry_severity_both_ways(self):
        result = self.gate.check("this is not a design\n")
        for diagnostic in result.diagnostics:
            self.assertEqual(diagnostic.top_level_severity, "error")
            self.assertEqual(diagnostic.params.get("severity"), "error")

    def test_trial_config_uses_the_arm_language_card(self):
        from bakeoff.gate import trial_config

        config = trial_config("blinker-555", self.arm, "inferred")
        self.assertEqual(config.system_context, self.arm.language_card())
        self.assertEqual(config.iteration_semantics, "total_write_check_cycles")


class LanguageCards(unittest.TestCase):
    def test_every_arm_ships_one(self):
        for arm in ARMS.values():
            with self.subTest(arm=arm.key):
                self.assertGreater(len(arm.language_card()), 500)

    def test_cards_are_ascii(self):
        for arm in ARMS.values():
            with self.subTest(arm=arm.key):
                arm.language_card().encode("ascii")

    def test_cards_are_inside_the_flip_criterion_budget(self):
        """§4's flip criterion is stated in tokens of this artifact."""
        try:
            from bakeoff.measure import load_tokenizer

            tokenizer = load_tokenizer(allow_stub=False)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            self.skipTest(
                f"the pinned tokenizer is unavailable, so the ~3K card budget "
                f"cannot be checked here: {exc}"
            )
        for arm in ARMS.values():
            with self.subTest(arm=arm.key):
                self.assertLessEqual(tokenizer.count(arm.language_card()), 3000)


class Columnar(unittest.TestCase):
    def test_a_short_table_is_rejected(self):
        source = (
            '#pragma language "0.1.0"\n\n'
            "module M:\n"
            "    table aed.lib.passive.Resistor part abstract (resistance):\n"
            "        r1  1kohm\n"
            "        r2  1kohm\n"
            "    net N:\n"
            "        r1.a\n"
            "        r2.a\n"
            "    r1.b ~ r2.b\n"
        )
        with self.assertRaises(ParseFailure) as caught:
            ARMS["candidate_b"].parse(source, "inferred")
        self.assertTrue(
            any("at least" in d.message for d in caught.exception.diagnostics)
        )

    def test_a_row_with_too_many_values_is_rejected(self):
        source = (
            '#pragma language "0.1.0"\n\n'
            "module M:\n"
            "    table aed.lib.passive.Resistor part abstract (resistance):\n"
            "        r1  1kohm\n"
            "        r2  1kohm  2kohm\n"
            "        r3  1kohm\n"
            "    net N:\n"
            "        r1.a\n"
            "        r2.a\n"
            "        r3.a\n"
        )
        with self.assertRaises(ParseFailure):
            ARMS["candidate_b"].parse(source, "inferred")


class Elaboration(unittest.TestCase):
    def test_module_ports_merge_parent_and_child_nets(self):
        flat = flatten(CORPUS["blinker-555"])
        members = {
            (c["instance"], c["port"]) for c in flat["connections"] if c["net"] == "OUT"
        }
        # The parent names it `indicator.ctl`; the module names it `ctl`. Both
        # must land on OUT along with the resistor inside the module.
        self.assertIn(("/indicator", "ctl"), members)
        self.assertIn(("/indicator/r_lim", "a"), members)

    def test_two_instantiations_colliding_on_a_net_name_are_rejected(self):
        """The silent-wrong-answer case, caught rather than guessed at.

        A module instantiated twice gives each copy its own internal net, both
        carrying the label the module wrote. Emitting two nets with one name
        would let any backend that keys on name fuse them into a single node —
        a wrong netlist that nothing downstream could detect. Deriving unique
        names is I2's rule (AMB-62/R27), so this refuses instead.
        """
        import copy

        document = json.loads(json.dumps(model_to_json(CORPUS["blinker-555"])))
        root = next(m for m in document["modules"] if m["name"] == "Blinker555")
        second = copy.deepcopy(
            next(i for i in root["instances"] if i["name"] == "indicator")
        )
        second["name"] = "indicator2"
        root["instances"].append(second)
        root["nets"].append({"name": "OUT2", "members": ["indicator2.ctl"]})
        next(n for n in root["nets"] if n["name"] == "GND")["members"].append(
            "indicator2.gnd"
        )
        with self.assertRaises(AnchorError) as caught:
            flatten(model_from_json(document))
        self.assertIn("same name", str(caught.exception))

    def test_an_unlabelled_flattened_net_is_an_error(self):
        document = json.loads(json.dumps(model_to_json(CORPUS["blinker-555"])))
        indicator = next(m for m in document["modules"] if m["name"] == "LedIndicator")
        for net in indicator["nets"]:
            net.pop("name", None)
        root = next(m for m in document["modules"] if m["name"] == "Blinker555")
        root["nets"] = [
            net for net in root["nets"] if net.get("name") not in ("OUT", "GND")
        ]
        root["instances"] = [
            i for i in root["instances"] if i["name"] not in ("tp_out", "mh1")
        ]
        document["assertions"] = []
        with self.assertRaises((AnchorError, ModelError)):
            flatten(model_from_json(document))


if __name__ == "__main__":
    unittest.main()
