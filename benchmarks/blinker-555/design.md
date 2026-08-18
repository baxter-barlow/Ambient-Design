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
30 nA typ / 250 nA max, which datasheets translate to an RA+RB ceiling of
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
- **f window: 0.923 – 1.052 Hz** (-6.58 %/+6.48 % about the 0.988 Hz
  nominal, ±6.53 % about the window's own midpoint; cap tolerance
  dominates). This read ±6.1 %, which is reproducible from neither.
- Equivalent period window: **0.951 – 1.083 s**

Duty is a resistor ratio only, so passives contribute almost nothing
(corners RA±1 %, RB∓1 % give 53.36 – 53.49 %). The realistic spread comes from
the 555 itself — comparator threshold ratio error, discharge-transistor Ron
(t_low is really ln2·(RB+Ron)·C, though at RB = 680 k the Ron term is
negligible), and finite edge shape — so the assertion window is set at device
level:

- **duty window: 53.3 – 55.8 %** (one-sided; see sec. "Duty-cycle window")

LED on-current window from Vf spread (1.8–2.2 V), Voh spread (7.0–7.5 V),
RL ±1 %: 8.5 – 10.3 mA, rounded outward to an **8.0 – 10.5 mA** assertion.

## Validation results (ngspice-46, behavioral NE555 macromodel)

| Assertion | Predicted window | Measured | Verdict |
|---|---|---|---|
| f_osc | 0.923 – 1.052 Hz | 0.98823 Hz | PASS |
| duty_pct | 53.3 – 55.8 % | 53.45 % | PASS |
| t_period | 0.951 – 1.083 s | 1.01191 s | PASS |
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

The design is 9 BOM lines (`parts.yaml`), 7 nets and 2 assertions. The
full 71-line rendering has 11 component instances: the count above is
fitted parts, and `mh1` (a mounting hole) and `tp_out` (a test point) are
instances that carry no BOM line. Neither number is countable from the
20-line excerpt below, which shows 8 components and stops before `tp_out`;
run the reproduce command for the whole thing. Stating the rule because the
reader's eye lands on the DSL, where the two numbers otherwise disagree. Rendered through
**candidate_b, the arm the bake-off chose** (`lang/README.md`), from
`lang/examples/blinker-555.design.json`:

| variant | lines |
|---|---|
| explicit | 119 |
| inferred | 82 |
| inferred + columnar | 71 |

against the ~150-line budget: 79 lines of margin at the most compact
variant, 31 at the most explicit.

An earlier revision of this section published 130/93/82 and called them "the
winning bake-off arm ... in the frozen v0.1 syntax". Both halves were wrong.
Those are **candidate_a**'s counts, and candidate_a is the arm that LOST --
`lang/tests/test_grammar.py::test_the_grammar_rejects_the_losing_candidates_surface`
asserts the frozen grammar rejects exactly that rendering. So AC1a's headline
evidence was measured on a syntax the frozen grammar refuses, and labelled as
the frozen syntax. `check-design-docs.py` reads only tables whose last column
is a verdict, so this one is outside it by construction; the counts are
reproducible from the command below instead.

Reproduce with:

    python3 -c "import sys; sys.path.insert(0,'lang'); \
      from bakeoff.arms import candidate_b; from bakeoff.model import load_model; \
      from pathlib import Path; \
      print(candidate_b.render(load_model(Path('lang/examples/blinker-555.design.json')), \
                               'inferred+columnar'))"

The first 20 lines of the top-level module from that command. It is 53 lines,
so this is a truncation, not the whole rendering: the cut lands one line before
a second constraint in the `timer` block and 32 lines before the two `assert`
statements, which is where a reader would have seen the windows this section
discusses.

```rhoform
module Blinker555:
    table rhoform.lib.passive.Capacitor part abstract (capacitance, part.dielectric, part.package, part.voltage_rating):
        c_byp  100nF +/- 10%  "X7R"       "0805"        50V
        c_ctl  10nF +/- 10%   "X7R"       "0805"        50V
        c_t    1uF +/- 5%     "PET_film"  "radial_5mm"  63V
    indicator = new LedIndicator(color = "red", current = 9.5mA (8.0mA to 10.5mA))
    j_bat = new rhoform.lib.connector.BatteryConnector9V:
        part "conn.battery_9v/keystone-232@1"
    mh1 = new rhoform.lib.mech.MountingHole(diameter = 3.2mm)
    r_a = new rhoform.lib.passive.Resistor(resistance = 100kohm +/- 1%):
        part abstract:
            package = "axial_0207"
            power_rating = 0.25W
    r_b = new rhoform.lib.passive.Resistor(resistance = 680kohm +/- 1%):
        part abstract:
            package = "axial_0207"
            power_rating = 0.25W
    timer = new rhoform.lib.timer.Ne555:
        part "timer.555/ti-NE555P@2":
            function = "timer_555"
```

## Duty-cycle window: why it is +/-2.2 points and not +/-1.0

The original window was `[52.4 %, 54.4 %]`, derived from comparator-threshold ratio
error, discharge-transistor Ron and finite edge shape. That derivation omits the
term that dominates at these impedances: the timing-pin **bias current**.

Both THRES and TRIG bias currents act on the shared timing node, so with a net
bias `Ib` the exact half-periods are

    t_high = (RA+RB)*C * ln[ (Vcc - Ib*(RA+RB) - Vcc/3) / (Vcc - Ib*(RA+RB) - 2Vcc/3) ]
    t_low  =      RB*C * ln[ (2Vcc/3 + Ib*RB) / (Vcc/3 + Ib*RB) ]

