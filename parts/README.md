# Part data (D3), schema version 0

The typed, provenance-carrying description of a physical component. This is
the contract the static tier checks against: pin roles feed ERC, abs-max
windows feed the voltage-domain check, per-pin capability and
supply-current-per-mode feed the current/power budget.

- `part-data.schema.json` — the schema. JSON Schema draft 2020-12.
- `lint-part-data.py` — cross-reference and consistency checks the schema
  cannot express. Run `--self-test` to verify the checks still fire.
- `examples/*.part.json` — real records, transcribed from live datasheets.
- `examples/negative/*.part.json` — expected-invalid controls. Each one
  states, inline, the guarantee it exists to prove.

Gates: `make check` runs schema validation and the linter. Both must pass.

## Stability

**Version 0 is versioned but explicitly unstable.** The `stability` field is
pinned by the schema to the literal `"unstable"`, so a record cannot assert a
guarantee this version does not make. Promotion to a third-party-implementable
contract happens at 1.x against the criteria tracked in open question §8-Q3.

Consumers must refuse records whose `schema_version` they do not recognise.

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
fetch the recorded `url` and `shasum -a 256` the bytes. Every one of the five
reproduces.

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

The empty stamp-strip list is correct for these five vendors: Espressif,
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
   must be repeated per pin. The ESP32-S3 record therefore populates
   capability on the pins benchmark (c) actually uses and leaves the rest with
   identity and role only. **A consumer must not read a missing `capability`
   block as "this pin cannot drive."** This is the most-wanted v1 change.

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

1. Fetch the datasheet, verify it is a PDF, hash the exact bytes.
2. Transcribe only what a check will read. Data no checker consumes is
   maintenance surface with no verification behind it — the example records
   say explicitly what they left out and why.
3. Record the statistic the vendor published. If the table gives a typ and no
   max, record a typ and no max.
4. Cite every value: `source_id`, `locator` a reviewer can navigate to, and an
   honest `confidence`.
5. Run `make check`.

If a value cannot be read unambiguously from the document, record nothing and
say so in `notes`. Two example records do exactly this — the 555's thermal
resistance and the HC00's supply current — because a confidently-wrong number
is worse than an absent one.
