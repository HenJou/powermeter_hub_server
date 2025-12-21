"""
A fake Efergy sensor data server, updated for Python 3.

This server emulates the sensornet.info API endpoints for an
Efergy hub, logging incoming sensor data to a sqlite database.
"""
import json
import logging
import socket
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Type
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from database import Database
from mqtt_manager import MQTTManager
from aggregator import Aggregator
from config import (
    SERVER_PORT, LOG_LEVEL
)

POWER_FACTOR = 0.6
MAINS_VOLTAGE = 230

class EfergyHTTPServer(HTTPServer):
    """
    A custom HTTPServer subclass that holds the database instance.
    This allows the request handler to access the database instance
    via `self.server.database`.
    """
    def __init__(self,
                 server_address: tuple[str, int],
                 request_handler_class: Type[SimpleHTTPRequestHandler],
                 database: Database,
                 mqtt_manager: MQTTManager,
                 bind_and_activate: bool = True):

        # Store the database instance *before* calling super_init
        # so it's available if the handler needs it during init.
        self.database = database
        self.mqtt_manager = mqtt_manager
        self.published_discovery = set()
        super().__init__(server_address, request_handler_class, bind_and_activate)


class FakeEfergyServer(SimpleHTTPRequestHandler):
    """
    Pretends to be a sensornet.info server.
    It accesses the database instance via `self.server.database`.

    Note: self.server will be an instance of EfergyHTTPServer.
    """
    protocol_version = "HTTP/1.1"
    server: "EfergyHTTPServer"

    def log_request_info(self):
        """Helper to log request details using f-strings."""
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)
        client_ip, client_port = self.client_address

        logging.debug("=" * 80)
        logging.debug(f">>> REQUEST: {self.command} {self.path}")
        logging.debug(f">>> Query params: {query}")
        logging.debug(f">>> Headers: {dict(self.headers)}")
        logging.debug(f">>> Client: {client_ip}:{client_port}")


    def _send_response(self, code: int, content_bytes: bytes, content_type: str = "text/html; charset=UTF-8"):
        """Helper to send a complete response."""
        try:
            response_preview = content_bytes.decode('utf-8', 'ignore')[:200] if content_bytes else ''
            logging.debug(f"<<< RESPONSE: {code} | Length: {len(content_bytes)} | Content: {response_preview!r}")

            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content_bytes)))
            self.end_headers()

            try:
                self.wfile.write(content_bytes)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                logging.debug(
                    f"Client disconnected while sending response "
                    f"(BrokenPipe): {e} — path: {self.path}"
                )
                return

        except Exception as e:
            logging.error(f"Failed during response send: {e}")


    def do_GET(self):
        """Handles GET requests for key checking."""
        try:
            self.log_request_info()
            parsed_url = urlparse(self.path)

            code = 200

            if parsed_url.path == "/get_key.html":
                content_bytes = b"TT|a1bCDEFGHa1zZ\n"
            # TO_CONFIRM: Just a pure guess that "E1" refers to the hub v1 type (?)
            elif parsed_url.path == "/check_key.html" and "E1" in parse_qs(parsed_url.query).get("p", []):
                content_bytes = b"success"
            elif parsed_url.path == "/check_key.html":
                content_bytes = b"\n"
            else:
                code = 404
                content_bytes = b"Not Found"

            self._send_response(code, content_bytes)

        except Exception as e:
            logging.error(f"Exception in GET: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")


    def do_POST(self):
        """Handles POST requests with sensor data."""
        try:
            self.log_request_info()
            parsed_url = urlparse(self.path)

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                logging.warning("POST request with no content length or 0.")
                self._send_response(411, b"Content-Length required")
                return

            post_data_bytes = self.rfile.read(content_length)
            logging.debug(f">>> POST body: {post_data_bytes.decode('utf-8', 'ignore')}")

            db = getattr(self.server, "database", None)
            if not db:
                logging.error("Database not initialized on server instance.")
                self._send_response(500, b"Server Error: DB not configured")
                return

            content_type = self.headers.get("Content-Type", "")
            if content_type == "application/eh-ping":
                sensor_ids = post_data_bytes.decode("utf-8").strip().split("|")
                logging.debug(f"Received ping from sensors: {sensor_ids}")
            elif parsed_url.path in ["/h2", "/h3"]:
                hub_version = parsed_url.path.strip("/")
                self.process_sensor_data(post_data_bytes, hub_version, db)
            elif parsed_url.path == '/recjson':
                # v1 hub sends URL-encoded form data: json=<pipe-delimited-data>
                hub_version = 'HH-1.0-NA'
                decoded_body = post_data_bytes.decode('utf-8', 'ignore')
                if decoded_body.startswith('json='):
                    # Extract the actual sensor data
                    sensor_data = decoded_body[5:]  # Skip 'json='
                    self.process_sensor_data(sensor_data.encode('utf-8'), hub_version, db)
                else:
                    logging.warning(f"Unexpected /recjson body format: {decoded_body[:100]}")
            else:
                logging.warning(f"Unknown POST path or content-type: {self.path} / {content_type}")

            self._send_response(200, b"success" if parsed_url.path == '/recjson' else b"")

        except Exception as e:
            logging.error(f"Exception in POST: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")


    def process_sensor_data(self, post_data_bytes: bytes, hub_version: str, database: Database):
        """Parses and logs sensor data from the POST body."""
        try:
            http_data_str = post_data_bytes.decode("utf-8")
            sensor_lines = http_data_str.split("\r\n")
        except UnicodeDecodeError as e:
            logging.error(f"Failed to decode POST body: {e}")
            return

        for line in sensor_lines:
            if not line:  # Skip empty lines
                continue

            try:
                data = line.split("|")
                if len(data) < 4:
                    logging.warning(f"Malformed line, skipping: '{line}'")
                    continue

                sid = data[0]
                if sid == "0":  # Skip hub status lines
                    continue

                data_type = data[2].upper()

                # --- EFMS1 Multi-sensor debug logging ---
                if data_type.startswith("EFMS"):
                    raw_block = data[3]  # Example: "M,64.00&T,0.00&L,0.00"
                    rssi_val = None

                    # Some packets include RSSI after an additional pipe
                    if len(data) >= 5:
                        try:
                            rssi_val = float(data[4])
                        except ValueError:
                            pass

                    # Split metrics by "&" and log
                    metrics = raw_block.split("&")
                    for metric in metrics:
                        try:
                            key, val = metric.split(",", 1)
                            key = key.strip().upper()
                            num = float(val)
                            logging.debug(f"[EFMS1] SID={sid}, Metric={key}, Value={num}")
                        except Exception as e:
                            logging.warning(f"[EFMS1] Failed to parse metric '{metric}': {e}")

                    if rssi_val is not None:
                        logging.debug(f"[EFMS1] SID={sid}, RSSI={rssi_val}")

                    # Skip normal processing for EFMS1
                    continue

                if hub_version == 'HH-1.0-NA':
                    # Tom's processing for V1 hub.
                    # sensor_lines = 'json=<hub MAC address>|<8-digit number>|v1.0.1|{"data":[[548338,"mA","E1",14768,0,0,65535]]}|<32-digit hex value>'

                    # Actual version (e.g. "v1.0.1")
                    actual_version = data[2] if data[2].startswith('v') else 'v1'
                    # MAC address == sensor ID
                    sid = data[0]
                    jdata = json.loads(data[3])
                    milliamps = float(jdata['data'][0][3])
                    # V1: *Milliamps* values, converted to watts here
                    watts = MAINS_VOLTAGE * milliamps / 1000 * POWER_FACTOR
                    value = round(watts, 3)
                    # Override hub_version for label naming
                    label = f"efergy_h1_{actual_version}_{sid}"
                else:
                    # --- Normal CT sensor processing for v2/v3 ---
                    # V2: *Raw sensor* values, converted to watts during aggregation
                    # V3: *Pre-scaled* values, converted to watts during aggregation
                    port_and_value = data[3]
                    value_str = port_and_value.split(",")[1]
                    value = float(value_str)
                    sid = data[0]
                    label = f"efergy_{hub_version}_{sid}"

                logging.debug(f"Logging sensor: {label}, raw: {value}")
                database.log_data(label, value)

                # Publish power reading
                self.server.mqtt_manager.publish_power(label, sid, hub_version, value)

            except (IndexError, ValueError, TypeError) as e:
                logging.warning(f"Failed to parse line '{line}': {e}")
            except Exception as e:
                logging.error(f"Unexpected error processing line '{line}': {e}")


    def log_message(self, format, *args):
        """
        Suppress default logging
        """
        return


