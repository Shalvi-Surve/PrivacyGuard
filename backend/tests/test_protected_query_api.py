import os
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-that-is-long-enough-for-tests")

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.security import hash_password
from app.database.connection import Base
from app.database.models import (
    AuditLog, BudgetLedger, Dataset, DatasetGrant, DatasetMetadata, Employee,
    Permission, PrivacyBudget, ProtectedRelease, QueryAnalysisEvent, QueryHistory, Role,
    RolePermission, User, UserRole,
)
from app.query.analysis import analyze_query
from app.query.execution import execute_internal_aggregate
from app.datasets.generation import iter_employee_rows
from app.query.routes import ProtectedQueryRequest, execute_protected_query
from app.query.routes import AnalyzeRequest, analyze, get_query_history_detail, list_query_history
from app.operations.routes import get_budgets
from app.query.analysis import protected_release_key, protected_release_lookup_key
from app.privacy.sensitivity import bounded_sum_sensitivity
from app.budget.accountant import BudgetRejected, reserve_dataset_release
from app.privacy.policy import EpsilonAllocation
from app.privacy.history import query_history_signals


def _fix_allocation(monkeypatch, epsilon):
    import app.query.routes as query_routes
    def fixed(*, assessment, cumulative_fraction, remaining_epsilon, config):
        return EpsilonAllocation(epsilon, epsilon, assessment.overall, cumulative_fraction, remaining_epsilon, config.policy_id)
    monkeypatch.setattr(query_routes, "allocate_epsilon_decision", fixed)


def _session_factory(tmp_path, *, dataset_granted: bool = True):
    engine = create_engine(f"sqlite:///{tmp_path / 'protected-query-test.db'}", connect_args={"check_same_thread": False, "timeout": 15})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        permission = Permission(key="queries:execute_protected", description="test")
        read_permission = Permission(key="datasets:read", description="test")
        history_permission = Permission(key="history:read_own", description="test")
        budget_permission = Permission(key="budgets:read_own", description="test")
        manage_permission = Permission(key="datasets:manage", description="test")
        analyze_permission = Permission(key="queries:submit", description="test")
        role = Role(name="researcher", description="test")
        user = User(username="researcher", email="researcher@example.test", full_name="Test Researcher", password_hash=hash_password("test-password"))
        dataset = Dataset(name="employees-test", description="synthetic", is_active=True)
        db.add_all([permission, read_permission, history_permission, budget_permission, manage_permission, analyze_permission, role, user, dataset])
        db.flush()
        db.add_all([
            RolePermission(role_id=role.id, permission_id=permission.id),
            RolePermission(role_id=role.id, permission_id=read_permission.id),
            RolePermission(role_id=role.id, permission_id=history_permission.id),
            RolePermission(role_id=role.id, permission_id=budget_permission.id),
            RolePermission(role_id=role.id, permission_id=manage_permission.id),
            RolePermission(role_id=role.id, permission_id=analyze_permission.id),
            UserRole(user_id=user.id, role_id=role.id),
            DatasetMetadata(dataset_id=dataset.id, source_type="synthetic", table_name="employees", record_count=3, sensitivity="synthetic_personal", owner_id=user.id),
            PrivacyBudget(dataset_id=dataset.id, scope="dataset", owner_id=None, initial_epsilon=10.0, consumed_epsilon=0.0),
        ])
        if dataset_granted:
            db.add(DatasetGrant(dataset_id=dataset.id, role_id=role.id))
        db.add_all([
            Employee(dataset_id=dataset.id, employee_id="E-1", department="Engineering", designation="Senior", age=38, gender="Woman", salary=100_000, performance_score=4.0, location="North"),
            Employee(dataset_id=dataset.id, employee_id="E-2", department="Finance", designation="Lead", age=42, gender="Man", salary=130_000, performance_score=4.5, location="South"),
            Employee(dataset_id=dataset.id, employee_id="E-3", department="Engineering", designation="Associate", age=29, gender="Non-binary", salary=70_000, performance_score=3.5, location="East"),
        ])
        dataset_id = dataset.id
        user_id = user.id

    return factory, engine, dataset_id, user_id


