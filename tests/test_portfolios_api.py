"""Tests for portfolio API routes (Slice 2)."""
from __future__ import annotations

from quant_positions.api.testing import TestClient
from quant_positions.api.app import create_app
from quant_positions.repository.portfolios import PortfolioListParams, CreatePortfolioParams


SAMPLE_PORTFOLIO = {
    "id": 1,
    "name": "paper-main",
    "portfolio_type": "paper",
    "currency": "USD",
    "enabled": True,
    "metadata": {},
    "created_at": "2026-06-09T12:00:00+00:00",
    "updated_at": "2026-06-09T12:00:00+00:00",
}


def test_portfolios_list_returns_items():
    def fake_list(params: PortfolioListParams):
        assert params.limit == 50
        assert params.offset == 0
        return {"items": [SAMPLE_PORTFOLIO], "limit": 50, "offset": 0, "count": 1}

    client = TestClient(create_app(portfolio_list=fake_list))
    resp = client.get("/portfolios")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["name"] == "paper-main"


def test_portfolios_list_empty():
    def fake_list(params: PortfolioListParams):
        return {"items": [], "limit": 50, "offset": 0, "count": 0}

    client = TestClient(create_app(portfolio_list=fake_list))
    resp = client.get("/portfolios")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "limit": 50, "offset": 0, "count": 0}


def test_portfolios_list_pagination():
    seen = []

    def fake_list(params: PortfolioListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(portfolio_list=fake_list))
    resp = client.get("/portfolios?limit=10&offset=20")
    assert resp.status_code == 200
    assert seen[0].limit == 10
    assert seen[0].offset == 20


def test_portfolios_list_enabled_filter():
    seen = []

    def fake_list(params: PortfolioListParams):
        seen.append(params)
        return {"items": [], "limit": params.limit, "offset": params.offset, "count": 0}

    client = TestClient(create_app(portfolio_list=fake_list))
    resp = client.get("/portfolios?enabled=true")
    assert resp.status_code == 200
    assert seen[0].enabled is True


def test_create_portfolio_success():
    def fake_create(params: CreatePortfolioParams):
        assert params.name == "new-portfolio"
        assert params.portfolio_type == "paper"
        return {**SAMPLE_PORTFOLIO, "name": "new-portfolio"}

    client = TestClient(create_app(portfolio_create=fake_create))
    resp = client.post("/portfolios", json={"name": "new-portfolio"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "new-portfolio"


def test_create_portfolio_missing_name():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(portfolio_create=fail_if_called))
    resp = client.post("/portfolios", json={})
    assert resp.status_code == 422
    assert "name" in resp.json()["detail"]


def test_create_portfolio_invalid_type():
    def fail_if_called(params):
        raise AssertionError("should not be called")

    client = TestClient(create_app(portfolio_create=fail_if_called))
    resp = client.post("/portfolios", json={"name": "test", "portfolio_type": "invalid"})
    assert resp.status_code == 422
    assert "portfolio_type" in resp.json()["detail"]


def test_create_portfolio_valid_types():
    created = []

    def fake_create(params: CreatePortfolioParams):
        created.append(params)
        return {**SAMPLE_PORTFOLIO, "name": params.name, "portfolio_type": params.portfolio_type}

    client = TestClient(create_app(portfolio_create=fake_create))

    for pt in ("paper", "manual", "tracked"):
        resp = client.post("/portfolios", json={"name": f"test-{pt}", "portfolio_type": pt})
        assert resp.status_code == 201

    assert len(created) == 3


def test_delete_portfolio_success():
    def fake_delete(portfolio_id: int):
        assert portfolio_id == 1
        return SAMPLE_PORTFOLIO

    client = TestClient(create_app(portfolio_delete=fake_delete))
    resp = client.delete("/portfolios/1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "paper-main"


def test_delete_portfolio_not_found():
    def fake_delete(portfolio_id: int):
        return None

    client = TestClient(create_app(portfolio_delete=fake_delete))
    resp = client.delete("/portfolios/999")
    assert resp.status_code == 404


def test_delete_portfolio_invalid_id():
    def fail_if_called(portfolio_id):
        raise AssertionError("should not be called")

    client = TestClient(create_app(portfolio_delete=fail_if_called))
    resp = client.delete("/portfolios/abc")
    assert resp.status_code == 422


def test_delete_portfolio_in_use():
    from quant_positions.repository.portfolios import PortfolioInUseError

    def fake_delete(portfolio_id: int):
        raise PortfolioInUseError("portfolio has positions")

    client = TestClient(create_app(portfolio_delete=fake_delete))
    resp = client.delete("/portfolios/1")
    assert resp.status_code == 409
    assert "has positions" in resp.json()["error"]
