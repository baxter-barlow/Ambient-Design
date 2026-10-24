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
| `conduction_groups`, `pins[].ground_kind_hint` | Reserved, not populated: a v1 record carrying either fails validation, so a later version can define them (controls n25, n26). |

How a part transforms one supply into another is deliberately **not** a
part-data field: that is structure, and structure lives in the design's
rules. Part data carries the numbers (`output`, `series`).

## Checker-reliable keys

`parameters`, `ratings.*` and `characteristics` are open maps, so a key in
one is a name no check promised to read. The keys below are the ones a check
MAY read (L20, `VOCABULARY` in `rhoform/partdata.py`). Each has one home,
one meaning and one dimension, and the lint holds every Measure under it to
that dimension; any other key stays legal and no check reads it. Every
Measure's unit, anywhere in a record, must also parse by the part-unit
grammar the checker reads it with (`rhoform.check.values.parse_part_unit`:
`1`, an atom, or `atom/atom`, the atoms being the literal units plus `K`,
`ppm`, `min`, `dB` and `dBm`). A unit outside it -- `%`, `nC`, `pA`,
`Ohm` -- is refused, so a value with no unit in the grammar is recorded as an
`absent` entry naming the unit in its note. `temperature` below means a
reading on the degC scale; a `K` is a difference and is refused there.

A two-terminal rating is across the part's two terminals. A rating with a
polarity (a diode's or LED's reverse voltage, a TVS's stand-off, a MOSFET's
VDS and VGS, an IC's BST-to-SW) is not a key: it is the pin's own
`abs_max` or `recommended` window, as a relative bound on the other pin
(`K: max = A + 40`).

`parameters` -- what the part is:

| Key | Dimension | Meaning |
|---|---|---|
| `resistance` | resistance | A resistor's resistance between its terminals. `typ` is the nominal its MPN codes, `min`/`max` that nominal at the tolerance (datasheet-derived, the rule in the note). A jumper carries `max` only. |
| `resistance_tolerance` | dimensionless | The tolerance as a fraction of nominal: +/-1 % is `min -0.01, max 0.01`. |
| `capacitance` | capacitance | A capacitor's capacitance, as for `resistance`, at the vendor's measurement conditions. |
| `capacitance_tolerance` | dimensionless | As `resistance_tolerance`. |
| `capacitance_dc_bias_change` | dimensionless | Capacitance change at the DC bias in `vdc`, only where the vendor TABULATES it; a typical curve is not transcribed. |
| `inductance` | inductance | An inductor's inductance at its measurement conditions. |
| `inductance_tolerance` | dimensionless | As `resistance_tolerance`. |
| `impedance` | resistance | A ferrite bead's impedance magnitude at the `frequency` in its conditions. |
| `temperature_coefficient` | dimensionless/temperature | A resistor's TCR, or a C0G capacitor's coefficient, in `ppm/K`. |
| `temperature_characteristic` | dimensionless | A class-II capacitor's capacitance change over its rated range (X7R: `min -0.15, max 0.15`, conditions `ta` `min -55, max 125`). The EIA class itself is in `description`. |
| `reference_voltage` | voltage | An IC's internal reference as regulated at its feedback pin (the LM25145's VREF). |
| `efficiency` | dimensionless | A converter's guaranteed efficiency, where one is published; a typical curve is not transcribed. |
| `rds_on` | resistance | A MOSFET's drain-source on-resistance, one element per `vgs` and `tj`. |
| `gate_threshold_voltage` | voltage | VGS(th), with its `vds` and `id`. |
| `breakdown_voltage` | voltage | A TVS's or array's VBR at the test current `it`. |
| `clamping_voltage` | voltage | A TVS's VC at the pulse current `ipp`. |
| `reverse_leakage_current` | current | A two-terminal part's reverse current, cathode to anode, at the `vr` in its conditions. |
| `hold_current` | current | A PTC's hold current: the vendor guarantees it carries this much without tripping, so it is recorded in `min`. |
| `trip_current` | current | A PTC's trip current: the vendor guarantees it trips at no more than this, so it is recorded in `max`. |

