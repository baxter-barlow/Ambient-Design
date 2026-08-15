# AED repository entrypoints. Each target is a thin wrapper over a
# versioned script under tests/, so local runs and CI
# (.github/workflows/checks.yml) execute identical logic. Tool versions
# are pinned in toolchain/versions.yaml.

.PHONY: all check structure schemas lint sim golden

# Everything CI runs.
all: check sim golden

# Static repository gates: layout invariants, schema validation, and the
# cross-reference lint that JSON Schema cannot express.
check: structure schemas lint

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

# ngspice benchmark decks with .meas assertion and time-budget checks.
# Requires the ngspice version pinned in toolchain/versions.yaml.
sim:
	bash tests/benchmarks/run-sim.sh

# Golden-file harness; exits 0 with "no cases" while tests/golden is empty.
golden:
	bash tests/golden/run.sh
