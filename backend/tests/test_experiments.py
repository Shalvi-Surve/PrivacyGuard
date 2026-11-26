import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-that-is-long-enough-for-tests")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import current_user
from app.auth.security import create_access_token, hash_password
from app.database.connection import Base
from app.database.models import ExperimentResult, ExperimentRun, Permission, Role, RolePermission, User, UserRole
from app.datasets.generation import iter_employee_rows
from app.experiments.engine import (_build_workload, _cache_provenance_is_consistent, _mean_std_ci,
                                   _noise, _relative_error, _risk_for, _unique_attack_observations,
                                   _wilson_interval, run_comparison)
from app.experiments.statistics import wilson_score_interval
from app.experiments.validation import INVALID, UNVERIFIABLE, validate_result_metrics, validate_run
from app.experiments.routes import (
    ExperimentRunRequest, _serialize_run, create_experiment_run, export_experiment_csv,
    get_experiment_run, get_paired_experiment_comparisons, list_experiment_runs, list_benchmark_results,
    list_benchmark_run_summaries, simulate_attack,
)
from app.main import app
from app.rbac.permissions import require_permission


@pytest.fixture
def experiment_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'experiment-test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        permission = Permission(key="experiments:run", description="Run synthetic experiments")
        researcher_role = Role(name="experiment_researcher", description="authorized")
        denied_role = Role(name="experiment_denied", description="not authorized")
        researcher = User(username="exp-researcher", email="exp@example.test", full_name="Researcher", password_hash=hash_password("test-password"))
        denied = User(username="exp-denied", email="denied@example.test", full_name="Denied", password_hash=hash_password("test-password"))
        db.add_all([permission, researcher_role, denied_role, researcher, denied])
        db.flush()
        db.add_all([RolePermission(role_id=researcher_role.id, permission_id=permission.id), UserRole(user_id=researcher.id, role_id=researcher_role.id), UserRole(user_id=denied.id, role_id=denied_role.id)])
        researcher_id, denied_id = researcher.id, denied.id
    try:
        yield factory, researcher_id, denied_id
    finally:
        engine.dispose()


def test_synthetic_attack_scenarios_are_reproducible_and_emit_no_raw_values():
    for scenario in ("difference", "repeated", "narrowing", "overlapping"):
        config = {"scenario": scenario, "dataset_size": 5000, "baselines": ["B0", "B1", "B2", "B3", "B4"], "trials": 2, "repetitions": 4, "seed": 731, "epsilon": .5, "budget_epsilon": 10}
        first = run_comparison(config)
        second = run_comparison(config)
        for a, b in zip(first, second):
            for field in ("nominal_cumulative_epsilon", "independent_releases", "attack_success_rate", "inference_absolute_error", "aggregate_mae", "rejected_requests"):
                assert a[field] == b[field]
            serialized = str(a)
            assert "raw_aggregate" not in serialized
            assert "target_salary" not in serialized
            assert "truth" not in serialized


def test_fixed_dp_and_composition_baselines_account_for_distinct_releases():
    config = {"scenario": "difference", "dataset_size": 5000, "baselines": ["B1", "B2"], "trials": 1, "repetitions": 2, "seed": 9, "epsilon": .5, "budget_epsilon": .5}
    fixed, composed = run_comparison(config)
    assert fixed["independent_releases"] == 2
    assert fixed["nominal_cumulative_epsilon"] == pytest.approx(1.0)
    assert composed["independent_releases"] == 1
    assert composed["nominal_cumulative_epsilon"] == pytest.approx(.5)
    assert composed["rejected_requests"] == 1


def test_repeated_exact_requests_reuse_cache_and_adaptive_configuration_can_change():
    config = {"scenario": "repeated", "dataset_size": 5000, "baselines": ["M4", "M5"], "trials": 1, "repetitions": 8, "seed": 43, "epsilon": .5, "budget_epsilon": 10}
    fixed, adaptive = run_comparison(config)
    assert fixed["independent_releases"] == 1
    assert fixed["exact_cache_hits"] == 7
    assert fixed["nominal_cumulative_epsilon"] == pytest.approx(.5)
    assert adaptive["independent_releases"] >= 1
    assert adaptive["independent_releases"] == 1
    assert adaptive["exact_cache_hits"] == 7
    assert adaptive["nominal_cumulative_epsilon"] == pytest.approx(adaptive["mean_nominal_epsilon_per_trial"])
    assert adaptive["mean_selected_epsilon"] is not None
    assert adaptive["mean_repetition_signal"] > 0


