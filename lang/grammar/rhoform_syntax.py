"""Rhoform syntax v0 — THE SOURCE OF TRUTH, and the generator for both artifacts.

L5 asks for "EBNF + Lark artifacts generated from one source of truth". This
module is that source: the rule table below is written once, as data, and the
two artifacts are rendered from it. Neither artifact is edited by hand, and a
test asserts that regenerating reproduces both byte for byte, so the pair
cannot drift apart or fall behind this file.

WHY DATA AND NOT TWO TEXT FILES. The obvious cheaper design — write the EBNF,
then write the Lark, then promise to keep them in step — is the thing L5's
wording rules out, and for a reason this repository has already been bitten by:
two artifacts nobody diffs will disagree eventually, and the disagreement will
surface as a parser that accepts something the spec forbids. Rendering both
from one tree makes that unrepresentable rather than merely discouraged.

WHAT WAS FROZEN. Candidate B won the §8-Q1 bake-off (AMB-32/AMB-33); this is
its surface, over the layout-tokenized INDENT/DEDENT stream L5 fixes. The
grammar is context-free over that stream: indentation is resolved by the
lexer, so no rule here is sensitive to column position.

WHAT IS DELIBERATELY NOT IN THE GRAMMAR. Four closed vocabularies — pin roles
(T2), hardware kinds (L9), measurement kinds (V2) and net attributes (T5) — are
NOT keywords. They are ordinary names checked against a list after parsing,
exactly as the prototype checks them, and the reason is load-bearing: `input`
and `output` are pin roles, and a grammar that made them keywords would reject
`input = new ...`, which is a legal design today. They are published below as
CLOSED_VOCABULARIES so a constrained decoder or a linter can still use them,
and a test pins that they are reachable as plain names.

This module deliberately imports nothing from `bakeoff`. The prototypes are
throwaway and the frozen grammar outlives them; a test anchors the two against
each other while the prototypes still exist, which is the right direction of
dependency.

    python3 -m grammar.rhoform_syntax --check    # artifacts match this source
    python3 -m grammar.rhoform_syntax --write    # regenerate them
"""

import argparse
import sys
from pathlib import Path

# The L8 syntax-version pragma, spelled as the §8-Q2 naming decision fixed it.
# `<major.minor>`, not a quoted semver string: the pragma gates syntax, and a
# patch component would imply a syntax difference that cannot exist.
PRAGMA_TEXT = "#pragma rhoform-syntax 0.1"
SYNTAX_VERSION = "0.1"

# Terminal patterns, as Python regex source. These MIRROR the layout tokenizer
# rather than importing it (see the module docstring); `test_grammar.py` asserts
# they still agree with `bakeoff.layout` while that prototype exists.
#
# A quantity is ONE token, never assembled from pieces: `100kohm +/- 1%`
# contains spaces and parentheses, and splitting it would put the shared
# literal syntax back into the grammar where T3/T4 have already settled it.
# The grammar does distinguish the interval form from the scalar forms, which
# is a different thing — see the two patterns below.
_NUM = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
_UNIT = r"[A-Za-z][A-Za-z0-9/]*"
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

# The tokenizer lexes ONE quantity terminal. The grammar splits it in two,
# because the two halves are not interchangeable where a bound is expected:
# `within` takes an interval and `at least` takes a scalar. Left as one
# terminal, `within 5V` and `at least 3.0V to 3.6V` both parse, and the
# prototype rejects both. A test holds the union of the two to be exactly the
# tokenizer's single pattern, so the split cannot quietly change what lexes.
_QUANTITY_SCALAR = (
    rf"{_NUM}{_UNIT}"
    rf"(?: \+/- {_NUM}(?:{_UNIT}|%)"
    rf"| \({_NUM}{_UNIT} to {_NUM}{_UNIT}\))?"
)
_QUANTITY_INTERVAL = rf"{_NUM}{_UNIT} to {_NUM}{_UNIT}"
# An exact quantity, no tolerance and no interval. `at least` and `at most`
# take only this: the prototype splits the literal with a regex that is
# NUM+UNIT and nothing else, so `at most 100kohm +/- 1%` is "not a bound".
_QUANTITY_PLAIN = rf"{_NUM}{_UNIT}"

