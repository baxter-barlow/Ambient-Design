"""T2 pin-role ERC and the L9b single-pin-net rule (L1b, AMB-52).

Its range: RHO3101-RHO3199 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Spec 05/04 says
what fires each one, and restates this list (reconciled against
rhoform.check.erc.code_rows).
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # The pair table's two verdicts (KiCad's ERR and WAR cells), one
    # finding per net with every pin that takes part.
    CodeDef(
        code="RHO3101", slug="driver-contention", severity="error",
        message=(
            "net `{net}` joins pins that drive against each other: "
            "{members}, roles {roles}; two push-pull or rail drivers, a "
            "strong driver against an open-drain or open-collector pin, a "
            "tri-state pin against a rail, or a push-pull or tri-state "
            "output on a ground-typed net short one another."
        ),
        params=("net", "members", "roles"),
        rule="T2",
    ),
    CodeDef(
        code="RHO3102", slug="pin-role-caution", severity="warning",
        message=(
            "net `{net}` joins {members}, roles {roles}: a pairing the "
            "KiCad baseline warns about (an output with a tri-state pin, a "
            "bidirectional pin with a rail, a tri-state pin with a power "
            "input or an open drain, a bidirectional pin on a ground-typed "
            "net); make sure only one of them drives at a time."
        ),
        params=("net", "members", "roles"),
        rule="T2",
    ),
    CodeDef(
        code="RHO3103", slug="undriven-input", severity="error",
        message=(
            "input pin(s) {inputs} on net `{net}` have no driver: no "
            "output, rail, bidirectional, tri-state or passive pin is on "
            "the net, and no root port reaches it; drive the input, or "
            "strap it to a level."
        ),
        params=("net", "inputs"),
        rule="T2",
    ),
    CodeDef(
        code="RHO3104", slug="open-drain-without-pull", severity="error",
        message=(
            "net `{net}` is driven only by open-drain or open-collector "
            "pins {pins}, which pull low and never high, and nothing pulls "
            "it up; add a pull resistor, or waive the finding where a pull "
            "inside a part holds the net (T6)."
        ),
        params=("net", "pins"),
        rule="T2",
    ),
    # KiCad's pin-not-connected, for every role but nc. One finding per
    # instance, every unconnected pin in it.
    CodeDef(
        code="RHO3105", slug="unconnected-pin", severity="error",
        message=(
            "`{instance}` leaves pin(s) {ports} (roles {roles}) out of "
            "every net; connect each one, or declare it `isolated` if it "
            "is meant to stay unconnected (L9b)."
        ),
        params=("instance", "ports", "roles"),
        rule="T2",
    ),
    CodeDef(
        code="RHO3106", slug="undeclared-single-pin-net", severity="error",
        message=(
            "net `{net}` reaches one pin, `{member}`, and nothing else; a "
            "net with one pin is a forgotten connection unless an "
            "`isolated` statement declares it (L9b)."
        ),
        params=("net", "member"),
        rule="L9b",
    ),
    CodeDef(
        code="RHO3107", slug="isolated-input-floats", severity="warning",
        message=(
            "`{member}` is declared isolated, but it is a {role} pin, which "
            "then floats; tie it to a defined level unless its part holds "
            "it internally."
        ),
        params=("member", "role"),
        rule="L9b",
    ),
    CodeDef(
        code="RHO3108", slug="net-without-physical-pins",
        severity="warning",
        message=(
            "net `{net}` joins only module ports, {ports}: no pin of any "
            "component is on it, so it connects nothing."
        ),
        params=("net", "ports"),
        rule="L9b",
    ),
    # The AC2 corpus's net-topology family (amendment spec-fidelity 6):
    # BUG-0036 for the first, BUG-0042 and BUG-0056 for the second. Spec
    # 05/04 justifies each severity.
    CodeDef(
        code="RHO3109", slug="shorted-two-terminal-part", severity="error",
        message=(
            "both pins of the two-terminal `{instance}` are on net `{net}`, "
            "which shorts it out: no voltage appears across it and no "
            "current flows through it."
        ),
        params=("instance", "net"),
        rule="AC2",
    ),
    CodeDef(
        code="RHO3110", slug="power-input-without-decoupling",
        severity="warning",
        message=(
            "power-input pin(s) {pins} on net `{net}` have no capacitor to "
            "a ground-typed net; a supply pin needs local decoupling."
        ),
        params=("net", "pins"),
        rule="AC2",
    ),
)
