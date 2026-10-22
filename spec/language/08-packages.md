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
compile root is also the package specification's workspace root. The
compilation also holds the
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
and, transitively, those of the packages it depends on — and the
standard library modules those files name, and nothing else: a
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
path falls under the reserved prefix `rhoform.lib.` is RHO2068, and so
is such a file as the entry
([04](04-elaboration.md#the-standard-library)). No two files of a
compilation may have one module path
([04](04-elaboration.md#definitions-and-the-root)), since their
definitions would share IR names: a path naming a file whose module path
a file read earlier already has — `./a-b/x` after `a_b/x.rhoform`, both
`a_b.x` — is RHO2069, and the file is not read. Files are read from the
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
from `lib/divider.rhoform` is `lib.divider.Divider`. A name whose import
failed is not reported again where it is used.

## Files and hashes

`header.source_hash` and the source map's `files` cover every source
file the compilation read — the entry file, its import closure, and the
standard library modules they name — by compile-root-relative path, a
library module by its fixed path `rhoform/lib/<module>.rhoform`
([04](04-elaboration.md#the-source-map)). A manifest is configuration,
not source, and is not listed.

## The command line

`rhoform check FILE` compiles FILE as an entry. `rhoform check DIR`
compiles as entries the `*.rhoform` files under DIR that no other file
named on the command line reaches through its imports without being
reached back from it: a library is checked through the files that
import it, and a file imported only within a cycle is still an entry, so
the cycle is reported. The package specification defines no entry-point
key (`[package]` is closed), so no manifest names entries. A defect two
compilations of one run share is reported once.

## Deviations, recorded

This version implements §1 (identity), §2.1 and §2.3 (versions and
language versions), §3 (the manifest), §4.3 (ranges) and §7 (imports)
of the package specification, with these differences; each is a
diagnostic or a documented absence, never a silent skip:

- **No lockfile.** L3 requires `rhoform.lock` for compilation and L4/L5
  define it; the lockfile schema is R55 (M2). This version compiles
  without one and reads path dependencies in place; nothing is
  resolved, so there is no MVS selection (L6–L8) beyond the checks of
  [`[deps]`](#deps).
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
