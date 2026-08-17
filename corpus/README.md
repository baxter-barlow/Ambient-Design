# Rhoform AC2 Seeded-Bug Corpus

## Purpose

This directory is the **AC2 deliverable**: a curated set of real, externally documented
electronics-design bugs that seeds Rhoform's check development and evaluation, plus the
frozen in/out-of-scope classification the AC2 gate is measured against.

Two issues built it, in that order and deliberately not together:

- **AMB-35 — collection.** 61 entries against a published inclusion rule. No scoping
  judgment was made, because the syntax was not frozen yet and any judgment would have
  been against a moving target.
- **AMB-36 — classification and freeze.** Each entry classified against the *frozen*
  syntax v0.1, the frozen D3 field set, and the ground-architecture scope. See
  [Classification](#classification-amb-36) below.

Files:

- `bugs.yaml` — the corpus
- `classification.yaml` — the frozen verdicts, one per entry
- `validation.log` — collection-phase validation evidence
- `README.md` — this file

Gates: `make check` runs `tests/corpus/check-classification.py`, which proves every entry
is classified exactly once, that every verdict's citation resolves against the artifact it
names, and that the classification still hashes to its committed `decision_hash`.

## Inclusion rule

An entry qualifies only if all three hold:

1. **Externally documented** — a public URL (issue tracker, forum/mailing-list thread,
   postmortem blog, vendor erratum/datasheet, Q&A site) describes the failure.
2. **Diagnosed root cause** — the source (or a credible respondent in it) identifies
   the causal design error, not just the symptom.
3. **Schematic-level** — the defect exists in the connectivity, component selection,
   component values, pin roles, or electrical topology of the design (the abstraction
   level Rhoform's DSL describes). Pure layout, firmware, or process bugs are excluded;
   assembly/DNP errors are included where the schematic-level intent was the defect.

A sub-family of entries (`erc-gap-*`) documents cases where existing code-as-schematic
tools (SKiDL, atopile, tscircuit, KiCad ERC) *failed to catch* a schematic-level bug —
these are direct prior art for Rhoform's check design.

## Entry schema (`bugs.yaml`)

```yaml
- id: BUG-0001            # stable, never reused; gaps mark review removals
  title: <short name>
  source:
    url: <primary public URL>
    kind: github_issue | blog_postmortem | forum_postmortem | mailing_list |
          qa_site | vendor_erratum | other_public
    additional_urls: [...] # optional; kept when duplicates were merged
  symptom: <observed failure>
  root_cause: <diagnosed design error>
  category: <kebab-case failure class, fine-grained>
  class: <coarse class from the fixed vocabulary below>
  evidence: <verbatim quote or evidence note from the source>
  collected: '2026-08-14'
  review: needs-source-recheck   # optional flag, see below
```

The `class` field is a coarse grouping drawn from a fixed 12-value vocabulary:
`power-supply`, `bus-interface`, `pin-config`, `strapping-boot`, `protection-esd`,
`analog-stability`, `clock-crystal`, `usb`, `thermal`, `component-selection`,
`grounding`, `other`. The fine-grained `category` is unchanged; `class` exists so
histograms and check-coverage planning do not depend on the long category tail.

## Provenance rule

**Every entry keeps its source URL.** When the same underlying bug appeared from
multiple sources, the richer entry was kept and the other URLs preserved under
`source.additional_urls` — no provenance is discarded by deduplication.
Five entries left collection carrying `review: needs-source-recheck` — sources that were
bot-walled or returning 403/406, whose evidence rested on search snippets. **All five were
re-fetched in AMB-36 before classification**; the blocks turned out to be fetch tooling,
not paywalls. Each now carries `corrected:` and a `correction_note:`. See
[Corrected at re-check](#corrected-at-re-check-amb-36).

## Removed at review

Two entries were removed in the 2026-08-15 review round. Their ids are retired,
not reused, so the id sequence has gaps at these positions:

- **BUG-0009** (LM2596-ADJ feedback-divider output decay) — removed because the
  entry misrepresented its TI e2e source: the TI engineer stated bias current does
  *not* explain the output collapse and the thread ends undiagnosed, failing
  inclusion rule 2 (diagnosed root cause).
- **BUG-0063** (ISS ExPRESS 28V supply, polarized caps reversed) — removed because
  the defect was a design-change-control/process failure (units assembled to a
  superseded design), excluded by inclusion rule 3 (schematic-level).

## Corrected at re-check (AMB-36)

All five were recovered — none had to stay unverified. Three changed materially (BUG-0034's
root cause, BUG-0035's attribution, BUG-0051's fix) and two in wording only. Recorded here
rather than silently rewritten, because a corpus entry is evidence and its edit history is part
of the evidence.

- **BUG-0034** (MIC5504 enable) — **root cause was stated backwards.** The entry described
  a regulator substitution in which "the new LDO, unlike the old one, has no internal
  pull-down". The MIC5504 *does* have an internal pull-down, that pull-down is what held
  the part off, and there was no substitution — that framing came from unrelated generic
  advice elsewhere in the same article. What happened: an active-high EN was left
  unconnected. This mattered beyond tidiness. A check derived from the old wording ("flag
  EN pins on parts lacking an internal pull-down") would not have caught the bug the entry
  cites; the rule it actually supports is "flag an active-high enable that is neither
  driven nor tied to a rail", which is the generic undriven-input rule. The entry is
  classified in-scope on the corrected text.
- **BUG-0035** (TUSB2046B 22nF/22pF) — two claims removed as unsupported: that the
  *schematic* specified the wrong value, and that TI diagnosed it. The poster says the
  fault was "not ... in my board, but the components I used", which reads as an
  assembly/BOM error. On that reading the entry fails inclusion rule 3 the way BUG-0063
  did, so it is a **retirement candidate** and carries
  `review: schematic-vs-assembly-unresolved`. AMB-36 did not retire it — shrinking the
  population it was asked to classify is AMB-35's call. It is out-of-scope on either
  reading, so the AC2 denominator is unaffected either way.
- **BUG-0031** (ESP32-WROVER MTDI) — root cause confirmed; the previous `evidence`
  presented a paraphrase as a quote, and "intermittently" was not in the source. Espressif's
  boot-mode table was added because it *decides the classification*: MTDI has an internal
  pull-down, so unconnected reads low and is correct.
- **BUG-0045** (wrong strapping pin) — confirmed verbatim; "days lost" narrowed to one
  weekend, and the bench-vs-shipped distinction recorded.
- **BUG-0051** (KSZ9031 RX_CLK strap) — confirmed and corroborated by both vendor
  datasheets. The fix was a pull-up *replaced by* a pull-down, not removed. A later poster
  reproduces it on other PHYs, so it is a class rather than a one-off.

## Counts

**Total entries: 61** (78 raw candidates; 15 removed as same-bug duplicates with
their URLs merged into the surviving entries, then 2 removed at review, above).

### By source kind

| kind | count |
|---|---|
| forum_postmortem | 24 |
| github_issue | 13 |
| blog_postmortem | 12 |
| qa_site | 5 |
| vendor_erratum | 4 |
| mailing_list | 2 |
| other_public | 1 |

### By class (coarse)

| class | count |
|---|---|
| power-supply | 15 |
| bus-interface | 10 |
| strapping-boot | 9 |
| pin-config | 8 |
| analog-stability | 4 |
| usb | 4 |
| other | 3 |
| thermal | 3 |
| protection-esd | 2 |
| clock-crystal | 1 |
| component-selection | 1 |
| grounding | 1 |

### By category (fine)

| category | count |
|---|---|
| strapping-pin-conflict | 4 |
| abs-max-violation | 3 |
| floating-strap-pin | 3 |
| ldo-output-cap-esr-instability | 3 |
| opamp-stability | 2 |
| usb-c-cc-termination | 2 |
| wrong-pullup-value | 2 |
| adc-reference-conflict | 1 |
| brownout-insufficient-bulk-capacitance | 1 |
| bus-voltage-mismatch | 1 |
| comparator-hysteresis-miswired | 1 |
| converter-instability-component-sizing | 1 |
| crystal-load-caps | 1 |
| erc-gap-floating-input | 1 |
| erc-gap-i2c-address | 1 |
| erc-gap-missing-decoupling | 1 |
| erc-gap-missing-i2c-pullup | 1 |
| erc-gap-net-name-collision | 1 |
| erc-gap-phantom-part | 1 |
| erc-gap-shorted-part | 1 |
| erc-gap-voltage-domain | 1 |
| floating-enable-pin | 1 |
| floating-input-pins | 1 |
| floating-pin | 1 |
| i2c-address-conflict | 1 |
| inrush-brownout | 1 |
| logic-level-domain-crossing | 1 |
| missing-decoupling-cap | 1 |
| missing-reset-rc | 1 |
| missing-termination | 1 |
| opamp-biasing | 1 |
| open-drain-vs-push-pull | 1 |
| pin-role-misconfiguration | 1 |
| power-domain-crossing | 1 |
| pull-resistor-contention | 1 |
| regulator-feedback-misconfig | 1 |
| regulator-thermal-sizing | 1 |
| regulator-undersized-brownout | 1 |
| reverse-polarity-protection-omitted | 1 |
| reversed-supply-polarity | 1 |
| series-protection-voltage-budget | 1 |
| spi-bus-contention | 1 |
| standby-drain-missing-undervoltage-cutoff | 1 |
| strapping-pin-wrong-pin | 1 |
| thermal-runaway-bias | 1 |
| uart-tx-rx-swap | 1 |
| unconnected-exposed-pad | 1 |
| vendor-erratum-external-pull | 1 |
| wrong-component-value | 1 |

## Classification (AMB-36)

AC2 supplies the predicate, so the rubric is derived rather than invented:

> each **classified at freeze time — before checker tuning — as in-scope (static-tier
> domain, expressible in the v1 DSL) or out-of-scope**, both populations published.
> Gate: static tier catches **≥90% of in-scope** bugs. The out-of-scope fraction is
> reported as the honest measure of the static tier's limits.

In-scope is a conjunction: **(A)** the defective design is expressible, and **(B)** a
deterministic rule reading only the frozen inputs can tell it from the corrected design.

### Both populations

<!-- generated: classification-summary -->

| population | count | share |
|---|---|---|
| **in-scope** (static-tier domain, expressible in the v1 DSL) | 22 | 36% |
| **out-of-scope** | 39 | 64% |
| total | 61 | |

AC2 gate: the static tier must catch **20 of 22** in-scope bugs (≥90%).

| in-scope check family | count |
|---|---|
| `abs-max-containment` | 4 |
| `current-budget` | 1 |
| `erc-pin-role` | 12 |
| `net-topology` | 3 |
| `voltage-domain-crossing` | 2 |

| out-of-scope reason | count |
|---|---|
| `d3-gap` | 29 |
| `dynamic-vocabulary` | 5 |
| `not-expressible` | 2 |
| `v1-non-goal` | 3 |

**Margin.** 16 of 22 in-scope entries are flagged `at_risk` — verdicts whose catch is conditioned on one of four things: an implementation choice; a **defensible alternative** part-record transcription; an open-map fact; or an attribute the frozen grammar makes optional, which the design under test is therefore not required to declare. The defensibility test is what keeps the second category from covering everything — a dedicated I2C peripheral pin roled `open_drain` has no defensible alternative, while a general-purpose GPIO roled `bidirectional`, an AREF pin roled `passive`, a reserved pin roled `nc` and a record with no transmit mode all do. The fourth category is a grammar fact: `net_decl ::= 'net' FREE_NAME net_attributes? ...` — a design that declares no `voltage_domain` silences every rule that reads one.

- `BUG-0012` — reads a `voltage_domain` attribute the grammar makes optional, so a design under test that declares none silences the rule
- `BUG-0019` — in-scope on the L9b undeclared-single-pin-net leg only; the fix adds a pull resistor, so a T2 rule keying on "no driver" fires on both versions
- `BUG-0020` — both legs need directional roles on MCU UART pins that are defensibly transcribed `bidirectional`
- `BUG-0022` — the SCL pin is a general-purpose STM32 GPIO, and this corpus itself records that such pins transcribe as `bidirectional`; roled that way rather than `open_drain`, the missing-pull-up rule is silent
- `BUG-0023` — T10 fires only if the part record transcribes a transmit mode; D3 v0 has no pin-class mechanism and the example records populate only what the benchmarks use, so a record can inherit the designer's own omission
- `BUG-0025` — the abs-max leg is independent, but the domain leg reads the optional `voltage_domain` attribute
- `BUG-0026` — same L9b-only shape as BUG-0019
- `BUG-0027` — reads the optional `voltage_domain` attribute to know the net is 5 V
- `BUG-0029` — FT232RL TEST is a reserved pin, and `nc` is a defensible transcription — the one role a checker exempts from both the undriven-input and single-pin-net rules
- `BUG-0030` — depends on the exposed pad being transcribed with a supply role AND `package.thermal_pad` being set; either omission silences the rule
- `BUG-0040` — same optional-attribute dependency as BUG-0012; these two are the whole `voltage-domain-crossing` family
- `BUG-0042` — in-scope on a generic "power_in pin with no capacitor to ground" rule; AC2 also demands zero spurious errors on the benchmarks, and narrowing the rule for precision loses this
- `BUG-0054` — the abs-max bound is relative and its qualifying condition lives in `conditions`, an open map this gate now formally declares unreadable
- `BUG-0055` — the floating-input leg is L9b-only like BUG-0019, but the abs-max leg is independent of it, which makes this the least exposed of the flagged entries
- `BUG-0056` — same generic decoupling rule as BUG-0042, and lost with it
- `BUG-0059` — in-scope only if AREF is transcribed with a driving role; recorded `passive`, the contention rule goes silent

This is an upper bound on exposure, not a prediction: the flags are not independent and most will resolve the favourable way. But if every one went against the checker the tier would catch 6 of 22 against a bar of 20, so the honest statement is that **the AC2 outcome is decided by part-record authoring and rule-implementation choices, not by this classification**. 16 of 22 verdicts are conditional; only 6 are unconditional, which is fewer than the bar. AMB-61 should resolve the flags deliberately rather than discover them. Losing them also empties `current-budget`, `voltage-domain-crossing` entirely, so the gate would stop testing those families at all — which no count above shows.

The 29 `d3-gap` entries by missing fact. Each row is also the counterfactual: add that field and those entries become candidates for in-scope at the next `schema_version`.

| missing D3 fact | entries | with a residual blocker |
|---|---|---|
| `companion-requirement` — a requirement a part places on an external companion component | 11 | `BUG-0016`, `BUG-0035`, `BUG-0053` |
| `strap-semantics` — which pins latch at reset as configuration straps, and to what level | 6 | — |
| `functional-class` — what a part IS — regulator, protection diode, undervoltage cutoff | 4 | `BUG-0049` |
| `bus-address` — the bus address a part presents, fixed or strap-selected | 2 | — |
| `internal-pull` — a pin's internal pull-up or pull-down presence and strength | 2 | `BUG-0021`, `BUG-0032` |
| `part-own-value` — a part's own defining value that no closed field enumerates | 2 | `BUG-0010`, `BUG-0052` |
| `pin-semantics` — what a pin MEANS beyond its electrical role — which outputs it gates, its polarity | 2 | — |

Counted once but blocked by more than one missing fact, so the single row understates what each needs: `BUG-0002`, `BUG-0003`, `BUG-0008`, `BUG-0043`, `BUG-0051`, `BUG-0061`.

Entries in the third column carry a blocker that survives adding the field, named in `classification.yaml`. For one of them the counterfactual is not merely weaker but inverted: adding the fact would make the generic rule flag the *corrected* design.

1 of those entries make a weaker claim than the rest: the fact is already in D3 v0, in an open map, so the fix is to **promote** a key rather than add a field. They are marked here rather than given their own reason code, because a code with one member costs more than it buys.

| entry | carried at | further blocker, if any |
|---|---|---|
| `BUG-0052` | `parameters` | the root cause is that stray capacitance was ignored, and stray C is a layout quantity the DSL holds no coordinates for |

<!-- /generated -->

Per-entry verdicts, each with the citation that decided it, are in `classification.yaml`.

### What "out-of-scope" does and does not mean

It means *the static tier* cannot decide it. It does not mean Rhoform misses the bug: the
`dynamic-vocabulary` entries are ones where the ngspice tier is the tier that would catch them —
subject to macromodel fidelity, which V5 grades behavioral vs physical and v1 does not promise.
Reading the out-of-scope count as a list of things the product cannot do would misrepresent it;
reading them as guaranteed catches would overclaim in the other direction. Counts live in
the generated block, not here.

### The decision procedure

Ordered, first match wins. The order is load-bearing — a bug that cannot be written down never
reaches the question of whether a checker could read it — so it is published rather than implied.

1. **`not-expressible`** — the defective design cannot be written in frozen syntax v0.1.
2. **`v1-non-goal`** — root cause is a declared §3 non-goal: layout/XY, fab outputs, thermal,
   EMI, mechanical, digital simulation.
3. **`ground-arch-excluded`** — root cause is a ground-architecture §7 exclusion.
4. **`dynamic-vocabulary`** — deciding it needs time- or frequency-domain behaviour, and V2's v1
   vocabulary covers the measurement.
5. **`dynamic-deferred`** — same, but the measurement is on V2's deferred list (phase/gain
   margin, SOA, THD/FFT, Monte Carlo), so v1 has no tier for it.
6. **`d3-gap`** — the check would be static, instant and expressible, but the fact it must
   read is not available. Entries whose fact is *present* in D3 but only behind a conventional
   key in an open map carry `carried_at` naming that map, and are marked separately in the
   generated table: for those the fix is a promotion rather than an addition, which is a weaker
   claim and must not borrow the stronger one's counterfactual.
7. **`in-scope`** — everything that survives, naming the check family and the capability it reads.

Each out-of-scope code names a **pre-existing declared exclusion**, never a judgment invented
while classifying. That is the property that keeps the out-of-scope population honest.

**Steps 4/5 versus step 6** is the boundary that needed a stated rule, because both can be
argued for the same entry: **step 6 when a published datasheet requirement — a window, a
minimum, or a categorical qualification — would decide it statically; step 4 when the failure is
inherently a waveform that no published requirement decides.** That rule is what puts the three
LDO output-capacitor entries (BUG-0005, BUG-0033, BUG-0053) together, and what separates them
from BUG-0060, where the compensation network was derived on the bench and no datasheet states it.

**Ambiguity in a source resolves toward in-scope.** The classifier is the party who benefits
from out-of-scope, since a smaller denominator makes the AC2 gate easier, so a tie is not
neutral. The rule is published because it should govern future entries, but **it currently
decides nothing**: a draft applied it to BUG-0002, and that entry was then settled on a frozen
artifact instead — `ir/netlist-ir.schema.json` says a `dnp` part stays in the netlist, so the
ambiguity it turned on stopped mattering. BUG-0031 is not a tie either, and says why: an
unconnected MTDI reads low through the part's internal pull-down and is *correct*, so the
floating reading is incoherent rather than merely less likely.

### Two interpretations this rests on

Both are consequential enough that a reviewer should be able to disagree with them directly
rather than reverse-engineer them from the verdicts.

**1. "Expressible in the v1 DSL" is not "has a dedicated production in v0.1 today."** The frozen
syntax fixes the *shape* of the language — modules, instances, pins, nets, attributes, assertions
— and its closed vocabularies. It is not a freeze of the v1 feature set; T1's parameterised
interface types are a Must requirement that will be written within that shape. The closed
vocabularies *are* binding, and they decide several verdicts: there is no `measurement_kind` for
a logic level at reset, which is why no strapping bug can be rescued by declaring an assertion.

**2. A check may rely only on facts in the netlist, the checker-reliable D3 v0 fields, or
contracts the design itself declares.** The line is not that open-map data is invisible — it is
real data, it is unit-carrying, and `parts/lint-part-data.py` already validates units across those
maps. The line is that **their key spellings are conventional rather than enum-enforced**, so a
check keyed on `parameters.esr` is keyed on a name nothing freezes. `pins[].role`, `abs_max`,
`recommended`, `capability`, `modes[].draw` and `package` are closed and named; `parameters`,
`ratings.*`, `characteristics` and `conditions` are not.

An earlier draft justified this by claiming those maps constrain neither names nor units. That
was wrong on the artifact — `NamedMeasures` pins `propertyNames` to a pattern, every value is a
`Measure` with a required unit, and `parts/lint-part-data.py` already checks unit agreement
across them. The correction matters and is kept.

What the correction does **not** license is treating open-map data as readable. A draft flipped
BUG-0002, BUG-0010 and BUG-0052 to in-scope on the grounds that a polyfuse's resistance and a
crystal's CL are the part's *own* values rather than requirements placed on a companion. That
distinction is real but **orthogonal** to checker-reliability: an own value behind an unfrozen
key is still not a fact a check may read. All three are reverted, and each turned out to fail on
its own entry text as well — BUG-0002 because `ir/netlist-ir.schema.json` states that "a dnp
component is still present in the netlist", so the buggy and corrected designs are the same
netlist; BUG-0010 because its failure is a *degraded* fuse measured over 1 ohm, not a design-time
value; BUG-0052 because its root cause is precisely that stray capacitance was ignored, which a
comparison over declared values reproduces rather than catches.

The distinction the correction *does* buy is a sharper claim. `carried_at` marks the entries
whose fact D3 v0 already carries in an open map; the gate resolves it and requires it to end in
an open map and to sit at the same scope as the fact it stands in for. So the published finding
distinguishes "add a field" from "promote one", the machine checks which, and neither borrows the
other counterfactual. This began as its own reason code and was collapsed back: once the residual
kinds that empty a promotion were enforced, it had one member, and a code with one member costs
more than it buys.

**On the asymmetry between them.** Interpretation 1 judges the DSL at v1 while interpretation 2
judges D3 at v0, and that looks inconsistent until you read where each comes from. AC2 says
"expressible in the **v1 DSL**", so expressibility is a v1 question by its own words. AMB-36 says
classify against "the frozen syntax, **the D3 field set**, and the ground-architecture scope", and
the D3 field set that is frozen is v0 (AMB-34). The asymmetry is in the source documents, not
introduced here. The counterfactual is not left to be imagined: the gap table above is generated
per entry, so "close this gap class and N entries become candidates" is computable rather than
asserted.

The alternative reading that was rejected: had library content counted as a frozen input — a
stdlib `UsbCSink` type declaring Rd = 5.1k, say — entries in the `companion-requirement` and
`bus-address` classes would be candidates for in-scope instead. It was rejected because D5's seed
library does not exist yet, and a denominator resting on unwritten library code could be moved by
writing some. No count is put on it here: the reading cuts across two gap classes and is not
derivable from the verdicts, so quantifying it would be exactly the hand-counted number this
document is trying not to publish.

### The finding: the limit is the data, not the tier

Most of the out-of-scope population turns on part data, and it is not that many different
problems — a handful of missing facts account for nearly all of them. The counts, the gap table
and the separate promotion table are generated from the verdicts, in the block above, so nothing
here restates a number that could drift from it.

That is the actionable output of this issue. The static tier's reach is limited far more by D3
v0's deliberately small closed surface than by anything about static analysis, and each row is a
concrete candidate for the first `schema_version` bump (§8-Q3). Three entries — BUG-0005,
BUG-0033, BUG-0053 — land on the regulator output-capacitor requirement, which is the strongest
single case in the set; stated precisely, two of those are postmortems and the third
(BUG-0053) is a datasheet caveat, flagged as such in the corpus.

Caveats, because this is the part most likely to be quoted alone:

- **A `carried_at` entry asks for a promotion, not an addition.** It names the open map its
  fact already lives in — for the internal-pull cases, `pins[].characteristics`, which
  `parts/part-data.schema.json` documents with the example key `pull_up_resistance`. The
  distinction exists because an earlier draft filed these with the true gaps and handed them a
  counterfactual that was false for every one.
- **A missing field is not always a conservative absence.** For BUG-0049, recording the pin's role
  either way makes the generic contention rule flag the **corrected** design.

### Coverage gap: ground architecture is untested by this corpus

The issue names the ground-architecture scope as one of three frozen inputs, and it decided
almost nothing: one entry cites a GA rule, and no entry is `ground-arch-excluded` or lands in the
`ground-architecture` family. That is not an oversight in the classification — it is a property of
the corpus. There is exactly one `grounding`-class entry (BUG-0030, an unconnected exposed pad),
and no net-tie, star-ground, isolation-barrier or chassis/earth bug at all.

The consequence is worth stating before AMB-61 rather than after: **AMB-37's rules GA-1…GA-17 and
diagnostics RHO4001…RHO4010 will not be exercised by the AC2 gate.** Passing AC2 will say nothing
about whether the ground-architecture checker works. Closing that needs corpus augmentation, which
is AMB-35's territory, not a reclassification.

### Risks carried into AMB-61

**The margin arithmetic is generated, not written here** — it is in the summary block above, from
the `at_risk` annotations on the entries themselves, because it is both the number AMB-61 is meant
to plan against and the most drift-prone sentence in this file. The short version is that the
margin is already committed: lose every flagged entry and the gate fails.

The flags, and two risks that are not about margin:

- **`net-topology` decoupling rules are the spurious-error risk.** BUG-0042 and BUG-0056 are
  in-scope on a generic "power_in pin with no capacitor to ground" rule. AC2 also demands zero
  spurious static errors on the three benchmarks as authored. Narrow the rule for precision and
  both are lost.
- **BUG-0059 is the verdict most sensitive to part-record authoring.** In-scope only if AREF is
  transcribed with a driving role; recorded `passive`, the rule goes silent.
- **T10 budgets modes, not surges.** BUG-0001 and BUG-0023 are near-identical brownouts split by
  the shape of their fixes: BUG-0023's supply was undersized against a documented mode, BUG-0001's
  was adequate and its transient was not. T10 claims brownout is "trivially checkable over data D3
  already carries"; that holds for sustained modes and not for sub-millisecond surges. A
  requirements question, not one for this issue.
- **Where the T2 leg does not discriminate.** BUG-0019, BUG-0026 and BUG-0055 are corrected by
  *adding a pull resistor*, so an undriven-input rule keying only on "no driver" fires on both
  versions. They are in-scope on the L9b leg — the buggy net is a single-pin net never declared
  `isolated` — and AMB-61 should implement that leg, not the T2 one, for these three.

### How these verdicts were produced

Every entry was classified twice: once by the author against the rubric, and once by an
independent pass that had the same rubric and the corpus but not the author's verdicts, followed
by an adversarial pass whose brief was to overturn each verdict. Disagreements were adjudicated
against the frozen artifacts, and the adjudications went both ways rather than toward a
convenient number.

Recorded because publishing only the reversal that lowers the denominator would be selective:

| entry | change | direction |
|---|---|---|
| BUG-0017, BUG-0021, BUG-0041, BUG-0043 | author's in-scope reading overturned by the independent pass | narrows in-scope |
| BUG-0031 | independent pass's in-scope reading overturned on the vendor datasheet | narrows in-scope |
| BUG-0034 | out-of-scope overturned by the adversarial pass, then confirmed by the source re-check | widens |
| BUG-0002, BUG-0010, BUG-0052 | flipped to in-scope in review, then **reverted** when the flips proved unsound | none, net |
| BUG-0005, BUG-0053 | cited field and `missing_fact` corrected; the reason code did not change | none |
| BUG-0057, BUG-0061 | `dynamic-vocabulary` re-keyed to `d3-gap` under the published discriminator | none |
| BUG-0062 | re-keyed to `d3-gap`, then **reverted** — no datasheet states the mid-rail bias requirement, so step 6's test is not met | none, net |
| BUG-0060 | kept `dynamic-vocabulary` against the author's `dynamic-deferred` | none |
| BUG-0010, BUG-0021, BUG-0032, BUG-0052 | re-coded to a promotion claim, then three of the four re-coded back when the residual that empties a promotion was enforced | none |
| BUG-0047 | filed as an open-map value, corrected to `companion-requirement`: what the schema cannot say is that an external pull is required at all | none |

### How the freeze works

`classification.yaml` carries a `decision_hash` over each entry's decision fields and the
falsifiable claims behind them — **not** over the rationale prose, so that fixing a typo is not
indistinguishable from reclassifying. The exact field list lives in `decision_hash` in
`tests/corpus/check-classification.py` and is deliberately not repeated here: this sentence went
stale three revisions running when it tried to. The gate recomputes the hash and fails on a
mismatch. Reclassification stays possible and is sometimes right; what it cannot be is
quiet.

The gate resolves citations rather than pattern-matching them: `d3:` paths are walked
against `parts/part-data.schema.json`, and `syntax:` and `vocab:` tokens against the frozen
grammar module. Citations into the Notion specifications (`ga:`, `req:`, `v2:`, `nongoal:`)
resolve against lists transcribed into the gate, because it must run offline in CI — the
gate reports those as transcribed rather than passing them off as verified.
