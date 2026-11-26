from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.auth.schemas import LoginRequest, TokenResponse
from app.auth.security import create_access_token, verify_password
from app.database.connection import get_db
from app.database.models import AuditLog, User

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        db.add(AuditLog(user_id=user.id if user else None, event_type="login_failed", status="rejected", safe_metadata={}))
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    db.add(AuditLog(user_id=user.id, event_type="login_succeeded", status="success", safe_metadata={}))
    db.commit()
    return TokenResponse(access_token=create_access_token(user.username))


@router.post("/logout", status_code=204)
def logout() -> None:
    # Bearer tokens are stateless. Clients discard the token; revocation/refresh is not yet implemented.
    return None


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "roles": sorted(assignment.role.name for assignment in user.roles),
    }
