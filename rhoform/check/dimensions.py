"""T3/T4 dimensions and the exact-value lint (L1c, AMB-53): pass 2.

Three checks over the elaborated values, read exactly through
rhoform/check/values.py (spec 05 section 2):

  - RHO3202: a part constraint whose name is in CONSTRAINT_VOCABULARY holds
    a value of another dimension (`resistance = 10uF`, or a string);
  - RHO3203: an assertion's bound has a dimension its measurement does not
    admit (MEASUREMENT_DIMENSIONS: `operating_point(V) within 1W to 2W`);
  - RHO3201, a warning: a `part abstract` holds an exact-FORM value on a
    nominal-valued vocabulary name (`resistance = 10kohm`). Its form is the
    authored one (ConstraintSite.form), never the width of the interval,
    so `0ohm +/- 5%` is not exact; a rating or a limit is exact by nature
    and is never flagged. Its values are the evaluated ones in normal
    form, so instances given different values through one parameter stay
    apart.

A quantity-valued constraint whose name the vocabulary does not hold is
not dimension-checked. That is an inherent limit of a closed vocabulary,
so it is a `not-run` coverage row, never a diagnostic. Each finding has
its `fail` row, and none of this pass's rows is actionable.

The pass sets `analysis.values`: every quantity-valued constraint and
every assertion window it found well-typed, as exact enclosures, so a
later pass reads them without converting again, and never one it
reported (the earliest-pass rule).
"""

from dataclasses import dataclass, field

from .. import quantities
from ..codeset import quantities as quantities_codes
from ..diagnostics import Edit, FixIt, Span
from ..elaborate import Quantity
from . import values

NAME = "dimensions"
OWNER = "quantities"
IMPLEMENTED = True

# Each part-constraint name the checker knows: (its dimension, what kind of
# value it is). A `nominal` is a target value a real part only approaches;
# `at_least` and `at_most` are a rating or a limit the part must meet, and
# are informational until part resolution (R28) reads them. Spec 05
# section 2 restates the table.
CONSTRAINT_VOCABULARY = {
    "resistance": ("resistance", "nominal"),
    "capacitance": ("capacitance", "nominal"),
    "inductance": ("inductance", "nominal"),
    "reference_voltage": ("voltage", "nominal"),
    "voltage_rating": ("voltage", "at_least"),
    "supply_max": ("voltage", "at_least"),
    "vds_max": ("voltage", "at_least"),
    "power_rating": ("power", "at_least"),
    "rms_current": ("current", "at_least"),
    "saturation_current": ("current", "at_least"),
    "dcr_max": ("resistance", "at_most"),
    "rds_on_max": ("resistance", "at_most"),
}
CONSTRAINT_KINDS = ("nominal", "at_least", "at_most")

# The dimensions each measurement kind's bound may have (decision D22), in
# the order of the grammar's measurement_kind vocabulary, which a test
# holds this to. Spec 05 section 2 restates the table.
MEASUREMENT_DIMENSIONS = {
    "operating_point": ("voltage", "current"),
    "ripple": ("voltage", "current"),
    "frequency": ("frequency",),
    "period": ("time",),
    "duty_cycle": ("dimensionless",),
    "gain": ("dimensionless",),
    "bandwidth": ("frequency",),
    "rise_time": ("time",),
    "fall_time": ("time",),
    "prop_delay": ("time",),
    "settling_time": ("time",),
    "overshoot": ("dimensionless", "voltage"),
    "power_avg": ("power",),
    "power_rms": ("power",),
    "efficiency": ("dimensionless",),
}

# The coverage rows the pass writes, as (status, reason). None is
# actionable: a finding carries a `fail`, and a name outside the closed
# vocabulary is an inherent limit. Spec 05 section 2 restates the table.
ROWS = (
    ("fail", "constraint-dimension-mismatch"),
    ("fail", "exact-part-constraint"),
    ("fail", "bound-dimension-mismatch"),
    ("not-run", "constraint-outside-vocabulary"),
)


@dataclass
class ValuesAnalysis:
    """What the pass concluded: each well-typed quantity constraint, by
    (instance path, name), and each well-typed assertion window, by
    assertion path, as exact enclosures. A constraint's variable id is
    (instance path, name): each physical part realizes its tolerance on
    its own."""

    constraints: dict = field(default_factory=dict)
    windows: dict = field(default_factory=dict)

    def constraint(self, path: str, name: str):
        """The enclosure of one constraint, or None: not a quantity, or
        reported by this pass."""
        return self.constraints.get((path, name))

    def window(self, assertion: str):
        """An assertion's bound as a window, or None when reported."""
        return self.windows.get(assertion)


def _text(model, span) -> str:
    """The source text a span covers, as the author wrote it."""
    data = next(f.data for f in model.design.files if f.path == span.file)
    return data[span.byte_start:span.byte_end].decode("utf-8")


