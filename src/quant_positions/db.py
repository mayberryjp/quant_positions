"""Database engine helpers."""
from __future__ import annotations

import os

from sqlalchemy import create_engine as _create_engine, Engine


def get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return _create_engine(url, pool_pre_ping=True)