def test_protected_count_release_charges_once_and_caches_exact_repeat(tmp_path, monkeypatch):
    _fix_allocation(monkeypatch, 0.5)
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        with factory() as db:
            user = db.get(User, user_id)
            request = ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees")
            body = execute_protected_query(request, user, db)
            assert body.query_type == "count"
            assert body.sensitivity == 1.0
            assert body.noise_scale == body.sensitivity / body.epsilon
            assert body.decision == "RELEASED"
            assert not hasattr(body, "raw_aggregate")
            assert "raw_aggregate" not in body.model_dump()
            assert body.adjacency_model == "add_remove_one_record"
            assert body.mechanism == "Laplace"
            assert body.cache_hit is False
            assert body.privacy_spent == body.epsilon
            cached = execute_protected_query(request, user, db)
            assert cached.cache_hit is True
            assert cached.protected_result == body.protected_result
            assert cached.epsilon_charged == 0
            assert cached.privacy_spent == body.privacy_spent

        with factory() as db:
            assert db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).count() == 1
            assert db.query(QueryHistory).filter_by(dataset_id=dataset_id).count() == 2
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 1
            assert db.query(AuditLog).filter(AuditLog.event_type.in_(["protected_query_released", "protected_query_cached"])).count() == 2
    finally:
        engine.dispose()


def test_rejected_queries_do_not_charge_or_execute_raw_sql(tmp_path, monkeypatch):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        with factory() as db:
            user = db.get(User, user_id)
            with pytest.raises(HTTPException) as error:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="DELETE FROM employees"), user, db)
            assert error.value.status_code == 422
        with factory() as db:
            budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
            assert budget.consumed_epsilon == 0
            assert db.query(Employee).filter_by(dataset_id=dataset_id).count() == 3
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 0
            assert db.query(AuditLog).filter_by(event_type="query_rejected").count() == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("sql", ["SELECT COUNT(*) FROM employees", "SELECT SUM(salary) FROM employees"])
def test_dataset_role_grant_is_enforced_by_backend(tmp_path, monkeypatch, sql):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path, dataset_granted=False)
    try:
        with factory() as db:
            user = db.get(User, user_id)
            with pytest.raises(HTTPException) as error:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql=sql), user, db)
            assert error.value.status_code == 404
        with factory() as db:
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("sql", ["SELECT COUNT(*) FROM employees", "SELECT SUM(salary) FROM employees"])
def test_execution_failure_rolls_back_reservation_and_sanitizes_error(tmp_path, monkeypatch, sql):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        import app.query.routes as query_routes
        def fail_after_reservation(*args, **kwargs):
            raise RuntimeError("database password=do-not-leak; employee row details")
        monkeypatch.setattr(query_routes, "execute_internal_aggregate", fail_after_reservation)
        with factory() as db:
            with pytest.raises(HTTPException) as error:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql=sql), db.get(User, user_id), db)
            assert error.value.status_code == 503
            assert "do-not-leak" not in error.value.detail
        with factory() as db:
            budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
            assert budget.consumed_epsilon == 0
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 0
            history = db.query(QueryHistory).filter_by(dataset_id=dataset_id).one()
            assert history.decision == "execution_failed"
            audit = db.query(AuditLog).filter_by(event_type="protected_query_failed").one()
            assert "do-not-leak" not in str(audit.safe_metadata)
    finally:
        engine.dispose()


def test_history_detail_is_scoped_to_requesting_user(tmp_path):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        with factory.begin() as db:
            role = db.query(Role).filter_by(name="researcher").one()
            stranger = User(username="other-researcher", email="other@example.test", full_name="Other Researcher", password_hash=hash_password("other-password"))
            db.add(stranger)
            db.flush()
            db.add(UserRole(user_id=stranger.id, role_id=role.id))
            stranger_id = stranger.id
        with factory() as db:
            execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees"), db.get(User, user_id), db)
        with factory() as db:
            stranger = db.get(User, stranger_id)
            page = list_query_history(page=1, page_size=20, search="", dataset_id=None, user_id=None, query_type=None, decision=None, date_from=None, date_to=None, user=stranger, db=db)
            assert page.total == 0
            with pytest.raises(HTTPException) as error:
                get_query_history_detail("P-1", stranger, db)
            assert error.value.status_code == 404
    finally:
        engine.dispose()


def test_or_predicates_keep_their_boolean_meaning(tmp_path, monkeypatch):
    factory, engine, dataset_id, _ = _session_factory(tmp_path)
    try:
        analysis = analyze_query(
            "SELECT COUNT(*) FROM employees WHERE department = 'Engineering' OR department = 'Finance'",
            allowed_tables={"employees"},
            allowed_columns={"department"},
        )
        with factory() as db:
            dataset = db.get(Dataset, dataset_id)
            metadata = db.get(DatasetMetadata, dataset_id)
            assert execute_internal_aggregate(db, dataset, metadata, analysis) == 3
    finally:
        engine.dispose()


