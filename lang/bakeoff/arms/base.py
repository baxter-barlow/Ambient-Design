"""What every arm shares, and the variant axes measured on top of it.

An ARM is a candidate surface syntax plus the two functions that make it
measurable: `render` (model -> canonical source) and `parse` (source -> model).
`render` is the arm's prototype of I1's zero-option formatter, which is why
there is exactly one canonical spelling per design per variant — a token count
over source somebody hand-formatted would be a count of their habits.

A VARIANT is an axis measured on top of an arm, not another candidate:

  explicit           Everything written out. The no-inference upper bound.
  inferred           The T9 rules in library.py applied. The realistic cell,
                     and the one AMB-33 should compare arms on.
  inferred+columnar  L6's columnar sub-syntax on top of `inferred`.

L6 is only measured on top of `inferred` on purpose. A columnar section is for
UNIFORM TABULAR data, and per-instance pin declarations are neither: in the
`explicit` cell almost no group of instances is uniform, so a columnar reading
there would measure the absence of inference rather than the value of columns.

Both candidates hold the following IDENTICAL, so that the measured difference
is attributable to one axis rather than to a pile of unrelated choices:

  - the `#pragma` version header (L8 fixes that it exists)
  - literals and the quantity mini-language (T3/T4 already fix these)
  - the layout tokenizer (L5 fixes it)
  - `module` block headers and `port` interface declarations
  - assertion statements
  - the columnar sub-syntax, which is L6's proposal and not either
    candidate's invention

WHAT ACTUALLY DIFFERS is one axis, stated so it can be argued with: how a
design attaches facts to an instance and how it states connectivity.
Candidate A spends one statement per fact and one statement per connection;
candidate B scopes facts in a block under the instantiation and members in a
block under a net label.
"""

from ..diagnostics import Diag, ParseFailure, Span
from ..layout import Token, strip_comments, tokenize
from ..model import (
    Assertion,
    HARDWARE_KINDS,
    MEASUREMENT_KINDS,
    PIN_ROLES,
    Port,
    Value,
)
from ..quantities import QuantityError, parse_quantity

# L8's syntax-version pragma, spelled as the §8-Q2 naming decision fixed it
# (AMB-30): `#pragma rhoform-syntax <major.minor>`. The placeholder this
# replaced, `#pragma language "0.1.0"`, predated the decision.
#
# The syntax freeze adopted this one spelling ahead of the rest, on the
# grounds that freezing a grammar does not license a repository-wide rename.
# That rename has since happened, so the stdlib root and the diagnostic
# prefixes here now say Rhoform too — the note that used to explain why they
# did not was rewritten by the very sweep it was describing.
PRAGMA = "#pragma rhoform-syntax 0.1"

VARIANTS = ("explicit", "inferred", "inferred+columnar")

# How many rows a columnar section needs before it is emitted.
#
# THIS IS AN OPEN L6 DESIGN PARAMETER, NOT A FACT. An earlier comment here
# claimed 3 was "the smallest group where a table is shorter than the
# statements it replaces", which is false: sweeping it shows 2 is cheaper
# still on benchmark (c) in both candidates. Three is a readability judgement
# — a two-row table is a header and two lines, which reads worse than two
# statements — and because it is a judgement the measurement reports the whole
# curve (`bakeoff measure` prints L6 across thresholds 2..6) rather than one
# cell that could be improved by quietly lowering the constant.
COLUMNAR_MIN_ROWS = 3

# L5 makes the surface keyword-based, so these words cannot also be names.
# Held in one place and shared by both candidates: a reserved-word list that
# differed between them would be a second axis nobody is choosing between.
# The list is a superset of each candidate's own keywords, so a design that
# parses under one candidate parses under the other, which the cross-arm
# agreement check depends on.
RESERVED = frozenset({
    "module", "port", "pin", "signal", "net", "table", "assert", "new",
    "part", "abstract", "hardware", "dnp", "exclude_from_bom", "board_only",
    "within", "at", "least", "most", "to", "static", "dynamic", "isolated", "no",
    "true", "false",
})


