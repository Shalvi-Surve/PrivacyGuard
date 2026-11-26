from app.experiments.engine import _build_workload
from app.experiments.protocol import PROTOCOL_VERSION, make_protocol
from app.experiments.quality import classify_quality
from app.experiments.statistics import compare_protocol_compatibility, paired_comparisons
from app.experiments.validation import validate_run


def _config(trials=4):
    return {
        "scenario": "overlapping", "dataset_size": 5000, "baselines": ["M1", "M5"],
        "trials": trials, "repetitions": 4, "seed": 91, "epsilon": 0.5,
        "budget_epsilon": 10, "trial_seed_strategy": "matched_sequential",
        "attack_relative_success_tolerance": 0.05,
        "narrowing_absolute_success_tolerance": 1,
    }


def test_protocol_records_semantics_seeds_and_all_baseline_parameters():
    config = _config()
    config["baselines"] = ["M0", "M1", "M2", "M3", "M4", "M5"]
    protocol = make_protocol(config)
    assert protocol["version"] == PROTOCOL_VERSION
    assert protocol["trials"]["trial_seeds"] == [91, 1_000_094, 2_000_097, 3_000_100]
    assert protocol["scenario"]["estimator"] == "Engineering SUM + North SUM - (Engineering UNION North) SUM"
    assert protocol["dataset"]["registered_dataset_access"] is False
    assert next(item for item in protocol["baselines"] if item["id"] == "M3")["configured_epsilon"] == 0.5
    assert protocol["privacy_parameters"]["privacy_status"].startswith("nominal_uncertified")
    m5 = next(item for item in protocol["baselines"] if item["id"] == "M5")["adaptive_policy"]
    assert m5["policy_id"] == "query-history-adaptive-nominal-v2"
    assert "exact repeats reuse the stored release" in m5["cache_policy"]
    assert m5["risk_penalty"] == 0.1 and m5["cumulative_penalty"] == 0.05


def test_repeated_protocol_versions_unique_release_estimator_without_retrofitting_v2():
    config = _config()
    config.update({"scenario": "repeated", "baselines": ["M1", "M4", "M5"], "repetitions": 100})
    protocol = make_protocol(config)
    assert protocol["version"] == "privacyguard-research-protocol-v2"
    assert protocol["scenario"]["estimator"].startswith("Arithmetic mean of unique independent release outputs")
    assert protocol["attack_parameters"]["estimator_version"] == "repeated-unique-release-mean-v2"
    assert "cached requests reference the original release" in protocol["attack_parameters"]["repeated_cache_handling"]
    assert protocol["metric_definitions"]["version"] == "comparative-metrics-v5"


def test_overlap_workload_uses_every_query_in_its_intersection_estimator():
    rows = [
        {"employee_id": "e1", "department": "Engineering", "location": "North", "salary": 10},
        {"employee_id": "e2", "department": "Engineering", "location": "South", "salary": 20},
        {"employee_id": "e3", "department": "Sales", "location": "North", "salary": 30},
    ]
    queries, truth, group_size, target_id = _build_workload("overlapping", rows)
    assert [query.key for query in queries] == ["overlap:a", "overlap:north", "overlap:union"]
    assert queries[0].truth + queries[1].truth - queries[2].truth == truth == 10
    assert group_size == 1
    assert target_id == "synthetic-cohort:engineering-and-north"


def test_paired_analysis_requires_matched_evidence_and_is_exploratory_below_20():
    config = _config()
    config["protocol"] = make_protocol(config)
    seeds = config["protocol"]["trials"]["trial_seeds"]
    reference = {"baseline": "M1", "metrics": {"protocol_version": PROTOCOL_VERSION, "measurements": [
        {"trial": i + 1, "trial_seed": seed, "attack_success": bool(i % 2), "attack_absolute_error": float(i),
         "aggregate_mae": float(i + 1), "aggregate_rmse": float(i + 2), "query_latency_ms_mean": float(2 * i), "nominal_epsilon_spent": 0.5}
        for i, seed in enumerate(seeds)
    ]}}
    candidate = {"baseline": "M5", "metrics": {"protocol_version": PROTOCOL_VERSION, "measurements": [
        {"trial": i + 1, "trial_seed": seed, "attack_success": bool((i + 1) % 2), "attack_absolute_error": float(i + 1),
         "aggregate_mae": float(i + 2), "aggregate_rmse": float(i + 3), "query_latency_ms_mean": float(2 * i + 1), "nominal_epsilon_spent": 0.25}
        for i, seed in enumerate(seeds)
    ]}}
    report = paired_comparisons([reference, candidate], config)
    assert report["status"] == "AVAILABLE"
    attack = next(item for item in report["comparisons"] if item["metric"] == "attack_success")
    assert attack["n_pairs"] == 4
    assert attack["status"] == "exploratory"
    assert attack["raw_p_value"] is not None
    continuous = next(item for item in report["comparisons"] if item["metric"] == "aggregate_mae")
    assert continuous["mean_difference_baseline_minus_reference"] == 1.0
    assert continuous["ci95_mean_difference"][0] is not None
    assert continuous["effect_size_paired_dz"] is None  # zero-variance paired differences
    candidate["metrics"]["measurements"][0]["trial_seed"] += 1
    assert paired_comparisons([reference, candidate], config)["status"] == "INCOMPATIBLE"


