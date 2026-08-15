# Measurement harness

Token-cost measurement, the AC5 repair-loop trial protocol, and result
capture. Two consumers, about nine months apart:

- the **§8-Q1 syntax bake-off** — candidate grammars measured on token cost
  and emission accuracy, against throwaway prototype parsers;
- the **AC5a gate run** — the same protocol against the real `aed check`.

The issue says "reused verbatim by the AC5a gate run — build once", so
nothing here is written against a concrete compiler. A gate is anything that
can look at emitted source and return a verdict plus diagnostics; `aed check`
plugs in later as a `CommandGate` with no change to the protocol, the result
format, or the statistics.

```
python3 -m unittest discover -s eval/tests -t eval   # 42 tests, stdlib only
cd eval && python3 -m aed_eval selftest              # statistics vs closed form
cd eval && python3 -m aed_eval replay --transcript fixtures/demo-replay.json --allow-stub
cd eval && python3 -m aed_eval plan --rate-a 0.6 --rate-b 0.9
```

`make check` runs the first three.

## Modules

| File | Role |
|---|---|
| `stats.py` | Exact small-sample statistics: AC5a threshold rule, Wilson intervals, Fisher and McNemar exact tests, exact power by enumeration |
| `tokenizer.py` | The pinned budget tokenizer, pinned behaviourally; the A4 12K context budget |
| `protocol.py` | The AC5 trial loop: emit, extract, check, repair |
| `gates.py` | `CallableGate`, `CommandGate`, `CompositeGate`, `ReplayGate` |
| `models.py` | `AnthropicClient`, `ReplayClient` with divergence detection |
| `results.py` | Run-record assembly and canonical serialization |
| `run-result.schema.json` | The result contract, validated by `make check` |

## Things worth knowing before you trust a number from this

**A gate can be a pipeline.** AC5a's bar is "compile/type-check/export
gates" — plural — so `CompositeGate` chains stages and each `CommandGate`
carries its own stage name. It short-circuits on the first failure: running
export over a design that failed type-checking produces cascade noise, and
P2 makes diagnostic quality the thing the repair loop converges on. The
failing stage travels out on `GateResult.stage` with the stages that already
passed, so a grammar that fails to parse stays distinguishable from one that
parses and then fails to export.

**Two token counters, on purpose.** *Budget tokens* come from the pinned
local tokenizer and answer "is grammar A cheaper than grammar B?" and "does
the A4 context fit in 12K?". *Trial tokens* come from the provider's reported
usage and answer "what did this cost?", which is the only defensible source
for the AC5 150K-per-trial budget. The local tokenizer is a common ruler, not
a claim to reproduce any model's tokenization — unverifiable for a closed
tokenizer, so AED does not assert it.

**The tokenizer is pinned by behaviour, not by file hash.** The pin is a
sha256 over the encoding's token counts on a fixed probe corpus. Behaviour is
what changes a count: a re-packaged artifact that tokenizes identically
should not fail the pin, and a same-named artifact that tokenizes differently
must. Never edit `PROBE_CORPUS` — it would invalidate every recorded pin.

**A stub can never satisfy a gate.** The test tokenizer reports
`gating: false`, and `authoritative` on a run record is *computed* from the
tokenizer and model identities rather than passed in. A replayed, scripted or
stub-tokenizer run is structurally incapable of presenting itself as gate
evidence, and the run-result schema enforces the same rule independently.

**AC5's iteration budget is ambiguous, and this records which reading it
used.** "≤3 repair iterations (1 iteration = one write + one `aed check`)"
supports both *3 write+check cycles in total* and *the first emission plus 3
repairs*. The second is about 33% more generous. Both are expressible, the
stricter is the default, and every result states which applied — so numbers
taken under different readings can never be silently compared. **This should
be settled in the requirements document.**

**Budgets are conjunctive.** A trial passes only if the gate passed *and* it
stayed inside both the iteration budget and the token budget. Passing on the
last cycle having spent 200K tokens is a failure.

**No retries.** A failed API call fails its trial. Retrying until a trial
succeeds is the same "retry to green" pathology the project prohibits for
simulation, and it would bias the very pass rate AC5a gates on.