def test_m5_reuses_exact_adaptive_release_but_allocates_equivalent_variants_independently():
    base = {"scenario": "repeated", "dataset_size": 5000, "baselines": ["M5"], "trials": 2,
            "repetitions": 4, "seed": 431, "epsilon": .5, "budget_epsilon": 10}
    identical = run_comparison({**base, "repeat_query_mode": "identical"})[0]
    variants = run_comparison({**base, "repeat_query_mode": "equivalent_variants"})[0]
    assert identical["independent_releases"] == 2
    assert identical["exact_cache_hits"] == 6
    assert identical["exact_cache_reuse_consistent"] is True
    assert variants["independent_releases"] == 8
    assert variants["exact_cache_hits"] == 0
    assert variants["attack_attempt_count"] == 2
    assert all(item["attack_independent_observation_count"] == 4 for item in variants["measurements"])
    assert identical["nominal_cumulative_epsilon"] < variants["nominal_cumulative_epsilon"]


def test_m5_calibrated_policy_is_configurable_responsive_and_budget_bounded():
    base = {"scenario": "difference", "dataset_size": 5000, "baselines": ["M5"], "trials": 2,
            "repetitions": 3, "seed": 551, "epsilon": .5, "budget_epsilon": 1.0}
    conservative = run_comparison({**base, "adaptive_risk_penalty": .6, "adaptive_cumulative_penalty": .3})[0]
    calibrated = run_comparison({**base, "adaptive_risk_penalty": .2, "adaptive_cumulative_penalty": .1})[0]
    assert calibrated["mean_selected_epsilon"] > conservative["mean_selected_epsilon"]
    assert calibrated["inference_absolute_error"] < conservative["inference_absolute_error"]
    assert calibrated["adaptive_policy_config"]["policy_id"] == "query-history-adaptive-nominal-v2"
    assert calibrated["adaptive_policy_config"]["risk_penalty"] == .2
    assert all(row["nominal_epsilon_spent"] <= base["budget_epsilon"] for row in calibrated["measurements"])


def test_policy_risk_uses_query_sensitivity_normalized_to_supported_sum_bound():
    rows = [{"employee_id": f"employee-{i}", "department": "Engineering", "location": "North", "salary": 100 + i, "designation": "Senior", "age": 60} for i in range(4)]
    difference, _, _, _ = _build_workload("difference", rows)
    narrowing, _, _, _ = _build_workload("narrowing", rows)
    salary_risk = _risk_for(difference[0], [], 0)[0]
    count_risk = _risk_for(narrowing[0], [], 0)[0]
    assert salary_risk.query_sensitivity == 1.0  # SUM sensitivity 300,000 / normalization 300,000
    assert count_risk.query_sensitivity == pytest.approx(1 / 300_000)
    assert salary_risk.overall > count_risk.overall


def test_experiment_request_validates_adaptive_bounds_and_penalty_ranges():
    base = {"scenario": "difference", "epsilon": .5}
    with pytest.raises(ValueError):
        ExperimentRunRequest(**base, adaptive_epsilon_min=.6)
    with pytest.raises(ValueError):
        ExperimentRunRequest(**base, adaptive_risk_penalty=1.01)
    legacy_request = ExperimentRunRequest(**{**base, "epsilon": .05})
    assert legacy_request.adaptive_epsilon_min == .05


def test_equivalent_repeated_requests_are_independent_and_accounted():
    config = {"scenario": "repeated", "dataset_size": 5000, "baselines": ["M1"], "trials": 1, "repetitions": 4, "repeat_query_mode": "equivalent_variants", "seed": 43, "epsilon": .5, "budget_epsilon": 10}
    result = run_comparison(config)[0]
    assert result["measurements"][0]["request_count"] == 4
    assert result["independent_releases"] == 4
    assert result["nominal_cumulative_epsilon"] == pytest.approx(2.0)
    assert result["mean_repetition_signal"] > 0


