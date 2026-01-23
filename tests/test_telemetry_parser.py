import json
from core import parse_drone_info

UA = {
    0: 'No UA type defined',
    1: 'Aeroplane/Airplane (Fixed wing)',
    2: 'Helicopter or Multirotor',
    15: 'Other type',
}

def test_dji_list_with_freq_and_serial():
    msg = [
        {"Basic ID": {"id_type": "Serial Number (ANSI/CTA-2063-A)", "id": "SN123", "ua_type": 2, "MAC": "AA:BB", "RSSI": -65}},
        {"Location/Vector Message": {"latitude": 10.0, "longitude": 20.0, "speed": 5.0, "vert_speed": -1.0, "geodetic_altitude": 120.0, "height_agl": 30.0}},
        {"Frequency Message": {"frequency": 5805000000.0}},  # 5.805 GHz
        {"Self-ID Message": {"text": "DJI Phantom"}}
    ]
    out = parse_drone_info(msg, UA)
    assert out["id"] == "SN123"
    assert out["ua_type"] == 2 and out["ua_type_name"].lower().startswith("helicopter")
    assert out["lat"] == 10.0 and out["lon"] == 20.0
    assert out["freq"] == 5805000000.0

def test_esp32_dict_caa_only_no_freq():
    msg = {
        "Basic ID": {"id_type": "CAA Assigned Registration ID", "id": "CAA-XYZ", "ua_type": "Other type", "MAC": "CC:DD", "RSSI": -70},
        "Location/Vector Message": {"latitude": 1.0, "longitude": 2.0, "speed": 0.5, "vert_speed": 0.0, "geodetic_altitude": 50.0, "height_agl": 5.0},
        "Self-ID Message": {"text": "Some RID"}
    }
    out = parse_drone_info(msg, UA)
    assert out["caa"] == "CAA-XYZ"
    # freq key should not be present (no Frequency Message in dict)
    assert "freq" not in out


# ===== Additional comprehensive tests =====

def test_esp32_with_aux_adv_ind():
    """Test ESP32 dict format with AUX_ADV_IND and aext fields"""
    msg = {
        "index": 42,
        "runtime": 12345,
        "AUX_ADV_IND": {"rssi": -68},
        "aext": {"AdvA": "AA:BB:CC:DD:EE:FF 12:34:56:78:90:AB"},
        "Basic ID": {
            "id_type": "Serial Number (ANSI/CTA-2063-A)",
            "id": "ESP32TEST",
            "ua_type": 2
        },
        "Location/Vector Message": {
            "latitude": 39.76,
            "longitude": -105.01,
            "geodetic_altitude": 1720.0,
            "height_agl": 75.0,
            "speed": 10.0,
            "vert_speed": 0.5
        }
    }
    out = parse_drone_info(msg, UA)

    assert out["id"] == "ESP32TEST"
    assert out["index"] == 42
    assert out["runtime"] == 12345
    assert out["rssi"] == -68  # From AUX_ADV_IND
    assert out["mac"] == "AA:BB:CC:DD:EE:FF"  # First part of AdvA
    assert out["lat"] == 39.76
    assert out["lon"] == -105.01


def test_esp32_system_message_operator_lat_lon():
    """Test that ESP32 System Message uses operator_lat/lon not latitude/longitude"""
    msg = {
        "Basic ID": {"id": "ESP_OP_TEST", "id_type": "Serial Number (ANSI/CTA-2063-A)"},
        "Location/Vector Message": {"latitude": 1.0, "longitude": 2.0},
        "System Message": {
            "operator_lat": 3.0,
            "operator_lon": 4.0
        }
    }
    out = parse_drone_info(msg, UA)

    # ESP32 path should use operator_lat/lon for pilot location
    assert out["pilot_lat"] == 3.0
    assert out["pilot_lon"] == 4.0


def test_droneid_system_message_latitude_longitude():
    """Test that DroneID list format System Message uses latitude/longitude"""
    msg = [
        {"Basic ID": {"id": "DRONEID_SYS", "id_type": "Serial Number (ANSI/CTA-2063-A)"}},
        {"Location/Vector Message": {"latitude": 10.0, "longitude": 20.0}},
        {"System Message": {
            "latitude": 10.5,  # Pilot location
            "longitude": 20.5,
            "home_lat": 10.3,
            "home_lon": 20.3
        }}
    ]
    out = parse_drone_info(msg, UA)

    assert out["pilot_lat"] == 10.5
    assert out["pilot_lon"] == 20.5
    assert out["home_lat"] == 10.3
    assert out["home_lon"] == 20.3


def test_operator_id_message():
    """Test Operator ID Message parsing"""
    msg = [
        {"Basic ID": {"id": "OP_ID_TEST", "id_type": "Serial Number (ANSI/CTA-2063-A)"}},
        {"Location/Vector Message": {"latitude": 1.0, "longitude": 2.0}},
        {"Operator ID Message": {
            "operator_id_type": "CAA Assigned Registration ID",
            "operator_id": "OP-12345"
        }}
    ]
    out = parse_drone_info(msg, UA)

    assert out["operator_id"] == "OP-12345"
    assert out["operator_id_type"] == "CAA Assigned Registration ID"


