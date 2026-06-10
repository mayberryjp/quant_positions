"""Ledger repository – database access for position ledger entries."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text

from quant_positions.domain.accounting import apply_ledger_event
from quant_positions.domain.models import ALLOWED_EVENT_TYPES


@dataclass(frozen=True)
class LedgerImportParams:
    portfolio: str
    idempotency_key: str
    source: str
    ticker: str
    market: str
    locale: str
    event_type: str
    quantity_delta: Decimal
    occurred_at: datetime
    reason: str
    source_event_id: str | None = None
    price: Decimal | None = None
    fees: Decimal = Decimal("0")
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class LedgerListParams:
    portfolio: str | None = None
    portfolio_id: int | None = None
    ticker: str | None = None
    symbol_id: int | None = None
    event_type: str | None = None
    source: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    limit: int = 50
    offset: int = 0


def import_ledger_entry(params: LedgerImportParams) -> dict[str, Any]:
    """Import a position-changing event into the ledger.

    This is the core transactional write path. It:
    1. Validates the event type
    2. Resolves the portfolio (must exist)
    3. Checks idempotency (returns duplicate if key already used)
    4. Creates or finds the position row
    5. Applies accounting rules to update the position
    6. Inserts the immutable ledger entry
    All in a single transaction.
    """
    # Validate event type
    if params.event_type not in ALLOWED_EVENT_TYPES:
        return {"status": "rejected", "error": f"unsupported event_type: {params.event_type}"}

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            # Resolve portfolio
            portfolio_row = conn.execute(
                text("""
                    SELECT id FROM position_tracking.portfolios
                    WHERE name = :name
                """),
                {"name": params.portfolio},
            ).mappings().first()

            if portfolio_row is None:
                return {"status": "rejected", "error": f"portfolio not found: {params.portfolio}"}
            portfolio_id = int(portfolio_row["id"])

            # Check idempotency
            existing = conn.execute(
                text("""
                    SELECT id, portfolio_id, submitted_ticker, symbol_id,
                           position_id, quantity_delta
                    FROM position_tracking.position_ledger_entries
                    WHERE idempotency_key = :key
                """),
                {"key": params.idempotency_key},
            ).mappings().first()

            if existing is not None:
                return {
                    "status": "duplicate",
                    "ledger_entry_id": int(existing["id"]),
                    "portfolio": params.portfolio,
                    "submitted_ticker": existing["submitted_ticker"],
                    "symbol_id": int(existing["symbol_id"]) if existing["symbol_id"] else None,
                    "position_id": int(existing["position_id"]) if existing["position_id"] else None,
                    "quantity_delta": str(existing["quantity_delta"]),
                }

            # Find or create position
            position_row = conn.execute(
                text("""
                    SELECT id, quantity, average_cost, realized_pnl
                    FROM position_tracking.positions
                    WHERE portfolio_id = :portfolio_id
                      AND lower(submitted_ticker) = :ticker
                      AND market = :market
                      AND locale = :locale
                    LIMIT 1
                """),
                {
                    "portfolio_id": portfolio_id,
                    "ticker": params.ticker.strip().lower(),
                    "market": params.market,
                    "locale": params.locale,
                },
            ).mappings().first()

            if position_row is None:
                position_row = conn.execute(
                    text("""
                        INSERT INTO position_tracking.positions
                            (portfolio_id, symbol_id, submitted_ticker, market, locale,
                             quantity, average_cost, status)
                        VALUES (:portfolio_id, :symbol_id, :ticker, :market, :locale,
                                0, 0, 'open')
                        RETURNING id, quantity, average_cost, realized_pnl
                    """),
                    {
                        "portfolio_id": portfolio_id,
                        "symbol_id": None,  # symbol resolution deferred
                        "ticker": params.ticker,
                        "market": params.market,
                        "locale": params.locale,
                    },
                ).mappings().one()

            position_id = int(position_row["id"])
            current_qty = Decimal(str(position_row["quantity"]))
            current_avg = Decimal(str(position_row["average_cost"]))
            current_realized = Decimal(str(position_row["realized_pnl"]))

            # Apply accounting rules
            update = apply_ledger_event(
                current_quantity=current_qty,
                current_avg_cost=current_avg,
                quantity_delta=params.quantity_delta,
                price=params.price,
                fees=params.fees,
            )

            new_status = "open" if update.new_quantity != 0 else "closed"

            # Update position
            conn.execute(
                text("""
                    UPDATE position_tracking.positions
                    SET quantity = :quantity,
                        average_cost = :average_cost,
                        realized_pnl = :realized_pnl,
                        status = :status,
                        updated_at = now()
                    WHERE id = :id
                """),
                {
                    "quantity": str(update.new_quantity),
                    "average_cost": str(update.new_average_cost),
                    "realized_pnl": str(current_realized + update.realized_pnl_delta),
                    "status": new_status,
                    "id": position_id,
                },
            )

            # Insert ledger entry
            ledger_row = conn.execute(
                text("""
                    INSERT INTO position_tracking.position_ledger_entries
                        (portfolio_id, position_id, symbol_id, submitted_ticker,
                         market, locale, idempotency_key, source, source_event_id,
                         event_type, quantity_delta, price, fees, occurred_at,
                         reason, tags, metadata)
                    VALUES (:portfolio_id, :position_id, :symbol_id, :ticker,
                            :market, :locale, :idempotency_key, :source, :source_event_id,
                            :event_type, :quantity_delta, :price, :fees, :occurred_at,
                            :reason, :tags, :metadata)
                    RETURNING id
                """),
                {
                    "portfolio_id": portfolio_id,
                    "position_id": position_id,
                    "symbol_id": None,
                    "ticker": params.ticker,
                    "market": params.market,
                    "locale": params.locale,
                    "idempotency_key": params.idempotency_key,
                    "source": params.source,
                    "source_event_id": params.source_event_id,
                    "event_type": params.event_type,
                    "quantity_delta": str(params.quantity_delta),
                    "price": str(params.price) if params.price is not None else None,
                    "fees": str(params.fees),
                    "occurred_at": params.occurred_at,
                    "reason": params.reason,
                    "tags": json.dumps(params.tags or []),
                    "metadata": json.dumps(params.metadata or {}),
                },
            ).mappings().one()

            return {
                "status": "recorded",
                "ledger_entry_id": int(ledger_row["id"]),
                "portfolio": params.portfolio,
                "submitted_ticker": params.ticker,
                "symbol_id": None,
                "position_id": position_id,
                "quantity_delta": str(params.quantity_delta),
            }
    finally:
        engine.dispose()


def list_ledger_entries(params: LedgerListParams) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            where_parts, values = _build_ledger_where(params)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            values["limit"] = params.limit
            values["offset"] = params.offset

            rows = conn.execute(
                text(f"""
                    SELECT le.id, le.portfolio_id, le.position_id, le.symbol_id,
                           le.submitted_ticker, le.market, le.locale,
                           le.idempotency_key, le.source, le.source_event_id,
                           le.event_type, le.quantity_delta, le.price, le.fees,
                           le.occurred_at, le.reason, le.tags, le.metadata,
                           le.created_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.position_ledger_entries le
                    JOIN position_tracking.portfolios pf ON pf.id = le.portfolio_id
                    {where}
                    ORDER BY le.occurred_at DESC, le.id DESC
                    LIMIT :limit OFFSET :offset
                """),
                values,
            ).mappings().all()
    finally:
        engine.dispose()

    items = [_row_to_ledger_entry(r) for r in rows]
    return {"items": items, "limit": params.limit, "offset": params.offset, "count": len(items)}


def get_ledger_entry_by_id(ledger_entry_id: int) -> dict[str, Any] | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT le.id, le.portfolio_id, le.position_id, le.symbol_id,
                           le.submitted_ticker, le.market, le.locale,
                           le.idempotency_key, le.source, le.source_event_id,
                           le.event_type, le.quantity_delta, le.price, le.fees,
                           le.occurred_at, le.reason, le.tags, le.metadata,
                           le.created_at,
                           pf.name AS portfolio_name
                    FROM position_tracking.position_ledger_entries le
                    JOIN position_tracking.portfolios pf ON pf.id = le.portfolio_id
                    WHERE le.id = :id
                    LIMIT 1
                """),
                {"id": ledger_entry_id},
            ).mappings().first()
    finally:
        engine.dispose()

    if row is None:
        return None
    return _row_to_ledger_entry(row)


