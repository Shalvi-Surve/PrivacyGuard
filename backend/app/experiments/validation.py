"""Read-only integrity checks for versioned synthetic research results.

Protocol v2 persists minimal synthetic-only target/estimate evidence. Historical
records remain immutable and may lack the evidence required for verification.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

from app.experiments.statistics import wilson_score_interval

VALID = "PASS"
WARNING = "WARNING"
INVALID = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"
POOLED_RMSE_METRIC_VERSIONS = {"comparative-metrics-v3", "comparative-metrics-v4", "comparative-metrics-v5"}
CURRENT_METRIC_VERSION = "comparative-metrics-v5"


def _close(left: Any, right: Any, *, abs_tol: float = 1e-8, rel_tol: float = 1e-8) -> bool:
    return isinstance(left, (int, float)) and isinstance(right, (int, float)) and math.isclose(float(left), float(right), abs_tol=abs_tol, rel_tol=rel_tol)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sample_sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    center = sum(values) / len(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - 1))


def _t_interval(values: list[float]) -> list[float | None]:
    if len(values) < 2:
        return [None, None]
    criticals = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
                 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
                 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)
    mean = sum(values) / len(values)
    margin = criticals[len(values) - 2] * (_sample_sd(values) or 0.0) / math.sqrt(len(values)) if len(values) <= 31 else 1.96 * (_sample_sd(values) or 0.0) / math.sqrt(len(values))
    return [mean - margin, mean + margin]


def _wilson(successes: int, attempts: int) -> list[float | None]:
    """Compatibility alias so validation and execution share the same method."""
    return wilson_score_interval(successes, attempts)


def _same_bounds(actual: Any, expected: list[float | None]) -> bool:
    return isinstance(actual, list) and len(actual) == len(expected) and all(
        (left is None and right is None) or _close(left, right) for left, right in zip(actual, expected)
    )


def _validate_request_aggregates(metrics: dict[str, Any], trials: list[Any], requests: list[Any], add: Any) -> None:
    valid_statuses = {"released", "cached", "raw_unprotected", "budget_rejected"}
    unexpected = [row.get("request_status") for row in requests if isinstance(row, dict) and row.get("request_status") not in valid_statuses]
    if unexpected:
        add(UNVERIFIABLE, "request_status", "Request outcomes include states outside the current synthetic evaluator taxonomy.", repr(sorted(valid_statuses)), repr(unexpected[:5]))
    rows = [row for row in requests if isinstance(row, dict)]
    status_counts = Counter(row.get("request_status") for row in rows)
    answered_statuses = {"released", "cached", "raw_unprotected"}
    answered = sum(row.get("request_status") in answered_statuses for row in rows)
    attempted = len(rows)
    per_trial: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row.get("trial"), int):
            per_trial.setdefault(row["trial"], []).append(row)
    for trial in trials:
        if not isinstance(trial, dict) or not isinstance(trial.get("trial"), int):
            continue
        current = per_trial.get(trial["trial"], [])
        if "request_count" in trial and len(current) != trial.get("request_count"):
            add(INVALID, f"trial[{trial['trial']}].request_count", "Per-request rows do not match the recorded attempted request count.", str(trial.get("request_count")), str(len(current)))
        eligible = trial.get("legitimate_requests", trial.get("request_count"))
        trial_answered = sum(row.get("request_status") in answered_statuses for row in current)
        if trial.get("answerable_requests") is not None and trial["answerable_requests"] != trial_answered:
            add(INVALID, f"trial[{trial['trial']}].answerable_requests", "Answered count differs from successful request outcomes.", str(trial_answered), repr(trial.get("answerable_requests")))
        if eligible is not None and trial_answered > eligible:
            add(INVALID, f"trial[{trial['trial']}].answerable_requests", "Answered count exceeds eligible request count.", f"<= {eligible}", str(trial_answered))
        if len(errors := [float(row["aggregate_absolute_error"]) for row in current if row.get("request_status") in answered_statuses and isinstance(row.get("aggregate_absolute_error"), (int, float)) and math.isfinite(float(row["aggregate_absolute_error"]))]) != trial_answered:
            add(UNVERIFIABLE, f"trial[{trial['trial']}].aggregate_error", "One or more answered request rows lack a finite aggregate error, so trial utility cannot be independently recomputed.", str(trial_answered), str(len(errors)))
        if eligible and trial.get("legitimate_query_answerability_rate") is not None and not _close(trial.get("legitimate_query_answerability_rate"), trial_answered / eligible):
            add(INVALID, f"trial[{trial['trial']}].legitimate_query_answerability_rate", "Trial answerability rate uses an inconsistent denominator.", str(trial_answered / eligible), repr(trial.get("legitimate_query_answerability_rate")))
        expected_mae = _mean(errors)
        expected_rmse = math.sqrt(sum(value * value for value in errors) / len(errors)) if errors else None
        for field, expected_value in (("aggregate_mae", expected_mae), ("aggregate_rmse", expected_rmse)):
            if field in trial and ((expected_value is None and trial[field] is not None) or (expected_value is not None and not _close(trial[field], expected_value))):
                add(INVALID, f"trial[{trial['trial']}].{field}", "Trial aggregate error summary disagrees with request-level errors.", repr(expected_value), repr(trial.get(field)))

    if metrics.get("metric_definition_version") == CURRENT_METRIC_VERSION:
        provenance_valid = True
        total_observations = total_independent = total_noise_samples = 0
        for trial in trials:
            if not isinstance(trial, dict) or not isinstance(trial.get("trial"), int):
                continue
            trial_id = trial["trial"]
            current = per_trial.get(trial_id, [])
            released: dict[str, dict[str, Any]] = {}
            observation_ids: set[str] = set()
            source_ids: set[str] = set()
            noise_ids: set[str] = set()
            answered_rows = [row for row in current if row.get("request_status") in answered_statuses]
            for row in current:
                status = row.get("request_status")
                observation_id = row.get("observation_id")
                release_id = row.get("release_id")
                noise_id = row.get("noise_sample_id")
                attack_source_id = row.get("attack_source_id")
                if not isinstance(observation_id, str) or not observation_id or observation_id in observation_ids:
                    provenance_valid = False
                    add(INVALID, f"trial[{trial_id}].observation_id", "Answered/request evidence lacks a unique request observation identifier.", "Unique nonempty identifier", repr(observation_id))
                else:
                    observation_ids.add(observation_id)
                if status == "released":
                    if not isinstance(release_id, str) or not release_id or release_id in released or noise_id != release_id:
                        provenance_valid = False
                        add(INVALID, f"trial[{trial_id}].release_id", "Independent release lacks a unique release/noise-sample identity.", "Unique release_id == noise_sample_id", repr((release_id, noise_id)))
                        continue
                    charge = row.get("epsilon_charged")
                    selected = row.get("selected_epsilon")
                    if not isinstance(charge, (int, float)) or not isinstance(selected, (int, float)) or not _close(charge, selected):
                        provenance_valid = False
                        add(INVALID, f"trial[{trial_id}].epsilon_charged", "A new independent release must charge its selected epsilon exactly once.", repr(selected), repr(charge))
                    released[release_id] = row
                    if attack_source_id != release_id:
                        provenance_valid = False
                        add(INVALID, f"trial[{trial_id}].attack_source_id", "A protected release must be the estimator source identified by its release/noise identity.", repr(release_id), repr(attack_source_id))
                    source_ids.add(release_id)
                    noise_ids.add(release_id)
                elif status == "cached":
                    original = released.get(str(release_id))
                    if original is None or noise_id != release_id or row.get("query_key") != original.get("query_key") or not _close(row.get("selected_epsilon"), original.get("selected_epsilon")) or float(row.get("epsilon_charged") or 0.0) != 0.0:
                        provenance_valid = False
                        add(INVALID, f"trial[{trial_id}].cache_provenance", "Cached response does not reference a prior matching release with zero additional epsilon charge.", "Prior release identity/query/epsilon match and charge 0", repr({"release_id": release_id, "noise_sample_id": noise_id, "query_key": row.get("query_key"), "epsilon_charged": row.get("epsilon_charged")}))
                    elif isinstance(release_id, str):
                        if attack_source_id != release_id:
                            provenance_valid = False
                            add(INVALID, f"trial[{trial_id}].attack_source_id", "A cached response must retain the source identity of the original release.", repr(release_id), repr(attack_source_id))
                        source_ids.add(release_id)
                        noise_ids.add(release_id)
                elif status == "raw_unprotected":
                    if release_id is not None or noise_id is not None:
                        provenance_valid = False
                        add(INVALID, f"trial[{trial_id}].raw_release_identity", "Raw M0 responses must not be labeled as protected releases or noise samples.", "Null release_id and noise_sample_id", repr((release_id, noise_id)))
                    if not isinstance(attack_source_id, str) or not attack_source_id:
                        provenance_valid = False
                        add(INVALID, f"trial[{trial_id}].attack_source_id", "Raw responses require an explicit estimator-source identity distinct from request identity.", "Nonempty source identity", repr(attack_source_id))
                    else:
                        source_ids.add(attack_source_id)
                elif status == "budget_rejected" and (release_id is not None or noise_id is not None or float(row.get("epsilon_charged") or 0.0) != 0.0):
                    provenance_valid = False
                    add(INVALID, f"trial[{trial_id}].rejected_release_identity", "Budget-rejected requests cannot carry a release/noise identity or epsilon charge.", "Null identities and charge 0", repr((release_id, noise_id, row.get("epsilon_charged"))))
                if status == "budget_rejected" and attack_source_id is not None:
                    provenance_valid = False
                    add(INVALID, f"trial[{trial_id}].rejected_attack_source_id", "A rejected request cannot contribute an estimator source.", "Null source identity", repr(attack_source_id))
            observed_counts = {
                "attack_observation_count": len(answered_rows),
                "attack_independent_observation_count": len(noise_ids),
                "unique_attack_observation_count": len(source_ids),
                "unique_noise_sample_count": len(noise_ids),
            }
            for field, expected_value in observed_counts.items():
                if trial.get(field) != expected_value:
                    provenance_valid = False
                    add(INVALID, f"trial[{trial_id}].{field}", "Attack observation count disagrees with request/release provenance.", str(expected_value), repr(trial.get(field)))
            evidence = trial.get("attack_evidence")
            if evidence is not None:
                if evidence.get("estimator_version") != trial.get("attack_estimator_version") or set(evidence.get("observation_source_ids", [])) != source_ids:
                    provenance_valid = False
                    add(INVALID, f"trial[{trial_id}].attack_evidence_provenance", "Attack evidence estimator version or source identifiers disagree with request records.", repr(sorted(source_ids)), repr(evidence.get("observation_source_ids")))
            total_observations += observed_counts["attack_observation_count"]
            total_independent += observed_counts["attack_independent_observation_count"]
            total_noise_samples += observed_counts["unique_noise_sample_count"]
        total_unique_sources = sum(
            len({row.get("attack_source_id") for row in per_trial.get(trial["trial"], []) if isinstance(row.get("attack_source_id"), str) and row.get("request_status") in answered_statuses})
            for trial in trials if isinstance(trial, dict) and isinstance(trial.get("trial"), int)
        )
        for field, expected_value in (("attack_observation_count", total_observations), ("attack_independent_observation_count", total_independent), ("unique_attack_observation_count", total_unique_sources), ("unique_noise_sample_count", total_noise_samples)):
            if metrics.get(field) != expected_value:
                provenance_valid = False
                add(INVALID, field, "Run-level attack provenance total disagrees with the per-trial totals.", str(expected_value), repr(metrics.get(field)))
        if metrics.get("scenario") == "repeated" and metrics.get("attack_estimator_version") != "repeated-unique-release-mean-v2":
            provenance_valid = False
            add(INVALID, "attack_estimator_version", "Repeated-query results must use the versioned unique-release averaging estimator.", "repeated-unique-release-mean-v2", repr(metrics.get("attack_estimator_version")))
        if metrics.get("baseline") in {"M4", "M5"} and metrics.get("exact_cache_hits", 0) > 0:
            if metrics.get("exact_cache_reuse_consistent") is not provenance_valid:
                add(INVALID, "exact_cache_reuse_consistent", "Cache consistency status disagrees with verifiable release provenance.", str(provenance_valid), repr(metrics.get("exact_cache_reuse_consistent")))
    elif metrics.get("scenario") == "repeated":
        add(UNVERIFIABLE, "attack_estimator_version", "Historical repeated-query metrics predate unique release/noise-sample provenance; cached copies cannot be audited as estimator inputs from persisted evidence.", "Versioned estimator plus per-request release identities", repr(metrics.get("attack_estimator_version", "Not recorded")))
    if metrics.get("eligible_request_count") is not None and metrics["eligible_request_count"] != attempted:
        add(INVALID, "eligible_request_count", "Eligible query denominator differs from the persisted request count.", str(attempted), repr(metrics.get("eligible_request_count")))
    if metrics.get("answerable_request_count") is not None and metrics["answerable_request_count"] != answered:
        add(INVALID, "answerable_request_count", "Run-level answered count differs from request outcomes.", str(answered), repr(metrics.get("answerable_request_count")))
    if attempted and metrics.get("query_answerability_rate") is not None and not _close(metrics.get("query_answerability_rate"), answered / attempted):
        add(INVALID, "query_answerability_rate", "Answerability rate denominator differs from attempted eligible requests.", str(answered / attempted), repr(metrics.get("query_answerability_rate")))
    if attempted and metrics.get("exact_cache_hit_rate") is not None and not _close(metrics.get("exact_cache_hit_rate"), status_counts.get("cached", 0) / attempted):
        add(INVALID, "exact_cache_hit_rate", "Cache hit rate denominator differs from attempted requests.", str(status_counts.get("cached", 0) / attempted), repr(metrics.get("exact_cache_hit_rate")))
    rejected = status_counts.get("budget_rejected", 0)
    if metrics.get("budget_rejected_requests") is not None and metrics["budget_rejected_requests"] != rejected:
        add(INVALID, "budget_rejected_requests", "Budget rejection count differs from request outcomes.", str(rejected), repr(metrics.get("budget_rejected_requests")))
    if metrics.get("rejected_requests") is not None and metrics["rejected_requests"] != rejected:
        add(INVALID, "rejected_requests", "The current synthetic engine's rejection count should equal budget rejections.", str(rejected), repr(metrics.get("rejected_requests")))
    if attempted and metrics.get("legitimate_query_rejection_rate") is not None and not _close(metrics.get("legitimate_query_rejection_rate"), rejected / attempted):
        add(INVALID, "legitimate_query_rejection_rate", "Rejection rate denominator differs from attempted legitimate requests.", str(rejected / attempted), repr(metrics.get("legitimate_query_rejection_rate")))
    if metrics.get("baseline") != "M0" and rows:
        charged = sum(float(row.get("epsilon_charged") or 0.0) for row in rows if isinstance(row.get("epsilon_charged"), (int, float)) and math.isfinite(float(row["epsilon_charged"])))
        if "epsilon_charged" in rows[0] and not _close(metrics.get("nominal_cumulative_epsilon"), charged):
            add(INVALID, "nominal_cumulative_epsilon", "Run epsilon does not match per-request charged amounts.", str(charged), repr(metrics.get("nominal_cumulative_epsilon")))
    request_errors = [float(row["aggregate_absolute_error"]) for row in rows if row.get("request_status") in answered_statuses and isinstance(row.get("aggregate_absolute_error"), (int, float)) and math.isfinite(float(row["aggregate_absolute_error"]))]
    if request_errors:
        pooled_rmse = math.sqrt(sum(value * value for value in request_errors) / len(request_errors))
        if metrics.get("metric_definition_version") in POOLED_RMSE_METRIC_VERSIONS:
            if metrics.get("aggregate_rmse") is not None and not _close(metrics.get("aggregate_rmse"), pooled_rmse):
                add(INVALID, "aggregate_rmse", "Pooled aggregate RMSE does not match request-level errors.", str(pooled_rmse), repr(metrics.get("aggregate_rmse")))
        else:
            add(UNVERIFIABLE, "aggregate_rmse_aggregation", "Historical metric version does not identify whether run-level aggregate RMSE is pooled across requests or averaged across per-trial RMSE values; the two summaries need not be equal.", "Versioned aggregation rule", f"stored={metrics.get('aggregate_rmse')!r}; request-pooled={pooled_rmse!r}")
        relative_errors = [float(row["aggregate_relative_error"]) for row in rows if row.get("request_status") in answered_statuses and isinstance(row.get("aggregate_relative_error"), (int, float)) and math.isfinite(float(row["aggregate_relative_error"]))]
        if relative_errors and not _close(metrics.get("aggregate_relative_error"), _mean(relative_errors)):
            add(INVALID, "aggregate_relative_error", "Mean relative aggregate error does not match available request-level ratios.", str(_mean(relative_errors)), repr(metrics.get("aggregate_relative_error")))
        elif metrics.get("metric_definition_version") in POOLED_RMSE_METRIC_VERSIONS and not relative_errors and metrics.get("aggregate_relative_error") is not None:
            add(INVALID, "aggregate_relative_error", "Relative aggregate error is reported although no request has a defined denominator.", "Null / NOT_MEASURED", repr(metrics.get("aggregate_relative_error")))
    elif metrics.get("aggregate_mae") is not None or metrics.get("aggregate_rmse") is not None:
        add(INVALID, "aggregate_error", "Aggregate error is reported despite no successfully answered request observations.", "Null / NOT_MEASURED", f"MAE={metrics.get('aggregate_mae')!r}; RMSE={metrics.get('aggregate_rmse')!r}")


def validate_result_metrics(metrics: dict[str, Any], expected_trials: int | None = None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(status: str, field: str, description: str, expected: str, observed: str) -> None:
        findings.append({"status": status, "severity": "error" if status == INVALID else "warning", "field": field,
                         "description": description, "expected": expected, "observed": observed})

    fraction_fields = ("attack_success_rate", "cold_start_attack_success_rate", "small_group_exposure_rate",
                       "exact_cache_hit_rate", "query_answerability_rate", "legitimate_query_rejection_rate",
                       "budget_rejection_rate", "mean_risk_score", "mean_history_overlap", "mean_repetition_signal")
    for field in fraction_fields:
        value = metrics.get(field)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1):
            add(INVALID, field, "Fraction/rate is outside its defined [0, 1] range or is non-finite.", "0..1 or explicit null", repr(value))
    nonnegative_fields = ("nominal_cumulative_epsilon", "mean_nominal_epsilon_per_trial", "initial_nominal_budget_per_trial",
                          "remaining_nominal_budget_per_trial_mean", "inference_absolute_error", "inference_rmse",
                          "aggregate_mae", "aggregate_rmse", "query_latency_ms_mean", "query_latency_ms_median",
                          "query_latency_ms_p95", "throughput_requests_per_second", "relative_inference_error",
                          "aggregate_relative_error")
    for field in nonnegative_fields:
        value = metrics.get(field)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0):
            add(INVALID, field, "Metric must be a finite nonnegative value or explicit null.", "Finite >= 0 or null", repr(value))
    utilization_percentage = metrics.get("budget_utilization_percentage")
    if utilization_percentage is not None and (not isinstance(utilization_percentage, (int, float)) or isinstance(utilization_percentage, bool) or not math.isfinite(float(utilization_percentage)) or not 0 <= float(utilization_percentage) <= 100):
        add(INVALID, "budget_utilization_percentage", "Budget utilization percentage must be between 0 and 100.", "0..100 or null", repr(utilization_percentage))
    for field in ("attack_attempt_count", "attack_success_count", "independent_releases", "exact_cache_hits",
                  "request_count", "answerable_request_count", "eligible_request_count", "budget_rejected_requests", "rejected_requests"):
        value = metrics.get(field)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            add(INVALID, field, "Count must be a nonnegative integer or explicit null.", "Integer >= 0 or null", repr(value))

    trials = metrics.get("measurements")
    if not isinstance(trials, list):
        add(UNVERIFIABLE, "measurements", "Per-trial measurements are absent.", "A list of trial records", "Missing")
        trials = []
    if expected_trials is not None and len(trials) != expected_trials:
        add(INVALID, "measurements", "Persisted trial count differs from configuration.", str(expected_trials), str(len(trials)))
    if not trials:
        add(UNVERIFIABLE, "measurements", "No trial rows are available for arithmetic validation.", "At least one trial", "None")

    attempts = successes = releases = cache_hits = request_count = answerable = charged = 0.0
    has_attack_counts = any(isinstance(item, dict) and "attack_attempt_count" in item for item in trials)
    has_release_counts = any(isinstance(item, dict) and "independent_releases" in item for item in trials)
    has_cache_counts = any(isinstance(item, dict) and "exact_cache_hits" in item for item in trials)
    has_answerability_counts = any(isinstance(item, dict) and "answerable_requests" in item for item in trials)
    has_attack_missing = False
    has_attack_classification_without_threshold = False
    for index, trial in enumerate(trials, start=1):
        if not isinstance(trial, dict):
            add(INVALID, f"measurements[{index}]", "Trial entry is not an object.", "Object", type(trial).__name__)
            continue
        attempt = trial.get("attack_attempt_count")
        success = trial.get("attack_success_count")
        if attempt is None:
            has_attack_missing = True
        else:
            attempts += int(attempt)
            if success is None and int(attempt) > 0:
                add(INVALID, f"measurements[{index}].attack_success_count", "Attempted attack has no success count.", "Integer count", "Missing")
            elif success is not None:
                successes += int(success)
                if int(success) < 0 or int(success) > int(attempt):
                    add(INVALID, f"measurements[{index}].attack_success_count", "Success count is outside attempt count.", f"0..{attempt}", str(success))
        absolute_error = trial.get("attack_absolute_error")
        success_threshold = trial.get("attack_success_threshold")
        evidence = trial.get("attack_evidence")
        if metrics.get("metric_definition_version") == CURRENT_METRIC_VERSION:
            if attempt is not None and int(attempt) > 0:
                if not isinstance(evidence, dict):
                    add(INVALID, f"measurements[{index}].attack_evidence", "Protocol v2 requires synthetic target and estimate evidence for a completed attack attempt.", "Evidence object", repr(evidence))
                else:
                    target_value, inferred_value = evidence.get("target_value"), evidence.get("inferred_value")
                    evidence_error = evidence.get("absolute_error")
                    evidence_threshold = evidence.get("success_threshold")
                    evidence_success = evidence.get("success")
                    evidence_values = (target_value, inferred_value, evidence_error, evidence_threshold)
                    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in evidence_values):
                        add(INVALID, f"measurements[{index}].attack_evidence", "Attack evidence has a missing or non-finite numeric value.", "Finite target, estimate, error and threshold", repr(evidence_values))
                    else:
                        expected_error = abs(float(inferred_value) - float(target_value))
                        expected_success = expected_error <= float(evidence_threshold)
                        if not evidence.get("target_reference_id") or evidence.get("evidence_scope") != "synthetic_only_owner_scoped":
                            add(INVALID, f"measurements[{index}].attack_evidence", "Evidence must identify its synthetic-only scope and target reference.", "Synthetic scope and target identifier", repr({"scope": evidence.get("evidence_scope"), "target": evidence.get("target_reference_id")}))
                        if not _close(evidence_error, expected_error) or not _close(absolute_error, expected_error):
                            add(INVALID, f"measurements[{index}].attack_evidence.absolute_error", "Persisted inference error disagrees with target and reconstructed values.", str(expected_error), f"evidence={evidence_error!r}; metric={absolute_error!r}")
                        if success_threshold is None or not _close(evidence_threshold, success_threshold):
                            add(INVALID, f"measurements[{index}].attack_evidence.success_threshold", "Evidence threshold disagrees with the metric row.", repr(success_threshold), repr(evidence_threshold))
                        if evidence_success is not expected_success or trial.get("attack_success") is not expected_success:
                            add(INVALID, f"measurements[{index}].attack_evidence.success", "Success classification disagrees with the persisted error and predeclared threshold.", str(expected_success), repr({"evidence": evidence_success, "trial": trial.get("attack_success")}))
                        denominator = evidence.get("relative_error_denominator")
                        expected_denominator = abs(float(target_value)) if abs(float(target_value)) >= 1.0 else None
                        if (denominator is None) != (expected_denominator is None) or (denominator is not None and not _close(denominator, expected_denominator)):
                            add(INVALID, f"measurements[{index}].attack_evidence.relative_error_denominator", "Relative-error denominator does not match the persisted target and declared threshold.", repr(expected_denominator), repr(denominator))
                        expected_relative = expected_error / expected_denominator if expected_denominator is not None else None
                        observed_relative = evidence.get("relative_error_fraction")
                        if (expected_relative is None and observed_relative is not None) or (expected_relative is not None and not _close(observed_relative, expected_relative)):
                            add(INVALID, f"measurements[{index}].attack_evidence.relative_error_fraction", "Persisted relative error does not match evidence values.", repr(expected_relative), repr(observed_relative))
                        if (expected_relative is None and trial.get("attack_relative_error") is not None) or (expected_relative is not None and not _close(trial.get("attack_relative_error"), expected_relative)):
                            add(INVALID, f"measurements[{index}].attack_relative_error", "Trial relative inference error disagrees with the persisted synthetic evidence.", repr(expected_relative), repr(trial.get("attack_relative_error")))
            elif evidence is not None:
                add(INVALID, f"measurements[{index}].attack_evidence", "Evidence is present for a trial with no completed attack estimate.", "Null", repr(evidence))
        if attempt is not None and int(attempt) > 0 and isinstance(absolute_error, (int, float)) and isinstance(success_threshold, (int, float)):
            expected_success = float(absolute_error) <= float(success_threshold)
            if trial.get("attack_success") is not expected_success:
                add(INVALID, f"measurements[{index}].attack_success", "Trial success flag contradicts the stored error and threshold.", str(expected_success), repr(trial.get("attack_success")))
        elif attempt is not None and int(attempt) > 0 and (absolute_error is None or success_threshold is None):
            has_attack_classification_without_threshold = True
        for key, target in (("independent_releases", "releases"), ("exact_cache_hits", "cache_hits"),
                            ("request_count", "request_count"), ("answerable_requests", "answerable")):
            value = trial.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                if target == "releases": releases += value
                elif target == "cache_hits": cache_hits += value
                elif target == "request_count": request_count += value
                else: answerable += value
            elif key in {"independent_releases", "request_count"} or (key == "answerable_requests" and has_answerability_counts):
                add(INVALID, f"measurements[{index}].{key}", "Required count is missing or non-finite.", "Finite count", repr(value))
        epsilon = trial.get("nominal_epsilon_spent")
        if isinstance(epsilon, (int, float)) and math.isfinite(float(epsilon)):
            charged += float(epsilon)
        elif metrics.get("baseline") != "M0":
            add(INVALID, f"measurements[{index}].nominal_epsilon_spent", "No finite nominal expenditure is recorded.", "Finite nonnegative value", repr(epsilon))
        if trial.get("attack_success") is None and int(trial.get("attack_attempt_count") or 0) == 0:
            has_attack_missing = True
        for field in ("aggregate_mae", "aggregate_rmse", "attack_absolute_error", "attack_relative_error"):
            value = trial.get(field)
            if isinstance(value, (int, float)) and not math.isfinite(float(value)):
                add(INVALID, f"measurements[{index}].{field}", "Metric value is non-finite.", "Finite value or explicit null", repr(value))
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) < 0:
                add(INVALID, f"measurements[{index}].{field}", "Absolute error/RMSE metric cannot be negative.", ">= 0 or null", repr(value))

    if not has_attack_counts:
        add(UNVERIFIABLE, "attack_counts", "Historical trial records do not contain attempt-level counts.", "Persisted attempt counts", "Missing")
    elif attempts > 0:
        rate = metrics.get("attack_success_rate")
        expected_rate = successes / attempts
        if not _close(rate, expected_rate):
            add(INVALID, "attack_success_rate", "Success rate does not agree with persisted counts.", str(expected_rate), repr(rate))
        if metrics.get("attack_attempt_count") != attempts or metrics.get("attack_success_count") != successes:
            add(INVALID, "attack_counts", "Run-level attack counts do not agree with trial counts.", f"{successes}/{attempts}", f"{metrics.get('attack_success_count')}/{metrics.get('attack_attempt_count')}")
        interval = metrics.get("attack_success_ci95")
        if not isinstance(interval, list) or len(interval) != 2 or interval[0] is None or interval[1] is None:
            add(INVALID, "attack_success_ci95", "A measured binary attack rate is missing its confidence interval.", "Two interval bounds", repr(interval))
        elif metrics.get("metric_definition_version") in POOLED_RMSE_METRIC_VERSIONS:
            expected_interval = _wilson(int(successes), int(attempts))
            if not all(_close(actual, expected) for actual, expected in zip(interval, expected_interval)):
                add(INVALID, "attack_success_ci95", "Wilson interval does not match persisted success counts.", repr(expected_interval), repr(interval))
        elif successes in {0, attempts}:
            add(WARNING, "attack_success_ci95", "Historical binary interval uses the previous method; at 0% or 100%, a zero-width normal/Wald interval is misleading.", "Wilson score interval", repr(interval))
    elif metrics.get("attack_success_rate") is not None and has_attack_counts:
        add(INVALID, "attack_success_rate", "A success rate is present without an executed attack attempt.", "null", repr(metrics.get("attack_success_rate")))
    else:
        add(UNVERIFIABLE, "attack_success_rate", "No complete attacker estimate was available.", "A rate based on executed attempts", "Not measured")

    if has_release_counts and "independent_releases" in metrics and not _close(metrics.get("independent_releases"), releases):
        add(INVALID, "independent_releases", "Run-level release count differs from trial sum.", str(releases), repr(metrics.get("independent_releases")))
    if has_cache_counts and "exact_cache_hits" in metrics and metrics.get("exact_cache_hits") != cache_hits:
        add(INVALID, "exact_cache_hits", "Run-level cache hit count differs from trial sum.", str(cache_hits), repr(metrics.get("exact_cache_hits")))
    if metrics.get("baseline") in {"M4", "M5"}:
        consistency_checks = metrics.get("cache_consistency_checks")
        consistency = metrics.get("exact_cache_reuse_consistent")
        if consistency_checks is not None and consistency_checks != cache_hits:
            add(INVALID, "cache_consistency_checks", "Cache consistency check count differs from cache hits.", str(cache_hits), repr(consistency_checks))
        if cache_hits == 0 and consistency is not None:
            status = INVALID if metrics.get("metric_definition_version") == CURRENT_METRIC_VERSION else UNVERIFIABLE
            add(status, "exact_cache_reuse_consistent", "Cache consistency is reported despite no cache reuse being observed; a historical default may be untested rather than a measured success.", "Null / NOT_MEASURED", repr(consistency))
        elif cache_hits > 0 and consistency is None:
            add(UNVERIFIABLE, "exact_cache_reuse_consistent", "Cache hits occurred but no consistency outcome was recorded.", "Boolean outcome", "Missing")
        elif consistency is False:
            add(INVALID, "exact_cache_reuse_consistent", "A reused output differed from the cached output.", "True", "False")
    if metrics.get("baseline") != "M0" and not _close(metrics.get("nominal_cumulative_epsilon"), charged):
        add(INVALID, "nominal_cumulative_epsilon", "Run expenditure differs from trial expenditure sum.", str(charged), repr(metrics.get("nominal_cumulative_epsilon")))
    if not has_answerability_counts:
        add(UNVERIFIABLE, "answerable_request_count", "Historical trial records do not contain answerability counts.", "Persisted eligible and answered request counts", "Missing")
    if request_count and answerable > request_count:
        add(INVALID, "answerable_request_count", "Answered query count exceeds attempted eligible requests.", f"<= {request_count}", str(answerable))

    requests = metrics.get("request_measurements")
    if isinstance(requests, list) and requests:
        statuses = Counter(str(row.get("request_status")) for row in requests if isinstance(row, dict))
        request_releases = statuses.get("released", 0)
        request_cached = statuses.get("cached", 0)
        request_budget_rejected = statuses.get("budget_rejected", 0)
        request_raw = statuses.get("raw_unprotected", 0)
        if metrics.get("independent_releases") is not None and request_releases != releases:
            add(INVALID, "independent_releases", "Request release statuses do not match the aggregate release count.", str(releases), str(request_releases))
        if metrics.get("exact_cache_hits") is None:
            add(UNVERIFIABLE, "exact_cache_hits", "Historical aggregate cache-hit count is absent, so request statuses cannot be reconciled to it.", "Recorded cache-hit count", "Unknown")
        elif request_cached != cache_hits:
            add(INVALID, "exact_cache_hits", "Request cache statuses do not match the aggregate cache-hit count.", str(cache_hits), str(request_cached))
        if metrics.get("budget_rejected_requests") is None:
            add(UNVERIFIABLE, "budget_rejected_requests", "Historical aggregate budget-rejection count is absent.", "Recorded budget-rejection count", "Unknown")
        elif request_budget_rejected != metrics.get("budget_rejected_requests"):
            add(INVALID, "budget_rejected_requests", "Budget rejection count differs from request records.", str(request_budget_rejected), repr(metrics.get("budget_rejected_requests")))
        if metrics.get("baseline") == "M0" and request_raw != len(requests):
            add(INVALID, "request_measurements", "M0 request records are not all explicitly unprotected.", str(len(requests)), str(request_raw))
    else:
        add(UNVERIFIABLE, "request_measurements", "Per-request records needed for cache and rejection checks are absent.", "Request records", "Missing")
    if isinstance(requests, list) and requests:
        _validate_request_aggregates(metrics, trials, requests, add)

    if metrics.get("metric_definition_version") in POOLED_RMSE_METRIC_VERSIONS:
        attack_errors = [float(item["attack_absolute_error"]) for item in trials if isinstance(item, dict) and isinstance(item.get("attack_absolute_error"), (int, float)) and math.isfinite(float(item["attack_absolute_error"]))]
        if attack_errors:
            expected_attack_mae = _mean(attack_errors)
            expected_attack_rmse = math.sqrt(sum(value * value for value in attack_errors) / len(attack_errors))
            for field, expected in (("inference_absolute_error", expected_attack_mae), ("inference_rmse", expected_attack_rmse)):
                if not _close(metrics.get(field), expected):
                    add(INVALID, field, "Inference summary disagrees with per-trial reconstruction errors.", str(expected), repr(metrics.get(field)))
            relative_errors = [float(item["attack_relative_error"]) for item in trials if isinstance(item, dict) and isinstance(item.get("attack_relative_error"), (int, float)) and math.isfinite(float(item["attack_relative_error"]))]
            if relative_errors and not _close(metrics.get("relative_inference_error"), _mean(relative_errors)):
                add(INVALID, "relative_inference_error", "Relative inference error summary disagrees with the available trial ratios.", str(_mean(relative_errors)), repr(metrics.get("relative_inference_error")))
            elif not relative_errors and metrics.get("relative_inference_error") is not None:
                add(INVALID, "relative_inference_error", "Relative inference error is reported although no trial has a defined reference denominator.", "Null / NOT_MEASURED", repr(metrics.get("relative_inference_error")))
            expected_interval = _t_interval(attack_errors)
            observed_interval = metrics.get("inference_error_ci95")
            if not _same_bounds(observed_interval, expected_interval):
                add(INVALID, "inference_error_ci95", "Continuous inference error interval does not match the documented Student-t method.", repr(expected_interval), repr(observed_interval))
        else:
            add(UNVERIFIABLE, "inference_error", "No per-trial attack reconstruction errors are available.", "Trial-level errors", "Missing")
            for field in ("inference_absolute_error", "inference_rmse", "relative_inference_error"):
                if metrics.get(field) is not None:
                    add(INVALID, field, "Inference metric is reported without any available trial-level attack estimate.", "Null / NOT_MEASURED", repr(metrics.get(field)))
        trial_maes = [float(item["aggregate_mae"]) for item in trials if isinstance(item, dict) and isinstance(item.get("aggregate_mae"), (int, float)) and math.isfinite(float(item["aggregate_mae"]))]
        if trial_maes:
            if not _close(metrics.get("aggregate_mae"), _mean(trial_maes)):
                add(INVALID, "aggregate_mae", "Run aggregate MAE differs from the mean of per-trial MAEs.", str(_mean(trial_maes)), repr(metrics.get("aggregate_mae")))
            observed_interval = metrics.get("aggregate_error_ci95")
            expected_interval = _t_interval(trial_maes)
            if not _same_bounds(observed_interval, expected_interval):
                add(INVALID, "aggregate_error_ci95", "Aggregate MAE interval does not match the documented Student-t method over trial MAEs.", repr(expected_interval), repr(observed_interval))
        elif metrics.get("aggregate_mae") is not None or metrics.get("aggregate_rmse") is not None:
            add(INVALID, "aggregate_error", "Aggregate error is reported without any measured trial aggregate error.", "Null / NOT_MEASURED", f"MAE={metrics.get('aggregate_mae')!r}; RMSE={metrics.get('aggregate_rmse')!r}")
        if has_attack_counts and attempts > 0:
            expected_sd = _sample_sd([1.0 if item.get("attack_success") is True else 0.0 for item in trials if isinstance(item, dict) and item.get("attack_attempt_count")])
            if expected_sd is not None and not _close(metrics.get("attack_success_standard_deviation"), expected_sd):
                add(INVALID, "attack_success_standard_deviation", "Success standard deviation does not match trial flags.", str(expected_sd), repr(metrics.get("attack_success_standard_deviation")))

    if metrics.get("metric_definition_version") is None:
        add(UNVERIFIABLE, "metric_definition_version", "Historical run has no metric definition version.", "Recorded version", "Unknown")
    elif metrics.get("metric_definition_version") == "comparative-metrics-v2":
        add(WARNING, "statistical_method", "This historical version used a normal approximation for binary success and continuous trial means; boundary binary results and small samples need cautious interpretation.", "Wilson score intervals for binary rates and Student-t intervals for continuous means", "comparative-metrics-v2")
    if not metrics.get("scenario_definition"):
        add(UNVERIFIABLE, "scenario_definition", "Scenario success criteria cannot be confirmed from this result.", "Versioned scenario definition", "Missing")
    if has_attack_classification_without_threshold:
        add(UNVERIFIABLE, "attack_success_classification", "One or more trial success classifications cannot be independently checked because historical records omit the reconstruction error or threshold.", "Stored per-trial error and threshold", "Missing for one or more trials")
    if has_attack_missing:
        add(UNVERIFIABLE, "attack_attempt_count", "At least one trial has no complete attack estimate; it is excluded from the measured rate.", "All trials attempted or explicitly unavailable", "One or more unavailable")
    if metrics.get("scenario") == "repeated":
        add(WARNING, "attack_success_rate", "This scenario measures reconstruction of the full synthetic salary sum within its configured tolerance, not individual attribute inference.", "Interpret as aggregate reconstruction only", "Target is a full-dataset sum")
    if metrics.get("scenario") == "narrowing":
        add(WARNING, "scenario_definition", "The synthetic workload issues a fixed sequence of progressively narrower predicates; it does not model an interactive attacker choosing each next predicate from prior observations.", "Interpret as fixed narrowing sequence", "Interactive adaptation is not modeled")
    if metrics.get("baseline") == "M0":
        add(WARNING, "privacy_guarantee_status", "M0 is an unprotected utility reference and has no privacy protection.", "No privacy protection", repr(metrics.get("privacy_guarantee_status")))
    else:
        add(WARNING, "privacy_guarantee_status", "Nominal epsilon is uncertified for this finite-precision seeded experiment sampler and is not a formal end-to-end guarantee.", "nominal_uncertified", repr(metrics.get("accounting_status")))
    if metrics.get("metric_definition_version") != CURRENT_METRIC_VERSION:
        add(UNVERIFIABLE, "attack_ground_truth", "Historical target and attacker estimate were not persisted, so per-trial inference errors cannot be independently reconstructed.", "Versioned synthetic evidence", "Target/estimate evidence absent")
        add(UNVERIFIABLE, "relative_error_denominator", "Historical relative-error reference magnitude was not persisted, so ratios cannot be independently recalculated.", "Persisted denominator evidence", "Reference magnitude absent")
    return findings


def validate_run(configuration: dict[str, Any], results: list[dict[str, Any]], experiment_id: int | None = None) -> dict[str, Any]:
    expected = configuration.get("baselines")
    expected_count = configuration.get("trials")
    observed = [row.get("baseline") for row in results]
    findings: list[dict[str, str]] = []
    if isinstance(expected, list):
        normalized = expected
        if Counter(normalized) != Counter(observed):
            findings.append({"status": INVALID, "severity": "error", "field": "baselines", "description": "Persisted baseline set differs from requested configuration.", "expected": repr(normalized), "observed": repr(observed)})
    if not results:
        findings.append({"status": UNVERIFIABLE, "severity": "warning", "field": "results", "description": "No baseline results are available.", "expected": "At least one result", "observed": "None"})
    protocol = configuration.get("protocol")
    if not isinstance(protocol, dict):
        findings.append({"status": UNVERIFIABLE, "severity": "warning", "field": "experiment_protocol", "description": "Run has no persisted versioned protocol; historical definitions must not be inferred from current code.", "expected": "Protocol v2 object", "observed": "Missing"})
    else:
        if protocol.get("version") != "privacyguard-research-protocol-v2":
            findings.append({"status": INVALID, "severity": "error", "field": "experiment_protocol.version", "description": "Unsupported or missing protocol version.", "expected": "privacyguard-research-protocol-v2", "observed": repr(protocol.get("version"))})
        dataset = protocol.get("dataset") or {}
        if protocol.get("scenario_identifier") != configuration.get("scenario") or dataset.get("row_count") != configuration.get("dataset_size") or dataset.get("seed") != configuration.get("seed"):
            findings.append({"status": INVALID, "severity": "error", "field": "experiment_protocol.configuration", "description": "Persisted protocol scenario or dataset configuration disagrees with the run configuration.", "expected": repr({"scenario": configuration.get("scenario"), "dataset_size": configuration.get("dataset_size"), "seed": configuration.get("seed")}), "observed": repr({"scenario": protocol.get("scenario_identifier"), "dataset_size": dataset.get("row_count"), "seed": dataset.get("seed")})})
        trial_protocol = protocol.get("trials") or {}
        trial_seeds = trial_protocol.get("trial_seeds")
        if not isinstance(trial_seeds, list) or len(trial_seeds) != configuration.get("trials"):
            findings.append({"status": INVALID, "severity": "error", "field": "trial_seed_schedule", "description": "Persisted trial seed list does not match the configured trial count.", "expected": str(configuration.get("trials")), "observed": repr(len(trial_seeds) if isinstance(trial_seeds, list) else trial_seeds)})
        protocol_baselines = {str(item.get("id")) for item in protocol.get("baselines", []) if isinstance(item, dict)}
        if protocol_baselines != set(str(item) for item in (expected or [])):
            findings.append({"status": INVALID, "severity": "error", "field": "experiment_protocol.baselines", "description": "Protocol baseline configurations do not match the requested baseline set.", "expected": repr(sorted(str(item) for item in (expected or []))), "observed": repr(sorted(protocol_baselines))})
    baseline_reports: dict[str, dict[str, Any]] = {}
    for row in results:
        row_findings = validate_result_metrics(row.get("metrics") or {}, expected_count)
        metrics = row.get("metrics") or {}
        if isinstance(protocol, dict):
            if metrics.get("protocol_version") != protocol.get("version"):
                row_findings.append({"status": INVALID, "severity": "error", "field": "protocol_version", "description": "Baseline result protocol version does not match the run protocol.", "expected": repr(protocol.get("version")), "observed": repr(metrics.get("protocol_version"))})
            schedule = (protocol.get("trials") or {}).get("trial_seeds") or []
            for measurement in metrics.get("measurements", []):
                if isinstance(measurement, dict) and isinstance(measurement.get("trial"), int) and 1 <= measurement["trial"] <= len(schedule):
                    if measurement.get("trial_seed") != schedule[measurement["trial"] - 1]:
                        row_findings.append({"status": INVALID, "severity": "error", "field": f"trial[{measurement['trial']}].trial_seed", "description": "Per-trial seed differs from the shared protocol schedule.", "expected": repr(schedule[measurement["trial"] - 1]), "observed": repr(measurement.get("trial_seed"))})
        for finding in row_findings:
            finding["baseline"] = str(row.get("baseline"))
        findings.extend(row_findings)
        row_states = {item["status"] for item in row_findings}
        baseline_reports[str(row.get("baseline"))] = {
            "status": INVALID if INVALID in row_states else WARNING if WARNING in row_states or UNVERIFIABLE in row_states else VALID,
            "findings": row_findings,
        }
    result_map = {str(row.get("baseline")): row.get("metrics") or {} for row in results}
    m1, m2, m4 = result_map.get("M1"), result_map.get("M2"), result_map.get("M4")
    if m1 is not None and m2 is not None and m2.get("budget_rejected_requests") == 0:
        compared = ("attack_success_rate", "inference_absolute_error", "aggregate_mae", "aggregate_rmse", "independent_releases", "nominal_cumulative_epsilon")
        if all(m1.get(key) == m2.get(key) for key in compared):
            findings.append({"status": WARNING, "severity": "warning", "field": "M1_vs_M2", "description": "M1 and M2 observations are identical and the M2 cap did not reject requests; the shared budget did not bind in this configuration, so the baselines were not empirically distinguished.", "expected": "Interpret as same observed behavior when the cap is nonbinding", "observed": f"M2 budget rejections={m2.get('budget_rejected_requests')}; epsilon={m2.get('nominal_cumulative_epsilon')}"})
    if m1 is not None and m4 is not None and m4.get("exact_cache_hits") == 0:
        findings.append({"status": WARNING, "severity": "warning", "field": "M1_vs_M4", "description": "The cache-only baseline recorded no exact cache hits, so this run did not exercise its defining cache behavior.", "expected": "At least one repeated identical request if cache behavior is being compared", "observed": "M4 exact cache hits=0"})
    versions = ("experiment_engine_version", "baseline_definition_version", "metric_definition_version", "workload_definition_version", "attack_definition_version", "mechanism_version")
    missing_versions = [name for name in versions if not configuration.get(name)]
    if missing_versions:
        findings.append({"status": UNVERIFIABLE, "severity": "warning", "field": "experiment_versions", "description": "Historical run lacks one or more reproducibility version identifiers.", "expected": "All relevant version identifiers", "observed": ", ".join(missing_versions)})
    # Keep the original compact fields for current API clients while exposing
    # a self-contained audit record for report consumers. This is computed on
    # read and never persisted back onto historical result rows.
    context_baselines = [str(row.get("baseline")) for row in results]
    def enrich(finding: dict[str, Any]) -> dict[str, Any]:
        baseline = finding.get("baseline")
        status = finding.get("status")
        if status == INVALID:
            action = "Investigate the cited arithmetic or record inconsistency; preserve the historical row and correct only future runs after a verified fix."
        elif status == UNVERIFIABLE:
            action = "Retain as unverified; add versioned, non-sensitive evidence to future runs if independent validation is required."
        elif status == WARNING:
            action = "Interpret with the stated qualification; do not treat this warning alone as proof of a defect."
        else:
            action = "No corrective action indicated by this check."
        return {
            **finding,
            "experiment_id": experiment_id,
            "scenario": configuration.get("scenario"),
            "dataset": configuration.get("dataset_size"),
            "baselines": [baseline] if baseline else context_baselines,
            "metric": finding.get("field"),
            "finding": finding.get("description"),
            "reason": finding.get("description"),
            "evidence": {"expected": finding.get("expected"), "observed": finding.get("observed")},
            "suggested_action": action,
        }
    findings = [enrich(item) for item in findings]
    for baseline_report in baseline_reports.values():
        baseline_report["findings"] = [enrich(item) for item in baseline_report["findings"]]
    states = {item["status"] for item in findings}
    status = INVALID if INVALID in states else WARNING if WARNING in states or UNVERIFIABLE in states else VALID
    return {"status": status, "findings": findings, "baseline_reports": baseline_reports, "summary": {"errors": sum(item["status"] == INVALID for item in findings), "warnings": sum(item["status"] == WARNING for item in findings), "unverifiable": sum(item["status"] == UNVERIFIABLE for item in findings)}}
