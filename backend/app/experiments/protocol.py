"""Versioned, self-describing protocol metadata for synthetic runs."""
from __future__ import annotations

import platform
import sys
import hashlib
from typing import Any

from app.privacy.policy import (AdaptivePolicyConfig, EXPERIMENT_CUMULATIVE_PENALTY,
                                EXPERIMENT_POLICY_ID, EXPERIMENT_RISK_PENALTY)

PROTOCOL_VERSION = "privacyguard-research-protocol-v2"
DATASET_VERSION = "synthetic-employee-generator-v1"
SCENARIO_ESTIMATOR_VERSIONS = {
    "difference": "difference-paired-query-estimator-v1",
    "repeated": "repeated-unique-release-mean-v2",
    "narrowing": "fixed-script-final-count-v1",
    "overlapping": "overlap-inclusion-exclusion-v1",
}

SCENARIO_PROTOCOLS: dict[str, dict[str, str]] = {
    "difference": {
        "objective": "Individual contribution inference",
        "target": "One selected synthetic employee salary contribution",
        "estimator": "Engineering salary SUM minus the same SUM excluding the selected employee",
        "success": "absolute error <= relative_tolerance * max(abs(target), 1)",
        "interpretation": "Contribution inference only; not membership inference.",
    },
    "repeated": {
        "objective": "Aggregate reconstruction",
        "target": "Full synthetic dataset salary SUM",
        "estimator": "Arithmetic mean of unique independent release outputs; exact-cache reuses are represented once",
        "success": "absolute error <= relative_tolerance * max(abs(target), 1)",
        "interpretation": "Population aggregate reconstruction; not individual attribute inference.",
    },
    "narrowing": {
        "objective": "Fixed-scripted cohort-size reconstruction",
        "target": "Count in the final Engineering/Senior/age>=60/North cohort",
        "estimator": "The final predeclared progressively narrowed COUNT observation",
        "success": "absolute count error <= absolute_count_tolerance",
        "interpretation": "The query sequence is fixed, not interactively selected; not membership inference.",
    },
    "overlapping": {
        "objective": "Overlapping-query aggregate reconstruction",
        "target": "Salary SUM for Engineering AND North",
        "estimator": "Engineering SUM + North SUM - (Engineering UNION North) SUM",
        "success": "absolute error <= relative_tolerance * max(abs(target), 1)",
        "interpretation": "Aggregate intersection reconstruction; not individual attribute or membership inference.",
    },
}


