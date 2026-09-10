"""Quantity literals: parsing, exact-decimal semantics, and the T3 normal form.

This is the production sibling of the bake-off's shared literal
mini-language (lang/bakeoff/quantities.py), and the module the spec's
literal-normal-form section names as its reference implementation. It exists
now, before the formatter (R16) and the full quantity type (R21), because
R54 orders it so: the normal form is authored FIRST as a single source, and
both later issues consume THIS module rather than re-deciding the rules.
While the prototypes exist, lang/tests anchors this module's unit table and
parse acceptance against theirs, so the port cannot quietly diverge.

EXACT DECIMALS, NEVER FLOATS. Same posture as the prototype and for the
same reason: `0.1` is not an IEEE double, and a tolerance band is exactly
where that stops being a curiosity. All arithmetic is `decimal.Decimal`
under a local context sized from its own operands (never narrower than 60
digits) that REFUSES to round rather than rounding silently, and every
normal-form rewrite is a power-of-ten shift, so normalization NEVER rounds
— value-exactness (T3) is a property of the construction, and the
conformance vectors re-check it anyway.

THE NORMAL FORM, in one paragraph (normative text: the spec's
literal-normal-form section; this docstring paraphrases). Every
number-plus-unit pair in a literal is rewritten independently: the number
takes its minimal decimal spelling (no leading `+`, no padding zeros, `-0`
is `0`), and the unit is the dimension's ladder entry that puts the
magnitude in [1, 1000) — unique because every ladder steps by exactly 10^3
— falling back to the ladder's nearest end when no entry achieves it, with
zero spelled in the base unit and `degC` never rescaled (an offset scale
has no prefixes to move to). A percent tolerance keeps `%` with the minimal
number. The literal's FORM is preserved: exact, `+/-` absolute, `+/- %`,
bracketed interval, and bare interval are five distinct value shapes (T4),
and normalization rewrites their components without converting between
them.

DELIBERATELY ABSENT: the prototype's dimensionless pseudo-unit `"1"`. No
literal can lex it (a quantity token requires a letter-initial unit), and
dimensionless assertion bounds are NUMBER tokens, not quantities. Carrying
an unreachable table row into the production module would make the closed
table lie about what the language accepts.
"""

import re
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact,
    InvalidOperation, Overflow, Subnormal, localcontext,
)

# Unit table: symbol -> (dimension, multiplier to the dimension's base unit).
# CLOSED ON PURPOSE, exactly as the prototype's: an unknown unit is an error
# rather than a pass-through, so a typo cannot become its own dimension.
# Multipliers are exact powers of ten; within each dimension the ladder
# steps by exactly 10^3, which is what makes the normal form's unit choice
# unique (see the docstring). Extend only with the spec section.
UNITS: dict[str, tuple[str, Decimal]] = {
    "mohm": ("resistance", Decimal("1e-3")),
    "ohm": ("resistance", Decimal(1)),
    "kohm": ("resistance", Decimal("1e3")),
    "Mohm": ("resistance", Decimal("1e6")),
    "pF": ("capacitance", Decimal("1e-12")),
    "nF": ("capacitance", Decimal("1e-9")),
    "uF": ("capacitance", Decimal("1e-6")),
    "mF": ("capacitance", Decimal("1e-3")),
    "F": ("capacitance", Decimal(1)),
    "nH": ("inductance", Decimal("1e-9")),
    "uH": ("inductance", Decimal("1e-6")),
    "mH": ("inductance", Decimal("1e-3")),
    "H": ("inductance", Decimal(1)),
    "uV": ("voltage", Decimal("1e-6")),
    "mV": ("voltage", Decimal("1e-3")),
    "V": ("voltage", Decimal(1)),
    "kV": ("voltage", Decimal("1e3")),
    "nA": ("current", Decimal("1e-9")),
    "uA": ("current", Decimal("1e-6")),
    "mA": ("current", Decimal("1e-3")),
    "A": ("current", Decimal(1)),
    "uW": ("power", Decimal("1e-6")),
    "mW": ("power", Decimal("1e-3")),
    "W": ("power", Decimal(1)),
    "Hz": ("frequency", Decimal(1)),
    "kHz": ("frequency", Decimal("1e3")),
    "MHz": ("frequency", Decimal("1e6")),
    "ns": ("time", Decimal("1e-9")),
    "us": ("time", Decimal("1e-6")),
    "ms": ("time", Decimal("1e-3")),
    "s": ("time", Decimal(1)),
    "um": ("length", Decimal("1e-6")),
    "mm": ("length", Decimal("1e-3")),
    "m": ("length", Decimal(1)),
    # Celsius is an OFFSET scale: multiplier 1, its own dimension, and the
    # normal form never rescales it — there is nowhere exact to go.
    "degC": ("temperature", Decimal(1)),
}

