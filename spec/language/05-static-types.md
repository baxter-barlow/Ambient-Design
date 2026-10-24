# 05 — Static types and domains

*Rhoform Language Specification · normative, v0.1 (section 1, the
checking model; sections 2–9 land with their checkers across M2) ·
CC-BY-4.0 (see [spec/README.md](../README.md))*

The static type system — interface types (T1), the pin-role ERC lattice
(T2), quantity typing and dimensional algebra beyond literals (T3/T4),
voltage domains with component-mediated transfer semantics (T5), waivers
(T6), budgets (T10) and the static assertion tier (V1) — runs as one
stage, the **check stage**, after elaboration. Section 1 below is the
model every checker shares and is normative now. Each later section lands
in the same change that implements its checker, in a file of its own so
that checkers landing in parallel edit disjoint text:

| Section | Checker | Status |
|---|---|---|
| 1 — The checking model | the stage itself | normative |
| [2 — Values and dimensions](05-static-types/02-values.md) | T3/T4 (AMB-53) | reserved |
| [3 — Interfaces](05-static-types/03-interfaces.md) | T1 (AMB-51) | normative |
| [4 — Pin roles](05-static-types/04-pin-roles.md) | T2, L9b (AMB-52) | reserved |
| [5 — Ground architecture](05-static-types/05-ground.md) | GA-1..GA-17 (AMB-54) | reserved |
| [6 — Voltage domains](05-static-types/06-domains.md) | T5 (AMB-54) | reserved |
| [7 — Budgets](05-static-types/07-budgets.md) | T10 (AMB-55) | reserved |
| [8 — Waivers and static assertions](05-static-types/08-waivers-and-static-assertions.md) | T6, V1 (AMB-56) | reserved |
| [9 — Part data at check time](05-static-types/09-part-data.md) | D1, D3 (AMB-59) | normative |

One part of T5 is specified already and is normative today: the
ground-architecture semantics (GA-1..GA-17), published as *Rhoform
Ground-Architecture Semantics* in the project's Notion Docs collection
(CC-BY-4.0). Its diagnostics catalog is transcribed into the registry —
see [06 — Diagnostics](06-diagnostics.md) — and section 5 will absorb it
by reference, not restate it, when its checker lands.

## 1. The checking model

### When the stage runs

