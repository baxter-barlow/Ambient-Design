# Rhoform Netlist IR v0

The IR is the single, versioned JSON artifact between the Rhoform language and **all** backends
(requirement I4). The compiler elaborates DSL source into one `*.ir.json` document plus one
`*.sourcemap.json` sidecar; every downstream tool reads those two files and nothing else.

Files here:

| File | Purpose |
| --- | --- |
| `netlist-ir.schema.json` | JSON Schema (draft 2020-12) for the elaborated design |
| `source-map.schema.json` | JSON Schema for the I9 source-map sidecar |
| `examples/blinker.ir.json` | Hand-written elaboration of the 555 blinker benchmark |
| `examples/blinker.sourcemap.json` | Matching source map |
| `examples/negative/` | Negative controls: each file must be **rejected** by its schema |
| `validation.log` | Transcript of the validation runs, and the carried-forward retraction |

## `rhoform-canonical-json/1`

The serialization profile `header.canonical_form` names and `design_hash` is
taken over. It was referenced by the schema and defined nowhere, which meant
the determinism claim below rested on a document nobody had written — and the
gate did not implement it either, hashing raw committed bytes instead. Two
conforming implementations could therefore produce different `design_hash`
values for the same design, which is the one thing "IR v0" had to nail down.

1. UTF-8, no BOM, exactly one trailing `LF`.
2. Object keys sorted by Unicode code point. **Not** "the order given by this
   schema": open maps (`parameters`, `x_` extensions) have no schema order, so
   that rule was unimplementable for precisely the objects most likely to
   differ between implementations.
3. No insignificant whitespace — `,` and `:` separators and nothing else.
4. Non-ASCII characters emitted literally, never `\u`-escaped.
5. `NaN` and `Infinity` are not representable and are an error.
6. Arrays keep their order. Order is meaning here; each array's sort rule is
   stated on its own field and is not the encoder's business.
7. **Numbers have one spelling per value**, and that spelling is
   **ECMA-262 `Number::toString`** (§6.1.6.1.20) — the algorithm behind
   `JSON.stringify`. Given the shortest round-tripping digit string `s` of
   length `k`, and the exponent `n` such that the value is `0.s × 10ⁿ`:

   | condition | form | example |
   | --- | --- | --- |
   | `k ≤ n ≤ 21` | digits, then `n−k` zeros | `1500` |
   | `0 < n ≤ 21` | digits with a point after `n` of them | `1.5` |
   | `−6 < n ≤ 0` | `0.`, `−n` zeros, then digits | `0.0015` |
   | otherwise | `d[.rest]e(+|−)|n−1|` | `1.5e-7` |

   `-0.0` normalizes to `0`: a design has no signed zero.

   The first version of this clause said "the shortest form that round-trips"
   and left it there. That is not a specification, it is whichever spelling the
   host language happens to use — and Python and JavaScript differ across
   exactly the band an electronics IR lives in. Python pads a one-digit
   exponent (`1e-07` against `1e-7`) and switches to exponential below 1e-4
   where JavaScript switches below 1e-6 (`1e-05` against `0.00001`). Express
   one 100 nF capacitor as `1e-7` F, which `netlist-ir.schema.json` invites by
   saying "the compiler normalizes units", and two conforming implementations
   produce different `design_hash` values for a document both accept. That is
   the precise failure this profile exists to prevent, surviving inside the
   clause written to prevent it.

`design_hash` is the SHA-256 of that serialization with `header.design_hash`,
`header.generator` and `header.source_hash` set to `""`. The last two are
excluded for the same reason the first is: they describe **how** the document
was produced, not **what** it describes. Hashing `generator.version` gave one
unchanged netlist a new content address every time the compiler was rebuilt,
and hashing `source_hash` gave it a new one for a comment-only edit to the DSL
source — so a source map produced by one toolchain could never pair with an IR
produced by another, which is the interoperability the profile is for.

Because it is computed from the parsed document, re-indenting a committed file
or reordering its keys does not move it, while any change to the data does.
`tests/ir/check-hashes.py` implements the profile and its self-test asserts all
three invariances.


## Versioning policy

- `header.ir_version` is a **plain integer**, starting at `0`.
- In the 0.x era, **any** shape change — additive or breaking — bumps the integer. There is no
  minor/patch distinction: an IR document either matches a known integer version exactly or a
  backend must refuse it. This is what makes "a missing gate is not a pass" enforceable at the
  artifact boundary.
- Schema files are immutable per version: `netlist-ir.schema.json` here *is* version 0. A bump
  adds a new schema file; old ones are never edited in place.
- **No external stability promise in v1.0 (P7).** The IR is inspectable — plain JSON, every field
  described in-schema — but it is an *internal* contract between Rhoform's own language front end and
  Rhoform's own backends. Third-party tools that parse it do so at their own risk until a future
  release explicitly declares a stable IR. Do not build migration tooling, compatibility shims,
  or deprecation windows for v0; refusal-on-mismatch is the whole policy.
