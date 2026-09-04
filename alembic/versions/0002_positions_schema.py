"""0002 – Relocate all objects into the `positions` schema.

Moves every table created by 0001 out of the legacy `position_tracking`
schema into `positions`. This is data-preserving: ``ALTER TABLE ... SET SCHEMA``
carries each table's data along with its indexes, constraints, and
column-owned sequences. Once every table has been moved, the now-empty
`position_tracking` schema is dropped.

The Alembic version table is relocated into `positions` separately, in
alembic/env.py, before migration history is read.

Revision ID: 0002_positions_schema
Create Date: 2026-09-04
"""

from alembic import op

revision = "0002_positions_schema"
down_revision = "0001_position_tracking"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "positions"
LEGACY_SCHEMA = "position_tracking"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}")
    op.execute(f"""
        DO $$
        DECLARE
            tbl text;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = '{LEGACY_SCHEMA}'
            ) THEN
                FOR tbl IN
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = '{LEGACY_SCHEMA}'
                LOOP
                    EXECUTE format(
                        'ALTER TABLE {LEGACY_SCHEMA}.%I SET SCHEMA {TARGET_SCHEMA}', tbl
                    );
                END LOOP;
            END IF;
        END $$;
    """)
    op.execute(f"DROP SCHEMA IF EXISTS {LEGACY_SCHEMA} CASCADE")


def downgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {LEGACY_SCHEMA}")
    op.execute(f"""
        DO $$
        DECLARE
            tbl text;
        BEGIN
            FOR tbl IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = '{TARGET_SCHEMA}'
                  AND tablename <> 'quant_positions_alembic_version'
            LOOP
                EXECUTE format(
                    'ALTER TABLE {TARGET_SCHEMA}.%I SET SCHEMA {LEGACY_SCHEMA}', tbl
                );
            END LOOP;
        END $$;
    """)
