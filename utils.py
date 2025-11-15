"""
Copyright 2025 cemaxecuter

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from typing import Optional, Dict, Any
import configparser
import logging
import sys

logger = logging.getLogger(__name__)

def load_config(config_path: str) -> Dict[str, Any]:
    """
    Loads the configuration from the specified INI file.
    Returns a dictionary of configuration values.
    """
    config = configparser.ConfigParser()
    try:
        config.read(config_path)
        # Assuming configurations are under the 'SETTINGS' section
        if 'SETTINGS' in config:
            return dict(config['SETTINGS'])
        else:
            logger.warning(f"No 'SETTINGS' section found in {config_path}. Using empty configuration.")
            return {}
    except Exception as e:
        logger.critical(f"Failed to load configuration file {config_path}: {e}")
        sys.exit(1)

def get_str(value: Optional[Any], default: str = "") -> str:
    """
    Safely converts a value to a string. If the value is None or empty, returns the default.
    """
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default

def get_int(value: Optional[Any], default: Optional[int] = None) -> Optional[int]:
    """
    Safely converts a value to an integer. If conversion fails or value is None, returns the default.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def get_float(value: Optional[Any], default: float = 0.0) -> float:
    """
    Safely converts a value to float. If the value is a string containing units (e.g., "7.5 m"),
    it extracts the numeric part before conversion.
    """
    if value is None:
        return default
    if isinstance(value, str):
        # Split the string and take the first part as the numeric value
        parts = value.strip().split()
        if parts:
            try:
                numeric_value = float(parts[0])
                logger.debug(f"Parsed float from string '{value}': {numeric_value}")
                return numeric_value
            except ValueError:
                logger.warning(f"Unable to parse float from string: '{value}'. Using default {default}.")
                return default
        else:
            logger.warning(f"Empty string provided for float conversion. Using default {default}.")
            return default
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid float value: {value}. Using default {default}.")
        return default

def get_bool(value: Optional[Any], default: bool = False) -> bool:
    """
    Safely converts a value to a boolean. If conversion fails or value is None, returns the default.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value_str = value.strip().lower()
        if value_str in ['true', 'yes', '1']:
            return True
        elif value_str in ['false', 'no', '0']:
            return False
    return default

def validate_config(config: Dict[str, Any]):
    """
    Validates the configuration dictionary.
    Raises ValueError if any required configuration is invalid.
    """
    required_keys = ["zmq_host", "zmq_port"]
    for key in required_keys:
        if key not in config or not config[key]:
            raise ValueError(f"Configuration '{key}' is required and cannot be empty.")

    # Validate ZMQ port
    zmq_port = get_int(config.get('zmq_port'))
    if zmq_port is None or not (1 <= zmq_port <= 65535):
        raise ValueError(f"Invalid ZMQ port: {zmq_port}. Must be between 1 and 65535.")

    # Retrieve TAK configurations
    tak_host = get_str(config.get('tak_host'))
    tak_port = get_int(config.get('tak_port'))
    tak_protocol = get_str(config.get('tak_protocol', 'TCP')).upper()

    if tak_host and tak_port:
        # Validate TAK protocol
        if not tak_protocol:
            raise ValueError("Configuration 'tak_protocol' is required when 'tak_host' and 'tak_port' are provided.")
        if tak_protocol not in ('TCP', 'UDP'):
            raise ValueError(f"Invalid TAK protocol: {tak_protocol}. Must be either 'TCP' or 'UDP'.")
        config['tak_protocol'] = tak_protocol  # Normalize value

        # Validate TAK protocol-specific configurations
        if tak_protocol == 'TCP':
            tak_tls_p12 = config.get('tak_tls_p12')
            tak_tls_p12_pass = config.get('tak_tls_p12_pass')
            if not tak_tls_p12 or not tak_tls_p12_pass:
                raise ValueError("TAK protocol is set to TCP but 'tak_tls_p12' or 'tak_tls_p12_pass' is missing.")
        elif tak_protocol == 'UDP':
            # For UDP, tak_tls_p12 and tak_tls_p12_pass should not be set
            if config.get('tak_tls_p12') or config.get('tak_tls_p12_pass'):
                logger.warning("TAK protocol is set to UDP. 'tak_tls_p12' and 'tak_tls_p12_pass' will be ignored.")
    else:
        # If tak_host and tak_port are not both provided, ignore tak_protocol
        config['tak_protocol'] = None

    # Validate multicast configurations if enabled
    enable_multicast = get_bool(config.get('enable_multicast', False))
    if enable_multicast:
        multicast_address = get_str(config.get('tak_multicast_addr'))
        multicast_port = get_int(config.get('tak_multicast_port'))
        multicast_ttl = get_int(config.get('multicast_ttl', 1))
        if not multicast_address or not multicast_port:
            raise ValueError("Multicast is enabled but 'tak_multicast_addr' or 'tak_multicast_port' is missing.")
        if multicast_ttl < 1:
            raise ValueError("Multicast TTL must be at least 1.")
        config['enable_multicast'] = True
    else:
        config['enable_multicast'] = False

    # Validate receive configurations if enabled
    enable_receive = get_bool(config.get('enable_receive', False))
    if enable_receive:
        if not enable_multicast:
            raise ValueError("Receive is enabled but multicast is not. Receive requires multicast to be enabled.")
        config['enable_receive'] = True
    else:
        config['enable_receive'] = False

    # Ensure consistency between tak_host and tak_port
    if (tak_host and not tak_port) or (tak_port and not tak_host):
        raise ValueError("Both 'tak_host' and 'tak_port' must be provided together.")
