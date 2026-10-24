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

WHAT IS DELIBERATELY NOT IN THE GRAMMAR. Seven closed vocabularies — pin roles
(T2), hardware kinds (L9), measurement kinds (V2), net attributes (T5), since
syntax 0.2 parameter types and the loop iterator, and since 0.3 ground kinds —
are NOT keywords. They are ordinary names checked against a list after parsing,
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
import re
import sys
from pathlib import Path

# The L8 syntax-version pragma, spelled as the §8-Q2 naming decision fixed it.
# `<major.minor>`, not a quoted semver string: the pragma gates syntax, and a
# patch component would imply a syntax difference that cannot exist.
#
# A SET OF VERSIONS, ONE GRAMMAR (decision S-1/S-2). Each version adds to
# the one before: 0.2 imports, component definitions, parameters, `if`, `for`
# and arrays, and 0.3 the design annotations (`supply`, `draw`, `waive`),
# component rules, rule overrides, a quoted designator and an assertion's
# `warning`. A file declaring an older version keeps its tree under the one
# grammar; what a newer version takes away is only in files that declare it
# (0.3 reserves a few names, RESERVED_SINCE, and refuses designators run
# together). One grammar therefore parses all of them, and the PRAGMA
# terminal accepts exactly the versions listed here.
# What an older version forbids is enforced AFTER parsing, by the production
# parser, as one diagnostic per file with a fix-it that rewrites the pragma
# (CONSTRUCT_SINCE says what needs which version) — a second grammar per
# version would be two artifacts nobody diffs, which is the failure this
# module exists to prevent.
#
# SYNTAX_VERSION is the CURRENT version: what a new file is written with and
# what a missing pragma's fix-it inserts. PRAGMA_TEXT is its header line.
#
# UNFROZEN VERSIONS (decision OD8, 2026-10-24). 0.3 is the working version
# M2's checkers grow in: its constructs may still change shape in place,
# with no E1 migrator, until M2 exit freezes it. That is honest only while
# nothing ships, so no tagged release may ship while any version here is
# unfrozen (spec 01 records the deviation from L8). An unfrozen version
# parses like any other, but it is never the current version, and the
# package layer does not announce it (rhoform.package.language_versions).
PRAGMA_PREFIX = "#pragma rhoform-syntax "
SYNTAX_VERSIONS = ("0.1", "0.2", "0.3")
UNFROZEN_SYNTAX_VERSIONS = ("0.3",)
FROZEN_SYNTAX_VERSIONS = tuple(version for version in SYNTAX_VERSIONS
                               if version not in UNFROZEN_SYNTAX_VERSIONS)
SYNTAX_VERSION = "0.2"
PRAGMA_TEXTS = tuple(PRAGMA_PREFIX + version for version in SYNTAX_VERSIONS)
PRAGMA_TEXT = PRAGMA_PREFIX + SYNTAX_VERSION

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
# The same numeral with the fractional part removed. `value` takes this and
# `bound` takes _NUM; see the TERMINALS comment on INTEGER for why.
_INT = r"-?(?:0|[1-9][0-9]*)"
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


# Every word the grammar spells as a literal — the keywords of the language,
# and nothing else. A test holds the 0.1 ones to be a SUBSET of the
# prototype's shared `RESERVED` set: a word the grammar treats as a keyword
# while the parser still lets you name a net with it is a hole.
#
# The containment is deliberately one-way. `RESERVED` is shared by both
# bake-off candidates and so is a superset of either one's keywords: it
# reserves `signal`, which is candidate A's net declaration and has no meaning
# in the frozen grammar. Carrying A's vocabulary into B's freeze would reserve
# a useful identifier for a language that no longer exists, so v0 does not.
#
# The seven 0.2 words at the end were RESERVED_FUTURE until 0.2 gave them
# productions. The prototype never reserved them (see RESERVED_FUTURE's
# history below), so they are the one stated exception to the subset rule.
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
    # Syntax 0.2 (decision S-5), promoted from RESERVED_FUTURE.
    "component",
    "else",
    "for",
    "from",
    "if",
    "import",
    "in",
)

# The keywords syntax 0.2 promoted out of RESERVED_FUTURE. Published so the
# anchor against the prototype can state the relationship that now holds
# exactly — every keyword is a prototype reserved word OR one of these —
# rather than weakening it to nothing.
PROMOTED_IN_0_2 = ("component", "else", "for", "from", "if", "import", "in")

