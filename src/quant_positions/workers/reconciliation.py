"""Reconciliation worker.

Runs continuously under supervisor. Derives expected positions from ledger
entries and compares them with current positions. Mismatches are recorded as
reconciliation warnings.

Local run (single pass):
    python -m quant_positions.workers.reconciliation --once

Container run (continuous, managed by supervisor):
    python -m quant_positions.workers.reconciliation --schedule 300
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text

WORKER_NAME = "reconciliation-worker"
log = logging.getLogger(WORKER_NAME)


def run_reconciliation(database_url: str | None = None) -> dict[str, Any]:
    """Execute one reconciliation pass. Returns summary dict."""
    resolved_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_url:
        raise RuntimeError("DATABASE_URL is not configured")

    engine = create_engine(resolved_url, pool_pre_ping=True)
    warnings_found = 0
    positions_checked = 0

    try:
        with engine.begin() as conn:
            # Record heartbeat
            conn.execute(
                text("""
                    INSERT INTO position_tracking.worker_heartbeats (worker_name, last_heartbeat, status)
                    VALUES (:name, now(), 'alive')
                    ON CONFLICT (worker_name) DO UPDATE
                    SET last_heartbeat = now(), status = 'alive'
                """),
                {"name": WORKER_NAME},
            )

            # Create reconciliation run
            run_row = conn.execute(
                text("""
                    INSERT INTO position_tracking.reconciliation_runs (status, started_at)
                    VALUES ('running', now())
                    RETURNING id
                """)
            ).mappings().one()
            run_id = int(run_row["id"])

            # Get all current positions
            positions = conn.execute(
                text("""
                    SELECT p.id, p.portfolio_id, p.symbol_id, p.submitted_ticker,
                           p.market, p.locale, p.quantity, p.average_cost,
                           pf.name AS portfolio_name
                    FROM position_tracking.positions p
                    JOIN position_tracking.portfolios pf ON pf.id = p.portfolio_id
                    ORDER BY p.id
                """)
            ).mappings().all()

            for pos in positions:
                positions_checked += 1
                position_id = int(pos["id"])
                portfolio_id = int(pos["portfolio_id"])
                current_qty = Decimal(str(pos["quantity"]))

                # Derive expected quantity from ledger entries
                ledger_sum = conn.execute(
                    text("""
                        SELECT COALESCE(SUM(quantity_delta), 0) AS total_delta
                        FROM position_tracking.position_ledger_entries
                        WHERE position_id = :position_id
                    """),
                    {"position_id": position_id},
                ).scalar_one()
                expected_qty = Decimal(str(ledger_sum))

                if current_qty != expected_qty:
                    warnings_found += 1
                    conn.execute(
                        text("""
                            INSERT INTO position_tracking.reconciliation_warnings
                                (run_id, portfolio_id, position_id, symbol_id,
                                 submitted_ticker, warning_type,
                                 expected_quantity, actual_quantity, detail)
                            VALUES (:run_id, :portfolio_id, :position_id, :symbol_id,
                                    :ticker, :warning_type,
                                    :expected, :actual, :detail)
                        """),
                        {
                            "run_id": run_id,
                            "portfolio_id": portfolio_id,
                            "position_id": position_id,
                            "symbol_id": pos["symbol_id"],
                            "ticker": pos["submitted_ticker"],
                            "warning_type": "quantity_mismatch",
                            "expected": str(expected_qty),
                            "actual": str(current_qty),
                            "detail": (
                                f"Position {position_id} ({pos['submitted_ticker']}) in "
                                f"portfolio {pos['portfolio_name']}: "
                                f"ledger-derived qty={expected_qty}, "
                                f"current qty={current_qty}"
                            ),
                        },
                    )

            # Check for ledger entries with no current position
            orphan_entries = conn.execute(
                text("""
                    SELECT le.position_id, le.portfolio_id, le.submitted_ticker,
                           le.symbol_id,
                           COALESCE(SUM(le.quantity_delta), 0) AS total_delta,
                           pf.name AS portfolio_name
                    FROM position_tracking.position_ledger_entries le
                    JOIN position_tracking.portfolios pf ON pf.id = le.portfolio_id
                    LEFT JOIN position_tracking.positions p ON p.id = le.position_id
                    WHERE p.id IS NULL AND le.position_id IS NOT NULL
                    GROUP BY le.position_id, le.portfolio_id, le.submitted_ticker,
                             le.symbol_id, pf.name
                """)
            ).mappings().all()

            for orphan in orphan_entries:
                warnings_found += 1
                conn.execute(
                    text("""
                        INSERT INTO position_tracking.reconciliation_warnings
                            (run_id, portfolio_id, position_id, symbol_id,
                             submitted_ticker, warning_type,
                             expected_quantity, actual_quantity, detail)
                        VALUES (:run_id, :portfolio_id, :position_id, :symbol_id,
                                :ticker, :warning_type,
                                :expected, :actual, :detail)
                    """),
                    {
                        "run_id": run_id,
                        "portfolio_id": int(orphan["portfolio_id"]),
                        "position_id": orphan["position_id"],
                        "symbol_id": orphan["symbol_id"],
                        "ticker": orphan["submitted_ticker"],
                        "warning_type": "missing_current_position",
                        "expected": str(orphan["total_delta"]),
                        "actual": None,
                        "detail": (
                            f"Ledger entries reference position_id={orphan['position_id']} "
                            f"({orphan['submitted_ticker']}) in portfolio "
                            f"{orphan['portfolio_name']}, but no current position exists"
                        ),
                    },
                )

            # Complete the run
            conn.execute(
                text("""
                    UPDATE position_tracking.reconciliation_runs
                    SET status = 'completed',
                        positions_checked = :checked,
                        warnings_found = :warnings,
                        completed_at = now()
                    WHERE id = :id
                """),
                {"checked": positions_checked, "warnings": warnings_found, "id": run_id},
            )

    except Exception as exc:
        log.exception("reconciliation_error: %s", exc)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE position_tracking.reconciliation_runs
                        SET status = 'failed', error_message = :error, completed_at = now()
                        WHERE id = :id
                    """),
                    {"error": str(exc)[:500], "id": run_id},
                )
        except Exception:
            pass
        raise
    finally:
        engine.dispose()

    summary = {
        "run_id": run_id,
        "status": "completed",
        "positions_checked": positions_checked,
        "warnings_found": warnings_found,
    }
    log.info("reconciliation_complete: %s", summary)
    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )

    parser = argparse.ArgumentParser(description="Position reconciliation worker")
    parser.add_argument("--once", action="store_true", help="Run a single reconciliation pass")
    parser.add_argument("--schedule", type=int, default=300, help="Interval in seconds between passes")
    args = parser.parse_args()

    if args.once:
        result = run_reconciliation()
        print(f"Reconciliation complete: {result}", file=sys.stderr, flush=True)
        return

    log.info("Starting reconciliation worker (interval=%ds)...", args.schedule)
    while True:
        try:
            run_reconciliation()
        except Exception:
            log.exception("reconciliation_pass_failed")
        time.sleep(args.schedule)


if __name__ == "__main__":
    main()