_NUM = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
_UNIT = r"[A-Za-z][A-Za-z0-9/]*"

# The five T4 forms in one anchored expression — the same shape the frozen
# grammar's QUANTITY terminals and the prototype lexer match, so what parses
# here is what lexes there.
_QUANTITY_RE = re.compile(
    rf"""
    \A
    (?P<value>{_NUM})(?P<unit>{_UNIT})
    (?:
        \ \+/-\ (?P<tol>{_NUM})(?P<tol_unit>{_UNIT}|%)
      | \ \((?P<lo_v>{_NUM})(?P<lo_u>{_UNIT})\ to\ (?P<hi_v>{_NUM})(?P<hi_u>{_UNIT})\)
      | \ to\ (?P<to_v>{_NUM})(?P<to_u>{_UNIT})
    )?
    \Z
    """,
    re.VERBOSE,
)

_PRECISION = 60


def _wide_enough(*values: Decimal) -> int:
    """A precision that cannot round a product OR a sum of `values`.

    `_PRECISION` is a FLOOR, not a ceiling. Pinning it flat meant a
    literal past 60 significant digits rounded exactly the way a literal
    past 28 did before this was adaptive: `1.0...01ohm` with 70 digits
    became `1ohm`, the whole fractional part gone. Round 6 fixed the
    28-digit boundary in `_plain()` alone, which MOVED the boundary
    rather than removing it, and round 7 found it again one order of
    magnitude out — the same half-fix shape it caught in the prescan.

    Two bounds, because the module has two kinds of operation. Summing
    the operands' digit counts is exact for a PRODUCT and generous for
    the power-of-ten shifts that make up most of the arithmetic, which
    move the exponent and neither create nor destroy significant digits.
    It says nothing about a SUM: `value - spread` with the spread many
    orders of magnitude below the value needs every position from the
    value's leading digit down to the spread's trailing one, however few
    digits either operand has on its own. Round 7's bound covered the
    product and left that one sum — the third time this defect was fixed
    for the term in front of it and not the sibling (round 8, the focused
    pass). The span term is that sibling: highest adjusted exponent to
    lowest exponent, plus one for the inclusive count and one for a carry.

    Callers pass the operands of the operation they are about to do, not
    the numbers the literal started with: the sum's operand is the spread
    as COMPUTED, whose exponent is not any literal number's.
    """
    digits = sum(len(value.as_tuple().digits) for value in values)
    span = (max(value.adjusted() for value in values)
            - min(value.as_tuple().exponent for value in values) + 2)
    return max(_PRECISION, digits, span)