# What the layout tokenizer matches at a digit, as one alternation. Held here
# only so a test can compare it against `bakeoff.layout`.
LEXER_QUANTITY = (
    rf"{_NUM}{_UNIT}"
    rf"(?: \+/- {_NUM}(?:{_UNIT}|%)"
    rf"| \({_NUM}{_UNIT} to {_NUM}{_UNIT}\)"
    rf"| to {_NUM}{_UNIT})?"
)


# Every word the frozen grammar spells as a literal — the keywords of the
# language, and nothing else. A test holds this to be a SUBSET of the
# prototype's shared `RESERVED` set: a word the grammar treats as a keyword
# while the parser still lets you name a net with it is a hole.
#
# The containment is deliberately one-way. `RESERVED` is shared by both
# bake-off candidates and so is a superset of either one's keywords: it
# reserves `signal`, which is candidate A's net declaration and has no meaning
# in the frozen grammar. Carrying A's vocabulary into B's freeze would reserve
# a useful identifier for a language that no longer exists, so v0 does not.
KEYWORDS = (
    "abstract",
    "assert",
    "at",
    "board_only",
    "dnp",
    "dynamic",
    "exclude_from_bom",
    "false",
    "hardware",
    "isolated",
    "least",
    "module",
    "most",
    "net",
    "new",
    "no",
    "part",
    "pin",
    "port",
    "static",
    "table",
    "to",
    "true",
    "within",
)

def _free_name_pattern() -> str:
    """An identifier that is not a keyword.

    L5 makes the surface keyword-based, and a keyword-based grammar has to say
    so somewhere. Without this the contextual lexer happily reads `module` as
    an ordinary NAME wherever a name is expected, so `module module:` and
    `net net:` parse — while the prototype rejects every one of them. The
    exclusion is generated from KEYWORDS, so it cannot fall behind.

    The trailing lookahead matters: without it `moduleX` would be rejected as
    if it began with the keyword `module`.
    """
    alternatives = "|".join(KEYWORDS)
    return rf"(?!(?:{alternatives})(?![A-Za-z0-9_])){_IDENT}"

TERMINALS: dict[str, str] = {
    "PRAGMA": r"\#pragma[^\n]*",
    # Two identifier terminals, because the prototype checks reserved words at
    # some name positions and not others. FREE_NAME is where a name is being
    # BOUND — module, port, net, table row, instance — and is the set the
    # parser's `expect_free_name` guards. NAME is every other position:
    # constraint and parameter names, column names, the components of a dotted
    # reference. `r1.net` is a legal endpoint today and freezing it away would
    # be a language change this issue did not measure.
    "FREE_NAME": _free_name_pattern(),
    "NAME": _IDENT,
    "QUANTITY": _QUANTITY_SCALAR,
    "QUANTITY_INTERVAL": _QUANTITY_INTERVAL,
    "QUANTITY_PLAIN": _QUANTITY_PLAIN,
    "NUMBER": _NUM,
    # Printable ASCII only, and the closing quote excluded. The tokenizer
    # scans every character of every line for tabs and non-ASCII, so `"µF"`
    # is a lexical error there; a grammar that allowed it would disagree
    # about a file, and L5's ASCII rule would hold between tokens and nowhere
    # else.
    "STRING": r'"[ !#-~]*"',
}

# Names the grammar checks by list AFTER parsing, never as keywords. See the
# module docstring for why this separation is not an oversight.
CLOSED_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "pin_role": (
        "power_in",
        "power_out",
        "passive",
        "bidirectional",
        "open_drain",
        "open_collector",
        "tri_state",
        "input",
        "output",
        "nc",
    ),
    "hardware_kind": (
        "mounting_hole",
        "fiducial",
        "artwork",
        "test_point",
        "grounded_mounting_hole",
    ),
    "net_attribute": ("ground_domain", "voltage_domain"),
    "measurement_kind": (
        "operating_point",
        "ripple",
        "frequency",
        "period",
        "duty_cycle",
        "gain",
        "bandwidth",
        "rise_time",
        "fall_time",
        "prop_delay",
        "settling_time",
        "overshoot",
        "power_avg",
        "power_rms",
        "efficiency",
    ),
}


