"""Seed demo roles, permissions, and users; set DEMO_PASSWORD before running."""
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.auth.security import hash_password  # noqa: E402
from app.auth.role_policy import ROLE_PERMISSIONS  # noqa: E402
from app.database.connection import Base, SessionLocal, engine  # noqa: E402
from app.database.models import Permission, Role, RolePermission, User, UserRole  # noqa: E402

ROLES = ROLE_PERMISSIONS
USERS = [
    ("admin", "admin@example.test", "Demo Administrator", "administrator"),
    ("hr_demo", "hr@example.test", "Demo HR User", "hr"),
    ("doctor_demo", "doctor@example.test", "Demo Doctor", "doctor"),
    ("researcher_demo", "researcher@example.test", "Demo Researcher", "researcher"),
    ("analyst_demo", "analyst@example.test", "Demo Analyst", "analyst"),
]


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD")
    if not password or len(password) < 12:
        raise SystemExit("Set DEMO_PASSWORD to a value at least 12 characters long.")
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        permissions = {}
        keys = sorted({key for role_keys in ROLES.values() for key in role_keys})
        for key in keys:
            permission = db.scalar(select(Permission).where(Permission.key == key))
            if permission is None:
                permission = Permission(key=key, description=key.replace(":", " ").replace("_", " ").title())
                db.add(permission)
            permissions[key] = permission
        db.flush()
        roles = {}
        for name, role_keys in ROLES.items():
            role = db.scalar(select(Role).where(Role.name == name))
            if role is None:
                role = Role(name=name, description=f"Demonstration {name} role")
                db.add(role)
            db.flush()
            roles[name] = role
            for key in role_keys:
                exists = db.scalar(select(RolePermission).where(RolePermission.role_id == role.id, RolePermission.permission_id == permissions[key].id))
                if exists is None:
                    db.add(RolePermission(role_id=role.id, permission_id=permissions[key].id))
        db.flush()
        for username, email, full_name, role_name in USERS:
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(username=username, email=email, full_name=full_name, password_hash=hash_password(password))
                db.add(user)
                db.flush()
            else:
                # Re-running the seed command intentionally rotates each demo account
                # to the operator-supplied DEMO_PASSWORD rather than preserving an
                # earlier test or local password hash.
                user.password_hash = hash_password(password)
            if db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == roles[role_name].id)) is None:
                db.add(UserRole(user_id=user.id, role_id=roles[role_name].id))
    print("Demo users and roles are ready. All demo accounts use DEMO_PASSWORD.")


if __name__ == "__main__":
    main()
