"""IR version 2 (unfrozen): the preservation oracle, and determinism.

THE ORACLE. Version 2 only adds to version 1 (ir/README.md, "Versioning
policy"): with the additions removed and `ir_version` set back to 1, every
golden regenerated for version 2 must hash to exactly the design_hash its
version 1 golden had. The version 1 hashes are written down below, read off
the goldens as they were committed before the regeneration (base 19313f2),
so the oracle compares against history rather than against anything this
change could have moved. Both encoders compute it, the package's and the
gate's (tests/ir/check-hashes.py, loaded by path), so a fault in one is not
hidden by the same fault in the other.

DETERMINISM. A design using every 0.3 source fact emits the same bytes
under any hash seed.
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

from rhoform import ir

ROOT = Path(__file__).resolve().parents[2]
ELABORATE = "spec/conformance/elaborate/accept/"
PACKAGES = "spec/conformance/packages/accept/"


def _gate():
    spec = importlib.util.spec_from_file_location(
        "_rhoform_check_hashes_v2", ROOT / "tests" / "ir" / "check-hashes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _gate()

# Every IR golden that existed under version 1, and the design_hash it had.
V1_DESIGN_HASHES = {
    "benchmarks/blinker-555/blinker-555.ir.json":
        "sha256:108487655581569464c2e4238501a03308f11439e90f895c4b158842dd31e541",
    "benchmarks/buck-3v3/buck-3v3.ir.json":
        "sha256:38aa700af0b13ce0b180b96c0b8cbc77953a5245c035aa39278bb19bdef2bec8",
    "benchmarks/esp32s3-devboard/esp32s3-devboard.ir.json":
        "sha256:addaa110bc839e19e1b04a3eddc03a9ec5c9fb096b24631780f91a3f8744dd6c",
    ELABORATE + "a01_hierarchy.expected.ir.json":
        "sha256:60a274e575fcbbbbba0a7dc0b6eb2f9769e041279d37e3f6d75990f3eb0e81ca",
    ELABORATE + "a02_labels_across_scopes.expected.ir.json":
        "sha256:c76caac126eb33e228b662b312e7844b49166871c653891700da87da9ae2165f",
    ELABORATE + "a03_unlabelled_and_isolated_nets.expected.ir.json":
        "sha256:5cace8246d22f350a968c10dbc0f24df7db0def3131b2270e289cb2c50d86762",
    ELABORATE + "a04_flags_and_hardware.expected.ir.json":
        "sha256:3d99981bedb2edfcf70f6263490f62be9a6b6f3cef673e95841fe5e751b77a42",
    ELABORATE + "a05_tables.expected.ir.json":
        "sha256:6cb7a7952ed5fa6f01bf4a8a1d009653a423ae0e12ee9092513f9a278c82a15c",
    ELABORATE + "a06_assertions.expected.ir.json":
        "sha256:ee7c4a05006ab79f80b3776bed182be4b818dc5a27df28cfa9699bd9f61d167c",
    ELABORATE + "a07_values_and_units.expected.ir.json":
        "sha256:8c62ebec2dab3a566a9f55af5c2fd33ada4f710bf55195681109a47dbc3a4411",
    ELABORATE + "a08_decimal_to_double.expected.ir.json":
        "sha256:ffc84de44ae461c0d8fe1e0e93939365e2f3d169e6bae9efc44f5cbfc45583fe",
    ELABORATE + "a09_component_definitions.expected.ir.json":
        "sha256:67dc1d6dc18613d8ce4924a0597697ff8af8463682aa232938f210b34a9fdfe2",
    ELABORATE + "a10_parameters_and_defaults.expected.ir.json":
        "sha256:18c9551347f55a14632e1796b1ba4ed95cd1efcf24ad8ccc6a3bbf2084a5e572",
    ELABORATE + "a11_if_else.expected.ir.json":
        "sha256:69620fe4f02ac0dc4fa1620145fe9c0dd121ff6d85ea3c8601a376ea3fb97679",
    ELABORATE + "a12_arrays.expected.ir.json":
        "sha256:e9d8ee71ee4a2aec1fdc92c126fcb93ed3fab6a5226e92449f537519527b7f94",
    ELABORATE + "a13_for_loops.expected.ir.json":
        "sha256:16b70991e8d8c791138297772a08f1af73ed89dea56b99ecd1c770321c4f25e2",
    ELABORATE + "a14_language_version_0_2.expected.ir.json":
        "sha256:9b9835a569eabb9e8a02d8ccdd134e9c731c979c1d8f39c14fdc72467e18a8a9",
    ELABORATE + "a15_standard_library.expected.ir.json":
        "sha256:003c43a6ca6cd495682a5e25c2584bafe069b45598e6b1df82734efd1642afc0",
    ELABORATE + "a16_standard_library_table.expected.ir.json":
        "sha256:6a55a619ddb4385328e2717bd4778bbd4f94b0d261753c73bf18f27f67eaeab4",
    PACKAGES + "a01_local_imports/expected.ir.json":
        "sha256:d21f6880d69b14488fe95c7e54d1f8d42f5fd82c39754aaee62ef99fa97d60cd",
    PACKAGES + "a02_path_dependency/expected.ir.json":
        "sha256:2723c055a5804476656acb17baef34d2c082199ef8d4c76abeec8d3f475408c5",
    PACKAGES + "a03_no_manifest/expected.ir.json":
        "sha256:1d253f4e3b491c7fcd31fe4da609d02089bdfb92292a4fdd42bda02c3e0bf56e",
    PACKAGES + "a04_reserved_namespace_ack/expected.ir.json":
        "sha256:36dd61f95e6bbf7ad0f440ab2f999905808f96f30fe40d786959719fa54a801c",
    PACKAGES + "a05_standard_library/expected.ir.json":
        "sha256:d2dbcb0f88df1e7deca46f7576c816594d93e459f49ee9786ea249e42f802294",
}

# Goldens that came with version 2 and have no version 1 to be held to:
# their sources use syntax 0.3.
V2_ONLY = {ELABORATE + "a17_syntax_0_3_source_facts.expected.ir.json"}


def _goldens() -> set:
    found = {path.relative_to(ROOT).as_posix()
             for path in (ROOT / "benchmarks").glob("*/*.ir.json")
             if path.name == path.parent.name + ".ir.json"}
    found |= {path.relative_to(ROOT).as_posix()
              for path in (ROOT / ELABORATE).glob("*.expected.ir.json")}
    found |= {path.relative_to(ROOT).as_posix()
              for path in (ROOT / PACKAGES).glob("*/expected.ir.json")}
    return found


def as_version_1(document: dict) -> dict:
    """`document`, a version 2 IR, less what version 2 added: the two
    top-level arrays, a component's rules, a net's isolated and ground_kind,
    an assertion's severity; `ir_version` 1, and its hash blanked."""
    out = json.loads(json.dumps(document))
    del out["interfaces"]
    del out["annotations"]
    for instance in out["instances"]:
        instance.pop("rules", None)
    for net in out["nets"]:
        net.pop("isolated", None)
        net.pop("ground_kind", None)
    for assertion in out["assertions"]:
        assertion.pop("severity", None)
    out["header"]["ir_version"] = 1
    out["header"]["design_hash"] = ""
    return out


