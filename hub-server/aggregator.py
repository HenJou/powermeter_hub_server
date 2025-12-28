import logging
import threading
import time
from database import Database
from mqtt_manager import MQTTManager
from config import HISTORY_RETENTION_MONTHS


class Aggregator:
    def __init__(self, database: Database, mqtt_manager: MQTTManager, interval_sec=300):
        self.database = database
        self.mqtt_manager = mqtt_manager
        self.interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread = None
        self._last_truncation_ts = 0


    def aggregate_loop(self):
        """
        Start a background thread that runs aggregate_hours every interval_sec seconds.

        Idempotent: calling multiple times won't start multiple threads.
        """
        while not self._stop_event.is_set():
            try:
                # Perform history truncation check once per day
                if HISTORY_RETENTION_MONTHS > 0:
                    now = time.time()
                    if now - self._last_truncation_ts >= 86400:
                        self.database.truncate_old_data(HISTORY_RETENTION_MONTHS)
                        self._last_truncation_ts = now

                processed = self.database.aggregate_hours(limit_hours=1000)
                logging.debug(f"Aggregator processed {processed} hours")

                # Publish total energy to MQTT
                total_kwh = self.database.get_total_energy()
                self.mqtt_manager.publish_energy(total_kwh)

            except Exception:
                logging.exception("Unhandled exception in aggregator loop")
            # Sleep with wake-up on stop event
            self._stop_event.wait(self.interval_sec)
        logging.debug("Hourly aggregator thread stopping")


    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.aggregate_loop, name='hourly-aggregator', daemon=True)
        self._thread.start()


    def stop(self):
        """
        Signal the aggregator thread to stop and wait briefly.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