def reserved_words_block(width: int = 76) -> str:
    """The reserved words, wrapped, for a language card to interpolate.

    Generated rather than transcribed. Both cards previously carried the list
    by hand and both had fallen two words behind `RESERVED` — `isolated` and
    `no` were reserved without being taught, so the A4 artifact told a model a
    name was available that the parser rejects. The test meant to catch it
    asked `assertIn(word, card)` against the whole card, and a two-letter word
    like `no` is a substring of `not`, `none` and `nominal`, so it passed on
    prose. A card and a parser that read the same constant cannot drift.
    """
    words = sorted(RESERVED)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def variant_flags(variant: str) -> tuple[bool, bool]:
    """(apply_inference, use_columnar) for a variant name."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; known: {', '.join(VARIANTS)}")
    return variant != "explicit", variant == "inferred+columnar"


class Cursor:
    """Token cursor with error accumulation.

    Accumulates diagnostics rather than raising on the first one: P2 makes
    diagnostic quality the property the bake-off is really measuring, and a
    parser that reports one error per run would give every candidate the same
    flattering score.
    """

    def __init__(self, tokens: list[Token], code_prefix: str):
        self.tokens = tokens
        self.index = 0
        self.prefix = code_prefix
        self.diagnostics: list[Diag] = []

    # -- inspection ------------------------------------------------------
    @property
    def current(self) -> Token:
        return self.tokens[min(self.index, len(self.tokens) - 1)]

    def at(self, kind: str, text: str | None = None) -> bool:
        token = self.current
        return token.kind == kind and (text is None or token.text == text)

    def at_keyword(self, *words: str) -> bool:
        return self.current.kind == "NAME" and self.current.text in words

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def reject_reserved_name(self) -> None:
        """Catch a keyword used as a name, and say so.

        Without this the keyword dispatch wins and the author gets
        "expected a signal name, found '='" for a line that plainly declares
        an instance called `signal`. A diagnostic that blames the wrong token
        is precisely the repair-loop failure P2 is about.
        """
        token = self.current
        if token.kind != "NAME" or token.text not in RESERVED:
            return
        if self.peek().kind == "OP" and self.peek().text in ("=", ".", "~"):
            self.diagnostics.append(
                Diag(
                    code=f"{self.prefix}0212",
                    message=(
                        f"{token.text!r} is a reserved word and cannot be used "
                        "as a name"
                    ),
                    span=token.span(),
                    params={"word": token.text},
                    fixit="rename it; the reserved words are: "
                    + ", ".join(sorted(RESERVED)),
                )
            )
            self.fail()

    def advance(self) -> Token:
        token = self.current
        if self.index < len(self.tokens) - 1:
            self.index += 1
        return token

    # -- errors ----------------------------------------------------------
    def error(self, number: str, message: str, *, fixit: str | None = None, **params):
        self.diagnostics.append(
            Diag(
                code=f"{self.prefix}{number}",
                message=message,
                span=self.current.span(),
                params=params,
                fixit=fixit,
            )
        )

    def fail(self) -> None:
        if not self.diagnostics:
            self.error("9999", "parse failed with no diagnostic recorded")
        raise ParseFailure(self.diagnostics)

    def finish(self) -> None:
        if self.diagnostics:
            raise ParseFailure(self.diagnostics)

    # -- consumption -----------------------------------------------------
    def expect(self, kind: str, text: str | None = None, *, what: str = "") -> Token:
        if self.at(kind, text):
            return self.advance()
        wanted = f"{text!r}" if text else kind.lower()
        self.error(
            "0001",
            f"expected {wanted}{' ' + what if what else ''}, found "
            f"{self.current.text!r}"
            if self.current.kind != "EOF"
            else f"expected {wanted}{' ' + what if what else ''}, found end of file",
            found=self.current.text or self.current.kind,
        )
        self.fail()

    def expect_name(self, what: str) -> str:
        return self.expect("NAME", what=what).text

    def expect_free_name(self, what: str) -> str:
        """A name being BOUND: rejected if it is a reserved word.

        Every site that introduces an identifier goes through this. The
        statement-head guard alone was not enough — table row names, table
        header definitions, module names and port names all bound identifiers
        through a bare `expect_name`, so a design could declare a row called
        `net` that its own formatter could not re-emit.
        """
        token = self.current
        name = self.expect_name(what)
        if name in RESERVED:
            self.diagnostics.append(
                Diag(
                    code=f"{self.prefix}0212",
                    message=f"{name!r} is a reserved word and cannot name {what}",
                    span=token.span(len(name)),
                    params={"word": name},
                    fixit="the reserved words are: " + ", ".join(sorted(RESERVED)),
                )
            )
            self.fail()
        return name

    def expect_newline(self) -> None:
        self.expect("NEWLINE", what="at end of statement")

    def skip_newlines(self) -> None:
        while self.at("NEWLINE"):
            self.advance()

    def expect_block(self, what: str) -> None:
        """Consume `:` NEWLINE INDENT."""
        self.expect("OP", ":", what=f"to open the {what} block")
        self.expect_newline()
        if not self.at("INDENT"):
            self.error(
                "0101",
                f"expected an indented block after `{what}:`",
                fixit=f"indent the {what} body by 4 spaces",
                block=what,
            )
            self.fail()
        self.advance()

    def end_block(self) -> None:
        if self.at("DEDENT"):
            self.advance()
            return
        if self.at("EOF"):
            return
        self.error("0102", f"expected end of block, found {self.current.text!r}")
        self.fail()

    # -- shared productions ----------------------------------------------
    def qualified_name(self, what: str) -> str:
        parts = [self.expect_name(what)]
        while self.at("OP", "."):
            self.advance()
            parts.append(self.expect_name(what))
        return ".".join(parts)

    def dotted_ref(self, what: str) -> str:
        """`name` or `name.port`, the endpoint production."""
        first = self.expect_name(what)
        if self.at("OP", "."):
            self.advance()
            return f"{first}.{self.expect_name(what)}"
        return first

    def value(self, what: str) -> Value:
        token = self.current
        if token.kind == "QUANTITY":
            self.advance()
            try:
                return Value(tag="q", quantity=parse_quantity(token.text))
            except QuantityError as exc:
                self.diagnostics.append(
                    Diag(
                        code="RHOX0005",
                        message=str(exc),
                        span=token.span(),
                        params={"literal": token.text},
                    )
                )
                self.fail()
        if token.kind == "STRING":
            self.advance()
            return Value(tag="s", text=token.text)
        if token.kind == "NUMBER":
            self.advance()
            if "." in token.text:
                self.diagnostics.append(
                    Diag(
                        code=f"{self.prefix}0003",
                        message=(
                            f"{token.text!r} is a bare decimal; a dimensioned value "
                            "needs a unit and a count must be a whole number"
                        ),
                        span=token.span(),
                        params={"literal": token.text},
                        fixit="add a unit, e.g. `10kohm`",
                    )
                )
                self.fail()
            return Value(tag="i", number=int(token.text))
        if token.kind == "NAME" and token.text in ("true", "false"):
            self.advance()
            return Value(tag="b", flag=token.text == "true")
        self.error(
            "0002",
            f"expected a value for {what}, found {token.text!r}",
            fixit="values are quantities, \"strings\", whole numbers, true or false",
            found=token.text or token.kind,
        )
        self.fail()


def open_source(source: str, code_prefix: str) -> Cursor:
    """Tokenize and check the L8 pragma. Shared by every arm."""
    cursor = Cursor(strip_comments(tokenize(source)), code_prefix)
    if not cursor.at("PRAGMA"):
        cursor.error(
            "0100",
            "file does not start with a syntax-version pragma",
            fixit=f"add `{PRAGMA}` as the first line",
        )
        cursor.fail()
    pragma = cursor.advance()
    if pragma.text != PRAGMA:
        cursor.diagnostics.append(
            Diag(
                code=f"{code_prefix}0100",
                message=(
                    f"unsupported syntax-version pragma {pragma.text!r}; this "
                    f"prototype implements {PRAGMA!r}"
                ),
                span=pragma.span(),
                params={"pragma": pragma.text},
            )
        )
        cursor.fail()
    cursor.skip_newlines()
    return cursor


def render_role(role: str) -> str:
    return role


def render_pin(port) -> str:
    """`pin <name> <role> [<designator> ...]` — shared by both candidates."""
    pins = " " + " ".join(port.pin_numbers) if port.pin_numbers else ""
    return f"pin {port.name} {port.role}{pins}"


def render_assertion(assertion) -> str:
    """Assertion statement, held identical across candidates.

    Assertions are not repeated per-instance facts, so they are not on the
    axis the two candidates differ along. Varying them anyway would add a
    difference to the measurement that nobody asked a question about.
    """
    unit = "" if assertion.unit == "1" else assertion.unit
    if assertion.minimum is not None and assertion.maximum is not None:
        bounds = f"within {assertion.minimum}{unit} to {assertion.maximum}{unit}"
    elif assertion.minimum is not None:
        bounds = f"at least {assertion.minimum}{unit}"
    else:
        bounds = f"at most {assertion.maximum}{unit}"
    return (
        f"assert {assertion.name} {assertion.tier} "
        f"{assertion.measurement}({assertion.subject}) {bounds}"
    )


def parse_role(cursor: Cursor, what: str) -> str:
    """A T2 lattice role. Closed vocabulary, so a typo is a diagnostic."""
    token = cursor.current
    if token.kind != "NAME" or token.text not in PIN_ROLES:
        cursor.error(
            "0004",
            f"{token.text!r} is not a pin role for {what}",
            fixit="roles are: " + ", ".join(PIN_ROLES),
            found=token.text or token.kind,
        )
        cursor.fail()
    cursor.advance()
    return token.text


def parse_port_decl(cursor: Cursor) -> Port:
    """`port <name> <role>` — a module's own interface port."""
    cursor.advance()  # `port`
    name = cursor.expect_free_name("a port")
    role = parse_role(cursor, f"port {name}")
    cursor.expect_newline()
    return Port(name=name, role=role)


