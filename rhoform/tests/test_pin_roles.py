"""The T2 pin roles, held to one list everywhere they are restated.

rhoform.check.model.PinRole transcribes the grammar's closed vocabulary
(lang/grammar/rhoform_syntax.py, CLOSED_VOCABULARIES["pin_role"]), because
rhoform may not import lang.grammar; the IR v1 and the part-data schemas
each restate it as an enum, and a part record's role is joined to the
role the IR carries. A role added to one and not the others would surface
only when a checker compared them, so all four are reconciled here,
member for member and in order.
"""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def grammar_roles() -> tuple:
    spec = importlib.util.spec_from_file_location(
        "_sot_roles", ROOT / "lang" / "grammar" / "rhoform_syntax.py")
    sot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sot)
    return tuple(sot.CLOSED_VOCABULARIES["pin_role"])


def schema_roles(path: Path) -> tuple:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return tuple(schema["$defs"]["PinRole"]["enum"])


class PinRoleTest(unittest.TestCase):
    def test_the_checker_list_is_the_grammars(self):
        from rhoform.check.model import PinRole

        self.assertEqual(PinRole, grammar_roles())
        self.assertEqual(len(PinRole), 10)

    def test_the_ir_schema_restates_the_same_roles(self):
        from rhoform.check.model import PinRole

        self.assertEqual(
            schema_roles(ROOT / "ir" / "netlist-ir.v1.schema.json"), PinRole)

    def test_the_part_data_schema_restates_the_same_roles(self):
        from rhoform.check.model import PinRole

        self.assertEqual(
            schema_roles(ROOT / "parts" / "part-data.schema.json"), PinRole)