# Words the grammar does not use and v1 will. Reserved now, because reserving a
# word later is a BREAKING syntax change and E1 forbids those without a
# deterministic auto-migrator that does not exist.
#
# The distinction from KEYWORDS is the point: these are not literals in any
# rule below, and `test_every_literal_in_the_tree_is_a_declared_keyword` still
# holds KEYWORDS to be exactly the words the grammar spells. They are excluded
# from FREE_NAME and nothing else, so today they are simply unusable as bound
# names — which costs nothing while the only v0.1 sources are this repo's own
# examples, and costs a migrator once anyone else has written a design.
#
# WHY THESE, and not a guess at the language's future. v0.1 reserved eight
# words, each required by an approved M·core requirement a later milestone
# implements:
#
#   interface, component  L2 core nouns, alongside `module`, which IS a
#                         keyword here. AMB-44 adds them.
#   if, else, for, in     L3 `if` over parameters and bounded `for`
#                         comprehensions. AMB-44.
#   import, from          L4/X2 imports, spelled `import X from "path"` in the
#                         package-identity spec's own worked example. AMB-45.
#
# Syntax 0.2 gave seven of them productions and moved them to KEYWORDS, which
# is additive precisely because they were reserved: no 0.1 file could bind
# one, and every NAME position still accepts them. `interface` stays here,
# because T1 interface semantics are R19 (M2) and a production with no
# meaning behind it would be syntax nobody can use correctly.
#
# This is a DELIBERATE divergence from the prototype, which accepts all eight
# as names — unlike the two fixes either side of it, which close gaps where
# the grammar was looser than the prototype. Recorded here because an anchor
# test that reads "the grammar and the prototype disagree" should say why.
#
# `signal` is deliberately NOT here. It is candidate A's dead net keyword, not
# a word v1 needs; see KEYWORDS above and
# `test_the_freeze_drops_signal_and_nothing_else`.
RESERVED_FUTURE = ("interface",)

# SOFT KEYWORDS (syntax 0.3). A word 0.1 and 0.2 never reserved cannot become
# a keyword without breaking a file that binds it (E1), so each 0.3 statement
# opens with a NAMED terminal that matches only its word and is viable only
# where that statement may start. FREE_NAME does not exclude these words:
# `supply = new ...` still parses, the head positions of `instance_decl` and
# `chain_head` accept the soft terminals beside FREE_NAME, and the production
# parser retypes such a head to FREE_NAME, so a 0.2 file that names something
# `supply` keeps its 0.2 tree. It also lexes a file older than 0.3 with them
# demoted to FREE_NAME first, so a broken line one heads keeps its 0.2
# diagnostic (rhoform/parser.py, _parse_as).
#
# WHY TERMINALS AND NOT NAMES. The other closed vocabularies are plain names
# checked after parsing, which is right where the position is a name anyway.
# A statement head is not: spelled as a name, `prt p passive` (a typo of
# `port`, conformance case r13) would parse as a three-word 0.3 statement and
# lose the 0.1 diagnostic it has always had, and every expected set at a
# statement's start would name "a name" for 0.3's sake. A terminal that only
# the exact word lexes as leaves every other line's parse, error and
# expected set what they were.
#
# The first four open module statements and compete with FREE_NAME at a
# statement's start, so they outrank it (LARK_TERMINAL_PRIORITY). `side` opens
# a component-body statement and `warning` ends an assertion, positions where
# no name is viable, so they need no rank.
SOFT_KEYWORDS = {
    "SUPPLY": "supply",
    "DRAW": "draw",
    "WAIVE": "waive",
    "RULE": "rule",
    "SIDE": "side",
    "WARNING": "warning",
}

# The words a component rule opens with (0.3): the electrical structure of a
# component KIND, whose numbers come from part data and parameters and whose
# meaning is spec 05's (the check stage's). One terminal, RULE_WORD, viable
# only where a component-body statement starts, for the reason the soft
# keywords above are terminals: a component body held only `pin` lines
# through 0.2, and a name-shaped rule head would turn every misspelled `pin`
# into a rule. The trade is that a misspelled rule word is an unexpected-token
# error naming "a rule word", not a did-you-mean.
RULE_WORDS = (
    "bias",
    "bridge",
    "conduct",
    "connector",
    "diode",
    "feedback",
    "ground",
    "hiz",
    "open",
    "pass",
    "rail",
    "ref",
    "regulate",
    "source",
    "switch",
    "tie",
)

# The version that introduced each word the grammar spells, keyword or soft
# keyword, after 0.1, and each other token. The production parser drops an
# expected token newer than the file's pragma from RHO1006 and RHO1007
# (AMB-146 #2), so a 0.1 file is never told to write `import` and a 0.2 file
# never `supply`. Punctuation is keyed by its spelling, a named terminal by
# its name.
KEYWORDS_SINCE = {
    **{word: "0.2" for word in PROMOTED_IN_0_2},
    **{word: "0.3" for word in SOFT_KEYWORDS.values()},
}
TERMINALS_SINCE = {
    "[": "0.2",
    "]": "0.2",
    "COMPARE": "0.2",
    "INDEX_OP": "0.2",
    "DIAGNOSTIC_CODE": "0.3",
    "QUOTED_DESIGNATOR": "0.3",
    "RULE_WORD": "0.3",
}

