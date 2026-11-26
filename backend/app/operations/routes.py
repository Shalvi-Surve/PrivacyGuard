from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, literal, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.budget.accountant import ACCOUNTING_STATUS, validated_budget_values
from app.auth.dependencies import current_user
from app.database.connection import get_db
from app.database.models import AuditLog, BudgetLedger, Dataset, DatasetGrant, DatasetMetadata, Permission, PrivacyBudget, ProtectedRelease, QueryAnalysisEvent, QueryHistory, RolePermission, User, UserRole

router = APIRouter(prefix="/api", tags=["operations"])


def _has_permission(db: Session, user: User, key: str) -> bool:
    return db.scalar(
        select(RolePermission.role_id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == user.id, Permission.key == key)
        .limit(1)
    ) is not None


def _accessible_dataset_ids(db: Session, user: User):
    return select(DatasetGrant.dataset_id).join(UserRole, UserRole.role_id == DatasetGrant.role_id).where(UserRole.user_id == user.id)


def _budget_state(initial: float, consumed: float) -> str:
    remaining = max(0.0, initial - consumed)
    fraction = consumed / initial if initial else 1.0
    return "EXHAUSTED" if remaining <= 1e-9 else "CRITICAL" if fraction >= .9 else "WARNING" if fraction >= .7 else "NORMAL"


