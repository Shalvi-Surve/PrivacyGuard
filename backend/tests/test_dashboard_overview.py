import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-that-is-long-enough-for-tests")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import current_user
from app.auth.security import hash_password
from app.database.connection import Base
from app.database.models import (
    AuditLog, BudgetLedger, Dataset, DatasetGrant, DatasetMetadata, Employee, Permission,
    PrivacyBudget, ProtectedRelease, QueryAnalysisEvent, QueryHistory, Role,
    RolePermission, User, UserRole,
)
from app.main import app
from app.operations.routes import dashboard_summary, router as operations_router
from app.query.routes import ProtectedQueryRequest, execute_protected_query


@pytest.fixture
def dashboard_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        permissions = [Permission(key=key, description="test") for key in ("datasets:read", "history:read_own", "history:read_all", "budgets:read_own", "audit:read", "queries:execute_protected")]
        researcher_role = Role(name="dashboard_researcher", description="test")
        admin_role = Role(name="dashboard_admin", description="test")
        isolated_role = Role(name="dashboard_isolated", description="test")
        researcher = User(username="dash-researcher", email="dash-researcher@example.test", full_name="Researcher", password_hash=hash_password("test-password"))
        second_user = User(username="dash-other", email="dash-other@example.test", full_name="Other", password_hash=hash_password("test-password"))
        admin = User(username="dash-admin", email="dash-admin@example.test", full_name="Admin", password_hash=hash_password("test-password"))
        denied = User(username="dash-denied", email="dash-denied@example.test", full_name="Denied", password_hash=hash_password("test-password"))
        visible = Dataset(name="visible-dataset", description="visible", is_active=True)
        hidden = Dataset(name="hidden-dataset", description="hidden", is_active=True)
        db.add_all([*permissions, researcher_role, admin_role, isolated_role, researcher, second_user, admin, denied, visible, hidden])
        db.flush()
        permission_map = {permission.key: permission.id for permission in permissions}
        for key in ("datasets:read", "history:read_own", "budgets:read_own", "queries:execute_protected"):
            db.add(RolePermission(role_id=researcher_role.id, permission_id=permission_map[key]))
        for key in ("datasets:read", "history:read_all", "budgets:read_own", "audit:read"):
            db.add(RolePermission(role_id=admin_role.id, permission_id=permission_map[key]))
        db.add(RolePermission(role_id=isolated_role.id, permission_id=permission_map["datasets:read"]))
        db.add_all([
            UserRole(user_id=researcher.id, role_id=researcher_role.id),
            UserRole(user_id=second_user.id, role_id=researcher_role.id),
            UserRole(user_id=admin.id, role_id=admin_role.id),
            UserRole(user_id=denied.id, role_id=isolated_role.id),
            DatasetGrant(dataset_id=visible.id, role_id=researcher_role.id),
            DatasetGrant(dataset_id=visible.id, role_id=admin_role.id),
            DatasetGrant(dataset_id=hidden.id, role_id=isolated_role.id),
            DatasetMetadata(dataset_id=visible.id, source_type="synthetic", table_name="employees", record_count=3, owner_id=researcher.id),
            DatasetMetadata(dataset_id=hidden.id, source_type="synthetic", table_name="employees", record_count=10, owner_id=denied.id),
            PrivacyBudget(dataset_id=visible.id, scope="dataset", owner_id=None, initial_epsilon=10.0, consumed_epsilon=0.5),
            Employee(dataset_id=visible.id, employee_id="E-1", department="Research", designation="Analyst", age=32, gender="Woman", salary=100_000, performance_score=4.0, location="North"),
            Employee(dataset_id=visible.id, employee_id="E-2", department="Research", designation="Scientist", age=41, gender="Man", salary=180_000, performance_score=4.5, location="South"),
        ])
        researcher_id, second_id, admin_id, denied_id, visible_id = researcher.id, second_user.id, admin.id, denied.id, visible.id
        db.flush()
        released = QueryHistory(user_id=researcher_id, dataset_id=visible_id, fingerprint="fp-1", query_type="count", tables_accessed=["employees"], attributes_accessed=[], risk_score=0.2, epsilon=0.5, decision="released")
        cached = QueryHistory(user_id=second_id, dataset_id=visible_id, fingerprint="fp-1", query_type="count", tables_accessed=["employees"], attributes_accessed=[], risk_score=0.2, epsilon=0.0, decision="cached")
        db.add_all([released, cached])
        db.flush()
        db.add_all([
            ProtectedRelease(dataset_id=visible_id, release_key="release-key", cache_lookup_key="lookup-key", fingerprint="fp-1", query_type="count", protected_value=3.0, epsilon=0.5, sensitivity=1.0, noise_scale=2.0, risk_score=0.2),
            BudgetLedger(budget_id=db.query(PrivacyBudget).filter_by(dataset_id=visible_id).one().id, query_id=released.id, delta_epsilon=0.5, event_type="release"),
            QueryAnalysisEvent(user_id=researcher_id, dataset_id=visible_id, fingerprint="fp-2", query_type="sum", attributes_accessed=["salary"], decision="rejected"),
            AuditLog(user_id=researcher_id, event_type="protected_query_released", status="success", safe_metadata={"token": "must-not-leak", "raw_aggregate": 123}),
            AuditLog(user_id=second_id, event_type="login_failed", status="rejected", safe_metadata={}),
        ])
    yield {"factory": factory, "engine": engine, "researcher_id": researcher_id, "second_id": second_id, "admin_id": admin_id, "denied_id": denied_id, "dataset_id": visible_id}
    app.dependency_overrides.clear()
    engine.dispose()


