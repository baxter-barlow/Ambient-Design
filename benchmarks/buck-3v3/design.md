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

Peak current and saturation margin. The steady-state peak follows from the
measured worst-case ripple, but it is NOT the deck's highest current: the
1 A -> 2 A load step at 1.5 ms -- the transient `load_step_settling` gates --
overshoots it, and that transient peak is what the magnetics actually see.

    Ipk(steady state) = Iout + DIL/2 = 2.0 + 0.5119/2 = 2.256 A
    Ipk(load step)    = max i(Vsns) over 1.45-1.7 ms  = 2.534 A

This document published the 2.256 A figure as "worst case" and derived its
saturation margin from it, 12% optimistic in the unsafe direction (round
21). The margins below are the transient ones.

Part: **Coilcraft XGL6060-103MEC** (10 uH +/-20%, DCR 18.5 mOhm typ /
20.4 mOhm max, Isat 3.6 A at 10% inductance drop / 5.5 A at 20% / 7.3 A at
30%, Irms 7.3 A for 20 C rise / 10.0 A for 40 C rise; Coilcraft datasheet
Document 1621-2, rev. 02/19/26). Saturation margin against the strictest
rating point, at the measured transient peak: 3.6/2.534 = **1.42x** at the
10%-drop Isat, 5.5/2.534 = 2.17x at the 20%-drop rating. (Against the
steady-state peak alone they would read 1.6x and 2.4x.) A 100% overload
transient (4.534 A) stays below the 5.5 A 20%-drop rating -- soft-saturating composite core, so inductance sags
gracefully rather than collapsing. RMS heating: Irms ~= 2.0 A vs 7.3 A
(20 C rise) rating. The BOM records L at +/-20%: at the -20% corner (8 uH)
the ripple scales by 1/0.8 to 0.640 App, the computed steady-state Ipk
rises to 2.32 A and the measured load-step peak to 2.566 A, and the margins
become 3.6/2.566 = 1.40x (10%-drop Isat) and 5.5/2.566 = 2.14x -- the
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
- Current: continuous Id rating tens of amps vs the 2.534 A load-step peak.
- Conduction loss at 2 A, 12 V (D' = 0.30):
  - HS: I^2 x Ron x D'     = 4 x 0.0059 x 0.30 = 7.1 mW
  - LS: I^2 x Ron x (1-D') = 4 x 0.0059 x 0.70 = 16.5 mW

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
Design: crossover fc = 30 kHz (about fsw/17; a previous revision printed
"fsw/16", which is 31.25 kHz -- every downstream number is computed from
30 kHz and is unaffected). The deck's PID below places a double zero on the
LC resonance. The LM25145's Type-III network (sec. 10.8) does not: it takes
the datasheet's placement, first zero at f0/2 and second at f0, which keeps
the estimated phase margin at 54.9-60.5 deg over every load and L/C corner,
inside the datasheet's 50-70 deg target; the double zero fell to 47.6 deg.
Both cross over at about 30 kHz.
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
1.42x margin to even the strictest 10%-drop Isat rating instead). Those
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
1.117 ms) against `vmax_late 3.29751`, 0.022 mV -- the .meas difference,
2.21932e+01 uV, not the difference of the two six-figure printouts, which
rounds to 0.03 mV and is the figure this sentence used to publish. The
reported figure is half the peak-to-peak ripple over the mean; it would
report nearly the same
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