`ratings.abs_max` -- stress limits from the vendor's absolute-maximum table;
exceeding one is damage:

| Key | Dimension | Meaning |
|---|---|---|
| `junction_temperature`, `storage_temperature` | temperature | As named. |
| `power_dissipation` | power | Total dissipation, at the ambient or case condition stated. |
| `esd_hbm`, `esd_cdm`, `esd_mm` | voltage | Component ESD ratings by model. |
| `esd_iec_contact`, `esd_iec_air` | voltage | IEC 61000-4-2 system ESD ratings, contact and air. |
| `forward_current` | current | A diode's average forward current or an LED's continuous forward current. |
| `peak_forward_current` | current | An LED's pulsed forward current, with its duty cycle and `pulse_width`. |
| `surge_current` | current | A diode's non-repetitive peak forward surge current, with its `pulse_width`. |
| `peak_pulse_power`, `peak_pulse_current` | power, current | A TVS's PPP and IPP, with the waveform. |
| `drain_current`, `pulsed_drain_current` | current | A MOSFET's ID and IDM, with `tc` or `ta`. |
| `interrupt_current` | current | A PTC's maximum fault current (Imax). |
| `overload_voltage` | voltage | A resistor's maximum overload voltage. |

`ratings.recommended` -- what the design must keep the part within:

| Key | Dimension | Meaning |
|---|---|---|
| `voltage_rating` | voltage | The continuous voltage across the part's terminals it is rated for: a capacitor's rated voltage, a resistor's maximum working voltage, a PTC's Vmax, a connector's or switch's rated voltage. The DSL's `voltage_rating` constraint is compared with this. |
| `power_rating` | power | A two-terminal part's rated dissipation, at the `ta` in its conditions (a resistor's P70). |
| `current_rating` | current | A ferrite's, jumper's, contact's or switch's rated continuous current. |
| `rms_current` | current | An inductor's rms current for the temperature rise in its conditions. |
| `saturation_current` | current | An inductor's saturation current, one element per inductance drop. |
| `ambient_temperature` | temperature | The operating ambient range, whichever table the vendor states it in. |

`ratings.thermal`: `theta_ja`, `theta_jb`, `theta_jc`, `theta_jc_top`,
`theta_jc_bottom`, `theta_jl`, `psi_jt` and `psi_jb`, each a
temperature/power (`degC/W`) for THIS record's package, with its board or
mounting in the conditions.

`characteristics`, on a pin or on a pin class:

