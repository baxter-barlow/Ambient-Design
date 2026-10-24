# Part data (D3), schema versions 0 and 1

The typed, provenance-carrying description of a physical component. This is
the contract the static tier checks against: pin roles feed ERC, abs-max
windows feed the voltage-domain check, per-pin capability and
supply-current-per-mode feed the current/power budget.

- `part-data.schema.json` — the version 0 schema, frozen and byte-identical
  since its freeze. JSON Schema draft 2020-12.
- `part-data.v1.schema.json` — the version 1 schema: version 0 plus the
  additive members described below.
- `lint-part-data.py` — the gate for the cross-reference and consistency
  checks the schemas cannot express. The checks themselves are
  `rhoform/partdata.py`'s, which the compiler runs on every record it loads.
  Run `--self-test` to verify the checks still fire.
- `examples/*.part.json` — the schema's teaching set: real records,
  transcribed from live datasheets, that no design picks.
- `examples/negative/*.part.json` — expected-invalid controls. Each one
  states, inline, the guarantee it exists to prove. A `REJECTED at` control
  fails the schema at the pointers it names; a `LINT-REJECTED by <check> at`
  control is schema-valid and fails that one lint check at those pointers.
- `../rhoform/parts/<vendor>/<slug>.part.json` — the seed library the
  toolchain bundles, and the records designs are bound to (see "The seed
  store" below).

Gates: `make check` runs schema validation and the linter. Both must pass.

## Stability

**Versions 0 and 1 are versioned but explicitly unstable.** The `stability`
field is pinned by each schema to the literal `"unstable"`, so a record cannot
assert a guarantee these versions do not make. Promotion to a
third-party-implementable contract happens at 1.x against the criteria tracked
in open question §8-Q3.

Each version has its own immutable schema file, and a record is validated
against the schema of the version it declares. The toolchain implements
versions 0 and 1; consumers must refuse records whose `schema_version` they do
not recognise, and never read one against a neighbouring version's schema.

## What a record contains

| Field | Purpose |
|---|---|
| `pins[]` | Identity, physical designators, T2 role, per-pin windows and capability |
| `parameters` | The part's own defining values — resistance, capacitance, Vf |
| `ratings` | Part-level abs-max, recommended operating, thermal |
| `modes[]` | Supply-current-per-mode, the T10 budget input |
| `units[]`, `shared_pins` | Reserved multi-unit fields |
| `sources[]` | Cited documents: locator and hashes, never bytes |
| `provenance` | Per-field: which source, where in it, how confident |
| `license_class` | The basis on which these facts may be republished |

## Version 1

Version 1 is additive: every v0 member keeps its v0 meaning, every new member
is optional, and a v0 record relabelled `schema_version: 1` is a valid v1
record. What it adds, and what a consumer may rely on:

| Member | What it says |
|---|---|
| `implements[]` | The definitions the part implements, each with a map from the definition's pin names to the record's. The **only** join between a design's ports and the record's pins: no name, case or designator matching (`ctl` is not `CONT`, `p3v3` is not `3V3`). Total over the record (every pin mapped, in `unbound`, or `nc`) and injective (L14); total over the definition, checked where the definition is known. |
| `pin_classes[]`, `pins[].class` | Data a datasheet states once for a class of pins (a GPIO DC table). A pin's effective blocks are its class's with its own overlaid member by member; a class declares its members' role and never changes it (L15). |
| `pins[].strap`, `straps[]` | A strapping pin's reset default (`pull_up`, `pull_down`, `floating`) and, per pin, what each latched level selects; the part's documented level combinations (the boot table). A combination the vendor does not list is undocumented, not invalid (L16). |
| condition arrays | A characteristic, parameter, rating, output or series value may be an array of Measures, each with its own conditions: the same quantity at several operating points, never a default and an alternative. No two elements state the same conditions (L19). |
| `pins[].output` | What a power_out pin delivers: `voltage`, `current_limit`, `dropout`, each with its conditions. An output's accuracy goes here and never in `recommended.voltage`, which is a window the design must keep a pin inside (L17). |
| `series` | A two-terminal part's DC series model: `resistance`, `forward_voltage`. |
| `absent[]` | A field deliberately not recorded, with the reason: `vendor-unpublished`, `ambiguous-in-source`, or `not-transcribed`. The pointer names where the field would sit and must not resolve (L18). A consumer that needs the field reports degraded coverage with that reason; it never reads the absence as a value. `not-transcribed` is refused on the pin-role, abs-max and supply-current-per-mode fields of any record a benchmark picks (R29a). |
| `conduction_groups`, `pins[].ground_kind_hint` | Reserved, not populated: a v1 record carrying either fails validation, so a later version can define them. |

How a part transforms one supply into another is deliberately **not** a
part-data field: that is structure, and structure lives in the design's
rules. Part data carries the numbers (`output`, `series`).

## The seed store

`rhoform/parts/<vendor>/<slug>.part.json` is the record library the toolchain
bundles, alongside the standard library in `rhoform/lib/`. A record's path is
its `part_id`, so finding one is a path, with no index and no search. A design
reaches a record only through a pick in its lockfile; nothing is looked up by
part number at compile time.

A store record's **revision is the sha256 of its exact file bytes**, so the
bytes must be a function of the content: every store record is in canonical
layout (L22) — UTF-8, LF line ends, two-space indent, keys sorted, each number
spelled as its author wrote it, one trailing LF. A corrected record therefore
has a new revision, and a lock pinning the old one fails visibly rather than
silently reading the new facts. To write a record in canonical layout:

```sh
python3 -c 'import sys; from pathlib import Path; from rhoform import partdata
p = Path(sys.argv[1]); p.write_bytes(partdata.canonical_layout(p.read_bytes()))' \
  rhoform/parts/<vendor>/<slug>.part.json
```

The store also requires every record to implement at least one definition,
and every source URL to be on its vendor's own hosts (L21; the list is
`VENDOR_DOMAINS` in `rhoform/partdata.py`, extended in the change that adds a
vendor's first record).

The three benchmark records moved here from `examples/` in D3 v1 and were
upgraded to version 1: the NE555's 15 V datasheet column, the AP7361C's
output figures moved to `output`, and the ESP32-S3 module's GPIO class,
strapping pins and boot table. Benchmark (a)'s `design.md` and
`assertions.yaml` still cite the old `examples/` path in prose; the record is
`rhoform/parts/ti/ne555p.part.json`.

## Design decisions worth knowing

**Statistics are recorded as published.** `Measure` carries `min`, `typ`,
`max` and `peak` as distinct members because datasheets mean different things
by them. `max` is a guaranteed limit; `peak` is an observed maximum with no
guarantee behind it. The two example parts make the difference concrete: the
AP7361C guarantees `IOUT min 1.0 A`, a floor a checker may rely on, while the
ESP32-S3 publishes `IOH 40 mA typ` and nothing else, so no guaranteed drive
figure exists for it at all. Promoting a typ or a peak into the `max` slot
would manufacture a vendor guarantee, and the budget checker would then
under-guardband a real board.

**Bounds may be relative.** Logic thresholds are specified against the supply
(`VIH min = 0.75 x VDD`, `VIH max = VDD + 0.3 V`). `Bound` is therefore either
a number or a `{reference, factor, offset}` triple, evaluated once the
referenced rail is known. Flattening those to absolutes at authoring time
would silently pick a supply voltage the vendor did not.

**Provenance is keyed by JSON Pointer.** One entry can cover a subtree, and
the applicable entry for any value is the one whose pointer is its longest
prefix — so `""` is a record-wide default and a deeper pointer overrides it.
Wrapping every value in a `{value, provenance}` pair was the alternative; it
doubles the depth of the document and makes the data unreadable.

**Per-field license class is derived rather than stored.** D3 asks for a
license class per field. Each field resolves to a source through
`provenance`, and each source carries its own `license_class`, so the class
for any value is `field pointer → provenance → source_id → license_class`.
Storing it again on every field would let the two copies disagree. The
record-level `license_class` is the ceiling, and linter check L10 rejects a
record that cites a source more restrictive than its ceiling — which is what
makes the derivation safe to rely on.

**Confidence is ordinal, not numeric.** `datasheet-stated` /
`datasheet-derived` / `vendor-confirmed` / `estimated` / `unverified`. A
0-to-1 score would be false precision nobody can calibrate. The distinction
that earns its keep is `estimated`: benchmark (c) applies an in-house 0.50 V/A
dropout guardband that appears in no datasheet, and marking such a figure
`datasheet-stated` would launder an assumption into a vendor guarantee.

**Closed where checkers depend on it, open where the vocabulary is still
being learned.** `abs_max`, `recommended` and `capability` are closed and
named, so a misspelling fails validation instead of silently disarming a
check. `characteristics`, `parameters`, `ratings.*` and `conditions` are open
maps, because their vocabulary is part-family specific and a closed list at
v0 would push real data into free text where no checker can see it.

**Interoperates with the datasheet pipeline by construction.** The
`license_class` vocabulary, the `origin` restriction, and the two-level
`byte_sha256` / `content_hash` identity are taken from the Rhoform
datasheet-knowledge pipeline, which is the upstream producer of these
records. Two consequences are deliberate: `restricted-nda` is absent from the
enum and `distributor-*` is absent from `origin`, so both red lines are
unrepresentable here rather than merely forbidden by policy.

*Integration note:* the pipeline emits bare hex digests; this schema requires
the `sha256:`-prefixed spelling used elsewhere in Rhoform (the IR's `design_hash`
and `source_hash`). The writer that turns pipeline `SourceRecord`s into part
records adds the prefix.

**No `format` keywords.** In draft 2020-12 `format` is an annotation by
default: Python `jsonschema` does not enforce it without an explicit format
checker, and `ajv` refuses an unknown format in strict mode unless
`ajv-formats` is loaded. A `format: "uri"` would have looked like a constraint
while enforcing nothing. URLs and timestamps are constrained by `pattern`
instead, and negative controls n13 and n14 prove those constraints fire.

*Precisely:* the schema validates under both validators at their defaults,
which is what `make check` runs and what the fixtures are checked against. It
is not clean under `ajv --strict=true`, and neither is the merged IR schema:
both use `anyOf: [{required: [min]}, {required: [max]}]` to say "at least one
of these", which `strictRequired` flags because the properties are declared on
the enclosing object rather than inside each branch. That is a standard idiom
and the flag is a style opinion, not a defect — but the distinction is worth
stating rather than implying strict-mode cleanliness the schema does not have.
The `^x_` extension constraint WAS rewritten to be strict-clean, because that
one was introduced by a fix and there was no reason to add new friction.

## Verification performed at freeze

Both validators agree on every fixture — Python `jsonschema` 4.26.0 and
`ajv-cli --spec=draft2020`, 21 of 21 parts cases. Datasheet revisions were
confirmed to match the citations already in `benchmarks/` (ESP32-S3-WROOM-1
v1.8, AP7361C DS37274 Rev. 5-2).

**Reproducing the hashes.** `byte_sha256` is checkable with nothing but curl:
fetch the recorded `url` and `shasum -a 256` the bytes. At the v0 freeze every
one of the five reproduced. Re-fetched for version 1 on 2026-10-24, the
AP7361C and ESP32-S3-WROOM-1 documents still did; TI now serves the NE555
datasheet, the same SLFS022K revision, as new bytes, so that record cites the
re-fetch as a second source for the values read from it. A byte hash is a
locator, and vendors re-stamp documents; the `document_version` is what has to
match.

`content_hash` is **not reproducible from this repository**, and that
asymmetry is worth stating plainly rather than letting the two hashes sit
side by side looking equally verifiable. It is computed by
`compute_identity` in the *separate* `aed-part-data` pipeline repository,
which owns the text-normalization algorithm (`CONTENT_HASH_VERSION`) and the
vendor stamp-strip registry — both of which the `identity_version`
`chv1+reg2026.08.0` names. To reproduce:

```bash
PYTHONPATH=<path-to>/aed-part-data/src python3 -c "
from aed_part_data.identity import compute_identity
print(compute_identity(open('datasheet.pdf','rb').read(), [], '2026.08.0'))"
```

The empty stamp-strip list is correct for these four vendors: Espressif,
Diodes, TI and Vishay have no entry in that registry yet, so no patterns are
applied. A reviewer without that repository can verify the byte hashes and
must treat the content hashes as unverified — which is exactly why the schema
makes `content_hash` optional rather than required.

No datasheet PDF is stored in this repository. Records carry the retrieval URL
and the hashes; the documents themselves are fetched on demand.

## Known limitations at v0

These are recorded rather than hidden. Each is a candidate for the first
`schema_version` bump.

1. **No pin-class mechanism.** Datasheets specify GPIO DC characteristics once
   for a whole class of pins; this schema has no inheritance, so the values
   must be repeated per pin. Under v0 the ESP32-S3 record therefore populated
   capability on the pins benchmark (c) actually uses and left the rest with
   identity and role only. **A consumer must not read a missing `capability`
   block as "this pin cannot drive."** Closed in version 1 by `pin_classes`.

2. **Provenance addresses array elements by index, and those arrays are
   sorted.** Renaming a mode re-sorts `modes[]` and silently re-points every
   index-based citation at a different element — the pointer still resolves,
   so a dangling-pointer check cannot catch it. Mitigated by the `target`
   field, which echoes the intended element's identity, and by linter check
   L11, which rejects an indexed citation that is missing or contradicts it.
   A future version may replace index pointers with identity-based addressing.

3. **Cross-references live in the linter, not the schema.** JSON Schema cannot
   check that a mode draws on a pin that exists and is `power_in`, or that
   unit membership is disjoint from `shared_pins`. Anything consuming these
   records outside `make check` must run `lint-part-data.py` too, or it is
   only checking shape.

4. **Conditions are not machine-comparable.** A condition value may be a
   string (`"VOUT + 1 V"`) where the datasheet states a relation rather than a
   number. A checker cannot evaluate those; it can only surface them.

## Authoring a record

1. Fetch the datasheet from the vendor's own host, verify it is a PDF, hash
   the exact bytes. Never commit it.
2. Transcribe only what a check will read. Data no checker consumes is
   maintenance surface with no verification behind it — the example records
   say explicitly what they left out and why.
3. Record the statistic the vendor published. If the table gives a typ and no
   max, record a typ and no max. Where the vendor publishes a quantity at
   several operating points, record each as an element of a condition array.
4. Cite every value: `source_id`, `locator` a reviewer can navigate to, and an
   honest `confidence`. A re-fetch that returns new bytes for the same
   document revision is a second source entry, with its own hash and
   retrieval time, cited by the values read from it.
5. Fill `implements` from the vendor's pin table, map by map; never by name.
6. Write the file in canonical layout and run `make check`.

If a value cannot be read unambiguously from the document, record nothing and
say so: an `absent` entry with reason `ambiguous-in-source`, or
`vendor-unpublished` when the document does not state it at all, and the
detail in its `note`, because a confidently-wrong number is worse than an
absent one. `ambiguous-in-source` is a statement about the document, not
about the extraction. A PDF text layer that scrambles a table is not an
ambiguous table: render the page and read it there, or try a second
vendor-direct source, and if the value still was not read, it is
`not-transcribed`. The 555's thermal table is the example. Its text layer
flattens merged header cells, and the rendered page shows the P (PDIP)
column plainly, so the record carries that column's figure.