def test_six_baseline_comparison_exposes_versioned_metrics_and_cache_isolation():
    config = {"scenario": "repeated", "dataset_size": 5000, "baselines": ["M0", "M1", "M2", "M3", "M4", "M5"], "trials": 2, "repetitions": 4, "seed": 43, "epsilon": .5, "budget_epsilon": 10}
    results = run_comparison(config)
    assert [row["baseline"] for row in results] == ["M0", "M1", "M2", "M3", "M4", "M5"]
    by_id = {row["baseline"]: row for row in results}
    assert by_id["M0"]["accounting_status"] == "not_applicable_raw_baseline"
    assert by_id["M1"]["independent_releases"] == 8
    assert by_id["M2"]["exact_cache_hits"] == 0
    assert by_id["M4"]["independent_releases"] == 2
    assert by_id["M4"]["exact_cache_hits"] == 6
    assert by_id["M5"]["metric_definition_version"] == "comparative-metrics-v5"
    assert by_id["M4"]["latency_measurement_scope"].startswith("synthetic experiment engine")


def test_history_depth_and_m5_ablation_are_isolated_experimental_inputs():
    base = {"scenario": "repeated", "dataset_size": 5000, "baselines": ["M5"], "trials": 2, "repetitions": 4, "seed": 43, "epsilon": .5, "budget_epsilon": 10}
    with_history = run_comparison({**base, "history_depth": 5})[0]
    without_overlap = run_comparison({**base, "history_depth": 5, "ablation_mode": "no_history_overlap"})[0]
    assert with_history["mean_history_overlap"] > 0
    assert without_overlap["mean_history_overlap"] == 0
    assert with_history["mean_selected_epsilon"] != without_overlap["mean_selected_epsilon"]
    assert with_history["metric_definition_version"] == without_overlap["metric_definition_version"]


def test_metric_math_preserves_unmeasured_and_uses_small_sample_intervals():
    assert _mean_std_ci([]) == {"mean": None, "median": None, "standard_deviation": None, "p95": None, "ci95_lower": None, "ci95_upper": None}
    single = _mean_std_ci([0.0])
    assert single["mean"] == 0.0 and single["standard_deviation"] is None and single["ci95_lower"] is None
    pair = _mean_std_ci([1.0, 3.0])
    assert pair["mean"] == 2.0 and pair["standard_deviation"] == pytest.approx(2**0.5)
    assert pair["ci95_lower"] < pair["mean"] < pair["ci95_upper"]
    assert _wilson_interval(20, 20)[0] < 1.0
    assert _wilson_interval(0, 20)[1] > 0.0
    assert _wilson_interval(0, 0) == [None, None]
    assert _relative_error(0.0, 100.0) == 0.0
    assert _relative_error(5.0, 0.0) is None
    assert _relative_error(5.0, 0.5) is None


@pytest.mark.parametrize("successes,attempts,expected", [
    (0, 20, (0.0, 0.1611)),
    (20, 20, (0.8389, 1.0)),
    (10, 20, (0.2993, 0.7007)),
    (0, 1, (0.0, 0.7935)),
    (1, 1, (0.2065, 1.0)),
])
def test_wilson_score_intervals_cover_boundary_and_interior_counts(successes, attempts, expected):
    interval = wilson_score_interval(successes, attempts)
    assert interval == pytest.approx(expected, abs=0.0001)
    assert _wilson_interval(successes, attempts) == pytest.approx(expected, abs=0.0001)


def test_wilson_score_interval_handles_unmeasured_denominators_and_rejects_invalid_counts():
    assert wilson_score_interval(0, 0) == [None, None]
    assert wilson_score_interval(3, None) == [None, None]
    assert wilson_score_interval(None, 20) == [None, None]
    with pytest.raises(ValueError):
        wilson_score_interval(1, 0)
    with pytest.raises(ValueError):
        wilson_score_interval(21, 20)


@pytest.mark.parametrize("successes,stored_interval,expected", [
    (0, [0.0, 0.0], [0.0, 0.161125]),
    (20, [1.0, 1.0], [0.838875, 1.0]),
])
def test_run_serialization_recomputes_legacy_wilson_interval_without_mutating_stored_metrics(
    experiment_db, successes, stored_interval, expected
):
    factory, _, _ = experiment_db
    metrics = {
        "metric_definition_version": "comparative-metrics-v2",
        "attack_success_count": successes,
        "attack_attempt_count": 20,
        "attack_success_rate": successes / 20,
        "attack_success_ci95": stored_interval,
    }
    with factory() as db:
        run = ExperimentRun(name="legacy interval fixture", configuration={"scenario": "difference", "trials": 20}, status="completed")
        db.add(run)
        db.flush()
        result_row = ExperimentResult(run_id=run.id, baseline="M1", metrics=metrics)
        db.add(result_row)
        db.commit()
        run_id, result_id = run.id, result_row.id

        response = _serialize_run(db, run)

        assert response["results"][0]["metrics"]["attack_success_ci95"] == pytest.approx(expected, abs=0.000001)
        assert db.get(ExperimentResult, result_id).metrics["attack_success_ci95"] == stored_interval
        assert db.get(ExperimentRun, run_id) is not None


