"""Small, forward-only SQLite migrations for the local personal app."""

from __future__ import annotations

from sqlalchemy import text


_VERSION = 2


def migrate(engine) -> None:
    """Bring an existing SQLite database to the schema used by the models.

    SQLModel's create_all does not alter existing tables. The app only supports a
    local SQLite deployment, so a transactional table rebuild is both explicit
    and sufficient while preserving every legacy observation.

    Each step is gated on the version that introduced it. Gating only on the
    final version would re-run every earlier step on an upgrade — and step 1
    drops ``daily_summary``, which now holds real derived data.
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

        if version < 1:
            _migrate_v1(connection)
        if version < 2:
            _migrate_v2(connection)

        connection.execute(text("UPDATE schema_version SET version = :version"), {"version": _VERSION})


def _migrate_v1(connection) -> None:
    """Add provider record identity to daily_metric; rebuild derived summaries."""
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


def _migrate_v2(connection) -> None:
    """Add the deep-research job, report, plan, and daily-check tables.

    Purely additive: no existing table is touched, so an upgrade cannot lose the
    imported observations or their derived summaries.
    """
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS research_job (
            id VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL,
            question VARCHAR,
            phase VARCHAR,
            rounds_done INTEGER NOT NULL DEFAULT 0,
            report_id VARCHAR,
            error VARCHAR,
            started_at DATETIME NOT NULL,
            finished_at DATETIME
        )
    """))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_research_job_status ON research_job (status)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_research_job_started_at ON research_job (started_at)"))

    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS research_report (
            id VARCHAR PRIMARY KEY,
            job_id VARCHAR NOT NULL,
            narrative VARCHAR NOT NULL,
            analysis_json VARCHAR NOT NULL,
            created_at DATETIME NOT NULL
        )
    """))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_research_report_job_id ON research_report (job_id)"))

    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS health_plan (
            id VARCHAR PRIMARY KEY,
            report_id VARCHAR NOT NULL,
            horizon VARCHAR NOT NULL,
            plan_json VARCHAR NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            parent_id VARCHAR,
            created_at DATETIME NOT NULL
        )
    """))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_health_plan_is_active ON health_plan (is_active)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_health_plan_report_id ON health_plan (report_id)"))

    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS daily_check (
            id INTEGER PRIMARY KEY,
            date DATE NOT NULL,
            plan_id VARCHAR,
            summary VARCHAR NOT NULL,
            result_json VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT uq_daily_check_date UNIQUE (date)
        )
    """))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_daily_check_date ON daily_check (date)"))
