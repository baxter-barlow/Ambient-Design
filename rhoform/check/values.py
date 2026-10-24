"""The exact quantity and interval algebra the checks share (L1c, AMB-53).

Spec 05 section 2 is the normative text; this docstring paraphrases it.

EXACT, OVER THE RATIONALS. Every number here is a `fractions.Fraction`,
or one of the two infinities, and every operation is exact: + - * / over
the rationals is closed, so nothing rounds and no precision is chosen. An
elaborated value is an exact Decimal and converts exactly; a part
record's number is a Decimal (rhoform.partdata parses it so) and converts
exactly, `0.3` to `Fraction(3, 10)`. A float is refused, never converted:
an IR double never feeds a check. The one place a number is rounded is
display, and display rounds OUTWARD (a lower end down, an upper end up),
and only when the exact decimal does not terminate.

THE VALUES. A `Q` is a closed interval of the extended rationals that
encloses an uncertain quantity, with its dimension (an exponent vector,
`Dimension`), whether it is a reading on an offset scale (`degC`), its
nominal when it has one, and whether it is TIGHT: equal to the exact
range of what it encloses rather than a wider enclosure. Two sentinels
stand where no interval can: `UNDEFINED` (a division by exactly zero) and
`UNVERIFIED` (part data with no guaranteed statistic). Each absorbs every
operation, `UNDEFINED` over `UNVERIFIED`.

TIGHTNESS is the single-use rule (Moore): an expression in which each
uncertain operand occurs once, with no divisor containing zero, has a
natural interval extension equal to its range. So each uncertain leaf
carries a variable id (`vars`), and a result is tight when its operands
are and share no variable. `square` is a primitive because `x * x` uses
`x` twice: [-1, 2]**2 is [0, 4], [-1, 2]*[-1, 2] is [-2, 4]. An
uncertain leaf with no variable id is never tight, since nothing could
show it is used once.

THE VERDICT a containment check reaches on a measured enclosure M and a
fixed window B (`verdict`): pass iff M is inside B; fail, definitely, iff
M is outside B; fail, possibly, iff they overlap and M is tight (some
in-tolerance combination violates); otherwise incomplete, with a reason
(INCOMPLETE_REASONS). Nothing but inside ever passes, and an enclosure
built from a typ or peak figure (`from_measure(lower_bound_only=True)`)
never passes at all: it may prove a violation and says so in its
`basis`. An implicit check maps incomplete to an `undecided` coverage
row; a declared static assertion maps it to a gating error.

Nothing here reaches the IR: dimensions, rationals and intervals are
erased after checking (T3).
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import math

from .. import quantities
from ..partdata import Relative


class DimensionError(TypeError):
    """Arithmetic the dimensions forbid: adding volts to amps, a reading
    on an offset scale inside a product, any arithmetic on a level unit.
    Raised inside a check it is a checker bug, which the command line
    reports as INTERNAL (exit 2); it is never a diagnostic."""


class UnitError(ValueError):
    """A part-data unit outside the part-unit grammar (spec 05 section
    2): the measure's numbers cannot be read."""


# ---- dimensions -------------------------------------------------------------

@dataclass(frozen=True)
class Dimension:
    """An exponent vector over quantities.BASE_DIMENSIONS. `level` names a
    logarithmic unit (`dB`, `dBm`): such a value has no exponents, admits
    no arithmetic, and compares only with the identical unit, because
    converting it would be transcendental and so inexact."""

    exponents: tuple[int, int, int, int, int]
    level: str | None = None

    def __post_init__(self):
        if len(self.exponents) != len(quantities.BASE_DIMENSIONS) or not \
                all(type(e) is int for e in self.exponents):
            raise ValueError(f"{self.exponents!r} is not an exponent vector "
                             f"over {quantities.BASE_DIMENSIONS}")
        if self.level is not None and any(self.exponents):
            raise ValueError("a level unit has no exponents")

    def _plain(self, operation):
        if self.level is not None:
            raise DimensionError(
                f"{operation} of a `{self.level}` value: a level unit "
                "admits no arithmetic")

    def __mul__(self, other: "Dimension") -> "Dimension":
        self._plain("a product")
        other._plain("a product")
        return Dimension(tuple(a + b for a, b in zip(self.exponents,
                                                     other.exponents)))

    def __truediv__(self, other: "Dimension") -> "Dimension":
        self._plain("a quotient")
        other._plain("a quotient")
        return Dimension(tuple(a - b for a, b in zip(self.exponents,
                                                     other.exponents)))

    def __pow__(self, power: int) -> "Dimension":
        self._plain("a power")
        return Dimension(tuple(e * power for e in self.exponents))

    @property
    def name(self) -> str | None:
        """The dimension's word: a quantities.DIMENSIONS name,
        `dimensionless`, the level unit, or None for a derived vector no
        word names."""
        if self.level is not None:
            return self.level
        if not any(self.exponents):
            return "dimensionless"
        return _NAMES.get(self.exponents)

    def describe(self) -> str:
        """The dimension with its article, as a diagnostic says it."""
        name = self.name
        if name == "dimensionless":
            return "a dimensionless number"
        if name in ("dB", "dBm"):
            return f"a `{name}` level"
        if name is None:
            return f"a quantity of dimension {self.spelling()}"
        return ("an " if name[0] in "aeiou" else "a ") + name

    def spelling(self) -> str:
        """The vector as base dimensions, `m^2*kg*s^-3*A^-1`."""
        if self.level is not None:
            return self.level
        terms = [symbol if e == 1 else f"{symbol}^{e}"
                 for symbol, e in zip(quantities.BASE_DIMENSIONS,
                                      self.exponents) if e]
        return "*".join(terms) or "1"