def test_repeated_scenario_records_observation_dependence_and_metric_states():
    config = {"scenario": "repeated", "dataset_size": 5000, "baselines": ["M1", "M4"], "trials": 2, "repetitions": 5, "seed": 2026, "epsilon": .5, "budget_epsilon": 10}
    independent, cached = run_comparison(config)
    assert independent["measurements"][0]["attack_observation_count"] == 5
    assert independent["measurements"][0]["attack_independent_observation_count"] == 5
    assert cached["measurements"][0]["attack_observation_count"] == 5
    assert cached["measurements"][0]["attack_independent_observation_count"] == 1
    assert cached["measurements"][0]["unique_attack_observation_count"] == 1
    assert cached["measurements"][0]["unique_noise_sample_count"] == 1
    assert independent["metric_states"]["attack_success_rate"]["state"] == "MEASURED"
    assert cached["metric_states"]["aggregate_mae"]["state"] == "MEASURED"
    no_reuse = run_comparison({"scenario": "difference", "dataset_size": 5000, "baselines": ["M4"], "trials": 2, "repetitions": 2, "seed": 2026, "epsilon": .5, "budget_epsilon": 10})[0]
    assert no_reuse["exact_cache_reuse_consistent"] is None
    assert no_reuse["metric_states"]["exact_cache_reuse_consistent"]["state"] == "NOT_MEASURED"
    assert cached["exact_cache_reuse_consistent"] is True
    assert cached["metric_states"]["exact_cache_reuse_consistent"]["state"] == "MEASURED"
    inconsistent = {**cached, "exact_cache_reuse_consistent": False}
    assert any(item["field"] == "exact_cache_reuse_consistent" and item["status"] == INVALID for item in validate_result_metrics(inconsistent, 2))


def test_repeated_estimator_averages_unique_release_sources_only():
    observations = [
        {"value": 10.0, "request_status": "released", "observation_id": "q1", "attack_source_id": "r1", "release_id": "r1", "noise_sample_id": "r1"},
        {"value": 10.0, "request_status": "cached", "observation_id": "q2", "attack_source_id": "r1", "release_id": "r1", "noise_sample_id": "r1"},
        {"value": 10.0, "request_status": "cached", "observation_id": "q3", "attack_source_id": "r1", "release_id": "r1", "noise_sample_id": "r1"},
        {"value": 20.0, "request_status": "released", "observation_id": "q4", "attack_source_id": "r2", "release_id": "r2", "noise_sample_id": "r2"},
    ]
    values, unique_noise_samples, source_ids = _unique_attack_observations(observations)
    assert values == [10.0, 20.0]
    assert sum(values) / len(values) == 15.0
    assert unique_noise_samples == 2
    assert source_ids == ["r1", "r2"]


def test_cache_provenance_requires_prior_identity_and_zero_repeat_charge():
    requests = [
        {"request_index": 1, "query_key": "same", "request_status": "released", "release_id": "r1", "noise_sample_id": "r1", "selected_epsilon": .5, "epsilon_charged": .5},
        {"request_index": 2, "query_key": "same", "request_status": "cached", "release_id": "r1", "noise_sample_id": "r1", "selected_epsilon": .5, "epsilon_charged": 0.0},
    ]
    assert _cache_provenance_is_consistent(requests)
    assert not _cache_provenance_is_consistent([requests[0], {**requests[1], "release_id": "r2", "noise_sample_id": "r2"}])
    assert not _cache_provenance_is_consistent([requests[0], {**requests[1], "epsilon_charged": .5}])