# --------------------------------------------------------------------------
# The production combinators. Small on purpose: five shapes cover the whole
# grammar, and every shape both dialects can express directly.
# --------------------------------------------------------------------------


class Node:
    """A production fragment. Subclasses render themselves into a dialect.

    Bracketing is decided by PRECEDENCE, not by inspecting the rendered text.
    The first version of this file matched a regex against the output to guess
    whether parentheses were needed, and silently emitted
    `part_decl ::= 'part' 'abstract' | STRING ':' ...` — an alternation
    spanning the whole production instead of the two-way choice intended. Both
    artifacts were wrong in the same way, which is precisely the failure
    generating them from one source is supposed to prevent, and only running
    the result through a parser caught it.

    Levels: alternation binds loosest, then concatenation, then the postfix
    repetition operators, then atoms.
    """

    prec = 3

    def render(self, dialect: str) -> str:
        raise NotImplementedError

    def bracketed(self, dialect: str, minimum: int) -> str:
        """Rendered, parenthesised if this node binds looser than `minimum`."""
        text = self.render(dialect)
        return f"({text})" if self.prec < minimum else text


class Lit(Node):
    """A literal keyword or operator."""

    def __init__(self, text: str):
        self.text = text

    def render(self, dialect: str) -> str:
        return f'"{self.text}"' if dialect == "lark" else f"'{self.text}'"


class Term(Node):
    """A terminal produced by the layout tokenizer."""

    def __init__(self, name: str):
        self.name = name

    def render(self, dialect: str) -> str:
        # Lark drops a terminal from the tree when its name is underscored.
        # Layout terminals carry no information a consumer wants in the tree,
        # and keeping them makes every downstream visitor filter them out.
        if dialect == "lark" and self.name in _FILTERED:
            return f"_{self.name}"
        return self.name


class Ref(Node):
    """A reference to another rule."""

    def __init__(self, name: str):
        self.name = name

    def render(self, dialect: str) -> str:
        return self.name


class Seq(Node):
    prec = 1

    def __init__(self, *items: Node):
        self.items = items

    def render(self, dialect: str) -> str:
        return " ".join(item.bracketed(dialect, 1) for item in self.items)


class Alt(Node):
    prec = 0

    def __init__(self, *options: Node):
        self.options = options

    def render(self, dialect: str) -> str:
        return " | ".join(option.bracketed(dialect, 0) for option in self.options)


class Opt(Node):
    prec = 2

    def __init__(self, item: Node):
        self.item = item

    def render(self, dialect: str) -> str:
        return self.item.bracketed(dialect, 3) + "?"


class Rep(Node):
    """Repetition. `at_least=0` is `*`, `at_least=1` is `+`."""

    prec = 2

    def __init__(self, item: Node, at_least: int = 0):
        self.item = item
        self.at_least = at_least

    def render(self, dialect: str) -> str:
        return self.item.bracketed(dialect, 3) + ("+" if self.at_least else "*")


# Terminals Lark should keep out of the parse tree.
_FILTERED = frozenset({"NEWLINE", "INDENT", "DEDENT"})


def _vocab(kind: str) -> Node:
    """A closed vocabulary: a plain NAME, checked against a list afterwards.

    The kind is named at the call site so a reader can see WHICH list applies
    where, and validated here so a typo fails at import rather than silently
    documenting a vocabulary that does not exist.
    """
    if kind not in CLOSED_VOCABULARIES:
        raise KeyError(f"unknown closed vocabulary {kind!r}")
    return Term("NAME")


# --------------------------------------------------------------------------
# The grammar. Order is the order both artifacts present it in.
# --------------------------------------------------------------------------

NEWLINE, INDENT, DEDENT = Term("NEWLINE"), Term("INDENT"), Term("DEDENT")
NAME, NUMBER, STRING = Term("NAME"), Term("NUMBER"), Term("STRING")
QUANTITY, QUANTITY_INTERVAL = Term("QUANTITY"), Term("QUANTITY_INTERVAL")
QUANTITY_PLAIN = Term("QUANTITY_PLAIN")
# A name being bound, which may not be a keyword. See TERMINALS.
FREE_NAME = Term("FREE_NAME")