def _normal(value: Quantity) -> str:
    """An exact elaborated value in normal form (spec 05 section 2), the
    value a reference evaluates to rather than its name."""
    return quantities.normal_form(format(value.value, "f") + value.unit)


def _found(value) -> str:
    """What a constraint value is, as a diagnostic says it."""
    if isinstance(value, Quantity):
        return values.from_quantity(value).dim.describe()
    if isinstance(value, bool):
        return "a bool"
    if isinstance(value, int):
        return "an int"
    return "a string"


def _either(dimensions) -> str:
    return " or ".join(values.named(name).describe() for name in dimensions)


def _after(span) -> Span:
    """The insertion point just past a one-line span."""
    return Span(span.file, span.byte_end, span.byte_end, span.line_end,
                span.col_end, span.line_end, span.col_end)


def _constraints(model, found, report):
    for path in model.components:
        part = model.instances[path].part
        if part is None:
            continue
        mismatched, exact, unchecked = [], [], []
        for name in sorted(part.constraints):
            site = model.constraint(path, name)
            quantity = isinstance(site.value, Quantity)
            known = CONSTRAINT_VOCABULARY.get(name)
            q = values.from_quantity(site.value, var=(path, name)) \
                if quantity else None
            if known is None:
                if quantity:
                    unchecked.append(name)
                    found.constraints[(path, name)] = q
                continue
            dimension, kind = known
            if q is None or q.dim != values.named(dimension):
                mismatched.append((name, site, dimension))
                continue
            found.constraints[(path, name)] = q
            if kind == "nominal" and part.binding == "abstract" \
                    and site.form == "exact":
                exact.append((name, site))
        if mismatched:
            report.finding(
                "RHO3202",
                {"constraints": [name for name, _site, _dim in mismatched],
                 "values": [_text(model, site.span)
                            for _name, site, _dim in mismatched],
                 "found": [_found(site.value)
                           for _name, site, _dim in mismatched],
                 "expected": [values.named(dim).describe()
                              for _name, _site, dim in mismatched]},
                entity=path, primary=mismatched[0][1].span,
                secondary=tuple((site.span, f"`{name}` too")
                                for name, site, _dim in mismatched[1:]))
            report.row(path, "fail", "constraint-dimension-mismatch",
                       detail={"constraints": [name for name, _site, _dim
                                               in mismatched]})
        if exact:
            literal = [site for _name, site in exact
                       if site.origin == "literal"]
            fixits = (FixIt(
                "state the tolerance the design accepts",
                "has-placeholders",
                tuple(Edit(_after(site.span), " +/- <tolerance>")
                      for site in literal),
                ("tolerance",)),) if literal else ()
            report.finding(
                "RHO3201",
                {"constraints": [name for name, _site in exact],
                 "values": [_normal(site.value) for _name, site in exact]},
                entity=path, primary=exact[0][1].span,
                secondary=tuple((site.span, f"`{name}` too")
                                for name, site in exact[1:]),
                fixits=fixits)
            report.row(path, "fail", "exact-part-constraint",
                       detail={"constraints": [name for name, _site
                                               in exact]})
        if unchecked:
            report.row(path, "not-run", "constraint-outside-vocabulary",
                       detail={"constraints": unchecked})


def _bounds(model, found, report):
    for path, assertion in model.assertions.items():
        window = values.from_bounds(assertion.bounds)
        allowed = MEASUREMENT_DIMENSIONS[assertion.measurement]
        if window.dim.name in allowed:
            found.windows[path] = window
            continue
        kind = assertion.measurement
        report.finding(
            "RHO3203",
            {"value": _text(model, assertion.bound_span),
             "found": window.dim.describe(),
             "context": ("the bound of an" if kind[0] in "aeiou"
                         else "the bound of a") + f" `{kind}` assertion",
             "expected": _either(allowed)},
            entity=path, primary=assertion.bound_span)
        report.row(path, "fail", "bound-dimension-mismatch")


def run(model, analysis, report):
    """Pass 2: constraint and bound dimensions, then the exact-value lint
    (spec 05 section 2)."""
    analysis.values = ValuesAnalysis()
    _constraints(model, analysis.values, report)
    _bounds(model, analysis.values, report)


# ---- the tables spec 05 section 2 restates ----------------------------------

def vocabulary_rows() -> tuple:
    """(name, dimension, kind) for every vocabulary name."""
    return tuple((name,) + entry
                 for name, entry in CONSTRAINT_VOCABULARY.items())


def measurement_rows() -> tuple:
    """(measurement kind, the dimensions its bound may have)."""
    return tuple((kind, ", ".join(allowed))
                 for kind, allowed in MEASUREMENT_DIMENSIONS.items())


def code_rows() -> tuple:
    """(code, slug, severity) for every code of the pass's owner."""
    return tuple((entry.code, entry.slug, entry.severity)
                 for entry in quantities_codes.CODES)
