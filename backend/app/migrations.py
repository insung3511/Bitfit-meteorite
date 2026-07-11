"""Small, forward-only SQLite migrations for the local personal app."""

from __future__ import annotations

from sqlalchemy import text


_VERSION = 1


def migrate(engine) -> None:
    """Bring an existing SQLite database to the schema used by the models.

    SQLModel's create_all does not alter existing tables. The app only supports a
    local SQLite deployment, so a transactional table rebuild is both explicit
    and sufficient while preserving every legacy observation.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        version = connection.execute(text("SELECT version FROM schema_version LIMIT 1")).scalar()
        if version is None:
            connection.execute(text("INSERT INTO schema_version (version) VALUES (0)"))
            version = 0
        if version >= _VERSION:
            return

        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info('daily_metric')"))
        }
        if columns and "provider_record_id" not in columns:
            connection.execute(text("ALTER TABLE daily_metric RENAME TO daily_metric_legacy"))
            connection.execute(text("""
                CREATE TABLE daily_metric (
                    id INTEGER PRIMARY KEY,
                    date DATE NOT NULL,
                    metric_name VARCHAR NOT NULL,
                    value FLOAT NOT NULL,
                    unit VARCHAR,
                    source VARCHAR,
                    provider_record_id VARCHAR,
                    source_platform VARCHAR,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_daily_metric_source_record UNIQUE (source, provider_record_id)
                )
            """))
            connection.execute(text("""
                INSERT INTO daily_metric
                    (id, date, metric_name, value, unit, source, provider_record_id, source_platform, created_at)
                SELECT id, date, metric_name, value, unit, COALESCE(source, 'legacy'),
                    'legacy:' || id, NULL, created_at
                FROM daily_metric_legacy
            """))
            connection.execute(text("DROP TABLE daily_metric_legacy"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_daily_metric_date ON daily_metric (date)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_daily_metric_metric_name ON daily_metric (metric_name)"))

        summary_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info('daily_summary')"))
        }
        if summary_columns:
            # Summaries are derived data. Recreate rather than preserve duplicate,
            # potentially source-averaged legacy results.
            connection.execute(text("DROP TABLE daily_summary"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY,
                date DATE NOT NULL,
                metric_name VARCHAR NOT NULL,
                mean_7d FLOAT,
                mean_30d FLOAT,
                stddev_30d FLOAT,
                delta_vs_baseline FLOAT,
                created_at DATETIME NOT NULL,
                CONSTRAINT uq_daily_summary_date_metric UNIQUE (date, metric_name)
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_daily_summary_date ON daily_summary (date)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_daily_summary_metric_name ON daily_summary (metric_name)"))
        connection.execute(text("UPDATE schema_version SET version = :version"), {"version": _VERSION})