None of the engineering conclusions move across the sweep: steady-state
`Ipk` 2.256 A, saturation margin 1.42x at the measured load-step peak, ripple margin 13.9x, efficiency 0.92864 (invariant to
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

## 10. Component-level design (PROPOSAL, EE review required, AMB-128)

Sections 1-9 size the power stage and the deck. This section derives, with a
citation for every value, the parts the BOM used to leave unstated: the
bootstrap capacitor, the RT resistor, the SS capacitor, the Type-III network's
values (once "chosen at layout time"), and what the LM25145 pin map (sec. 11)
turns out to need. Every part here is a proposal awaiting EE review in AMB-128;
none of the numbers the gates pin (netlist.cir, assertions.yaml, the validation
logs, the tables in sections 1-9) depends on it. The living source
`buck-3v3.rhoform` declares these parts, pins and nets.

### 10.0 Sources and fixed inputs

**LM25145 datasheet.** https://www.ti.com/lit/ds/symlink/lm25145.pdf, revision "*"
(June 2017, p. 2), 62 pages. It is cited as "DS p. N, eq. N / Table N / section".

**BSC059N04LS6 datasheet.** Infineon, rev. 2.1 (2020-07-22),
https://www.infineon.com/assets/row/public/documents/24/49/infineon-bsc059n04ls6-datasheet-en.pdf.
It is cited as "IFX p. N, Table/Diagram N". Page mapping:
- p. 1: key parameters and pinout
- p. 4: static, dynamic and gate-charge tables
- p. 7: Diagrams 5-8
- p. 8: Diagrams 9-12
- p. 9: Diagrams 13-15

**XGL6060 datasheet.** Coilcraft,
https://www.coilcraft.com/getmedia/329fe97c-7311-4726-9bf3-37718f42b168/xgl6060.pdf.
It is cited as "CC p. 2" (the part table). The extracted text carries no document
number or revision, so the "Document 1621-2 rev 02/19/26" that sec. 3 and
parts.yaml cite was not confirmed from it.

**Fixed by sections 1-9 and parts.yaml (not changed here):**
- Vin 9-14 V (12 V nominal), Vout 3.3 V at 2 A, fsw = 500 kHz.
- L = 10 uH, effective Cout 36 uF, net ESR 2 mOhm, DCR 20.4 mOhm max.
- f0 = 8.4 kHz, fc target about 30 kHz, soft-start about 500 us.
- R1 = 31.2 k (R_FB1 below), R2 = 10.0 k (R_FB2).
- the MPNs of U1, Q1, Q2, L1, C1, C2, C3, R1, R2.

Datasheet text was read through a PDF-to-text extraction. Table rows on DS pp. 8-9
come out with shifted columns in places; where that matters it is said so below.

### 10.1 RT: switching frequency

DS p. 20, eq. 3: `R_RT[kOhm] = 10^4 / F_SW[kHz]`. The 500 kHz row of DS Table 1
(p. 20) is 20 kOhm.

    R_RT = 10^4 / 500 = 20.0 kOhm   -> E96 20.0 k, 1 %, 0402 (R5)

The datasheet gives oscillator accuracy only at R_RT = 25 k: 380 kHz min and 400 kHz
typ (DS p. 8; the maximum did not survive extraction). Assuming the same relative
spread at 20 k, fsw is roughly 475-525 kHz. That moves f0/fc ratios by nothing
(f0 does not depend on fsw) and the inductor ripple by +/-5 %.

### 10.2 Soft-start capacitor

DS p. 21, eq. 4 and eq. 5:

    t_SS = C_SS * V_REF / I_SS;    C_SS[nF] = 12.5 * t_SS[ms]

For the about 500 us that sec. 7 states:

    C_SS = 12.5 * 0.5 = 6.25 nF   -> E12 6.8 nF C0G, 0402 (C9)
    t_SS = 6.8 nF * 0.8 V / 10 uA = 544 us

E12 neighbour 5.6 nF gives 448 us. 6.8 nF is the nearer of the two: 44 us against
52 us.

Spread, with I_SS 8.5-12 uA (DS p. 8) and C at +/-5 %: 431-672 us. That is above the
DS minimum of 2.2 nF (DS p. 4) and the more than 2 nF the SS clamp needs (DS p. 21).
C0G is chosen for a ramp that does not move with bias or temperature; X7R would also
work.

**The deck's ramp is an idealisation of this.** Its PWL reference rises over
100-600 us. With the UVLO divider of sec. 10.5 and the fixture's 0-12 V input
ramp, EN would rise at about 162 us and SS complete at about 706 us. The
startup_overshoot windows (0-1.4 ms and 1.3-1.5 ms) contain either ramp, and the
deck is not changed.

### 10.3 Bootstrap capacitor (BST to SW)

DS p. 23 (8.3.9): "Connect a 0.1-uF or larger ceramic capacitor close to the BST and
SW pins." Check:

- **Charge per cycle.** Q_g at V_GS = 7.5 V is about 7 nC (IFX p. 9, Diagram 14:
  7.5 V is reached between about 6.4 nC at V_DD = 8 V and about 7.4 nC at
  V_DD = 20 V). Add I_Q-BST of 80 uA x 2 us = 0.16 nC (DS p. 9).

      dV_BST = 7.2 nC / 100 nF = 72 mV per cycle

- **Headroom.** dV_BST is far inside the headroom between VCC minus the boot-diode
  drop (7.5 - 0.9 V max, DS p. 9) and the 3.4 V BST-SW UV threshold (DS p. 9).
- **Rating.** BST-SW stays at or below 14 V absolute (DS p. 6), so the capacitor is
  rated 25 V.

Pick: 100 nF, X7R, 25 V, 0402 (C10).

### 10.4 VCC decoupling and VIN bypass

DS p. 17 (8.3.3): "Connect a ceramic decoupling capacitor between 1 uF and 5 uF from
VCC to AGND". DS p. 5 (pin 14) says to decouple to PGND; the two grounds are one net
here. All three DS application circuits use 2.2 uF: Figure 46 on p. 36, Figure 32 on
p. 18.

    C_VCC = 2.2 uF, X7R, 25 V, 0603 (C11)

- **Rating.** VCC is 7.5 V nominal and 14 V absolute (DS pp. 6, 7).
- **Ratio to C10.** C11/C10 = 22.
- **DC bias.** A 0603 2.2 uF X7R loses a large fraction of its capacitance at 7.5 V
  DC. The effective value must stay at or above 1 uF, and the EE should check that
  on the TDK DC-bias curve. If it does not hold, use 0805.

**There is no VDDA pin on the LM25145.** See sec. 11, decision 2.

VIN pin bypass: parts.yaml already carries C3, 100 nF at U1 VIN. DS Figure 32
(p. 18) and Figure 46 (p. 36) show C_VIN = 0.1 uF. The DS's optional 4.7 Ohm series
filter for high-voltage use (p. 17) is not needed at 14 V maximum.

### 10.5 EN/UVLO divider

**Is it needed?** Not for function. DS p. 18 lists EN tied to VIN as "the simplest
way". It is proposed for three reasons:

1. VCC regulation (7.3-7.7 V) is specified only for 9 V <= VIN <= 42 V (DS p. 7).
   Below about 7.75 V the LDO drops out and the gate drive falls (DS p. 18,
   8.3.3).
2. Starting at about 5 V input (the VCC UV point, 4.93 V, DS p. 7) would let the
   converter draw about 1.2 A at 6 V input. That is outside the 9-14 V range the
   benchmark specifies.
3. A defined UVLO is buildability hygiene.

DS p. 18, eqs. 1-2, with I_HYS = 10 uA and V_EN = 1.2 V (DS p. 8). Targets: on 8.5 V,
off 7.5 V, both below the 9 V minimum. Off is set where VCC is still about 7.25 V.

    R_UV1 = (V_on - V_off) / I_HYS = 1.0 V / 10 uA = 100 kOhm    -> E96 100 k (R6)
    R_UV2 = R_UV1 * V_EN / (V_on - V_EN) = 100k * 1.2 / 7.3 = 16.44 k -> E96 16.5 k (R7)
    V_on  = 1.2 * (1 + 100/16.5) = 8.47 V;   V_off = V_on - 10 uA * 100 k = 7.47 V

Tolerance: V_EN 1.164-1.236 V and I_HYS 9-11 uA (DS p. 8, columns shifted in the
extraction), with resistors at 1 %:
- V_on is 8.08-8.88 V and V_off is 6.97-7.99 V. Both stay below 9 V.
- EN at 14 V input is 2.12 V. The absolute maximum is 45 V (DS p. 6).
- The divider draws 103 uA at 12 V.

### 10.6 Gate drive and bias budget (check, no part)

- **VCC current.** I_VCC is about 2 x 7 nC x 500 kHz + 1.8 mA (I_Q, DS p. 7), which is
  8.8 mA. The VCC current limit is 40 mA minimum (DS p. 18).
- **LDO dissipation at 14 V.** (14 - 7.5) x 8.8 mA = 57 mW, which is about 2 C rise at
  36.8 C/W (DS p. 7).
- **On-resistance at 7.5 V drive.** The FETs are driven at 7.5 V, not the 10 V their
  R_DS(on) max is specified at. Typical at 7.5 V, 25 C is 4.8 mOhm (IFX p. 7,
  Diagram 8), against 4.7 typ / 5.9 max at 10 V (IFX p. 4, Table 4). No maximum is
  given at 7.5 V. Scaling max/typ gives about 6.0 mOhm, which equals the deck's
  RON = 6 m to within 0.5 %. This is an open EE-review question (AMB-128).
- **Timing.**
  - Minimum on-time at 14 V: 0.236 x 2 us = 472 ns, against 60 ns max as
    extracted (DS p. 9; sec. 2 quotes 40 ns, and T_ON(MIN) is one of the rows the
    extraction shifts, sec. 10.11 item 3).
  - Minimum off-time at 9 V: about 0.6 x 2 us = 1.2 us, against 200 ns max.

### 10.7 Current limit (ILIM, R_DS(on) sensing on Q2)

DS p. 23-24, eq. 6, in R_DS(on) mode:

    R_ILIM = (I_OUT(OCP) - dI_L/2) / I_RDSON * R_DS(on)Q2

- **I_RDSON.** 200 uA at 27 C (DS p. 23), 180-220 uA at 25 C (DS p. 9), with a
  +4500 ppm/C tempco.
- **R_DS(on) value.** The DS examples use "typical at TJ = 25 C and VGS = 7.5 V"
  (DS p. 37, p. 41). That is 4.8 mOhm (IFX p. 7, Diagram 8).
- **Ripple.** dI_L at 12 V is 0.479 A (sec. 3).
- **Setpoint.** I_OUT(OCP) = 3.0 A, 1.5 x rated. The DS examples sit at 1.3-1.4 x
  (26 A for 20 A, p. 37; 11 A for 8 A, p. 41). More is used here to clear the
  2.534 A load-step peak that sec. 3 measures. At this setpoint the
  nominal peak inductor current at the limit is about 2.77 + 0.50 = 3.27 A at 14 V.
  That is below the strictest Isat of 3.6 A at 10 % drop (CC p. 2).

        R_ILIM = (3.0 - 0.24) / 200e-6 * 4.8e-3 = 66.3 Ohm   -> E96 66.5 Ohm, 1 % (R8)
        valley trip (eq. 6 form) = 200 uA * 66.5 / 4.8 mOhm = 2.77 A

- **C_ILIM.** DS p. 24: "Choose this capacitance such that the time constant
  R_ILIM * C_ILIM is approximately 6 ns." 6 ns / 66.5 Ohm = 90 pF, so E12 82 pF C0G
  50 V (C12), giving 5.5 ns. C_ILIM goes from ILIM to PGND; R_ILIM goes from ILIM to
  SW (DS p. 50, layout item 4). C12 sees up to VIN plus ringing, hence 50 V.

**Tolerance stack (the reason this section needs EE attention).** Eq. 6 omits the
ILIM comparator threshold. DS p. 9 gives V_ILIM-TH as -8 / -2 / 3.5 mV
(min/typ/max as extracted). At this design's sense level (2.77 A x 4.8 mOhm, which is
13 mV) that offset is the same order as the signal. The trip is
I = (I_RDSON x R_ILIM - V_TH) / R_DS(on):

