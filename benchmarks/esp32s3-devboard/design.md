# Rhoform Benchmark (c): ESP32-S3 Devboard Reference Design

Benchmark target for AC1c: ~60 components, expressible in <= ~600 DSL lines.
"Simulates" for this benchmark means the power tree checked against
load-equivalent stubs only. Digital ICs (the ESP32-S3 module itself, the ESD
array) are NOT simulated; the module is represented as a per-mode current-sink
stub whose values come from `power-tree.yaml`.

## 1. Block architecture

```
USB-C (J1) --[F1 PTC]--[FB1 bead]--> VBUS_PROT --[D1 Schottky]--> P5V0
   |  |                                                             |
   CC1/CC2: R1/R2 5.1k Rd            D3 SMF5.0A TVS            D4+R7 PWR LED
   D+/D-: D2 USBLC6-2SC6, R11/R12 0R                                |
   Shield: R9 1M || C18 4.7nF to GND                     U2 AP7361C-33 LDO
                                                                    |
                                              J5 IDD-measure header (JP1 shunt)
                                                                    |
                                                                  P3V3
                                                                    |
        +----------+----------+----------+----------+----------+
        |          |          |          |          |          |
   U1 ESP32-S3   decoupling  EN circuit  BOOT ckt  D5+R8 LED  J2/J3 headers
   WROOM-1-N8R2  C6..C9      R3,C10,SW1  R4,C11,SW2 (GPIO48)  + J4 DNP debug
```

Deliberately OUT of scope (justifications in section 8): USB-UART bridge and
its two-transistor auto-download circuit, addressable RGB LED, battery/charger.

## 2. Module and supply-current basis (datasheet-cited)

Module: **ESP32-S3-WROOM-1-N8R2** (8 MB Quad SPI flash, 2 MB Quad SPI PSRAM,
-40..85 C). Quad-PSRAM variant chosen so GPIO35/36/37 remain usable (Octal
R8 variants consume them).

All current numbers below are from the **ESP32-S3-WROOM-1 & ESP32-S3-WROOM-1U
Datasheet v1.8 (Espressif)**, Section 6, measured at 3.3 V supply, 25 C
ambient; TX rated at 100% duty cycle:

| Mode | Value (typ) | Source table |
|---|---|---|
| Wi-Fi TX 802.11b 1 Mbps @20.5 dBm (peak) | **355 mA** | Table 6-4 "Current Consumption for Wi-Fi (2.4 GHz) in Active Mode" |
| Wi-Fi TX 802.11g 54 Mbps @18 dBm | 297 mA | Table 6-4 |
| Wi-Fi TX 802.11n HT20 MCS7 @17.5 dBm | 286 mA | Table 6-4 |
| Wi-Fi RX 802.11b/g/n HT20 | 95 mA | Table 6-4 |
| Modem-sleep, 240 MHz, WAITI, peripheral clocks enabled | 47.6 mA | Table 6-6 "Current Consumption in Modem-sleep Mode" |
| Modem-sleep worst row (240 MHz dual-core 128-bit, clocks enabled) | 107.9 mA | Table 6-6 |
| Light-sleep | 240 uA (+40 uA for 2 MB quad PSRAM, footnote 1) | Table 6-7 "Current Consumption in Low-Power Modes" |
| Deep-sleep, RTC memory + RTC peripherals powered | **8 uA** | Table 6-7 |
| Power off (EN low) | 1 uA | Table 6-7 |

Supply requirement: VDD33 3.0-3.6 V and an external supply able to deliver
**>= 0.5 A** ("Current delivered by external power supply, min 0.5 A") —
Table 6-2 "Recommended Operating Conditions", same datasheet.

## 3. USB-C input

- J1: 16-pin USB 2.0-only USB-C receptacle (GCT USB4105-GF-A).
- **CC pulldowns**: R1, R2 = 5.1 kOhm 1%, one per CC pin, never shared —
  presents Rd (UFP sink). No PD controller; board budgets to **default USB
  power, 500 mA** and does not read the source Rp. This is the VBUS source
  capability used in `power-tree.yaml`.
