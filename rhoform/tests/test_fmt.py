"""The canonical formatter's contract (R16/I1, AC6; decision record F-1..F-12).

Three layers. Golden cases pin the canonical spelling of every construct and
every comment-attachment rule, for both syntax versions. The conformance
corpus pins refusal (every reject case) and acceptance (every accept case
formats to a clean fixed point), and every 0.2 source in it keeps its
normalized AST and its 0.2 constructs through formatting, while a seeded
fuzz over mutated 0.2 sources holds the formatter total. Seeded property
tests generate designs and render each one twice with independent
non-semantic perturbations - indent widths, spacing around `=` `~` `,`,
wrapped argument lists, blank-line runs, comment columns, equivalent quantity
spellings, permutations of sortable lists - and require both renderings to
format to the same bytes, the output to be a fixed point, and the normalized
AST to survive formatting.

Every test skips cleanly without lark, as test_parser.py does.
"""

import json
import random
import unittest
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

SKIP = "lark (pinned in toolchain/versions.yaml) is required"
P = "#pragma rhoform-syntax 0.1\n"
_ROOT = Path(__file__).resolve().parents[2]
_PARSE_CASES = _ROOT / "spec" / "conformance" / "parse"


def _fmt(source):
    from rhoform.fmt import format_source

    return format_source(source)


def _ast(source):
    from rhoform import fmt
    from rhoform.parser import parse

    parsed = parse(source)
    assert parsed.ok, parsed.diagnostics.render()
    return fmt.normalized_ast(fmt._build(source, parsed.tree))


# (name, input, expected canonical output). Inputs omit the pragma's
# trailing blank line on purpose: F-9 adds it.
GOLDEN = [
    ("minimal module", P + "module M:\n  port p passive\n",
     P + "\nmodule M:\n    port p passive\n"),
    ("final newline added", P + "module M:\n    port p passive",
     P + "\nmodule M:\n    port p passive\n"),
    ("modules keep source order, one blank line apart",
     P + "\n\n\nmodule Z:\n port a passive\n\n\n\nmodule A:\n port a passive\n",
     P + "\nmodule Z:\n    port a passive\n\nmodule A:\n    port a passive\n"),
    ("statements sort by kind rank then name",
     P + "module M:\n"
     "    assert a static frequency(N) at least 1Hz\n"
     "    a ~ b\n"
     "    isolated z\n"
     "    net N:\n        a\n"
     "    r1 = new L\n"
     "    table T ():\n        t1\n"
     "    port p passive\n",
     P + "\nmodule M:\n"
     "    port p passive\n"
     "    table T ():\n        t1\n"
     "    r1 = new L\n"
     "    net N:\n        a\n"
     "    a ~ b\n"
     "    isolated z\n"
     "    assert a static frequency(N) at least 1Hz\n"),
    ("isolated and chains keep source order within rank 4",
     P + "module M:\n    z ~ y\n    isolated b\n    a ~ c\n",
     P + "\nmodule M:\n    z ~ y\n    isolated b\n    a ~ c\n"),
    ("natural sort: c2 before c10",
     P + "module M:\n    c10 = new L\n    c2 = new L\n    c1 = new L\n",
     P + "\nmodule M:\n    c1 = new L\n    c2 = new L\n    c10 = new L\n"),
    ("tables sort by their least row name among instances' rank",
     P + "module M:\n    table B ():\n        r9\n    table A ():\n        r10\n",
     P + "\nmodule M:\n    table B ():\n        r9\n    table A ():\n        r10\n"),
    ("arguments sorted, spaced, unwrapped",
     P + "module M:\n    r=new lib.R(  b=2,a =\"x\",\n        c= true\n    )\n",
     P + "\nmodule M:\n    r = new lib.R(a = \"x\", b = 2, c = true)\n"),
    ("empty () dropped on an instance",
     P + "module M:\n    r = new L()\n",
     P + "\nmodule M:\n    r = new L\n"),
    ("instance body in F-5 order",
     P + "module M:\n    u = new L:\n        dnp\n        board_only\n"
     "        no exclude_from_bom\n        hardware test_point\n"
     "        part \"key\"\n        pin b passive\n        pin a passive\n",
     P + "\nmodule M:\n    u = new L:\n        pin a passive\n"
     "        pin b passive\n        part \"key\"\n        hardware test_point\n"
     "        no exclude_from_bom\n        board_only\n        dnp\n"),
    ("negated board_only and plain exclude_from_bom",
     P + "module M:\n    u = new L:\n        no board_only\n        exclude_from_bom\n",
     P + "\nmodule M:\n    u = new L:\n        exclude_from_bom\n        no board_only\n"),
    ("designators natural-sorted",
     P + "module M:\n    u = new L:\n        pin a passive B2 10 2 A1 1\n",
     P + "\nmodule M:\n    u = new L:\n        pin a passive 1 2 10 A1 B2\n"),
    ("part constraints sorted",
     P + "module M:\n    u = new L:\n        part abstract:\n"
     "            z = 1V\n            a = \"x\"\n",
     P + "\nmodule M:\n    u = new L:\n        part abstract:\n"
     "            a = \"x\"\n            z = 1V\n"),
    ("net attributes and members sorted, no space before (",
     P + "module M:\n    net N ( voltage_domain = \"5V\" , ground_domain = \"G\" ):\n"
     "        r10.a\n        r2.a\n        p\n",
     P + "\nmodule M:\n    net N(ground_domain = \"G\", voltage_domain = \"5V\"):\n"
     "        p\n        r2.a\n        r10.a\n"),
    ("empty () dropped on net attributes",
     P + "module M:\n    net N():\n        a\n",
     P + "\nmodule M:\n    net N:\n        a\n"),
    ("chain endpoints keep source order",
     P + "module M:\n    x~in.a  ~   b\n",
     P + "\nmodule M:\n    x ~ in.a ~ b\n"),
    ("table: one space before columns, columns kept, rows sorted and padded",
     P + "module M:\n    table lib.R part abstract (resistance,part.package):\n"
     "        r10 1kohm \"0402\"\n        r2 1000ohm \"0603\"\n        r1 10ohm \"0402\"\n",
     P + "\nmodule M:\n    table lib.R part abstract (resistance, part.package):\n"
     "        r1   10ohm  \"0402\"\n        r2   1kohm  \"0603\"\n"
     "        r10  1kohm  \"0402\"\n"),
    ("table keeps () and ragged rows pad by what they have",
     P + "module M:\n    table T part \"k\" ():\n        bb 1 2\n        a\n",
     P + "\nmodule M:\n    table T part \"k\" ():\n        a\n        bb  1  2\n"),
    ("assertion: no space before (, bounds normalized",
     P + "module M:\n    assert f static frequency (OUT) within 1000Hz to 2.0kHz\n"
     "    assert d static duty_cycle (OUT) within 0.50 to 0.6\n"
     "    assert v dynamic operating_point (OUT) at most 5000mV\n",
     P + "\nmodule M:\n    assert d static duty_cycle(OUT) within 0.50 to 0.6\n"
     "    assert f static frequency(OUT) within 1kHz to 2kHz\n"
     "    assert v dynamic operating_point(OUT) at most 5V\n"),
    ("quantities normalized, INTEGER verbatim",
     P + "module M:\n    r = new L(a = 4700pF, b = 2.0V +/- 10.0%, "
     "c = 9.5mA (8.0mA to 10.5mA), d = 1000mV to 3V, e = -0, f = 7ohm +/- 1000mohm)\n",
     P + "\nmodule M:\n    r = new L(a = 4.7nF, b = 2V +/- 10%, "
     "c = 9.5mA (8mA to 10.5mA), d = 1V to 3V, e = -0, f = 7ohm +/- 1ohm)\n"),
    ("blank lines and comments delimit sort runs",
     P + "module M:\n    r2 = new L\n    r1 = new L\n\n\n"
     "    port z passive\n    port a passive\n    # power section\n"
     "    c2 = new L\n    c1 = new L\n",
     P + "\nmodule M:\n    r1 = new L\n    r2 = new L\n\n"
     "    port a passive\n    port z passive\n\n    # power section\n"
     "    c1 = new L\n    c2 = new L\n"),
    ("no blank line after a header or before a dedent",
     P + "module M:\n\n    port a passive\n\n\nmodule N:\n    u = new L:\n\n"
     "        pin a passive\n\n        pin b passive\n\n    port b passive\n",
     P + "\nmodule M:\n    port a passive\n\nmodule N:\n    u = new L:\n"
     "        pin a passive\n        pin b passive\n\n    port b passive\n"),
]

