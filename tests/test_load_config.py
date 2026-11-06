#!/usr/bin/env python3
"""
load_config and '%' in config.ini.

configparser reads % as interpolation, so a plain % in any value (a password,
say) used to make load_config exit. It now falls back to reading values
literally. Every file that loaded before must give exactly the same values.
"""

import logging

import pytest

from utils.config import load_config


def _load(tmp_path, text):
    path = tmp_path / "config.ini"
    path.write_text(text, encoding="utf-8")
    return load_config(str(path))


def test_plain_values_are_unchanged(tmp_path):
    assert _load(tmp_path, "[SETTINGS]\nzmq_port = 4224\nmqtt_password = secret\n") == {
        "zmq_port": "4224", "mqtt_password": "secret"}


def test_escaped_percent_still_means_percent(tmp_path):
    assert _load(tmp_path, "[SETTINGS]\nmqtt_password = pa%%ss\n") == {"mqtt_password": "pa%ss"}


def test_interpolation_that_worked_before_still_works(tmp_path):
    values = _load(tmp_path, "[SETTINGS]\nbase = /opt/wd\ncerts = %(base)s/certs\n")
    assert values["certs"] == "/opt/wd/certs"


def test_plain_percent_no_longer_stops_dragonsync(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="utils.config"):
        values = _load(tmp_path, "[SETTINGS]\nmqtt_password = pa%ssw0rd\nlabel = 50%%\n")
    assert values == {"mqtt_password": "pa%ssw0rd", "label": "50%"}
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "mqtt_password" in messages
    assert "pa%ssw0rd" not in messages and "ssw0rd" not in messages  # never log the value


def test_missing_settings_section_is_still_empty(tmp_path):
    assert _load(tmp_path, "[other]\nx = 1\n") == {}