def make_protocol(configuration: dict[str, Any]) -> dict[str, Any]:
    scenario = str(configuration["scenario"])
    seed = int(configuration["seed"])
    trial_count = int(configuration["trials"])
    trial_seed_strategy = str(configuration.get("trial_seed_strategy", "matched_sequential"))
    if trial_seed_strategy == "matched_sequential":
        trial_seeds = [seed + 1_000_003 * index for index in range(trial_count)]
    else:
        trial_seeds = [int.from_bytes(hashlib.sha256(f"{seed}:{index}:trial".encode("ascii")).digest()[:4], "big") for index in range(trial_count)]
    baselines = list(configuration.get("baselines", []))
    epsilon = float(configuration["epsilon"])
    adaptive_epsilon_min = float(configuration.get("adaptive_epsilon_min") if configuration.get("adaptive_epsilon_min") is not None else min(0.1, epsilon))
    role_factors = [1.0, 0.75, 0.6]
    baseline_configs = []
    for baseline in baselines:
        baseline_configs.append({
            "id": baseline,
            # M3 scales this configured base epsilon by its documented role
            # factor; retaining the base value makes the comparison auditable.
            "configured_epsilon": epsilon if baseline in {"M1", "M2", "M3", "M4", "M5"} else None,
            "budget_epsilon_per_trial": float(configuration["budget_epsilon"]) if baseline in {"M2", "M3", "M4", "M5"} else None,
            "role_factors": role_factors if baseline == "M3" else None,
            "exact_cache": baseline in {"M4", "M5"},
            "adaptive_policy": ({
                "policy_id": EXPERIMENT_POLICY_ID,
                "cache_policy": "allocate once per exact query identity per trial; exact repeats reuse the stored release and its original epsilon",
                "ablation_mode": configuration.get("ablation_mode", "full"),
                "epsilon_min": adaptive_epsilon_min,
                "epsilon_max": epsilon,
                "risk_penalty": float(configuration.get("adaptive_risk_penalty", EXPERIMENT_RISK_PENALTY)),
                "cumulative_penalty": float(configuration.get("adaptive_cumulative_penalty", EXPERIMENT_CUMULATIVE_PENALTY)),
                "risk_weights": dict(AdaptivePolicyConfig().weights.__dict__),
            } if baseline == "M5" else None),
            "accounting": "nominal_uncertified" if baseline != "M0" else "not_applicable_raw_reference",
        })
    request_limit = int(configuration["repetitions"]) if scenario == "repeated" else {"difference": 2, "narrowing": 3, "overlapping": 3}[scenario]
    return {
        "version": PROTOCOL_VERSION,
        "scenario_identifier": scenario,
        "scenario": SCENARIO_PROTOCOLS[scenario],
        "dataset": {
            "identifier": "synthetic-employees",
            "version": DATASET_VERSION,
            "row_count": int(configuration["dataset_size"]),
            "seed": seed,
            "registered_dataset_access": False,
        },
        "workload": {
            "definition_version": "synthetic-workloads-v3",
            "repeat_query_mode": configuration.get("repeat_query_mode", "identical"),
            "repetitions": int(configuration["repetitions"]),
            "history_depth": int(configuration.get("history_depth", 0)),
            "ablation_mode": configuration.get("ablation_mode", "full"),
            "max_queries_per_trial": request_limit,
        },
        "attack_parameters": {
            "relative_success_tolerance": float(configuration.get("attack_relative_success_tolerance", 0.05)),
            "absolute_count_success_tolerance": float(configuration.get("narrowing_absolute_success_tolerance", 1.0)),
            "success_threshold_rule": SCENARIO_PROTOCOLS[scenario]["success"],
            "estimator_version": SCENARIO_ESTIMATOR_VERSIONS[scenario],
            "repeated_cache_handling": "cached requests reference the original release and are not additional estimator samples" if scenario == "repeated" else None,
        },
        "trials": {
            "count": trial_count,
            "dataset_seed": seed,
            "trial_seed_strategy": trial_seed_strategy,
            "trial_seeds": trial_seeds,
            "noise_seed_derivation": "trial_seed + 10007 * zero_based_request_index" if trial_seed_strategy == "matched_sequential" else "first 32 bits of SHA-256(trial_seed:zero_based_request_index)",
            "shared_across_baselines": True,
        },
        "baselines": baseline_configs,
        "privacy_parameters": {
            "fixed_epsilon": epsilon,
            "nominal_budget_per_trial": float(configuration["budget_epsilon"]),
            "adaptive_policy_version": EXPERIMENT_POLICY_ID,
            "adaptive_epsilon_min": adaptive_epsilon_min,
            "adaptive_risk_penalty": float(configuration.get("adaptive_risk_penalty", EXPERIMENT_RISK_PENALTY)),
            "adaptive_cumulative_penalty": float(configuration.get("adaptive_cumulative_penalty", EXPERIMENT_CUMULATIVE_PENALTY)),
            "mechanism_version": "seeded-experiment-laplace-v1",
            "privacy_status": "nominal_uncertified; no formal end-to-end guarantee established",
        },
        "metric_definitions": {
            "version": "comparative-metrics-v5",
            "relative_error_denominator_threshold": 1.0,
            "attack_success_denominator": "completed attack estimates only; an unanswered estimate is not a success or failure",
            "aggregate_error_denominator": "successfully answered generated requests only",
            "attack_observation_count": "answered query requests; cached copies included as requests",
            "attack_independent_observation_count": "independent protected releases available to the attacker; cached copies counted once; raw M0 responses are not protected releases",
            "unique_attack_observation_count": "unique response sources used by the scenario estimator; exact-cache copies share one source",
            "unique_noise_sample_count": "distinct seeded noise-generating releases; raw M0 responses have no noise sample",
        },
        "statistical_methodology": {
            "binary_ci": "95% Wilson score interval",
            "continuous_ci": "95% Student-t interval for trial means through n=31; normal-limit approximation thereafter",
            "paired_continuous": "paired percentile bootstrap CI and sign-flip randomization test; Monte Carlo for n>16",
            "paired_binary": "exact two-sided McNemar test and paired bootstrap CI for risk difference",
            "multiple_testing": "Holm adjustment within each metric across reference-baseline contrasts",
            "minimum_trials_for_inferential_label": 20,
            "small_samples": "exploratory; no inferential significance label below 20 paired trials",
        },
        "execution_environment": {"python": sys.version.split()[0], "platform": platform.platform()},
    }
