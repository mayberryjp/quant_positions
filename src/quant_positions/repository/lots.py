"""Lots repository – database access for position lots."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class LotListParams:
    portfolio: str | None = None
    portfolio_id: int | None = None
    ticker: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0


def list_lots(params: LotListParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            where_parts, values = _build_lot_where(params)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            values["limit"] = params.limit
            values["offset"] = params.offset

            rows = conn.execute(
                text(f"""
                    SELECT l.id, l.position_id, l.portfolio_id, l.symbol_id,
                           l.submitted_ticker, l.lot_identifier, l.quantity,
                           l.cost_basis, l.acquired_at, l.closed_at,
                           l.status, l.metadata, l.created_at, l.updated_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.position_lots l
                    JOIN position_tracking.portfolios pf ON pf.id = l.portfolio_id
                    {where}
                    ORDER BY l.acquired_at ASC NULLS LAST, l.id ASC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_lot(r) for r in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def _build_lot_where(params: LotListParams) -> tuple[list[str], dict[str, Any]]:
    parts: list[str] = []
    values: dict[str, Any] = {}
    if params.portfolio is not None:
        parts.append("pf.name = :portfolio")
        values["portfolio"] = params.portfolio
    if params.portfolio_id is not None:
        parts.append("l.portfolio_id = :portfolio_id")
        values["portfolio_id"] = params.portfolio_id
    if params.ticker is not None:
        parts.append("lower(l.submitted_ticker) = :ticker")
        values["ticker"] = params.ticker.strip().lower()
    if params.status is not None:
        parts.append("l.status = :status")
        values["status"] = params.status
    return parts, values


def _row_to_lot(row: Any) -> dict[str, Any]:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {
        "id": int(row["id"]),
        "position_id": int(row["position_id"]),
        "portfolio_id": int(row["portfolio_id"]),
        "portfolio_name": row["portfolio_name"],
        "symbol_id": int(row["symbol_id"]) if row["symbol_id"] else None,
        "submitted_ticker": row["submitted_ticker"],
        "lot_identifier": row["lot_identifier"],
        "quantity": str(row["quantity"]),
        "cost_basis": str(row["cost_basis"]),
        "acquired_at": row["acquired_at"].isoformat() if row["acquired_at"] else None,
        "closed_at": row["closed_at"].isoformat() if row["closed_at"] else None,
        "status": row["status"],
        "metadata": meta,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
