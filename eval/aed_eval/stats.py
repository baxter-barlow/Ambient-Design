"""Exact small-sample statistics for the AC5 protocol and the §4 comparison.

Everything here is computed EXACTLY with integer arithmetic and Fractions,
then converted to float only at the boundary. No scipy, no normal
approximations, no random sampling: the same inputs give bit-identical
outputs on every machine, which the determinism contract requires of a
number that gates a release.

Two decisions are supported, and they are NOT the same kind of decision:

  AC5a GATE — "design (a) passes in at least 7 of 10 independent trials".
  This is a threshold rule, not a hypothesis test. `ac5_gate` implements it
  literally. `wilson_interval` accompanies it so the report states how
  little 10 trials actually pin down.

  §4 FLIP CRITERION — "emission accuracy after repair loops is
  statistically below a Starlark-restricted-Python baseline under the AC5
  protocol". That IS a hypothesis test, and it needs a pre-registered rule,
  a direction, and an honest account of its power. `mcnemar_exact` (paired,
  preferred) and `fisher_exact_one_sided` (unpaired) implement it;
  `power_paired` and `power_unpaired` say what those tests can actually
  detect at a given sample size.

WHY THE POWER FUNCTIONS ARE HERE. Ten trials per arm is enough to gate a
threshold but nowhere near enough to compare two arms: see
`required_n_unpaired`, which reports what a real comparison costs. Shipping
the comparison without that number invites reading a non-significant result
as evidence of equivalence, which it is not. The bake-off should decide its
sample size from these functions BEFORE spending tokens, not after.
"""

from fractions import Fraction
from math import comb


# ---------------------------------------------------------------- binomial


def binom_pmf(k: int, n: int, p: Fraction) -> Fraction:
    """Exact P(X = k) for X ~ Binomial(n, p)."""
    if k < 0 or k > n:
        return Fraction(0)
    return comb(n, k) * (p**k) * ((1 - p) ** (n - k))


def binom_cdf(k: int, n: int, p: Fraction) -> Fraction:
    """Exact P(X <= k)."""
    if k < 0:
        return Fraction(0)
    if k >= n:
        return Fraction(1)
    return sum((binom_pmf(i, n, p) for i in range(k + 1)), Fraction(0))


def binom_sf(k: int, n: int, p: Fraction) -> Fraction:
    """Exact P(X >= k)."""
    if k <= 0:
        return Fraction(1)
    if k > n:
        return Fraction(0)
    return sum((binom_pmf(i, n, p) for i in range(k, n + 1)), Fraction(0))


# ------------------------------------------------------------- AC5a gating


def ac5_gate(successes: int, trials: int, threshold: int = 7, of: int = 10) -> dict:
    """The AC5a acceptance rule, applied literally.

    The requirement is "in >= 7/10 independent trials", i.e. a success RATE
    of at least threshold/of. Expressed as a rate so a run with more than
    ten trials is judged on the same bar rather than on a raw count that
    would silently become easier to clear.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError("successes must lie in [0, trials]")

    required_rate = Fraction(threshold, of)
    observed_rate = Fraction(successes, trials)
    # Smallest integer count meeting the required rate.
    required_successes = -((-threshold * trials) // of)

    return {
        "successes": successes,
        "trials": trials,
        "observed_rate": float(observed_rate),
        "required_rate": float(required_rate),
        "required_successes": required_successes,
        "passed": observed_rate >= required_rate,
        "rule": f"pass iff successes/trials >= {threshold}/{of}",
    }


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> dict:
    """Wilson score interval for a binomial proportion (default 95%).

    Reported alongside every gate result. At 7/10 the interval runs roughly
    0.40 to 0.89 — consistent with a true pass rate anywhere from a coin
    flip to near-certainty. Stating that next to a PASS is the difference
    between an honest result and an overclaimed one.

    Wilson rather than Wald because Wald is badly behaved at small n and
    near 0 or 1, which is exactly where these runs live.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    n = trials
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z / denom) * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5)
    return {
        "point": phat,
        "low": max(0.0, centre - half),
        "high": min(1.0, centre + half),
        "z": z,
    }


