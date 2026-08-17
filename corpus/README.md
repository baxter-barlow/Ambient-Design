# Rhoform AC2 Seeded-Bug Corpus (collection phase, AMB-35)

## Purpose

This directory is the **collection deliverable for AC2** of the Rhoform bug-corpus work
(Linear issue AMB-35): a curated set of real, externally documented electronics-design
bugs that will seed Rhoform's static/dynamic check development and evaluation.

**This phase collects only.** Classification of each bug as in-scope or out-of-scope
for the Rhoform DSL happens later, in **AMB-36**, against the *frozen* AC2 syntax.
No in/out-of-scope classification is assigned here, deliberately: the DSL syntax is
not frozen at collection time, so any scoping judgment made now would be against a
moving target and would have to be redone. Scoping decisions must be deterministic
and reviewable against a fixed language definition; collecting and classifying in
one pass would entangle the two and make the classification unreproducible.

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
Entries whose evidence was only confirmable via search snippets (source bot-walled
or returning 403/406 at collection time) carry `review: needs-source-recheck`
(5 entries: BUG-0031, BUG-0034, BUG-0035, BUG-0045, BUG-0051).

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

## Files

- `bugs.yaml` — the corpus (validated with `python3` + `yaml.safe_load`)
- `validation.log` — validation evidence and final counts
- `README.md` — this file