| Case | I_RDSON | R_DS(on) | V_TH | Valley trip |
|---|---|---|---|---|
| eq. 6 nominal | 200 uA | 4.8 m | 0 | 2.77 A |
| typical incl. V_TH typ | 200 uA | 4.8 m | -2 mV | 3.19 A |
| low corner, 25 C | 180 uA | 6.0 m (est. max) | +3.5 mV | 1.41 A |
| low corner, -40 C | 180 uA x 0.71 | 6.0 m x 0.85 | +3.5 mV | 0.98 A |
| high corner, 25 C | 220 uA | 4.8 m | -8 mV | 4.71 A |
| high corner, 125 C | 220 uA x 1.45 | 4.8 m x 1.26 | -8 mV | 4.85 A |

- **Temperature factors.** The R_DS(on) factors come from IFX p. 8, Diagram 9. The
  I_RDSON factors are the +4500 ppm/C tempco.
- **Normal-operation valley currents.** Up to 1.83 A in steady state (9 V input,
  L +20 %). About 2.06 A in the 1 A to 2 A load-step cycle (2.534 A peak minus one
  off-time ramp of 0.479 A).
- **The stack.** Stacked worst case, the low corner can trip in normal operation. The
  high corner lets the peak reach about 5.4-5.5 A, which is the 20 %-drop Isat.
