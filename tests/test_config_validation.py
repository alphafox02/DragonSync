#!/usr/bin/env python3
"""
Tests for configuration validation in DragonSync.
"""

import pytest
from utils.config import validate_config, get_str, get_int, get_float, get_bool


class TestConfigHelpers:
    """Test config helper functions."""

    def test_get_str(self):
        assert get_str("test") == "test"
        assert get_str("  test  ") == "test"
        assert get_str(None) == ""
        assert get_str("") == ""
        assert get_str(None, "default") == "default"
        assert get_str("", "default") == "default"

    def test_get_int(self):
        assert get_int("42") == 42
        assert get_int(42) == 42
        assert get_int(None) is None
        assert get_int("invalid") is None
        assert get_int("invalid", 10) == 10

    def test_get_float(self):
        assert get_float("3.14") == 3.14
        assert get_float(3.14) == 3.14
        assert get_float("7.5 m") == 7.5  # Handle unit strings
        assert get_float(None, 1.0) == 1.0
        assert get_float("invalid", 2.5) == 2.5

    def test_get_bool(self):
        assert get_bool("true") is True
        assert get_bool("True") is True
        assert get_bool("yes") is True
        assert get_bool("1") is True
        assert get_bool(True) is True
        assert get_bool("false") is False
        assert get_bool("False") is False
        assert get_bool("no") is False
        assert get_bool("0") is False
        assert get_bool(False) is False
        assert get_bool(None) is False
        assert get_bool(None, True) is True


class TestRequiredFields:
    """Test validation of required configuration fields."""

    def test_missing_zmq_host(self):
        config = {"zmq_port": "5556"}
        with pytest.raises(ValueError, match="'zmq_host' is required"):
            validate_config(config)

    def test_missing_zmq_port(self):
        config = {"zmq_host": "127.0.0.1"}
        with pytest.raises(ValueError, match="'zmq_port' is required"):
            validate_config(config)

    def test_empty_zmq_host(self):
        config = {"zmq_host": "", "zmq_port": "5556"}
        with pytest.raises(ValueError, match="'zmq_host' is required"):
            validate_config(config)


class TestPortValidation:
    """Test validation of port numbers."""

    def test_invalid_zmq_port_too_low(self):
        config = {"zmq_host": "127.0.0.1", "zmq_port": "0"}
        with pytest.raises(ValueError, match="Invalid ZMQ port"):
            validate_config(config)

    def test_invalid_zmq_port_too_high(self):
        config = {"zmq_host": "127.0.0.1", "zmq_port": "99999"}
        with pytest.raises(ValueError, match="Invalid ZMQ port"):
            validate_config(config)

    def test_invalid_mqtt_port(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "mqtt_enabled": "true",
            "mqtt_port": "99999",
        }
        with pytest.raises(ValueError, match="Invalid MQTT port"):
            validate_config(config)

    def test_invalid_api_port(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "api_enabled": "true",
            "api_port": "0",
        }
        with pytest.raises(ValueError, match="Invalid API port"):
            validate_config(config)

    def test_valid_ports(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "mqtt_enabled": "true",
            "mqtt_port": "1883",
            "api_enabled": "true",
            "api_port": "8088",
        }
        validate_config(config)  # Should not raise


class TestTAKValidation:
    """Test validation of TAK server configuration."""

    def test_tak_host_without_port(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "tak_host": "192.168.1.100",
        }
        with pytest.raises(ValueError, match="tak_host.*tak_port.*together"):
            validate_config(config)

    def test_tak_port_without_host(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "tak_port": "8087",
        }
        with pytest.raises(ValueError, match="tak_host.*tak_port.*together"):
            validate_config(config)

    def test_tcp_without_tls(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "tak_host": "192.168.1.100",
            "tak_port": "8087",
            "tak_protocol": "TCP",
        }
        with pytest.raises(ValueError, match="TLS credentials"):
            validate_config(config)

    def test_tcp_with_p12(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "tak_host": "192.168.1.100",
            "tak_port": "8087",
            "tak_protocol": "TCP",
            "tak_tls_p12": "/path/to/cert.p12",
        }
        validate_config(config)  # Should not raise

    def test_tcp_with_cert_and_key(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "tak_host": "192.168.1.100",
            "tak_port": "8087",
            "tak_protocol": "TCP",
            "tak_tls_certfile": "/path/to/cert.pem",
            "tak_tls_keyfile": "/path/to/key.pem",
        }
        validate_config(config)  # Should not raise


