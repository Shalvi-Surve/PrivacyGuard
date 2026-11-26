from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

import app.main as main


def test_health_reports_database_unavailable_without_failing_liveness(monkeypatch):
    def unavailable():
        raise OperationalError("SELECT 1", {}, RuntimeError("database down"))

    monkeypatch.setattr(main.engine, "connect", unavailable)
    response = main.health()

    assert response == {
        "status": "ok",
        "service": "adaptive-dp-middleware",
        "database": {"status": "unavailable"},
        "readiness": "degraded",
    }


def test_health_reports_database_available(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return 1

    monkeypatch.setattr(main.engine, "connect", lambda: Connection())
    response = main.health()

    assert response["status"] == "ok"
    assert response["database"] == {"status": "available"}
    assert response["readiness"] == "ready"


def test_development_schema_failure_does_not_stop_api_process(monkeypatch, caplog):
    def fail_create_all(**_kwargs):
        raise OperationalError("CREATE TABLE", {}, RuntimeError("database down"))

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(app_env="development"))
    monkeypatch.setattr(main.Base.metadata, "create_all", fail_create_all)

    main.initialize_development_schema()

    assert "database-backed operations are unavailable" in caplog.text