# Words no name may be from a version on, though older files may bind them:
# the module-statement soft keywords, and E4's assembly-variant word, which
# 0.3 reserves before any construct uses it so that adding one later breaks
# nothing. Reserving per version is what keeps it additive: a 0.2 file binds
# `variant` freely. Checked after parsing (RHO1019), because the grammar is one
# grammar for every version.
RESERVED_SINCE = {
    "draw": "0.3",
    "rule": "0.3",
    "supply": "0.3",
    "variant": "0.3",
    "waive": "0.3",
}


def _free_name_pattern() -> str:
    """An identifier that is neither a keyword nor a reserved future keyword.

    L5 makes the surface keyword-based, and a keyword-based grammar has to say
    so somewhere. Without this the contextual lexer happily reads `module` as
    an ordinary NAME wherever a name is expected, so `module module:` and
    `net net:` parse — while the prototype rejects every one of them. The
    exclusion is generated from both tuples, so it cannot fall behind either.

    The trailing lookahead matters: without it `moduleX` would be rejected as
    if it began with the keyword `module`.
    """
    alternatives = "|".join(sorted(KEYWORDS + RESERVED_FUTURE))
    return rf"(?!(?:{alternatives})(?![A-Za-z0-9_])){_IDENT}"


def _pragma_pattern() -> str:
    """The pragma lines this artifact defines: PRAGMA_PREFIX and exactly one
    of SYNTAX_VERSIONS, each escaped. No other version, and no prefix of
    one, can lex as the header."""
    versions = "|".join(re.escape(version) for version in SYNTAX_VERSIONS)
    return f"{re.escape(PRAGMA_PREFIX)}(?:{versions})"


TERMINALS: dict[str, str] = {
    # EXACTLY the pragmas this artifact defines, generated from PRAGMA_PREFIX
    # and SYNTAX_VERSIONS (one per version, since 0.2).
    #
    # It used to be `\#pragma[ -~]*` — any printable text after the word — which
    # made L8's version header decorative: `#pragma rhoform-syntax 9.9` and
    # `#pragma verilog 1.0` both parsed, while the prototype rejects both with
    # "unsupported syntax-version pragma" (base.py). A version header nothing
    # validates cannot do its one job, which is to refuse a file written for a
    # syntax version this artifact does not define.
    #
    # Generating it from the version tuple is what makes SYNTAX_VERSIONS
    # load-bearing: the version was previously read only to interpolate a
    # comment, so the constant could have said anything without a test
    # noticing.
    #
    # This does NOT change the two recorded pragma/comment asymmetries: the
    # exclusion on COMMENT still ends at a word boundary, so `#pragmatic` is
    # still a comment and a mid-line `#pragma x` is still rejected. See
    # `test_the_pragma_and_comment_boundary_is_a_decision`. It removes a THIRD
    # asymmetry that was never recorded, in the direction of the prototype.
    #
    # The ASCII rule this line used to be the last exception to is now
    # enforced trivially: the only accepted pragma is ASCII by construction.
    "PRAGMA": _pragma_pattern(),
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
    # Two numeric terminals, for the same reason QUANTITY is split three ways:
    # the positions are not interchangeable, and one terminal serving both let
    # the grammar accept what the prototype rejects.
    #
    # NUMBER is a bound's operand and MUST admit decimals — `within 0.5 to 0.6`
    # is a legal duty-cycle assertion, pinned by test_grammar.py.
    #
    # INTEGER is a `value`'s operand and must NOT. The `value` rule's own
    # docstring, rendered verbatim into both artifacts, has always said "a bare
    # decimal is not a value: it is either a quantity missing its unit or a
    # count that should be whole" — and the grammar did not implement it, so
    # `resistance = 1.5` parsed here and failed in the prototype with RHOB0003.
    # A whole count IS a value (`count = 8`), which is why this is a narrowing
    # of NUMBER rather than dropping the alternative.
    "NUMBER": _NUM,
    "INTEGER": _INT,
    # Printable ASCII only, and the closing quote excluded. The tokenizer
    # scans every character of every line for tabs and non-ASCII, so `"µF"`
    # is a lexical error there; a grammar that allowed it would disagree
    # about a file, and L5's ASCII rule would hold between tokens and nowhere
    # else.
    "STRING": r'"[ !#-~]*"',
    # Syntax 0.2. Two OPERATOR terminals, named rather than written as
    # quoted literals, because Lark drops anonymous string tokens from the
    # tree: `if n == 3` and `if n != 3` would parse to the same tree, and so
    # would `c[i + 1]` and `c[i - 1]`. A named terminal keeps the operator
    # in the tree for the elaborator to read.
    #
    # COMPARE is an `if` condition's operator. Two-character spellings come
    # first so `<=` is never read as `<` followed by junk.
    "COMPARE": r"==|!=|<=|>=|<|>",
    # INDEX_OP is the offset operator inside an index, `[i + 1]`. It is only
    # viable inside `[...]` after the index base, so the contextual lexer
    # never confuses it with a signed INTEGER there.
    #
    # It must never claim the `+` of the `+/-` tolerance operator, hence the
    # lookahead. Lark's contextual lexer, on a character the current state
    # cannot lex, re-lexes with EVERY terminal to choose its error: a bare
    # `[+-]` turned each malformed tolerance (`100kohm  +/- 5%`, `2V +/-`)
    # from an unlexable character, which the parser diagnoses as one
    # RHO1010/RHO1012 naming the literal, into an "unexpected `+`" token
    # error that skips that recovery entirely.
    "INDEX_OP": r"[+-](?!/)",
    # Syntax 0.3. The soft keywords, each its word with the keyword boundary
    # every keyword carries, then the rule words as one terminal, longest
    # alternative first.
    **{name: rf"{word}(?![A-Za-z0-9_])" for name, word in SOFT_KEYWORDS.items()},
    "RULE_WORD": "(?:" + "|".join(sorted(RULE_WORDS, key=lambda w: (-len(w), w)))
                 + ")(?![A-Za-z0-9_])",
    # The code a waiver names: `RHO` and four digits, a terminal so that a
    # malformed code is a syntax error at its own token. Viable only after
    # `waive`, so a net or instance spelled like a code is still a name.
    "DIAGNOSTIC_CODE": r"RHO[0-9]{4}(?![A-Za-z0-9_])",
    # A designator in quotes (AMB-146 #1): `"01"` and `"1A"` are one
    # designator each, where `01` is the two designators `0` and `1`. Printable
    # ASCII with no space and no quote, and never empty, so it is a narrowing
    # of STRING that only a designator position lexes.
    "QUOTED_DESIGNATOR": r'"[!#-~]+"',
}

