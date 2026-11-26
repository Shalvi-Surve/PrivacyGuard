from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from scripts.run_validation_campaign import (
    BASELINES,
    CONFIRMATION,
    CampaignError,
    CampaignRunner,
    HttpApi,
    LOCKED_PAYLOAD,
    SCENARIOS,
    build_report,
    locked_trial_seeds,
    write_report,
)


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_locked_seed_schedule_is_stable():
    assert locked_trial_seeds() == [
        1454974249, 343349929, 2857857935, 917643282, 3030494052,
        1844710238, 3912520240, 170160790, 2640246751, 784832993,
        143557794, 232832621, 2445831254, 47203277, 3588750260,
        2933628016, 3185823385, 2008729112, 663988879, 3002564589,
    ]


def protocol_for(scenario):
    seeds = [int.from_bytes(hashlib.sha256(f"20261126:{i}:trial".encode()).digest()[:4], "big") for i in range(20)]
    return {
        "version": "privacyguard-research-protocol-v2",
        "scenario_identifier": scenario,
        "trials": {"count": 20, "trial_seed_strategy": "matched_hashed", "trial_seeds": seeds},
        "dataset": {"row_count": 5000},
        "privacy_parameters": {"adaptive_risk_penalty": 0.10, "adaptive_cumulative_penalty": 0.05},
    }


def persisted_run(run_id, scenario):
    config = {"scenario": scenario, **LOCKED_PAYLOAD}
    config["protocol"] = protocol_for(scenario)
    config["protocol_version"] = "privacyguard-research-protocol-v2"
    config["trial_seed_schedule"] = {"trial_seeds": config["protocol"]["trials"]["trial_seeds"]}
    measurements = [
        {"trial": i, "trial_seed": config["protocol"]["trials"]["trial_seeds"][i - 1]}
        for i in range(1, 21)
    ]
    return {
        "id": run_id,
        "configuration": config,
        "status": "completed",
        "validation_status": "PASS",
        "validation_report": {"status": "PASS", "findings": []},
        "quality_control": {"status": "valid_completed", "inferentially_eligible": True},
        "paired_comparisons": {"comparisons": []},
        "results": [
            {"baseline": baseline, "metrics": {"measurements": measurements}}
            for baseline in BASELINES
        ],
    }


def test_authentication_verifies_identity_and_effective_permission():
    captured = []

    def opener(request, timeout):
        captured.append(request)
        if request.full_url.endswith("/api/auth/login"):
            return Response({"access_token": "secret-token", "token_type": "bearer"})
        if request.full_url.endswith("/api/auth/me"):
            return Response({"username": "researcher", "is_active": True, "roles": ["researcher"]})
        return Response({"items": [], "total": 0, "page": 1, "page_size": 1})

    api = HttpApi("http://127.0.0.1:8001", opener=opener)
    identity = api.authenticate("researcher", "not-logged")
    assert identity["username"] == "researcher"
    assert captured[2].get_header("Authorization") == "Bearer secret-token"
    assert "not-logged" not in repr(captured)


