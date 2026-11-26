from __future__ import annotations

from dataclasses import dataclass
import math
import sys
import hashlib
from time import perf_counter, perf_counter_ns
from typing import Callable

from app.datasets.generation import iter_employee_rows
from app.experiments.statistics import wilson_score_interval
from app.privacy.laplace import apply_laplace_for_synthetic_experiment
from app.privacy.policy import (AdaptivePolicyConfig, EXPERIMENT_CUMULATIVE_PENALTY,
                                EXPERIMENT_POLICY_ID, EXPERIMENT_RISK_PENALTY,
                                allocate_epsilon_decision, assess_risk)
from app.experiments.protocol import PROTOCOL_VERSION, SCENARIO_ESTIMATOR_VERSIONS, SCENARIO_PROTOCOLS


BASELINES = ("M0", "M1", "M2", "M3", "M4", "M5")
BASELINE_NAMES = {
    "M0": "Raw SQL / no privacy",
    "M1": "Fixed-ε DP, uncapped composition",
    "M2": "Fixed-ε DP with shared budget",
    "M3": "Role-aware fixed DP with shared budget",
    "M4": "Cache-only fixed DP with shared budget",
    "M5": "PrivacyGuard history-aware adaptive DP",
}
SCENARIOS = ("difference", "repeated", "narrowing", "overlapping")
METRIC_DEFINITION_VERSION = "comparative-metrics-v5"
BASELINE_DEFINITION_VERSION = "matched-six-baselines-v2"
RELATIVE_ERROR_DENOMINATOR_THRESHOLD = 1.0
EXPERIMENT_ENGINE_VERSION = "synthetic-engine-v6"
WORKLOAD_DEFINITION_VERSION = "synthetic-workloads-v3"
ATTACK_DEFINITION_VERSION = "attack-scenarios-v4"
MECHANISM_VERSION = "seeded-experiment-laplace-v1"
LEGACY_BASELINE_MAP = {"B0": "M0", "B1": "M1", "B2": "M2", "B3": "M3", "B4": "M5"}
SCENARIO_DEFINITIONS = SCENARIO_PROTOCOLS


@dataclass(frozen=True)
class QuerySpec:
    key: str
    label: str
    columns: frozenset[str]
    predicate_count: int
    query_type: str
    sensitivity: float
    truth: float
    cohort_size: int
    scan_ms: float


