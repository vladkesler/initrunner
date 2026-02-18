"""Tests for the SQL query tool."""

from __future__ import annotations

import sqlite3

from initrunner.agent.schema.tools import SqlToolConfig
from initrunner.agent.sql_tools import build_sql_toolset
from initrunner.agent.tools._registry import ToolBuildContext


def _make_ctx(role_dir=None):
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-4o-mini"},
            },
        }
    )
    return ToolBuildContext(role=role, role_dir=role_dir)


def _create_test_db(path, rows=5):
    """Create a test SQLite database with sample data."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    for i in range(1, rows + 1):
        conn.execute("INSERT INTO users VALUES (?, ?, ?)", (i, f"user{i}", 20 + i))
    conn.commit()
    conn.close()


class TestSqlToolset:
    def test_builds_toolset(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        assert "query_database" in toolset.tools

    def test_select_query(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="SELECT name, age FROM users WHERE id = 1")
        assert "user1" in result
        assert "21" in result

    def test_read_only_blocks_write(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db), read_only=True)
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="INSERT INTO users VALUES (99, 'hack', 0)")
        assert "error" in result.lower()

    def test_attach_database_blocked(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="ATTACH DATABASE '/tmp/other.db' AS other")
        assert "ATTACH DATABASE is not allowed" in result

    def test_max_rows(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db, rows=20)
        config = SqlToolConfig(database=str(db), max_rows=3)
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="SELECT * FROM users")
        # Header + separator + 3 data rows = 5 lines
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 5

    def test_invalid_sql(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="NOT VALID SQL")
        assert "SQL error" in result

    def test_output_truncation(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db, rows=50)
        config = SqlToolConfig(database=str(db), max_result_bytes=100)
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="SELECT * FROM users")
        assert "[truncated]" in result

    def test_empty_result(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="SELECT * FROM users WHERE id = 999")
        assert result == "No results"

    def test_writable_mode(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db), read_only=False)
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="INSERT INTO users VALUES (99, 'new_user', 30)")
        assert "OK" in result
        # Verify the insert worked
        result2 = fn(sql="SELECT name FROM users WHERE id = 99")
        assert "new_user" in result2

    def test_attach_blocked_with_block_comment(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="/* comment */ ATTACH DATABASE '/tmp/x.db' AS x")
        assert "ATTACH DATABASE is not allowed" in result

    def test_attach_blocked_with_line_comment(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="-- comment\nATTACH DATABASE '/tmp/x.db' AS x")
        assert "ATTACH DATABASE is not allowed" in result

    def test_attach_blocked_mixed_case(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="attach database '/tmp/x.db' as x")
        assert "ATTACH DATABASE is not allowed" in result

    def test_pragma_query_only_blocked(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="PRAGMA query_only=OFF")
        assert "PRAGMA query_only is not allowed" in result

    def test_pragma_query_only_blocked_case_insensitive(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="pragma Query_Only = off")
        assert "PRAGMA query_only is not allowed" in result

    def test_benign_pragma_allowed(self, tmp_path):
        db = tmp_path / "test.db"
        _create_test_db(db)
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="PRAGMA table_info(users)")
        assert "name" in result

    def test_attachments_table_not_blocked(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE attachments (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO attachments VALUES (1, 'file.pdf')")
        conn.commit()
        conn.close()
        config = SqlToolConfig(database=str(db))
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="SELECT * FROM attachments WHERE id = 1")
        assert "file.pdf" in result

    def test_attach_string_literal_not_blocked(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, msg TEXT)")
        conn.commit()
        conn.close()
        config = SqlToolConfig(database=str(db), read_only=False)
        toolset = build_sql_toolset(config, _make_ctx(role_dir=tmp_path))
        fn = toolset.tools["query_database"].function
        result = fn(sql="INSERT INTO logs (msg) VALUES ('Please attach the file')")
        assert "OK" in result