def test_bounded_sum_clips_rows_and_uses_full_record_level_sensitivity(tmp_path):
    factory, engine, dataset_id, _ = _session_factory(tmp_path)
    try:
        with factory() as db:
            employee = db.query(Employee).filter_by(dataset_id=dataset_id, employee_id="E-1").one()
            employee.salary = 999_999
            db.commit()
            dataset = db.get(Dataset, dataset_id)
            metadata = db.get(DatasetMetadata, dataset_id)
            analysis = analyze_query("SELECT SUM(salary) FROM employees", allowed_tables={"employees"}, allowed_columns={"salary"})
            assert execute_internal_aggregate(db, dataset, metadata, analysis) == 300_000 + 130_000 + 70_000
            from app.query.execution import sensitivity_for
            assert sensitivity_for(analysis)[0] == 300_000
            score_analysis = analyze_query("SELECT SUM(performance_score) FROM employees", allowed_tables={"employees"}, allowed_columns={"performance_score"})
            assert execute_internal_aggregate(db, dataset, metadata, score_analysis) == pytest.approx(12.0)
            assert sensitivity_for(score_analysis) == (5.0, 0.0, 1.0, 5.0)
    finally:
        engine.dispose()


def test_bounded_sum_release_is_noisy_cached_once_and_charges_shared_budget(tmp_path, monkeypatch):
    import math
    import app.privacy.laplace as laplace
    import app.query.routes as query_routes

    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        monkeypatch.setattr(laplace.secrets, "randbelow", lambda _: 3 * 2**51)
        _fix_allocation(monkeypatch, 0.5)
        with factory.begin() as db:
            db.query(Employee).filter_by(dataset_id=dataset_id, employee_id="E-1").one().salary = -500
            db.query(Employee).filter_by(dataset_id=dataset_id, employee_id="E-2").one().salary = 300_001

        request = ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT SUM(salary) FROM employees")
        with factory() as db:
            first = execute_protected_query(request, db.get(User, user_id), db)
            expected_raw = 370_000.0  # -500 clips to 0; 300001 clips to 300000
            assert first.protected_result == pytest.approx(expected_raw + 600_000 * math.log(2))
            assert first.query_type == "sum"
            assert first.adjacency_model == "add_remove_one_record"
            assert first.sensitivity == 300_000
            assert first.noise_scale == first.sensitivity / first.epsilon == 600_000
            assert first.clipping_bounds == {"lower": 0.0, "upper": 300_000.0}
            assert first.cache_hit is False
            assert first.privacy_spent == pytest.approx(0.5)
            assert not hasattr(first, "raw_aggregate")
            assert "raw_aggregate" not in first.model_dump()
            assert first.protected_result != expected_raw

            _fix_allocation(monkeypatch, 0.5)
            cached = execute_protected_query(request, db.get(User, user_id), db)
            assert cached.cache_hit is True
            assert cached.protected_result == first.protected_result
            assert cached.epsilon == first.epsilon
            assert cached.epsilon_charged == 0
            assert cached.privacy_spent == first.privacy_spent

        with factory() as db:
            release = db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).one()
            assert release.protected_value == pytest.approx(first.protected_result)
            assert release.protected_value != expected_raw
            assert not hasattr(release, "raw_aggregate")
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 1
            assert db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one().consumed_epsilon == pytest.approx(0.5)
            history = db.query(QueryHistory).filter_by(dataset_id=dataset_id).order_by(QueryHistory.id).all()
            assert [row.decision for row in history] == ["released", "cached"]
            assert all(not hasattr(row, "raw_aggregate") and not hasattr(row, "sql") for row in history)
    finally:
        engine.dispose()


def test_empty_bounded_sum_returns_noisy_zero_and_charges(tmp_path, monkeypatch):
    import math
    import app.privacy.laplace as laplace
    import app.query.routes as query_routes

    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        monkeypatch.setattr(laplace.secrets, "randbelow", lambda _: 3 * 2**51)
        _fix_allocation(monkeypatch, 0.5)
        with factory.begin() as db:
            db.query(Employee).filter_by(dataset_id=dataset_id).delete()
        with factory() as db:
            result = execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT SUM(salary) FROM employees"), db.get(User, user_id), db)
            assert result.protected_result == pytest.approx(600_000 * math.log(2))
            assert result.sensitivity == 300_000
            assert result.noise_scale == 600_000
            assert result.protected_result != 0
        with factory() as db:
            assert db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one().consumed_epsilon == pytest.approx(0.5)
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 1
    finally:
        engine.dispose()