def _build_workload(scenario: str, rows: list[dict[str, object]]) -> tuple[list[QuerySpec], float, int, str]:
    def aggregate(key: str, label: str, predicate: Callable[[dict[str, object]], bool], columns: set[str], count: int, query_type: str = "sum") -> QuerySpec:
        started = perf_counter()
        selected = [row for row in rows if predicate(row)]
        value = float(len(selected)) if query_type == "count" else float(sum(int(row["salary"]) for row in selected))
        return QuerySpec(key, label, frozenset(columns), count, query_type, 1.0 if query_type == "count" else 300_000.0, value, len(selected), (perf_counter() - started) * 1000)

    if scenario == "difference":
        department = "Engineering"
        members = [row for row in rows if row["department"] == department]
        if not members:
            department = str(rows[0]["department"])
            members = [row for row in rows if row["department"] == department]
        target_id = members[len(members) // 2]["employee_id"]
        target_value = float(members[len(members) // 2]["salary"])
        cohort = aggregate("difference:cohort", f"SUM salary in {department}", lambda row: row["department"] == department, {"salary", "department"}, 1)
        excluding = aggregate("difference:excluding-target", f"SUM salary in {department} excluding one synthetic row", lambda row: row["department"] == department and row["employee_id"] != target_id, {"salary", "department", "employee_id"}, 2)
        target_ordinal = int(str(members[len(members) // 2]["employee_id"]).rsplit("-", 1)[1])
        return [cohort, excluding], target_value, 1, f"synthetic-employee-ordinal:{target_ordinal}"

    if scenario == "repeated":
        query = aggregate("repeated:all-salaries", "SUM salary over synthetic dataset", lambda _row: True, {"salary"}, 0)
        return [query], query.truth, query.cohort_size, "synthetic-dataset:salary-sum"

    if scenario == "narrowing":
        clauses = [
            ("Engineering", lambda row: row["department"] == "Engineering", {"department"}),
            ("Engineering AND Senior", lambda row: row["department"] == "Engineering" and row["designation"] == "Senior", {"department", "designation"}),
            ("Engineering AND Senior AND age >= 60 AND North", lambda row: row["department"] == "Engineering" and row["designation"] == "Senior" and int(row["age"]) >= 60 and row["location"] == "North", {"department", "designation", "age", "location"}),
        ]
        specs = [aggregate(f"narrowing:{i}", label, predicate, set(columns) | {"employee_id"}, i + 1, "count") for i, (label, predicate, columns) in enumerate(clauses)]
        return specs, specs[-1].truth, int(specs[-1].truth), "synthetic-cohort:engineering-senior-age60-north"

    if scenario == "overlapping":
        a = aggregate("overlap:a", "SUM salary for Engineering", lambda row: row["department"] == "Engineering", {"salary", "department"}, 1)
        b = aggregate("overlap:north", "SUM salary for North location", lambda row: row["location"] == "North", {"salary", "location"}, 1)
        union = aggregate("overlap:union", "SUM salary for Engineering OR North", lambda row: row["department"] == "Engineering" or row["location"] == "North", {"salary", "department", "location"}, 2)
        intersection_value = a.truth + b.truth - union.truth
        intersection_size = max(0, int(a.cohort_size + b.cohort_size - union.cohort_size))
        return [a, b, union], intersection_value, intersection_size, "synthetic-cohort:engineering-and-north"
    raise ValueError("unsupported synthetic scenario")


def _noise(value: float, sensitivity: float, epsilon: float, seed: int) -> float:
    return apply_laplace_for_synthetic_experiment(value, sensitivity, epsilon, seed=seed)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _mean_std_ci(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "standard_deviation": None, "p95": None, "ci95_lower": None, "ci95_upper": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"mean": mean, "median": _percentile(values, .5), "standard_deviation": None, "p95": _percentile(values, .95), "ci95_lower": None, "ci95_upper": None}
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    std = math.sqrt(variance)
    # Student-t critical values for 95% two-sided intervals (df 1..30),
    # followed by the normal limit for larger samples.
    t95 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
           2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
           2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)
    critical = t95[len(values) - 2] if len(values) <= 31 else 1.96
    margin = critical * std / math.sqrt(len(values))
    return {"mean": mean, "median": _percentile(values, .5), "standard_deviation": std,
            "p95": _percentile(values, .95), "ci95_lower": mean - margin, "ci95_upper": mean + margin}


def _wilson_interval(successes: int, attempts: int) -> list[float | None]:
    """Compatibility alias for the shared Wilson score implementation."""
    return wilson_score_interval(successes, attempts)


def _relative_error(absolute_error: float, truth: float) -> float | None:
    if not math.isfinite(absolute_error) or not math.isfinite(truth) or abs(truth) < RELATIVE_ERROR_DENOMINATOR_THRESHOLD:
        return None
    return absolute_error / abs(truth)


def _unique_attack_observations(observations: list[dict[str, object]]) -> tuple[list[float], int, list[str]]:
    """Return one value per independently generated source, never per cache hit."""
    by_source: dict[str, float] = {}
    noise_sources: set[str] = set()
    for item in observations:
        value = item.get("value")
        status = item.get("request_status")
        source = item.get("attack_source_id")
        if isinstance(source, str) and source and isinstance(value, (int, float)) and math.isfinite(float(value)):
            by_source.setdefault(source, float(value))
            if status in {"released", "cached"}:
                noise_sources.add(source)
    return list(by_source.values()), len(noise_sources), list(by_source)


def _cache_provenance_is_consistent(requests: list[dict[str, object]]) -> bool:
    """Check cache-hit lineage, query/epsilon identity, and zero additional charge."""
    released: dict[str, dict[str, object]] = {}
    for request in sorted(requests, key=lambda row: int(row.get("request_index", 0))):
        status = request.get("request_status")
        release_id = request.get("release_id")
        if status == "released":
            if not isinstance(release_id, str) or not release_id or release_id in released:
                return False
            if request.get("noise_sample_id") != release_id:
                return False
            if not math.isclose(float(request.get("epsilon_charged") or 0.0), float(request.get("selected_epsilon") or 0.0), rel_tol=1e-9, abs_tol=1e-12):
                return False
            released[release_id] = request
        elif status == "cached":
            original = released.get(str(release_id))
            if original is None:
                return False
            if request.get("noise_sample_id") != release_id or request.get("query_key") != original.get("query_key"):
                return False
            if not math.isclose(float(request.get("selected_epsilon") or 0.0), float(original.get("selected_epsilon") or 0.0), rel_tol=1e-9, abs_tol=1e-12):
                return False
            if float(request.get("epsilon_charged") or 0.0) != 0.0:
                return False
        elif status == "budget_rejected" and (release_id is not None or request.get("noise_sample_id") is not None or float(request.get("epsilon_charged") or 0.0) != 0.0):
            return False
    return True


def _metric_states(metrics: dict[str, object]) -> dict[str, dict[str, str | None]]:
    """Represent every scalar metric explicitly without collapsing null into zero."""
    states: dict[str, dict[str, str | None]] = {}
    for key, value in metrics.items():
        if key in {"metric_states", "measurements", "request_measurements", "scenario_definition"}:
            continue
        if value is None:
            state = "NOT_APPLICABLE" if key in {"mean_selected_epsilon", "budget_utilization_percentage"} and metrics.get("baseline") == "M0" else "NOT_MEASURED"
            reason = "This metric does not apply to the raw unprotected baseline." if state == "NOT_APPLICABLE" else "No valid observation was available."
        elif isinstance(value, bool):
            state = "MEASURED"
            reason = None
        elif isinstance(value, (int, float)):
            state = "MEASURED" if math.isfinite(float(value)) else "INVALID"
            reason = None if state == "MEASURED" else "The stored value is not finite."
        else:
            continue
        states[key] = {"state": state, "reason": reason}
    if metrics.get("baseline") == "M0":
        for key in ("nominal_cumulative_epsilon", "mean_nominal_epsilon_per_trial", "initial_nominal_budget_per_trial", "remaining_nominal_budget_per_trial_mean", "mean_budget_utilization"):
            states[key] = {"state": "NOT_APPLICABLE", "reason": "M0 is an unprotected reference and does not use a privacy budget."}
    if metrics.get("baseline") == "M0":
        states["independent_releases"] = {"state": "NOT_APPLICABLE", "reason": "M0 does not issue protected releases; its raw synthetic query outputs are counted as requests."}
    if metrics.get("baseline") in {"M0", "M1", "M2", "M3"}:
        for key in ("exact_cache_hits", "exact_cache_hit_rate", "exact_cache_reuse_consistent", "cache_consistency_checks"):
            states[key] = {"state": "NOT_APPLICABLE", "reason": "This baseline does not implement exact release caching."}
    return states


def _risk_for(spec: QuerySpec, previous: list[QuerySpec], repeats: int, ablation: str = "full"):
    history_started = perf_counter_ns()
    overlap = 0.0
    for old in previous:
        union = spec.columns | old.columns
        if union:
            overlap = max(overlap, len(spec.columns & old.columns) / len(union))
    history_lookup_ms = (perf_counter_ns() - history_started) / 1_000_000
    policy_started = perf_counter_ns()
    sensitivity = min(spec.sensitivity / 300_000.0, 1.0)
    data_sensitivity = 0.75 if "salary" in spec.columns else 0.35
    predicate_signal = min(spec.predicate_count / 4.0, 1.0)
    repetition_signal = min(repeats / 5.0, 1.0)
    if ablation == "no_predicate_narrowing":
        predicate_signal = 0.0
    if ablation == "no_repetition":
        repetition_signal = 0.0
    narrowness = 0.5 * predicate_signal + 0.5 * repetition_signal
    if ablation == "no_history_overlap":
        overlap = 0.0
    query_type_risk = 0.2 if spec.query_type == "count" else 0.8
    if ablation == "no_query_type":
        query_type_risk = 0.5
    assessment = assess_risk(query_sensitivity=sensitivity, data_sensitivity=data_sensitivity, history=overlap, narrowness=narrowness, query_type=query_type_risk)
    policy_ms = (perf_counter_ns() - policy_started) / 1_000_000
    return assessment, overlap, repetition_signal, history_lookup_ms, policy_ms


def _estimate_dataset_bytes(rows: list[dict[str, object]]) -> int:
    total = sys.getsizeof(rows)
    for row in rows:
        total += sys.getsizeof(row)
        total += sum(sys.getsizeof(key) + sys.getsizeof(value) for key, value in row.items())
    return total


def run_comparison(config: dict[str, object]) -> list[dict[str, object]]:
    """Evaluate selected baselines on one reproducible synthetic dataset only.

    Persistable output includes minimal owner-scoped synthetic-only target and
    estimate evidence for independent validation; query aggregate observations
    and synthetic employee records are never persisted.
    """
    scenario = str(config["scenario"])
    size = int(config["dataset_size"])
    trials = int(config["trials"])
    repetitions = int(config["repetitions"])
    seed = int(config["seed"])
    fixed_epsilon = float(config["epsilon"])
    budget_limit = float(config["budget_epsilon"])
    adaptive_epsilon_min = float(config.get("adaptive_epsilon_min") if config.get("adaptive_epsilon_min") is not None else min(0.1, fixed_epsilon))
    selected = [LEGACY_BASELINE_MAP.get(str(item), str(item)) for item in config["baselines"]]
    repeat_query_mode = str(config.get("repeat_query_mode", "identical"))
    history_depth = int(config.get("history_depth", 0))
    ablation_mode = str(config.get("ablation_mode", "full"))
    seed_strategy = str(config.get("trial_seed_strategy", "matched_sequential"))
    if ablation_mode not in {"full", "no_history_overlap", "no_repetition", "no_predicate_narrowing", "no_query_type"}:
        raise ValueError("unsupported experimental ablation mode")
    if history_depth not in {0, 5, 10, 25, 50}:
        raise ValueError("history_depth must be 0, 5, 10, 25, or 50")
    if seed_strategy not in {"matched_sequential", "matched_hashed"}:
        raise ValueError("unsupported matched trial seed strategy")
    rows = list(iter_employee_rows(1, size, seed))
    specs, attack_truth, at_risk_group_size, attack_target_reference = _build_workload(scenario, rows)
    if seed_strategy == "matched_sequential":
        trial_seed_values = [seed + 1_000_003 * index for index in range(trials)]
    else:
        trial_seed_values = [int.from_bytes(hashlib.sha256(f"{seed}:{index}:trial".encode("ascii")).digest()[:4], "big") for index in range(trials)]
    estimated_memory = _estimate_dataset_bytes(rows)
    results = []

    for baseline in selected:
        overall_started = perf_counter()
        measurements: list[dict[str, object]] = []
        request_measurements: list[dict[str, object]] = []
        all_aggregate_errors: list[float] = []
        attack_errors: list[float] = []
        relative_attack_errors: list[float] = []
        success_flags: list[float] = []
        small_group_flags: list[float] = []
        selected_epsilons: list[float] = []
        risks: list[float] = []
        overlaps: list[float] = []
        repeats_signals: list[float] = []
        latency_samples: list[float] = []
        overhead_samples: list[float] = []
        trial_aggregate_maes: list[float] = []
        trial_aggregate_rmses: list[float] = []
        trial_latency_means: list[float] = []
        trial_overhead_means: list[float] = []
        relative_aggregate_errors: list[float] = []
        latency_medians: list[float] = []
        latency_p95s: list[float] = []
        attack_squared_errors: list[float] = []
        exact_cache_hits = 0
        exact_cache_consistent = True
        exact_cache_consistency_checks = 0
        answerable_requests = 0
        budget_rejected_requests = 0
        history_lookup_samples: list[float] = []
        risk_policy_samples: list[float] = []
        release_execution_samples: list[float] = []
        cumulative_spend = 0.0
        independent_releases = 0
        rejected = 0
        request_count = 0
        mean_utilizations: list[float] = []

        for trial in range(trials):
            cache: dict[tuple[str, float], tuple[float, str]] = {}
            # M5 allocates once for a canonical exact request in each trial.
            # Later exact repeats reuse that release and its original epsilon.
            adaptive_epsilon_by_query: dict[str, float] = {}
            spent = 0.0
            previous: list[QuerySpec] = [
                QuerySpec(f"history:{trial}:{i}", specs[i % len(specs)].label,
                          specs[i % len(specs)].columns, specs[i % len(specs)].predicate_count,
                          specs[i % len(specs)].query_type, specs[i % len(specs)].sensitivity,
                          specs[i % len(specs)].truth, specs[i % len(specs)].cohort_size,
                          specs[i % len(specs)].scan_ms)
                for i in range(history_depth)
            ]
            shape_repeats: dict[str, int] = {}
            for previous_spec in previous:
                shape_repeats[previous_spec.label] = shape_repeats.get(previous_spec.label, 0) + 1
            if scenario == "repeated" and repeat_query_mode == "equivalent_variants":
                base = specs[0]
                query_order = [QuerySpec(f"{base.key}:variant:{i}", base.label, base.columns, base.predicate_count, base.query_type, base.sensitivity, base.truth, base.cohort_size, base.scan_ms) for i in range(repetitions)]
            else:
                query_order = [specs[0]] * repetitions if scenario == "repeated" else specs
            responses: dict[str, list[float]] = {spec.key: [] for spec in query_order}
            attack_observations: list[dict[str, object]] = []
            trial_errors: list[float] = []
            trial_latencies: list[float] = []
            trial_overheads: list[float] = []
            trial_rejected = 0
            trial_answerable = 0
            trial_budget_rejected = 0
            trial_releases = 0
            trial_cache_hits = 0
            trial_started_ns = perf_counter_ns()

            for request_index, spec in enumerate(query_order):
                request_count += 1
                request_started_ns = perf_counter_ns()
                risk, overlap, repeat_signal, history_lookup_ms, risk_policy_ms = _risk_for(
                    spec, previous, shape_repeats.get(spec.label, 0), ablation_mode if baseline == "M5" else "full"
                )
                history_lookup_samples.append(history_lookup_ms)
                risk_policy_samples.append(risk_policy_ms)
                risks.append(risk.overall)
                overlaps.append(overlap)
                repeats_signals.append(repeat_signal)

                if baseline == "M0":
                    output = spec.truth
                    responses[spec.key].append(output)
                    observation_id = f"M0:trial-{trial + 1}:request-{request_index + 1}"
                    attack_source_id = f"raw:trial-{trial + 1}:{spec.key}"
                    attack_observations.append({"value": output, "request_status": "raw_unprotected", "observation_id": observation_id, "attack_source_id": attack_source_id, "release_id": None, "noise_sample_id": None})
                    error = abs(output - spec.truth)
                    all_aggregate_errors.append(error)
                    trial_errors.append(error)
                    relative_error = _relative_error(error, spec.truth)
                    if relative_error is not None:
                        relative_aggregate_errors.append(relative_error)
                    overhead_ms = (perf_counter_ns() - request_started_ns) / 1_000_000
                    latency_samples.append(overhead_ms + spec.scan_ms)
                    overhead_samples.append(overhead_ms)
                    trial_latencies.append(overhead_ms + spec.scan_ms)
                    trial_overheads.append(overhead_ms)
                    answerable_requests += 1
                    trial_answerable += 1
                    request_measurements.append({"trial": trial + 1, "request_index": request_index + 1, "query_key": spec.key, "request_status": "raw_unprotected", "observation_id": observation_id, "attack_source_id": attack_source_id, "release_id": None, "noise_sample_id": None, "selected_epsilon": None, "epsilon_charged": 0.0, "cumulative_epsilon_spent": 0.0, "aggregate_absolute_error": error, "aggregate_relative_error": relative_error, "risk_score": risk.overall, "history_overlap": overlap, "repetition_signal": repeat_signal, "history_lookup_ms": history_lookup_ms, "risk_policy_ms": risk_policy_ms, "release_execution_ms": 0.0, "latency_ms": overhead_ms + spec.scan_ms})
                    continue

                if baseline in {"M1", "M2", "M4"}:
                    epsilon = fixed_epsilon
                elif baseline == "M3":
                    role_factor = (1.0, 0.75, 0.6)[request_index % 3]
                    epsilon = max(0.1, fixed_epsilon * role_factor)
                elif baseline == "M5":
                    if spec.key in adaptive_epsilon_by_query:
                        epsilon = adaptive_epsilon_by_query[spec.key]
                    else:
                        adaptive_config = AdaptivePolicyConfig(
                            epsilon_min=adaptive_epsilon_min,
                            epsilon_max=fixed_epsilon,
                            risk_penalty=float(config.get("adaptive_risk_penalty", EXPERIMENT_RISK_PENALTY)),
                            cumulative_penalty=float(config.get("adaptive_cumulative_penalty", EXPERIMENT_CUMULATIVE_PENALTY)),
                            policy_id=EXPERIMENT_POLICY_ID,
                        )
                        decision = allocate_epsilon_decision(
                            assessment=risk,
                            cumulative_fraction=min(1.0, spent / budget_limit),
                            remaining_epsilon=max(0.0, budget_limit - spent),
                            config=adaptive_config,
                        )
                        epsilon = decision.nominal_epsilon
                else:
                    epsilon = fixed_epsilon

                selected_epsilons.append(epsilon)
                cache_key = (spec.key, epsilon)
                cache_enabled = baseline in {"M4", "M5"}
                observation_id = f"{baseline}:trial-{trial + 1}:request-{request_index + 1}"
                release_id: str | None = None
                noise_sample_id: str | None = None
                if cache_enabled and cache_key in cache:
                    output, release_id = cache[cache_key]
                    noise_sample_id = release_id
                    is_new_release = False
                    exact_cache_hits += 1
                    trial_cache_hits += 1
                    exact_cache_consistency_checks += 1
                else:
                    if baseline in {"M2", "M3", "M4", "M5"} and epsilon > budget_limit - spent + 1e-12:
                        rejected += 1
                        trial_rejected += 1
                        budget_rejected_requests += 1
                        trial_budget_rejected += 1
                        latency = (perf_counter_ns() - request_started_ns) / 1_000_000
                        latency_samples.append(latency)
                        overhead_samples.append(latency)
                        request_measurements.append({"trial": trial + 1, "request_index": request_index + 1, "query_key": spec.key, "request_status": "budget_rejected", "observation_id": observation_id, "attack_source_id": None, "release_id": None, "noise_sample_id": None, "selected_epsilon": epsilon, "epsilon_charged": 0.0, "cumulative_epsilon_spent": spent, "aggregate_absolute_error": None, "aggregate_relative_error": None, "risk_score": risk.overall, "history_overlap": overlap, "repetition_signal": repeat_signal, "history_lookup_ms": history_lookup_ms, "risk_policy_ms": risk_policy_ms, "release_execution_ms": 0.0, "latency_ms": latency})
                        continue
                    if seed_strategy == "matched_hashed":
                        seed_material = f"{trial_seed_values[trial]}:{request_index}".encode("ascii")
                        noise_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:4], "big")
                    else:
                        noise_seed = trial_seed_values[trial] + 10_007 * request_index
                    release_started_ns = perf_counter_ns()
                    output = _noise(spec.truth, spec.sensitivity, epsilon, noise_seed)
                    release_id = f"{baseline}:trial-{trial + 1}:release-{trial_releases + 1}"
                    noise_sample_id = release_id
                    release_execution_ms = (perf_counter_ns() - release_started_ns) / 1_000_000
                    release_execution_samples.append(release_execution_ms)
                    if cache_enabled:
                        cache[cache_key] = (output, release_id)
                    if baseline == "M5":
                        adaptive_epsilon_by_query[spec.key] = epsilon
                    is_new_release = True
                    spent += epsilon
                    cumulative_spend += epsilon
                    independent_releases += 1
                    trial_releases += 1
                    shape_repeats[spec.label] = shape_repeats.get(spec.label, 0) + 1
                    previous.append(spec)
                if not is_new_release:
                    release_execution_ms = 0.0

                responses[spec.key].append(output)
                request_status = "released" if is_new_release else "cached"
                attack_observations.append({"value": output, "request_status": request_status, "observation_id": observation_id, "attack_source_id": noise_sample_id, "release_id": release_id, "noise_sample_id": noise_sample_id})
                answerable_requests += 1
                trial_answerable += 1
                error = abs(output - spec.truth)
                all_aggregate_errors.append(error)
                trial_errors.append(error)
                relative_error = _relative_error(error, spec.truth)
                if relative_error is not None:
                    relative_aggregate_errors.append(relative_error)
                latency = (perf_counter_ns() - request_started_ns) / 1_000_000
                latency_samples.append(latency + (spec.scan_ms if is_new_release else 0.0))
                overhead_samples.append(latency)
                trial_latencies.append(latency + (spec.scan_ms if is_new_release else 0.0))
                trial_overheads.append(latency)
                request_measurements.append({"trial": trial + 1, "request_index": request_index + 1, "query_key": spec.key, "request_status": request_status, "observation_id": observation_id, "attack_source_id": noise_sample_id, "release_id": release_id, "noise_sample_id": noise_sample_id, "selected_epsilon": epsilon, "epsilon_charged": epsilon if is_new_release else 0.0, "cumulative_epsilon_spent": spent, "aggregate_absolute_error": error, "aggregate_relative_error": relative_error, "risk_score": risk.overall, "history_overlap": overlap, "repetition_signal": repeat_signal, "history_lookup_ms": history_lookup_ms, "risk_policy_ms": risk_policy_ms, "release_execution_ms": release_execution_ms, "latency_ms": latency + (spec.scan_ms if is_new_release else 0.0)})

            if baseline in {"M4", "M5"} and trial_cache_hits:
                trial_request_rows = [item for item in request_measurements if item.get("trial") == trial + 1]
                exact_cache_consistent = exact_cache_consistent and _cache_provenance_is_consistent(trial_request_rows)

            unique_attack_values, trial_noise_sample_count, source_ids = _unique_attack_observations(attack_observations)
            trial_attack_independent_observation_count = trial_noise_sample_count
            trial_unique_attack_observation_count = len(source_ids)
            if scenario == "difference" and all(len(responses[spec.key]) == 1 for spec in specs):
                estimate = responses[specs[0].key][0] - responses[specs[1].key][0]
            elif scenario == "repeated" and len(attack_observations) == repetitions and unique_attack_values:
                estimate = sum(unique_attack_values) / len(unique_attack_values)
            elif scenario == "narrowing" and all(len(responses[spec.key]) == 1 for spec in specs):
                estimate = responses[specs[-1].key][-1]
            elif scenario == "overlapping" and all(responses[spec.key] for spec in specs):
                estimate = responses[specs[0].key][0] + responses[specs[1].key][0] - responses[specs[2].key][0]
            else:
                estimate = None

            if estimate is not None:
                inference_error = abs(estimate - attack_truth)
                relative_error = _relative_error(inference_error, attack_truth)
                attack_errors.append(inference_error)
                if relative_error is not None:
                    relative_attack_errors.append(relative_error)
                attack_squared_errors.append(inference_error * inference_error)
                threshold = float(config.get("narrowing_absolute_success_tolerance", 1.0)) if scenario == "narrowing" else float(config.get("attack_relative_success_tolerance", 0.05)) * max(abs(attack_truth), 1.0)
                success = 1.0 if inference_error <= threshold else 0.0
                success_flags.append(success)
                small_group_flags.append(1.0 if at_risk_group_size <= 5 and success else 0.0)
            mean_utilizations.append(spent / budget_limit)
            trial_aggregate_mae = sum(trial_errors) / len(trial_errors) if trial_errors else None
            trial_aggregate_rmse = math.sqrt(sum(error * error for error in trial_errors) / len(trial_errors)) if trial_errors else None
            if trial_aggregate_mae is not None:
                trial_aggregate_maes.append(trial_aggregate_mae)
                trial_aggregate_rmses.append(trial_aggregate_rmse)
            trial_latency_means.append(sum(trial_latencies) / len(trial_latencies) if trial_latencies else 0.0)
            trial_overhead_means.append(sum(trial_overheads) / len(trial_overheads) if trial_overheads else 0.0)
            latency_medians.append(_percentile(trial_latencies, .5) or 0.0)
            latency_p95s.append(_percentile(trial_latencies, .95) or 0.0)
            trial_requests = repetitions if scenario == "repeated" else len(specs)
            success_threshold = float(config.get("narrowing_absolute_success_tolerance", 1.0)) if scenario == "narrowing" else float(config.get("attack_relative_success_tolerance", 0.05)) * max(abs(attack_truth), 1.0)
            attack_evidence = None if estimate is None else {
                "evidence_scope": "synthetic_only_owner_scoped",
                "target_reference_id": attack_target_reference,
                "target_value": attack_truth,
                "inferred_value": estimate,
                "absolute_error": abs(estimate - attack_truth),
                "relative_error_fraction": _relative_error(abs(estimate - attack_truth), attack_truth),
                "relative_error_denominator": abs(attack_truth) if abs(attack_truth) >= RELATIVE_ERROR_DENOMINATOR_THRESHOLD else None,
                "success_threshold": success_threshold,
                "success": bool(success),
                "estimator_version": SCENARIO_ESTIMATOR_VERSIONS[scenario],
                "attack_observation_count": len(attack_observations),
                "attack_independent_observation_count": trial_attack_independent_observation_count,
                "unique_attack_observation_count": trial_unique_attack_observation_count,
                "unique_noise_sample_count": trial_noise_sample_count,
                "observation_source_ids": source_ids,
            }
            measurements.append({
                "trial": trial + 1,
                "request_count": trial_requests,
                "independent_releases": trial_releases,
                "exact_cache_hits": trial_cache_hits,
                "nominal_epsilon_spent": spent,
                "budget_utilization": spent / budget_limit,
                "attack_absolute_error": None if estimate is None else abs(estimate - attack_truth),
                "attack_relative_error": None if estimate is None else _relative_error(abs(estimate - attack_truth), attack_truth),
                "attack_observation_count": len(attack_observations),
                "attack_independent_observation_count": trial_attack_independent_observation_count,
                "unique_attack_observation_count": trial_unique_attack_observation_count,
                "unique_noise_sample_count": trial_noise_sample_count,
                "attack_estimator_version": SCENARIO_ESTIMATOR_VERSIONS[scenario],
                "attack_success_threshold": success_threshold,
                "attack_success": None if estimate is None else bool(success),
                "attack_evidence": attack_evidence,
                "trial_seed": trial_seed_values[trial],
                "small_group_exposure": None if estimate is None else bool(at_risk_group_size <= 5 and success),
                "aggregate_mae": trial_aggregate_mae,
                "aggregate_rmse": trial_aggregate_rmse,
                "query_latency_ms_mean": trial_latency_means[-1],
                "middleware_overhead_ms_mean": trial_overhead_means[-1],
                "rejected_requests": trial_rejected,
                "attack_success_count": int(success_flags[-1]) if estimate is not None else None,
                "attack_attempt_count": 1 if estimate is not None else 0,
                "answerable_requests": trial_answerable,
                "legitimate_requests": len(query_order),
                "legitimate_query_answerability_rate": trial_answerable / len(query_order) if query_order else None,
                "budget_rejected_requests": trial_budget_rejected,
                "cold_start": history_depth == 0,
                "elapsed_ms": (perf_counter_ns() - trial_started_ns) / 1_000_000,
            })

        elapsed = max((perf_counter() - overall_started) * 1000, 1e-9)
        attack_summary = _mean_std_ci(attack_errors)
        relative_summary = _mean_std_ci(relative_attack_errors)
        utility = _mean_std_ci(trial_aggregate_maes)
        aggregate_rmse_summary = _mean_std_ci(trial_aggregate_rmses)
        attack_success_summary = _mean_std_ci(success_flags)
        latency = _mean_std_ci(trial_latency_means)
        overhead = _mean_std_ci(trial_overhead_means)
        result_metrics: dict[str, object] = {
            "baseline": baseline,
            "baseline_name": BASELINE_NAMES[baseline],
            "trial_count": trials,
            "scenario": scenario,
            "dataset_size": size,
            "accounting_status": "nominal_uncertified" if baseline != "M0" else "not_applicable_raw_baseline",
            "privacy_guarantee_status": "not_formally_established_finite_precision_sampler" if baseline != "M0" else "no_privacy_protection",
            "adaptive_policy_config": ({
                "policy_id": EXPERIMENT_POLICY_ID,
                "cache_policy": "allocate once per exact query identity per trial; exact repeats reuse the stored release and its original epsilon",
                "epsilon_min": adaptive_epsilon_min,
                "epsilon_max": fixed_epsilon,
                "risk_penalty": float(config.get("adaptive_risk_penalty", EXPERIMENT_RISK_PENALTY)),
                "cumulative_penalty": float(config.get("adaptive_cumulative_penalty", EXPERIMENT_CUMULATIVE_PENALTY)),
                "risk_weights": dict(AdaptivePolicyConfig().weights.__dict__),
            } if baseline == "M5" else None),
            "nominal_cumulative_epsilon": cumulative_spend,
            "mean_nominal_epsilon_per_trial": cumulative_spend / trials,
            "independent_releases": independent_releases,
            "attack_estimator_version": SCENARIO_ESTIMATOR_VERSIONS[scenario],
            "attack_observation_count": sum(int(item.get("attack_observation_count") or 0) for item in measurements),
            "attack_independent_observation_count": sum(int(item.get("attack_independent_observation_count") or 0) for item in measurements),
            "unique_attack_observation_count": sum(int(item.get("unique_attack_observation_count") or 0) for item in measurements),
            "unique_noise_sample_count": sum(int(item.get("unique_noise_sample_count") or 0) for item in measurements),
            "exact_cache_hits": exact_cache_hits,
            "exact_cache_hit_rate": exact_cache_hits / request_count if request_count else 0.0,
            "exact_cache_reuse_consistent": exact_cache_consistent if exact_cache_consistency_checks else None,
            "cache_consistency_checks": exact_cache_consistency_checks,
            "query_answerability_rate": answerable_requests / request_count if request_count else None,
            "legitimate_query_rejection_rate": rejected / request_count if request_count else None,
            "budget_rejection_rate": budget_rejected_requests / request_count if request_count else None,
            "answerable_request_count": answerable_requests,
            "eligible_request_count": request_count,
            "rejection_counts": {"budget_exhausted": budget_rejected_requests},
            "rejection_category_coverage": {
                "budget_exhausted": {"state": "MEASURED", "reason": None},
                "invalid": {"state": "NOT_MEASURED", "reason": "Synthetic workload contains only predefined valid requests."},
                "unauthorized": {"state": "NOT_MEASURED", "reason": "Experiment engine does not simulate authorization failures."},
                "unsupported": {"state": "NOT_MEASURED", "reason": "Workload generator emits only supported synthetic aggregate requests."},
                "execution_failed": {"state": "NOT_MEASURED", "reason": "A failed engine execution fails the run instead of recording a request-level outcome."},
            },
            "budget_rejected_requests": budget_rejected_requests,
            "initial_nominal_budget_per_trial": budget_limit,
            "remaining_nominal_budget_per_trial_mean": max(0.0, budget_limit - cumulative_spend / trials),
            "budget_utilization_percentage": (cumulative_spend / trials / budget_limit * 100) if budget_limit else None,
            "attack_success_rate": sum(success_flags) / len(success_flags) if success_flags else None,
            "attack_success_count": int(sum(success_flags)) if success_flags else None,
            "attack_attempt_count": len(success_flags),
            "attack_success_standard_deviation": attack_success_summary["standard_deviation"] if success_flags else None,
            "attack_success_ci95": _wilson_interval(int(sum(success_flags)), len(success_flags)),
            "cold_start_attack_success_rate": (sum(success_flags) / len(success_flags)) if history_depth == 0 and success_flags else None,
            "inference_absolute_error": attack_summary["mean"],
            "inference_rmse": math.sqrt(sum(attack_squared_errors) / len(attack_squared_errors)) if attack_squared_errors else None,
            "inference_error_median": attack_summary["median"],
            "inference_error_standard_deviation": attack_summary["standard_deviation"],
            "inference_error_ci95": [attack_summary["ci95_lower"], attack_summary["ci95_upper"]],
            "relative_inference_error": relative_summary["mean"],
            "small_group_exposure_rate": sum(small_group_flags) / len(small_group_flags) if small_group_flags else None,
            "aggregate_mae": utility["mean"],
            "aggregate_median_absolute_error": _percentile(trial_aggregate_maes, .5),
            "aggregate_error_standard_deviation": utility["standard_deviation"],
            "aggregate_error_ci95": [utility["ci95_lower"], utility["ci95_upper"]],
            "aggregate_rmse": math.sqrt(sum(error * error for error in all_aggregate_errors) / len(all_aggregate_errors)) if all_aggregate_errors else None,
            "aggregate_rmse_trial_mean": aggregate_rmse_summary["mean"],
            "aggregate_rmse_trial_median": aggregate_rmse_summary["median"],
            "aggregate_rmse_standard_deviation": aggregate_rmse_summary["standard_deviation"],
            "aggregate_rmse_ci95": [aggregate_rmse_summary["ci95_lower"], aggregate_rmse_summary["ci95_upper"]],
            "aggregate_relative_error": sum(relative_aggregate_errors) / len(relative_aggregate_errors) if relative_aggregate_errors else None,
            "query_latency_ms_mean": latency["mean"],
            "query_latency_ms_median": _percentile(latency_samples, .5),
            "query_latency_ms_p95": _percentile(latency_samples, .95),
            "query_latency_ms_standard_deviation": latency["standard_deviation"],
            "query_latency_ms_ci95": [latency["ci95_lower"], latency["ci95_upper"]],
            "middleware_overhead_ms_mean": overhead["mean"],
            "history_lookup_ms_mean": sum(history_lookup_samples) / len(history_lookup_samples) if history_lookup_samples else 0.0,
            "risk_policy_ms_mean": sum(risk_policy_samples) / len(risk_policy_samples) if risk_policy_samples else 0.0,
            "release_execution_ms_mean": sum(release_execution_samples) / len(release_execution_samples) if release_execution_samples else 0.0,
            "persistence_ms": None,
            "latency_measurement_scope": "synthetic experiment engine; not production SQL middleware or API latency",
            "trial_latency_median_mean_ms": sum(latency_medians) / len(latency_medians) if latency_medians else 0.0,
            "trial_latency_p95_mean_ms": sum(latency_p95s) / len(latency_p95s) if latency_p95s else 0.0,
            "engine_runtime_ms": elapsed,
            "throughput_requests_per_second": request_count / (elapsed / 1000.0),
            "estimated_dataset_memory_bytes": estimated_memory,
            "mean_risk_score": sum(risks) / len(risks) if risks else None,
            "mean_selected_epsilon": sum(selected_epsilons) / len(selected_epsilons) if selected_epsilons else None,
            "mean_history_overlap": sum(overlaps) / len(overlaps) if overlaps else None,
            "mean_repetition_signal": sum(repeats_signals) / len(repeats_signals) if repeats_signals else None,
            "mean_budget_utilization": sum(mean_utilizations) / len(mean_utilizations) if mean_utilizations else 0.0,
            "rejected_requests": rejected,
            "measurements": measurements,
            "metric_definition_version": METRIC_DEFINITION_VERSION,
            "baseline_definition_version": BASELINE_DEFINITION_VERSION,
            "scenario_definition": {
                **SCENARIO_DEFINITIONS[scenario],
                "version": ATTACK_DEFINITION_VERSION,
                "estimator_version": SCENARIO_ESTIMATOR_VERSIONS[scenario],
                "relative_success_tolerance": float(config.get("attack_relative_success_tolerance", 0.05)),
                "absolute_count_success_tolerance": float(config.get("narrowing_absolute_success_tolerance", 1.0)),
                "target_reference_id": attack_target_reference,
            },
            "protocol_version": PROTOCOL_VERSION,
            "attack_objective": SCENARIO_PROTOCOLS[scenario]["objective"],
            "relative_error_denominator_threshold": RELATIVE_ERROR_DENOMINATOR_THRESHOLD,
            "request_measurements": request_measurements,
            "measurement_note": "Per-trial errors, policy/accounting values, and minimal synthetic target/inference evidence are persisted for owner-scoped verification; raw query aggregate outputs and employee records are not persisted.",
            "statistical_note": "Continuous metric intervals use a two-sided Student-t interval for the trial mean (normal-limit approximation after 30 observations); binary attack-success intervals use the Wilson score method. Small trial counts remain exploratory.",
            "attack_metric_scope_note": "Attack success is reconstruction within the scenario-specific tolerance; it is not a proof of privacy loss or evidence that individual inference was prevented.",
            "relative_error_definition": "Relative error is unavailable when the reference magnitude is below 1. Otherwise absolute error / absolute reference; the threshold is stored with the run.",
            "metric_states": {},
        }
        result_metrics["metric_states"] = _metric_states(result_metrics)
        results.append(result_metrics)
    return results
