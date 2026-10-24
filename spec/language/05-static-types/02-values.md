# 05 — Static types and domains: 2 — Values and dimensions

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

This section specifies how the check stage reads a quantity (T3, T4):
the dimension of every value a check reads, the exact interval algebra
over the elaborated values, the relations and the verdict a containment
check reaches, how part data becomes an interval, and the `dimensions`
pass — the dimension a part constraint's name and an assertion's
measurement require, and the exact-value lint on part constraints.
[Section 1](../05-static-types.md#1-the-checking-model) is the model it
plugs into. The reference implementation is `rhoform/check/values.py`
(the algebra, which every check shares) and `rhoform/check/dimensions.py`
(the pass). Its codes are the `quantities` owner's range, RHO3201–RHO3299,
and its pass is `dimensions`, the second the stage runs.

Literals themselves — their five forms, their exact decimal meaning and
their normal form — are [03 — Literals](../03-literals.md)'s, and this
section re-decides none of it.

## 2.1 Dimensions

A dimension is a vector of integer exponents over the SI base dimensions
length (m), mass (kg), time (s), current (A) and temperature (K). Each of
the ten dimension words of 03's unit table — which are also the
`param_type` words a parameter declares — names one vector:

<!-- reconcile: rhoform.check.values:dimension_rows -->

| Dimension | m | kg | s | A | K |
|---|---|---|---|---|---|
| `resistance` | 2 | 1 | -3 | -2 | 0 |
| `capacitance` | -2 | -1 | 4 | 2 | 0 |
| `inductance` | 2 | 1 | -2 | -2 | 0 |
| `voltage` | 2 | 1 | -3 | -1 | 0 |
| `current` | 0 | 0 | 0 | 1 | 0 |
| `power` | 2 | 1 | -3 | 0 | 0 |
| `frequency` | 0 | 0 | -1 | 0 | 0 |
| `time` | 0 | 0 | 1 | 0 | 0 |
| `length` | 1 | 0 | 0 | 0 | 0 |
| `temperature` | 0 | 0 | 0 | 0 | 1 |

The zero vector is **dimensionless**: an assertion bound written as bare
numbers (unit `1` in the elaborated design) is dimensionless. A product
adds exponents and a quotient subtracts them, so a resistance times a
capacitance is a time and a voltage over a resistance is a current. A
vector no word names is still a dimension.

**The offset scale.** A `degC` value is a *reading* against an arbitrary
zero, not a magnitude. Two readings have a difference, which is a plain
temperature (spelled `K` where it is shown); a reading plus or minus a
difference is a reading. Two readings have no sum, a reading has no
negation, and a reading inside a product, a quotient or a square is an
error. Comparing a reading with a difference is an error.

**Levels.** `dB` and `dBm` (part data only, 2.6) are logarithmic: a level
admits no arithmetic and compares only with a level of the identical
unit, because converting one would be transcendental and so inexact.

Arithmetic or a comparison the dimensions forbid — adding a voltage to a
current, say — can arise only inside a checker's own rule, never from
source text, since the language has no arithmetic on values: it is a
defect of the implementation, which the reference command line reports as
`INTERNAL` with exit status 2. It is never a diagnostic and never
skipped.

## 2.2 Values

A check computes over the **extended rationals**: exact rationals plus
−∞ and +∞. Every elaborated value is an exact decimal
([04](../04-elaboration.md#quantities-and-units)) and converts to a
rational exactly; so does every number of a part record, which is read as
the decimal its text spells (`0.3` is exactly 3/10). A binary floating
point number never feeds a check, and the IR's doubles are never read
(section 1, What the stage reads).

A value is an **enclosure**: a closed interval [lo, hi] with lo ≤ hi
that holds an uncertain quantity, with its dimension, whether it is a
reading on the offset scale, and optionally a **nominal** inside it.

- An exact literal is the degenerate interval [v, v], its nominal v.
- A toleranced literal (`10kohm +/- 1%`, `2V +/- 0.2V`) and a bracketed
  one (`9.5mA (8mA to 10.5mA)`) are their bounds, their nominal the
  literal's.
- An assertion's bound is its window: `within a to b` is [a, b],
  `at least a` is [a, +∞) and `at most b` is (−∞, b].

Two values stand where no interval can: **undefined**, the quotient by
exactly zero, and **unverified**, part data that guarantees nothing
(2.6). Each absorbs every operation it takes part in; undefined absorbs
unverified.

**Erasure.** Dimensions, rationals, intervals and verdicts are the check
stage's own and are erased after checking (T3): none reaches the IR, its
source map or any hash.

## 2.3 Interval arithmetic

For enclosures a = [a1, a2] and b = [b1, b2] of matching dimension where
the operation needs one:

- a + b = [a1 + b1, a2 + b2]; a − b = [a1 − b2, a2 − b1]; −a = [−a2, −a1].
- a × b = [min, max] of the four endpoint products, with 0 × ±∞ = 0.
- a² is primitive, because a × a uses a twice: [a1², a2²] when a1 ≥ 0,
  [a2², a1²] when a2 ≤ 0, and [0, max(a1², a2²)] otherwise. So
  [−1, 2]² = [0, 4] where [−1, 2] × [−1, 2] = [−2, 4].
- A scale by an exact dimensionless constant is a product with it.
- a / b, by six cases:
  1. 0 ∉ b: a × [1/b2, 1/b1], with 1/±∞ = 0;
  2. b = [0, 0]: undefined;
  3. a = [0, 0] and b ≠ [0, 0]: [0, 0];
  4. a1 ≤ 0 ≤ a2: (−∞, +∞);
  5. a2 < 0: b = [0, d] gives (−∞, a2/d]; b = [c, 0] gives [a2/c, +∞);
     c < 0 < d gives (−∞, +∞);
  6. a1 > 0: b = [0, d] gives [a1/d, +∞); b = [c, 0] gives (−∞, a1/c];
     c < 0 < d gives (−∞, +∞).
- The hull of a and b is [min(a1, b1), max(a2, b2)], what either of two
  states may be; the intersection is [max(a1, b1), min(a2, b2)], or
  nothing when they are disjoint.

The nominal of a result is the same operation on the operands' nominals,
and absent when any is absent or the quotient's divisor nominal is zero.
Every operation is inclusion-isotonic, so the nominal lies inside the
result. There is no square root, logarithm, exponential or π in v1: each
would need a rational enclosure with outward rounding.

## 2.4 Tightness and relations

An enclosure is **tight** when it equals the exact range of the
expression it encloses, not a wider interval. By the single-use rule
(Moore), an expression in which each uncertain operand occurs at most
once, with no divisor containing zero, has an interval extension equal
to its range. So each uncertain leaf carries a variable identity, and a
result is tight exactly when its operands are tight and share no
variable, except that division cases 4–6 are never tight. An exact value
is a constant: tight, with no variable. An uncertain leaf with no
identity is never tight, since nothing shows it is used once. A hull is
tight when both states are and they meet; an intersection is tight only
when one enclosure holds the other.

Rules that need a tight result are written in single-use form. The
buck benchmark's feedback divider (R1 = 31.2 kΩ ± 1 %, R2 = 10 kΩ ± 1 %,
Vref = 800 mV ± 1 %) is the worked case: Vref × (1 + R1/R2) is tight,
[3.2141, 3.3799] V rounded outward, inside its 3.201–3.399 V window,
while the algebraically equal Vref / (R2 / (R1 + R2)) uses R2 twice and
gives [3.1984, 3.3963] V, which overlaps the window only because it
overestimates.

A measured enclosure M **relates** to a window B as one of:

<!-- reconcile: rhoform.check.values:RELATIONS -->

| Relation | When |
|---|---|
| `inside` | B1 ≤ M1 and M2 ≤ B2 |
| `outside` | M2 < B1 or M1 > B2 |
| `overlaps` | otherwise; the ends are closed, so touching overlaps |

M is *certainly* ≤ N when M2 ≤ N1 and *possibly* ≤ N when M1 ≤ N2;
certainly and possibly < compare strictly.

## 2.5 The verdict

A containment check of a measured enclosure M against a fixed window B
reaches one of three outcomes:

- **pass** iff M is inside B;
- **fail**, *definite*, iff M is outside B: no value of M is allowed;
- **fail**, *possible*, iff M overlaps B and M is tight: some combination
  of in-tolerance values is not allowed (worst-case semantics);
- otherwise **incomplete**, with one of these reasons:

<!-- reconcile: rhoform.check.values:INCOMPLETE_REASONS -->

| Reason | Meaning |
|---|---|
| `interval-overestimate` | M overlaps B and is not tight, so the overlap may be the enclosure's and not the design's |
| `undefined-value` | M or B is undefined |
| `unverified-input` | M or B rests on part data that guarantees nothing, or on a typical figure read as a lower bound (2.6) |

Nothing but inside ever passes. A window's ends are its own: a window
whose ends depend on another uncertain value (a part-data limit relative
to a supply, 2.6) is not fixed, and a check compares it by moving that
value to the measured side — `pin − factor × supply` against `offset`,
evaluated at one instant. Such a window carries that value's identity,
and so does an uncertain value given an identity of its own, which is a
measured value; the verdict refuses either as a window.

An **implicit** check (an abs-max, a rating, a crossing, a budget, a
headroom) records an incomplete verdict as an `undecided` coverage row
naming its reason; at a safety site that row is actionable (section 1,
Coverage). A **declared static assertion** that is incomplete is a gating
error unless waived
([8](08-waivers-and-static-assertions.md)).

## 2.6 Part-data quantities

A D3 Measure states published statistics: `min`, `typ`, `max` and
`peak`. Only a **guaranteed** statistic bounds a quantity: a `min` or a
`max` whose provenance is the vendor's (`datasheet-stated`,
`datasheet-derived` or `vendor-confirmed`). A `typ` or a `peak` is never
promoted to a limit, and neither is a `min` or `max` an `estimated` or
`unverified` provenance holds. So a Measure's enclosure is [its
guaranteed min, its guaranteed max], a missing end infinite; its `typ`,
when it is one exact number inside, is the nominal. A Measure with no
guaranteed statistic is **unverified**.