def _get_user(data, user_id):
    with data["factory"]() as db:
        user = db.get(User, user_id)
        db.expunge(user)
        return user


def test_overview_route_is_registered_and_returns_persisted_metrics_for_authenticated_user(dashboard_data):
    route = next(route for route in operations_router.routes if getattr(route, "path", None) == "/api/dashboard/summary")
    assert "GET" in route.methods
    assert current_user in {dependency.call for dependency in route.dependant.dependencies}
    assert "/api/dashboard/summary" in app.openapi()["paths"]
    with dashboard_data["factory"]() as db:
        payload = dashboard_summary(days=7, user=db.get(User, dashboard_data["admin_id"]), db=db)
        assert payload["metrics"] == {
            "total_requests": 3, "protected_releases": 1, "approved_requests": 2,
            "rejected_requests": 1, "other_requests": 0, "high_risk_requests": 0,
            "risk_scored_requests": 2, "risk_unscored_or_rejected_requests": 1,
            "high_risk_threshold": 0.67, "high_risk_percentage_of_scored": 0.0,
            "privacy_spent": 0.5, "remaining_budget": 9.5, "accessible_datasets": 1,
        }
        assert payload["decision_distribution"] == {"released": 1, "cached": 1, "rejected": 1}
        assert len(payload["recent_activity"]) == 3
        assert {row["user"] for row in payload["recent_activity"]} == {"dash-researcher", "dash-other"}
        assert payload["budget_health"]["scope"] == "shared_dataset"
        assert payload["budget_health"]["datasets"][0]["dataset_name"] == "visible-dataset"
        assert {item["actor"] for item in payload["recent_audit_activity"]} >= {"dash-researcher", "dash-other"}
        assert "token" not in str(payload) and "raw_aggregate" not in str(payload)
        assert payload["operational_signals"]["experiments"] == "available"


def test_overview_scopes_datasets_history_and_audit_by_role(dashboard_data):
    data = dashboard_data
    with data["factory"]() as db:
        researcher = db.get(User, data["researcher_id"])
        researcher_data = dashboard_summary(days=7, user=researcher, db=db)
        assert researcher_data["metrics"]["total_requests"] == 2
        assert researcher_data["metrics"]["accessible_datasets"] == 1
        assert {item["actor"] for item in researcher_data["recent_audit_activity"]} == {"dash-researcher"}
        admin = db.get(User, data["admin_id"])
        admin_data = dashboard_summary(days=7, user=admin, db=db)
        assert admin_data["metrics"]["total_requests"] == 3
        assert admin_data["metrics"]["accessible_datasets"] == 1
        assert {item["actor"] for item in admin_data["recent_audit_activity"]} >= {"dash-researcher", "dash-other"}
        denied = db.get(User, data["denied_id"])
        with pytest.raises(HTTPException) as error:
            dashboard_summary(days=7, user=denied, db=db)
        assert error.value.status_code == 403


