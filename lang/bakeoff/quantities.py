"""The shared quantity mini-language.

Every arm of the bake-off parses and prints dimensioned literals with THIS
module. That is a deliberate constraint on the experiment, not an accident of
implementation: T3 already settles literals (value-exact, canonical SI normal
form) and T4 already settles the tolerance/interval value kind, so literal
spelling is not one of the axes §8-Q1 is choosing between. Letting each
candidate spell `100kohm` its own way would charge one of them tokens for a
decision the requirements have already made, and the resulting difference
would look like a grammar difference.

EXACT DECIMALS, NEVER FLOATS. `0.1` is not representable as an IEEE double,
and an assertion window or a tolerance band is exactly where that stops being
a rounding curiosity and starts being a wrong answer. Literal text is
preserved verbatim and all arithmetic runs through `decimal.Decimal` in a
local context, so `560ohm +/- 1%` is 554.4 to 565.6 and not
554.4000000000000341.

COMPARISON IS DIMENSIONAL, PRINTING IS VERBATIM. `100kohm` and `100000ohm`
are the same quantity and compare equal; the text each was written with is
kept for rendering. Choosing which of the two the formatter should emit is
the T3 normal form, which belongs to R21/R16 — this module deliberately does
not decide it.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext

# Unit table: symbol -> (dimension, multiplier to the dimension's base unit).
#
# CLOSED ON PURPOSE. An unknown unit is an error rather than a pass-through:
# a typo like "kOhm" or "uf" would otherwise sail through the model loader and
# silently become its own dimension, so two designs that differ by a typo
# would compare as legitimately different rather than as one being wrong.
# Multipliers are exact powers of ten, so normalization never rounds.
_UNITS: dict[str, tuple[str, Decimal]] = {
    "1": ("dimensionless", Decimal(1)),
    # Resistance. Note mohm (milli) vs Mohm (mega): the case carries three
    # orders of magnitude apiece, which is why the table is case-sensitive.
    "mohm": ("resistance", Decimal("1e-3")),
    "ohm": ("resistance", Decimal(1)),
    "kohm": ("resistance", Decimal("1e3")),
    "Mohm": ("resistance", Decimal("1e6")),
    # Capacitance.
    "pF": ("capacitance", Decimal("1e-12")),
    "nF": ("capacitance", Decimal("1e-9")),
    "uF": ("capacitance", Decimal("1e-6")),
    "mF": ("capacitance", Decimal("1e-3")),
    "F": ("capacitance", Decimal(1)),
    # Inductance.
    "nH": ("inductance", Decimal("1e-9")),
    "uH": ("inductance", Decimal("1e-6")),
    "mH": ("inductance", Decimal("1e-3")),
    "H": ("inductance", Decimal(1)),
    # Voltage.
    "uV": ("voltage", Decimal("1e-6")),
    "mV": ("voltage", Decimal("1e-3")),
    "V": ("voltage", Decimal(1)),
    "kV": ("voltage", Decimal("1e3")),
    # Current.
    "nA": ("current", Decimal("1e-9")),
    "uA": ("current", Decimal("1e-6")),
    "mA": ("current", Decimal("1e-3")),
    "A": ("current", Decimal(1)),
    # Power.
    "uW": ("power", Decimal("1e-6")),
    "mW": ("power", Decimal("1e-3")),
    "W": ("power", Decimal(1)),
    # Frequency.
    "Hz": ("frequency", Decimal(1)),
    "kHz": ("frequency", Decimal("1e3")),
    "MHz": ("frequency", Decimal("1e6")),
    # Time.
    "ns": ("time", Decimal("1e-9")),
    "us": ("time", Decimal("1e-6")),
    "ms": ("time", Decimal("1e-3")),
    "s": ("time", Decimal(1)),
    # Length.
    "um": ("length", Decimal("1e-6")),
    "mm": ("length", Decimal("1e-3")),
    "m": ("length", Decimal(1)),
    # Temperature. Celsius is an OFFSET scale, so it gets multiplier 1 and its
    # own dimension and is never converted to anything: scaling a temperature
    # by a power of ten is meaningless, and the way to make that mistake
    # unrepresentable is to give the table nowhere to scale it to.
    "degC": ("temperature", Decimal(1)),
}

_NUM = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
_UNIT = r"[A-Za-z][A-Za-z0-9/]*"

# The five T4 forms, in one anchored expression. Order matters inside the
# alternation only for readability; the branches are mutually exclusive.
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

# 60 significant digits is far more than any datasheet figure needs and far
# less than anything here can exhaust; it exists so a tolerance computation
# cannot silently round at the default 28.
_PRECISION = 60


class QuantityError(ValueError):
    """A literal is not a well-formed quantity, or its units do not agree."""


@dataclass(frozen=True)
class Quantity:
    """A dimensioned literal with an optional tolerance or interval.

    `text` is exactly what was written. `nominal` is None for the bare
    interval form (`3.0V to 3.6V`), which names a range with no centre — a
    real distinction that a representation forced to invent a midpoint would
    lose.
    """

    text: str
    unit: str
    dimension: str
    nominal: Decimal | None
    lower: Decimal
    upper: Decimal

    def key(self) -> tuple:
        """Dimensional identity, for comparison and canonical ordering.

        Bounds are converted to the dimension's base unit first, so two
        literals with the same physical meaning produce the same key whatever
        unit they were written in. That is what makes the IR anchor check
        possible at all: the IR stores `100000 ohm` where the model stores
        `100kohm`, and a key over the authored numbers would call those two
        different quantities.
        """
        return (
            self.dimension,
            None if self.nominal is None else _norm(to_base(self.nominal, self.unit)),
            _norm(to_base(self.lower, self.unit)),
            _norm(to_base(self.upper, self.unit)),
        )

    def is_exact(self) -> bool:
        return self.nominal is not None and self.lower == self.upper

    def __eq__(self, other) -> bool:
        return isinstance(other, Quantity) and self.key() == other.key()

    def __hash__(self) -> int:
        return hash(self.key())

    def __str__(self) -> str:
        return self.text


def _norm(value: Decimal) -> str:
    """Canonical string for an exact decimal, so equal values hash equal.

    `Decimal("1.0") == Decimal("1")` is true but they carry different
    exponents, and dataclass/tuple comparison of Decimals would honour the
    equality while a dict keyed on them would not. Normalizing to a string
    removes the distinction entirely. `normalize()` on a zero yields "0E+n",
    so zero is special-cased to a plain "0".
    """
    if value == 0:
        return "0"
    # `format(..., "f")` always renders plain digits, so 1E+5 and 100000 —
    # equal Decimals with different exponents — land on the same string.
    return format(value.normalize(), "f")


def unit_dimension(unit: str) -> str:
    """Dimension of a unit symbol, or raise. Also the unit-existence check."""
    try:
        return _UNITS[unit][0]
    except KeyError:
        raise QuantityError(
            f"unknown unit {unit!r}. The unit table in lang/bakeoff/quantities.py "
            "is closed: add the unit there deliberately rather than letting a "
            "typo become its own dimension."
        ) from None


def known_units() -> tuple[str, ...]:
    return tuple(sorted(_UNITS))


def _scale(unit: str) -> tuple[str, Decimal]:
    try:
        return _UNITS[unit]
    except KeyError:
        raise QuantityError(
            f"unknown unit {unit!r}. The unit table in lang/bakeoff/quantities.py "
            "is closed: add the unit there deliberately rather than letting a "
            "typo become its own dimension."
        ) from None


def to_base(value: Decimal, unit: str) -> Decimal:
    """Value expressed in its dimension's base unit, exactly."""
    dimension, multiplier = _scale(unit)
    if dimension == "temperature":
        return value
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return +(value * multiplier)