class TestMulticastValidation:
    """Test validation of multicast configuration."""

    def test_multicast_without_address(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "enable_multicast": "true",
            "tak_multicast_port": "6969",
        }
        with pytest.raises(ValueError, match="tak_multicast_addr.*missing"):
            validate_config(config)

    def test_multicast_without_port(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "enable_multicast": "true",
            "tak_multicast_addr": "239.2.3.1",
        }
        with pytest.raises(ValueError, match="tak_multicast_port.*missing"):
            validate_config(config)

    def test_multicast_invalid_ttl(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "enable_multicast": "true",
            "tak_multicast_addr": "239.2.3.1",
            "tak_multicast_port": "6969",
            "multicast_ttl": "0",
        }
        with pytest.raises(ValueError, match="Multicast TTL"):
            validate_config(config)

    def test_receive_without_multicast(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "enable_receive": "true",
        }
        with pytest.raises(ValueError, match="Receive.*multicast"):
            validate_config(config)


class TestDroneTrackingLimits:
    """Test validation of drone tracking configuration."""

    def test_invalid_max_drones_zero(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "0",
        }
        with pytest.raises(ValueError, match="Invalid max_drones.*greater than 0"):
            validate_config(config)

    def test_invalid_max_drones_negative(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "-5",
        }
        with pytest.raises(ValueError, match="Invalid max_drones.*greater than 0"):
            validate_config(config)

    def test_invalid_rate_limit_zero(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "rate_limit": "0",
        }
        with pytest.raises(ValueError, match="Invalid rate_limit.*greater than 0"):
            validate_config(config)

    def test_invalid_inactivity_timeout_negative(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "inactivity_timeout": "-10",
        }
        with pytest.raises(ValueError, match="Invalid inactivity_timeout.*greater than 0"):
            validate_config(config)


class TestTwoTierMode:
    """Test validation of two-tier drone tracking mode."""

    def test_two_tier_inconsistent_total(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "100",
            "max_verified_drones": "60",
            "max_unverified_drones": "30",  # 60 + 30 = 90 != 100
        }
        with pytest.raises(ValueError, match="Two-tier mode inconsistency"):
            validate_config(config)

    def test_two_tier_verified_zero(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "100",
            "max_verified_drones": "0",
            "max_unverified_drones": "100",
        }
        with pytest.raises(ValueError, match="Invalid max_verified_drones.*greater than 0"):
            validate_config(config)

    def test_two_tier_unverified_zero(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "100",
            "max_verified_drones": "100",
            "max_unverified_drones": "0",
        }
        with pytest.raises(ValueError, match="Invalid max_unverified_drones.*greater than 0"):
            validate_config(config)

    def test_two_tier_valid(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "100",
            "max_verified_drones": "70",
            "max_unverified_drones": "30",
        }
        validate_config(config)  # Should not raise


class TestADSBAltitudeFilters:
    """Test validation of ADS-B altitude filters."""

    def test_adsb_min_greater_than_max(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "adsb_min_alt": "10000",
            "adsb_max_alt": "5000",
        }
        with pytest.raises(ValueError, match="Invalid ADS-B altitude range"):
            validate_config(config)

    def test_adsb_min_equals_max(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "adsb_min_alt": "5000",
            "adsb_max_alt": "5000",
        }
        with pytest.raises(ValueError, match="Invalid ADS-B altitude range"):
            validate_config(config)

    def test_adsb_valid_range(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "adsb_min_alt": "1000",
            "adsb_max_alt": "10000",
        }
        validate_config(config)  # Should not raise

    def test_adsb_only_min_set(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "adsb_min_alt": "1000",
        }
        validate_config(config)  # Should not raise (no max means no upper limit)

    def test_adsb_only_max_set(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "adsb_max_alt": "10000",
        }
        validate_config(config)  # Should not raise (no min means no lower limit)


class TestMinimalValidConfig:
    """Test that minimal valid config passes."""

    def test_minimal_config(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
        }
        validate_config(config)  # Should not raise

    def test_typical_config(self):
        config = {
            "zmq_host": "127.0.0.1",
            "zmq_port": "5556",
            "max_drones": "100",
            "max_verified_drones": "70",
            "max_unverified_drones": "30",
            "rate_limit": "3.0",
            "inactivity_timeout": "60.0",
            "mqtt_enabled": "true",
            "mqtt_port": "1883",
            "api_enabled": "true",
            "api_port": "8088",
        }
        validate_config(config)  # Should not raise
