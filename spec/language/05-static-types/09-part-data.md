# 05 — Static types and domains: 9 — Part data at check time

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

D1 and D3 at check time: how a check reaches the data of the part an
instance stands for. The way is the compile root's `rhoform.lock`
([08 — The lockfile](../08-packages.md#the-lockfile)) and the part records
its picks name, each verified against the lockfile and joined to the
instance's definition through the record's `implements` map alone, and
read honestly: a minimum or maximum the vendor states is a guarantee, a
typical or peak figure never is. No part number is searched and nothing
is fetched at compile time. The pass is `parts`, the first the stage runs
([section 1](../05-static-types.md#the-passes)); its codes are the
`parts` owner's range, RHO6001–RHO6049, and a lockfile's own defects are
the package layer's, RHO2070–RHO2079 ([08](../08-packages.md#the-lockfile)),
reported before elaboration. The reference implementation is
`rhoform/check/parts.py`, over `rhoform/lockfile.py` and
`rhoform/partdata.py`.

## 9.1 What the pass reads

The check context holds the compile root and the lockfile the package
layer read and checked there, or none. The pass reads, besides the
design, exactly the records the picks this design uses name — each once,
whatever number of instances share it — and, once per process, the
part-data schema of each version those records declare
(`parts/part-data[.vN].schema.json`). It opens no other record: an entry
of the lockfile no instance of this design uses, which belongs to
another design of the workspace, is not read. It lists a directory only
to match a record path's spelling, starts no process and opens no
network connection.

## 9.2 Picks

Every component instance with a part statement is looked up:

- **`part "key"`** takes the **keyed pick** of that key, and there MUST
  be one: a resolved part whose key names nothing is a reference that
  points nowhere, `RHO6001`, whether the compile root holds no
  lockfile, a lockfile with no parts section, or a parts section with
  no entry of that key (decision D30).
- **`part abstract`** takes the **instance pick** of its design (the
  root instance's IR `definition`) and its identity path, when there is
  one (decision D29). With none, the part is **unlocked**: that is where
  D1's ladder begins, so it is no defect and no actionable row. A later
  check that needs its data says so (9.7).
- A component with no part statement, L9 hardware, and a component with
  a `tie` rule (D1-exempt, as the ground-architecture semantics' GA-4
  net tie is) have nothing to verify.

An instance pick of this design MUST name a component of it with `part
abstract`: one naming no instance, a module instance, or a component
whose part is resolved or absent is `RHO6002`, at the pick's `instance`
in the lockfile. An instance pick of another design is not this
compilation's to judge.

## 9.3 Verifying a record

A pick's record is verified in this order, and the first failure is its
one finding; a finding about a record or a keyed pick is the lockfile's,
not one instance's, so it names the record or the key and every instance
bound through the same pick shares it (section 1):

1. **Located.** The record path is the pick's `record`, an input of the
   parts section. A path beginning `rhoform/parts/` names the record in
   the toolchain's bundled store; any other is under the compile root.
   Every name on it matches the file system's exactly, letter case
   included, and a compile root's record a symbolic link leads out of
   the root names nothing. A path that names no file is `RHO6003`.
2. **The revision.** The sha256 of the record file's exact bytes MUST
   equal the one the parts section records for it. A record that
   changed since it was picked is never re-pinned silently (D1):
   `RHO6004`, with a `needs-review` fix-it that re-pins the recorded
   revision to the record as it is now.
3. **The version.** A record of a part-data version this toolchain does
   not implement is `RHO6005`, refused rather than read against a
   neighbouring version's schema.
4. **The record.** Canonical layout, the schema of the version it
   declares and every lint clause of `rhoform/partdata.py`; any failure
   is `RHO6006`, listing each. The vendor-host allowlist (L21) is the
   bundled store's provenance policy and holds the records under
   `rhoform/parts/` alone: a compile root's own record has the
   provenance its author gives it.
5. **The identity.** The pick's echoes — `part_id`, `manufacturer`,
   `mpn` — MUST equal the record's; otherwise `RHO6007`.

A lint check a record's data cannot support (a window over a relative
bound, say) is not a failure; the instance gets a
`record-check-unperformed` row naming it.

## 9.4 Binding

A verified record is joined to the instance's definition through the
record's `implements` entry for that definition — the only join (decision
D28): no pin name, letter case or designator is matched to guess. The
entry MUST map every definition pin to a record pin, and name no pin the
definition lacks; where both sides state designators they MUST agree.
Otherwise the binding is incomplete, `RHO6008`. **A record of part-data
version 0 has no `implements` map**: it loads, verifies, and never binds,
so every pick of one is `RHO6008`, which says so.

The design's role is authoritative, and the record's role need only be
compatible with it: equal, or a record `passive` pin, which takes its
function from the design, or a record `bidirectional` pin narrowed to
`input`, `output`, `tri_state`, `open_drain` or `open_collector`. A
standard library definition that models one product
(`rhoform.partdata.PART_SPECIFIC`) is that part's pinout, so on it the two
roles MUST be equal. A binding whose only defects are roles the record
cannot carry is `RHO6009`, naming each port: a wrong role would disarm
the pin-role checks, so it is never overridden. An incomplete binding is
`RHO6008` whatever else is wrong with it, listing every defect, roles
included.

## 9.5 Instance picks

An instance pick is made for the constraints its instance stated then,
and is held to the constraints it states now.

**Staleness.** The pick records the digest of its instance's part
constraints (`constraints`, [08](../08-packages.md#picks)): the sha256 of
the `rhoform-canonical-json/1` bytes of an object mapping each
constraint name to its exact elaborated value — a string or a boolean as
itself, an integer as `{"integer": "<decimal>"}`, and a quantity as
`{"unit", "value"}` in its normal-form unit, with `"min"` and `"max"`
for a tolerance, every number a plain decimal string with no exponent,
no trailing fractional zero and no negative zero. The digest is over the
exact values, never the IR's doubles, so two spellings of one value are
one digest. A digest that differs now is a **stale pick**, `RHO6011`,
with a `needs-review` fix-it re-pinning it: a pick is re-made
explicitly, never silently (D1).

**The constraint-satisfaction subset** (decision D29). A fresh pick's
record MUST satisfy each constraint the subset covers:

| Constraint | The record satisfies it when |
|---|---|
| `mpn`, `manufacturer` | the record's value is equal |
| `package` | the record's `package.name` is equal |
| a nominal of the constraint vocabulary ([2.7](02-values.md#27-the-dimensions-pass)) | the guaranteed enclosure of the record field below lies inside the constraint's interval |
| an `at_least` rating | the guaranteed maximum of the record field below is at least the constraint's upper end |
| an `at_most` limit | the guaranteed maximum of the record field below is at most the constraint's lower end |

Each vocabulary constraint is read from one record field, the one home
the D3 v1 key vocabulary (lint L20) gives its key: a nominal from
`parameters`, the values that define the part; a rating from
`ratings.recommended`, the operating ratings, never from
`ratings.abs_max`, whose stress limits are no rating to operate at; and a
limit from the `parameters` value it limits. A record stating a key
anywhere else is not read for it. A
vocabulary name whose key has no home is outside the subset: `dcr_max`,
which no D3 key states yet, and `vds_max` and `supply_max`, which are a
pin's own window relative to another pin, not a value of the part.

<!-- reconcile: rhoform.check.parts:subset_rows -->

| Constraint | Kind | Record field |
|---|---|---|
| `resistance` | nominal | `parameters.resistance` |
| `capacitance` | nominal | `parameters.capacitance` |
| `inductance` | nominal | `parameters.inductance` |
| `reference_voltage` | nominal | `parameters.reference_voltage` |
| `voltage_rating` | at_least | `ratings.recommended.voltage_rating` |
| `supply_max` | at_least | none: outside the subset |
| `vds_max` | at_least | none: outside the subset |
| `power_rating` | at_least | `ratings.recommended.power_rating` |
| `rms_current` | at_least | `ratings.recommended.rms_current` |
| `saturation_current` | at_least | `ratings.recommended.saturation_current` |
| `dcr_max` | at_most | none: outside the subset |
| `rds_on_max` | at_most | `parameters.rds_on` |

The record is read as [2.6](02-values.md#26-part-data-quantities) reads
part data: a guaranteed statistic is a `min` or `max` of vendor
provenance, never a `typ` or a `peak`. A constraint the
record fails is `RHO6010`, one finding per instance naming each failed
constraint, what the instance requires and what the record gives. A
constraint the subset does not cover — any name but these and the
vocabulary's, or a vocabulary name with no record field — is a
`constraint-outside-subset` row, and one the record cannot decide — no
entry at its record field, several operating points, or no guaranteed
statistic — a `constraint-unverified` row. Both are
actionable: the pick binds, and nothing shows it satisfies them. A
vocabulary constraint of the wrong dimension is the `dimensions` pass's
to report (2.7), and gets an inherent `constraint-ill-typed` row here.

A keyed pick is the author's explicit choice, so the subset does not
hold it to the constraints a `part "key"` may also state: they describe
the chosen part, and the IR does not carry them.

## 9.6 The codes

<!-- reconcile: rhoform.check.parts:code_rows -->

| Code | Slug | Severity | Fires on |
|---|---|---|---|
| RHO6001 | `pick-missing` | error | a `part "key"` with no keyed pick (9.2) |
| RHO6002 | `pick-names-no-instance` | error | an instance pick naming no `part abstract` of the design |
| RHO6003 | `record-not-found` | error | a record path that names no file (9.3) |
| RHO6004 | `record-hash-mismatch` | error | a record whose bytes moved since it was picked |
| RHO6005 | `record-version-unsupported` | error | a record of a part-data version not implemented |
| RHO6006 | `record-invalid` | error | a record its layout, schema or lint refuses |
| RHO6007 | `record-identity-mismatch` | error | a pick whose echoes differ from its record |
| RHO6008 | `binding-incomplete` | error | a record whose `implements` map does not join the definition (9.4) |
| RHO6009 | `role-conflict` | error | a record pin that cannot carry the definition's role |
| RHO6010 | `constraint-unsatisfied` | error | an instance pick's record failing the subset (9.5) |
| RHO6011 | `pick-stale` | error | an instance pick made for other constraints |

None is waivable: a pick that does not hold is a defect of the lockfile
or the record, not a judgment a design can overrule. A pick the pass
reported gives its instance no facts, and a later pass treats it as
unknown (`upstream-defect`, section 1).

## 9.7 What later passes read

The pass sets `analysis.parts`. `facts(instance)` is an instance's part
facts: `d3` for a verified, bound pick — the record's binding, with
every value statistic-tagged — or `constraints` for an unlocked `part
abstract`, its constraints alone; none for an instance with no part
statement or a pick the pass reported. A later pass that needs a fact
asks with `require(instance, field, section)`, which returns the facts
it has and, when the instance has no verified part data, records a row
in that pass's own section, so a check that could not read part data is
never a silent pass:

<!-- reconcile: rhoform.check.parts:REQUIRE_ROWS -->

| Status | Reason | Kind | About |
|---|---|---|---|
| `no-data` | `part-data-unresolved` | actionable | an instance with no verified pick, unlocked or with no part statement |
| `no-data` | `upstream-defect` | inherent | an instance whose pick this pass reported |

## 9.8 Coverage

The pass's own rows, reconciled against it:

<!-- reconcile: rhoform.check.parts:ROWS -->

| Status | Reason | Kind | About |
|---|---|---|---|
| `pass` | `bound` | inherent | a pick verified and bound |
| `no-data` | `no-pick` | inherent | an unlocked `part abstract` (9.2) |
| `no-data` | `no-part-statement` | inherent | a component with no part statement |
| `not-run` | `hardware` | inherent | L9 hardware |
| `not-run` | `net-tie` | inherent | a `tie` component |
| `not-run` | `record-check-unperformed` | inherent | lint checks a record's data cannot support |
| `not-run` | `constraint-ill-typed` | inherent | a constraint the dimensions pass reports |
| `not-run` | `constraint-outside-subset` | actionable | an instance-pick constraint the subset does not cover |
| `undecided` | `constraint-unverified` | actionable | an instance-pick constraint the record cannot decide |
| `fail` | `pick-missing` | inherent | `RHO6001` |
| `fail` | `pick-names-no-instance` | inherent | `RHO6002` |
| `fail` | `record-not-found` | inherent | `RHO6003` |
| `fail` | `record-hash-mismatch` | inherent | `RHO6004` |
| `fail` | `record-version-unsupported` | inherent | `RHO6005` |
| `fail` | `record-invalid` | inherent | `RHO6006` |
| `fail` | `record-identity-mismatch` | inherent | `RHO6007` |
| `fail` | `binding-incomplete` | inherent | `RHO6008` |
| `fail` | `role-conflict` | inherent | `RHO6009` |
| `fail` | `constraint-unsatisfied` | inherent | `RHO6010` |
| `fail` | `pick-stale` | inherent | `RHO6011` |

An unlocked part and a component with no part statement are no gap of
this pass, which has nothing to verify for them; they become actionable
where a check needs their data (9.7). The three benchmarks commit no
lockfile yet, so their abstract parts are unlocked, and benchmark (a)'s
two resolved parts are `RHO6001` until their picks land (L5b).

## 9.9 Conformance

The cases are the `parts` area,
[`conformance/check/parts/`](../../conformance/check/parts/), whose cases
run the passes through `parts`. The accept cases cover a keyed pick that
holds, an instance pick satisfying every constraint of the subset,
unlocked parts beside hardware and a part-less component, and an
instance pick whose constraints the subset cannot all show, which binds
and draws the coverage note. The reject cases give every code above at
least one case: a key with no pick with no lockfile, with no parts
section and with no entry; an instance pick of no instance; a missing,
changed, future-version, lint-failing and misidentified record; a
record implementing another definition, and a version 0 record, neither
of which binds; a role conflict; the mpn, package, value-interval,
voltage-rating and power-rating failures of the subset; and a stale
pick.
