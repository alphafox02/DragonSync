"""Tests for the operator-facing callsign rule used by signal_ingest.

The callsign is what an operator reads on the ATAK marker and in the
WarDragon console. It answers "what is this contact", so it is built from
the contact's identifier, never from `source`, which answers the different
question of "how was it confirmed".

The standard, mirroring the elevated drone key without its "drone-" prefix
(that prefix is reserved for a link that has produced a position):

    RF-only                    elevated
    900FHSS-NETID-25    ->     drone-900FHSS-NETID-25
    MLRS-LINK-1A2B      ->     drone-MLRS-LINK-1A2B
    FPV-5945MHz                (FPV never elevates: no RF identity)

Regression under test: keying the label on `source` gave every contact of
a kind the same caption, so two SiK drones both read "GFSK-FHSS
sik_confirm" while being correctly separate markers. An operator could not
tell them apart.
"""

from ingest.signal_ingest import _rf_drone_id, _signal_callsign


def _sik(net_id=25, source="sik_confirm", chip_family=None):
    a = {
        "signal_type": "gfsk_fhss",
        "net_id": net_id,
        "alert_id": f"900FHSS-NETID-{net_id}",
        "center_hz": 915_000_000,
        "source": source,
    }
    if chip_family:
        a["chip_family"] = chip_family
    return a


def _mlrs(link_id=0x1A2B, source="mlrs_confirm"):
    return {
        "signal_type": "lora_css",
        "link_id": link_id,
        "alert_id": f"MLRS-LINK-{link_id:04X}",
        "center_hz": 915_000_000,
        "source": source,
    }


def _fpv(center_hz=5_945_000_000):
    return {"signal_type": "fpv", "center_hz": center_hz, "source": "confirm"}


# ---- the label names the contact, not the confirmation ------------------

def test_sik_callsign_is_the_net_id_not_the_source():
    assert _signal_callsign(_sik(25), "gfsk_fhss") == "900FHSS-NETID-25"


def test_mlrs_callsign_carries_the_link_id():
    """The customer-visible regression: this read 'LORA-CSS mlrs_confirm'."""
    assert _signal_callsign(_mlrs(0x1A2B), "lora_css") == "MLRS-LINK-1A2B"


def test_fpv_callsign_is_its_channel():
    assert _signal_callsign(_fpv(5_945_000_000), "fpv") == "FPV-5945MHz"


def test_source_never_appears_in_the_callsign():
    for alert, st in ((_sik(), "gfsk_fhss"), (_mlrs(), "lora_css"), (_fpv(), "fpv")):
        for src in ("sik_confirm", "sik_reasm", "mlrs_confirm", "confirm"):
            alert["source"] = src
            assert src not in _signal_callsign(alert, st)


# ---- distinct contacts must read differently ----------------------------

def test_two_sik_drones_do_not_share_a_caption():
    """Separate markers that read identically are unusable on a map."""
    assert _signal_callsign(_sik(25), "gfsk_fhss") != _signal_callsign(_sik(77), "gfsk_fhss")


def test_confirm_and_reasm_of_one_link_read_the_same():
    """One contact keeps one name however it was confirmed."""
    a = _signal_callsign(_sik(25, source="sik_confirm"), "gfsk_fhss")
    b = _signal_callsign(_sik(25, source="sik_reasm"), "gfsk_fhss")
    assert a == b


# ---- the label survives elevation ---------------------------------------

def test_callsign_matches_the_elevated_drone_key():
    """RF-only and elevated names differ only by the drone- prefix, so a
    contact stays recognisable when it starts reporting position."""
    for alert in (_sik(25), _mlrs(0x1A2B)):
        assert _rf_drone_id(alert) == f"drone-{_signal_callsign(alert, alert['signal_type'])}"


def test_fpv_has_no_elevated_form():
    assert _rf_drone_id(_fpv()) is None


# ---- degraded input still yields something renderable -------------------

def test_missing_identifier_falls_back_to_frequency():
    assert _signal_callsign({"center_hz": 5_800_000_000}, "fpv") == "FPV-5800MHz"


def test_no_identifier_and_no_frequency_still_returns_a_label():
    assert _signal_callsign({}, "gfsk_fhss") == "GFSK-FHSS"


# ---- remarks identify the contact too ----------------------------------

def _remarks(alert):
    import re
    from utils.cot_builder import build_signal_cot
    xml = build_signal_cot(alert, 33.5, -82.2, 0.0, 60, 100.0)
    xml = xml.decode() if isinstance(xml, bytes) else xml
    m = re.search(r"<remarks[^>]*>(.*?)</remarks>", xml, re.S)
    return m.group(1) if m else ""


def test_remarks_name_the_mlrs_link():
    """Reported by a customer: remarks read 'signal=lora_css
    source=mlrs_confirm ...' with nothing identifying which link."""
    r = _remarks({"uid": "u", "signal_type": "lora_css", "source": "mlrs_confirm",
                  "callsign": "MLRS-LINK-1A2B", "link_id": 0x1A2B, "center_hz": 915e6})
    assert "link_id=1A2B" in r


def test_remarks_name_the_sik_net_id_and_radio():
    r = _remarks({"uid": "u", "signal_type": "gfsk_fhss", "source": "sik_reasm",
                  "callsign": "900FHSS-NETID-77", "net_id": 77,
                  "chip_family": "type-b", "center_hz": 915e6})
    assert "net_id=77" in r and "chip_family=type-b" in r


def test_remarks_keep_source_for_provenance():
    """source stays — it answers how the contact was confirmed, which an
    operator still needs to judge trust. It just cannot be the only thing."""
    r = _remarks({"uid": "u", "signal_type": "gfsk_fhss", "source": "sik_confirm",
                  "net_id": 25, "center_hz": 915e6})
    assert "source=sik_confirm" in r


# ---- signal quality in remarks ------------------------------------------

def test_remarks_carry_snr_when_measured():
    r = _remarks({"uid": "u", "signal_type": "gfsk_fhss", "source": "sik_reasm",
                  "net_id": 77, "center_hz": 915e6,
                  "snr_db": 30.6, "noise_floor_db": -28.7})
    assert "snr_db=30.6" in r and "noise_floor_db=-28.7" in r


def test_remarks_omit_snr_when_not_measured():
    r = _remarks({"uid": "u", "signal_type": "gfsk_fhss", "source": "sik_confirm",
                  "net_id": 25, "center_hz": 915e6})
    assert "snr_db" not in r and "noise_floor_db" not in r


def test_remarks_prefix_is_unchanged_for_existing_matchers():
    """snr is appended after rssi, so anything matching the old prefix
    still matches."""
    r = _remarks({"uid": "u", "signal_type": "gfsk_fhss", "source": "sik_confirm",
                  "net_id": 25, "center_hz": 915e6, "snr_db": 12.0})
    assert r.startswith("signal=gfsk_fhss net_id=25 source=sik_confirm")
