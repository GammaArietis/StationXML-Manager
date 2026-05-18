import sqlite3
import logging
import threading
from contextlib import contextmanager
from pathlib import Path

# Configure a basic logger
logger = logging.getLogger(__name__)


_MUTATING_SQL_PREFIXES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "REPLACE",
    "CREATE",
    "ALTER",
    "DROP",
    "BEGIN",
)


class _LockedCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=(), /):
        self.connection._acquire_write_lock_for_sql(sql)
        return super().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        self.connection._acquire_write_lock_for_sql(sql)
        return super().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script, /):
        self.connection._acquire_write_lock()
        return super().executescript(sql_script)


class _LockedConnection(sqlite3.Connection):
    _write_lock = threading.RLock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._write_lock_acquired = False

    def _acquire_write_lock_for_sql(self, sql: object) -> None:
        text = str(sql).lstrip().upper()
        if text.startswith(_MUTATING_SQL_PREFIXES):
            self._acquire_write_lock()

    def _acquire_write_lock(self) -> None:
        if not self._write_lock_acquired:
            self._write_lock.acquire()
            self._write_lock_acquired = True

    def _release_write_lock(self) -> None:
        if self._write_lock_acquired:
            self._write_lock_acquired = False
            self._write_lock.release()

    def cursor(self, *args, **kwargs):
        kwargs.setdefault("factory", _LockedCursor)
        return super().cursor(*args, **kwargs)

    def execute(self, sql, parameters=(), /):
        self._acquire_write_lock_for_sql(sql)
        return super().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        self._acquire_write_lock_for_sql(sql)
        return super().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script, /):
        self._acquire_write_lock()
        return super().executescript(sql_script)

    def commit(self) -> None:
        try:
            super().commit()
        finally:
            self._release_write_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_write_lock()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._release_write_lock()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self._release_write_lock()


class DatabaseManager:
    """
    Manages the SQLite database connection and schema initialization.
    """
    
    def __init__(self, db_path: str | Path):
        """
        Initializes the manager.
        :param db_path: Path to the database file (e.g., 'data/stationxml.db')
        """
        self.db_path = Path(db_path)
        
        # Ensure the directory containing the DB exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """
        Creates and returns a database connection.
        Automatically enables foreign keys for every new connection.
        """
        try:
            # detect_types=sqlite3.PARSE_DECLTYPES helps manage advanced types if needed
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
                timeout=30.0,
                factory=_LockedConnection,
            )
            
            # Return rows as dictionaries (much more convenient for the GUI)
            conn.row_factory = sqlite3.Row
            
            # Enable foreign keys in SQLite
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode=WAL;")
            return conn
        except sqlite3.Error as e:
            logger.error(f"Database connection error {self.db_path}: {e}")
            raise

    @contextmanager
    def write_transaction(self):
        """
        Open one SQLite write transaction protected by the process-wide write lock.

        SELECT-only code should keep using get_connection(); this context is for
        multi-step writes that must commit or roll back as one unit.
        """
        conn = self.get_connection()
        conn._acquire_write_lock()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_database(self, schema_path: str | Path) -> None:
        """
        Reads schema.sql and applies it (CREATE TABLE IF NOT EXISTS, migrations).

        Prefer :func:`core.database.init_database` at application startup.
        """
        schema_path = Path(schema_path)
        
        if not schema_path.exists():
            error_msg = f"Schema file not found: {schema_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        logger.info(f"Initializing database: {self.db_path}")
        
        try:
            # Read all the content from the SQL file
            with open(schema_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()

            # Use a context manager for the connection (auto-closes at the end)
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # executescript runs multiple statements separated by semicolons
                cursor.executescript(sql_script)
                self._ensure_channel_restricted_status_column(conn)
                conn.commit()

            logger.info("Database initialized successfully.")
            
        except sqlite3.Error as e:
            logger.error(f"Error executing SQL schema: {e}")
            raise

    def _ensure_channel_restricted_status_column(self, conn: sqlite3.Connection) -> None:
        """
        CREATE TABLE IF NOT EXISTS does not add columns to existing DBs.
        FDSN Channel.restrictedStatus is stored as channel.restricted_status.
        """
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='channel' LIMIT 1"
        )
        if not cur.fetchone():
            return
        cur.execute("PRAGMA table_info(channel)")
        col_names = {row[1] for row in cur.fetchall()}
        if "restricted_status" in col_names:
            return
        cur.execute(
            "ALTER TABLE channel ADD COLUMN restricted_status TEXT DEFAULT 'open'"
        )
        logger.info("Applied migration: channel.restricted_status column added.")