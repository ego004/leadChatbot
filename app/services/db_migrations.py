from sqlalchemy import text
from sqlalchemy.engine import Engine

NEW_CLIENT_COLUMNS = [
    ("smtp_server", "VARCHAR(255) NULL"),
    ("smtp_port", "INT NULL"),
    ("smtp_user", "VARCHAR(255) NULL"),
    ("smtp_password", "VARCHAR(255) NULL"),
    ("smtp_from_name", "VARCHAR(255) NULL"),
    ("imap_server", "VARCHAR(255) NULL"),
    ("imap_port", "INT NULL"),
    ("email_enabled", "TINYINT(1) NULL DEFAULT NULL")
]

# New columns for client_deployments table
NEW_CLIENT_DEPLOYMENT_COLUMNS = [
    ("email_system_prompt", "TEXT NULL"),
    ("email_welcome_message", "TEXT NULL"),
    ("deployment_api_token", "VARCHAR(255) NULL"),
]


def _column_exists_mysql(conn, table: str, column: str) -> bool:
    sql = text(
        """
        SELECT COUNT(*) as cnt
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :table
          AND COLUMN_NAME = :column
        """
    )
    res = conn.execute(sql, {"table": table, "column": column}).scalar()
    return bool(res)


def _column_exists_sqlite(conn, table: str, column: str) -> bool:
    sql = text("PRAGMA table_info(\"%s\")" % table)
    rows = conn.execute(sql).fetchall()
    return any(r[1] == column for r in rows)  # (cid, name, type, notnull, dflt_value, pk)


def _column_exists_postgres(conn, table: str, column: str) -> bool:
    sql = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
        )
        """
    )
    return conn.execute(sql, {"table": table, "column": column}).scalar()


def run_lightweight_migrations(engine: Engine):
    """Add new columns to clients table if they do not exist.
    Supports MySQL, Postgres, and SQLite.
    """
    dialect = engine.url.get_backend_name()
    with engine.begin() as conn:
        if dialect == "mysql":
            exists_fn = _column_exists_mysql
        elif dialect in ("postgresql", "postgres"):
            exists_fn = _column_exists_postgres
        elif dialect == "sqlite":
            exists_fn = _column_exists_sqlite
        else:
            # Best-effort: try information_schema, else skip
            exists_fn = _column_exists_mysql

        for col, col_type in NEW_CLIENT_COLUMNS:
            try:
                if not exists_fn(conn, "clients", col):
                    # different SQL per dialect
                    if dialect == "postgresql":
                        alter_sql = text(f"ALTER TABLE clients ADD COLUMN IF NOT EXISTS {col} {col_type};")
                    elif dialect == "mysql":
                        # MySQL IF NOT EXISTS for columns is available in newer versions; use check above + plain ADD COLUMN
                        alter_sql = text(f"ALTER TABLE clients ADD COLUMN {col} {col_type};")
                    elif dialect == "sqlite":
                        alter_sql = text(f"ALTER TABLE clients ADD COLUMN {col} {col_type};")
                    else:
                        alter_sql = text(f"ALTER TABLE clients ADD COLUMN {col} {col_type};")
                    conn.execute(alter_sql)
            except Exception:
                # Continue with other columns; log is optional to keep lightweight
                pass

        # Ensure large content support for knowledge_documents.content
        try:
            if dialect == "mysql":
                # Check current data type of knowledge_documents.content
                cur_type = conn.execute(text(
                    """
                    SELECT DATA_TYPE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'knowledge_documents'
                      AND COLUMN_NAME = 'content'
                    """
                )).scalar()
                # If it's 'text' (64KB), upgrade to MEDIUMTEXT (~16MB)
                if str(cur_type).lower() == "text":
                    conn.execute(text("ALTER TABLE knowledge_documents MODIFY content MEDIUMTEXT NULL;"))
            # Also ensure column is nullable (metadata-only strategy)
            if dialect == "postgresql":
                try:
                    conn.execute(text("ALTER TABLE knowledge_documents ALTER COLUMN content DROP NOT NULL;"))
                except Exception:
                    pass
            # Postgres TEXT and SQLite TEXT already support large content; no change required
        except Exception:
            # Best-effort; do not block app startup if this fails
            pass

        # Add columns to knowledge_documents for Supabase-backed storage
        try:
            # storage_path column
            if not exists_fn(conn, "knowledge_documents", "storage_path"):
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS storage_path VARCHAR(512) NULL;"))
                else:
                    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN storage_path VARCHAR(512) NULL;"))
            # content_preview column
            if not exists_fn(conn, "knowledge_documents", "content_preview"):
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS content_preview TEXT NULL;"))
                else:
                    conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN content_preview TEXT NULL;"))
        except Exception:
            pass

        # Add columns to client_deployments table
        for col, col_type in NEW_CLIENT_DEPLOYMENT_COLUMNS:
            try:
                if not exists_fn(conn, "client_deployments", col):
                    if dialect == "postgresql":
                        alter_sql = text(f"ALTER TABLE client_deployments ADD COLUMN IF NOT EXISTS {col} {col_type};")
                    elif dialect == "mysql":
                        alter_sql = text(f"ALTER TABLE client_deployments ADD COLUMN {col} {col_type};")
                    elif dialect == "sqlite":
                        alter_sql = text(f"ALTER TABLE client_deployments ADD COLUMN {col} {col_type};")
                    else:
                        alter_sql = text(f"ALTER TABLE client_deployments ADD COLUMN {col} {col_type};")
                    conn.execute(alter_sql)
            except Exception:
                pass
