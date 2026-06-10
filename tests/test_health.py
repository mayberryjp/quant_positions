"""Tests for health and readiness endpoints (Slice 7)."""
from __future__ import annotations

from quant_positions.api.testing import TestClient
from quant_positions.api.app import create_app
from quant_positions.api.readiness import ReadinessError, ReadinessStatus


def test_health_returns_ok_without_database_access():
    def fail_if_called():
        raise AssertionError("readiness check should not be called by /positions/health")

    client = TestClient(create_app(readiness_check=fail_if_called))
    resp = client.get("/positions/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "quant-positions-api"}


def test_ready_returns_ok_when_check_succeeds():
    client = TestClient(
        create_app(
            readiness_check=lambda: ReadinessStatus(
                database="ok",
                schema_version="0001_position_tracking",
                tables=8,
                open_positions=5,
                recent_ledger_entries=12,
                reconciliation_warnings=0,
                stale_workers=0,
            )
        )
    )
    resp = client.get("/positions/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["schema_version"] == "0001_position_tracking"
    assert body["tables"] == 8
    assert body["open_positions"] == 5
    assert body["recent_ledger_entries"] == 12
    assert body["reconciliation_warnings"] == 0
    assert body["stale_workers"] == 0


def test_ready_returns_503_when_check_fails():
    def fail_readiness():
        raise ReadinessError("schema_version=old expected=0001_position_tracking")

    client = TestClient(create_app(readiness_check=fail_readiness))
    resp = client.get("/positions/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "error"


def test_ready_error_redacts_database_url(monkeypatch):
    database_url = "postgresql+psycopg://user:super-secret@db.example.test:5432/quant"
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fail_readiness():
        raise RuntimeError(f"could not connect to {database_url}")

    client = TestClient(create_app(readiness_check=fail_readiness))
    resp = client.get("/positions/ready")
    assert resp.status_code == 503
    error = resp.json()["error"]
    assert "super-secret" not in error
    assert database_url not in error
    assert "user:***@db.example.test:5432/quant" in error


def test_readiness_status_includes_operational_counts():
    status = ReadinessStatus(
        database="ok",
        schema_version="0001_position_tracking",
        tables=8,
        open_positions=10,
        recent_ledger_entries=25,
        reconciliation_warnings=3,
        stale_workers=1,
    )
    j = status.as_json()
    assert j["open_positions"] == 10
    assert j["recent_ledger_entries"] == 25
    assert j["reconciliation_warnings"] == 3
    assert j["stale_workers"] == 1


def test_ready_not_ready_when_db_unavailable():
    def fail_readiness():
        raise ReadinessError("DATABASE_URL is not configured")

    client = TestClient(create_app(readiness_check=fail_readiness))
    resp = client.get("/positions/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_reconciliation_runs_route():
    from quant_positions.repository.reconciliation import ReconciliationRunListParams

    def fake_runs(params: ReconciliationRunListParams):
        return {
            "items": [
                {
                    "id": 1,
                    "status": "completed",
                    "positions_checked": 10,
                    "warnings_found": 2,
                    "started_at": "2026-06-09T12:00:00+00:00",
                    "completed_at": "2026-06-09T12:01:00+00:00",
                    "error_message": None,
                    "created_at": "2026-06-09T12:00:00+00:00",
                }
            ],
            "limit": 20,
            "offset": 0,
            "count": 1,
        }

    client = TestClient(create_app(reconciliation_run_list=fake_runs))
    resp = client.get("/reconciliation/runs")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["items"][0]["warnings_found"] == 2


def test_reconciliation_warnings_route():
    from quant_positions.repository.reconciliation import ReconciliationWarningListParams

    def fake_warnings(params: ReconciliationWarningListParams):
        return {
            "items": [
                {
                    "id": 1,
                    "run_id": 1,
                    "portfolio_id": 1,
                    "portfolio_name": "paper-main",
                    "position_id": 1,
                    "symbol_id": None,
                    "submitted_ticker": "AAPL",
                    "warning_type": "quantity_mismatch",
                    "expected_quantity": "10",
                    "actual_quantity": "15",
                    "detail": "Mismatch for AAPL",
                    "created_at": "2026-06-09T12:01:00+00:00",
                }
            ],
            "limit": 50,
            "offset": 0,
            "count": 1,
        }

    client = TestClient(create_app(reconciliation_warning_list=fake_warnings))
    resp = client.get("/reconciliation/warnings")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["items"][0]["warning_type"] == "quantity_mismatch"


def test_reconciliation_warnings_with_stale_heartbeat_visibility():
    """Readiness status should expose stale worker count."""
    status = ReadinessStatus(
        database="ok",
        schema_version="0001_position_tracking",
        tables=8,
        stale_workers=2,
    )
    assert status.as_json()["stale_workers"] == 2
