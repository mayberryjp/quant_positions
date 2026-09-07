"""Quant position tracking service."""
from __future__ import annotations

import os

from sqlalchemy import event
from sqlalchemy.engine import Engine


def _container_timezone() -> str:
    """Return the container's local IANA timezone (defaults to New York)."""
    return os.environ.get("TZ") or "America/New_York"


@event.listens_for(Engine, "connect")
def _pin_session_timezone(dbapi_connection, connection_record):
    # Pin every database session to the container's local time so all timestamps
    # are stored and returned in that zone rather than UTC or any other offset.
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SELECT set_config('timezone', %s, false)", (_container_timezone(),))
