"""Syntax 0.3 (L1a): its parse codes, and the generic elaboration of 0.3
statements (annotation targets, duplicate facts, rule pins).

Its range: RHO1018-RHO1029 and RHO2080-RHO2089 (rhoform.codes.RANGES). A new
code takes the next free number in the range, and CODES stays in code order.
Syntax 0.3 is unfrozen (decision OD8), so until M2 exits a code here may
still be renumbered inside the range.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # AMB-146 #1. 0.1 and 0.2 keep reading `01` as two designators (the
    # AMB-139 decision); from 0.3 on a run needs its separator, and the
    # quoted designator spells the other reading. Two needs-review fix-its,
    # because only the author knows which was meant.
    CodeDef(
        code="RHO1018", slug="adjacent-designators", severity="error",
        message=(
            "designators `{text}` run together with no space between them; "
            "separate them, or quote the one designator they spell."
        ),
        params=("text",),
        rule="L5",
    ),
    # The other half of a soft keyword: a word an older version left free
    # is refused as a name from the version that reserves it (the grammar
    # source of truth's RESERVED_SINCE), so the older files that bind it
    # keep their meaning.
    CodeDef(
        code="RHO1019", slug="reserved-word-as-name", severity="error",
        message=(
            "`{word}` is reserved from syntax {version} on and cannot be a "
            "name; choose another."
        ),
        params=("word", "version"),
        rule="E1/E4",
    ),
    # Generic elaboration of the 0.3 module statements. What a target MEANS
    # to the check stage (a role, a dimension) is the owning pass's own
    # block-3 question; whether it names anything at all is elaboration's.
    CodeDef(
        code="RHO2080", slug="annotation-target-unresolved", severity="error",
        message=(
            "the target `{target}` of this `{statement}` statement does not "
            "resolve in module `{module}`: {reason}."
        ),
        params=("statement", "target", "module", "reason"),
        rule="R22/R23/R24",
    ),
    CodeDef(
        code="RHO2081", slug="duplicate-annotation", severity="error",
        message=(
            "this `{statement}` statement repeats one for `{target}` in "
            "module `{module}`; each fact about a target is stated once."
        ),
        params=("statement", "target", "module"),
        rule="R22/R23/R24",
    ),
    CodeDef(
        code="RHO2082", slug="rule-pin-unknown", severity="error",
        message=(
            "`{pin}` in this `{word}` rule is not a pin of `{component}`."
        ),
        params=("pin", "word", "component"),
        rule="R22",
    ),
)