_NAMES = {vector: name for name, vector in quantities.DIMENSIONS.items()}
DIMENSIONLESS = Dimension((0, 0, 0, 0, 0))


def named(name: str) -> Dimension:
    """The Dimension a word names: a quantities.DIMENSIONS name or
    `dimensionless`."""
    if name == "dimensionless":
        return DIMENSIONLESS
    return Dimension(quantities.DIMENSIONS[name])


# ---- the extended rationals -------------------------------------------------

class _Infinity:
    """One end of the extended rationals. Compares with any Fraction, and
    is never mixed with a float, so 0 * inf is a rule (0) rather than
    NaN."""

    __slots__ = ("sign",)

    def __init__(self, sign: int):
        self.sign = sign

    def __repr__(self):
        return "POS_INF" if self.sign > 0 else "NEG_INF"

    def __neg__(self):
        return NEG_INF if self.sign > 0 else POS_INF

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return hash(("infinity", self.sign))

    def __lt__(self, other):
        return self.sign < 0 and other is not self

    def __le__(self, other):
        return self.sign < 0 or other is self

    def __gt__(self, other):
        return self.sign > 0 and other is not self

    def __ge__(self, other):
        return self.sign > 0 or other is self


POS_INF = _Infinity(1)
NEG_INF = _Infinity(-1)
ZERO = Fraction(0)


def _infinite(x) -> bool:
    return isinstance(x, _Infinity)


def _sign(x) -> int:
    if _infinite(x):
        return x.sign
    return (x > 0) - (x < 0)


def _add(a, b):
    # Only like ends are ever added (lower to lower, upper to upper, or
    # lower to a negated upper), so an infinity never meets its opposite.
    if _infinite(a):
        return a
    if _infinite(b):
        return b
    return a + b


def _mul(a, b):
    if a == 0 or b == 0:
        return ZERO  # 0 * inf = 0: the convention closed intervals need
    if _infinite(a) or _infinite(b):
        return POS_INF if _sign(a) * _sign(b) > 0 else NEG_INF
    return a * b


def _over(a, b):
    """a / b for an end b that is not zero; a finite a over an infinite b
    is 0."""
    if _infinite(b):
        return ZERO if not _infinite(a) else (
            POS_INF if a.sign * b.sign > 0 else NEG_INF)
    if _infinite(a):
        return POS_INF if a.sign * _sign(b) > 0 else NEG_INF
    return a / b


