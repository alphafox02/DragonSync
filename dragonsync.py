#!/usr/bin/env python3
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

import sys
import ssl
import socket
import signal
import argparse
import datetime
import time
import threading
import tempfile
from typing import Optional, Dict, Any
from queue import Queue
from pathlib import Path
import atexit
import os

import zmq
import json

# Default kit identifier (overridden once wardragon_monitor status arrives)
KIT_ID_DEFAULT = "wardragon-unknown"
KIT_ID = KIT_ID_DEFAULT
try:
    from mqtt_sink import MqttSink
except Exception:
    MqttSink = None

from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization

from tak_client import TAKClient
from tak_udp_client import TAKUDPClient
from drone import Drone
from system_status import SystemStatus
from api_server import serve_api
from manager import DroneManager
from messaging import CotMessenger
from update_check import update_check
from utils import load_config, validate_config, get_str, get_int, get_float, get_bool
from telemetry_parser import parse_drone_info
from aircraft import adsb_worker_loop
from kismet_ingest import start_kismet_worker
import logging
logger = logging.getLogger(__name__)

# FAA RID lookup module (optional git submodule)
lookup_serial = None
_FAA_LOOKUP_AVAILABLE = False

try:
    FAA_LOOKUP_PATH = Path(__file__).parent / "faa-rid-lookup"
    if FAA_LOOKUP_PATH.exists():
        sys.path.insert(0, str(FAA_LOOKUP_PATH))
        from drone_serial_lookup import lookup_serial
        _FAA_LOOKUP_AVAILABLE = True
    else:
        logger.info("FAA RID lookup submodule not present; continuing without RID enrichment.")
except Exception as e:
    lookup_serial = None
    _FAA_LOOKUP_AVAILABLE = False
    logger.warning("FAA RID lookup module unavailable: %s", e)

# FAA lookup controls and async worker
_rid_lookup_enabled = _FAA_LOOKUP_AVAILABLE
_rid_lookup_failure_logged = False
_rid_lookup_queue: Optional[Queue] = None
_rid_lookup_worker: Optional[threading.Thread] = None
_rid_api_enabled = False  # API fallback off by default unless enabled via config
_rid_queue_max = 100  # drop API fallback when backlog exceeds this
_rid_rate_limit = 1.0  # seconds between FAA API calls
_rid_last_api_time = 0.0
_rid_miss_cache = set()  # serials that returned no result
_rid_miss_cache_max = 1000


def _start_rid_lookup_worker() -> None:
    """Start a background worker for FAA API fallback."""
    global _rid_lookup_queue, _rid_lookup_worker
    if not _rid_lookup_enabled or not _rid_api_enabled:
        return
    if _rid_lookup_queue is None:
        _rid_lookup_queue = Queue()
    if _rid_lookup_worker and _rid_lookup_worker.is_alive():
        return

    def _worker():
        global _rid_lookup_enabled, _rid_lookup_failure_logged, _rid_last_api_time
        while True:
            item = _rid_lookup_queue.get()
            if item is None:
                break
            drone_obj, serial_number = item
            try:
                # rate limit API calls
                now = time.time()
                delta = now - _rid_last_api_time
                if delta < _rid_rate_limit:
                    time.sleep(_rid_rate_limit - delta)

                res = lookup_serial(serial_number, use_api_fallback=True, add_to_db=True)  # type: ignore
                _rid_last_api_time = time.time()

                # cache misses to avoid repeat API hits
                if not res.get("found"):
                    if len(_rid_miss_cache) >= _rid_miss_cache_max:
                        _rid_miss_cache.pop()
                    _rid_miss_cache.add(serial_number)
            except FileNotFoundError as e:
                if not _rid_lookup_failure_logged:
                    logger.warning("FAA RID lookup skipped (database missing?): %s", e)
                    _rid_lookup_failure_logged = True
                _rid_lookup_enabled = False
                drone_obj.rid_lookup_pending = False
                continue
            except Exception as e:
                if not _rid_lookup_failure_logged:
                    logger.warning("FAA RID lookup failed; disabling further attempts: %s", e)
                    _rid_lookup_failure_logged = True
                _rid_lookup_enabled = False
                drone_obj.rid_lookup_pending = False
                continue

            try:
                drone_obj.apply_rid_lookup_result(res)
            except Exception as e:
                logger.debug("RID lookup apply failed for %s: %s", serial_number, e)
            finally:
                drone_obj.rid_lookup_pending = False

    _rid_lookup_worker = threading.Thread(target=_worker, daemon=True, name="rid_lookup_worker")
    _rid_lookup_worker.start()


def _queue_rid_lookup(drone_obj: Drone, serial_number: str) -> None:
    """Queue a background RID lookup (API fallback) without blocking main loop."""
    if not _rid_lookup_enabled or not _rid_api_enabled or lookup_serial is None or not serial_number:
        return
    if drone_obj.rid_lookup_pending:
        return
    if _rid_lookup_queue is None:
        return
    if serial_number in _rid_miss_cache:
        return
    try:
        if _rid_lookup_queue.qsize() >= _rid_queue_max:
            logger.debug("RID API queue full; skipping fallback for %s", serial_number)
            return
    except Exception:
        pass

    drone_obj.rid_lookup_pending = True
    drone_obj.rid_lookup_attempted = True  # prevent re-queueing
    try:
        _rid_lookup_queue.put_nowait((drone_obj, serial_number))
    except Exception as e:
        drone_obj.rid_lookup_pending = False
        logger.debug("Failed to enqueue RID lookup for %s: %s", serial_number, e)


def _apply_rid_lookup(drone_obj: Drone, serial_number: str) -> None:
    """
    Perform a local DB lookup synchronously; if not found, queue API fallback asynchronously.
    """
    global _rid_lookup_enabled, _rid_lookup_failure_logged
    if not _rid_lookup_enabled or lookup_serial is None or not serial_number:
        return
    if drone_obj.rid_lookup_success or drone_obj.rid_lookup_pending:
        return

    # Synchronous local DB only (fast, no network)
    try:
        res = lookup_serial(serial_number, use_api_fallback=False)  # type: ignore
        drone_obj.apply_rid_lookup_result(res)
    except FileNotFoundError as e:
        if not _rid_lookup_failure_logged:
            logger.warning("FAA RID lookup skipped (database missing?): %s", e)
            _rid_lookup_failure_logged = True
        _rid_lookup_enabled = False
        return
    except Exception as e:
        if not _rid_lookup_failure_logged:
            logger.warning("FAA RID lookup failed (local DB); disabling: %s", e)
            _rid_lookup_failure_logged = True
        _rid_lookup_enabled = False
        return

    # If not found locally, queue API fallback in the background
    if not drone_obj.rid_lookup_success:
        _queue_rid_lookup(drone_obj, serial_number)