def _block(*body: Node) -> Seq:
    """`: NEWLINE INDENT <body> DEDENT` — the one block shape in the language."""
    return Seq(Lit(":"), NEWLINE, INDENT, *body, DEDENT)


RULES: tuple[tuple[str, str, Node], ...] = (
    (
        "start",
        "A file is the L8 pragma and then modules, nothing else at file scope.",
        Seq(Opt(NEWLINE), Term("PRAGMA"), NEWLINE, Rep(Ref("module_def"), 1)),
    ),
    (
        "module_def",
        "A module groups instances, nets and assertions.",
        Seq(Lit("module"), FREE_NAME, _block(Rep(Ref("statement"), 1))),
    ),
    (
        "statement",
        "Everything a module body can carry.",
        Alt(
            Ref("port_decl"),
            Ref("isolated_decl"),
            Ref("net_decl"),
            Ref("assertion"),
            Ref("table_decl"),
            Ref("chain"),
            Ref("instance_decl"),
        ),
    ),
    (
        "port_decl",
        "This module's own interface port. The role is a pin_role name.",
        Seq(Lit("port"), FREE_NAME, _vocab("pin_role"), NEWLINE),
    ),
    (
        "isolated_decl",
        "L9b's intentional single-pin net, declared rather than inferred.",
        Seq(Lit("isolated"), Ref("endpoint"), NEWLINE),
    ),
    (
        "net_decl",
        "A named net and its members, one per line.",
        Seq(
            Lit("net"),
            FREE_NAME,
            Opt(Ref("net_attributes")),
            _block(Rep(Seq(Ref("endpoint"), NEWLINE), 1)),
        ),
    ),
    (
        "net_attributes",
        "Typed net attributes (T5 voltage/ground domains).",
        Seq(
            Lit("("),
            Opt(Seq(Ref("net_attribute"), Rep(Seq(Lit(","), Ref("net_attribute"))))),
            Lit(")"),
        ),
    ),
    (
        "net_attribute",
        "A domain label. The attribute is a net_attribute name and the value "
        "is a string, never a bare name.",
        Seq(_vocab("net_attribute"), Lit("="), STRING),
    ),
    (
        "chain",
        "An unnamed net written as a chain of endpoints.",
        Seq(Ref("chain_head"), Rep(Seq(Lit("~"), Ref("endpoint")), 1), NEWLINE),
    ),
    (
        "chain_head",
        "The endpoint that opens a chain. Its first component is a FREE_NAME "
        "and every other endpoint's is a NAME, which looks arbitrary and is "
        "not: the parser reserved-checks the token that starts a statement "
        "and does not check the ones after `~`, so `net.a ~ x` is rejected "
        "while `x ~ net.a` is accepted. Writing that asymmetry down is also "
        "what keeps the statement head unambiguous for a one-token lexer.",
        Seq(FREE_NAME, Opt(Seq(Lit("."), NAME))),
    ),
    (
        "instance_decl",
        "Instantiation. Facts about the instance live in its optional body.",
        Seq(
            FREE_NAME,
            Lit("="),
            Lit("new"),
            Ref("qualified_name"),
            Opt(Ref("arguments")),
            Alt(Ref("instance_body"), NEWLINE),
        ),
    ),
    (
        "instance_body",
        "The block that carries everything about an instance but its values.",
        _block(Rep(Ref("instance_stmt"), 1)),
    ),
    (
        "instance_stmt",
        "One fact about the enclosing instance.",
        Alt(
            Ref("pin_decl"),
            Ref("part_decl"),
            Ref("hardware_decl"),
            Ref("negated_flag"),
            Ref("flag"),
        ),
    ),
    (
        "pin_decl",
        "A component pin, optionally carrying footprint designators.",
        Seq(
            Lit("pin"),
            NAME,
            _vocab("pin_role"),
            Rep(Ref("designator")),
            NEWLINE,
        ),
    ),
    (
        "designator",
        "A footprint pin designator: `7`, or `A1` on a connector.",
        Alt(NUMBER, NAME),
    ),
    (
        "part_decl",
        "D1's binding ladder: an abstract constrained part, or a pinned pick.",
        Seq(
            Lit("part"),
            Alt(Lit("abstract"), STRING),
            Alt(_block(Rep(Ref("constraint"), 1)), NEWLINE),
        ),
    ),
    (
        "constraint",
        "One resolution constraint.",
        Seq(NAME, Lit("="), Ref("value"), NEWLINE),
    ),
    (
        "hardware_decl",
        "L9 hardware classification. The kind is a hardware_kind name.",
        Seq(Lit("hardware"), _vocab("hardware_kind"), NEWLINE),
    ),
    (
        "negated_flag",
        "An explicit false. The bare flag only means true, so denying a "
        "library default needs its own spelling.",
        Seq(Lit("no"), Alt(Lit("exclude_from_bom"), Lit("board_only")), NEWLINE),
    ),
    (
        "flag",
        "A fabrication flag set to true (L9c).",
        Seq(
            Alt(Lit("dnp"), Lit("exclude_from_bom"), Lit("board_only")),
            NEWLINE,
        ),
    ),
    (
        "table_decl",
        "L6's columnar sub-syntax for uniform tabular instances.",
        Seq(
            Lit("table"),
            Ref("qualified_name"),
            Opt(Ref("table_binding")),
            Lit("("),
            Opt(Ref("column_list")),
            Lit(")"),
            _block(Rep(Ref("table_row"), 1)),
        ),
    ),
    (
        "table_binding",
        "The part binding shared by every row.",
        Seq(Lit("part"), Alt(Lit("abstract"), STRING)),
    ),
    (
        "column_list",
        "Column names. `part.<name>` addresses a constraint.",
        Seq(Ref("column"), Rep(Seq(Lit(","), Ref("column")))),
    ),
    ("column", "A parameter name, or `part.` and a constraint name.",
     Seq(NAME, Opt(Seq(Lit("."), NAME)))),
    (
        "table_row",
        "An instance name and its values. HOW MANY is not a syntactic fact: "
        "a row carries one value per column of its header, and no "
        "context-free rule can count a preceding declaration. The grammar "
        "therefore accepts any number, including none — a table declaring no "
        "columns has rows that are a bare name — and the arity check belongs "
        "to the checker, which reports the mismatch against the header.",
        Seq(FREE_NAME, Rep(Ref("value")), NEWLINE),
    ),
    (
        "assertion",
        "A V1 assertion. The tier is written because V1 makes it visible in "
        "every diagnostic.",
        Seq(
            Lit("assert"),
            NAME,
            Alt(Lit("static"), Lit("dynamic")),
            _vocab("measurement_kind"),
            Lit("("),
            NAME,
            Lit(")"),
            Ref("bound"),
            NEWLINE,
        ),
    ),
    (
        "bound",
        "`within` takes an interval; a dimensionless one is two NUMBERs, "
        "since the lexer only forms a QUANTITY around a unit.",
        Alt(
            Seq(
                Lit("within"),
                Alt(QUANTITY_INTERVAL, Seq(NUMBER, Lit("to"), NUMBER)),
            ),
            Seq(
                Lit("at"),
                Alt(Lit("least"), Lit("most")),
                Alt(QUANTITY_PLAIN, NUMBER),
            ),
        ),
    ),
    (
        "arguments",
        "Elaboration parameters, as keyword arguments.",
        Seq(
            Lit("("),
            Opt(Seq(Ref("argument"), Rep(Seq(Lit(","), Ref("argument"))))),
            Lit(")"),
        ),
    ),
    ("argument", "One named parameter.", Seq(NAME, Lit("="), Ref("value"))),
    (
        "value",
        "T3/T4 literals. A bare decimal is not a value: it is either a "
        "quantity missing its unit or a count that should be whole.",
        Alt(QUANTITY, QUANTITY_INTERVAL, STRING, NUMBER, Lit("true"), Lit("false")),
    ),
    (
        "endpoint",
        "A connectable point: this module's port, or an instance pin.",
        Seq(NAME, Opt(Seq(Lit("."), NAME))),
    ),
    (
        "qualified_name",
        "A dotted definition path, e.g. `rhoform.lib.passive.Resistor`.",
        Seq(NAME, Rep(Seq(Lit("."), NAME))),
    ),
)


