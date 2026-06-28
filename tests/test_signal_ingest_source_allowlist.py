"""Tests for the Signal Info.source allow-list in signal_ingest.

The ingest worker filters incoming alerts on the JSON
`Signal Info.source` field. Each known source value maps to a
distinct trust tier; unknown values are dropped. These tests assert
membership behavior on the constants and parse-side behavior on the
wire-format message shape.
"""

from ingest import signal_ingest


def _build_sik_alert_message(source, has_mavlink, net_id=25,
                              lat="1.234567", lon="2.345678",
                              center_hz=916000000):
    """Build a synthetic Signal Info JSON message matching the publisher's
    sik_alert layout (array of single-key dicts: Basic ID, Location/Vector
    Message, Self-ID Message, Signal Info)."""
    return [
        {"Basic ID": {
            "protocol_version": "F3411.22",
            "id_type": "Signal",
            "ua_type": 2,
            "id": f"900FHSS-NETID-{net_id}",
            "RSSI": -50,
            "transport": "ISM-FHSS",
            "frequency_mhz": center_hz // 1_000_000,
        }},
        {"Location/Vector Message": {
            "protocol_version": "F3411.22",
            "op_status": "Airborne",
            "latitude": lat,
            "longitude": lon,
            "geodetic_altitude": "100.000000 m",
        }},
        {"Self-ID Message": {
            "protocol_version": "F3411.22",
            "text_type": "Text",
            "text": f"MAVLink drone Net ID {net_id} (64 kbps) on 900MHz FHSS",
        }},
        {"Signal Info": {
            "source": source,
            "signal_type": "gfsk_fhss",
            "has_mavlink": has_mavlink,
            "center_hz": center_hz,
            "net_id": net_id,
            "baud_rate": 64000,
            "rssi": -50.0,
            "fhss_channels": 3,
        }},
    ]


# ---- Allow-list membership ----------------------------------------------

def test_known_sources_in_accepted():
    for src in (
        "confirm",
        "sik_confirm",
        "sik_alive_no_gps",
        "sik_reasm",
        "sik_gps_repaired",
        "sik_position_hint",
    ):
        assert src in signal_ingest._ACCEPTED_SIGNAL_SOURCES, src


def test_energy_source_in_ignored_not_accepted():
    assert "energy" in signal_ingest._IGNORED_SIGNAL_SOURCES
    assert "energy" not in signal_ingest._ACCEPTED_SIGNAL_SOURCES


def test_substring_attack_rejected():
    """A label that contains 'confirm' as a substring but isn't a real
    source value must NOT be accepted by the allow-list."""
    fake = "sik_confirm_lookalike_butnot"
    assert fake not in signal_ingest._ACCEPTED_SIGNAL_SOURCES


def test_unknown_source_rejected():
    """Any string not explicitly in the allow-list is rejected."""
    assert "sik_future_unknown_label" not in signal_ingest._ACCEPTED_SIGNAL_SOURCES
    assert "" not in signal_ingest._ACCEPTED_SIGNAL_SOURCES


# ---- Parse-side message shape ------------------------------------------

def test_parse_sik_reasm_alert_carries_has_mavlink_true():
    msg = _build_sik_alert_message("sik_reasm", has_mavlink=True)
    parsed = signal_ingest._parse_fpv_alert(msg)
    assert parsed is not None
    assert parsed["source"] == "sik_reasm"
    assert parsed["has_mavlink"] is True
    assert parsed["net_id"] == 25


def test_parse_sik_gps_repaired_alert_carries_has_mavlink_true():
    msg = _build_sik_alert_message("sik_gps_repaired", has_mavlink=True)
    parsed = signal_ingest._parse_fpv_alert(msg)
    assert parsed is not None
    assert parsed["source"] == "sik_gps_repaired"
    assert parsed["has_mavlink"] is True
    assert parsed["net_id"] == 25


def test_parse_sik_confirm_alert_carries_has_mavlink_false():
    msg = _build_sik_alert_message("sik_confirm", has_mavlink=False)
    parsed = signal_ingest._parse_fpv_alert(msg)
    assert parsed is not None
    assert parsed["source"] == "sik_confirm"
    assert parsed["has_mavlink"] is False
    assert parsed["net_id"] == 25


def test_parse_sik_alive_no_gps_alert_carries_has_mavlink_false():
    msg = _build_sik_alert_message("sik_alive_no_gps", has_mavlink=False)
    parsed = signal_ingest._parse_fpv_alert(msg)
    assert parsed is not None
    assert parsed["source"] == "sik_alive_no_gps"
    assert parsed["has_mavlink"] is False
    assert parsed["net_id"] == 25
