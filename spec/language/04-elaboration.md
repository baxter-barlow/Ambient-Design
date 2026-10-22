# 04 — Elaboration

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

Elaboration turns the parsed sources of one compilation into one
design: a flat list of instances named by hierarchical paths, the nets
that join their ports, and the assertions that check them. Its output is
the netlist IR v0 and its source map, whose shapes are normative by
reference — [`ir/netlist-ir.schema.json`](../../ir/netlist-ir.schema.json)
and [`ir/source-map.schema.json`](../../ir/source-map.schema.json) — and
whose serialization and hashes are defined in
[`ir/README.md`](../../ir/README.md). This section states what the
schemas cannot: which design a source denotes. The cases under
[`conformance/elaborate/`](../conformance/README.md) hold the reference
implementation to it, and a conforming implementation MUST reproduce
them.

This section covers the v0.1 surface. Imports, `component` definitions,
parameter lists, `if`, `for` and arrays land here with the slices that
implement them.

## Inputs, totality and determinism

Elaboration MUST run only on sources that parse with no error-severity
diagnostic ([02 — Grammar](02-grammar.md)). A file that does not parse
is not elaborated: its parse diagnostics are the whole report, because
the tree a parser recovers is the file with its broken lines removed,
and elaborating it would report consequences of text the author never
wrote.