# --------------------------------------------------------------------------
# Emitters
# --------------------------------------------------------------------------

_HEADER = f"""\
Rhoform syntax v{SYNTAX_VERSION} — {{title}}

GENERATED FROM lang/grammar/rhoform_syntax.py. Do not edit it: regenerate
with `python3 -m grammar.rhoform_syntax --write`. `make grammar` only CHECKS
that this file matches its source, and fails if it does not.

The grammar is context-free over the layout-tokenized stream L5 fixes, so
INDENT, DEDENT and NEWLINE arrive as terminals and no rule below is sensitive
to column position. Every file opens with the L8 pragma `{PRAGMA_TEXT}`.

Pin roles, hardware kinds, measurement kinds and net attributes are NOT
keywords here: they are plain names checked against a closed list after
parsing, because `input` and `output` are pin roles and a design may
legitimately name an instance `input`. The four lists are published in the
source module as CLOSED_VOCABULARIES.
"""


def _comment(text: str, marker: str) -> str:
    return "\n".join(f"{marker} {line}".rstrip() for line in text.split("\n"))


def _regex_literal(pattern: str) -> str:
    """A `/.../` regex literal with the delimiter escaped inside.

    Both dialects write terminals as slash-delimited regexes, and the unit
    pattern contains a slash — `[A-Za-z0-9/]` for units like `V/us`, and the
    ASCII tolerance operator `+/-`. Unescaped, the literal ends at the first
    one and the rest of the pattern is read as grammar. `\\/` is an ordinary
    slash to every regex engine, so this changes the delimiter only.
    """
    return "/" + pattern.replace("/", r"\/") + "/"


