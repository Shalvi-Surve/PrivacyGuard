"""One-off isolated calibration; does not use the project database."""
import json

from app.experiments.engine import run_comparison


profiles = [("original-penalties", .6, .3), ("balanced", .2, .1), ("gentle", .1, .05), ("gentle-plus", .12, .06), ("mid", .15, .075), ("moderate", .3, .15), ("strong-moderate", .4, .2)]
base = {"dataset_size": 5000, "trials": 5, "repetitions": 5, "seed": 83021,
        "epsilon": .5, "budget_epsilon": 10, "baselines": ["M1", "M4", "M5"]}
report = []
for scenario in ("difference", "repeated"):
    for profile, risk_penalty, cumulative_penalty in profiles:
        rows = run_comparison({**base, "scenario": scenario,
                              "adaptive_risk_penalty": risk_penalty,
                              "adaptive_cumulative_penalty": cumulative_penalty})
        by_id = {row["baseline"]: row for row in rows}
        reference_id = "M4" if scenario == "repeated" else "M1"
        reference, adaptive = by_id[reference_id], by_id["M5"]
        report.append({"scenario": scenario, "profile": profile,
                       "alpha": risk_penalty, "gamma": cumulative_penalty,
                       "reference": reference_id,
                       "reference_epsilon": round(reference["mean_nominal_epsilon_per_trial"], 5),
                       "reference_mae": round(reference["aggregate_mae"], 2),
                       "reference_successes": f'{reference["attack_success_count"]}/{reference["attack_attempt_count"]}',
                       "m5_epsilon": round(adaptive["mean_nominal_epsilon_per_trial"], 5),
                       "m5_mean_risk": round(adaptive["mean_risk_score"], 5),
                       "m5_mean_selected_epsilon": round(adaptive["mean_selected_epsilon"], 5) if adaptive["mean_selected_epsilon"] is not None else None,
                       "m5_mae": round(adaptive["aggregate_mae"], 2),
                       "m5_successes": f'{adaptive["attack_success_count"]}/{adaptive["attack_attempt_count"]}',
                       "m5_releases": adaptive["independent_releases"],
                       "m5_cache_hits": adaptive["exact_cache_hits"],
                       "m5_budget_rejections": adaptive["budget_rejected_requests"],
                       "m5_history_lookup_ms": round(adaptive["history_lookup_ms_mean"], 6),
                       "m5_risk_policy_ms": round(adaptive["risk_policy_ms_mean"], 6)})
print(json.dumps(report, indent=2))