def test_repeated_baselines_count_cache_reuse_once_and_reset_release_identity_per_trial():
    results = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M1", "M4", "M5"], "trials": 2, "repetitions": 5, "seed": 2026, "epsilon": .5, "budget_epsilon": 10})
    by_id = {row["baseline"]: row for row in results}
    assert len({row["measurements"][0]["trial_seed"] for row in results}) == 1
    assert by_id["M1"]["measurements"][0]["attack_independent_observation_count"] == 5
    assert by_id["M1"]["measurements"][0]["unique_attack_observation_count"] == 5
    specs, target, _, _ = _build_workload("repeated", list(iter_employee_rows(1, 5000, 2026)))
    expected_m1 = sum(_noise(target, specs[0].sensitivity, .5, 2026 + 10_007 * index) for index in range(5)) / 5
    expected_m4 = _noise(target, specs[0].sensitivity, .5, 2026)
    assert by_id["M1"]["measurements"][0]["attack_evidence"]["inferred_value"] == pytest.approx(expected_m1)
    assert by_id["M4"]["measurements"][0]["attack_evidence"]["inferred_value"] == pytest.approx(expected_m4)
    for baseline in ("M4", "M5"):
        item = by_id[baseline]
        first_trial = [row for row in item["request_measurements"] if row["trial"] == 1]
        second_trial = [row for row in item["request_measurements"] if row["trial"] == 2]
        first_release = [row for row in first_trial if row["request_status"] == "released"]
        first_cached = [row for row in first_trial if row["request_status"] == "cached"]
        assert len(first_release) == 1 and len(first_cached) == 4
        assert item["measurements"][0]["attack_observation_count"] == 5
        assert item["measurements"][0]["attack_independent_observation_count"] == 1
        assert item["measurements"][0]["unique_attack_observation_count"] == 1
        assert item["measurements"][0]["unique_noise_sample_count"] == 1
        assert all(row["release_id"] == first_release[0]["release_id"] for row in first_cached)
        assert all(row["epsilon_charged"] == 0 for row in first_cached)
        assert second_trial[0]["release_id"] != first_release[0]["release_id"]
        assert item["exact_cache_reuse_consistent"] is True
        assert sum(row["epsilon_charged"] for row in item["request_measurements"]) == pytest.approx(item["nominal_cumulative_epsilon"])


def test_run49_shape_repeated_campaign_records_100_requests_but_one_cached_noise_sample():
    result = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M4"], "trials": 1, "repetitions": 100, "seed": 2026, "epsilon": .5, "budget_epsilon": 10})[0]
    trial = result["measurements"][0]
    assert trial["attack_observation_count"] == 100
    assert trial["attack_independent_observation_count"] == 1
    assert trial["unique_attack_observation_count"] == 1
    assert trial["unique_noise_sample_count"] == 1
    assert trial["exact_cache_hits"] == 99
    assert trial["attack_evidence"]["estimator_version"] == "repeated-unique-release-mean-v2"
    assert trial["attack_success"] is (trial["attack_absolute_error"] <= trial["attack_success_threshold"])


def test_current_integrity_validator_checks_release_provenance_and_flags_legacy_repeated_metrics():
    result = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M4"], "trials": 2, "repetitions": 5, "seed": 2026, "epsilon": .5, "budget_epsilon": 10})[0]
    findings = validate_result_metrics(result, expected_trials=2)
    assert not any(item["status"] == INVALID for item in findings)
    broken_requests = [dict(row) for row in result["request_measurements"]]
    cached_row = next(row for row in broken_requests if row["request_status"] == "cached")
    cached_row["epsilon_charged"] = .5
    broken = {**result, "request_measurements": broken_requests}
    findings = validate_result_metrics(broken, expected_trials=2)
    assert any(item["field"].endswith("cache_provenance") and item["status"] == INVALID for item in findings)
    legacy = {**result, "metric_definition_version": "comparative-metrics-v4"}
    legacy.pop("attack_estimator_version", None)
    findings = validate_result_metrics(legacy, expected_trials=2)
    assert any(item["field"] == "attack_estimator_version" and item["status"] == UNVERIFIABLE for item in findings)


def test_raw_m0_repeated_sources_are_not_misreported_as_protected_releases():
    result = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M0"], "trials": 1, "repetitions": 5, "seed": 2026, "epsilon": .5, "budget_epsilon": 10})[0]
    trial = result["measurements"][0]
    assert trial["attack_observation_count"] == 5
    assert trial["attack_independent_observation_count"] == 0
    assert trial["unique_attack_observation_count"] == 1
    assert trial["unique_noise_sample_count"] == 0
    assert len({row["attack_source_id"] for row in result["request_measurements"]}) == 1
    findings = validate_result_metrics(result, expected_trials=1)
    assert not any(item["status"] == INVALID for item in findings)


