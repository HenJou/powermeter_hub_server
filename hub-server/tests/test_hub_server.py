import pytest
import http.client
import threading
import socket
from unittest.mock import MagicMock
from hub_server import EfergyHTTPServer, FakeEfergyServer

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_mqtt():
    return MagicMock()

@pytest.fixture
def test_server(mock_db, mock_mqtt):
    """
    Starts the HTTP server in a background thread and ensures clean shutdown.
    """
    server_address = ('127.0.0.1', 0)  # 0 = pick a free port
    httpd = EfergyHTTPServer(server_address, FakeEfergyServer, mock_db, mock_mqtt)
    port = httpd.server_port

    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()

    # Wait until the server socket is ready
    timeout = 1.0
    while timeout > 0:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                break
        except ConnectionRefusedError:
            timeout -= 0.1
    else:
        raise RuntimeError("Server failed to start")

    yield ('127.0.0.1', port)

    # Clean shutdown
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def http_request(host, port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def test_get_key(test_server):
    host, port = test_server
    status, data = http_request(host, port, "GET", "/get_key.html")
    assert status == 200
    assert data == b"TT|a1bCDEFGHa1zZ\n"


def test_check_key(test_server):
    host, port = test_server
    status, data = http_request(host, port, "GET", "/check_key.html")
    assert status == 200
    assert data == b"success"


def test_404(test_server):
    host, port = test_server
    status, data = http_request(host, port, "GET", "/unknown")
    assert status == 404


def test_post_h2(test_server, mock_db, mock_mqtt):
    host, port = test_server
    payload = b"741459|1|EFCT|P1,2479.98"
    headers = {"Content-Type": "text/plain", "Content-Length": str(len(payload))}

    status, data = http_request(host, port, "POST", "/h2", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"

    assert mock_db.log_data.called
    assert mock_mqtt.publish_power.called


def test_post_recjson_h1(test_server, mock_db, mock_mqtt):
    host, port = test_server
    payload = b'json=AABBCCDDDDDD|694851F9|v1.0.1|{"data":[[610965,"mA","E1",33314,0,0,65535]]}|39ef0bdc14b52df375b79555f059b52f'
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(payload))}

    status, data = http_request(host, port, "POST", "/recjson", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"

    assert mock_db.log_data.called
    assert mock_mqtt.publish_power.called


def test_post_ping(test_server):
    host, port = test_server
    payload = b"123456|789012"
    headers = {"Content-Type": "application/eh-ping", "Content-Length": str(len(payload))}

    status, data = http_request(host, port, "POST", "/any", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"
