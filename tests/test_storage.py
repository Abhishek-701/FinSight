"""V5.4 tests for app.storage: dialect-generation helpers and placeholder translation.

The live Postgres path itself (session ordering, watchlist dedupe, portfolio upsert/migration)
was verified manually against a throwaway Postgres container — not part of this offline suite,
since the existing session/portfolio/watchlist tests rely on a fresh sqlite file per test
(config.SESSION_DB_PATH monkeypatched in setUp) for isolation, which doesn't carry over to a
shared Postgres instance without per-test cleanup infrastructure this phase didn't add. These
tests cover what CAN be verified offline: the sqlite default path end-to-end, and the dialect
logic (`?`->`%s` translation, insert_ignore SQL shape) in isolation.
"""

import tempfile
import unittest
from pathlib import Path

from app import config, storage


class BackendSelectionTests(unittest.TestCase):
    def setUp(self):
        self._orig = config.DATABASE_URL

    def tearDown(self):
        config.DATABASE_URL = self._orig

    def test_defaults_to_sqlite_when_database_url_unset(self):
        config.DATABASE_URL = ""
        self.assertFalse(storage.is_postgres())
        self.assertEqual(storage.backend_name(), "sqlite")

    def test_reports_postgres_when_database_url_set(self):
        config.DATABASE_URL = "postgresql://user:pass@host/db"
        self.assertTrue(storage.is_postgres())
        self.assertEqual(storage.backend_name(), "postgres")


class InsertIgnoreSqlTests(unittest.TestCase):
    def setUp(self):
        self._orig = config.DATABASE_URL

    def tearDown(self):
        config.DATABASE_URL = self._orig

    def test_sqlite_uses_insert_or_ignore(self):
        config.DATABASE_URL = ""
        sql = storage.insert_ignore("watchlist", ("client_id", "ticker", "added_at"), ("client_id", "ticker"))
        self.assertIn("INSERT OR IGNORE INTO watchlist", sql)
        self.assertNotIn("ON CONFLICT", sql)
        self.assertEqual(sql.count("?"), 3)

    def test_postgres_uses_on_conflict_do_nothing(self):
        config.DATABASE_URL = "postgresql://user:pass@host/db"
        sql = storage.insert_ignore("watchlist", ("client_id", "ticker", "added_at"), ("client_id", "ticker"))
        self.assertIn("INSERT INTO watchlist", sql)
        self.assertIn("ON CONFLICT (client_id, ticker) DO NOTHING", sql)
        self.assertNotIn("OR IGNORE", sql)
        self.assertEqual(sql.count("?"), 3)  # still `?` — connect()'s translation handles %s


class FakeCursor:
    def __init__(self):
        self.last_sql = None
        self.last_params = None

    def execute(self, sql, params=()):
        self.last_sql = sql
        self.last_params = params

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class TranslatingCursorTests(unittest.TestCase):
    def test_translates_question_marks_to_percent_s_when_enabled(self):
        fake = FakeCursor()
        cur = storage._TranslatingCursor(fake, translate=True)
        cur.execute("SELECT * FROM t WHERE a = ? AND b = ?", (1, 2))
        self.assertEqual(fake.last_sql, "SELECT * FROM t WHERE a = %s AND b = %s")
        self.assertEqual(fake.last_params, (1, 2))

    def test_leaves_question_marks_alone_when_disabled(self):
        fake = FakeCursor()
        cur = storage._TranslatingCursor(fake, translate=False)
        cur.execute("SELECT * FROM t WHERE a = ?", (1,))
        self.assertEqual(fake.last_sql, "SELECT * FROM t WHERE a = ?")


class SqliteConnectIntegrationTests(unittest.TestCase):
    """The default path (no DATABASE_URL) end-to-end through storage.connect()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_db_url = config.DATABASE_URL
        config.DATABASE_URL = ""

    def tearDown(self):
        config.DATABASE_URL = self._orig_db_url
        self._tmpdir.cleanup()

    def test_connect_creates_parent_dir_and_runs_init_once_committed(self):
        path = Path(self._tmpdir.name) / "nested" / "test.sqlite3"
        self.assertFalse(path.parent.exists())

        def init(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")

        conn = storage.connect(path, init=init)
        try:
            self.assertTrue(path.parent.exists())
            with conn:
                conn.execute("INSERT INTO t (v) VALUES (?)", ("hello",))
        finally:
            conn.close()

        # A fresh connection should see the committed insert.
        conn2 = storage.connect(path, init=init)
        try:
            rows = conn2.execute("SELECT v FROM t").fetchall()
            self.assertEqual(rows, [("hello",)])
        finally:
            conn2.close()

    def test_sqlite_columns_reflects_actual_schema(self):
        path = Path(self._tmpdir.name) / "cols.sqlite3"

        def init(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS t (a TEXT, b REAL)")

        conn = storage.connect(path, init=init)
        try:
            cols = storage.sqlite_columns(conn, "t")
        finally:
            conn.close()
        self.assertEqual(cols, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
