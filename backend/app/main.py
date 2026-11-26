import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.database.connection import Base, engine
from app.database import models  # noqa: F401 - registers models on metadata
from app.datasets.routes import router as dataset_router
from app.experiments.routes import router as experiments_router
from app.operations.routes import router as operations_router
from app.query.routes import router as query_router
from app.users.routes import router as users_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_development_schema()
    yield


app = FastAPI(
    title="Adaptive Differential Privacy Middleware",
    description="Research prototype API for privacy-aware aggregate query processing.",
    version="0.1.0",
    lifespan=lifespan,
)
logger = logging.getLogger("privacyguard.api")
settings = get_settings()
development_origins = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 5174, 5190)
]
configured_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
if "*" in configured_origins:
    raise RuntimeError("CORS_ALLOWED_ORIGINS must list explicit origins; wildcard CORS is not supported.")
allowed_origins = list(dict.fromkeys(configured_origins + (development_origins if settings.app_env == "development" else [])))
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.include_router(auth_router)
app.include_router(dataset_router)
app.include_router(experiments_router)
app.include_router(query_router)
app.include_router(operations_router)
app.include_router(users_router)


def initialize_development_schema() -> None:
    """Create local demo tables; production migrations will replace this path."""
    if get_settings().app_env == "development":
        try:
            Base.metadata.create_all(bind=engine)
            _upgrade_additive_columns()
        except SQLAlchemyError:
            logger.warning("Development schema initialization failed; API is live but database-backed operations are unavailable.")


def _upgrade_additive_columns() -> None:
    """Additive local schema updates for existing SQLite development databases."""
    additions = {
        "dataset_metadata": {
            "column_metadata": "JSON NOT NULL DEFAULT '[]'",
            "version": "INTEGER NOT NULL DEFAULT 1",
        },
        "protected_releases": {
            "cache_lookup_key": "VARCHAR(64)",
            "adjacency_model": "VARCHAR(40) NOT NULL DEFAULT 'add_remove_one_record'",
            "policy_version": "VARCHAR(40) NOT NULL DEFAULT 'protected-release-v2'",
            "mechanism": "VARCHAR(30) NOT NULL DEFAULT 'Laplace'",
            "clipping_bounds": "JSON NOT NULL DEFAULT '{}'",
            "dataset_version": "INTEGER NOT NULL DEFAULT 1",
            "authorization_scope_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        },
        "experiment_runs": {
            "owner_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        },
    }
    existing_tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        for table, columns in additions.items():
            if table not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing_columns:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
        if "protected_releases" in existing_tables:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_protected_release_dataset_lookup ON protected_releases(dataset_id, cache_lookup_key)"))
        if "experiment_runs" in existing_tables and "owner_user_id" in {column["name"] for column in inspect(connection).get_columns("experiment_runs")}:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_experiment_runs_owner_user_id ON experiment_runs(owner_user_id)"))


@app.get("/health", tags=["system"])
def health() -> dict[str, object]:
    """Report process liveness and database readiness separately without leaking errors."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status = "available"
    except SQLAlchemyError:
        database_status = "unavailable"
    return {
        "status": "ok",
        "service": "adaptive-dp-middleware",
        "database": {"status": database_status},
        "readiness": "ready" if database_status == "available" else "degraded",
    }
