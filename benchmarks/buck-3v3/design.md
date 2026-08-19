# Rhoform benchmark b: 3.3 V / 2 A synchronous buck reference design

Requirements: AC1b, AC3. Every dynamic assertion runs green on stock ngspice
with an original behavioral switching model, rung 0, total runtime well under
60 s (measured: 4.9 s canonical run (2 ns timestep); see `validation.log`).

## 1. Specification

| Parameter | Value |
|---|---|
| Input voltage | 12 V nominal, 9-14 V window |
| Output | 3.3 V, 2 A (6.6 W) |
| Output tolerance | +/-3% (3.201-3.399 V) |
| Output ripple | <= 50 mVpp |
| Efficiency at full load | >= 85% |
| Startup overshoot | <= 5% |
| Settling after 1 A -> 2 A step | <= 500 us to +/-1% band |

Topology: synchronous buck (a Schottky freewheel at 2 A / 3.3 V would burn
~0.45 V x 0.7 x 2 A ~= 0.63 W, ~9% of output power, putting the 85% floor at
risk; a 6 mOhm sync FET burns ~17 mW in the same slot -- see sec. 6).

## 2. Duty cycle and switching frequency

Ideal duty D = Vout/Vin:

- Vin = 9 V:  D = 3.3/9  = 0.367
- Vin = 12 V: D = 3.3/12 = 0.275
- Vin = 14 V: D = 3.3/14 = 0.236