The `Ib*R` products scale with **R**, not with the RC product. The 2026-08-15
fix round rescaled `RA 10k -> 100k`, `RB 68k -> 680k`, `CT 10uF -> 1uF` and
recorded that this left "the ~1 Hz target, duty ratio, and all tolerance windows
unchanged" because the RC products are identical. The frequency claim is right;
the duty claim is not. The rescale multiplied the bias term by ten.

At the shipped values (RA 100k, RB 680k, C 1uF, Vcc 9 V):

| Ib | duty |
|---|---|
| -0.25 uA | 51.241 % |
| -0.10 uA | 52.551 % |
| 0 (the macromodel) | 53.425 % |
| +0.10 uA | 54.298 % |
| +0.25 uA | 55.609 % |

The NE555 datasheet specifies threshold current 30 nA typ / **250 nA max**, so
the part's own guaranteed corner lands outside the old window. At the
pre-rescale values the same +/-0.25 uA gives 53.21-53.64 %, about ten times the
margin -- which is what "unchanged" was true of.

The window is `[53.3 %, 55.8 %]`, and it is ONE-SIDED. **This is a corrected
derivation, not a relaxed bound** — but it took two goes, and the first was
wrong in three ways worth recording:

1. **Sign.** Both timing pins SINK current from the node, so `Ib >= 0`. TI's
   SLFS022K publishes THRES and TRIG currents positive and RESET negative. A
   symmetric `+/-0.25 uA` window spent 2.2 points modelling a low corner with
   no mechanism, and spent them instead of covering the high corner that exists.
2. **Magnitude — and this took a third pass to get right.** A revision used
   `Ib <= 0.5 uA`, obtained by inverting the datasheet's design guideline that
   `RA+RB <= 3.4 MOhm` at 5 V and `10 MOhm` at 15 V. That inversion is arithmetic
   on a recommendation, not a specification, and the recommendation already
   carries its own margin: `(5/3)/3.4M = 0.490 uA` and `(15/3)/10M = 0.500 uA`
   are **1.96x and 2.00x** the guaranteed 250 nA THRES maximum. Reading 0.5 uA
   off it double-counts that margin. The bound is the specified maximum,
   250 nA, and the window is `[53.3, 55.8]` accordingly.

   TRIG's bias current is specified at 2 uA **max with TRIG at 0 V**, and the
   astable's timing node swings between Vcc/3 and 2Vcc/3 — it is never at 0 V,
   so that figure does not transfer. Under the sign argument above TRIG does
   contribute, but the datasheet publishes no bound applicable at this
   operating point, so it is not in the window and this paragraph is the record
   of why. (TI's THRES typ is 30 nA, not the 0.1 uA quoted in sec. "Timing
   design"; `parts/examples/ti-ne555p.part.json` records 30/250 nA correctly.)
3. **Rounding.** The first correction tabulated 55.609 % and then set the
   window to 55.6 %, excluding the very corner it was widened to admit.

Corners are now swept over `RA +/-1 %`, `RB +/-1 %`, `C +/-5 %` and
`Ib in [0, 0.25 uA]` jointly, and rounded OUTWARD, which is what sec. "LED drive" already
does for the LED window. The old number was computed from an incomplete model of the
same circuit; nothing about the circuit got worse and no measurement was made to
fit. The rescale itself is kept: a 1 uF film part has far better tolerance and
leakage than a 10 uF electrolytic, which is worth more than duty precision in a
blinker.

The simulation cannot see any of this. `Bset`/`Bthr` in `netlist.cir` are B-source
voltage expressions and draw exactly zero input current, so the deck measures the
Ib = 0 row (53.45 %) and always will. That is a stated limit of the rung-0
macromodel, not a passing result.

### The same term moves the frequency and period windows

Applying the correction to duty alone left two sibling assertions failing at the
corner this section declares real: at `Ib = 0.25 uA` (the guaranteed THRES maximum) with `R +1 %` and `C +5 %`,
`f = 0.92422 Hz` against a declared floor of 0.932, and `T = 1.08199 s` against
a declared ceiling of 1.073. All three assertions come from the same two
equations, so all three are now swept over the same joint corner set:

| assertion | was | is |
|---|---|---|
| `osc_period` | 0.952 – 1.073 s | **0.951 – 1.083 s** |
| `osc_frequency` | 0.932 – 1.051 Hz | **0.923 – 1.052 Hz** |
| `duty_cycle_high` | 52.4 – 54.4 % | **53.3 – 55.8 %** |

The period window was also rounded INWARD at both ends even at `Ib = 0`
(0.95178 < 0.952 and 1.07322 > 1.073), so it excluded the passive-tolerance
corner before bias current was considered at all.

## VCC bypass

`CBYP`, 100 nF from pin 8 to ground, added under AMB-123. The design had no
supply bypass at all -- the only capacitors were the timing cap and the CONT
bypass on pin 5. At 9 V the totem-pole output draws a shoot-through spike on
every edge, and both comparator thresholds are derived from VCC, so on a real
board with a PP3 snap and lead inductance this is the classic 555 double-trigger.

The deck cannot show it either: `VCC vcc 0 PWL(...)` is an ideal zero-impedance
source.

Worth recording for AC2: `corpus/README.md` reasons about a generic "power_in pin
with no capacitor to ground" rule and treats it as producing a **spurious** error
on this benchmark, which is part of why the `decoupling-rule` group is rated
"passes, with nothing to spare". It was not spurious. It was a true positive
against a real omission, and the corpus's own BUG-0056 describes the same defect
class on a DIP-8. Fixing the benchmark removes the tension instead of narrowing
the rule to hide it.