- **Choice of R8.** No E96 value satisfies both corners at once. Raising R8 to
  90.9 Ohm puts the 25 C low corner at 2.1 A, but the high corner then reaches
  about 6.5 A peak.
- **Alternative.** The datasheet itself points to shunt sensing at low output
  current (DS p. 24: "typically implemented at lower output current levels to provide
  accurate overcurrent protection"). R_SENSE mode uses I_RS 100 uA +/-10 %, zero
  tempco (DS p. 9).

The proposal follows the DS procedure: R_DS(on) mode at 66.5 Ohm. Whether to move
to shunt sensing is the first open EE-review question (AMB-128).

**Temperature mismatch.** I_RDSON's +4500 ppm/C over-compensates this FET. Its
R_DS(on) rises about +2500 ppm/C (IFX p. 8, Diagram 9: 0.97 at 20 C to 1.22 at
120 C), so the trip current climbs about 13 % by 100 C.

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
  would also hold the phase-margin window (53.7-59.4 deg by the same estimate).
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
- the exact op-amp network impedances, including R_FB2;
- finite error-amplifier gain (94 dB, 6.5 MHz GBW, DS p. 8);
- the LC with R_DAMP = R_DS(on) + DCR = 26.3 mOhm (DS Table 3 footnote 2), ESR, and
  a resistive load;
- k_FF = 15.

It does not model PWM sampling or propagation delay, which typically cost a few
degrees at f_c/f_sw = 0.06.

| Condition | f_c | Phase margin | Gain margin |
|---|---|---|---|
| nominal, 2 A | 31.5 kHz | 59.9 deg | 23.5 dB at 231 kHz |
| 1 A | 31.6 kHz | 57.3 deg | 23.4 dB |
| 0.1 A | 31.6 kHz | 54.9 deg | 23.3 dB |
| L -20 % | 38.2 kHz | 59.8 deg | 21.5 dB |
| L +20 % | 27.0 kHz | 59.2 deg | 25.1 dB |
| Ceff 30 uF | 36.8 kHz | 60.5 deg | 21.7 dB |
| Ceff 44 uF | 26.6 kHz | 58.3 deg | 25.6 dB |
| L -20 %, Ceff 30 uF | 44.8 kHz | 59.4 deg | 19.7 dB |
| L +20 %, Ceff 44 uF | 22.9 kHz | 56.7 deg | 27.2 dB |

Crossover lands at about 30 kHz as sec. 7 intends: 31.5 kHz nominal, 23-45 kHz
over the L and C corners. Phase margin is 59.9 deg nominal and 54.9-60.5 deg over
every row, inside the DS target of 50-70 deg (p. 33). The double zero at f_0
(2.7 nF, all else equal) gave 52.8 deg nominal and 47.6-54.4 deg over the same
rows, at the same crossover.

**Cross-check against sec. 7.**
- Sec. 7's |Gc(fc)| = 4.4 is defined against the error V_REF - V_FB, with a deck
  modulator gain of 12 (V_IN over a 1 V ramp). The equivalent for the LM25145,
  K_mid (f_c/f_0) / h = 0.24 x 3.6 / 0.242 = 3.5 at k_FF = 15, gives the same product
  (4.4 x 12 = 53 against 3.5 x 15 = 53).
- So the network reproduces the deck's crossover. It is not the deck's PID: the
  deck's KP, KI and KD are unchanged and are not derived from these parts.

### 10.9 PGOOD

PGOOD is open drain and needs a pull-up of at most 13 V, typically 10-100 k
(DS p. 19). Pick: 49.9 k to VOUT (R9), the value DS Figure 46 uses (p. 36). It draws
66 uA with PGOOD low. PGOOD-low voltage is at most 150 mV at 2 mA (DS p. 8).

Thresholds (DS p. 19) in VOUT terms, with the 3.296 V set point:
- rising 94 %: 3.10 V
- falling 92 %: 3.03 V
- over-voltage 108 %: 3.56 V, recovery 105 %: 3.46 V
- deglitch: 25 us

Nothing in the benchmark consumes PGOOD. It is included so the open-drain pin is
terminated and observable. Dropping R9 is acceptable; PGOOD then becomes
`isolated`.

### 10.10 SYNCIN and SYNCOUT

- **SYNCIN** is tied to VCC: forced PWM (DS p. 26, 8.4.4). The deck's switch node is
  an always-synchronous pair that conducts negative inductor current. Forced PWM is
  the hardware mode it models, and the deck's 1 A minimum load keeps it in CCM
  regardless. SYNCIN input resistance is 20 k (DS p. 8), so it costs 375 uA from VCC.
- **SYNCOUT** is unused.

### 10.11 Assumptions, stated once

1. The 36 uF effective output capacitance, 2 mOhm ESR and 20.4 mOhm DCR are the
   numbers of sections 3 and 4. They are not re-derived here.
2. Q2 R_DS(on) for eq. 6 is 4.8 mOhm, read from a typical-curve plot (IFX Diagram 8)
   at I_D = 50 A, not 2-3 A. Its maximum at 7.5 V gate drive is an estimate, scaled by
   5.9/4.7 from the 10 V row.
3. **Extraction alignment.** DS EC-table values from pp. 8-9 were read through a text
   extraction whose columns shift. The affected rows are V_EN, I_EN-HYS, V_ILIM-TH,
   FSW2 and T_ON(MIN). The min/typ/max assignment of V_ILIM-TH (-8/-2/3.5 mV) is the
   one most worth confirming against the PDF.
4. **Tolerances from MPN codes.**
   - Capacitor tolerance for C2 and C3 (+/-10 %) comes from the Murata MPN code "K".
     parts.yaml states no tolerance for them.
   - C0G parts are +/-5 % (code "J").
5. **Catalog checks.** Every new MPN follows the manufacturer's published ordering-code
   pattern for that value, and every value is a member of the series the line is sold
   in. NONE was checked against a distributor: the only network access this
   derivation had was the three datasheets. parts.yaml's history (a fabricated R1
   MPN shipped for two audit rounds) is the reason this matters.
