from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from io import StringIO
from time import perf_counter_ns

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import ExperimentResult, ExperimentRun, User
from app.experiments.engine import (
    ATTACK_DEFINITION_VERSION, BASELINES, BASELINE_NAMES, BASELINE_DEFINITION_VERSION,
    EXPERIMENT_ENGINE_VERSION, LEGACY_BASELINE_MAP, MECHANISM_VERSION,
    METRIC_DEFINITION_VERSION, SCENARIOS, WORKLOAD_DEFINITION_VERSION, run_comparison,
)
from app.experiments.validation import validate_run
from app.experiments.protocol import PROTOCOL_VERSION, make_protocol
from app.experiments.quality import classify_quality
from app.experiments.statistics import paired_comparisons
from app.experiments.statistics import wilson_score_interval
from app.rbac.permissions import require_permission

router = APIRouter(tags=["research experiments"])


class ExperimentRunRequest(BaseModel):
    scenario: str = "difference"
    dataset_size: int = 5_000
    baselines: list[str] = Field(default_factory=lambda: list(BASELINES), min_length=1, max_length=6)
    trials: int = Field(default=20, ge=1, le=30)
    repetitions: int = Field(default=5, ge=2, le=20)
    repeat_query_mode: str = "identical"
    seed: int = Field(default=2026, ge=0, le=2**32 - 1)
    epsilon: float = Field(default=0.5, gt=0, le=1)
    budget_epsilon: float = Field(default=10.0, gt=0, le=1000)
    adaptive_epsilon_min: float | None = Field(default=None, gt=0, le=1)
    adaptive_risk_penalty: float = Field(default=0.1, ge=0, le=1)
    adaptive_cumulative_penalty: float = Field(default=0.05, ge=0, le=1)
    attack_relative_success_tolerance: float = Field(default=0.05, ge=0, le=1)
    narrowing_absolute_success_tolerance: float = Field(default=1.0, ge=0, le=100)
    trial_seed_strategy: str = "matched_sequential"
    history_depth: int = 0
    ablation_mode: str = "full"

    @model_validator(mode="after")
    def valid_adaptive_policy_bounds(self):
        if self.adaptive_epsilon_min is None:
            self.adaptive_epsilon_min = min(0.1, self.epsilon)
        elif self.adaptive_epsilon_min > self.epsilon:
            raise ValueError("adaptive_epsilon_min must not exceed fixed epsilon")
        return self

    @field_validator("scenario")
    @classmethod
    def valid_scenario(cls, value: str) -> str:
        if value not in SCENARIOS:
            raise ValueError("scenario must be difference, repeated, narrowing, or overlapping")
        return value

    @field_validator("dataset_size")
    @classmethod
    def valid_dataset_size(cls, value: int) -> int:
        if value not in {5_000, 25_000, 100_000}:
            raise ValueError("dataset_size must be 5000, 25000, or 100000")
        return value

    @field_validator("repeat_query_mode")
    @classmethod
    def valid_repeat_query_mode(cls, value: str) -> str:
        if value not in {"identical", "equivalent_variants"}:
            raise ValueError("repeat_query_mode must be identical or equivalent_variants")
        return value

    @field_validator("baselines")
    @classmethod
    def valid_baselines(cls, value: list[str]) -> list[str]:
        normalized = [LEGACY_BASELINE_MAP.get(item, item) for item in value]
        if len(set(normalized)) != len(normalized) or any(item not in BASELINES for item in normalized):
            raise ValueError("baselines must be unique values from M0 through M5")
        return normalized

    @field_validator("trial_seed_strategy")
    @classmethod
    def valid_seed_strategy(cls, value: str) -> str:
        if value not in {"matched_sequential", "matched_hashed"}:
            raise ValueError("trial_seed_strategy must be matched_sequential or matched_hashed")
        return value

    @field_validator("attack_relative_success_tolerance", "narrowing_absolute_success_tolerance")
    @classmethod
    def finite_success_tolerance(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("success tolerances must be finite")
        return value

    @field_validator("history_depth")
    @classmethod
    def valid_history_depth(cls, value: int) -> int:
        if value not in {0, 5, 10, 25, 50}:
            raise ValueError("history_depth must be 0, 5, 10, 25, or 50")
        return value

    @field_validator("ablation_mode")
    @classmethod
    def valid_ablation(cls, value: str) -> str:
        if value not in {"full", "no_history_overlap", "no_repetition", "no_predicate_narrowing", "no_query_type"}:
            raise ValueError("unsupported experimental ablation mode")
        return value


def _serialize_run(db: Session, run: ExperimentRun) -> dict:
    results = db.scalars(select(ExperimentResult).where(ExperimentResult.run_id == run.id).order_by(ExperimentResult.id)).all()
    stored_results = [{"id": result.id, "baseline": result.baseline, "baseline_name": result.metrics.get("baseline_name", BASELINE_NAMES.get(result.baseline, result.baseline)), "metrics": dict(result.metrics)} for result in results]
    # Validate the immutable stored values first, so legacy Wald intervals remain
    # auditable. The response copy derives Wilson bounds from persisted counts.
    validation_report = validate_run(run.configuration or {}, stored_results, experiment_id=run.id)
    quality_control = classify_quality(run.status, run.configuration or {}, stored_results, validation_report)
    serialized_results = []
    for result in stored_results:
        metrics = dict(result["metrics"])
        successes = metrics.get("attack_success_count")
        attempts = metrics.get("attack_attempt_count")
        try:
            metrics["attack_success_ci95"] = wilson_score_interval(successes, attempts)
        except ValueError:
            metrics["attack_success_ci95"] = [None, None]
        serialized_results.append({**result, "metrics": metrics})
    for result in serialized_results:
        result["validation_report"] = validation_report["baseline_reports"].get(str(result["baseline"]))
    return {
        "id": run.id,
        "name": run.name,
        "configuration": run.configuration,
        "seed": run.seed,
        "status": run.status,
        "created_at": run.created_at,
        "results": serialized_results,
        "validation_report": validation_report,
        "validation_status": validation_report["status"],
        "quality_control": quality_control,
        "paired_comparisons": paired_comparisons(serialized_results, run.configuration or {}, reference_baseline=str((run.configuration or {}).get("paired_reference_baseline", "M1")), validation_status=validation_report["status"]),
    }


def _owned_run(db: Session, user: User, run_id: int) -> ExperimentRun:
    run = db.scalar(select(ExperimentRun).where(ExperimentRun.id == run_id, ExperimentRun.owner_user_id == user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Experiment run was not found.")
    return run


def _execute_run(payload: ExperimentRunRequest, user: User, db: Session) -> dict:
    config = payload.model_dump()
    config["experiment_engine_version"] = EXPERIMENT_ENGINE_VERSION
    config["baseline_definition_version"] = BASELINE_DEFINITION_VERSION
    config["metric_definition_version"] = METRIC_DEFINITION_VERSION
    config["workload_definition_version"] = WORKLOAD_DEFINITION_VERSION
    config["attack_definition_version"] = ATTACK_DEFINITION_VERSION
    config["mechanism_version"] = MECHANISM_VERSION
    config["protocol"] = make_protocol(config)
    config["protocol_version"] = PROTOCOL_VERSION
    config["trial_seed_schedule"] = {
        "strategy": payload.trial_seed_strategy,
        "seed": payload.seed,
        "trial_seeds": config["protocol"]["trials"]["trial_seeds"],
        "derivation": config["protocol"]["trials"]["noise_seed_derivation"],
        "shared_across_baselines": True,
    }
    run = ExperimentRun(
        name=f"{payload.scenario.replace('_', ' ').title()} · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        configuration=config,
        seed=payload.seed,
        owner_user_id=user.id,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    try:
        engine_started_ns = perf_counter_ns()
        metrics = run_comparison(config)
        engine_ms = (perf_counter_ns() - engine_started_ns) / 1_000_000
        report_rows = [{"baseline": str(item["baseline"]), "metrics": item} for item in metrics]
        integrity_report = validate_run(config, report_rows, experiment_id=run_id)
        quality_control = classify_quality("completed", config, report_rows, integrity_report)
        config["validation_status"] = integrity_report["status"]
        config["validation_summary"] = integrity_report["summary"]
        # Persist findings with new runs; this does not rewrite historical rows
        # or store raw targets/aggregate values.
        config["validation_findings"] = integrity_report["findings"]
        config["quality_control"] = quality_control
        run.configuration = config
        result_rows = []
        for item in metrics:
            item["campaign_engine_runtime_ms"] = engine_ms
            row = ExperimentResult(run_id=run.id, baseline=str(item["baseline"]), metrics=item)
            result_rows.append(row)
            db.add(row)
        run.status = "completed"
        flush_started_ns = perf_counter_ns()
        db.flush()
        persistence_flush_ms = (perf_counter_ns() - flush_started_ns) / 1_000_000
        for row in result_rows:
            row.metrics = {**row.metrics, "persistence_ms": persistence_flush_ms, "persistence_measurement_scope": "SQLAlchemy flush duration; final transaction commit excluded"}
        db.commit()
        db.refresh(run)
    except Exception as exc:
        db.rollback()
        failed = db.get(ExperimentRun, run_id)
        if failed is not None:
            failed.status = "failed"
            db.commit()
        raise HTTPException(status_code=500, detail="The synthetic experiment failed. No result metrics were saved.") from exc
    return _serialize_run(db, run)


@router.post("/api/experiments/runs")
def create_experiment_run(
    payload: ExperimentRunRequest,
    user: User = Depends(require_permission("experiments:run")),
    db: Session = Depends(get_db),
) -> dict:
    return _execute_run(payload, user, db)


@router.post("/api/attacks/simulate")
def simulate_attack(
    payload: ExperimentRunRequest,
    user: User = Depends(require_permission("experiments:run")),
    db: Session = Depends(get_db),
) -> dict:
    return _execute_run(payload, user, db)


@router.get("/api/experiments/runs")
def list_experiment_runs(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_permission("experiments:run")), db: Session = Depends(get_db),
) -> dict:
    base = select(ExperimentRun).where(ExperimentRun.owner_user_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(ExperimentRun.created_at.desc(), ExperimentRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "name": row.name, "configuration": row.configuration, "seed": row.seed, "status": row.status, "created_at": row.created_at} for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/api/experiments/benchmark-runs")
def list_benchmark_run_summaries(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    scenario: str | None = None, dataset_size: int | None = Query(default=None, ge=1),
    baseline: str | None = None, trials: int | None = Query(default=None, ge=1),
    run_id: int | None = Query(default=None, ge=1), date_from: datetime | None = None,
    date_to: datetime | None = None,
    user: User = Depends(require_permission("experiments:run")), db: Session = Depends(get_db),
) -> dict:
    """Return lightweight, owner-scoped benchmark run metadata for selectors.

    This deliberately does not load result JSON or reconstruct integrity and
    paired-statistics reports. Call the existing run-detail route for the
    selected run when those measurements are needed.
    """
    stmt = select(ExperimentRun).where(ExperimentRun.owner_user_id == user.id, ExperimentRun.status == "completed")
    if run_id is not None:
        stmt = stmt.where(ExperimentRun.id == run_id)
    if date_from is not None:
        stmt = stmt.where(ExperimentRun.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(ExperimentRun.created_at <= date_to)
    if scenario:
        stmt = stmt.where(ExperimentRun.configuration["scenario"].as_string() == scenario)
    if dataset_size is not None:
        stmt = stmt.where(ExperimentRun.configuration["dataset_size"].as_integer() == dataset_size)
    if trials is not None:
        stmt = stmt.where(ExperimentRun.configuration["trials"].as_integer() == trials)
    if baseline:
        stmt = stmt.join(ExperimentResult, ExperimentResult.run_id == ExperimentRun.id).where(ExperimentResult.baseline == baseline).distinct()
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ExperimentRun.created_at.desc(), ExperimentRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [{"id": row.id, "name": row.name, "configuration": row.configuration, "seed": row.seed,
              "status": row.status, "created_at": row.created_at} for row in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/api/experiments/benchmark-results")
def list_benchmark_results(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    scenario: str | None = None, dataset_size: int | None = Query(default=None, ge=1),
    baseline: str | None = None, trials: int | None = Query(default=None, ge=1),
    run_id: int | None = Query(default=None, ge=1), date_from: datetime | None = None,
    date_to: datetime | None = None,
    user: User = Depends(require_permission("experiments:run")), db: Session = Depends(get_db),
) -> dict:
    """Return completed, owner-scoped persisted measurements for benchmarking."""
    stmt = select(ExperimentRun).where(ExperimentRun.owner_user_id == user.id, ExperimentRun.status == "completed")
    if run_id is not None:
        stmt = stmt.where(ExperimentRun.id == run_id)
    if date_from is not None:
        stmt = stmt.where(ExperimentRun.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(ExperimentRun.created_at <= date_to)
    if scenario:
        stmt = stmt.where(ExperimentRun.configuration["scenario"].as_string() == scenario)
    if dataset_size is not None:
        stmt = stmt.where(ExperimentRun.configuration["dataset_size"].as_integer() == dataset_size)
    if trials is not None:
        stmt = stmt.where(ExperimentRun.configuration["trials"].as_integer() == trials)
    if baseline:
        stmt = stmt.join(ExperimentResult, ExperimentResult.run_id == ExperimentRun.id).where(ExperimentResult.baseline == baseline).distinct()
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ExperimentRun.created_at.desc(), ExperimentRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [_serialize_run(db, row) for row in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/api/experiments/runs/{run_id}")
def get_experiment_run(
    run_id: int,
    user: User = Depends(require_permission("experiments:run")), db: Session = Depends(get_db),
) -> dict:
    return _serialize_run(db, _owned_run(db, user, run_id))


@router.get("/api/experiments/runs/{run_id}/paired-comparisons")
def get_paired_experiment_comparisons(
    run_id: int, reference_baseline: str = Query(default="M1", pattern="^(M0|M1|M2|M3|M4|M5)$"),
    user: User = Depends(require_permission("experiments:run")), db: Session = Depends(get_db),
) -> dict:
    run = _owned_run(db, user, run_id)
    results = db.scalars(select(ExperimentResult).where(ExperimentResult.run_id == run.id).order_by(ExperimentResult.id)).all()
    rows = [{"baseline": row.baseline, "metrics": row.metrics} for row in results]
    report = paired_comparisons(rows, run.configuration or {}, reference_baseline, validate_run(run.configuration or {}, rows, experiment_id=run.id)["status"])
    return {"experiment_id": run.id, **report}


@router.get("/api/experiments/runs/{run_id}/export.csv")
def export_experiment_csv(
    run_id: int,
    user: User = Depends(require_permission("experiments:run")), db: Session = Depends(get_db),
) -> Response:
    run = _owned_run(db, user, run_id)
    results = db.scalars(select(ExperimentResult).where(ExperimentResult.run_id == run.id).order_by(ExperimentResult.id)).all()
    output = StringIO(newline="")
    fields = ["run_id", "scenario", "dataset_size", "seed", "trial_seed_strategy", "protocol_version", "protocol_json", "experiment_engine_version", "metric_definition_version", "baseline_definition_version", "workload_definition_version", "attack_definition_version", "mechanism_version", "baseline", "baseline_name", "row_type", "trial", "trial_seed", "request_index", "query_key", "request_status", "observation_id", "attack_source_id", "release_id", "noise_sample_id", "attack_estimator_version", "request_count", "independent_releases", "exact_cache_hits", "unique_attack_observation_count", "unique_noise_sample_count", "answerable_requests", "legitimate_requests", "legitimate_query_answerability_rate", "budget_rejected_requests", "selected_epsilon", "epsilon_charged", "cumulative_epsilon_spent", "nominal_epsilon_spent", "budget_utilization", "attack_absolute_error", "attack_relative_error", "attack_success", "attack_success_count", "attack_attempt_count", "attack_observation_count", "attack_independent_observation_count", "attack_success_threshold", "attack_evidence_json", "small_group_exposure", "aggregate_absolute_error", "aggregate_relative_error", "aggregate_mae", "aggregate_rmse", "risk_score", "history_overlap", "repetition_signal", "history_lookup_ms", "risk_policy_ms", "release_execution_ms", "query_latency_ms_mean", "middleware_overhead_ms_mean", "latency_ms", "rejected_requests", "elapsed_ms", "metric_states"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for result in results:
        for measurement in result.metrics.get("measurements", []):
            writer.writerow({
                "row_type": "trial",
                "run_id": run.id,
                "scenario": run.configuration.get("scenario"),
                "dataset_size": run.configuration.get("dataset_size"),
                "seed": run.seed,
                "trial_seed_strategy": run.configuration.get("trial_seed_strategy"),
                "protocol_version": run.configuration.get("protocol_version"),
                "protocol_json": json.dumps(run.configuration.get("protocol"), separators=(",", ":")),
                "experiment_engine_version": run.configuration.get("experiment_engine_version"),
                "metric_definition_version": run.configuration.get("metric_definition_version"),
                "baseline_definition_version": run.configuration.get("baseline_definition_version"),
                "workload_definition_version": run.configuration.get("workload_definition_version"),
                "attack_definition_version": run.configuration.get("attack_definition_version"),
                "mechanism_version": run.configuration.get("mechanism_version"),
                "trial_seed": measurement.get("trial_seed"),
                "attack_evidence_json": json.dumps(measurement.get("attack_evidence"), separators=(",", ":")),
                "metric_states": json.dumps(result.metrics.get("metric_states", {}), separators=(",", ":")),
                "baseline": result.baseline,
                "baseline_name": result.metrics.get("baseline_name", BASELINE_NAMES.get(result.baseline, result.baseline)),
                **measurement,
            })
        for measurement in result.metrics.get("request_measurements", []):
            writer.writerow({
                "row_type": "request",
                "run_id": run.id,
                "scenario": run.configuration.get("scenario"),
                "dataset_size": run.configuration.get("dataset_size"),
                "seed": run.seed,
                "trial_seed_strategy": run.configuration.get("trial_seed_strategy"),
                "protocol_version": run.configuration.get("protocol_version"),
                "protocol_json": json.dumps(run.configuration.get("protocol"), separators=(",", ":")),
                "experiment_engine_version": run.configuration.get("experiment_engine_version"),
                "metric_definition_version": run.configuration.get("metric_definition_version"),
                "baseline_definition_version": run.configuration.get("baseline_definition_version"),
                "workload_definition_version": run.configuration.get("workload_definition_version"),
                "attack_definition_version": run.configuration.get("attack_definition_version"),
                "mechanism_version": run.configuration.get("mechanism_version"),
                "metric_states": json.dumps(result.metrics.get("metric_states", {}), separators=(",", ":")),
                "baseline": result.baseline,
                "baseline_name": result.metrics.get("baseline_name", BASELINE_NAMES.get(result.baseline, result.baseline)),
                **measurement,
            })
    filename = f"privacyguard-experiment-{run.id}.csv"
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
