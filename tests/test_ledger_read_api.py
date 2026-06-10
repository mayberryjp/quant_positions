"""Tests for ledger read API and lot read API (Slice 6)."""
from __future__ import annotations

from quant_positions.api.testing import TestClient
from quant_positions.api.app import create_app
from quant_positions.repository.ledger import LedgerListParams
from quant_positions.repository.lots import LotListParams


SAMPLE_LEDGER_ENTRY = {
    "id": 1,
    "portfolio_id": 1,
    "portfolio_name": "paper-main",
    "position_id": 1,
    "symbol_id": None,
    "submitted_ticker": "AAPL",
    "market": "stocks",
    "locale": "us",
    "idempotency_key": "key-001",
    "source": "external",
    "source_event_id": "evt-001",
    "event_type": "external_position_change",
    "quantity_delta": "10",
    "price": "185.50",
    "fees": "1.25",
    "occurred_at": "2026-06-09T15:31:00+00:00",
    "reason": "Test import",
    "tags": ["imported"],
    "metadata": {},
    "created_at": "2026-06-09T15:31:00+00:00",
}

SAMPLE_LOT = {
    "id": 1,
    "position_id": 1,
    "portfolio_id": 1,
    "portfolio_name": "paper-main",
    "symbol_id": None,
    "submitted_ticker": "AAPL",
    "lot_identifier": "lot-001",
    "quantity": "10",
    "cost_basis": "185.50",
    "acquired_at": "2026-06-09T15:31:00+00:00",
    "closed_at": None,
    "status": "open",
    "metadata": {},
    "created_at": "2026-06-09T15:31:00+00:00",
    "updated_at": "2026-06-09T15:31:00+00:00",
}


# -- Ledger list tests --

def test_ledger_list_returns_items():
    def fake_list(params: LedgerListParams):
        return {"items": [SAMPLE_LEDGER_ENTRY], "limit": 50, "offset": 0, "count": 1}

    client = TestClient(create_app(ledger_list=fake_list))
    resp = client.get("/position-ledger")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["submitted_ticker"] == "AAPL"


def test_ledger_list_empty():
    def fake_list(params: LedgerListParams):
        return {"items": [], "limit": 50, "offset": 0, "count": 0}

    client = TestClient(create_app(ledger_list=fake_list))
    resp = client.get("/position-ledger")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_ledger_list_filters():
    seen = []

    def fake_list(params: LedgerListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(ledger_list=fake_list))
    resp = client.get(
        "/position-ledger?portfolio=paper-main&ticker=AAPL&event_type=manual_adjustment"
        "&source=operator&from_date=2026-06-01&to_date=2026-06-30"
    )
    assert resp.status_code == 200
    assert seen[0].portfolio == "paper-main"
    assert seen[0].ticker == "AAPL"
    assert seen[0].event_type == "manual_adjustment"
    assert seen[0].source == "operator"
    assert seen[0].from_date == "2026-06-01"
    assert seen[0].to_date == "2026-06-30"


def test_ledger_list_pagination():
    seen = []

    def fake_list(params: LedgerListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(ledger_list=fake_list))
    resp = client.get("/position-ledger?limit=10&offset=20")
    assert resp.status_code == 200
    assert seen[0].limit == 10
    assert seen[0].offset == 20


def test_ledger_detail():
    def fake_detail(ledger_entry_id: int):
        if ledger_entry_id == 1:
            return SAMPLE_LEDGER_ENTRY
        return None

    client = TestClient(create_app(ledger_detail=fake_detail))
    resp = client.get("/position-ledger/1")
    assert resp.status_code == 200
    assert resp.json()["id"] == 1


def test_ledger_detail_not_found():
    def fake_detail(ledger_entry_id: int):
        return None

    client = TestClient(create_app(ledger_detail=fake_detail))
    resp = client.get("/position-ledger/999")
    assert resp.status_code == 404


def test_ledger_detail_invalid_id():
    def fail_if_called(lid: int):
        raise AssertionError("should not be called")

    client = TestClient(create_app(ledger_detail=fail_if_called))
    resp = client.get("/position-ledger/abc")
    assert resp.status_code == 422


# -- Lot list tests --

def test_lots_list_returns_items():
    def fake_list(params: LotListParams):
        return {"items": [SAMPLE_LOT], "limit": 50, "offset": 0, "count": 1}

    client = TestClient(create_app(lot_list=fake_list))
    resp = client.get("/position-lots")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["lot_identifier"] == "lot-001"


def test_lots_list_empty():
    def fake_list(params: LotListParams):
        return {"items": [], "limit": 50, "offset": 0, "count": 0}

    client = TestClient(create_app(lot_list=fake_list))
    resp = client.get("/position-lots")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_lots_list_filters():
    seen = []

    def fake_list(params: LotListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(lot_list=fake_list))
    resp = client.get("/position-lots?portfolio=paper-main&ticker=AAPL&status=open")
    assert resp.status_code == 200
    assert seen[0].portfolio == "paper-main"
    assert seen[0].ticker == "AAPL"
    assert seen[0].status == "open"


def test_lots_list_pagination():
    seen = []

    def fake_list(params: LotListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(lot_list=fake_list))
    resp = client.get("/position-lots?limit=10&offset=5")
    assert resp.status_code == 200
    assert seen[0].limit == 10
    assert seen[0].offset == 5
