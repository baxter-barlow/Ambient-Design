# Rhoform benchmark b: 3.3 V / 2 A synchronous buck reference design

Requirements: AC1b, AC3. Every dynamic assertion runs green on stock ngspice
with an original behavioral switching model, rung 0, total runtime well under
60 s (measured: 6.6 s canonical run (2 ns timestep); see `validation.log`).

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
risk; a 6 mOhm sync FET burns ~17 mW in the same slot, and ~73 mW with the
20 mOhm current-sense shunt R10 in series with it -- see sec. 6).

## 2. Duty cycle and switching frequency

Ideal duty D = Vout/Vin:

- Vin = 9 V:  D = 3.3/9  = 0.367
- Vin = 12 V: D = 3.3/12 = 0.275
- Vin = 14 V: D = 3.3/14 = 0.236

With ~92% efficiency the practical duty is D' ~= D/eta, i.e. 0.30 at 12 V and
0.40 worst case at 9 V -- comfortably inside any controller's duty range; no
minimum-on-time hazard (on-time at 14 V, 500 kHz: 0.236 x 2 us = 472 ns, and
at least 3.214/14/532 kHz = 431 ns at the low output corner and the fastest
oscillator of sec. 10.1, against the LM25145's T_ON(MIN) of 40 ns typ /
60 ns max, DS p. 9: 7.2x).

**fsw = 500 kHz** (nominal: R_RT = 20.0 k gives 497 kHz typ and 463-532 kHz
worst case, sec. 10.1). Rationale: (a) small enough L and C that all-ceramic
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

Measured in the behavioral deck: 0.4868 App at 12 V, 0.5164 App worst case at
14 V -- slightly above ideal because the loop regulates duty above D = Vout/Vin
to cover the modeled IR drops (Ron, the R10 current-sense shunt during the
off-time, and DCR: ~40 mOhm x 2 A ~= 81 mV at 12 V).

Peak current and saturation margin. The steady-state peak follows from the
measured worst-case ripple, but it is NOT the deck's highest current: the
1 A -> 2 A load step at 1.5 ms -- the transient `load_step_settling` gates --
overshoots it, and that transient peak is what the magnetics actually see.

    Ipk(steady state) = Iout + DIL/2 = 2.0 + 0.5164/2 = 2.258 A
    Ipk(load step)    = max i(Vsns) over 1.45-1.7 ms  = 2.530 A

This document published the 2.256 A figure as "worst case" and derived its
saturation margin from it, 12% optimistic in the unsafe direction (round
21). The margins below are the transient ones.

Part: **Coilcraft XGL6060-103MEC** (10 uH +/-20%, DCR 18.5 mOhm typ /
20.4 mOhm max, Isat 3.6 A at 10% inductance drop / 5.5 A at 20% / 7.3 A at
30%, Irms 7.3 A for 20 C rise / 10.0 A for 40 C rise; Coilcraft datasheet
Document 1621-2, rev. 02/19/26). Saturation margin against the strictest
rating point, at the measured transient peak: 3.6/2.530 = **1.42x** at the
10%-drop Isat, 5.5/2.530 = 2.17x at the 20%-drop rating. (Against the
steady-state peak alone they would read 1.6x and 2.4x.) The core is
soft-saturating composite, so inductance sags gracefully rather than
collapsing. RMS heating: Irms ~= 2.0 A vs 7.3 A (20 C rise) rating. The BOM
records L at +/-20%: at the -20% corner (8 uH) the ripple scales by 1/0.8 to
0.645 App, the computed steady-state Ipk rises to 2.32 A and the measured
load-step peak to 2.562 A, and the margins become 3.6/2.562 = 1.41x
(10%-drop Isat) and 5.5/2.562 = 2.15x -- the conclusions above are computed
at nominal L and survive the tolerance corner.

Overload is bounded by the LM25145's valley current limit (sec. 10.7), in two
cases that need different numbers:

- **Sustained overload**, the load just below the trip: no limit events occur
  and the loop still regulates, so the peak is the valley trip plus one
  regulating ripple, at most 4.035 + 0.865 = **4.90 A** (14 V, Vout 3.38 V,
  the 463 kHz oscillator minimum, and 6.4 uH: the -20% part sagged a further
  20%). That is below the 5.5 A 20%-drop rating, and it is the case that can
  persist.
- **Overload and short onset**: when COMP steps up, the pulse released at the
  valley trip is limited only by the duty-cycle clamp (DS sec. 8.3.11, p. 9).
  The peak is then about **6.4 A** at 14 V with Vout in regulation, 5.8 A at
  9 V and **7.2 A** into a short, for one or a few pulses before the clamp
  folds back: above the 20%-drop rating and at about the 7.3 A 30%-drop
  rating. Later pulses peak at 4.5 A or less, and hiccup follows after 128
  limit cycles.

Isat is a 25 C figure, and Coilcraft publishes its temperature derating only
in its online tool, which is why the sustained case keeps a 10.9% margin.

## 4. Output capacitor

Ripple has a capacitive and an ESR term (ceramic caps: ESL negligible at
500 kHz):

    DV_C   = DIL / (8 x fsw x C)
    DV_ESR = DIL x ESR

Part: 2x **Murata GRM32ER61C226KE20L** (22 uF, 16 V, X5R, 1210). At 3.3 Vdc
bias these derate ~18%, so C_eff ~= **36 uF** (the deck simulates the derated
value -- deratings are physics, not pessimism). Net ESR of two ~4 mOhm
ceramics in parallel: ~2 mOhm. Murata lists the part NRND (stocked on
2026-10-22); it stays the modelled primary, and parts.yaml records
GRM32ER71C226KEA8L (X7R) as the qualified alternate, whose promotion would
re-pin the deck's CEFF and RESR (sec. 12).

    DV_C   = 0.5164 / (8 x 500e3 x 36e-6) = 3.6 mV
    DV_ESR = 0.5164 x 0.002              = 1.0 mV
    DV_pp  ~= 5 mV  (terms are phase-shifted, not directly additive)

Measured: 3.657 mVpp at 12 V -- **13.7x margin** against the 50 mV spec. The cap
size is actually set by the load-step requirement, not ripple: for a 1 A step
with loop crossover fc, the droop is approximately

    DV_step ~= DI / (2 pi x fc x C) = 1.0 / (2 pi x 30e3 x 36e-6) = 147 mV

which recovers within the band well inside 500 us (measured settling:
17.01 us to +/-1%). A ripple-only design -- DIL/(8 x fsw x DV_spec) =
0.5164/(8 x 500e3 x 0.05) ~= 2.6 uF -- would have failed the step spec by an
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
1.8x derating headroom. Murata lists it NRND; it is stocked and stays the
primary. The recorded in-production alternate, GRM32ER71E226KE15L (22 uF
25 V X7R 1210), holds 11.16/8.46/7.35 uF at 9/12/14 V, at least this part at
every input voltage, and Murata's temperature-rise data gives it 0.16 C at
0.49 A rms, which closes the per-part rms question this paragraph used to
leave open (AMB-128, sec. 12).

## 5. Power semiconductors

Synchronous FETs, both **Infineon BSC059N04LS6** (orderable OPN
BSC059N04LS6ATMA1; OptiMOS 6, 40 V, Rds(on) 5.9 mOhm max at Vgs = 10 V, Qg
9.4 nC typ over 0-10 V, Qoss 10.2 nC typ at 20 V, Id 59 A at Tc; Infineon
datasheet rev. 2.1, 2020-07-22):

- Voltage margin: 40 V rating vs 14 V max input plus switch-node ringing
  (budget 2x Vin transient) -> 40/14 = **2.8x** static margin.
- Current: continuous Id rating tens of amps vs the 2.530 A load-step peak,
  and 236 A pulsed (IFX Table 2) vs the overload-onset peaks of sec. 10.7.
