# Syntax bake-off, and the syntax it froze

**Decided: candidate B. The frozen grammar is `grammar/`; the bake-off
prototypes in `bakeoff/` are the evidence it was decided on, and are
throwaway.** AMB-43/R12 generates the real parser from `grammar/`, and nothing
outside `lang/` may import `bakeoff`.

Two L5-conformant candidate grammars were measured against each other and
against the Starlark-restricted-Python baseline §4 names as the one fallback.
The freeze-basis memo — what was measured, what was not, and what the decision
does and does not rest on — is [Syntax v0 Freeze Basis](https://app.notion.com/p/3bf627dbcc4281e38431ec227cbdc9f7)
in Notion; this file is the operational half.

## The frozen syntax (v0.1)

| Path | Role |
|---|---|
| `grammar/rhoform_syntax.py` | **the source of truth.** Rules as data, plus both emitters |
| `grammar/rhoform.ebnf` | generated. Do not edit |
| `grammar/rhoform.lark` | generated. Do not edit — AMB-43's input |
| `grammar/conformance.py` | builds a real LALR parser from the artifact |

```
make grammar                                   # both gates below
cd lang && python3 -m grammar.rhoform_syntax --check   # artifacts are current
cd lang && python3 -m grammar.rhoform_syntax --write   # regenerate them
cd lang && python3 -m grammar.conformance      # the grammar parses the corpus
```

L5 asks for "EBNF + Lark artifacts generated from one source of truth", and
the wording is doing work: two hand-maintained files would disagree
eventually, and the disagreement would surface as a parser accepting what the
spec forbids. Both artifacts render from one tree, and a test fails if either
falls behind it.

**The Lark artifact is loaded by Lark and run over the corpus, every CI run.**
A grammar file nobody parses with is prose — the same mistake as a gate that
prints "agrees with its anchor" while comparing a refdes list, which this
repository shipped once already. The conformance gate needs the pinned `lark`
and **exits 2, not 0, when it is missing**: an unavailable gate is not a pass.

Four things are deliberately *not* keywords: pin roles (T2), hardware kinds
(L9), measurement kinds (V2) and net attributes (T5). `input` and `output` are
pin roles, and a grammar that made them keywords would reject `input = new
...`, which is a legal design. They are closed vocabularies checked after
parsing, exactly as the prototype checks them, and a test pins that they stay
usable as names.

The one word the freeze drops from the prototypes' shared reserved set is
`signal` — candidate A's net declaration, which lost. `RESERVED` is a superset
of both candidates' keywords because the bake-off needed one, and carrying the
loser's vocabulary into the frozen language would reserve a useful identifier
for a syntax that no longer exists.

## The bake-off that decided it

```
python3 -m bakeoff check                    # gate: round trip, agreement, anchors
python3 -m bakeoff measure                  # token cost, T9 and L6 readings
python3 -m bakeoff defects                  # diagnostic quality on seeded defects
python3 -m bakeoff render --arm candidate_b --design blinker-555
python3 -m bakeoff card --arm candidate_a   # the A4 language card
python3 -m unittest discover -s tests -t .  # 157 tests (29 need lark)
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
# candidate A                             # candidate B
r_a = new rhoform.lib.passive.Resistor    r_a = new rhoform.lib.passive.Resistor(
r_a.resistance = 100kohm +/- 1%               resistance = 100kohm +/- 1%):
r_a.part.package = "axial_0207"               part abstract:
signal VCC                                        package = "axial_0207"
VCC ~ j_bat.pos                           net VCC:
VCC ~ r_a.a                                   j_bat.pos
VCC ~ timer.vcc                               r_a.a
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

Four properties, all checked by `bakeoff check` and by the test suite. If any
fails, the run reports a failure instead of numbers.

**Round trip.** `parse(render(m)) == m` for every arm and variant. An arm whose
printer and parser disagree is measuring a language nobody can read back.

**Agreement.** Every arm's parse of its own rendering equals the same reference
model. Without this, "arm B is 20% cheaper" might only mean arm B was given
less to say.

**Anchoring.** Each reference design is checked against an artifact authored by
a *different issue*. `blinker-555` is elaborated, flattened, and required to
reproduce `ir/examples/blinker.ir.json` (AMB-38) exactly — 13 instances, 7
nets, 27 connections, 2 assertions. `esp32s3-devboard` is required to match
`benchmarks/esp32s3-devboard/parts.yaml` (AMB-39) — 60 placements, 3 DNP, and
172 refdes/package/MPN fields — *and* to reproduce the five series edges in
that benchmark's `power-tree.yaml`. A bake-off whose reference netlist was
written by the same hand as its parsers proves nothing.

The power tree is there because **a BOM anchors no connectivity whatsoever**.
Until it was added, a mutation shorting VBUS straight to 3V3 passed every gate
while `bakeoff check` cheerfully printed that the design agreed with its
anchor. Adding it immediately failed, and the failures were real. D3's TVS was
transcribed forward-biased across the supply — anode on VBUS, cathode on GND —
when a TVS clamps in reverse bias and the SMF5.0A's 5 V figure is a *standoff*
voltage, meaningless with the cathode anywhere else. And `VBUS_PROT` named the
node after the ferrite bead in this model and the node after the fuse in the
power tree, so one label meant two different nodes across two files describing
one board. The node names here are now the power tree's, verbatim.

**Coverage.** `coverage-probe` is a synthetic design whose only job is to use
every field of `design-model.schema.json` at least once, so an arm that cannot
express something fails the gate instead of waiting for a corpus that happens
to hit it. It found two things the two benchmarks never happened to contain:
`exclude_from_bom` on a component with no hardware kind, which the Starlark
arm had no setter for and silently dropped, and L9b's intentional single-pin
net, which **no arm could spell at all** — A dropped it, B emitted a bare
endpoint its own parser rejected, and the baseline's `link` demanded two. All
three now spell it `isolated`.

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

`examples/coverage-probe.design.json` — not a circuit and not measured. It
declares `purpose: coverage-probe`, which the schema uses to *forbid* it an
anchor (there is nothing external for a synthetic design to agree with) and
which `bakeoff measure` uses to exclude it from every number. A token count
over a design nobody would build is a token count over nothing. It is in the
corpus for the gate's sake, not the measurement's.

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
over each arm's canonical rendering. Held to the harness by
`lang/tests/check_readme_numbers.py`: the blinker rows sat two revisions stale
until AMB-123 because no gate read this file, and the same staleness had
recorded L6's saving on (a) as 0 when it is 45-82.

| Design | Arm | explicit | inferred | +columnar |
|---|---|---:|---:|---:|
| blinker-555 | candidate_a | 1344 | 993 | 911 |
| blinker-555 | candidate_b | 1069 | **814** | 769 |
| blinker-555 | starlark | 1252 | 901 | — |
| esp32s3-devboard | candidate_a | 8554 | 6318 | 5131 |
| esp32s3-devboard | candidate_b | 6631 | **5003** | **4160** |
| esp32s3-devboard | starlark | 7333 | 5124 | — |

Language cards: candidate_a 865, candidate_b 888, starlark 827 tokens — all
comfortably inside §4's ~3K flip-criterion budget.

**The decision, on the `inferred` cell** — the realistic one, and the one the
arms were built to be compared on:

| | (a) blinker | (c) esp32 | (c) +columnar | card | defects | localised |
|---|---:|---:|---:|---:|---:|---:|
| candidate_a | 993 | 6318 | 5131 | 865 | 15/15 | 100% |
| **candidate_b** | **814** | **5003** | **4160** | 888 | **16/16** | 94% |
| starlark | 901 | 5124 | — | 827 | 14/16 | 100% |

B is 18.0% cheaper than A on (a) and 20.8% on (c), and it is the only arm that
beats the Starlark baseline on both designs. It detects one defect more than A
— A cannot express the dropped-bracket mutation on (c) at all — and pays for
its block scoping with one mis-localised diagnostic in sixteen, which is the
cost its own docstring predicted. A's 23-token-smaller card decides nothing
against a ~3K budget.

**What the decision does not rest on: emission accuracy.** No model has been
near either grammar. AC5a is AMB-33's successor work, and if it contradicts
this, the flip criterion in §4 is the mechanism, not this table.

**T9 annotation tax: 24-30% in aggregate (23.9-30.1 measured), and the aggregate is the wrong
number.** An earlier version of this file called it a lower bound. Decomposing
it per rule shows why that was wrong:

| Design | Arm | T9-1 library pins | T9-2 inference | T9-3 L9 flags | all |
|---|---|---:|---:|---:|---:|
| blinker-555 | candidate_a | 15.1% | 7.7% | 3.4% | 26.1% |
| blinker-555 | candidate_b | 14.3% | 7.0% | 2.5% | 23.9% |
| blinker-555 | starlark | 20.4% | 4.9% | 2.7% | 28.0% |
| esp32s3-devboard | candidate_a | 17.3% | 6.0% | 2.9% | 26.1% |
| esp32s3-devboard | candidate_b | 16.5% | 5.8% | 2.3% | 24.6% |
| esp32s3-devboard | starlark | 23.3% | 4.2% | 2.6% | 30.1% |

T9-1 is 58-77% of the total, and T9-1 is not inference — it is a component
library handing over a pin list, which L2, D3 and D5 give unconditionally and
which no candidate grammar would ever have charged an author for. The
`explicit` denominator that includes it describes a language nobody proposed.
**The reading that answers T9's question is the T9-2 column: 4.2-7.7%.**

Three biases, stated rather than one: counting T9-1 as inference at all biases
UP; benchmark (c) is built so every instance is port-recoverable, which
maximises T9-1 specifically, biasing UP; and the rules carry no value defaults
— the right default package for (a)'s through-hole build is wrong for (c)'s
SMD build, so a library carrying one would hand the measurement a number that
depends on which design is in the corpus — which biases T9-2 DOWN.

**L6 columnar saving: 843-1187 tokens (17-19%) on (c) at the default
threshold, 45-82 (5.5-8.3%) on (a) — but the threshold is a judgement, so the
report sweeps it.**
`COLUMNAR_MIN_ROWS = 3` was documented here as "the smallest group where a
table is shorter than the statements it replaces". Sweeping it showed that is
simply false: 2 is cheaper still, on both candidates.

| Design | Arm | ≥2 | ≥3 | ≥4 | ≥5 | ≥6 |
|---|---|---:|---:|---:|---:|---:|
| blinker-555 | candidate_a | 112 | 82 | 0 | 0 | 0 |
| blinker-555 | candidate_b | 65 | 45 | 0 | 0 | 0 |
| esp32s3-devboard | candidate_a | 1265 | 1187 | 1151 | 1151 | 1151 |
| esp32s3-devboard | candidate_b | 901 | 843 | 819 | 819 | 819 |

Three stays the default because a two-row table is a header and two lines,
which reads worse than two statements — a readability judgement, now labelled
as one. Whichever threshold you pick, the shape of the answer holds: (a) saves
5-8% where (c) saves 17-19%, so L6 is a big-design feature — worth having, and
not decided by the small design either way.

This paragraph read "0 on (a)" and the blinker rows read 72/0 and 40/0 until
AMB-123. Both were measured before 333869c added the bypass capacitor to
`lang/examples/blinker-555.design.json`; that part gave (a) a third repeated
group, so the default threshold now clears. The stale figure said L6 buys
nothing on small designs, which is the stronger claim and the wrong one, and it
sat in the section this README offers as the basis for whether L6 earns a place
in v1. The numbers above come from `python3 -m bakeoff measure`, run in `lang/`, and
the token counts are now held to `lang/token-counts.json` by
`lang/tests/check_readme_numbers.py`. This paragraph said "no gate reads this
file" while the same document, twenty lines up, said it was gated -- the
sentence was true when written and nobody updated it.

**Line counts against AC1's ceilings.** Benchmark (c) is budgeted at ~600 DSL
lines and `design.md` estimates 380-450. Measured: 548 (A, inferred), 513 (B,
inferred), 408/368 with columnar. The estimate was optimistic without columnar
and right with it. Benchmark (a) is budgeted at ~150 and comes in at 119 explicit / 82 inferred / 71 inferred+columnar on candidate_b, the arm that won, matching benchmarks/blinker-555/design.md sec. AC1a. (This line read 86/75 until AMB-123, then 130/93/82 -- which are candidate_a's, the arm that LOST and whose rendering the frozen grammar is tested to reject.)

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

The table above counts the two reference designs; `bakeoff defects` also runs
the coverage probe, where the same defect makes it three for three. Acceptance
is now scored against the netlist rather than the exit code, and in all three
cases the accepted design **differs from the intended one** — the baseline
does not merely tolerate the corruption, it silently builds a different
circuit. That distinction is the difference between a cosmetic miss and the
failure this whole exercise exists to catch.

**The baseline's second cost does not appear in any token count: it needs a
sandbox, and sandboxes leak.** §6 rejects the embedded path partly over
"arbitrary code execution from an untrusted model", so the baseline enforces
its subset with an AST allowlist and a tree-walking evaluator rather than
`exec` with tidied globals. Attacking that evaluator rather than reading it
found five holes, every one of which the module docstring had claimed was
closed:

- **Attribute access was a spelling rule, not a capability rule.** It allowed
  any non-underscore attribute on any value. `"".format` walks `.attr` and
  `[key]` for free, so five lines of "design" could read `os.environ` and
  `sys.modules` and put the host's state into the netlist. The surface is now
  a table of the methods the builder and its handles declare, and nothing else.
- **A method was an ordinary 2-tuple** in the value space, which the evaluator
  happily indexed — so a design could pull the raw callable out and invoke it
  with arguments the call protocol never saw.
- **`callable(target)`** decided what could be called, which meant anything
  callable that reached the value space could be.
- **The step budget bounded syntax, not work.** Fourteen node visits allocate
  1.25 GB via `range(5000000)`. Collection size is now charged separately.
- **Recursion was checked statically on the call graph**, the way Starlark
  does — but the static graph only sees a cycle routed through a bare name, so
  `helper(helper, 0)` recursed until the interpreter's own stack gave out.
  Depth is now counted at runtime too.

None of this is an argument that a restricted-Python baseline cannot be made
safe. It is a measurement of what "restricted" costs to actually mean, on a
subset small enough to fit on one card, written by someone trying to get it
right. A candidate grammar has no equivalent surface because it has no host
language to restrict.

## Honest limits

**No model has been near this.** Token cost here is a property of a grammar and
a canonical formatter, not of anything a model emitted. Emission accuracy under
the AC5 protocol is AMB-33's run, using these arms as gates
(`bakeoff/gate.py`); the readings above are the half that can be produced
offline for zero spend, and they are not a substitute for the other half.

**Parse level only.** No type checker exists at M0 — that is roadmap Risk 8,
accepted and bounded there. The T9 and L6 readings are preliminary by
construction and AMB-57/R59 re-measures both against the real checker at M2.

**The defect corpus is nine mutations on three designs, not a repair-loop
simulation.** It measures what a grammar says about a broken file, which is a
necessary condition for the loop to converge and not a sufficient one.

**Benchmark (c)'s signal nets are not externally anchored.** `parts.yaml`
states no connectivity, and `power-tree.yaml` states only the series chain
between supply nodes — five edges, all of which are checked. Everything else,
the GPIO headers and the USB and strapping nets, is transcribed from
`pin-plan.md` by hand and verified by nothing outside this package. The power
tree is what turned "the BOM agrees" into "the BOM and the power chain agree";
it did not turn it into "the netlist is correct".

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
| `grammar/rhoform_syntax.py` | the frozen syntax v0, as data, and both emitters |
| `grammar/rhoform.ebnf`, `grammar/rhoform.lark` | generated artifacts; never hand-edited |
| `grammar/conformance.py` | builds a real parser from the Lark artifact |
| `design-model.schema.json` | the arm-neutral design model, with negative controls under `examples/negative/` |
| `examples/coverage-probe.design.json` | the synthetic probe that makes the gate's coverage complete |
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