- VBUS window at receptacle taken as **[4.40, 5.25] V** (USB 2.0 worst-case
  device-side minimum; USB-C nominal min 4.75 V is also shown as a
  typical-min row in the assertions).
- F1: PTC resettable fuse, 0.75 A hold / 1.5 A trip (Littelfuse 1206L075) —
  fault protection, not budget enforcement. R_initial assumed [0.07, 0.35] Ohm.
- FB1: ferrite bead 600 Ohm @100 MHz, 1206, DCR [0.05, 0.11] Ohm (Murata
  BLM31PG601SN1L) — EMI, keeps RF hash off VBUS.
- D1: SS34 Schottky, VBUS -> P5V0. Prevents backdriving the host when the
  board is powered from the J2 5V header pin. Vf at ~0.4 A: 0.35 V typ,
  0.40 V worst (assumption, flagged in assertions).
- D3: SMF5.0A TVS on VBUS (5 V standoff) for surge.
- D2: USBLC6-2SC6 ESD array on D+/D-/VBUS, placed at the connector.
- R11/R12: 0 Ohm series links in D+/D- (isolation/rework aid; FS USB needs no
  series termination — the S3 PHY is internal).
- Shield: R9 1 MOhm || C18 4.7 nF to GND (avoids hard shield-ground loop).
- VBUS-visible bulk capacitance C1 + C3 = 4.7 + 4.7 = **9.5 uF <= 10 uF**
  USB attach limit; the 3.3 V bank charges behind the LDO's current limit.

## 4. 3.3 V LDO, sized against Wi-Fi TX peak

Peak rail demand (worst, with 10% guardband on the radio number):
355 mA x 1.10 + 1.1 mA (status LED) = **391.6 mA**; module datasheet
independently demands a >= 500 mA-capable source (Table 6-2).

Chosen regulator: **AP7361C-33E-13** (Diodes, SOT-223): 1 A output, dropout
**340 mV typ at 1 A** (datasheet DS37274 Rev. 5-2 EC table, 2.6 V <= VOUT <=
3.3 V row; the features page quotes 360 mV for 3.3 V; **no max is specified**),
Iq ~60 uA, Vin up to 6 V, thermal shutdown 150 C. Because the datasheet gives
no dropout max, the budget also carries a **conservative in-house guardband
assumption of 0.50 V/A** (not a datasheet figure). Rationale:

- 1 A rating gives 608 mA margin over worst peak and 2x the module's required
  500 mA source capability. (A 600 mA AP2112K in SOT-25 fails the thermal
  check below at ~250 C/W; the classic AMS1117 fails dropout at min VBUS
  with its 1.1-1.3 V dropout. Both rejected — this is exactly the trap the
  benchmark should catch.)
- Dropout at worst-worst corner (VBUS 4.40 V, max series drops, guardbanded
  load), both dropout bases: at the datasheet 340 mV-typ figure (0.34 V/A),
  required V_in = 3.499 V -> **+319 mV margin**; at the in-house 0.50 V/A
  guardband, required V_in = 3.562 V -> **+257 mV margin**. V_LDO_in = 3.818 V
  in both rows. Full arithmetic in `assertions.yaml` A4.
- Thermal at continuous TX, Ta = 50 C, VBUS 5.25 V: P = 0.654 W. At the
  datasheet SOT-223 theta_JA of **110 C/W** (DS37274 Rev. 5-2 thermal table,
  Note 9: "mounted on FR-4 substrate PC board, with minimum recommended pad
  layout" — the note states no airflow condition and no board size for
  SOT-223), Tj = **121.9 C** -> only +3.1 C to the 125 C design gate. With
  the assumed 62 C/W (SOT-223 on ~1 in^2 outer-layer pour, AN1028 range),
  Tj = 90.5 C -> +34.5 C. The PASS is therefore **layout-dependent**: it
  requires copper pour beyond the minimum pad. `assertions.yaml` A5.