def test_sum_without_configured_bounds_is_rejected_before_accounting(tmp_path, monkeypatch):
    from app.query import execution
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        monkeypatch.delitem(execution.SUM_BOUNDS, "salary")
        with factory() as db:
            with pytest.raises(HTTPException) as error:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT SUM(salary) FROM employees"), db.get(User, user_id), db)
            assert error.value.status_code == 422
        with factory() as db:
            assert db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one().consumed_epsilon == 0
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 0
    finally:
        engine.dispose()


def test_insufficient_budget_rejects_new_sum_without_creating_release(tmp_path, monkeypatch):
    import app.query.routes as query_routes
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        _fix_allocation(monkeypatch, 0.1)
        with factory.begin() as db:
            db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one().initial_epsilon = 0.05
        with factory() as db:
            with pytest.raises(HTTPException) as error:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT SUM(salary) FROM employees"), db.get(User, user_id), db)
            assert error.value.status_code == 409
        with factory() as db:
            assert db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).count() == 0
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 0
            assert db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one().consumed_epsilon == 0
    finally:
        engine.dispose()


def test_adaptive_epsilon_changes_create_distinct_charged_release(tmp_path, monkeypatch):
    import app.query.routes as query_routes
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    allocations = iter((0.5, 0.4))
    def changing(*, assessment, cumulative_fraction, remaining_epsilon, config):
        epsilon = next(allocations)
        return EpsilonAllocation(epsilon, epsilon, assessment.overall, cumulative_fraction, remaining_epsilon, config.policy_id)
    monkeypatch.setattr(query_routes, "allocate_epsilon_decision", changing)
    try:
        request = ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees")
        with factory() as db:
            first = execute_protected_query(request, db.get(User, user_id), db)
            second = execute_protected_query(request, db.get(User, user_id), db)
            assert first.epsilon == 0.5 and second.epsilon == 0.4
            assert first.cache_hit is False and second.cache_hit is False
            assert second.privacy_spent == pytest.approx(0.9)
        with factory() as db:
            assert db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).count() == 2
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 2
    finally:
        engine.dispose()


def test_exact_cached_release_remains_free_after_budget_exhaustion(tmp_path, monkeypatch):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    _fix_allocation(monkeypatch, 0.5)
    try:
        request = ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees")
        with factory() as db:
            first = execute_protected_query(request, db.get(User, user_id), db)
        with factory.begin() as db:
            budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
            budget.consumed_epsilon = budget.initial_epsilon
        with factory() as db:
            cached = execute_protected_query(request, db.get(User, user_id), db)
            assert cached.cache_hit is True
            assert cached.epsilon_charged == 0
            assert cached.protected_result == first.protected_result
        with factory() as db:
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 1
    finally:
        engine.dispose()


def test_authorized_users_share_the_dataset_budget(tmp_path, monkeypatch):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    _fix_allocation(monkeypatch, 0.5)
    try:
        with factory.begin() as db:
            role_id = db.query(UserRole).filter_by(user_id=user_id).one().role_id
            second = User(username="researcher-two", email="two@example.test", full_name="Second Researcher", password_hash=hash_password("test-password"))
            db.add(second)
            db.flush()
            db.add(UserRole(user_id=second.id, role_id=role_id))
            second_user_id = second.id
        requests = [
            (user_id, "SELECT COUNT(*) FROM employees WHERE department = 'Engineering'"),
            (second_user_id, "SELECT COUNT(*) FROM employees WHERE department = 'Finance'"),
        ]
        with factory() as db:
            for uid, sql in requests:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql=sql), db.get(User, uid), db)
        with factory() as db:
            assert db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).count() == 1
            assert db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one().consumed_epsilon == pytest.approx(1.0)
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 2
    finally:
        engine.dispose()


def test_inconsistent_budget_metadata_fails_closed(tmp_path):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        with factory.begin() as db:
            budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
            budget.consumed_epsilon = budget.initial_epsilon + 1
        with factory() as db:
            with pytest.raises(HTTPException) as error:
                execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees"), db.get(User, user_id), db)
            assert error.value.status_code == 409
        with factory() as db:
            assert db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).count() == 0
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 0
    finally:
        engine.dispose()


