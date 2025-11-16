import logging
import time
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Union

class Database:
    """Handles all database operations for sensor readings."""

    def __init__(self, db_path: Union[str, Path]):
        """
        Initializes the Database handler.

        Args:
            db_path: The file path to the sqlite database.
        """
        self.db_path = Path(db_path)
        self.label_cache: Dict[str, int] = {}
        logging.info(f"Database initialized at path: {self.db_path}")

    def setup(self) -> None:
        """
        Sets up the database, creating tables and indices if they don't exist.
        """
        logging.info("Setting up database tables and indices...")
        # Use a context manager to handle connection and transactions
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS labels (
                    label_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label STRING UNIQUE
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS labels_label_index
                ON labels(label)
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS readings (
                    label_id INTEGER,
                    timestamp INTEGER,
                    value REAL,
                    FOREIGN KEY(label_id) REFERENCES labels(label_id)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS readings_timestamp
                ON readings(timestamp)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS readings_label_id
                ON readings(label_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS readings_label_id_timestamp
                ON readings(label_id, timestamp)
            ''')
        logging.info("Database setup complete.")

    def _get_or_create_label_id(self, cursor: sqlite3.Cursor, label: str) -> int:
        """
        Gets a label_id from the cache or database.
        If the label doesn't exist, it's created.

        NOTE: This must be called with a cursor from an active transaction,
        as it may perform a database write (INSERT).

        Args:
            cursor: The database cursor from an active connection.
            label: The string label to get or create.

        Returns:
            The integer ID for the label.
        """
        # Check cache first
        if label in self.label_cache:
            return self.label_cache[label]

        # If not in cache, check database
        cursor.execute('SELECT label_id FROM labels WHERE label=?', (label,))
        result = cursor.fetchone()

        if result:
            label_id = result[0]
        else:
            # Not in DB, so create it
            cursor.execute('INSERT INTO labels(label) VALUES (?)', (label,))
            label_id = cursor.lastrowid
            logging.debug(f"Created new label '{label}' with id {label_id}")

        # Update cache and return
        self.label_cache[label] = label_id
        return label_id

    def log_data(self, label: str, value: float, timestamp: Optional[int] = None) -> None:
        """
        Logs a new data point to the database.

        This opens a single connection and handles the transaction
        for potentially creating a new label and logging the reading.

        Args:
            label: The string identifier for the data (e.g., 'efergy_h2_123456').
            value: The floating-point value of the reading.
            timestamp: The Unix timestamp. If None, current time is used.
        """
        if timestamp is None:
            timestamp = int(time.time())

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Get or create the label ID within the transaction
                label_id = self._get_or_create_label_id(cursor, label)

                # Insert the actual reading
                cursor.execute(
                    'INSERT INTO readings(label_id, timestamp, value) VALUES (?,?,?)',
                    (label_id, int(timestamp), value)
                )
                # The 'with' block automatically commits on success

            logging.info(
                f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(timestamp))}: "
                f"{label} ({label_id}), {value}"
            )
        except sqlite3.Error as e:
            logging.error(f"Failed to log data for label '{label}': {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred in log_data: {e}")