COMMENT_GOLDEN = [
    ("header comments kept in order with their paragraph breaks",
     "\n# one   \n\n\n# two\n# three\n\n" + P + "module M:\n    port p passive\n",
     "# one\n\n# two\n# three\n\n" + P + "\nmodule M:\n    port p passive\n"),
    ("trailing comment after two spaces, trailing spaces stripped",
     P + "module M:   # m\n    port p passive        # t   \n",
     P + "\nmodule M:  # m\n    port p passive  # t\n"),
    ("# inside a string is not a comment",
     P + "module M:\n    r = new L(s = \"a#b\")  # real\n",
     P + "\nmodule M:\n    r = new L(s = \"a#b\")  # real\n"),
    ("own-line comment leads the next statement at its indent",
     P + "module M:\n    u = new L:\n  # about pin a\n            pin a passive\n",
     P + "\nmodule M:\n    u = new L:\n        # about pin a\n        pin a passive\n"),
    ("comments in sorted blocks travel with their statement",
     P + "module M:\n    net N:\n        # zed\n        z\n        a  # ay\n"
     "    u = new L:\n        dnp  # flag\n        # pin\n        pin a passive\n",
     P + "\nmodule M:\n    u = new L:\n        # pin\n        pin a passive\n"
     "        dnp  # flag\n    net N:\n        a  # ay\n        # zed\n        z\n"),
    ("a run's comments stay at its top while its statements sort",
     P + "module M:\n    # ports\n    port z passive  # zed\n    port a passive\n",
     P + "\nmodule M:\n    # ports\n    port a passive\n    port z passive  # zed\n"),
    ("a deeper comment trails the inner block it reaches",
     P + "module M:\n    u = new L:\n        pin a passive\n"
     "        # end of u\n    port p passive\n",
     P + "\nmodule M:\n    port p passive\n    u = new L:\n        pin a passive\n"
     "        # end of u\n"),
    ("the innermost reached block wins; reaching none, the outermost",
     P + "module M:\n    u = new L:\n        part abstract:\n            a = 1V\n"
     "          # reaches u's body only\n      # reaches nothing\n"
     "            # reaches the constraints\n    port p passive\n",
     P + "\nmodule M:\n    port p passive\n    u = new L:\n        part abstract:\n"
     "            a = 1V\n            # reaches the constraints\n"
     "        # reaches u's body only\n        # reaches nothing\n"),
    ("module-body trailer at the end of the file",
     P + "module M:\n    port p passive\n  # end of M\n",
     P + "\nmodule M:\n    port p passive\n    # end of M\n"),
    ("file trailer at column 0",
     P + "module M:\n    port p passive\n# end of file\n# really\n",
     P + "\nmodule M:\n    port p passive\n\n# end of file\n# really\n"),
    ("comments between modules lead the next module",
     P + "# about A\nmodule A:\n    port p passive\n# about B\nmodule B:\n"
     "    port p passive\n",
     P + "\n# about A\nmodule A:\n    port p passive\n\n# about B\nmodule B:\n"
     "    port p passive\n"),
    ("comments inside a wrapped argument list are hoisted (F-6)",
     P + "module M:\n    r = new L(  # open\n        # own line\n"
     "        b = 1,  # after b\n        a = 2)  # close\n",
     P + "\nmodule M:\n    # open\n    # own line\n    # after b\n"
     "    r = new L(a = 2, b = 1)  # close\n"),
    ("comments inside wrapped net attributes are hoisted",
     P + "module M:\n    net N(  # x\n        voltage_domain = \"5V\"\n    ):  # y\n        a\n",
     P + "\nmodule M:\n    # x\n    net N(voltage_domain = \"5V\"):  # y\n        a\n"),
    ("a trailing comment on a table row follows the padded row",
     P + "module M:\n    table T (v):\n        bb 1  # long\n        a 22\n",
     P + "\nmodule M:\n    table T (v):\n        a   22\n        bb  1  # long\n"),
]


@unittest.skipUnless(HAVE_LARK, SKIP)
class GoldenTest(unittest.TestCase):
    def _check(self, name, source, expected):
        with self.subTest(name):
            result = _fmt(source)
            self.assertTrue(result.ok, result.diagnostics.render())
            self.assertEqual(result.text, expected)
            self.assertEqual(_fmt(expected).text, expected)

    def test_every_construct(self):
        for name, source, expected in GOLDEN:
            self._check(name, source, expected)

    def test_every_comment_rule(self):
        for name, source, expected in COMMENT_GOLDEN:
            self._check(name, source, expected)

    def test_the_prototype_spacing_is_a_fixed_point(self):
        # The bake-off renderer's own layout (candidate_b), comment- and
        # blank-free: already canonical.
        source = P + (
            "\nmodule Blinker:\n"
            "    port vin power_in\n"
            "    table rhoform.lib.passive.Resistor part abstract (resistance, part.package):\n"
            "        r1  1kohm    \"0402\"\n"
            "        r2  100kohm  \"0402\"\n"
            "        r3  1kohm    \"0603\"\n"
            "    d1 = new rhoform.lib.semiconductor.Led(color = \"red\", forward_voltage = 2V +/- 10%):\n"
            "        pin a passive 1\n"
            "        pin k passive 2\n"
            "        part abstract:\n"
            "            package = \"0603\"\n"
            "            power_rating = 250mW\n"
            "        dnp\n"
            "    net VCC(voltage_domain = \"9V\"):\n"
            "        d1.a\n"
            "        vin\n"
            "    d1.k ~ r1.a\n"
            "    assert f static frequency(VCC) within 0.9 to 1.1\n"
        )
        from rhoform.fmt import is_canonical

        self.assertTrue(is_canonical(source))

    def test_digit_runs_sort_however_long(self):
        """Natural sort keys a digit run by its value without int(), which
        CPython refuses past sys.get_int_max_str_digits (4300 by default):
        a long designator or index used to crash `rhoform fmt`."""
        from rhoform.fmt import natural_key

        long = "1" * 5000
        self.assertLess(natural_key("2"), natural_key(long))
        self.assertLess(natural_key(long), natural_key("2" + "0" * 4999))
        self.assertLess(natural_key(long), natural_key("0" + long))
        self.assertLess(natural_key("0"), natural_key("00"))
        self.assertLess(natural_key("00"), natural_key("1"))
        self._check(
            "long designator and index",
            P2 + "\ncomponent C:\n    pin a passive " + long + " 2\n\n"
            "module M:\n    port p passive\n    cs = new C[2]\n"
            "    net N:\n        cs[" + long + "].a\n        cs[0].a\n",
            P2 + "\ncomponent C:\n    pin a passive 2 " + long + "\n\n"
            "module M:\n    port p passive\n    cs = new C[2]\n"
            "    net N:\n        cs[0].a\n        cs[" + long + "].a\n")

    def test_is_canonical_and_first_difference(self):
        from rhoform.fmt import first_difference, is_canonical

        self.assertFalse(is_canonical(P + "module M:\n  port p passive\n"))
        self.assertFalse(is_canonical(P + "module M:\n  prt p passive\n"))
        self.assertEqual(first_difference("abc", "abc"), -1)
        self.assertEqual(first_difference("abc", "abd"), 2)
        self.assertEqual(first_difference("ab", "abc"), 2)


@unittest.skipUnless(HAVE_LARK, SKIP)
class RefusalTest(unittest.TestCase):
    def _reject_sources(self):
        for path in sorted((_PARSE_CASES / "reject").iterdir()):
            if path.suffix == ".rhoform":
                yield path, path.read_text(encoding="utf-8")
            elif path.name.endswith(".rhoform.escaped"):
                raw = path.read_bytes().decode("ascii")
                data = raw.encode("ascii").decode("unicode_escape").encode("latin-1")
                yield path, data.decode("utf-8", errors="surrogateescape")

    def test_every_reject_case_is_refused_with_its_diagnostics(self):
        from rhoform.parser import parse

        cases = list(self._reject_sources())
        self.assertGreaterEqual(len(cases), 16)
        for path, source in cases:
            with self.subTest(path.name):
                result = _fmt(source)
                self.assertFalse(result.ok)
                self.assertIsNone(result.text)
                self.assertTrue(result.diagnostics.has_errors)
                self.assertEqual(result.diagnostics.render(),
                                 parse(source).diagnostics.render())

    def test_a_recovered_tree_is_never_formatted(self):
        # The broken line would vanish from a formatted recovered tree.
        result = _fmt(P + "module M:\n    port p passive\n    prt q passive\n")
        self.assertIsNone(result.text)
        codes = [json.loads(line)["code"]
                 for line in result.diagnostics.render().splitlines()]
        self.assertEqual(codes, ["RHO1006"])