def test_unanswered_budget_rejected_workload_does_not_report_zero_error():
    result = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M2"], "trials": 2, "repetitions": 2, "seed": 8, "epsilon": .5, "budget_epsilon": .1})[0]
    assert result["budget_rejected_requests"] == 4
    assert result["query_answerability_rate"] == 0.0
    assert result["aggregate_mae"] is None
    assert result["aggregate_rmse"] is None
    assert result["attack_success_rate"] is None
    assert result["attack_success_count"] is None
    assert result["metric_states"]["aggregate_mae"]["state"] == "NOT_MEASURED"


def test_validator_verifies_synthetic_attack_evidence_and_detects_corruption():
    result = run_comparison({"scenario": "difference", "dataset_size": 5000, "baselines": ["M1"], "trials": 2, "repetitions": 2, "seed": 29, "epsilon": .5, "budget_epsilon": 10})[0]
    findings = validate_result_metrics(result, expected_trials=2)
    assert not any(item["status"] == INVALID for item in findings)
    assert not any(item["field"] == "attack_ground_truth" for item in findings)
    evidence = result["measurements"][0]["attack_evidence"]
    assert evidence["evidence_scope"] == "synthetic_only_owner_scoped"
    assert evidence["target_reference_id"]
    assert evidence["absolute_error"] == pytest.approx(abs(evidence["inferred_value"] - evidence["target_value"]))
    broken = {**result, "attack_success_rate": 0.99}
    findings = validate_result_metrics(broken, expected_trials=2)
    assert any(item["field"] == "attack_success_rate" and item["status"] == INVALID for item in findings)
    broken_measurements = [dict(item) for item in result["measurements"]]
    broken_measurements[0]["attack_evidence"] = {**broken_measurements[0]["attack_evidence"], "absolute_error": -1}
    findings = validate_result_metrics({**result, "measurements": broken_measurements}, expected_trials=2)
    assert any(item["field"].endswith("absolute_error") and item["status"] == INVALID for item in findings)


def test_validator_detects_trial_aggregate_and_confidence_interval_corruption():
    result = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M1"], "trials": 3, "repetitions": 3, "seed": 39, "epsilon": .5, "budget_epsilon": 10})[0]
    assert not any(item["status"] == INVALID for item in validate_result_metrics(result, 3))
    altered_trial = {**result, "measurements": [dict(item) for item in result["measurements"]]}
    altered_trial["measurements"][0]["aggregate_rmse"] += 1
    findings = validate_result_metrics(altered_trial, 3)
    assert any(item["field"] == "trial[1].aggregate_rmse" and item["status"] == INVALID for item in findings)
    altered_ci = {**result, "attack_success_ci95": [0.0, 1.0]}
    findings = validate_result_metrics(altered_ci, 3)
    assert any(item["field"] == "attack_success_ci95" and item["status"] == INVALID for item in findings)


def test_validator_does_not_fail_legacy_rmse_for_unknown_aggregation_level():
    result = run_comparison({"scenario": "repeated", "dataset_size": 5000, "baselines": ["M1"], "trials": 3, "repetitions": 3, "seed": 71, "epsilon": .5, "budget_epsilon": 10})[0]
    legacy = dict(result)
    legacy["metric_definition_version"] = None
    # Earlier records used the mean of per-trial RMSE values, while v4 stores
    # pooled request-level RMSE. The historical schema does not version this.
    legacy["aggregate_rmse"] = sum(item["aggregate_rmse"] for item in legacy["measurements"]) / len(legacy["measurements"])
    findings = validate_result_metrics(legacy, expected_trials=3)
    assert not any(item["status"] == INVALID and item["field"] == "aggregate_rmse" for item in findings)
    assert any(item["field"] == "aggregate_rmse_aggregation" and item["status"] == UNVERIFIABLE for item in findings)


