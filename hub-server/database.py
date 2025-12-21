import logging
import threading
import time
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Union
from config import SQLITE_TIMEOUT


class Database:
    """Handles all database operations for sensor readings."""

    def __init__(self, db_path: Union[str, Path]):
        """
        Initializes the Database handler.

        Args:
            db_path: The file path to the sqlite database.
        """
        self.db_path = Path(db_path)

        # Ensure parent directory exists
        if not self.db_path.parent.exists():
            logging.info(f"Creating database directory: {self.db_path.parent}")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.label_cache: Dict[str, int] = {}
        self._aggregator_stop = threading.Event()
        self._aggregator_thread = None
        logging.info(f"Database initialized at path: {self.db_path}")


    def setup(self) -> None:
        """
        Sets up the database, creating tables and indices if they don't exist.
        """
        db_exists = self.db_path.exists()

        if not db_exists:
            logging.info(f"Creating new database: {self.db_path}")
        else:
            logging.debug(f"Using existing database: {self.db_path}")

        logging.debug("Setting up database tables and indices...")

        with sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT) as conn:
            cursor = conn.cursor()

            # Enable WAL + busy timeout
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout = 5000;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS labels (
                    label_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label STRING UNIQUE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS readings (
                    label_id INTEGER,
                    timestamp INTEGER,
                    value REAL,
                    FOREIGN KEY(label_id) REFERENCES labels(label_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS energy_hourly (
                    hour_start INTEGER PRIMARY KEY,
                    kwh REAL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_labels_label_index
                ON labels(label)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_timestamp
                ON readings(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_label_id
                ON readings(label_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_label_id_timestamp
                ON readings(label_id, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_energy_hourly_hour
                ON energy_hourly (hour_start)
            """)

        logging.debug("Database setup complete.")


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
        cursor.execute("SELECT label_id FROM labels WHERE label=?", (label,))
        row = cursor.fetchone()

        if row:
            label_id = row[0]
        else:
            # Not in DB, so create it
            cursor.execute("INSERT INTO labels(label) VALUES (?)", (label,))
            label_id = cursor.lastrowid
            logging.debug(f"Created new label '{label}' with id {label_id}")

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
            with sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT) as conn:
                cursor = conn.cursor()
                label_id = self._get_or_create_label_id(cursor, label)

                # Insert the actual reading
                cursor.execute(
                    "INSERT INTO readings(label_id, timestamp, value) VALUES (?,?,?)",
                    (label_id, int(timestamp), value)
                )
                # The 'with' block automatically commits on success

            logging.debug(
                f"Inserted reading: {label} ({label_id}), {value}"
            )

        except sqlite3.Error as e:
            logging.error(f"Failed to log data for label '{label}': {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred in log_data: {e}")


    def get_all_labels(self):
        try:
            with sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT label FROM labels ORDER BY label ASC")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logging.error(f"Failed to fetch labels: {e}")
            return []


    def get_total_energy(self) -> float:
        try:
            with sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT SUM(kwh) FROM energy_hourly")
                row = cursor.fetchone()
                return float(row[0]) if row and row[0] else 0.0
        except Exception as e:
            logging.error(f"Failed to compute total energy: {e}")
            return 0.0


    # ---------------- Aggregation logic ----------------
    def fetch_hour_range_to_process(self, cursor: sqlite3.Cursor) -> Optional[int]:
        """
        Return the epoch second of the first hour_start we should process next,
        or None if there's nothing to process.

        Strategy:
        - Find the minimum reading timestamp in readings.
        - Find the maximum hour_start already in energy_hourly.
        - Start from next hour after max(earliest reading hour, last aggregated hour + 1h)
        """
        cursor.execute("SELECT MIN(timestamp) FROM readings")
        row = cursor.fetchone()
        if not row or not row[0]:
            return None

        min_ts = int(row[0])
        first_hour = min_ts - (min_ts % 3600)

        cursor.execute("SELECT MAX(hour_start) FROM energy_hourly")
        row = cursor.fetchone()
        last_hour_done = int(row[0]) if (row and row[0]) else None

        if last_hour_done is None:
            return first_hour

        return last_hour_done + 3600

    def aggregate_one_hour(self, cursor: sqlite3.Cursor, hour_start: int) -> Optional[float]:
        """
        Aggregate a single hour [hour_start, hour_start+3600) and return kwh inserted,
        or None if there were no readings in that hour.
        """
        hour_end = hour_start + 3600

        cursor.execute("""
            SELECT timestamp,
                   CASE
                       WHEN labels.label LIKE 'efergy_h1%%'
                           THEN readings.value / 1000.0
                       WHEN labels.label LIKE 'efergy_h2%%'
                           THEN ((readings.value / 100.0) * 230 * 0.6) / 10000.0
                       WHEN labels.label LIKE 'efergy_h3%%'
                           THEN (readings.value / 10.0) / 1000.0
                       ELSE readings.value / 1000.0
                   END AS kw
            FROM readings
            INNER JOIN labels ON labels.label_id = readings.label_id
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
        """, (hour_start, hour_end))

        rows = cursor.fetchall()
        if not rows:
            return None

        kwh_total = 0.0
        for i in range(len(rows) - 1):
            ts, kw = rows[i]
            next_ts = rows[i + 1][0]
            interval_sec = next_ts - ts
            kwh_total += kw * (interval_sec / 3600)

        # Last reading (assume same interval as previous)
        if len(rows) > 1:
            last_ts, last_kw = rows[-1]
            interval_sec = rows[-1][0] - rows[-2][0]
            kwh_total += last_kw * (interval_sec / 3600)

        # Store hourly total
        cursor.execute(
            "INSERT OR REPLACE INTO energy_hourly(hour_start, kwh) VALUES (?, ?)",
            (hour_start, kwh_total)
        )
        return kwh_total


    def aggregate_hours(self, limit_hours: int = 1000) -> int:
        """
        Aggregate up to `limit_hours` past unprocessed full hours.

        Returns the number of hours processed.
        """
        now = int(time.time())
        processed = 0

        try:
            with sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT) as conn:
                cursor = conn.cursor()

                next_hour = self.fetch_hour_range_to_process(cursor)
                if next_hour is None:
                    return 0

                # Don't aggregate the current partial hour
                cutoff = now - (now % 3600)

                while next_hour + 3600 <= cutoff and processed < limit_hours:
                    # If an entry already exists (defensive), skip
                    cursor.execute(
                        "SELECT 1 FROM energy_hourly WHERE hour_start = ?",
                        (next_hour,)
                    )
                    if cursor.fetchone():
                        next_hour += 3600
                        continue

                    # Do the work for this hour
                    kwh = self.aggregate_one_hour(cursor, next_hour)

                    if kwh is not None:
                        readable = time.strftime('%Y-%m-%d %H:%M', time.localtime(next_hour))
                        logging.info(f"[AGG] Hour {readable} => {kwh:.5f} kWh")
                    else:
                        logging.debug(
                            f"[AGG] Hour {time.strftime('%Y-%m-%d %H:%M', time.localtime(next_hour))} had no readings"
                        )

                    processed += 1
                    next_hour += 3600

                conn.commit()

        except Exception:
            logging.exception("Error during aggregation")

        return processed