def parse_quantity(text: str) -> Quantity:
    """Parse one literal of the shared quantity mini-language."""
    match = _QUANTITY_RE.match(text)
    if match is None:
        raise QuantityError(
            f"{text!r} is not a quantity. Accepted forms: `100kohm`, "
            "`100kohm +/- 1%`, `2.0V +/- 0.2V`, `9.5mA (8.0mA to 10.5mA)`, "
            "`3.0V to 3.6V`. ASCII only, no exponent notation, and exactly "
            "one space either side of `+/-` and `to`."
        )

    unit = match.group("unit")
    dimension, _ = _scale(unit)
    value = Decimal(match.group("value"))

    with localcontext() as ctx:
        ctx.prec = _PRECISION

        if match.group("tol") is not None:
            tol_unit = match.group("tol_unit")
            magnitude = Decimal(match.group("tol"))
            if magnitude < 0:
                raise QuantityError(
                    f"{text!r}: a `+/-` tolerance is a magnitude and cannot be "
                    "negative; the sign is already in the operator."
                )
            if tol_unit == "%":
                spread = +(value.copy_abs() * magnitude / Decimal(100))
            else:
                tol_dimension, tol_multiplier = _scale(tol_unit)
                if tol_dimension != dimension:
                    raise QuantityError(
                        f"{text!r}: tolerance unit {tol_unit!r} is "
                        f"{tol_dimension} but the value is {dimension}."
                    )
                # Express the tolerance in the value's own unit before adding,
                # so `1V +/- 50mV` is 0.95..1.05 V and not 1 +/- 50.
                spread = +(magnitude * tol_multiplier / _scale(unit)[1])
            lower, upper = +(value - spread), +(value + spread)
            nominal = value

        elif match.group("lo_v") is not None:
            lower = _convert(match.group("lo_v"), match.group("lo_u"), unit, dimension, text)
            upper = _convert(match.group("hi_v"), match.group("hi_u"), unit, dimension, text)
            nominal = value
            if not (lower <= value <= upper):
                raise QuantityError(
                    f"{text!r}: the nominal value lies outside its own interval. "
                    "An interval that does not contain its nominal is a "
                    "transcription error, not a wide tolerance."
                )

        elif match.group("to_v") is not None:
            lower = value
            upper = _convert(match.group("to_v"), match.group("to_u"), unit, dimension, text)
            nominal = None

        else:
            lower = upper = nominal = value

        if lower > upper:
            raise QuantityError(
                f"{text!r}: lower bound exceeds upper bound."
            )

    return Quantity(
        text=text,
        unit=unit,
        dimension=dimension,
        nominal=nominal,
        lower=lower,
        upper=upper,
    )


