import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret-that-is-long-enough-for-tests"

from fastapi import HTTPException

from app.auth.dependencies import current_user
from app.auth.routes import login
from app.auth.schemas import LoginRequest
from app.auth.security import decode_access_token
from app.auth.security import hash_password
from app.database.connection import Base, engine, SessionLocal
from app.database.models import Role, User, UserRole


def setup_demo_account() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="analyst").one_or_none()
        if user is None:
            role = Role(name="analyst", description="test")
            user = User(username="analyst", email="analyst@example.test", full_name="Test Analyst", password_hash=hash_password("correct horse battery staple"))
            db.add_all([role, user])
            db.flush()
            db.add(UserRole(user_id=user.id, role_id=role.id))


def test_login_and_profile():
    setup_demo_account()
    db = SessionLocal()
    try:
        token_response = login(LoginRequest(username="analyst", password="correct horse battery staple"), db)
        assert token_response.token_type == "bearer"
        username = decode_access_token(token_response.access_token)
        assert username == "analyst"
        user = current_user(token_response.access_token, db)
        assert sorted(assignment.role.name for assignment in user.roles) == ["analyst"]
    finally:
        db.close()


def test_invalid_password_is_rejected():
    setup_demo_account()
    db = SessionLocal()
    try:
        try:
            login(LoginRequest(username="analyst", password="incorrect"), db)
            assert False, "invalid password must be rejected"
        except HTTPException as exc:
            assert exc.status_code == 401
    finally:
        db.close()
