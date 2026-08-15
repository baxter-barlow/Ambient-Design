# Syntax bake-off

Throwaway prototypes for the §8-Q1 syntax bake-off: two L5-conformant
candidate grammars and the Starlark-restricted-Python baseline §4 names as the
one fallback. They exist to be measured and then thrown away — AMB-33/R6 picks
a winner and writes the grammar's real source of truth, AMB-43/R12 generates
the parser from it, and nothing outside `lang/` may import this package.

```
python3 -m bakeoff check                    # gate: round trip, agreement, anchors
python3 -m bakeoff measure                  # token cost, T9 and L6 readings
python3 -m bakeoff defects                  # diagnostic quality on seeded defects
python3 -m bakeoff render --arm candidate_b --design blinker-555
python3 -m bakeoff card --arm candidate_a   # the A4 language card
python3 -m unittest discover -s tests -t .  # 77 tests, stdlib only
```

Run from this directory. `make check` runs the gate and the tests from the
repository root; `measure` needs the pinned tokenizer and is not part of the
gate.

## The three arms

| Arm | Shape | Variants |
|---|---|---|
| `candidate_a` | one fact per statement, atopile-faithful | explicit, inferred, inferred+columnar |
| `candidate_b` | facts scoped in a block under what they describe | explicit, inferred, inferred+columnar |
| `starlark` | restricted-Python builder API (§4's baseline) | explicit, inferred |

```
# candidate A                         # candidate B
r_a = new aed.lib.passive.Resistor    r_a = new aed.lib.passive.Resistor(
r_a.resistance = 100kohm +/- 1%           resistance = 100kohm +/- 1%):
r_a.part.package = "axial_0207"           part abstract:
signal VCC                                    package = "axial_0207"
VCC ~ j_bat.pos                       net VCC:
VCC ~ r_a.a                               j_bat.pos
VCC ~ timer.vcc                           r_a.a
                                          timer.vcc
```

**ONE AXIS DIFFERS, and it is stated so it can be argued with:** how a design
attaches facts to an instance and how it states connectivity. Everything else
is held identical between the candidates — the `#pragma` header (L8), the
quantity mini-language (T3/T4 already settle literals), the layout tokenizer
(L5), `module` headers, `port` declarations, assertions, and the columnar
sub-syntax (L6's proposal, not either candidate's). Two candidates differing
in a dozen ways would produce a number nobody could attribute to anything.

## What makes the numbers comparable

Three properties, all checked by `bakeoff check` and by the test suite. If any
fails, the run reports a failure instead of numbers.

**Round trip.** `parse(render(m)) == m` for every arm and variant. An arm whose
printer and parser disagree is measuring a language nobody can read back.

**Agreement.** Every arm's parse of its own rendering equals the same reference
model. Without this, "arm B is 20% cheaper" might only mean arm B was given
less to say.

**Anchoring.** Each design is checked against an artifact authored by a
*different issue*. `blinker-555` is elaborated, flattened, and required to
reproduce `ir/examples/blinker.ir.json` (AMB-38) exactly — 12 instances, 7
nets, 25 connections, 2 assertions. `esp32s3-devboard` is required to match
`benchmarks/esp32s3-devboard/parts.yaml` (AMB-39) — 60 placements, 3 DNP. A
bake-off whose reference netlist was written by the same hand as its parsers
proves nothing.

Equality is structural and dimensional: instance order and key order do not
matter, `100kohm` equals `100000ohm`, and an unlabelled net is identified by
its member set. Two things are deliberately outside it — `qualified_name`,
which no arm can recover because the prototypes have no import syntax (L4 owns
imports), and `design_id`, which is corpus metadata rather than a fact about
the circuit.

## The corpus, and what is not in it

`examples/blinker-555.design.json` — benchmark (a), hand-transcribed from the
committed IR. This is the design AC5a runs its trials on.

`examples/esp32s3-devboard.design.json` — benchmark (c), **generated** by
`examples/make_esp32_model.py` from `benchmarks/esp32s3-devboard/`. Edit the
generator, never the JSON; a test asserts regenerating reproduces it byte for
byte. It carries the L6 and T9 readings, because it is the only corpus member
with enough repeated structure for a columnar section to mean anything.

**Benchmark (b), the buck converter, is deliberately absent.** Its BOM leaves
the compensation network as "standard E96 R, C0G C — chosen at layout time"
and never enumerates the LM25145's pin-level netlist, so expressing it at
component level would require design decisions this issue has no business
making. AMB-50/R53 owns the living benchmark sources. Inventing a netlist and
calling it benchmark (b) would have put a fiction into the measurement.

Also absent, and for the same reason: **footprint pin designators on (c)**. The
WROOM-1, USB-C and regulator pin maps are datasheet facts no document in this
repository states. `pin_numbers` is optional in the schema precisely so an
unresolved mapping can be left unresolved; AMB-58 and AMB-65 own the real ones.

## Results

Measured with the pinned `o200k_base` tokenizer from `toolchain/versions.yaml`,
over each arm's canonical rendering.

| Design | Arm | explicit | inferred | +columnar |
|---|---|---:|---:|---:|
| blinker-555 | candidate_a | 1223 | 905 | 905 |
| blinker-555 | candidate_b | 980 | **747** | 747 |
| blinker-555 | starlark | 1144 | 822 | — |
| esp32s3-devboard | candidate_a | 8514 | 6278 | 5091 |
| esp32s3-devboard | candidate_b | 6622 | **4994** | **4151** |
| esp32s3-devboard | starlark | 7265 | 5056 | — |

Language cards: candidate_a 786, candidate_b 809, starlark 711 tokens — all
comfortably inside §4's ~3K flip-criterion budget.

**T9 annotation tax: 24-30%**, and it is a LOWER BOUND. The rules in
`bakeoff/library.py` carry no value defaults, deliberately: the right default
package for benchmark (a)'s through-hole build is wrong for (c)'s SMD build, so
a library carrying one would hand the measurement a number that depends on
which design happens to be in the corpus. A real type checker recovers at least
this much.

**L6 columnar saving: 17-19% on (c), 0% on (a).** Nothing in a 555 blinker
repeats three times with the same shape. L6 is a big-design feature or it is
nothing, which is itself the answer to whether it earns a place in v1.

**Line counts against AC1's ceilings.** Benchmark (c) is budgeted at ~600 DSL
lines and `design.md` estimates 380-450. Measured: 548 (A, inferred), 513 (B,
inferred), 408/368 with columnar. The estimate was optimistic without columnar
and right with it. Benchmark (a) is budgeted at ~150 and comes in at 86/75.

**Diagnostic quality on nine seeded defects** (P2: the repair loop is the unit
of design, so this is not a side measurement):

| Arm | detected | localised | diagnostics/defect |
|---|---|---|---|
| candidate_a | 15/15 | 100% | 1.0 |
| candidate_b | 16/16 | 94% | 1.1 |
| starlark | 14/16 | 100% | 1.0 |

**The sharpest result in the bake-off is the baseline's two misses.** Corrupt
`10kohm` to `10kOhm` and the Starlark baseline *accepts the design* — the
string does not parse as a quantity, so it is read as a symbolic value and the
resistance silently becomes text. Both candidates reject it. This is §6's
"SKiDL's stringly values" criticism reproduced rather than asserted, and no API
design fixes it while the host language owns literal syntax. A test pins the
finding so a later change cannot make it disappear quietly.

## Honest limits

**No model has been near this.** Token cost here is a property of a grammar and
a canonical formatter, not of anything a model emitted. Emission accuracy under
the AC5 protocol is AMB-33's run, using these arms as gates
(`bakeoff/gate.py`); the readings above are the half that can be produced
offline for zero spend, and they are not a substitute for the other half.

**Parse level only.** No type checker exists at M0 — that is roadmap Risk 8,
accepted and bounded there. The T9 and L6 readings are preliminary by
construction and AMB-57/R59 re-measures both against the real checker at M2.

**The defect corpus is nine mutations on two designs, not a repair-loop
simulation.** It measures what a grammar says about a broken file, which is a
necessary condition for the loop to converge and not a sufficient one.

**L6 is only measured on top of `inferred`.** A columnar section is for uniform
tabular data, and per-instance pin declarations are neither, so a columnar
reading of the `explicit` cell would measure the absence of inference rather
than the value of columns.

**The Starlark baseline has no columnar cell.** Python has no columnar
sub-syntax; inventing one so the table had no gaps would be reporting a number
for a construct nobody proposed.

## Layout

| Path | Role |
|---|---|
| `design-model.schema.json` | the arm-neutral design model, with negative controls under `examples/negative/` |
| `bakeoff/quantities.py` | the shared literal mini-language, exact decimals |
| `bakeoff/layout.py` | the shared INDENT/DEDENT tokenizer (L5) |
| `bakeoff/model.py` | the design model: loading, coherence, canonical equality |
| `bakeoff/library.py` | the component library and the three T9 inference rules |
| `bakeoff/elaborate.py` | flattening and the external anchor checks |
| `bakeoff/arms/` | the three arms, plus what they share |
| `bakeoff/defects.py` | the seeded-defect corpus |
| `bakeoff/measure.py` | token cost and the T9/L6 readings |
| `bakeoff/gate.py` | `CallableGate` adapters into the AC5 harness |

The gate `bakeoff/gate.py` builds is a **pipeline**, not a single verdict:
`parse` then `netlist`. AC5a's bar is "compile/type-check/export gates" —
plural — and without the second stage a model that emitted a syntactically
perfect resistor divider instead of a 555 blinker would score a pass.
