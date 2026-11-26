from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import AuditLog, BudgetLedger, Dataset, DatasetGrant, DatasetMetadata, Employee, Permission, PrivacyBudget, ProtectedRelease, QueryAnalysisEvent, QueryHistory, Role, RolePermission, User, UserRole, utcnow
from app.datasets.generation import SUPPORTED_EMPLOYEE_SIZES, iter_employee_rows
from app.datasets.schemas import DatasetListResponse, DatasetResponse, EmployeeDatasetRequest
from app.rbac.permissions import require_permission

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
BATCH_SIZE = 2_000
EMPLOYEE_COLUMN_TYPES = {
    "employee_id": "string", "department": "string", "designation": "string",
    "age": "integer", "gender": "string", "salary": "integer",
    "performance_score": "number", "location": "string",
}


def _response(dataset: Dataset, metadata: DatasetMetadata, db: Session | None = None) -> DatasetResponse:
    owner = db.get(User, metadata.owner_id) if db is not None and metadata.owner_id else None
    roles = db.scalars(select(Role.name).join(DatasetGrant, DatasetGrant.role_id == Role.id).where(DatasetGrant.dataset_id == dataset.id)).all() if db is not None else []
    return DatasetResponse(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        source_type=metadata.source_type,
        table_name=metadata.table_name,
        record_count=metadata.record_count,
        sensitivity=metadata.sensitivity,
        created_at=metadata.created_at,
        owner=owner.username if owner else None,
        access_roles=list(roles),
        columns=metadata.column_metadata or [],
    )


def _allowed_dataset(db: Session, *, user: User, dataset_id: int) -> tuple[Dataset, DatasetMetadata]:
    role_query = select(UserRole.role_id).join(DatasetGrant, DatasetGrant.role_id == UserRole.role_id).join(RolePermission, RolePermission.role_id == UserRole.role_id).join(Permission, Permission.id == RolePermission.permission_id).where(UserRole.user_id == user.id, DatasetGrant.dataset_id == dataset_id, Permission.key == "datasets:read")
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.is_active.is_(True), role_query.exists())
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset is unavailable or not assigned to your role.")
    metadata = db.get(DatasetMetadata, dataset.id)
    if metadata is None:
        raise HTTPException(status_code=409, detail="Dataset metadata is incomplete.")
    return dataset, metadata


@router.get("", response_model=DatasetListResponse)
def list_datasets(user: User = Depends(require_permission("datasets:read")), db: Session = Depends(get_db)) -> DatasetListResponse:
    rows = db.execute(
        select(Dataset, DatasetMetadata)
        .join(DatasetMetadata, DatasetMetadata.dataset_id == Dataset.id)
        .join(DatasetGrant, DatasetGrant.dataset_id == Dataset.id)
        .join(UserRole, UserRole.role_id == DatasetGrant.role_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == user.id, Permission.key == "datasets:read", Dataset.is_active.is_(True))
        .distinct()
        .order_by(Dataset.id)
    ).all()
    return DatasetListResponse(items=[_response(dataset, metadata, db) for dataset, metadata in rows])


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(dataset_id: int, user: User = Depends(require_permission("datasets:read")), db: Session = Depends(get_db)) -> DatasetResponse:
    dataset, metadata = _allowed_dataset(db, user=user, dataset_id=dataset_id)
    return _response(dataset, metadata, db)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: int, user: User = Depends(require_permission("datasets:manage")), db: Session = Depends(get_db)) -> None:
    role_can_manage = db.scalar(select(UserRole.role_id).join(RolePermission, RolePermission.role_id == UserRole.role_id).join(Permission, Permission.id == RolePermission.permission_id).join(DatasetGrant, DatasetGrant.role_id == UserRole.role_id).where(UserRole.user_id == user.id, DatasetGrant.dataset_id == dataset_id, Permission.key == "datasets:manage").limit(1))
    if role_can_manage is None:
        raise HTTPException(status_code=404, detail="Dataset is unavailable or not assigned to your role.")
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or not dataset.is_active:
        raise HTTPException(status_code=404, detail="Dataset is unavailable or not assigned to your role.")
    budget_ids = db.scalars(select(PrivacyBudget.id).where(PrivacyBudget.dataset_id == dataset_id)).all()
    history_ids = db.scalars(select(QueryHistory.id).where(QueryHistory.dataset_id == dataset_id)).all()
    db.add(AuditLog(user_id=user.id, event_type="dataset_deleted", status="success", safe_metadata={"dataset_id": dataset_id}))
    if history_ids:
        db.execute(delete(BudgetLedger).where(BudgetLedger.query_id.in_(history_ids)))
    if budget_ids:
        db.execute(delete(BudgetLedger).where(BudgetLedger.budget_id.in_(budget_ids)))
    db.execute(delete(QueryHistory).where(QueryHistory.dataset_id == dataset_id))
    db.execute(delete(QueryAnalysisEvent).where(QueryAnalysisEvent.dataset_id == dataset_id))
    db.execute(delete(ProtectedRelease).where(ProtectedRelease.dataset_id == dataset_id))
    db.execute(delete(Employee).where(Employee.dataset_id == dataset_id))
    db.execute(delete(DatasetGrant).where(DatasetGrant.dataset_id == dataset_id))
    db.execute(delete(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset_id))
    db.execute(delete(PrivacyBudget).where(PrivacyBudget.dataset_id == dataset_id))
    db.delete(dataset)
    db.commit()


@router.post("/synthetic/employees", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
def generate_employee_dataset(
    payload: EmployeeDatasetRequest,
    user: User = Depends(require_permission("datasets:manage")),
    db: Session = Depends(get_db),
) -> DatasetResponse:
    if payload.size not in SUPPORTED_EMPLOYEE_SIZES:
        raise HTTPException(status_code=422, detail="Choose a supported record count: 5000, 25000, 100000, or 500000.")
    if db.scalar(select(Dataset.id).where(Dataset.name == payload.name)) is not None:
        raise HTTPException(status_code=409, detail="A dataset with this name already exists.")
    dataset = Dataset(name=payload.name, description=f"Reproducible synthetic employee dataset ({payload.size:,} rows)")
    db.add(dataset)
    try:
        db.flush()
        metadata = DatasetMetadata(
            dataset_id=dataset.id,
            source_type="synthetic",
            table_name="employees",
            record_count=payload.size,
            sensitivity="synthetic_personal",
            column_metadata=[{"name": name, "data_type": kind, "missing_values": 0} for name, kind in EMPLOYEE_COLUMN_TYPES.items()],
            owner_id=user.id,
            created_at=utcnow(),
        )
        db.add(metadata)
        db.add(PrivacyBudget(dataset_id=dataset.id, scope="dataset", owner_id=None, initial_epsilon=payload.initial_epsilon, consumed_epsilon=0.0))
        allowed_roles = db.scalars(
            select(UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(Permission.key == "queries:execute_protected")
            .distinct()
        ).all()
        db.add_all([DatasetGrant(dataset_id=dataset.id, role_id=role_id) for role_id in allowed_roles])
        db.flush()
        iterator = iter_employee_rows(dataset.id, payload.size, payload.seed)
        while batch := [next(iterator, None) for _ in range(BATCH_SIZE)]:
            batch = [row for row in batch if row is not None]
            if not batch:
                break
            db.execute(insert(Employee), batch)
        db.commit()
        db.refresh(dataset)
        db.refresh(metadata)
    except Exception:
        db.rollback()
        raise
    return _response(dataset, metadata)