6. **Ground and layout.** There is one ground net. Layout (loop areas, the snubber
   footprint the DS suggests on p. 49, an optional 2-10 Ohm resistor in series with
   C10, p. 49) is out of scope: the DSL carries no placement in v1.

## 11. LM25145 pin map (PROPOSAL, EE review required, AMB-128)

Source: TI, "LM25145 6-V to 42-V Synchronous Buck DC-DC Controller With Wide
Duty Cycle Range", https://www.ti.com/lit/ds/symlink/lm25145.pdf, 62 pages, revision
history "June 2017, *, Initial release" (p. 2), read 2026-10-22. Page numbers below
are that PDF's printed page numbers. Pin numbers, names and types come from section 6,
"Pin Configuration and Functions" (pp. 4-5). The PDF-to-text extraction used to read
it was checked against the table of contents page by page.

Type column (datasheet footnote, p. 4): P = power, G = ground, I = input, O = output.
"Role" is the T2 lattice role `buck-3v3.rhoform` declares
(`lang/grammar/rhoform_syntax.py` CLOSED_VOCABULARIES pin_role). "Rhoform pin" is the
datasheet name with `/` written `_`, because a pin name must be an identifier.

| Pin | Datasheet name | Type | Function (datasheet, condensed) | Rhoform pin | Role | Connection in this design | Net |
|---|---|---|---|---|---|---|---|
| 1 | EN/UVLO | I | Enable and UVLO programming. Below 0.4 V shutdown; 0.4-1.2 V standby; above 1.2 V switching. A 10 uA source turns on above 1.2 V for hysteresis (p. 4) | EN_UVLO | input | Midpoint of R6 (100 k, to VIN) and R7 (16.5 k, to GND): on at about 8.47 V, off at about 7.47 V | EN |
| 2 | RT | I | Oscillator frequency resistor to AGND. Required even when SYNCIN is clocked (p. 4) | RT | input | R5 20.0 k to GND (500 kHz) | RT |
| 3 | SS/TRK | I | Soft-start capacitor, charged by 10 uA; tracking input. Minimum 2.2 nF to AGND (p. 4) | SS_TRK | input | C9 6.8 nF C0G to GND (about 544 us) | SS |
| 4 | COMP | O | Error amplifier output. The compensation network goes between COMP and FB (p. 4) | COMP | output | CN1: R3 (7.50 k) in series with C6 (5.6 nF) to FB, and C7 (82 pF) to FB | COMP |
| 5 | FB | I | Inverting error amplifier input, regulates to 0.8 V (p. 4) | FB | input | R1/R2 divider midpoint; C6, C7, and C8 (560 pF, in series with R4 1.13 k from VOUT) | FB |
| 6 | AGND | P | Analog ground, return for the 0.8 V reference (p. 5) | AGND | power_in | Ground plane (single GND net) | GND |
| 7 | SYNCOUT | O | Clock output 180 degrees out of phase with HO (p. 5) | SYNCOUT | output | Unused. Declared `isolated u1.SYNCOUT` | (isolated) |
| 8 | SYNCIN | I | Clock input; logic low or floating enables diode emulation, logic high forces PWM (pp. 5, 26) | SYNCIN | input | Tied directly to VCC: forced PWM, matching the deck's always-synchronous switch model (p. 26: "tie SYNCIN to VCC either directly or using a pullup resistor") | VCC |
| 9 | NC | - | No electrical connection (p. 5) | NC9 | nc | Not connected in the netlist | - |
| 10 | PGOOD | O | Open-drain power-good output; pull-up to at most 13 V, typically 10-100 k (pp. 5, 19) | PGOOD | open_drain | R9 49.9 k pull-up to VOUT | PGOOD |
| 11 | ILIM | I | Valley current-limit resistor; in RDS(on) mode the other end goes to the low-side FET drain (SW) (p. 5) | ILIM | input | R8 66.5 ohm to SW; C12 82 pF to GND (PGND) | ILIM |
| 12 | PGND | P | Low-side driver power ground; connect directly to the low-side FET source (p. 5) | PGND | power_in | Ground plane (single GND net) | GND |
| 13 | LO | P | Low-side gate drive output (p. 5) | LO | output | Q2 gate | LO |
| 14 | VCC | O | 7.5 V bias regulator output; decouple locally to PGND (p. 5) | VCC | power_out | C11 2.2 uF to GND; also feeds SYNCIN | VCC |
| 15 | EP | - | Pin internally connected to the exposed pad; electrically isolated (p. 5) | EP (with pad 21) | passive | Ground plane | GND |
| 16 | NC | - | No electrical connection (p. 5) | NC16 | nc | Not connected in the netlist | - |
| 17 | BST | O | Bootstrap supply for the high-side driver; connect to the bootstrap capacitor (p. 5) | BST | power_out | C10 100 nF to SW | HB |
| 18 | HO | P | High-side gate drive output (p. 5) | HO | output | Q1 gate | HO |
| 19 | SW | P | Switch node; bootstrap capacitor, high-side source, low-side drain (p. 5) | SW | passive | Q1 source, Q2 drain, L1, C10, R8 | SW |
| 20 | VIN | P | Supply input for the VCC LDO (p. 5) | VIN | power_in | Input rail; C3 100 nF local bypass | VIN |
| pad | Exposed pad | - | "Electrically isolated. Solder to the system ground plane to reduce thermal resistance." (p. 5); p. 4: "Connect Exposed Pad on bottom to AGND and PGND on the PCB." | EP (designator 21) | passive | Ground plane | GND |

