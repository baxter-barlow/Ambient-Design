# Rhoform Benchmark (a): 9 V 555 LED Blinker (~1 Hz astable)

Reference design for requirement AC1a: a complete blinker expressible in well
under ~150 DSL lines, with two gating dynamic assertions — oscillation
frequency and duty cycle — each measured by the V2 "one .meas TRIG/TARG"
pattern on the output node.

## Topology

Classic NE555 astable. The timing capacitor CT charges from VCC through
RA + RB and discharges through RB into the DISCH pin. TRIG and THRES are tied
together on the capacitor node, so CT shuttles between 1/3 VCC and 2/3 VCC.
RESET is tied to VCC; CONT gets a 10 nF bypass. OUT drives the LED through a
ballast resistor to ground (LED lit while OUT is high).

```
9V ──VCC(8)          NE555          OUT(3)──RL 560R──▶|──GND
      │   RST(4)=VCC  CONT(5)─10n─GND        (LED, red)
      RA 100k
      │────DISCH(7)
      RB 680k
      │────THRES(6)=TRIG(2)
      CT 1u
      │
     GND
```

## Timing design (astable equations)

Standard equations:

- f = 1.44 / ((RA + 2·RB) · C)
- duty(high) = (RA + RB) / (RA + 2·RB)

Exact ln-2 forms used for the predictions:

- t_high = ln2 · (RA + RB) · C
- t_low  = ln2 · RB · C

Target ~1 Hz with duty as close to 50% as the diode-less astable allows
(duty > 50% is structural: RA must stay in the charge path). Keeping RA small
relative to RB pushes duty toward 50%, but RA ≥ ~5 k is good practice to limit
discharge-transistor current at 9 V. CT is capped at 1 µF because that is the
largest value with broad 5 % film availability (e.g. the 5 mm B32529 series
tops out well below 10 µF); RA/RB scale up ×10 to hold f ≈ 1 Hz. The higher
timing resistance is still safe for a bipolar 555: threshold input current is
0.1 µA typ / 0.25 µA max, which datasheets translate to an RA+RB ceiling of
3.4 MΩ at VCC = 5 V (10 MΩ at 15 V) — 780 kΩ at 9 V has >4× margin even
against the 5 V limit. Chosen E24 values:

| Param | Value | Basis |
|---|---|---|
| RA | 100 kΩ, 1% | E24; small vs RB for duty; pin-7 current 9 V/100 k = 0.09 mA |
| RB | 680 kΩ, 1% | E24; sets f ≈ 1 Hz with C = 1 µF |
| CT | 1 µF, 5% | largest widely available 5 % film value; verified MPN in parts.yaml |
| CB (CONT) | 10 nF | datasheet-customary bypass of the 2/3 divider tap |

Predicted performance (nominal):

- t_high = 0.6931 · 780 kΩ · 1 µF = 0.5407 s
- t_low  = 0.6931 · 680 kΩ · 1 µF = 0.4713 s
- T = 1.0120 s → **f = 0.988 Hz** (1.44-approximation form: 1.44/(1.46 MΩ · 1 µF) = 0.986 Hz)
- **duty = 780 k / 1460 k = 53.42 % high**

## LED drive (9 V supply)

Bipolar NE555 totem-pole high level is roughly VCC − 1.7 V ≈ 7.3 V at light
load. Red LED Vf ≈ 2.0 V at 10 mA. Ballast:

- RL = (9 − 1.7 − 2.0) V / 10 mA = 530 Ω → E24 **560 Ω**
- I_LED = (7.3 − 2.0) / 560 = **9.5 mA** nominal — bright for a 20 mA-class
  indicator, comfortably inside the 555's 200 mA drive and RL dissipation
  (I²R ≈ 50 mW in a 0805/axial part).

## Tolerance windows (1 % resistors, 5 % capacitor)

Frequency scales as 1/((RA+2RB)·C), so worst-case corners multiply. Because
RA/RB scaled ×10 while C scaled ÷10, the relative corners are unchanged from
the first draft (re-derived for RA = 100 k, RB = 680 k, C = 1 µF):

- f_min = 0.988 / (1.01 · 1.05) = 0.932 Hz  (all R +1 %, C +5 %)
- f_max = 0.988 / (0.99 · 0.95) = 1.051 Hz  (all R −1 %, C −5 %)
- **f window: 0.932 – 1.051 Hz** (≈ ±6.1 %, cap tolerance dominates)
- Equivalent period window: **0.952 – 1.073 s**

