from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.database.connection import get_db
from app.database.models import AuditLog, User
from app.rbac.permissions import require_permission

router = APIRouter(prefix="/api/users", tags=["user management"])
MIN_PASSWORD_LENGTH = 12  # Existing demo-account password policy (seed_demo.py).
MAX_PASSWORD_LENGTH = 1024


@router.get("")
def list_users(
    _admin: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict:
    """Return only non-secret account fields for the administrator UI."""
    users = db.scalars(select(User).order_by(User.username)).all()
    return {
        "items": [
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "is_active": user.is_active,
                "roles": sorted(assignment.role.name for assignment in user.roles),
            }
            for user in users
        ],
        "total": len(users),
    }


@router.post("/{username}/password-reset", status_code=status.HTTP_200_OK)
async def reset_user_password(
    username: str,
    request: Request,
    admin: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Reset a different user's password without echoing it in validation errors."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="A valid JSON password reset request is required.") from None
    if not isinstance(payload, dict) or set(payload) != {"new_password"}:
        raise HTTPException(status_code=422, detail="Request must contain only a new_password field.")
    new_password = payload.get("new_password")
    if not isinstance(new_password, str):
        raise HTTPException(status_code=422, detail="The new password must be a string.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"The new password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(new_password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"The new password must be no longer than {MAX_PASSWORD_LENGTH} characters.")
    if username == admin.username:
        raise HTTPException(status_code=400, detail="Use the account recovery process to change your own password.")

    target = db.scalar(select(User).where(User.username == username))
    if target is None:
        raise HTTPException(status_code=404, detail="User was not found.")

    # The supplied plaintext is used only for hashing and is never included in
    # logs, audit metadata, response data, or a persisted field.
    target.password_hash = hash_password(new_password)
    db.add(AuditLog(
        user_id=admin.id,
        event_type="user_password_reset",
        status="success",
        safe_metadata={"target_user_id": target.id, "target_username": target.username},
    ))
    db.commit()
    return {"username": target.username, "status": "password_reset"}
