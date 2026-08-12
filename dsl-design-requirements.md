# AED-DSL — Design Requirements (v0.1)

*Requirements for a standalone electronics-design DSL at the core of an open-source, bring-your-own-model agentic hardware-design harness ("Claude Code for EEs"). Status: v0.1 — approved by adversarial review panel (4 lenses, 3 revision rounds, final gate passed 2026-08-12).*

## 1. Purpose

The DSL is the source of truth for a circuit design: an LLM agent emits and edits it; deterministic tooling elaborates it to a netlist IR, type-checks it electrically, discharges assertions (statically or via ngspice), renders reviewable schematics, resolves parts, and exports KiCad projects. The agent makes design decisions; it never performs layout, netlist bookkeeping, file-format emission, or by-hand analysis. **Wedge user:** greenfield, agent-first designs — not migration of existing KiCad schematics.

## 2. Design principles

- **P1 — Agent decides, compiler compiles.** Any task with a deterministic algorithm (rendering, checking, measuring, exporting) belongs to tooling, never to the model.
- **P2 — The loop is the unit of design.** First emissions will be wrong (rare-language penalty ≈2x vs Python on day one). Grammar size, diagnostics, and check latency are optimized for repair-loop convergence, not first-shot success. Evidence: repair odds collapse 90.5%→57.2% after one failed fix (SWE-agent, arXiv:2405.15793 §B.3.3); feedback quality is the repair bottleneck (1.58x lift from better failure explanations — Olausson et al., arXiv:2306.09896).
- **P3 — Verification is the moat.** ERC is type-checking; requirements are code; assertions gate progress. JITX 4.0 currently enforces voltage-domain correctness with markdown checklists read by LLMs — beating that with a compiler is the clearest available superiority claim.
- **P4 — Zero novelty budget on syntax.** All novelty goes to semantics. Surface must be Python-shaped and boring; Stanza's esotericism, not code-as-design, killed JITX's DSL.
- **P5 — Determinism is a contract.** Canonical bytes, stable names, stable UUIDs, hermetic elaboration, rename-safe identity (I2). atopile retrofitted deterministic naming after users' layouts were destroyed; we spec it up front.
- **P6 — Generated schematic-side files are artifacts.** `.kicad_sch`, `.kicad_pro`, netlists, BOMs, SPICE decks, reports are AED-owned build outputs, regenerated at will and guarded against divergence (I5). `.kicad_pcb` is **user-owned** after first scaffold (I5b) — layout is the user's work product and is never regenerated over.
- **P7 — No new interchange formats.** KiCad's own formats are the interop boundary (EDIF lesson). The internal IR (I4) is versioned and inspectable but explicitly *not* a third-party stability contract in v1.0.

## 3. Scope and phasing

**v1 delivers:** spec → typed netlist → statically + dynamically verified design → rendered schematic → resolved BOM → KiCad project handoff.

**Two Must phases, each with its own exit gate (§7):**
- **v1.0-core** — language, static type system, formatter, IR, KiCad export, diagnostics, seed part data. Exit: AC1 (compile/type-check/export legs), AC2, AC4, AC5a, AC6, AC7.
- **v1.0-verify** — SPICE tier, fixtures, macromodel library, part discovery. Exit: AC1 (simulation legs), AC3, AC5b.

**Non-goals (v1):** placement/routing or any XY coordinates in the DSL; fab outputs; thermal/EMI/mechanical analysis; digital simulation; a neutral interchange format; Turing-complete computation; a GUI editor; KiCad IPC API integration (needs a running GUI until KiCad 11); KiCad→DSL import (v1.x, I6); vision-based schematic review (v1.x).

