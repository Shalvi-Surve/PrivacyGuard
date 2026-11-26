"""Terminal-only launcher for the locked PrivacyGuard validation campaign.

This script uses only the application's public authenticated HTTP API. It never
opens or edits the SQLite database and never stores credentials or bearer tokens.
"""
from __future__ import annotations

import getpass
import hashlib
import ipaddress
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
CONFIRMATION = "RUN PRIVACYGUARD VALIDATION"
SCENARIOS = ("difference", "repeated", "narrowing", "overlapping")
BASELINES = ("M0", "M1", "M2", "M3", "M4", "M5")
LOCKED_PAYLOAD: dict[str, Any] = {
    "dataset_size": 5000,
    "baselines": list(BASELINES),
    "trials": 20,
    "repetitions": 20,
    "repeat_query_mode": "identical",
    "seed": 20261126,
    "epsilon": 0.5,
    "budget_epsilon": 5.0,
    "adaptive_epsilon_min": 0.1,
    "adaptive_risk_penalty": 0.10,
    "adaptive_cumulative_penalty": 0.05,
    "attack_relative_success_tolerance": 0.05,
    "narrowing_absolute_success_tolerance": 1.0,
    "trial_seed_strategy": "matched_hashed",
    "history_depth": 0,
    "ablation_mode": "full",
}
REQUEST_TIMEOUT_SECONDS = 1800
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 1800


def locked_trial_seeds() -> list[int]:
    return [
        int.from_bytes(hashlib.sha256(f"{LOCKED_PAYLOAD['seed']}:{index}:trial".encode("ascii")).digest()[:4], "big")
        for index in range(LOCKED_PAYLOAD["trials"])
    ]


class CampaignError(RuntimeError):
    """Safe, user-facing error which never contains credentials or response bodies."""


