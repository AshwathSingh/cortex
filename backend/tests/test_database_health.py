from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.postgres import get_session
from app.main import app


class FakeSession:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))
        if self.error:
            raise self.error


def test_database_health_executes_select_one():
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).get("/api/health/database")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "postgres"}
    assert session.statements == ["SELECT 1"]


def test_database_health_returns_503_when_postgres_is_unavailable():
    error = OperationalError("SELECT 1", {}, Exception("connection failed"))
    app.dependency_overrides[get_session] = lambda: FakeSession(error)
    try:
        response = TestClient(app).get("/api/health/database")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Postgres unavailable"}
