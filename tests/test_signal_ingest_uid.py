"""Tests for the CoT/MQTT UID rule used by signal_ingest.

The signal UID drives ATAK marker identity. Same UID for repeated alerts
means ATAK updates the existing dot; different UID means a new dot.

The rules under test:
  - SiK (signal_type="gfsk_fhss") with a Net ID uses the Net ID so the
    marker is stable across frequency hops.
  - SiK without a Net ID falls back to center-MHz so something still emits.
  - FPV (signal_type="fpv") uses center-MHz — the channel frequency IS
    the identifier (different VTX channel == different drone).
  - Distinct Net IDs map to distinct UIDs (Net 25 must not collide with
    Net 26 even on the same hop frequency).
"""

from ingest.signal_ingest import _compute_signal_uid


def _sik_alert(net_id, center_hz=915_000_000):
    return {
        "signal_type": "gfsk_fhss",
        "net_id": net_id,
        "center_hz": center_hz,
    }


def _fpv_alert(center_hz):
    return {
        "signal_type": "fpv",
        "center_hz": center_hz,
    }


# ---- SiK: stable across hops, distinct per Net ID -----------------------

def test_sik_uid_stable_across_hop_frequencies():
    """Net 25 must produce the same UID regardless of which channel
    the confirm/reasm fired on — otherwise ATAK gets a new marker per hop."""
    uids = {
        _compute_signal_uid(_sik_alert(25, hz))
        for hz in (915_000_000, 918_000_000, 921_500_000, 927_000_000)
    }
    assert uids == {"gfsk_fhss-netid-25"}


def test_sik_uid_distinguishes_net_ids():
    """Two SiK drones on the same hop frequency but different Net IDs
    must produce different UIDs."""
    u25 = _compute_signal_uid(_sik_alert(25, 918_000_000))
    u26 = _compute_signal_uid(_sik_alert(26, 918_000_000))
    assert u25 == "gfsk_fhss-netid-25"
    assert u26 == "gfsk_fhss-netid-26"
    assert u25 != u26


def test_sik_uid_independent_of_center_hz_zero():
    """sik_reasm publisher emits center_hz=0 today. Net ID alone must
    drive the UID; center_hz=0 must not collapse different Net IDs."""
    u25 = _compute_signal_uid(_sik_alert(25, 0))
    u26 = _compute_signal_uid(_sik_alert(26, 0))
    assert u25 == "gfsk_fhss-netid-25"
    assert u26 == "gfsk_fhss-netid-26"


def test_sik_uid_falls_back_to_center_when_no_net_id():
    """If a SiK alert ever arrives without a Net ID, the UID must still
    be derivable from center_hz so the message is not dropped silently."""
    uid = _compute_signal_uid({
        "signal_type": "gfsk_fhss",
        "center_hz": 915_000_000,
    })
    assert uid == "gfsk_fhss-alert-915MHz"


def test_sik_uid_final_fallback_when_no_net_id_and_no_center():
    """Last-resort fallback: alert_id, else a generic placeholder."""
    uid = _compute_signal_uid({
        "signal_type": "gfsk_fhss",
        "alert_id": "abc-123",
    })
    assert uid == "abc-123"

    uid_unknown = _compute_signal_uid({"signal_type": "gfsk_fhss"})
    assert uid_unknown == "gfsk_fhss-alert-unknown"


# ---- FPV: unchanged, frequency-based ------------------------------------

def test_fpv_uid_uses_channel_frequency():
    """FPV channels are the identifier — different channel == different
    drone. UID must continue to track channel frequency."""
    assert _compute_signal_uid(_fpv_alert(5_945_000_000)) == "fpv-alert-5945MHz"
    assert _compute_signal_uid(_fpv_alert(5_645_000_000)) == "fpv-alert-5645MHz"


def test_fpv_uid_distinct_per_channel():
    """Two FPV signals on different channels must produce different UIDs
    even though both are 'FPV'."""
    a = _compute_signal_uid(_fpv_alert(5_945_000_000))
    b = _compute_signal_uid(_fpv_alert(5_685_000_000))
    assert a != b


def test_fpv_uid_ignores_stray_net_id_field():
    """net_id only applies to gfsk_fhss. If an FPV alert somehow carries
    a stray net_id, it must NOT hijack the FPV UID."""
    alert = {
        "signal_type": "fpv",
        "center_hz": 5_945_000_000,
        "net_id": 25,
    }
    assert _compute_signal_uid(alert) == "fpv-alert-5945MHz"


# ---- Default signal_type ------------------------------------------------

def test_missing_signal_type_defaults_to_fpv():
    """Backward-compat: legacy alerts with no signal_type are treated as
    FPV (matches the inline default in start_signal_worker)."""
    uid = _compute_signal_uid({"center_hz": 5_945_000_000})
    assert uid == "fpv-alert-5945MHz"
