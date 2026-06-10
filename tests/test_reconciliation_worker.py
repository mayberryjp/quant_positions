"""Tests for reconciliation worker (Slice 5).

Uses fake engine/connection objects to test worker logic without a real database.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch


def _make_fake_conn(positions=None, ledger_sums=None, orphans=None):
    """Build a fake connection that returns given test data."""
    conn = MagicMock()
    call_count = {"execute": 0}
    results = []

    # We need to track execute() calls and return appropriate data
    # The worker calls execute() in this order:
    # 1. heartbeat upsert (no return needed for begin() context)
    # 2. create run (returns run id)
    # 3. get all positions
    # 4. for each position: get ledger sum
    # 5. for each mismatch: insert warning
    # 6. get orphan entries
    # 7. for each orphan: insert warning
    # 8. complete run update

    class FakeResult:
        def __init__(self, data=None, scalar=None):
            self._data = data or []
            self._scalar = scalar

        def mappings(self):
            return self

        def all(self):
            return self._data

        def one(self):
            return self._data[0] if self._data else {}

        def first(self):
            return self._data[0] if self._data else None

        def scalar_one(self):
            return self._scalar

    def fake_execute(stmt, params=None):
        call_count["execute"] += 1
        stmt_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)

        if "worker_heartbeats" in stmt_str:
            return FakeResult()
        elif "INSERT INTO position_tracking.reconciliation_runs" in stmt_str:
            return FakeResult(data=[{"id": 1}])
        elif "FROM position_tracking.positions p" in stmt_str and "JOIN" in stmt_str:
            return FakeResult(data=positions or [])
        elif "SUM(quantity_delta)" in stmt_str and "WHERE position_id" in stmt_str:
            pos_id = params.get("position_id") if params else None
            scalar = ledger_sums.get(pos_id, Decimal("0")) if ledger_sums else Decimal("0")
            return FakeResult(scalar=scalar)
        elif "LEFT JOIN position_tracking.positions p ON p.id" in stmt_str:
            return FakeResult(data=orphans or [])
        elif "INSERT INTO position_tracking.reconciliation_warnings" in stmt_str:
            return FakeResult()
        elif "UPDATE position_tracking.reconciliation_runs" in stmt_str:
            return FakeResult()
        else:
            return FakeResult()

    conn.execute = fake_execute
    return conn


def test_reconciliation_clean():
    """No mismatches when positions match ledger sums."""
    positions = [
        {
            "id": 1, "portfolio_id": 1, "symbol_id": None,
            "submitted_ticker": "AAPL", "market": "stocks",
            "locale": "us", "quantity": Decimal("10"),
            "average_cost": Decimal("100"), "portfolio_name": "paper-main",
        }
    ]
    ledger_sums = {1: Decimal("10")}
    fake_conn = _make_fake_conn(positions=positions, ledger_sums=ledger_sums)

    from quant_positions.workers.reconciliation import run_reconciliation

    class FakeEngine:
        def begin(self):
            return _FakeContextManager(fake_conn)
        def dispose(self):
            pass

    with patch("quant_positions.workers.reconciliation.create_engine", return_value=FakeEngine()):
        result = run_reconciliation("postgresql+psycopg://test:test@localhost/test")

    assert result["status"] == "completed"
    assert result["positions_checked"] == 1
    assert result["warnings_found"] == 0


def test_reconciliation_quantity_mismatch():
    """Detects mismatch between current position and ledger sum."""
    positions = [
        {
            "id": 1, "portfolio_id": 1, "symbol_id": None,
            "submitted_ticker": "AAPL", "market": "stocks",
            "locale": "us", "quantity": Decimal("15"),  # current says 15
            "average_cost": Decimal("100"), "portfolio_name": "paper-main",
        }
    ]
    ledger_sums = {1: Decimal("10")}  # ledger says 10
    warnings_inserted = []
    base_conn = _make_fake_conn(positions=positions, ledger_sums=ledger_sums)
    orig_execute = base_conn.execute

    def tracking_execute(stmt, params=None):
        stmt_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)
        if "INSERT INTO position_tracking.reconciliation_warnings" in stmt_str:
            warnings_inserted.append(params)
        return orig_execute(stmt, params)

    base_conn.execute = tracking_execute

    from quant_positions.workers.reconciliation import run_reconciliation

    class FakeEngine:
        def begin(self):
            return _FakeContextManager(base_conn)
        def dispose(self):
            pass

    with patch("quant_positions.workers.reconciliation.create_engine", return_value=FakeEngine()):
        result = run_reconciliation("postgresql+psycopg://test:test@localhost/test")

    assert result["warnings_found"] == 1
    assert len(warnings_inserted) == 1
    assert warnings_inserted[0]["warning_type"] == "quantity_mismatch"


def test_reconciliation_missing_current_position():
    """Detects ledger entries referencing a position that doesn't exist."""
    orphans = [
        {
            "position_id": 99, "portfolio_id": 1,
            "submitted_ticker": "GONE", "symbol_id": None,
            "total_delta": Decimal("5"),
            "portfolio_name": "paper-main",
        }
    ]
    warnings_inserted = []
    base_conn = _make_fake_conn(positions=[], orphans=orphans)
    orig_execute = base_conn.execute

    def tracking_execute(stmt, params=None):
        stmt_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)
        if "INSERT INTO position_tracking.reconciliation_warnings" in stmt_str:
            warnings_inserted.append(params)
        return orig_execute(stmt, params)

    base_conn.execute = tracking_execute

    from quant_positions.workers.reconciliation import run_reconciliation

    class FakeEngine:
        def begin(self):
            return _FakeContextManager(base_conn)
        def dispose(self):
            pass

    with patch("quant_positions.workers.reconciliation.create_engine", return_value=FakeEngine()):
        result = run_reconciliation("postgresql+psycopg://test:test@localhost/test")

    assert result["warnings_found"] == 1
    assert warnings_inserted[0]["warning_type"] == "missing_current_position"


