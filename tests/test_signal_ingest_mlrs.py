"""Tests for mLRS (LoRa CSS) alert handling in signal_ingest.

mLRS is a frequency-hopping LoRa control link. DragonSig publishes it in
the same Signal Info envelope as SiK but identifies a link by its 16-bit
FrameSyncWord (`link_id`) rather than a Net ID, and splits presence from
position across two sources:

    mlrs_confirm   RF/link confirmation, no verified position
    mlrs_reasm     CRC-clean MAVLink position update

These tests pin the three properties that would silently break operator
visibility if regressed: both sources are accepted, positions bypass the
per-UID throttle, and one hopping link maps to one stable identity.
"""

from ingest import signal_ingest


def _build_mlrs_alert_message(source, has_mavlink, link_id=0x7C85,
                              lat="1.234567", lon="2.345678",
                              center_hz=920000000):
    """Synthetic message matching the publisher's mlrs_alert layout."""
    return [
        {"Basic ID": {
            "protocol_version": "F3411.22",
            "id_type": "Signal",
            "ua_type": 2,
            "id": f"MLRS-LINK-{link_id:04X}",
            "RSSI": 15,
            "transport": "LoRa-FHSS",
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
            "text": f"MAVLink drone Link {link_id:04X} (profile-a) "
                    "on mLRS 500 kHz FHSS",
        }},
        {"Signal Info": {
            "source": source,
            "signal_type": "lora_css",
            "has_mavlink": has_mavlink,
            "center_hz": center_hz,
            "bandwidth_hz": 500000.0,
            "link_id": link_id,
            "crc_repaired": False,
            "profile": "profile-a",
            "chip_family": "type-c",
            "rssi": 15.0,
        }},
    ]


def test_both_mlrs_sources_are_accepted():
    """Neither source may be dropped by the confirm_only allow-list."""
    assert "mlrs_confirm" in signal_ingest._ACCEPTED_SIGNAL_SOURCES
    assert "mlrs_reasm" in signal_ingest._ACCEPTED_SIGNAL_SOURCES


def test_mlrs_reasm_bypasses_the_per_uid_throttle():
    """mLRS emits roughly 96 confirms per position, so a throttled
    position would almost always land inside a recent confirm's window
    and never reach drone-dict elevation. Same rationale as sik_reasm."""
    assert "mlrs_reasm" in signal_ingest._UNTHROTTLED_SIGNAL_SOURCES
    assert "mlrs_confirm" not in signal_ingest._UNTHROTTLED_SIGNAL_SOURCES


def test_parser_extracts_link_identity_and_position_flag():
    msg = _build_mlrs_alert_message("mlrs_reasm", True)
    alert = signal_ingest._parse_fpv_alert(msg)
    assert alert["source"] == "mlrs_reasm"
    assert alert["signal_type"] == "lora_css"
    assert alert["link_id"] == 0x7C85
    assert alert["has_mavlink"] is True
    assert alert["crc_repaired"] is False


def test_uid_is_stable_across_hops():
    """The link hops across a 25-channel set. Deriving the UID from the
    centre frequency would spawn a new ATAK marker per hop."""
    uids = {
        signal_ingest._compute_signal_uid(
            signal_ingest._parse_fpv_alert(
                _build_mlrs_alert_message("mlrs_confirm", False,
                                          center_hz=hz)))
        for hz in (904200000, 909000000, 919800000, 927000000)
    }
    assert len(uids) == 1, f"link produced multiple UIDs across hops: {uids}"


def test_distinct_links_get_distinct_uids():
    a = signal_ingest._compute_signal_uid(
        signal_ingest._parse_fpv_alert(
            _build_mlrs_alert_message("mlrs_confirm", False, link_id=0x7C85)))
    b = signal_ingest._compute_signal_uid(
        signal_ingest._parse_fpv_alert(
            _build_mlrs_alert_message("mlrs_confirm", False, link_id=0x1234)))
    assert a != b


def test_drone_id_matches_the_published_callsign():
    """The drone-dict key must line up with the MLRS-LINK-XXXX identity
    DragonSig puts in Basic ID, so operators see one consistent name."""
    alert = signal_ingest._parse_fpv_alert(
        _build_mlrs_alert_message("mlrs_reasm", True, link_id=0x7C85))
    assert signal_ingest._rf_drone_id(alert) == "drone-MLRS-LINK-7C85"


def test_sik_drone_id_is_unchanged():
    """mLRS support must not alter the existing SiK identity."""
    alert = {"net_id": 25}
    assert signal_ingest._rf_drone_id(alert) == "drone-900FHSS-NETID-25"


def test_fpv_has_no_rf_identity():
    assert signal_ingest._rf_drone_id({"signal_type": "fpv"}) is None
