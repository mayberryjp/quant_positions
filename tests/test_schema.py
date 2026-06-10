"""Tests for schema contract and domain models."""
from __future__ import annotations

from quant_positions.domain.models import (
    ALLOWED_EVENT_TYPES,
    Portfolio,
    Position,
    PositionLot,
    LedgerEntry,
    ReconciliationRun,
    ReconciliationWarning,
    WorkerHeartbeat,
)


def test_allowed_event_types_is_frozen():
    assert isinstance(ALLOWED_EVENT_TYPES, frozenset)
    assert "external_position_change" in ALLOWED_EVENT_TYPES
    assert "manual_adjustment" in ALLOWED_EVENT_TYPES
    assert "transfer_in" in ALLOWED_EVENT_TYPES
    assert "transfer_out" in ALLOWED_EVENT_TYPES
    assert "stock_split" in ALLOWED_EVENT_TYPES
    assert "fee" in ALLOWED_EVENT_TYPES
    assert "correction" in ALLOWED_EVENT_TYPES
    assert "opening_balance" in ALLOWED_EVENT_TYPES
    assert len(ALLOWED_EVENT_TYPES) == 8


def test_portfolio_dataclass_defaults():
    p = Portfolio(id=1, name="test")
    assert p.portfolio_type == "paper"
    assert p.currency == "USD"
    assert p.enabled is True
    assert p.metadata == {}


def test_position_dataclass_defaults():
    from decimal import Decimal
    pos = Position(id=1, portfolio_id=1, symbol_id=None, submitted_ticker="AAPL")
    assert pos.quantity == Decimal("0")
    assert pos.average_cost == Decimal("0")
    assert pos.status == "open"


def test_position_lot_dataclass_defaults():
    lot = PositionLot(
        id=1, position_id=1, portfolio_id=1, symbol_id=None, submitted_ticker="AAPL"
    )
    assert lot.status == "open"
    assert lot.lot_identifier is None


def test_position_lot_uniqueness_is_by_position_and_lot_identifier():
    """Lot identity should be (position_id, lot_identifier) per schema."""
    lot1 = PositionLot(
        id=1, position_id=1, portfolio_id=1, symbol_id=None,
        submitted_ticker="AAPL", lot_identifier="lot-001"
    )
    lot2 = PositionLot(
        id=2, position_id=1, portfolio_id=1, symbol_id=None,
        submitted_ticker="AAPL", lot_identifier="lot-002"
    )
    assert lot1.lot_identifier != lot2.lot_identifier


def test_ledger_entry_is_frozen():
    entry = LedgerEntry(
        id=1, portfolio_id=1, position_id=1, symbol_id=None,
        submitted_ticker="AAPL", idempotency_key="key-1",
        source="test", event_type="manual_adjustment", reason="test",
    )
    try:
        entry.id = 2  # type: ignore[misc]
        assert False, "should be frozen"
    except AttributeError:
        pass


def test_ledger_entry_preserves_submitted_ticker_and_symbol_id():
    entry = LedgerEntry(
        id=1, portfolio_id=1, position_id=1, symbol_id=42,
        submitted_ticker="AAPL",
    )
    assert entry.submitted_ticker == "AAPL"
    assert entry.symbol_id == 42


def test_reconciliation_run_defaults():
    run = ReconciliationRun(id=1)
    assert run.status == "running"
    assert run.positions_checked == 0


def test_reconciliation_warning_dataclass():
    w = ReconciliationWarning(
        id=1, run_id=1, portfolio_id=1, position_id=1,
        symbol_id=None, submitted_ticker="AAPL",
        warning_type="quantity_mismatch",
    )
    assert w.warning_type == "quantity_mismatch"


def test_worker_heartbeat_defaults():
    hb = WorkerHeartbeat(worker_name="test-worker")
    assert hb.status == "alive"


def test_migration_revision_constant():
    from quant_positions.api.readiness import EXPECTED_SCHEMA_VERSION, EXPECTED_TABLES
    assert EXPECTED_SCHEMA_VERSION == "0001_position_tracking"
    assert len(EXPECTED_TABLES) == 8
    assert "portfolios" in EXPECTED_TABLES
    assert "positions" in EXPECTED_TABLES
    assert "position_lots" in EXPECTED_TABLES
    assert "position_ledger_entries" in EXPECTED_TABLES
    assert "position_snapshots" in EXPECTED_TABLES
    assert "reconciliation_runs" in EXPECTED_TABLES
    assert "reconciliation_warnings" in EXPECTED_TABLES
    assert "worker_heartbeats" in EXPECTED_TABLES