# The lexical layer, stated once and rendered into both artifacts.
#
# Each entry is (name, definition, doc). A DEFINITION IS A TUPLE OF PARTS, not
# a regex string, and that is the whole point: `NEWLINE` has to say "a line
# break OR a comment", where `COMMENT` is a REFERENCE to the terminal above it
# and not the eight literal characters C-O-M-M-E-N-T. Written as one regex
# string, the EBNF rendered `/(?:\n[ ]*|COMMENT)+/`, which as a regex matches
# the word "COMMENT" and does not match a comment — a false statement in the
# artifact L5 names as a deliverable, while the Lark half quietly emitted a
# different, correct spelling from a hardcoded branch in its emitter. Parts
# make the two renderings the same text by construction.
#
# `Pat` is a regex fragment; `Ref` is a reference to another lexical name.
class Pat(str):
    """A regex fragment inside a lexical definition."""


class LexRef(str):
    """A reference to another lexical rule, rendered as its bare name."""


def _render_parts(parts: tuple) -> str:
    """One alternation, rendered identically for both dialects."""
    rendered = []
    for part in parts:
        rendered.append(
            _regex_literal(part) if isinstance(part, Pat) else str(part)
        )
    if len(rendered) == 1:
        return rendered[0]
    return "( " + " | ".join(rendered) + " )+"


LEXICAL = (
    (
        "COMMENT",
        (Pat(r"\#(?!pragma(?![A-Za-z0-9_]))[ -~]*"),),
        "A comment runs to end of line. A `#pragma` word is excluded so the "
        "L8 header is never swallowed as one — but `#pragmatic` is an "
        "ordinary comment, which is why the exclusion ends at a word "
        "boundary. ASCII only, like every other lexeme.",
    ),
    (
        "NEWLINE",
        (Pat(r"\n[ ]*"), LexRef("COMMENT")),
        "A run of line breaks AND comment lines is ONE newline token. "
        "Without the comment alternative a comment-only line leaves two "
        "adjacent newlines, which no production accepts — so no file with a "
        "standalone comment would parse.",
    ),
    (
        "WHITESPACE",
        (Pat(r"[ ]+"),),
        "Ignored between tokens. Spaces only: a tab is a lexical error, "
        "because L5 says ASCII with indentation blocks and two files that "
        "differ by a tab must not be the same program.",
    ),
    (
        "INDENT",
        None,
        "Manufactured by the layout pass from the leading spaces of each "
        "line, suspended inside brackets so a parameter list may wrap.",
    ),
    (
        "DEDENT",
        None,
        "The closing half of INDENT, one per level left.",
    ),
    (
        "FINAL_NEWLINE",
        None,
        "The layout pass owes the grammar a newline token at the end of the "
        "last line whether or not the file's final byte is one, so that every "
        "statement really is newline-terminated. See `conformance.normalize`.",
    ),
)