def test_failed_authentication_does_not_leak_server_body():
    def opener(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    api = HttpApi("http://127.0.0.1:8001", opener=opener)
    with pytest.raises(CampaignError, match="HTTP 401") as error:
        api.authenticate("researcher", "never-print-this")
    assert "never-print-this" not in str(error.value)


def test_missing_permission_stops_before_submission():
    def opener(request, timeout):
        if request.full_url.endswith("/api/auth/login"):
            return Response({"access_token": "token"})
        if request.full_url.endswith("/api/auth/me"):
            return Response({"username": "researcher", "is_active": True, "roles": ["researcher"]})
        raise HTTPError(request.full_url, 403, "Permission denied", {}, None)

    with pytest.raises(CampaignError, match="lacks experiments:run"):
        HttpApi("http://127.0.0.1:8001", opener=opener).authenticate("researcher", "secret")


def test_campaign_confirmation_is_exact_and_precedes_api_calls(tmp_path):
    class NoCalls:
        def list_runs(self):
            raise AssertionError("Must not call API before exact confirmation")

    runner = CampaignRunner(NoCalls(), tmp_path)
    with pytest.raises(CampaignError, match="no campaign was submitted"):
        runner.execute(confirm=CONFIRMATION.lower())


def test_campaign_submits_each_locked_scenario_and_verifies_persisted_runs(tmp_path):
    class FakeApi:
        def __init__(self):
            self.runs = {}
            self.posts = []

        def list_runs(self):
            return [{"id": run_id, "configuration": run["configuration"], "status": run["status"]} for run_id, run in self.runs.items()]

        def request(self, method, path, *, payload=None):
            assert method == "POST" and path == "/api/experiments/runs"
            assert payload == {"scenario": payload["scenario"], **LOCKED_PAYLOAD}
            run_id = len(self.runs) + 1
            scenario = payload["scenario"]
            run = persisted_run(run_id, scenario)
            self.runs[run_id] = run
            self.posts.append(payload)
            return {"id": run_id, "status": "completed"}

        def get_run(self, run_id):
            return self.runs[run_id]

        def verify_benchmark_visibility(self, run_id):
            return run_id in self.runs

    api = FakeApi()
    runs, status, report_path = CampaignRunner(api, tmp_path).execute(confirm=CONFIRMATION)
    assert status == "completed"
    assert [run["configuration"]["scenario"] for run in runs] == list(SCENARIOS)
    assert [payload["scenario"] for payload in api.posts] == list(SCENARIOS)
    assert report_path.exists()
    assert "secret-token" not in report_path.read_text()


def test_existing_matching_runs_prevent_duplicate_posts(tmp_path):
    class ExistingApi:
        def __init__(self):
            self.runs = {index + 41: persisted_run(index + 41, scenario) for index, scenario in enumerate(SCENARIOS)}
            self.posts = 0

        def list_runs(self):
            return [{"id": run_id, "configuration": run["configuration"], "status": "completed"} for run_id, run in self.runs.items()]

        def get_run(self, run_id):
            return self.runs[run_id]

        def verify_benchmark_visibility(self, run_id):
            return run_id in self.runs

        def request(self, *args, **kwargs):
            self.posts += 1
            return None

    api = ExistingApi()
    runs, status, _ = CampaignRunner(api, tmp_path).execute(confirm=CONFIRMATION)
    assert status == "completed"
    assert len(runs) == 4
    assert api.posts == 0


def test_timeout_is_not_retried_and_status_is_checked(tmp_path):
    class TimeoutApi:
        def __init__(self):
            self.posts = 0
            self.run = persisted_run(55, "difference")

        def list_runs(self):
            return []

        def request(self, *args, **kwargs):
            self.posts += 1
            raise CampaignError("request timed out; execution status may be uncertain.")

    # No newly persisted run is visible, so the runner propagates uncertainty.
    api = TimeoutApi()
    with pytest.raises(CampaignError, match="status may be uncertain"):
        CampaignRunner(api, tmp_path).execute(confirm=CONFIRMATION)
    assert api.posts == 1


def test_report_contains_measurements_and_never_credentials_or_tokens(tmp_path):
    run = persisted_run(9, "difference")
    run["results"][0]["metrics"].update({"attack_success_count": 1, "attack_attempt_count": 20, "attack_success_rate": 0.05})
    report = build_report([run], status="completed", notes=["safe note"])
    assert "1/20" in report
    assert "5%" in report
    assert "secret-token" not in report and "password" not in report
    first = write_report(report, tmp_path)
    second = write_report(report, tmp_path)
    assert first != second
    assert Path(first).read_text(encoding="utf-8") == report


def test_run_response_parsing_rejects_missing_id():
    def opener(request, timeout):
        return Response({"status": "completed"})

    api = HttpApi("http://127.0.0.1:8001", opener=opener)
    result = api.request("POST", "/api/experiments/runs", payload={"scenario": "difference"})
    assert result.get("id") is None
