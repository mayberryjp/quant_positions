"""Portfolio repository – database access for portfolios."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class CreatePortfolioParams:
    name: str
    portfolio_type: str = "paper"
    currency: str = "USD"
    enabled: bool = True
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class PortfolioListParams:
    enabled: bool | None = None
    limit: int = 50
    offset: int = 0


def list_portfolios(params: PortfolioListParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            where = ""
            values: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
            if params.enabled is not None:
                where = "WHERE enabled = :enabled"
                values["enabled"] = params.enabled
            rows = conn.execute(
                text(f"""
                    SELECT id, name, portfolio_type, currency, enabled,
                           metadata, created_at, updated_at
                    FROM position_tracking.portfolios
                    {where}
                    ORDER BY name ASC, id ASC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_portfolio(r) for r in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def create_portfolio(params: CreatePortfolioParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO position_tracking.portfolios (name, portfolio_type, currency, enabled, metadata)
                    VALUES (:name, :portfolio_type, :currency, :enabled, :metadata)
                    RETURNING id, name, portfolio_type, currency, enabled, metadata, created_at, updated_at
                """),
                {
                    "name": params.name,
                    "portfolio_type": params.portfolio_type,
                    "currency": params.currency,
                    "enabled": params.enabled,
                    "metadata": json.dumps(params.metadata or {}),
                },
            ).mappings().one()
    finally:
        engine.dispose()

    return _row_to_portfolio(row)


def get_portfolio_by_name(name: str) -> dict[str, Any] | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, name, portfolio_type, currency, enabled,
                           metadata, created_at, updated_at
                    FROM position_tracking.portfolios
                    WHERE name = :name
                    LIMIT 1
                """),
                {"name": name},
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return _row_to_portfolio(row)


class PortfolioInUseError(Exception):
    """Raised when a portfolio cannot be deleted because it has related records."""


def delete_portfolio(portfolio_id: int) -> dict[str, Any] | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT id, name, portfolio_type, currency, enabled,
                           metadata, created_at, updated_at
                    FROM position_tracking.portfolios
                    WHERE id = :id
                """),
                {"id": portfolio_id},
            ).mappings().first()

            if row is None:
                return None

            has_positions = conn.execute(
                text("SELECT 1 FROM position_tracking.positions WHERE portfolio_id = :id LIMIT 1"),
                {"id": portfolio_id},
            ).first()
            if has_positions:
                raise PortfolioInUseError("portfolio has positions")

            conn.execute(
                text("DELETE FROM position_tracking.portfolios WHERE id = :id"),
                {"id": portfolio_id},
            )

            return _row_to_portfolio(row)
    finally:
        engine.dispose()


def _row_to_portfolio(row: Any) -> dict[str, Any]:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "portfolio_type": row["portfolio_type"],
        "currency": row["currency"],
        "enabled": bool(row["enabled"]),
        "metadata": meta,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