def _build_ledger_where(params: LedgerListParams) -> tuple[list[str], dict[str, Any]]:
    parts: list[str] = []
    values: dict[str, Any] = {}
    if params.portfolio is not None:
        parts.append("pf.name = :portfolio")
        values["portfolio"] = params.portfolio
    if params.portfolio_id is not None:
        parts.append("le.portfolio_id = :portfolio_id")
        values["portfolio_id"] = params.portfolio_id
    if params.ticker is not None:
        parts.append("lower(le.submitted_ticker) = :ticker")
        values["ticker"] = params.ticker.strip().lower()
    if params.symbol_id is not None:
        parts.append("le.symbol_id = :symbol_id")
        values["symbol_id"] = params.symbol_id
    if params.event_type is not None:
        parts.append("le.event_type = :event_type")
        values["event_type"] = params.event_type
    if params.source is not None:
        parts.append("le.source = :source")
        values["source"] = params.source
    if params.from_date is not None:
        parts.append("le.occurred_at >= :from_date")
        values["from_date"] = params.from_date
    if params.to_date is not None:
        parts.append("le.occurred_at <= :to_date")
        values["to_date"] = params.to_date
    return parts, values


def _row_to_ledger_entry(row: Any) -> dict[str, Any]:
    tags = row["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return {
        "id": int(row["id"]),
        "portfolio_id": int(row["portfolio_id"]),
        "portfolio_name": row["portfolio_name"],
        "position_id": int(row["position_id"]) if row["position_id"] else None,
        "symbol_id": int(row["symbol_id"]) if row["symbol_id"] else None,
        "submitted_ticker": row["submitted_ticker"],
        "market": row["market"],
        "locale": row["locale"],
        "idempotency_key": row["idempotency_key"],
        "source": row["source"],
        "source_event_id": row["source_event_id"],
        "event_type": row["event_type"],
        "quantity_delta": str(row["quantity_delta"]),
        "price": str(row["price"]) if row["price"] is not None else None,
        "fees": str(row["fees"]),
        "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
        "reason": row["reason"],
        "tags": tags,
        "metadata": meta,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
