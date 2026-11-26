"""Paired within-run baseline comparisons for matched synthetic trials.

The tests avoid pooled independent-sample comparisons. Continuous p-values use
a paired sign-flip randomization test; binary success uses exact McNemar.
Intervals use a deterministic paired percentile bootstrap. Inference labels are
withheld below the protocol's predeclared 20-pair threshold.
"""
from __future__ import annotations

from itertools import product
import hashlib
import math
import random
from typing import Any

from app.experiments.protocol import SCENARIO_ESTIMATOR_VERSIONS

STATISTICS_VERSION = "paired-statistics-v1"
MIN_INFERENTIAL_TRIALS = 20
BOOTSTRAP_REPLICATES = 4000
PERMUTATION_REPLICATES = 10000


def wilson_score_interval(successes: int | None, attempts: int | None) -> list[float | None]:
    """Return a two-sided 95% Wilson score interval for a binary proportion.

    Missing counts and a zero denominator are unmeasured. Invalid non-integer
    counts or counts outside 0 <= successes <= attempts are rejected.
    """
    if successes is None or attempts is None:
        return [None, None]
    if (isinstance(successes, bool) or not isinstance(successes, int)
            or isinstance(attempts, bool) or not isinstance(attempts, int)
            or attempts < 0 or successes < 0 or successes > attempts):
        raise ValueError("Wilson interval requires integer counts with 0 <= successes <= attempts.")
    if attempts == 0:
        return [None, None]

    z = 1.959963984540054
    proportion = successes / attempts
    z2 = z * z
    denominator = 1 + z2 / attempts
    center = (proportion + z2 / (2 * attempts)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / attempts + z2 / (4 * attempts * attempts)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def compare_protocol_compatibility(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    lp, rp = left.get("protocol"), right.get("protocol")
    if not isinstance(lp, dict) or not isinstance(rp, dict):
        return {"compatible": False, "reasons": ["One or both runs lack a persisted versioned protocol."]}
    reasons: list[str] = []
    for key in ("version", "scenario_identifier", "dataset", "workload", "attack_parameters", "trials", "privacy_parameters", "metric_definitions", "statistical_methodology", "execution_environment"):
        if lp.get(key) != rp.get(key):
            reasons.append(f"Protocol field '{key}' differs.")
    left_baselines = {str(item.get("id")): item for item in lp.get("baselines", []) if isinstance(item, dict)}
    right_baselines = {str(item.get("id")): item for item in rp.get("baselines", []) if isinstance(item, dict)}
    for baseline in sorted(left_baselines.keys() & right_baselines.keys()):
        if left_baselines[baseline] != right_baselines[baseline]:
            reasons.append(f"Baseline configuration '{baseline}' differs.")
    return {"compatible": not reasons, "reasons": reasons, "protocol_version": lp.get("version") if not reasons else None}


def _percentile(sorted_values: list[float], probability: float) -> float:
    pos = (len(sorted_values) - 1) * probability
    lower, upper = math.floor(pos), math.ceil(pos)
    if lower == upper:
        return sorted_values[lower]
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _stable_seed(protocol_version: str, reference: str, candidate: str, metric: str) -> int:
    digest = hashlib.sha256(f"{protocol_version}:{reference}:{candidate}:{metric}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _bootstrap_mean_ci(differences: list[float], rng: random.Random) -> list[float | None]:
    if len(differences) < 2:
        return [None, None]
    estimates = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = [differences[rng.randrange(len(differences))] for _ in differences]
        estimates.append(sum(sample) / len(sample))
    estimates.sort()
    return [_percentile(estimates, .025), _percentile(estimates, .975)]


def _sign_flip_p(differences: list[float], rng: random.Random) -> tuple[float | None, str]:
    n = len(differences)
    if n < 2:
        return None, "insufficient pairs"
    observed = abs(sum(differences) / n)
    tolerance = 1e-15 * max(1.0, observed)
    if n <= 16:
        extreme = total = 0
        for signs in product((-1.0, 1.0), repeat=n):
            statistic = abs(sum(value * sign for value, sign in zip(differences, signs)) / n)
            extreme += statistic + tolerance >= observed
            total += 1
        return extreme / total, "exact paired sign-flip randomization test"
    extreme = sum(abs(sum(value * (1 if rng.getrandbits(1) else -1) for value in differences) / n) + tolerance >= observed for _ in range(PERMUTATION_REPLICATES))
    return (extreme + 1) / (PERMUTATION_REPLICATES + 1), "Monte Carlo paired sign-flip test (10,000 draws)"


def _mcnemar(success_a: list[bool], success_b: list[bool]) -> tuple[float | None, int, int]:
    a_only = sum(a and not b for a, b in zip(success_a, success_b))
    b_only = sum(b and not a for a, b in zip(success_a, success_b))
    discordant = a_only + b_only
    if not discordant:
        return 1.0, a_only, b_only
    tail = sum(math.comb(discordant, k) for k in range(min(a_only, b_only) + 1)) / (2 ** discordant)
    return min(1.0, 2 * tail), a_only, b_only


def _holm(raw_values: list[float | None]) -> list[float | None]:
    indexed = sorted(((value, index) for index, value in enumerate(raw_values) if value is not None), key=lambda pair: pair[0])
    adjusted: list[float | None] = [None] * len(raw_values)
    running = 0.0
    count = len(indexed)
    for rank, (p_value, index) in enumerate(indexed):
        running = max(running, min(1.0, (count - rank) * p_value))
        adjusted[index] = running
    return adjusted


def paired_comparisons(results: list[dict[str, Any]], configuration: dict[str, Any], reference_baseline: str = "M1", validation_status: str | None = None) -> dict[str, Any]:
    if validation_status == "FAIL":
        return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline,
                "reason": "Integrity validation failed; paired statistics are withheld until the persisted metrics are corrected in a future run.", "comparisons": []}
    if configuration.get("scenario") == "repeated" and any(
        (row.get("metrics") or {}).get("attack_estimator_version") != SCENARIO_ESTIMATOR_VERSIONS["repeated"]
        for row in results
    ):
        return {"version": STATISTICS_VERSION, "status": "INELIGIBLE", "reference_baseline": reference_baseline,
                "reason": "Legacy repeated-query results lack unique release/noise-sample estimator provenance; retain them as descriptive historical evidence only.", "comparisons": []}
    protocol = configuration.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("version") != "privacyguard-research-protocol-v2":
        return {"version": STATISTICS_VERSION, "status": "UNAVAILABLE", "reference_baseline": reference_baseline, "reason": "A persisted protocol v2 is required for paired comparisons.", "comparisons": []}
    by_baseline = {str(row.get("baseline")): row.get("metrics") or {} for row in results}
    if len(by_baseline) != len(results):
        return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": "Duplicate baseline rows prevent unambiguous pairing.", "comparisons": []}
    if not isinstance(protocol.get("version"), str) or not protocol.get("version"):
        return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": "Persisted protocol version is missing or invalid.", "comparisons": []}
    if reference_baseline not in by_baseline:
        return {"version": STATISTICS_VERSION, "status": "UNAVAILABLE", "reference_baseline": reference_baseline, "reason": "The selected reference baseline is not present in this run.", "comparisons": []}
    expected_seeds = protocol.get("trials", {}).get("trial_seeds", [])
    ref_measurements = by_baseline[reference_baseline].get("measurements", [])
    if by_baseline[reference_baseline].get("protocol_version") != protocol.get("version"):
        return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": "Reference result protocol version does not match the persisted run protocol.", "comparisons": []}
    ref_by_trial = {row.get("trial"): row for row in ref_measurements if isinstance(row, dict)}
    if len(ref_by_trial) != len(expected_seeds) or any(ref_by_trial.get(i + 1, {}).get("trial_seed") != seed for i, seed in enumerate(expected_seeds)):
        return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": "Reference trial evidence does not match the persisted trial seed schedule.", "comparisons": []}

    metric_specs = {
        "attack_success": {"field": "attack_success", "kind": "binary", "direction": "lower is better"},
        "inference_absolute_error": {"field": "attack_absolute_error", "kind": "continuous", "direction": "lower is better"},
        "aggregate_mae": {"field": "aggregate_mae", "kind": "continuous", "direction": "lower is better"},
        "aggregate_rmse": {"field": "aggregate_rmse", "kind": "continuous", "direction": "lower is better"},
        "synthetic_engine_latency_ms": {"field": "query_latency_ms_mean", "kind": "continuous", "direction": "lower is better"},
        "nominal_epsilon_spent": {"field": "nominal_epsilon_spent", "kind": "continuous", "direction": "context-dependent"},
    }
    output: list[dict[str, Any]] = []
    for candidate in sorted(by_baseline):
        if candidate == reference_baseline:
            continue
        candidate_measurements = by_baseline[candidate].get("measurements", [])
        if by_baseline[candidate].get("protocol_version") != protocol.get("version"):
            return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": f"{candidate} result protocol version does not match the persisted run protocol.", "comparisons": []}
        candidate_by_trial = {row.get("trial"): row for row in candidate_measurements if isinstance(row, dict)}
        if len(candidate_by_trial) != len(expected_seeds) or any(candidate_by_trial.get(i + 1, {}).get("trial_seed") != seed for i, seed in enumerate(expected_seeds)):
            return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": f"{candidate} trial evidence does not match the shared persisted seed schedule.", "comparisons": []}
        for metric, spec in metric_specs.items():
            pairs: list[tuple[Any, Any]] = []
            for trial_number in range(1, len(expected_seeds) + 1):
                a, b = ref_by_trial[trial_number].get(spec["field"]), candidate_by_trial[trial_number].get(spec["field"])
                if spec["kind"] == "binary":
                    if any(value is not None and not isinstance(value, bool) for value in (a, b)):
                        return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": f"Non-boolean outcome found for binary metric '{metric}'.", "comparisons": []}
                elif any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))) for value in (a, b)):
                    return {"version": STATISTICS_VERSION, "status": "INCOMPATIBLE", "reference_baseline": reference_baseline, "reason": f"Non-finite or non-numeric observation found for metric '{metric}'.", "comparisons": []}
                if a is not None and b is not None:
                    pairs.append((a, b))
            n = len(pairs)
            if spec["kind"] == "binary":
                ref_values, cand_values = [bool(a) for a, _ in pairs], [bool(b) for _, b in pairs]
                differences = [float(b) - float(a) for a, b in pairs]
                raw_p, a_only, b_only = _mcnemar(ref_values, cand_values) if n else (None, None, None)
                method = "exact McNemar test; paired percentile bootstrap CI for risk difference"
                test_assumptions = "paired binary outcomes; under the null, discordant outcomes are equally likely"
            else:
                ref_values, cand_values = [float(a) for a, _ in pairs], [float(b) for _, b in pairs]
                differences = [b - a for a, b in pairs]
                rng_seed = _stable_seed(str(protocol["version"]), reference_baseline, candidate, metric)
                rng = random.Random(rng_seed)
                raw_p, test_method = _sign_flip_p(differences, rng)
                method = f"{test_method}; paired percentile bootstrap CI for mean paired difference"
                test_assumptions = "trial pairs are exchangeable; sign-flip test assumes symmetric differences under the null"
                a_only = b_only = None
            if n:
                rng = random.Random(_stable_seed(str(protocol["version"]), reference_baseline, candidate, metric + ":bootstrap"))
                ci = _bootstrap_mean_ci(differences, rng)
                mean_diff = sum(differences) / n
                ordered_diff = sorted(differences)
                median_diff = _percentile(ordered_diff, .5)
                sd = math.sqrt(sum((value - mean_diff) ** 2 for value in differences) / (n - 1)) if n > 1 else None
                effect = mean_diff / sd if sd not in (None, 0.0) else None
            else:
                ci, mean_diff, median_diff, effect = [None, None], None, None, None
            output.append({"reference_baseline": reference_baseline, "baseline": candidate, "metric": metric, "direction": spec["direction"], "n_pairs": n,
                           "reference_mean": sum(ref_values) / n if n else None, "baseline_mean": sum(cand_values) / n if n else None,
                           "mean_difference_baseline_minus_reference": mean_diff, "median_paired_difference": median_diff,
                           "ci95_mean_difference": ci, "effect_size_paired_dz": effect if spec["kind"] == "continuous" else None,
                           "discordant_reference_only_successes": a_only, "discordant_baseline_only_successes": b_only,
                           "raw_p_value": raw_p, "method": method, "assumptions": test_assumptions, "status": "exploratory" if n < MIN_INFERENTIAL_TRIALS else "tested"})
    for metric in metric_specs:
        indexes = [i for i, item in enumerate(output) if item["metric"] == metric]
        adjusted = _holm([output[i]["raw_p_value"] for i in indexes])
        for index, p_adjusted in zip(indexes, adjusted):
            output[index]["holm_adjusted_p_value"] = p_adjusted
            output[index]["statistically_significant_after_holm"] = (p_adjusted < .05) if output[index]["n_pairs"] >= MIN_INFERENTIAL_TRIALS and p_adjusted is not None else None
    return {"version": STATISTICS_VERSION, "status": "AVAILABLE", "reference_baseline": reference_baseline,
            "protocol_version": protocol["version"], "minimum_trials_for_inferential_label": MIN_INFERENTIAL_TRIALS,
            "multiple_testing_correction": "Holm within each metric across contrasts against the reference",
            "comparisons": output}
