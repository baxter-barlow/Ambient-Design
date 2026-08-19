# Rhoform repository entrypoints. Each target is a thin wrapper over a
# versioned script under tests/, so local runs and CI
# (.github/workflows/checks.yml) execute identical logic. Tool versions
# are pinned in toolchain/versions.yaml.

.PHONY: all check policy structure pins schemas lint ir-hashes corpus bakeoff grammar eval-tests gate-coverage sim golden

# gate-coverage MUTATES gate files in place (blank one report site, run the
# self-test, restore). Under -j another target can execute a gate while its
# mutant is on disk, judging the tree by a check that momentarily is not
# there. Serial execution is the isolation boundary.
.NOTPARALLEL:

# Everything CI runs, with ONE stated exception: checks.yml's "Resolve the
# pinned KiCad digests" step needs network (`docker manifest inspect`) and so
# cannot be a local target. It is named here rather than left to be rediscovered
# — a comment that quietly excludes something is how this went wrong before.
#
# That comment used to be false in a way that was not stated: .github/workflows/
# repository-policy.yml ran two gates no make target invoked, so a contributor
# could get `make all` green and still take a red CI on a check they had no way
# to run locally.
all: check policy sim golden

# Static repository gates: layout invariants, schema validation, the
# cross-reference lint JSON Schema cannot express, and the measurement
# harness's own tests.
check: structure pins schemas lint ir-hashes corpus bakeoff grammar eval-tests gate-coverage

# Monorepo layout invariants (allowlisted top-level dirs, root Markdown
# policy, required files, JSON well-formedness under ir/).
structure:
	python3 tests/structure/check-retired-names.py --self-test
	bash tests/structure/check-layout.sh --self-test
	bash tests/structure/check-layout.sh

# Toolchain pins: every version in toolchain/versions.yaml must appear in the
# consumer that is supposed to use it, and every `uses:` in a workflow must be
# a SHA the manifest pins. Without this the manifest was decoration — every pin
# except ngspice's could be corrupted with `make all` still green, while
# README.md called it "the single pinned-toolchain manifest every local run and
# CI job resolves versions from". P5 determinism rests on it.
pins:
	python3 tests/toolchain/check-pins.py --self-test
	python3 tests/toolchain/check-pins.py

# Schema well-formedness and example validation across every declared
# schema root (ir/, parts/). Requires the pinned jsonschema from
# toolchain/versions.yaml:
#   python3 -m pip install jsonschema==4.26.0
schemas:
	python3 tests/schemas/validate-schemas.py --self-test
	python3 tests/schemas/validate-schemas.py

# Part-record consistency: cross-references, sort order, and licence
# containment — invariants JSON Schema has no vocabulary for. The
# self-test runs first so a linter whose checks silently stopped firing
# fails loudly instead of reporting a clean sweep.
lint:
	python3 parts/lint-part-data.py --self-test
	python3 parts/lint-part-data.py

# IR content hashes. The schemas gate proves an IR document has the right
# SHAPE; this proves its `design_hash` actually describes its own bytes and
# that the paired source map agrees. Nothing recomputed either until this
# existed, so a rename could invalidate the determinism contract's worked
# example with every gate green. The self-test runs first, for the same
# reason the part linter's does.
ir-hashes:
	python3 tests/ir/check-hashes.py --self-test
	python3 tests/ir/check-hashes.py

# AC2 corpus classification (corpus/). Proves every bug is classified exactly
# once, that each verdict's citation RESOLVES against the artifact it names
# (D3 field paths walked against the schema, grammar tokens against the frozen
# grammar), and that the verdicts still hash to the committed decision_hash.
# The hash is the freeze AC2's "before checker tuning" clause needs to be
# enforceable rather than aspirational: AMB-61 must not be able to move its own
# denominator quietly. Self-test first, as everywhere else here.
corpus:
	python3 tests/corpus/check-corpus.py --self-test
	python3 tests/corpus/check-corpus.py
	python3 tests/corpus/check-classification.py --self-test
	python3 tests/corpus/check-classification.py

# Syntax bake-off (lang/): the candidate grammars must round-trip their own
# output, agree with each other on the same design, and agree with the
# artifacts AMB-38 and AMB-39 committed. Deliberately stdlib-only and
# tokenizer-free — token counting is `cd lang && python3 -m bakeoff measure`,
# which needs the optional tiktoken pin and is not a gate.
bakeoff:
	cd lang && python3 -m bakeoff check
	python3 -m unittest discover -s lang/tests -t lang -p 'test_bakeoff.py'

