# AED v1 Roadmap

Scope: entirety of v1 (v1.0-core + v1.0-verify) per `dsl-design-requirements.md` v0.1. Team: 2–3 engineers, start 2026-09-01. Status: approved by adversarial review panel (4 lenses, 2 revision rounds, final gate passed 2026-08-12). Mirrored to Linear project "Agentic Electronic Design".

## Scheduling model (read first)

- **Milestones are landing windows, not start windows.** Work starts when its dependencies clear per the dep graph; the milestone is where it must land. Long-leads (R29c CAD, R34 placement, R46a models, R8a corpus) start milestones before they land.
- **Velocity conversion, stated:** dates assume team throughput ≈ 6 pts/week (2.5 engineers). Total plan = **262 pts** (per-milestone sums in the table) ⇒ ~44 ideal weeks against ~54.5 calendar weeks ⇒ **~20% schedule buffer** — thin, and stated as such. **Plan-wide 2-engineer rule:** at 2 engineers (~4.8 pts/week) the buffer is zero; every date after M1 slips +25% (verify ship → ~2027-12). This subsumes Risk 3's compiler-specific rule.
- **The §3 cut order is exhausted at baseline.** T8, L6, V5≥R2, and T7 are already unscheduled in this plan; the only remaining sanctioned lever is I10 relaxation (~2 pts). Therefore **any material overrun forces a §3 requirements-doc revision, not a cut.** Candidate Must-descopes proposed now, before gate pressure, for that revision if needed: (i) R31 reduced to hash-refuse without the three resolution flows; (ii) R14b registry stub deferred to v1.x; (iii) AC5b's non-gating (b)/(c) reporting narrowed; (iv) R58 hosted-service v0 narrowed to fetch-on-demand proxy only. None may be taken silently.
- **Honest tension with §3:** at stated velocity, core lands 2027-05-30 (3 quarters incl. M0 pre-phase) and verify 2027-09-15 — a quarter over the doc's ~2-quarters-per-phase target, declared here rather than discovered later.
- **Estimates are relative points** (1/2/3/5/8), re-estimated at milestone boundaries; dates after M1 are expected to move ±2 weeks and that is normal, not failure.

## Planning principles

1. **Freezes first.** M0 lands every freeze the doc requires before dependent work: AC2 corpus classified before checker tuning; D3 reservations before freeze; package-identity rules spec'd before syntax freeze (L4); ground-architecture spec'd before AC1(b) checker work (§8-Q6). Naming (§8-Q2) is **not** on the syntax-freeze path — the doc only requires it before exemplars/telemetry (R36/R38).
2. **Benchmarks are the spine.** Reference designs authored in M0 (R11), re-expressed in AED in M1 (R53) the moment the elaborator can hold them; they drive V2 vocabulary, D4 manifest, D5 part list, and every gate.
3. **Milestone = demonstrable capability.** Each ends with something runnable end-to-end on a benchmark, because the repair-loop thesis (P2) is only testable against a working loop.
4. **Long-leads start early regardless of landing milestone** — each is flagged inline with its start milestone.
5. **S-items scheduled only where the doc gates on them** (I10 measurement, L6/T9 bake-off inputs). Everything else S/L stays unscheduled — better general than overconstrained.
6. **AC gate-run issues carry deps audited against the AC text**, not milestone position — the dep graph, not milestone boxes, is the scheduling instrument.

## Milestones