class HttpApi:
    def __init__(
        self,
        base_url: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise CampaignError("API URL must be an HTTP(S) origin without embedded credentials.")
        host = parsed.hostname or ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"
        if not loopback or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise CampaignError("For credential safety, API URL must be a local loopback origin (localhost, 127.0.0.1, or ::1).")
        self.base_url = base_url.rstrip("/")
        self._opener = opener
        self._timeout = timeout
        self._token: str | None = None

    def set_token(self, token: str) -> None:
        self._token = token

    def request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                raise CampaignError("Authentication failed or the session expired (HTTP 401).") from None
            if exc.code == 403:
                raise CampaignError("The account is authenticated but lacks experiments:run permission (HTTP 403).") from None
            if exc.code == 404:
                raise CampaignError(f"Required API route is unavailable (HTTP 404): {path}") from None
            raise CampaignError(f"Backend returned HTTP {exc.code} for {method} {path}.") from None
        except (TimeoutError, OSError) as exc:
            reason = "timed out" if isinstance(exc, TimeoutError) else "could not be reached"
            raise CampaignError(f"Request {method} {path} {reason}; execution status may be uncertain.") from None
        except URLError as exc:
            reason = "timed out" if isinstance(exc.reason, TimeoutError) else "could not be reached"
            raise CampaignError(f"Request {method} {path} {reason}; execution status may be uncertain.") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CampaignError(f"Backend returned an invalid JSON response for {method} {path}.") from None

    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        response = self.request("POST", "/api/auth/login", payload={"username": username, "password": password})
        token = response.get("access_token") if isinstance(response, dict) else None
        if not isinstance(token, str) or not token:
            raise CampaignError("Login response did not contain an access token.")
        self.set_token(token)
        identity = self.request("GET", "/api/auth/me")
        if not isinstance(identity, dict) or not identity.get("is_active"):
            raise CampaignError("The authenticated account is missing or inactive.")
        roles = identity.get("roles")
        if not isinstance(roles, list) or "researcher" not in roles:
            raise CampaignError("Sign in with an active Researcher account; no campaign was submitted.")
        # This owner-scoped read endpoint uses the exact same RBAC dependency as
        # POST /runs, so a successful request verifies effective DB permission.
        self.request("GET", "/api/experiments/runs?page=1&page_size=1")
        return identity

    def list_runs(self) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            response = self.request("GET", f"/api/experiments/runs?page={page}&page_size=100")
            if not isinstance(response, dict) or not isinstance(response.get("items"), list):
                raise CampaignError("Experiment run listing returned an unexpected response schema.")
            current = response["items"]
            items.extend(item for item in current if isinstance(item, dict))
            if len(items) >= int(response.get("total", len(items))) or not current:
                return items
            page += 1

    def get_run(self, run_id: int) -> dict[str, Any]:
        response = self.request("GET", f"/api/experiments/runs/{run_id}")
        if not isinstance(response, dict) or response.get("id") != run_id:
            raise CampaignError(f"Persisted run {run_id} returned an unexpected response schema.")
        return response

    def verify_benchmark_visibility(self, run_id: int) -> bool:
        response = self.request("GET", f"/api/experiments/benchmark-results?run_id={run_id}&page=1&page_size=20")
        if not isinstance(response, dict) or not isinstance(response.get("items"), list):
            raise CampaignError("Comparative Results endpoint returned an unexpected response schema.")
        return any(isinstance(item, dict) and item.get("id") == run_id for item in response["items"])


def _campaign_payload(scenario: str) -> dict[str, Any]:
    return {"scenario": scenario, **LOCKED_PAYLOAD}


def _matching_locked_run(run: dict[str, Any], scenario: str) -> bool:
    config = run.get("configuration")
    if not isinstance(config, dict):
        return False
    expected = _campaign_payload(scenario)
    if any(config.get(key) != value for key, value in expected.items()):
        return False
    protocol = config.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("version") != "privacyguard-research-protocol-v2":
        return False
    trial_seeds = (protocol.get("trials") or {}).get("trial_seeds")
    expected_seeds = locked_trial_seeds()
    return (
        protocol.get("scenario_identifier") == scenario
        and (protocol.get("trials") or {}).get("count") == 20
        and (protocol.get("dataset") or {}).get("row_count") == 5000
        and (protocol.get("privacy_parameters") or {}).get("adaptive_risk_penalty") == 0.10
        and (protocol.get("privacy_parameters") or {}).get("adaptive_cumulative_penalty") == 0.05
        and isinstance(trial_seeds, list)
        and trial_seeds == expected_seeds
        and (protocol.get("trials") or {}).get("trial_seed_strategy") == "matched_hashed"
        and config.get("trial_seed_schedule", {}).get("trial_seeds") == expected_seeds
    )


def _format_metric(value: Any, suffix: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "Not measured"
    return f"{value:.6g}{suffix}"


def _format_fraction_percent(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "Not measured"
    return f"{value * 100:.6g}%"


def summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    baselines: list[dict[str, Any]] = []
    for row in run.get("results", []) if isinstance(run.get("results"), list) else []:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, dict):
            continue
        baselines.append({
            "baseline": row.get("baseline"),
            "trials": len(metrics.get("measurements", [])) if isinstance(metrics.get("measurements"), list) else 0,
            "attack_success_count": metrics.get("attack_success_count"),
            "attack_attempt_count": metrics.get("attack_attempt_count"),
            "attack_success_rate": metrics.get("attack_success_rate"),
            "attack_success_ci95": metrics.get("attack_success_ci95"),
            "aggregate_mae": metrics.get("aggregate_mae"),
            "aggregate_rmse": metrics.get("aggregate_rmse"),
            "nominal_cumulative_epsilon": metrics.get("nominal_cumulative_epsilon"),
            "mean_nominal_epsilon_per_trial": metrics.get("mean_nominal_epsilon_per_trial"),
            "remaining_nominal_budget_per_trial_mean": metrics.get("remaining_nominal_budget_per_trial_mean"),
            "budget_utilization_percentage": metrics.get("budget_utilization_percentage"),
            "independent_releases": metrics.get("independent_releases"),
            "exact_cache_hits": metrics.get("exact_cache_hits"),
            "exact_cache_hit_rate": metrics.get("exact_cache_hit_rate"),
            "mean_risk_score": metrics.get("mean_risk_score"),
            "mean_selected_epsilon": metrics.get("mean_selected_epsilon"),
            "mean_history_overlap": metrics.get("mean_history_overlap"),
            "mean_repetition_signal": metrics.get("mean_repetition_signal"),
            "budget_rejected_requests": metrics.get("budget_rejected_requests"),
            "query_answerability_rate": metrics.get("query_answerability_rate"),
            "legitimate_query_rejection_rate": metrics.get("legitimate_query_rejection_rate"),
            "inference_absolute_error": metrics.get("inference_absolute_error"),
            "inference_rmse": metrics.get("inference_rmse"),
            "relative_inference_error": metrics.get("relative_inference_error"),
            "aggregate_relative_error": metrics.get("aggregate_relative_error"),
            "query_latency_ms_mean": metrics.get("query_latency_ms_mean"),
            "query_latency_ms_median": metrics.get("query_latency_ms_median"),
            "query_latency_ms_p95": metrics.get("query_latency_ms_p95"),
            "history_lookup_ms_mean": metrics.get("history_lookup_ms_mean"),
            "risk_policy_ms_mean": metrics.get("risk_policy_ms_mean"),
            "release_execution_ms_mean": metrics.get("release_execution_ms_mean"),
        })
    return {
        "id": run.get("id"),
        "scenario": (run.get("configuration") or {}).get("scenario"),
        "status": run.get("status"),
        "protocol_version": (run.get("configuration") or {}).get("protocol_version"),
        "validation_status": run.get("validation_status"),
        "quality_control": run.get("quality_control"),
        "comparative_results_visible": run.get("comparative_results_visible"),
        "validation_report": run.get("validation_report"),
        "paired_comparisons": run.get("paired_comparisons"),
        "baselines": baselines,
    }


def build_report(runs: list[dict[str, Any]], *, status: str, notes: list[str] | None = None) -> str:
    lines = [
        "# PrivacyGuard locked validation campaign report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Campaign status: **{status}**",
        f"- Protocol: `privacyguard-research-protocol-v2`",
        "- Scope: synthetic employees only; registered datasets are not read.",
        "- Privacy accounting: nominal and uncertified; this report does not establish an end-to-end DP guarantee.",
        "- Statistical interpretation: exploratory validation; do not infer superiority without compatible paired results and multiplicity-aware analysis.",
        "",
        "## Locked configuration",
        "",
        "- Dataset: Synthetic Employees, 5,000 rows; base seed 20261126.",
        "- Scenarios: difference, repeated, narrowing, overlapping.",
        "- Baselines: M0–M5; 20 matched trials per scenario.",
        "- Fixed epsilon: 0.5; per-trial nominal budget: 5.0.",
        "- M5 risk penalty α: 0.10; cumulative-use penalty γ: 0.05; adaptive epsilon minimum: 0.1.",
        "- Trial seed strategy: matched_hashed; repeated-query mode: identical; history depth: 0; ablation: full.",
        "- Matched trial seeds: `" + ", ".join(str(seed) for seed in locked_trial_seeds()) + "`.",
        "",
        "## Results",
        "",
    ]
    if not runs:
        lines.append("No run result was confirmed from the authenticated API.")
    for raw_run in runs:
        run = summarize_run(raw_run)
        lines.extend([
            f"### Run {run.get('id', 'unknown')} — {run.get('scenario', 'unknown')} — {run.get('status', 'unknown')}",
            "",
            f"- Protocol: {run.get('protocol_version') or 'Not available'}; integrity: {run.get('validation_status') or 'Not available'}; quality: {(run.get('quality_control') or {}).get('status', 'Not available')}.",
            f"- Inferential eligibility: {(run.get('quality_control') or {}).get('inferentially_eligible', 'Not available')}; paired analysis status: {(run.get('paired_comparisons') or {}).get('status', 'Not available')}.",
            f"- Comparative Results API visibility: {run.get('comparative_results_visible', 'Not checked')}.",
        ])
        for baseline in run.get("baselines", []):
            success = baseline.get("attack_success_count")
            attempts = baseline.get("attack_attempt_count")
            success_count = f"{success}/{attempts}" if isinstance(success, int) and isinstance(attempts, int) else "Not measured"
            interval = baseline.get("attack_success_ci95")
            ci_text = f"[{_format_fraction_percent(interval[0])}, {_format_fraction_percent(interval[1])}]" if isinstance(interval, list) and len(interval) == 2 else "Not measured"
            lines.extend([
                f"#### {baseline.get('baseline', '?')} — {baseline.get('trials', 0)} trial records",
                f"- Attack: {success_count} successes; observed rate {_format_fraction_percent(baseline.get('attack_success_rate'))}; Wilson 95% CI {ci_text}.",
                f"- Inference error: MAE {_format_metric(baseline.get('inference_absolute_error'))}; RMSE {_format_metric(baseline.get('inference_rmse'))}; relative {_format_fraction_percent(baseline.get('relative_inference_error'))}.",
                f"- Aggregate utility: MAE {_format_metric(baseline.get('aggregate_mae'))}; RMSE {_format_metric(baseline.get('aggregate_rmse'))}; relative error {_format_fraction_percent(baseline.get('aggregate_relative_error'))}.",
                f"- Nominal / uncertified accounting: total ε {_format_metric(baseline.get('nominal_cumulative_epsilon'))}; mean per-trial ε {_format_metric(baseline.get('mean_nominal_epsilon_per_trial'))}; mean remaining budget {_format_metric(baseline.get('remaining_nominal_budget_per_trial_mean'))}; utilization {_format_metric(baseline.get('budget_utilization_percentage'), '%')}; budget rejections {_format_metric(baseline.get('budget_rejected_requests'))}.",
                f"- Cache: {_format_metric(baseline.get('exact_cache_hits'))} exact hits; hit rate {_format_fraction_percent(baseline.get('exact_cache_hit_rate'))}; independent releases {_format_metric(baseline.get('independent_releases'))}.",
                f"- Adaptive signals: mean risk {_format_metric(baseline.get('mean_risk_score'))}; selected ε {_format_metric(baseline.get('mean_selected_epsilon'))}; history overlap {_format_metric(baseline.get('mean_history_overlap'))}; repetition signal {_format_metric(baseline.get('mean_repetition_signal'))}.",
                f"- Request outcomes: answerability {_format_fraction_percent(baseline.get('query_answerability_rate'))}; legitimate-query rejection {_format_fraction_percent(baseline.get('legitimate_query_rejection_rate'))}.",
                f"- Timing (synthetic engine, not production API latency): mean {_format_metric(baseline.get('query_latency_ms_mean'), ' ms')}; median {_format_metric(baseline.get('query_latency_ms_median'), ' ms')}; p95 {_format_metric(baseline.get('query_latency_ms_p95'), ' ms')}; history lookup {_format_metric(baseline.get('history_lookup_ms_mean'), ' ms')}; policy {_format_metric(baseline.get('risk_policy_ms_mean'), ' ms')}; release {_format_metric(baseline.get('release_execution_ms_mean'), ' ms')}.",
            ])
        report = run.get("validation_report") or {}
        findings = report.get("findings", []) if isinstance(report, dict) else []
        lines.append(f"- Integrity findings: {len(findings)}.")
        for finding in findings:
            if isinstance(finding, dict) and finding.get("status") in {"FAIL", "WARNING", "UNVERIFIABLE"}:
                lines.append(f"  - {finding.get('status')}: {finding.get('field', 'metric')}: {finding.get('finding', finding.get('description', finding.get('reason', 'Review persisted integrity detail.')))}")
        comparisons = (run.get("paired_comparisons") or {}).get("comparisons", [])
        if comparisons:
            lines.append("- Paired comparisons (baseline minus M1; only common non-missing trial pairs):")
            for comparison in comparisons:
                if not isinstance(comparison, dict):
                    continue
                ci = comparison.get("ci95_mean_difference")
                ci_text = f"[{_format_metric(ci[0])}, {_format_metric(ci[1])}]" if isinstance(ci, list) and len(ci) == 2 else "Not measured"
                p_adj = comparison.get("holm_adjusted_p_value")
                lines.append(
                    f"  - {comparison.get('baseline')} {comparison.get('metric')}: n={comparison.get('n_pairs', 0)}, "
                    f"mean difference={_format_metric(comparison.get('mean_difference_baseline_minus_reference'))}, "
                    f"95% CI={ci_text}, Holm p={_format_metric(p_adj)}, status={comparison.get('status', 'Not available')}"
                )
        lines.append("")
    if notes:
        lines.extend(["## Execution notes", "", *[f"- {note}" for note in notes], ""])
    lines.extend([
        "## Next steps",
        "",
        "1. Review every run's persisted protocol, validation findings, quality-control status, and paired comparisons in the authenticated Comparative Results view.",
        "2. Treat partial, failed, invalid, or warning runs according to their reported status; do not silently rerun uncertain submissions.",
        "3. Keep this validation dataset separate from any later policy calibration.",
        "",
    ])
    return "\n".join(lines)


def write_report(content: str, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = report_dir / f"privacyguard-validation-{stamp}.md"
    counter = 1
    while True:
        try:
            with candidate.open("x", encoding="utf-8", newline="\n") as output:
                output.write(content)
            return candidate
        except FileExistsError:
            candidate = report_dir / f"privacyguard-validation-{stamp}-{counter}.md"
            counter += 1


def _locked_summary() -> str:
    return (
        "PrivacyGuard locked validation campaign\n"
        "  Dataset: Synthetic Employees (5,000 rows), seed 20261126\n"
        "  Scenarios: difference, repeated, narrowing, overlapping\n"
        "  Baselines: M0, M1, M2, M3, M4, M5 (where applicable)\n"
        "  Trials: 20 matched per scenario; matched_hashed seed schedule\n"
        "  Trial seeds: " + ", ".join(str(seed) for seed in locked_trial_seeds()) + "\n"
        "  M5 locked policy: α=0.10, γ=0.05; epsilon min=0.1, max=0.5\n"
        "  Fixed epsilon=0.5; nominal budget=5.0 per trial\n"
        "  Synthetic-only; nominal accounting is uncertified.\n"
    )


def _validate_run(run: dict[str, Any], scenario: str) -> None:
    if run.get("status") != "completed":
        raise CampaignError(f"Run {run.get('id')} for {scenario} is {run.get('status', 'unknown')}.")
    config = run.get("configuration")
    if not isinstance(config, dict) or not _matching_locked_run(run, scenario):
        raise CampaignError(f"Persisted run {run.get('id')} does not match the locked protocol for {scenario}.")
    results = run.get("results")
    if not isinstance(results, list) or {item.get("baseline") for item in results if isinstance(item, dict)} != set(BASELINES):
        raise CampaignError(f"Run {run.get('id')} does not contain exactly the requested M0–M5 baselines.")
    protocol = config["protocol"]
    expected_seeds = protocol["trials"]["trial_seeds"]
    for result in results:
        metrics = result.get("metrics") if isinstance(result, dict) else None
        measurements = metrics.get("measurements") if isinstance(metrics, dict) else None
        if not isinstance(measurements, list) or len(measurements) != 20:
            raise CampaignError(f"Run {run.get('id')} baseline trial coverage is incomplete.")
        if [row.get("trial") for row in measurements if isinstance(row, dict)] != list(range(1, 21)):
            raise CampaignError(f"Run {run.get('id')} baseline trial identifiers are incomplete or unordered.")
        if [row.get("trial_seed") for row in measurements if isinstance(row, dict)] != expected_seeds:
            raise CampaignError(f"Run {run.get('id')} baseline does not use the locked matched trial seed schedule.")
    if protocol["trials"]["trial_seeds"] != config.get("trial_seed_schedule", {}).get("trial_seeds"):
        raise CampaignError(f"Run {run.get('id')} trial seed schedule is inconsistent.")


@dataclass
class CampaignRunner:
    api: HttpApi
    report_dir: Path
    sleep: Callable[[float], None] = time.sleep
    progress: Callable[[str], None] = print
    poll_interval: float = POLL_INTERVAL_SECONDS
    poll_timeout: float = POLL_TIMEOUT_SECONDS

    def _poll_run(self, run_id: int) -> dict[str, Any]:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            run = self.api.get_run(run_id)
            if run.get("status") != "running":
                return run
            self.progress(f"Run {run_id} is still running; checking persisted status again shortly.")
            if time.monotonic() >= deadline:
                raise CampaignError(f"Run {run_id} remains running; it was not resubmitted. Check its persisted status later.")
            self.sleep(self.poll_interval)

    def execute(self, *, confirm: str, confirmed_at: datetime | None = None) -> tuple[list[dict[str, Any]], str, Path]:
        if confirm != CONFIRMATION:
            raise CampaignError("Confirmation did not match exactly; no campaign was submitted.")
        initial_runs = self.api.list_runs()
        preexisting: dict[str, dict[str, Any]] = {}
        for scenario in SCENARIOS:
            matches = [run for run in initial_runs if _matching_locked_run(run, scenario)]
            if len(matches) > 1:
                raise CampaignError(f"Multiple existing runs match the locked {scenario} configuration; refusing duplicate submissions.")
            if matches:
                found = matches[0]
                if found.get("status") != "completed":
                    raise CampaignError(f"An existing {scenario} run {found.get('id')} is {found.get('status')}; refusing to submit a duplicate.")
                preexisting[scenario] = self.api.get_run(int(found["id"]))
                _validate_run(preexisting[scenario], scenario)
                preexisting[scenario]["comparative_results_visible"] = self.api.verify_benchmark_visibility(int(found["id"]))

        results: list[dict[str, Any]] = []
        notes: list[str] = []
        start = confirmed_at or datetime.now(timezone.utc)
        try:
            for scenario in SCENARIOS:
                if scenario in preexisting:
                    notes.append(f"Scenario {scenario}: reused existing matching persisted run {preexisting[scenario]['id']}; no duplicate submission.")
                    self.progress(f"Scenario {scenario}: using existing verified run {preexisting[scenario]['id']}.")
                    results.append(preexisting[scenario])
                    continue
                self.progress(f"Submitting locked scenario '{scenario}' (one request; automatic retry is disabled).")
                try:
                    submitted = self.api.request("POST", "/api/experiments/runs", payload=_campaign_payload(scenario))
                except CampaignError as exc:
                    # A timed-out synchronous POST may still be executing. Inspect
                    # the owner-scoped run list once; never retry the submission.
                    if "status may be uncertain" in str(exc):
                        candidates = [r for r in self.api.list_runs() if _matching_locked_run(r, scenario) and r.get("id") not in {x.get("id") for x in initial_runs}]
                        if len(candidates) == 1:
                            run = self._poll_run(int(candidates[0]["id"]))
                            _validate_run(run, scenario)
                            run["comparative_results_visible"] = self.api.verify_benchmark_visibility(int(run["id"]))
                            results.append(run)
                            notes.append(f"Scenario {scenario}: POST timed out, but persisted run {run['id']} was found and verified; it was not resubmitted.")
                            self.progress(f"Scenario {scenario}: persisted run {run['id']} was found and verified after the request timeout.")
                            continue
                    raise
                if not isinstance(submitted, dict) or not isinstance(submitted.get("id"), int):
                    raise CampaignError(f"The {scenario} submission returned no run ID; do not submit it again until status is checked.")
                run_id = int(submitted["id"])
                persisted = self._poll_run(run_id) if submitted.get("status") == "running" else self.api.get_run(run_id)
                _validate_run(persisted, scenario)
                persisted["comparative_results_visible"] = self.api.verify_benchmark_visibility(run_id)
                results.append(persisted)
                self.progress(f"Scenario {scenario}: persisted run {run_id} verified ({persisted.get('status')}).")
        except KeyboardInterrupt:
            notes.append("Interrupted by the local operator. Any submitted run IDs remain persisted; no deletion or resubmission was performed.")
            current = self.api.list_runs()
            known_ids = {item.get("id") for item in results}
            for run in current:
                if run.get("id") not in known_ids and run.get("id") not in {item.get("id") for item in initial_runs}:
                    for scenario in SCENARIOS:
                        if _matching_locked_run(run, scenario):
                            try:
                                results.append(self.api.get_run(int(run["id"])))
                            except CampaignError:
                                pass
                            break
            report_status = "interrupted; inspect persisted run statuses before continuing"
            path = write_report(build_report(results, status=report_status, notes=notes), self.report_dir)
            return results, report_status, path
        except CampaignError as exc:
            notes.append(f"Execution stopped safely: {exc}")
            try:
                current = self.api.list_runs()
                previous_ids = {item.get("id") for item in initial_runs}
                known_ids = {item.get("id") for item in results}
                for run in current:
                    if run.get("id") in previous_ids or run.get("id") in known_ids:
                        continue
                    for scenario in SCENARIOS:
                        if _matching_locked_run(run, scenario):
                            results.append(self.api.get_run(int(run["id"])))
                            break
            except CampaignError as status_error:
                notes.append(f"Could not confirm additional persisted status through the API: {status_error}")
            report_status = "partial or uncertain; do not resubmit until persisted status is reviewed"
            path = write_report(build_report(results, status=report_status, notes=notes), self.report_dir)
            raise CampaignError(f"{exc} A status report was saved to {path}; do not resubmit until the run status is reviewed.") from None
        status = "completed" if len(results) == len(SCENARIOS) and all(r.get("status") == "completed" for r in results) else "partial"
        path = write_report(build_report(results, status=status, notes=notes), self.report_dir)
        return results, status, path


def main() -> int:
    api_url = input(f"Backend API base URL [{DEFAULT_API_BASE_URL}]: ").strip() or DEFAULT_API_BASE_URL
    try:
        api = HttpApi(api_url)
        username = input("Researcher username: ").strip()
        if not username:
            raise CampaignError("A username is required.")
        password = getpass.getpass("Researcher password (input hidden): ")
        identity = api.authenticate(username, password)
        del password
        print(f"Authenticated as active Researcher account '{identity.get('username')}'. Effective experiments:run permission verified.")
        print("\n" + _locked_summary())
        confirmation = input(f"Type {CONFIRMATION} to proceed: ")
        runner = CampaignRunner(api, Path(__file__).resolve().parents[1] / "reports")
        runs, status, report_path = runner.execute(confirm=confirmation)
        print(f"Campaign status: {status}")
        print("Run IDs created or verified as existing: " + (", ".join(str(run.get("id")) for run in runs) if runs else "none confirmed"))
        print(f"Report saved: {report_path}")
        return 0 if status == "completed" else 2
    except CampaignError as exc:
        print(f"Campaign stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