Elaboration is total. On every input that parses it MUST terminate and
MUST produce either one design or at least one error-severity
diagnostic; when any error is reported, no IR is produced. v0.1 has no
recursion, loops or parameter references, so instantiation is the only
construct that could fail to terminate, and an instantiation cycle is
an error (see [Instances](#instances)). Warnings do not prevent the
design.

Elaboration is hermetic and deterministic: it reads the compilation's
source files and nothing else (no environment, clock, network or host
path), and the same sources compiled by the same toolchain MUST yield
byte-identical IR, source map and diagnostic stream.

## The compile root

Every path elaboration records is a POSIX path relative to the
**compile root**: the root given explicitly, else the nearest ancestor
directory of the entry file that holds a `rhoform.toml`, else the entry
file's directory. These paths name the source map's `files`, feed
`source_hash`, and derive definition names (below), so a compilation
moved to another directory or machine elaborates to the same bytes.
Absolute paths MUST NOT appear in the IR or the source map.

## Definitions and the root

A module's IR `definition` is `<module path>.<Name>`, where the module
path is its file's compile-root-relative path without `.rhoform`, with
`/` turned into `.`, and with each segment made an identifier: every
character outside `[A-Za-z0-9_]` becomes `_`, and a segment that would
start with a digit is prefixed with `_`. `boards/blinker-555.rhoform`
gives the module path `boards.blinker_555`; `555/main.rhoform` gives
`_555.main`. Two modules of one file MUST NOT share a name (RHO2001).

The **root** is the unique module of the entry file that no module of
the compilation instantiates. (A `table` that names a module counts as a
use for this purpose; it is an error of its own, see [Tables](#tables).)
More than one candidate is an error (RHO2002). An implementation MAY let
the user name the root explicitly; a name that is not a module of the
entry file is then an error (RHO2003). There is no separate error for
zero candidates: in v0.1 a file whose every module is instantiated by
another necessarily contains an instantiation cycle, which is already
reported, and no root is chosen while a cycle exists.

The root module elaborates to the instance at path `/`, with an empty
`parameters`, the root module's ports, and every flag false.
`header.design_name` is the root module's name, and
`header.language_version` is the entry file's pragma version plus `.0`
(`0.1` gives `0.1.0`).

## Instances

### Module or component

A `new` (or a `table`) names its definition by a qualified name.

- A **single word** MUST name a module defined in the same file; the
  instance is then a module instance. Any other single word is an
  unknown definition (RHO2005).
- A **dotted name** is a library component. v0.1 bundles no library and
  has no imports, so it is an ad-hoc component: its `definition` is the
  dotted name verbatim and its ports are exactly its inline `pin`
  statements.

The instantiation graph MUST be acyclic: a module that contains itself,
directly or through other modules, is an error (RHO2004), reported once
per set of mutually instantiating modules, so elaboration terminates and
every hierarchy is finite.

### Paths

The root's path is `/`. A member named `x` of the instance at path `P`
has path `P/x` (`/x` when `P` is the root). A module instantiated `n`
times therefore gives each of its members `n` distinct paths. Member
names — instance names and table-row names — MUST be unique within
their module (RHO2007), and an assertion MUST NOT share a member's name,
because the two would share one path (RHO2008).

### Ports

A module instance's ports are its module's `port` declarations, each a
name and a role. A component instance's ports are its `pin` statements:
name, role, and the pin's designators as `pin_numbers`, sorted. Port
names are unique per module, pin names per instance, and a designator
appears at most once per pin (RHO2007).

### Facts on an instance

A module instance MUST NOT state `pin`, `part`, `hardware`, or a `no`
flag (RHO2009): its ports and parts come from its definition, and a
module carries no defaults to deny. A component instance states at most
one `part` and at most one `hardware` (RHO2010).

`part "key"` binds the instance to a resolved part whose `lockfile_key`
is the key, which MUST NOT be empty (RHO2015); constraints are optional.
`part abstract` binds it to the constraint set that follows, which MUST
NOT be empty (RHO2014). Constraint names are unique per part (RHO2007).

### Flags

The fabrication flags are `board_only`, `dnp` and `exclude_from_bom`.
Every IR instance carries all three as booleans. A flag is true on an
instance when its own body states it or when any module instance above
it states it: flags stated on a module instance are recorded on that
instance and inherited, by logical OR, by every instance beneath it.

`no <flag>` on a component instance states that the flag is absent. No
v0.1 definition supplies flag defaults, so it does not change the IR.
Stating a flag and its negation on one instance is an error (RHO2012);
stating a flag twice is a warning (RHO2011).

### Hardware

The pinless hardware kinds are `artwork`, `fiducial` and
`mounting_hole`. An instance of a pinless kind MUST declare no pins.

The single-pin hardware kinds are `grounded_mounting_hole` and
`test_point`. An instance of a single-pin kind MUST declare exactly one
pin, of role `passive`; it is a component on a real net (L9b).

A violation of either rule is RHO2013, reported against the `hardware`
statement.

## Values

### Quantities and units

A quantity elaborates to an IR Quantity whose `unit` is the T3
normal-form unit of its nominal ([03 — Literals](03-literals.md), Rule
3) and whose `value` is the nominal's mantissa in that unit. An absolute
or percent tolerance, and a bracketed interval, become `tolerance`: the
absolute lower and upper values in the same unit. Every T3 respelling
of a literal therefore elaborates to identical IR: `0.1uF +/- 10%` and
`100nF (90nF to 110nF)` both give `{"value": 100, "unit": "nF",
"tolerance": {"min": 90, "max": 110}}`.

A bare interval (`3V to 3.6V`) has no nominal, and an IR Quantity
requires one: a bare interval MUST NOT be a parameter or constraint
value (RHO2016). Strings (without their quotes), integers, `true` and
`false` elaborate to themselves.

### Decimal to double

Elaboration is exact: every value it holds is the exact decimal the
source wrote. The IR's numbers are IEEE-754 doubles, so an IR number
MUST be the double nearest the exact decimal, ties to even, spelled as
the canonical profile requires. This is the only point at which a value
is rounded; the source and the elaborated design stay exact, and the IR
is inspectable, not authoritative (P7). An integer whose magnitude
exceeds 2^53, or a quantity whose double would not be finite, is an
error rather than a rounding (RHO2017).

### Arguments

An instance's arguments (`new D(name = value, ...)`) elaborate to its IR
`parameters`. Argument names are unique per instance (RHO2007). v0.1
modules declare no parameters, so the arguments of a module instance
are recorded verbatim and checked against nothing.

## Tables

Each row of `table D [binding] (columns):` elaborates to one component
instance, named by the row's first cell, whose definition is `D`
(resolved as for `new`; a `D` that names a module is an error, RHO2006,
since rows are components). A row MUST carry exactly one value per
column; a row that does not is RHO2018, reported against the table
header with the row as a secondary span. Row names share the module's
member namespace.

A plain column `name` sets the row's parameter `name`. A column
`part.name` sets the row's part constraint `name`, and requires a part
binding in the header (RHO2020). Any other dotted column is an error
(RHO2019), and a column given twice is RHO2007. A header binding
`part "key"` gives each row a resolved part with that key and its
constraint cells; `part abstract` gives each row an abstract part, and
a table whose binding is `part abstract` MUST have at least one
`part.*` column (RHO2014, reported once, against the binding).

A row's ports come from its definition when one is known. v0.1 knows
none, so table rows have no ports, and an endpoint naming a port of a
row is an unknown port (RHO2022).

## Nets

### Endpoints

An endpoint `inst.port` names a port of a member of the same module
(an unknown member is RHO2021; an unknown port, RHO2022). A bare
endpoint names one of the module's own ports (RHO2023). A port whose
role is `nc` MUST NOT appear in any connecting statement, `isolated`
included (RHO2024).

### Union

Net blocks, chains and `isolated` statements are the connecting
statements, and each joins its endpoints into one net. The nets of a
design are the connected components of the graph whose nodes are
`(instance path, port)` pairs, over the connecting statements of every
module instance. A module port is one node, named by the parent as
`inst.port` and by the module itself as `port`, so nets join across the
hierarchy with no special rule. An endpoint MAY appear in several
connecting statements; their nets are then one net. Listing one
endpoint twice within one statement is a warning (RHO2025).

The port an `isolated` statement names MUST be the only member of its
flattened net, also when another member would reach it through a
module port (RHO2026).

Every net a connecting statement creates is emitted, a single-member
net included. Every node of a net is one IR connection, module-port
nodes included (they are non-physical members); a port that no
statement names appears in no connection.

### Names

A net block's name is a **label**. A label declared in the module
elaborated at path `P` other than the root is qualified by that path,
always: `LED` declared in the module instance `/indicator` is the label
`indicator/LED`. A net's name is then its shallowest label, where a
label's depth is the number of segments of `P` (the root's labels are at
depth 0). Two different labels at the shallowest depth of one net are
an error (RHO2027), and a module MUST NOT declare one label twice
(RHO2007). Qualification makes a net's name independent of unrelated
parts of the design, and gives each copy of a module instantiated twice
its own net names.

An unlabelled net is named `N_` followed by its least member, compared
bytewise, where a member is spelled `<instance path without its leading
slash>.<port>`: `/r1`'s port `b` is `r1.b`, `/indicator/d1`'s port `a`
is `indicator/d1.a`, and the root's own port `vin` is `.vin`, giving
`N_r1.b`, `N_indicator/d1.a` and `N_.vin`. This rule is interim: net
naming belongs to R27 (I2), which MUST adopt it or record the change in
the rename ledger. Labels contain no `.` and every derived name does,
so no two nets of a design share a name.

### Domains

The `ground_domain` and `voltage_domain` attributes of every label on a
net merge onto the net. Two different values for one attribute are an
error (RHO2028); an attribute given twice in one net block is RHO2007,
and the empty string is RHO2032. Elaboration merges domain strings
only: it computes no ground-architecture meet and emits no RHO40xx.
Ground nets joined directly are merged into one net, never aliased, so
the T5 checker evaluates GA-2 over merged nets.

## Assertions

An assertion named `name` in the module elaborated at path `P` has the
path `P/name` (`/name` at the root). Assertion names are unique per
module (RHO2007).

Its subject MUST be a net label declared in the same module (RHO2029);
a port name is not a subject in v0.1. In the IR, `subject.net` is the
final name of the flattened net that label belongs to, which an outer
label may have given it.

The static measurement kinds are `efficiency`, `operating_point`,
`power_avg` and `power_rms`. A `static` assertion of any other kind has
no static evaluation rule and is an error (RHO2030).

Bounds take units as values do. `at least Q` and `at most Q` use the
normal-form unit of `Q`. A quantity window `within A to B` uses the
normal-form unit of whichever bound has the larger magnitude (the
larger value on a tie), with both bounds in that unit: `within 900mV to
1.1V` gives `{"unit": "V", "min": 0.9, "max": 1.1}`. A plain number
bound has the unit `"1"`, so a ratio is written as a fraction. A
quantity window is ordered at parse level ([03 — Literals](03-literals.md));
a plain-number window whose lower bound exceeds its upper is an error
(RHO2031).

## Diagnostics

Elaboration reports in block 2 (`RHO2xxx`, see
[06 — Diagnostics](06-diagnostics.md)); the registry
(`rhoform/codes.py`) declares each code, and the conformance suite
holds one reject case for every block-2 code a source can trigger.

- A defect in a module's body is reported once per module, however many
  times the module is instantiated.
- A diagnostic about an IR entity SHOULD carry that entity's identity
  in `entity`: an instance or assertion path when its module is
  elaborated at exactly one path, a net's final name for a defect of a
  flattened net. It carries null when no single entity exists — a
  module elaborated at several paths, a definition, a table header, an
  endpoint naming nothing, a literal. The reject cases pin the reference
  implementation's choice for every code.
- Elaboration diagnostics are reported while the design is being
  built, so their spans are raw spans of the offending source text, not
  resolutions through a source map.
- A fix-it suggesting the one close match for an unknown name has
  applicability `needs-review`.

## The source map

The source map's `files` lists every source file the compilation read,
each with its compile-root-relative path and the sha256 of its exact
bytes, sorted by path. `header.source_hash` is `sha256:` followed by the
hex sha256 of the `rhoform-canonical-json/1` bytes of the list of
`[path, sha256]` pairs, sorted by path. It is excluded from
`design_hash`, so editing a comment moves `source_hash` and leaves
`design_hash` alone.

Every instance path, net name and assertion path has one node, and its
`declaration` is a statement's span, from its first token to its last
token: a block statement includes its body, and the trailing line
break, trailing comment and following comment lines are excluded.

- `/`: the root module's header, `module Name:`.
- An instance: its `new` statement, or its table row.
- A net: the net block carrying the winning label; an unlabelled net's
  shallowest connecting statement, ties broken by instance path, then
  file, then byte offset.
- An assertion: its `assert` statement.

`instantiation_trace` runs innermost first: the declaration, then the
statement instantiating each enclosing module instance, outward to the
root's member; `/` has an empty trace. Entities replicated by a module
instantiated more than once share a declaration span and differ in
their traces. Two declarations are therefore either the same span or
disjoint, never partially overlapping.