With ~92% efficiency the practical duty is D' ~= D/eta, i.e. 0.30 at 12 V and
0.40 worst case at 9 V -- comfortably inside any controller's duty range; no
minimum-on-time hazard (on-time at 14 V, 500 kHz: 0.236 x 2 us = 472 ns >>
the LM25145's 40 ns datasheet minimum on-time).

**fsw = 500 kHz.** Rationale: (a) small enough L and C that all-ceramic
output filtering is cheap; (b) high enough that 2.5 ms of simulated time is
1250 switching cycles, so steady state, a full soft-start, and a load step
all fit in a sub-second rung-0 run; (c) below the range where switching
losses would threaten the 85% floor (fixed-loss budget scales ~linearly with
fsw, sec. 6); (d) comfortably above the audio band and below the AM band.

## 3. Inductor

Ripple-current target: DIL = 30% of Iout = 0.6 App (standard 20-40% window:
lower ripple wastes inductor volume, higher ripple raises core/AC losses and
output ripple). Worst case is Vin,max = 14 V (D = 0.236):

    L = Vout x (1 - D) / (fsw x DIL)
      = 3.3 x (1 - 0.236) / (500e3 x 0.6)
      = 2.521 / 3.0e5
      = 8.4 uH

Choose the standard value **L = 10 uH**, which gives (ideal duty):

    DIL(14 V) = 3.3 x 0.764 / (500e3 x 10e-6) = 0.504 App  (25% of Iout)
    DIL(12 V) = 3.3 x 0.725 / 5.0             = 0.479 App
    DIL(9 V)  = 3.3 x 0.633 / 5.0             = 0.418 App

Measured in the behavioral deck: 0.4844 App at 12 V, 0.5119 App worst case at
14 V -- slightly above ideal because the loop regulates duty above D = Vout/Vin
to cover the modeled IR drops (Ron + DCR ~= 26 mOhm x 2 A ~= 53 mV).

Peak current and saturation margin (using measured worst-case ripple):

    Ipk = Iout + DIL/2 = 2.0 + 0.5119/2 = 2.256 A

Part: **Coilcraft XGL6060-103MEC** (10 uH +/-20%, DCR 18.5 mOhm typ /
20.4 mOhm max, Isat 3.6 A at 10% inductance drop / 5.5 A at 20% / 7.3 A at
30%, Irms 7.3 A for 20 C rise / 10.0 A for 40 C rise; Coilcraft datasheet
Document 1621-2, rev. 02/19/26). Saturation margin against the strictest
rating point: 3.6/2.26 = **1.6x** at the 10%-drop Isat, 5.5/2.26 = 2.4x at
the 20%-drop rating. A 100% overload transient (4.256 A) stays below the
5.5 A 20%-drop rating -- soft-saturating composite core, so inductance sags
gracefully rather than collapsing. RMS heating: Irms ~= 2.0 A vs 7.3 A
(20 C rise) rating. The BOM records L at +/-20%: at the -20% corner (8 uH)
the ripple scales by 1/0.8 to 0.640 App, Ipk rises to 2.32 A, and the
margins become 3.6/2.32 = 1.55x (10%-drop Isat) and 5.5/2.32 = 2.4x -- the
conclusions above are computed at nominal L and survive the tolerance
corner.

## 4. Output capacitor

Ripple has a capacitive and an ESR term (ceramic caps: ESL negligible at
500 kHz):

    DV_C   = DIL / (8 x fsw x C)
    DV_ESR = DIL x ESR

Part: 2x **Murata GRM32ER61C226KE20L** (22 uF, 16 V, X5R, 1210). At 3.3 Vdc
bias these derate ~18%, so C_eff ~= **36 uF** (the deck simulates the derated
value -- deratings are physics, not pessimism). Net ESR of two ~4 mOhm
ceramics in parallel: ~2 mOhm.

    DV_C   = 0.5119 / (8 x 500e3 x 36e-6) = 3.6 mV
    DV_ESR = 0.5119 x 0.002              = 1.0 mV
    DV_pp  ~= 5 mV  (terms are phase-shifted, not directly additive)

Measured: 3.587 mVpp at 12 V -- **13.9x margin** against the 50 mV spec. The cap
size is actually set by the load-step requirement, not ripple: for a 1 A step
with loop crossover fc, the droop is approximately

    DV_step ~= DI / (2 pi x fc x C) = 1.0 / (2 pi x 30e3 x 36e-6) = 147 mV

which recovers within the band well inside 500 us (measured settling:
16.86 us to +/-1%). A ripple-only design -- DIL/(8 x fsw x DV_spec) =
0.5119/(8 x 500e3 x 0.05) ~= 2.6 uF -- would have failed the step spec by an
order of magnitude (DV_step ~= 1.0/(2 pi x 30e3 x 2.6e-6) ~= 2.0 V); 2x22 uF
satisfies both with margin. (A previous revision said "~7 uF" here, a number
derivable from nothing shipped.)

Input capacitor: worst-case input RMS ripple current. sqrt(D x (1-D)) grows
toward D = 0.5, so over the 9..14 V input window the worst case is the 9 V
corner, not nominal:

    Irms,in = Iout x sqrt(D x (1-D))
            = 2 x sqrt(0.275 x 0.725) = 0.89 A   at 12 V nominal (D = 0.275)
            = 2 x sqrt(0.40  x 0.60)  = 0.98 A   at 9 V, practical D' ~= 0.40

(A previous revision published the 12 V evaluation labelled "worst-case",
understating the stress by ~10%.) 2x **Murata GRM32DR71E106KA12L** (10 uF
+/-10%, 25 V, X7R, 1210, 3.2 x 2.5 x 2.0 mm; Murata product catalog) split
this, ~0.49 A rms each at the 9 V corner; 25 V rating vs 14 V max input gives
1.8x derating headroom. Per-part rms current handling should be confirmed
against Murata's temperature-rise curves at 500 kHz for the final land
pattern -- not claimed here.

## 5. Power semiconductors

Synchronous FETs, both **Infineon BSC059N04LS6** (OptiMOS 6, 40 V, Rds(on)
5.9 mOhm max at Vgs = 10 V, Qg 9.4 nC typ over 0-10 V, Qoss 10.2 nC typ at
20 V, Id 59 A at Tc; Infineon datasheet rev. 2.1, 2020-07-22):

- Voltage margin: 40 V rating vs 14 V max input plus switch-node ringing
  (budget 2x Vin transient) -> 40/14 = **2.8x** static margin.
- Current: continuous Id rating tens of amps vs 2.256 A peak.
- Conduction loss at 2 A, 12 V (D' = 0.30):
  - HS: I^2 x Ron x D'     = 4 x 0.0059 x 0.30 = 7.1 mW
  - LS: I^2 x Ron x (1-D') = 4 x 0.0059 x 0.70 = 16.5 mW

Controller: **TI LM25145** (6-42 V synchronous buck controller,
voltage-mode, 0.8 V +/-1% reference, integrated 7.5 V drivers, RT-programmed
to 500 kHz). Chosen because its control law -- voltage-mode PWM with Type-III
compensation -- is exactly what the behavioral deck implements, keeping the
benchmark's model and the buildable hardware in one-to-one correspondence.

## 6. Loss budget and efficiency

At Vin = 12 V, Iout = 2 A (Pout = 3.296 x 1.9988 = 6.588 W):

| Mechanism | Formula | Value |
|---|---|---|
| HS conduction | 4 x 5.9m x 0.30 | 7 mW |
| LS conduction | 4 x 5.9m x 0.70 | 17 mW |
| Inductor DCR | 4 x 20.4m (max) | 82 mW |
| Cap ESR | ~DIL^2/12 x ESR | ~0 mW |
| V-I overlap | 0.5 x Vin x Iout x (tr+tf) x fsw = 0.5 x 12 x 2 x 20n x 500k | 120 mW |
| Gate charge | 2 x Qg,budget x Vdrv x fsw = 2 x 12n x 7.5 x 500k | 90 mW |
| Coss | 0.5 x Coss,budget x Vin^2 x fsw = 0.5 x 600p x 144 x 500k | 22 mW |
| Dead-time body diode | 2 x tdt x Vf x Iout x fsw ~= 2 x 40n x 0.8 x 2 x 500k | 64 mW |
| Controller Iq + housekeeping | -- | ~100 mW |

The gate-charge and Coss rows use budget allowances above the datasheet
figures on purpose: 12 nC vs the 9.4 nC typ Qg (headroom for driver
resistive loss and bootstrap recharge) and 600 pF vs the 510 pF
charge-equivalent Coss implied by Qoss = 10.2 nC at 20 V. Both round the
loss up, so the budget is conservative rather than optimistic.

Fixed (frequency-dependent + quiescent) subtotal ~= 0.40 W; conduction
subtotal ~= 0.11 W.

    eta = 6.588 / (6.588 + 0.502) = 92.9% (predicted)

The behavioral deck carries the conduction terms explicitly (Ron in the
switch-node B-source, DCR and ESR as real elements) and draws the fixed
0.40 W as a constant-power term on the input node (`PFIX`). Measured
efficiency: **92.864%** -- matching the budget and leaving 7.86 points of
margin over the 85% floor to absorb budget error. This margin is the honest
buffer for what a rung-0 behavioral model cannot measure (actual switching
waveform losses); the design does not rely on behavioral optimism to pass.

## 7. Feedback and control

Divider from the LM25145's 0.8 V reference:

    Vout = Vref x (1 + R1/R2) = 0.8 x (1 + 31.2k/10k) = 3.296 V  (-0.12%)

31.2k is an E192 value (192 x log10(3.12) = 95); 10k is E96. 80 uA divider
current. Worst-case DC error stack: +/-1% ref, +/-1% resistors x2 -> +/-2.52%
about a regulation point that sits 0.12% low, giving +2.42%/-2.60% -- inside
the +/-3% window on both sides, and the table in the Output-voltage error stack section (end of this document) reproduces it
(3.2141 .. 3.3799 V). Production would use 0.5% resistors if this were a
shipping design; that is margin commentary, not a spec change.

An earlier revision of this paragraph quoted +3.0%/-1.4% for the 31.6k
divider. That was wrong for 31.6k too -- the same table gives 3.2452 .. 3.4129,
i.e. +3.42%/-1.66%, which grazes the top of the window rather than sitting
inside it. Centring the divider is what fixed that, not the arithmetic.

Control: voltage-mode PWM, Type-III compensation (== PID + parasitic poles).
Plant: duty-to-Vout gain Vin with the LC double pole at

    f0 = 1 / (2 pi sqrt(L x C_eff)) = 1 / (2 pi sqrt(10u x 36u)) = 8.4 kHz

ESR zero at 1/(2 pi x C x ESR) = 2.2 MHz -- too high to help, hence Type-III.
Design: place a double zero on the LC resonance, crossover fc = 30 kHz
(about fsw/17; a previous revision printed "fsw/16", which is 31.25 kHz --
every downstream number is computed from 30 kHz and is unaffected).
Required compensator gain at fc, with divider gain h = 0.8/3.3 =
0.242 and |P(fc)| ~= (f0/fc)^2 = 0.078:

    |Gc(fc)| = 1 / (12 x 0.242 x 0.078) = 4.4

PID realization (deck parameters): double zero at w0 = 2 pi f0 = 5.27e4 rad/s
via Kd(s + w0)^2 = Kd s^2 + Kp s + Ki:

    Kd = |Gc(fc)| / (2 pi fc) = 4.4 / 1.885e5 = 2.33e-5
    Kp = 2 x Kd x w0          = 2.46
    Ki = Kd x w0^2            = 6.47e4 s^-1

plus a derivative-path pole at 159 kHz (1k/1n RC) standing in for Type-III's
high-frequency poles and taming switching-ripple feedthrough. Soft start:
the reference ramps 0 -> 0.8 V over 500 us (SS pin cap on the LM25145),
which is why measured startup overshoot is 0.0466% against the 5% budget.

## 8. Behavioral model (fidelity class: behavioral, rung 0)

Original construction, no vendor models:

- **Switch node** `Bsw`: B-source that outputs `Vin - IL x Ron_HS` when the
  PWM is high and `-IL x Ron_LS` when low -- a lossy ideal synchronous pair
  with no switching-edge dynamics. IL is sensed by a 0 V ammeter in series
  with L.
- **PWM**: 500 kHz 0->1 sawtooth (PULSE source) against the compensator
  output in a B-source comparator; duty is clamped to [0, 0.96].
- **Compensator**: PID from sec. 7 -- G-source integrator into a 1 F cap
  (V = Ki x integral(err)), `ddt()` derivative on a filtered error, summed
  and clamped in a B-source.
- **Input current** `Gin`: mirrors IL onto the input node during the HS
  on-time (charge-correct average input current) plus `PFIX/V(in)` for the
  fixed losses, so input power is measurable at the V3 source.
- **Fixture**: `V3` ramps 0 -> 12 V over 200 us (exercises the regulator
  coming up under a rising rail); load is a 3.3 Ohm base (1 A) plus a 1 A
  PWL current step at t = 1.5 ms; `.tran 100n 2.5m 0 2n` gives 1250 cycles,
  1000 points per cycle.
- **Settling detector**: a B-source flags |Vout - 3.296| > 32.96 mV (the
  deck's `SBAND`, 1% of the 3.296 V target; a previous revision rounded it
  to 33.0 mV here, which is 1.001%); the
  `.meas ... FALL=LAST` on that flag implements "enters and stays within
  +/-1%" exactly, immune to multi-crossing ringing.

What this class deliberately does not model: switching edges (so no measured
overlap/Coss loss -- budgeted instead, sec. 6), dead-time conduction,
gate-drive dynamics, and large-signal magnetics saturation (guarded by the
1.6x margin to even the strictest 10%-drop Isat rating instead). Those
belong to higher rungs.

## 9. Results vs. assertions

| Assertion (`meas_id`) | Window | Measured | Status |
|---|---|---|---|
| Mean Vout (2 A) (`vout_avg`) | 3.3 V +/-3% | 3.2960 V (-0.12%) | pass |
| Output ripple (`vout_pp`) | <= 50 mVpp | 3.587 mVpp | pass |
| Efficiency (`eff`) | >= 85% | 92.864% | pass |
| Startup overshoot (`overshoot_pct`) | <= 5% | 0.0466% | pass |
| 1A->2A settling (`t_settle_us`) | <= 500 us | 16.86 us | pass |

Input corners, in `validation-corners.log` (2 ns, 31.2k divider). Each block
there declares the one deck substitution that produced it, and
`tests/benchmarks/check-corners.py` applies that edit and re-runs, so these are
runs of MODIFIED decks -- not of the shipped one, and not in `validation.log`,
which this paragraph cited until AMB-123 while that file's only mention of a
corner is the line recording that an earlier regeneration destroyed them:

| Vin | il_pp | vout_pp | t_settle_us |
|---|---|---|---|
| 9 V | 0.421457 A | 3.084 mVpp | 45.392 us |
| 12 V | 0.484413 A | 3.587 mVpp | 16.858 us |
| 14 V | 0.511869 A | 3.812 mVpp | 15.528 us |

All five assertions stay green at every corner. Worst deltas are
ripple-current 0.5119 App at 14 V, settling 45.39 us at 9 V (11x inside the
500 us window), and output ripple 3.812 mVpp at 14 V (13x inside the 50 mV
window). No assertion window was modified from the task defaults; every
target was met with the components as chosen.

An earlier revision of this paragraph published 0.515 App, 39.4 us and
3.14 mVpp and cited "supplementary runs in `validation.log`". None of the
three came from the shipped deck: 0.515 and 3.14 are the 31.6k divider at
2 ns, and 39.4 us is the 31.6k divider at 40 ns. The cited runs were not in
`validation.log` either -- the only occurrence of the word "corner" in that
file is the line recording that an earlier regeneration destroyed them. The
survey was never re-run when the divider changed; it is now, and the numbers
above are in the evidence file.

It also claimed the 9 V ripple was "a slow envelope over ~100 cycles --
per-cycle ripple there is 6.4 mVpp". A peak-to-peak over a window cannot be
smaller than the peak-to-peak of a cycle inside it, so that could not have
been true of any deck. Measured directly at 9 V, single-cycle probes give
2.995 / 3.002 mVpp against the 50-cycle figure of 3.084: the envelope adds
0.09 mV, which is to say there is none. The "2x" was 50/24.4, the 40 ns
value.

## Two assertions that cannot currently fail, stated rather than implied

`efficiency` is **arithmetic over a hand-entered constant, not a measurement.**
`Gin` injects `PFIX/V(in)` as input current, so `pin_avg` is identically
`pout + I^2*(Ron+DCR) + PFIX`, and `eff` is a closed form in `PFIX = 0.40 W`.
It is invariant under the timestep (0.928704 at 40 ns, 0.928644 at 2 ns) and
essentially flat across the input range (0.928649 / 0.928644 / 0.928625 at
9 / 12 / 14 V). The `>= 0.85` bound is satisfied for any `PFIX <= 1.056 W`:
`PFIX_max = Pout/0.85 - Pout - conduction = 6.588/0.85 - 6.588 - 0.106 = 1.0566 W`,
confirmed by running the deck at PFIX = 1.056 (eff 0.850042) and 1.06
(eff 0.849603). This read 1.07 W, at which the assertion actually fails
(eff 0.848509) -- overstating the headroom in the unsafe direction, in the one
place a reader is told the check is weak.
Nothing about switching loss is being verified: at rung 0 there is no switching
model to verify. The assertion earns its place by pinning the loss BUDGET, and
it should be re-derived against a real switching model at rung 1.

`startup_overshoot` **measures steady-state ripple, not overshoot.** Probing the
same expression over 1.20-1.40 ms — a window containing no startup transient,
since soft-start ends at 600 us — gives 0.0459 % against the assertion's
0.0466 %. The residual true overshoot is `vout_max_startup 3.29754` (at
1.117 ms) against `vmax_late 3.29751`, about 0.03 mV. The reported figure is
half the peak-to-peak ripple over the mean; it would report nearly the same
number on a converter with no soft-start at all. (A previous revision quoted
0.0466 %/3.29753 for this probe — numbers no single window over the shipped
deck produces; the exact-match figure only arises from a window that still
contains the 1.117 ms peak, which would have voided the point being made.
Re-derived from the deck: append
`.meas tran vmax_late MAX v(out) from=1.2m to=1.4m` and
`.meas tran ripple_late_pct PARAM=(vmax_late/vout_pre - 1)*100`.)

Both are kept because they bound something real (a loss budget, a ripple
envelope) and both are labelled `informational_at_rung_0` in assertions.yaml so
that a reader does not mistake either for the check its name suggests.

## Convergence: what 2 ns does and does not buy

The deck ran at 40 ns until AMB-123 and the values it produced were numerical
artifacts. 2 ns is much closer and is not fully converged:

| tmax | vout_pp | il_pp | overshoot_pct | wall |
|---|---|---|---|---|
| 40 ns | 6.435 mV | 0.5159 A | 0.0964 % | 0.4 s |
| 4 ns | 3.649 mV | 0.4857 A | 0.0480 % | 3 s |
| **2 ns (shipped)** | **3.587 mV** | **0.4844 A** | **0.0466 %** | 5 s |
| 1 ns | 3.548 mV | 0.4837 A | 0.0454 % | 11 s |
| 500 ps | 3.476 mV | 0.4833 A | 0.0444 % | 24 s |

`vout_pp` at 2 ns is 3.19% above the 500 ps value and `overshoot_pct` 4.98%
(3.19% is (3.587-3.476)/3.476 from the table; 4.98% needs the precision the
table rounds away -- (0.0466129-0.0444020)/0.0444020 -- because the rounded
cells give 4.95%). An
earlier revision said "~2.5%" and "~7%"; neither is derivable from that table,
and 2.5% is below the minimum possible value -- the sequence decreases
monotonically in h, so any extrapolated limit is at most 3.476 mV and the 2 ns
error is at least 3.19%.
Because `check-assertions.py` compares `measured:` at the precision it was
recorded to, refining further still fails `make sim` until those values are
re-recorded — the same coupling that made the 40 ns error un-fixable without a
red gate. That is a deliberate trade, not an oversight: 500 ps costs 22 s
against a 60 s budget for three digits nothing downstream reads, and the
alternative is a gate that cannot detect a deck change at all. Anyone refining
the timestep for a real reason should re-record the five values and say so.

None of the engineering conclusions move across the sweep: `Ipk` 2.256 A,
saturation margin 1.6x, ripple margin 13.9x, efficiency 0.92864 (invariant to
four figures over 4 ns..500 ps, three over the whole sweep: the run at 40 ns
gives 0.928704, and the five values are 0.928704 / 0.928628 / 0.928644 /
0.928634 / 0.928635), settling 16.86 us against a 500 us budget.

## Output-voltage error stack

`Vout = Vref x (1 + R1/R2)`, and the terms are the LM25145's +/-1% reference and
+/-1% on both divider resistors. With the original 31.6k/10k the nominal was
3.328 V, already +0.85% before any tolerance, and the worst case reached
**3.4129 V — outside the design's own [3.201, 3.399] window**, i.e. the
converter did not meet the +/-3% specification it asserts.

| divider | nominal | worst case | fits +/-3% |
|---|---|---|---|
| 31.6k / 10k | 3.328 V (+0.85%) | 3.2452 .. 3.4129 V | **no** |
| **31.2k / 10k** | **3.296 V (-0.12%)** | **3.2141 .. 3.3799 V** | yes |

Centring the divider is the fix. Widening the window to admit 3.413 V would
have been asserting a specification the design does not meet, which is the same
move as fitting an expected value to a bug.

Both worst-case corners are 25 C figures, and the stack has a fourth term the
table does not show: divider tempco. The LM25145's +/-1% reference is specified
over its full junction range; the divider is now a MIXED pair -- R1 is a
+/-25 ppm/K thin film part (TNPW040231K2BEED; 31.2k is an E192-only value,
and the thick-film part an earlier revision named here does not exist, see
parts.yaml) and R2 remains +/-100 ppm/K thick film -- so the worst ratio
drift is |25 - (-100)| = 125 ppm/K, which the divider gain
R1/R2 / (1 + R1/R2) = 0.757 turns into 0.31 mV/K on Vout. The binding side is
the low corner's 13.1 mV of headroom (3.2141 V against the 3.201 V floor), so
the +/-3% window holds for part temperatures within about 42 K of the
tolerance reference -- roughly -17..67 C, which covers the bench this
benchmark models but is not an over-temperature guarantee. Holding the window
over -40..85 C means matching R2 to the same thin-film line (TNPW/RT0402 in
the same footprint): a matched +/-25 ppm/K pair bounds the ratio drift at
50 ppm/K (0.125 mV/K), stretching the same headroom past 100 K. (An earlier
revision of this paragraph computed 0.50 mV/K / 26 K for a both-thick-film
divider; the round-18 part correction improved the shipped stack.)

The simulation never showed this: it runs at nominal, where both dividers are
comfortably inside. This is a tolerance defect, and the deck has no tolerance.
