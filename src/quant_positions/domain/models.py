"""Domain models for position tracking.

Schema Concepts
===============

Portfolio / Tracking Account
    A logical container for positions. Examples: paper portfolio, manual account,
    externally managed account. Has a name, type, currency, and enabled flag.

Position (Current Aggregate)
    The system's current holding state for a normalized symbol in a named
    portfolio. Tracks aggregate quantity, average cost, market value placeholder,
    and realized/unrealized PnL placeholders. A position is uniquely identified
    by (portfolio_id, submitted_ticker, market, locale).

Position Lot
    An optional cost-basis record preserving acquisition-level accounting detail.
    Lots are tracked using FIFO ordering by default. Each lot has its own
    quantity and cost basis.

Position Ledger Entry
    An immutable, append-only accounting record that changes or explains position
    state. Examples: external position changes, manual adjustments, splits,
    transfers, corrections, fees, and opening-balance imports. Duplicate-safe
    submission is enforced through unique idempotency keys.

Position Snapshot
    An optional point-in-time record of position state, used for reconciliation
    and history.

Reconciliation Run / Warning
    Operational check that compares current aggregate positions against
    ledger-derived positions and records mismatches for review.

Worker Heartbeat
    Operational visibility row for reconciliation workers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


# -- Allowed ledger event types --
ALLOWED_EVENT_TYPES = frozenset((
    "external_position_change",
    "manual_adjustment",
    "transfer_in",
    "transfer_out",
    "stock_split",
    "fee",
    "correction",
    "opening_balance",
))


@dataclass(frozen=True)
class Portfolio:
    id: int
    name: str
    portfolio_type: str = "paper"
    currency: str = "USD"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Position:
    id: int
    portfolio_id: int
    symbol_id: int | None
    submitted_ticker: str
    market: str = "stocks"
    locale: str = "us"
    quantity: Decimal = Decimal("0")
    average_cost: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PositionLot:
    id: int
    position_id: int
    portfolio_id: int
    symbol_id: int | None
    submitted_ticker: str
    lot_identifier: str | None = None
    quantity: Decimal = Decimal("0")
    cost_basis: Decimal = Decimal("0")
    acquired_at: datetime | None = None
    closed_at: datetime | None = None
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class LedgerEntry:
    id: int
    portfolio_id: int
    position_id: int | None
    symbol_id: int | None
    submitted_ticker: str
    market: str = "stocks"
    locale: str = "us"
    idempotency_key: str = ""
    source: str = ""
    source_event_id: str | None = None
    event_type: str = ""
    quantity_delta: Decimal = Decimal("0")
    price: Decimal | None = None
    fees: Decimal = Decimal("0")
    occurred_at: datetime | None = None
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class ReconciliationRun:
    id: int
    status: str = "running"
    positions_checked: int = 0
    warnings_found: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ReconciliationWarning:
    id: int
    run_id: int
    portfolio_id: int
    position_id: int | None
    symbol_id: int | None
    submitted_ticker: str
    warning_type: str
    expected_quantity: Decimal | None = None
    actual_quantity: Decimal | None = None
    detail: str | None = None


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_name: str
    last_heartbeat: datetime | None = None
    status: str = "alive"
    metadata: dict[str, Any] = field(default_factory=dict)
