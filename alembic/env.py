import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


VERSION_TABLE = "quant_positions_alembic_version"
VERSION_TABLE_SCHEMA = "positions"


def _relocate_version_table(connection) -> None:
    """Ensure the `positions` schema exists and owns the Alembic version table.

    Runs before Alembic reads migration history. If the version table already
    exists in another schema (e.g. the default `public`), it is moved into
    `positions` so recorded revision history survives pinning
    version_table_schema to `positions`.
    """
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {VERSION_TABLE_SCHEMA}"))
    connection.execute(text(f"""
        DO $$
        DECLARE
            src_schema text;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = '{VERSION_TABLE_SCHEMA}'
                  AND table_name = '{VERSION_TABLE}'
            ) THEN
                SELECT table_schema INTO src_schema
                FROM information_schema.tables
                WHERE table_name = '{VERSION_TABLE}'
                  AND table_schema <> '{VERSION_TABLE_SCHEMA}'
                ORDER BY (table_schema = 'public') DESC
                LIMIT 1;
                IF src_schema IS NOT NULL THEN
                    EXECUTE format(
                        'ALTER TABLE %I.{VERSION_TABLE} SET SCHEMA {VERSION_TABLE_SCHEMA}',
                        src_schema
                    );
                END IF;
            END IF;
        END $$;
    """))
    connection.commit()


def run_migrations_offline() -> None:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, pool_pre_ping=True)
    with connectable.connect() as connection:
        _relocate_version_table(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