# Lark lexer priorities. A terminal absent from this map is emitted unranked.
#
# This used to be spelled by hand-writing eight `NAME.priority: pattern` lines
# in `emit_lark`, which meant the Lark artifact carried its own terminal LIST:
# adding INTEGER to TERMINALS put it in the EBNF and not in the Lark, and the
# only symptom was `GrammarError: Rule 'INTEGER' used but not defined`. The set
# now comes from TERMINALS for both artifacts and only the ranking lives here,
# so the two cannot disagree about which terminals exist.
#
#   PRAGMA             outranks COMMENT, which is also `#`-initial.
#   QUANTITY_INTERVAL  outranks QUANTITY so `A to B` lexes as the interval
#                      wherever both are legal.
#   INTEGER            outranks NUMBER so that a value position, where only
#                      INTEGER is grammatical, cannot lex `8` as a NUMBER and
#                      then fail to reduce. NUMBER still wins on `1.5` because
#                      it matches longer, which is exactly the rejection the
#                      `value` rule wants.
#   SUPPLY DRAW WAIVE  outrank FREE_NAME, which also matches their word at a
#   RULE               statement's start; the head positions that bind a name
#                      take them too (see SOFT_KEYWORDS).
LARK_TERMINAL_PRIORITY = {
    "PRAGMA": 2,
    "QUANTITY_INTERVAL": 2,
    "QUANTITY": 1,
    "INTEGER": 1,
    "SUPPLY": 1,
    "DRAW": 1,
    "WAIVE": 1,
    "RULE": 1,
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
    # `ground_kind` is syntax 0.3 (WORDS_SINCE).
    "net_attribute": ("ground_domain", "voltage_domain", "ground_kind"),
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
    # Syntax 0.2: a declared parameter's type (decision S-4). `string`, `int`
    # and `bool`, then every quantity DIMENSION, in the order the dimensions
    # first appear in `rhoform.quantities.UNITS`. Transcribed by hand, not
    # imported: this module must not import the production package. A test
    # in rhoform/tests holds the transcription to the live table, so a
    # dimension added there without this list fails loudly.
    "param_type": (
        "string",
        "int",
        "bool",
        "resistance",
        "capacitance",
        "inductance",
        "voltage",
        "current",
        "power",
        "frequency",
        "time",
        "length",
        "temperature",
    ),
    # Syntax 0.2: the one callable a `for` header may name. A closed
    # vocabulary of one word rather than a keyword, for the reason every
    # list here exists: `range` was never reserved, so making it a keyword
    # would stop `range = new ...` parsing — a breaking change E1 forbids.
    "loop_iterator": ("range",),
    # Syntax 0.3: what a `ground_kind` net attribute's string may say (GA-2's
    # kinds). The value is a string, like every net attribute's, and the word
    # inside it is checked here.
    "ground_kind": ("unspecified", "signal", "power", "chassis", "earth"),
}