**Typical figures as a lower bound.** The worst case is at least what a
typical part does, so where a check needs a worst case (a budget's draw)
and a Measure guarantees nothing, its `typ` or `peak` may be read as the
enclosure [the greater of them, +∞). Such an enclosure is unverified: it
can prove a limit exceeded — a definite fail whose basis is
`lower-bound`, which the finding states — and it never passes.

**Relative bounds.** A bound `{reference, factor, offset}` is
factor × V(reference) + offset, evaluated exactly over the enclosure of
the referenced quantity (factor 1 and offset 0 when absent; the offset in
the Measure's unit). Over an uncertain reference the Measure's enclosure
takes the corner that widens it, depends on the reference, and is not
tight. It carries the reference's identity whether or not the reference
has a variable of its own, so it is never taken for a fixed window, and
it is unverified when the reference is. A reference the check cannot
resolve leaves the Measure unread; it is never guessed.

**Units.** A Measure's unit is `1`, an atom, or `atom/atom`. The atoms
are 03's literal units and these:

<!-- reconcile: rhoform.check.values:atom_rows -->

| Atom | Dimension | Factor | Kind |
|---|---|---|---|
| `K` | temperature | 1 | linear |
| `ppm` | dimensionless | 1/1000000 | linear |
| `min` | time | 60 | linear |
| `dB` | level | 1 | level |
| `dBm` | level | 1 | level |

A unit is of one of these kinds:

<!-- reconcile: rhoform.check.values:UNIT_KINDS -->

| Kind | Units |
|---|---|
| `linear` | every unit not below, and every ratio |
| `offset` | `degC` standing alone: a reading |
| `level` | `dB` and `dBm` standing alone; a level is never part of a ratio |

`K` is a temperature difference, and so is `degC` inside a ratio
(`degC/W`); `1/K` is not a unit (write `ppm/K`). A unit outside this
grammar leaves its Measure unread.

## 2.7 The dimensions pass

The pass runs second, after `parts`, over every component instance's
part constraints and every assertion, and reports three codes:

<!-- reconcile: rhoform.check.dimensions:code_rows -->

| Code | Slug | Severity |
|---|---|---|
| `RHO3201` | `exact-part-constraint` | warning |
| `RHO3202` | `constraint-dimension-mismatch` | error |
| `RHO3203` | `bound-dimension-mismatch` | error |

**Constraint dimensions.** A part constraint whose name is in the
constraint vocabulary MUST hold a quantity of that name's dimension:

<!-- reconcile: rhoform.check.dimensions:vocabulary_rows -->

| Name | Dimension | Kind |
|---|---|---|
| `resistance` | resistance | nominal |
| `capacitance` | capacitance | nominal |
| `inductance` | inductance | nominal |
| `reference_voltage` | voltage | nominal |
| `voltage_rating` | voltage | at_least |
| `supply_max` | voltage | at_least |
| `vds_max` | voltage | at_least |
| `power_rating` | power | at_least |
| `rms_current` | current | at_least |
| `saturation_current` | current | at_least |
| `dcr_max` | resistance | at_most |
| `rds_on_max` | resistance | at_most |

A **nominal** name is a target value a real part only approaches; an
`at_least` or `at_most` name is a rating or a limit the part must meet
(which way is informational until part resolution, R28, reads it). A
quantity of another dimension, a string, an integer or a boolean under a
vocabulary name is `RHO3202`, one per instance. Its params take
RHO2038's shape as arrays in name order, one entry per mismatched
constraint: `constraints`, their `values` as written, what each is
(`found`) and what the vocabulary takes (`expected`); the first
constraint's value is the primary span and each other's a secondary
span. A
quantity-valued constraint whose name is outside the vocabulary is not
dimension-checked: that is a limit of a closed vocabulary, recorded as an
inherent `not-run` row naming the constraints, never a diagnostic.

**Bound dimensions.** An assertion's bound MUST have a dimension its
measurement admits:

<!-- reconcile: rhoform.check.dimensions:measurement_rows -->

| Measurement | Bound dimensions |
|---|---|
| `operating_point` | voltage, current |
| `ripple` | voltage, current |
| `frequency` | frequency |
| `period` | time |
| `duty_cycle` | dimensionless |
| `gain` | dimensionless |
| `bandwidth` | frequency |
| `rise_time` | time |
| `fall_time` | time |
| `prop_delay` | time |
| `settling_time` | time |
| `overshoot` | dimensionless, voltage |
| `power_avg` | power |
| `power_rms` | power |
| `efficiency` | dimensionless |

A bound of another dimension is `RHO3203`, about the assertion, whatever
its tier: params `value` (the bound as written), `found`, `context` and
`expected`, RHO2038's shape, its primary span the bound.

**The exact-value lint (T4).** A `part abstract` constraint on a nominal
name whose value is exact *by authored form* is `RHO3201`, a warning: no
physical part has an exact resistance, so resolution would match nothing
or invent a tolerance. It is one per instance, with its constraints and
values as arrays, each value the evaluated one in normal form (2.8) — a
reference's value, never its name — so instances given different values
are separate findings. The form is the one the author wrote — a
reference to a parameter has the form of the value it evaluates to —
never the width of the interval: `0ohm +/- 5%` is written with a
tolerance and is not exact, though its interval is a point. A rating or
a limit is exact by nature and is never flagged, and neither is a
constraint of a part bound to a lockfile key, which names one real
part. For each literal it
flags, the finding's fix-it (`has-placeholders`) inserts
` +/- <tolerance>` after the literal; a reference has no literal to fix
here.

A wrong dimension is a defect of the source, not a judgment a design can
overrule, so `RHO3202` and `RHO3203` are not waivable. A value the pass
reports is one later passes do not read (section 1, The passes). The
pass's coverage rows are these, none actionable:

<!-- reconcile: rhoform.check.dimensions:ROWS -->

| Status | Reason | About |
|---|---|---|
| `fail` | `constraint-dimension-mismatch` | an instance `RHO3202` reports |
| `fail` | `exact-part-constraint` | an instance `RHO3201` reports |
| `fail` | `bound-dimension-mismatch` | an assertion `RHO3203` reports |
| `not-run` | `constraint-outside-vocabulary` | an instance with quantity constraints the vocabulary does not name |

## 2.8 Quantities in diagnostics

A quantity a diagnostic carries is a normal-form string (03), and an
interval two of them, as the params `<name>_min` and `<name>_max`; an
infinite end is `-inf` or `+inf`. An end whose exact decimal terminates
is shown exactly; one that does not is rounded **outward** — a lower end
down, an upper end up — to six significant digits, so the interval shown
always holds the exact one. A temperature difference is shown in `K`, a
level in its own unit, and a dimension no word names after its number as
base dimensions (`m^2*kg*s^-3*A^-1`).