def test_overview_empty_state_and_missing_budget_are_not_fabricated(dashboard_data):
    data = dashboard_data
    with data["factory"].begin() as db:
        db.query(PrivacyBudget).filter_by(dataset_id=data["dataset_id"]).delete()
        db.query(QueryHistory).filter_by(dataset_id=data["dataset_id"]).delete()
        db.query(QueryAnalysisEvent).filter_by(dataset_id=data["dataset_id"]).delete()
        db.query(ProtectedRelease).filter_by(dataset_id=data["dataset_id"]).delete()
    with data["factory"]() as db:
        researcher = db.get(User, data["researcher_id"])
        payload = dashboard_summary(days=7, user=researcher, db=db)
        assert payload["metrics"]["total_requests"] == 0
        assert payload["metrics"]["protected_releases"] == 0
        assert payload["budget_health"]["available"] is False
        assert payload["metrics"]["privacy_spent"] is None
        assert payload["budget_health"]["datasets"][0]["initial_budget"] is None
        assert len(payload["daily_activity"]) == 7
        assert all(day["total"] == 0 for day in payload["daily_activity"])


def test_overview_counts_multiple_unique_releases_and_shared_ledger(dashboard_data):
    data = dashboard_data
    with data["factory"].begin() as db:
        budget = db.query(PrivacyBudget).filter_by(dataset_id=data["dataset_id"]).one()
        budget.consumed_epsilon = 0.75
        db.add(ProtectedRelease(dataset_id=data["dataset_id"], release_key="release-key-2", cache_lookup_key="lookup-key-2", fingerprint="fp-2", query_type="sum", protected_value=0, epsilon=0.25, sensitivity=5, noise_scale=20, risk_score=0.8))
        db.add(BudgetLedger(budget_id=budget.id, query_id=None, delta_epsilon=0.25, event_type="release"))
    with data["factory"]() as db:
        admin = db.get(User, data["admin_id"])
        overview = dashboard_summary(days=7, user=admin, db=db)
        assert overview["metrics"]["protected_releases"] == 2
        assert overview["metrics"]["privacy_spent"] == pytest.approx(0.75)
        assert overview["metrics"]["remaining_budget"] == pytest.approx(9.25)
        assert overview["budget_health"]["datasets"][0]["utilization"] == pytest.approx(0.075)


def test_protected_query_workflow_updates_live_dashboard_and_cache_counts_once(dashboard_data, monkeypatch):
    from app.privacy.policy import EpsilonAllocation
    import app.query.routes as query_routes
    def fixed(*, assessment, cumulative_fraction, remaining_epsilon, config):
        return EpsilonAllocation(.5, .5, assessment.overall, cumulative_fraction, remaining_epsilon, config.policy_id)
    monkeypatch.setattr(query_routes, "allocate_epsilon_decision", fixed)
    data = dashboard_data
    with data["factory"].begin() as db:
        db.query(BudgetLedger).delete()
        db.query(QueryHistory).delete()
        db.query(QueryAnalysisEvent).delete()
        db.query(ProtectedRelease).delete()
        budget = db.query(PrivacyBudget).filter_by(dataset_id=data["dataset_id"]).one()
        budget.consumed_epsilon = 0
    sql = "SELECT COUNT(*) FROM employees"
    with data["factory"]() as db:
        researcher = db.get(User, data["researcher_id"])
        first = execute_protected_query(ProtectedQueryRequest(dataset_id=data["dataset_id"], sql=sql), researcher, db)
        assert first.cache_hit is False
    with data["factory"]() as db:
        researcher = db.get(User, data["researcher_id"])
        overview = dashboard_summary(days=7, user=researcher, db=db)
        assert overview["metrics"]["total_requests"] == 1
        assert overview["metrics"]["protected_releases"] == 1
        assert overview["metrics"]["privacy_spent"] == pytest.approx(first.epsilon)
        assert overview["metrics"]["remaining_budget"] == pytest.approx(10 - first.epsilon)
        assert overview["recent_activity"][0]["id"] == f"P-{first.query_id}"
    with data["factory"]() as db:
        researcher = db.get(User, data["researcher_id"])
        cached = execute_protected_query(ProtectedQueryRequest(dataset_id=data["dataset_id"], sql=sql), researcher, db)
        assert cached.cache_hit is True
        assert cached.protected_result == first.protected_result
    with data["factory"]() as db:
        researcher = db.get(User, data["researcher_id"])
        overview = dashboard_summary(days=7, user=researcher, db=db)
        assert overview["metrics"]["total_requests"] == 2
        assert overview["metrics"]["approved_requests"] == 2
        assert overview["metrics"]["protected_releases"] == 1
        assert overview["metrics"]["privacy_spent"] == pytest.approx(first.epsilon)
        assert overview["decision_distribution"] == {"released": 1, "cached": 1}
        assert len(overview["recent_audit_activity"]) >= 2
