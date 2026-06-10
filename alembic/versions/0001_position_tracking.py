"""0001 – Position tracking schema.

Revision ID: 0001_position_tracking
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_position_tracking"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS position_tracking")

    # -- portfolios / tracking accounts --
    op.execute("""
        CREATE TABLE position_tracking.portfolios (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            portfolio_type  TEXT NOT NULL DEFAULT 'paper',
            currency        TEXT NOT NULL DEFAULT 'USD',
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # -- positions (current aggregate) --
    op.execute("""
        CREATE TABLE position_tracking.positions (
            id              SERIAL PRIMARY KEY,
            portfolio_id    INTEGER NOT NULL REFERENCES position_tracking.portfolios(id),
            symbol_id       INTEGER,
            submitted_ticker TEXT NOT NULL,
            market          TEXT NOT NULL DEFAULT 'stocks',
            locale          TEXT NOT NULL DEFAULT 'us',
            quantity        NUMERIC(20, 8) NOT NULL DEFAULT 0,
            average_cost    NUMERIC(20, 8) NOT NULL DEFAULT 0,
            market_value    NUMERIC(20, 8) NOT NULL DEFAULT 0,
            realized_pnl    NUMERIC(20, 8) NOT NULL DEFAULT 0,
            unrealized_pnl  NUMERIC(20, 8) NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'open',
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (portfolio_id, submitted_ticker, market, locale)
        )
    """)

    op.execute("""
        CREATE INDEX idx_positions_portfolio ON position_tracking.positions (portfolio_id)
    """)
    op.execute("""
        CREATE INDEX idx_positions_ticker ON position_tracking.positions (submitted_ticker)
    """)
    op.execute("""
        CREATE INDEX idx_positions_status ON position_tracking.positions (status)
    """)

    # -- position lots (cost-basis records) --
    op.execute("""
        CREATE TABLE position_tracking.position_lots (
            id              SERIAL PRIMARY KEY,
            position_id     INTEGER NOT NULL REFERENCES position_tracking.positions(id),
            portfolio_id    INTEGER NOT NULL REFERENCES position_tracking.portfolios(id),
            symbol_id       INTEGER,
            submitted_ticker TEXT NOT NULL,
            lot_identifier  TEXT,
            quantity         NUMERIC(20, 8) NOT NULL DEFAULT 0,
            cost_basis       NUMERIC(20, 8) NOT NULL DEFAULT 0,
            acquired_at      TIMESTAMPTZ,
            closed_at        TIMESTAMPTZ,
            status           TEXT NOT NULL DEFAULT 'open',
            metadata         JSONB NOT NULL DEFAULT '{}',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (position_id, lot_identifier)
        )
    """)

    op.execute("""
        CREATE INDEX idx_position_lots_position ON position_tracking.position_lots (position_id)
    """)

    # -- position ledger entries (append-only, immutable) --
    op.execute("""
        CREATE TABLE position_tracking.position_ledger_entries (
            id                SERIAL PRIMARY KEY,
            portfolio_id      INTEGER NOT NULL REFERENCES position_tracking.portfolios(id),
            position_id       INTEGER REFERENCES position_tracking.positions(id),
            symbol_id         INTEGER,
            submitted_ticker  TEXT NOT NULL,
            market            TEXT NOT NULL DEFAULT 'stocks',
            locale            TEXT NOT NULL DEFAULT 'us',
            idempotency_key   TEXT NOT NULL UNIQUE,
            source            TEXT NOT NULL,
            source_event_id   TEXT,
            event_type        TEXT NOT NULL,
            quantity_delta    NUMERIC(20, 8) NOT NULL DEFAULT 0,
            price             NUMERIC(20, 8),
            fees              NUMERIC(20, 8) NOT NULL DEFAULT 0,
            occurred_at       TIMESTAMPTZ NOT NULL,
            reason            TEXT NOT NULL,
            tags              JSONB NOT NULL DEFAULT '[]',
            metadata          JSONB NOT NULL DEFAULT '{}',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX idx_ledger_portfolio ON position_tracking.position_ledger_entries (portfolio_id)
    """)
    op.execute("""
        CREATE INDEX idx_ledger_ticker ON position_tracking.position_ledger_entries (submitted_ticker)
    """)
    op.execute("""
        CREATE INDEX idx_ledger_event_type ON position_tracking.position_ledger_entries (event_type)
    """)
    op.execute("""
        CREATE INDEX idx_ledger_occurred_at ON position_tracking.position_ledger_entries (occurred_at)
    """)
    op.execute("""
        CREATE INDEX idx_ledger_source ON position_tracking.position_ledger_entries (source)
    """)

    # -- position snapshots (point-in-time for reconciliation) --
    op.execute("""
        CREATE TABLE position_tracking.position_snapshots (
            id              SERIAL PRIMARY KEY,
            position_id     INTEGER NOT NULL REFERENCES position_tracking.positions(id),
            portfolio_id    INTEGER NOT NULL REFERENCES position_tracking.portfolios(id),
            symbol_id       INTEGER,
            submitted_ticker TEXT NOT NULL,
            quantity         NUMERIC(20, 8) NOT NULL,
            average_cost     NUMERIC(20, 8) NOT NULL,
            market_value     NUMERIC(20, 8) NOT NULL DEFAULT 0,
            realized_pnl     NUMERIC(20, 8) NOT NULL DEFAULT 0,
            snapshot_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX idx_snapshots_position ON position_tracking.position_snapshots (position_id)
    """)

    # -- reconciliation runs --
    op.execute("""
        CREATE TABLE position_tracking.reconciliation_runs (
            id              SERIAL PRIMARY KEY,
            status          TEXT NOT NULL DEFAULT 'running',
            positions_checked INTEGER NOT NULL DEFAULT 0,
            warnings_found    INTEGER NOT NULL DEFAULT 0,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ,
            error_message   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # -- reconciliation warnings --
    op.execute("""
        CREATE TABLE position_tracking.reconciliation_warnings (
            id                SERIAL PRIMARY KEY,
            run_id            INTEGER NOT NULL REFERENCES position_tracking.reconciliation_runs(id),
            portfolio_id      INTEGER NOT NULL REFERENCES position_tracking.portfolios(id),
            position_id       INTEGER REFERENCES position_tracking.positions(id),
            symbol_id         INTEGER,
            submitted_ticker  TEXT NOT NULL,
            warning_type      TEXT NOT NULL,
            expected_quantity NUMERIC(20, 8),
            actual_quantity   NUMERIC(20, 8),
            detail            TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX idx_warnings_run ON position_tracking.reconciliation_warnings (run_id)
    """)

    # -- worker heartbeats --
    op.execute("""
        CREATE TABLE position_tracking.worker_heartbeats (
            id              SERIAL PRIMARY KEY,
            worker_name     TEXT NOT NULL UNIQUE,
            last_heartbeat  TIMESTAMPTZ NOT NULL DEFAULT now(),
            status          TEXT NOT NULL DEFAULT 'alive',
            metadata        JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS position_tracking CASCADE")
