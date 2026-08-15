#!/usr/bin/env python3
"""Generate the benchmark (c) design model from its committed reference design.

Benchmark (c) is sixty placements and about fifty nets. Hand-writing that as
JSON would be a transcription exercise with no reviewable relationship to the
design it claims to be, so it is generated from tables that mirror the
documents it comes from — `benchmarks/esp32s3-devboard/{design.md,pin-plan.md,
parts.yaml}`, authored under AMB-39 — and the result is checked against
`parts.yaml` by `lang/bakeoff/elaborate.py`. A BOM line no instance covers, or
an instance no BOM line covers, fails the gate.

Everything here is TRANSCRIBED, never invented:

  - the header pin assignments are pin-plan.md section 5, in order;
  - the strapping, EN, BOOT and USB details are pin-plan.md sections 1-4;
  - the power chain is design.md section 1's block diagram;
  - values, packages, MPNs and the three DNP placements are parts.yaml;
  - tolerances come from the tolerance letter in the MPN parts.yaml states
    (Yageo `F` = 1%, `J` = 5%; Murata/TDK `K` = 10%, `M` = 20%).

What is deliberately ABSENT: footprint pin designators. The WROOM-1, USB-C and
regulator pin maps are datasheet facts, this issue has no datasheet in front of
it for them, and a plausible-looking guess committed to a fixture is worse than
an honest gap — `pin_numbers` is optional in the schema for exactly this case.
AMB-58 and AMB-65 own the real pin maps.

    python3 lang/examples/make_esp32_model.py

Rerunning must produce byte-identical output; lang/tests/test_bakeoff.py
asserts it, so the committed fixture can never drift from this generator.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bakeoff.library import lookup  # noqa: E402

OUT = Path(__file__).resolve().parent / "esp32s3-devboard.design.json"

# --------------------------------------------------------------------------
# Components, from parts.yaml. (ref, definition, parameters, constraints)
# --------------------------------------------------------------------------

RESISTOR = "aed.lib.passive.Resistor"
CAPACITOR = "aed.lib.passive.Capacitor"
LED = "aed.lib.semiconductor.Led"

# ref -> (value, mpn). Tolerance letters: Yageo F = 1%, J = 5%.
RESISTORS = {
    "R1": ("5.1kohm +/- 1%", "Yageo RC0402FR-075K1L"),
    "R2": ("5.1kohm +/- 1%", "Yageo RC0402FR-075K1L"),
    "R3": ("10kohm +/- 1%", "Yageo RC0402FR-0710KL"),
    "R4": ("10kohm +/- 1%", "Yageo RC0402FR-0710KL"),
    "R5": ("10kohm +/- 1%", "Yageo RC0402FR-0710KL"),
    "R6": ("10kohm +/- 1%", "Yageo RC0402FR-0710KL"),
    "R7": ("1kohm +/- 1%", "Yageo RC0402FR-071KL"),
    "R8": ("1kohm +/- 1%", "Yageo RC0402FR-071KL"),
    "R9": ("1Mohm +/- 1%", "Yageo RC0402FR-071ML"),
    "R10": ("10kohm +/- 1%", "Yageo RC0402FR-0710KL"),
    "R11": ("0ohm +/- 5%", "Yageo RC0402JR-070RL"),
    "R12": ("0ohm +/- 5%", "Yageo RC0402JR-070RL"),
}

# ref -> (capacitance, voltage rating, dielectric, package, mpn).
# Murata/TDK tolerance letters: K = 10%, M = 20%.
CAPACITORS = {
    "C1": ("4.7uF +/- 10%", "25V", "X5R", "0603", "TDK C1608X5R1E475K080AC"),
    "C2": ("100nF +/- 10%", "50V", "X7R", "0402", "Murata GRM155R71H104KE14"),
    "C3": ("4.7uF +/- 10%", "25V", "X5R", "0603", "TDK C1608X5R1E475K080AC"),
    "C4": ("22uF +/- 20%", "10V", "X5R", "0805", "Murata GRM21BR61A226ME44"),
    "C5": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C6": ("22uF +/- 20%", "10V", "X5R", "0805", "Murata GRM21BR61A226ME44"),
    "C7": ("10uF +/- 10%", "10V", "X5R", "0603", "Murata GRM188R61A106KE69"),
    "C8": ("1uF +/- 10%", "16V", "X5R", "0402", "Murata GRM155R61C105KE01"),
    "C9": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C10": ("1uF +/- 10%", "16V", "X5R", "0402", "Murata GRM155R61C105KE01"),
    "C11": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C12": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C13": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C14": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C15": ("100nF +/- 10%", "16V", "X7R", "0402", "Murata GRM155R71C104KA88"),
    "C16": ("10uF +/- 10%", "10V", "X5R", "0603", "Murata GRM188R61A106KE69"),
    "C17": ("10uF +/- 10%", "10V", "X5R", "0603", "Murata GRM188R61A106KE69"),
    "C18": ("4.7nF +/- 10%", "100V", "X7R", "0603", "Murata GRM188R72A472KA01"),
    "C19": ("22uF +/- 20%", "10V", "X5R", "0805", "Murata GRM21BR61A226ME44"),
}

DNP = {"J4", "R6", "R10"}

TEST_POINTS = {
    "TP1": "VBUS",
    "TP2": "P3V3",
    "TP3": "GND",
    "TP4": "GND",
    "TP5": "EN",
    "TP6": "IO0",
    "TP7": "U0TXD",
    "TP8": "U0RXD",
}

# pin-plan.md section 5, in header order.
J2_PINS = [
    "P3V3", "EN", "IO4", "IO5", "IO6", "IO7", "IO15", "IO16", "IO17", "IO18",
    "IO8", "IO9", "IO10", "IO11", "IO12", "IO13", "IO14", "IO21", "GND", "P5V0",
]
J3_PINS = [
    "GND", "U0TXD", "U0RXD", "IO1", "IO2", "IO42", "IO41", "IO40", "IO39",
    "IO38", "IO37", "IO36", "IO35", "IO45", "IO46", "IO47", "IO48", "IO19",
    "IO20", "GND",
]
# pin-plan.md section 4.
J4_PINS = ["P3V3", "GND", "U0TXD", "U0RXD", "EN", "IO0"]

# Signal -> the U1 port that carries it. Only the three non-GPIO names need
# spelling out; the rest are `IO<n>` -> `io<n>`.
U1_SPECIAL = {"P3V3": "p3v3", "GND": "gnd", "EN": "en", "U0TXD": "io43", "U0RXD": "io44"}


def q(text):
    return {"q": text}


def s(text):
    return {"s": text}


def component(name, definition, parameters=None, constraints=None, dnp=False,
              hardware_kind=None, exclude_from_bom=False, board_only=False):
    record = {"name": name, "kind": "component", "definition": definition}
    if parameters:
        record["parameters"] = parameters
    # Ports come from the same library the T9-1 rule reads, so every instance
    # here is fully inference-recoverable. That is deliberate: benchmark (c) is
    # the design the annotation-tax reading rests on, and an instance whose
    # ports the library could not supply would silently drop out of that
    # measurement. The pin-level anchor for (c) is parts.yaml, not the ports.
    record["ports"] = [
        {"name": port.name, "role": port.role}
        | ({"pin_numbers": list(port.pin_numbers)} if port.pin_numbers else {})
        for port in lookup(definition).ports
    ]
    if constraints:
        record["part"] = {"binding": "abstract", "constraints": constraints}
    if hardware_kind:
        record["hardware_kind"] = hardware_kind
    for flag, value in (("dnp", dnp), ("exclude_from_bom", exclude_from_bom),
                        ("board_only", board_only)):
        if value:
            record[flag] = True
    return record


def build():
    instances = []
    nets = {}
    refdes_map = {}

    def add(ref, record):
        instances.append(record)
        refdes_map[ref] = "/" + record["name"]

    def join(net, *members, ground=None, voltage=None):
        entry = nets.setdefault(net, {"members": [], "ground": ground, "voltage": voltage})
        if ground:
            entry["ground"] = ground
        if voltage:
            entry["voltage"] = voltage
        entry["members"].extend(members)

    # -- module, regulator ------------------------------------------------
    add("U1", component(
        "u1", "aed.lib.module.Esp32S3Wroom1",
        constraints={"mpn": s("ESP32-S3-WROOM-1-N8R2"),
                     "package": s("XCVR_ESP32-S3-WROOM-1")}))
    add("U2", component(
        "u2", "aed.lib.regulator.LinearRegulator",
        parameters={"output_voltage": q("3.3V"), "output_current": q("1A")},
        constraints={"mpn": s("AP7361C-33E-13"), "package": s("SOT-223")}))

    # -- connectors -------------------------------------------------------
    add("J1", component(
        "j1", "aed.lib.connector.UsbCReceptacle16",
        constraints={"mpn": s("GCT USB4105-GF-A"), "package": s("USB-C-16P-HYBRID")}))
    for ref, name in (("J2", "j2"), ("J3", "j3")):
        add(ref, component(
            ref.lower(), "aed.lib.connector.PinHeader1x20",
            constraints={"mpn": s("Sullins PRPC020SAAN-RC"),
                         "package": s("PinHeader_1x20_P2.54")}))
    add("J4", component(
        "j4", "aed.lib.connector.PinHeader1x6",
        constraints={"mpn": s("Sullins PRPC006SAAN-RC"),
                     "package": s("PinHeader_1x6_P2.54")},
        dnp=True))
    add("J5", component(
        "j5", "aed.lib.connector.PinHeader1x2",
        constraints={"mpn": s("Sullins PRPC002SAAN-RC"),
                     "package": s("PinHeader_1x2_P2.54")}))
    add("JP1", component(
        "jp1", "aed.lib.connector.Shunt2",
        constraints={"mpn": s("Sullins SPC02SYAN"), "package": s("Shunt_2.54")}))

    # -- protection, filtering, diodes, LEDs ------------------------------
    add("F1", component(
        "f1", "aed.lib.passive.PtcFuse",
        parameters={"hold_current": q("0.75A"), "trip_current": q("1.5A")},
        constraints={"mpn": s("Littelfuse 1206L075YR"), "package": s("1206")}))
    add("FB1", component(
        "fb1", "aed.lib.passive.FerriteBead",
        parameters={"impedance": q("600ohm")},
        constraints={"mpn": s("Murata BLM31PG601SN1L"), "package": s("1206")}))
    add("D1", component(
        "d1", "aed.lib.semiconductor.SchottkyDiode",
        parameters={"reverse_voltage": q("40V"), "forward_current": q("3A")},
        constraints={"mpn": s("SS34-E3/57T"), "package": s("SMA")}))
    add("D2", component(
        "d2", "aed.lib.semiconductor.UsbEsdArray",
        constraints={"mpn": s("STMicro USBLC6-2SC6"), "package": s("SOT-23-6")}))
    add("D3", component(
        "d3", "aed.lib.semiconductor.TvsDiode",
        parameters={"standoff_voltage": q("5V")},
        constraints={"mpn": s("Littelfuse SMF5.0A"), "package": s("SOD-123FL")}))
    add("D4", component(
        "d4", LED, parameters={"color": s("red")},
        constraints={"color": s("red"), "mpn": s("Kingbright KP-1608SURCK"),
                     "package": s("0603")}))
    add("D5", component(
        "d5", LED, parameters={"color": s("green")},
        constraints={"color": s("green"), "mpn": s("Kingbright APT1608SGC"),
                     "package": s("0603")}))

    # -- buttons ----------------------------------------------------------
    for ref in ("SW1", "SW2"):
        add(ref, component(
            ref.lower(), "aed.lib.switch.TactileSwitch",
            constraints={"mpn": s("C&K PTS645SM43SMTR92"), "package": s("SW_SMD_6x6")}))

    # -- mounting holes ---------------------------------------------------
    # H1's pad is on GND, so it is a grounded_mounting_hole with one passive
    # port. H2-H4 are plain: pinless, on no net, which is the L9b case
    # design.md section 7 says the lint must accept only when declared
    # mechanical.
    add("H1", component(
        "h1", "aed.lib.mech.GroundedMountingHole",
        parameters={"diameter": q("3.2mm")},
        hardware_kind="grounded_mounting_hole", exclude_from_bom=True))
    for ref in ("H2", "H3", "H4"):
        add(ref, component(
            ref.lower(), "aed.lib.mech.MountingHole",
            parameters={"diameter": q("3.2mm")},
            hardware_kind="mounting_hole", exclude_from_bom=True, board_only=True))

    # -- test points ------------------------------------------------------
    for ref in TEST_POINTS:
        add(ref, component(
            ref.lower(), "aed.lib.mech.TestPoint",
            constraints={"mpn": s("Keystone 5015"),
                         "package": s("TestPoint_Keystone_5015")},
            hardware_kind="test_point", exclude_from_bom=True))

    # -- passives ---------------------------------------------------------
    for ref, (value, mpn) in RESISTORS.items():
        add(ref, component(
            ref.lower(), RESISTOR, parameters={"resistance": q(value)},
            constraints={"mpn": s(mpn), "package": s("0402"), "resistance": q(value)},
            dnp=ref in DNP))
    for ref, (value, rating, dielectric, package, mpn) in CAPACITORS.items():
        add(ref, component(
            ref.lower(), CAPACITOR, parameters={"capacitance": q(value)},
            constraints={"capacitance": q(value), "dielectric": s(dielectric),
                         "mpn": s(mpn), "package": s(package),
                         "voltage_rating": q(rating)}))

    # -- power chain (design.md section 1) --------------------------------
    join("VBUS", "j1.vbus", "f1.a", "d2.vbus", "d3.a", "c1.a", "c2.a", "tp1.p",
         voltage="vbus_5v")
    join("N_FUSED", "f1.b", "fb1.a", voltage="vbus_5v")
    join("VBUS_PROT", "fb1.b", "d1.a", voltage="vbus_5v")
    join("P5V0", "d1.k", "c3.a", "u2.vin", "r7.a", voltage="p5v0")
    join("N_LDO_OUT", "u2.vout", "c4.a", "c5.a", "j5.p1", "jp1.a", voltage="p3v3")
    join("P3V3", "j5.p2", "jp1.b", "u1.p3v3", "r3.a", "r4.a", "tp2.p",
         voltage="p3v3")
    for ref in ("c6", "c7", "c8", "c9", "c12", "c13", "c14", "c15", "c16",
                "c17", "c19"):
        join("P3V3", f"{ref}.a")

    # -- ground -----------------------------------------------------------
    join("GND", "j1.gnd", "d2.gnd", "d3.k", "u1.gnd", "u2.gnd", "d4.k", "d5.k",
         "sw1.b", "sw2.b", "r1.b", "r2.b", "r5.b", "r6.b", "r9.b", "r10.b",
         "tp3.p", "tp4.p", "h1.p", ground="gnd")
    for ref in CAPACITORS:
        join("GND", f"{ref.lower()}.b")

    # -- reset, boot, straps (pin-plan.md sections 1-2) -------------------
    join("EN", "r3.b", "c10.a", "sw1.a", "u1.en", "tp5.p", voltage="p3v3")
    join("IO0", "r4.b", "c11.a", "sw2.a", "u1.io0", "tp6.p", voltage="p3v3")
    join("IO45", "u1.io45", "r5.a", voltage="p3v3")
    join("IO46", "u1.io46", "r6.a", voltage="p3v3")
    join("IO3", "u1.io3", "r10.a", voltage="p3v3")

    # -- USB (pin-plan.md section 3) --------------------------------------
    join("USB_DP", "j1.dp", "d2.dp", "r11.a")
    join("USB_DM", "j1.dm", "d2.dm", "r12.a")
    join("IO20", "u1.io20", "r11.b", voltage="p3v3")
    join("IO19", "u1.io19", "r12.b", voltage="p3v3")
    join("CC1", "j1.cc1", "r1.a")
    join("CC2", "j1.cc2", "r2.a")
    join("SHIELD", "j1.shield", "r9.a", "c18.a")

    # -- LEDs (design.md section 7) ---------------------------------------
    join("N_LED_PWR", "r7.b", "d4.a", voltage="p5v0")
    join("N_LED_STATUS", "r8.b", "d5.a", voltage="p3v3")
    join("IO48", "u1.io48", "r8.a", voltage="p3v3")

    # -- console ----------------------------------------------------------
    join("U0TXD", "u1.io43", "tp7.p", voltage="p3v3")
    join("U0RXD", "u1.io44", "tp8.p", voltage="p3v3")

    # -- headers, in pin order --------------------------------------------
    def header(instance, signals):
        """Attach a header's pins, in order, to the signals pin-plan.md names.

        A GPIO that reaches a header and nothing else needs its module port
        joined here; one that was already wired above (IO0, IO19, IO20, IO45,
        IO46, IO48) must not be joined twice. The duplicate check in `build`
        is left strict so a genuine double-wire still fails.
        """
        for index, signal in enumerate(signals, start=1):
            if signal.startswith("IO") and signal not in U1_SPECIAL:
                port = f"u1.{signal.lower()}"
                if port not in nets.get(signal, {"members": []})["members"]:
                    join(signal, port, voltage="p3v3")
            join(signal, f"{instance}.p{index}")

    header("j2", J2_PINS)
    header("j3", J3_PINS)
    header("j4", J4_PINS)

    net_list = []
    for name in sorted(nets):
        entry = nets[name]
        members = sorted(set(entry["members"]))
        if len(members) != len(entry["members"]):
            raise SystemExit(f"net {name}: an endpoint is listed twice")
        record = {"name": name}
        if entry["ground"]:
            record["ground_domain"] = entry["ground"]
        if entry["voltage"]:
            record["voltage_domain"] = entry["voltage"]
        record["members"] = members
        net_list.append(record)

    return instances, net_list, refdes_map


def main() -> int:
    instances, nets, refdes_map = build()
    model = {
        "model_version": 0,
        "stability": "unstable",
        "design_id": "esp32s3-devboard",
        "root_module": "Esp32S3Devboard",
        "source_benchmark": "benchmarks/esp32s3-devboard",
        "anchor": {
            "kind": "parts-yaml",
            "path": "benchmarks/esp32s3-devboard/parts.yaml",
            "refdes_map": {ref: refdes_map[ref] for ref in sorted(refdes_map)},
        },
        "notes": (
            "Benchmark (c), the ESP32-S3 devboard: 60 placements, 57 fitted and "
            "3 DNP (J4, R6, R10). GENERATED by lang/examples/make_esp32_model.py "
            "from benchmarks/esp32s3-devboard/{design.md,pin-plan.md,parts.yaml}, "
            "authored under AMB-39. Edit the generator, never this file.\n\n"
            "This design carries the bake-off's L6 and T9 readings: it is the "
            "only corpus member with enough repeated structure for a columnar "
            "section to mean anything, and design.md section 9 estimates it at "
            "380-450 DSL lines against the AC1 ceiling of ~600, which the "
            "measurement now checks instead of estimating.\n\n"
            "FLAT, no submodules. Benchmark (a) carries the hierarchy leg; "
            "adding an invented module decomposition here would be a design "
            "decision AMB-50 owns, and it would change the token counts.\n\n"
            "Footprint pin designators are deliberately absent: the WROOM-1, "
            "USB-C and regulator pin maps are datasheet facts no document in "
            "this repository states, and a plausible guess would be worse than "
            "the gap. The regulator's enable pin is not modelled for the same "
            "reason. AMB-58 and AMB-65 own both.\n\n"
            "No assertions: benchmark (c) is gated by power-tree.yaml and "
            "assertions.yaml, whose vocabulary (thermal, dropout margin) is "
            "outside the closed V2 v1 measurement set, and inventing an "
            "expressible one would be measuring a fiction."
        ),
        "modules": [
            {
                "name": "Esp32S3Devboard",
                "qualified_name": "esp32s3_devboard.Esp32S3Devboard",
                "ports": [],
                "instances": sorted(instances, key=lambda i: i["name"]),
                "nets": nets,
            }
        ],
    }
    OUT.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT} ({len(instances)} instances, {len(nets)} nets, "
        f"{sum(len(n['members']) for n in nets)} connections)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
