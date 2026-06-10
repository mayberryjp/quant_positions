"""Readiness checks for the position tracking API."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


EXPECTED_SCHEMA_VERSION = "0001_position_tracking"
EXPECTED_TABLES = frozenset((
    "portfolios",
    "positions",
    "position_lots",
    "position_ledger_entries",
    "position_snapshots",
    "reconciliation_runs",
    "reconciliation_warnings",
    "worker_heartbeats",
))


class ReadinessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReadinessStatus:
    database: str
    schema_version: str
    tables: int
    open_positions: int = 0
    recent_ledger_entries: int = 0
    reconciliation_warnings: int = 0
    stale_workers: int = 0

    def as_json(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "database": self.database,
            "schema_version": self.schema_version,
            "tables": self.tables,
            "open_positions": self.open_positions,
            "recent_ledger_entries": self.recent_ledger_entries,
            "reconciliation_warnings": self.reconciliation_warnings,
            "stale_workers": self.stale_workers,
        }


def _database_url_from_env() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise ReadinessError("DATABASE_URL is not configured")
    return value


def _redact_database_url(database_url: str) -> str:
    try:
        parts = urlsplit(database_url)
    except ValueError:
        return "<redacted database url>"
    if not parts.netloc:
        return "<redacted database url>"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    username = parts.username or ""
    userinfo = f"{username}:***@" if username else ""
    return urlunsplit((parts.scheme, f"{userinfo}{host}{port}", parts.path, "", ""))


def sanitize_readiness_error(error: BaseException, database_url: str | None = None) -> str:
    message = str(error) or error.__class__.__name__
    if database_url:
        message = message.replace(database_url, _redact_database_url(database_url))
    return message


def check_database_readiness(database_url: str | None = None) -> ReadinessStatus:
    from sqlalchemy import create_engine, text

    resolved_url = database_url or _database_url_from_env()
    expected_table_names = tuple(sorted(EXPECTED_TABLES))
    engine = create_engine(resolved_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()

            schema_version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

            tables = tuple(
                connection.execute(
                    text("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'position_tracking'
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                    """)
                ).scalars().all()
            )

            open_positions = connection.execute(
                text("SELECT count(*) FROM position_tracking.positions WHERE status = 'open'")
            ).scalar_one()

            recent_ledger = connection.execute(
                text("""
                    SELECT count(*) FROM position_tracking.position_ledger_entries
                    WHERE created_at >= now() - interval '24 hours'
                """)
            ).scalar_one()

            recon_warnings = connection.execute(
                text("SELECT count(*) FROM position_tracking.reconciliation_warnings")
            ).scalar_one()

            stale_workers = connection.execute(
                text("""
                    SELECT count(*) FROM position_tracking.worker_heartbeats
                    WHERE last_heartbeat < now() - interval '10 minutes'
                """)
            ).scalar_one()
    finally:
        engine.dispose()

    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise ReadinessError(
            f"schema_version={schema_version} expected={EXPECTED_SCHEMA_VERSION}"
        )
    if tables != expected_table_names:
        raise ReadinessError(
            f"tables={','.join(tables)} expected={','.join(expected_table_names)}"
        )

    return ReadinessStatus(
        database="ok",
        schema_version=schema_version,
        tables=len(tables),
        open_positions=int(open_positions),
        recent_ledger_entries=int(recent_ledger),
        reconciliation_warnings=int(recon_warnings),
        stale_workers=int(stale_workers),
    )
