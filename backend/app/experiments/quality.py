"""Quality-control classification for completed and interrupted experiment runs."""
from __future__ import annotations

from typing import Any


def classify_quality(run_status: str, configuration: dict[str, Any], results: list[dict[str, Any]], validation_report: dict[str, Any]) -> dict[str, Any]:
    if run_status == "failed":
        return {"status": "failed", "reasons": ["Experiment execution failed; no complete result set is available."], "inferentially_eligible": False}
    expected = configuration.get("trials")
    expected_baselines = configuration.get("baselines")
    observed_baselines = [row.get("baseline") for row in results]
    incomplete_trials = isinstance(expected, int) and any(
        [item.get("trial") for item in ((row.get("metrics") or {}).get("measurements", [])) if isinstance(item, dict)]
        != list(range(1, expected + 1))
        for row in results
    )
    missing_baseline = isinstance(expected_baselines, list) and (
        len(observed_baselines) != len(set(observed_baselines)) or set(expected_baselines) != set(observed_baselines)
    )
    if run_status != "completed" or not results or incomplete_trials or missing_baseline:
        reasons = ["The run is not fully completed or one or more baselines lack the configured trial set."]
        if missing_baseline:
            reasons.append("Persisted baseline rows do not exactly match the requested configuration.")
        return {"status": "partial", "reasons": reasons, "inferentially_eligible": False}
    if validation_report.get("status") == "FAIL":
        return {"status": "invalid", "reasons": ["Persisted result evidence contradicts one or more integrity checks."], "inferentially_eligible": False}
    protocol = configuration.get("protocol")
    reasons: list[str] = []
    findings = validation_report.get("findings", [])
    hard_findings = [item for item in findings if item.get("status") in {"FAIL", "UNVERIFIABLE"}]
    if hard_findings:
        reasons.append(f"{len(hard_findings)} integrity check(s) failed or cannot be verified from persisted evidence.")
    relevant_warnings = [item for item in findings if item.get("status") == "WARNING" and item.get("field") in {
        "M1_vs_M2", "M1_vs_M4", "attack_success_ci95", "statistical_method", "scenario_definition",
    }]
    if relevant_warnings:
        reasons.append(f"{len(relevant_warnings)} protocol or baseline-comparability warning(s) require interpretation.")
    if not isinstance(protocol, dict) or not protocol.get("version"):
        reasons.append("A versioned experiment protocol is missing.")
    if isinstance(expected, int) and expected < 20:
        reasons.append("Fewer than 20 paired trials; findings are exploratory and no inferential label is available.")
    if reasons:
        return {"status": "completed_with_warnings", "reasons": reasons, "inferentially_eligible": bool(isinstance(expected, int) and expected >= 20 and protocol and not hard_findings)}
    return {"status": "valid_completed", "reasons": [], "inferentially_eligible": True}