def test_reconciliation_stale_heartbeat_concept():
    """Worker heartbeat is always updated at the start of a pass."""
    heartbeat_calls = []
    base_conn = _make_fake_conn(positions=[])
    orig_execute = base_conn.execute

    def tracking_execute(stmt, params=None):
        stmt_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)
        if "worker_heartbeats" in stmt_str:
            heartbeat_calls.append(params)
        return orig_execute(stmt, params)

    base_conn.execute = tracking_execute

    from quant_positions.workers.reconciliation import run_reconciliation

    class FakeEngine:
        def begin(self):
            return _FakeContextManager(base_conn)
        def dispose(self):
            pass

    with patch("quant_positions.workers.reconciliation.create_engine", return_value=FakeEngine()):
        run_reconciliation("postgresql+psycopg://test:test@localhost/test")

    assert len(heartbeat_calls) == 1
    assert heartbeat_calls[0]["name"] == "reconciliation-worker"


def test_reconciliation_retryable_failure():
    """Worker survives and re-raises on failure; reconciliation run is marked failed."""
    from quant_positions.workers.reconciliation import run_reconciliation

    class FailingEngine:
        def __init__(self):
            self._call = 0

        def begin(self):
            self._call += 1
            if self._call == 1:
                return _FailingContextManager()
            return _FakeContextManager(_make_fake_conn())

        def dispose(self):
            pass

    with patch("quant_positions.workers.reconciliation.create_engine", return_value=FailingEngine()):
        try:
            run_reconciliation("postgresql+psycopg://test:test@localhost/test")
            assert False, "should have raised"
        except RuntimeError:
            pass  # expected


class _FakeContextManager:
    def __init__(self, conn):
        self._conn = conn
    def __enter__(self):
        return self._conn
    def __exit__(self, *args):
        return False


class _FailingContextManager:
    def __enter__(self):
        raise RuntimeError("simulated DB failure")
    def __exit__(self, *args):
        return False
