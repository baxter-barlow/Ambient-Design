# 04 — Elaboration

*Rhoform Language Specification · normative, v0.2 and the unfrozen 0.3 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

Elaboration turns the parsed sources of one compilation into one
design: a flat list of instances named by hierarchical paths, the nets
that join their ports, and the assertions that check them. Its output is
the netlist IR and its source map at `ir_version` 2 (`sourcemap_version`
2), whose shapes are normative by reference —
[`ir/netlist-ir.v2.schema.json`](../../ir/netlist-ir.v2.schema.json)
and [`ir/source-map.v2.schema.json`](../../ir/source-map.v2.schema.json) — and
whose serialization and hashes are defined in
[`ir/README.md`](../../ir/README.md). Version 1 is version 0 with net
names that carry an array index mid-name ([Names](#names)), which version
0's schema refuses. Version 2 is version 1 with the source facts syntax
0.3 states ([Syntax 0.3 source facts](#syntax-03-source-facts-unfrozen))
and the one version 1 dropped, an `isolated` net; with those removed, a
version 2 document is the version 1 document of the same design. Version
2 is unfrozen with syntax 0.3, and an implementation MUST write it. This section states what the
schemas cannot: which design a source denotes. The cases under
[`conformance/elaborate/`](../conformance/README.md) hold the reference
implementation to it, and a conforming implementation MUST reproduce
them.

This section covers the v0.1 surface and what syntax 0.2 adds to it:
`component` definitions, parameter lists, parameter references, `if`,
`for`, arrays, imports, and the bundled standard library those
definitions make possible; and the source facts the unfrozen syntax 0.3
adds, which no check reads yet. Every rule stated for v0.1 holds unchanged
for a 0.1 source, with one deliberate exception: the standard library's
reserved prefix. Under a toolchain that also implements 0.2, a dotted
name beginning `rhoform.lib.` names a component of the bundled library
in a 0.1 source as in a 0.2 one (decision E-5, and [Module or
component](#module-or-component)), where v0.1 read every dotted name as
an ad-hoc component whose ports are its inline `pin` statements. A 0.1
source that writes such a name can therefore mean something else than it
did: a name the library does not define is RHO2067, not an ad-hoc
component; an instance of a library component takes its ports from the
definition, so inline `pin` lines MUST restate it exactly (RHO2035) and
an instance with none still has the definition's pins; the library
modules read join the source map and `source_hash`; and a 0.1 file whose
own module path falls under the prefix is not compiled (RHO2068, [The
standard library](#the-standard-library)). That departs from the
strict-superset wording of decision S-1, which promised every valid 0.1
file the same meaning, and it does so on purpose: a reserved prefix that
named the library in one file and an ad-hoc part in another would
reserve nothing. Raising a pragma from 0.1 to 0.2 still changes nothing,
since the prefix means the library under both, and a 0.1 source that
writes no `rhoform.lib.` name, at a path outside the prefix, elaborates
to the same design as under v0.1 (written as IR version 1, which for
such a design differed from version 0 only in `ir_version` and the
`design_hash` that covers it; version 2 adds an `isolated` net's flag and
two empty arrays).

Which files a compilation holds — the entry file and the files it
imports — and how an import's path names a file are the package layer's,
specified in [08 — Packages and imports](08-packages.md); this section
takes those files as given, and adds the standard library modules they
use.

## Inputs, totality and determinism

Elaboration MUST run only on sources that parse with no error-severity
diagnostic ([02 — Grammar](02-grammar.md)), and only on a compilation
the package layer reported no error for ([08](08-packages.md)). A file
that does not parse is not elaborated: its parse diagnostics are the
whole report, because
the tree a parser recovers is the file with its broken lines removed,
and elaborating it would report consequences of text the author never
wrote.

Elaboration is total. On every input that parses it MUST terminate and
MUST produce either one design or at least one error-severity
diagnostic; when any error is reported, no IR is produced. Two
constructs could fail to terminate or run without bound: instantiation,
whose graph MUST be acyclic (see [Instances](#instances)), and
replication, which is budgeted (see
[The replication budget](#the-replication-budget)). Warnings do not
prevent the design.

Elaboration is hermetic and deterministic: it reads the compilation's
source files — the author's, and the standard library modules they
name — and nothing else (no environment, clock, network or host path),
and the same sources compiled by the same toolchain MUST yield
byte-identical IR, source map and diagnostic stream.

## The compile root

Every path elaboration records is a POSIX path relative to the
**compile root**: the root given explicitly (the reference CLI's
`--compile-root DIR`), else the nearest ancestor directory of the entry
file that holds a `rhoform.lock` — the workspace root, above every
package in it, so sibling path dependencies compile without an explicit
root — else the nearest that holds a `rhoform.toml`, else the entry
file's directory. Each of those names matches exactly, letter case
included. A `rhoform.lock` decides the root by its presence; this
version does not read it (the lockfile is R55,
[08](08-packages.md#deviations-recorded)). These paths name the source
map's `files`, feed `source_hash`, derive the definition names of files
no manifest governs (below) and are the `file` of every diagnostic span,
so a compilation moved to another directory or machine elaborates to the
same bytes. Every file an author writes into a compilation lies under
its compile root ([08](08-packages.md#the-compilation)). A
[standard library](#the-standard-library) module is the one exception:
it is the toolchain's file, not the author's, and is recorded by its
library path `rhoform/lib/<module>.rhoform` whatever the compile root.
Absolute paths MUST NOT appear in the IR or the source map.

## Definitions and the root

A module's or component's IR `definition` is `<module name>.<Name>`.
A file's **module path** is its path without `.rhoform`, with `/` turned
into `.`, and with each segment made an identifier: every character
outside `[A-Za-z0-9_]` becomes `_`, and a segment that would start with
a digit is prefixed with `_`. `boards/blinker-555.rhoform` gives the
module path `boards.blinker_555`; `555/main.rhoform` gives `_555.main`.
The path is the file's path within its package
([08](08-packages.md#the-compilation)), and its **module name** is the
package's identity, each segment of the package name made an identifier
the same way, then the module path: `lib/divider.rhoform` of the package
`acme/app` is `acme.app.lib.divider`, wherever the package sits under
the compile root, so a package keeps its names whether it is compiled on
its own or as a dependency, and vendoring or moving it renames nothing
(AMB-144). No package name holds `_`, so two packages never share a
module name. A file no manifest governs has its compile-root-relative
module path as its module name: the benchmarks, which have no manifest,
are named as before. Two definitions of one file MUST NOT share a name:
two modules are RHO2001, and a clash involving a `component` is RHO2034.
The rule maps several paths to one module path — `a-b/x.rhoform` and
`a_b/x.rhoform` are both `a_b.x` — so two files of one package MUST NOT
share one: a `Divider` in each would be two definitions with one name.
The package layer refuses the second of the two files read, at the
import that brings it in (RHO2069, [08](08-packages.md#imports)), so
within a compilation one definition name names one definition.

The **root** is the unique module of the entry file that no module of
the compilation instantiates; a module of an imported file is never a
root candidate. (A `table` that names a module counts as a
use for this purpose; it is an error of its own, see [Tables](#tables).)
Instantiation here is a fact of the text, not of parameter values: a
`new` counts wherever it stands, in an `if` branch not taken included.
More than one candidate is an error (RHO2002), except when the
compilation reports an unresolved single-word definition (RHO2005): a
misspelled `d = new Divder` leaves `Divider` instantiated by nothing, and
the unresolved name is the defect, so it is reported alone and no root
is chosen. Candidates are found in the text, so that defect is too: a
single-word `new` whose one close match is a candidate is reported
(RHO2005, with that match as its fix-it) wherever it stands, in an `if`
branch no instance takes included. Any other misspelling in a branch no
instance takes is not reported (see [Diagnostics](#diagnostics)), so it
does not suppress RHO2002. An implementation MAY let the user name the root explicitly
(the reference CLI's `--root-module NAME`); a name that is not a module
of the entry file is then an error (RHO2003). There is no separate error
for zero candidates: a file whose every module is instantiated by
another necessarily contains an instantiation cycle, which is already
reported, and no root is chosen while a cycle exists. An entry file that
defines no module at all — only `component`s — has no design and is
RHO2047.

The root module elaborates to the instance at path `/`, with the root
module's ports and every flag false. Its `parameters` are empty when it
declares no parameter list, and otherwise its
[environment](#parameters) built from defaults alone: nothing
instantiates the root, so a root parameter with no default is an error
(RHO2037, reported against the parameter with the entity `/`).
`header.design_name` is the root module's name, and
`header.language_version` is the newest pragma version among the
compilation's authored files plus `.0` (`0.1` gives `0.1.0`); the
standard library's modules are the toolchain's and do not count, so a
0.1 design that uses them stays `0.1.0`. Only a 0.2 file can import, so
that is the entry file's version whenever the compilation has more than
one authored file.

## Instances

### Module or component

A `new` (or a `table`) names its definition by a qualified name.

- A **single word** MUST name a module or a `component` defined in the
  same file or imported into it ([08](08-packages.md#names)); the
  instance is then a module instance or a component instance of that
  definition, whose IR `definition` is named by the file that defines
  it. A definition of the file itself is found before an imported one.
  Any other single word is an unknown definition (RHO2005), except a
  name whose import failed, which is reported once, at the import.
- A dotted name under the **reserved prefix** `rhoform.lib.` MUST name a
  component of the [standard library](#the-standard-library):
  `rhoform.lib.<module>.<Component>`, four words, where `<module>` is a
  library module and `<Component>` one of its definitions. The instance
  is then a component instance of that definition, exactly as of a
  `component` defined in the file. Any other name under the prefix — an
  unknown module or component, too few words or too many — is RHO2067.
  This holds in every file of the compilation, the entry file and the
  files it imports alike.
- **Any other dotted name** is an ad-hoc component, as in v0.1: its
  `definition` is the dotted name verbatim and its ports are exactly its
  inline `pin` statements.

The instantiation graph MUST be acyclic: a module that contains itself,
directly or through other modules, is an error (RHO2004), reported once
per set of mutually instantiating modules, so elaboration terminates and
every hierarchy is finite. Like the root, the graph is read from the
text: a `new` in any branch is an edge, whatever the parameters.

### Component definitions

A `component` definition declares a component's pins and nothing else.
Its pins are its ports: name, role, and designators as `pin_numbers`,
sorted. A quoted designator (syntax 0.3) is its text without the
quotes: `"01"` is the `pin_numbers` entry `01`, and `"3"` is the same
designator as `3`. Pin names are unique per definition and a designator
appears at most once per pin (RHO2007).

An instance (or a table row) of a component definition — one of the
file's own or one of the standard library's — gets its ports from the
definition. The instance MAY also state `pin` lines; when it
states any, they MUST restate the definition exactly — the same pin
names, and for each the same role and the same designators. Each
disagreeing pin is RHO2035: a pin the instance states differently or
the definition lacks is reported against the instance's `pin` line, a
definition pin the instance omits against the instance's definition
name. Everything else an instance body may state (`part`, `hardware`,
flags) applies to a component-definition instance as to any component
instance, and the hardware rules below are checked against the
definition's pins.

### Paths

The root's path is `/`. A member named `x` of the instance at path `P`
has path `P/x` (`/x` when `P` is the root), and member `i` of an array
`x` has path `P/x[i]` (see [Arrays](#arrays)). A module instantiated `n`
times therefore gives each of its members `n` distinct paths. Member
names — instance names, array names and table-row names — MUST be
unique among the statements a module instance evaluates (RHO2007), so
the two branches of an `if` may each declare the same name; and an
assertion MUST NOT share a member's name, because the two would share
one path (RHO2008).

### Ports

A module instance's ports are its module's `port` declarations, each a
name and a role. A component instance's ports are its definition's pins
when it instantiates a `component` definition, and otherwise its `pin`
statements: name, role, and the pin's designators as `pin_numbers`,
sorted. Port names are unique per module, pin names per instance, and a
designator appears at most once per pin (RHO2007). A module's ports are
the `port` declarations of its body's top level: a `port` inside an
`if` or `for` is RHO2040, since an interface does not depend on
parameter values.

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
definition supplies flag defaults (a `component` definition states
pins only), so it does not change the IR.
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

## The standard library

The toolchain bundles a standard library of components. A conforming
implementation MUST resolve the reserved prefix `rhoform.lib.` against
its own bundled library and nothing else (see
[Module or component](#module-or-component)); no source, manifest or
search path can add to it or replace it.

The library is a set of **modules**, each a syntax 0.2 file at
`rhoform/lib/<module>.rhoform` in the toolchain, holding `component`
definitions and nothing else, in the canonical form
([07 — Formatting](07-formatting.md)). By the naming rule of
[Definitions and the root](#definitions-and-the-root), applied to that
path, the definition `Resistor` of module `passive` is
`rhoform.lib.passive.Resistor`: the name a source writes is the IR
`definition`. A module name matches exactly as written, letter case
included, on every host.

The library's definitions follow three rules, which the reference
implementation's tests hold it to:

- A **generic** component — a passive, a discrete semiconductor, a
  switch, a generic connector, a mechanical part — declares its pins
  WITHOUT designators. Which pad a resistor's `a` lands on is its
  footprint's, and part data supplies it; a source cannot supply it
  either, since pins an instance restates must equal the definition's.
  A component named for one part (`timer.Ne555`, `regulator.Lm25145`)
  declares that part's pads as designators.
- A **hardware kind's** definition has the kind's arity
  ([Hardware](#hardware)): the definitions of pinless kinds
  (`mech.MountingHole`, `mech.Fiducial`, `mech.Logo`) have no pins, and
  those of single-pin kinds (`mech.TestPoint`,
  `mech.GroundedMountingHole`) exactly one `passive` pin. A definition
  states no `hardware` kind or flag, so an instance still does.
- A definition declares a **parameter list** only where it checks
  something every use agrees on (`passive.Inductor(inductance:
  inductance)`); without one, an instance's arguments are recorded as
  written ([Arguments](#arguments)).

A compilation **reads** exactly the library modules named by the
qualified names of its authored sources — the entry file and every file
of its import closure, each name under the reserved prefix contributing
its third word, in a branch taken or not — and no others. Each module
read is a source file of the compilation: the source map lists it as
`rhoform/lib/<module>.rhoform` with the sha256 of its bytes, so it is
part of `source_hash`. That path is fixed: it is the same whatever the
compile root, whether a `rhoform.toml` governs the entry file, and
wherever the toolchain is installed. Adding a module to the library, or
changing one a design does not name, therefore changes no existing
design's hashes. Diagnostics that point into a library definition
(RHO2035's "defined here") span the library file by the same path.
Because a library module holds component definitions only, it imports
nothing: no author's file is ever read on the library's behalf. No
author's file is compiled whose module path falls under the reserved
prefix — `rhoform/lib.rhoform`, or any file under `rhoform/lib/`,
relative to the compile root — or whose module name does, as every file
of a package named `rhoform/lib` would: its definitions would take the
library's names, and one name cannot name two definitions. Such a file
is refused before it is read (RHO2068), at the import that names it or,
as the entry, at its start, so a library name always means the
toolchain's definition.

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
error rather than a rounding (RHO2017). The integer bound holds for
every integer literal, not only for values: an array size, a `range`
bound, an index or its offset, or a condition's operand past 2^53 is
RHO2017 too, whether or not its branch is taken. Conformance case
`elaborate/accept/a08_decimal_to_double` pins both directions: a bound
written exactly halfway between the doubles 1 and 1 + 2^-52 is `1` in
the IR (ties to even), and one with more significant digits than a
double holds is the nearest double, `3.4`.

### Arguments

An instance's arguments (`new D(name = value, ...)`) elaborate to its IR
`parameters`. Argument names are unique per instance (RHO2007). A
definition with no parameter list — every v0.1 module, a `component`
written without one, an ad-hoc component — checks its arguments against
nothing and records them verbatim. A definition with a parameter list
checks them as [Parameters](#parameters) says.

## Parameters

A `module` or `component` MAY declare a parameter list,
`(name: type [= default], ...)`. An empty list, `()`, is no list: the
definition checks its arguments as one written without a list does,
which is what lets the formatter remove it
([07 — Formatting](07-formatting.md)). Parameter names are unique per list
(RHO2007). The type is a `param_type` word ([02 — Grammar](02-grammar.md)):
`string`, `int`, `bool`, or a quantity dimension. A value has a type: a
string literal is a `string`, an integer an `int`, `true` and `false`
a `bool`, a quantity literal its dimension, and a parameter reference
the type its parameter declares. A bare interval has no nominal and is
never a parameter value (RHO2016) when its dimension matches the
declared type, and is RHO2038 when it does not.

A **default** is a literal of the declared type, or a reference to a
parameter declared EARLIER in the same list, of the same type; it is
evaluated per instance, after the parameters before it. A wrong type is
RHO2038; a reference to anything else is RHO2039.

Each instance of a definition with a parameter list has an
**environment**: every declared parameter bound to its argument, else
its default, in declaration order. Against that list:

- an argument naming no declared parameter is RHO2036;
- a parameter with no default that the instance gives no value for is
  RHO2037, reported against the instance's definition name;
- an argument whose value has the wrong type is RHO2038 (an `int` is not
  a quantity, and a `voltage` is not a `resistance`).

The instance's IR `parameters` are its whole environment, defaults
included: the schema's "fully evaluated parameter environment".

### References

A bare name in a value position is a **parameter reference**. In a
module body it names a parameter of that module, and evaluates to the
value the instance being elaborated binds it to; in an `if` condition, a
`range` bound or an index it may also name a loop variable of an
enclosing `for`. Anything else is RHO2039. A reference resolves when its
module instance is elaborated, so two instances of one module with
different environments elaborate different values from one body.

## Conditionals

`if <condition>:` with an optional `else:` elaborates exactly one of
its blocks per module instance, chosen by evaluating the condition in
that instance's environment; with no `else`, a false condition
elaborates nothing. A block's statements then elaborate as if written in
place of the `if`, so an instance or a net declared in a branch exists
only in the instances that take it.

The condition is a reference to a `bool` parameter, or `NAME op value`
where `op` is one of `==`, `!=`, `<`, `<=`, `>`, `>=`. `NAME` is a
parameter or loop variable; `value` is a literal or a reference, of
the same type as `NAME` (RHO2038 otherwise). Comparison is exact:

- `int`s compare as integers, `bool`s and `string`s only with `==` and
  `!=` (an ordering of them is RHO2038);
- quantities compare as exact decimals in the base unit of their common
  dimension, a toleranced quantity by its nominal. A literal compared
  with MUST be exact: a toleranced or bracketed literal, or a bare
  interval, has no single value to compare and is RHO2038.

There are no connectives; nested `if`s give conjunction. A `port`
declaration inside an `if` is RHO2040.

## Loops

`for v in range(N):` and `for v in range(A, B):` elaborate their block
once per integer `v` from `A` (default 0) up to but excluding `B` (or
`N`), in increasing order; a range whose end does not exceed its start
runs zero times. Each bound is an integer literal, or a reference of
type `int` to a parameter or an enclosing loop variable (RHO2038
otherwise). The loop variable is an `int` in scope in its block only,
and it MUST NOT have the name of a parameter of the module or of an
enclosing loop variable (RHO2041).

A loop body holds connections — net blocks, chains, `isolated` — and
nested `if`s and `for`s. An instance declaration or table inside a
`for` is RHO2040 (arrays, not loops, replicate instances), as is an
assertion (every iteration would declare one path) and a `port`
declaration. A net block inside a loop declares its label once however
many times it runs: every iteration joins its endpoints to the one
labelled net. Two different net blocks declaring one label in one
module are still RHO2007.

## Arrays

`x = new D[N](...)` declares an array: `N` member instances of `D`,
named `x[0]` to `x[N-1]`, each with the path `P/x[i]` and with the one
set of arguments, body facts and declaration span the statement gives.
`N` is an integer literal or a reference of type `int` to a parameter
(RHO2038 otherwise), and MUST be at least 1 (RHO2042). The array's name
is one member name of its module.

An endpoint names an array member with an index: `x[i].port`. An index
is an integer, a reference of type `int` to a parameter or loop
variable, or either plus or minus an integer (`x[i + 1]`, `x[i - 1]`).
Its value MUST select a member, `0 <= i < N` (RHO2043, whose `endpoint`
spells the evaluated index). An array named without an index where one
instance is required — `x.port` — is RHO2044; an index on an instance
that is not an array is RHO2045; and an indexed name with no port is not
a port of the module (RHO2023).

## The replication budget

Elaboration counts the loop iterations and array members it expands,
over every module instance of the design: a loop of 8 iterations in a
module instantiated 4 times counts 32. The total MUST NOT exceed
**4096**, and a module body whose own expansion would exceed it is an
error even when nothing instantiates the module. A design over the
budget draws one RHO2046, with no entity — one for the design, not one
per instance of a module whose body crosses the limit, as the
per-instance rule of [Diagnostics](#diagnostics) would give — against a
replicating statement whose expansion takes the count past the limit
(which one, when several do, is the reference implementation's choice,
pinned by its reject case), and no IR. The budget is what keeps a
source that parses from making elaboration slow; v0.1 sources replicate
nothing and are unaffected.

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

A row's ports come from its definition when one is known: the pins of a
`component` definition, the file's own or the standard library's, so
`row.pin` is an endpoint like any instance's. A row of an ad-hoc
component (a dotted name outside the reserved prefix) has no ports, and
an endpoint naming a port of such a row is an unknown port (RHO2022). When `D` is a `component`
definition with a parameter list, the plain columns are its arguments:
a column naming no parameter is RHO2036, a parameter with no default and
no column is RHO2037 (reported once, against the table's definition
name), a cell of the wrong type is RHO2038, and each row's IR
`parameters` are its environment.

## Nets

### Endpoints

An endpoint `inst.port` names a port of a member of the same module
(an unknown member is RHO2021; an unknown port, RHO2022), and
`x[i].port` a port of an array member (see [Arrays](#arrays)). A bare
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
module port (RHO2026). The net it makes is thereby declared an
intentional single-member net: the elaborated design records that, for
the check stage's single-pin-net rule (L9b,
[05](05-static-types.md)), and IR version 2 carries it as the net's
`isolated`, present only when true (version 1 did not carry it).

Every net a connecting statement creates is emitted, a single-member
net included. Every node of a net is one IR connection, module-port
nodes included (they are non-physical members); a port that no
statement names appears in no connection.

### Names

A net block's name is a **label**. A label declared in the module
elaborated at path `P` other than the root is qualified by that path,
always: `LED` declared in the module instance `/indicator` is the label
`indicator/LED`, and `LED` in `/cells[2]` is `cells[2]/LED`. A net's
name is then its shallowest label, where a
label's depth is the number of segments of `P` (the root's labels are at
depth 0). Two different labels at the shallowest depth of one net are
an error (RHO2027), and a module MUST NOT declare one label twice
(RHO2007). Qualification makes a net's name independent of unrelated
parts of the design, and gives each copy of a module instantiated twice
its own net names.

An unlabelled net is named `N_` followed by its least member, compared
bytewise, where a member is spelled `<instance path without its leading
slash>.<port>`: `/r1`'s port `b` is `r1.b`, `/indicator/d1`'s port `a`
is `indicator/d1.a`, the root's own port `vin` is `.vin`, and
`/leds[0]`'s port `a` is `leds[0].a`, giving `N_r1.b`,
`N_indicator/d1.a`, `N_.vin` and `N_leds[0].a`. This rule is interim: net
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

`ground_kind` (syntax 0.3) is no domain label, and is not merged: labels
of one net that give it different values are no elaboration error, but
GA-2's question, which the check stage asks of every site. The net's IR
`ground_kind` is the one value its sites agree on, and absent when they
disagree or none gives it.

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

An assertion ending `warning` (syntax 0.3) has the IR `severity`
`"warning"`; one without it has none, and is an error when it fails.

## Syntax 0.3 source facts (unfrozen)

Syntax 0.3's statements state facts no check reads yet; the check stage
gives them their meaning ([05](05-static-types.md)). Elaboration keeps
each one, resolved to the entity it is about, and refuses only what
needs no electrical meaning to refuse: a target that names nothing it
may name, a fact stated twice, a rule naming a pin its component does
not have. Each is reported per definition or per instance by the rules
of [Diagnostics](#diagnostics).

### Rules and sides

A component definition's rules and sides are checked once per
definition: every pin a rule or side names is one of the component's
(RHO2082, with a did-you-mean fix-it when one pin is close), a side's
name is declared once in its component (RHO2007), and a parameter
reference in a rule's value names one of the component's parameters
(RHO2039). Each component instance's IR `rules` are its definition's
rules and sides, a parameter reference evaluated in the instance's
environment: `regulate out from in = vout` on an instance created with
`vout = 1.8V` is `{"word": "regulate", "pins": ["out"], "from": "in",
"value": {"unit": "V", "value": 1.8}}`, and a side is `{"word": "side",
"name": ..., "pins": [...]}`. Pins keep the order written; the list is
in the order of its entries' canonical bytes. An instance with no rules
has no `rules`, and a module instance never does.

A `rule` statement's target MUST be a component member of its module,
an array member indexed (RHO2080), and its pins that component's
(RHO2082); its value is evaluated in the module's environment and its
loop variables. Every `rule` statement naming one member replaces that
member's definition rules with the statements' rules, in each instance
of the module; the definition's sides stay, since a side is what the
part is, not how it is used.

### Annotations

`supply`, `draw` and `waive` statements elaborate to the IR
`annotations`, each `{kind, scope, target}` with a `supply` or `draw`'s
`bounds` (as an assertion's) or a `waive`'s `code` and `justification`.
`scope` is the path of the module instance whose body states it, so a
statement in a module instantiated twice is two annotations, as its
assertions are two. The array is in the order of its entries'
canonical bytes.

A target resolves within its module. A `supply` or `draw` names a net
label (`{"net": <the net's final name>}`) or a pin of a member, an
array member indexed (`{"port": {"instance": <path>, "port": <name>}}`).
A `waive` names a member (`{"instance": <path>}`), a net label, or an
assertion of the module (`{"assertion": <path>}`). A target that names
none of those — an unknown name, a pin of a module that has no such
port, an array without an index, an index out of range, a module
instance for a `rule`, a name that is both a member and a label — is
RHO2080, whose `reason` says which. One statement of a fact per target:
a second `supply`, or a second `draw`, of the same dimension for one
target, or a second `waive` of one code for one target, in one module,
is RHO2081. A voltage window and a current capability for one target are
two facts.

What a target may be for each kind, which dimensions a bound may have,
and which codes may be waived are the owning check pass's (spec 05),
reported in its own block-3 range.

## Diagnostics

Elaboration reports in block 2 (`RHO2xxx`, see
[06 — Diagnostics](06-diagnostics.md)); the registry
(`rhoform/codes.py`) declares each code, and the conformance suite
holds one reject case for every block-2 code a source can trigger.

- What needs no parameter value is checked once per definition, over
  its whole body, branches not taken and loops that run zero times
  included: the names references resolve to, the types of arguments,
  defaults, conditions, bounds, sizes and indexes (RHO2036–RHO2039,
  RHO2041), and where a statement may stand (RHO2040). Every other rule
  applies to the statements an instance actually elaborates.
- A module's body is elaborated once per distinct environment the
  design gives it (a module with no parameter list has one, the empty
  one), and a module the design builds no instance of once under its
  defaults. That includes a module whose only `new` stands in a branch
  no instance takes, so a default that is invalid on its own (an array
  size of 0, say) is reported even when every `new` of the module passes
  a valid value; give such a parameter a valid default. This is a known
  limitation of the current rule, not a promise. Nothing of that defaults
  run reaches the check stage, which checks only the instances the walk
  from the root built ([05](05-static-types.md#what-a-pass-never-sees)).
  A defect found under every environment of its module — every defect of
  a v0.1 body — is reported once per module, however many times the
  module is instantiated. A defect found under some environments only depends
  on the parameter values, and is reported once per instance whose
  environment shows it, in path order.
- The same rule holds for a defect of a flattened net (RHO2026 to
  RHO2028), counted against the module whose body holds the statement
  the diagnostic points at. Each instance of that module makes its own
  copy of the defect, alike but for instance paths. When instances
  under every environment of the module show it, the copies are one
  diagnostic, carrying an entity only when every copy names the same
  net. Otherwise each instance that shows it reports its own copy,
  carrying its own net as the entity (RHO2027, which names no net, the
  module instance's path); copies that come out the same diagnostic (two
  instances whose defect lands on one net) are one.
- A defect a loop body shows identically in several iterations is
  reported once: such diagnostics name the endpoint as written
  (`taps[i]`), and only those that depend on the index's value (RHO2043,
  RHO2026) spell it evaluated.
- A diagnostic about an IR entity SHOULD carry that entity's identity
  in `entity`: an instance or assertion path when its module is
  elaborated at exactly one path, a net's final name for a defect of a
  flattened net. It carries null when no single entity exists — a
  module elaborated at several paths, a definition, a table header, an
  endpoint naming nothing, a literal — except that a defect reported
  per instance always carries one: the entity it is about within that
  instance, else the module instance's own path. The reject cases pin
  the reference implementation's choice for every code.
- Elaboration diagnostics are reported while the design is being
  built, so their spans are raw spans of the offending source text, not
  resolutions through a source map.
- A fix-it suggesting the one close match for an unknown name has
  applicability `needs-review`. For RHO2067 the words of the name are
  compared one at a time — a module name with the library's modules, a
  component name with its module's definitions — because whole names
  share their prefix and would all look close; the fix-it is the whole
  corrected name, offered only when exactly one word was wrong.

## The source map

The source map's `files` lists every source file the compilation read —
the entry file, every file of its import closure, and the standard
library modules they use — each with its compile-root-relative path (a
standard library module, its library path) and the sha256 of its exact
bytes, sorted by path. A `rhoform.toml` is configuration, not source,
and is not listed; what it changes about the compilation shows in which
sources are read. `header.source_hash` is `sha256:` followed by the
hex sha256 of the `rhoform-canonical-json/1` bytes of the list of
`[path, sha256]` pairs, sorted by path. It is excluded from
`design_hash`, so editing a comment moves `source_hash` and leaves
`design_hash` alone.

Every instance path, net name and assertion path has one node, and so,
in version 2, does every interface (keyed `<instance path>.<port>`, none
yet); its
`declaration` is a statement's span, from its first token to its last
token: a block statement includes its body, and the trailing line
break, trailing comment and following comment lines are excluded.

- `/`: the root module's header, `module Name:`.
- An instance: its `new` statement, or its table row. The members of an
  array share their `new` statement.
- A net: the net block carrying the winning label; an unlabelled net's
  shallowest connecting statement, ties broken by instance path, then
  file, then byte offset. Every iteration of a loop shares the
  statement's span.
- An assertion: its `assert` statement.

`instantiation_trace` runs innermost first: the declaration, then the
statement instantiating each enclosing module instance, outward to the
root's member; `/` has an empty trace. Entities replicated by a module
instantiated more than once share a declaration span and differ in
their traces. Two declarations are therefore either the same span or
disjoint, never partially overlapping.
