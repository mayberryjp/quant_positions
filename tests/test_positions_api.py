"""Tests for position API routes (Slice 2)."""
from __future__ import annotations

from quant_positions.api.testing import TestClient
from quant_positions.api.app import create_app
from quant_positions.repository.positions import PositionListParams, PositionTickerLookupParams


SAMPLE_POSITION = {
    "id": 1,
    "portfolio_id": 1,
    "portfolio_name": "paper-main",
    "symbol_id": None,
    "submitted_ticker": "AAPL",
    "market": "stocks",
    "locale": "us",
    "quantity": "10",
    "average_cost": "185.50",
    "market_value": "0",
    "realized_pnl": "0",
    "unrealized_pnl": "0",
    "status": "open",
    "metadata": {},
    "created_at": "2026-06-09T12:00:00+00:00",
    "updated_at": "2026-06-09T12:00:00+00:00",
}


def test_positions_list_returns_items():
    def fake_list(params: PositionListParams):
        return {"items": [SAMPLE_POSITION], "limit": 100, "offset": 0, "count": 1}

    client = TestClient(create_app(position_list=fake_list))
    resp = client.get("/positions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["submitted_ticker"] == "AAPL"


def test_positions_list_empty():
    def fake_list(params: PositionListParams):
        return {"items": [], "limit": 100, "offset": 0, "count": 0}

    client = TestClient(create_app(position_list=fake_list))
    resp = client.get("/positions")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_positions_list_filters():
    seen = []

    def fake_list(params: PositionListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(position_list=fake_list))
    resp = client.get("/positions?portfolio=paper-main&status=open&ticker=AAPL&market=stocks&locale=us")
    assert resp.status_code == 200
    assert seen[0].portfolio == "paper-main"
    assert seen[0].status == "open"
    assert seen[0].ticker == "AAPL"
    assert seen[0].market == "stocks"
    assert seen[0].locale == "us"


def test_positions_list_pagination():
    seen = []

    def fake_list(params: PositionListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(position_list=fake_list))
    resp = client.get("/positions?limit=25&offset=50")
    assert resp.status_code == 200
    assert seen[0].limit == 25
    assert seen[0].offset == 50


def test_positions_list_pagination_max():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(position_list=fail_if_called))
    resp = client.get("/positions?limit=501")
    assert resp.status_code == 422


def test_position_detail():
    def fake_detail(position_id: int):
        if position_id == 1:
            return SAMPLE_POSITION
        return None

    client = TestClient(create_app(position_detail=fake_detail))
    resp = client.get("/positions/1")
    assert resp.status_code == 200
    assert resp.json()["id"] == 1


def test_position_detail_not_found():
    def fake_detail(position_id: int):
        return None

    client = TestClient(create_app(position_detail=fake_detail))
    resp = client.get("/positions/999")
    assert resp.status_code == 404


def test_position_detail_invalid_id():
    def fail_if_called(position_id: int):
        raise AssertionError("should not be called")

    client = TestClient(create_app(position_detail=fail_if_called))
    resp = client.get("/positions/abc")
    assert resp.status_code == 422


def test_position_by_ticker():
    def fake_by_ticker(params: PositionTickerLookupParams):
        if params.ticker == "AAPL" and params.portfolio == "paper-main":
            return SAMPLE_POSITION
        return None

    client = TestClient(create_app(position_by_ticker=fake_by_ticker))
    resp = client.get("/positions/by-ticker/AAPL?portfolio=paper-main")
    assert resp.status_code == 200
    assert resp.json()["submitted_ticker"] == "AAPL"


def test_position_by_ticker_not_found():
    def fake_by_ticker(params: PositionTickerLookupParams):
        return None

    client = TestClient(create_app(position_by_ticker=fake_by_ticker))
    resp = client.get("/positions/by-ticker/NOPE?portfolio=paper-main")
    assert resp.status_code == 404


def test_position_by_ticker_requires_portfolio():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(position_by_ticker=fail_if_called))
    resp = client.get("/positions/by-ticker/AAPL")
    assert resp.status_code == 422
    assert "portfolio" in resp.json()["detail"]