def exact(value) -> Fraction:
    """A number as a Fraction, exactly: a Decimal, an int or a Fraction.
    A float or a bool is refused, and so is a non-finite Decimal."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{value!r} is not an exact number; a check never "
                        "computes from a double")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{value} is not a finite number")
        return Fraction(value)
    if isinstance(value, (int, Fraction)):
        return Fraction(value)
    raise TypeError(f"{value!r} is not a number")


# ---- intervals --------------------------------------------------------------

@dataclass(frozen=True)
class Interval:
    """A closed interval [lo, hi] of the extended rationals, never empty.
    `lo` is a Fraction or NEG_INF, `hi` a Fraction or POS_INF."""

    lo: object
    hi: object

    def __post_init__(self):
        for end in (self.lo, self.hi):
            if not (_infinite(end) or type(end) is Fraction):
                raise TypeError(f"{end!r} is not a Fraction or an infinity")
        if self.lo is POS_INF or self.hi is NEG_INF or self.lo > self.hi:
            raise ValueError(f"[{self.lo}, {self.hi}] is not an interval")

    @classmethod
    def point(cls, value) -> "Interval":
        value = exact(value)
        return cls(value, value)

    @property
    def is_point(self) -> bool:
        return self.lo == self.hi

    @property
    def bounded(self) -> bool:
        return not (_infinite(self.lo) or _infinite(self.hi))

    def contains(self, other) -> bool:
        """Whether a number, or every point of an Interval, lies inside."""
        if isinstance(other, Interval):
            return self.lo <= other.lo and other.hi <= self.hi
        return self.lo <= other <= self.hi


def _iv_neg(a: Interval) -> Interval:
    return Interval(-a.hi, -a.lo)


def _iv_add(a: Interval, b: Interval) -> Interval:
    return Interval(_add(a.lo, b.lo), _add(a.hi, b.hi))


def _iv_mul(a: Interval, b: Interval) -> Interval:
    products = [_mul(x, y) for x in (a.lo, a.hi) for y in (b.lo, b.hi)]
    return Interval(min(products), max(products))


def _iv_square(a: Interval) -> Interval:
    low, high = _mul(a.lo, a.lo), _mul(a.hi, a.hi)
    if a.lo >= 0:
        return Interval(low, high)
    if a.hi <= 0:
        return Interval(high, low)
    return Interval(ZERO, max(low, high))


def _iv_div(a: Interval, b: Interval):
    """(a / b, tight-preserving) by the six cases, or (None, False) when b
    is exactly zero (the result is UNDEFINED)."""
    c, d = b.lo, b.hi
    if not (c <= 0 <= d):  # (i) 0 is not in b
        return _iv_mul(a, Interval(_over(Fraction(1), d),
                                   _over(Fraction(1), c))), True
    if c == 0 and d == 0:  # (ii)
        return None, False
    if a.lo == 0 and a.hi == 0:  # (iii) 0 / b is 0 wherever it is defined
        return Interval(ZERO, ZERO), True
    everything = Interval(NEG_INF, POS_INF)
    if a.lo <= 0 <= a.hi:  # (iv)
        return everything, False
    if a.hi < 0:  # (v)
        if c == 0:
            return Interval(NEG_INF, _over(a.hi, d)), False
        if d == 0:
            return Interval(_over(a.hi, c), POS_INF), False
        return everything, False
    if c == 0:  # (vi) a.lo > 0
        return Interval(_over(a.lo, d), POS_INF), False
    if d == 0:
        return Interval(NEG_INF, _over(a.lo, c)), False
    return everything, False


# ---- quantities -------------------------------------------------------------

class _Sentinel:
    """A value no interval can stand for. Absorbs every operation."""

    __slots__ = ("name", "reason")

    def __init__(self, name: str, reason: str):
        self.name, self.reason = name, reason

    def __repr__(self):
        return self.name

    def _absorb(self, *_other):
        return _absorbing(self, *_other)

    __add__ = __radd__ = __sub__ = __rsub__ = _absorb
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _absorb

    def __neg__(self):
        return self


UNDEFINED = _Sentinel("UNDEFINED", "undefined-value")
UNVERIFIED = _Sentinel("UNVERIFIED", "unverified-input")


def _absorbing(*operands):
    """The sentinel an operation on `operands` yields, or None."""
    if any(op is UNDEFINED for op in operands):
        return UNDEFINED
    if any(op is UNVERIFIED for op in operands):
        return UNVERIFIED
    return None


@dataclass(frozen=True)
class Q:
    """An exact enclosure of one uncertain quantity, in base units.

    `offset` marks a reading on an offset scale (a `degC` point); the
    difference of two readings is a plain temperature. `nominal`, when
    present, lies inside the interval. `tight` says the interval is the
    exact range of what it encloses. `vars` are the variable ids of the
    uncertain leaves it was computed from. `verified` is False for an
    enclosure resting on a typ or peak figure, which may prove a violation
    but never a pass."""

    iv: Interval
    dim: Dimension
    offset: bool = False
    nominal: Fraction | None = None
    tight: bool = True
    vars: tuple = ()
    verified: bool = True

    def __post_init__(self):
        if self.nominal is not None and not self.iv.contains(self.nominal):
            raise ValueError(f"nominal {self.nominal} lies outside "
                             f"[{self.iv.lo}, {self.iv.hi}]")
        if self.offset and (self.dim != named("temperature")):
            raise ValueError("only a temperature is read on an offset scale")

    def __add__(self, other):
        return add(self, other)

    def __sub__(self, other):
        return sub(self, other)

    def __mul__(self, other):
        return mul(self, other)

    def __truediv__(self, other):
        return div(self, other)

    def __neg__(self):
        return neg(self)


def constant(value, dim: Dimension = DIMENSIONLESS, *,
             offset: bool = False) -> Q:
    """An exact value: a point, tight, with no variable."""
    value = exact(value)
    return Q(Interval(value, value), dim, offset, value)


def _leaf(iv: Interval, dim, offset, nominal, var) -> Q:
    """An uncertain input. A point is a constant and needs no variable;
    any other leaf is tight only when it has one."""
    if iv.is_point:
        return Q(iv, dim, offset, nominal)
    return Q(iv, dim, offset, nominal, var is not None,
             () if var is None else (var,))


def _vars(*operands) -> tuple:
    found = set()
    for q in operands:
        found.update(q.vars)
    return tuple(sorted(found, key=repr))


def _independent(a: Q, b: Q) -> bool:
    return not set(a.vars) & set(b.vars)


def _same(a: Q, b: Q, operation: str) -> None:
    if a.dim != b.dim:
        raise DimensionError(f"{operation} of {a.dim.describe()} and "
                             f"{b.dim.describe()}")


def _point_op(op, *nominals):
    if any(n is None for n in nominals):
        return None
    return op(*nominals)


def add(a, b):
    """a + b. A reading plus a difference is a reading; two readings
    cannot be added."""
    sentinel = _absorbing(a, b)
    if sentinel is not None:
        return sentinel
    _same(a, b, "a sum")
    a.dim._plain("a sum")
    if a.offset and b.offset:
        raise DimensionError("a sum of two offset-scale readings; only "
                             "their difference is a quantity")
    return Q(_iv_add(a.iv, b.iv), a.dim, a.offset or b.offset,
             _point_op(lambda x, y: x + y, a.nominal, b.nominal),
             a.tight and b.tight and _independent(a, b), _vars(a, b),
             a.verified and b.verified)


def neg(a):
    """-a. A reading on an offset scale has no negation."""
    if isinstance(a, _Sentinel):
        return a
    a.dim._plain("a negation")
    if a.offset:
        raise DimensionError("a negated offset-scale reading")
    return Q(_iv_neg(a.iv), a.dim, False,
             _point_op(lambda x: -x, a.nominal), a.tight, a.vars, a.verified)


def sub(a, b):
    """a - b. Two readings give their difference; a reading minus a
    difference is a reading; a difference minus a reading is refused."""
    sentinel = _absorbing(a, b)
    if sentinel is not None:
        return sentinel
    _same(a, b, "a difference")
    a.dim._plain("a difference")
    if b.offset and not a.offset:
        raise DimensionError("a difference minus an offset-scale reading")
    return Q(_iv_add(a.iv, _iv_neg(b.iv)), a.dim, a.offset and not b.offset,
             _point_op(lambda x, y: x - y, a.nominal, b.nominal),
             a.tight and b.tight and _independent(a, b), _vars(a, b),
             a.verified and b.verified)


def _scalar(a, b, operation):
    for q in (a, b):
        if q.offset:
            raise DimensionError(f"an offset-scale reading inside "
                                 f"{operation}")


def mul(a, b):
    """a * b: exponents add."""
    sentinel = _absorbing(a, b)
    if sentinel is not None:
        return sentinel
    _scalar(a, b, "a product")
    return Q(_iv_mul(a.iv, b.iv), a.dim * b.dim, False,
             _point_op(lambda x, y: x * y, a.nominal, b.nominal),
             a.tight and b.tight and _independent(a, b), _vars(a, b),
             a.verified and b.verified)


def div(a, b):
    """a / b by the six division cases: UNDEFINED when b is exactly zero,
    and an unbounded, non-tight result when b contains zero (except 0 / b,
    which is 0)."""
    sentinel = _absorbing(a, b)
    if sentinel is not None:
        return sentinel
    _scalar(a, b, "a quotient")
    dim = a.dim / b.dim
    iv, keeps = _iv_div(a.iv, b.iv)
    if iv is None:
        return UNDEFINED
    nominal = None
    if a.nominal is not None and b.nominal is not None and b.nominal != 0:
        nominal = a.nominal / b.nominal
    return Q(iv, dim, False, nominal,
             keeps and a.tight and b.tight and _independent(a, b),
             _vars(a, b), a.verified and b.verified)


def square(a):
    """a**2 as one use of a: tight when a is, unlike a * a."""
    if isinstance(a, _Sentinel):
        return a
    _scalar(a, a, "a square")
    return Q(_iv_square(a.iv), a.dim ** 2, False,
             _point_op(lambda x: x * x, a.nominal), a.tight, a.vars,
             a.verified)


def scale(a, factor):
    """a times an exact dimensionless constant."""
    if isinstance(a, _Sentinel):
        return a
    return mul(a, constant(factor))


def hull(a, b):
    """The least interval holding both: what either of two states may be.
    Tight when both are and they meet, so every point of the hull is a
    value one of them takes."""
    sentinel = _absorbing(a, b)
    if sentinel is not None:
        return sentinel
    _same(a, b, "a hull")
    if a.offset != b.offset:
        raise DimensionError("a hull of a reading and a difference")
    meet = a.iv.lo <= b.iv.hi and b.iv.lo <= a.iv.hi
    return Q(Interval(min(a.iv.lo, b.iv.lo), max(a.iv.hi, b.iv.hi)), a.dim,
             a.offset, a.nominal if a.nominal == b.nominal else None,
             a.tight and b.tight and meet, _vars(a, b),
             a.verified and b.verified)


def intersect(a, b):
    """What both enclosures allow, or None when they are disjoint. It is
    tight only when one holds the other, and is then that one."""
    sentinel = _absorbing(a, b)
    if sentinel is not None:
        return sentinel
    _same(a, b, "an intersection")
    if a.offset != b.offset:
        raise DimensionError("an intersection of a reading and a difference")
    if a.iv.lo > b.iv.hi or b.iv.lo > a.iv.hi:
        return None
    if b.iv.contains(a.iv):
        return a
    if a.iv.contains(b.iv):
        return b
    iv = Interval(max(a.iv.lo, b.iv.lo), min(a.iv.hi, b.iv.hi))
    nominal = next((n for n in (a.nominal, b.nominal)
                    if n is not None and iv.contains(n)), None)
    return Q(iv, a.dim, a.offset, nominal, False, _vars(a, b),
             a.verified and b.verified)


# ---- relations and the verdict ----------------------------------------------

RELATIONS = ("inside", "outside", "overlaps")
OUTCOMES = ("pass", "fail", "incomplete")
# Why a verdict is incomplete. Spec 05 section 2 restates the list.
INCOMPLETE_REASONS = ("interval-overestimate", "undefined-value",
                      "unverified-input")


def _comparable(a: Q, b: Q) -> None:
    _same(a, b, "a comparison")
    if a.offset != b.offset:
        raise DimensionError("a comparison of an offset-scale reading with "
                             "a difference")


def relate(m: Q, b: Q) -> str:
    """Where M lies against the window B: `inside` (B holds all of M),
    `outside` (no point of M is in B) or `overlaps`. Ends are closed, so
    touching is overlap."""
    _comparable(m, b)
    if b.iv.contains(m.iv):
        return "inside"
    if m.iv.hi < b.iv.lo or m.iv.lo > b.iv.hi:
        return "outside"
    return "overlaps"


def certainly_le(a: Q, b: Q) -> bool:
    """Every value of a is <= every value of b."""
    _comparable(a, b)
    return a.iv.hi <= b.iv.lo


def possibly_le(a: Q, b: Q) -> bool:
    """Some value of a is <= some value of b."""
    _comparable(a, b)
    return a.iv.lo <= b.iv.hi


def certainly_lt(a: Q, b: Q) -> bool:
    _comparable(a, b)
    return a.iv.hi < b.iv.lo


def possibly_lt(a: Q, b: Q) -> bool:
    _comparable(a, b)
    return a.iv.lo < b.iv.hi


@dataclass(frozen=True)
class Verdict:
    """A containment check's conclusion. `certainty` is `definite` or
    `possible` on a fail; `reason` is one of INCOMPLETE_REASONS on an
    incomplete; `basis` says what a fail rests on: `guaranteed` data, or a
    `lower-bound` read from a typ or peak figure."""

    outcome: str
    certainty: str | None = None
    reason: str | None = None
    basis: str | None = None

    @property
    def row_status(self) -> str:
        """The coverage-row status an implicit check records for it."""
        return {"pass": "pass", "fail": "fail",
                "incomplete": "undecided"}[self.outcome]


def verdict(m, b) -> Verdict:
    """The static verdict on the measured enclosure M against the fixed
    window B (spec 05 section 2). B's ends are the window's own: a window
    whose ends depend on another uncertain value is not fixed, and is
    checked by moving that value to the measured side."""
    sentinel = _absorbing(m, b)
    if sentinel is not None:
        return Verdict("incomplete", reason=sentinel.reason)
    if b.vars:
        raise ValueError("the window depends on an uncertain value; move it "
                         "to the measured side")
    where = relate(m, b)
    trusted = m.verified and b.verified
    if not b.verified:
        return Verdict("incomplete", reason="unverified-input")
    if where == "outside":
        return Verdict("fail", "definite",
                       basis="guaranteed" if trusted else "lower-bound")
    if not trusted:
        return Verdict("incomplete", reason="unverified-input")
    if where == "inside":
        return Verdict("pass")
    if m.tight:
        return Verdict("fail", "possible", basis="guaranteed")
    return Verdict("incomplete", reason="interval-overestimate")


# ---- conversions ------------------------------------------------------------

def _literal_unit(unit: str):
    """(Dimension, multiplier, offset) of a literal unit or `1`."""
    if unit == "1":
        return DIMENSIONLESS, Fraction(1), False
    dimension, multiplier = quantities.UNITS[unit]
    return (named(dimension), Fraction(multiplier),
            dimension in quantities.OFFSET_DIMENSIONS)


def from_quantity(quantity, var=None) -> Q:
    """An elaborated value (rhoform.elaborate.Quantity), exactly. An exact
    literal is a constant; a toleranced one is an uncertain leaf whose
    variable id `var` (say (instance path, constraint name)) makes it
    tight. The elaborated Decimals convert without loss."""
    dim, multiplier, offset = _literal_unit(quantity.unit)
    nominal = exact(quantity.value) * multiplier
    if quantity.tolerance is None:
        iv = Interval(nominal, nominal)
    else:
        low, high = quantity.tolerance
        iv = Interval(exact(low) * multiplier, exact(high) * multiplier)
    return _leaf(iv, dim, offset, nominal, var)


def from_literal(text: str, var=None) -> Q:
    """A quantity literal's value, exactly, as from_quantity reads its
    elaborated form; a bare interval has no nominal."""
    parsed = quantities.parse_quantity(text)
    offset = parsed.dimension in quantities.OFFSET_DIMENSIONS
    iv = Interval(exact(parsed.lower), exact(parsed.upper))
    nominal = None if parsed.nominal is None else exact(parsed.nominal)
    return _leaf(iv, named(parsed.dimension), offset, nominal, var)


def from_bounds(bounds) -> Q:
    """An assertion's window (rhoform.elaborate.Bounds), exactly: unit `1`
    is dimensionless and a missing end is infinite."""
    dim, multiplier, offset = _literal_unit(bounds.unit)
    low = NEG_INF if bounds.min is None else exact(bounds.min) * multiplier
    high = POS_INF if bounds.max is None else exact(bounds.max) * multiplier
    return Q(Interval(low, high), dim, offset)


# Part-data units: the literal UNITS, `1`, and these atoms (spec 05 section
# 2 restates the table). `K` is a temperature difference, `degC` inside a
# compound unit means one too, and `dB`/`dBm` are levels, opaque.
PART_ATOMS = {
    "K": ("temperature", Fraction(1), "linear"),
    "ppm": ("dimensionless", Fraction(1, 10 ** 6), "linear"),
    "min": ("time", Fraction(60), "linear"),
    "dB": (None, Fraction(1), "level"),
    "dBm": (None, Fraction(1), "level"),
}
UNIT_KINDS = ("linear", "offset", "level")


@dataclass(frozen=True)
class PartUnit:
    """A part-data unit: its dimension, the exact factor to base units,
    and its kind (UNIT_KINDS): `offset` for a `degC` reading, `level` for
    `dB`/`dBm`, `linear` for everything else."""

    dimension: Dimension
    scale: Fraction
    kind: str


def _atom(symbol: str) -> PartUnit:
    if symbol in quantities.UNITS:
        dimension, multiplier = quantities.UNITS[symbol]
        kind = "offset" if dimension in quantities.OFFSET_DIMENSIONS \
            else "linear"
        return PartUnit(named(dimension), Fraction(multiplier), kind)
    if symbol in PART_ATOMS:
        dimension, factor, kind = PART_ATOMS[symbol]
        if kind == "level":
            return PartUnit(Dimension((0, 0, 0, 0, 0), symbol), factor, kind)
        return PartUnit(named(dimension), factor, kind)
    raise UnitError(
        f"unknown part-data unit {symbol!r}; a measure's unit is `1`, an "
        "atom or `atom/atom`, its atoms the literal units plus "
        f"{', '.join(PART_ATOMS)} (spec 05 section 2)")


def parse_part_unit(unit: str) -> PartUnit:
    """A D3 Measure's unit, by the grammar `1 | atom | atom/atom`. Raises
    UnitError outside it."""
    if unit == "1":
        return PartUnit(DIMENSIONLESS, Fraction(1), "linear")
    pieces = unit.split("/")
    if len(pieces) == 1:
        return _atom(unit)
    if len(pieces) != 2 or not all(pieces):
        raise UnitError(f"part-data unit {unit!r} is not `1`, an atom or "
                        "`atom/atom`")
    top, bottom = (_atom(piece) for piece in pieces)
    if "level" in (top.kind, bottom.kind):
        raise UnitError(f"part-data unit {unit!r} divides a level unit; a "
                        "level is opaque and stands alone")
    # Inside a ratio a `degC` is a temperature difference (`degC/W`), so
    # the compound is linear whatever its parts are.
    return PartUnit(top.dimension / bottom.dimension,
                    top.scale / bottom.scale, "linear")


def _bound_value(bound, unit: PartUnit, refs) -> Q:
    """One published statistic as a Q: a number, or a relative bound
    `factor * V(reference) + offset` evaluated exactly over the
    reference's enclosure in `refs`. Raises KeyError for a reference
    `refs` does not hold: resolving it is the caller's job."""
    if not isinstance(bound, Relative):
        return constant(exact(bound) * unit.scale, unit.dimension,
                        offset=unit.kind == "offset")
    if unit.kind == "level":
        raise DimensionError("a relative bound on a level unit")
    if refs is None or bound.reference not in refs:
        raise KeyError(f"relative bound on {bound.reference!r}, which refs "
                       "does not resolve")
    reference = refs[bound.reference]
    if isinstance(reference, _Sentinel):
        return reference
    if reference.dim != unit.dimension \
            or reference.offset != (unit.kind == "offset"):
        raise DimensionError(
            f"relative bound on {bound.reference!r}: the reference is "
            f"{reference.dim.describe()}{' (a reading)' * reference.offset} "
            f"and the measure is {unit.dimension.describe()} in "
            f"`{unit.kind}` units")
    term = reference if exact(bound.factor) == 1 \
        else scale(reference, bound.factor)
    shift = exact(bound.offset) * unit.scale
    if shift == 0:
        return term
    # The offset is a magnitude even on an offset scale: a reading plus a
    # difference.
    return add(term, constant(shift, unit.dimension))


