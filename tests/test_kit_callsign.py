#!/usr/bin/env python3
"""
Tests for the optional kit callsign.

The callsign is a display name for the kit's own CoT marker. The kit id
(wardragon-<serial>) must stay the identity everywhere: the CoT uid, the
/status kit_id and uid fields, SeenBy, MQTT topics and Lattice ids. A blank
or invalid callsign must behave exactly like before the setting existed.
"""

import configparser
import logging
from pathlib import Path

import pytest
from lxml import etree

from core.system_status import SystemStatus
from utils.config import parse_kit_callsign
from utils.cot_builder import build_system_status_cot


def _status(callsign=None):
    return SystemStatus(serial_number="TEST123", lat=1.5, lon=2.5, alt=10.0,
                        callsign=callsign)


# ─── parse_kit_callsign ──────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["Alpha 1", "WD-North", "kit.2", "A", "a_b", "X" * 32])
def test_valid_callsigns_are_kept(value):
    assert parse_kit_callsign(value) == value


def test_surrounding_whitespace_is_trimmed():
    assert parse_kit_callsign("  Alpha 1  ") == "Alpha 1"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_means_use_the_kit_id(value):
    assert parse_kit_callsign(value) is None


@pytest.mark.parametrize("value", [
    "50% done",       # configparser interpolation
    "a;b", "a#b",     # ini comment characters
    "line\nbreak",
    "X" * 33,         # too long
    "-dash-first", ".dot-first",
    "<tag>", 'quote"', "café",
])
def test_invalid_callsigns_fall_back_to_the_kit_id(value, caplog):
    with caplog.at_level(logging.WARNING, logger="utils.config"):
        assert parse_kit_callsign(value) is None
    assert any("kit_callsign" in r.getMessage() for r in caplog.records)


# ─── SystemStatus ────────────────────────────────────────────────────────

def test_default_callsign_is_the_kit_id():
    s = _status()
    assert s.id == "wardragon-TEST123"
    assert s.callsign == "wardragon-TEST123"
    d = s.to_dict()
    assert d["uid"] == "wardragon-TEST123"
    assert d["callsign"] == "wardragon-TEST123"


def test_custom_callsign_does_not_change_the_kit_id():
    s = _status("Alpha 1")
    assert s.id == "wardragon-TEST123"
    d = s.to_dict()
    assert d["uid"] == "wardragon-TEST123"
    assert d["callsign"] == "Alpha 1"


# ─── System CoT ──────────────────────────────────────────────────────────

def _contact_and_uid(status):
    root = etree.fromstring(build_system_status_cot(status, stale_seconds=600.0))
    return root.get("uid"), root.find("detail").find("contact").get("callsign")


def test_cot_without_callsign_is_unchanged():
    assert _contact_and_uid(_status()) == ("wardragon-TEST123", "wardragon-TEST123")


def test_cot_callsign_changes_only_the_contact_name():
    uid, callsign = _contact_and_uid(_status("Alpha 1"))
    assert uid == "wardragon-TEST123"   # what ATAK and the plugin key on
    assert callsign == "Alpha 1"


# ─── Shipped config.ini ──────────────────────────────────────────────────

def test_shipped_config_has_a_blank_callsign_and_parses():
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).resolve().parent.parent / "config.ini")
    settings = dict(cfg["SETTINGS"])  # raises on any interpolation problem
    assert "kit_callsign" in settings
    assert parse_kit_callsign(settings["kit_callsign"]) is None