def emit_ebnf() -> str:
    """W3C-style EBNF: the human-readable half of L5's pair."""
    out = ["(*\n" + _HEADER.format(title="EBNF") + "*)", ""]
    out.append("(* Terminals. *)")
    for name, pattern in TERMINALS.items():
        out.append(f"{name} ::= {_regex_literal(pattern)}")
    out.append("")
    out.append("(* The lexical layer. *)")
    for name, parts, doc in LEXICAL:
        out.append(f"(* {doc} *)")
        if parts is None:
            out.append(f"{name} ::= (* supplied by the layout pass *)")
        else:
            out.append(f"{name} ::= {_render_parts(parts)}")
        out.append("")
    out.append("(* Productions. *)")
    for name, doc, node in RULES:
        out.append(f"(* {doc} *)")
        out.append(f"{name} ::= {node.render('ebnf')}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def emit_lark() -> str:
    """Lark grammar: the machine-readable half, and AMB-43's input.

    Targets `parser="lalr"` with Lark's contextual lexer and an `Indenter`
    postlex. The contextual lexer is what lets a closed-vocabulary word like
    `input` stay usable as an ordinary name: terminals are only considered in
    parser states that accept them.
    """
    out = [_comment(_HEADER.format(title="Lark"), "//"), ""]
    for name, doc, node in RULES:
        out.append(f"// {doc}")
        out.append(f"{name}: {node.render('lark')}")
        out.append("")

    out.append("// Terminals. QUANTITY_INTERVAL outranks QUANTITY so that the")
    out.append("// `A to B` form lexes as the interval wherever both are legal.")
    out.append(f'PRAGMA.2: {_regex_literal(TERMINALS["PRAGMA"])}')
    out.append(f'QUANTITY_INTERVAL.2: {_regex_literal(TERMINALS["QUANTITY_INTERVAL"])}')
    out.append(f'QUANTITY.1: {_regex_literal(TERMINALS["QUANTITY"])}')
    out.append(f'QUANTITY_PLAIN: {_regex_literal(TERMINALS["QUANTITY_PLAIN"])}')
    out.append(f'FREE_NAME: {_regex_literal(TERMINALS["FREE_NAME"])}')
    out.append(f'NAME: {_regex_literal(TERMINALS["NAME"])}')
    out.append(f'NUMBER: {_regex_literal(TERMINALS["NUMBER"])}')
    out.append(f'STRING: {_regex_literal(TERMINALS["STRING"])}')
    out.append("")
    for name, parts, doc in LEXICAL:
        out.append(f"// {doc}")
        if name == "COMMENT":
            # Both ignored (a trailing comment disappears) and part of
            # _NEWLINE (a comment-only line is absorbed into the line break
            # rather than leaving a second one behind) — Lark's own Python
            # grammar uses exactly this shape.
            out.append(f"COMMENT: {_render_parts(parts)}")
        elif name == "NEWLINE":
            out.append(f"_NEWLINE: {_render_parts(parts)}")
        elif name == "WHITESPACE":
            out.append(f"%ignore {_render_parts(parts)}")
            out.append("%ignore COMMENT")
        elif name == "INDENT":
            out.append("%declare _INDENT _DEDENT")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


ARTIFACTS = {
    "rhoform.ebnf": emit_ebnf,
    "rhoform.lark": emit_lark,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="regenerate artifacts")
    group.add_argument(
        "--check",
        action="store_true",
        help="fail if an artifact differs from this source",
    )
    parser.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)

    problems = []
    for filename, emit in ARTIFACTS.items():
        target = args.dir / filename
        rendered = emit()
        if args.write:
            target.write_text(rendered, encoding="utf-8")
            print(f"grammar: wrote {target}")
            continue
        if not target.exists():
            problems.append(f"{filename}: missing; run `--write`")
        elif target.read_text(encoding="utf-8") != rendered:
            problems.append(f"{filename}: differs from rhoform_syntax.py")

    if problems:
        for problem in problems:
            print(f"grammar: FAIL: {problem}", file=sys.stderr)
        return 1
    if args.check:
        print(f"grammar: OK: {len(ARTIFACTS)} artifact(s) match the source of truth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