def test_integrity_report_contains_context_and_action_without_writing_history():
    metrics = run_comparison({"scenario": "difference", "dataset_size": 5000, "baselines": ["M1"], "trials": 2, "repetitions": 2, "seed": 72, "epsilon": .5, "budget_epsilon": 10})
    broken_metrics = dict(metrics[0])
    broken_metrics["measurements"] = [dict(item) for item in broken_metrics["measurements"]]
    broken_metrics["measurements"][0]["attack_evidence"] = None
    report = validate_run({"baselines": ["M1"], "trials": 2, "scenario": "difference", "dataset_size": 5000}, [{"baseline": "M1", "metrics": broken_metrics}], experiment_id=123)
    finding = next(item for item in report["findings"] if item["field"].endswith("attack_evidence"))
    assert finding["experiment_id"] == 123
    assert finding["scenario"] == "difference"
    assert finding["dataset"] == 5000
    assert finding["baselines"] == ["M1"]
    assert finding["metric"].endswith("attack_evidence")
    assert finding["evidence"]["observed"] == "None"
    assert finding["suggested_action"]


def test_run_validator_explains_when_shared_budget_or_cache_were_not_exercised():
    metrics = run_comparison({"scenario": "difference", "dataset_size": 5000, "baselines": ["M1", "M2", "M4"], "trials": 2, "repetitions": 2, "seed": 29, "epsilon": .5, "budget_epsilon": 10})
    config = {"baselines": ["M1", "M2", "M4"], "trials": 2, "scenario": "difference"}
    report = validate_run(config, [{"baseline": item["baseline"], "metrics": item} for item in metrics])
    fields = {item["field"] for item in report["findings"]}
    assert "M1_vs_M2" in fields
    assert "M1_vs_M4" in fields
    assert report["status"] == "WARNING"


def test_historical_run_validation_does_not_fill_unknown_versions():
    report = validate_run({"baselines": ["B0", "B4"], "trials": 2}, [
        {"baseline": "B0", "metrics": {"baseline": "B0", "measurements": []}},
        {"baseline": "B4", "metrics": {"baseline": "B4", "measurements": []}},
    ])
    assert report["status"] == INVALID
    assert any(item["field"] == "experiment_versions" and item["status"] == UNVERIFIABLE for item in report["findings"])
    assert report["baseline_reports"]["B4"]["status"] == INVALID


def test_experiment_api_authorization_persistence_and_csv_export(experiment_db):
    factory, researcher_id, denied_id = experiment_db
    registered_paths = app.openapi()["paths"]
    assert set(registered_paths) >= {
        "/api/experiments/runs", "/api/experiments/runs/{run_id}",
        "/api/experiments/runs/{run_id}/export.csv", "/api/experiments/runs/{run_id}/paired-comparisons", "/api/attacks/simulate", "/api/experiments/benchmark-results",
        "/api/experiments/benchmark-runs",
    }
    with factory() as db:
        with pytest.raises(HTTPException) as unauthorized:
            current_user("not-a-valid-token", db)
        assert unauthorized.value.status_code == 401
        denied = db.get(User, denied_id)
        with pytest.raises(HTTPException) as forbidden:
            require_permission("experiments:run")(user=denied, db=db)
        assert forbidden.value.status_code == 403

        researcher = db.get(User, researcher_id)
        payload = ExperimentRunRequest(scenario="difference", dataset_size=5000, baselines=["M0", "M1", "M2", "M3", "M4", "M5"], trials=2, repetitions=3, seed=22, epsilon=.5, budget_epsilon=10)
        run = simulate_attack(payload, researcher, db)
        assert run["status"] == "completed"
        assert run["validation_status"] in {"WARNING", "UNVERIFIABLE"}
        assert run["configuration"]["experiment_engine_version"] == "synthetic-engine-v6"
        assert len(run["results"]) == 6
        body = str(run)
        assert "raw_aggregate" not in body and "target_salary" not in body
        assert list_experiment_runs(page=1, page_size=20, user=researcher, db=db)["total"] == 1
        run_id = run["id"]
        assert run["configuration"]["protocol"]["version"] == "privacyguard-research-protocol-v2"
        assert run["configuration"]["protocol"]["trials"]["trial_seeds"] == [22, 1_000_025]
        assert run["quality_control"]["status"] in {"completed_with_warnings", "valid_completed"}
        paired = get_paired_experiment_comparisons(run_id, "M1", researcher, db)
        assert paired["status"] == "AVAILABLE"
        assert paired["comparisons"]
        assert all(item["status"] == "exploratory" for item in paired["comparisons"])
        benchmark_page = list_benchmark_results(page=1, page_size=20, scenario="difference", dataset_size=5000, baseline="M5", trials=None, run_id=None, date_from=None, date_to=None, user=researcher, db=db)
        assert benchmark_page["total"] == 1
        assert len(benchmark_page["items"][0]["results"]) == 6
        summaries = list_benchmark_run_summaries(page=1, page_size=20, scenario="difference", dataset_size=5000, baseline="M5", trials=None, run_id=None, date_from=None, date_to=None, user=researcher, db=db)
        assert summaries["total"] == 1
        assert summaries["items"][0]["id"] == run_id
        assert "results" not in summaries["items"][0]
        assert list_benchmark_run_summaries(page=1, page_size=20, scenario=None, dataset_size=None, baseline=None, trials=None, run_id=None, date_from=None, date_to=None, user=db.get(User, denied_id), db=db)["total"] == 0
        assert list_benchmark_results(page=1, page_size=20, scenario=None, dataset_size=None, baseline=None, trials=None, run_id=None, date_from=None, date_to=None, user=db.get(User, denied_id), db=db)["total"] == 0
        assert get_experiment_run(run_id, researcher, db)["id"] == run_id
        csv_response = export_experiment_csv(run_id, researcher, db)
        assert csv_response.status_code == 200
        assert b"attack_absolute_error" in csv_response.body
        assert b"metric_states" in csv_response.body
        assert b"protocol_json" in csv_response.body
        assert b"attack_evidence_json" in csv_response.body
        assert b"target_salary" not in csv_response.body
        with pytest.raises(HTTPException) as owner_denied:
            get_experiment_run(run_id, db.get(User, denied_id), db)
        assert owner_denied.value.status_code == 404
        with pytest.raises(HTTPException) as paired_owner_denied:
            get_paired_experiment_comparisons(run_id, "M1", db.get(User, denied_id), db)
        assert paired_owner_denied.value.status_code == 404
        with pytest.raises(HTTPException) as csv_owner_denied:
            export_experiment_csv(run_id, db.get(User, denied_id), db)
        assert csv_owner_denied.value.status_code == 404
        assert db.query(ExperimentRun).filter_by(owner_user_id=researcher_id).count() == 1