- `header.language_version` records the DSL definition the source was compiled under; it versions
  independently of `ir_version`.

## Identity model

- Every entity's **primary identity is its hierarchical path** (L7): `/` for the root design,
  then one segment per DSL scope member, e.g. `/indicator/r_lim`, with `[n]` indices for
  replicated members (`/leds/led[3]`). Instances and assertions carry paths; nets carry stable
  derived names (explicit DSL label, else synthesized deterministically from the highest-scope
  driving port). Refdes assignment, schematic symbols, layout footprint links, lockfile entries,
  diagnostics, and the source map all key off these identities — never off array position, never
  off refdes.
- Hierarchy is *encoded in* paths: the `instances` array is flat, and an instance's parent is the
  longest strict path prefix that is itself an instance path.
- **Rename ledger (I2):** identities must be continuous across edits. Renaming a member in the
  DSL is recorded in the design's rename ledger; the aliased path **keeps the original identity**
  — layout bindings, waivers, and history follow the entity to its new path. A path change that
  is not in the ledger is a hard error (an entity "disappearing" and a new one "appearing" is
  exactly the failure mode this rule exists to catch). The ledger lives beside the design source;
  the IR itself always shows current paths only.
- Determinism contract: identical source + identical toolchain ⇒ byte-identical IR, and
  `header.design_hash` proves it. All arrays are sorted (rules on each field's description), the
  serialization is canonical (`header.canonical_form`), and no timestamps, hostnames, or absolute
  paths may appear anywhere in the document.

## Source maps (I9)

`source-map.schema.json` defines the sidecar: a file table (repo-relative paths + content
hashes), spans (byte offsets authoritative, line/col denormalized), and a `nodes` map from IR
identity → declaration span + instantiation trace, innermost first. Because elaboration expands
one source line into many instances, replicated entities share a declaration span but carry
distinct traces.

**Diagnostic-anchor rule:** every diagnostic emitted by any Rhoform tool — static checks, ngspice
`.meas` assertion failures, KiCad export divergence — references an IR identity (path or net
name), never a raw file position. Renderers resolve identity → spans through the map. That keeps
diagnostics stable under source reformatting and gives every failure both a definition site and
the instantiation chain that produced it.

A `(IR, source map)` pair is bound by `design_hash`; consumers must reject mismatched pairs.

## How backends consume the IR

All backends read the one IR artifact; none re-parse DSL source, and none talk to each other.

- **KiCad export** walks `instances` + `connections` to emit the netlist/schematic-side
  artifacts. Path identities become the stable UUID/refdes basis so regeneration is
  divergence-protected; `dnp`, `exclude_from_bom`, `board_only`, and the pinless /
  net-attachable `hardware_kind`s (L9) map directly onto the corresponding KiCad attributes.
  Footprints and symbols come from dereferencing `part.lockfile_key` in the parts lockfile —
  never from the IR itself (D1). KiCad runs strictly at the subprocess boundary.
- **SPICE emission** flattens component instances to an ngspice deck (models via the lockfile),
  compiles `tier: "dynamic"` assertions to `.meas` statements with the V2 measurement vocabulary,
  and runs batch mode under the quit-code protocol. An assertion whose `measurement` has no
  `.meas` template is gating unless it carries a `waiver`.
- **Static checks** evaluate `tier: "static"` assertions with interval arithmetic over
  `Quantity.tolerance` intervals, run the T2 pin-role lattice ERC over `Port.role`, and populate
  / verify the reserved T5 `ground_domain` / `voltage_domain` net attributes per the
  component-mediated transfer model (domains propagate through components, not bare nets).
- **The renderer** draws from `instances`/`nets`/`connections` and uses the source map to link
  every drawn element and diagnostic back to DSL lines. No placement or routing coordinates
  exist in the IR (v1 invariant); the renderer owns layout of the picture.

## Compiler-enforced (not schema-enforced)

JSON Schema validates *shape*. The following invariants are real requirements on every IR
document but are **not** expressible in the schema, so a document can be schema-green and still
be rejected by the compiler. They are listed here so nobody mistakes a green schema gate for a
correctness proof; each needs a compiler check plus its own test, not a schema fixture.

- **Path uniqueness.** `instances[].path` and `assertions[].path` must each be unique across the
  document, and no instance path may collide with an assertion path. `uniqueItems` compares whole
  array elements, so two instances sharing a path but differing in any other field validate fine.
- **Cross-reference integrity.** Every `connections[].net` and `Probe.net` must name a real
  `nets[].name`; every `connections[].port.instance` and `Probe.instance` must name a real
  `instances[].path`; every `connections[].port.port` must name a port declared on that instance.
  JSON Schema has no mechanism for referencing sibling data.
- **Port connection cardinality.** A port appears in at most one connection, and a port with role
  `nc` appears in none.
- **Hierarchy well-formedness.** An instance's parent — its longest strict path prefix that is
  itself an instance path — must exist and must be `kind: "module"`. Component instances have no
  children.
- **Interval ordering.** `Interval.max >= min` and `AssertionBounds.max >= min` are cross-field
  comparisons the schema cannot express.
- **Ordering and canonicality.** The sort rules on `instances`, `nets`, `connections`,
  `assertions`, and `ports`, and the `canonical_form` serialization profile itself.
- **Hash correctness and pairing.** `design_hash` and `source_hash` must actually hash what they
  claim, the source map's `files` table must agree with `source_hash`, and a consumer must reject
  an (IR, source map) pair whose `design_hash` values disagree.
- **Source-map coverage.** Every instance, net, and assertion identity in the IR must have a
  `nodes` entry, every `Span.file` must index into `files`, and `byte_end >= byte_start`.
- **Rename continuity (I2).** A path change not recorded in the rename ledger is a hard error.
  Nothing in a single document can reveal this; it needs the previous build plus the ledger.

## Validating

```sh
python3 ../tests/schemas/validate-schemas.py   # validates ir/ with the pinned jsonschema
```

Uses `python3 -m jsonschema` (the pinned jsonschema) when the `jsonschema` package is present, falls
back to `npx ajv-cli --spec=draft2020`, and degrades (with a distinct non-zero exit code) to
well-formedness checking if neither validator is available — degraded coverage is reported,
never hidden.

Two case kinds run. The two examples must **validate**; every file in `examples/negative/` must be
**rejected**. A negative control that validates fails the run, which is what stops the schema from
quietly losing a constraint it advertises. Each fixture is a minimal complete document carrying
exactly one defect, described in its own `x_negative_control` member:

| Fixture | Defect it pins |
| --- | --- |
| `n01_mounting_hole_with_port.ir.json` | pinless L9 `hardware_kind` carrying a port |
| `n02_unknown_property.ir.json` | unknown non-`x_` member (here a stray `refdes`) |
| `n03_module_with_part.ir.json` | `kind: "module"` carrying a part binding |
| `n04_bad_pin_role.ir.json` | port role outside the T2 lattice |
| `n05_empty_bounds.ir.json` | assertion bounds with neither `min` nor `max` |
| `n06_bad_path.ir.json` | unrooted path identity |
| `n07_static_tier_dynamic_kind.ir.json` | static-tier assertion using a dynamic-only V2 kind |
| `n08_retired_measurement_kind.ir.json` | a measurement kind outside the V2 v1 vocabulary |
| `n09_span_missing_byte_offset.sourcemap.json` | source-map span with no authoritative byte offset |

`*.ir.json` files are checked against the IR schema, `*.sourcemap.json` against the source-map
schema, and an empty fixture directory is itself a failure. The duplicate-path and dangling-net
cases you might expect here are deliberately absent: they belong to the compiler-enforced list
above, because JSON Schema cannot detect either one.

Note on the examples: they are hand-written illustrations tracking the fixed benchmark (a) design
(RA 100 k 1 %, RB 680 k 1 %, CT 1 µF 5 %, RL 560 Ω 1 %, CONT bypass 10 nF
on pin 5, VCC bypass 100 nF on pin 8, assertion windows from
`benchmarks/blinker-555/assertions.yaml`). `/mh1` and `/tp_out` are board-side extras beyond that BOM and are
both `exclude_from_bom`. `design_hash` is genuine: it is the sha256 of this document's `rhoform-canonical-json/1` serialization with the `design_hash` value blanked (see the profile section above), so the pair binding is real and recheckable with `python3 tests/ir/check-hashes.py`. Do NOT recompute it from the file's raw bytes — that was the old rule, it is not what the schema says, and it is why two conforming implementations disagreed.
Recompute it with the gate's own canonicaliser -- not with a regex over the
raw bytes, which is the rule this paragraph just disavowed:

```sh
python3 -c 'import importlib.util,json,pathlib
s=importlib.util.spec_from_file_location("h","../tests/ir/check-hashes.py")
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
d=json.loads(pathlib.Path("examples/blinker.ir.json").read_text())
d["header"]["design_hash"]=""
print(m.design_hash_of(d))'
# -> sha256:8d056aa1c1f5075974ed5cd6cc1f4be4ffa826c4851c9b1f70bcbc73c3ef2330
```

That is the value committed in `examples/blinker.ir.json` and mirrored in the
source map. An earlier revision of this section published
`sha256:107d254b...`, produced by a raw-byte regex recipe printed three lines
under the sentence forbidding raw-byte hashing -- and that digest matched
neither the recipe's actual output nor the committed hash. It was residue of a
half-deleted block, which also left the paragraph above starting mid-sentence.

`source_hash`, the source-map file digests, and all byte/line offsets remain shape-valid
placeholders: no `.rhoform` source files exist yet, so there is nothing to hash or index. The compiler
is what will make those honest.
