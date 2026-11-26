from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(240), default="")
    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(240), default="")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship()


class Dataset(Base):
    __tablename__ = "dataset_registry"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DatasetMetadata(Base):
    """Non-secret registry details for supported analytical datasets."""
    __tablename__ = "dataset_metadata"
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_registry.id", ondelete="CASCADE"), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(30), default="synthetic")
    table_name: Mapped[str] = mapped_column(String(80))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    sensitivity: Mapped[str] = mapped_column(String(30), default="synthetic")
    column_metadata: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DatasetGrant(Base):
    __tablename__ = "dataset_grants"
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_registry.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class Employee(Base):
    """Synthetic employee row; dataset_id enforces tenant-style dataset isolation."""
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("dataset_id", "employee_id"), Index("ix_employees_dataset_department", "dataset_id", "department"))
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_registry.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[str] = mapped_column(String(24))
    department: Mapped[str] = mapped_column(String(40), index=True)
    designation: Mapped[str] = mapped_column(String(40))
    age: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(20))
    salary: Mapped[int] = mapped_column(Integer)
    performance_score: Mapped[float] = mapped_column(Float)
    location: Mapped[str] = mapped_column(String(50))


class ProtectedRelease(Base):
    """Cached protected outputs only; raw aggregate values are never persisted."""
    __tablename__ = "protected_releases"
    __table_args__ = (UniqueConstraint("dataset_id", "release_key"), UniqueConstraint("dataset_id", "cache_lookup_key"))
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_registry.id", ondelete="CASCADE"), index=True)
    release_key: Mapped[str] = mapped_column(String(64))
    cache_lookup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    query_type: Mapped[str] = mapped_column(String(20))
    protected_value: Mapped[float] = mapped_column(Float)
    epsilon: Mapped[float] = mapped_column(Float)
    sensitivity: Mapped[float] = mapped_column(Float)
    noise_scale: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    mechanism: Mapped[str] = mapped_column(String(30), default="Laplace", server_default="Laplace")
    clipping_bounds: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    dataset_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    authorization_scope_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    adjacency_model: Mapped[str] = mapped_column(String(40), default="add_remove_one_record", server_default="add_remove_one_record")
    policy_version: Mapped[str] = mapped_column(String(40), default="protected-release-v2", server_default="protected-release-v2")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrivacyBudget(Base):
    """Dataset ledger is authoritative; user rows are usage attribution only."""
    __tablename__ = "privacy_budgets"
    __table_args__ = (UniqueConstraint("scope", "owner_id", "dataset_id"), Index("ix_budget_dataset_scope", "dataset_id", "scope"))
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), default="dataset")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_registry.id"))
    initial_epsilon: Mapped[float] = mapped_column(Float)
    consumed_epsilon: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class QueryHistory(Base):
    __tablename__ = "query_history"
    __table_args__ = (Index("ix_query_history_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_registry.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    query_type: Mapped[str] = mapped_column(String(20))
    tables_accessed: Mapped[list] = mapped_column(JSON, default=list)
    attributes_accessed: Mapped[list] = mapped_column(JSON, default=list)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    epsilon: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueryAnalysisEvent(Base):
    """Analysis-only requests; stores structure, never submitted SQL text."""
    __tablename__ = "query_analysis_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_registry.id"), nullable=True, index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    query_type: Mapped[str] = mapped_column(String(20), default="unknown")
    attributes_accessed: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(30), default="analysis_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BudgetLedger(Base):
    __tablename__ = "budget_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("privacy_budgets.id"), index=True)
    query_id: Mapped[int | None] = mapped_column(ForeignKey("query_history.id"), nullable=True)
    delta_epsilon: Mapped[float] = mapped_column(Float)
    event_type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20))
    safe_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentResult(Base):
    __tablename__ = "experiment_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("experiment_runs.id", ondelete="CASCADE"), index=True)
    baseline: Mapped[str] = mapped_column(String(50))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
