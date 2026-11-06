#!/usr/bin/env python3
"""
/status over the real API server.

kit_id_provider and the other providers are plain functions stored on the
handler class. Read through the instance, a function becomes a bound method
and gets called with the handler as an argument, which failed silently and
left kit_id out of /status. Consumers fell back to uid, so it went unnoticed.
"""

import json
import socket
import threading
import urllib.request

import pytest

from api.api_server import serve_api
from core.system_status import SystemStatus


@pytest.fixture
def api():
    servers = []

    def start(status, kit_id):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = serve_api(None, lambda: status, lambda: kit_id, host="127.0.0.1", port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return lambda path: json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}"))

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def test_status_includes_kit_id(api):
    get = api(SystemStatus(serial_number="TEST123", lat=1.5, lon=2.5, alt=10.0), "wardragon-TEST123")
    status = get("/status")
    assert status["kit_id"] == "wardragon-TEST123"
    assert status["uid"] == "wardragon-TEST123"


def test_status_callsign_is_separate_from_kit_id(api):
    get = api(SystemStatus(serial_number="TEST123", lat=1.5, lon=2.5, alt=10.0, callsign="Alpha 1"),
              "wardragon-TEST123")
    status = get("/status")
    assert status["kit_id"] == "wardragon-TEST123"
    assert status["uid"] == "wardragon-TEST123"
    assert status["callsign"] == "Alpha 1"
