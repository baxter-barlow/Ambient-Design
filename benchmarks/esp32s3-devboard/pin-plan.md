# Pin Plan — ESP32-S3 Devboard Benchmark (c)

## 1. Strapping pins

Straps are sampled on the rising edge of EN (power-on or reset release).
Internal weak pull-up/pull-down = 45 kOhm (WROOM-1 datasheet v1.8, Table 6-3
R_PU/R_PD). Chosen states:

| Pin | Function | Internal default | This board | Sampled state |
|---|---|---|---|---|
| GPIO0 | Boot mode | weak pull-up | R4 10k PU + SW2 to GND, C11 100n | 1 (0 while BOOT held) |
| GPIO3 | JTAG signal source | floating | floating; R10 10k PD pad **DNP** | float |
| GPIO45 | VDD_SPI voltage select | weak pull-down | **R5 10k PD fitted** | 0 |
| GPIO46 | Boot mode companion | weak pull-down | R6 10k PD pad **DNP** | 0 |

Boot-mode matrix (ESP32-S3):

| GPIO0 | GPIO46 | Result |
|---|---|---|
| 1 | x | SPI boot (normal) — default on this board |
| 0 | 0 | Joint download boot — BOOT held at reset |
| 0 | 1 | Invalid — unreachable here (GPIO46 never pulled high) |

Rules encoded in the design:

- GPIO45 = 0 forces VDD_SPI = 3.3 V. The N8R2 flash/PSRAM are 3.3 V parts; a
  1.8 V mis-strap is a boot-failure, so R5 is fitted rather than trusting the
  weak internal pull-down alone.
- GPIO46 needs only its internal pull-down for correct SPI and download boot;
  R6 is a DNP reinforcement pad for electrically noisy deployments.
- GPIO3's strap is only sampled when the JTAG-source eFuse
  (EFUSE_STRAP_JTAG_SEL) is burned; left floating with a DNP pad (R10) for
  provisioned units.
- Strapping pins are exposed on J3 (marked *) — external circuits must be
  high-impedance at reset or boot mode can be corrupted; documented on silk.
- No auto-download transistors exist (no USB-UART bridge): download entry is
  native USB-Serial-JTAG via esptool, or manual BOOT+EN.

## 2. EN (reset) circuit

R3 10k to 3V3, C10 1 uF to GND, SW1 to GND. tau = 10 ms guarantees EN rises
after VDD33 is stable (satisfies Espressif's EN-timing requirement); C10 also
debounces SW1. EN brought to TP5 and J2 for external supervisors.

## 3. USB D+/D- routing notes

- GPIO19 = D-, GPIO20 = D+ (native full-speed PHY; USB-Serial-JTAG shares it
  by time-division with USB-OTG, module datasheet 5.2.1.8).
- No external series termination or D+ pull-up: internal to the S3 PHY.
  R11/R12 0R links allow isolation/rework only.
- Route as a 90 Ohm differential pair, J1 -> D2 (ESD array, at the
  connector) -> R11/R12 -> module; keep under ~30 mm, matched within ~1 mm,
  solid ground reference, no stubs (full-speed is forgiving; treat as good
  practice, not a gating constraint).
- GPIO19/20 also appear on J3 for OTG experiments; leave unconnected
  externally when the native USB port is in use.

## 4. DNP UART debug header J4 (1x6)

| J4 pin | Signal |
|---|---|
| 1 | 3V3 |
| 2 | GND |
| 3 | U0TXD (GPIO43) |
| 4 | U0RXD (GPIO44) |
| 5 | EN |
| 6 | GPIO0 |

Covers external-adapter flashing (manual or adapter-driven EN/GPIO0) and
ROM/console logging when native USB is unavailable. TP7/TP8 duplicate
U0TXD/U0RXD for probing with J4 unpopulated.

## 5. Breakout headers (2.54 mm, 1x20 each)

J2 (left): 3V3, EN, IO4, IO5, IO6, IO7, IO15, IO16, IO17, IO18, IO8, IO9,
IO10, IO11, IO12, IO13, IO14, IO21, GND, 5V(P5V0).

J3 (right): GND, U0TXD(IO43), U0RXD(IO44), IO1, IO2, IO42, IO41, IO40, IO39,
IO38, IO37, IO36, IO35, IO45*, IO46*, IO47, IO48, IO19*, IO20*, GND.

Notes: IO35/36/37 usable because N8R2 is a quad-PSRAM variant; IO48 shared
with status LED D5; * = strapping or USB pins (see sections 1 and 3);
5V pin sits on P5V0, D1's cathode side, so a backfeed reaches the LDO
only — D1 blocks it from the USB host. (An earlier revision said "anode
side"; the protection was right, the mechanism was stated backwards.)

## 6. Other assignments

| Signal | Resource |
|---|---|
| Status LED | GPIO48 (active-high via R8 1k) |
| BOOT button | GPIO0 (SW2) |
| Test points | TP1 VBUS, TP2 3V3, TP3/TP4 GND, TP5 EN, TP6 GPIO0, TP7 U0TXD, TP8 U0RXD |
| IDD measure | J5/JP1 in series with P3V3 (stub boundary; excludes LDO Iq and 5V PWR LED) |
| Mounting | H1 GND-tied; H2-H4 mechanical-only (L9b single-pin-net declarations) |
