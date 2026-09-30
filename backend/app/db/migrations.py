from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_compatibility_migrations(engine: Engine) -> None:
    """Apply additive SQLite-safe changes for databases created before auth."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "projects" in tables:
            project_columns = {
                column["name"] for column in inspector.get_columns("projects")
            }
            if "owner_user_id" not in project_columns:
                connection.execute(
                    text("ALTER TABLE projects ADD COLUMN owner_user_id VARCHAR(36)")
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_projects_owner_user_id "
                        "ON projects (owner_user_id)"
                    )
                )
        if "auth_sessions" in tables:
            session_columns = {
                column["name"] for column in inspector.get_columns("auth_sessions")
            }
            if "csrf_token_hash" not in session_columns:
                connection.execute(
                    text("ALTER TABLE auth_sessions ADD COLUMN csrf_token_hash VARCHAR(64)")
                )
                connection.execute(
                    text("UPDATE auth_sessions SET csrf_token_hash = '' WHERE csrf_token_hash IS NULL")
                )
        _add_column_if_missing(
            connection, inspector, tables, "projects", "updated_at", "DATETIME"
        )
        _add_column_if_missing(
            connection, inspector, tables, "analysis_results", "created_at", "DATETIME"
        )
        _add_column_if_missing(
            connection, inspector, tables, "analysis_messages", "answer_version_id", "INTEGER"
        )
        _add_column_if_missing(
            connection, inspector, tables, "analysis_messages", "status", "VARCHAR(16)"
        )
        _add_column_if_missing(
            connection, inspector, tables, "commerce_benchmark_snapshots", "snapshot_json", "JSON"
        )
        if "commerce_benchmark_snapshots" in tables:
            connection.execute(
                text(
                    "UPDATE commerce_benchmark_snapshots "
                    "SET snapshot_json = json_extract(dataset_json, '$.snapshot') "
                    "WHERE snapshot_json IS NULL"
                )
            )
        for table, column in (
            ("projects", "updated_at"),
            ("analysis_results", "created_at"),
        ):
            if table in tables:
                connection.execute(
                    text(f"UPDATE {table} SET {column} = CURRENT_TIMESTAMP WHERE {column} IS NULL")
                )
        if "analysis_messages" in tables:
            connection.execute(
                text("UPDATE analysis_messages SET status = 'completed' WHERE status IS NULL")
            )


def _add_column_if_missing(
    connection, inspector, tables: set[str], table: str, column: str, definition: str
) -> None:
    if table not in tables:
        return
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column not in columns:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