# Words of a closed vocabulary that a version after its first added, by
# vocabulary: a 0.2 file's `ground_kind` attribute is a 0.3 construct
# (RHO1016), not an unknown attribute.
WORDS_SINCE = {
    "net_attribute": {"ground_kind": "0.3"},
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
        # BOTH ARTIFACTS. The guard went into the Lark half only, so the
        # human-readable EBNF still described the pre-fix language and an
        # implementer working from it would reproduce `moduleM:` -> `module M:`.
        # This module's own docstring says two artifacts nobody diffs will
        # disagree eventually and the disagreement will surface as a parser
        # that accepts something the spec forbids -- which is exactly what a
        # one-sided fix to a frozen pair produces.
        if dialect != "lark":
            # The EBNF states the boundary ONCE, in the lexical layer, rather
            # than repeating a lookahead on all 28 keyword literals. Spelling
            # it inline 28 times is noise; stating it nowhere is what let the
            # Lark half and this half describe different languages.
            return f"'{self.text}'"
        # KEYWORDS CARRY THEIR OWN WORD BOUNDARY. An anonymous "module"
        # literal is matched by Lark's LALR CONTEXTUAL lexer, which restricts
        # the viable terminal set per parser state -- so in a state where
        # MODULE is the only candidate, `moduleM` matched the keyword and left
        # `M`, and `moduleM:` parsed identically to `module M:`. Eight
        # constructs did this (`pinb passive`, `partabstract:`, `noexclude_
        # from_bom`, `newrhoform.lib...`, and so on).
        #
        # rhoform.ebnf:21 already encodes the boundary on the FREE_NAME side,
        # and lang/tests/test_grammar.py asserts "the negative lookahead must
        # end at a word boundary" -- but every probe was in the BINDING
        # position, where FREE_NAME is viable and longest-match wins, so no
        # test could reach this. The guard belongs on both sides.
        if self.text.isidentifier():
            return f'/{self.text}(?![A-Za-z0-9_])/'
        return f'"{self.text}"'


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
INTEGER = Term("INTEGER")
QUANTITY, QUANTITY_INTERVAL = Term("QUANTITY"), Term("QUANTITY_INTERVAL")
QUANTITY_PLAIN = Term("QUANTITY_PLAIN")
# A name being bound, which may not be a keyword. See TERMINALS.
FREE_NAME = Term("FREE_NAME")
# A statement's head name. Since 0.3 a module-statement soft keyword lexes as
# its own terminal where a statement starts, so the two head positions that
# bind or name something there take those terminals too: `supply = new ...`
# is still a 0.2 instance named `supply` (see SOFT_KEYWORDS).
_HEAD = Alt(FREE_NAME, Term("SUPPLY"), Term("DRAW"), Term("WAIVE"),
            Term("RULE"))
# A pin a component rule or side names (0.3). A pin's own declaration takes
# any NAME, keywords included (`pin in power_in 1`), so a rule must be able
# to name it back: a FREE_NAME or any keyword but the two a rule body spells
# itself, `from` and `to`, which a pin so named cannot be referred to by.
# Every keyword here is already a literal of an older rule, so no terminal
# is added or renumbered.
PIN_KEYWORDS = tuple(word for word in KEYWORDS if word not in ("from", "to"))
_PIN = Alt(FREE_NAME, *(Lit(word) for word in PIN_KEYWORDS))


def _block(*body: Node) -> Seq:
    """`: NEWLINE INDENT <body> DEDENT` — the one block shape in the language."""
    return Seq(Lit(":"), NEWLINE, INDENT, *body, DEDENT)


RULES: tuple[tuple[str, str, Node], ...] = (
    (
        "start",
        "A file is the L8 pragma, then imports (0.2), then definitions: "
        "modules, and (0.2) components. Nothing else at file scope. The "
        "definitions are an inline choice rather than a `definition` rule so "
        "a 0.1 file's tree is exactly what it was under 0.1.",
        Seq(
            Opt(NEWLINE),
            Term("PRAGMA"),
            NEWLINE,
            Rep(Ref("import_stmt")),
            Rep(Alt(Ref("module_def"), Ref("component_def")), 1),
        ),
    ),
    (
        "module_def",
        "A module groups instances, nets and assertions. A parameter list "
        "is 0.2.",
        Seq(
            Lit("module"),
            FREE_NAME,
            Opt(Ref("params")),
            _block(Rep(Ref("statement"), 1)),
        ),
    ),
    (
        "statement",
        "Everything a module body can carry. `if` and `for` are 0.2; the "
        "annotations, waivers and rule overrides are 0.3.",
        Alt(
            Ref("port_decl"),
            Ref("isolated_decl"),
            Ref("net_decl"),
            Ref("assertion"),
            Ref("table_decl"),
            Ref("chain"),
            Ref("instance_decl"),
            Ref("if_stmt"),
            Ref("for_stmt"),
            Ref("annotation"),
            Ref("waiver"),
            Ref("rule_override"),
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
        "what keeps the statement head unambiguous for a one-token lexer. "
        "An index is 0.2. A 0.3 soft keyword heads a chain too, as the name "
        "it was before 0.3.",
        Seq(_HEAD, Opt(Ref("index")), Opt(Seq(Lit("."), NAME))),
    ),
    (
        "instance_decl",
        "Instantiation. Facts about the instance live in its optional body. "
        "An array size is 0.2. A 0.3 soft keyword may be the bound name, "
        "as it could before 0.3; from 0.3 on that name is reserved.",
        Seq(
            _HEAD,
            Lit("="),
            Lit("new"),
            Ref("qualified_name"),
            Opt(Ref("array_size")),
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
        "A footprint pin designator: `7`, or `A1` on a connector, or (0.3) a "
        "quoted one, `\"01\"`, which is one designator where `01` is two.",
        Alt(NUMBER, NAME, Term("QUOTED_DESIGNATOR")),
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
        "every diagnostic. A trailing `warning` (0.3) makes a failure "
        "annotate rather than gate; without it a failure is an error.",
        Seq(
            Lit("assert"),
            NAME,
            Alt(Lit("static"), Lit("dynamic")),
            _vocab("measurement_kind"),
            Lit("("),
            NAME,
            Lit(")"),
            Ref("bound"),
            Opt(Term("WARNING")),
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
        "quantity missing its unit or a count that should be whole — hence "
        "INTEGER here and NUMBER in `bound`. A bare name is a parameter "
        "reference (0.2); what it refers to is the elaborator's question.",
        Alt(
            QUANTITY,
            QUANTITY_INTERVAL,
            STRING,
            INTEGER,
            Lit("true"),
            Lit("false"),
            FREE_NAME,
        ),
    ),
    (
        "endpoint",
        "A connectable point: this module's port, or an instance pin. An "
        "index selects an array member (0.2).",
        Seq(NAME, Opt(Ref("index")), Opt(Seq(Lit("."), NAME))),
    ),
    (
        "qualified_name",
        "A dotted definition path, e.g. `rhoform.lib.passive.Resistor`.",
        Seq(NAME, Rep(Seq(Lit("."), NAME))),
    ),
    # ----------------------------------------------------------------------
    # Syntax 0.2 (decision S-5). Every rule below is new in 0.2, and they sit
    # AFTER every 0.1 rule on purpose: Lark numbers anonymous keyword
    # terminals in order of first appearance, so appending keeps each 0.1
    # keyword's terminal name — and with it every 0.1 file's tree — exactly
    # what it was. The production parser rejects each construct below under
    # a 0.1 pragma, with a fix-it that rewrites the pragma; the grammar
    # itself is one grammar for both versions.
    # ----------------------------------------------------------------------
    (
        "import_stmt",
        "Names imported from another file. The names are BOUND here, so each "
        "is a FREE_NAME; resolving the path is the package layer's job.",
        Seq(
            Lit("import"),
            FREE_NAME,
            Rep(Seq(Lit(","), FREE_NAME)),
            Lit("from"),
            STRING,
            NEWLINE,
        ),
    ),
    (
        "component_def",
        "A component definition: its pins and, since 0.3, its electrical "
        "rules and sides, and nothing else. Defaults such as `hardware` or "
        "flags are deliberately not definable here. A component with no "
        "pins (a mounting hole, a fiducial, artwork) has no block, as a "
        "`part` binding with no constraints has none.",
        Seq(
            Lit("component"),
            FREE_NAME,
            Opt(Ref("params")),
            Alt(_block(Rep(Alt(Ref("pin_decl"), Ref("rule_decl"),
                               Ref("side_decl")), 1)), NEWLINE),
        ),
    ),
    (
        "params",
        "A definition's parameter list. It may be empty, and like an "
        "argument list it may wrap, because `(` suspends layout.",
        Seq(
            Lit("("),
            Opt(Seq(Ref("param"), Rep(Seq(Lit(","), Ref("param"))))),
            Lit(")"),
        ),
    ),
    (
        "param",
        "One declared parameter: a bound name, a param_type name, and an "
        "optional default.",
        Seq(FREE_NAME, Lit(":"), _vocab("param_type"), Opt(Seq(Lit("="), Ref("value")))),
    ),
    (
        "if_stmt",
        "Statement-level conditional. The first block is the `if` branch and "
        "an optional second block the `else` branch; nesting gives "
        "conjunction, since there is no `and`.",
        Seq(
            Lit("if"),
            Ref("condition"),
            Ref("block"),
            Opt(Seq(Lit("else"), Ref("block"))),
        ),
    ),
    (
        "condition",
        "A bool parameter, or a parameter compared with a value.",
        Seq(FREE_NAME, Opt(Seq(Term("COMPARE"), Ref("value")))),
    ),
    (
        "for_stmt",
        "A bounded loop over compile-time integers. The callable is a "
        "loop_iterator name, checked after parsing; `range` is the only one.",
        Seq(
            Lit("for"),
            FREE_NAME,
            Lit("in"),
            _vocab("loop_iterator"),
            Lit("("),
            Ref("bound_arg"),
            Opt(Seq(Lit(","), Ref("bound_arg"))),
            Lit(")"),
            Ref("block"),
        ),
    ),
    (
        "bound_arg",
        "A loop bound: an integer, or an int parameter.",
        Alt(INTEGER, FREE_NAME),
    ),
    (
        "block",
        "The body of an `if`, `else` or `for`. A rule of its own so the two "
        "branches of an `if` stay two subtrees.",
        _block(Rep(Ref("statement"), 1)),
    ),
    (
        "array_size",
        "An array of instances, `name[0]` to `name[N-1]`. `[` does NOT "
        "suspend layout: an index never wraps.",
        Seq(Lit("["), Alt(INTEGER, FREE_NAME), Lit("]")),
    ),
    (
        "index",
        "An array member. A loop variable may be offset by a whole number.",
        Seq(
            Lit("["),
            Alt(FREE_NAME, INTEGER),
            Opt(Seq(Term("INDEX_OP"), INTEGER)),
            Lit("]"),
        ),
    ),
    # ----------------------------------------------------------------------
    # Syntax 0.3 (unfrozen until M2 exit, decision OD8). Appended after every
    # 0.2 rule for the reason the 0.2 rules follow the 0.1 ones, and spelling
    # no new keyword literal: every word they open with is a soft keyword
    # (SOFT_KEYWORDS, RULE_WORDS), so no 0.1 or 0.2 keyword's terminal moves
    # and no 0.1 or 0.2 tree changes. The production parser refuses each
    # construct below under an older pragma (CONSTRUCT_SINCE).
    # ----------------------------------------------------------------------
    (
        "annotation",
        "A design annotation: `supply` (a voltage window or a current "
        "capability at its target) or `draw` (a current bound into it), a "
        "target, and a bound. The target is a net label or an instance pin. "
        "What the bound means is the check stage's.",
        Seq(Alt(Term("SUPPLY"), Term("DRAW")), Ref("target"), Ref("bound"),
            NEWLINE),
    ),
    (
        "waiver",
        "A per-site waiver (T6): the code it waives, the target it waives it "
        "for (an instance, a net label or an assertion), and the "
        "justification, which is mandatory.",
        Seq(Term("WAIVE"), Term("DIAGNOSTIC_CODE"), Ref("target"), STRING,
            NEWLINE),
    ),
    (
        "rule_override",
        "An instance's electrical rules, stated by the module that "
        "instantiates it: a component used for something its definition "
        "does not say (a diode as a power path, a FET as a load switch).",
        Seq(Term("RULE"), Ref("target"), Ref("rule_body"), NEWLINE),
    ),
    (
        "target",
        "What a 0.3 module statement is about: a name, an array member, or "
        "a pin of either. Its first name is a FREE_NAME, as a chain head's "
        "is, so that the keyword after it (`within`, `at`) lexes as one.",
        Seq(FREE_NAME, Opt(Ref("index")), Opt(Seq(Lit("."), NAME))),
    ),
    (
        "rule_decl",
        "One electrical rule of a component definition. Rules and sides "
        "follow the pins in canonical form; the grammar takes them in any "
        "order.",
        Seq(Ref("rule_body"), NEWLINE),
    ),
    (
        "rule_body",
        "A rule word, the pins it covers, optionally a `from` or `to` pin, "
        "and optionally a value. A pin is a FREE_NAME or a keyword other "
        "than `from` and `to`, so those two after the pins lex as keywords; "
        "which words take how many pins is the check stage's.",
        Seq(
            Term("RULE_WORD"),
            Rep(_PIN),
            Opt(Seq(Alt(Lit("from"), Lit("to")), _PIN)),
            Opt(Seq(Lit("="), Ref("value"))),
        ),
    ),
    (
        "side_decl",
        "One side of an isolating component (GA-13): its name and the pins "
        "on it.",
        Seq(Term("SIDE"), FREE_NAME, Lit(":"), Rep(_PIN, 1), NEWLINE),
    ),
)

# What needs which syntax version, for the production parser's version gate
# (RHO1016): a tree rule, or a terminal whose token is the whole construct.
# A construct appearing under an older pragma counts once per node, nested
# ones included. Two 0.2 constructs have no key here, because neither is a
# rule or a token of its own: a parameter reference (a `value` whose token is
# a FREE_NAME) and, in 0.3, a `ground_kind` attribute (WORDS_SINCE); the
# parser recognizes both directly.
CONSTRUCT_SINCE = {
    "import_stmt": "0.2",
    "component_def": "0.2",
    "params": "0.2",
    "if_stmt": "0.2",
    "for_stmt": "0.2",
    "array_size": "0.2",
    "index": "0.2",
    "annotation": "0.3",
    "waiver": "0.3",
    "rule_override": "0.3",
    "rule_decl": "0.3",
    "side_decl": "0.3",
    "QUOTED_DESIGNATOR": "0.3",
    "WARNING": "0.3",
}


# --------------------------------------------------------------------------
# Emitters
# --------------------------------------------------------------------------

_VERSION_LIST = ", ".join(SYNTAX_VERSIONS)
_UNFROZEN_LIST = ", ".join(UNFROZEN_SYNTAX_VERSIONS)

_HEADER = f"""\
Rhoform syntax v{SYNTAX_VERSION} — {{title}}

GENERATED FROM lang/grammar/rhoform_syntax.py. Do not edit it: regenerate
with `python3 -m grammar.rhoform_syntax --write`. `make grammar` only CHECKS
that this file matches its source, and fails if it does not.

The grammar is context-free over the layout-tokenized stream L5 fixes, so
INDENT, DEDENT and NEWLINE arrive as terminals and no rule below is sensitive
to column position. Every file opens with the L8 pragma, naming one of the
versions {_VERSION_LIST}; new files use `{PRAGMA_TEXT}`. One grammar
serves every version: each version only adds, and the constructs it adds are
refused under an older pragma after parsing, not by a second grammar.
Version {_UNFROZEN_LIST} is unfrozen: its constructs may still change shape
before it is frozen, and no release ships while it is.

Pin roles, hardware kinds, measurement kinds, net attributes, parameter types,
the loop iterator and ground kinds are NOT keywords here: they are plain names
checked against a closed list after parsing, because `input` and `output` are
pin roles and a design may legitimately name an instance `input`. The lists are
published in the source module as CLOSED_VOCABULARIES. The words that open a
0.3 statement are soft keywords: named terminals viable only where that
statement starts, which leave the word free as a name everywhere else.
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
        "line, suspended inside `(` `)` so a parameter list may wrap. `[` "
        "`]` do NOT suspend it: an index or array size never wraps, and an "
        "unclosed `[` is one error on its own line rather than a file "
        "swallowed into one logical line.",
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
    out.append("(* KEYWORD BOUNDARY. Every quoted word literal in the productions")
    out.append("   of this grammar matches only when NOT followed by [A-Za-z0-9_].")
    out.append("   Without this rule `moduleM:` lexes as `module` + `M` and parses as")
    out.append("   `module M:`; the Lark artifact encodes it per-literal as")
    out.append("   /word(?![A-Za-z0-9_])/. An implementer who ignores this rule builds")
    out.append("   a parser that accepts programs this grammar forbids. *)")
    out.append("")
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

    out.append("// Terminals, emitted from TERMINALS so this artifact cannot")
    out.append("// carry a different terminal SET from the EBNF. Priorities come")
    out.append("// from LARK_TERMINAL_PRIORITY; see it for why each is ranked.")
    for name, pattern in TERMINALS.items():
        priority = LARK_TERMINAL_PRIORITY.get(name)
        label = f"{name}.{priority}" if priority is not None else name
        out.append(f"{label}: {_regex_literal(pattern)}")
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
