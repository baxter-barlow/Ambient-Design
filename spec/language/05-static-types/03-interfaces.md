# 05 — Static types and domains: 3 — Interfaces

*Rhoform Language Specification · normative, v0.1, unfrozen with syntax
0.3 · CC-BY-4.0 (see [spec/README.md](../../README.md))*

T1: nominal, parameter-carrying interface types, the bundles they type,
and one statement that connects a bundle. An interface is a named record
of members; a bundle is a port of that type, on a module or as a view of
a component; a chain of bundles joins them member by member. Typing is
**nominal**: two bundles connect when they are of one interface
definition and one shape, and never because their members happen to
agree. The surface is syntax 0.3's ([02](../02-grammar.md#interfaces)),
unfrozen with it, and elaboration builds the design from it
([04](../04-elaboration.md#interfaces-unfrozen)).

**Where the checks run.** Every rule of this section is checked during
elaboration, not in the check stage: a bundle that does not resolve
leaves no design to check, and every one of them is decided from the
text and the definitions alone. Section 1's pass order therefore has no
interfaces pass. The codes are the `interfaces` owner's range,
RHO3001–RHO3099 (section 1, Code ranges), reported by the elaborator
under 04's rules for when a finding is reported once and when per
instance.

## 3.1 Interface definitions

An interface definition is `interface`, its name, an optional parameter
list, and its members. Its IR `definition` is named as any definition's
(`rhoform.lib.iface.Power`, `probes.Probe`), and that name is its
identity: an interface imported into a file
([08](../08-packages.md)) is the definition its file defines, under that
name. A definition name of a file names one definition, of whatever kind
(RHO2001, RHO2034).

An interface is never instantiated: `new` and `table` name modules and
components, and an interface where one is required, like a module or a
component where an interface is required (a bundle port, a view, a
nested member), is RHO3001.

## 3.2 Members and shape

A member is a **leaf**, a single node, or a **nested** interface; either
may be an **array** of a literal size, at least 1. A member's name is
unique in its interface (RHO2007). A nested member names an interface
(RHO3001) and takes no arguments: it carries its interface's defaults.
The nesting MUST be acyclic (RHO3002, once per set of interfaces that
contain one another).

An interface's **shape** is therefore finite and fixed by its definition:
its leaves and its nested bundles, each named by a **member path**
relative to it — names joined by `.`, an array's element by its index
(`hv`, `d[3]`, `bus.sck`, `rails[1].gnd`). A size is a literal
(RHO3012), never a parameter, because a port set and a nominal shape
must not depend on parameter values (the principle 04 states for every
`port`): which bundles are compatible is then decided without
evaluating anything. Every leaf of a bundle counts against the
replication budget ([04](../04-elaboration.md#the-replication-budget)),
and an interface's leaves are counted before they are spelled out.

## 3.3 Parameters are carried attributes

An interface's parameter list declares what its bundles carry: `v` of a
`Power`, `addr` and `freq` of an `I2C`. A bundle port's or a view's
arguments give them values, checked as any arguments are (RHO2036,
RHO2038, RHO2039), and a default is carried when no value is given.
Unlike a module's or a component's, a parameter with no default is
**optional**: a bundle that gives it no value leaves it **unset**, which
is no error (no RHO2037), and the IR omits it. An unset parameter is
unknown to every consumer, never a value: a controller's `I2C` has no
address, and a sink's `Power` does not know its rail, so requiring one
would make an author invent a confidently wrong number.

A parameter never takes part in compatibility (3.6). What a value means
is the consuming check's: `Power.v` is an **expectation** of the rail's
voltage, which T5 checks by containment against what the domains pass
computes for the bundle's `hv` net (section 6); a bundle never
originates a voltage, since the structure that does is the DSL's
component rules.

## 3.4 Bundle ports and views

A **bundle port**, `port x = new I[N](args)` at the top level of a
module body, is a port of the module typed by `I`, an array of `N` when
sized. Its leaves become ports of every instance of the module, named
by member path from the port (`x.hv`, `x[2].line`) with the role
`passive`. They are module ports like any other: non-physical nodes
that join nets across the hierarchy, named by the parent as `inst.x.hv`
and by the module itself as `x.hv`. A bundle port's name is no member's
of its module (RHO3011), since `x.y` would then name two things, and a
bundle port inside `if` or `for` is RHO2040.

A **view**, `port v = new I(args):` with a binding for each leaf, is an
interface over pins a component already has: each leaf member path is
bound to one of its pins. It is an alias and adds no node: a view's
leaf is the pin it binds, so joining two views joins their pins. A view
binds every leaf (RHO3007), each once (RHO2007) and to a pin the
component declares (RHO3008) that is not `nc` (RHO3009); no two leaves
of one view share a pin (RHO3010), which would join them, though two
views may (an LDO's `input` and `output` share `gnd`). A view's name is
no pin's (RHO3011). A view is scalar in this version, and its arguments
are evaluated per component instance, in its environment
(`output = new Power(v = vout)` carries each instance's own `vout`).

No library component has a view in M2: interfaces are shown in the
conformance suite's exemplars, and a wrong view would type a domain
silently, so views on library parts wait for part data that agrees with
them pin for pin.

## 3.5 Endpoints and connecting bundles

An endpoint reaches into a bundle by member path: `j1.power.hv`,
`cells[i].bus[1].d[3]`, `power.gnd` for a module's own bundle port. Its
first name is a member of the module when it names one, and otherwise
one of the module's own ports, which may be a bundle port; the next
name is then a port of that member, a bundle port or a view among them;
each later name is a member of the bundle it is in, and an index selects
an element of an array. A name a bundle lacks is RHO3003; an index on
what is not an array RHO3013, out of range RHO3014; a member of an array
no index selects RHO3016. An endpoint that stops at a leaf names that
node; one that stops at a bundle, or at an array, names it **whole**.

A chain of whole bundles joins them **member by member**: for each leaf
path of the shape, the leaves there are joined as a chain of their own.
Nothing else is made: no net, no label and no node beyond the leaves'
own, so a bundle connect is sugar, and a design written with it
flattens to the nets the same design written leaf by leaf would have. A
whole bundle where single nodes are joined — a net block, `isolated`, or
a chain that also names a single node — is RHO3006, with each leaf as a
needs-review fix-it.

## 3.6 Nominal compatibility

The bundles of one chain MUST be of the first one's interface, its very
definition (RHO3004), and of its shape: a bundle against a bundle, an
array against an array of as many elements (RHO3005). Parameters never
take part. There is no subtyping, no coercion of a record to a leaf, and
no structural equivalence: an author's `Rail` with exactly the members
of `rhoform.lib.iface.Power` is still another interface (conformance
case `elaborate/r59_nominal_mismatch_same_members`). Structural typing
is rejected, as T1 requires.

## 3.7 Members carry no roles

A member declares no pin role: roles stay on pins (T2). That is
sufficient because every interface of this version is side-invariant —
`Power`'s `hv` and `gnd`, `Logic`'s `line` and `ref`, `I2C`'s `scl` and
`sda`, `SpiBus`'s `sck`, `mosi` and `miso`, a `DiffPair`'s `p` and `n`
mean the same thing on either side of a connection — so a member-wise
union is always correct for them. A view's leaves are pins with their
own roles. A bundle port's leaves are module ports, role `passive`,
which the pin-role pass never counts as pins (section 4.2): below the
root they are hierarchical nodes, at the root external terminals. A
member no side of a connection uses therefore makes a net of module
ports alone, which section 4 reports as any such net (RHO3108).

## 3.8 Reference members and the ground architecture

The ground-architecture semantics' GA-1 is normative on references, and
this section is the contract the passes that implement it read
(section 5, the ground architecture, and section 6, voltage domains):

- **`Power.gnd`.** Every `Power` carries the reference member `gnd`. The
  net a `rhoform.lib.iface.Power` bundle's `gnd` lands on is
  ground-typed (GA-1, definition (b)), and `Power.v` is measured from
  that net's ground domain.
- **`ref`.** A member named `ref` is a reference: it MUST be one leaf,
  neither a nested interface nor an array (RHO3015), so that it is one
  node that a pass can find by the name `ref`, and it MUST land on a
  ground-typed net, which the ground pass checks.
- **Union.** A bundle connect joins `gnd` with `gnd` and `ref` with
  `ref`, like every member. Each one is recorded in the elaborated design
  — its interface, the bundles it joined and the nodes it joined at each
  leaf path, kept in memory and not in the IR — which is the provenance
  RHO4006 and RHO4010 read for an interface connection across isolation
  or ground domains.
- **Net-level union suffices.** GA-16's single ground forms through
  ordinary connections: a design that joins its returns with net blocks
  and no bundle at all, as the benchmarks do, has the same single ground
  domain. No check may require a bundle connect for it.

## 3.9 What interfaces feed

- **T2, pin roles:** nothing. Roles stay on pins, and bundle-port leaves
  are never counted (3.7).
- **T5, domains:** `Power.v` as an expectation checked by containment
  (3.3), and the reference members (3.8).
- **T10, budgets:** nothing in this version; `Power` carries no current.

## 3.10 The standard interfaces

The library module `rhoform/lib/iface.rhoform` ([04](../04-elaboration.md#the-standard-library))
is normative by reference: its definitions are the standard interfaces,
named `rhoform.lib.iface.<Name>`.

| Interface | Parameters | Members |
|---|---|---|
| `Power` | `v: voltage` | `gnd`, `hv` |
| `Logic` | | `line`, `ref` |
| `DiffPair` | `impedance: resistance` | `n`, `p` |
| `I2C` | `addr: int`, `freq: frequency` | `ref`, `scl`, `sda` |
| `SpiBus` | | `miso`, `mosi`, `ref`, `sck` |
| `Spi` | | `bus` (a `SpiBus`), `cs` |

T1's `SPI(cs)` is modelled by nesting, not by a parameter that adds a
member: `Spi` is one target's view of a shared `SpiBus` plus its own
chip select, which is what a target on a shared bus has, and a member
set that depended on a parameter would make compatibility depend on
evaluation (3.2).

**Not in this version** (decision D16), each a deliberate omission:

- **Side-relative buses** — a UART's `tx` and `rx`, an SPI described as
  `sdo` and `sdi` — mean different things on the two sides of a
  connection, so a member-wise union would join an output to an output;
  they need a flip operator or roles on members, which v1 does not have.
- **`Usb2`** (a `DiffPair` and a `Power`), until a library part has a
  view to give it.
- **Module-local bundles** (`bus = new I2C` in a module body): bundles
  exist only as ports, so every node belongs to an instance.
- **An I2C address rule** (two targets on one bus with one `addr`):
  `addr` is carried and checked by no rule yet.
- **Importing the library by path:** an interface of the library is
  named by its dotted name.

## 3.11 Diagnostics

The codes, reconciled against the registry:

<!-- reconcile: rhoform.codeset.interfaces:code_rows -->

| Code | Slug | Severity | Fires on |
|---|---|---|---|
| RHO3001 | `definition-kind-mismatch` | error | an interface instantiated, or a module or component typing a port (3.1) |
| RHO3002 | `interface-nesting-cycle` | error | interfaces that contain one another (3.2) |
| RHO3003 | `unknown-member` | error | a member path naming no member (3.5) |
| RHO3004 | `interface-mismatch` | error | bundles of two interfaces in one chain (3.6) |
| RHO3005 | `bundle-shape-mismatch` | error | bundles of one interface, two shapes (3.6) |
| RHO3006 | `bundle-where-node-required` | error | a whole bundle where single nodes are joined (3.5) |
| RHO3007 | `unbound-view-member` | error | a view leaving a leaf unbound (3.4) |
| RHO3008 | `view-binds-unknown-pin` | error | a view binding a pin its component lacks (3.4) |
| RHO3009 | `view-binds-nc-pin` | error | a view binding an `nc` pin (3.4) |
| RHO3010 | `view-members-share-pin` | error | two leaves of one view on one pin (3.4) |
| RHO3011 | `port-name-clash` | error | a bundle port with a member's name, a view with a pin's (3.4) |
| RHO3012 | `interface-array-size-not-literal` | error | a bundle port or member sized by a parameter (3.2) |
| RHO3013 | `index-on-scalar-port` | error | an index on what is not an array (3.5) |
| RHO3014 | `port-index-out-of-range` | error | an index outside a bundle port or member array (3.5) |
| RHO3015 | `reference-member-not-leaf` | error | a `ref` member that is a nested interface or an array (3.8) |
| RHO3016 | `port-array-needs-index` | error | a member of an array no index selects (3.5) |

Block-2 codes keep their meaning for interfaces: RHO2005 and RHO2067 for
a name that names no definition, and RHO2007, RHO2036, RHO2038, RHO2039,
RHO2040, RHO2042 and RHO2046 for what they report of any definition.
