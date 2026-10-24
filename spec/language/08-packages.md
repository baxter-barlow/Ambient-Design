# 08 — Packages and imports

*Rhoform Language Specification · normative, v0.2 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

A package is a directory of Rhoform sources governed by a `rhoform.toml`
manifest. This section states which files one compilation holds, how an
`import` names a file and the definitions in it, and what the manifest
must say. The rules are those of the Rhoform package specification
(R14a, *Package identity and registry rules*), whose clause ids appear
in parentheses; this section restates the part the reference
implementation compiles today and records, under
[Deviations](#deviations-recorded), where it stops short of the package
specification and which roadmap item closes each gap. The cases under
[`conformance/packages/`](../conformance/README.md) hold the reference
implementation to it.

## The compilation

A compilation is its **entry file** plus that file's **import closure**:
every file it imports, every file those import, and so on. Its compile
root is defined in [04 — Elaboration](04-elaboration.md#the-compile-root),
and every file of the compilation MUST lie under it; in this version the
compile root is also the package specification's workspace root, which
is why the nearest `rhoform.lock` (L1) decides it ahead of the nearest
`rhoform.toml`. The compilation also holds the
[standard library](04-elaboration.md#the-standard-library) modules its
files name under `rhoform.lib.`; those are the toolchain's own files,
recorded by their fixed library path, and are not imported: no import
path names one, and no manifest or `[deps]` entry is needed to use one.

Every name on a path — a directory, a file, a manifest — matches the
file system's name exactly, letter case included, on every host: a name
that matches only when case is ignored names nothing, so a
case-insensitive file system resolves no path a case-sensitive one
reports missing, and one file never has two spellings in one
compilation.

A file belongs to the package rooted at the nearest directory, from the
file's own up to the compile root, that holds a `rhoform.toml`. A file
with no such directory belongs to no package: the compile root then
plays the package's part, with no manifest and no dependencies. A
manifest above the compile root is not read.

Compilation is hermetic (L2, I3). It reads the files of the import
closure, the manifests that govern them — the entry file's package's
and, transitively, those of the packages it depends on — the compile
root's `rhoform.lock` when there is one ([The lockfile](#the-lockfile)),
the standard library modules those files name, and, at the check stage,
the part records the picks the design uses name
([05 section 9](05-static-types/09-part-data.md)), and nothing else: a
directory of the author's is listed only to match the spelling of a name
on a path being resolved (as the toolchain's own library directory is,
to match module names exactly), no network is opened, and a
dependency's source files are read only when something imports them.
Nothing a symbolic link leads outside the compile root is read: an
import or a dependency reaching one is the error above, and the entry
file or a governing manifest, which no statement names, is an
operational failure (the CLI's exit 2). When the
package layer reports any error, the compilation is not elaborated.

## The manifest

The manifest is a TOML 1.0.0 file named `rhoform.toml` at the package
root (§3.1). A file that is not valid UTF-8 TOML is RHO2048, reported at
the position the TOML reader names. Its schema is closed (M1): the only
top-level tables are `package` and `deps`, and an unknown table or key
anywhere is RHO2049, reported at the key. Every manifest diagnostic
spans the offending key or value in `rhoform.toml`; a missing key
(RHO2050) spans the key of the table that lacks it.

### [package]

The [package] keys are `description`, `exclude`, `license`, `name`,
`requires-rhoform`, `reserved-namespace-ack` and `version`.
The required [package] keys are `license`, `name`, `requires-rhoform`
and `version`.

- `name` is a package name: exactly two segments joined by `/`, each
  matching `[a-z](?:-?[a-z0-9])*`, each at most 63 bytes and the whole
  at most 100 (N1, N2, N4). Names compare byte-wise (N3). A name that
  breaks a rule is RHO2052.
- `version` is a SemVer 2.0.0 version, `MAJOR.MINOR.PATCH` with an
  optional pre-release, and MUST NOT carry build metadata (V1, V2);
  otherwise RHO2053.
- `requires-rhoform` is a version range (V8, below); otherwise RHO2054.
- `license` is an SPDX license expression: identifiers (an optional
  trailing `+`, `LicenseRef-` and `DocumentRef-...:LicenseRef-` forms
  included) joined by `AND`, `OR` and `WITH`, with parentheses.
- `description` is a string of at most 500 bytes; `exclude` an array of
  strings; `reserved-namespace-ack` a boolean.

A value of the wrong type, or a `license`, `description` or `exclude`
that breaks its rule, is RHO2051.

The reserved namespaces are `rho` and `rhoform`. A manifest naming a
package in one of them MUST also state `reserved-namespace-ack = true`
(R1, R2); otherwise RHO2055.

### Versions and ranges

A version range is exactly `^X.Y.Z` or `=X.Y.Z` (L9). No other operator
exists. `^X.Y.Z` admits every release version from `X.Y.Z` up to, not
including, `(X+1).0.0`, or `0.(Y+1).0` when `X` is `0`: each `0.Y` line
is its own window. A `^` range names a release version, and a
pre-release version is admitted only by an `=` range naming it exactly
(V3). Build metadata appears in no range (V2).

### [deps]

Each key of `[deps]` is a package name (RHO2052 otherwise) and each
value a table, written inline or as a `[deps."<name>"]` table, which TOML
makes the same value. The dependency keys are `git`, `integrity`,
`path`, `rev` and `version`.

- `version` is required (RHO2050) and is a range (RHO2054).
- `path` is the dependency's package root, relative to the directory of
  the manifest that declares it. It MUST lie under the compile root,
  also once symbolic links are resolved, and
  MUST hold a `rhoform.toml` that declares the package the key names, at
  a version the range admits (RHO2057). One package name has one source
  across the whole compilation: two declarations of one name at
  different paths are RHO2057, reported at the second one read (L7a).
- A bare version string is RHO2056: it implies a registry, and v1 has
  none (M2). So is a dependency with neither `path` nor `git`, and the
  sources this version does not read (see
  [Deviations](#deviations-recorded)).

A dependency whose own manifest is in error is reported in that
manifest, and an import from it is not reported again.

## Language versions

A file's **language version** is its pragma's version plus `.0`: syntax
`0.2` is language version `0.2.0`. The toolchain implements the language
version of each syntax version in
[01 — Lexical structure](01-lexical-structure.md#syntax-versions).

- A package whose `requires-rhoform` admits none of the toolchain's
  language versions is refused outright (V10): RHO2058, reported at the
  range, and none of its files is compiled.
- A file whose language version lies outside its package's
  `requires-rhoform` is refused (V9, V10): RHO2059, reported at its
  pragma with the range as a secondary span. The file's imports are not
  followed.
- A file no manifest governs is held to [01](01-lexical-structure.md)'s
  pragma rule alone.

Both diagnostics name the package or file, the declared range or
version, and the toolchain's versions, as V10 requires.

## Imports

An import line ([02](02-grammar.md#imports)) names definitions and a
path. The path names one file:

- A path beginning `./` or `../`, or holding no `/`, is a **module of
  the importing file's own package** (X1). It is relative to the
  importing file's directory and normalized lexically, and the file is
  identified by that path. It MUST NOT leave that package: neither above
  its root nor into a directory below it that holds a `rhoform.toml` of
  its own (RHO2061).
- Any other path is `<namespace>/<name>/<module>...`: its first two
  segments are a **package the importing package lists in `[deps]`**
  (X2), and the rest a module path within that package's root. A package
  not in `[deps]` is RHO2063: there are no implicit dependencies, and a
  file no manifest governs has none. The module path MUST NOT hold `.`
  or `..` segments, and MUST NOT lead into a nested package (RHO2061).

A module path names `<module path>.rhoform`; the suffix may also be
written. The file MUST exist (RHO2060); when the path misses a file only
by letter case, the diagnostic carries the file system's spelling as a
fix-it. A symbolic link on the path is
followed only when what it leads to is still inside the package the
path is in, so neither form of import can leave its package, or the
compile root, through one (RHO2061). A path naming a file whose module
path or module name falls under the reserved prefix `rhoform.lib.` is
RHO2068, and so is such a file as the entry
([04](04-elaboration.md#the-standard-library)). No two files of one
package may have one module path
([04](04-elaboration.md#definitions-and-the-root)), since their
definitions would share IR names: a path naming a file whose module path
a file of its package read earlier already has — `./a-b/x` after
`a_b/x.rhoform`, both `a_b.x` — is RHO2069, and the file is not read.
Files of two packages never collide: their module names begin with two
different package identities. Files are read from the
entry breadth first, each file's imports in source order, so the file
refused is always the second of the two that order reaches. A path that
is empty, absolute, holds an empty segment, ends in `.` or `..`, or is
not `./`-relative and whose first two segments are not a package name or
name no module, is RHO2062.

The imports of a compilation MUST NOT form a cycle (RHO2064). A cycle is
reported once, naming its files in path order, at the first of its
import statements by file path and then position, with its other import
statements as secondary spans; which file was the entry does not change
the report.

### Names

Each imported name MUST be a module or `component` the imported file
itself defines (RHO2065): a file's imports are not re-exported. An
imported name is bound in the importing file, so it MUST NOT also name
a definition of that file or be imported twice (RHO2066). An imported
name is used exactly as a definition of the file: a single word in a
`new` or `table` ([04](04-elaboration.md#module-or-component)). Its
instances' IR `definition` is named by the file that defines it
([04](04-elaboration.md#definitions-and-the-root)): `Divider` imported
from `lib/divider.rhoform` of the package `acme/app` is
`acme.app.lib.divider.Divider`, and `Led` from the dependency
`acme/parts`'s `leds.rhoform` is `acme.parts.leds.Led`, wherever either
package sits under the compile root. A name whose import failed is not
reported again where it is used.

## Files and hashes

`header.source_hash` and the source map's `files` cover every source
file the compilation read — the entry file, its import closure, and the
standard library modules they name — by compile-root-relative path, a
library module by its fixed path `rhoform/lib/<module>.rhoform`
([04](04-elaboration.md#the-source-map)). A manifest is configuration,
not source, and is not listed; nor is the lockfile, nor a part record.

## The command line

`rhoform check FILE` compiles FILE as an entry. `rhoform check DIR`
compiles as entries the `*.rhoform` files under DIR that no other file
named on the command line reaches through its imports without being
reached back from it: a library is checked through the files that
import it, and a file imported only within a cycle is still an entry, so
the cycle is reported. The package specification defines no entry-point
key (`[package]` is closed), so no manifest names entries. A defect two
compilations of one run share is reported once.

## The lockfile

`rhoform.lock` (R55; R14a L1, L4, L5; D1; I2, I3) records what a
workspace resolved: one file at the compile root, the workspace root,
named so exactly. It is **optional** in this version (decision D30): with
none, every section is **unlocked** — path dependencies are read in
place, and a `part abstract` has no pick — which
[Deviations](#deviations-recorded) records against L3. A `part "key"` is
an error with no lockfile too ([05 section 9](05-static-types/09-part-data.md#92-picks)).
Its shape is [`rhoform/lockfile.schema.json`](../../rhoform/lockfile.schema.json),
normative by reference, one immutable schema file per `lockfile_version`
as the IR has; a reader refuses a version it does not implement.

### Canonical bytes

A lockfile's bytes MUST be the canonical serialization of its content:
`json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)`
followed by one line feed. That is UTF-8 with no byte-order mark; object
keys sorted; a two-space indent, `": "` after a key and one member or
element per line; `[]` and `{}` for empty containers; strings escaping
exactly `"`, `\` and the C0 controls (as `\b`, `\f`, `\n`, `\r`, `\t`
or `\u00xx`); integers only, no key repeated in an object, no NaN or
infinity. JavaScript's `JSON.stringify(sorted, null, 2)` writes the same
bytes: every key the schema admits is ASCII, so code-point and UTF-16
key orders agree. A reader refuses any other bytes, so one lockfile
state has one byte string, its diff is a diff of states, and every
diagnostic span in it is exact.

### Sections

The top level holds `lockfile_version` and up to three sections, which
share one framing: each is `{inputs, entries}`. An **input** is a file
the section's entries rest on, its path and the `sha256:` hash of its
exact bytes. An input path is relative and POSIX — no empty, `.` or `..`
segment, no backslash — and names a file under the compile root, except
that a path beginning `rhoform/` names the toolchain's own file, as the
source map's `rhoform/lib/` paths do; of the toolchain, a lockfile names
only its bundled part store, `rhoform/parts/`. Inputs are sorted by
path, each once.

- **`packages`** (L5): its inputs are the `rhoform.toml` of each package
  resolution read; each entry is one package — its `name`, `version`,
  `source` (`{"path": <package root>}`, `.` for the compile root),
  `manifest` (an input), `requires_rhoform` (the language range the
  resolution admits it under) and `content_hash`. The archive content
  hash (T2, G8–G10) is not built, so `content_hash` is `null` and
  `unavailable_reason` says why (`canonical-archive-unavailable`).
  Entries are sorted by name, each once.
- **`parts`** (D1): its inputs are part records; each entry is a
  **keyed pick**, `{key, part_id, manufacturer, mpn, record}`, the
  record a `part "key"` with that key stands for, or an **instance
  pick**, `{design, instance, constraints, part_id, manufacturer, mpn,
  record}`, the record picked for the `part abstract` of the instance
  whose identity path is `instance` in the design whose root definition
  is `design`, made for the constraints whose digest is `constraints`
  ([05 section 9.5](05-static-types/09-part-data.md#95-instance-picks)).
  `record` is an input; `part_id`, `manufacturer` and `mpn` echo the
  record so the file reads on its own. Keyed picks come first, sorted by
  key, then instance picks, sorted by design and instance; each selector
  once.
- **`renames`** (I2): each entry `{design, path, origin}` keeps the
  identity `origin` for the entity now at `path`, sorted by design and
  path, each path and each origin once within a design. Its inputs are
  reserved for R27's identity baseline and are empty.

The keys of each object, reconciled against the reader:

<!-- reconcile: rhoform.lockfile:key_rows -->

| Object | Key | Required |
|---|---|---|
| the lockfile | `lockfile_version` | yes |
| the lockfile | `packages` | no |
| the lockfile | `parts` | no |
| the lockfile | `renames` | no |
| a section | `entries` | yes |
| a section | `inputs` | yes |
| an input | `path` | yes |
| an input | `sha256` | yes |
| a package entry | `content_hash` | yes |
| a package entry | `manifest` | yes |
| a package entry | `name` | yes |
| a package entry | `requires_rhoform` | yes |
| a package entry | `source` | yes |
| a package entry | `unavailable_reason` | no |
| a package entry | `version` | yes |
| a keyed pick | `key` | yes |
| a keyed pick | `manufacturer` | yes |
| a keyed pick | `mpn` | yes |
| a keyed pick | `part_id` | yes |
| a keyed pick | `record` | yes |
| an instance pick | `constraints` | yes |
| an instance pick | `design` | yes |
| an instance pick | `instance` | yes |
| an instance pick | `manufacturer` | yes |
| an instance pick | `mpn` | yes |
| an instance pick | `part_id` | yes |
| an instance pick | `record` | yes |
| a rename | `design` | yes |
| a rename | `origin` | yes |
| a rename | `path` | yes |

An `x_` member at the top level is the schema's reserved annotation slot
(a schema-gate fixture's declaration); the reader refuses every one, so
nothing in a lockfile a compilation reads goes unread.

### What a compilation checks

The package layer reads the lockfile once the import closure is read,
and checks, each step only once the one before it passed: that it is
JSON (`RHO2070`, at the decoder's position); that it is in canonical
layout (`RHO2071`, alone, spanning the line of the first byte that
differs, with a machine-applicable fix-it that rewrites the file and
changes no value); its version (`RHO2072`); its schema and the
invariants a schema cannot state — the orders and uniqueness above, each
entry naming an input of its own section, the input paths and the
renames rules (`RHO2073`, at the offending value); and what this version
refuses rather than ignores (`RHO2075`): every rename-ledger entry,
until R27 applies the ledger, and a non-null `content_hash`, which
nothing could verify. When nothing else was reported, the packages
section is then held to the compilation: every manifest it read MUST be
an input with its bytes' hash, and every package it read MUST have an
entry agreeing with its manifest on source, manifest and version, whose
range is contained in the manifest's `requires-rhoform` and admits a
language version the toolchain implements (`RHO2074`, naming the
manifest or the package). Any of these errors stops the compilation
before elaboration. A pick is checked by the check stage, which reads
the records the design's picks name
([05 section 9](05-static-types/09-part-data.md)).

A workspace's lockfile serves every compilation of it, and one
compilation sees only its own closure: an entry or input none of its
packages or instances names belongs to another compilation and is not
checked here. Nothing yet checks a workspace's lockfile as a whole.

<!-- reconcile: rhoform.lockfile:code_rows -->

| Code | Slug | Severity |
|---|---|---|
| RHO2070 | `lockfile-not-json` | error |
| RHO2071 | `lockfile-not-canonical` | error |
| RHO2072 | `lockfile-version-unsupported` | error |
| RHO2073 | `lockfile-invalid` | error |
| RHO2074 | `lockfile-packages-stale` | error |
| RHO2075 | `lockfile-entry-unsupported` | error |

### Picks

`pick_key(key)` and `pick_instance(design, instance)` are how the check
stage finds a pick: the entry, or **unlocked** with its reason —
`no-lockfile`, `no-parts-section` or `no-pick`. An instance pick is
keyed by identity, the instance's path, never by a spelling of its
definition; a ledgered rename would keep its pick, once R27 applies
the ledger.

### Writers

Each section has one writer: `packages` is `rhoform pkg lock`'s,
`parts` is `rhoform parts pin` and `unpin`'s (R28), and `renames` the
rename refactor's (R27). A writer reads the whole file, replaces only its
own section, writes the file canonically — so every other section comes
out byte for byte as it was — and replaces it atomically. None of the
three exists yet; `rhoform/lockfile.py` holds the pure half of the
contract (`replace_section`, `canonical_bytes`, `input_entry`,
`constraints_digest`).

## Deviations, recorded

This version implements §1 (identity), §2.1 and §2.3 (versions and
language versions), §3 (the manifest), §4.3 (ranges) and §7 (imports)
of the package specification, with these differences; each is a
diagnostic or a documented absence, never a silent skip:

- **The lockfile is optional.** L3 requires `rhoform.lock` for
  compilation and fails one that is absent; this version compiles
  without one (decision D30), unlocked, reading path dependencies in
  place, and a section the file lacks is unlocked too. Nothing is
  resolved, so there is no MVS selection (L6–L8) beyond the checks of
  [`[deps]`](#deps).
- **Staleness is per input file.** L3 decides a path dependency's
  staleness by the canonical-archive content hash of the package as
  well as its manifest's hash; the archive is not built (G8–G10), so
  this version records and checks the manifests' bytes alone, an edit to
  a dependency's sources is not seen, and `content_hash` is null with
  its reason. Conformance to L5 is not claimed.
- **The L8 intersection** is checked for containment in each package's
  own range, not recomputed across the closure.
- **No writer.** Nothing writes `rhoform.lock` yet: `pkg lock`, `parts
  pin`/`unpin` and the rename refactor are R14a O1, R28 and R27.
- **Renames are refused** (`RHO2075`) until R27 applies the ledger.
- **Path dependencies only.** A `git` source (and with it `rev`, M3) is
  RHO2056 until the lockfile and fetching land with R55; `rev` without
  `git` is RHO2056 too.
- **No archive.** The canonical package archive (G8–G10) is not built,
  so `integrity` (M4), which only it could verify, is RHO2056 rather
  than ignored, and `exclude` is checked for type only.
- **No `rhoform pkg`.** `pkg lock`, `pkg vendor`, `pkg check` and
  `pkg semver-check` (L1, O1, V7, V9) do not exist; V9's containment is
  checked at compile time for every file a compilation reads.
- **SPDX syntax only.** `license` is checked as an expression, not
  against the SPDX license list, which this repository does not vendor.
- **Registry rules.** There is no registry (G1), so R3's unpublishable
  namespaces and G2–G7 have nothing to bind yet.