@router.get("/budgets")
def get_budgets(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
    dataset_id: int | None = Query(default=None, gt=0),
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    if not (_has_permission(db, user, "budgets:read_own") or _has_permission(db, user, "budgets:read_all")):
        raise HTTPException(status_code=403, detail="Permission denied")
    accessible_ids = _accessible_dataset_ids(db, user)
    conditions = [PrivacyBudget.scope == "dataset", PrivacyBudget.owner_id.is_(None), Dataset.is_active.is_(True), Dataset.id.in_(accessible_ids)]
    if dataset_id is not None:
        conditions.append(Dataset.id == dataset_id)
    base = select(PrivacyBudget, Dataset).join(Dataset, Dataset.id == PrivacyBudget.dataset_id).where(*conditions)
    count = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = []
    for budget, dataset in db.execute(base.order_by(Dataset.name).offset((page - 1) * page_size).limit(page_size)).all():
        try:
            remaining, utilization = validated_budget_values(budget.initial_epsilon, budget.consumed_epsilon)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Shared privacy accounting metadata is inconsistent.") from exc
        release_count = db.scalar(select(func.count(BudgetLedger.id)).where(BudgetLedger.budget_id == budget.id, BudgetLedger.event_type == "release")) or 0
        metadata = db.get(DatasetMetadata, dataset.id)
        items.append({"budget_id": budget.id, "dataset_id": dataset.id, "dataset_name": dataset.name, "source_type": metadata.source_type if metadata else "unknown", "initial_epsilon": budget.initial_epsilon, "spent_epsilon": budget.consumed_epsilon, "remaining_epsilon": remaining, "utilization": utilization, "state": _budget_state(budget.initial_epsilon, budget.consumed_epsilon), "release_count": release_count, "updated_at": budget.updated_at, "accounting_status": ACCOUNTING_STATUS})
    ledger_query = select(BudgetLedger, Dataset.name, User.username).join(PrivacyBudget, PrivacyBudget.id == BudgetLedger.budget_id).join(Dataset, Dataset.id == PrivacyBudget.dataset_id).outerjoin(QueryHistory, QueryHistory.id == BudgetLedger.query_id).outerjoin(User, User.id == QueryHistory.user_id).where(BudgetLedger.budget_id.in_(select(PrivacyBudget.id).where(*[PrivacyBudget.scope == "dataset", PrivacyBudget.owner_id.is_(None), PrivacyBudget.dataset_id.in_(accessible_ids)])))
    if dataset_id is not None:
        ledger_query = ledger_query.where(Dataset.id == dataset_id)
    ledger_count = db.scalar(select(func.count()).select_from(ledger_query.subquery())) or 0
    ledger = [{"id": entry.id, "query_id": entry.query_id, "dataset_name": name, "user": username, "epsilon": entry.delta_epsilon, "event_type": entry.event_type, "created_at": entry.created_at} for entry, name, username in db.execute(ledger_query.order_by(BudgetLedger.created_at.desc(), BudgetLedger.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()]
    return {"items": items, "total": count, "page": page, "page_size": page_size, "ledger": ledger, "ledger_total": ledger_count, "accounting_status": ACCOUNTING_STATUS}


@router.get("/audit")
def list_audit_logs(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
    search: str = Query(default="", max_length=100), event_type: str | None = Query(default=None, max_length=50),
    status: str | None = Query(default=None, max_length=20), user_id: int | None = Query(default=None, gt=0),
    date_from: datetime | None = None, date_to: datetime | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    if not _has_permission(db, user, "audit:read"):
        raise HTTPException(status_code=403, detail="Permission denied")
    stmt = select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.user_id)
    conditions = []
    if event_type:
        conditions.append(AuditLog.event_type == event_type)
    if status:
        conditions.append(AuditLog.status == status)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    if date_from:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to:
        conditions.append(AuditLog.created_at <= date_to)
    if search.strip():
        term = f"%{search.strip()}%"
        conditions.append(or_(AuditLog.event_type.ilike(term), AuditLog.status.ilike(term), User.username.ilike(term), cast(AuditLog.safe_metadata, String).ilike(term), cast(AuditLog.id, String).ilike(term)))
    if conditions:
        stmt = stmt.where(*conditions)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": event.id, "user_id": event.user_id, "username": username, "event_type": event.event_type, "status": event.status, "metadata": event.safe_metadata, "created_at": event.created_at} for event, username in rows], "total": total, "page": page, "page_size": page_size}


def _safe_event_description(event_type: str) -> str:
    descriptions = {
        "login_succeeded": "User signed in successfully.",
        "login_failed": "A sign-in attempt was rejected.",
        "dataset_created": "A dataset was registered.",
        "dataset_deleted": "A dataset was removed.",
        "query_analyzed": "A restricted SQL request was analyzed.",
        "query_analysis_rejected": "SQL analysis rejected a request.",
        "protected_query_released": "A protected query release was created.",
        "protected_query_cached": "A protected query reused a stored release.",
        "query_rejected": "A protected query request was rejected.",
        "privacy_budget_rejected": "A request exceeded the available privacy budget.",
        "protected_query_failed": "Protected query processing failed.",
    }
    return descriptions.get(event_type, "A recorded system event occurred.")


@router.get("/dashboard/summary")
def dashboard_summary(
    days: int = 7,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return persisted, permission-scoped overview analytics.

    Request counts count submitted analysis/protected requests, including a
    cache-hit request. ``protected_releases`` counts unique stored DP outputs.
    """
    if days < 1 or days > 90:
        raise HTTPException(status_code=422, detail="days must be between 1 and 90")
    can_read_history_all = _has_permission(db, user, "history:read_all")
    can_read_history_own = _has_permission(db, user, "history:read_own")
    can_read_datasets = _has_permission(db, user, "datasets:read")
    can_read_budgets = _has_permission(db, user, "budgets:read_all") or _has_permission(db, user, "budgets:read_own")
    can_read_audit_all = _has_permission(db, user, "audit:read")
    if not (can_read_history_all or can_read_history_own):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        db.execute(select(1))
        database_status = "available"
    except SQLAlchemyError:
        database_status = "unavailable"
    if database_status == "unavailable":
        raise HTTPException(status_code=503, detail="Dashboard data is temporarily unavailable because the database cannot be reached.")

    if can_read_datasets:
        accessible_ids = (
            select(DatasetGrant.dataset_id)
            .join(UserRole, UserRole.role_id == DatasetGrant.role_id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRole.user_id == user.id, Permission.key == "datasets:read")
            .distinct()
        )
        datasets = db.execute(
            select(Dataset.id, Dataset.name)
            .where(Dataset.id.in_(accessible_ids), Dataset.is_active.is_(True))
            .order_by(Dataset.name)
        ).all()
    else:
        datasets = []
    dataset_ids = [row.id for row in datasets]

    history_conditions = [QueryHistory.dataset_id.in_(dataset_ids)] if dataset_ids else [False]
    analysis_conditions = [or_(QueryAnalysisEvent.dataset_id.in_(dataset_ids), QueryAnalysisEvent.dataset_id.is_(None))]
    if not can_read_history_all:
        history_conditions.append(QueryHistory.user_id == user.id)
        analysis_conditions.append(QueryAnalysisEvent.user_id == user.id)

    history_total = db.scalar(select(func.count(QueryHistory.id)).where(*history_conditions)) or 0
    analysis_total = db.scalar(select(func.count(QueryAnalysisEvent.id)).where(*analysis_conditions)) or 0
    total_requests = history_total + analysis_total
    if can_read_history_all:
        protected_releases = db.scalar(
            select(func.count(ProtectedRelease.id)).where(ProtectedRelease.dataset_id.in_(dataset_ids))
        ) if dataset_ids else 0
    else:
        # Without history:read_all, only count unique protected query identities
        # visible in this user's own request history.
        protected_releases = db.scalar(
            select(func.count(func.distinct(QueryHistory.fingerprint))).where(
                *history_conditions, QueryHistory.decision.in_(("released", "cached")),
            )
        ) or 0

    decision_counts: dict[str, int] = {}
    for conditions, model in ((history_conditions, QueryHistory), (analysis_conditions, QueryAnalysisEvent)):
        grouped = db.execute(
            select(model.decision, func.count())
            .where(*conditions)
            .group_by(model.decision)
        ).all()
        for decision, count in grouped:
            key = str(decision or "unknown")
            decision_counts[key] = decision_counts.get(key, 0) + int(count)

    rejected_decisions = {"rejected", "budget_rejected", "execution_rejected"}
    approved_requests = sum(count for key, count in decision_counts.items() if key in {"released", "cached", "analysis_only"})
    rejected_requests = sum(count for key, count in decision_counts.items() if key in rejected_decisions)
    other_requests = total_requests - approved_requests - rejected_requests
    high_risk = db.scalar(
        select(func.count(QueryHistory.id)).where(*history_conditions, QueryHistory.risk_score >= 0.67)
    ) or 0
    scored_requests = db.scalar(
        select(func.count(QueryHistory.id)).where(*history_conditions, QueryHistory.risk_score.is_not(None))
    ) or 0
    risk_distribution = {
        "low": db.scalar(select(func.count(QueryHistory.id)).where(*history_conditions, QueryHistory.risk_score.is_not(None), QueryHistory.risk_score < 0.34)) or 0,
        "medium": db.scalar(select(func.count(QueryHistory.id)).where(*history_conditions, QueryHistory.risk_score >= 0.34, QueryHistory.risk_score < 0.67)) or 0,
        "high": int(high_risk),
    }

    end = datetime.now(timezone.utc)
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_counts: dict[str, dict[str, int]] = {}
    for conditions, model in ((history_conditions, QueryHistory), (analysis_conditions, QueryAnalysisEvent)):
        grouped = db.execute(
            select(func.date(model.created_at), model.decision, func.count())
            .where(*conditions, model.created_at >= start)
            .group_by(func.date(model.created_at), model.decision)
        ).all()
        for day, decision, count in grouped:
            date_key = str(day)
            category = "approved" if decision in {"released", "cached", "analysis_only"} else "rejected" if decision in rejected_decisions else "other"
            counts = daily_counts.setdefault(date_key, {"approved": 0, "rejected": 0, "other": 0})
            counts[category] += int(count)
    daily_activity = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date().isoformat()
        counts = daily_counts.get(day, {"approved": 0, "rejected": 0, "other": 0})
        daily_activity.append({"date": day, **counts, "total": sum(counts.values())})

    def recent_rows(model, conditions, kind: str):
        stmt = (
            select(model.id, model.user_id, User.username, model.dataset_id, Dataset.name.label("dataset_name"), model.query_type, model.decision, model.created_at)
            .join(User, User.id == model.user_id)
            .outerjoin(Dataset, Dataset.id == model.dataset_id)
            .where(*conditions)
            .order_by(model.created_at.desc(), model.id.desc())
            .limit(10)
        )
        if model is QueryHistory:
            stmt = stmt.add_columns(model.epsilon, model.risk_score)
        else:
            stmt = stmt.add_columns(literal(None).label("epsilon"), literal(None).label("risk_score"))
        return [
            {"id": f"{'P' if kind == 'protected' else 'A'}-{row.id}", "query_id": row.id,
             "request_kind": kind, "user": row.username, "dataset_id": row.dataset_id,
             "dataset_name": row.dataset_name, "query_type": row.query_type,
             "epsilon": row.epsilon, "risk_score": row.risk_score,
             "decision": row.decision, "created_at": row.created_at}
            for row in db.execute(stmt).all()
        ]

    recent_activity = recent_rows(QueryHistory, history_conditions, "protected") + recent_rows(QueryAnalysisEvent, analysis_conditions, "analysis")
    recent_activity.sort(key=lambda row: row["created_at"], reverse=True)

    budget_rows = []
    if can_read_budgets and dataset_ids:
        budget_rows = db.execute(
            select(PrivacyBudget, Dataset.name)
            .join(Dataset, Dataset.id == PrivacyBudget.dataset_id)
            .where(PrivacyBudget.dataset_id.in_(dataset_ids), PrivacyBudget.scope == "dataset", PrivacyBudget.owner_id.is_(None))
            .order_by(Dataset.name)
        ).all()
    budget_by_dataset = {budget.dataset_id: budget for budget, _ in budget_rows}
    budget_datasets = []
    for dataset in datasets:
        budget = budget_by_dataset.get(dataset.id)
        if budget is None:
            budget_datasets.append({"dataset_id": dataset.id, "dataset_name": dataset.name, "available": False, "scope": "dataset", "initial_budget": None, "spent_budget": None, "remaining_budget": None, "utilization": None})
        else:
            try:
                remaining, utilization = validated_budget_values(budget.initial_epsilon, budget.consumed_epsilon)
            except ValueError:
                budget_datasets.append({"dataset_id": dataset.id, "dataset_name": dataset.name, "available": False, "scope": "dataset", "initial_budget": None, "spent_budget": None, "remaining_budget": None, "utilization": None})
                continue
            budget_datasets.append({"dataset_id": dataset.id, "dataset_name": dataset.name, "available": True, "scope": "dataset", "initial_budget": budget.initial_epsilon, "spent_budget": budget.consumed_epsilon, "remaining_budget": remaining, "utilization": utilization})
    budgets_complete = bool(budget_datasets) and all(item["available"] for item in budget_datasets) and can_read_budgets
    budget_health = {
        "available": budgets_complete,
        "scope": "shared_dataset",
        "accounting_status": ACCOUNTING_STATUS,
        "initial_budget": sum(item["initial_budget"] for item in budget_datasets) if budgets_complete else None,
        "spent_budget": sum(item["spent_budget"] for item in budget_datasets) if budgets_complete else None,
        "remaining_budget": sum(item["remaining_budget"] for item in budget_datasets) if budgets_complete else None,
        "utilization": (sum(item["spent_budget"] for item in budget_datasets) / sum(item["initial_budget"] for item in budget_datasets)) if budgets_complete and sum(item["initial_budget"] for item in budget_datasets) else (1.0 if budgets_complete else None),
        "datasets": budget_datasets,
    }

    audit_conditions = [] if can_read_audit_all else [AuditLog.user_id == user.id]
    audit_rows = db.execute(
        select(AuditLog.id, AuditLog.event_type, AuditLog.status, AuditLog.created_at, User.username)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*audit_conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(6)
    ).all()
    recent_audit = [{"id": row.id, "event_type": row.event_type, "actor": row.username or "System", "timestamp": row.created_at, "status": row.status, "description": _safe_event_description(row.event_type)} for row in audit_rows]

    return {
        "window_days": days,
        "metrics": {
            "total_requests": total_requests,
            "protected_releases": int(protected_releases or 0),
            "approved_requests": approved_requests,
            "rejected_requests": rejected_requests,
            "other_requests": other_requests,
            "high_risk_requests": int(high_risk),
            "risk_scored_requests": int(scored_requests),
            "risk_unscored_or_rejected_requests": max(0, total_requests - int(scored_requests)),
            "high_risk_threshold": 0.67,
            "high_risk_percentage_of_scored": (int(high_risk) / int(scored_requests) * 100) if scored_requests else None,
            "privacy_spent": budget_health["spent_budget"],
            "remaining_budget": budget_health["remaining_budget"],
            "accessible_datasets": len(dataset_ids),
        },
        "daily_activity": daily_activity,
        "decision_distribution": decision_counts,
        "recent_activity": recent_activity[:10],
        "budget_health": budget_health,
        "recent_audit_activity": recent_audit,
        "operational_signals": {
            "api_health": "available",
            "database": database_status,
            "sql_analysis": "available" if database_status == "available" else "unavailable",
            "protected_releases": "available" if database_status == "available" else "unavailable",
            "experiments": "available",
        },
    }