@contextmanager
def _exact_context(*operands: Decimal):
    """A local context wide enough for `operands` that cannot round quietly.

    The bound above is the ESTIMATE; the `Inexact` trap is the CHECK. An
    operation that would discard a nonzero digit raises instead, and the
    literal is refused with a stable reason — a value silently changed on
    the way in is the one thing T3 forbids, and three rounds of moving the
    boundary are three reasons not to trust the next bound on inspection
    alone. `Overflow` is caught for the same reason from the other side:
    a numeral of a million digits leaves Decimal's default exponent range
    inside `to_base()`, and until round 8 escaped `parse()` as a
    traceback, which compilation-is-total forbids. Its mirror, a million
    zeros after the point, is refused by the `Subnormal` trap the moment
    a result drops below `Emin` — at EVERY site alike. Trapping only the
    rounding let the refusal depend on which site's precision estimate
    happened to widen `Etiny`: `parse()` accepted a literal that `key()`
    and `normal_form()` then refused (round 8's focused pass). The floor
    is a property of the literal, not of the site. No realistic literal
    reaches either end; the point is that the unrealistic one gets one
    diagnostic, everywhere, not a crash and not a new value.

    Every field is set, none inherited. `localcontext()` COPIES the
    ambient context, so fixing the precision alone (round 6) left the
    exponent range and the rounding mode to whatever the process had
    last set: an ambient `Emax` of 5 made `5000000MHz` overflow and be
    refused (round 8). Hermetic means the same literal parses to the same
    value in every process state.
    """
    with localcontext(Context(
        prec=_wide_enough(*operands),
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Subnormal,
               Inexact],
    )) as ctx:
        try:
            yield ctx
        except (Inexact, Overflow, Subnormal):
            raise QuantityError(
                "the literal's exact value cannot be carried at the working "
                "precision or exponent range rhoform.quantities derived for "
                "it; it was refused rather than rounded"
            ) from None

FORMS = ("exact", "tolerance-absolute", "tolerance-percent",
         "interval-bracketed", "interval-bare")