Duty is a resistor ratio only, so passives contribute almost nothing
(corners RA±1 %, RB∓1 % give 53.36 – 53.49 %). The realistic spread comes from
the 555 itself — comparator threshold ratio error, discharge-transistor Ron
(t_low is really ln2·(RB+Ron)·C, though at RB = 680 k the Ron term is
negligible), and finite edge shape — so the assertion window is set at device
level:

- **duty window: 52.4 – 54.4 %** (53.42 % ± 1.0 point)

LED on-current window from Vf spread (1.8–2.2 V), Voh spread (7.0–7.5 V),
RL ±1 %: 8.5 – 10.3 mA, rounded outward to an **8.0 – 10.5 mA** assertion.

## Validation results (ngspice-46, behavioral NE555 macromodel)

| Assertion | Predicted window | Measured | Verdict |
|---|---|---|---|
| f_osc | 0.932 – 1.051 Hz | 0.98823 Hz | PASS |
| duty_pct | 52.4 – 54.4 % | 53.45 % | PASS |
| t_period | 0.952 – 1.073 s | 1.01191 s | PASS |
| i_led_on | 8.0 – 10.5 mA | 9.257 mA | PASS |
| v_out_high | 6.8 – 7.6 V | 7.199 V | PASS |

Full transcript, exact command, and iteration history: `validation.log`.
Wallclock 0.25 s — stated as engineering context (the sim is cheap enough for
interactive iteration); no runtime acceptance criterion applies to
benchmark (a). (The AC3 <60 s budget governs benchmark (b).)

## Fixture and measurement notes

- **V3 ramped supply:** VCC is PWL 0→9 V over 2 ms; measurements are gated
  with TD=2 s so the longer first high phase (charge from 0 V instead of
  1/3 VCC: ln3·(RA+RB)·C ≈ 0.86 s) is excluded from the settle window.
- **V2 one-meas TRIG/TARG:** period = one .meas (RISE=1 → RISE=2 on v(out));
  on-time = one .meas (RISE=1 → FALL=1); f and duty are derived .meas PARAMs.
  TD=2 s deterministically lands inside a low phase (steady-state rises at
  ~2.34/3.35/4.36 s, falls at ~1.87/2.88/3.89 s), so the RISE=1/FALL=1 pairing
  after TD is well-defined.
- **V1:** the deck was iterated until every .meas returned a real number; the
  two convergence failures and their root causes are recorded in
  `validation.log`. No assertion window was widened to make a failure pass.

## Behavioral NE555 macromodel (original, D4 core-library seed)

`NE555_RHOFORM` in `netlist.cir` is written from the device's block diagram, not
from any vendor or textbook deck: 5k/5k/5k divider (CONT rides the 2/3 tap),
two tanh-smoothed B-source comparators, a set-dominant SR latch realized as a
B current source on a 100 pF state cap with a weak tanh positive-feedback hold
term, a softplus-clamped totem-pole output (Voh ≈ VCC − 1.7 V, Vol ≈ 0.15 V,
12 Ω), and a switch-model open-collector discharge transistor (18 Ω on).
Pinout matches the DIP-8 order. Intended license: Apache-2.0/CC0.

## AC1a: DSL expressibility

The design is 8 components, 7 nets, 2 assertions — an illustrative Rhoform DSL
rendering fits in ~30 lines, far under the ~150-line budget:

```rhoform
design blinker_555 {
  supply V9 { rail vcc 9V ramp 2ms }
  part U1  NE555      { }
  part RA  R 100k 1%  ; part RB R 680k 1%
  part CT  C 1u 5%    ; part CB C 10n
  part RL  R 560 1%   ; part D1 LED red
  net vcc  { V9.+, U1.VCC, U1.RST, RA.1 }
  net dis  { RA.2, RB.1, U1.DISCH }
  net tim  { RB.2, CT.1, U1.THRES, U1.TRIG }
  net ctl  { U1.CONT, CB.1 }
  net led  { U1.OUT, RL.1 }  ; net anod { RL.2, D1.A }
  net gnd  { V9.-, CT.2, CB.2, D1.K, U1.GND }
  assert freq(U1.OUT) in 0.932Hz..1.051Hz after 2s
  assert duty(U1.OUT) in 52.4%..54.4%   after 2s
}
```