UA_TYPE_MAPPING = {
    0: 'No UA type defined',
    1: 'Aeroplane/Airplane (Fixed wing)',
    2: 'Helicopter or Multirotor',
    3: 'Gyroplane',
    4: 'VTOL (Vertical Take-Off and Landing)',
    5: 'Ornithopter',
    6: 'Glider',
    7: 'Kite',
    8: 'Free Balloon',
    9: 'Captive Balloon',
    10: 'Airship (Blimp)',
    11: 'Free Fall/Parachute',
    12: 'Rocket',
    13: 'Tethered powered aircraft',
    14: 'Ground Obstacle',
    15: 'Other type',
}

# Setup logging
def setup_logging(debug: bool):
    """Set up logging configuration."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if debug else logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    ch.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(ch)

logger = logging.getLogger(__name__)

def setup_tls_context(tak_tls_p12: str, tak_tls_p12_pass: Optional[str], tak_tls_skip_verify: bool) -> Optional[ssl.SSLContext]:
    """Sets up the TLS context using the provided PKCS#12 file."""
    if not tak_tls_p12:
        return None

    try:
        with open(tak_tls_p12, 'rb') as p12_file:
            p12_data = p12_file.read()
    except OSError as err:
        logger.critical("Failed to read TAK server TLS PKCS#12 file: %s.", err)
        sys.exit(1)

    p12_pass = tak_tls_p12_pass.encode() if tak_tls_p12_pass else None

    try:
        key, cert, more_certs = pkcs12.load_key_and_certificates(p12_data, p12_pass)
    except Exception as err:
        logger.critical("Failed to load TAK server TLS PKCS#12: %s.", err)
        sys.exit(1)

    if key is None:
        logger.critical("PKCS#12 loaded but contains no private key (did you export a truststore instead of a client identity?).")
        sys.exit(1)
    if cert is None:
        logger.critical("PKCS#12 loaded but contains no end-entity certificate (need client cert + private key).")
        sys.exit(1)

    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption() if not p12_pass else serialization.BestAvailableEncryption(p12_pass)
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    ca_bytes = b"".join(
        cert.public_bytes(serialization.Encoding.PEM) for cert in more_certs
    ) if more_certs else b""

    # Create temporary files and ensure they are deleted on exit
    key_temp = tempfile.NamedTemporaryFile(delete=False)
    cert_temp = tempfile.NamedTemporaryFile(delete=False)
    ca_temp = tempfile.NamedTemporaryFile(delete=False)

    key_temp.write(key_bytes)
    cert_temp.write(cert_bytes)
    ca_temp.write(ca_bytes)

    key_temp_path = key_temp.name
    cert_temp_path = cert_temp.name
    ca_temp_path = ca_temp.name

    key_temp.close()
    cert_temp.close()
    ca_temp.close()

    # Register cleanup
    atexit.register(os.unlink, key_temp_path)
    atexit.register(os.unlink, cert_temp_path)
    atexit.register(os.unlink, ca_temp_path)

    try:
        tls_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        tls_context.load_cert_chain(certfile=cert_temp_path, keyfile=key_temp_path, password=p12_pass)
        if ca_bytes:
            tls_context.load_verify_locations(cafile=ca_temp_path)
        if tak_tls_skip_verify:
            tls_context.check_hostname = False
            tls_context.verify_mode = ssl.CERT_NONE
    except Exception as e:
        logger.critical(f"Failed to set up TLS context: {e}")
        sys.exit(1)

    return tls_context