J5 (2-pin header + JP1 shunt) breaks the 3.3 V rail between LDO output and
loads: pull the shunt, insert an ammeter — this is the physical analogue of
the load-equivalent stub boundary, and excludes LDO Iq and the 5 V-side
power LED from the measurement (predicted deep-sleep reading: ~8 uA).

## 5. EN / BOOT buttons and strapping (details in pin-plan.md)

- EN (reset): R3 10 k pull-up to 3V3, C10 1 uF to GND (tau = 10 ms power-on
  delay, satisfies Espressif's EN-after-VDD timing), SW1 shorts EN to GND.
  C10 doubles as button debounce.
- BOOT (GPIO0): internal 45 k weak pull-up (Table 6-3) reinforced with R4
  10 k external pull-up; SW2 to GND; C11 100 nF debounce.
- GPIO45: R5 10 k pull-down **fitted** — hard-forces VDD_SPI = 3.3 V so noise
  at reset can never mis-strap the 3.3 V flash to 1.8 V.
- GPIO46: R6 10 k pull-down pad **DNP** (internal default pull-down is the
  correct download-boot companion state; pad kept for noisy environments).
- GPIO3 (JTAG source strap): floating per default eFuse config; R10 10 k
  pull-down pad **DNP** for provisioned units.

## 6. Auto-download circuit: OUT (justified)

The classic two-transistor DTR/RTS auto-download circuit only exists to let a
USB-UART bridge toggle EN/GPIO0. This board has no bridge: the S3's native
**USB-Serial-JTAG** controller (module datasheet section 5.2.1.8) enumerates
over J1 and esptool can enter download mode over it without touching straps.
Omitting bridge + transistors removes ~10 components and a digital IC the
benchmark would not simulate anyway, keeping the ~60-part / <=600-line
budget. Fallbacks: manual EN+BOOT buttons; DNP UART header J4 with an
external adapter.

## 7. Decoupling, LED, test points, mounting holes, debug header

- Decoupling: module 3V3 pin gets C9 100 nF + C8 1 uF + C7 10 uF close-in
  and C6 22 uF bulk; LDO C3 4.7 uF in, C4 22 uF + C5 100 nF out; VBUS C1
  4.7 uF + C2 100 nF; headers get distributed C12-C15 100 nF, C16/C17 10 uF,
  C19 22 uF far-corner bulk.
- LEDs: D4 red PWR LED + R7 1 k on P5V0 (3.0 mA, always on, deliberately on
  the 5 V side so it does not pollute 3.3 V sleep measurements); D5 green
  status LED + R8 1 k on GPIO48 (1.1 mA when lit).
- Test points TP1-TP8 (Keystone 5015): VBUS, 3V3, GND x2, EN, GPIO0,
  U0TXD, U0RXD.
- Mounting holes: **H1 grounded** (pad on GND net), **H2-H4 plain** — their
  pads carry intentional single-pin/no-connect nets and exercise the L9b
  single-pin-net rule: the lint must fail unless the DSL declares them
  mechanical.
- J4: 1x6 UART debug header, **DNP**: 3V3, GND, U0TXD(GPIO43), U0RXD(GPIO44),
  EN, GPIO0. Exercises DNP propagation to BOM/POS while staying in the
  netlist.

## 8. Scope exclusions

- USB-UART bridge (CP2102/CH340): superseded by native USB-Serial-JTAG (sec 6).
- WS2812 RGB LED: needs 3.5 V min VDD; driving it at 3.3 V logic/5 V supply
  violates VIH = 0.7*VDD — a plain GPIO LED avoids an out-of-spec digital
  part the benchmark cannot simulate.
- Battery/charger: separate benchmark concern; keeps one power domain pair.

## 9. Budget claims

- Component count: **60 total placements, 57 fitted + 3 DNP** (J4, R6, R10) —
  enumerated in `parts.yaml`.
- DSL estimate: 60 instantiations + ~45 nets + power-tree/assertion decls
  ~= 380-450 lines, inside the <= ~600-line ceiling.
- Validation: no ngspice run required; `power-tree.yaml` (T10 hand-computed
  current budget, the future stub input) + `assertions.yaml` are the gate.