def references(measure) -> tuple[str, ...]:
    """The references a measure's relative bounds name, sorted: what
    `refs` must resolve before from_measure can read it."""
    return tuple(sorted({v.bound.reference for v in measure.values
                         if isinstance(v.bound, Relative)}))


def statistic(measure, name: str, refs=None):
    """One statistic of a rhoform.partdata.Measure (`min`, `typ`, `max`
    or `peak`) as a Q, exactly, whatever it guarantees; None when the
    measure does not publish it."""
    value = measure.get(name)
    if value is None:
        return None
    return _bound_value(value.bound, parse_part_unit(measure.unit), refs)


def from_measure(measure, refs=None, *, var=None, lower_bound_only=False):
    """What a rhoform.partdata.Measure guarantees about its quantity: the
    enclosure [min, max] of its GUARANTEED statistics alone, a missing end
    infinite. A typ or a peak is never promoted to a limit, so a measure
    with no guaranteed statistic is UNVERIFIED.

    With `lower_bound_only` such a measure reads instead as [the greater
    of its typ and peak, +inf): the worst case is at least what a typical
    part does, so the enclosure can prove a limit exceeded, but it is
    unverified and never passes (amendment, budgets). A relative bound is
    evaluated exactly as factor * ref + offset over refs[reference] (a Q),
    at the corner that widens the enclosure; the result depends on that
    reference, and carries its variables. Conditions are not read here:
    which operating point applies is the caller's to decide."""
    unit = parse_part_unit(measure.unit)
    offset = unit.kind == "offset"
    guaranteed = {v.statistic: v.bound for v in measure.values
                  if v.guaranteed}
    low = guaranteed.get("min")
    high = guaranteed.get("max")
    if low is None and high is None:
        if not lower_bound_only:
            return UNVERIFIED
        floors = [statistic(measure, name, refs) for name in ("typ", "peak")]
        floors = [q for q in floors if q is not None]
        if not floors:
            return UNVERIFIED
        sentinel = _absorbing(*floors)
        if sentinel is not None:
            return sentinel
        return Q(Interval(max(q.iv.lo for q in floors), POS_INF),
                 unit.dimension, offset, None, False, _vars(*floors), False)
    ends = [None if raw is None else _bound_value(raw, unit, refs)
            for raw in (low, high)]
    sentinel = _absorbing(*(q for q in ends if q is not None))
    if sentinel is not None:
        return sentinel
    low_q, high_q = ends
    lo = NEG_INF if low_q is None else low_q.iv.lo
    hi = POS_INF if high_q is None else high_q.iv.hi
    if lo > hi:
        raise ValueError(f"{measure.pointer}: its guaranteed min exceeds "
                         "its guaranteed max")
    iv = Interval(lo, hi)
    # The typ, where it is one exact number inside the enclosure, is the
    # nominal: a centre, never a limit.
    typ = measure.get("typ")
    nominal = None
    if typ is not None and (not isinstance(typ.bound, Relative)
                            or (refs or {}).get(typ.bound.reference)):
        typical = _bound_value(typ.bound, unit, refs)
        if isinstance(typical, Q) and typical.iv.is_point \
                and iv.contains(typical.iv.lo):
            nominal = typical.iv.lo
    depends = _vars(*(q for q in ends if q is not None))
    fixed = all(q is not None and q.iv.is_point for q in ends)
    own = () if var is None or iv.is_point else (var,)
    tight = fixed and (iv.is_point or var is not None)
    return Q(iv, unit.dimension, offset, nominal, tight,
             tuple(sorted(set(depends) | set(own), key=repr)))