P2 = "#pragma rhoform-syntax 0.2\n"
_FMT_CASES = _ROOT / "spec" / "conformance" / "fmt"

# The 0.2 surface, one golden per production: (name, input, canonical).
GOLDEN_0_2 = [
    ("imports sorted by path then names, names sorted, one blank line after",
     P2 + 'import  Resistor,Led   from "lib/parts.rhoform"\n\n'
     'import B from "lib/a.rhoform"\nimport A from "lib/a.rhoform"\n'
     'import R10, R2 from "lib/z.rhoform"\nmodule M:\n    port p passive\n',
     P2 + '\nimport A from "lib/a.rhoform"\nimport B from "lib/a.rhoform"\n'
     'import Led, Resistor from "lib/parts.rhoform"\n'
     'import R2, R10 from "lib/z.rhoform"\n\nmodule M:\n    port p passive\n'),
    ("components keep source order among definitions, pins sorted, () dropped",
     P2 + "module M:\n    u = new C\ncomponent C ( ):\n  pin k passive 2\n"
     "  pin a passive B2 1\n",
     P2 + "\nmodule M:\n    u = new C\n\ncomponent C:\n    pin a passive 1 B2\n"
     "    pin k passive 2\n"),
    ("parameters keep author order, spaced, unwrapped, defaults normalized",
     P2 + "module M(z:int=3,a : resistance = 10000ohm,\n"
     "         s: string=\"x\", r: resistance = a):\n    port p passive\n",
     P2 + "\nmodule M(z: int = 3, a: resistance = 10kohm, s: string = \"x\", "
     "r: resistance = a):\n    port p passive\n"),
    ("empty () dropped on a module",
     P2 + "module M():\n    port p passive\n",
     P2 + "\nmodule M:\n    port p passive\n"),
    ("if/else spacing, operand normalized, branches sorted by F-1",
     P2 + "module M(n: int = 1, v: voltage = 1V, on: bool = true):\n"
     "    if n>2 :\n        a ~ b\n        port q passive\n    else :\n"
     "        isolated a\n    if v>=3300mV:\n        isolated b\n"
     "    if on:\n        isolated c\n",
     P2 + "\nmodule M(n: int = 1, v: voltage = 1V, on: bool = true):\n"
     "    if n > 2:\n        port q passive\n        a ~ b\n    else:\n"
     "        isolated a\n    if v >= 3.3V:\n        isolated b\n"
     "    if on:\n        isolated c\n"),
    ("if and for share rank 4 with chains and isolated, in source order",
     P2 + "module M(n: int = 1):\n    isolated z\n    for i in range(n):\n"
     "        isolated a\n    a ~ b\n    if n > 0:\n        isolated b\n"
     "    port p passive\n",
     P2 + "\nmodule M(n: int = 1):\n    port p passive\n    isolated z\n"
     "    for i in range(n):\n        isolated a\n    a ~ b\n    if n > 0:\n"
     "        isolated b\n"),
    ("for spacing, bounds kept, wrapped bounds unwrapped",
     P2 + "module M(n: int = 1):\n    for i in range( 4 ):\n        isolated a\n"
     "    for j in range(1 ,\n            n):\n        isolated b\n",
     P2 + "\nmodule M(n: int = 1):\n    for i in range(4):\n        isolated a\n"
     "    for j in range(1, n):\n        isolated b\n"),
    ("arrays and indexes spaced, members natural-sorted on the printed endpoint",
     P2 + "module M:\n    r = new Q [4] ( a=1 )\n    net N:\n        r[10].a\n"
     "        r[ 2 ].a\n        r[i+1].a\n        r[i].a\n"
     "    r[ i - 1 ].b~r[-1]\n",
     # Natural sort on the printed text, so `r[i + 1].a` precedes
     # `r[i].a`: a space sorts before `]`.
     P2 + "\nmodule M:\n    r = new Q[4](a = 1)\n    net N:\n        r[2].a\n"
     "        r[10].a\n        r[i + 1].a\n        r[i].a\n"
     "    r[i - 1].b ~ r[-1]\n"),
]

# Comments around `if`/`else`/`for` blocks (F-10 with the `else:` line as a
# unit of its own).
COMMENT_GOLDEN_0_2 = [
    ("a comment above else leads it; a deeper one trails the if branch",
     P2 + "module M(on: bool = true):\n    if on:\n        isolated a\n"
     "          # deeper: trails the if branch\n    # leads else\n"
     "    else:  # else trailer\n        isolated b\n",
     P2 + "\nmodule M(on: bool = true):\n    if on:\n        isolated a\n"
     "        # deeper: trails the if branch\n    # leads else\n"
     "    else:  # else trailer\n        isolated b\n"),
    ("trailers of else and for bodies; a run comment inside a branch",
     P2 + "module M(on: bool = true):\n    if on:  # header\n"
     "        isolated a\n        # second run\n        isolated b\n"
     "    else:\n        isolated c\n        # end of else\n"
     "    for i in range(2):\n        isolated x[i]\n        # end of for\n"
     "    port p passive\n",
     P2 + "\nmodule M(on: bool = true):\n    port p passive\n"
     "    if on:  # header\n        isolated a\n\n        # second run\n"
     "        isolated b\n    else:\n        isolated c\n        # end of else\n"
     "    for i in range(2):\n        isolated x[i]\n        # end of for\n"),
    ("a comment between imports travels with the import below it",
     P2 + 'import B from "b"\n# about a\nimport A from "a"\n'
     "module M:\n    port p passive\n",
     P2 + '\n# about a\nimport A from "a"\nimport B from "b"\n'
     "\nmodule M:\n    port p passive\n"),
    ("comments in a component body travel with their pins",
     P2 + "component C:\n    # about z\n    pin z passive\n    pin a passive  # a\n"
     "      # end of C\nmodule M:\n    port p passive\n",
     P2 + "\ncomponent C:\n    pin a passive  # a\n    # about z\n"
     "    pin z passive\n    # end of C\n\nmodule M:\n    port p passive\n"),
]

# One source per 0.2 construct, each the construct's only use. Before the
# interim refusal the formatter DROPPED imports and component definitions
# (the walk only knew modules, and the self-check compared two documents
# that both lacked them) and raised FormatterError on the rest; the
# refusal (RHO2033) is now replaced by real formatting.
SYNTAX_0_2 = [
    'import Led from "parts.rhoform"\nmodule M:\n    port p passive\n',
    "component Led:\n    pin a passive\nmodule M:\n    port p passive\n",
    "module M(n: int = 2):\n    port p passive\n",
    "module M:\n    port p passive\n    if fast:\n        isolated p\n",
    "module M:\n    port p passive\n    for i in range(2):\n"
    "        isolated p\n",
    "module M:\n    r = new lib.R[2]\n",
    "module M:\n    port p passive\n    isolated r[0].a\n",
    "module M:\n    r = new lib.R(resistance = r_value)\n",
    "module M(n: int = 2):\n    r = new lib.R[2]\n    for i in range(n):\n"
    "        if i == 0:\n            isolated r[i].a\n        else:\n"
    "            isolated r[i].b\n",
]


def _sources_0_2():
    """Every 0.2 source this suite and the conformance corpus hold."""
    sources = [("parse/accept/" + p.name, p.read_text(encoding="utf-8"))
               for p in sorted((_PARSE_CASES / "accept").glob("*.rhoform"))]
    sources += [("fmt/" + p.name, p.read_text(encoding="utf-8"))
                for p in sorted(_FMT_CASES.glob("*.rhoform"))]
    sources += [(name, source) for name, source, _ in
                GOLDEN_0_2 + COMMENT_GOLDEN_0_2]
    sources += [(f"SYNTAX_0_2[{n}]", P2 + body)
                for n, body in enumerate(SYNTAX_0_2)]
    return [(name, source) for name, source in sources
            if source.startswith(P2)]


