"""
A fake Efergy sensor data server, updated for Python 3.

This server emulates the sensornet.info API endpoints for an
Efergy hub, logging incoming sensor data to a sqlite database.
"""
import logging
import socket
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Type
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from database import Database
from mqtt_manager import MQTTManager
from aggregator import Aggregator
from payload_parser import parse_sensor_payload
from __version__ import __version__
from config import (
    SERVER_PORT, LOG_LEVEL, MQTT_ENABLED, HA_DISCOVERY
)

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
            elif parsed_url.path == "/check_key.html":
                # Detect V1 hub by Host header pattern: [MAC].keys.sensornet.info
                # V2/V3 use: [MAC].[h2/h3].sensornet.info
                host_header = self.headers.get("Host", "")
                content_bytes = b"success"
                logging.debug(f"Key check from: {host_header}")
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
                hub_version = 'h1'
                decoded_body = post_data_bytes.decode('utf-8', 'ignore')
                if decoded_body.startswith('json='):
                    # Extract the actual sensor data
                    sensor_data = decoded_body[5:]  # Skip 'json='
                    self.process_sensor_data(sensor_data.encode('utf-8'), hub_version, db)
                else:
                    logging.warning(f"Unexpected /recjson body format: {decoded_body[:100]}")
            else:
                logging.warning(f"Unknown POST path or content-type: {self.path} / {content_type}")

            self._send_response(200, b"success")

        except Exception as e:
            logging.error(f"Exception in POST: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")


    def process_sensor_data(self, post_data_bytes: bytes, hub_version: str, database: Database):
        """Parses and logs sensor data from the POST body."""
        parsed_results = parse_sensor_payload(post_data_bytes, hub_version)

        for data in parsed_results:
            try:
                if data["type"] == "EFMS":
                    sid = data["sid"]
                    for key, num in data["metrics"]:
                        logging.debug(f"[EFMS1] SID={sid}, Metric={key}, Value={num}")
                    
                    if data["rssi"] is not None:
                        logging.debug(f"[EFMS1] SID={sid}, RSSI={data['rssi']}")
                else:
                    sid = data["sid"]
                    label = data["label"]
                    value = data["value"]
                    
                    logging.debug(f"Logging sensor: {label}, raw: {value}")
                    database.log_data(label, value)

                    # Publish power reading
                    self.server.mqtt_manager.publish_power(label, sid, hub_version, value)

            except Exception as e:
                logging.error(f"Unexpected error processing parsed data {data}: {e}")


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

    # Startup banner
    logging.info("=" * 60)
    logging.info("  Efergy Hub Server")
    logging.info(f"  Version: {__version__}")
    logging.info("=" * 60)
    logging.info(f"  Python: {sys.version.split()[0]}")
    logging.info(f"  Port: {SERVER_PORT}")
    logging.info(f"  MQTT: {'enabled' if MQTT_ENABLED else 'disabled'}")
    logging.info(f"  HA Discovery: {'enabled' if HA_DISCOVERY else 'disabled'}")
    logging.info("=" * 60)

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
