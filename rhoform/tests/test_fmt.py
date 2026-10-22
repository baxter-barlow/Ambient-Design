"""The canonical formatter's contract (R16/I1, AC6; decision record F-1..F-12).

Three layers. Golden cases pin the canonical spelling of every construct and
every comment-attachment rule. The conformance corpus pins refusal (every
reject case) and acceptance (every accept case formats to a clean fixed
point). Seeded property tests generate designs and render each one twice
with independent non-semantic perturbations - indent widths, spacing around
`=` `~` `,`, wrapped argument lists, blank-line runs, comment columns,
equivalent quantity spellings, permutations of sortable lists - and require
both renderings to format to the same bytes, the output to be a fixed point,
and the normalized AST to survive formatting.

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


@unittest.skipUnless(HAVE_LARK, SKIP)
class ConformanceAcceptTest(unittest.TestCase):
    def test_every_accept_case_formats_to_a_clean_fixed_point(self):
        from rhoform.parser import parse

        paths = sorted((_PARSE_CASES / "accept").glob("*.rhoform"))
        self.assertGreaterEqual(len(paths), 8)
        for path in paths:
            with self.subTest(path.name):
                source = path.read_text(encoding="utf-8")
                result = _fmt(source)
                self.assertTrue(result.ok, result.diagnostics.render())
                self.assertTrue(parse(result.text).ok)
                self.assertEqual(_fmt(result.text).text, result.text)
                self.assertEqual(_ast(result.text), _ast(source))


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

    def test_output_that_drops_a_comment_is_caught(self):
        from unittest import mock

        from rhoform import fmt

        with mock.patch.object(fmt, "_with_trailing", lambda line, comment: line):
            with self.assertRaises(fmt.FormatterError):
                fmt.format_source(P + "module M:\n    port p input  # gone\n")
