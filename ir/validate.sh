#!/bin/sh
# Validate the AED IR v0 example documents against their schemas.
#
# Two kinds of case are run:
#   POSITIVE  examples/blinker.ir.json + examples/blinker.sourcemap.json must VALIDATE.
#   NEGATIVE  every examples/negative/*.ir.json (against the IR schema) and
#             every examples/negative/*.sourcemap.json (against the source-map schema)
#             must be REJECTED. A negative control that validates is a failure:
#             it means the schema stopped catching a defect it claims to catch.
#
# Validator selection, in order:
#   1. python3 + jsonschema (draft 2020-12 support required)
#   2. npx ajv-cli with --spec=draft2020
#   3. fallback: JSON well-formedness only via python3 -m json.tool
# Exit code 0 iff every case behaved as expected AND schema-level validation
# actually ran. The well-formedness-only fallback cannot test negative controls
# at all, so it exits 2 (degraded coverage) -- never reported as a pass.
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
IR_SCHEMA="$DIR/netlist-ir.schema.json"
SM_SCHEMA="$DIR/source-map.schema.json"
IR_DOC="$DIR/examples/blinker.ir.json"
SM_DOC="$DIR/examples/blinker.sourcemap.json"
NEG_DIR="$DIR/examples/negative"

fail=0

# Emit one "expect|schema|doc" case per line.
cases() {
  printf 'valid|%s|%s\n' "$IR_SCHEMA" "$IR_DOC"
  printf 'valid|%s|%s\n' "$SM_SCHEMA" "$SM_DOC"
  for f in "$NEG_DIR"/*.ir.json; do
    [ -e "$f" ] || continue
    printf 'invalid|%s|%s\n' "$IR_SCHEMA" "$f"
  done
  for f in "$NEG_DIR"/*.sourcemap.json; do
    [ -e "$f" ] || continue
    printf 'invalid|%s|%s\n' "$SM_SCHEMA" "$f"
  done
}

n_ir_neg=0
n_sm_neg=0
for f in "$NEG_DIR"/*.ir.json; do [ -e "$f" ] && n_ir_neg=$((n_ir_neg + 1)); done
for f in "$NEG_DIR"/*.sourcemap.json; do [ -e "$f" ] && n_sm_neg=$((n_sm_neg + 1)); done

wellformed() {
  for f in "$IR_SCHEMA" "$SM_SCHEMA" "$IR_DOC" "$SM_DOC"; do
    if python3 -m json.tool "$f" > /dev/null; then
      echo "WELL-FORMED  $f"
    else
      echo "MALFORMED    $f"
      fail=1
    fi
  done
}

echo "== AED IR v0 validation =="
date -u +"run (UTC): %Y-%m-%dT%H:%M:%SZ"
echo "negative controls found: $n_ir_neg IR, $n_sm_neg source-map"

# A missing negative-control corpus is a failure, not a quiet pass.
if [ "$n_ir_neg" -eq 0 ] || [ "$n_sm_neg" -eq 0 ]; then
  echo "ERROR        negative-control corpus is incomplete (need >=1 IR and >=1 source-map fixture)"
  fail=1
fi

FAILMARK="$(mktemp)"
trap 'rm -f "$FAILMARK"' EXIT INT TERM

if python3 -c 'import jsonschema' 2> /dev/null; then
  echo "validator: python3 jsonschema $(python3 -c 'import jsonschema; print(jsonschema.__version__)')"
  cases | python3 - "$FAILMARK" <<'EOF'
import json, sys
from jsonschema import Draft202012Validator

failmark = sys.argv[1]
bad = False
for line in sys.stdin.read().splitlines():
    if not line.strip():
        continue
    expect, schema_path, doc_path = line.split("|", 2)
    schema = json.load(open(schema_path))
    doc = json.load(open(doc_path))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(doc),
                    key=lambda e: list(e.absolute_path))
    got = "invalid" if errors else "valid"
    if got == expect == "valid":
        print(f"VALID        {doc_path}")
    elif got == expect == "invalid":
        e = errors[0]
        loc = "/" + "/".join(str(p) for p in e.absolute_path)
        print(f"REJECTED     {doc_path} (expected) at {loc}: {e.message[:120]}")
    elif expect == "valid":
        for e in errors:
            loc = "/" + "/".join(str(p) for p in e.absolute_path)
            print(f"INVALID      {doc_path} at {loc}: {e.message}")
        bad = True
    else:
        print(f"ACCEPTED     {doc_path} -- NEGATIVE CONTROL WAS NOT REJECTED")
        bad = True
if bad:
    open(failmark, "a").write("fail\n")
EOF
elif command -v npx > /dev/null 2>&1; then
  echo "validator: npx ajv-cli (--spec=draft2020)"
  cases | while IFS='|' read -r expect schema doc; do
    # --errors=line makes ajv emit machine-readable JSON errors (its default
    # renderer is util.inspect output, which is not parseable JSON).
    out="$(npx --yes ajv-cli validate --spec=draft2020 --errors=line -s "$schema" -d "$doc" 2>&1)"
    rc=$?
    if [ "$rc" -eq 0 ] && [ "$expect" = "valid" ]; then
      echo "VALID        $doc"
    elif [ "$rc" -ne 0 ] && [ "$expect" = "invalid" ]; then
      echo "REJECTED     $doc (expected)"
      # Show WHY it was rejected, so the log proves the fixture failed for its
      # intended reason rather than by accident.
      if command -v python3 > /dev/null 2>&1; then
        printf '%s' "$out" | python3 -c '
import sys, json, re
t = sys.stdin.read()
m = re.search(r"^\[.*\]$", t, re.M | re.S)
try:
    errs = json.loads(m.group(0))
except Exception:
    print("               (could not parse ajv error output)"); raise SystemExit
for e in errs[:2]:
    print("               %s: %s %s" % (e.get("instancePath") or "/",
                                        e.get("keyword", "?"),
                                        e.get("message", "?")))
'
      else
        printf '%s' "$out" | head -3 | sed 's/^/               /'
      fi
    elif [ "$expect" = "valid" ]; then
      echo "INVALID      $doc -- EXPECTED TO VALIDATE"
      echo "$out"
      echo fail >> "$FAILMARK"
    else
      echo "ACCEPTED     $doc -- NEGATIVE CONTROL WAS NOT REJECTED"
      echo fail >> "$FAILMARK"
    fi
  done
else
  echo "validator: NONE AVAILABLE -- degraded to JSON well-formedness only"
  echo "note: negative controls CANNOT be exercised in this mode"
  wellformed
  [ "$fail" -eq 0 ] && fail=2
fi

[ -s "$FAILMARK" ] && fail=1

if [ "$fail" -eq 0 ]; then
  echo "RESULT: PASS"
elif [ "$fail" -eq 2 ]; then
  echo "RESULT: DEGRADED (well-formed JSON, but no schema validation ran)"
else
  echo "RESULT: FAIL"
fi
exit "$fail"
