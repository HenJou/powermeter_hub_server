import pytest
import http.client
import threading
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
    # Use a random free port
    server_address = ('127.0.0.1', 0)
    httpd = EfergyHTTPServer(server_address, FakeEfergyServer, mock_db, mock_mqtt)
    port = httpd.server_port
    
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    
    yield ('127.0.0.1', port)
    
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_get_key(test_server):
    host, port = test_server
    conn = http.client.HTTPConnection(host, port)
    conn.request("GET", "/get_key.html")
    response = conn.getresponse()
    assert response.status == 200
    assert response.read() == b"TT|a1bCDEFGHa1zZ\n"


def test_check_key(test_server):
    host, port = test_server
    conn = http.client.HTTPConnection(host, port)
    conn.request("GET", "/check_key.html")
    response = conn.getresponse()
    assert response.status == 200
    assert response.read() == b"success"


def test_404(test_server):
    host, port = test_server
    conn = http.client.HTTPConnection(host, port)
    conn.request("GET", "/unknown")
    response = conn.getresponse()
    assert response.status == 404


def test_post_h2(test_server, mock_db, mock_mqtt):
    host, port = test_server
    conn = http.client.HTTPConnection(host, port)
    
    # Example h2 payload (from test_payload_parser.py or similar)
    # The payload parser expects a certain format.
    payload = '741459|1|EFCT|P1,2479.98'
    headers = {"Content-Type": "text/plain", "Content-Length": len(payload)}
    
    conn.request("POST", "/h2", body=payload, headers=headers)
    response = conn.getresponse()
    
    assert response.status == 200
    assert response.read() == b"success"
    
    # Verify DB call
    # parse_sensor_payload("741459|1|EFCT|P1,2479.98", "h2") should return something that results in log_data
    assert mock_db.log_data.called
    assert mock_mqtt.publish_power.called


def test_post_recjson_h1(test_server, mock_db, mock_mqtt):
    host, port = test_server
    conn = http.client.HTTPConnection(host, port)
    
    # h1 sends json=<data>
    payload = 'json=AABBCCDDDDDD|694851F9|v1.0.1|{"data":[[610965,"mA","E1",33314,0,0,65535]]}|39ef0bdc14b52df375b79555f059b52f'
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": len(payload)}
    
    conn.request("POST", "/recjson", body=payload, headers=headers)
    response = conn.getresponse()
    
    assert response.status == 200
    assert response.read() == b"success"
    
    assert mock_db.log_data.called
    assert mock_mqtt.publish_power.called


def test_post_ping(test_server):
    host, port = test_server
    conn = http.client.HTTPConnection(host, port)
    
    payload = '123456|789012'
    headers = {"Content-Type": "application/eh-ping", "Content-Length": len(payload)}
    
    conn.request("POST", "/any", body=payload, headers=headers)
    response = conn.getresponse()
    
    assert response.status == 200
    assert response.read() == b"success"
