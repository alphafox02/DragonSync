#!/usr/bin/env python3
"""
The kit callsign reaches MQTT / Home Assistant and Lattice as a display name
only. Topics, HA identifiers and unique_ids, the attrs "id" and the Lattice
entity id must be byte-for-byte the same with or without a callsign.
"""

import json

import pytest

from sinks.mqtt_sink import MqttSink
from sinks.lattice_sink import LatticeSink


class _FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload))


STATUS = {
    "serial_number": "TEST123",
    "gps_data": {"latitude": 1.5, "longitude": 2.5, "altitude": 10.0},
    "system_stats": {"cpu_usage": 5.0},
}


def _mqtt_publishes(callsign):
    sink = MqttSink.__new__(MqttSink)  # no broker connection
    sink.qos = 0
    sink.ha_enabled = True
    sink._ha_system_announced = False
    sink._sys_base = "wardragon/system"
    sink.ha_prefix = "homeassistant"
    sink.ha_device_base = "wardragon_drone"
    sink._kit_id_provider = lambda: "wardragon-TEST123"
    sink.kit_callsign = callsign
    sink.client = _FakeClient()
    sink.publish_system(STATUS)
    return sink.client.published


def _discovery(published):
    """topic -> parsed config for every HA discovery message."""
    return {t: json.loads(p) for t, p in published if t.startswith("homeassistant/")}


def _attrs(published):
    return next(json.loads(p) for t, p in published if t.endswith("/attrs"))


def test_mqtt_default_names_are_unchanged():
    published = _mqtt_publishes(None)
    tracker = next(c for t, c in _discovery(published).items() if "/device_tracker/" in t)
    assert tracker["name"] == "WarDragon wardragon-TEST123"
    assert tracker["device"]["name"] == "WarDragon wardragon-TEST123"
    attrs = _attrs(published)
    assert attrs["id"] == "wardragon-TEST123"
    assert attrs["callsign"] == "wardragon-TEST123"


def test_mqtt_callsign_changes_only_display_names():
    plain, named = _mqtt_publishes(None), _mqtt_publishes("Alpha 1")

    # Every topic is identical: nothing retained moves, no new HA device.
    assert [t for t, _ in plain] == [t for t, _ in named]

    plain_cfg, named_cfg = _discovery(plain), _discovery(named)
    for topic, cfg in named_cfg.items():
        assert cfg["unique_id"] == plain_cfg[topic]["unique_id"]
        assert cfg["device"]["identifiers"] == plain_cfg[topic]["device"]["identifiers"]
        assert cfg["device"]["name"] == "Alpha 1"

    tracker = next(c for t, c in named_cfg.items() if "/device_tracker/" in t)
    assert tracker["name"] == "Alpha 1"
    sensors = [c for t, c in named_cfg.items() if "/sensor/" in t]
    assert sensors and all(c["name"] == plain_cfg[t]["name"] for t, c in named_cfg.items() if "/sensor/" in t)

    attrs = _attrs(named)
    assert attrs["id"] == "wardragon-TEST123"
    assert attrs["callsign"] == "Alpha 1"


def _lattice(callsign):
    sink = LatticeSink.__new__(LatticeSink)  # no SDK / API needed for the alias
    sink.kit_callsign = callsign
    return sink


def test_lattice_default_alias_is_unchanged():
    assert _lattice(None)._kit_alias("TEST123") == "WarDragon TEST123"


def test_lattice_callsign_becomes_the_alias():
    assert _lattice("Alpha 1")._kit_alias("TEST123") == "Alpha 1"