### Decisions and assumptions in this map

1. **The datasheet calls the bootstrap pin BST, not HB.** The bootstrap net is
   named `HB`, and it joins `u1.BST` to C10.
2. **There is no VDDA pin on the LM25145.** Its 20 pins are listed above; the only bias
   rail is VCC, so "VCC/VDDA decoupling" reduces to the VCC capacitor (C11). A VDDA
   pin exists on other TI controllers, not on this one.
3. **Exposed-pad designator 21.** The datasheet does not number the exposed pad; it is
   row "-" in the pin table (p. 5). Pin 15 (EP) is "internally connected to exposed pad",
   so the source declares one port `EP` with designators `15 21`. The number 21 is an
   assumption: it is the common footprint convention for a 20-pin package plus one
   exposed pad. The KiCad footprint that R30 eventually binds must agree.
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
   no section 8-Q6 net tie is needed.
7. **Unused functions.**
   - SYNCOUT: driven, unused, declared `isolated`.
   - Tracking: SS/TRK carries only the soft-start capacitor.
   - External VCC bias (Figure 32, p. 18): not used. At 14 V maximum input the LDO
     dissipates about 57 mW (sec. 10.6).

### MOSFET pinout (Q1, Q2)

Infineon BSC059N04LS6, datasheet rev. 2.1 (2020-07-22), p. 1 pin diagram:
S = 1, 2, 3; G = 4; D = 5, 6, 7, 8. The package on p. 1 is "PG-TDSON-8 FL" (fused
lead). parts.yaml writes "PG-TDSON-8 (SuperSO8 5x6)". The large drain pad is part of
the drain leadframe and shares the D designators, which is an assumption about the
footprint. Roles: d passive, s passive, g input.

| Instance | d (5-8) | g (4) | s (1-3) |
|---|---|---|---|
| q1 (high side) | VIN | HO | SW |
| q2 (low side) | SW | LO | GND |

### Inductor

Coilcraft XGL6060-103ME (datasheet p. 2 table), two terminals declared `a` (1) and
`b` (2). l1.a is on SW and l1.b is on VOUT. The part is unpolarised, so the assignment
is arbitrary.