- Conduction loss at 2 A, 12 V (D' = 0.30):
  - HS: I^2 x Ron x D'     = 4 x 0.0059 x 0.30 = 7.1 mW
  - LS: I^2 x Ron x (1-D') = 4 x 0.0059 x 0.70 = 16.5 mW
  - R10, the current-sense shunt in series with Q2: 4 x 0.020 x 0.70 = 56 mW
- Gate drive. The LM25145 drives the gates from its 7.5 V VCC, Q1 at about
  6.8 V after the BST diode (DS p. 9), not at the 10 V the 5.9 mOhm maximum
  is specified at. At 7.5 V and 25 C, Rds(on) is 5.07 mOhm typ at 50 A and
  about 5.0 mOhm at 2-3 A (IFX Diagrams 6 and 8). IFX publishes no 7.5 V
  maximum; scaling the typical by 5.9/4.7 estimates 6.3-6.4 mOhm, and the
  only guaranteed bound is the 8.4 mOhm maximum at Vgs = 4.5 V (IFX
  Table 4). Temperature factors (IFX Diagram 9): 0.81 at -40 C, 1.35 at
  100 C, 1.51 at 125 C. The rows above and the deck use 5.9-6 mOhm, which
  is the Q2 typical at about Tj 67 C; hot-maximum FETs would add about
  15 mW, 0.21 points of efficiency, inside the 7.1-point margin of sec. 6.

Controller: **TI LM25145** (6-42 V synchronous buck controller,
voltage-mode, 0.8 V +/-1% reference, integrated 7.5 V drivers, RT-programmed
to 500 kHz). Chosen because its control law -- voltage-mode PWM with Type-III
compensation -- is exactly what the behavioral deck implements, keeping the
benchmark's model and the buildable hardware in one-to-one correspondence.
The correspondence is the control law and the crossover, not the zero
placement: sec. 7 says where the two differ.

## 6. Loss budget and efficiency

At Vin = 12 V, Iout = 2 A (Pout = 3.296 x 1.9988 = 6.588 W):

| Mechanism | Formula | Value |
|---|---|---|
| HS conduction | 4 x 5.9m x 0.30 | 7 mW |
| LS conduction | 4 x 5.9m x 0.70 | 17 mW |
| LS current-sense shunt (R10) | 4 x 20m x 0.70 | 56 mW |
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
subtotal ~= 0.16 W (0.11 W of FETs and DCR, plus 56 mW in R10, which AMB-128
added for shunt current sensing, sec. 10.7).

    eta = 6.588 / (6.588 + 0.502 + 0.056) = 92.2% (predicted)

The behavioral deck carries the conduction terms explicitly (Ron and the R10
shunt in the switch-node B-source, DCR and ESR as real elements) and draws the
fixed 0.40 W as a constant-power term on the input node (`PFIX`). Measured
efficiency: **92.114%** -- matching the budget and leaving 7.11 points of
margin over the 85% floor to absorb budget error (92.864% before R10). This
margin is the honest buffer for what a rung-0 behavioral model cannot measure
(actual switching waveform losses); the design does not rely on behavioral
optimism to pass.

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
Design: crossover fc = 30 kHz (about fsw/17; a previous revision printed
"fsw/16", which is 31.25 kHz -- every downstream number is computed from
30 kHz and is unaffected). The deck's PID below places a double zero on the
LC resonance. The LM25145's Type-III network (sec. 10.8) does not: it takes
the datasheet's placement, first zero at f0/2 and second at f0, which keeps
the estimated phase margin at 55.4-60.9 deg over every load and L/C corner
taken one at a time (with the R10 shunt's damping in the plant) and at
50.1 deg or more at the benchmark's 1-2 A load with every tolerance stacked
(50.5 deg with the resistors held to +/-1 % and their TCR left out), inside the
datasheet's 50-70 deg target; the double zero fell to 47.6 deg one
at a time. Both cross over at about 30 kHz.
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
the reference ramps 0 -> 0.8 V over 500 us (the deck's idealisation of the
LM25145's SS pin; its 6.8 nF capacitor gives 544 us nominal, sec. 10.2),
which is why measured startup overshoot is 0.0476% against the 5% budget.

## 8. Behavioral model (fidelity class: behavioral, rung 0)

Original construction, no vendor models:

- **Switch node** `Bsw`: B-source that outputs `Vin - IL x Ron_HS` when the
  PWM is high and `-IL x (Ron_LS + Rsns)` when low -- a lossy ideal
  synchronous pair with no switching-edge dynamics, whose low side returns
  to ground through the R10 current-sense shunt (`RSNS` = 20 mOhm, held to
  parts.yaml R10 by check-assertions.py as `RON_LS` is held to Q2). IL is
  sensed by a 0 V ammeter in series with L.
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
gate-drive dynamics, the LM25145's valley current limit and duty-cycle clamp
(sec. 10.7), and large-signal magnetics saturation (guarded by the
1.42x margin to even the strictest 10%-drop Isat rating instead). Those
belong to higher rungs.

## 9. Results vs. assertions

| Assertion (`meas_id`) | Window | Measured | Status |
|---|---|---|---|
| Mean Vout (2 A) (`vout_avg`) | 3.3 V +/-3% | 3.2960 V (-0.12%) | pass |
| Output ripple (`vout_pp`) | <= 50 mVpp | 3.657 mVpp | pass |
| Efficiency (`eff`) | >= 85% | 92.114% | pass |
| Startup overshoot (`overshoot_pct`) | <= 5% | 0.0476% | pass |
| 1A->2A settling (`t_settle_us`) | <= 500 us | 17.01 us | pass |

Input corners, in `validation-corners.log` (2 ns, 31.2k divider). Each block
there declares the one deck substitution that produced it, and
`tests/benchmarks/check-corners.py` applies that edit and re-runs, so these are
runs of MODIFIED decks -- not of the shipped one, and not in `validation.log`,
which this paragraph cited until AMB-123 while that file's only mention of a
corner is the line recording that an earlier regeneration destroyed them:

| Vin | il_pp | vout_pp | t_settle_us |
|---|---|---|---|
| 9 V | 0.424440 A | 3.095 mVpp | 43.844 us |
| 12 V | 0.486818 A | 3.657 mVpp | 17.008 us |
| 14 V | 0.516398 A | 3.976 mVpp | 16.002 us |

All five assertions stay green at every corner. Worst deltas are
ripple-current 0.5164 App at 14 V, settling 43.84 us at 9 V (11x inside the
500 us window), and output ripple 3.976 mVpp at 14 V (12.6x inside the 50 mV
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
been true of any deck. Measured directly at 9 V on the shipped deck,
single-cycle probes (2.400-2.402 ms and 2.498-2.500 ms) give 3.008 /
3.017 mVpp against the 50-cycle figure of 3.095: the envelope adds 0.08 mV,
which is to say there is none. The "2x" was 50/24.4, the 40 ns
value.

## Two assertions that cannot currently fail, stated rather than implied

`efficiency` is **arithmetic over a hand-entered constant, not a measurement.**
`Gin` injects `PFIX/V(in)` as input current, so `pin_avg` is identically
`pout + I^2*(Ron+Rsns+DCR) + PFIX` (Rsns in the off-time only), and `eff` is a
closed form in `PFIX = 0.40 W`. It is invariant under the timestep (0.921193
at 40 ns, 0.921141 at 2 ns) and nearly flat across the input range
(0.922132 / 0.921141 / 0.920704 at 9 / 12 / 14 V; the slope is the R10 term,
which scales with 1 - D). The `>= 0.85` bound is satisfied for any
`PFIX <= 0.998 W`:
`PFIX_max = Pout/0.85 - Pout - conduction = 6.588/0.85 - 6.588 - 0.164 = 0.9986 W`,
confirmed by running the deck at PFIX = 0.998 (eff 0.850065) and 0.999
(eff 0.849955). Before R10 joined the deck (AMB-128) conduction was 0.106 W
and the ceiling 1.056 W; an earlier revision read 1.07 W for that deck, at
which the assertion actually failed (eff 0.848509) -- overstating the
headroom in the unsafe direction, in the one place a reader is told the check
is weak.
Nothing about switching loss is being verified: at rung 0 there is no switching
model to verify. The assertion earns its place by pinning the loss BUDGET, and
it should be re-derived against a real switching model at rung 1.

`startup_overshoot` **measures steady-state ripple, not overshoot.** Probing the
same expression over 1.20-1.40 ms — a window containing no startup transient,
since soft-start ends at 600 us — gives 0.0463 % against the assertion's
0.0476 %. The residual true overshoot is `vout_max_startup 3.29756` (at
1.175 ms) against `vmax_late 3.29752`, 0.043 mV -- the .meas difference,
4.29407e+01 uV, not the difference of the two six-figure printouts. The
reported figure is half the peak-to-peak ripple over the mean; it would
report nearly the same
number on a converter with no soft-start at all. (On the deck before R10 the
same probe gave 0.0459 % against 0.0466 % and a 0.022 mV residual. A previous
revision quoted 0.0466 %/3.29753 for this probe — numbers no single window
over the deck of that time produced; the exact-match figure only arises from
a window that still contained the startup peak, which would have voided the
point being made. Re-derived from the deck: append
`.meas tran vmax_late MAX v(out) from=1.2m to=1.4m`,
`.meas tran ripple_late_pct PARAM=(vmax_late/vout_pre - 1)*100` and
`.meas tran dov_uv PARAM=(vout_max_startup - vmax_late)*1e6`.)

Both are kept because they bound something real (a loss budget, a ripple
envelope) and both are labelled `informational_at_rung_0` in assertions.yaml so
that a reader does not mistake either for the check its name suggests.

## Convergence: what 2 ns does and does not buy

The deck ran at 40 ns until AMB-123 and the values it produced were numerical
artifacts. 2 ns is much closer and is not fully converged. The sweep below was
re-run on the shipped deck with R10 (AMB-128); wall times are one machine's
on 2026-10-22:

| tmax | vout_pp | il_pp | overshoot_pct | wall |
|---|---|---|---|---|
| 40 ns | 6.855 mV | 0.5190 A | 0.1030 % | 0.4 s |
| 4 ns | 3.832 mV | 0.4905 A | 0.0497 % | 3 s |
| **2 ns (shipped)** | **3.657 mV** | **0.4868 A** | **0.0476 %** | 7 s |
| 1 ns | 3.584 mV | 0.4879 A | 0.0455 % | 10 s |
| 500 ps | 3.520 mV | 0.4875 A | 0.0446 % | 20 s |

`vout_pp` at 2 ns is 3.88% above the 500 ps value and `overshoot_pct` 6.57%,
both at the precision the table rounds away -- (3.65668-3.51996)/3.51996 and
(0.0475544-0.0446234)/0.0446234 -- because the rounded cells give 3.89% and
6.73%. Both sequences decrease monotonically in h, so any extrapolated limit
is at most 3.520 mV and the 2 ns `vout_pp` error is at least 3.88%. `il_pp`
is not monotone below 2 ns and sits within 0.15% of the 500 ps value. (On the
deck before R10 the same comparison gave 3.19% and 4.98%; an earlier
revision had said "~2.5%" and "~7%", neither derivable from that deck's
table, and 2.5% below the minimum possible value.)
Because `check-assertions.py` compares `measured:` at the precision it was
recorded to, refining further still fails `make sim` until those values are
re-recorded — the same coupling that made the 40 ns error un-fixable without a
red gate. That is a deliberate trade, not an oversight: 500 ps costs 20 s
against a 60 s budget for three digits nothing downstream reads, and the
alternative is a gate that cannot detect a deck change at all. Anyone refining
the timestep for a real reason should re-record the five values and say so.

None of the engineering conclusions move across the sweep: steady-state
`Ipk` 2.258 A, saturation margin 1.42x at the measured load-step peak,
ripple margin 13.7x, efficiency 0.92114 (the five values are 0.921193 /
0.921154 / 0.921141 / 0.921142 / 0.921141: within 1.3e-5 over 4 ns..500 ps
and 5.2e-5 over the whole sweep), settling 17.01 us against a 500 us budget
(16.72-17.05 us across the sweep).

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

## 10. Component-level design (EE-reviewed 2026-10-22, AMB-128)

Sections 1-9 size the power stage and the deck. This section derives, with a
citation for every value, the parts the BOM used to leave unstated: the
bootstrap capacitor, the RT resistor, the SS capacitor, the Type-III network's
values (once "chosen at layout time"), the current-limit network, and what the
LM25145 pin map (sec. 11) turns out to need. It was proposed in b45d168 and
d04d775 and EE-reviewed on 2026-10-22 (AMB-128); sec. 12 records each review
decision with its sources. One decision reaches the gates: the current limit
moved to shunt sensing (sec. 10.7), which puts R10 in the low-side conduction
path, so the deck carries it (`RSNS`), and netlist.cir, assertions.yaml, both
validation logs and the tables of sections 6 and 9 were re-recorded from fresh
runs. Nothing else here moves a number the gates pin. The living source
`buck-3v3.rhoform` declares these parts, pins and nets.

### 10.0 Sources and fixed inputs

**LM25145 datasheet.** TI SNVSAT9, https://www.ti.com/lit/ds/symlink/lm25145.pdf,
revision "*" (June 2017, p. 2), 62 pages. TI's product page, read 2026-10-22, lists
the part Active with this data sheet. It is cited as "DS p. N, eq. N / Table N /
section".

**BSC059N04LS6 datasheet.** Infineon, rev. 2.1 (2020-07-22),
https://www.infineon.com/assets/row/public/documents/24/49/infineon-bsc059n04ls6-datasheet-en.pdf.
It is cited as "IFX p. N, Table/Diagram N". Page mapping:
- p. 1: key parameters and pinout
- p. 4: static, dynamic and gate-charge tables
- p. 7: Diagrams 5-8
- p. 8: Diagrams 9-12
- p. 9: Diagrams 13-15
- p. 11: Fig. 2, the TDSON-8 FL board pads

**XGL6060 datasheet.** Coilcraft,
https://www.coilcraft.com/getmedia/329fe97c-7311-4726-9bf3-37718f42b168/xgl6060.pdf.
It is cited as "CC 1621-N" or "CC p. 2" (the part table). The page footers read
Documents 1621-1 to 1621-4, revised 02/19/26, which confirms the "Document 1621-2
rev 02/19/26" that sec. 3 and parts.yaml cite; the proposal's text extraction had
lost the footers.

**WSLP datasheet.** Vishay document 30122, rev. 09-Sep-2024,
https://www.vishay.com/docs/30122/wslp.pdf. It is cited as "WSLP p. N".

**Fixed by sections 1-9 and parts.yaml (not changed here):**
- Vin 9-14 V (12 V nominal), Vout 3.3 V at 2 A, fsw = 500 kHz.
- L = 10 uH, effective Cout 36 uF, net ESR 2 mOhm, DCR 20.4 mOhm max.
- f0 = 8.4 kHz, fc target about 30 kHz, soft-start about 500 us.
- R1 = 31.2 k (R_FB1 below), R2 = 10.0 k (R_FB2).
- the MPNs of U1, L1, C1, C2, R1, R2. (AMB-128 changed Q1 and Q2 to the orderable
  OPN and replaced C3 for lifecycle, sec. 12.)

The proposal read the datasheet through a non-layout PDF-to-text extraction that
shifted columns on some EC-table rows (DS pp. 7-9). AMB-128 re-read the table with
a layout-preserving extraction (`pdftotext -layout`), which keeps every row under
MIN/TYP/MAX; the values below are from that reading (sec. 10.11 item 3).

### 10.1 RT: switching frequency

DS p. 20, eq. 3: `R_RT[kOhm] = 10^4 / F_SW[kHz]`. The 500 kHz row of DS Table 1
(p. 20) is 20 kOhm.

    R_RT = 10^4 / 500 = 20.0 kOhm   -> E96 20.0 k, 1 %, 0402 (R5)

The datasheet gives oscillator accuracy only at R_RT = 25 k: FSW2 is 380 / 400 /
420 kHz min/typ/max over TJ (DS p. 8). Eq. 3 is not exact at 20 k: it gives
400 kHz at 25 k, matching FSW2 typ, but 800 kHz at 12.5 k against the 780 kHz
typical the DS gives there (p. 20), so the typical at 20 k is about 497 kHz. With
the IC's +/-5 % and R5 at +/-2 % (1 % plus 100 ppm/K over 100 K):

    f_sw = 497 x 0.95/1.02 = 463 kHz   to   497 x 1.05/0.98 = 532 kHz

This replaces the 475-525 kHz the proposal assumed. Loop gain does not depend on
f_sw (line feedforward, k_FF = 15), and neither does f0. The current-limit peaks
of sec. 10.7 use 463 kHz; the valley requirement and the minimum on-time use
532 kHz. At 14 V and 463 kHz the inductor ripple is 0.545 App at 10 uH and
0.681 App at 8 uH, about 4.4 mVpp at the output.

### 10.2 Soft-start capacitor

DS p. 21, eq. 4 and eq. 5:

    t_SS = C_SS * V_REF / I_SS;    C_SS[nF] = 12.5 * t_SS[ms]

For the about 500 us that sec. 7 states:

    C_SS = 12.5 * 0.5 = 6.25 nF   -> E12 6.8 nF C0G, 0402 (C9)
    t_SS = 6.8 nF * 0.8 V / 10 uA = 544 us

E12 neighbour 5.6 nF gives 448 us. 6.8 nF is the nearer of the two: 44 us against
52 us.

Spread, with I_SS 8.5-12 uA, V_REF 792-808 mV (DS p. 8) and C at +/-5 %:
6.46 nF x 0.792 V / 12 uA = 426 us to 7.14 nF x 0.808 V / 8.5 uA = 679 us. The
capacitor is above the DS minimum of 2.2 nF (DS p. 4) and the more than 2 nF the
SS clamp needs (DS p. 21). C0G is chosen for a ramp that does not move with bias
or temperature; X7R would also work. The start-up current corner of sec. 10.7
depends on the ramp's slope, at most 12 uA / 6.46 nF = 1.858 V/ms, not on t_SS.

**The deck's ramp is an idealisation of this.** Its PWL reference rises over
100-600 us. With the UVLO divider of sec. 10.5 and the fixture's 0-12 V input
ramp, EN would rise at about 20 + 200 x 8.30/12 = 158 us and SS complete at
about 702 us. The startup_overshoot windows (0-1.4 ms and 1.3-1.5 ms) contain
either ramp, and the deck is not changed.

### 10.3 Bootstrap capacitor (BST to SW)

DS p. 23 (8.3.9): "Connect a 0.1-uF or larger ceramic capacitor close to the BST and
SW pins." Check:

- **Charge per cycle.** IFX p. 9, Diagram 14, digitised in AMB-128: V_GS = 7.5 V
  is reached at 6.9 nC on the V_DD = 8 V curve, 7.2 nC on the 20 V curve and
  7.3 nC on the 32 V curve. Cross-check: Table 6's Qg(0-10 V) = 9.4 nC at 20 V,
  less 2.5 V x 0.873 nC/V of post-plateau slope, is 7.22 nC. Q1's gate swings only
  about 6.8 V (VCC less the BST diode), about 6.4 nC, so 7.3 nC is an upper bound.
  Add I_Q-BST of 80 uA x 2 us = 0.16 nC (DS p. 9). Against C10's worst-case
  effective capacitance of 70.3 nF:

      dV_BST = (7.3 + 0.16) nC / 70.3 nF = 106 mV per cycle

- **Headroom.** That is far inside the 7.3 - 0.9 - 3.4 = 3.0 V between the minimum
  VCC less the boot-diode drop (DS pp. 7, 9) and the 3.4 V BST-SW UV threshold
  (DS p. 9).
- **Rating.** BST-SW stays at or below 14 V absolute (DS p. 6), so the capacitor is
  rated 25 V.

Pick: 100 nF, X7R, 25 V, 0402 (C10).

### 10.4 VCC decoupling and VIN bypass

DS p. 17 (8.3.3): "Connect a ceramic decoupling capacitor between 1 uF and 5 uF from
VCC to AGND". DS p. 5 (pin 14) says to decouple to PGND; the two grounds are one net
here. All three DS application circuits use 2.2 uF: Figure 46 on p. 36, Figure 32 on
p. 18.

    C_VCC = 2.2 uF, X7R, 25 V, 0805 (C11, Murata GRM21BR71E225KE11L)

- **Rating.** VCC is 7.5 V nominal, 7.7 V at most (DS p. 7), and 14 V absolute
  (DS p. 6).
- **DC bias.** The effective value must stay at or above 1 uF. The 0805 part loses
  28.2 % at 7.7 V (Murata EC data), so its worst case is
  2.2 x 0.718 x 0.90 (K) x 0.85 (X7R) x 0.95 (aging) = 1.15 uF, and at 0 V it is at
  most 2.2 x 1.1 = 2.42 uF, inside the 5 uF limit. The 0603 class fails: the
  closest 0603 data (GRM188Z71E225KE43) gives 2.2 x 0.526 x 0.9 x 0.85 = 0.885 uF.
  The proposal's TDK C1608X7R1E225K080AC (0603) is not listed by TDK or Digi-Key,
  and a 4.7 uF 0805 would read about 5.4 uF at low bias, over the limit.
- **Ratio to C10.** At least 1.15/0.092 = 12.5, both at their worst case.

**There is no VDDA pin on the LM25145.** See sec. 11, decision 2.

VIN pin bypass: parts.yaml already carries C3, 100 nF at U1 VIN. DS Figure 32
(p. 18) and Figure 46 (p. 36) show C_VIN = 0.1 uF. The DS's optional 4.7 Ohm series
filter for high-voltage use (p. 17) is not needed at 14 V maximum.

### 10.5 EN/UVLO divider

**Is it needed?** Not for function. DS p. 18 lists EN tied to VIN as "the simplest
way". It is kept, after review, for three reasons:

1. VCC regulation (7.3-7.7 V) is specified only for 9 V <= VIN <= 42 V (DS p. 7).
   Below about 7.75 V the LDO drops out and the gate drive falls (DS p. 18,
   8.3.3).
2. With EN tied to VIN the IC would start at the VCC UV point, 4.8-5.2 V with only
   0.26 V of hysteresis (DS p. 7), and draw about 1.3 A at 5.5 V input. That is
   outside the 9-14 V range the benchmark specifies.
3. A defined UVLO is buildability hygiene.

DS p. 18, eqs. 1-2, with I_HYS = 10 uA and V_EN = 1.2 V (DS p. 8). Targets: on 8.5 V,
off 7.5 V, both below the 9 V minimum.

    R_UV1 = (V_on - V_off) / I_HYS = 1.0 V / 10 uA = 100 kOhm    -> E96 100 k (R6)
    R_UV2 = R_UV1 * V_EN / (V_on - V_EN) = 100k * 1.2 / 7.3 = 16.44 k

From KCL at EN with the 10 uA source on (DS Fig. 33, p. 19):

    V_on  = V_EN (1 + R6/R7)
    V_off = V_EN (1 + R6/R7) - I_HYS x R6

**Tolerance, and why R7 is 16.9 k (AMB-128).** V_EN is 1.164-1.236 V and I_HYS
9-11 uA over TJ (DS p. 8); each resistor is +/-2 % (1 % plus 100 ppm/K over 100 K,
Yageo's +/-100 ppm/C). V_off rises with R6 (dV_off/dR6 = V_EN/R7 - I_HYS, about
71 - 10 uA, positive), so each V_off bound takes one consistent R6 corner.
- 16.5 k, the E96 neighbour of the ideal and the proposal's pick, turns on as late
  as 1.236 x (1 + 102/16.17) = 9.03 V, above the 9 V minimum input. With 1 % parts
  alone it is 8.88 V, a 0.12 V margin the resistor TCR consumes.
- **16.9 k (R7):** V_on = 1.2 x (1 + 100/16.9) = **8.30 V** nominal, from
  1.164 x (1 + 98/17.238) = 7.78 V to 1.236 x (1 + 102/16.562) = 8.85 V.
  V_off = **7.30 V** nominal, from 7.78 - 11 uA x 98 k = 6.70 V to
  8.85 - 9 uA x 102 k = 7.93 V.
- Every turn-on point is below 9 V with at least 0.15 V of margin. Every turn-off
  point is above 6.70 V, above the 6 V VIN minimum (DS p. 7) and well above the
  4.67 V VCC UV falling threshold (DS p. 18). Hysteresis is at least
  9 uA x 98 k = 0.88 V, so the converter does not chatter on input sag.
- At V_off,min = 6.70 V, VCC is at least 6.70 - 0.63 = 6.07 V (DS p. 7 dropout),
  and the required duty, 3.38/6.70/0.98 = 0.515, is inside the 0.894 maximum that
  T_OFF(MIN) (200 ns at 532 kHz) leaves.
- EN at 14 V input is 14 x 16.9/116.9 + 10 uA x (100 k || 16.9 k) = 2.17 V. The
  absolute maximum is 45 V (DS p. 6).
- The divider draws 12/116.9 k = 103 uA (1.2 mW) at 12 V.

### 10.6 Gate drive and bias budget (check, no part)

- **VCC current.** Gate charge 2 x 7.2 nC (sec. 10.3) x 532 kHz = 7.66 mA, plus
  I_Q,switching of at most 3.4 mA (DS Fig. 11, p. 12: 3.27-3.40 mA at 9-14 V over
  -40 to 125 C). Fig. 11 is measured with SYNCIN tied to VCC (the
  typical-characteristics conditions, pp. 11-12), so it already includes the
  0.39 mA SYNCIN draw. Total about **11.1 mA**, against the 20 mA regulation
  condition and the 40 mA minimum current limit (DS p. 7). Fig. 11 is at
  R_RT = 25 k (400 kHz); the small increase at 500 kHz is not quantified.
- **Dissipation at 14 V.** The LDO pass device dissipates about
  (14 - 7.3) x 11.1 mA = 74 mW. The whole IC dissipates at most
  14 V x 11.1 mA = 155 mW (part of the gate-drive energy goes to the FETs' gate
  resistance instead), at most +5.7 C at 36.8 C/W (DS p. 7).
- **On-resistance at 7.5 V drive.** Sec. 5: 5.07 mOhm typ at 50 A and about
  5.0 mOhm at 2-3 A (IFX Diagrams 6 and 8), an estimated 6.3-6.4 mOhm maximum at
  25 C, temperature factors 0.81 at -40 C and 1.51 at 125 C (Diagram 9). Diagram 8
  reads 4.73 mOhm at 10 V against Table 4's 4.7 typ, so the IFX curves and table
  agree. The deck's RON = 6 m is kept: it equals the Q2 typical at about Tj 67 C.
- **Timing.**
  - Minimum on-time at 14 V: at least 3.2141 V / 14 V / 532 kHz = 431 ns, against
    T_ON(MIN) 40 ns typ / 60 ns max (DS p. 9): 7.2x. At the IC's 42 V maximum it
    would be 144 ns.
  - Minimum off-time at 9 V: about 0.6 x 2 us = 1.2 us, against 200 ns max.

### 10.7 Current limit (ILIM, R_SENSE mode on R10)

**Decision (AMB-128): shunt sensing.** The proposal used R_DS(on) sensing on Q2 (R8
= 66.5 Ohm to SW). No value of R8 works at both corners in that mode, so the review
moved the limit to the LM25145's R_SENSE mode: R10, 20 mOhm, from the Q2 source to
GND, and R8 = 634 Ohm from ILIM to the Q2-source side of R10 (net ISNS).

**Datasheet basis (DS).**
- ILIM sources a current into R_ILIM, and the comparator "prevents further SW
  pulses if the ILIM pin voltage goes below GND" (p. 23). Fig. 40 (p. 24) puts ILIM
  on its + input and PGND on its - input. The inductor current is sensed during
  the off-time.
- R_DS(on) mode (R_ILIM to SW): I_RDSON 200 uA at 27 C, +4500 ppm/C typical, with
  limits of 180-220 uA at 25 C only (pp. 9, 23). R_SENSE mode (R_ILIM to a shunt at
  the Q2 source, Fig. 39): I_RS 100 uA, 90-110 uA over TJ, tempco 0 (p. 9). The IC
  detects R_SENSE mode because R_ILIM's far end never rises to VIN (p. 23).
- PGND (p. 5, pin 12): connect it "directly to the source of the low-side MOSFET
  or the ground side of a shunt resistor".
- Eq. 6 (p. 24): R_ILIM = (I_OUT(OCP) - dI_L/2) / I_RS x R_S. The dI_L/2 term is
  part of the equation, so the programmed quantity is the valley.
- C_ILIM is "essential" in R_DS(on) mode (tau about 6 ns) and not required in
  R_SENSE mode (p. 24). The DS recommends shunt sensing at lower output currents
  "to provide accurate overcurrent protection" and wherever setpoint accuracy over
  temperature is critical (p. 24).
- 128 consecutive current-limit cycles start hiccup, 8192 cycles off (pp. 9, 25).
- Duty-cycle clamp (p. 9; sec. 8.3.11, Fig. 41, p. 25): CLAMP sits
  V_CLAMP-OS = 0.2 + VIN/75 above the steady-state COMP, against a ramp of
  VIN/k_FF = VIN/15, so a pulse can run to D_ss + 0.2 + 3/VIN before it is ended.
  Under repeated limit events CLAMP falls toward V_CLAMP-MIN = 0.3 + VIN/150, which
  is D = 0.1. The DS gives no fold-back rate.

**Trip law.** Eq. 6 omits the comparator threshold, V_ILIM-TH = -8 / -2 / +3.5 mV
(DS p. 9, over TJ). The comparator trips when I_x R_ILIM - I_L R_S falls below it:

    I_valley,trip = (I_x * R_ILIM - V_ILIM-TH) / R_S

**Required window: 2.30 A <= trip <= 4.635 A.**
- Low side, no nuisance trip. The largest normal-operation valley is 2.278 A, in
  start-up into a 1.65 Ohm (2 A) load with the SS slope at its maximum (sec. 10.2),
  on a Type-III loop model with the SS-FB clamp (DS p. 8, 115 mV). The deck PID
  gives 2.177 A for the same case and 2.250 A for the 1 A -> 2 A step at
  9 V / 532 kHz / 12 uH / 45.6 uF; the steady-state valley is at most 1.838 A
  (9 V, 12 uH, 532 kHz, 3.214 V). Those runs are scratch runs of decks modified at
  FSW, LVAL, CEFF, V3 and the load, before R10, and are not committed; R10's
  damping would only lower them. 2.30 A rounds the largest up. (The proposal's
  2.06 A was the nominal 12 V step only.)
- High side, sustained operation must not saturate L1. One ripple on top of the
  trip, at 14 V, Vout 3.38 V (the error-stack maximum), 463 kHz and 6.4 uH (8 uH
  sagged a further 20 %), must stay at or below the 5.5 A 20 %-drop Isat (CC 1621-2):
  dI_max = 3.38 x (1 - 3.38/14) / (6.4e-6 x 463e3) = 0.865 A, so the trip must stay
  at or below 4.635 A.

**Why R_DS(on) mode is rejected.** At 25 C only, with R8 at +/-2 % and the Q2
maximum estimate of 6.33 mOhm (sec. 5): at 66.5 Ohm the low corner is
(180e-6 x 66.5 x 0.98 - 3.5e-3) / 6.33e-3 = 1.30 A, below even the steady-state
valley and before any temperature effect (0.92-0.99 A at -40 C). The smallest R8
that clears 2.30 A at 25 C is 105 Ohm, and its high corner, taking the typical
5.0 mOhm as the minimum because IFX publishes none, is
(220e-6 x 105 x 1.02 + 8e-3) / 5.0e-3 = 6.31 A, a 7.18 A peak. No R8 meets both
bounds, so the uncertain R_DS(on) minimum and temperature factors cannot change the
verdict. The proposal's figures here were also wrong: R_DS(on) is 5.07 mOhm, not
4.8; Diagram 9's factors are 0.81 and 1.51, not 0.85 and 1.26; and in R_DS(on) mode
the trip moves about -1 % at 100 C, -4 % at 125 C and -13 % at -40 C, rather than
climbing 13 % by 100 C.

**Shunt sizing.** For each R_S, the E96 R_ILIM that maximises the smaller of the two
margins. Tolerances: I_RS 90-110 uA and V_ILIM-TH -8 to +3.5 mV over TJ; R_ILIM
+/-2 % (1 % plus 100 ppm/K over 100 K); R_S +/-1.94 % (1 % plus 75 ppm/K over 125 K,
WSLP p. 2); and the R8/C12 filter lag, 0.469 A/us x R_ILIM x 82 pF (x 1.02 x 1.05),
taken off the low corner only, because a filtered node lagging a falling current
reads high and trips early. Onset peaks use the clamp-limited on-time at 14 V
(1.435 us) and 6.4 uH, with Vout at 3.38 V and then 0 V. The last column is the
PGND-to-shunt layout offset that would use up the low margin.

| R_S / R_ILIM | Low trip (margin to 2.30 A) | Nominal (eq. 6) | High trip | Sustained peak (margin to 5.5 A) | Onset peak, 14 V / short | Loss, 12 / 14 V | Offset |
|---|---|---|---|---|---|---|---|
| 10 m / 316 | 2.378 (+3.4 %) | 3.360 (3.160) | 4.431 | 5.297 (+3.7 %) | 6.81 / 7.57 | 28 / 30 mW | 0.8 mV |
| 12 m / 383 | 2.460 (+6.9 %) | 3.358 (3.192) | 4.332 | 5.197 (+5.5 %) | 6.71 / 7.47 | 34 / 36 mW | 1.9 mV |
| 15 m / 475 | 2.491 (+8.3 %) | 3.300 (3.167) | 4.167 | 5.032 (+8.5 %) | 6.55 / 7.31 | 42 / 45 mW | 2.9 mV |
| 18 m / 576 | 2.554 (+11.1 %) | 3.311 (3.200) | 4.115 | 4.980 (+9.5 %) | 6.50 / 7.25 | 51 / 54 mW | 4.6 mV |
| **20 m / 634** | **2.545 (+10.7 %)** | **3.270 (3.170)** | **4.035** | **4.900 (+10.9 %)** | **6.42 / 7.17** | **56 / 60 mW** | **4.9 mV** |

20 m / 634 is the only row with at least 10 % on both margins. It also has the
lowest high trip of the rows that clear the low bound, so the lowest onset peaks;
every lower-R_S optimum reaches 7.25-7.57 A into a short. Against 15 mOhm it costs
14 mW at 12 V / 2 A, which moves the efficiency 92.30 % -> 92.11 %.

**Values.**
- R10: 20 mOhm +/-1 %, 1 W at 70 C, +/-75 ppm/C, 1206 metal strip, AEC-Q200,
  Vishay WSLP1206R0200FEA.
- R8: 634 Ohm +/-1 %, 0402, +/-100 ppm/C, Yageo RC0402FR-07634RL.
- C12: 82 pF +/-5 % C0G 50 V, unchanged (the same MPN as C7); tau = 634 Ohm x 82 pF
  = 52 ns.

**Trip currents.**

    low   (90e-6 x 634 x 0.98 - 3.5e-3) / (0.020 x 1.019375) - 0.026 = 2.545 A
    high  (110e-6 x 634 x 1.02 + 8e-3) / (0.020 x 0.980625)          = 4.035 A
    nom   (63.4 + 2) mV / 20 mOhm                                     = 3.270 A

Eq. 6 with V_ILIM-TH = 0 gives 3.170 A, the R_ILIM for I_OUT(OCP) = 3.41 A at 12 V.
The output current limit is 3.270 + 0.479/2 = 3.51 A nominal at 12 V and at least
2.545 + 0.324/2 = 2.71 A (9 V, 12 uH, 532 kHz), 1.35x rated. The low trip clears
2.30 A by 0.245 A and the 2.250 A load-step valley by 0.295 A. Into a 2 A
constant-current start-up load the Type-III model shows at most 62 consecutive
cycles above 2.30 A, so any run of trips is shorter than the 128 cycles that
start hiccup, and start-up completes.

**Peak currents (sec. 3).**
- Sustained overload, load just below the high trip: 4.035 + 0.865 = **4.90 A**,
  0.60 A under 5.5 A (4.73 A without the sag term).
- Overload and short onset: the pulse released at the trip runs to
  t_on <= min(D_ss + 0.2 + 3/VIN, 1 - T_OFF(MIN) x f) / f, with f = 463 kHz and
  L = 6.4 uH:
  - 14 V, Vout about 3.38 V: D = 0.25 + 0.414 = 0.664, t_on = 1.435 us,
    I_pk = 4.035 + 10.62 x 1.435/6.4 = **6.42 A**;
  - 12 V: D = 0.74, t_on = 1.598 us, 6.19 A;
  - 9 V: D = 0.93, cut by T_OFF(MIN) (140 typ / 200 max ns, p. 9) to
    t_on = 1.96-2.02 us, 5.76-5.81 A;
  - short at 14 V (Vout = 0): 4.035 + 14 x 1.435/6.4 = **7.17 A**;
  - with 6.0 uH over the excursion, since L is already below 0.8 L0 above 5.5 A,
    the 14 V figures read 6.57 A and 7.38 A.

  These sit above the 5.5 A 20 %-drop rating and at about the 7.3 A 30 %-drop
  rating (CC 1621-2), for one or a few pulses. Near regulation the current decays
  back to the trip at Vout/L = 0.53 A/us, about two periods, and CLAMP then steps
  down toward V_CLAMP-MIN, after which peaks are at most
  4.035 + 14 x 0.1 / (463e3 x 6.4e-6) = 4.51 A even into a short; hiccup follows
  after 128 limit cycles. This is a property of valley limiting with this clamp in
  either sensing mode. The sensing choice enters only through the high trip, which
  the chosen row minimises.

**Dissipation and other checks.**
- R10: P = R_S (1 - D')(Io^2 + dI^2/12) = 48 / 56 / 60 mW at 9 / 12 / 14 V, and
  0.30 W in the worst sustained overload (I_avg 4.468 A at 14 V), against 0.45 W
  derated at 125 C ambient (WSLP p. 3: full rating to 70 C, linear to zero at
  170 C), a 1.48x margin; 0.85 W at 85 C. The onset pulses carry negligible energy.
  R8 dissipates (110 uA)^2 x 634 Ohm = 7.7 uW.
- ILIM pin minimum: -44 mV at the 4.90 A sustained peak and -90 mV at the 7.17 A
  short-onset peak, against the -1 V absolute maximum (DS p. 6).
- Shunt ESL is 0.5-5 nH (WSLP p. 1). At turn-off commutation that is a spike of
  about 0.2-0.8 V across the shunt for about 10 ns, which the 52 ns R8/C12 filter
  attenuates about 5x at the pin. That is why C12 stays.
- Q2's V_GS rises by I x R_S, about 0.1 V sustained and 0.15 V at the onset peak,
  because its source sits below PGND. This is harmless.
- R10 adds (1 - D) x 20 mOhm of series damping to the LC plant (DS Table 3
  note 2, p. 31); sec. 10.8 includes it.

**Layout constraints** (v1 has no placement; recorded here for R30 and sec. 11):
- R10 sits at the Q2 source pins.
- A Kelvin trace runs from R10's Q2-side pad to R8, and R8 sits at U1 ILIM, away
  from SW (DS p. 50, layout item 4).
- A ground Kelvin trace runs from R10's ground-side pad to U1 PGND and C12.
- No power current flows in either sense trace. Each 1 mV of PGND-to-shunt offset
  moves the trip by 50 mA; the low margin absorbs 4.9 mV.

**Residual risks** (none changes the choice): the onset peaks above, whose number of
wide pulses the DS does not bound; XGL6060 Isat temperature derating, which is
unquantified; ILIM comparator propagation delay, which is unspecified (100 ns at
0.47 A/us is 0.05 A, inside the low margin); the low-side requirement's dependence
on the loop model, 2.18-2.28 A across the two; and the Kelvin layout, which is
mandatory.

### 10.8 Type-III compensation (CN1: R3, R4, C6, C7, C8)

**Topology.** DS Table 3 (p. 31):
- R_C1 in series with C_C1, from COMP to FB.
- C_C2 from COMP to FB.
- R_C2 in series with C_C3, from VOUT to FB, in parallel with R_FB1.

**Transfer functions.** DS Table 4 (p. 32), with the modulator line-feedforward gain
V_IN/V_RAMP = k_FF = 15 (DS p. 22, p. 31; k_FF row DS p. 9). Because of
feedforward, loop gain does not depend on V_IN.

**Design equations.** DS eq. 15-16 (p. 33) and Table 5 (p. 33):

    K_mid = (f_c / f_0) * (1 / k_FF) = R_C1 / R_FB1
    R_C1 = K_mid * R_FB1;  C_C1 = 2/(w_z1 R_C1);  C_C2 = 1/(w_p2 R_C1)
    C_C3 = 1/(w_z2 R_FB1); R_C2 = 1/(w_p1 C_C3)

**Plant.** Sections 4 and 7:

    f_0   = 1 / (2 pi sqrt(10 uH * 36 uF)) = 8388 Hz
    f_ESR = 1 / (2 pi * 2 mOhm * 36 uF)    = 2.21 MHz

**Placement.** The DS premise (p. 33) is w_z1 = 0.5 w_0, w_z2 = w_0,
w_p1 = w_ESR, w_p2 = w_SW/2. This design follows it for both zeros, so the first
zero sits at half the LC resonance and the second on it, and departs from it in
one place:
- **w_p1 at fsw/2.** The ESR zero (2.21 MHz) is above fsw/2, so placing w_p1 on it
  cancels nothing. w_p1 is placed at fsw/2 = 250 kHz, beside w_p2.

The deck's PID places a double zero on the LC resonance instead (sec. 7). An
earlier draft of this network did the same (C_C1 = 1/(w_0 R_C1), 2.7 nF); it is
not used, because its phase margin fell below the DS's 50-70 deg target at light
load and at the L +20 %, C +22 % corner (loop estimate below).

**Ideal values and E-series picks:**

    K_mid = (30e3 / 8388) / 15 = 0.2384
    R_C1  = 0.2384 * 31.2 k = 7.44 k              -> E96 7.50 k (R3)
    C_C1  = 2 / (2 pi 8388 * 7.44 k) = 5.10 nF    -> E12 5.6 nF C0G (C6)
    C_C2  = 1 / (2 pi 250e3 * 7.44 k) = 85.6 pF   -> E12 82 pF C0G (C7)
    C_C3  = 1 / (2 pi 8388 * 31.2 k) = 608 pF     -> E12 560 pF C0G (C8)
    R_C2  = 1 / (2 pi 250e3 * 560 pF) = 1137 Ohm  -> E96 1.13 k (R4)

Why these neighbours:
- **C_C1.** 4.7 nF is fractionally nearer the ideal by ratio (8.5 % against 9.8 %) and
  would also hold the phase-margin window (54.1-59.8 deg by the same estimate with R10 in the plant; 53.7-59.4 deg
  without it).
  5.6 nF errs toward a lower z1, which adds about 1 deg at every corner.
- **C_C3.** The exact expression includes R_C2: w_z2 = 1/((R_FB1 + R_C2) C_C3) (DS
  Table 3), so the ideal is 586 pF. 560 pF lands 4.8 % above f_0; 680 pF would land
  13 % below.

**Resulting singularities:**
- f_z1 = 1/(2 pi 7.5k 5.6n) = 3.79 kHz
- f_z2 = 1/(2 pi 32.33k 560p) = 8.79 kHz
- f_p1 = 1/(2 pi 1.13k 560p) = 251.5 kHz
- f_p2 = 1/(2 pi 7.5k (5.6n series 82p)) = 262.6 kHz
- K_mid = 7.5/31.2 = 0.2404. Eq. 15 gives f_c = f_0 K_mid k_FF = 30.2 kHz.

**Loop estimate.** The loop was evaluated numerically with a small model that is
not committed; what it contains is stated here so it can be rebuilt:
- the exact op-amp network impedances, including R_FB1 and R_FB2;
- finite error-amplifier gain (94 dB, 6.5 MHz GBW, DS p. 8);
- the LC with R_DAMP = D x R_DS(on)HS + (1 - D)(R_DS(on)LS + R10) + DCR (DS Table 3
  note 2, p. 31), with D = Vout/(VIN x 0.92): 40.4 mOhm at 12 V with R10 in the
  low-side path, 26.4 mOhm without it; ESR 2 mOhm, Ceff 36 uF, L 10 uH and a
  resistive load;
- k_FF = 15.

The one-at-a-time rows below do not model PWM sampling or propagation delay, which
typically cost a few degrees at f_c/f_sw = 0.06; the worst-case search after them
includes a 100 ns loop delay. Phase margin is given for the plant without R10 (the
proposal's) and with it (the shipped design):

| Condition | f_c | PM without R10 | PM with R10 | GM with R10 |
|---|---|---|---|---|
| nominal, 2 A | 31.4 kHz | 59.9 deg | 60.3 deg | 23.5 dB |
| 1 A | 31.5 kHz | 57.3 deg | 57.7 deg | 23.4 dB |
| 0.1 A | 31.6 kHz | 54.9 deg | 55.4 deg | 23.3 dB |
| L -20 % | 38.2 kHz | 59.8 deg | 60.3 deg | 21.6 dB |
| L +20 % | 26.9 kHz | 59.2 deg | 59.6 deg | 25.1 dB |
| Ceff 30 uF | 36.8 kHz | 60.5 deg | 60.9 deg | 21.7 dB |
| Ceff 44 uF | 26.6 kHz | 58.3 deg | 58.8 deg | 25.6 dB |
| L -20 %, Ceff 30 uF | 44.7 kHz | 59.4 deg | 59.8 deg | 19.7 dB |
| L +20 %, Ceff 44 uF | 22.9 kHz | 56.7 deg | 57.3 deg | 27.2 dB |

Crossover lands at about 30 kHz as sec. 7 intends: 31.45 kHz nominal, 23-45 kHz
over the L and C corners. With R10, phase margin is 60.3 deg nominal and
55.4-60.9 deg over every row (59.9 and 54.9-60.5 deg without it), inside the DS
target of 50-70 deg (p. 33), and gain margin is at least 19.7 dB. The double zero
at f_0 (2.7 nF, all else equal, without R10) gave 52.8 deg nominal and
47.6-54.4 deg over the same rows, at the same crossover.

**Worst case over every tolerance extreme (AMB-128).** An exhaustive 2^10 vertex
search over L 8/12 uH, Ceff 27.5/45.5 uF, R_DAMP at its bounds (35.2/41.9 mOhm with
R10, 23.6/26.4 mOhm without), R_C1, R_C2, R_FB1 and R_FB2 at +/-1 %, and C_C1,
C_C2 and C_C3 at +/-5 %, all with a 100 ns loop delay, gives these phase margins:

| Plant | 2 A | 1 A | no load (1 mA) |
|---|---|---|---|
| without R10 | 53.1 deg | 50.05 deg | 46.95 deg |
| **with R10 (shipped)** | **53.6 deg** | **50.50 deg** | **47.40 deg** |
| with R10, resistors at +/-2 % (TCR stacked) | 53.2 deg | 50.12 deg | 47.00 deg |

The worst vertex is L 12 uH, Ceff 45.5 uF, R_DAMP at its minimum, R_C1 -1 %,
C_C1 -5 %, C_C2 +5 %, R_C2 +1 %, C_C3 -5 %, R_FB1 -1 % and R_FB2 -1 %. The worst
case meets the DS target at the benchmark's 1-2 A load (50.5 deg; 50.1 deg with TCR
stacked). At no load in forced PWM, outside the benchmark's load range, it is
47.0-47.4 deg and the loop is still stable. R3, C6, C7, C8 and R4 are therefore
kept as derived above. With the C2 alternate GRM32ER71C226KEA8L (ESR 1.04 mOhm per
pair, Ceff 31.7-45.6 uF) the same search gives 50.1 deg at 1 A (49.7 deg with TCR
stacked), 53.2 deg at 2 A and 47.0 deg at no load.

**Two DS errata** (found in review): Table 3's w_z2 shows R_FB2 where the topology
gives R_FB1, so this design uses (R_FB1 + R_C2), as the C_C3 note above says; and
Table 5's C_C1 = 2/(w_z1 R_C1) has to be read with w_z1 meaning w_0.

**Cross-check against sec. 7.**
- Sec. 7's |Gc(fc)| = 4.4 is defined against the error V_REF - V_FB, with a deck
  modulator gain of 12 (V_IN over a 1 V ramp). The equivalent for the LM25145,
  K_mid (f_c/f_0) / h = 0.24 x 3.6 / 0.242 = 3.5 at k_FF = 15, gives the same product
  (4.4 x 12 = 53 against 3.5 x 15 = 53).
- So the network reproduces the deck's crossover. It is not the deck's PID: the
  deck's KP, KI and KD are unchanged and are not derived from these parts.

### 10.9 PGOOD

PGOOD is open drain and needs a pull-up of at most 13 V, typically 10-100 k
(DS p. 19; p. 7 recommends at most 13 V and 2 mA). Pick: 49.9 k to VOUT (R9). DS
Figure 46 (p. 36) uses 49.9 k too, but pulled up to VCC; VOUT is chosen here for a
3.3 V logic level. With PGOOD low it sinks 3.38/49.9 k = 68 uA, far below the 2 mA
at which PGOOD-low is at most 150 mV (DS p. 8), and the 100 nA high-state leakage
(DS p. 8) drops 5 mV across R9.

Thresholds (DS pp. 8, 19) in VOUT terms, with the 3.296 V set point:
- rising 94 %: 3.098 V
- falling 92 %: 3.032 V
- over-voltage 108 %: 3.560 V, recovery 105 %: 3.461 V
- deglitch: 25 us

Nothing in the benchmark consumes PGOOD. It is included so the open-drain pin is
terminated and observable. Dropping R9 is acceptable; PGOOD then becomes
`isolated`.

### 10.10 SYNCIN and SYNCOUT

- **SYNCIN** is tied directly to VCC: forced PWM (DS p. 26, 8.4.4: "tie SYNCIN to
  VCC either directly or using a pullup resistor"). The deck's switch node is an
  always-synchronous pair that conducts negative inductor current; forced PWM is
  the only mode in which that is the hardware behaviour, and the loop analysis at
  0-0.1 A (sec. 10.8) assumes CCM, which holds only in forced PWM. The deck's 1 A
  minimum load keeps the valley at 0.74 A or more, so the choice moves no deck
  number. V_SYNC-IH is 2 V minimum (DS p. 8) and the SYNCIN absolute maximum 14 V
  (DS p. 6), against VCC's 7.7 V maximum. SYNCIN input resistance is 20 k (DS p. 8),
  so it draws up to 7.7 V / 20 k = 0.39 mA from VCC, already inside the Fig. 11
  I_Q of sec. 10.6.
- **SYNCOUT** is unused.

### 10.11 Assumptions, stated once

1. The 36 uF effective output capacitance, 2 mOhm ESR and 20.4 mOhm DCR are the
   numbers of sections 3 and 4. They are not re-derived here.
2. Q2 R_DS(on) at 7.5 V gate drive is 5.07 mOhm typ at 50 A and about 5.0 mOhm at
   2-3 A, read from typical curves (IFX Diagrams 6 and 8; three independent
   digitisations agree within 0.06 mOhm). Its maximum is an estimate, 6.3-6.4 mOhm
   at 25 C by typ x 5.9/4.7, and the only guaranteed bound is the 8.4 mOhm
   V_GS = 4.5 V maximum. Since AMB-128 the current limit does not depend on it
   (sec. 10.7).
3. **Extraction alignment (closed in AMB-128).** The proposal read DS pp. 7-9
   through a non-layout text extraction whose columns shifted. A layout-preserving
   re-extraction aligns every row: V_EN, I_EN-HYS, V_ILIM-TH (-8 / -2 / +3.5 mV),
   FSW2 and T_ON(MIN) are as stated above. The table header (p. 7, repeated on
   pp. 8-9) makes the min/max limits hold over TJ -40 to 125 C unless a row says
   otherwise, so I_RS and V_ILIM-TH are full-temperature limits and I_RDSON's hold
   at 25 C only.
4. **Tolerances from MPN codes (confirmed).**
   - Murata's code "K" is +/-10 % and "J" is +/-5 % (Murata's capacitance-tolerance
     field). C2 and C3 carry +/-10 % in the Rhoform source on that basis; parts.yaml
     states no tolerance for them.
   - R1 is written at the +/-1 % requirement in the Rhoform source on purpose,
     matching the error stack.
5. **Catalog checks (done in AMB-128).** Every MPN of sections 10 and 11 was checked
   against manufacturer data on 2026-10-22, and the ones the review introduced
   against live Digi-Key stock as well (sec. 12). The proposal's C6 and C9 codes
   (JA01) do not exist and its C11 could not be found; all three are replaced.
   parts.yaml's history (a fabricated R1 MPN shipped for two audit rounds) is the
   reason this matters.
6. **Ground and layout.** There is one ground net. Layout (loop areas, the snubber
   footprint the DS suggests on p. 49, an optional 2-10 Ohm resistor in series with
   C10, p. 49) is out of scope: the DSL carries no placement in v1. The exception
   that has to reach R30 is the current-sense Kelvin routing of sec. 10.7.

## 11. LM25145 pin map (EE-reviewed 2026-10-22, AMB-128)

Source: TI, "LM25145 6-V to 42-V Synchronous Buck DC-DC Controller With Wide
Duty Cycle Range", https://www.ti.com/lit/ds/symlink/lm25145.pdf, 62 pages, revision
history "June 2017, *, Initial release" (p. 2), read 2026-10-22. Page numbers below
are that PDF's printed page numbers. Pin numbers, names and types come from section 6,
"Pin Configuration and Functions" (pp. 4-5). The PDF-to-text extraction used to read
it was checked against the table of contents page by page.

Type column (datasheet footnote, p. 4): P = power, G = ground, I = input, O = output.
"Role" is the T2 lattice role the library definition `rhoform.lib.regulator.Lm25145`
declares in `rhoform/lib/regulator.rhoform`, which the source takes its pins from
(`lang/grammar/rhoform_syntax.py` CLOSED_VOCABULARIES pin_role). "Rhoform pin" is the
datasheet name with `/` written `_`, because a pin name must be an identifier.

| Pin | Datasheet name | Type | Function (datasheet, condensed) | Rhoform pin | Role | Connection in this design | Net |
|---|---|---|---|---|---|---|---|
| 1 | EN/UVLO | I | Enable and UVLO programming. Below 0.4 V shutdown; 0.4-1.2 V standby; above 1.2 V switching. A 10 uA source turns on above 1.2 V for hysteresis (p. 4) | EN_UVLO | input | Midpoint of R6 (100 k, to VIN) and R7 (16.9 k, to GND): on at about 8.30 V, off at about 7.30 V | EN |
| 2 | RT | I | Oscillator frequency resistor to AGND. Required even when SYNCIN is clocked (p. 4) | RT | input | R5 20.0 k to GND (500 kHz) | RT |
| 3 | SS/TRK | I | Soft-start capacitor, charged by 10 uA; tracking input. Minimum 2.2 nF to AGND (p. 4) | SS_TRK | input | C9 6.8 nF C0G to GND (about 544 us) | SS |
| 4 | COMP | O | Error amplifier output. The compensation network goes between COMP and FB (p. 4) | COMP | output | CN1: R3 (7.50 k) in series with C6 (5.6 nF) to FB, and C7 (82 pF) to FB | COMP |
| 5 | FB | I | Inverting error amplifier input, regulates to 0.8 V (p. 4) | FB | input | R1/R2 divider midpoint; C6, C7, and C8 (560 pF, in series with R4 1.13 k from VOUT) | FB |
| 6 | AGND | P | Analog ground, return for the 0.8 V reference (p. 5) | AGND | power_in | Ground plane (single GND net) | GND |
| 7 | SYNCOUT | O | Clock output 180 degrees out of phase with HO (p. 5) | SYNCOUT | output | Unused. Declared `isolated u1.SYNCOUT` | (isolated) |
| 8 | SYNCIN | I | Clock input; logic low or floating enables diode emulation, logic high forces PWM (pp. 5, 26) | SYNCIN | input | Tied directly to VCC: forced PWM, matching the deck's always-synchronous switch model (p. 26: "tie SYNCIN to VCC either directly or using a pullup resistor") | VCC |
| 9 | NC | - | No electrical connection (p. 5) | NC9 | nc | Not connected in the netlist | - |
| 10 | PGOOD | O | Open-drain power-good output; pull-up to at most 13 V, typically 10-100 k (pp. 5, 19) | PGOOD | open_drain | R9 49.9 k pull-up to VOUT | PGOOD |
| 11 | ILIM | I | Valley current-limit resistor; its other end goes to the low-side FET drain (SW) in RDS(on) mode or to the shunt at the FET source in RSENSE mode (pp. 5, 23) | ILIM | input | RSENSE mode: R8 634 ohm to net ISNS (Q2 source and the top of R10, by Kelvin trace); C12 82 pF to GND (PGND) | ILIM |
| 12 | PGND | P | Low-side driver power ground; connect directly to the low-side FET source or the ground side of a shunt resistor (p. 5) | PGND | power_in | Ground plane (single GND net), at R10's ground-side pad | GND |
| 13 | LO | P | Low-side gate drive output (p. 5) | LO | output | Q2 gate | LO |
| 14 | VCC | O | 7.5 V bias regulator output; decouple locally to PGND (p. 5) | VCC | power_out | C11 2.2 uF (0805) to GND; also feeds SYNCIN | VCC |
| 15 | EP | - | Pin internally connected to the exposed pad; electrically isolated (p. 5) | EP (with pad 21) | passive | Ground plane | GND |
| 16 | NC | - | No electrical connection (p. 5) | NC16 | nc | Not connected in the netlist | - |
| 17 | BST | O | Bootstrap supply for the high-side driver; connect to the bootstrap capacitor (p. 5) | BST | power_out | C10 100 nF to SW | HB |
| 18 | HO | P | High-side gate drive output (p. 5) | HO | output | Q1 gate | HO |
| 19 | SW | P | Switch node; bootstrap capacitor, high-side source, low-side drain (p. 5) | SW | passive | Q1 source, Q2 drain, L1, C10 | SW |
| 20 | VIN | P | Supply input for the VCC LDO (p. 5) | VIN | power_in | Input rail; C3 100 nF local bypass | VIN |
| pad | Exposed pad | - | "Electrically isolated. Solder to the system ground plane to reduce thermal resistance." (p. 5); p. 4: "Connect Exposed Pad on bottom to AGND and PGND on the PCB." | EP (designator 21) | passive | Ground plane | GND |

### Decisions and assumptions in this map

1. **The datasheet calls the bootstrap pin BST, not HB.** The bootstrap net is
   named `HB`, and it joins `u1.BST` to C10.
2. **There is no VDDA pin on the LM25145.** Its 20 pins are listed above; the only bias
   rail is VCC, so "VCC/VDDA decoupling" reduces to the VCC capacitor (C11). A VDDA
   pin exists on other TI controllers, not on this one.
3. **Exposed-pad designator 21.** The pin table does not number the exposed pad; it
   is row "-" (p. 5). Pin 15 (EP) is "internally connected to exposed pad", so the
   library definition `Lm25145` declares one pin `EP` with designators `15 21`. TI's RGY0020B package
   drawing 4222860/B (DS pp. 55-57) numbers the 1.7 x 2.7 mm thermal pad 21, so the
   number is the drawing's. The KiCad footprint that R30 eventually binds must be
   that RGY0020B land pattern.
4. **Two NC pins, two ports.** Pins 9 and 16 are separate pads with no internal
   connection, so they are separate `nc` ports (`NC9`, `NC16`). One port carrying
   both designators would claim the two pads are one node. The layout guidance
   (11.1.4, p. 50) suggests tying them to the thermal land with copper for heat
   spreading; that is a layout decision and is not in the netlist.
5. **Roles where the datasheet type is P.**
   - AGND and PGND are `power_in`, matching the bake-off library's ground pins.
   - LO and HO are `output`: they drive gates, and the gates are declared `input`.
   - SW is `passive`, not `power_in`. Its net has no power source of its own; it is
     driven by the FETs, which are passive. `power_in` there would make a T2 driver
     check demand a `power_out` that no part provides.
   - VIN is `power_in`.
   - BST is `power_out`. The datasheet types it O: the integrated diode charges C10
     from it.
   - EP is `passive`. It is electrically isolated from the die circuits and soldered
     to ground.
6. **AGND and PGND share one net.** The datasheet's layout guidance (11.1.5, p. 50)
   puts PGND, and the exposed pad under it, on the system ground plane, and
   p. 4 connects the exposed pad to both AGND and PGND. There is no split ground, so
   no section 8-Q6 net tie is needed. PGND does have to reach that plane at R10's
   ground-side pad (p. 5, pin 12; sec. 10.7), a Kelvin connection v0.1 cannot spell;
   electrically the single GND net is correct.
7. **Unused functions.**
   - SYNCOUT: driven, unused, declared `isolated`.
   - Tracking: SS/TRK carries only the soft-start capacitor.
   - External VCC bias (Figure 32, p. 18): not used. At 14 V maximum input the LDO
     dissipates about 74 mW and the whole IC at most 155 mW (sec. 10.6).

### MOSFET pinout (Q1, Q2)

Infineon BSC059N04LS6 (orderable OPN BSC059N04LS6ATMA1), datasheet rev. 2.1
(2020-07-22), p. 1 pin diagram: S = 1, 2, 3; G = 4; D = 5, 6, 7, 8. The package on
p. 1 is "PG-TDSON-8 FL" (enlarged source interconnection); parts.yaml and the
Rhoform source write "PG-TDSON-8 FL (SuperSO8 5x6)". IFX p. 11, Fig. 2 (the
TDSON-8 fused-lead board pads) shows how it differs from a standard SuperSO8:
source pins 1-3 merge into one 3.20 mm land, gate pin 4 has its own pad, and the
drain pad with leads 5-8 is as on any SuperSO8, the large pad sharing the D
designators. R30 must bind that TDSON-8 FL footprint, not a SuperSO8 footprint with
three separate source pads. Roles: d passive, s passive, g input.

| Instance | d (5-8) | g (4) | s (1-3) |
|---|---|---|---|
| q1 (high side) | VIN | HO | SW |
| q2 (low side) | SW | LO | ISNS (R10 to GND) |

### Inductor

Coilcraft XGL6060-103ME (CC 1621-2 part table), two terminals `a` and `b` from the
library's generic `Inductor`, which carries no pad numbers (they belong to the
footprint: pads 1 and 2). l1.a is on SW and l1.b is on VOUT. The inductor is electrically
unpolarised but marked for EMI: the CC 1621-1 drawing marks the start (short) lead
and says "Connect high dv/dt here for lowest EMI". So l1.a, the SW end, must be
the marked start-lead pad, and the footprint R30 binds has to carry that marking.

## 12. EE review (AMB-128, 2026-10-22)

The EE review delegated in AMB-128 decided the items below on 2026-10-22 for the
proposal of sections 10 and 11 (b45d168, d04d775). Each decision is final; its derivation
is in the section named.

| ID | Decision | Derivation (summary) | Sources |
|---|---|---|---|
| A1 | Current limit in R_SENSE mode: R10 20 mOhm (WSLP1206R0200FEA) from the Q2 source to GND; R8 66.5 -> 634 Ohm (RC0402FR-07634RL) from ILIM to the top of R10 by Kelvin trace; C12 82 pF kept; PGND at R10's ground side | R_DS(on) mode fails one corner or the other for every R8, even at 25 C. 20 m / 634 is the only per-R_S optimum with at least 10 % on both margins: trip 2.545-4.035 A against the required 2.30-4.635 A; sustained-overload peak 4.90 A against 5.5 A; overload- and short-onset peaks about 6.4 A (14 V) and 7.2 A (short) for one or a few pulses (sec. 3, 10.7) | DS pp. 5, 6, 9, 23-25, 31, 50 (eq. 6, Figs. 39-41, sec. 8.3.11); WSLP pp. 1-3; CC 1621-2 |
| A1-deck | netlist.cir carries R10 as `RSNS` = 20m in Bsw's off-time branch; check-assertions.py pins RSNS to R10 and requires it | Fresh runs: eff 92.114 % (>= 85 %), ripple 3.657 mVpp (<= 50 mV), settling 17.01 us (<= 500 us), overshoot 0.0476 % (<= 5 %); the PFIX ceiling falls from 1.056 to 0.998 W (sec. 6, 9) | validation.log, validation-corners.log |
| A2 | Keep EN/UVLO; R6 100 k; R7 16.5 -> 16.9 k (RC0402FR-0716K9L) | 16.5 k turns on as late as 9.03 V; 16.9 k turns on at 8.30 V (7.78-8.85 V) and off at 7.30 V (6.70-7.93 V), hysteresis at least 0.88 V (sec. 10.5) | DS pp. 6-8, 18-19 (eqs. 1-2, Fig. 33) |
| A3 | C6 = 5.6 nF and the rest of CN1 unchanged | 60.3 deg nominal with R10's damping; over every tolerance extreme with a 100 ns delay, 53.6 / 50.5 / 47.4 deg at 2 A / 1 A / no load (sec. 10.8) | DS pp. 8-9, 31-33 (Tables 3-5, eqs. 15-16) |
| A4 | SYNCIN tied directly to VCC (forced PWM) | The only mode matching the deck's always-synchronous switch; I_VCC about 11.1 mA, IC at most 155 mW (sec. 10.6, 10.10) | DS pp. 6-8, 11-12 (Fig. 11), 26; IFX Diagram 14, Table 6 |
| A5 | R9 49.9 k to VOUT | 68 uA with PGOOD low; DS Fig. 46 pulls up to VCC, VOUT is chosen for 3.3 V logic (sec. 10.9) | DS pp. 7-8, 19, 36 |
| A6 | C11 -> Murata GRM21BR71E225KE11L, 0805 | Worst case 1.15 uF (at least 1 uF), at most 2.42 uF (at most 5 uF); the 0603 class reaches only 0.885 uF; the TDK part is not listed (sec. 10.4) | DS pp. 7, 17; Murata EC data |
| A7 | C6 -> GRM1555C1H562JE01D, C9 -> GRM1555C1H682JE01D | The JA01 codes do not exist; values unchanged, same 0402 land | Murata product data |
| A7-L | C3 -> GCM188R71H104KA57D; C1 and C2 keep their NRND primaries with recorded alternates; C1's old alternate struck | C3's part was "To be discontinued"; promoting C2's alternate would re-pin CEFF and RESR (its own issue); GRM31CR71E106KA12L loses 65 % at 14 V (sec. 4, parts.yaml) | Murata data; Digi-Key, 2026-10-22 |
| B-1 | Q1/Q2 R_DS(on) at 7.5 V: 5.07 mOhm typ, an estimated 6.3-6.4 mOhm max; Diagram 9 factors 0.81 (-40 C) and 1.51 (125 C); deck RON = 6 m kept | Three digitisations agree within 0.06 mOhm (sec. 5, 10.6) | IFX Table 4, Diagrams 6, 8, 9 |
| B-2 | Exposed pad = 21; FETs S 1-3 on a fused source land, G 4, D 5-8 | Vendor package drawings; "assumption" wording removed (sec. 11) | DS pp. 55-57 (RGY0020B, 4222860/B); IFX pp. 1, 11 |
| B-3 | f_sw 463-532 kHz worst case (497 kHz typ), not 475-525 | IC +/-5 %, eq. 3's curvature, R5 +/-2 % (sec. 10.1) | DS pp. 8, 20 |
| B-4 | L1's marked start lead goes on SW | CC Document 1621-2 rev 02/19/26 confirmed (sec. 11) | CC 1621-1, 1621-2 |
| B-5 | Q1/Q2 MPN -> BSC059N04LS6ATMA1, package "PG-TDSON-8 FL (SuperSO8 5x6)" | The orderable OPN, active | IFX p. 1; Digi-Key 9829538 |
| B-6 | Murata K = +/-10 %, J = +/-5 % | R1 stays +/-1 % in the source by design (sec. 10.11) | Murata data |
| T-ON | T_ON(MIN) is 40 ns typ / 60 ns max | Required on-time at least 431 ns, 7.2x; the extraction-alignment question is closed (sec. 2, 10.6, 10.11) | DS p. 9 |
| SUP | C9 6.8 nF, C10 100 nF and R5 20.0 k unchanged | t_SS 426-679 us; BST droop 106 mV against 3.0 V (sec. 10.1-10.3) | DS pp. 4, 7-9, 20-21, 23; IFX Diagram 14 |
| D | DSL items out of scope | Listed below | - |

**Documents.** Vendor files are not committed; each is identified by its digest.

| Document | Number, revision | URL | sha256 |
|---|---|---|---|
| TI LM25145 data sheet | SNVSAT9 rev * (June 2017); product page read 2026-10-22: Active | https://www.ti.com/lit/ds/symlink/lm25145.pdf | e485439876b4dfc56ea30e3a0d8eb7ee84e6ffe64a17b98a0bd11e0c9a242975 |
| Infineon BSC059N04LS6 data sheet | Rev. 2.1, 2020-07-22 | https://www.infineon.com/assets/row/public/documents/24/49/infineon-bsc059n04ls6-datasheet-en.pdf | cff6fe428cffd411ce188368185745172d91557b1a8f39f428e33a5d59801629 |
| Coilcraft XGL6060 data sheet | Documents 1621-1 to 1621-4, revised 02/19/26 | https://www.coilcraft.com/getmedia/329fe97c-7311-4726-9bf3-37718f42b168/xgl6060.pdf | ac31402b202cb110237dedf38bc057e5f7e84f965aeaadd2dfe24e7a92bf127b |
| Vishay WSLP data sheet | Document 30122, rev. 09-Sep-2024 | https://www.vishay.com/docs/30122/wslp.pdf | d3dd7b4f590e713c84303e32530e8c8c6fd025617896e11d25599521771e4c13 |
| Yageo RC0402FR-07634RL spec sheet | generated 2026-10-22 | https://yageogroup.com/component-documentation/download/specsheet/RC0402FR-07634RL | 5b5a0915ee2b804d2dbc471b9f6976a26906a7d48666575ebeb910dd54f46298 |
| Yageo RC0402FR-0716K9L spec sheet | generated 2026-10-22 | https://yageogroup.com/component-documentation/download/specsheet/RC0402FR-0716K9L | 05cef50878ab594d29a59ff5eaff251f69887527a6fe022d5dac6112b84019b1 |

Murata DC-bias, ESR, temperature-rise and existence data came from Murata's
product-data service and EC-data sheets. Digi-Key, read 2026-10-22:
WSLP1206R0200FEA (1883281) Active, 343,192 in stock; RC0402FR-07634RL (5281063)
Active, 273,878; RC0402FR-0716K9L (5280863) Active, 102; GRM21BR71E225KE11L
(6606096) Active, 775,498; GCM188R71H104KA57D (1641653) Active, 1,821,403;
GRM32ER61C226KE20L (586553) Not For New Designs, 216,804; GRM32DR71E106KA12L
(586590) Not For New Designs, 257,636; GRM32ER71C226KEA8L (3465249) Active, 0
(17-week lead time); GRM32ER71E226KE15L (2039040) Active, 0 (21-week lead time).

**Residual risks** (recorded in AMB-128; none changes a decision): the overload-
and short-onset peaks of sec. 10.7, whose number of wide pulses the DS does not
bound; XGL6060 Isat temperature derating, which is unquantified; ILIM comparator
propagation delay, which is unspecified; the 0.1 A spread in the low-side valley
requirement between the two loop models; and the Kelvin layout, which is
mandatory.

**Out of scope (D, the DSL).** No `power_out` on VIN or GND, because there is no
input connector (if one is added, rate it at least 3 A: about 1.9 A input at OCP,
9 V); no voltage domain for SW, HB, HO and ISNS; no `nC` unit, typ/max interval for
DCR, or spelling for the efficiency probe, measurement windows and
`informational_at_rung_0` flags; passive pin designators against decision E-5; the
undefined library names `rhoform.lib.regulator.Lm25145` and
`rhoform.lib.semiconductor.Nmos`; and no net-tie or Kelvin spelling for R10, where
one GND net is electrically correct. Statement order is now held by `rhoform fmt`.

*Note added with syntax 0.2 (2026-10-22):* two of those DSL items are now handled. The
bundled library defines `rhoform.lib.regulator.Lm25145` and
`rhoform.lib.semiconductor.Nmos`, and generic passives carry no pad designators
(decision E-5), so the source takes every pin from the library.