def test_remote_id_accuracy_fields():
    """Test that Remote ID accuracy/status fields are preserved"""
    msg = [
        {"Basic ID": {"id": "ACCURACY_TEST", "id_type": "Serial Number (ANSI/CTA-2063-A)"}},
        {"Location/Vector Message": {
            "latitude": 1.0,
            "longitude": 2.0,
            "height_type": "Above Takeoff",
            "op_status": "Airborne",
            "ew_dir_segment": "East",
            "horizontal_accuracy": "< 10 m",
            "vertical_accuracy": "< 3 m",
            "baro_accuracy": "< 4 m",
            "speed_accuracy": "< 1 m/s",
            "timestamp": "3600.5",
            "timestamp_accuracy": "0.1s"
        }}
    ]
    out = parse_drone_info(msg, UA)

    assert out["height_type"] == "Above Takeoff"
    assert out["op_status"] == "Airborne"
    assert out["ew_dir"] == "East"
    assert out["horizontal_accuracy"] == "< 10 m"
    assert out["vertical_accuracy"] == "< 3 m"
    assert out["timestamp"] == "3600.5"
    assert out["rid_timestamp"] == "3600.5"  # Both should be set


def test_speed_multiplier_pressure_altitude_with_units():
    """Test parsing of speed_multiplier and pressure_altitude with unit strings"""
    msg = [
        {"Basic ID": {"id": "UNITS_TEST", "id_type": "Serial Number (ANSI/CTA-2063-A)"}},
        {"Location/Vector Message": {
            "latitude": 1.0,
            "longitude": 2.0,
            "speed_multiplier": "0.25 m/s",  # Has unit suffix
            "pressure_altitude": "1650.0 m"  # Has unit suffix
        }}
    ]
    out = parse_drone_info(msg, UA)

    # get_float should split on space and take first part
    assert out["speed_multiplier"] == 0.25
    assert out["pressure_altitude"] == 1650.0


def test_top_level_mac_rssi_in_list():
    """Test that top-level MAC/RSSI in list items are captured"""
    msg = [
        {
            "MAC": "FF:EE:DD:CC:BB:AA",
            "RSSI": -55
        },
        {
            "Basic ID": {
                "id": "TOPLEVEL_TEST",
                "id_type": "Serial Number (ANSI/CTA-2063-A)"
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 1.0,
                "longitude": 2.0
            }
        }
    ]
    out = parse_drone_info(msg, UA)

    assert out["mac"] == "FF:EE:DD:CC:BB:AA"
    assert out["rssi"] == -55


def test_empty_list_returns_none():
    """Test that empty list returns None"""
    result = parse_drone_info([], UA)
    assert result is None


def test_empty_dict_returns_none():
    """Test that empty dict returns minimal data (index/runtime default to 0)"""
    result = parse_drone_info({}, UA)
    # Empty dict in ESP32 path returns dict with defaults, not None
    assert result is not None
    assert result.get("index") == 0
    assert result.get("runtime") == 0


def test_invalid_type_returns_none():
    """Test that invalid message type returns None"""
    result = parse_drone_info("invalid string", UA)
    assert result is None

    result = parse_drone_info(12345, UA)
    assert result is None


def test_list_with_invalid_items():
    """Test that list with non-dict items is handled gracefully"""
    msg = [
        "invalid item",
        {"Basic ID": {"id": "MIXED_TEST", "id_type": "Serial Number (ANSI/CTA-2063-A)"}},
        None,
        {"Location/Vector Message": {"latitude": 1.0, "longitude": 2.0}}
    ]
    # Should skip invalid items but process valid ones
    out = parse_drone_info(msg, UA)

    assert out is not None
    assert out["id"] == "MIXED_TEST"
    assert out["lat"] == 1.0


def test_minimal_message():
    """Test message with only minimal required fields"""
    msg = [
        {"Basic ID": {"id": "MINIMAL", "id_type": "Serial Number (ANSI/CTA-2063-A)"}},
        {"Location/Vector Message": {"latitude": 1.0, "longitude": 2.0}}
    ]
    out = parse_drone_info(msg, UA)

    assert out["id"] == "MINIMAL"
    assert out["lat"] == 1.0
    assert out["lon"] == 2.0
    # Optional fields should have defaults or be missing
    assert out.get("speed", 0.0) == 0.0
    assert out.get("alt", 0.0) == 0.0


def test_none_values_handled_gracefully():
    """Test that None values in fields don't crash parser"""
    msg = [
        {
            "Basic ID": {
                "id": "NONE_TEST",
                "ua_type": None,
                "MAC": None
            }
        },
        {
            "Location/Vector Message": {
                "latitude": 1.0,
                "longitude": 2.0,
                "direction": None,
                "speed": None
            }
        }
    ]
    out = parse_drone_info(msg, UA)

    assert out is not None
    assert out.get("direction") is None
    # speed should be 0.0 (default from get_float)
    assert out.get("speed", 0.0) == 0.0
