# 05 — Static types and domains: 4 — Pin roles

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

T2 and L9b: every pin's role is checked against the other pins of its
net, every pin is on a net or declared not to be, and a net with one pin
is declared as such. The pass is `erc`, the fourth of the check stage
([section 1](../05-static-types.md#the-passes)): it runs after `ground`,
whose typing it reads, and its codes are the `erc` owner's range,
RHO3101–RHO3199. It reads the roles the design declares, the design's
connectivity, its DNP flags and the ground typing, and nothing else: no
part data and no value.

## 4.1 The roles

Every pin and every port states one of ten roles; none is inferred. The
list is the same in the grammar, IR version 1 and the part-data schema,
and is reconciled against the checker's own transcription:

<!-- reconcile: rhoform.check.model:PinRole -->

| Role | Meaning | Transcribe for |
|---|---|---|
| `power_in` | draws from a supply or returns to one | supply and ground pins of a part |
| `power_out` | sources a rail | a regulator output, a connector's supply contact |
| `passive` | two-terminal or contact behaviour, no drive of its own | resistors, capacitors, inductors, diodes, switches, connector contacts, exposed pads |
| `bidirectional` | drives or reads, as configured | general-purpose I/O |
| `open_drain` | pulls low, never high | a pin that cannot drive high (a dedicated I2C pin, a power-good flag) |
| `open_collector` | pulls low, never high | as `open_drain`; the two check alike |
| `tri_state` | drives, or lets go | a bus driver with an enable |
| `input` | reads, drives nothing | a logic or analog input |
| `output` | drives push-pull | a push-pull output |
| `nc` | must not be connected | a pin the datasheet says to leave open |

**Transcription.** A role is a claim the checker relies on, and `passive`
is the most permissive one: it is ok against every role but `nc`, so an
active pin written `passive` silences every rule below. These rules hold
for a component definition and for a part record alike:

- `passive` means electrically passive or a connector contact, never "not
  known".
- `nc` is for a pin the datasheet forbids connecting. A pin with no
  internal connection that may be tied off is `passive`.
- `open_drain` or `open_collector` is for a pin that cannot drive high.
  A general-purpose I/O stays `bidirectional`, even where a design uses
  it as an open drain; the contention and missing-pull rules then trust
  the design.
- An exposed pad is a pin, so that leaving it unconnected is reported.
- A part record's roles agree with the definition the design names, pin
  for pin. Which wins when they do not is section 9's (D1).

**KiCad types with no Rhoform role.** KiCad's *unspecified* has none on
purpose: a typed system has no "do not know". Its *free* (not internally
connected) is transcribed `passive`. Its *open emitter* has none yet;
adding it is a coordinated change to the grammar, the IR and the
part-data schema, deferred to their next versions.

## 4.2 What a net's pins are

A net's members (section 1, [04](../04-elaboration.md#union)) are of
three kinds:

- **Component pins**, the ports of component instances: the only
  members that are physical, and the only ones the pair table counts.
- **Module ports below the root**: hierarchical nodes that join nets
  across the hierarchy. They are never counted, whatever role they
  declare (KiCad's sheet pins); a module port's role contract is T1's.
- **The root module's ports**: external terminals, through which
  something outside the design reaches the net. A root port counts as a
  second terminal for the single-pin rule, drives an input, may pull an
  open drain up, and is never a power source. It does not take part in
  the pair table: what is outside is not known.

**Fitted pins.** A DNP instance, or one beneath a DNP module instance,
is not fitted (section 1): it adds no driver, no pull and no decoupling.
The electrical rules (4.5 to 4.8: the table, undriven inputs, missing
pulls, isolated inputs, shorted parts, decoupling) count fitted pins
only. The connectivity rules (unconnected pins, single-pin nets, nets
with no pins) count every pin, fitted or not: a DNP part's pads are on
the board, and its schematic must be right for the day it is fitted. A
net whose electrical findings would differ were its DNP parts fitted
gets a `depends-on-dnp` row in the check report naming the DNP
instances, the codes as fitted and the codes if fitted, and so does a
DNP two-terminal part that would be shorted. That row is inherent: it
records a fit option, not a gap. This pass reads no part data, so it has
no strap pins to report.

**Ground-typed nets.** A net is ground-typed when the ground pass says
it is (section 5). Until that pass lands, its interim rule types a net
as ground exactly when an author labelled it with `ground_domain`, and
this pass reads that rule unchanged; a design whose return net carries
no label loses the ground exemptions below until the ground pass
synthesizes its default ground (GA-16).

## 4.3 The pair table

T2 asks for a complete ERC lattice with KiCad's pin-conflict matrix as
its baseline. That matrix is no lattice in the order-theoretic sense
(two open collectors share a net, two outputs may not; a bidirectional
pin is fine with an output, a tri-state pin is not), so a lattice is
read here as a **total, symmetric pair table plus an order-independent
fold**, which keeps the baseline as it is. The table gives each
unordered pair of the nine connectable roles — 45 cells, the diagonal
included — one verdict, `ok`, `warning` or `error`; `nc` connects to
nothing (RHO2024 refuses it at elaboration). Restated in full and
reconciled against the checker:

<!-- reconcile: rhoform.check.erc:pair_matrix -->

| | `power_in` | `power_out` | `passive` | `bidirectional` | `open_drain` | `open_collector` | `tri_state` | `input` | `output` |
|---|---|---|---|---|---|---|---|---|---|
| `power_in` | ok | ok | ok | ok | ok | ok | warning | ok | ok |
| `power_out` | ok | error | ok | warning | error | error | error | ok | error |
| `passive` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `bidirectional` | ok | warning | ok | ok | ok | ok | ok | ok | ok |
| `open_drain` | ok | error | ok | ok | ok | ok | warning | ok | error |
| `open_collector` | ok | error | ok | ok | ok | ok | warning | ok | error |
| `tri_state` | warning | error | ok | ok | warning | warning | ok | ok | warning |
| `input` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `output` | ok | error | ok | ok | error | error | warning | ok | error |

**The fold.** Let a net's fitted component pins be counted by role. A
pair is two distinct pins, so a role meets itself only when two pins
hold it. The net has a verdict-`v` pair when, for some cell of verdict
`v`, both its roles are held (by two pins, for a diagonal cell). Only
the counts matter, so the result does not depend on the order of pins,
statements or files.

**Correspondence with KiCad.** The table is KiCad's default pin map
restricted to these roles, with `open_drain` and `open_collector` both
KiCad's *open collector*. It is transcribed from KiCad's documented
default as recalled, not from its source (KiCad is GPL, and none of it
was read), and it has not been confirmed behaviourally:

- **High confidence:** output with output, output with power output,
  power output with power output, and output or power output with an
  open drain or collector are errors; every `passive` and every `input`
  cell is ok; open drain with open drain, bidirectional with
  bidirectional, tri-state with tri-state, and power input with power
  output or power input are ok.
- **Medium confidence:** output with tri-state, bidirectional with power
  output, tri-state with power input and tri-state with an open drain
  are warnings; tri-state with power output is an error; output with
  bidirectional, bidirectional with an open drain and power input with
  an open drain are ok.

Confirming the table cell by cell against `kicad-cli` 10.0.4 ERC on
generated pair fixtures needs the schematic emitter (R30, M3) and is
recorded as that milestone's work. Until then a disagreement on a
medium cell would show as the KiCad smoke gate (V8) and this pass
disagreeing on a warning.

## 4.4 Ground-typed nets

A ground-typed net is the reference, so it carries an implicit driver.
Several supply returns may share it: on a ground-typed net the cells
power output with power output, and power output with an open drain or
collector, are ok. Every pin on it also meets the reference, by its role:

<!-- reconcile: rhoform.check.erc:reference_rows -->

| Role | Against the reference |
|---|---|
| `power_in` | ok |
| `power_out` | ok |
| `passive` | ok |
| `bidirectional` | warning |
| `open_drain` | ok |
| `open_collector` | ok |
| `tri_state` | error |
| `input` | ok |
| `output` | error |

A push-pull or tri-state output tied to ground shorts when it drives
high; a bidirectional pin tied to it is KiCad's bidirectional-with-a-rail
warning. An input or a power input on a ground-typed net is driven, by
the reference. The undriven-input, missing-pull and decoupling rules do
not apply to a ground-typed net.

## 4.5 The rules

Each rule reports at most one finding per net or per instance, with the
pins it is about in array params. The codes, reconciled against the
registry:

<!-- reconcile: rhoform.check.erc:code_rows -->

| Code | Slug | Severity | Fires on |
|---|---|---|---|
| RHO3101 | `driver-contention` | error | a net with an `error` pair (4.3, 4.4) |
| RHO3102 | `pin-role-caution` | warning | a net with a `warning` pair |
| RHO3103 | `undriven-input` | error | an input with nothing to drive it |
| RHO3104 | `open-drain-without-pull` | error | open drains with nothing to pull them up |
| RHO3105 | `unconnected-pin` | error | a pin, not `nc`, on no net |
| RHO3106 | `undeclared-single-pin-net` | error | a net of one pin, not declared |
| RHO3107 | `isolated-input-floats` | warning | `isolated` on an input or power input |
| RHO3108 | `net-without-physical-pins` | warning | a net of module ports alone |
| RHO3109 | `shorted-two-terminal-part` | error | a two-terminal part with both pins on one net |
| RHO3110 | `power-input-without-decoupling` | warning | a supply net with no capacitor to ground |

Over a net's fitted component pins, for a net no `isolated` statement
made:

- **RHO3101** fires when the net has an `error` pair; its params are the
  net and every pin of a role in such a pair, with their roles.
- **RHO3102** fires when the net has a `warning` pair, with the pins of
  the roles in such pairs. A net with both reports both.
- **RHO3103** fires on a net that is not ground-typed and holds an
  input, when no pin on it is a **driver** — an output, a power output,
  a bidirectional, tri-state or passive pin, single-pin hardware
  excepted — no pin pulls low (that is RHO3104's case), and no root port
  is on it.
- **RHO3104** fires on a net that is not ground-typed and holds an open
  drain or open collector, when no pin on it is a driver and no root
  port is on it.
- **RHO3110** is 4.8's.

An `isolated` net holds one member (RHO2026). When that member is a
fitted pin whose role is `input` or `power_in`, **RHO3107** warns that
the pin floats; any other role left open is fine.

## 4.6 Deviations from the KiCad baseline

Each is a reading the baseline does not make, and why:

1. **Module ports are not counted** (4.2): they are hierarchical nodes,
   like KiCad's sheet pins, and a module's `power_out` port on a rail
   its regulator drives is one source, not two.
2. **Root ports are external terminals** (4.2): a module checked on its
   own has its environment outside it, so its ports neither contend nor
   leave a net with one pin.
3. **A ground-typed net carries an implicit reference** (4.4), per the
   ground-architecture semantics (§1.1): several supply returns share
   it, and an input strapped to it is driven.
4. **Passive pins drive inputs.** A divider, an RC node or a strap
   resistor sets an input's level; without this, (a)'s timing node and
   (b)'s feedback, enable, current-limit, timing and soft-start inputs
   would all be undriven.
5. **Single-pin hardware does not drive.** A test point or grounded
   mounting hole is a physical passive pad (L9), so it is a pin on its
   net, but it sets no level: an input with only a test point beside it
   is undriven.
6. **Power-input sourcing is not a T2 rule.** KiCad's
   power-pin-not-driven asks for a power output on the same net; whether
   a supply reaches a power input through a fuse, a ferrite, a diode or
   a jumper is a domain question, and T5 decides it (section 6). This
   pass reports nothing for it.
7. **An open drain with nothing to pull it up is an error** (RHO3104),
   which KiCad does not check: such a net can never go high. A pull
   inside a part is a T6 waiver.
8. **`isolated` is the no-connect flag** (4.7), and an unconnected pin
   is an error whatever its role (KiCad gives the same).
9. **Net topology** (4.8): two rules from the AC2 corpus, outside the
   pair table.

## 4.7 L9b: single-pin nets and unconnected pins

- **RHO3105** fires for every component instance with a pin, of any
  role but `nc`, that no connecting statement names: one finding per
  instance, every such pin in its params. It carries a `needs-review`
  fix-it inserting `isolated INST.PIN` for each, after the instance's
  `name = new` statement; an instance with no such statement (a table
  row) gets none. The fix-it is needs-review because the usual repair is
  a connection, and an isolated input then draws RHO3107.
- **RHO3106** fires on a net with exactly one component pin, DNP or not,
  that no `isolated` statement made and that no root port is on. When a
  module port is on it and nothing outside that module instance is,
  the parent left the port unconnected, and a secondary span marks the
  module instance's declaration.
- **RHO3108** warns on a net with no component pin and no root port: it
  joins module ports and connects nothing.

An `isolated` statement makes the intentional single-member net of
[04](../04-elaboration.md#union), so none of these fires for it.

## 4.8 Net topology

Two rules from the AC2 corpus's in-scope `net-topology` family, both
decidable from the netlist alone:

- **RHO3109** (BUG-0036) fires on a fitted component with exactly two
  pins, both on one net: the part is shorted out, with no voltage across
  it and no current through it. **Error:** for every two-terminal
  circuit element — resistor, capacitor, inductor, diode, fuse, ferrite,
  switch, jumper — it is a defect, and a correct design never has one.
  The one deliberate shape known is a two-contact connector whose
  contacts share a net on purpose; that takes a T6 waiver, which states
  why. A net tie with both pins on one net is GA-9's (RHO4009) once ties
  are typed (L2c).
- **RHO3110** (BUG-0042, BUG-0056) fires on a net that is not
  ground-typed and holds a fitted `power_in` pin, when no fitted
  **capacitor** has one pin on the net and the other on a ground-typed
  net. A power input on a ground-typed net is a return, not a supply,
  and is exempt. A capacitor is a component with two pins that is the
  standard library's `Capacitor` or states a `capacitance`, as a
  parameter or a part constraint. **Warning:** the rule is a membership
  heuristic, and correct designs exist that it flags — a supply pin
  decoupled on the far side of a ferrite or a series resistor, a module
  carrying its own decoupling, a `power_in` pin that senses a rail
  rather than drawing from it, a capacitor returning to a ground the
  interim typing does not see. A warning annotates and gates nothing
  (V1); it still tells each corpus entry's buggy design from its
  corrected one, which is what the AC2 classification asks of it.

When the design has no ground-typed net at all, RHO3110 cannot know
what a return is: it reports nothing, and one actionable
`no-ground-typed-net` row (status `no-data`) on the root lists the
supply nets it could not decide. The ground pass's typing, or a label,
closes it.

## 4.9 Reporting

- **Entities.** A net rule's entity is the net; RHO3105's and RHO3109's
  are the instance. The primary span is the entity's declaration: the
  net's declaring statement, or the instance's `new` statement. RHO3101
  to RHO3104, RHO3109 and RHO3110 carry a secondary span per listed pin,
  where a statement joins it to the net.
- **Once per definition.** Params spell a net and its pins as the module
  whose body declares the net writes them (`Y`, `a.y`), and an instance
  as the module declaring it writes it (`u`, `w[0]`), never by instance
  path. The copies a module instantiated several times makes
  of one defect therefore agree on code, params and spans, and are one
  finding (section 1), with an entity only when they are one net.
  Copies that differ — the pins or nets of one instance's defect are not
  another's, or a parent leaves one instance's port open and not the
  other's — are reported apart, each with its own entity.
- **Order.** Rules iterate nets and instances in IR order; the framework
  orders the stream, and nothing depends on hash order.

## 4.10 Coverage

The pass is implemented, so its section of the check report holds no
`pass-not-implemented` row. It writes only these rows: `depends-on-dnp`
(4.2), inherent, and `no-ground-typed-net` (4.8), actionable. Every
verdict it reaches from roles it reaches exactly, so it has no
undecided rows; what it cannot see — whether a role is transcribed
right, whether a supply reaches a power input — is said in 4.1 and 4.6.

## 4.11 Conformance

The cases are the `erc` area,
[`conformance/check/erc/`](../../conformance/check/erc/), whose cases
run the passes through `erc`. The accept cases cover a shared I2C bus
with pull-ups, a wired-OR of open collectors, a tri-state bus, a rail
fanning out, a ground with two power outputs, an input strapped to
ground, an RC timing node, a divider into an input, an isolated output,
an `nc` pin left out, test points, module-port roles, root ports as
terminals and a DNP alternate regulator; each reports nothing. The
reject cases give every code above at least one case, mirror the corpus
entries the rules catch (BUG-0018, 0020, 0022, 0030, 0034, 0036, 0038,
0042, 0046, 0056), and include a module reused twice whose defect is
reported once. The three benchmarks produce no finding of this pass
(test_benchmarks.py pins their streams).
