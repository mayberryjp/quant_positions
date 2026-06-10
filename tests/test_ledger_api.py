"""Tests for ledger import API (Slice 3)."""
from __future__ import annotations

from quant_positions.api.testing import TestClient
from quant_positions.api.app import create_app
from quant_positions.repository.ledger import LedgerImportParams


VALID_IMPORT_BODY = {
    "portfolio": "paper-main",
    "idempotency_key": "paper-main:external:AAPL:event-001",
    "source": "external-position-event",
    "source_event_id": "event-001",
    "ticker": "AAPL",
    "market": "stocks",
    "locale": "us",
    "event_type": "external_position_change",
    "quantity_delta": 10,
    "price": 185.50,
    "fees": 1.25,
    "occurred_at": "2026-06-09T15:31:00Z",
    "reason": "Imported from external position source",
    "tags": ["imported"],
    "metadata": {"external_system": "example"},
}


def test_ledger_import_valid():
    seen = []

    def fake_import(params: LedgerImportParams):
        seen.append(params)
        return {
            "status": "recorded",
            "ledger_entry_id": 123,
            "portfolio": params.portfolio,
            "submitted_ticker": params.ticker,
            "symbol_id": None,
            "position_id": 45,
            "quantity_delta": str(params.quantity_delta),
        }

    client = TestClient(create_app(ledger_import=fake_import))
    resp = client.post("/position-ledger/import", json=VALID_IMPORT_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "recorded"
    assert body["ledger_entry_id"] == 123
    assert len(seen) == 1
    assert seen[0].portfolio == "paper-main"
    assert seen[0].idempotency_key == "paper-main:external:AAPL:event-001"


def test_ledger_import_duplicate():
    def fake_import(params: LedgerImportParams):
        return {
            "status": "duplicate",
            "ledger_entry_id": 123,
            "portfolio": params.portfolio,
            "submitted_ticker": params.ticker,
            "symbol_id": None,
            "position_id": 45,
            "quantity_delta": str(params.quantity_delta),
        }

    client = TestClient(create_app(ledger_import=fake_import))
    resp = client.post("/position-ledger/import", json=VALID_IMPORT_BODY)
    assert resp.status_code == 200
    assert resp.json()["status"] == "duplicate"


def test_ledger_import_missing_fields():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))

    # Missing portfolio
    body = {**VALID_IMPORT_BODY}
    del body["portfolio"]
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "portfolio" in resp.json()["detail"]


def test_ledger_import_missing_idempotency_key():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY}
    del body["idempotency_key"]
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "idempotency_key" in resp.json()["detail"]


def test_ledger_import_missing_reason():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY}
    del body["reason"]
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "reason" in resp.json()["detail"]


def test_ledger_import_invalid_event_type():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "event_type": "bogus_event"}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "event_type" in resp.json()["detail"]


def test_ledger_import_missing_quantity_delta():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY}
    del body["quantity_delta"]
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "quantity_delta" in resp.json()["detail"]


def test_ledger_import_invalid_quantity_delta():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "quantity_delta": "not-a-number"}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "quantity_delta" in resp.json()["detail"]


def test_ledger_import_negative_price():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "price": -10}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "price" in resp.json()["detail"]


def test_ledger_import_invalid_price():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "price": "abc"}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "price" in resp.json()["detail"]


def test_ledger_import_negative_fees():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "fees": -5}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "fees" in resp.json()["detail"]


def test_ledger_import_invalid_timestamp():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "occurred_at": "not-a-date"}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "occurred_at" in resp.json()["detail"]


def test_ledger_import_rejected_event_type():
    def fake_import(params: LedgerImportParams):
        return {"status": "rejected", "error": f"unsupported event_type: {params.event_type}"}

    client = TestClient(create_app(ledger_import=fake_import))
    body = {**VALID_IMPORT_BODY, "event_type": "external_position_change"}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422 or resp.json()["status"] == "rejected"


def test_ledger_import_empty_body():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    resp = client.post("/position-ledger/import", json={})
    assert resp.status_code == 422


def test_ledger_import_no_body():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    resp = client.post("/position-ledger/import", json=None)
    assert resp.status_code == 422


def test_ledger_import_manual_adjustment():
    seen = []

    def fake_import(params: LedgerImportParams):
        seen.append(params)
        return {
            "status": "recorded",
            "ledger_entry_id": 124,
            "portfolio": params.portfolio,
            "submitted_ticker": params.ticker,
            "symbol_id": None,
            "position_id": 45,
            "quantity_delta": str(params.quantity_delta),
        }

    client = TestClient(create_app(ledger_import=fake_import))
    body = {
        "portfolio": "paper-main",
        "idempotency_key": "paper-main:manual:AAPL:adjustment-001",
        "source": "operator",
        "ticker": "AAPL",
        "market": "stocks",
        "locale": "us",
        "event_type": "manual_adjustment",
        "quantity_delta": -2,
        "occurred_at": "2026-06-09T16:00:00Z",
        "reason": "Manual correction after position review",
    }
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 201
    assert seen[0].event_type == "manual_adjustment"
    assert str(seen[0].quantity_delta) == "-2"


def test_ledger_import_tags_validation():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "tags": "not-a-list"}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "tags" in resp.json()["detail"]


def test_ledger_import_too_many_tags():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_import=fail_if_called))
    body = {**VALID_IMPORT_BODY, "tags": [f"tag-{i}" for i in range(25)]}
    resp = client.post("/position-ledger/import", json=body)
    assert resp.status_code == 422
    assert "tags" in resp.json()["detail"]
