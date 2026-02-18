"""SQL query tool: executes queries against SQLite databases."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent._paths import _INITRUNNER_DIR, validate_path_within
from initrunner.agent._truncate import truncate_output
from initrunner.agent.schema.tools import SqlToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool

_BLOCKED_ATTACH = re.compile(r"\bATTACH\s+DATABASE\b", re.IGNORECASE)
_BLOCKED_PRAGMA = re.compile(r"\bPRAGMA\s+query_only\b", re.IGNORECASE)


def _authorizer(action, arg1, arg2, db_name, trigger_name):
    """sqlite3 authorizer callback that denies ATTACH at the engine level."""
    if action == sqlite3.SQLITE_ATTACH:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _resolve_db_path(database: str, role_dir: Path | None) -> Path:
    """Resolve database path, making relative paths relative to role_dir."""
    db_path = Path(database)
    if not db_path.is_absolute() and role_dir is not None:
        db_path = role_dir / db_path
    return db_path.resolve()


def _validate_db_path(db_path: Path, role_dir: Path | None) -> str | None:
    """Validate that the database path is under role_dir or ~/.initrunner/."""
    if str(db_path) == ":memory:":
        return None
    allowed_roots = [_INITRUNNER_DIR]
    if role_dir is not None:
        allowed_roots.append(role_dir)
    err, _ = validate_path_within(db_path, allowed_roots)
    return err


@register_tool("sql", SqlToolConfig)
def build_sql_toolset(config: SqlToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for querying SQLite databases."""
    role_dir = ctx.role_dir
    is_memory = config.database == ":memory:"

    if is_memory:
        db_path_str = ":memory:"
    else:
        db_path = _resolve_db_path(config.database, role_dir)
        if err := _validate_db_path(db_path, role_dir):
            raise ValueError(err)
        db_path_str = str(db_path)

    toolset = FunctionToolset()

    @toolset.tool
    def query_database(sql: str) -> str:
        """Execute a SQL query against the configured SQLite database."""
        # Block ATTACH DATABASE to prevent escaping to other databases
        if _BLOCKED_ATTACH.search(sql):
            return "Error: ATTACH DATABASE is not allowed"
        if _BLOCKED_PRAGMA.search(sql):
            return "Error: PRAGMA query_only is not allowed"

        try:
            conn = sqlite3.connect(db_path_str, timeout=config.timeout_seconds)
            try:
                conn.set_authorizer(_authorizer)
                if config.read_only:
                    conn.execute("PRAGMA query_only=ON")

                cursor = conn.execute(sql)

                # For non-SELECT statements, return rowcount
                if cursor.description is None:
                    conn.commit()
                    return f"OK ({cursor.rowcount} rows affected)"

                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchmany(config.max_rows)

                if not rows:
                    return "No results"

                # Format as text table
                col_widths = [len(c) for c in columns]
                for row in rows:
                    for i, val in enumerate(row):
                        col_widths[i] = max(col_widths[i], len(str(val)))

                lines: list[str] = []
                header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
                lines.append(header)
                lines.append("-+-".join("-" * w for w in col_widths))
                for row in rows:
                    line = " | ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(row))
                    lines.append(line)

                output = "\n".join(lines)
                return truncate_output(output, config.max_result_bytes)

            finally:
                conn.close()

        except sqlite3.Error as e:
            return f"SQL error: {e}"

    return toolset