class PreservationOracleTest(unittest.TestCase):
    def test_every_golden_is_held_to_its_version_1_hash(self):
        # A golden added later, or one renamed, cannot slip past the oracle:
        # it is in the table or is declared version 2 only.
        self.assertEqual(_goldens(), set(V1_DESIGN_HASHES) | V2_ONLY)

    def test_version_2_less_its_additions_is_version_1(self):
        for name, v1_hash in sorted(V1_DESIGN_HASHES.items()):
            with self.subTest(name):
                document = json.loads((ROOT / name).read_text(
                    encoding="utf-8"))
                self.assertEqual(document["header"]["ir_version"], 2)
                stripped = as_version_1(document)
                self.assertEqual(ir.design_hash_of(stripped), v1_hash)
                self.assertEqual(GATE.design_hash_of(stripped), v1_hash)

    def test_a_0_1_or_0_2_design_adds_no_0_3_fact(self):
        # What the oracle strips from these is exactly what version 2 says
        # they hold: nothing a 0.3 statement states, and `isolated` only on
        # the nets an `isolated` statement made.
        isolated = 0
        for name in sorted(V1_DESIGN_HASHES):
            with self.subTest(name):
                document = json.loads((ROOT / name).read_text(
                    encoding="utf-8"))
                self.assertEqual(document["interfaces"], [])
                self.assertEqual(document["annotations"], [])
                self.assertFalse(any("rules" in i
                                     for i in document["instances"]))
                self.assertFalse(any("ground_kind" in n
                                     for n in document["nets"]))
                self.assertFalse(any("severity" in a
                                     for a in document["assertions"]))
                isolated += sum("isolated" in n for n in document["nets"])
        self.assertGreater(isolated, 0)

    def test_the_oracle_notices_a_change_it_does_not_strip(self):
        name = ELABORATE + "a01_hierarchy.expected.ir.json"
        document = json.loads((ROOT / name).read_text(encoding="utf-8"))
        document["nets"][0]["name"] += "x"
        self.assertNotEqual(ir.design_hash_of(as_version_1(document)),
                            V1_DESIGN_HASHES[name])

    def test_both_encoders_hash_a_version_2_design_alike(self):
        for name in sorted(V2_ONLY):
            with self.subTest(name):
                document = json.loads((ROOT / name).read_text(
                    encoding="utf-8"))
                self.assertTrue(document["annotations"])
                self.assertEqual(GATE.design_hash_of(document),
                                 document["header"]["design_hash"])
                self.assertEqual(ir.design_hash_of(document),
                                 document["header"]["design_hash"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class DeterminismTest(unittest.TestCase):
    def test_a_0_3_design_emits_the_same_bytes_under_any_hash_seed(self):
        script = (
            "import hashlib, sys\n"
            "from pathlib import Path\n"
            "from rhoform import compile as pipeline\n"
            "from rhoform.diagnostics import Diagnostics\n"
            "from rhoform.ir import emit\n"
            "root = Path(sys.argv[1]) / 'spec/conformance/elaborate/accept'\n"
            "sink = Diagnostics()\n"
            "compiled = pipeline.compile("
            "'a17_syntax_0_3_source_facts.rhoform', root, "
            "stage='elaborate', sink=sink)\n"
            "assert not sink.render(), sink.render()\n"
            "ir_bytes, map_bytes = emit(compiled.design)[:2]\n"
            "print(hashlib.sha256(ir_bytes + map_bytes).hexdigest())\n"
        )
        digests = set()
        for seed in ("0", "1", "4242"):
            run = subprocess.run(
                [sys.executable, "-c", script, str(ROOT)], cwd=ROOT,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            digests.add(run.stdout.strip())
        self.assertEqual(len(digests), 1)


if __name__ == "__main__":
    unittest.main()