def test_history_features_are_bounded_structural_and_dataset_wide(tmp_path):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        current = analyze_query("SELECT COUNT(*) FROM employees WHERE department = 'Engineering'", allowed_tables={"employees"}, allowed_columns={"department"})
        with factory.begin() as db:
            role_id = db.query(UserRole).filter_by(user_id=user_id).one().role_id
            second = User(username="history-peer", email="peer@example.test", full_name="History Peer", password_hash=hash_password("test-password"))
            db.add(second)
            db.flush()
            db.add(UserRole(user_id=second.id, role_id=role_id))
            db.add(QueryHistory(user_id=second.id, dataset_id=dataset_id, fingerprint=current.fingerprint, query_type="count", tables_accessed=["employees"], attributes_accessed=["department", "salary"], risk_score=.2, epsilon=.5, decision="released"))
            db.add(QueryAnalysisEvent(user_id=user_id, dataset_id=dataset_id, fingerprint=current.fingerprint, query_type="count", attributes_accessed=["department"], decision="analysis_only"))
        with factory() as db:
            signals = query_history_signals(db, dataset_id=dataset_id, analysis=current)
            assert signals.overlap == pytest.approx(1.0)
            assert signals.normalized_shape_repeats == pytest.approx(0.4)
            assert signals.normalized_predicate_count == pytest.approx(0.25)
            assert signals.refinement == pytest.approx(0.325)
            assert all(0 <= value <= 1 for value in (signals.overlap, signals.refinement))
    finally:
        engine.dispose()


def test_release_cache_key_scopes_dataset_authorization_and_policy():
    analysis = analyze_query("SELECT COUNT(*) FROM employees WHERE department = 'Engineering'", allowed_tables={"employees"}, allowed_columns={"department"})
    def lookup(query=analysis, dataset=1, version=1, scope=None, policy="v3", mechanism="Laplace", sensitivity=1.0, bounds=None, adjacency="add_remove_one_record", epsilon=0.5):
        return protected_release_lookup_key(analysis=query, dataset_id=dataset, dataset_version=version, authorization_scope=scope or [2], policy_version=policy, mechanism=mechanism, sensitivity=sensitivity, clipping_bounds=bounds, adjacency_model=adjacency, epsilon=epsilon)
    base = lookup()
    assert base == lookup(scope=[2, 2])
    assert base != lookup(dataset=2)
    assert base != lookup(version=2)
    assert base != lookup(scope=[3])
    assert base != lookup(policy="v4")
    assert base != lookup(mechanism="Gaussian")
    assert base != lookup(sensitivity=2)
    assert base != lookup(adjacency="replace_one_record")
    assert base != lookup(epsilon=0.25)
    assert lookup(sensitivity=300_000, bounds={"lower": 0, "upper": 300_000}) != lookup(sensitivity=5, bounds={"lower": 1, "upper": 5})
    other_value = analyze_query("SELECT COUNT(*) FROM employees WHERE department = 'Finance'", allowed_tables={"employees"}, allowed_columns={"department"})
    assert base != lookup(query=other_value)
    config_a = protected_release_key(lookup_key=base, epsilon=0.5, sensitivity=1, mechanism="Laplace", clipping_bounds=None, adjacency_model="add_remove_one_record", dataset_version=1, policy_version="v2")
    config_b = protected_release_key(lookup_key=base, epsilon=0.25, sensitivity=1, mechanism="Laplace", clipping_bounds=None, adjacency_model="add_remove_one_record", dataset_version=1, policy_version="v2")
    assert config_a != config_b


def test_sum_release_cache_configuration_distinguishes_epsilon_and_bounds():
    analysis = analyze_query("SELECT SUM(salary) FROM employees", allowed_tables={"employees"}, allowed_columns={"salary"})
    common = dict(
        analysis=analysis, dataset_id=1, dataset_version=1, authorization_scope=[2],
        policy_version="v3", mechanism="Laplace", sensitivity=300_000,
        adjacency_model="add_remove_one_record",
        epsilon=0.5,
    )
    default_bounds = {"lower": 0.0, "upper": 300_000.0}
    lookup = protected_release_lookup_key(**common, clipping_bounds=default_bounds)
    alternate_bounds_lookup = protected_release_lookup_key(
        **common, clipping_bounds={"lower": -300_000.0, "upper": 300_000.0},
    )
    assert lookup != alternate_bounds_lookup
    configuration = dict(
        lookup_key=lookup, sensitivity=300_000, mechanism="Laplace",
        clipping_bounds=default_bounds, adjacency_model="add_remove_one_record",
        dataset_version=1, policy_version="v3",
    )
    assert protected_release_key(**configuration, epsilon=0.5) != protected_release_key(**configuration, epsilon=0.25)