def _constructs(source):
    """Every construct newer than 0.1, by name, as the parser's version
    gate finds them (the finder RHO1016 rests on, which shares nothing with
    the formatter). An empty `()` is not counted: F-7 drops it."""
    from collections import Counter

    from rhoform.parser import _load, _newer_constructs, parse

    parsed = parse(source)
    return Counter(
        construct for start, end, construct, _version
        in _newer_constructs(parsed.data, parsed.shift, parsed.tree, _load())
        if parsed.data[start:end].translate(None, b" \n") != b"()")


@unittest.skipUnless(HAVE_LARK, SKIP)
class Syntax02Test(unittest.TestCase):
    """The canonical form of the 0.2 surface: goldens per production and
    per comment rule, design preservation, and totality."""

    def _check(self, name, source, expected):
        with self.subTest(name):
            result = _fmt(source)
            self.assertTrue(result.ok, result.diagnostics.render())
            self.assertEqual(result.text, expected)
            self.assertEqual(_fmt(expected).text, expected)

    def test_every_production(self):
        for name, source, expected in GOLDEN_0_2:
            self._check(name, source, expected)

    def test_every_comment_rule_around_blocks(self):
        for name, source, expected in COMMENT_GOLDEN_0_2:
            self._check(name, source, expected)

    def test_each_construct_formats_and_survives(self):
        # Each construct the interim refusal named now formats, and is
        # still there afterwards: the parser's own construct finder, which
        # shares nothing with the formatter, counts the same constructs in
        # the output as in the input.
        for body in SYNTAX_0_2:
            source = P2 + body
            with self.subTest(body):
                result = _fmt(source)
                self.assertTrue(result.ok, result.diagnostics.render())
                self.assertEqual(_constructs(result.text), _constructs(source))
                self.assertTrue(_constructs(source))

    def test_design_preservation_over_every_0_2_input(self):
        sources = _sources_0_2()
        self.assertGreaterEqual(len(sources), 30)
        for name, source in sources:
            with self.subTest(name):
                result = _fmt(source)
                self.assertTrue(result.ok, result.diagnostics.render())
                self.assertEqual(_ast(result.text), _ast(source))
                self.assertEqual(_constructs(result.text), _constructs(source))
                self.assertEqual(_fmt(result.text).text, result.text)
                self.assertEqual(result.text.split("\n", 1)[0], P2.rstrip("\n"))

    def test_a_0_1_file_never_gains_0_2_syntax(self):
        # The pragma line is written as authored and the formatter adds no
        # construct, so every 0.1 source formats to a 0.1 source.
        from rhoform.parser import parse

        p1 = P.rstrip("\n")
        sources = [p.read_text(encoding="utf-8") for p in
                   sorted((_PARSE_CASES / "accept").glob("*.rhoform"))
                   + sorted(_FMT_CASES.glob("*.rhoform"))]
        sources += [source for _, source, _ in GOLDEN + COMMENT_GOLDEN]
        checked = 0
        for source in sources:
            if p1 + "\n" not in source:
                continue
            with self.subTest(source[:80]):
                text = _fmt(source).text
                self.assertIn("\n" + p1 + "\n", "\n" + text)
                self.assertNotIn(P2.rstrip("\n"), text)
                self.assertTrue(parse(text).ok)
                self.assertFalse(_constructs(text))
                checked += 1
        self.assertGreaterEqual(checked, 40)

    def test_a_0_2_file_of_0_1_constructs_formats_and_keeps_its_pragma(self):
        result = _fmt(P2 + "module M:\n  port p passive\n")
        self.assertEqual(result.text, P2 + "\nmodule M:\n    port p passive\n")

    def test_output_independent_of_hash_seed(self):
        import subprocess
        import sys

        script = (
            "import hashlib, sys\n"
            "from pathlib import Path\n"
            "from rhoform.fmt import format_source\n"
            "root = Path(sys.argv[1])\n"
            "paths = sorted((root / 'spec/conformance/parse/accept')"
            ".glob('*.rhoform')) + sorted((root / 'spec/conformance/fmt')"
            ".glob('*.rhoform'))\n"
            "digest = hashlib.sha256()\n"
            "for path in paths:\n"
            "    text = format_source(path.read_text(encoding='utf-8')).text\n"
            "    digest.update(repr(text).encode())\n"
            "print(digest.hexdigest())\n"
        )
        digests = set()
        for seed in ("0", "1", "4242"):
            run = subprocess.run(
                [sys.executable, "-c", script, str(_ROOT)], cwd=_ROOT,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            digests.add(run.stdout.strip())
        self.assertEqual(len(digests), 1)


P3 = "#pragma rhoform-syntax 0.3\n"

# The 0.3 surface (unfrozen), one golden per production: (name, input,
# canonical).
GOLDEN_0_3 = [
    ("a component body is pins, then rules by line, then sides by name",
     P3 + "component C:\n    side s2 :b\n    tie a  b\n    pin b passive 2\n"
     "    side s1: a\n    conduct a to b = 1000mohm\n    pin a passive 1\n",
     P3 + "\ncomponent C:\n    pin a passive 1\n    pin b passive 2\n"
     "    conduct a to b = 1ohm\n    tie a b\n    side s1: a\n"
     "    side s2: b\n"),
    ("a rule keeps its pins in author order",
     P3 + "component C:\n    pin a passive 1\n    pin b passive 2\n"
     "    tie b a\n",
     P3 + "\ncomponent C:\n    pin a passive 1\n    pin b passive 2\n"
     "    tie b a\n"),
    ("a quoted designator sorts with the others, as written",
     P3 + 'component C:\n    pin a passive "02" 1\n',
     P3 + '\ncomponent C:\n    pin a passive "02" 1\n'),
    ("module statements: rule after instances, annotations after "
     "connections, waivers last",
     P3 + 'module M:\n    waive RHO3001 u "x"\n'
     "    assert a static operating_point(N) at most 1V   warning\n"
     "    supply N within 4.5V to 5.5V\n    draw u.a at most 5000uA\n"
     "    a ~ b\n    rule u  tie a b\n    u = new C\n    port p passive\n",
     P3 + "\nmodule M:\n    port p passive\n    u = new C\n    rule u tie a b\n"
     "    a ~ b\n    draw u.a at most 5mA\n    supply N within 4.5V to 5.5V\n"
     "    assert a static operating_point(N) at most 1V warning\n"
     '    waive RHO3001 u "x"\n'),
    ("indexed targets and ground_kind",
     P3 + 'module M:\n    net N ( ground_kind="power" ):\n        a\n'
     "    supply us[ 1 ].a at most 1A\n",
     P3 + '\nmodule M:\n    net N(ground_kind = "power"):\n        a\n'
     "    supply us[1].a at most 1A\n"),
    ("an interface's members by name, its empty parameter list dropped",
     P3 + "interface I ( ):\n    port z = new J [ 2 ]\n    port a[ 3 ]\n",
     P3 + "\ninterface I:\n    port a[3]\n    port z = new J[2]\n"),
    ("a bundle port ranks with the ports, by name",
     P3 + "module M:\n    u = new C\n    port z passive\n"
     "    port p=new I [2] ( v=3.30V )\n    port a passive\n",
     P3 + "\nmodule M:\n    port a passive\n    port p = new I[2](v = 3.3V)\n"
     "    port z passive\n    u = new C\n"),
    ("views follow the sides, their bindings by member path",
     P3 + "component C:\n    port v = new I :\n        d[10] = b\n"
     "        d[2]=a\n    side s: a\n    pin b passive 2\n"
     "    pin a passive 1\n",
     P3 + "\ncomponent C:\n    pin a passive 1\n    pin b passive 2\n"
     "    side s: a\n    port v = new I:\n        d[2] = a\n"
     "        d[10] = b\n"),
    ("a member access is spelled tight, a net's members naturally",
     P3 + "module M:\n    net N:\n        c[ 10 ] .p.hv\n        c[2].p . hv\n"
     "    a . b [ i + 1 ] . c ~ x\n",
     P3 + "\nmodule M:\n    net N:\n        c[2].p.hv\n        c[10].p.hv\n"
     "    a.b[i + 1].c ~ x\n"),
]


def _package_design(directory, texts):
    """(design_hash or None, sorted codes) of compiling the package in
    `directory` from its one main.rhoform, wherever it sits, each file of
    `texts` (path relative to it -> source) replacing that file's bytes, in
    a scratch copy."""
    import shutil
    import tempfile

    from rhoform import compile as pipeline
    from rhoform import ir
    from rhoform.diagnostics import Diagnostics

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / directory.name
        shutil.copytree(directory, root, ignore=shutil.ignore_patterns(
            "*.expected.rhoform", "expected.*"))
        for relative, text in texts.items():
            (root / relative).write_text(text, encoding="utf-8")
        (entry,) = root.rglob("main.rhoform")
        sink = Diagnostics()
        compiled = pipeline.compile(entry.relative_to(root).as_posix(), root,
                                    stage="elaborate", sink=sink)
        design = (None if compiled.design is None else
                  ir.design_hash_of(ir.to_ir(compiled.design)))
        return design, sorted(json.loads(line)["code"]
                              for line in sink.render().splitlines())


@unittest.skipUnless(HAVE_LARK, SKIP)
class Syntax03Test(unittest.TestCase):
    """The canonical form of the unfrozen 0.3 surface, AMB-140's hoisting
    rule, and design preservation across a package's files (AMB-144 #9)."""

    def test_every_production(self):
        for name, source, expected in GOLDEN_0_3:
            with self.subTest(name):
                result = _fmt(source)
                self.assertTrue(result.ok, result.diagnostics.render())
                self.assertEqual(result.text, expected)
                self.assertEqual(_fmt(expected).text, expected)
                self.assertEqual(_ast(result.text), _ast(source))
                self.assertEqual(_constructs(result.text), _constructs(source))

    def test_a_hoisted_comment_stays_above_its_own_statement(self):
        # AMB-140: the comment came out of r1's header, and used to lead a
        # run that `port p` sorted to the top of.
        source = (P2 + "module M:\n    r1 = new lib.R(  # about r1\n"
                  "        resistance = 1kohm)\n    port p passive\n"
                  "    r0 = new lib.R\n")
        text = _fmt(source).text
        self.assertEqual(text, P2 + "\nmodule M:\n    # about r1\n"
                         "    r1 = new lib.R(resistance = 1kohm)\n\n"
                         "    port p passive\n    r0 = new lib.R\n")
        self.assertEqual(_fmt(text).text, text)

    def test_formatting_keeps_every_0_3_design(self):
        sources = [path for path in
                   sorted((_PARSE_CASES / "accept").glob("*.rhoform"))
                   + sorted(_FMT_CASES.glob("*.rhoform"))
                   + sorted((_ROOT / "spec" / "conformance" / "elaborate")
                            .rglob("*.rhoform"))
                   if path.read_text(encoding="utf-8").find(P3) >= 0]
        self.assertGreaterEqual(len(sources), 6)
        designs = 0
        for path in sources:
            with self.subTest(path.name):
                source = path.read_text(encoding="utf-8")
                result = _fmt(source)
                if result.text is None:
                    continue
                self.assertEqual(_fmt(result.text).text, result.text)
                self.assertEqual(_constructs(result.text), _constructs(source))
                before = _design_and_codes(source, path.name)
                self.assertEqual(_design_and_codes(result.text, path.name),
                                 before)
                designs += before[0] is not None
        self.assertGreaterEqual(designs, 3)

    def test_formatting_a_package_keeps_its_design(self):
        """The single-file preservation tests cannot see an import: this
        formats every file of each multi-file package and compiles the
        package again (AMB-144 #9)."""
        packages = ([_FMT_CASES / "f28_package"]
                    + sorted(p for p in (_ROOT / "spec" / "conformance"
                                         / "packages" / "accept").iterdir()
                             if p.is_dir()))
        changed = 0
        for package in packages:
            with self.subTest(package.name):
                files = sorted(path for path in package.rglob("*.rhoform")
                               if not path.name.endswith(".expected.rhoform"))
                self.assertGreater(len(files), 1)
                texts = {}
                for path in files:
                    source = path.read_text(encoding="utf-8")
                    result = _fmt(source)
                    self.assertTrue(result.ok, result.diagnostics.render())
                    self.assertEqual(_fmt(result.text).text, result.text)
                    texts[path.relative_to(package).as_posix()] = result.text
                    changed += result.text != source
                before = _package_design(package, {})
                self.assertIsNotNone(before[0], before[1])
                self.assertEqual(_package_design(package, texts), before)
        # The fmt case's sources are not canonical, so formatting did work.
        self.assertGreaterEqual(changed, 2)


# Mutations for the totality fuzz: each takes (rng, lines) and returns new
# lines. They break layout, punctuation and keywords on purpose, so most
# mutants do not parse; the ones that do are the inputs nobody wrote a
# golden for.
_FRAGMENTS = ("[", "]", "(", ")", ":", ",", "+ 1", "- 1", "~", "=", " ",
              "if", "else:", "for i in range(2):", "# c", "[i]", "[0]",
              "== 1", "> n", "()", "  ", ".a", "import X from \"x\"")


def _mutate(rng, lines):
    lines = list(lines)
    kind = rng.randrange(8)
    at = rng.randrange(len(lines))
    if kind == 0 and len(lines) > 2:
        del lines[at]
    elif kind == 1:
        lines.insert(at, lines[at])
    elif kind == 2:
        other = rng.randrange(len(lines))
        lines[at], lines[other] = lines[other], lines[at]
    elif kind == 3:
        stripped = lines[at].lstrip(" ")
        indent = max(0, len(lines[at]) - len(stripped) + rng.choice((-4, -1, 1, 4)))
        lines[at] = " " * indent + stripped
    elif kind == 4:
        lines.insert(at, " " * rng.randrange(13) + "# m" + str(rng.randrange(9)))
    elif kind == 5:
        lines[at] += rng.choice(("  # t", "", "\n"))
    elif kind == 6:
        line = lines[at]
        cut = rng.randrange(len(line) + 1)
        lines[at] = line[:cut] + rng.choice(_FRAGMENTS) + line[cut:]
    else:
        line = lines[at]
        if line:
            cut = rng.randrange(len(line))
            lines[at] = line[:cut] + line[cut + rng.randint(1, 3):]
    return "\n".join(lines).split("\n")


FUZZ_MUTANTS = 900


@unittest.skipUnless(HAVE_LARK, SKIP)
class TotalityFuzzTest(unittest.TestCase):
    """No input may crash the formatter: a mutant that parses clean formats
    to a fixed point with its normalized AST preserved, and one that does
    not is refused with diagnostics. FormatterError counts as a crash
    here, because on a clean parse it is a formatter defect."""

    def test_mutated_0_2_sources(self):
        seeds = [source for _, source in _sources_0_2()]
        rng = random.Random(20261022)
        clean = 0
        for number in range(FUZZ_MUTANTS):
            lines = rng.choice(seeds).split("\n")
            for _ in range(rng.randint(1, 3)):
                lines = _mutate(rng, lines)
            source = "\n".join(lines)
            with self.subTest(number=number, source=source):
                result = _fmt(source)
                if result.text is None:
                    self.assertTrue(result.diagnostics.has_errors)
                    continue
                clean += 1
                self.assertEqual(_fmt(result.text).text, result.text)
                self.assertEqual(_ast(result.text), _ast(source))
        # The fuzz must reach the formatter, not only the parser.
        self.assertGreaterEqual(clean, 150)

    def test_nesting_as_deep_as_the_parser_accepts(self):
        """Blocks nest without bound, so no walk may spend a Python frame
        per level: 1000 levels of `for` and `if`/`else` parse, format and
        elaborate. 300 used to overflow the normalized-AST walk, and 330
        the parser's own quantity scan, which the self-check re-parse hit."""
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        lines = [P2, "module M(flag: bool = true):", "    port a passive",
                 "    port b passive"]
        branches = []
        indent = "    "
        for level in range(1000):
            if level % 2:
                lines.append(indent + "if flag:")
                branches.append([indent + "else:", indent + "    b ~ a"])
            else:
                lines.append(indent + f"for i{level} in range(1):")
            indent += "    "
        lines.append(indent + "a ~ b")
        for branch in reversed(branches):
            lines += branch
        source = "\n".join(lines) + "\n"
        parsed = parse(source)
        self.assertTrue(parsed.ok, parsed.diagnostics.render())
        result = _fmt(source)
        self.assertIsNotNone(result.text, result.diagnostics.render())
        self.assertEqual(_fmt(result.text).text, result.text)
        self.assertIsNotNone(elaborate([parse(result.text)]).design)


@unittest.skipUnless(HAVE_LARK, SKIP)
class ConformanceAcceptTest(unittest.TestCase):
    def test_every_accept_case_formats_to_a_clean_fixed_point(self):
        from rhoform.parser import parse

        paths = sorted((_PARSE_CASES / "accept").glob("*.rhoform"))
        self.assertGreaterEqual(len(paths), 16)
        for path in paths:
            with self.subTest(path.name):
                source = path.read_text(encoding="utf-8")
                result = _fmt(source)
                self.assertTrue(result.ok, result.diagnostics.render())
                self.assertTrue(parse(result.text).ok)
                self.assertEqual(_fmt(result.text).text, result.text)
                self.assertEqual(_ast(result.text), _ast(source))


def _design_and_codes(source, name):
    """(design_hash or None, sorted codes) of compiling `source` alone.
    Codes, not whole diagnostics: messages echo the author's spelling
    (`3.0V` vs `3V`), which formatting is allowed to change."""
    from rhoform import ir
    from rhoform.elaborate import elaborate
    from rhoform.parser import parse

    parsed = parse(source, file=name)
    sink = parsed.diagnostics
    design = None
    if parsed.ok:
        elaboration = elaborate([parsed])
        sink = elaboration.diagnostics
        if elaboration.design is not None:
            design = ir.design_hash_of(ir.to_ir(elaboration.design))
    codes = sorted(json.loads(line)["code"]
                   for line in sink.render().splitlines())
    return design, codes


@unittest.skipUnless(HAVE_LARK, SKIP)
class FormattingPreservesTheDesignTest(unittest.TestCase):
    """The formatter and elaborator were written apart; this is where they
    meet. Formatting must not change what a source elaborates to, and the
    sources the elaborator is pinned by are themselves canonical."""

    def _sources(self):
        conformance = _ROOT / "spec" / "conformance"
        return sorted(
            list((conformance / "elaborate").rglob("*.rhoform"))
            + list((_ROOT / "benchmarks").glob("*/*.rhoform")))

    def test_elaboration_cases_and_benchmarks_are_canonical(self):
        paths = self._sources()
        self.assertGreaterEqual(len(paths), 60)
        for path in paths:
            with self.subTest(str(path.relative_to(_ROOT))):
                source = path.read_text(encoding="utf-8")
                self.assertEqual(_fmt(source).text, source)

    def test_formatting_keeps_the_design_hash_and_the_codes(self):
        paths = (self._sources()
                 + sorted((_PARSE_CASES / "accept").glob("*.rhoform"))
                 + sorted(_FMT_CASES.glob("f*.rhoform")))
        designs = 0
        for path in paths:
            with self.subTest(str(path.relative_to(_ROOT))):
                source = path.read_text(encoding="utf-8")
                result = _fmt(source)
                if result.text is None:
                    continue
                before = _design_and_codes(source, path.name)
                self.assertEqual(_design_and_codes(result.text, path.name),
                                 before)
                designs += before[0] is not None
        # Every elaboration accept case and benchmark must have reached
        # the hash comparison, not only the code comparison.
        self.assertGreaterEqual(designs, 15)

    def test_an_empty_parameter_list_is_no_list(self):
        """The formatter drops `()` on a definition (F-7), so the elaborator
        may not give it a meaning: a typed list of nothing would reject the
        arguments that the formatted file, with no list, records."""
        source = (P2 + "\ncomponent C():\n    pin a passive\n"
                  "    pin b passive\n\nmodule M():\n    port p passive\n"
                  "    c = new C(x = 1)\n    c.a ~ p\n    table C (y):\n"
                  "        t1  2\n\nmodule Top:\n    port p passive\n"
                  "    m = new M(y = 2)\n    m.p ~ p\n")
        formatted = _fmt(source).text
        self.assertNotIn("()", formatted)
        before = _design_and_codes(source, "e.rhoform")
        self.assertEqual(_design_and_codes(formatted, "e.rhoform"), before)
        self.assertIsNotNone(before[0], before[1])


# --------------------------------------------------------------------------
# Property tests: a seeded design generator and a perturbing writer
# --------------------------------------------------------------------------
#
# The generator builds a design MODEL; the writer spells it as source with
# random non-semantic choices. Two writers with different seeds spell the
# same model differently but always with the same normalized AST (F-12), so
# AC6 says they must format to identical bytes. The writer only varies what
# F-12 erases: indentation, intra-line spacing, wrapping, blank lines that
# do not delimit a run, comment columns within one attachment class,
# quantity spellings, and the order of sortable lists (never the relative
# order of chains and `isolated`, which F-1 sorts by source index).

from decimal import Decimal  # noqa: E402

PIN_ROLES = ("power_in", "power_out", "passive", "bidirectional", "input",
             "output", "nc", "open_drain")
HARDWARE = ("mounting_hole", "fiducial", "artwork", "test_point",
            "grounded_mounting_hole")
MEASURES = ("operating_point", "ripple", "frequency", "duty_cycle", "gain")
MANTISSAS = ("1", "2.2", "4.7", "10", "33", "100", "470", "0.5", "1.5")
COMMENT_WORDS = ("power", "see datasheet", "a#b", 'quote "x"', "(paren",
                 "TODO", "x ~ y", "= 3", ",", "#")


def _ladders():
    from rhoform.quantities import UNITS

    ladders = {}
    for unit, (dimension, mult) in UNITS.items():
        if dimension != "temperature":
            ladders.setdefault(dimension, []).append((unit, mult))
    return {d: sorted(l, key=lambda p: p[1]) for d, l in ladders.items()}


class Quantity:
    """A quantity literal as value-exact base-unit pairs plus its form; the
    writer picks a unit per pair, so spellings vary and values do not."""

    def __init__(self, rng, ladders, form=None):
        self.dimension = rng.choice(sorted(ladders))
        unit, mult = rng.choice(ladders[self.dimension])
        base = Decimal(rng.choice(MANTISSAS)) * mult
        self.form = form or rng.choice(
            ("exact", "exact", "percent", "absolute", "bracketed", "interval"))
        delta = base / 10
        self.pairs = {
            "exact": [base],
            "percent": [base],
            "absolute": [base, delta],
            "bracketed": [base, base - delta, base + delta],
            "interval": [base - delta, base + delta],
        }[self.form]
        self.percent = Decimal(rng.choice(("1", "5", "10", "0.5")))
        self.ladder = ladders[self.dimension]

    @staticmethod
    def number(rng, value):
        text = format(value.normalize(), "f")
        if rng.random() < 0.3:
            text += ("" if "." in text else ".") + "0" * rng.randint(1, 2)
        return text

    def pair(self, rng, value):
        options = [(u, value / m) for u, m in self.ladder
                   if Decimal("1e-6") <= abs(value / m) < Decimal("1e9")]
        unit, mantissa = rng.choice(options)
        return self.number(rng, mantissa) + unit

    def spell(self, rng):
        p = [self.pair(rng, v) for v in self.pairs]
        if self.form == "exact":
            return p[0]
        if self.form == "percent":
            return f"{p[0]} +/- {self.number(rng, self.percent)}%"
        if self.form == "absolute":
            return f"{p[0]} +/- {p[1]}"
        if self.form == "bracketed":
            return f"{p[0]} ({p[1]} to {p[2]})"
        return f"{p[0]} to {p[1]}"


class Literal:
    def __init__(self, text):
        self.text = text

    def spell(self, rng):
        return self.text


class Item:
    """One line unit: a header, an optional sorted block of child items,
    comments, and (for module statements) a sort rank."""

    def __init__(self, kind, **fields):
        self.kind = kind
        self.leading = []      # own-line comments (sorted blocks only)
        self.trailing = None
        self.hoisted = []      # comments written inside its parentheses
        self.children = []     # a sorted block
        self.trailer = []      # comments trailing that block
        self.__dict__.update(fields)


class DesignGenerator:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.ladders = _ladders()
        self.used = set()
        self.comments = 0

    def name(self):
        while True:
            text = self.rng.choice(("r", "c", "u", "n", "net_", "x")) + \
                str(self.rng.randint(0, 120))
            if text not in self.used:
                self.used.add(text)
                return text

    def comment(self):
        self.comments += 1
        words = " ".join(self.rng.sample(COMMENT_WORDS, 2))
        return f"# c{self.comments} {words}" + " " * self.rng.randint(0, 1)

    def maybe(self, p):
        return self.rng.random() < p

    def value(self):
        roll = self.rng.random()
        if roll < 0.55:
            return Quantity(self.rng, self.ladders)
        if roll < 0.75:
            return Literal(f'"{self.rng.choice(("0402", "a#b", "X7R", ""))}"')
        if roll < 0.9:
            return Literal(str(self.rng.choice((0, 1, 8, 42, -3))))
        return Literal(self.rng.choice(("true", "false")))

    def endpoint(self):
        if self.maybe(0.3):
            return self.name()
        return f"{self.name()}.{self.rng.choice(('a', 'b', 'net', 'vcc', 'p1'))}"

    def comments_for(self, item, sorted_block):
        if sorted_block and self.maybe(0.25):
            item.leading = [self.comment() for _ in range(self.rng.randint(1, 2))]
        if self.maybe(0.25):
            item.trailing = self.comment()

    def sub_item(self, kind, **fields):
        item = Item(kind, **fields)
        self.comments_for(item, sorted_block=True)
        return item

    def instance(self):
        args = {self.name(): self.value() for _ in range(self.rng.randint(0, 3))}
        item = Item("instance", name=self.name(),
                    definition=self.rng.choice(("L", "lib.R", "rhoform.lib.passive.Capacitor")),
                    args=args, empty_parens=self.maybe(0.3))
        body = []
        for _ in range(self.rng.randint(0, 3)):
            designators = self.rng.sample(
                ("1", "2", "3", "10", "11", "A1", "A2", "B10"), self.rng.randint(0, 3))
            body.append(self.sub_item("pin", name=self.name(),
                                      role=self.rng.choice(PIN_ROLES),
                                      designators=designators))
        if self.maybe(0.5):
            part = self.sub_item("part", binding=self.rng.choice(
                ("abstract", '"GRM#155"')))
            part.children = [
                self.sub_item("constraint", name=self.name(), value=self.value())
                for _ in range(self.rng.randint(0, 3))]
            if part.children and self.maybe(0.2):
                part.trailer = [self.comment()]
            body.append(part)
        if self.maybe(0.3):
            body.append(self.sub_item("hardware", hw=self.rng.choice(HARDWARE)))
        for word in ("exclude_from_bom", "board_only"):
            if self.maybe(0.3):
                body.append(self.sub_item("flag", text=self.rng.choice((word, "no " + word))))
        if self.maybe(0.3):
            body.append(self.sub_item("flag", text="dnp"))
        item.children = body
        if body and self.maybe(0.2):
            item.trailer = [self.comment()]
        return item

    def statement(self):
        kind = self.rng.choice(("port", "instance", "instance", "net", "table",
                                "isolated", "chain", "assert"))
        if kind == "port":
            return Item("port", name=self.name(), role=self.rng.choice(PIN_ROLES))
        if kind == "instance":
            return self.instance()
        if kind == "net":
            attrs = self.rng.sample(("voltage_domain", "ground_domain"),
                                    self.rng.randint(0, 2))
            item = Item("net", name=self.name(),
                        attrs={a: f'"{self.rng.choice(("5V", "GND", "3V3"))}"' for a in attrs},
                        empty_parens=self.maybe(0.3))
            item.children = [self.sub_item("member", text=self.endpoint())
                             for _ in range(self.rng.randint(1, 4))]
            if self.maybe(0.2):
                item.trailer = [self.comment()]
            return item
        if kind == "table":
            columns = [self.rng.choice(("v", "part.package", "count", "part.mpn"))
                       for _ in range(self.rng.randint(0, 3))]
            item = Item("table", definition=self.rng.choice(("lib.R", "T")),
                        binding=self.rng.choice((None, "abstract", '"k"')),
                        columns=columns)
            item.children = [
                self.sub_item("row", name=self.name(),
                              cells=[self.value() for _ in columns])
                for _ in range(self.rng.randint(1, 4))]
            return item
        if kind == "isolated":
            return Item("isolated", text=self.endpoint())
        if kind == "chain":
            return Item("chain", head=self.name(),
                        rest=[self.endpoint() for _ in range(self.rng.randint(1, 3))])
        roll = self.rng.random()
        if roll < 0.4:
            bound = ("within", Quantity(self.rng, self.ladders, form="interval"))
        elif roll < 0.6:
            bound = ("within", Literal(self.rng.choice(("0.9 to 1.1", "0.50 to 0.6", "1 to 2"))))
        else:
            word = self.rng.choice(("at least", "at most"))
            bound = (word, self.rng.choice(
                (Quantity(self.rng, self.ladders, form="exact"), Literal("3"), Literal("0.25"))))
        return Item("assert", name=self.name(), tier=self.rng.choice(("static", "dynamic")),
                    measure=self.rng.choice(MEASURES), subject=self.name(), bound=bound)

    def module(self):
        runs = []
        for number in range(self.rng.randint(1, 3)):
            statements = [self.statement() for _ in range(self.rng.randint(1, 4))]
            for item in statements:
                if self.maybe(0.25):
                    item.trailing = self.comment()
            comments = []
            if self.maybe(0.4) or (number and self.maybe(0.3)):
                comments = [self.comment() for _ in range(self.rng.randint(1, 2))]
            if len(statements) == 1 and statements[0].kind in ("instance", "net") \
                    and self.maybe(0.5):
                statements[0].hoisted = [self.comment()
                                         for _ in range(self.rng.randint(1, 3))]
            runs.append((comments, statements))
        module = Item("module", name="M" + self.name(), runs=runs)
        if self.maybe(0.3):
            module.leading = [self.comment()]
        if self.maybe(0.2):
            module.trailing = self.comment()
        if self.maybe(0.2):
            module.trailer = [self.comment()]
        return module

    def design(self):
        header = [(self.comment(), self.maybe(0.3)) for _ in range(self.rng.randint(0, 2))]
        modules = [self.module() for _ in range(self.rng.randint(1, 3))]
        trailer = [self.comment() for _ in range(self.rng.randint(0, 2))]
        return header, self.maybe(0.5), modules, trailer


class Writer:
    """Spells a generated design as source, choosing every non-semantic
    detail at random from its own seed."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.lines = []

    def sp(self, lo=0, hi=2):
        return " " * self.rng.randint(lo, hi)

    def blank(self, lo, hi):
        self.lines.extend([""] * self.rng.randint(lo, hi))

    def own(self, column, text):
        self.lines.append(" " * column + text)

    def add(self, column, text, trailing):
        line = " " * column + text
        if trailing:
            line += self.sp(1, 4) + trailing
        self.lines.append(line)

    def permuted(self, items, fixed=()):
        """A random order, except that items whose kind is in `fixed` keep
        their relative order (F-1 sorts them by source index)."""
        order = list(items)
        self.rng.shuffle(order)
        pinned = iter([i for i in items if i.kind in fixed])
        return [next(pinned) if i.kind in fixed else i for i in order]

    def paren(self, column, prefix, entries, suffix, trailing, hoisted,
              empty_parens):
        """`prefix(entries)suffix`, single-line or wrapped. `hoisted`
        comments are spread, in order, over the wrapped lines."""
        if not entries and not hoisted:
            parens = "(" + self.sp() + ")" if empty_parens else ""
            self.add(column, prefix + parens + suffix, trailing)
            return
        if not hoisted and self.rng.random() < 0.7:
            joined = (self.sp() + "," + self.sp()).join(entries)
            self.add(column, f"{prefix}({self.sp()}{joined}{self.sp()}){suffix}",
                     trailing)
            return
        lines = [prefix + "("]
        for position, entry in enumerate(entries):
            comma = "," if position < len(entries) - 1 else ""
            lines.append(self.sp(0, 10) + entry + comma)
        if not entries or self.rng.random() < 0.4:
            lines.append(self.sp(0, 6) + ")" + suffix)
        else:
            lines[-1] += ")" + suffix
        # Gaps are every line but the last, whose comment is the trailer.
        # Non-decreasing slots, so the comments keep their order.
        slots = [[] for _ in lines[:-1]]
        picks = sorted(self.rng.randrange(len(slots)) for _ in hoisted)
        for slot, text in zip(picks, hoisted):
            slots[slot].append(text)
        out = []
        for line, slot in zip(lines, slots):
            if slot and self.rng.random() < 0.5:
                out.append(line + self.sp(1, 3) + slot[0])
                out.extend(self.sp(0, 12) + text for text in slot[1:])
            else:
                out.append(line)
                out.extend(self.sp(0, 12) + text for text in slot)
        out.append(lines[-1])
        self.lines.append(" " * column + out[0])
        self.lines.extend(out[1:-1])
        self.add(0, out[-1], trailing)

    def sorted_block(self, column, items, trailer):
        inner = column + self.rng.randint(1, 4)
        for item in self.permuted(items):
            self.blank(0, 1)
            for text in item.leading:
                self.own(self.rng.randint(0, inner), text)
            self.sub_item(inner, item)
        for text in trailer:
            self.own(inner, text)

    def sub_item(self, column, item):
        s = self.sp
        if item.kind == "pin":
            words = ["pin", item.name, item.role, *item.designators]
            self.add(column, s(1, 2).join(words), item.trailing)
        elif item.kind == "part":
            colon = s() + ":" if item.children else ""
            self.add(column, f"part{s(1, 2)}{item.binding}{colon}", item.trailing)
            if item.children:
                self.sorted_block(column, item.children, item.trailer)
        elif item.kind == "constraint":
            self.add(column, f"{item.name}{s()}={s()}{item.value.spell(self.rng)}",
                     item.trailing)
        elif item.kind == "hardware":
            self.add(column, f"hardware{s(1, 2)}{item.hw}", item.trailing)
        elif item.kind == "flag":
            self.add(column, item.text.replace(" ", s(1, 2)), item.trailing)
        elif item.kind == "member":
            self.add(column, item.text, item.trailing)
        elif item.kind == "row":
            cells = [item.name] + [c.spell(self.rng) for c in item.cells]
            self.add(column, s(1, 3).join(cells), item.trailing)
        else:  # pragma: no cover - generator and writer disagree
            raise AssertionError(item.kind)

    def statement(self, column, item):
        s, rng = self.sp, self.rng
        if item.kind == "port":
            self.add(column, f"port{s(1, 2)}{item.name}{s(1, 2)}{item.role}", item.trailing)
        elif item.kind == "instance":
            entries = [f"{n}{s()}={s()}{v.spell(rng)}" for n, v in item.args.items()]
            rng.shuffle(entries)
            self.paren(column, f"{item.name}{s()}={s()}new {item.definition}{s()}",
                       entries, s() + ":" if item.children else "", item.trailing,
                       item.hoisted, item.empty_parens)
            if item.children:
                self.sorted_block(column, item.children, item.trailer)
        elif item.kind == "net":
            entries = [f"{n}{s()}={s()}{v}" for n, v in item.attrs.items()]
            rng.shuffle(entries)
            self.paren(column, f"net {item.name}{s()}", entries, s() + ":",
                       item.trailing, item.hoisted, item.empty_parens)
            self.sorted_block(column, item.children, item.trailer)
        elif item.kind == "table":
            binding = f" part {item.binding}" if item.binding else ""
            prefix = f"table {item.definition}{binding}{s()}"
            if item.columns:
                self.paren(column, prefix, list(item.columns), s() + ":",
                           item.trailing, [], False)
            else:
                self.add(column, f"{prefix}({s()}){s()}:", item.trailing)
            self.sorted_block(column, item.children, [])
        elif item.kind == "isolated":
            self.add(column, f"isolated{s(1, 2)}{item.text}", item.trailing)
        elif item.kind == "chain":
            joined = (s() + "~" + s()).join([item.head] + item.rest)
            self.add(column, joined, item.trailing)
        elif item.kind == "assert":
            word, bound = item.bound
            self.add(column, f"assert {item.name} {item.tier} {item.measure}{s()}"
                     f"({s()}{item.subject}{s()}) {word.replace(' ', s(1, 2))} "
                     f"{bound.spell(rng)}", item.trailing)
        else:  # pragma: no cover - generator and writer disagree
            raise AssertionError(item.kind)

    def module(self, module):
        for text in module.leading:
            self.own(0, text)
        self.add(0, f"module {module.name}{self.sp()}:", module.trailing)
        column = self.rng.randint(1, 6)
        self.blank(0, 2)
        for number, (comments, statements) in enumerate(module.runs):
            if number:
                self.blank(0 if comments else 1, 2)
            for text in comments:
                self.own(self.rng.randint(0, column), text)
                self.blank(0, 1)
            for item in self.permuted(statements, fixed=("isolated", "chain")):
                self.statement(column, item)
        for text in module.trailer:
            self.own(self.rng.randint(1, column), text)

    def design(self, design):
        header, gap, modules, trailer = design
        self.blank(0, 2)
        for number, (text, before) in enumerate(header):
            if number and before:
                self.blank(1, 2)
            self.own(self.rng.randint(0, 2), text)
        if header and gap:
            self.blank(1, 2)
        self.lines.append(P.rstrip("\n"))
        for module in modules:
            self.blank(0, 3)
            self.module(module)
        if trailer:
            self.blank(0, 2)
        for text in trailer:
            self.own(0, text)
        self.blank(0, 2)
        text = "\n".join(self.lines)
        return text if self.rng.random() < 0.2 else text + "\n"


PROPERTY_DESIGNS = 260  # two spellings each: 520 generated sources


@unittest.skipUnless(HAVE_LARK, SKIP)
class PropertyTest(unittest.TestCase):
    """AC6: idempotent, and identical normalized ASTs give identical bytes."""

    def test_generated_designs(self):
        checked = 0
        for seed in range(PROPERTY_DESIGNS):
            design = DesignGenerator(seed).design()
            spellings = [Writer(seed * 7919 + k).design(design) for k in (1, 2)]
            outputs = []
            for source in spellings:
                with self.subTest(seed=seed, source=source):
                    result = _fmt(source)
                    self.assertTrue(result.ok, result.diagnostics.render())
                    self.assertEqual(_fmt(result.text).text, result.text)
                    self.assertEqual(_ast(result.text), _ast(source))
                    outputs.append(result.text)
                    checked += 1
            with self.subTest(seed=seed, spellings=spellings):
                self.assertEqual(len(set(outputs)), 1)
        self.assertGreaterEqual(checked, 500)

    def test_accept_cases_under_perturbation(self):
        # Re-indenting and re-spacing the conformance accept cases changes
        # nothing canonical.
        for path in sorted((_PARSE_CASES / "accept").glob("*.rhoform")):
            source = path.read_text(encoding="utf-8")
            expected = _fmt(source).text
            for seed in range(4):
                rng = random.Random(seed)
                width = rng.randint(1, 6)
                lines = []
                for line in source.split("\n"):
                    stripped = line.lstrip(" ")
                    depth = (len(line) - len(stripped)) // 4
                    lines.append(" " * (width * depth) + stripped)
                perturbed = "\n".join(lines).replace(" = ", rng.choice(("=", " =", "=  ")))
                with self.subTest(path.name, seed=seed):
                    self.assertEqual(_fmt(perturbed).text, expected)


@unittest.skipUnless(HAVE_LARK, SKIP)
class SelfCheckTest(unittest.TestCase):
    """F-11: output that fails the self-check is an internal error, never
    returned. Each case breaks one header renderer on purpose."""

    def _broken(self, renderer):
        from unittest import mock

        from rhoform import fmt

        with mock.patch.dict(fmt._HEADS, {"port_decl": renderer}):
            with self.assertRaises(fmt.FormatterError) as caught:
                fmt.format_source(P + "module M:\n    port p input\n")
        return str(caught.exception)

    def test_output_that_does_not_parse_is_caught(self):
        message = self._broken(lambda node: "port")
        self.assertIn("does not re-parse clean", message)

    def test_output_that_changes_meaning_is_caught(self):
        message = self._broken(lambda node: f"port {node.children[1]} passive")
        self.assertIn("normalized AST differs", message)

    def test_a_0_2_renderer_that_changes_meaning_is_caught(self):
        from unittest import mock

        from rhoform import fmt

        for production, renderer, source in (
            ("import_stmt", lambda node: 'import A from "x"',
             P2 + 'import B, A from "x"\nmodule M:\n    port p passive\n'),
            ("for_stmt", lambda node: "for i in range(n)",
             P2 + "module M(n: int = 2):\n    for i in range(1, n):\n"
             "        isolated p\n"),
        ):
            with self.subTest(production):
                with mock.patch.dict(fmt._HEADS, {production: renderer}):
                    with self.assertRaises(fmt.FormatterError) as caught:
                        fmt.format_source(source)
                self.assertIn("normalized AST differs", str(caught.exception))

    def test_output_that_drops_a_comment_is_caught(self):
        from unittest import mock

        from rhoform import fmt

        with mock.patch.object(fmt, "_with_trailing", lambda line, comment: line):
            with self.assertRaises(fmt.FormatterError):
                fmt.format_source(P + "module M:\n    port p input  # gone\n")