def test_small_four_scenario_campaign_persists_matched_six_baseline_results(experiment_db):
    factory, researcher_id, _ = experiment_db
    with factory() as db:
        researcher = db.get(User, researcher_id)
        for scenario in ("difference", "repeated", "narrowing", "overlapping"):
            payload = ExperimentRunRequest(
                scenario=scenario, dataset_size=5000,
                baselines=["M0", "M1", "M2", "M3", "M4", "M5"],
                trials=5, repetitions=3, seed=20261125, epsilon=.5, budget_epsilon=10,
                history_depth=0, trial_seed_strategy="matched_sequential", ablation_mode="full",
            )
            saved = simulate_attack(payload, researcher, db)
            assert saved["status"] == "completed"
        assert saved["configuration"]["metric_definition_version"] == "comparative-metrics-v5"
        assert saved["configuration"]["trial_seed_schedule"]["shared_across_baselines"] is True
        assert [item["baseline"] for item in saved["results"]] == ["M0", "M1", "M2", "M3", "M4", "M5"]
        assert all(item["metrics"]["trial_count"] == 5 for item in saved["results"])
        assert all(item["metrics"]["scenario_definition"]["version"] == "attack-scenarios-v4" for item in saved["results"])
        assert all(item["metrics"]["accounting_status"] != "formal_dp_certified" for item in saved["results"])
        m1_request_keys = [row["query_key"] for row in saved["results"][1]["metrics"]["request_measurements"] if row["trial"] == 1]
        m5_request_keys = [row["query_key"] for row in saved["results"][5]["metrics"]["request_measurements"] if row["trial"] == 1]
        assert m1_request_keys == m5_request_keys
        restored = get_experiment_run(saved["id"], researcher, db)
        assert restored["results"] == saved["results"]
        csv = export_experiment_csv(saved["id"], researcher, db)
        assert csv.status_code == 200 and b"nominal_epsilon_spent" in csv.body


@pytest.mark.parametrize("payload", [
    {"scenario": "not-a-scenario"},
    {"dataset_size": 999},
    {"baselines": ["B1", "B1"]},
    {"baselines": ["B9"]},
    {"trials": 31},
    {"epsilon": 1.1},
    {"seed": -1},
    {"history_depth": 3},
    {"trial_seed_strategy": "unmatched"},
    {"ablation_mode": "production_policy_change"},
])
def test_invalid_experiment_configuration_is_rejected(payload):
    with pytest.raises(ValueError):
        ExperimentRunRequest(**payload)
