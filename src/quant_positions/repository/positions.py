"""Position repository – database access for positions."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class PositionListParams:
    portfolio: str | None = None
    portfolio_id: int | None = None
    status: str | None = None
    ticker: str | None = None
    market: str | None = None
    locale: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class PositionTickerLookupParams:
    portfolio: str
    ticker: str
    market: str = "stocks"
    locale: str = "us"


def list_positions(params: PositionListParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            where_parts, values = _build_list_where(params)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            values["limit"] = params.limit
            values["offset"] = params.offset

            rows = conn.execute(
                text(f"""
                    SELECT p.id, p.portfolio_id, p.symbol_id, p.submitted_ticker,
                           p.market, p.locale, p.quantity, p.average_cost,
                           p.market_value, p.realized_pnl, p.unrealized_pnl,
                           p.status, p.metadata, p.created_at, p.updated_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.positions p
                    JOIN position_tracking.portfolios pf ON pf.id = p.portfolio_id
                    {where}
                    ORDER BY p.submitted_ticker ASC, p.id ASC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_position(r) for r in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def get_position_by_id(position_id: int) -> dict[str, Any] | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT p.id, p.portfolio_id, p.symbol_id, p.submitted_ticker,
                           p.market, p.locale, p.quantity, p.average_cost,
                           p.market_value, p.realized_pnl, p.unrealized_pnl,
                           p.status, p.metadata, p.created_at, p.updated_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.positions p
                    JOIN position_tracking.portfolios pf ON pf.id = p.portfolio_id
                    WHERE p.id = :position_id
                    LIMIT 1
                """),
                {"position_id": position_id},
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return _row_to_position(row)


def get_position_by_ticker(params: PositionTickerLookupParams) -> dict[str, Any] | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT p.id, p.portfolio_id, p.symbol_id, p.submitted_ticker,
                           p.market, p.locale, p.quantity, p.average_cost,
                           p.market_value, p.realized_pnl, p.unrealized_pnl,
                           p.status, p.metadata, p.created_at, p.updated_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.positions p
                    JOIN position_tracking.portfolios pf ON pf.id = p.portfolio_id
                    WHERE pf.name = :portfolio
                      AND lower(p.submitted_ticker) = :ticker
                      AND p.market = :market
                      AND p.locale = :locale
                    ORDER BY p.status ASC, p.id DESC
                    LIMIT 1
                """),
                {
                    "portfolio": params.portfolio,
                    "ticker": params.ticker.strip().lower(),
                    "market": params.market,
                    "locale": params.locale,
                },
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return _row_to_position(row)


def _build_list_where(params: PositionListParams) -> tuple[list[str], dict[str, Any]]:
    parts: list[str] = []
    values: dict[str, Any] = {}
    if params.portfolio is not None:
        parts.append("pf.name = :portfolio")
        values["portfolio"] = params.portfolio
    if params.portfolio_id is not None:
        parts.append("p.portfolio_id = :portfolio_id")
        values["portfolio_id"] = params.portfolio_id
    if params.status is not None:
        parts.append("p.status = :status")
        values["status"] = params.status
    if params.ticker is not None:
        parts.append("lower(p.submitted_ticker) = :ticker")
        values["ticker"] = params.ticker.strip().lower()
    if params.market is not None:
        parts.append("p.market = :market")
        values["market"] = params.market
    if params.locale is not None:
        parts.append("p.locale = :locale")
        values["locale"] = params.locale
    return parts, values


def _row_to_position(row: Any) -> dict[str, Any]:
    import json as _json
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = _json.loads(meta)
    return {
        "id": int(row["id"]),
        "portfolio_id": int(row["portfolio_id"]),
        "portfolio_name": row["portfolio_name"],
        "symbol_id": int(row["symbol_id"]) if row["symbol_id"] is not None else None,
        "submitted_ticker": row["submitted_ticker"],
        "market": row["market"],
        "locale": row["locale"],
        "quantity": str(row["quantity"]),
        "average_cost": str(row["average_cost"]),
        "market_value": str(row["market_value"]),
        "realized_pnl": str(row["realized_pnl"]),
        "unrealized_pnl": str(row["unrealized_pnl"]),
        "status": row["status"],
        "metadata": meta,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