The check stage runs on a compilation whose elaboration produced a design
with no error-severity diagnostic ([04 — Elaboration](04-elaboration.md)),
and never otherwise: a design elaboration rejected is not checked, so an
elaboration reject case reports the same stream whether or not the stage
exists. The reference command line, `rhoform check`, runs it on every
entry. The stage changes no byte of the IR or its source map and no hash:
the IR of a design that elaborates is written (`--emit-ir`) whatever the
checks find, and the run exits `1` when any stage reported an error
([06](06-diagnostics.md#the-stream)).

### What the stage reads

The checks read the **elaborated design**, not the serialized IR, and a
context holding everything else they may read: the compile root's
`rhoform.lock` (that spelling exactly) and the part records the picks the
design uses name ([9](05-static-types/09-part-data.md)). Nothing else is
read — no other file, no network, no environment, no clock — and nothing
is written. Until the lockfile lands (AMB-59) the context holds the
compile root alone, so the stage reads no file at all.

**The reading of "on the IR".** The ground-architecture semantics
(section 0) and its checker notes (section 1) place the static tier "on
the I4 netlist IR". This specification reads that as the elaborated
design whose serialization is the IR, and this section is normative on
the point: the IR's numbers are IEEE doubles, where exactness ends
([04](04-elaboration.md#decimal-to-double)) — in doubles 0.1 A + 0.2 A
does not stay within 0.3 A — while the elaborated design keeps every
value as the exact decimal the source wrote, and the IR is a pure, total
function of it, so the design holds exactly the IR's content. The intent
of the GA wording is kept: the stage is static, a pure function of the
design and the lockfile, and every finding names an IR entity. The
departure from its letter is recorded as a source conflict against the
GA spec (AMB-54).

**Exactness.** Every comparison and every sum a check makes is exact,
over the exact decimals in base units; an IR double never feeds a check.

### What a finding is about

Every finding names the IR entity it is about in its `entity`: an
instance path, a net name or an assertion path, each a node of the
source map. A finding about a port names the port's instance or net and
carries the port in its params. Its primary span is the entity's
declaration unless a finer one is known — the connecting statement that
names an endpoint, a port's declaration, an attribute, a part
constraint's value, an assertion's bound. A pass reports one finding per
code and entity: the members of a set (the nets a rail feeds, the pins of
one instance) go in one array param, so a design of many instances cannot
reach the output cap through one rule. Findings that agree on code,
params, spans and fix-its are one finding, which keeps its entity only
when every copy names the same one. Quantities in params are normal-form
strings and intervals two of them ([06](06-diagnostics.md#structured-params-rendered-messages)).

### The passes

The stage builds the checked design, runs the passes in this order, then
applies waivers, raises the coverage summary and emits the findings. The
table is reconciled against the stage's own order by the conformance
gate:

<!-- reconcile: rhoform.check:pass_names -->

| Pass | Codes of | Checks |
|---|---|---|
| `model` | `check` | the checked design itself, built from the elaborated one |
| `parts` | `parts` | lockfile picks and the part records they name (D1, D3) |
| `dimensions` | `quantities` | dimensions of constraints and bounds, the exact-value lint (T3/T4) |
| `ground` | `ground` | GA passes 1–4: isolation, ground typing, ground domains |
| `erc` | `erc` | pin roles and single-pin nets (T2, L9b) |
| `domains` | `domains` | origins, rails, envelopes, abs-max and crossings (T5) |
| `budget` | `budget` | current and power budgets (T10) |
| `domains_refine` | `domains` | the T5 sites that depend on current |
| `assertions` | `waivers` | the static assertion tier (V1) |

A pass reads only what earlier passes concluded. A defect is reported
once, by the earliest pass that sees it: later passes treat what it
touches as unknown and record a coverage row with the reason
`upstream-defect` rather than a second diagnostic. A pass reports only
codes inside its owner's ranges (below).

### What a pass never sees

**The defaults run.** A module the design builds no instance of — one
whose only `new` stands in a branch no instance takes, say — is
elaborated once under its defaults for its own diagnostics
([04](04-elaboration.md#diagnostics)). Nothing of that run reaches the
check stage: checks run on the instances the walk from the root built
and on the nets flattening made, and on nothing else.

**DNP instances.** An instance flagged `dnp`, or inheriting the flag
from a module instance, is not fitted, and every pass treats it as
absent from the board's electrical behaviour: it adds no driver, no pull,
no origin, no transfer edge, no draw and no conduction between its pins.
A conclusion that would change if a DNP part were fitted is listed in
the check report, and a strap pin whose part data describes strap
behaviour gets a `not-run` row. `exclude_from_bom` and `board_only`
change what is bought or exported, not what is fitted, and do not change
any check.

### Coverage

A check that cannot decide is never a silent pass. Every pass writes
**coverage rows** — an entity, a status, a reason, whether the row is
actionable, and structured detail — into its section of the **check
report**. A row's status is one of these, reconciled against the
reporter:

<!-- reconcile: rhoform.check.report:STATUSES -->

| Status | Meaning |
|---|---|
| `pass` | decided, and it holds |
| `fail` | decided, and it does not (the finding carries the diagnostic) |
| `undecided` | the enclosure overlaps the bound and is not tight |
| `no-data` | a fact the check needs is absent |
| `not-run` | the check does not apply in this tier, or was not reached |
| `not-implemented` | the pass is a stub so far |
| `interim` | an interim rule stands in for the pass's own |

A row is **actionable** when the author or the toolchain can close the
gap it records: an undecided implicit safety site (an abs-max, a rating,
a crossing, a budget, a headroom); a pass not implemented yet; a
top-of-lattice net caused by a missing declaration (a rule-less passive
or `power_out` pin, an unsupplied connector); an origin taken only from
an unverified declaration, or with no declared capability; a part-data
field a pass reads marked `not-transcribed`, or a requirement field the
checker does not consume; an ambiguous reference rail; a component with
no pins that is no L9 hardware. Every other row is **inherent**: a
reviewed switch node, vendor-unpublished data, a dynamic-tier assertion,
a class outside the static scope this section names. Inherent rows live
in the report only.

Any actionable row raises the compilation's **one** `RHO3901`
(`static-coverage-degraded`) note, anchored at the root instance `/`,
whose params count the actionable rows by class (the row's reason) and
name the sections that hold them. "The benchmarks check with zero
diagnostics" therefore means an empty stream: no `RHO3901`, and so no
actionable row; their inherent rows are pinned in committed check
reports. While any pass is unimplemented, every check-stage run carries
the note.

A **declared static-tier assertion** that no evaluator measures gates,
as V1 requires of an assertion that cannot be measured: until the static
tier lands (section 8) every one is an `RHO3553`
(`static-assertion-incomplete`) error, tier `static`, reported in the
`assertions` pass's place. A dynamic-tier
assertion is the dynamic tier's (M5): the check stage never evaluates
it, and it is no incomplete here.

The check report is `rhoform-check-report` version 0
([`rhoform/check-report.schema.json`](../../rhoform/check-report.schema.json),
normative by reference): the design's `design_hash`, the generator, one
section per pass that ran (`model` included), the waivers and the
safety-relevant bonds. It is written in `rhoform-canonical-json/1`,
validated against its schema before it is written, and never part of
`design_hash`; `rhoform check --emit-report DIR` writes it as
`<stem>.check.json`. Version 0 is unfrozen while M2 lands its passes.

### Code ranges

Every diagnostic code a checker adds lives in a range one owner holds, so
checkers landing in parallel can never take one number twice; an owner
takes the next free number inside its own range. `core` is the registry
file's own blocks as M1 left them; every other owner is a file of
`rhoform/codeset/`. The table is reconciled against the registry's
`RANGES` by the conformance gate, and the registry gate refuses a code
outside its owner's ranges:

<!-- reconcile: rhoform.codes:RANGES -->

| First | Last | Owner | Numbers |
|---|---|---|---|
| RHO0001 | RHO0001 | core | the truncation note |
| RHO0002 | RHO0009 | waivers | the waiver reporting layer (T6) |
| RHO1001 | RHO1017 | core | syntax 0.1 and 0.2 |
| RHO1018 | RHO1029 | syntax | syntax 0.3 |
| RHO1030 | RHO1039 | interfaces | interface syntax |
| RHO2001 | RHO2069 | core | the elaborator and the package layer |
| RHO2070 | RHO2079 | lockfile | the lockfile and its packages section |
| RHO2080 | RHO2089 | syntax | elaboration of syntax 0.3 statements |
| RHO2100 | RHO2119 | interfaces | interface elaboration |
| RHO2120 | RHO2149 | elaboration | elaborator residuals |
| RHO3001 | RHO3099 | interfaces | T1 interfaces |
| RHO3101 | RHO3199 | erc | T2 pin roles and L9b |
| RHO3201 | RHO3299 | quantities | T3/T4 quantities |
| RHO3301 | RHO3399 | domains | T5 voltage domains |
| RHO3401 | RHO3499 | budget | T10 budgets |
| RHO3501 | RHO3549 | waivers | T6 waiver statements |
| RHO3551 | RHO3599 | waivers | V1 static assertion results |
| RHO3901 | RHO3999 | check | the check stage and its coverage |
| RHO4001 | RHO4011 | ground | the GA catalog |
| RHO4012 | RHO4099 | ground | GA follow-ons |
| RHO6001 | RHO6049 | parts | picks, records and binding |
| RHO6050 | RHO6099 | parts | part-data follow-ons |

A number in no range has no owner and cannot be declared. Block 5 is the
dynamic tier's (M5) and block 7 the exporters' (M3); neither has a range
yet.

### Conformance

The check cases ([`conformance/check/`](../conformance/README.md)) are
grouped by area, and each area names the last pass it runs. An area's
run stops after that pass, and its coverage note counts the actionable
rows of `model` and of that pass alone, so neither a pass after it nor
another pass's being still a stub can move an area's stream: what an
area pins is its own pass's behaviour, and any finding a pass before it
makes in its cases. The command line always runs every pass and counts
every section. Across the suite's reject cases, every active code of
blocks 1–4 and 6 a source can trigger is emitted by some case.