def run_server(database: Database, host: str = '0.0.0.0', port: int = 5000):
    """
    Starts the HTTP server.

    Args:
        database: The initialized Database instance.
        host: The host address to bind to.
        port: The port to listen on.
    """
    server_address = (host, port)

    httpd = EfergyHTTPServer(
        server_address,
        FakeEfergyServer,
        database=database,
        mqtt_manager=mqtt_manager,
    )

    logging.info(f"Serving HTTP on {host} port {port}...")

    try:
        aggregator = Aggregator(db_instance, mqtt_manager)
        aggregator.start()
    except Exception:
        logging.exception("Failed to start aggregator thread")

    # Publish startup discovery for all known sensors
    mqtt_manager.publish_startup_discovery(database.get_all_labels())

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server shutting down...")
        httpd.server_close()


if __name__ == '__main__':
    # Configure logging
    logging_level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=logging_level,
        format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
    )

    # Adjust this path as needed for your project structure
    DB_FILE_PATH = Path(__file__).resolve().parent / "data/readings.db"

    # Initialize the database
    db_instance = Database(DB_FILE_PATH)

    # Create tables and indices
    db_instance.setup()

    # Initialize MQTT
    mqtt_manager = MQTTManager()

    # Start the server, passing the database instance
    run_server(db_instance, port=SERVER_PORT)