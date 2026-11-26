from time import perf_counter

from datetime import datetime
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.budget.accountant import ACCOUNTING_STATUS, FORMAL_GUARANTEE_STATUS, BudgetRejected, reserve_dataset_release, validated_budget_values
from app.database.connection import get_db
from app.database.models import AuditLog, Dataset, DatasetGrant, DatasetMetadata, Permission, PrivacyBudget, ProtectedRelease, QueryAnalysisEvent, QueryHistory, RolePermission, User, UserRole
from app.privacy.laplace import apply_laplace
from app.privacy.history import query_history_signals
from app.privacy.policy import DEFAULT_POLICY, UnaffordableAllocation, allocate_epsilon_decision, assess_risk, require_affordable_allocation
from app.query.analysis import QueryRejected, analyze_query, protected_release_key, protected_release_lookup_key
from app.query.execution import ADJACENCY_MODEL, PROTECTED_RELEASE_POLICY_VERSION, execute_internal_aggregate, sensitivity_for
from app.rbac.permissions import require_permission

router = APIRouter(prefix="/api/queries", tags=["queries"])
APPROVED_TABLES = {"employees"}
APPROVED_COLUMNS = {"employee_id", "department", "designation", "age", "gender", "salary", "performance_score", "location"}


class AnalyzeRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=4000)
    dataset_id: int | None = Field(default=None, gt=0)


class AnalyzeResponse(BaseModel):
    analysis_id: int
    canonical_sql: str
    fingerprint: str
    query_type: str
    table: str
    aggregate_column: str | None
    referenced_columns: list[str]


class ProtectedQueryRequest(BaseModel):
    dataset_id: int = Field(gt=0)
    sql: str = Field(min_length=1, max_length=4000)


class ProtectedQueryResponse(BaseModel):
    query_id: int
    dataset_id: int
    dataset_name: str
    query_type: str
    protected_result: float
    epsilon: float
    epsilon_charged: float
    sensitivity: float
    noise_scale: float
    risk_score: float
    risk_level: str
    risk_components: dict[str, float]
    privacy_spent: float
    remaining_budget: float
    budget_state: str
    query_fingerprint: str
    cache_hit: bool
    processing_ms: float
    decision: str
    explanation: str
    adjacency_model: str
    policy_version: str
    mechanism: str
    clipping_bounds: dict[str, float] | None
    dataset_version: int
    accounting_status: str
    privacy_guarantee_status: str
    allocation_decision: dict[str, object]


class QueryHistoryResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, user: User = Depends(require_permission("queries:submit")), db: Session = Depends(get_db)) -> AnalyzeResponse:
    """Validate restricted SQL and return structural analysis; it does not execute SQL."""
    if payload.dataset_id is not None:
        _allowed_dataset(db, user=user, dataset_id=payload.dataset_id, permission_key="queries:submit")
    try:
        result = analyze_query(payload.sql, allowed_tables=APPROVED_TABLES, allowed_columns=APPROVED_COLUMNS)
    except QueryRejected as exc:
        event = QueryAnalysisEvent(user_id=user.id, dataset_id=payload.dataset_id, fingerprint=None, query_type="unknown", decision="rejected")
        db.add(event)
        _write_audit(db, user_id=user.id, event_type="query_analysis_rejected", status_value="rejected", metadata={"dataset_id": payload.dataset_id, "reason": "query_validation_failed"})
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    event = QueryAnalysisEvent(user_id=user.id, dataset_id=payload.dataset_id, fingerprint=result.fingerprint, query_type=result.query_type, attributes_accessed=list(result.columns), decision="analysis_only")
    db.add(event)
    db.flush()
    _write_audit(db, user_id=user.id, event_type="query_analyzed", status_value="success", metadata={"analysis_id": event.id, "dataset_id": payload.dataset_id, "fingerprint": result.fingerprint})
    db.commit()
    return AnalyzeResponse(
        analysis_id=event.id,
        canonical_sql=result.canonical_sql,
        fingerprint=result.fingerprint,
        query_type=result.query_type,
        table=result.table,
        aggregate_column=result.aggregate_column,
        referenced_columns=list(result.columns),
    )


def _risk_level(score: float) -> str:
    return "high" if score >= 0.67 else "medium" if score >= 0.34 else "low"