def parse_pin_decl(cursor: Cursor) -> Port:
    """`pin <name> <role> [<designator> ...]` — a component's pin-mapped port."""
    cursor.advance()  # `pin`
    name = cursor.expect_free_name("a pin")
    role = parse_role(cursor, f"pin {name}")
    designators = []
    while cursor.current.kind in ("NUMBER", "NAME") and not cursor.at("NEWLINE"):
        designators.append(cursor.advance().text)
    cursor.expect_newline()
    return Port(name=name, role=role, pin_numbers=tuple(sorted(designators)))


_BOUND_RE = __import__("re").compile(r"\A(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)([A-Za-z][A-Za-z0-9/]*)\Z")


def _split_bound(cursor: Cursor, text: str) -> tuple[str, str]:
    match = _BOUND_RE.match(text)
    if match is None:
        cursor.error("0005", f"{text!r} is not a bound")
        cursor.fail()
    return match.group(1), match.group(2)


def parse_assertion(cursor: Cursor) -> Assertion:
    """`assert <name> <tier> <kind>(<net>) within|at least|at most <bounds>`.

    Held identical across candidates: an assertion is not a repeated
    per-instance fact, so it is not on the axis the two differ along.
    """
    cursor.advance()  # `assert`
    name = cursor.expect_name("an assertion name")
    tier_token = cursor.current
    if tier_token.kind != "NAME" or tier_token.text not in ("static", "dynamic"):
        cursor.error(
            "0006",
            f"expected `static` or `dynamic` after assertion name, found "
            f"{tier_token.text!r}",
            fixit="V1 makes the tier visible in every diagnostic, so it is written",
            found=tier_token.text or tier_token.kind,
        )
        cursor.fail()
    tier = cursor.advance().text

    kind_token = cursor.current
    if kind_token.kind != "NAME" or kind_token.text not in MEASUREMENT_KINDS:
        cursor.error(
            "0007",
            f"{kind_token.text!r} is not in the V2 measurement vocabulary",
            fixit="the v1 vocabulary is closed: " + ", ".join(MEASUREMENT_KINDS),
            found=kind_token.text or kind_token.kind,
        )
        cursor.fail()
    measurement = cursor.advance().text

    cursor.expect("OP", "(", what="around the probed net")
    subject = cursor.expect_name("the probed net")
    cursor.expect("OP", ")", what="around the probed net")

    keyword = cursor.current
    minimum = maximum = None
    unit = "1"
    if keyword.kind == "NAME" and keyword.text == "within":
        cursor.advance()
        if cursor.at("QUANTITY"):
            text = cursor.advance().text
            if " to " not in text:
                cursor.error("0008", f"`within` needs two bounds, found {text!r}")
                cursor.fail()
            low, high = text.split(" to ", 1)
            minimum, unit = _split_bound(cursor, low)
            maximum, high_unit = _split_bound(cursor, high)
            if high_unit != unit:
                cursor.error(
                    "0009",
                    f"bound units differ: {unit!r} and {high_unit!r}",
                )
                cursor.fail()
        else:
            minimum = cursor.expect("NUMBER", what="as the lower bound").text
            if not cursor.at_keyword("to"):
                cursor.error("0008", "expected `to` between the two bounds")
                cursor.fail()
            cursor.advance()
            maximum = cursor.expect("NUMBER", what="as the upper bound").text
    elif keyword.kind == "NAME" and keyword.text in ("at",):
        cursor.advance()
        direction = cursor.current
        if direction.kind != "NAME" or direction.text not in ("least", "most"):
            cursor.error("0010", "expected `at least` or `at most`")
            cursor.fail()
        cursor.advance()
        if cursor.at("QUANTITY"):
            value, unit = _split_bound(cursor, cursor.advance().text)
        else:
            value = cursor.expect("NUMBER", what="as the bound").text
        if direction.text == "least":
            minimum = value
        else:
            maximum = value
    else:
        cursor.error(
            "0011",
            f"expected `within`, `at least` or `at most`, found {keyword.text!r}",
            found=keyword.text or keyword.kind,
        )
        cursor.fail()

    cursor.expect_newline()
    return Assertion(
        name=name,
        tier=tier,
        measurement=measurement,
        subject=subject,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
    )