def test_paired_comparisons_withhold_invalid_integrity_and_nonfinite_metrics():
    config = _config(2)
    config["protocol"] = make_protocol(config)
    seeds = config["protocol"]["trials"]["trial_seeds"]
    measurements = [{"trial": i + 1, "trial_seed": seed, "attack_success": False, "attack_absolute_error": 1.0,
                     "aggregate_mae": 2.0, "aggregate_rmse": 3.0, "query_latency_ms_mean": 4.0, "nominal_epsilon_spent": 0.5}
                    for i, seed in enumerate(seeds)]
    rows = [{"baseline": baseline, "metrics": {"protocol_version": PROTOCOL_VERSION, "measurements": [dict(item) for item in measurements]}}
            for baseline in ("M1", "M5")]
    assert paired_comparisons(rows, config, validation_status="FAIL")["comparisons"] == []
    rows[1]["metrics"]["measurements"][0]["aggregate_mae"] = float("nan")
    report = paired_comparisons(rows, config)
    assert report["status"] == "INCOMPATIBLE"
    assert "Non-finite" in report["reason"]


def test_legacy_repeated_results_are_ineligible_for_confirmatory_paired_analysis():
    config = _config(20)
    config.update({"scenario": "repeated", "baselines": ["M1", "M4"]})
    config["protocol"] = make_protocol(config)
    seeds = config["protocol"]["trials"]["trial_seeds"]
    rows = [{"baseline": baseline, "metrics": {"protocol_version": PROTOCOL_VERSION, "measurements": [
        {"trial": index + 1, "trial_seed": seed, "attack_success": False, "attack_absolute_error": 1.0,
         "aggregate_mae": 1.0, "aggregate_rmse": 1.0, "query_latency_ms_mean": 1.0, "nominal_epsilon_spent": 1.0}
        for index, seed in enumerate(seeds)
    ]}} for baseline in ("M1", "M4")]
    report = paired_comparisons(rows, config)
    assert report["status"] == "INELIGIBLE"
    assert "descriptive historical evidence only" in report["reason"]


def test_cross_run_compatibility_and_quality_status_do_not_retrofit_legacy_protocols():
    config = _config()
    protocol = make_protocol(config)
    left = {"protocol": protocol}
    assert compare_protocol_compatibility(left, {"protocol": protocol})["compatible"] is True
    altered = {"protocol": {**protocol, "dataset": {**protocol["dataset"], "seed": 92}}}
    assert compare_protocol_compatibility(left, altered)["compatible"] is False
    altered_version = {"protocol": {**protocol, "version": "privacyguard-research-protocol-v3"}}
    assert compare_protocol_compatibility(left, altered_version)["compatible"] is False
    report = validate_run({"scenario": "overlapping", "dataset_size": 5000, "seed": 91, "trials": 4, "baselines": ["M1"]}, [], experiment_id=44)
    assert any(item["field"] == "experiment_protocol" and item["status"] == "UNVERIFIABLE" for item in report["findings"])
    quality = classify_quality("completed", {"trials": 4, "baselines": ["M1"]}, [{"baseline": "M1", "metrics": {"measurements": [{"trial": number} for number in range(1, 5)]}}], {
        "status": "UNVERIFIABLE", "findings": [{"status": "UNVERIFIABLE", "field": "experiment_protocol"}],
    })
    assert quality["status"] == "completed_with_warnings"
    assert quality["inferentially_eligible"] is False


def test_quality_control_distinguishes_failed_partial_invalid_and_valid_protocol_v2():
    protocol_config = _config(20)
    protocol_config["protocol"] = make_protocol(protocol_config)
    rows = [{"baseline": baseline, "metrics": {"measurements": [{"trial": trial} for trial in range(1, 21)]}}
            for baseline in protocol_config["baselines"]]
    clean_report = {"status": "PASS", "findings": []}
    assert classify_quality("failed", protocol_config, [], clean_report)["status"] == "failed"
    assert classify_quality("running", protocol_config, rows, clean_report)["status"] == "partial"
    assert classify_quality("completed", protocol_config, rows[:1], clean_report)["status"] == "partial"
    assert classify_quality("completed", protocol_config, rows, {"status": "FAIL", "findings": []})["status"] == "invalid"
    valid = classify_quality("completed", protocol_config, rows, clean_report)
    assert valid == {"status": "valid_completed", "reasons": [], "inferentially_eligible": True}
