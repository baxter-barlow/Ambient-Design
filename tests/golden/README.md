# Golden-file harness

Golden tests pin the byte-exact output of Rhoform's deterministic tooling:
compiled netlist IR, rendered schematics, exported KiCad artifacts,
diagnostic reports. If a change alters any output byte, the harness fails
and the change must either be fixed or the golden files must be
regenerated with a recorded justification.

## Case layout

Each case is one directory under `tests/golden/`:

```text
tests/golden/<case>/
  driver.sh    # produces the case's outputs into the directory in $1
  expected/    # committed expected outputs, compared byte-for-byte
  ...          # any input files the driver needs
```

The driver contract:

- `driver.sh` is invoked with `bash`, with the case directory as the
  working directory and one argument: an empty output directory. It must
  write all outputs there and exit 0.
- Drivers must be deterministic: no timestamps, no network, no absolute
  paths in output, fixed seeds, sorted iteration. The harness exports
  `LC_ALL=C`, `TZ=UTC`, and `SOURCE_DATE_EPOCH=0`; drivers must not
  override them.

## Running

```sh
bash tests/golden/run.sh          # run every case
bash tests/golden/run.sh <case>   # run one case
```

Cases run in `LC_ALL=C` sorted order. Comparison is `diff -rq` between
`expected/` and the produced output directory: any content difference,
missing file, or extra file fails the case. With zero cases the harness
prints `golden: no cases` and exits 0, so the CI job passes on an empty
tree without weakening the gate.

Exit codes: `0` all cases pass (or no cases), `1` any case failed,
`2` usage or environment error.

## Regenerating expected outputs

Intentional output changes are regenerated, never hand-edited:

```sh
UPDATE=1 UPDATE_REASON="why the bytes legitimately changed" bash tests/golden/run.sh <case>
```

`UPDATE=1` without a non-empty `UPDATE_REASON` is an error. Each
regeneration appends a line to `tests/golden/UPDATES.log` (date, case,
justification); commit the ledger together with the regenerated
`expected/` files so review sees why the bytes moved. Unledgered golden
changes are treated like unledgered identity changes: errors.
