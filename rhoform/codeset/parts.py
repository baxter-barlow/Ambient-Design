"""Part picks, record verification, binding and constraint satisfaction (L2b,
AMB-59), then the D3 follow-ons inside M2 (L2d, L5b). A `part "key"` with no
keyed pick is RHO6001.

Its range: RHO6001-RHO6049 and RHO6050-RHO6099 (rhoform.codes.RANGES). A new
code takes the next free number in the range, and CODES stays in code order.
The `parts` pass (rhoform/check/parts.py) reports every one of them; spec
05/09 says what fires each, and restates this list (reconciled against
rhoform.check.parts.code_rows).

A defect of a record or a keyed pick is the lockfile's, not one
instance's, so those findings name the key or the record and never an
instance path: every instance bound through one broken pick agrees on
code, params and span, and the reporter makes them one finding. None of
these codes is waivable: a pick that does not hold is not a judgment a
design can overrule.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # D30: the dangerous case is a resolved reference that points nowhere,
    # so this holds with no lockfile at all.
    CodeDef(
        code="RHO6001", slug="pick-missing", severity="error",
        message=(
            "`part \"{key}\"` names no pick: {reason}. A resolved part is "
            "an entry of the compile root's rhoform.lock, and nothing is "
            "searched for at compile time (D1)."
        ),
        params=("key", "reason"),
        rule="D1",
    ),
    CodeDef(
        code="RHO6002", slug="pick-names-no-instance", severity="error",
        message=(
            "the instance pick of `{design}` for `{instance}` {reason}; an "
            "instance pick names a component of the design with `part "
            "abstract`, by its identity path."
        ),
        params=("design", "instance", "reason"),
        rule="D1/I2",
    ),
    CodeDef(
        code="RHO6003", slug="record-not-found", severity="error",
        message="the part record `{record}` a pick names {reason}.",
        params=("record", "reason"),
        rule="D1/D3",
    ),
    # Amendment engineering 10: a record's revision is the hash of its
    # bytes, and a corrected record is a new revision every pick of the old
    # one must be re-pinned to, visibly.
    CodeDef(
        code="RHO6004", slug="record-hash-mismatch", severity="error",
        message=(
            "the part record `{record}` hashes to {actual}, not the "
            "{recorded} rhoform.lock records: it changed since it was "
            "picked, and a changed record is never re-pinned silently (D1). "
            "The fix-it re-pins the pick to the record as it is now."
        ),
        params=("record", "recorded", "actual"),
        rule="D1",
    ),
    CodeDef(
        code="RHO6005", slug="record-version-unsupported", severity="error",
        message=(
            "the part record `{record}` declares schema_version {version}; "
            "this toolchain reads version(s) {supported} only."
        ),
        params=("record", "version", "supported"),
        rule="D3",
    ),
    CodeDef(
        code="RHO6006", slug="record-invalid", severity="error",
        message=(
            "the part record `{record}` cannot be trusted: {problems}."
        ),
        params=("record", "problems"),
        rule="D3",
    ),
    CodeDef(
        code="RHO6007", slug="record-identity-mismatch", severity="error",
        message=(
            "the pick of the part record `{record}` echoes {fields} as "
            "{pinned}, and the record says {found}; a pick echoes the record "
            "it pins."
        ),
        params=("record", "fields", "pinned", "found"),
        rule="D1",
    ),
    # The join is the record's `implements` map and nothing else (decision
    # D28): a version 0 record has none, so it never binds.
    CodeDef(
        code="RHO6008", slug="binding-incomplete", severity="error",
        message=(
            "`{part_id}` does not bind to `{definition}`: {problems}. A "
            "record joins a definition only through its `implements` map."
        ),
        params=("part_id", "definition", "problems"),
        rule="D3",
    ),
    CodeDef(
        code="RHO6009", slug="role-conflict", severity="error",
        message=(
            "`{part_id}` cannot carry the roles `{definition}` declares: "
            "port(s) {ports}, of role(s) {roles}, land on record pin(s) of "
            "role(s) {record_roles}. A wrong role would disarm the pin-role "
            "checks, so it is never overridden."
        ),
        params=("part_id", "definition", "ports", "roles", "record_roles"),
        rule="D3/T2",
    ),
    # Decision D29's constraint-satisfaction subset, for an instance pick:
    # what the record guarantees against what the instance requires.
    CodeDef(
        code="RHO6010", slug="constraint-unsatisfied", severity="error",
        message=(
            "the record `{part_id}` the instance pick binds does not "
            "satisfy constraint(s) {constraints}: the instance requires "
            "{required}, and the record gives {found}."
        ),
        params=("part_id", "constraints", "required", "found"),
        rule="D1",
    ),
    CodeDef(
        code="RHO6011", slug="pick-stale", severity="error",
        message=(
            "the instance pick for `{instance}` was made for constraints "
            "that have changed since (recorded {recorded}, now {current}); "
            "a pick is re-made explicitly, never silently (D1). The fix-it "
            "re-pins it to the constraints as they are now."
        ),
        params=("instance", "recorded", "current"),
        rule="D1",
    ),
)
