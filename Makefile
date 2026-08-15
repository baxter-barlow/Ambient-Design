# AED repository entrypoints. Each target is a thin wrapper over a
# versioned script under tests/, so local runs and CI
# (.github/workflows/checks.yml) execute identical logic. Tool versions
# are pinned in toolchain/versions.yaml.

.PHONY: all check structure schemas lint bakeoff eval-tests sim golden

# Everything CI runs.
all: check sim golden

# Static repository gates: layout invariants, schema validation, the
# cross-reference lint JSON Schema cannot express, and the measurement
# harness's own tests.
check: structure schemas lint bakeoff eval-tests

# Monorepo layout invariants (allowlisted top-level dirs, root Markdown
# policy, required files, JSON well-formedness under ir/).
structure:
	bash tests/structure/check-layout.sh

# Schema well-formedness and example validation across every declared
# schema root (ir/, parts/). Requires the pinned jsonschema from
# toolchain/versions.yaml:
#   python3 -m pip install jsonschema==4.26.0
schemas:
	python3 tests/schemas/validate-schemas.py

# Part-record consistency: cross-references, sort order, and licence
# containment — invariants JSON Schema has no vocabulary for. The
# self-test runs first so a linter whose checks silently stopped firing
# fails loudly instead of reporting a clean sweep.
lint:
	python3 parts/lint-part-data.py --self-test
	python3 parts/lint-part-data.py

# Syntax bake-off (lang/): the candidate grammars must round-trip their own
# output, agree with each other on the same design, and agree with the
# artifacts AMB-38 and AMB-39 committed. Deliberately stdlib-only and
# tokenizer-free — token counting is `cd lang && python3 -m bakeoff measure`,
# which needs the optional tiktoken pin and is not a gate.
bakeoff:
	cd lang && python3 -m bakeoff check
	python3 -m unittest discover -s lang/tests -t lang

# Measurement-harness tests (eval/). stdlib unittest only, so this needs no
# dependency beyond the pinned interpreter; the harness's optional tiktoken
# and anthropic pins are for live runs, not for these tests. The statistics
# selftest re-checks the exact tests against closed-form values, because a
# harness whose statistics quietly changed would still emit confident
# verdicts.
eval-tests:
	python3 -m unittest discover -s eval/tests -t eval
	cd eval && python3 -m aed_eval selftest
	cd eval && python3 -m aed_eval replay --transcript fixtures/demo-replay.json --allow-stub

# ngspice benchmark decks with .meas assertion and time-budget checks.
# Requires the ngspice version pinned in toolchain/versions.yaml.
sim:
	bash tests/benchmarks/run-sim.sh

# Golden-file harness; exits 0 with "no cases" while tests/golden is empty.
golden:
	bash tests/golden/run.sh