| # | Name | Target | Pts | Exit condition |
|---|------|--------|-----|----------------|
| M0 | Foundations & freezes | 2026-11-01 | 45 | Syntax v0 frozen post-bake-off; D3 v0 frozen w/ reservations; package-identity rules spec'd; IR v0; AC2 corpus frozen+classified; ground-architecture spec'd; benchmark reference designs done |
| M1 | Compile leg | 2027-01-17 | 43 | All three benchmarks (a)(b)(c) parse→elaborate→IR; `aed fmt` idempotent (AC6); diagnostics NDJSON live; spec+conformance suite skeleton in-repo |
| M2 | Static type system | 2027-02-28 | 36 | R53 benchmarks type-check with zero diagnostics; R54 conformance sections green; benchmark-part D3 data complete; lockfile schema v0; T9/L6 final call made (§8-Q1 complete) |
| M3 | Determinism, KiCad handoff & AC2 | 2027-04-25 | 55 | AC2 gate ≥90% in-scope / zero spurious; AC4 both legs green incl. rename leg; exports ERC-clean in KiCad 9+10; non-gating AC5 dry-run observed |
| M4 | Agent surface & core gate | 2027-05-30 | 24 | AC1-core gate run (one-command, line limits, offline leg); AC5a ≥7/10; A4 ≤12K budget enforced; AC7; M·core completeness sweep; **v1.0-core ships** |
| M5 | Simulation tier | 2027-08-01 | 38 | Benchmark (b) dynamic assertions run end-to-end on D4 core models; (a) freq/duty measured |
| M6 | Discovery & verify gate | 2027-09-15 | 21 | A7 live (offline + hosted v0); AC3, AC1-sim, AC5b; **v1.0-verify ships** |

Cumulative ideal-velocity check: 45/88/124/179/203/241/262 pts ⇒ ideal landing ~Oct 23 / Dec 13 / Jan 25 / Mar 29 / Apr 26 / Jun 10 / Jul 5; dated targets carry the ~20% buffer, weighted toward the statistically-gated milestones (M3/M4/M6).

## Issues

Format: `ID · Title [workstream] (est, P#) — deps`. P1=critical path/freeze, P2=high, P3=medium.

### M0 — Foundations & freezes

