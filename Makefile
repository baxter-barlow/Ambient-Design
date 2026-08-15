# AED repository entrypoints. Each target is a thin wrapper over a
# versioned script under tests/, so local runs and CI
# (.github/workflows/checks.yml) execute identical logic. Tool versions
# are pinned in toolchain/versions.yaml.

.PHONY: all check structure schemas sim golden

# Everything CI runs.
all: check sim golden

# Static repository gates: layout invariants plus IR schema validation.
check: structure schemas

# Monorepo layout invariants (allowlisted top-level dirs, root Markdown
# policy, required files, JSON well-formedness under ir/).
structure:
	bash tests/structure/check-layout.sh

# IR schema well-formedness and example validation. Requires the pinned
# jsonschema from toolchain/versions.yaml:
#   python3 -m pip install jsonschema==4.26.0
schemas:
	python3 tests/schemas/validate-schemas.py

# ngspice benchmark decks with .meas assertion and time-budget checks.
# Requires the ngspice version pinned in toolchain/versions.yaml.
sim:
	bash tests/benchmarks/run-sim.sh

# Golden-file harness; exits 0 with "no cases" while tests/golden is empty.
golden:
	bash tests/golden/run.sh
