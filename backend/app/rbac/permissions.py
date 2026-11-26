from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.database.connection import get_db
from app.database.models import Permission, RolePermission, User, UserRole


def require_permission(permission_key: str):
    """Return a dependency that enforces a seeded role permission server-side."""
    def check(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        granted = db.scalar(
            select(Permission.id)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user.id, Permission.key == permission_key)
            .limit(1)
        )
        if granted is None:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user

    return check