def _convert(
    raw: str, from_unit: str, to_unit: str, dimension: str, text: str
) -> Decimal:
    if _scale(from_unit)[0] != dimension:
        raise QuantityError(
            f"{text!r}: bound unit {from_unit!r} is {_scale(from_unit)[0]} "
            f"but the value is {dimension}."
        )
    return +(Decimal(raw) * _scale(from_unit)[1] / _scale(to_unit)[1])


def quantity_from_ir(value: float | int | str, unit: str, tolerance: dict | None) -> Quantity:
    """Build a Quantity from an IR-shaped `{value, unit, tolerance}` triple.

    Used only by the anchor check, which has to compare this model against a
    document written in the IR's representation. JSON numbers arrive as
    Python floats, so they are routed through `repr` before Decimal: a float
    parsed straight into Decimal expands to its full binary expansion
    (554.4 becomes 554.40000000000003410605131648480892181396484375) and
    would never compare equal to the model's exact 554.4.
    """
    dimension, _ = _scale(unit)
    nominal = Decimal(str(value))
    if tolerance is None:
        lower = upper = nominal
    else:
        lower = Decimal(str(tolerance["min"]))
        upper = Decimal(str(tolerance["max"]))
    return Quantity(
        text=f"{value}{unit}",
        unit=unit,
        dimension=dimension,
        nominal=nominal,
        lower=lower,
        upper=upper,
    )


def base_bounds(quantity: Quantity) -> tuple[Decimal, Decimal]:
    """(lower, upper) in the dimension's base unit."""
    return to_base(quantity.lower, quantity.unit), to_base(quantity.upper, quantity.unit)