def test_analysis_history_and_budget_dashboard_use_persisted_records(tmp_path):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    try:
        with factory() as db:
            user = db.get(User, user_id)
            analyzed = analyze(AnalyzeRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees"), user, db)
            assert analyzed.analysis_id > 0
            execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql="SELECT COUNT(*) FROM employees"), user, db)
        with factory() as db:
            user = db.get(User, user_id)
            page = list_query_history(page=1, page_size=20, search="", dataset_id=None, user_id=None, query_type=None, decision=None, date_from=None, date_to=None, user=user, db=db)
            assert page.total == 2
            assert {item["request_kind"] for item in page.items} == {"analysis", "protected"}
            assert next(item for item in page.items if item["request_kind"] == "analysis")["epsilon"] == 0
            budgets = get_budgets(page=1, page_size=25, dataset_id=None, user=user, db=db)
            assert budgets["items"][0]["spent_epsilon"] > 0
            assert budgets["items"][0]["release_count"] == 1
            assert len(budgets["ledger"]) == 1
    finally:
        engine.dispose()


def test_concurrent_distinct_protected_queries_share_atomic_budget(tmp_path):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    barrier = __import__("threading").Barrier(2)
    queries = [
        "SELECT COUNT(*) FROM employees WHERE department = 'Engineering'",
        "SELECT COUNT(*) FROM employees WHERE department = 'Finance'",
    ]
    def run(sql):
        barrier.wait()
        with factory() as db:
            return execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql=sql), db.get(User, user_id), db)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, queries))
        assert len(results) == 2
        with factory() as db:
            assert db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).count() == 2
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 2
            budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
            assert budget.consumed_epsilon == pytest.approx(sum(item.epsilon for item in results))
    finally:
        engine.dispose()


def test_concurrent_reservations_reject_when_combined_budget_is_insufficient(tmp_path):
    factory, engine, dataset_id, _ = _session_factory(tmp_path)
    barrier = __import__("threading").Barrier(2)
    with factory.begin() as db:
        budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
        budget.initial_epsilon = 1.0
    def reserve():
        barrier.wait()
        with factory() as db:
            try:
                reserve_dataset_release(db, dataset_id=dataset_id, epsilon=0.6)
                db.commit()
                return "reserved"
            except BudgetRejected:
                db.rollback()
                return "rejected"
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: reserve(), range(2)))
        assert sorted(results) == ["rejected", "reserved"]
        with factory() as db:
            budget = db.query(PrivacyBudget).filter_by(dataset_id=dataset_id).one()
            assert budget.consumed_epsilon == pytest.approx(0.6)
            ledger = db.query(BudgetLedger).filter_by(event_type="release").all()
            assert len(ledger) == 1
            assert ledger[0].delta_epsilon == pytest.approx(0.6)
            with pytest.raises(BudgetRejected):
                reserve_dataset_release(db, dataset_id=dataset_id, epsilon=0.5)
    finally:
        engine.dispose()


def test_concurrent_identical_protected_queries_persist_one_release(tmp_path):
    factory, engine, dataset_id, user_id = _session_factory(tmp_path)
    barrier = __import__("threading").Barrier(2)
    sql = "SELECT COUNT(*) FROM employees WHERE department = 'Engineering'"
    def run():
        barrier.wait()
        with factory() as db:
            return execute_protected_query(ProtectedQueryRequest(dataset_id=dataset_id, sql=sql), db.get(User, user_id), db)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: run(), range(2)))
        assert sorted(result.cache_hit for result in results) == [False, True]
        assert results[0].protected_result == results[1].protected_result
        with factory() as db:
            assert db.query(ProtectedRelease).filter_by(dataset_id=dataset_id).count() == 1
            assert db.query(BudgetLedger).filter_by(event_type="release").count() == 1
    finally:
        engine.dispose()


def test_synthetic_generator_is_reproducible_and_supports_requested_sizes():
    first = list(iter_employee_rows(7, 5_000, 221))
    second = list(iter_employee_rows(7, 5_000, 221))
    assert len(first) == 5_000
    assert first == second
    assert {row["department"] for row in first} <= {"Engineering", "Finance", "HR", "Operations", "Sales", "Legal", "Research", "Support"}