def _write_audit(db: Session, *, user_id: int, event_type: str, status_value: str, metadata: dict) -> None:
    db.add(AuditLog(user_id=user_id, event_type=event_type, status=status_value, safe_metadata=metadata))


def _allowed_dataset(db: Session, *, user: User, dataset_id: int, permission_key: str | None = None) -> tuple[Dataset, DatasetMetadata]:
    role_query = select(UserRole.role_id).join(DatasetGrant, DatasetGrant.role_id == UserRole.role_id).where(UserRole.user_id == user.id, DatasetGrant.dataset_id == dataset_id)
    if permission_key:
        role_query = role_query.join(RolePermission, RolePermission.role_id == UserRole.role_id).join(Permission, Permission.id == RolePermission.permission_id).where(Permission.key == permission_key)
    dataset = db.scalar(
        select(Dataset)
        .where(Dataset.id == dataset_id, Dataset.is_active.is_(True), role_query.exists())
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset is unavailable or not assigned to your role.")
    metadata = db.get(DatasetMetadata, dataset.id)
    if metadata is None:
        raise HTTPException(status_code=409, detail="Dataset metadata is incomplete.")
    return dataset, metadata


def _budget_snapshot(db: Session, dataset_id: int) -> tuple[PrivacyBudget, float, str]:
    budget = db.scalar(select(PrivacyBudget).where(
        PrivacyBudget.dataset_id == dataset_id,
        PrivacyBudget.scope == "dataset",
        PrivacyBudget.owner_id.is_(None),
    ))
    if budget is None:
        raise HTTPException(status_code=409, detail="No shared privacy budget is configured for this dataset.")
    try:
        remaining, fraction = validated_budget_values(budget.initial_epsilon, budget.consumed_epsilon)
    except ValueError:
        raise HTTPException(status_code=409, detail="Shared privacy accounting metadata is inconsistent; no release was attempted.")
    state = "EXHAUSTED" if remaining <= 1e-9 else "CRITICAL" if fraction >= .9 else "WARNING" if fraction >= .7 else "NORMAL"
    return budget, remaining, state


def _response_from_release(
    *, query_id: int, dataset: Dataset, release: ProtectedRelease, budget: PrivacyBudget,
    remaining: float, budget_state: str, cache_hit: bool, processing_ms: float,
    risk_components: dict[str, float] | None = None,
    allocation_decision: dict[str, object] | None = None,
) -> ProtectedQueryResponse:
    score = release.risk_score
    return ProtectedQueryResponse(
        query_id=query_id,
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        query_type=release.query_type,
        protected_result=release.protected_value,
        epsilon=release.epsilon,
        epsilon_charged=0.0 if cache_hit else release.epsilon,
        sensitivity=release.sensitivity,
        noise_scale=release.noise_scale,
        risk_score=score,
        risk_level=_risk_level(score),
        risk_components=risk_components or {},
        privacy_spent=budget.consumed_epsilon,
        remaining_budget=remaining,
        budget_state=budget_state,
        query_fingerprint=release.fingerprint,
        cache_hit=cache_hit,
        processing_ms=round(processing_ms, 3),
        decision="CACHED" if cache_hit else "RELEASED",
        explanation=("The request reused an identical stored release configuration and output; this request charged 0 nominal epsilon." if cache_hit else "The approved aggregate was computed internally, bounded where required, and noise was applied before returning the protected result. The recorded epsilon is nominal; a formal guarantee for this finite-precision sampler is not established."),
        adjacency_model=release.adjacency_model or ADJACENCY_MODEL,
        policy_version=release.policy_version or PROTECTED_RELEASE_POLICY_VERSION,
        mechanism=release.mechanism or "Laplace",
        clipping_bounds=release.clipping_bounds or None,
        dataset_version=release.dataset_version or 1,
        accounting_status=ACCOUNTING_STATUS,
        privacy_guarantee_status=FORMAL_GUARANTEE_STATUS,
        allocation_decision=allocation_decision or {},
    )


@router.post("/execute", response_model=ProtectedQueryResponse)
def execute_protected_query(
    payload: ProtectedQueryRequest,
    user: User = Depends(require_permission("queries:execute_protected")),
    db: Session = Depends(get_db),
) -> ProtectedQueryResponse:
    started = perf_counter()
    dataset, dataset_metadata = _allowed_dataset(db, user=user, dataset_id=payload.dataset_id, permission_key="queries:execute_protected")
    try:
        analysis = analyze_query(payload.sql, allowed_tables=APPROVED_TABLES, allowed_columns=APPROVED_COLUMNS)
        sensitivity, _, lower, upper = sensitivity_for(analysis)
    except QueryRejected as exc:
        db.add(QueryAnalysisEvent(user_id=user.id, dataset_id=dataset.id, fingerprint=None, query_type="unknown", decision="rejected"))
        _write_audit(db, user_id=user.id, event_type="query_rejected", status_value="rejected", metadata={"reason": "query_validation_failed"})
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if dataset_metadata.table_name != analysis.table:
        raise HTTPException(status_code=422, detail="Query table does not match the selected dataset.")
    authorization_scope = db.scalars(
        select(UserRole.role_id)
        .join(DatasetGrant, DatasetGrant.role_id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == user.id, DatasetGrant.dataset_id == dataset.id, Permission.key == "queries:execute_protected")
    ).all()
    authorization_scope = sorted(set(authorization_scope))
    scope_hash = hashlib.sha256(json.dumps(authorization_scope, separators=(",", ":")).encode()).hexdigest()
    clipping_bounds = {"lower": lower, "upper": upper} if lower is not None and upper is not None else None
    mechanism = "Laplace"
    budget, remaining, budget_state = _budget_snapshot(db, dataset.id)

    history_signals = query_history_signals(db, dataset_id=dataset.id, analysis=analysis)
    sensitivity_score = min(sensitivity / 300_000.0, 1.0)
    sensitive_columns = {"salary", "performance_score", "gender", "age"}
    data_sensitivity = 0.75 if sensitive_columns.intersection(analysis.columns) else 0.35
    query_type_risk = 0.20 if analysis.query_type == "count" else 0.80
    assessment = assess_risk(
        query_sensitivity=sensitivity_score,
        data_sensitivity=data_sensitivity,
        history=history_signals.overlap,
        narrowness=history_signals.refinement,
        query_type=query_type_risk,
        weights=DEFAULT_POLICY.weights,
    )
    cumulative_fraction = validated_budget_values(budget.initial_epsilon, budget.consumed_epsilon)[1]
    allocation = allocate_epsilon_decision(
        assessment=assessment,
        cumulative_fraction=cumulative_fraction,
        remaining_epsilon=remaining,
        config=DEFAULT_POLICY,
    )

    epsilon = allocation.nominal_epsilon
    allocation_metadata = allocation.audit_metadata(components=assessment, config=DEFAULT_POLICY)
    lookup_key = protected_release_lookup_key(
        analysis=analysis, dataset_id=dataset.id, dataset_version=dataset_metadata.version,
        authorization_scope=authorization_scope, policy_version=PROTECTED_RELEASE_POLICY_VERSION,
        mechanism=mechanism, sensitivity=sensitivity, clipping_bounds=clipping_bounds,
        adjacency_model=ADJACENCY_MODEL, epsilon=epsilon,
    )

    cached = db.scalar(select(ProtectedRelease).where(
        ProtectedRelease.dataset_id == dataset.id,
        ProtectedRelease.cache_lookup_key == lookup_key,
    ))
    if cached is not None:
        expected_configuration = (dataset_metadata.version, PROTECTED_RELEASE_POLICY_VERSION, mechanism, ADJACENCY_MODEL, sensitivity, clipping_bounds, scope_hash, epsilon)
        stored_configuration = (cached.dataset_version, cached.policy_version, cached.mechanism, cached.adjacency_model, cached.sensitivity, cached.clipping_bounds or None, cached.authorization_scope_hash, cached.epsilon)
        if stored_configuration != expected_configuration:
            raise HTTPException(status_code=503, detail="Stored release configuration does not match the current policy. Please contact the administrator.")
        history = QueryHistory(
            user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint,
            query_type=analysis.query_type, tables_accessed=[analysis.table],
            attributes_accessed=list(analysis.columns), risk_score=cached.risk_score,
            epsilon=0.0, decision="cached",
        )
        db.add(history)
        db.flush()
        _write_audit(db, user_id=user.id, event_type="protected_query_cached", status_value="success", metadata={"query_id": history.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, **allocation_metadata})
        db.commit()
        db.refresh(history)
        budget, remaining, budget_state = _budget_snapshot(db, dataset.id)
        return _response_from_release(query_id=history.id, dataset=dataset, release=cached, budget=budget, remaining=remaining, budget_state=budget_state, cache_hit=True, processing_ms=(perf_counter() - started) * 1000, risk_components={"query_sensitivity": assessment.query_sensitivity, "data_sensitivity": assessment.data_sensitivity, "history_overlap": assessment.history, "predicate_refinement_proxy": assessment.narrowness, "query_type": assessment.query_type}, allocation_decision=allocation_metadata)

    try:
        require_affordable_allocation(allocation)
    except UnaffordableAllocation as exc:
        history = QueryHistory(
            user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint,
            query_type=analysis.query_type, tables_accessed=[analysis.table],
            attributes_accessed=list(analysis.columns), risk_score=assessment.overall,
            epsilon=0.0, decision="budget_rejected",
        )
        db.add(history)
        db.flush()
        _write_audit(
            db, user_id=user.id, event_type="privacy_budget_rejected", status_value="rejected",
            metadata={"query_id": history.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint,
                      "reason": "policy_allocation_exceeds_remaining", **exc.decision.audit_metadata(components=assessment, config=DEFAULT_POLICY)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    release_key = protected_release_key(
        lookup_key=lookup_key, epsilon=epsilon, sensitivity=sensitivity,
        mechanism=mechanism, clipping_bounds=clipping_bounds,
        adjacency_model=ADJACENCY_MODEL, dataset_version=dataset_metadata.version,
        policy_version=PROTECTED_RELEASE_POLICY_VERSION,
    )
    noise_scale = sensitivity / epsilon
    components = {
        "query_sensitivity": assessment.query_sensitivity,
        "data_sensitivity": assessment.data_sensitivity,
        "history_overlap": assessment.history,
        "predicate_refinement_proxy": assessment.narrowness,
        "query_type": assessment.query_type,
    }

    history = QueryHistory(
        user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint,
        query_type=analysis.query_type, tables_accessed=[analysis.table],
        attributes_accessed=list(analysis.columns), risk_score=assessment.overall,
        epsilon=epsilon, decision="pending",
    )
    db.add(history)
    db.flush()
    try:
        reserve_dataset_release(db, dataset_id=dataset.id, epsilon=epsilon, query_id=history.id)
    except BudgetRejected as exc:
        history.decision = "budget_rejected"
        history.epsilon = 0.0
        _write_audit(db, user_id=user.id, event_type="privacy_budget_rejected", status_value="rejected", metadata={"query_id": history.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, "reason": "concurrent_budget_reservation", **allocation_metadata})
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        raw_aggregate = execute_internal_aggregate(db, dataset, dataset_metadata, analysis)
        protected_value = apply_laplace(raw_aggregate, sensitivity, epsilon)
        release = ProtectedRelease(
            dataset_id=dataset.id,
            release_key=release_key,
            cache_lookup_key=lookup_key,
            fingerprint=analysis.fingerprint,
            query_type=analysis.query_type,
            protected_value=protected_value,
            epsilon=epsilon,
            sensitivity=sensitivity,
            noise_scale=noise_scale,
            risk_score=assessment.overall,
            mechanism=mechanism,
            clipping_bounds=clipping_bounds or {},
            dataset_version=dataset_metadata.version,
            authorization_scope_hash=scope_hash,
            adjacency_model=ADJACENCY_MODEL,
            policy_version=PROTECTED_RELEASE_POLICY_VERSION,
        )
        db.add(release)
        history.decision = "released"
        db.flush()
        _write_audit(db, user_id=user.id, event_type="protected_query_released", status_value="success", metadata={"query_id": history.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, "epsilon_charged": epsilon, **allocation_metadata})
        db.commit()
        db.refresh(history)
        db.refresh(release)
    except IntegrityError:
        db.rollback()
        # Concurrent identical requests may race to create the unique cached release.
        release = db.scalar(select(ProtectedRelease).where(ProtectedRelease.dataset_id == dataset.id, ProtectedRelease.cache_lookup_key == lookup_key))
        if release is None:
            raise HTTPException(status_code=503, detail="The protected release could not be finalized. Please retry.")
        history = QueryHistory(
            user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint,
            query_type=analysis.query_type, tables_accessed=[analysis.table],
            attributes_accessed=list(analysis.columns), risk_score=release.risk_score,
            epsilon=0.0, decision="cached",
        )
        db.add(history)
        db.flush()
        _write_audit(db, user_id=user.id, event_type="protected_query_cached", status_value="success", metadata={"query_id": history.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, **allocation_metadata})
        db.commit()
        budget, remaining, budget_state = _budget_snapshot(db, dataset.id)
        return _response_from_release(query_id=history.id, dataset=dataset, release=release, budget=budget, remaining=remaining, budget_state=budget_state, cache_hit=True, processing_ms=(perf_counter() - started) * 1000, allocation_decision=allocation_metadata)
    except QueryRejected as exc:
        db.rollback()
        failed = QueryHistory(user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint, query_type=analysis.query_type, tables_accessed=[analysis.table], attributes_accessed=list(analysis.columns), risk_score=assessment.overall, epsilon=0.0, decision="execution_rejected")
        db.add(failed)
        db.flush()
        _write_audit(db, user_id=user.id, event_type="protected_query_rejected", status_value="rejected", metadata={"query_id": failed.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, "reason": "execution_validation_failed", "epsilon_charged": 0.0, **allocation_metadata})
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        failed = QueryHistory(user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint, query_type=analysis.query_type, tables_accessed=[analysis.table], attributes_accessed=list(analysis.columns), risk_score=assessment.overall, epsilon=0.0, decision="execution_failed")
        db.add(failed)
        db.flush()
        _write_audit(db, user_id=user.id, event_type="protected_query_failed", status_value="error", metadata={"query_id": failed.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, "reason": "database_execution_failed", "epsilon_charged": 0.0, **allocation_metadata})
        db.commit()
        raise HTTPException(status_code=503, detail="The protected query could not be completed; no privacy budget was charged.") from exc
    except Exception as exc:
        db.rollback()
        failed = QueryHistory(user_id=user.id, dataset_id=dataset.id, fingerprint=analysis.fingerprint, query_type=analysis.query_type, tables_accessed=[analysis.table], attributes_accessed=list(analysis.columns), risk_score=assessment.overall, epsilon=0.0, decision="execution_failed")
        db.add(failed)
        db.flush()
        _write_audit(db, user_id=user.id, event_type="protected_query_failed", status_value="error", metadata={"query_id": failed.id, "dataset_id": dataset.id, "fingerprint": analysis.fingerprint, "reason": "release_processing_failed", "epsilon_charged": 0.0, **allocation_metadata})
        db.commit()
        raise HTTPException(status_code=503, detail="The protected query could not be completed; no privacy budget was charged.") from exc

    budget, remaining, budget_state = _budget_snapshot(db, dataset.id)
    return _response_from_release(
        query_id=history.id, dataset=dataset, release=release, budget=budget,
        remaining=remaining, budget_state=budget_state, cache_hit=False,
        processing_ms=(perf_counter() - started) * 1000, risk_components=components,
        allocation_decision=allocation_metadata,
    )


def _query_history_rows():
    protected = select(
        literal("protected").label("kind"), QueryHistory.id.label("record_id"),
        QueryHistory.user_id.label("user_id"), User.username.label("username"),
        QueryHistory.dataset_id.label("dataset_id"), Dataset.name.label("dataset_name"),
        QueryHistory.query_type.label("query_type"), QueryHistory.fingerprint.label("fingerprint"),
        QueryHistory.epsilon.label("epsilon"), QueryHistory.risk_score.label("risk_score"),
        QueryHistory.decision.label("decision"), QueryHistory.created_at.label("created_at"),
        QueryHistory.attributes_accessed.label("attributes"),
    ).join(User, User.id == QueryHistory.user_id).join(Dataset, Dataset.id == QueryHistory.dataset_id)
    analysis = select(
        literal("analysis").label("kind"), QueryAnalysisEvent.id.label("record_id"),
        QueryAnalysisEvent.user_id.label("user_id"), User.username.label("username"),
        QueryAnalysisEvent.dataset_id.label("dataset_id"), Dataset.name.label("dataset_name"),
        QueryAnalysisEvent.query_type.label("query_type"), QueryAnalysisEvent.fingerprint.label("fingerprint"),
        literal(0.0).label("epsilon"), literal(None).label("risk_score"),
        QueryAnalysisEvent.decision.label("decision"), QueryAnalysisEvent.created_at.label("created_at"),
        QueryAnalysisEvent.attributes_accessed.label("attributes"),
    ).join(User, User.id == QueryAnalysisEvent.user_id).outerjoin(Dataset, Dataset.id == QueryAnalysisEvent.dataset_id)
    return union_all(protected, analysis).subquery()


def _has_permission(db: Session, user: User, permission_key: str) -> bool:
    return db.scalar(select(RolePermission.role_id).join(UserRole, UserRole.role_id == RolePermission.role_id).join(Permission, Permission.id == RolePermission.permission_id).where(UserRole.user_id == user.id, Permission.key == permission_key).limit(1)) is not None


@router.get("/history", response_model=QueryHistoryResponse)
def list_query_history(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=100), dataset_id: int | None = Query(default=None, gt=0),
    user_id: int | None = Query(default=None, gt=0), query_type: str | None = Query(default=None, max_length=20),
    decision: str | None = Query(default=None, max_length=30), date_from: datetime | None = None,
    date_to: datetime | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> QueryHistoryResponse:
    can_read_all = _has_permission(db, user, "history:read_all")
    if not can_read_all and not _has_permission(db, user, "history:read_own"):
        raise HTTPException(status_code=403, detail="Permission denied")
    if dataset_id is not None:
        _allowed_dataset(db, user=user, dataset_id=dataset_id)
    if user_id is not None and not can_read_all and user_id != user.id:
        raise HTTPException(status_code=403, detail="You may only filter your own query history.")
    records = _query_history_rows()
    stmt = select(records)
    count_stmt = select(func.count()).select_from(records)
    conditions = []
    if not can_read_all:
        conditions.append(records.c.user_id == user.id)
    if dataset_id is not None:
        conditions.append(records.c.dataset_id == dataset_id)
    if user_id is not None:
        conditions.append(records.c.user_id == user_id)
    if query_type:
        conditions.append(records.c.query_type == query_type.lower())
    if decision:
        conditions.append(records.c.decision == decision.lower())
    if date_from:
        conditions.append(records.c.created_at >= date_from)
    if date_to:
        conditions.append(records.c.created_at <= date_to)
    if search.strip():
        term = f"%{search.strip()}%"
        conditions.append(or_(records.c.username.ilike(term), records.c.dataset_name.ilike(term), records.c.fingerprint.ilike(term), records.c.query_type.ilike(term), records.c.decision.ilike(term), cast(records.c.record_id, String).ilike(term)))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    rows = db.execute(stmt.order_by(records.c.created_at.desc(), records.c.record_id.desc()).offset((page - 1) * page_size).limit(page_size)).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["id"] = f"{'A' if item['kind'] == 'analysis' else 'P'}-{item.pop('record_id')}"
        item["request_kind"] = item.pop("kind")
        item["attributes"] = item.get("attributes") or []
        items.append(item)
    return QueryHistoryResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/history/{record_ref}")
def get_query_history_detail(record_ref: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        prefix, raw_id = record_ref.split("-", maxsplit=1)
        record_id = int(raw_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail="Query history item was not found.") from exc
    can_read_all = _has_permission(db, user, "history:read_all")
    if not can_read_all and not _has_permission(db, user, "history:read_own"):
        raise HTTPException(status_code=403, detail="Permission denied")
    analysis_only = prefix.upper() == "A"
    model = QueryAnalysisEvent if analysis_only else QueryHistory if prefix.upper() == "P" else None
    if model is None:
        raise HTTPException(status_code=404, detail="Query history item was not found.")
    entry = db.get(model, record_id)
    if entry is None or (not can_read_all and entry.user_id != user.id):
        raise HTTPException(status_code=404, detail="Query history item was not found.")
    dataset = db.get(Dataset, entry.dataset_id) if entry.dataset_id else None
    return {
        "id": record_ref.upper(), "request_kind": "analysis" if analysis_only else "protected",
        "user_id": entry.user_id, "username": db.get(User, entry.user_id).username,
        "dataset_id": entry.dataset_id, "dataset_name": dataset.name if dataset else None,
        "query_type": entry.query_type, "fingerprint": entry.fingerprint,
        "epsilon": 0.0 if analysis_only else entry.epsilon,
        "risk_score": None if analysis_only else entry.risk_score,
        "decision": entry.decision, "created_at": entry.created_at,
        "attributes": entry.attributes_accessed,
        "detail": "SQL structure was analyzed; no database execution or privacy budget charge occurred." if analysis_only else "Protected release metadata only. Raw aggregate and protected result are not included in query history.",
    }
