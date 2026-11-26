from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.auth.dependencies import current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.database.connection import Base
from app.database.models import AuditLog, Permission, Role, RolePermission, User, UserRole
from app.rbac.permissions import require_permission
from app.users.routes import list_users, reset_user_password, router as users_router


@pytest.fixture
def user_management_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'user-reset-test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as db:
        admin_role = Role(name="administrator", description="Administrator")
        researcher_role = Role(name="researcher", description="Researcher")
        manage_permission = Permission(key="users:manage", description="Manage users")
        admin = User(username="admin", email="admin@example.test", full_name="Admin", password_hash=hash_password("admin-old-password"))
        target = User(username="researcher_demo", email="researcher@example.test", full_name="Researcher", password_hash=hash_password("researcher-old-password"), is_active=False)
        other = User(username="unrelated", email="unrelated@example.test", full_name="Unrelated", password_hash=hash_password("unrelated-old-password"))
        db.add_all([admin_role, researcher_role, manage_permission, admin, target, other])
        db.flush()
        db.add_all([
            RolePermission(role_id=admin_role.id, permission_id=manage_permission.id),
            UserRole(user_id=admin.id, role_id=admin_role.id),
            UserRole(user_id=target.id, role_id=researcher_role.id),
            UserRole(user_id=other.id, role_id=researcher_role.id),
        ])
        db.flush()
        ids = {"admin": admin.id, "target": target.id, "other": other.id}
        other_hash = other.password_hash
        target_hash = target.password_hash
    yield factory, ids, target_hash, other_hash
    engine.dispose()


def request_with_json(payload: object) -> Request:
    body = json.dumps(payload).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/users/researcher_demo/password-reset", "raw_path": b"/api/users/researcher_demo/password-reset",
        "query_string": b"", "headers": [(b"content-type", b"application/json")],
        "client": ("testclient", 123), "server": ("testserver", 80),
    }
    return Request(scope, receive)


def run_immediate(coroutine):
    """Drive this request-only coroutine without opening a Windows event loop."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Password reset unexpectedly performed asynchronous I/O.")


def user_from_token(username: str, factory) -> User:
    with factory() as db:
        return current_user(create_access_token(username), db)


def test_only_users_manage_can_list_accounts_and_response_has_no_hash(user_management_db):
    factory, _, target_hash, _ = user_management_db
    with factory() as db:
        admin = current_user(create_access_token("admin"), db)
        response = list_users(admin, db)
        assert {row["username"] for row in response["items"]} == {"admin", "researcher_demo", "unrelated"}
        assert all("password" not in row and "hash" not in row for row in response["items"])
        assert target_hash not in json.dumps(response)

        permission_check = require_permission("users:manage")
        researcher = db.scalar(select(User).where(User.username == "researcher_demo"))
        with pytest.raises(HTTPException) as forbidden:
            permission_check(researcher, db)
        assert forbidden.value.status_code == 403
        with pytest.raises(HTTPException) as unauthenticated:
            current_user("not-a-valid-token", db)
        assert unauthenticated.value.status_code == 401

    paths = {route.path: route.methods for route in users_router.routes}
    assert paths["/api/users"] == {"GET"}
    assert "POST" in paths["/api/users/{username}/password-reset"]


def test_admin_reset_hashes_new_password_audits_safely_and_preserves_account(user_management_db):
    factory, ids, target_hash, other_hash = user_management_db
    new_password = "A newly chosen secure password 2026!"
    with factory() as db:
        admin = db.get(User, ids["admin"])
        response = run_immediate(reset_user_password("researcher_demo", request_with_json({"new_password": new_password}), admin, db))
        assert response == {"username": "researcher_demo", "status": "password_reset"}

    with factory() as db:
        target = db.get(User, ids["target"])
        other = db.get(User, ids["other"])
        assert target.password_hash != new_password
        assert target.password_hash != target_hash
        assert verify_password(new_password, target.password_hash)
        assert not verify_password("researcher-old-password", target.password_hash)
        assert target.is_active is False
        assert [assignment.role.name for assignment in target.roles] == ["researcher"]
        assert other.password_hash == other_hash
        event = db.scalar(select(AuditLog).where(AuditLog.event_type == "user_password_reset"))
        assert event is not None
        assert event.user_id == ids["admin"]
        assert event.status == "success"
        assert event.safe_metadata == {"target_user_id": ids["target"], "target_username": "researcher_demo"}
        assert new_password not in str(event.safe_metadata)
        assert target_hash not in str(event.safe_metadata)


@pytest.mark.parametrize(
    ("username", "payload", "expected_status", "expected_detail"),
    [
        ("researcher_demo", {"new_password": "short"}, 422, "at least 12 characters"),
        ("researcher_demo", {"new_password": "long enough password", "extra": "secret"}, 422, "only a new_password"),
        ("not-a-user", {"new_password": "long enough password"}, 404, "not found"),
        ("admin", {"new_password": "long enough password"}, 400, "own password"),
    ],
)
def test_reset_validation_errors_are_safe_and_do_not_write_audit(user_management_db, username, payload, expected_status, expected_detail):
    factory, ids, target_hash, _ = user_management_db
    with factory() as db:
        admin = db.get(User, ids["admin"])
        request = request_with_json(payload)
        request.scope["path"] = f"/api/users/{username}/password-reset"
        request.scope["raw_path"] = request.scope["path"].encode()
        with pytest.raises(HTTPException) as error:
            run_immediate(reset_user_password(username, request, admin, db))
        assert error.value.status_code == expected_status
        assert expected_detail in error.value.detail
        assert "short" not in error.value.detail and "secret" not in error.value.detail
        assert db.scalar(select(AuditLog).where(AuditLog.event_type == "user_password_reset")) is None
        assert db.get(User, ids["target"]).password_hash == target_hash


def test_non_admin_cannot_invoke_password_reset_dependency(user_management_db):
    factory, ids, target_hash, _ = user_management_db
    with factory() as db:
        researcher = db.get(User, ids["target"])
        target = db.get(User, ids["other"])
        with pytest.raises(HTTPException) as forbidden:
            require_permission("users:manage")(researcher, db)
        assert forbidden.value.status_code == 403
        assert verify_password("unrelated-old-password", target.password_hash)
        assert target_hash != target.password_hash
