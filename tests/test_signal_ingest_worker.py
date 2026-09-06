"""End-to-end test of the signal ingest worker loop.

The other ingest tests exercise _parse_fpv_alert and the allow-list
constants directly. Nothing drove the worker loop itself, which is where
the signal record is assembled and handed to the sinks - so a record built
from a name bound later in the loop passed every test while, at runtime,
dropping the first alert and giving later ones the previous alert's Net ID.

This drives the real worker over a real ZMQ socket with stub sinks.
"""

import json
import threading
import time

import pytest

zmq = pytest.importorskip("zmq")

from ingest import signal_ingest


class _StubMessenger:
    def __init__(self):
        self.sent = []

    def send_cot(self, cot):
        self.sent.append(cot)


class _StubSignalManager:
    def __init__(self):
        self.signals = []

    def add_signal(self, signal):
        self.signals.append(signal)


def _sik_alert(net_id, source="sik_confirm", chip_family="type-a"):
    return [{
        "Basic ID": {"id": f"900FHSS-NETID-{net_id}", "description": "SiK"},
        "Location/Vector Message": {
            "latitude": 33.5257, "longitude": -82.2204,
            "geodetic_altitude": "100.0 m",
        },
        "Self-ID Message": {"text": f"RF contact Net ID {net_id}"},
        "Signal Info": {
            "source": source,
            "signal_type": "gfsk_fhss",
            "center_hz": 915000000,
            "net_id": net_id,
            "baud_rate": 64000,
            "rssi": -12.5,
            "chip_family": chip_family,
            "has_mavlink": False,
        },
    }]


def _run_worker_with(alerts, port=5599):
    """Publish alerts to a real socket and collect what the worker records."""
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://127.0.0.1:{port}")

    messenger = _StubMessenger()
    manager = _StubSignalManager()
    thread, stop = signal_ingest.start_signal_worker(
        zmq_host="127.0.0.1", zmq_port=port,
        cot_messenger=messenger, signal_manager=manager,
        min_send_interval=0.0,
    )
    try:
        time.sleep(0.4)  # let SUB connect before PUB sends
        for a in alerts:
            pub.send_string(json.dumps(a))
            time.sleep(0.15)
        deadline = time.time() + 3.0
        while time.time() < deadline and len(manager.signals) < len(alerts):
            time.sleep(0.05)
    finally:
        stop.set()
        thread.join(timeout=3.0)
        pub.close(0)
        ctx.term()
    return manager.signals


def test_worker_records_the_first_alert():
    """Regression: the first alert was lost when the record referenced a
    name the loop had not bound yet."""
    signals = _run_worker_with([_sik_alert(25)])
    assert len(signals) == 1
    assert signals[0]["net_id"] == 25


def test_each_alert_keeps_its_own_net_id():
    """Regression: a record built from a stale loop variable gave the
    second alert the first alert's Net ID."""
    signals = _run_worker_with([_sik_alert(25), _sik_alert(77)], port=5600)
    assert [s["net_id"] for s in signals] == [25, 77]


def test_worker_records_callsign_and_chip_family():
    signals = _run_worker_with([_sik_alert(77, chip_family="type-b")], port=5601)
    assert signals[0]["callsign"] == "900FHSS-NETID-77"
    assert signals[0]["chip_family"] == "type-b"
    assert signals[0]["source"] == "sik_confirm"
