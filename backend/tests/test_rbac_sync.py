from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.role_policy import ROLE_PERMISSIONS
from app.database.connection import Base
from app.database.models import (
    Dataset, DatasetGrant, DatasetMetadata, Permission, Role, RolePermission,
    User, UserRole,
)
from app.operations.routes import dashboard_summary
from scripts.sync_rbac import sync_role_permissions


LEGACY_ROLE_PERMISSIONS = {
    "administrator": {"audit:read", "budgets:read_all", "experiments:run", "queries:submit", "settings:manage", "users:manage"},
    "hr": {"budgets:read_own", "history:read_own", "queries:submit"},
    "doctor": {"budgets:read_own", "history:read_own", "queries:submit"},
    "researcher": {"budgets:read_own", "experiments:run", "history:read_own", "queries:submit"},
    "analyst": {"budgets:read_own", "history:read_own", "queries:submit"},
}


def test_rbac_sync_adds_missing_policy_permissions_idempotently_and_preserves_data():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory.begin() as db:
            role_objects = {name: Role(name=name, description=f"Existing {name}") for name in ROLE_PERMISSIONS}
            user = User(username="admin", email="admin@example.test", full_name="Demo Administrator", password_hash="do-not-change-this-hash")
            dataset = Dataset(name="preserve-me", description="existing dataset", is_active=True)
            db.add_all([*role_objects.values(), user, dataset])
            db.flush()
            db.add_all([
                UserRole(user_id=user.id, role_id=role_objects["administrator"].id),
                DatasetMetadata(dataset_id=dataset.id, source_type="synthetic", table_name="employees", record_count=5_000, owner_id=user.id),
                DatasetGrant(dataset_id=dataset.id, role_id=role_objects["researcher"].id),
            ])
            legacy_keys = sorted(set().union(*LEGACY_ROLE_PERMISSIONS.values()))
            permission_objects = {key: Permission(key=key, description="legacy") for key in legacy_keys}
            db.add_all(permission_objects.values())
            db.flush()
            for role_name, keys in LEGACY_ROLE_PERMISSIONS.items():
                db.add_all([RolePermission(role_id=role_objects[role_name].id, permission_id=permission_objects[key].id) for key in keys])
            db.flush()
            admin_id = user.id
            admin_role_id = role_objects["administrator"].id
            preserved_password_hash = user.password_hash
            db.commit()

        with factory.begin() as db:
            first = sync_role_permissions(db)
        assert first["permissions_added"] > 0
        assert first["role_permissions_added"] > 0

        with factory() as db:
            user = db.get(User, admin_id)
            assert user.password_hash == preserved_password_hash
            actual = {
                row[0] for row in db.execute(
                    select(Permission.key)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == admin_role_id)
                )
            }
            assert actual == set(ROLE_PERMISSIONS["administrator"])
            hr_role = db.scalar(select(Role).where(Role.name == "hr"))
            hr_actual = {
                row[0] for row in db.execute(
                    select(Permission.key)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == hr_role.id)
                )
            }
            assert hr_actual == set(ROLE_PERMISSIONS["hr"])
            assert "users:manage" not in hr_actual
            assert db.query(Dataset).filter_by(name="preserve-me").count() == 1
            assert db.query(DatasetMetadata).count() == 1
            assert db.query(DatasetGrant).count() == 1
            dashboard = dashboard_summary(days=7, user=user, db=db)
            assert dashboard["metrics"]["accessible_datasets"] == 0
            assert dashboard["metrics"]["total_requests"] == 0
            assert dashboard["recent_activity"] == []

        with factory.begin() as db:
            second = sync_role_permissions(db)
        assert second == {"permissions_added": 0, "roles_added": 0, "role_permissions_added": 0}
    finally:
        engine.dispose()