# Frozen syntax v0 (lang/grammar/): the EBNF and Lark artifacts must still
# match the source of truth they are generated from, and the Lark grammar must
# actually parse everything the winning prototype renders. The second leg
# needs the lark pin from toolchain/versions.yaml:
#   python3 -m pip install lark==1.3.0
# It exits 2 rather than 0 when that is absent, because a grammar nobody could
# load is not a grammar that passed.
grammar:
	cd lang && python3 -m grammar.rhoform_syntax --check
	cd lang && python3 -m grammar.conformance
	python3 -m unittest discover -s lang/tests -t lang -p 'test_grammar.py'

# Measurement-harness tests (eval/). stdlib unittest only, so this needs no
# dependency beyond the pinned interpreter; the harness's optional tiktoken
# and anthropic pins are for live runs, not for these tests. The statistics
# selftest re-checks the exact tests against closed-form values, because a
# harness whose statistics quietly changed would still emit confident
# verdicts.
eval-tests:
	python3 tests/eval/check-run-records.py --self-test
	python3 tests/eval/check-run-records.py
	python3 -m unittest discover -s eval/tests -t eval
	cd eval && python3 -m rhoform_eval selftest
	cd eval && python3 -m rhoform_eval replay --transcript fixtures/demo-replay.json --allow-stub

# ngspice benchmark decks: the decks run, and the numbers they produce land
# inside the windows benchmarks/*/assertions.yaml declares. The second half is
# what makes these "gate-load-bearing" (AMB-39) rather than decorative —
# `assertions.yaml` was read by no code at all until check-assertions.py, so a
# deck could be electrically destroyed and still pass. Requires the ngspice
# version pinned in toolchain/versions.yaml. Self-test first, as everywhere.
sim:
	python3 tests/benchmarks/check-assertions.py --self-test
	python3 tests/benchmarks/check-hand-assertions.py --self-test
	python3 tests/benchmarks/derive-555-windows.py --self-test
	python3 tests/benchmarks/derive-555-windows.py --check
	python3 tests/benchmarks/check-design-docs.py --self-test
	python3 tests/benchmarks/check-design-docs.py
	python3 tests/benchmarks/check-corners.py --self-test
	python3 tests/benchmarks/check-corners.py
	python3 lang/tests/check_readme_numbers.py --self-test
	python3 lang/tests/check_readme_numbers.py
	bash tests/benchmarks/run-sim.sh --self-test
	bash tests/benchmarks/run-sim.sh

# How much of each gate is pinned by its own --self-test. Slow (it re-runs
# every gate's self-test once per report site), which is why it is the last
# thing `check` does. Across twelve audit rounds "a check with no case" was the
# most common finding; this makes the number visible and refuses to let it
# grow. Thirteen rounds in, it found four blockers in itself.
gate-coverage:
	python3 tests/meta/check-gate-coverage.py --self-test
	python3 tests/meta/check-gate-coverage.py

# The gates in .github/workflows/repository-policy.yml. Kept as its own target
# rather than folded into `check` because the whitespace leg needs a commit
# range, which only exists once something is committed.
policy:
	sh .agents/skills/verify-rhoform-change/scripts/validate-layout.sh
	# The COMMIT, not the working tree. `git diff --check HEAD` compares the
	# index to HEAD, so it goes silent the moment a defect is committed — which
	# is how a trailing-whitespace failure landed in this repository while
	# `make policy` reported clean. CI compares base..head; this compares the
	# whole branch against the default branch, which is what CI does. HEAD~1
	# only covered the last commit, so a defect two commits back was invisible
	# locally and red in CI -- the same index-vs-HEAD miss one commit further
	# back. Falls back to the root commit on a branch with no merge-base.
	# -c pins the whitespace rules to git's documented defaults: without it
	# `git diff --check` reads the USER'S core.whitespace, so a local config
	# with `-blank-at-eol` gave local-green/CI-red on the same bytes.
	git -c core.whitespace=blank-at-eol,space-before-tab,blank-at-eof \
	  diff --check $$(git merge-base HEAD origin/main 2>/dev/null \
	  || git merge-base HEAD main 2>/dev/null \
	  || git rev-list --max-parents=0 HEAD) HEAD
	git -c core.whitespace=blank-at-eol,space-before-tab,blank-at-eof \
	  diff --check HEAD
	sh .github/scripts/check-dco.sh --self-test
	sh .github/scripts/check-dco.sh $$(git rev-list --max-parents=0 HEAD) HEAD

# Golden-file harness; exits 0 with "no cases" while tests/golden is empty.
golden:
	bash tests/golden/run.sh --self-test
	bash tests/golden/run.sh
