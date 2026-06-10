"""Reconciliation repository – database access for reconciliation runs and warnings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class ReconciliationRunListParams:
    status: str | None = None
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class ReconciliationWarningListParams:
    run_id: int | None = None
    portfolio_id: int | None = None
    limit: int = 50
    offset: int = 0


def list_reconciliation_runs(params: ReconciliationRunListParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            where = ""
            values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
            if params.status is not None:
                where = "WHERE status = :status"
                values["status"] = params.status
            rows = conn.execute(
                text(f"""
                    SELECT id, status, positions_checked, warnings_found,
                           started_at, completed_at, error_message, created_at
                    FROM position_tracking.reconciliation_runs
                    {where}
                    ORDER BY started_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_run(r) for r in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def list_reconciliation_warnings(params: ReconciliationWarningListParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            where_parts: list[str] = []
            values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
            if params.run_id is not None:
                where_parts.append("w.run_id = :run_id")
                values["run_id"] = params.run_id
            if params.portfolio_id is not None:
                where_parts.append("w.portfolio_id = :portfolio_id")
                values["portfolio_id"] = params.portfolio_id
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            rows = conn.execute(
                text(f"""
                    SELECT w.id, w.run_id, w.portfolio_id, w.position_id,
                           w.symbol_id, w.submitted_ticker, w.warning_type,
                           w.expected_quantity, w.actual_quantity, w.detail,
                           w.created_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.reconciliation_warnings w
                    JOIN position_tracking.portfolios pf ON pf.id = w.portfolio_id
                    {where}
                    ORDER BY w.created_at DESC, w.id DESC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_warning(r) for r in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def _row_to_run(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "status": row["status"],
        "positions_checked": int(row["positions_checked"]),
        "warnings_found": int(row["warnings_found"]),
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "error_message": row["error_message"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _row_to_warning(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "run_id": int(row["run_id"]),
        "portfolio_id": int(row["portfolio_id"]),
        "portfolio_name": row["portfolio_name"],
        "position_id": int(row["position_id"]) if row["position_id"] else None,
        "symbol_id": int(row["symbol_id"]) if row["symbol_id"] else None,
        "submitted_ticker": row["submitted_ticker"],
        "warning_type": row["warning_type"],
        "expected_quantity": str(row["expected_quantity"]) if row["expected_quantity"] is not None else None,
        "actual_quantity": str(row["actual_quantity"]) if row["actual_quantity"] is not None else None,
        "detail": row["detail"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
