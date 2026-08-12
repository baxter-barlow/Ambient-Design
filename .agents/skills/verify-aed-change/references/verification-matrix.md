# AED Verification Matrix

Use every row touched by the change. Obtain exact commands from the implemented repository; this matrix defines evidence, not command names.

| Change class | Minimum evidence |
|---|---|
| Agent policy or skills | Layout validator; open Agent Skills validator; script syntax and representative run; positive trigger and near-miss trigger review; fresh Codex and Claude discovery, with every unavailable host recorded as a remaining manual gate in Linear |
| Grammar, lexer, parser, formatter | Grammar generation consistency; parser unit and conformance tests; error-recovery fixtures; formatter golden tests and idempotency; token/source-span preservation |
| IR, identity, rename ledger | Schema validation; serialization golden tests; repeated clean-build byte equality; rename and hierarchy property tests; source-map round trips |
| Electrical type system | Unit tests for the affected lattice or interval rule; positive and negative circuit fixtures; stable diagnostic codes, spans, parameters, and fix-its |
| CLI or write gate | Unit tests; subprocess/integration tests; canonical returned bytes; refusal behavior; parallel and hermetic execution; no compile-time network |
| Parts and lockfile | Schema validation; provenance, confidence, checksum, and license checks; offline resolution fixtures; pin/unpin and no-silent-reresolution tests |
| KiCad export | Golden corpus for the pinned format; stable UUID/name checks; clean repeated export equality; `kicad-cli sch erc --format json --exit-code-violations`; divergence refusal; proof that `.kicad_pcb` was not overwritten |
| SPICE emission or runner | Netlist golden tests; isolated stock-ngspice run; exit code plus known-error log scan plus rawfile point-count; three-state result checks; visible remediation rung and fidelity class |
| Documentation or exemplars | Link and snippet checks; terminology consistency; token budget under the pinned tokenizer when required; example compile/check results; no duplicated source of truth |
| Release or milestone | All affected rows; acceptance-gate scripts; clean immutable candidate; dependency and toolchain lock; artifact hashes; independent review; reproducibility from a fresh clone |

## Result rules

- `PASS`: every required gate ran successfully against the identified candidate.
- `FAIL`: at least one required gate ran and failed.
- `BLOCKED`: a required gate could not run, the candidate was not immutable, ownership was unclear, or the environment was not isolated.
- Manual inspection may supplement evidence but cannot replace an executable gate that exists.
- A declared assertion that produces no measurement is gating unless an explicit waiver is in scope.
- A non-gating coverage report must still enumerate each omitted simulation and its reason.