**Sizing rule with teeth.** Target: 2–3 engineers, ~2 quarters per phase — acknowledged as tight. r4 therefore applies a second demotion pass (beyond r3's): GBNF artifact → S (its only consumer, A5b, is L); A1's root-cause clustering and Elm-style rendered prose → S (launch bar is stable codes + spans + structured params + fix-its); L2's atopile-ism recognition → S; A5a's org-level grant machinery → S; I8's HTML report scoped to netlist view + power tree. **If the phase still overruns, the pre-named cut order is:** (1) T8 stays v1.x, (2) L6 dropped, (3) V5 rungs beyond R1 stay S, (4) T7 net classes → v1.x, (5) I10 budget relaxed before any Must is silently slipped. Anything beyond this list requires revising this doc.

## 4. The standalone-DSL decision

JITX abandoned its Stanza DSL for Python (Oct 2025), stating "any advantage of a custom DSL is completely blown out of the water by… having AI write all your code." This is the strongest counter-evidence to our choice and must be answered:

1. **What the pivot cost them:** JITX now ships ~300KB of agent guardrail prompts banning Python patterns (getattr/setattr, string-keyed parallel models, dynamic classes, free-function mutation) — every one a semantic restriction a DSL compiler makes *unrepresentable*. Prompt-enforced semantics is the tax of the embedded choice.
2. **The embedded trap is documented elsewhere:** Chisel/Migen's elaboration-vs-source mismatch; SKiDL's stringly values and operator landmines; tscircuit's missing ERC as its top criticism. A design that exists only after arbitrary host-code execution cannot be statically verified, canonically formatted, or safely emitted by an untrusted model.
3. **The rare-language penalty is closable; unfamiliarity is not:** Flix (rare in training data) was written successfully by a frontier model given docs + a compiler loop; grammar prompting adds ~6 points with an in-context BNF; atopile's founder reports Copilot learned .ato from a few dozen lines of context. What does not recover: exotic syntax (Stanza) and version churn (Zig).

**Decision:** standalone DSL, Python-shaped, small grammar. **Flip criteria** (re-evaluate if any holds): the **language card** (grammar + cheatsheet, the A4 artifact) exceeds ~3K tokens and still can't express real designs; emission accuracy after repair loops is statistically below a Starlark-restricted-Python baseline under the AC5 protocol (the baseline harness is a budgeted line item of the §8-Q1 bake-off); or the language grows general-purpose features anyway.

## 5. Requirements

Priority: **M·core** / **M·verify** = must within the named phase; **S** = should (v1.x if not cheap); **L** = later.

### 5.1 Language core

- **L1 (M·core)** A declarative language with **total, terminating, hermetic, effect-free elaboration**: no user-defined side effects, I/O, reflection, or unbounded computation; JITX's banned-pattern list is unrepresentable. Every elaborated entity has a stable, source-derived hierarchical identity (L7); diagnostics map to originating source lines through the IR (I9).
- **L2 (M·core)** Core nouns: `module`, `interface`, `component`, instantiated with `new` (array form `new X[8]`), connected with `~` (plus a series/bridge form). Adopt atopile's MIT-licensed surface with public attribution (syntax per se is not copyrightable; MIT covers any copied grammar text; references to atopile/.ato stay nominative). The language card explicitly diffs AED from `.ato`; compiler "did you mean" recognition of atopile-isms is S.
- **L3 (M·core)** Parametrization on the Starlark model: typed module parameters with defaults, `if` over parameters, bounded `for`-comprehensions over compile-time-known ranges. No recursion, no `while`, no dynamic imports. Escape hatch is outside the language (agent or macro tool emits expanded DSL).
- **L4 (M·core)** Import/package system: file imports and a package manifest pinning language version (`requires-aed`) are M·core; full package-identity/registry rules are spec'd before syntax freeze but may ship as a stub implementation.
- **L5 (M·core)** Surface syntax: newline + indentation blocks, ASCII only, keyword-based. Grammar is context-free **over a layout-tokenized (INDENT/DEDENT) stream**. EBNF + Lark artifacts generated from one source of truth (M·core); a GBNF approximation for local-model whole-file generation is S (its consumer, A5b, is L). Language card ≤ ~3K tokens (§4 flip criterion).
- **L6 (S, gated)** Columnar sub-syntax for uniform tabular sections — only if the §8-Q1 bake-off measures a worthwhile saving.
- **L7 (M·core)** Identity is the stable hierarchical name, never object reference. Renames are explicit refactors that update the rename ledger (I2). Every compiler-generated entity has a stable, user-referenceable ID.
- **L8 (M·core)** Every file carries a syntax-version pragma; unstable features gate behind `#pragma experiment(...)`.
- **L9 (M·core)** Fabrication reality, correctly typed: (a) pinless artwork/mechanical items (mounting holes without net, fiducials, logos); (b) net-attachable hardware (test points, grounded mounting holes) — single-pin components on real nets, with a T2 rule for *intentional* single-pin nets; (c) per-instance fabrication attributes (`dnp`, `exclude_from_bom`, `board_only`) flowing through IR, BOM, and KiCad export. Full assembly variants stay E4 (S).

### 5.2 Electrical type system

- **T1 (M·core)** Nominal, parameter-carrying interface types: `Power(v=3.3V±5%)`, `Logic(ref)`, `I2C(addr, freq)`, `SPI(cs=True)`, `DiffPair`, arrays, nesting. One statement connects a bundle. Structural typing rejected (atopile tried and abandoned it).
- **T2 (M·core)** Pin roles form a **complete ERC lattice** — open-drain/open-collector, tri-state, passive, power-in/out, bidirectional, NC — with KiCad's ERC pin-conflict matrix as the reference baseline, so shared buses type-check cleanly. Explicit `nc`; intentional single-pin-net rule (L9b).
- **T3 (M·core)** Quantities are typed and dimension-checked (full dimensional algebra, erased after checking). Literals are **value-exact**; the canonical formatter rewrites them to a defined SI normal form — canonical text wins over authored spelling. Normative checking semantics in the spec.
- **T4 (M·core)** Tolerance/interval is a value kind: `10kohm ± 1%`, `3.0V to 3.6V`; interval arithmetic; lint on exact-valued part constraints.
- **T5 (M·core)** Voltage domains are typed net attributes with **component-mediated transfer semantics** (Polymorphic Blocks model): domains originate at declared sources/regulators/connectors; passives propagate by rule; declared transfer components — converters, level shifters, power-path elements (diode-OR, PMOS reverse protection, load switches, charger power paths) — transform domains by rule. Undeclared crossings are type errors with fix-its. Pin abs-max ratings checked by interval containment. Ground-architecture semantics (net-ties, star grounds) are spec'd during core detailed design — **a dependency of AC1(b)**, tracked in §8-Q6.
- **T6 (M·core)** Escape vocabulary: per-site waivers with mandatory justification, surfaced in reports; applies to static errors and `incomplete` results (V1).
- **T7 (S)** Net classes as declarative tags, exported to KiCad `net_settings.classes`.
- **T8 (S → v1.x)** Provide/require pin-assignment solving, deterministic, persisted.
- **T9 (S)** Inference beyond cheap local defaulting; annotation-tax measured in the bake-off first.
- **T10 (M·core)** **Current/power budgets in the static tier:** sources declare capability, loads declare draw (D3 supply-current-per-mode), interval summation per domain checks containment — brownout/overload is the dominant real postmortem class for the battery/regulator wedge and it is trivially checkable over data D3 already carries. D3 reserves per-pin/source current-capability fields before any freeze.

### 5.3 Verification

- **V1 (M·verify)** Two assertion tiers, tier visible in diagnostics: **static** (interval arithmetic — instant; M·core) and **dynamic** (ngspice testbenches; M·verify). Severity: `error` gates, `warning` annotates. **A declared assertion that fails to measure (`incomplete`) gates like `error` unless waived (T6).** Stub-driven *coverage* limits are not incompletes — they emit a non-gating structured coverage report (D2).
- **V2 (M·verify)** v1 dynamic vocabulary = what the benchmark assertions exercise: operating-point values, ripple, **oscillation period/frequency, duty cycle** (the 555's assertions — one `meas` TRIG/TARG pattern), gain/bandwidth/-3dB, rise/fall/prop delay, settling time, overshoot, avg/RMS power, efficiency. **Deferred (S):** phase/gain margin (Middlebrook/Tian fixtures — a mini-project), SOA windows, THD/FFT, Monte Carlo/corners (reimplement CACE's Apache-2.0 architecture — efabless is defunct; it is a reference, not a dependency).
- **V3 (M·verify)** Fixtures are first-class: wrap the DUT with sources/loads, declare startup strategy — ramped supplies by default, optional `uic`, mandatory settle window.
- **V4 (M·verify)** Execution: isolated ngspice batch subprocess per testbench, process-level parallel (no libngspice — also keeps GPL code at arm's length; kicad-cli and ngspice are invoked strictly as subprocesses, never linked). `.control` scripts ending `quit <code>`; `set strict_errorhandling`; classification = quit code + known-regex log scan + rawfile point-count sanity; never trust exit code 0. A `meas` with no crossing → `incomplete` (V1 gating).
- **V5 (M·verify)** Remediation ladder: R0 (classify; topological causes bounce to the type layer) and R1 (reltol/abstol rescale) are M·verify; R2–R5 are S. Visible escalation; accuracy caveats for rungs ≥1; **model-fidelity class** (behavioral vs physical) on results; silent retry-to-green prohibited.
- **V6 (M·verify)** Checks travel with modules (self-verifying blocks). Three-state results (pass/fail/incomplete) with name, category, message, source locator.
- **V7 (M·verify / S)** **Dynamic results emit in the A1 structured schema — measured value, bound, margin, fixture context — as M·verify** (P2: feedback quality is the repair bottleneck; a bare FAIL string gives the loop nothing to converge on). The human-facing "as-verified datasheet" artifact is S.
- **V8 (M·core)** `kicad-cli sch erc --format json --exit-code-violations` on every exported project as an export-correctness smoke gate — never the domain checker.

### 5.4 Parts & data

- **D1 (M·core)** Binding ladder: abstract constrained part → optional explicit MPN. Resolved picks in a revision-keyed lockfile; no silent re-resolution; lockfile is agent-readable, edited via CLI (`aed parts pin/unpin`); changes reported into agent context (A7). Pick-failure diagnostics echo unsatisfied constraints.
- **D2 (M·verify)** Stub parts: electrical interface + types suffice for netlist/ERC/assertions; footprint/symbol/sourcing attach later behind completeness gates. Digital ICs without SPICE models simulate as load-equivalent stubs (supply-current-per-mode). **Degradation mechanism: a structured, non-gating coverage report enumerating what was not simulated and why** — distinct from V1's gating `incomplete` (which is a declared assertion failing to measure).
- **D3 (M·core)** Part-data contract, published with the language: pins with roles + abs-max/recommended windows (typed intervals), supply-current-per-mode, **per-pin/source current capability (T10)**, package, footprint ref, per-field provenance + confidence, license class. Schema versioned but **explicitly unstable in v1.0** (third-party contract at 1.x, per §8-Q3 criteria). **Reserved before freeze: multi-unit/shared-package fields** (units, pin membership, shared power pins, swappability class). Hosted service stores extracted facts + citations + vendor URL/sha256; **datasheet PDFs fetch-on-demand absent a vendor redistribution agreement**.
- **D4 (M·verify)** SPICE models: metadata only — vendor URL, sha256, dialect, *verified* `ngbehavior` mode, subckt + positional pin map, license class; fetch-on-demand. Apache/CC0 **core macromodel library**, version-pinned per design, conformance corpus, **manifest derived from the benchmark assertions (incl. a 555 macromodel)**. Smoke-sim on ingest; "loads" ≠ "verified"; encrypted models → simulation-unavailable with explicit degradation (D2 report).
- **D5 (M·core)** **Open seed part library** (Apache/CC0): ~100 parts in the documented local D3 file format, sufficient for AC1–AC4 fully offline, with D3-lite fields (per-field provenance S, license-class retained). **Two production paths, both budgeted:** jellybean passives and simple packages via a minimal parametric footprint generator; the ~10–20 complex benchmark parts (USB-C receptacle, ESP32-S3 module, power packages) **hand-authored as original CAD work** under `ael:` (KiCad official libs are CC-BY-SA + exception; we do not redistribute derived collections). User-side part authoring (`aed parts new` scaffold + agent-assisted D3 drafting from a datasheet, served locally by A7) is S — the community-contribution feed to the hosted service.

### 5.5 Determinism & interop

- **I1 (M·core)** Zero-option canonical formatter from v0, canonical ordering + T3 literal normalization; token-efficient with accuracy-favoring tie-breaks. CI enforces. **The A2 write returns the canonicalized bytes**, so the agent always holds final bytes.
- **I2 (M·core)** Deterministic naming with **rename continuity**: net names, refdes, KiCad UUIDs derive from hierarchical instance paths; **explicit rename refactors write path-alias entries to a persisted rename ledger (in the lockfile, an I3 compile input), and aliased paths keep their original derived identities** — so renames and hierarchy moves never orphan the user's layout. Un-ledgered identity changes are compile errors, not silent re-derivations. Property-tested (AC4 rename leg).
- **I3 (M·core)** Compilation is a pure, hermetic, parallel-safe function of source + lockfile. No daemon, no network at compile time.
- **I4 (M·core)** Versioned JSON netlist IR between the language and ALL backends; **inspectable but no external stability promise in v1.0** (promoted at 1.x per §8-Q3; keeps P7 honest).
- **I5 (M·core)** **AED-owned exports** (`.kicad_sch`, `.kicad_pro`, netlists, BOM): regenerated at will, hashed; diverged files are refused-and-diffed with defined resolutions (accept-theirs / regenerate-to-new-path / defer to I6). Emission as verified with kicad-cli 10.0.4: embedded `ael:` symbols, 1.27mm grid, auto-PWR_FLAG, correct `(instances)` blocks, L9 attributes → dnp/in_bom/on_board; oldest covering format version (20250114 = KiCad 9+10), flag-selectable; own the emitter (no KiCad code linkage — GPL stays at subprocess arm's length); CI against pinned kicad/kicad Docker with a golden-file corpus per KiCad release.
- **I5b (M·core)** **User-owned board:** `.kicad_pcb` scaffolded once, never regenerated. Schematic changes reach the board via KiCad's UUID-matched Update-from-Schematic (manual GUI step in v1; kicad-cli has no headless equivalent through 10.x; revisit with KiCad 11). Hand-prettifying an exported `.kicad_sch` for formal review is a supported state — recommended at tagged review milestones, since prettification is superseded on regeneration (I5 refuse-and-diff applies).
- **I6 (S — v1.x)** KiCad import: netlist → skeleton DSL + diff report. v1 commitment: file-level `.kicad_sch` round-trip is never promised.
- **I7 (M·verify)** SPICE emission from our IR only: sanitized names, ground at node 0, `.subckt` per module, `.global` rails, positional pin maps from part data.
- **I8 (M·core, scoped)** Renderer v1 bar: correct connectivity, deterministic placement stable under unrelated edits (AC7), hierarchical sheet-per-module navigation, source-mapped elements. **Primary v1.0 review surface: HTML report scoped to netlist view + power tree** (bus maps S). Analog schematic legibility: best-effort (S), measurable bar from benchmark feedback (§8-Q5); a curated demo-quality bar applies to the three benchmark schematics only. I5 and I8 share one placement subsystem.
- **I9 (M·core)** Source maps: DSL line ↔ IR node ↔ diagnostic. Schematic-element and KiCad-UUID legs: S.
- **I10 (S)** Static-check latency budget: `aed check` on benchmark (c) < 2 s warm; measured from v1.0-core onward.

### 5.6 Agent interface

- **A1 (M·core)** Diagnostics: rustc-style newline-delimited JSON — stable unique codes from the first commit, byte spans, structured parameter fields separate from message strings, fix-its with applicability levels, deterministic output cap. Root-cause cascade clustering and Elm-style rendered prose: S (launch bar is codes + spans + params + fix-its).
- **A2 (M·core)** Write gate: syntax + file-local checks synchronously on write, atomic reject; whole-design type-check at explicit `aed check`. Write result returns canonicalized bytes (I1). The language card documents that single-file writes must be syntactically whole.
- **A3 (M·core)** Agent reads/writes DSL as plain text via file tools — never DSL-in-JSON arguments.
- **A4 (M·core)** Model-facing docs as release artifacts: language card (≤ ~3K tokens), llms-full.txt, first-party Claude Code skill, 10–20 idiomatic exemplars. **The AC5 protocol's total model-facing context (card + skill + exemplar) is one measured budget: ≤ 12K tokens under the pinned tokenizer** — the teaching payload cannot silently migrate into the skill (JITX's 300KB failure mode through the back door).
- **A5a (M·core)** Flywheel capture schema + consent: local, opt-in (prompt, verified-DSL) pairs with (a) explicit written license grant (CC0/CDLA-Permissive) + personal-project attestation, (b) separated consents (telemetry ≠ training ≠ public model release), (c) part *references* only (resolved D3 payloads stripped — the corpus must not republish the paid DB; residual fact-memorization in released weights is accepted and documented). Org-level grant machinery and the automated scrub gate: S.
- **A5b (L)** Fine-tune/release a 7B-class local emitter at the ~20–30K verified-pair threshold; models pin `requires-aed`; harness migrates their output.
- **A6 (S)** Expanded-design artifact + `aed query <instance|net>` single-entity introspection.
- **A7 (M·verify)** **Agent-facing part discovery:** `aed parts search` (constraint vocabulary shared with D1) and `aed parts show`, returning token-bounded, deterministically ranked/paginated D3-schema records with provenance; offline it serves D5 + local part files; lockfile changes reported into the loop. Without this the agent hallucinates MPNs and discovers failure at resolve time.

### 5.7 Evolution & governance

- **E1 (M·core)** Policy: no breaking syntax change ships without a deterministic auto-migrator; migrator infrastructure built with the first breaking change.
- **E2 (M·core)** Reference implementation defines semantics; conformance/golden-file suite in-repo; parser rejects ambiguity. Governance: **trademark + conformance defend against third-party incompatible forks; the defense against first-party closure is structural — DCO-only contributions (no CLA) + a written license-stability covenant.** Spec CC-BY-4.0, code Apache-2.0; trademark/spec company-held at launch with a stated neutral-home commitment at a defined milestone. (Filing mechanics live in a governance doc.)
- **E3 (M·core)** Licensing boundary: spec, compiler, formatter, renderer, exporters, docs, skills, seed library, core macromodels — open forever. Monetization: the **hosted part-data service** (coverage breadth, freshness, ingestion, provenance/confidence tooling) + team services, with a generous stated free tier for individuals. **Pricing principle: interactive in-loop A7 traffic is never per-call metered** (flat within a seat) — metering applies to seats, coverage/freshness tiers, and bulk/ingestion/export APIs; anything else recreates the metered-agent-loop failure §6 cites against Flux. The D3 contract is public and third-party-implementable (instability until 1.x is temporal and criteria-bound, §8-Q3); the moat is data quality, freshness, API terms, and metering — **not** copyright on facts (Feist), and the EU sui generis database right **only if operations are structured through an EU establishment** (Directive 96/9/EC Art. 11 — a governance-doc question, not an assumed protection).
- **E4 (S)** Assembly variants reserved in grammar; mapped to KiCad 10 native variants (raises the export floor to KiCad 10's format when enabled).

## 6. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Embedded Python (JITX 4.0 path) | Prompt-enforced semantics (~300KB guardrails), elaboration-vs-source mismatch, arbitrary code execution from an untrusted model, no canonical form. Fallback if flipped: Starlark-restricted Python, never full Python. |
| Embedded TypeScript/JSX (tscircuit) | Same class of problems + stringly selectors; missing ERC is its top public criticism. |
| Fork atopile's implementation | MIT front-end reusable, surface adopted with attribution — but: two ground-up core rewrites in 24 months, a constraint-solver architecture we'd replace, no formatter, no simulation tier, governance drifting closed. `.ato`→AED migrator (S); outreach on attribution framing **before** the §8-Q2 naming decision. |
| Flux's architecture | Proprietary cloud format, no local files/git, metered agent loop, unverifiable output — the community verdict on it is this project's founding evidence. AED is the inverse on every axis (see E3's pricing principle). |
| JSON/YAML as source | Code-in-JSON measurably degrades emission; no readable diffs. JSON is the IR, not the language. |
| KiCad S-expressions as source | LLMs demonstrably fail at emitting them (SchGen); boilerplate hostile to models and humans. |
| Neutral interchange format | EDIF. No. KiCad-native export is the boundary; the I4 IR carries no external stability promise in v1.0. |
| Turing-complete DSL | Recreates Stanza; kills static analyzability, hermeticity, and the verification story. |

## 7. v1 acceptance criteria

*(AC1-compile/AC2/AC4/AC5a/AC6/AC7 gate v1.0-core; AC1-sim/AC3/AC5b gate v1.0-verify.)*

1. Benchmarks: (a) 9V 555 blinker, (b) 3.3V/2A buck converter, (c) ESP32-S3 devboard (USB-C, LDO, buttons, mounting holes, test points, ~60 components incl. DNP debug header). Each expressible — (a) ≤ ~150 lines, (c) ≤ ~600 lines — compiling, type-checking, and exporting in one command. (a)'s assertions: frequency and duty cycle (V2). (c)'s "simulates" = power tree against D2 load-equivalent stubs, with the D2 coverage report; digital ICs are not simulated.
2. Seeded-bug corpus with an **inclusion rule**: ≥50 bugs, majority externally sourced (forum postmortems, atopile issues, published errata), each **classified at freeze time — before checker tuning — as in-scope (static-tier domain, expressible in the v1 DSL) or out-of-scope**, both populations published. Gate: static tier catches **≥90% of in-scope** bugs (e.g., "31 of 55 were in principle catchable; we catch 29"). The out-of-scope fraction is reported as the honest measure of the static tier's limits. Precision: the three benchmarks as authored produce **zero spurious static errors and zero static-tier waivers** (open-drain buses, buck inductor, dividers, AC coupling, test points all pass).
3. Every dynamic assertion in (b) runs green on stock ngspice using the core library's averaged/behavioral switch models (fidelity class reported), at rung 0, < 60 s total on a laptop.
4. Exported projects open warning-clean (ERC) in KiCad 9 and 10. **Layout preservation, two legs:** (i) *headless, every commit* — after a netlist-preserving design edit + regeneration, all UUIDs/net names/refdes of unedited entities are byte-stable, and `kicad-cli pcb drc --schematic-parity --exit-code-violations` passes against a **committed golden `.kicad_pcb` fixture** (produced by running GUI Update-from-Schematic once per KiCad release — the manual step, labeled honestly); (ii) *rename leg* — an explicit rename refactor (module instance + hierarchy move) preserves all exported identities via the I2 ledger, verified headlessly against the same fixture. AC1–AC4 pass **fully offline** (core legs on the D5 seed alone; sim legs additionally on the D4 core models).
5. Emittability, statistically, phase-split: **AC5a (core)** — a pinned frontier model (stated version + sampling params), given only the ≤12K-token A4 context, produces design (a) passing compile/type-check/export gates within ≤3 repair iterations (1 iteration = one write + one `aed check`) and ≤150K tokens, in ≥7/10 independent trials. **AC5b (verify)** — same protocol on (a) including dynamic assertions, ≥7/10; reported non-gating: (b) at ≥5/10 and (c) under the same protocol.
6. `aed fmt` is idempotent; two sources with identical post-normalization ASTs format to byte-identical output (property-tested).
7. Renderer property test: an unrelated edit (add a module) moves no element on untouched sheets.

## 8. Open questions (tracked, not blocking)

1. Syntax bake-off: two candidate grammars measured on token cost + emission accuracy (AC5 protocol), incl. T9 annotation-tax, L6 columnar, and the Starlark-baseline comparison harness (budgeted).
2. Language name + file extension — settle before exemplars/telemetry accumulate; sequence atopile outreach before this.
3. IR/D3 schema stability promotion criteria for 1.x.
4. Static-tier propagation strategy vs the I10 latency budget.
5. Measurable bar for analog schematic legibility (I8-S).
6. Ground-architecture semantics (net-ties, star grounds, chassis/earth) — dependency of AC1(b), spec'd during core detailed design.