def zmq_to_cot(
    zmq_host: str,
    zmq_port: int,
    zmq_status_port: Optional[int],
    tak_host: Optional[str] = None,
    tak_port: Optional[int] = None,
    tak_tls_context: Optional[ssl.SSLContext] = None,
    tak_protocol: Optional[str] = 'TCP',
    multicast_address: Optional[str] = None,
    multicast_port: Optional[int] = None,
    enable_multicast: bool = False,
    rate_limit: float = 1.0,
    max_drones: int = 30,
    inactivity_timeout: float = 60.0,
    multicast_interface: Optional[str] = None,
    multicast_ttl: int = 1,
    enable_receive: bool = False,
    lattice_sink: Optional[object] = None,
    mqtt_sink: Optional[object] = None,
    adsb_enabled=False,
    adsb_json_url=None,
    adsb_uid_prefix="adsb-",
    adsb_cot_stale=15.0,
    adsb_rate_limit=3.0,
    adsb_min_alt=0,
    adsb_max_alt=0,
):
    """Main function to convert ZMQ messages to CoT and send to TAK server."""
    global KIT_ID

    system_status_latest = None

    context = zmq.Context()
    telemetry_socket = context.socket(zmq.SUB)
    telemetry_socket.connect(f"tcp://{zmq_host}:{zmq_port}")
    telemetry_socket.setsockopt_string(zmq.SUBSCRIBE, "")
    logger.debug(f"Connected to telemetry ZMQ socket at tcp://{zmq_host}:{zmq_port}")

    # Only create and connect the status_socket if zmq_status_port is provided
    if zmq_status_port:
        status_socket = context.socket(zmq.SUB)
        status_socket.connect(f"tcp://{zmq_host}:{zmq_status_port}")
        status_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        logger.debug(f"Connected to status ZMQ socket at tcp://{zmq_host}:{zmq_status_port}")
    else:
        status_socket = None
        logger.debug("No ZMQ status port provided. Skipping status socket setup.")

    # Initialize TAK clients based on protocol
    tak_client = None
    tak_udp_client = None

    if tak_host and tak_port:
        if tak_protocol == 'TCP':
            tak_client = TAKClient(tak_host, tak_port, tak_tls_context)
            threading.Thread(target=tak_client.run_connect_loop, daemon=True).start()
        elif tak_protocol == 'UDP':
            tak_udp_client = TAKUDPClient(tak_host, tak_port)
        else:
            logger.critical(f"Unsupported TAK protocol: {tak_protocol}. Must be 'TCP' or 'UDP'.")
            sys.exit(1)

    # Initialize CotMessenger
    cot_messenger = CotMessenger(
        tak_client=tak_client,
        tak_udp_client=tak_udp_client,
        multicast_address=multicast_address,
        multicast_port=multicast_port,
        enable_multicast=enable_multicast,
        multicast_interface=multicast_interface,
        multicast_ttl=multicast_ttl,
        enable_receive=enable_receive
    )

    # Start receiver if enabled
    cot_messenger.start_receiver()

    # ---- Optional Kismet ingest (Wi-Fi / Bluetooth) ----
    kismet_thread = None
    kismet_stop = None
    if config.get("kismet_enabled"):
        try:
            kismet_thread, kismet_stop = start_kismet_worker(
                host=config.get("kismet_host", "http://127.0.0.1:2501"),
                apikey=config.get("kismet_apikey") or None,
                cot_messenger=cot_messenger,
                seen_by=KIT_ID,
            )
        except Exception as e:
            logger.warning(f"Failed to start Kismet ingest: {e}")
            kismet_thread, kismet_stop = None, None
    else:
        logger.info("Kismet ingestion disabled; set kismet_enabled=true to enable.")

    # ---- Build sinks list (Lattice + MQTT) ----
    extra_sinks = []

    # Lattice (optional; already created above)
    if lattice_sink is not None:
        extra_sinks.append(lattice_sink)

    if mqtt_sink is not None:
        extra_sinks.append(mqtt_sink)

    # Initialize DroneManager with CotMessenger (no legacy MQTT args)
    drone_manager = DroneManager(
        max_drones=max_drones,
        rate_limit=rate_limit,
        inactivity_timeout=inactivity_timeout,
        cot_messenger=cot_messenger,
        extra_sinks=extra_sinks,
    )

    # ---- Optional ADS-B worker (dump1090 aircraft.json) ----
    adsb_stop = threading.Event()
    adsb_thread = None

    if adsb_enabled and adsb_json_url:
        try:
            logger.info(f"ADS-B enabled; starting worker for {adsb_json_url}")
            adsb_thread = threading.Thread(
                target=adsb_worker_loop,
                name="adsb-worker",
                kwargs=dict(
                    json_url=adsb_json_url,
                    cot_messenger=cot_messenger,
                    uid_prefix=adsb_uid_prefix,
                    rate_limit=adsb_rate_limit,
                    stale=adsb_cot_stale,
                    min_alt=adsb_min_alt,
                    max_alt=adsb_max_alt,
                    poll_interval=1.0,
                    stop_event=adsb_stop,
                    aircraft_cache=drone_manager.aircraft,
                    seen_by=KIT_ID,
                ),
                daemon=True,
            )
            adsb_thread.start()
        except Exception as e:
            logger.exception(f"Failed to start ADS-B worker: {e}")
    else:
        logger.info("ADS-B ingestion disabled or adsb_json_url not set; skipping ADS-B worker.")

    # Start API server (read-only) to expose status and tracks
    api_server = None
    api_thread = None
    try:
        if config.get("api_enabled", True):
            env_host = os.environ.get("DRAGONSYNC_API_HOST")
            env_port = os.environ.get("DRAGONSYNC_API_PORT")
            api_host = env_host if env_host is not None else config.get("api_host", "0.0.0.0")
            api_port = int(env_port) if env_port is not None else int(config.get("api_port", 8088))
            api_server = serve_api(
                manager=drone_manager,
                system_status_provider=lambda: system_status_latest,
                kit_id_provider=lambda: KIT_ID,
                config_provider=_sanitized_config,
                update_check_provider=update_check,
                host=api_host,
                port=api_port,
            )
            api_thread = threading.Thread(target=api_server.serve_forever, name="api-server", daemon=True)
            api_thread.start()
            logger.info("Started DragonSync API server thread.")
        else:
            logger.info("DragonSync API disabled via config.")
    except Exception as e:
        logger.warning("API server failed to start: %s", e)

    def signal_handler(sig, frame):
        """Handles signal interruptions for graceful shutdown."""
        logger.info("Interrupted by user")
        telemetry_socket.close()
        if status_socket:
            status_socket.close()
        if not context.closed:
            context.term()
        if tak_client:
            tak_client.close()
        if tak_udp_client:
            tak_udp_client.close()
        if cot_messenger:
            cot_messenger.close()
        if drone_manager:
            try:
                drone_manager.close()
            except Exception:
                pass
        try:
            if api_server:
                api_server.shutdown()
        except Exception:
            pass
        # Stop RID lookup worker
        try:
            if _rid_lookup_queue is not None:
                _rid_lookup_queue.put_nowait(None)
        except Exception:
            pass
        try:
            if kismet_stop:
                kismet_stop.set()
                if kismet_thread and kismet_thread.is_alive():
                    kismet_thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            adsb_stop.set()
            if adsb_thread and adsb_thread.is_alive():
                adsb_thread.join(timeout=2.0)
        except Exception:
            pass
        logger.info("Cleaned up ZMQ resources")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    poller = zmq.Poller()
    poller.register(telemetry_socket, zmq.POLLIN)
    if status_socket:
        poller.register(status_socket, zmq.POLLIN)

    try:
        while True:
            try:
                socks = dict(poller.poll(timeout=1000))
            except zmq.error.ZMQError as e:
                # ETERM happens during shutdown; otherwise, log and keep going
                if e.errno == getattr(zmq, "ETERM", None):
                    break
                logger.exception(f"Poller error: {e}")
                time.sleep(0.5)
                continue
            if telemetry_socket in socks and socks[telemetry_socket] == zmq.POLLIN:
                try:
                    message = telemetry_socket.recv_json()
                except ValueError as e:
                    logger.warning(f"Telemetry JSON decode failed: {e}")
                    continue
                except Exception as e:
                    logger.exception(f"Telemetry recv failed: {e}")
                    continue
            
                try:
                    drone_info = parse_drone_info(message, UA_TYPE_MAPPING)
                except Exception as e:
                    logger.exception(f"parse_drone_info crashed; skipping message: {e}")
                    continue
            
                if not drone_info:
                    logger.debug("Parser returned no drone_info; skipping.")
                    continue

                # --- Updated logic for handling serial vs. CAA-only broadcasts ---
                if 'id' in drone_info:
                    if not drone_info['id'].startswith('drone-'):
                        drone_info['id'] = f"drone-{drone_info['id']}"
                        logger.debug(f"Ensured drone id with prefix: {drone_info['id']}")
                    else:
                        logger.debug(f"Drone id already has prefix: {drone_info['id']}")
                    drone_id = drone_info['id']
                    serial_number = drone_id[len("drone-"):] if drone_id.startswith("drone-") else drone_id

                    logger.debug(f"Drone detailts for id: {drone_id} - {drone_info}")

                    if drone_id in drone_manager.drone_dict:
                        drone = drone_manager.drone_dict[drone_id]
                        _apply_rid_lookup(drone, serial_number)
                        drone.update(
                            lat=drone_info.get('lat', 0.0),
                            lon=drone_info.get('lon', 0.0),
                            speed=drone_info.get('speed', 0.0),
                            vspeed=drone_info.get('vspeed', 0.0),
                            alt=drone_info.get('alt', 0.0),
                            height=drone_info.get('height', 0.0),
                            pilot_lat=drone_info.get('pilot_lat', 0.0),
                            pilot_lon=drone_info.get('pilot_lon', 0.0),
                            description=drone_info.get('description', ""),
                            mac=drone_info.get('mac', ""),
                            rssi=drone_info.get('rssi', 0),
                            home_lat=drone_info.get('home_lat', 0.0),
                            home_lon=drone_info.get('home_lon', 0.0),
                            id_type=drone_info.get('id_type', ""),
                            ua_type=drone_info.get('ua_type'),
                            ua_type_name=drone_info.get('ua_type_name', ""),
                            operator_id_type=drone_info.get('operator_id_type', ""),
                            operator_id=drone_info.get('operator_id', ""),
                            op_status=drone_info.get('op_status', ""),
                            height_type=drone_info.get('height_type', ""),
                            ew_dir=drone_info.get('ew_dir', ""),
                            direction=drone_info.get('direction'),
                            speed_multiplier=drone_info.get('speed_multiplier'),
                            pressure_altitude=drone_info.get('pressure_altitude'),
                            vertical_accuracy=drone_info.get('vertical_accuracy', ""),
                            horizontal_accuracy=drone_info.get('horizontal_accuracy', ""),
                            baro_accuracy=drone_info.get('baro_accuracy', ""),
                            speed_accuracy=drone_info.get('speed_accuracy', ""),
                            timestamp=drone_info.get('timestamp', ""),
                            rid_timestamp=drone_info.get('rid_timestamp', ""),
                            observed_at=time.time(),
                            timestamp_accuracy=drone_info.get('timestamp_accuracy', ""),
                            index=drone_info.get('index', 0),
                            runtime=drone_info.get('runtime', 0),
                            caa_id=drone_info.get('caa', ""),
                            freq=drone_info.get('freq'),
                            seen_by=KIT_ID
                        )
                        logger.debug(f"Updated drone: {drone_id}")
                    else:
                        drone = Drone(
                            id=drone_info['id'],
                            lat=drone_info.get('lat', 0.0),
                            lon=drone_info.get('lon', 0.0),
                            speed=drone_info.get('speed', 0.0),
                            vspeed=drone_info.get('vspeed', 0.0),
                            alt=drone_info.get('alt', 0.0),
                            height=drone_info.get('height', 0.0),
                            pilot_lat=drone_info.get('pilot_lat', 0.0),
                            pilot_lon=drone_info.get('pilot_lon', 0.0),
                            description=drone_info.get('description', ""),
                            mac=drone_info.get('mac', ""),
                            rssi=drone_info.get('rssi', 0),
                            home_lat=drone_info.get('home_lat', 0.0),
                            home_lon=drone_info.get('home_lon', 0.0),
                            id_type=drone_info.get('id_type', ""),
                            ua_type=drone_info.get('ua_type'),
                            ua_type_name=drone_info.get('ua_type_name', ""),
                            operator_id_type=drone_info.get('operator_id_type', ""),
                            operator_id=drone_info.get('operator_id', ""),
                            op_status=drone_info.get('op_status', ""),
                            height_type=drone_info.get('height_type', ""),
                            ew_dir=drone_info.get('ew_dir', ""),
                            direction=drone_info.get('direction'),
                            speed_multiplier=drone_info.get('speed_multiplier'),
                            pressure_altitude=drone_info.get('pressure_altitude'),
                            vertical_accuracy=drone_info.get('vertical_accuracy', ""),
                            horizontal_accuracy=drone_info.get('horizontal_accuracy', ""),
                            baro_accuracy=drone_info.get('baro_accuracy', ""),
                            speed_accuracy=drone_info.get('speed_accuracy', ""),
                            timestamp=drone_info.get('timestamp', ""),
                            rid_timestamp=drone_info.get('rid_timestamp', ""),
                            observed_at=time.time(),
                            timestamp_accuracy=drone_info.get('timestamp_accuracy', ""),
                            index=drone_info.get('index', 0),
                            runtime=drone_info.get('runtime', 0),
                            caa_id=drone_info.get('caa', ""),
                            freq=drone_info.get('freq'),
                            seen_by=KIT_ID
                        )
                        _apply_rid_lookup(drone, serial_number)
                        drone_manager.update_or_add_drone(drone_id, drone)
                        logger.debug(f"Added new drone: {drone_id}")
                else:
                    # No primary serial broadcast present (CAA-only)
                    if 'mac' in drone_info and drone_info['mac']:
                        updated = False
                        for d in drone_manager.drone_dict.values():
                            if d.mac == drone_info['mac']:
                                d.update(
                                    lat=drone_info.get('lat', 0.0),
                                    lon=drone_info.get('lon', 0.0),
                                    speed=drone_info.get('speed', 0.0),
                                    vspeed=drone_info.get('vspeed', 0.0),
                                    alt=drone_info.get('alt', 0.0),
                                    height=drone_info.get('height', 0.0),
                                    pilot_lat=drone_info.get('pilot_lat', 0.0),
                                    pilot_lon=drone_info.get('pilot_lon', 0.0),
                                    description=drone_info.get('description', ""),
                                    mac=drone_info.get('mac', ""),
                                    rssi=drone_info.get('rssi', 0),
                                    home_lat=drone_info.get('home_lat', 0.0),
                                    home_lon=drone_info.get('home_lon', 0.0),
                                    id_type=drone_info.get('id_type', ""),
                                    ua_type=drone_info.get('ua_type'),
                                    ua_type_name=drone_info.get('ua_type_name', ""),
                                    operator_id_type=drone_info.get('operator_id_type', ""),
                                    operator_id=drone_info.get('operator_id', ""),
                                    op_status=drone_info.get('op_status', ""),
                                    height_type=drone_info.get('height_type', ""),
                                    ew_dir=drone_info.get('ew_dir', ""),
                                    direction=drone_info.get('direction'),
                                    speed_multiplier=drone_info.get('speed_multiplier'),
                                    pressure_altitude=drone_info.get('pressure_altitude'),
                                    vertical_accuracy=drone_info.get('vertical_accuracy', ""),
                                    horizontal_accuracy=drone_info.get('horizontal_accuracy', ""),
                                    baro_accuracy=drone_info.get('baro_accuracy', ""),
                                    speed_accuracy=drone_info.get('speed_accuracy', ""),
                                    timestamp=drone_info.get('timestamp', ""),
                                    rid_timestamp=drone_info.get('rid_timestamp', ""),
                                    observed_at=time.time(),
                                    timestamp_accuracy=drone_info.get('timestamp_accuracy', ""),
                                    index=drone_info.get('index', 0),
                                    runtime=drone_info.get('runtime', 0),
                                    caa_id=drone_info.get('caa', ""),
                                    freq=drone_info.get('freq'),
                                    seen_by=KIT_ID
                                )
                                logger.debug(f"Updated existing drone with CAA info for MAC: {drone_info['mac']}")
                                updated = True
                                break
                        if not updated:
                            logger.debug(f"CAA-only message received for MAC {drone_info['mac']} but no matching drone record exists. Skipping for now.")
                    else:
                        logger.warning("CAA-only message received without a MAC. Skipping.")

            if status_socket and status_socket in socks and socks[status_socket] == zmq.POLLIN:
                try:
                    status_message = status_socket.recv_json()
                except ValueError as e:
                    logger.warning(f"Status JSON decode failed: {e}")
                    continue
                except Exception as e:
                    logger.exception(f"Status recv failed: {e}")
                    continue
            
                try:
                    serial_number = status_message.get('serial_number', 'unknown')
                    # Update kit identifier to align with system CoT identity
                    if serial_number and serial_number != "unknown":
                        KIT_ID = f"wardragon-{serial_number}"
                    else:
                        KIT_ID = KIT_ID_DEFAULT
                    gps_data = status_message.get('gps_data', {})
                    lat = get_float(gps_data.get('latitude', 0.0))
                    lon = get_float(gps_data.get('longitude', 0.0))
                    alt = get_float(gps_data.get('altitude', 0.0))
                    speed = get_float(gps_data.get('speed', 0.0))
                    track = get_float(gps_data.get('track', 0.0))
            
                    system_stats = status_message.get('system_stats', {})
                    ant_sdr_temps = status_message.get('ant_sdr_temps', {})
                    pluto_temp = ant_sdr_temps.get('pluto_temp', 'N/A')
                    zynq_temp  = ant_sdr_temps.get('zynq_temp',  'N/A')
            
                    cpu_usage = get_float(system_stats.get('cpu_usage', 0.0))
                    memory = system_stats.get('memory', {})
                    memory_total = get_float(memory.get('total', 0.0)) / (1024 * 1024)
                    memory_available = get_float(memory.get('available', 0.0)) / (1024 * 1024)
                    disk = system_stats.get('disk', {})
                    disk_total = get_float(disk.get('total', 0.0)) / (1024 * 1024)
                    disk_used = get_float(disk.get('used', 0.0)) / (1024 * 1024)
                    temperature = get_float(system_stats.get('temperature', 0.0))
                    uptime = get_float(system_stats.get('uptime', 0.0))
            
                    if lat == 0.0 and lon == 0.0:
                        logger.warning("Latitude and longitude are missing or zero. Proceeding with [0.0, 0.0].")
            
                    system_status = SystemStatus(
                        serial_number=serial_number,
                        lat=lat, lon=lon, alt=alt, speed=speed, track=track,
                        cpu_usage=cpu_usage,
                        memory_total=memory_total, memory_available=memory_available,
                        disk_total=disk_total, disk_used=disk_used,
                        temperature=temperature, uptime=uptime,
                        pluto_temp=pluto_temp, zynq_temp=zynq_temp
                    )
                    system_status_latest = system_status
                    cot_xml = system_status.to_cot_xml()
                except Exception as e:
                    logger.exception(f"Status handling failed: {e}")
                    continue
            
                try:
                    cot_messenger.send_cot(cot_xml)
                    logger.info("Sent CoT message to TAK/multicast.")
                except Exception as e:
                    logger.exception(f"send_cot(system) failed: {e}")
            
                if lattice_sink is not None:
                    try:
                        lattice_sink.publish_system(status_message)
                        #TODO: Add system_status to lattice sink system for health components
                        logger.debug(f"Published system status to Lattice: {status_message}")
                    except Exception as e:
                        logger.warning(f"Lattice publish_system failed: {e}")

                # Optional publish to MQTT sink if present
                if mqtt_sink is not None and hasattr(mqtt_sink, "publish_system"):
                    try:
                        mqtt_sink.publish_system(status_message)
                    except Exception as e:
                        logger.warning(f"MQTT publish_system failed: {e}")

            # Send drone updates via DroneManager
            try:
                drone_manager.send_updates()
            except Exception as e:
                logger.exception(f"send_updates failed (continuing): {e}")
    except KeyboardInterrupt:
        signal_handler(None, None)  # exits 0
    except Exception:
        logger.exception("Top-level error in zmq_to_cot — exiting for systemd restart")
        try:
            telemetry_socket.close(0)
        except Exception:
            pass
        try:
            if status_socket:
                status_socket.close(0)
        except Exception:
            pass
        try:
            if not context.closed:
                context.term()
        except Exception:
            pass
        # ensure sinks shut down
        try:
            if 'drone_manager' in locals() and drone_manager:
                drone_manager.close()
        except Exception:
            pass
        sys.exit(1)

