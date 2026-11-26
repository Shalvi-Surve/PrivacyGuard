"""Add missing role/permission records from policy without changing users or data."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth.role_policy import ROLE_PERMISSIONS  # noqa: E402
from app.database.connection import SessionLocal  # noqa: E402
from app.database.models import Permission, Role, RolePermission  # noqa: E402


def sync_role_permissions(db: Session) -> dict[str, int]:
    """Idempotently add source-defined permissions and role associations.

    This intentionally does not delete permissions, modify role memberships,
    touch dataset grants, create users, or update password hashes.
    """
    permission_keys = sorted({key for keys in ROLE_PERMISSIONS.values() for key in keys})
    permissions_added = 0
    roles_added = 0
    associations_added = 0
    permissions: dict[str, Permission] = {}

    for key in permission_keys:
        permission = db.scalar(select(Permission).where(Permission.key == key))
        if permission is None:
            permission = Permission(key=key, description=key.replace(":", " ").replace("_", " ").title())
            db.add(permission)
            permissions_added += 1
        permissions[key] = permission
    db.flush()

    for role_name, keys in ROLE_PERMISSIONS.items():
        role = db.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            role = Role(name=role_name, description=f"Demonstration {role_name} role")
            db.add(role)
            db.flush()
            roles_added += 1
        existing_ids = set(db.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all())
        for key in keys:
            permission = permissions[key]
            if permission.id not in existing_ids:
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
                existing_ids.add(permission.id)
                associations_added += 1
    db.flush()
    return {
        "permissions_added": permissions_added,
        "roles_added": roles_added,
        "role_permissions_added": associations_added,
    }


def main() -> None:
    with SessionLocal.begin() as db:
        result = sync_role_permissions(db)
    print("RBAC synchronized from source policy: " + ", ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