# ------------------------------------------------- §4 comparison: unpaired


def fisher_exact_one_sided(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher exact test on the 2x2 table

            success   failure
        A      a          b
        B      c          d

    Returns P(observing a success count for arm A this low or lower, given
    the margins), i.e. the p-value for the alternative "A's success rate is
    BELOW B's". That direction is the one §4 asks about: the flip criterion
    fires when AED is worse than the Starlark baseline, so a two-sided test
    would spend half its significance budget on an outcome nobody proposed
    to act on.

    Exact hypergeometric enumeration; no approximation.
    """
    for value in (a, b, c, d):
        if value < 0:
            raise ValueError("counts must be non-negative")
    row_a, row_b = a + b, c + d
    col_success = a + c
    total = row_a + row_b
    if total == 0 or row_a == 0 or row_b == 0:
        return 1.0

    def hypergeom(k: int) -> Fraction:
        if k < 0 or k > row_a or (col_success - k) < 0 or (col_success - k) > row_b:
            return Fraction(0)
        return Fraction(
            comb(row_a, k) * comb(row_b, col_success - k), comb(total, col_success)
        )

    lowest = max(0, col_success - row_b)
    p = sum((hypergeom(k) for k in range(lowest, a + 1)), Fraction(0))
    return float(min(Fraction(1), p))


def power_unpaired(n_a: int, n_b: int, p_a: float, p_b: float, alpha: float = 0.05) -> float:
    """Exact power of the one-sided Fisher test, by full enumeration.

    Enumerates every (successes_A, successes_B) outcome, weights it by its
    exact binomial probability under the stated true rates, and sums the
    weight of outcomes the test would reject. Cost is (n_a+1)*(n_b+1)
    p-value evaluations, which is trivial at the sample sizes involved.
    """
    fa, fb = Fraction(p_a).limit_denominator(10**6), Fraction(p_b).limit_denominator(10**6)
    total = Fraction(0)
    for ka in range(n_a + 1):
        pa = binom_pmf(ka, n_a, fa)
        if pa == 0:
            continue
        for kb in range(n_b + 1):
            pb = binom_pmf(kb, n_b, fb)
            if pb == 0:
                continue
            pval = fisher_exact_one_sided(ka, n_a - ka, kb, n_b - kb)
            if pval <= alpha:
                total += pa * pb
    return float(total)


def required_n_unpaired(
    p_a: float, p_b: float, target_power: float = 0.8, alpha: float = 0.05, cap: int = 200
) -> dict:
    """Smallest equal per-arm n reaching `target_power`, or None within `cap`.

    This is the number the bake-off should be budgeted against. Ten trials
    per arm detects only enormous differences; if the honest answer is that
    a properly powered comparison costs more tokens than the §4 flip
    decision is worth, that is a finding to record, not to discover halfway
    through a run.
    """
    for n in range(5, cap + 1, 5):
        power = power_unpaired(n, n, p_a, p_b, alpha)
        if power >= target_power:
            return {"n_per_arm": n, "power": power, "alpha": alpha}
    return {
        "n_per_arm": None,
        "power": power_unpaired(cap, cap, p_a, p_b, alpha),
        "alpha": alpha,
        "note": f"no equal-arm n <= {cap} reaches power {target_power}",
    }


# --------------------------------------------------- §4 comparison: paired


def mcnemar_exact(b: int, c: int) -> float:
    """Exact one-sided McNemar test on discordant pairs.

    `b` counts seeds where arm A succeeded and arm B failed; `c` counts the
    reverse. Concordant pairs carry no information about which arm is
    better and are correctly ignored.

    Returns the p-value for "A is worse than B" = P(X <= b) where
    X ~ Binomial(b + c, 1/2) under the null of no difference.

    PREFER THIS OVER FISHER when both arms run the same benchmark with the
    same seed set. Pairing removes between-seed variance, so it detects a
    real difference at a substantially smaller n — which at roughly 150K
    tokens per trial is a direct cost saving, not a statistical nicety.
    """
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    return float(binom_cdf(b, n, Fraction(1, 2)))


def power_paired(n_pairs: int, p_discordant: float, p_a_given_discordant: float,
                 alpha: float = 0.05) -> float:
    """Exact power of the one-sided McNemar test, by full enumeration.

    `p_discordant` is the probability a seed is discordant at all;
    `p_a_given_discordant` is the probability that, given discordance, it is
    arm A that succeeded. A is worse than B when that is below 0.5.
    """
    pd = Fraction(p_discordant).limit_denominator(10**6)
    pa = Fraction(p_a_given_discordant).limit_denominator(10**6)
    total = Fraction(0)
    for n_disc in range(n_pairs + 1):
        p_n = binom_pmf(n_disc, n_pairs, pd)
        if p_n == 0:
            continue
        for b in range(n_disc + 1):
            p_b = binom_pmf(b, n_disc, pa)
            if p_b == 0:
                continue
            if mcnemar_exact(b, n_disc - b) <= alpha:
                total += p_n * p_b
    return float(total)


# ------------------------------------------------------------ flip verdict


def flip_verdict(
    aed_successes: int,
    aed_trials: int,
    baseline_successes: int,
    baseline_trials: int,
    discordant_aed_only: int | None = None,
    discordant_baseline_only: int | None = None,
    alpha: float = 0.05,
) -> dict:
    """Evaluate the §4 flip criterion and report what the answer is worth.

    Uses the paired test when discordant counts are supplied (both arms ran
    the same seeds), otherwise the unpaired one. Returns the p-value, the
    verdict, and — crucially — the power the test had against a plausible
    effect, so a non-significant result is not read as equivalence.

    The verdict is deliberately three-valued. "inconclusive" is a real
    outcome: it means the run did not have the power to answer the question,
    and the correct response is more trials or an explicit decision to stop
    asking, never a quiet "no difference found".
    """
    paired = discordant_aed_only is not None and discordant_baseline_only is not None
    if paired:
        p_value = mcnemar_exact(discordant_aed_only, discordant_baseline_only)
        test = "mcnemar_exact_one_sided"
        n_disc = discordant_aed_only + discordant_baseline_only
        observed_power = power_paired(
            aed_trials, n_disc / aed_trials if aed_trials else 0.0, 0.25, alpha
        )
    else:
        p_value = fisher_exact_one_sided(
            aed_successes,
            aed_trials - aed_successes,
            baseline_successes,
            baseline_trials - baseline_successes,
        )
        test = "fisher_exact_one_sided"
        observed_power = power_unpaired(aed_trials, baseline_trials, 0.6, 0.9, alpha)

    significant = p_value <= alpha
    if significant:
        verdict = "flip_criterion_met"
    elif observed_power >= 0.8:
        verdict = "flip_criterion_not_met"
    else:
        verdict = "inconclusive"

    return {
        "test": test,
        "paired": paired,
        "p_value": p_value,
        "alpha": alpha,
        "aed_rate": aed_successes / aed_trials if aed_trials else None,
        "baseline_rate": (
            baseline_successes / baseline_trials if baseline_trials else None
        ),
        "power_against_reference_effect": observed_power,
        "verdict": verdict,
        "interpretation": {
            "flip_criterion_met": "AED is statistically below the Starlark baseline; §4 says re-evaluate the standalone-DSL decision.",
            "flip_criterion_not_met": "No evidence AED is below the baseline, and the run had adequate power to have found it.",
            "inconclusive": "The run lacked power to distinguish the arms. This is NOT evidence of equivalence; add trials or record the question as unanswered.",
        }[verdict],
    }
