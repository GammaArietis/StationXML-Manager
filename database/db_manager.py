import sqlite3
import logging
from pathlib import Path

# Configure a basic logger
logger = logging.getLogger(__name__)

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

    def initialize_database(self, schema_path: str | Path) -> None:
        """
        Reads the schema.sql file and creates the tables if they don't exist.
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