| Key | Dimension | Meaning |
|---|---|---|
| `vih`, `vil`, `voh`, `vol` | voltage | Logic thresholds and output levels, absolute or relative to a supply pin of the part. |
| `input_current` | current | Current into an input at the conditions stated. |
| `leakage_current` | current | Current into the pin at the voltage in its conditions (a protection array's VBUS leakage). |
| `pull_up_resistance`, `pull_down_resistance` | resistance | Internal pulls. |
| `capacitance` | capacitance | Pin or line capacitance. |
| `required_supply_current` | current | On a `power_in` pin only: what the supply feeding it must be able to deliver (the ESP32-S3 module's IVDD, `min 0.5 A`). The budget check holds the supply chain's capability to it. |

The closed slots have their dimensions by construction: `abs_max` and
`recommended` `voltage` and `current`, `capability.source_current` and
`sink_current`, `output.voltage`, `current_limit` and `dropout`,
`series.resistance` and `forward_voltage`, and `modes[].draw[].current`.

Conditions. A condition is a Measure (a number, or a range as `min` and
`max`) or a string (a categorical setting, or a relation the vendor states
in words: `VOUT + 1 V`). These names carry one meaning, and a numeric one
has its dimension: `ta`, `tc`, `tj` (temperature readings); `vcc`, `vdd`,
`vin`, `vout`, `vr`, `vgs`, `vds`, `vdc`, `voh`, `vol` (voltage); `iout`,
`if`, `ir`, `id`, `it`, `ipp`, `ioh`, `iol`, `iin` (current); `frequency`,
`cpu_frequency` (frequency); `cin`, `cout`, `cload` (capacitance); `rload`
(resistance); `duration`, `pulse_width` (time); `duty_cycle`
(dimensionless); `tx_power` (`dBm`). Two operating points are compared by
value, so `5`, `5.0` and `5000 mV` are one point (L19), and in a strap
combination `x` and leaving a pin out are one requirement (L16).

Relative bounds. A bound `{reference, factor, offset}` is
`factor x V(reference) + offset`, and its reference is a pin of THIS record
(L23); it bounds a voltage. `bind` keys ports by definition pin and leaves
a reference as the record pin's name, so a checker resolves it with
`Binding.port_of(reference)` and evaluates it in that port's net, at the
same corner; a reference to a pin the definition does not carry resolves
to nothing, which is a coverage row. L12 compares a recommended bound with
an absolute maximum when both are numbers or both are the same function of
one pin (`BST + 6` against `BST + 14`); any other pair is an unperformable
check, counted against the ceiling the lint gate holds.

## Authoring the benchmark records

What landing L2d's records carry, so L2b, L3 and L4 read one shape.

- **Identity.** `rhoform/parts/<vendor>/<slug>.part.json`, part_id
  `<vendor>/<slug>`: the vendor slug is a `VENDOR_DOMAINS` key, and the slug
  is the exact orderable MPN in lower case with every character outside
  `a-z 0-9 . _ -` written `-` (`SS34-E3/57T` is `ss34-e3-57t`). `mpn` is
  that MPN verbatim, `manufacturer` as the vendor writes its name,
  `lifecycle` from the vendor's product page, `description` paraphrased in
  about 120 characters and naming a capacitor's EIA class. For a chip
  passive `package.name` is the EIA inch size (`0402`); otherwise the
  vendor's package name.
- **Join.** One `implements` entry for the definition the benchmarks
  instantiate, mapped pin by pin. Two-terminal parts name their terminals as
  the vendor does: `A` and `K` for a diode or LED, else `1` and `2` (a
  generic `a`/`b` maps to `1`/`2`). A header's or shunt's contacts are named
  by their designators (`1` to `N`). A USB-C receptacle names each signal as
  the vendor's pin table does, one pin per signal with every designator it
  occupies (VBUS on A4, A9, B4 and B9), and its SBU1 and SBU2 are `unbound`.
  Internally common legs (a tactile switch's pairs) are one pin, named by
  the lowest designator. When the vendor gives two pins one name (`NC`),
  each takes its designator as a suffix (`NC9`, `NC16`). A part-specific definition
  (`PART_SPECIFIC`) must match the record role for role; where the vendor's
  pin table disagrees with the library, the record keeps the vendor's role
  and the drift is reported, never papered over.
- **Roles.** From the vendor's pin table. Passives, connectors, switches,
  test points and two-terminal semiconductors are `passive`; a ground or
  supply pin of an IC or array is `power_in`.
- **Statistics.** `min` and `max` only where the vendor guarantees them, as
  the column header or footnote says; `typ` where it says typical; `peak`
  for an observed maximum it does not guarantee. A tolerance-evaluated
  nominal (`10 kohm +/- 1 %` as `min 9.9, typ 10, max 10.1`) is
  `datasheet-derived`, the rule in the provenance note. Nothing is promoted,
  averaged or estimated.
- **Conditions.** Every condition the row states and every one its table
  header states, under the names above. A row that overrides a header
  condition replaces it; one the header does not apply to (a dropout,
  measured by lowering VIN) leaves it off, and the note says so.
- **Passives.** Resistor: `resistance`, `resistance_tolerance`,
  `temperature_coefficient`, `power_rating` with its `ta`, `voltage_rating`
  (maximum working voltage), `overload_voltage`, `ambient_temperature`.
  Capacitor: `capacitance`, `capacitance_tolerance`,
  `temperature_characteristic` (class II) or `temperature_coefficient`
  (C0G), `voltage_rating`, `ambient_temperature`. Inductor: `inductance`,
  `inductance_tolerance`, DCR as `series.resistance`, `rms_current`,
  `saturation_current`. Ferrite: `impedance`, DC resistance as
  `series.resistance`, `current_rating`. PTC: `hold_current`,
  `trip_current` (the hold-versus-ambient table as further elements, with
  the vendor's "reference only" in the note), initial and post-trip
  resistance as `series.resistance` elements, `voltage_rating` (Vmax),
  `interrupt_current` (Imax). No passive carries `modes`.
- **Semiconductors.** Diode, LED, TVS: forward voltage as
  `series.forward_voltage` per `if`; reverse limits on `K` relative to `A`
  (`abs_max` for VRRM or VR, `recommended` for a TVS's VRWM);
  `reverse_leakage_current`, `breakdown_voltage`, `clamping_voltage`,
  `forward_current`, `surge_current`, `peak_pulse_power`, thermal. MOSFET:
  VDS on `D` and VGS on `G`, each relative to `S`; `rds_on` per `vgs`,
  `gate_threshold_voltage`, `drain_current`, `pulsed_drain_current`,
  thermal. Gate charge has no unit in the grammar (`nC`): an `absent` entry
  says so.
- **ICs.** Every pin's role and `abs_max`, absolute or relative to another
  pin as the table states it, and its `recommended` window; one `modes`
  entry per supply-current row the vendor publishes (shutdown, standby,
  operating), drawn on `power_in` pins; what a `power_out` pin delivers in
  `output`; `capability.source_current` only for a guaranteed minimum.
- **Connectors and switches.** Contacts `passive`; `current_rating` and
  `voltage_rating` per contact as the vendor rates them; contact
  resistance as `series.resistance` where published.
- **Absences.** A profile field the documents do not state is an `absent`
  entry, `vendor-unpublished`, with where you looked; one they state but
  that cannot be read unambiguously is `ambiguous-in-source`, with what is
  ambiguous. `not-transcribed` is refused on pin roles, abs-max and modes
  of every `BENCHMARK_PICKED` record (L18). A part with no `power_in` pin
  has no supply modes and needs no absence for them; a part whose vendor
  publishes no absolute-maximum table carries `/ratings/abs_max` as
  `vendor-unpublished`.
- **Provenance.** One source per document as fetched: `url` on the vendor's
  host, `byte_sha256` of the exact bytes, `retrieved_at` in UTC, `doc_title`
  and `document_version` as printed (if the document prints no revision,
  `document_version` says what it does print and the note says no revision
  is printed), `origin` `vendor-direct`, `license_class` `vendor-public`, no
  `content_hash` (only the pipeline mints one). A record default entry and
  one entry per table read, each with a `locator` (page, table, row) and
  `target` wherever its pointer passes through a sorted array.
- **Checking one file.** From the repository root, with the pinned
  toolchain: `python3 parts/lint-part-data.py rhoform/parts/<vendor>/<slug>.part.json`
  (the lint, including layout), then `python3 tests/schemas/validate-schemas.py`
  and the whole-tree `python3 parts/lint-part-data.py`, which also holds
  NOTICE's provenance numbers to the records and prints the numbers to
  publish.

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
strapping pins and boot table.

A record a benchmark picks is listed in `BENCHMARK_PICKED`
(`parts/lint-part-data.py`), and on it `not-transcribed` is refused for pin
roles, abs-max and supply-current-per-mode (R29a). The list names one
part_id per distinct benchmark MPN, so a record arrives already held to it.
`tests/parts/pick-benchmark-parts.py` maps every benchmark instance to the
record it picks, by exact MPN (`--check` fails on an instance with no record
or a pick the list does not name), and `tests/parts/crosscheck.py` is the
review tooling: a figure table per record, the blind-extraction diff, and
the passive MPN-code decoders.

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
