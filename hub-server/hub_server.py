"""
A fake Efergy sensor data server, updated for Python 3.

This server emulates the sensornet.info API endpoints for an
Efergy hub, logging incoming sensor data to a sqlite database.
"""
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Type
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from db import Database


class EfergyHTTPServer(HTTPServer):
    """
    A custom HTTPServer subclass that holds the database instance.
    This allows the request handler to access the database instance
    via `self.server.database`.
    """
    def __init__(self,
                 server_address: tuple[str, int],
                 RequestHandlerClass: Type[SimpleHTTPRequestHandler],
                 database: Database,
                 bind_and_activate: bool = True):

        # Store the database instance *before* calling super_init
        # so it's available if the handler needs it during init.
        self.database = database
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)


class FakeEfergyServer(SimpleHTTPRequestHandler):
    """
    Pretends to be a sensornet.info server.
    It accesses the database instance via `self.server.database`.

    Note: self.server will be an instance of EfergyHTTPServer.
    """
    protocol_version = 'HTTP/1.1'

    def log_request_info(self):
        """Helper to log request details using f-strings."""
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)
        client_ip, client_port = self.client_address

        logging.debug(f"Request: {self.command} {self.path}")
        logging.debug(f"Query params: {query}")
        logging.debug(f"Headers: {dict(self.headers)}")
        logging.debug(f"Client: {client_ip}:{client_port}")

    def _send_response(self, code: int, content_bytes: bytes, content_type: str = "text/html; charset=UTF-8"):
        """Helper to send a complete response."""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content_bytes)))
        self.end_headers()
        self.wfile.write(content_bytes)

    def do_GET(self):
        """Handles GET requests for key checking."""
        try:
            self.log_request_info()
            parsed_url = urlparse(self.path)

            code = 200

            if parsed_url.path == '/get_key.html':
                content_bytes = b"TT|a1bCDEFGHa1zZ\n"
            elif parsed_url.path == '/check_key.html':
                content_bytes = b"\n"
            else:
                code = 404
                content_bytes = b"Not Found"

            self._send_response(code, content_bytes)

        except Exception as e:
            logging.error(f"Exception in GET: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")

        self.close_connection = True


    def do_POST(self):
        """Handles POST requests with sensor data."""
        try:
            self.log_request_info()
            parsed_url = urlparse(self.path)

            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                logging.warning("POST request with no content length or 0.")
                self._send_response(411, b"Content-Length required")
                return

            post_data_bytes = self.rfile.read(content_length)
            logging.debug(f"POST body:\n{post_data_bytes.decode('utf-8', 'ignore')}")

            if parsed_url.path in ['/h2', '/h3']:
                db = getattr(self.server, 'database', None)

                if not db:
                    logging.error("Database not initialized on server instance.")
                    self._send_response(500, b"Server Error: DB not configured")
                    return

                hub_version = parsed_url.path.strip('/')
                self._process_sensor_data(post_data_bytes, hub_version, db)

            # Always send a 200 OK for Efergy compatibility
            self._send_response(200, b"")

        except Exception as e:
            logging.error(f"Exception in POST: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")

        self.close_connection = True

    def _process_sensor_data(self, post_data_bytes: bytes, hub_version: str, database: Database):
        """Parses and logs sensor data from the POST body."""
        try:
            http_data_str = post_data_bytes.decode('utf-8')
            sensor_lines = http_data_str.split('\r\n')
        except UnicodeDecodeError as e:
            logging.error(f"Failed to decode POST body: {e}")
            return

        for line in sensor_lines:
            if not line:  # Skip empty lines
                continue

            try:
                data = line.split('|')
                if len(data) < 4:
                    logging.warning(f"Malformed line, skipping: '{line}'")
                    continue

                sid = data[0]
                if sid == '0':  # Skip hub status lines
                    continue

                port_and_value = data[3]
                value_str = port_and_value.split(',')[1]
                value = float(value_str)
                label = f'efergy_{hub_version}_{sid}'

                logging.debug(f"Logging sensor: {label}, Value: {value}")
                database.log_data(label, value)

            except (IndexError, ValueError, TypeError) as e:
                logging.warning(f"Failed to parse line '{line}': {e}")
            except Exception as e:
                logging.error(f"Unexpected error processing line '{line}': {e}")


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
        database=database
    )

    logging.info(f"Serving HTTP on {host} port {port}...")

    try:
        database.start_aggregator(interval_sec=300)
    except Exception:
        logging.exception("Failed to start aggregator thread")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server shutting down...")
        httpd.server_close()


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    # Adjust this path as needed for your project structure
    DB_FILE_PATH = Path(__file__).resolve().parent / "data/readings.db"

    # Initialize the database
    db_instance = Database(DB_FILE_PATH)

    # Create tables and indices
    db_instance.setup()

    # Start the server, passing the database instance
    run_server(db_instance)