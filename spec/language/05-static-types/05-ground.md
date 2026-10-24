# 05 — Static types and domains: 5 — Ground architecture

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

GA-1..GA-17, the ground-architecture semantics, are normative by
reference: *Rhoform Ground-Architecture Semantics*, in the project's
Notion Docs collection (CC-BY-4.0). This section does not restate them.
It says how Rhoform's surface expresses what they name, how the checker
decides each rule, and the decisions that implementation takes; where it
narrows a rule it says so, and why. The pass is `ground`, the third of
the check stage ([section 1](../05-static-types.md#the-passes)): it runs
before `erc`, whose ground exemptions read its typing, and before the
rest of T5, for which ground domains are a prerequisite (every T5 value
is an interval relative to one ground domain). Its codes are the
`ground` owner's ranges, RHO4001–RHO4011 for the GA catalog and
RHO4012–RHO4099 for follow-ons.

The pass reads the design's connectivity, its components' rules and
sides (an instance's own, after any `rule` statement,
[04](../04-elaboration.md#rules-and-sides)), the `ground_domain` and
`ground_kind` attributes of its nets with every site that sets one, and
its DNP flags. It reads no part data and no value.

## 5.1 Where each rule lives

| Rule | In Rhoform | Here |
|---|---|---|
| GA-1 ground-typed nets | a label or kind (definition a), the parts' `ground` pins (definition c); `Power.gnd` and `ref` (definition b) are interfaces' | 5.3; definition b is L3's |
| GA-2, GA-3 the kind meet | `ground_kind` and its sites | 5.3 |
| GA-4, GA-5 net-ties | a component whose rules include `tie` | 5.2, 5.4 |
| GA-6, GA-7 the tie graph | ties between ground nets | 5.4 |
| GA-8 export of ties | the exporter | M3 |
| GA-9 non-ground and redundant ties | ties | 5.4 |
| GA-10 earth | `ground_kind = "earth"` | 5.5 |
| GA-11 chassis and earth bonds | ties, safety capacitors, galvanic passives | 5.5 |
| GA-12 safety capacitors | `bridge`; a plain capacitor is `open` | 5.2, 5.5 |
| GA-13, GA-14, GA-14b isolation | `side` | 5.2, 5.5 |
| GA-14c unrelated ground domains | per component; a row where no part straddles them | 5.5; per interface connection and signal net, L3 |
| GA-15 disjoint domains | | 5.5 |
| GA-16, GA-17 the zero-annotation default | | 5.6 |

RHO4006 (`isolation-spanning-interface`) is an interface connection's
and stays reserved until interfaces carry their `ref` provenance (L3).

**Net-ties (GA-4).** A component whose rules include `tie` is the
reading of GA-4's first-class `NetTie` kind: the language core needs no
other construct for it. It is exempt from D1 part resolution, so it
needs no part binding, and it is excluded from the bill of materials by
default; that half is the exporter's, which lands in M3. The checker
reads it as a net-tie when it has exactly two pins and one `tie` rule
naming both (5.2). GA-12's Y-class rating attribute for a safety
capacitor, and the GA-4 and GA-12 cases that carry it, are L3's.

## 5.2 Conduction groups and the isolation partition

**Conduction groups.** Each component's pins are partitioned into
groups, galvanic connectivity existing only within a group, by its
rules:

<!-- reconcile: rhoform.check.ground:word_rows -->

| Word | Here |
|---|---|
| `bridge` | a group per pin; a safety capacitor |
| `conduct` | joins its pins; a galvanic passive |
| `connector` | a group per contact |
| `diode` | joins its pins |
| `feedback` | joins its pins |
| `ground` | types its pins' nets ground |
| `open` | a group per pin |
| `pass` | joins its pins; a galvanic passive |
| `regulate` | joins its pins |
| `side` | a group per side; a barrier |
| `source` | joins its pins |
| `switch` | joins its pins; a galvanic passive |
| `tie` | joins its two pins; a net-tie |

A component with no rule that splits it is **one group**, GA's default
for an ordinary component. Each pin an `open` or `bridge` rule names is
a group of its own, and so is each **contact** of a `connector`: the
pins a `connector` rule names, or, for a `connector` naming none, every
pin no other rule names. A joining word then joins the groups of the
pins it names, its `from` or `to` pin with them. A component that
declares a `side` is a **barrier** (GA-13): its groups are its sides,
and a pin on no side is a group of its own. Every other word means
nothing here; its meaning is T5's ([section 6](06-domains.md)).

A **galvanic passive** (GA section 1.4) unifies the ground domains of
the ground nets it joins (5.4): the pins of a `conduct`, `pass` or
`switch` rule, and a component with no rule at all and two or more
pins, every one `passive` — GA's default for a resistor, an inductor, a
ferrite or a fuse, and for a multi-terminal passive such as a
common-mode choke or a Kelvin shunt, which is one group like any
rule-less component. That reading is a default, not a declaration:
wherever it decides that two ground nets are one domain, the component
gets an actionable `assumed-galvanic-passive` row (5.11).

**The isolation partition (pass 1)** is declared, not observed (GA
section 1.1). It is a partition of the design's nets: each fitted
component joins the nets of each of its groups, and each side of a
fitted barrier **seeds** the nets of its pins with that side. A barrier
conducts within a side and never across one. Two classes are **kept
apart** by a barrier when each holds a side of it and no side is in
both. A join that would merge two classes some barrier keeps apart is
refused: a galvanic path across a barrier never merges the domains it
violates, it is the violation (5.5). The joins are taken in a fixed
order, every fitted barrier's sides first, then every other fitted
component's groups, components in IR path order and groups in order, so
the partition, and which component a refused join reports, is a
function of the design alone. The classes are the **isolation domains**.

## 5.3 Ground typing and the kind meet

**Ground-typed nets (GA-1).** A net is ground-typed when

- *(a, declared)* any site gives it a `ground_domain` label or a
  `ground_kind` attribute; or
- *(c, the default ground)* it holds a pin of a fitted component that
  the component's `ground` rule names.

A part's `ground` rule is how it declares its reference pins, of kind
`unspecified` (GA-3: library components adopt whatever the design
provides), so a design with no annotation at all gets its default
ground from its parts. Definition (b), binding the `gnd` member of a
`Power` interface or a `ref`, is L3's, with interfaces.

**The meet (GA-2).** Elaboration merges directly connected nets into
one, and does not merge `ground_kind`
([04](../04-elaboration.md#domains)); the meet is taken here, over
every site of the net's `ground_kind`, so a conflict carries both
spans. A ground-typed net's **kind** is the meet of the kinds its sites
write, `unspecified` with none. Two different specific kinds meet at
bottom: **RHO4001** on the net, once, however many sites disagree. Its
`kind_a` and `kind_b` are the two least specific kinds the sites write,
in the order of this table, and `net_a` and `net_b` the labels of the
earliest site writing each, as their modules write them; its primary
span is `kind_b`'s site and its secondary `kind_a`'s. Which kinds are
reported therefore does not depend on statement order or on which label
is shallower. A net whose kinds have no meet stays ground-typed, with no
kind: nothing in 5.5 that reads a kind reads it.

<!-- reconcile: rhoform.check.ground:KINDS -->

| Kind | |
|---|---|
| `unspecified` | the top: meets anything (the default) |
| `signal` | |
| `power` | |
| `chassis` | may be a reference; its bonds are safety-relevant |
| `earth` | never a reference; its bonds are safety-relevant |

A `ground_domain` label is a name, not a relation: two nets that carry
the same label are not one ground domain by it, and the computed domain
ids never overwrite the label (5.8).

## 5.4 Ground domains and the tie graph

**Pass 3** keeps two structures over the ground-typed nets and never
conflates them (GA notes section 2):

- **Ground domains**, a union-find: ground nets joined by a direct
  connection (one net already), by a net-tie, or by a fitted galvanic
  passive whose joined pins land on both. A galvanic passive whose
  joined pins land in two isolation domains a barrier keeps apart is
  RHO4005's (5.5) and, like a tie across a barrier, unifies nothing: a
  ground domain lies within one isolation domain (GA section 1.1), and
  the barrier stands as declared. An `earth` net joins no domain, as no
  reference does (GA-10), and stays a domain of its own.
- **The tie graph**: nodes the ground nets, edges the fitted net-ties
  between two of them, and only those. A galvanic passive is never an
  edge, so it can never raise a ground loop.

Each fitted net-tie, in IR path order:

- both pins on one net: **RHO4009**, a warning (GA-9); nothing else;
- its pins in two isolation domains a barrier keeps apart: **RHO4008**
  (5.5), no union and no edge (GA-14b);
- either net not ground-typed: domain-transparent, like a direct
  connection (GA-9), no union and no edge;
- otherwise it unifies the two ground domains and is an edge. An edge
  whose ends the edges before it already connect closes a cycle:
  **RHO4002** on that tie, its `cycle` the cycle's nets and ties by turn,
  from one end of the tie through the tree to the other and back over
  the tie (`[AGND, /t1, PGND, /t2, AGND]`), a secondary span at each
  other tie of the cycle.

A tie with a pin on no net is ERC's (RHO3105) and does nothing here.
The tie graph is a forest by construction of what is kept; star
grounding (GA-7) is a tree and needs nothing of its own.

## 5.5 The scans

Each finding is about one entity, once per code; params name nets and
instances by their IR names, as the domain ids are (5.8). The codes,
reconciled against the registry:

<!-- reconcile: rhoform.check.ground:code_rows -->

| Code | Slug | Severity | Fires on |
|---|---|---|---|
| RHO4001 | `ground-kind-conflict` | error | a net whose kinds meet at bottom (5.3) |
| RHO4002 | `ground-loop` | error | a tie closing a cycle of the tie graph (5.4) |
| RHO4003 | `earth-as-reference` | error | a part whose `ground` pin is on an `earth` net |
| RHO4004 | `undeclared-chassis-bridge` | error | an `open` pair across a chassis, earth or isolation boundary |
| RHO4005 | `isolation-spanning-component` | error | a group across a barrier |
| RHO4007 | `disjoint-ground-domains` | warning | isolation domains nothing crosses between |
| RHO4008 | `isolation-defeating-bond` | error | a net-tie across a barrier |
| RHO4009 | `redundant-net-tie` | warning | a tie with both pins on one net (5.4) |
| RHO4010 | `undeclared-ground-domain-crossing` | error | a part straddling unrelated ground domains |
| RHO4011 | `safety-relevant-bond` | note | a bond to a chassis or earth ground |

Over fitted components:

- **RHO4005** (GA-14): a component, a barrier included, one of whose
  groups lands in two isolation domains a barrier keeps apart, with the
  least such pair as `domain_a` and `domain_b` and the least such
  barrier as `barrier_component`, its declaration a secondary span. A
  net that holds pins of two sides of one barrier is that barrier
  wired across with no component at all: the finding is about the net,
  its `component` the net's name and both domain params the one domain
  it makes, with the least such barrier. **RHO4008** (GA-14b) is the
  same test on a net-tie.
- **RHO4004** (GA-12, by position): a component that is not a barrier,
  with two pins one `open` rule names landing on two isolation domains
  a barrier keeps apart (`boundary` `isolation`), or on two ground nets
  of different kinds of which one is `chassis` or `earth` (`earth` if
  either is, else `chassis`). A `bridge` is the declared safety
  capacitor and is never this; it relates nothing (5.4) and spans
  nothing.
- **RHO4010** (GA-14c): a component that is not a barrier or a net-tie,
  and reported nothing above, whose pins land on ground nets of two
  ground domains inside one isolation domain: two references that no
  direct connection, tie or galvanic passive relates, so no voltage
  comparison across the part exists. A `bridge` pin and a contact are
  not counted, the first relating nothing and the second transparent,
  and neither is an `earth` net, which is no reference. The least two
  domains are reported. The fix is a net-tie, or a direct connection if
  they are one reference. A rule-less component is one group, so
  joining two grounds through it puts them in one isolation domain:
  an integrated circuit whose two ground pins land on two untied
  grounds is this finding. The test over an interface connection's
  `ref` nets is L3's. Two unrelated ground domains in one isolation
  domain that no part straddles — two subcircuits that share only a
  signal net, GA-14c's own example, or a module whose ground port was
  never connected — are joined by parts that are not passives, and
  whether a pin compares across them depends on what each signal pin is
  referenced to, which is T5's to decide (L3). Until it does, that
  isolation domain gets an actionable `unrelated-ground-domains` row
  naming its ground domains (5.11), unless the pairs RHO4010 names in
  it already connect them all; it is never a silent pass.
- **RHO4003** (GA-10): a component whose `ground` rule names a pin on an
  `earth` net uses earth as its reference: the component is the entity
  and `referencing_entity`.
- **RHO4011** (GA-11): a fitted net-tie, safety capacitor or galvanic
  passive joining two ground nets one of which is `chassis` or `earth`
  is a bond, and safety-relevant: a note on the bond, `boundary` as for
  RHO4004. A tie across a barrier is RHO4008's and no bond, and a
  galvanic passive across one is RHO4005's and no bond. A bond that is
  neither a tie nor a safety capacitor — a bleeder resistor — is off the
  list GA-11 sanctions; GA section 8.2 makes it a note, not a gate, and
  the uncoded section 1.4 warning, which this pass writes as a row
  (5.9).
- **RHO4007** (GA-15), about the root `/`: the isolation domains holding
  a fitted pin fall into more than one cluster, where a fitted component
  with pins in two domains — a barrier whose sides they are, a safety
  capacitor, a contact — puts them in one. `domain_ids` is the least
  domain of each cluster. A carrier board for two independent circuits
  is legitimate, so it is a warning.

The scans read nothing they decided not to: a component reported
RHO4005 or RHO4004 is not also RHO4010, and a tie reported RHO4008 or
RHO4009 is no bond and no edge.

## 5.6 The zero-annotation default (GA-16, GA-17)

A design with no label, no kind, no tie and no side, whose parts declare
their ground pins, gets exactly one ground domain of kind `unspecified`
when those pins are on one net, or on nets that passives join (a ferrite
in the return, a common-mode choke, a shunt), in one isolation domain
when it is connected; naming its net `GND` is I2's, not this pass's. A
passive that joins them with no rules is read by the galvanic default
(5.2), whose row says so. Ground pins on nets that only other parts
join are references nothing relates, usually a forgotten ground
connection: RHO4010 on a part straddling them, or an
`unrelated-ground-domains` row (5.5). A design with no
ground-typed net at all, labelled, kinded or declared, has no ground to
synthesize: that is an actionable `no-ground-domain` row on `/` naming
the nets with fitted pins, since nothing after this pass then has a
reference.

The three benchmarks label their return net `GND` with `ground_domain`.
Each has exactly one ground domain, `GND`, of kind `unspecified`, one
isolation domain holding every net, an empty tie graph, and no RHO40xx
(GA-17); rhoform/tests/test_ground.py pins that, and that ERC reaches on
them, and on every `check/erc` case, exactly what it reached under the
interim rule this pass replaces (a net ground exactly when labelled
`ground_domain`).

## 5.7 DNP

A DNP instance is absent ([section 1](../05-static-types.md#what-a-pass-never-sees)):
it seeds no side, joins no nets, types no net with a `ground` rule, is
no tie, bond or galvanic passive, and is scanned for nothing. A DNP
component whose pins are on nets of two isolation domains, or on ground
nets of two ground domains, would relate or straddle them if fitted: an
inherent `depends-on-dnp` row names it and those domains.

## 5.8 What the pass hands on

Domain ids are the name of the class's least member net, compared
bytewise (GA notes section 1): stable under unrelated edits, and the
same whatever order the joins were taken in. They go to the check
report and to the passes after this one, never into the IR:
`Net.ground_domain` keeps the label its author wrote, so `design_hash`
does not depend on the checker. This departs from the GA notes' section
3 item 7, which suggested carrying the computed id in that slot.

The pass's analysis (rhoform/check/ground.py, `GroundAnalysis`) gives
the passes after it:

- `is_ground(net)` and `ground_kind(net)` (5.3);
- `ground_domain(net)`, the id of a ground-typed net's domain; a net
  that is not ground-typed has none here, its reference being T5's;
- `isolation_domain(net)`, for every net;
- `tie_graph`, the edges kept (tie, net, net), and `net_ties`, the
  well-formed net-ties: a redundant one is this pass's RHO4009, so
  ERC's RHO3109 skips them ([04](04-pin-roles.md#48-net-topology)) and
  the defect is reported once (section 1);
- `conduction_groups(component)` and `barriers()`, each barrier's sides.

## 5.9 Decisions

- **The model, not the IR.** The pass reads the elaborated design, as
  every check does; section 1 states the reading of GA section 0 and the
  checker notes' section 1, "on the I4 netlist IR", and records the
  departure.
- **The meet in the checker** (5.3), from the attribute sites, which
  hold both spans; elaboration merges no `ground_kind`. The checker
  notes allow either.
- **A barrier conducts within a side.** The checker notes' pass 1 says
  a declared isolated transfer contributes no unions at all; the
  semantics (section 1.1) say it conducts within a side and never
  across, and the semantics win. A side's pins are one domain.
- **Joins in a fixed order** (5.2). When a chain of parts crosses a
  barrier, the first of them in IR order whose join is refused is the
  one reported.
- **Labels relate nothing** (5.3). Ground domains are computed; an
  equal `ground_domain` label on two unconnected nets declares no
  relation between them.
- **Earth joins no domain** (5.4), as the checker notes' pass 3 says;
  ties to earth are still edges, so bonding earth twice is a loop.
- **Malformed GA rules are rows.** Which words take how many pins is the
  check stage's ([04](../04-elaboration.md#syntax-03-source-facts-unfrozen)).
  A `tie` on a component that does not have exactly two pins, or more
  than one `tie`, or a `tie` naming other than both, gives an actionable
  `malformed-tie` row, and the component is read by its other rules; a
  `bridge` naming other than two pins gives `malformed-bridge`, its pins
  still groups of their own. The GA block has no code for either.
- **The section 1.4 warning is a row.** A galvanic passive joining two
  ground nets of different specific kinds gets an inherent
  `passive-joins-distinct-kinds` row: GA leaves it uncoded by design, and
  the registry's GA block holds exactly the catalog. So does GA-10's
  note on a chassis reference (`chassis-as-reference`).
- **No fix-its yet.** The catalog's fix-its insert or remove an
  instance, which the fix-it machinery cannot yet synthesize; the
  findings carry none until it can.

## 5.10 Limitations

Stated, not hidden:

- **The standard library carries no rules yet** (L3 adds them). Until it
  does, its parts are each one group, its capacitor is a galvanic
  passive rather than `open`, so a library capacitor across a chassis
  boundary is a bond (RHO4011) where GA-12 wants RHO4004 — its
  `assumed-galvanic-passive` row keeps that from passing silently — and
  a library header with pins on both sides of a barrier spans it
  (RHO4005), and one with pins on two ground nets joins them, with that
  row, where a `connector` would do neither. Designs that need these
  distinctions declare their own components' rules, as the conformance
  cases do.
- **GA-14c across a shared signal net** is not decided here: which
  ground a signal pin is referenced to is T5's (L3), so two unrelated
  ground domains in one isolation domain that no part straddles are an
  `unrelated-ground-domains` row, not RHO4010 (5.5).
- **RHO4003** sees only a `ground` rule's pins; a `Power.gnd` or `ref`
  bound to earth is L3's.
- **The safety section of the check report** stays empty: its entry
  shape is stated with the waivers that GA-11 echoes there (L5a). The
  RHO4011 notes are in the stream.

## 5.11 Coverage

The pass is implemented, so its section of the check report holds no
`pass-not-implemented` row. Its rows: one `ground-domain` row per ground
domain (its nets, their kinds and its isolation domain) and one
`isolation-domain` row per isolation domain holding a fitted pin (its
nets, its ground domains and the barriers seeding it), with status
`pass`; `passive-joins-distinct-kinds`, `chassis-as-reference` and
`depends-on-dnp`, inherent; and `no-ground-domain`, `malformed-tie`,
`malformed-bridge`, `assumed-galvanic-passive` and
`unrelated-ground-domains`, actionable, with status `no-data`.
`assumed-galvanic-passive` is on a component with no rules whose
galvanic default (5.2) joined two ground nets, naming them: a missing
declaration decided that they are one ground domain, and, to a chassis
or earth ground, that the component is a bond; a `conduct`, `pass` or
`open` rule settles it. `unrelated-ground-domains` is on an isolation
domain whose ground domains nothing relates and no RHO4010 named (5.5),
naming them.

## 5.12 Conformance

The cases are the `ground` area,
[`conformance/check/ground/`](../../conformance/check/ground/), whose
cases run the passes through `ground`. The accept cases are a single
default ground from `ground` rules, a tie plus a ferrite (GA section
2.2), a star ground (GA-7), an isolated converter with optocoupler
feedback (GA section 4.2), a chassis tie with a safety capacitor and two
grounded mounting holes, a bleeder resistor with a tie in the same
position (GA section 8.2), a DNP resistor across a barrier, and, with
no annotation, a common-mode choke in a DC input's return and a
four-terminal Kelvin shunt in a low-side return, each one ground domain
by the galvanic default and its row. The reject cases give every code
above at least one case and include each of GA section 8's adversarial
traces: a resistor across a barrier, a tie across a barrier, a
double-tie loop, a third tie closing a triangle, the chassis bonded
twice, earth as a reference, a plain capacitor to the chassis and
across a barrier, a redundant tie, disjoint circuits, a part straddling
two untied grounds, and a barrier's two sides on one net.