- **R1 · Repo bootstrap: monorepo, licensing split, DCO, CI skeleton** [governance] (3, P2) — deps: none. Apache-2.0 code / CC-BY-4.0 spec dirs, DCO check, pinned toolchain, golden-file harness scaffold, pinned kicad/kicad + ngspice Docker in CI. (E2/E3 partial)
- **R3 · atopile attribution outreach** [governance] (1, P2) — deps: none. Calendar-bound; start day 1. Not on any freeze path.
- **R4 · Language name + file extension decision** [governance] (1, P2) — deps: R3 (with a hard latest-date of M2 exit so outreach can't drift). Gates R36 exemplars + R38 telemetry only (§8-Q2). Placeholder extension/pragma spelling until then is a trivially-migrated cost.
- **R5a · Bake-off measurement harness + AC5-protocol rig** [lang] (5, P1) — deps: R1. Token-cost measurement under pinned tokenizer, repair-loop trial protocol, result capture. Reused verbatim by R37/AC5a. (§8-Q1, §4)
- **R5b · Two candidate-grammar prototypes + Starlark baseline** [lang] (8, P1) — deps: R5a. Throwaway prototype parsers for both L5-conformant candidates plus the Starlark-restricted-Python baseline (§4's budgeted line item). Bake-off measures token cost + parse-level emission accuracy; **T9 annotation-tax and L6 columnar get preliminary reads here, final calls deferred to M2 when a type checker exists** — R6 records the freeze basis honestly. (§8-Q1, L6, T9)
- **R6 · Run bake-off, decide grammar, freeze syntax v0** [lang] (3, P1) — deps: R5b, R14a. EBNF + Lark from one source of truth; `#pragma` version header (L8); freeze-basis memo (what was and wasn't measured). **Not blocked on R4.** (L5, L8, §8-Q1)
- **R7 · D3 part-data schema v0 freeze** [parts-data] (3, P1) — deps: R1. Pins/roles/abs-max intervals, supply-current-per-mode, reserved per-pin current capability (T10) + multi-unit/shared-package fields; provenance + license-class; versioned-but-unstable marker. (D3)
- **R8a · AC2 bug-corpus collection** [benchmarks] (3, P2) — deps: none. Starts day 1, calendar-bound: ≥50 candidates, majority externally sourced (forum postmortems, atopile issues, errata).
- **R8b · AC2 corpus classification + freeze** [benchmarks] (2, P1) — deps: R8a, R6, R7, R9. In/out-of-scope classified against the *frozen* syntax, D3 field set, and ground-architecture scope — before any checker tuning; both populations published. (AC2)
- **R9 · Ground-architecture semantics spec** [types] (3, P1) — deps: none. Net-ties, star grounds, chassis/earth; blocks R22 and R8b. (§8-Q6, T5)
- **R10 · IR v0: versioned JSON netlist schema + source-map model** [lang] (3, P1) — deps: none. No external stability promise. (I4, I9)
- **R11 · Author the three benchmark reference designs** [benchmarks] (8 = a:2 + b:3 + c:3, P1) — deps: none. Real EE design work, gate-load-bearing: (a) 555 blinker, (b) 3.3V/2A buck — topology, inductor/FET selection, assertion values **hand-validated once in raw ngspice so AC3 surprises surface now, not M6** — (c) ESP32-S3 devboard ~60-component part list. Outputs: netlists, part lists, assertion lists; derives D4 manifest + D5 part list. (AC1/V2/D4/D5 inputs)
- **R14a · Package-identity & registry rules spec** [lang] (2, P1) — deps: none. L4 requires rules spec'd *before syntax freeze*; implementation may stub. Blocks R6.
### M1 — Compile leg

- **R2 · Governance pack** [governance] (2, P3) — deps: R1. License-stability covenant, trademark checklist, EU-establishment decision log, §8-Q3 promotion criteria draft. (E2, E3)
- **R54 · Language spec + conformance suite (standing)** [lang] (3 initial, P2) — deps: R6. CC-BY-4.0 normative spec skeleton + in-repo conformance/golden-file suite, **grown at every milestone**: T3 literal normal form authored first (consumed by both R16 and R21 — single source), T5 transfer semantics land with R22, parser ambiguity-rejection tests with R12. (E2, T3, T5)

- **R12 · Lexer/parser: INDENT/DEDENT, error-tolerant, generated from grammar SoT** [lang] (5, P2) — deps: R6. Ambiguity-rejection tests into R54 suite. (L5)
- **R13 · Elaborator: total/hermetic evaluation, modules/interfaces/components, params** [lang] (8, P1) — deps: R12, R10. `new`/arrays/`~`, Starlark-model if/bounded-for; no recursion/while/IO representable; stable source-derived identity per entity. (L1, L2, L3, L7)
- **R14b · Import system + package manifest implementation** [lang] (2, P3) — deps: R12, R14a. `requires-aed`; registry stubbed per R14a spec. (L4)
- **R15 · Fabrication-reality modeling through IR** [lang] (3, P2) — deps: R13. Pinless artwork, net-attachable single-pin hardware, `dnp`/`exclude_from_bom`/`board_only` to IR. (L9)
- **R16 · Canonical formatter `aed fmt`** [lang] (5, P1) — deps: R12, R54 (T3 normal-form section). Zero-option, canonical ordering, SI literal normal form, idempotency + AST-identity property tests (AC6). CI-enforced from first commit. (I1, AC6)
- **R17 · Diagnostics framework** [agent-ux] (5, P1) — deps: R10. Stable unique codes from first commit, NDJSON, byte spans, structured params, fix-its w/ applicability, deterministic output cap. All downstream emits through this. (A1)
- **R18 · CLI core: `aed check`, A2 write gate, hermetic compile** [agent-ux] (5, P2) — deps: R13, R16, R17. Sync file-local checks on write, atomic reject, returns canonical bytes; no daemon/network at compile. (A2, A3, I3)
- **R53 · Express benchmarks (a)(b)(c) in AED** [benchmarks] (5, P1) — deps: R6, R13, R15, R11. The living DSL sources — the M1 exit artifact, the AC2 precision-leg subjects ("as authored"), the R36 exemplar seeds, and the AC gate-run inputs. (b) stresses T5/§8-Q6 semantics early. Updated as the language grows; owned, not assumed. (AC1, AC2)

### M2 — Static type system

- **R19 · Interface type system: nominal parameter-carrying bundles** [types] (5, P1) — deps: R13. Power/Logic/I2C/SPI/DiffPair, arrays, nesting, one-statement bundle connect. (T1)
- **R20 · Pin-role ERC lattice** [types] (5, P2) — deps: R19. Complete lattice incl. open-drain/tri-state/NC, KiCad ERC matrix baseline, explicit `nc`, intentional single-pin-net rule. (T2, L9b)
- **R21 · Quantities, dimensional algebra, tolerance intervals** [types] (5, P2) — deps: R13, R54 (T3 normal-form section). Value-exact literals, erased-after-check dimensions, interval value kind, exact-value lint; normative semantics land in R54 spec. (T3, T4)
- **R22 · Voltage-domain checker: component-mediated transfer semantics** [types] (8, P1) — deps: R19, R21, R9. Sources/regulators/converters/power-path elements transform domains by rule; passives propagate; undeclared crossing = typed error + fix-it; abs-max containment. **Second engineer paired here (compiler-SPOF mitigation).** (T5)
- **R23 · Current/power budget checker** [types] (3, P2) — deps: R21, R7, R22 (domain partitioning is R22's output — "per domain" has no input without it). Interval summation per domain vs declared capability, from D3 supply-current-per-mode. (T10)
- **R24 · Waivers + static assertion tier** [types] (3, P2) — deps: R17, R21. Per-site waivers w/ mandatory justification surfaced in reports; static assertions instant; `error` gates. (T6, V1-static)
- **R59 · T9/L6 final call: annotation-tax + columnar re-measurement** [lang] (2, P2) — deps: R22, R5a, R5b. Re-run the bake-off rig against the real type checker; decision memo completes §8-Q1. Adoption path if yes: `#pragma experiment` (L8) + E1 migrator; if no, recorded closed. (§8-Q1, T9, L6)
- **R29a · Benchmark-part D3 data** [parts-data] (3, P1) — deps: R7, R11. Full typed data (pin roles, abs-max, supply-current-per-mode) for every part the three benchmarks use (~70 incl. ESP32-S3, USB-C). Blocks R25 precision leg. (D5-data slice)
- **R55 · Lockfile schema v0** [interop] (2, P1) — deps: R7. Single schema owning D1 picks + I2 rename ledger + I3 compile-input semantics; shared predecessor of R27 and R28 so they can't diverge. (D1/I2/I3 seam)

### M3 — Determinism, KiCad handoff & AC2

- **R26 · Static-tier propagation strategy + I10 latency measurement** [types] (2, P3) — deps: R22, R18, R53 (measured via `aed check` on the real (c) source). < 2s warm; measured from here on; I10 relaxation is the cut-order's only remaining lever. (§8-Q4, I10)
- **R25 · AC2 tuning & gate run** [benchmarks] (5, P1) — deps: R8b, R20, R22, R23, R53, R29a. ≥90% of in-scope corpus; zero spurious errors + zero waivers on the three benchmarks as authored. Sits in M3 so the full M2 window buffers checker-quality risk. (AC2)
- **R27 · Deterministic naming + rename ledger** [interop] (5, P1) — deps: R13, R55. Net names/refdes/UUIDs from hierarchical paths; explicit rename refactor writes path-aliases to lockfile; un-ledgered identity change = compile error; property-tested. (I2, L7)
- **R28 · D1 binding ladder + `aed parts pin/unpin`** [parts-data] (5, P2) — deps: R55, R13. Abstract constrained part → optional MPN; revision-keyed picks; pick-failure echoes unsatisfied constraints; agent-readable. (D1)
- **R29b · Parametric footprint/symbol generator + jellybean parts** [parts-data] (5, P2) — deps: R7. Generator + the ~80 simple parts of the D5 hundred. (D5 path 1)
- **R29c · Complex benchmark parts: hand-authored CAD** [parts-data] (8, P1) — deps: R7, R11. **Long-lead; starts M1.** ~10–20 parts (USB-C receptacle, ESP32-S3 module, power packages) as original CAD under `ael:`; review pass per part. Blocks R32's (c) fixture. (D5 path 2)
- **R30 · KiCad schematic emitters + golden-file CI** [interop] (8, P1) — deps: R10, R27, R34, R29b, R29c (benchmark symbol set). `.kicad_sch`/`.kicad_pro`, embedded `ael:` symbols, 1.27mm grid, auto-PWR_FLAG, `(instances)` blocks, format 20250114 flag-selectable, L9→dnp/in_bom/on_board; no KiCad code linkage. Done-condition: golden corpora green against **two pinned Docker images (KiCad 9 and KiCad 10), per-release corpora** per AC4/I5. (I5)
- **R31 · Artifact guard: hash + refuse-and-diff** [interop] (2, P2) — deps: R30. Resolutions: accept-theirs / regenerate-to-new-path / defer-to-I6. (I5)
- **R32 · `.kicad_pcb` scaffold-once + AC4 fixture pipeline** [interop] (5, P1) — deps: R30, R27, R53, R29c (full (c) footprint set). Golden `.kicad_pcb` fixture via documented once-per-KiCad-release GUI Update-from-Schematic; headless `drc --schematic-parity` leg every commit; rename leg via ledger. (I5b, AC4)
- **R33 · V8 ERC smoke gate + BOM/netlist exports** [interop] (2, P2) — deps: R30. `kicad-cli sch erc --format json --exit-code-violations` on every export; BOM w/ L9 attributes. (V8, P6)
- **R34 · Placement subsystem (shared I5/I8)** [render] (8, P1) — deps: R10. **Starts M1 (dep-free after IR); lands early M3 ahead of R30.** Deterministic, stable under unrelated edits; single subsystem feeding emitters and renderer per I8. (I8, AC7 substrate)

### M4 — Agent surface & core gate

- **R35 · Renderer + HTML report + AC7 property test** [render] (5, P2) — deps: R34, R30. Hierarchical sheet-per-module, source-mapped elements; HTML report = netlist view + power tree; AC7: unrelated edit moves nothing on untouched sheets; demo-quality bar for the three benchmarks only. (I8, I9, AC7)
- **R36 · A4 model-facing docs under the 12K budget** [agent-ux] (5, P1) — deps: R4, R53, R54; **R25 gates only the final exemplar-precision pass** — card/skill/llms-full.txt drafting starts in M3. Language card ≤~3K tokens, llms-full.txt (from R54 spec), Claude Code skill, 10–20 exemplars seeded from R53; CI: card+skill+exemplar ≤12K under pinned tokenizer. (A4)
- **R37 · AC5a emittability run** [benchmarks] (3, P1) — deps: R5a (harness), R36, R18, R30, R33, R28, R29b, R53. Pinned model+sampling; (a) through compile/type-check/export in ≤3 repair iterations, ≤150K tokens, ≥7/10 trials. Includes: **a non-gating dry-run at M3 exit** (draft card) so repair-loop convergence is observed before the gate, and **a conditional Starlark-baseline re-run under the same AC5 protocol, triggered if AC5a <7/10** — making the §4 flip decision actually runnable (see Risk 2). (AC5a, §4)
- **R57 · AC1-core gate run** [benchmarks] (3, P1) — deps: R18, R30, R32, R33, R53, R29a, R29b, R29c. All three benchmarks compile/type-check/export **in one command**; line limits ((a) ≤~150, (c) ≤~600); **AC1–AC4 fully-offline leg run network-isolated on the D5 seed alone**. (AC1-core, AC4-offline)
- **R38 · A5a flywheel capture schema + consent flow** [agent-ux] (3, P2) — deps: R18, R4. Local opt-in (prompt, verified-DSL) pairs; license grant + attestation; separated consents; part references only. (A5a)
- **R56 · Docs site + user-facing documentation** [governance] (3, P2) — deps: R54, R36. Rendered spec, tutorials for the three benchmarks, install/quickstart. (E2 surface)
- **R39 · v1.0-core release engineering** [governance] (2, P1) — deps: R25, R32, R33, R35, R37, R38, R16, R56, R57, **R2, R14b, R24, R28, R31** (every M·core issue reachable — the sweep is structural, not manual). Exit checklist AC1-core/AC2/AC4/AC5a/AC6/AC7 plus an **M·core completeness sweep run as a script: §5 M-list checked against the dep-graph closure of this issue** (no silent Must slip; one declared exception: D3's hosted clause lands as R58 in M6 — documented phasing, not a slip); versioned artifacts incl. grammar + language card; E1 migrator policy published. (§3 gate, E1)

### M5 — Simulation tier

- **R40 · SPICE emission from IR** [verify] (3, P2) — deps: R10, R28. Sanitized names, ground node 0, `.subckt` per module, `.global` rails, positional pin maps from D3. (I7)
- **R41 · ngspice batch runner** [verify] (5, P1) — deps: R40. Isolated subprocess per testbench, process-parallel, `.control`+`quit <code>`, `set strict_errorhandling`, classification = quit code + regex log scan + rawfile point-count; never trust exit 0. (V4)
- **R42 · Fixture system** [verify] (3, P2) — deps: R40. DUT wrap, sources/loads, ramped supplies default, optional `uic`, mandatory settle window. (V3)
- **R43 · Dynamic assertion tier + three-state results** [verify] (5, P1) — deps: R41, R42, R24. `incomplete` gates like `error` unless waived; checks travel with modules; V7 structured results (measured/bound/margin/fixture) in A1 schema. (V1, V6, V7)
- **R44 · V2 measurement vocabulary** [verify] (5, P2) — deps: R43. Op values, ripple, period/freq/duty (555 TRIG/TARG), gain/BW/-3dB, rise/fall/prop, settling, overshoot, avg/RMS power, efficiency. Scope = benchmark assertions. (V2)
- **R45 · Remediation ladder R0/R1 + fidelity classes** [verify] (3, P2) — deps: R43. R0 classify (topological → type layer), R1 reltol/abstol; visible escalation; accuracy caveats; no silent retry-to-green. (V5)
- **R46a · D4 core macromodel authoring** [parts-data] (8, P1) — deps: R11 only. **Long-lead; starts M3/M4 against stock ngspice** (model authoring needs no runner). Manifest from benchmark assertions: 555 macromodel, buck averaged + behavioral switch, supporting models; Apache/CC0; hand-validated vs R11's raw-ngspice runs. (D4)
- **R46b · D4 ingest pipeline + conformance corpus** [parts-data] (3, P2) — deps: R46a, R41. Ingest smoke-sim, "loads ≠ verified", version-pinning per design, vendor-model metadata (URL/sha256/dialect/`ngbehavior`), encrypted→degradation path. (D4)
- **R47 · D2 stub parts + coverage report** [parts-data] (3, P2) — deps: R7, R43, R29a (stub loads derive from benchmark-part supply-current data). Load-equivalent digital stubs from supply-current-per-mode; structured non-gating coverage report, distinct from V1 `incomplete`. (D2)

### M6 — Discovery & verify gate

- **R48 · A7 agent-facing part discovery** [parts-data] (5, P1) — deps: R28, R29b, R29c, R7. `aed parts search/show`; constraint vocabulary shared with D1; token-bounded, deterministically ranked/paginated D3 records w/ provenance; offline serves D5 + local files; lockfile changes reported into loop. (A7)
- **R49 · AC3 gate run** [benchmarks] (3, P1) — deps: R44, R46b, R53. Every dynamic assertion in (b) green on stock ngspice, core-library models, rung 0, fidelity class reported, <60s laptop. (AC3)
- **R50 · AC1 simulation legs incl. (c) power tree** [benchmarks] (3, P2) — deps: R47, R49. (c) power tree vs D2 stubs + coverage report; digital ICs not simulated. (AC1-sim)
- **R58 · Hosted part-data service v0** [parts-data] (5, P2) — deps: R7, R28. **Starts M5.** Minimal D3-mandated service: extracted facts + citations + vendor URL/sha256, datasheet fetch-on-demand (no rehosting), serving A7's online path with the same D3 records/vocabulary. Coverage breadth beyond the benchmark set is explicitly post-v1 (E3 commercial layer) — but the *mechanism* is M·core D3 scope and ships in v1. Descope below this requires a §3 revision. (D3 hosted clause, E3, A7-online)
- **R51 · AC5b emittability run** [benchmarks] (3, P1) — deps: R37, R43, R44, R46b, R47 (coverage-report path for (c)). (a) incl. dynamic assertions ≥7/10; reported non-gating: (b) ≥5/10, (c) same protocol. (AC5b)
- **R52 · v1.0-verify release engineering** [governance] (2, P1) — deps: R49, R50, R51, R45, R48, R58. Exit checklist + **M·verify completeness sweep run as a script against the dep-graph closure** (same mechanism as R39); release; §8-Q3 stability promotion queued for 1.x. (§3 gate)

## Traceability (M-requirements → issues)

- **L1–L9:** L1/L2/L3/L7→R13; L4→R14a+R14b; L5/L8→R6+R12; L9→R15. **T1–T10:** T1→R19; T2→R20; T3→R21+R16+R54; T4→R21; T5→R22+R9; T6→R24; T10→R23+R22.
- **V1–V8:** V1-static→R24 (**core phase**); V1-dynamic→R43 (verify); V2→R44; V3→R42; V4→R41; V5→R45; V6/V7→R43; V8→R33 (**core phase**).
- **D1–D5:** D1→R28+R55; D2→R47; D3→R7 (schema) + R58 (hosted clause); D4→R46a+R46b; D5→R29a+R29b+R29c.
- **I1–I9:** I1→R16; I2→R27+R55; I3→R18+R55; I4/I9→R10+R17; I5→R30+R31; I5b→R32; I7→R40; I8→R34+R35. **A:** A1→R17; A2/A3→R18; A4→R36; A5a→R38; A7→R48+R58. **E:** E1→R39; E2→R1+R2+R54+R56; E3→R1+R2+R58.
- S-items in plan only where gated: I10→R26; L6/T9→R5b (prelim) + R59 (final call, §8-Q1 completion). Cut-order status: **exhausted at baseline** (see Scheduling model) — overrun ⇒ §3 doc revision from the pre-proposed descope candidates.

## Risks

1. **AC2 is checker-quality-bound.** The gate run sits at M3, so the M2→M3 gap partially buffers checker retuning — *partially*: M2 itself is fully loaded (36 pts / 36 capacity), so the real absorber is the ~20% plan buffer plus the M3 window. A slip propagates to R36's exemplar-precision pass → R37 → R39 (core ship); M3's interop track is unaffected.
2. **AC5a is model-behavior-bound.** If <7/10, the §4 flip criteria trigger a requirements-doc revision — a named fallback, not silent slippage. The flip decision is *runnable*: R37 includes a conditional Starlark-baseline re-run under the same AC5 protocol (the M0 bake-off's parse-level evidence alone would not satisfy §4's "under the AC5 protocol" clause). Decision accepter: project lead, recorded in the freeze-basis memo's successor.
3. **Compiler SPOF.** R12→R13→R19→R22→R25 is one specialist's serial chain (~31 pts). Mitigation: second engineer paired on R22. The plan-wide 2-engineer re-date rule (Scheduling model) subsumes the per-case rule.
4. **EE/CAD/SPICE SPOF.** R11, R29a/b/c, R46a/b, R47 = 38 pts of domain-specialist work with two long-leads. Mitigation: R29c CAD is contractable (well-specified, reviewable deliverables); if in-house, pair-review each complex part; a team without an analog/SPICE-experienced engineer re-dates M5–M6 +4 weeks.
5. **Long-leads are calendar-bound:** R29c CAD (starts M1), R34 placement (M1), R46a models (M3/M4), R8a corpus (day 1), R3 outreach (day 1). Slipping a start slips a gate 1:1.
6. **KiCad-format inexperience** re-dates M3 +4 weeks (golden-file corpus absorbs the learning curve).
7. **Manual GUI step in AC4 fixture** (once per KiCad release) is documented and bounded; not automatable until KiCad 11 IPC.
8. **Bake-off measures parse-level emission only** (no type checker exists in M0). Accepted and bounded: the freeze-basis memo records it; R59 at M2 completes §8-Q1 against the real checker; R37's conditional baseline re-run covers the §4 flip comparison.