## The sample-size finding

The statistics module exists because AC5a's ten trials and §4's comparison
are different questions, and ten trials only answers the first.

`python3 -m aed_eval plan` reports exact power. Against a true 0.60-vs-0.90
difference — enormous by any standard — the one-sided test at 10 trials per
arm has:

| n per arm | power |
|---|---|
| 10 | 0.29 |
| 20 | 0.62 |
| 30 | 0.80 |
| 50 | 0.96 |

So a bake-off that ran 10 trials per arm and found no significant difference
would have learned almost nothing, and reporting that as "no difference" would
be wrong. Two consequences:

1. **Budget the §4 comparison from `plan`, before spending tokens.** At
   roughly 150K tokens per trial, sample size *is* cost.
2. **Pairing would halve the cost, but only with a real blocking factor —
   and matching seed numbers are not one.** A paired test assumes trial *i*
   of each arm shares something that correlates their outcomes. In the AC5
   protocol as specified, every trial of an arm runs the *same* prompt on the
   *same* benchmark and differs only by provider sampling; the seed labels a
   trial, it does not seed the model. So trial 3 of two arms share nothing
   but an index, and McNemar would report precision the design has not
   earned.

   This was a real defect: `build_run_record` used to infer pairing from the
   seed lists lining up. It now pairs only when a blocking factor is
   explicitly named via `paired_by`, and the default is the unpaired Fisher
   test. Pairing becomes legitimate the moment a genuine factor exists —
   several distinct benchmark designs with both arms run over each — because
   then trial *i* really does mean "the same design, both arms". If the
   bake-off wants the cheaper comparison, that is the design change to make.

`flip_verdict` is three-valued — `flip_criterion_met`,
`flip_criterion_not_met`, `inconclusive`. That is a real outcome, not a
rounding of "not met", and collapsing the two is how an underpowered run gets
read as evidence of equivalence.

**"Adequately powered" requires a pre-declared effect size.** The claim is
only meaningful relative to a difference someone committed to caring about,
and it has to be chosen *before* the data — choosing afterwards is choosing
the standard that gives the answer you already saw. So
`minimum_effect_of_interest` has no default: without it, a non-significant
run returns `inconclusive`, and the result schema makes
`flip_criterion_not_met` literally unrecordable in that case.

This was a real defect caught in review. An earlier version computed power
against a hardcoded 0.60-vs-0.90 reference regardless of the data, so at
n = 30 *any* non-significant run came back "not met" claiming adequate power
— including runs whose actual observed difference left real power near 0.16.
Power against the observed effect is still reported, but only as
information: observed power is a monotone function of the p-value and can
never justify an adequacy claim.

## Fixtures

`fixtures/demo-replay.json` is generated by `fixtures/make_demo_transcript.py`,
which drives the real protocol with a scripted model and records what the
protocol actually asked for. It is not hand-written: a hand-written transcript
would drift from the protocol and its request digests would be fiction.

It is **synthetic**. The responses and verdicts are scripted to exercise every
path — first-shot pass, repair-loop recovery, a response with no fenced code
block, iteration-budget exhaustion — and no conclusion about any model or
grammar may be drawn from it. The record it produces is marked
`authoritative: false` for that reason.

Regenerate after any change to the protocol or the prompt construction:

```bash
python3 eval/fixtures/make_demo_transcript.py
```

The digest check earns its keep. It caught a real bug during development:
`build_repair_message` rendered diagnostic parameters with Python's dict
repr, which follows insertion order, so a diagnostic round-tripped through
JSON produced a different prompt and therefore a different run. It now renders
key-sorted JSON.

## Not built yet

- No live AC5a run. `toolchain/versions.yaml` leaves `evaluation.model` unset
  rather than guessing; the harness refuses to record a run without a stated
  model and sampling parameters.
- The bake-off's candidate-grammar parsers are AMB-32's scope. They plug in
  as `CallableGate` or `CommandGate`.
- Cost estimation in currency. Deliberately absent: prices change, and a
  stale price in a result record would be worse than none.