class QuantityError(ValueError):
    """A literal is not a well-formed quantity. `reason` is the stable,
    single-sentence text RHO1010 carries as its structured param."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Quantity:
    """One parsed literal: its authored text, its form, its components.

    Components keep their AUTHORED units (unlike the prototype, which
    converts bounds into the nominal's unit and forgets the spelling) —
    the normal form rewrites each component independently, so re-rendering
    needs each one as written. `nominal`/`lower`/`upper` are the semantic
    reading in the dimension's base unit; `nominal` is None for the bare
    interval, a range with no centre.
    """

    text: str
    form: str
    dimension: str
    unit: str
    components: tuple[tuple[Decimal, str], ...]
    nominal: Decimal | None
    lower: Decimal
    upper: Decimal

    def key(self) -> tuple:
        """Dimensional identity, prototype-compatible: equal physical
        meanings produce equal keys whatever units they were written in."""
        return (
            self.dimension,
            None if self.nominal is None else _plain(self.nominal),
            _plain(self.lower),
            _plain(self.upper),
        )  # all three are base-unit values; see the constructor's return

    def is_exact(self) -> bool:
        return self.nominal is not None and self.lower == self.upper


def _plain(value: Decimal) -> str:
    """Canonical digit string for an exact decimal: minimal, no exponent.

    `normalize()` strips trailing zeros but renders 1000 as `1E+3`;
    `format(..., "f")` re-expands it. Zero is special-cased because
    `Decimal("0.0").normalize()` is `0` but `-0` must not print a sign.

    `normalize()` is a CONTEXT operation, so it rounds to the ambient
    context's precision — 28 by default. Called bare it made the normal
    form depend on process-global mutable state that no caller of
    `normal_form()` controls, and silently rounded any literal past 28
    significant digits: `1.0000000000000000000000000001ohm` normalized to
    `1ohm`, discarding the whole fractional part (review round 6). Every
    call site sits outside the module's own `localcontext` blocks, so the
    context belongs here, on the operation that needs it.

    The precision is the value's own digit count whenever that exceeds
    the module's, so the operation cannot round whatever it is handed.
    That is what makes this module's "normalization NEVER rounds" and the
    spec's T3 value-exactness true rather than merely intended — and both
    checks that claimed to pin it measured the wrong population: the
    precision test used 20 significant digits, comfortably under the
    default 28, and the idempotence checks compare `key()` to `key()`,
    where both sides round identically.
    """
    if value == 0:
        return "0"
    with _exact_context(value):
        return format(value.normalize(), "f")


def dimension_of(unit: str) -> str:
    try:
        return UNITS[unit][0]
    except KeyError:
        raise QuantityError(
            f"unknown unit {unit!r}; the unit table is closed and extended "
            "only with the spec's literal-normal-form section"
        ) from None


def to_base(value: Decimal, unit: str) -> Decimal:
    dimension, multiplier = UNITS[unit]
    if dimension == "temperature":
        return value
    with _exact_context(value, multiplier):
        return +(value * multiplier)


def parse_quantity(text: str) -> Quantity:
    """Parse one literal, or raise QuantityError with a stable reason."""
    match = _QUANTITY_RE.match(text)
    if match is None:
        raise QuantityError(
            "not one of the five quantity forms (`100kohm`, "
            "`100kohm +/- 1%`, `2V +/- 0.2V`, `9.5mA (8mA to 10.5mA)`, "
            "`3V to 3.6V`); ASCII only, no exponent notation, exactly one "
            "space either side of `+/-` and `to`"
        )

    unit = match.group("unit")
    dimension = dimension_of(unit)
    value = Decimal(match.group("value"))

    # Every number the literal carries, measured before the context is
    # opened: `Decimal(str)` is exact and context-independent, so this
    # cannot itself round. The widest PRODUCT here is value times a
    # percentage tolerance, which the digit-count sum covers; the one SUM
    # re-derives its width below from the spread it actually computed.
    with _exact_context(*(
        Decimal(match.group(name))
        for name in ("value", "tol", "lo_v", "hi_v", "to_v")
        if match.group(name) is not None
    )) as ctx:

        if match.group("tol") is not None:
            tol_unit = match.group("tol_unit")
            magnitude = Decimal(match.group("tol"))
            if magnitude < 0:
                raise QuantityError(
                    "a `+/-` tolerance is a magnitude and cannot be "
                    "negative; the sign is already in the operator"
                )
            if tol_unit == "%":
                form = "tolerance-percent"
                spread = +(value.copy_abs() * magnitude / Decimal(100))
                components = ((value, unit), (magnitude, "%"))
            else:
                form = "tolerance-absolute"
                if dimension_of(tol_unit) != dimension:
                    raise QuantityError(
                        f"tolerance unit {tol_unit!r} is "
                        f"{dimension_of(tol_unit)} but the value is "
                        f"{dimension}"
                    )
                spread = +(magnitude * UNITS[tol_unit][1] / UNITS[unit][1])
                components = ((value, unit), (magnitude, tol_unit))
            # The sum's operands are the value and the spread AS COMPUTED;
            # a spread far below the value needs the whole span between
            # them, which no count of the literal's own digits bounds.
            ctx.prec = _wide_enough(value, spread)
            lower, upper, nominal = +(value - spread), +(value + spread), value

        elif match.group("lo_v") is not None:
            form = "interval-bracketed"
            lo_v, lo_u = Decimal(match.group("lo_v")), match.group("lo_u")
            hi_v, hi_u = Decimal(match.group("hi_v")), match.group("hi_u")
            for bound_unit in (lo_u, hi_u):
                if dimension_of(bound_unit) != dimension:
                    raise QuantityError(
                        f"bound unit {bound_unit!r} is "
                        f"{dimension_of(bound_unit)} but the value is "
                        f"{dimension}"
                    )
            lower = +(lo_v * UNITS[lo_u][1] / UNITS[unit][1])
            upper = +(hi_v * UNITS[hi_u][1] / UNITS[unit][1])
            nominal = value
            components = ((value, unit), (lo_v, lo_u), (hi_v, hi_u))
            if not (lower <= value <= upper):
                raise QuantityError(
                    "the nominal value lies outside its own interval; an "
                    "interval that does not contain its nominal is a "
                    "transcription error, not a wide tolerance"
                )

        elif match.group("to_v") is not None:
            form = "interval-bare"
            to_v, to_u = Decimal(match.group("to_v")), match.group("to_u")
            if dimension_of(to_u) != dimension:
                raise QuantityError(
                    f"bound unit {to_u!r} is {dimension_of(to_u)} but the "
                    f"value is {dimension}"
                )
            lower = value
            upper = +(to_v * UNITS[to_u][1] / UNITS[unit][1])
            nominal = None
            components = ((value, unit), (to_v, to_u))

        else:
            form = "exact"
            lower = upper = nominal = value
            components = ((value, unit),)

        if lower > upper:
            raise QuantityError("lower bound exceeds upper bound")

    return Quantity(
        text=text,
        form=form,
        dimension=dimension,
        unit=unit,
        components=components,
        nominal=None if nominal is None else to_base(nominal, unit),
        lower=to_base(lower, unit),
        upper=to_base(upper, unit),
    )


def _ladder(dimension: str) -> list[tuple[str, Decimal]]:
    return sorted(
        ((symbol, mult) for symbol, (dim, mult) in UNITS.items()
         if dim == dimension),
        key=lambda item: item[1],
    )


def _canonical_pair(value: Decimal, unit: str) -> str:
    """One number-unit pair in normal form. Exact by construction: the only
    arithmetic is division by a power of ten under the wide context."""
    dimension, _ = UNITS[unit]
    if dimension == "temperature":
        return _plain(value) + unit
    ladder = _ladder(dimension)
    if value == 0:
        base = next(sym for sym, mult in ladder if mult == 1)
        return "0" + base
    with _exact_context(value, UNITS[unit][1]):
        base_value = +(value * UNITS[unit][1])
        chosen = None
        for symbol, mult in ladder:
            mantissa = +(base_value / mult)
            if 1 <= mantissa.copy_abs() < 1000:
                chosen = (symbol, mantissa)
                break
        if chosen is None:
            # Off the ladder's ends: below the smallest unit, or at/above
            # 1000x the largest. Nearest end keeps the spelling shortest.
            symbol, mult = (
                ladder[0]
                if base_value.copy_abs() < UNITS[ladder[0][0]][1]
                else ladder[-1]
            )
            chosen = (symbol, +(base_value / mult))
    symbol, mantissa = chosen
    return _plain(mantissa) + symbol


def normal_form(text: str) -> str:
    """The canonical spelling of a quantity literal (T3).

    Value-exact (`parse(normal_form(t)).key() == parse(t).key()`),
    idempotent, form-preserving. The conformance vectors in
    spec/conformance/ hold this function to the spec section; the formatter
    (R16) and the quantity type (R21) call it rather than reimplementing
    the rules.
    """
    quantity = parse_quantity(text)
    pairs = quantity.components
    if quantity.form == "exact":
        return _canonical_pair(*pairs[0])
    if quantity.form == "tolerance-percent":
        (value, unit), (pct, _) = pairs
        return f"{_canonical_pair(value, unit)} +/- {_plain(pct)}%"
    if quantity.form == "tolerance-absolute":
        (value, unit), (tol, tol_unit) = pairs
        return (f"{_canonical_pair(value, unit)} +/- "
                f"{_canonical_pair(tol, tol_unit)}")
    if quantity.form == "interval-bracketed":
        (value, unit), (lo, lo_u), (hi, hi_u) = pairs
        return (f"{_canonical_pair(value, unit)} "
                f"({_canonical_pair(lo, lo_u)} to "
                f"{_canonical_pair(hi, hi_u)})")
    (value, unit), (to_v, to_u) = pairs
    return f"{_canonical_pair(value, unit)} to {_canonical_pair(to_v, to_u)}"