# Configuration and Execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZMQ to CoT converter.")
    parser.add_argument("-c", "--config", type=str, help="Path to config file", default="config.ini")
    parser.add_argument("--zmq-host", help="ZMQ server host")
    parser.add_argument("--zmq-port", type=int, help="ZMQ server port for telemetry")
    parser.add_argument("--zmq-status-port", type=int, help="ZMQ server port for system status")
    parser.add_argument("--tak-host", type=str, help="TAK server hostname or IP address (optional)")
    parser.add_argument("--tak-port", type=int, help="TAK server port (optional)")
    parser.add_argument("--tak-protocol", type=str, choices=['TCP', 'UDP'], help="TAK server communication protocol (TCP or UDP)")
    parser.add_argument("--tak-tls-p12", type=str, help="Path to TAK server TLS PKCS#12 file (optional, for TCP)")
    parser.add_argument("--tak-tls-p12-pass", type=str, help="Password for TAK server TLS PKCS#12 file (optional, for TCP)")
    parser.add_argument("--tak-tls-skip-verify", action="store_true", help="(UNSAFE) Disable TLS server verification")
    parser.add_argument("--tak-multicast-addr", type=str, help="TAK multicast address (optional)")
    parser.add_argument("--tak-multicast-port", type=int, help="TAK multicast port (optional)")
    parser.add_argument("--enable-multicast", action="store_true", help="Enable sending to multicast address")
    parser.add_argument("--tak-multicast-interface", type=str, help="Multicast interface (IP or name) to use for sending multicast")
    parser.add_argument("--multicast-ttl", type=int, help="TTL for multicast packets (default: 1)")
    parser.add_argument("--enable-receive", action="store_true", help="Enable receiving multicast CoT messages")
    parser.add_argument("--rate-limit", type=float, help="Rate limit for sending CoT messages (seconds)")
    parser.add_argument("--max-drones", type=int, help="Maximum number of drones to track simultaneously")
    parser.add_argument("--inactivity-timeout", type=float, help="Time in seconds before a drone is considered inactive")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--mqtt-enabled", action="store_true", default=None,
                    help="Enable MQTT publishing of drone JSON (overrides config if set)")
    parser.add_argument("--mqtt-host", type=str, help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, help="MQTT broker port")
    parser.add_argument("--mqtt-topic", type=str, help="MQTT topic for drone messages")
    parser.add_argument("--mqtt-username", type=str, help="MQTT username")
    parser.add_argument("--mqtt-password", type=str, help="MQTT password")
    parser.add_argument("--mqtt-tls", action="store_true", help="Enable MQTT TLS")
    parser.add_argument("--mqtt-ca-file", type=str, help="Path to CA file for MQTT TLS")
    parser.add_argument("--mqtt-certfile", type=str, help="Path to client certificate for MQTT TLS (optional)")
    parser.add_argument("--mqtt-keyfile", type=str, help="Path to client key for MQTT TLS (optional)")
    parser.add_argument("--mqtt-tls-insecure", action="store_true", help="(UNSAFE) Skip MQTT TLS hostname/chain verification")
    parser.add_argument("--mqtt-retain", action="store_true", default=None,
                        help="Retain published state topics (default: true if unset)")
    parser.add_argument("--mqtt-per-drone-enabled", action="store_true", default=None,
                        help="Publish one message per drone to base/<drone_id>")
    parser.add_argument("--mqtt-per-drone-base", type=str,
                        help="Base topic for per-drone messages (default: wardragon/drone)")
    parser.add_argument("--mqtt-ha-enabled", action="store_true", default=None,
                        help="Enable Home Assistant MQTT Discovery")
    parser.add_argument("--mqtt-ha-prefix", type=str,
                        help="HA discovery prefix (default: homeassistant)")
    parser.add_argument("--mqtt-ha-device-base", type=str,
                        help="Base used for HA device unique_id (default: wardragon_drone)")
    # ---- Lattice (optional) ----
    parser.add_argument("--lattice-enabled", action="store_true", help="Enable publishing to Lattice")
    parser.add_argument("--lattice-token", type=str, help="Lattice environment token (or env LATTICE_TOKEN / ENVIRONMENT_TOKEN)")
    parser.add_argument("--lattice-base-url", type=str, help="Full base URL, e.g. https://lattice-XXXX.env.sandboxes.developer.anduril.com (or env LATTICE_BASE_URL)")
    parser.add_argument("--lattice-endpoint", type=str, help="Endpoint host only (no scheme) to build base_url, e.g. lattice-XXXX.env.sandboxes.developer.anduril.com (or env LATTICE_ENDPOINT)")
    parser.add_argument("--lattice-sandbox-token", type=str, help="Sandboxes Bearer token (or env SANDBOXES_TOKEN / LATTICE_SANDBOX_TOKEN)")
    parser.add_argument("--lattice-source-name", type=str, help="Provenance source name (or env LATTICE_SOURCE_NAME)")
    parser.add_argument("--lattice-drone-rate", type=float, help="Drone publish rate to Lattice (Hz)")
    parser.add_argument("--lattice-wd-rate", type=float, help="WarDragon publish rate to Lattice (Hz)")
    args = parser.parse_args()

    # Load config file if provided
    config_values = {}
    if args.config:
        config_values = load_config(args.config)

    # Retrieve 'tak_host' and 'tak_port' with precedence
    tak_host = args.tak_host if args.tak_host is not None else get_str(config_values.get("tak_host"))
    tak_port = args.tak_port if args.tak_port is not None else get_int(config_values.get("tak_port"), None)

    if tak_host and tak_port:
        # Fetch the raw protocol value from command-line or config
        tak_protocol_raw = args.tak_protocol if args.tak_protocol is not None else config_values.get("tak_protocol")
        # Use get_str to sanitize the input, defaulting to "TCP" if necessary
        tak_protocol_sanitized = get_str(tak_protocol_raw, "TCP")
        # Convert to uppercase
        tak_protocol = tak_protocol_sanitized.upper()
    else:
        # If TAK host and port are not provided, set tak_protocol to None
        tak_protocol = None
        logger.info("TAK host and port not provided. 'tak_protocol' will be ignored.")

    tak_multicast_interface = args.tak_multicast_interface if args.tak_multicast_interface is not None else get_str(config_values.get("tak_multicast_interface"))

    # Assign configuration values, giving precedence to command-line arguments
    config = {
        "zmq_host": args.zmq_host if args.zmq_host is not None else get_str(config_values.get("zmq_host", "127.0.0.1")),
        "zmq_port": args.zmq_port if args.zmq_port is not None else get_int(config_values.get("zmq_port"), 4224),
        "zmq_status_port": args.zmq_status_port if args.zmq_status_port is not None else get_int(config_values.get("zmq_status_port"), None),
        "tak_host": tak_host,
        "tak_port": tak_port,
        "tak_protocol": tak_protocol,
        "tak_tls_p12": args.tak_tls_p12 if args.tak_tls_p12 is not None else get_str(config_values.get("tak_tls_p12")),
        "tak_tls_p12_pass": args.tak_tls_p12_pass if args.tak_tls_p12_pass is not None else get_str(config_values.get("tak_tls_p12_pass")),
        "tak_tls_skip_verify": args.tak_tls_skip_verify if args.tak_tls_skip_verify else get_bool(config_values.get("tak_tls_skip_verify"), False),
        "api_enabled": get_bool(config_values.get("api_enabled"), True),
        "api_host": get_str(config_values.get("api_host", "0.0.0.0")),
        "api_port": get_int(config_values.get("api_port", 8088)),
        "tak_multicast_addr": args.tak_multicast_addr if args.tak_multicast_addr is not None else get_str(config_values.get("tak_multicast_addr")),
        "tak_multicast_port": args.tak_multicast_port if args.tak_multicast_port is not None else get_int(config_values.get("tak_multicast_port"), None),
        "enable_multicast": args.enable_multicast or get_bool(config_values.get("enable_multicast"), False),
        "rate_limit": args.rate_limit if args.rate_limit is not None else get_float(config_values.get("rate_limit", 1.0)),
        "max_drones": args.max_drones if args.max_drones is not None else get_int(config_values.get("max_drones", 30)),
        "inactivity_timeout": args.inactivity_timeout if args.inactivity_timeout is not None else get_float(config_values.get("inactivity_timeout", 60.0)),
        "tak_multicast_interface": tak_multicast_interface,
        "multicast_ttl": args.multicast_ttl if args.multicast_ttl is not None else get_int(config_values.get("multicast_ttl", 1)),
        "enable_receive": args.enable_receive or get_bool(config_values.get("enable_receive", False)),
        "mqtt_enabled": args.mqtt_enabled if hasattr(args, "mqtt_enabled") and args.mqtt_enabled is not None else get_bool(config_values.get("mqtt_enabled", False)),
        "mqtt_host": args.mqtt_host if hasattr(args, "mqtt_host") and args.mqtt_host is not None else get_str(config_values.get("mqtt_host", "127.0.0.1")),
        "mqtt_port": args.mqtt_port if hasattr(args, "mqtt_port") and args.mqtt_port is not None else get_int(config_values.get("mqtt_port", 1883)),
        "mqtt_topic": args.mqtt_topic if hasattr(args, "mqtt_topic") and args.mqtt_topic is not None else get_str(config_values.get("mqtt_topic", "wardragon/drones")),
        "mqtt_username": args.mqtt_username if hasattr(args, "mqtt_username") and args.mqtt_username is not None else get_str(config_values.get("mqtt_username")),
        "mqtt_password": args.mqtt_password if hasattr(args, "mqtt_password") and args.mqtt_password is not None else get_str(config_values.get("mqtt_password")),
        "mqtt_tls": args.mqtt_tls if hasattr(args, "mqtt_tls") and args.mqtt_tls is not None else get_bool(config_values.get("mqtt_tls", False)),
        "mqtt_ca_file": args.mqtt_ca_file if hasattr(args, "mqtt_ca_file") and args.mqtt_ca_file is not None else get_str(config_values.get("mqtt_ca_file")),
        "mqtt_certfile": args.mqtt_certfile if hasattr(args, "mqtt_certfile") and args.mqtt_certfile is not None else get_str(config_values.get("mqtt_certfile")),
        "mqtt_keyfile": args.mqtt_keyfile if hasattr(args, "mqtt_keyfile") and args.mqtt_keyfile is not None else get_str(config_values.get("mqtt_keyfile")),
        "mqtt_tls_insecure": args.mqtt_tls_insecure if hasattr(args, "mqtt_tls_insecure") and args.mqtt_tls_insecure is not None else get_bool(config_values.get("mqtt_tls_insecure", False)),
        "mqtt_retain": args.mqtt_retain if hasattr(args, "mqtt_retain") and args.mqtt_retain is not None else get_bool(config_values.get("mqtt_retain", True)),
        "mqtt_per_drone_enabled": args.mqtt_per_drone_enabled if hasattr(args, "mqtt_per_drone_enabled") and args.mqtt_per_drone_enabled is not None else get_bool(config_values.get("mqtt_per_drone_enabled", False)),
        "mqtt_per_drone_base": args.mqtt_per_drone_base if hasattr(args, "mqtt_per_drone_base") and args.mqtt_per_drone_base is not None else get_str(config_values.get("mqtt_per_drone_base", "wardragon/drone")),
        "mqtt_ha_enabled": args.mqtt_ha_enabled if hasattr(args, "mqtt_ha_enabled") and args.mqtt_ha_enabled is not None else get_bool(config_values.get("mqtt_ha_enabled", False)),
        "mqtt_ha_prefix": args.mqtt_ha_prefix if hasattr(args, "mqtt_ha_prefix") and args.mqtt_ha_prefix is not None else get_str(config_values.get("mqtt_ha_prefix", "homeassistant")),
        "mqtt_ha_device_base": args.mqtt_ha_device_base if hasattr(args, "mqtt_ha_device_base") and args.mqtt_ha_device_base is not None else get_str(config_values.get("mqtt_ha_device_base", "wardragon_drone")),

        # ---- Kismet (optional) config ----
        "kismet_enabled": get_bool(config_values.get("kismet_enabled"), False),
        "kismet_host": get_str(config_values.get("kismet_host", "http://127.0.0.1:2501")),
        "kismet_apikey": get_str(config_values.get("kismet_apikey")),

        # ---- Lattice (optional) config block ----
        "lattice_enabled": args.lattice_enabled or get_bool(config_values.get("lattice_enabled"), False),
        # Environment (Authorization) token
        "lattice_token": args.lattice_token if args.lattice_token is not None else (
            os.getenv("LATTICE_TOKEN") or os.getenv("ENVIRONMENT_TOKEN") or get_str(config_values.get("lattice_token"))
        ),
        # Prefer full base URL if provided
        "lattice_base_url": args.lattice_base_url if args.lattice_base_url is not None else (
            os.getenv("LATTICE_BASE_URL") or get_str(config_values.get("lattice_base_url"))
        ),
        # Or endpoint host to build base_url
        "lattice_endpoint": args.lattice_endpoint if args.lattice_endpoint is not None else (
            os.getenv("LATTICE_ENDPOINT") or get_str(config_values.get("lattice_endpoint"))
        ),
        # Sandboxes token for anduril-sandbox-authorization
        "lattice_sandbox_token": args.lattice_sandbox_token if args.lattice_sandbox_token is not None else (
            os.getenv("SANDBOXES_TOKEN") or os.getenv("LATTICE_SANDBOX_TOKEN") or get_str(config_values.get("lattice_sandbox_token"))
        ),
        "lattice_source_name": args.lattice_source_name if args.lattice_source_name is not None else (
            os.getenv("LATTICE_SOURCE_NAME") or get_str(config_values.get("lattice_source_name", "DragonSync"))
        ),
        "lattice_drone_rate": args.lattice_drone_rate if args.lattice_drone_rate is not None else get_float(config_values.get("lattice_drone_rate", 1.0)),
        "lattice_wd_rate": args.lattice_wd_rate if args.lattice_wd_rate is not None else get_float(config_values.get("lattice_wd_rate", 0.2)),
                
        # ---- ADS-B (dump1090) optional integration ----
        "adsb_enabled": get_bool(config_values.get("adsb_enabled"), False),
        "adsb_json_url": get_str(config_values.get("adsb_json_url")),
        "adsb_uid_prefix": get_str(config_values.get("adsb_uid_prefix", "adsb-")),
        "adsb_cot_stale": get_float(config_values.get("adsb_cot_stale", 15.0)),
        "adsb_rate_limit": get_float(config_values.get("adsb_rate_limit", 3.0)),
        "adsb_min_alt": get_int(config_values.get("adsb_min_alt", 0)),
        "adsb_max_alt": get_int(config_values.get("adsb_max_alt", 0)),
        # FAA RID API fallback (disabled by default; local DB still used)
        "rid_api_enabled": get_bool(config_values.get("rid_api_enabled"), False),
    }

    # Configure RID API fallback toggle
    _rid_api_enabled = bool(config.get("rid_api_enabled", False))

    setup_logging(args.debug)
    logger.info("Starting ZMQ to CoT converter with log level: %s", "DEBUG" if args.debug else "INFO")
    _start_rid_lookup_worker()

    
    # Validate configuration
    try:
        validate_config(config)
    except ValueError as ve:
        logger.critical(f"Configuration Error: {ve}")
        sys.exit(1)

    # Sanitize config for API exposure (redact secrets)
    def _sanitized_config():
        cfg = {}
        try:
            cfg["tak"] = {
                "host": config.get("tak_host"),
                "port": config.get("tak_port"),
                "protocol": config.get("tak_protocol"),
                "multicast_addr": config.get("tak_multicast_addr"),
                "multicast_port": config.get("tak_multicast_port"),
                "enable_multicast": bool(config.get("enable_multicast")),
                "enable_receive": bool(config.get("enable_receive")),
                "multicast_interface": config.get("tak_multicast_interface"),
                "multicast_ttl": config.get("multicast_ttl"),
                "tls": bool(config.get("tak_tls_p12")),
            }
            cfg["api"] = {
                "enabled": bool(config.get("api_enabled", True)),
                "host": config.get("api_host"),
                "port": config.get("api_port"),
            }
            cfg["zmq"] = {
                "host": config.get("zmq_host"),
                "port": config.get("zmq_port"),
                "status_port": config.get("zmq_status_port"),
            }
            cfg["mqtt"] = {
                "enabled": bool(config.get("mqtt_enabled")),
                "host": config.get("mqtt_host"),
                "port": config.get("mqtt_port"),
                "topic": config.get("mqtt_topic"),
                "per_drone_enabled": bool(config.get("mqtt_per_drone_enabled")),
                "per_drone_base": config.get("mqtt_per_drone_base"),
                "ha_enabled": bool(config.get("mqtt_ha_enabled")),
                "ha_prefix": config.get("mqtt_ha_prefix"),
            }
            cfg["adsb"] = {
                "enabled": bool(config.get("adsb_enabled")),
                "json_url": config.get("adsb_json_url"),
                "uid_prefix": config.get("adsb_uid_prefix"),
                "cot_stale": config.get("adsb_cot_stale"),
                "rate_limit": config.get("adsb_rate_limit"),
                "min_alt": config.get("adsb_min_alt"),
                "max_alt": config.get("adsb_max_alt"),
            }
            cfg["lattice"] = {
                "enabled": bool(config.get("lattice_enabled")),
                "base_url": config.get("lattice_base_url") or config.get("lattice_endpoint"),
                "source_name": config.get("lattice_source_name"),
                "drone_rate": config.get("lattice_drone_rate"),
                "wardragon_rate": config.get("lattice_wd_rate"),
            }
        except Exception:
            pass
        return cfg


    # Setup TLS context only if tak_protocol is set (which implies tak_host and tak_port are provided)
    tak_tls_context = setup_tls_context(
        tak_tls_p12=config["tak_tls_p12"],
        tak_tls_p12_pass=config["tak_tls_p12_pass"],
        tak_tls_skip_verify=config["tak_tls_skip_verify"]
    ) if config["tak_protocol"] == 'TCP' and config["tak_tls_p12"] else None

    # MQTT sink (optional)
    mqtt_sink = None
    try:
        from mqtt_sink import MqttSink  # your existing helper
    except Exception as e:
        MqttSink = None  # keep running even if not present
        if config.get("mqtt_enabled"):
            logger.warning("MQTT enabled but mqtt_sink import failed: %s", e)

    if config.get("mqtt_enabled") and MqttSink is not None:
        try:
            mqtt_sink = MqttSink(
                host=config.get("mqtt_host", "127.0.0.1"),
                port=int(config.get("mqtt_port", 1883)),
                username=(config.get("mqtt_username") or None),
                password=(config.get("mqtt_password") or None),
                tls=bool(config.get("mqtt_tls", False)),
                ca_file=(config.get("mqtt_ca_file") or None),
                certfile=(config.get("mqtt_certfile") or None),
                keyfile=(config.get("mqtt_keyfile") or None),
                tls_insecure=bool(config.get("mqtt_tls_insecure", False)),
                aggregate_topic=config.get("mqtt_topic", "wardragon/drones"),
                retain_state=bool(config.get("mqtt_retain", True)),
                per_drone_enabled=bool(config.get("mqtt_per_drone_enabled", False)),
                per_drone_base=config.get("mqtt_per_drone_base", "wardragon/drone"),
                ha_enabled=bool(config.get("mqtt_ha_enabled", False)),
                ha_prefix=config.get("mqtt_ha_prefix", "homeassistant"),
                ha_device_base=config.get("mqtt_ha_device_base", "wardragon_drone"),
            )
            logger.info("MQTT sink enabled.")
        except Exception as e:
            logger.exception("Failed to initialize MQTT sink: %s", e)
            mqtt_sink = None

    # ---- Optional Lattice sink construction (import-protected) ----
    lattice_sink = None
    if config["lattice_enabled"]:
        try:
            from lattice_sink import LatticeSink  # local helper that wraps the Lattice SDK
        except Exception as e:
            logger.warning(f"Lattice enabled, but lattice_sink import failed: {e}")
            LatticeSink = None  # type: ignore
        if "LatticeSink" in locals() and LatticeSink is not None:
            token = (config.get("lattice_token") or "").strip()
            if not token:
                logger.warning("Lattice enabled, but no environment token provided (set --lattice-token or env LATTICE_TOKEN/ENVIRONMENT_TOKEN). Disabling.")
            else:
                try:
                    # Resolve base_url
                    base_url = (config.get("lattice_base_url") or "").strip()
                    if not base_url:
                        endpoint = (config.get("lattice_endpoint") or "").strip()
                        if endpoint:
                            base_url = endpoint if endpoint.startswith(("http://", "https://")) else f"https://{endpoint}"
                    sb = (config.get("lattice_sandbox_token") or "").strip()
                    env_tok_len = len(token)
                    sb_tok_len = len(sb)
                    logger.debug(f"Lattice base_url resolved: {base_url!r}, env_token_len={env_tok_len}, sandbox_token_len={sb_tok_len}")
                    lattice_sink = LatticeSink(
                        token=token,
                        base_url=base_url or None,
                        drone_hz=config.get("lattice_drone_rate", 1.0),
                        wardragon_hz=config.get("lattice_wd_rate", 0.2),
                        source_name=config.get("lattice_source_name", "DragonSync"),
                        sandbox_token=sb or None,
                    )
                    logger.info("Lattice sink enabled.")
                except Exception as e:
                    logger.exception(f"Failed to initialize Lattice sink: {e}")

    zmq_to_cot(
        zmq_host=config["zmq_host"],
        zmq_port=config["zmq_port"],
        zmq_status_port=config["zmq_status_port"],
        tak_host=config["tak_host"],
        tak_port=config["tak_port"],
        tak_tls_context=tak_tls_context,
        tak_protocol=config["tak_protocol"],
        multicast_address=config["tak_multicast_addr"],
        multicast_port=config["tak_multicast_port"],
        enable_multicast=config["enable_multicast"],
        rate_limit=config["rate_limit"],
        max_drones=config["max_drones"],
        inactivity_timeout=config["inactivity_timeout"],
        multicast_interface=config["tak_multicast_interface"],
        multicast_ttl=config["multicast_ttl"],
        enable_receive=config["enable_receive"],
        lattice_sink=lattice_sink,
        mqtt_sink=mqtt_sink,
        adsb_enabled=config["adsb_enabled"],
        adsb_json_url=config["adsb_json_url"],
        adsb_uid_prefix=config["adsb_uid_prefix"],
        adsb_cot_stale=config["adsb_cot_stale"],
        adsb_rate_limit=config["adsb_rate_limit"],
        adsb_min_alt=config["adsb_min_alt"],
        adsb_max_alt=config["adsb_max_alt"],
    )
