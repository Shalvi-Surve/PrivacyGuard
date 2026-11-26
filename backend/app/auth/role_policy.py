"""Source-of-truth role permissions used by provisioning and RBAC sync."""

ROLE_PERMISSIONS = {
    "administrator": [
        "users:manage", "settings:manage", "audit:read", "queries:submit",
        "queries:execute_protected", "datasets:read", "datasets:manage",
        "experiments:run", "budgets:read_all", "history:read_own",
        "history:read_all",
    ],
    "hr": ["queries:submit", "queries:execute_protected", "datasets:read", "history:read_own", "budgets:read_own"],
    "doctor": ["queries:submit", "queries:execute_protected", "datasets:read", "history:read_own", "budgets:read_own"],
    "researcher": ["queries:submit", "queries:execute_protected", "datasets:read", "history:read_own", "budgets:read_own", "experiments:run"],
    "analyst": ["queries:submit", "queries:execute_protected", "datasets:read", "history:read_own", "budgets:read_own"],
}