# ---- display ----------------------------------------------------------------

# Significant digits a non-terminating end keeps, rounded outward.
DISPLAY_DIGITS = 6


def _decimal(value: Fraction) -> str | None:
    """The minimal decimal spelling of a terminating Fraction, else None."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return None
    places = max(twos, fives)
    digits = abs(value.numerator) * 10 ** places // value.denominator
    text = str(digits).rjust(places + 1, "0")
    whole, fraction = (text[:-places], text[-places:]) if places \
        else (text, "")
    fraction = fraction.rstrip("0")
    sign = "-" if value < 0 else ""
    return sign + whole + ("." + fraction if fraction else "")


def _outward(value: Fraction, up: bool) -> Fraction:
    """`value` rounded to DISPLAY_DIGITS significant digits, up or down."""
    magnitude = abs(value)
    exponent = len(str(magnitude.numerator)) - len(str(magnitude.denominator))
    if Fraction(10) ** exponent > magnitude:
        exponent -= 1
    if Fraction(10) ** (exponent + 1) <= magnitude:
        exponent += 1
    step = Fraction(10) ** (DISPLAY_DIGITS - 1 - exponent)
    scaled = value * step
    return Fraction(math.ceil(scaled) if up else math.floor(scaled)) / step


def _end(value, dim: Dimension, offset: bool, up: bool) -> str:
    if _infinite(value):
        return "+inf" if value.sign > 0 else "-inf"
    text = _decimal(value)
    if text is None:
        text = _decimal(_outward(value, up))
    name = dim.name
    if name == "dimensionless":
        return text
    if name in ("dB", "dBm"):
        return text + name
    if name == "temperature" and not offset:
        return text + "K"
    if name in quantities.DIMENSIONS:
        base = next(symbol for symbol, (dimension, multiplier)
                    in quantities.UNITS.items()
                    if dimension == name and multiplier == 1)
        return quantities.normal_form(text + base)
    return f"{text} {dim.spelling()}"


def display(q: Q) -> tuple[str, str]:
    """(lower, upper) as normal-form strings: exact where the decimal
    terminates, otherwise rounded outward to DISPLAY_DIGITS significant
    digits, so the shown interval always holds the exact one."""
    if isinstance(q, _Sentinel):
        raise TypeError(f"{q!r} has no interval to display")
    return (_end(q.iv.lo, q.dim, q.offset, False),
            _end(q.iv.hi, q.dim, q.offset, True))


def params(name: str, q: Q) -> dict:
    """A quantity as diagnostic params: `<name>_min` and `<name>_max`,
    normal-form strings, never JSON numbers."""
    low, high = display(q)
    return {f"{name}_min": low, f"{name}_max": high}


# ---- the tables spec 05 section 2 restates ----------------------------------

def dimension_rows() -> tuple:
    """(name, m, kg, s, A, K) for every dimension, as spec 05 lists them."""
    return tuple((name,) + vector
                 for name, vector in quantities.DIMENSIONS.items())


def atom_rows() -> tuple:
    """(atom, dimension, factor, kind) for every part-unit atom beyond the
    literal units."""
    return tuple((atom, dimension or "level", str(factor), kind)
                 for atom, (dimension, factor, kind) in PART_ATOMS.items())
