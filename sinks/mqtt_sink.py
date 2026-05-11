#!/usr/bin/env python3
"""
Copyright 2025-2026 CEMAXECUTER LLC.

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

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None  # type: ignore

_log = logging.getLogger(__name__)


class MqttSink:
    """
    Generic MQTT sink with optional Home Assistant discovery.

    Exposed methods (used by DroneManager):
      - publish_drone(drone_obj)
      - publish_pilot(drone_id, lat, lon, alt=0.0)
      - publish_home(drone_id, lat, lon, alt=0.0)
      - mark_inactive(drone_id)
      - close()

    Features:
      - Aggregate JSON publish to a single topic (optional)
      - Per-drone JSON publish to `<per_drone_base>/<drone_id>` (optional)
      - HA discovery (optional):
          * rich per-drone sensors (lat/lon/alt/speed/etc.)
          * a device_tracker per drone for a clean Map dot
          * OPTIONAL extra device_trackers for pilot/home dots
      - Lightweight in-memory state cache so pilot/home updates merge cleanly.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False,
        ca_file: Optional[str] = None,
        certfile: Optional[str] = None,
        keyfile: Optional[str] = None,
        tls_insecure: bool = False,
        client_id: Optional[str] = None,
        keepalive: int = 60,
        qos: int = 0,
        # Aggregate / per-drone topics
        aggregate_topic: Optional[str] = "wardragon/drones",
        per_drone_enabled: bool = False,
        per_drone_base: str = "wardragon/drone",
        retain_state: bool = False,
        # Signals (optional)
        signals_enabled: bool = False,
        signals_topic: str = "wardragon/signals",
        # Aircraft (optional)
        aircraft_enabled: bool = False,
        aircraft_topic: str = "wardragon/aircraft",
        # HA signal tracker (optional)
        ha_signal_tracker: bool = False,
        ha_signal_base: str = "wardragon_signal",
        ha_signal_id: str = "signal_latest",
        # Home Assistant
        ha_enabled: bool = False,
        ha_prefix: str = "homeassistant",
        ha_device_base: str = "wardragon_drone",
        # Multi-kit support: provider that returns the current kit_id (e.g.
        # "wardragon-G6PA14100J63"). When set, system/service topics and HA
        # system device unique IDs are scoped per-kit so multiple kits sharing
        # one MQTT broker don't collide on retained state. Backward compatible:
        # if not provided, falls back to a "wardragon-unknown" placeholder.
        kit_id_provider: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt not installed but required for MqttSink")

        self.qos = int(qos)
        self.retain_state = bool(retain_state)

        self.aggregate_topic = aggregate_topic or None
        self.per_drone_enabled = bool(per_drone_enabled)
        self.per_drone_base = per_drone_base.strip().strip("/")

        self.signals_enabled = bool(signals_enabled)
        self.signals_topic = signals_topic.strip().strip("/") if signals_topic else ""
        self._signal_state_topic = ""

        self.aircraft_enabled = bool(aircraft_enabled)
        self.aircraft_topic = aircraft_topic.strip().strip("/") if aircraft_topic else ""

        self.ha_enabled = bool(ha_enabled)
        self.ha_prefix = ha_prefix.strip().strip("/")
        self.ha_device_base = ha_device_base.strip()
        self.ha_signal_tracker = bool(ha_signal_tracker)
        self.ha_signal_base = ha_signal_base.strip()
        self.ha_signal_id = ha_signal_id.strip()

        self._seen_for_ha: set[str] = set()
        self._state_cache: Dict[str, Dict[str, Any]] = {}
        self._ha_signal_announced: set[str] = set()

        # system device (WarDragon kit) tracking
        self._ha_system_announced = False
        self._sys_base = "wardragon/system"

        # Multi-kit scoping: provider for the kit_id, plus connect-state
        # flags used by the lazy-connect background watcher.
        self._kit_id_provider: Optional[Callable[[], Optional[str]]] = kit_id_provider
        self._connected: bool = False
        self._connect_args: Optional[tuple] = None  # (host, port, keepalive); set below
        self._lazy_connect_thread: Optional[threading.Thread] = None

        # --- MQTT client setup (robust across paho v1.x and v2.x) ---
        protocol = getattr(mqtt, "MQTTv5", getattr(mqtt, "MQTTv311"))  # prefer v5 when available

        client_kwargs: Dict[str, Any] = {
            "client_id": client_id,
            "protocol": protocol,
        }

        # paho-mqtt v2 introduced explicit callback API versions
        try:
            cb_api_ver = getattr(mqtt, "CallbackAPIVersion", None)
            if cb_api_ver is not None:
                # Use the modern 5-arg callback signatures when possible
                client_kwargs["callback_api_version"] = cb_api_ver.VERSION2
        except Exception:
            pass

        # clean_session is invalid with MQTTv5; include only for v3.1.1
        if protocol != getattr(mqtt, "MQTTv5", object()):
            client_kwargs["clean_session"] = True

        self.client = mqtt.Client(**client_kwargs)  # type: ignore

        # Use paho's internal logging if available
        try:
            self.client.enable_logger(_log)  # paho >= 1.6
        except Exception:
            pass

        if username is not None:
            self.client.username_pw_set(username, password)

        if tls:
            try:
                self.client.tls_set(
                    ca_certs=ca_file,
                    certfile=certfile,
                    keyfile=keyfile,
                )
                self.client.tls_insecure_set(bool(tls_insecure))
            except Exception as e:
                _log.critical("MqttSink TLS configuration failed: %s", e)
                raise

        # paho restricts Will Topic to be set before connect(). We try to
        # resolve kit_id synchronously here so warm boots (cache populated)
        # get full LWT support. Cold first boot (no cache yet) connects
        # without LWT this run; the kit-id cache populates after wardragon_monitor's
        # first cycle, so every subsequent boot is warm.
        initial_kit_id = self._kit_id()
        if initial_kit_id:
            try:
                self.client.will_set(
                    f"wardragon/service/{initial_kit_id}/availability",
                    "offline", qos=self.qos, retain=True,
                )
            except Exception:
                pass
        else:
            _log.info(
                "MqttSink: kit_id not yet resolved at startup; connecting "
                "without LWT this run. Future boots will have full LWT once "
                "/var/lib/wardragon/kit-id is populated."
            )

        # Callbacks compatible with both API versions
        def _on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                _log.info("MqttSink connected to %s:%s", host, port)
                # Birth on the kit-scoped service availability topic. Skipped
                # silently if kit_id is not known yet — the lazy-connect worker
                # publishes the online message belatedly once kit_id resolves.
                kit_id = self._kit_id()
                if kit_id:
                    try:
                        self.client.publish(
                            f"wardragon/service/{kit_id}/availability",
                            "online", qos=self.qos, retain=True,
                        )
                    except Exception:
                        pass
            else:
                _log.warning("MqttSink connect rc=%s", rc)

        def _on_disconnect(client, userdata, *args, **kwargs):
            # Tolerant of paho v1 (rc, [properties]) and v2 VERSION2
            # (disconnect_flags, reason_code, properties) callback signatures.
            if len(args) == 3:
                rc = args[1]  # v2: reason_code
            elif args:
                rc = args[0]  # v1: rc
            else:
                rc = None
            _log.info("MqttSink disconnected rc=%s", rc)

        self.client.on_connect = _on_connect
        self.client.on_disconnect = _on_disconnect

        # Make reconnects resilient to broker restarts/outages
        try:
            self.client.reconnect_delay_set(min_delay=2, max_delay=30)
        except Exception:
            pass

        # Connect to the broker immediately. Drone, aircraft, and signal
        # publishes do NOT depend on kit_id — they're keyed by drone_id /
        # source — so they should flow from t=0 regardless of kit identity.
        # Only kit-scoped system/service publishes wait for kit_id (handled
        # in publish_system and the deferred-online worker below).
        try:
            self.client.connect_async(host, int(port), keepalive=int(keepalive))
            self.client.loop_start()
            self._connected = True
        except Exception as e:
            _log.warning("MqttSink connect_async failed (will retry via paho loop): %s", e)

        # If kit_id wasn't known at construction (cold first boot), spawn a
        # background watcher that publishes the per-kit "online" message as
        # soon as kit_id resolves. No reconnect/disconnect — purely a delayed
        # availability publish for that one boot.
        if not initial_kit_id:
            self._lazy_connect_thread = threading.Thread(
                target=self._publish_kit_online_when_ready,
                name="mqtt-kit-online-deferred",
                daemon=True,
            )
            self._lazy_connect_thread.start()

    # ────────────────────────────────────────────────
    # Public API used by DroneManager
    # ────────────────────────────────────────────────

    def publish_drone(self, d: Any) -> None:
        """Publish full drone state (aggregate + per-drone), HA discovery once."""
        drone_id = str(_get_attr(d, "id", "unknown")) or "unknown"

        # Build a clean, JSON-friendly dict
        payload = self._drone_to_state(d)

        # Update cache & publish
        self._merge_and_publish(drone_id, payload)

        # HA discovery (once per drone) — requires per-drone topics
        if self.ha_enabled and self.per_drone_enabled and drone_id not in self._seen_for_ha:
            try:
                state_topic = self._per_drone_topic(drone_id)
                # device_tracker for clean Map dot
                self._publish_ha_device_tracker(drone_id, state_topic, payload)
                # rich sensors for telemetry dashboards
                self._publish_ha_sensors(drone_id, state_topic, payload)
                self._seen_for_ha.add(drone_id)
            except Exception as e:
                _log.warning("HA discovery failed for %s: %s", drone_id, e)

        # Mark drone tracker online only when we have a real position (not 0,0)
        if self.ha_enabled and self.per_drone_enabled:
            try:
                avail, _, _ = self._availability_topics(drone_id)
                lat = payload.get("lat", 0.0) or 0.0
                lon = payload.get("lon", 0.0) or 0.0
                status = "online" if (lat or lon) else "offline"
                self.client.publish(avail, status, qos=self.qos, retain=True)
            except Exception as e:
                _log.warning("Drone availability publish failed for %s: %s", drone_id, e)

    def publish_pilot(self, drone_id: str, lat: float, lon: float, alt: float = 0.0) -> None:
        """Merge pilot fields into the per-drone state and republish (if enabled)."""
        drone_id = str(drone_id)
        if drone_id.startswith("pilot-"):
            drone_id = drone_id[len("pilot-") :]

        patch = {
            "pilot_lat": _f(lat),
            "pilot_lon": _f(lon),
            "pilot_alt": _f(alt),
        }
        self._merge_and_publish(drone_id, patch)

        # Also feed the pilot device_tracker with proper latitude/longitude keys
        if self.ha_enabled and self.per_drone_enabled:
            attr_topic = f"{self._per_drone_topic(drone_id)}/pilot_attrs"
            try:
                attrs = {
                    "latitude": _f(lat),
                    "longitude": _f(lon),
                    "gps_accuracy": 0.0,  # set if you have it
                }
                info = self.client.publish(attr_topic, json.dumps(attrs), qos=self.qos, retain=True)
                self._warn_if_publish_failed(info)
            except Exception as e:
                _log.warning("Pilot attrs publish failed for %s: %s", drone_id, e)
            # Mark pilot tracker online
            try:
                _, pilot_avail, _ = self._availability_topics(drone_id)
                self.client.publish(pilot_avail, "online", qos=self.qos, retain=True)
            except Exception as e:
                _log.warning("Pilot availability publish failed for %s: %s", drone_id, e)

    def publish_home(self, drone_id: str, lat: float, lon: float, alt: float = 0.0) -> None:
        """Merge home fields into the per-drone state and republish (if enabled)."""
        drone_id = str(drone_id)
        if drone_id.startswith("home-"):
            drone_id = drone_id[len("home-") :]

        patch = {
            "home_lat": _f(lat),
            "home_lon": _f(lon),
            "home_alt": _f(alt),
        }
        self._merge_and_publish(drone_id, patch)

        # Also feed the home device_tracker with proper latitude/longitude keys
        if self.ha_enabled and self.per_drone_enabled:
            attr_topic = f"{self._per_drone_topic(drone_id)}/home_attrs"
            try:
                attrs = {
                    "latitude": _f(lat),
                    "longitude": _f(lon),
                    "gps_accuracy": 0.0,  # set if you have it
                }
                info = self.client.publish(attr_topic, json.dumps(attrs), qos=self.qos, retain=True)
                self._warn_if_publish_failed(info)
            except Exception as e:
                _log.warning("Home attrs publish failed for %s: %s", drone_id, e)
            # Mark home tracker online
            try:
                _, _, home_avail = self._availability_topics(drone_id)
                self.client.publish(home_avail, "online", qos=self.qos, retain=True)
            except Exception as e:
                _log.warning("Home availability publish failed for %s: %s", drone_id, e)

    def close(self) -> None:
        """Stop MQTT loop and disconnect cleanly."""
        try:
            # Mark system + service offline on the per-kit topics before
            # disconnect. If kit_id never resolved (broken wardragon_monitor
            # for the entire process lifetime), we have no kit identity to
            # publish offline against — skip silently rather than pollute the
            # broker with a placeholder. Drone/aircraft/signal topics are
            # unaffected by this skip.
            kit_id_for_close = self._kit_id()
            if kit_id_for_close:
                try:
                    self.client.publish(
                        f"{self._sys_base}/{kit_id_for_close}/availability",
                        "offline", qos=self.qos, retain=True,
                    )
                except Exception:
                    pass
                try:
                    self.client.publish(
                        f"wardragon/service/{kit_id_for_close}/availability",
                        "offline", qos=self.qos, retain=True,
                    )
                except Exception:
                    pass
            if self.signals_topic:
                try:
                    self.client.publish(f"{self.signals_topic}/availability", "offline", qos=self.qos, retain=True)
                except Exception:
                    pass
            self.client.loop_stop()
        except Exception as e:
            _log.warning("MqttSink loop_stop error: %s", e)
        try:
            self.client.disconnect()
        except Exception as e:
            _log.warning("MqttSink disconnect error: %s", e)

    def mark_pilot_offline(self, drone_id: str) -> None:
        """Mark just the pilot tracker as offline (coords reverted to 0,0)."""
        if not self.ha_enabled or not self.per_drone_enabled:
            return
        _, pilot_avail, _ = self._availability_topics(str(drone_id))
        try:
            self.client.publish(pilot_avail, "offline", qos=self.qos, retain=True)
        except Exception as e:
            _log.warning("Pilot offline publish failed for %s: %s", drone_id, e)

    def mark_home_offline(self, drone_id: str) -> None:
        """Mark just the home tracker as offline (coords reverted to 0,0)."""
        if not self.ha_enabled or not self.per_drone_enabled:
            return
        _, _, home_avail = self._availability_topics(str(drone_id))
        try:
            self.client.publish(home_avail, "offline", qos=self.qos, retain=True)
        except Exception as e:
            _log.warning("Home offline publish failed for %s: %s", drone_id, e)

    # NEW: allow manager to mark trackers 'not_home' when a drone ages out
    def mark_inactive(self, drone_id: str) -> None:
        """
        Mark the drone and its pilot/home trackers as 'offline' (unavailable) in HA.
        This hides dots on the map but keeps last-known coordinates in history.
        """
        avail, pilot_avail, home_avail = self._availability_topics(str(drone_id))
        for t in (avail, pilot_avail, home_avail):
            try:
                self.client.publish(t, "offline", qos=self.qos, retain=True)
            except Exception as e:
                _log.warning("MqttSink mark_inactive availability publish failed for %s: %s", t, e)

    # ────────────────────────────────────────────────
    # Internals
    # ────────────────────────────────────────────────

    def _merge_and_publish(self, drone_id: str, patch: Dict[str, Any]) -> None:
        """
        Merge fields into cache and publish to aggregate/per-drone as configured.
        """
        cur = self._state_cache.get(drone_id, {})
        cur.update(patch)
        cur["id"] = drone_id
        self._state_cache[drone_id] = cur

        # Aggregate stream (single topic, all drones as independent messages)
        if self.aggregate_topic:
            try:
                payload = json.dumps(cur, default=_json_default)
                info = self.client.publish(self.aggregate_topic, payload, qos=self.qos, retain=self.retain_state)
                self._warn_if_publish_failed(info)
            except Exception as e:
                _log.warning("Aggregate publish failed for %s: %s", drone_id, e)

        # Per-drone state (required for HA sensors/device_tracker)
        if self.per_drone_enabled:
            try:
                topic = self._per_drone_topic(drone_id)
                payload = json.dumps(cur, default=_json_default)
                info = self.client.publish(topic, payload, qos=self.qos, retain=self.retain_state)
                self._warn_if_publish_failed(info)
            except Exception as e:
                _log.warning("Per-drone publish failed for %s: %s", drone_id, e)

    def publish_signal(self, signal: Dict[str, Any]) -> None:
        """
        Publish a signal alert payload (e.g., FPV) to a dedicated topic.
        """
        if not self.signals_enabled or not self.signals_topic:
            return
        try:
            state = self._signal_to_state(signal)
            payload = json.dumps(state, default=_json_default)
            info = self.client.publish(
                self.signals_topic, payload, qos=self.qos, retain=self.retain_state
            )
            self._warn_if_publish_failed(info)
            if self.ha_enabled and self.ha_signal_tracker:
                seen_by = state.get("seen_by") or "unknown"
                subtopic = self._signal_topic_for_seen_by(seen_by)
                self._ensure_ha_signal_tracker(seen_by, subtopic)
                self.client.publish(subtopic, payload, qos=self.qos, retain=self.retain_state)
                self.client.publish(
                    f"{subtopic}/state",
                    "not_home",
                    qos=self.qos,
                    retain=self.retain_state,
                )
                self.client.publish(
                    f"{subtopic}/availability",
                    "online",
                    qos=self.qos,
                    retain=True,
                )
        except Exception as e:
            _log.warning("Signal publish failed: %s", e)

    def publish_aircraft(self, aircraft: Dict[str, Any]) -> None:
        """
        Publish ADS-B aircraft to MQTT aggregate topic only.
        No per-aircraft topics or HA discovery (would overwhelm system with 100+ aircraft).
        """
        if not self.aircraft_enabled or not self.aircraft_topic:
            return
        try:
            state = self._aircraft_to_state(aircraft)
            payload = json.dumps(state, default=_json_default)
            info = self.client.publish(
                self.aircraft_topic, payload, qos=self.qos, retain=False  # Don't retain aircraft
            )
            self._warn_if_publish_failed(info)
        except Exception as e:
            _log.warning("Aircraft publish failed: %s", e)

    def _warn_if_publish_failed(self, info) -> None:
        try:
            rc = getattr(info, "rc", None)
            if rc is not None and rc != getattr(mqtt, "MQTT_ERR_SUCCESS", 0):  # type: ignore
                _log.warning("MQTT publish returned rc=%s", rc)
        except Exception:
            pass

    def _kit_id(self) -> Optional[str]:
        """Return the current kit_id (slugified for MQTT topic safety) or None.

        Returns None when no provider was supplied, when the provider raises,
        or when the provider returns the placeholder default ('wardragon-unknown').
        Callers should treat None as 'kit identity not yet resolved' and skip
        any kit-scoped publish — never publish to a 'wardragon-unknown' topic
        as a placeholder, since that pollutes retained state and breaks
        multi-kit collision-freeness during the startup window.
        """
        if self._kit_id_provider is None:
            return None
        try:
            kid = self._kit_id_provider()
        except Exception:
            return None
        if not isinstance(kid, str) or not kid:
            return None
        if kid == "wardragon-unknown":
            return None
        return _slugify(kid)

    def _publish_kit_online_when_ready(self) -> None:
        """Background thread: wait for kit_id to resolve, then publish online
        to the per-kit service availability topic.

        Started only when kit_id was not known at MqttSink construction
        (cold first boot). The broker connection is already up by this
        point — drones/aircraft/signals are publishing normally — we just
        need to belatedly announce kit identity once wardragon_monitor's
        first status message arrives.

        Polls forever with escalating log severity. If kit_id never resolves
        (broken wardragon_monitor or missing dmidecode), the kit will be
        silent on the per-kit service topic, which is the correct
        professional behavior — operators investigate the underlying issue
        rather than seeing phantom 'wardragon-unknown' state on the broker.
        """
        poll_interval = 0.5
        elapsed = 0.0
        warned_2min = False
        warned_5min = False
        last_error_log = -1e9

        while True:
            kit_id = self._kit_id()
            if kit_id:
                try:
                    self.client.publish(
                        f"wardragon/service/{kit_id}/availability",
                        "online", qos=self.qos, retain=True,
                    )
                    _log.info(
                        "MqttSink kit_id resolved (%s); per-kit service "
                        "availability published online", kit_id,
                    )
                except Exception as e:
                    _log.warning("MqttSink belated availability publish failed: %s", e)
                return

            time.sleep(poll_interval)
            elapsed += poll_interval

            # Escalating severity: helps operators distinguish "monitor is
            # warming up" from "monitor is broken" without spamming the log.
            if elapsed >= 120.0 and not warned_2min:
                _log.warning(
                    "MqttSink: kit_id still not resolved after 2 minutes. "
                    "Check 'systemctl status wardragon-monitor.service' and "
                    "/var/lib/wardragon/kit-id; per-kit MQTT topics will not "
                    "publish until kit identity is known."
                )
                warned_2min = True
            if elapsed >= 300.0 and not warned_5min:
                _log.warning(
                    "MqttSink: kit_id still not resolved after 5 minutes. "
                    "wardragon_monitor.service appears unhealthy. Drones, "
                    "aircraft, and FPV signals continue to publish normally; "
                    "system telemetry and per-kit availability are deferred "
                    "until kit identity resolves."
                )
                warned_5min = True
            if elapsed >= 1800.0 and (elapsed - last_error_log) >= 1800.0:
                _log.error(
                    "MqttSink: kit_id unresolved for over 30 minutes. The "
                    "kit cannot self-identify; per-kit MQTT topics remain "
                    "unpublished. Investigate wardragon_monitor.service and "
                    "dmidecode availability."
                )
                last_error_log = elapsed

    def _per_drone_topic(self, drone_id: str) -> str:
        return f"{self.per_drone_base}/{drone_id}"

    def _signal_to_state(self, sig: Dict[str, Any]) -> Dict[str, Any]:
        lat = _f(sig.get("lat", 0.0))
        lon = _f(sig.get("lon", 0.0))
        state = {
            "uid": sig.get("uid"),
            "signal_type": sig.get("signal_type", "fpv"),
            "source": sig.get("source"),
            "callsign": sig.get("callsign"),
            "description": sig.get("description"),
            "center_hz": _f_or_none(sig.get("center_hz")),
            "bandwidth_hz": _f_or_none(sig.get("bandwidth_hz")),
            "pal": _f_or_none(sig.get("pal_conf")),
            "ntsc": _f_or_none(sig.get("ntsc_conf")),
            "rssi": _f_or_none(sig.get("rssi")),  # Signal strength in dBm
            "sensor_lat": _f_or_none(sig.get("sensor_lat")),
            "sensor_lon": _f_or_none(sig.get("sensor_lon")),
            "sensor_alt": _f_or_none(sig.get("sensor_alt")),
            "lat": lat,
            "lon": lon,
            "alt": _f(sig.get("alt", 0.0)),
            "latitude": lat,
            "longitude": lon,
            "gps_accuracy": _f(sig.get("radius_m", 0.0)),
            "radius_m": _f(sig.get("radius_m", 0.0)),
            "seen_by": sig.get("seen_by"),
            "observed_at": sig.get("observed_at", None),
        }
        return state

    def _aircraft_to_state(self, aircraft: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ADS-B aircraft dict to MQTT state payload."""
        lat = _f(aircraft.get("lat", 0.0))
        lon = _f(aircraft.get("lon", 0.0))

        # Get altitude (prefer geometric, fallback to barometric)
        alt = aircraft.get("alt_geom")
        if alt is None:
            alt = aircraft.get("alt_baro", 0)

        state = {
            "icao": aircraft.get("hex", "").strip().upper(),
            "callsign": (aircraft.get("flight") or "").strip(),
            "registration": aircraft.get("reg", ""),
            "lat": lat,
            "lon": lon,
            "latitude": lat,
            "longitude": lon,
            "alt": _f(alt),
            "altitude_ft": _f(alt),
            "speed": _f(aircraft.get("gs", 0.0)),  # Ground speed in knots
            "speed_kt": _f(aircraft.get("gs", 0.0)),
            "track": _f(aircraft.get("track", 0.0)),  # True track
            "heading": _f(aircraft.get("track", 0.0)),
            "vertical_rate": _f_or_none(aircraft.get("baro_rate")),
            "squawk": aircraft.get("squawk", ""),
            "category": aircraft.get("category", ""),
            "on_ground": bool(aircraft.get("onground") or aircraft.get("OnGround", False)),
            "nac_p": _f_or_none(aircraft.get("nac_p") or aircraft.get("NACp")),
            "nac_v": _f_or_none(aircraft.get("nac_v") or aircraft.get("NACv")),
            "rssi": _f_or_none(aircraft.get("rssi")),  # Signal strength from readsb (dBFS)
            "seen_by": aircraft.get("seen_by"),
            "track_type": "aircraft",
        }
        return state

    def _availability_topics(self, drone_id: str):
        base = self._per_drone_topic(drone_id)
        return (
            f"{base}/availability",       # drone tracker
            f"{base}/pilot_availability", # pilot tracker
            f"{base}/home_availability",  # home tracker
        )

    def _signal_topic_for_seen_by(self, seen_by: str) -> str:
        safe = _slugify(seen_by)
        return f"{self.signals_topic}/{safe}"

    def _ensure_ha_signal_tracker(self, seen_by: str, attr_topic: str) -> None:
        if not self.signals_topic:
            return
        safe = _slugify(seen_by)
        base_unique = f"{self.ha_signal_base}_{self.ha_signal_id}_{safe}"
        if base_unique in self._ha_signal_announced:
            return
        device = {
            "identifiers": [f"{self.ha_signal_base}:{self.ha_signal_id}:{safe}"],
            "name": f"Signal Alert ({seen_by})",
        }
        cfg_topic = f"{self.ha_prefix}/device_tracker/{base_unique}/config"
        state_topic = f"{attr_topic}/state"
        payload = {
            "name": f"Signal Alert ({seen_by})",
            "unique_id": base_unique,
            "device": device,
            "source_type": "gps",
            "state_topic": state_topic,
            "json_attributes_topic": attr_topic,
            "icon": "mdi:radio-tower",
            "availability_topic": f"{attr_topic}/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        self.client.publish(cfg_topic, json.dumps(payload), qos=self.qos, retain=True)
        self._ha_signal_announced.add(base_unique)

    def _drone_to_state(self, d: Any) -> Dict[str, Any]:
        """
        Convert the Drone object (or dict) into a compact, JSON-friendly state dict.
        """
        def g(name, default=None):
            return _get_attr(d, name, default)

        # freq: allow Hz or MHz; keep raw and also include computed MHz for convenience
        freq = g("freq", None)
        freq_mhz = _fmt_freq_mhz(freq)

        # Mirror keys for HA device_tracker and optional accuracy
        horiz_acc = g("horizontal_accuracy", 0)

        state = {
            "id": g("id", "unknown"),
            "description": g("description", ""),
            "rid_make": g("rid_make", None),
            "rid_model": g("rid_model", None),
            "rid_status": g("rid_status", None),
            "rid_tracking": g("rid_tracking", None),
            "rid_source": g("rid_source", None),
            "rid_lookup_attempted": g("rid_lookup_attempted", False),
            "rid_lookup_success": g("rid_lookup_success", False),

            # existing keys used elsewhere
            "lat": _f(g("lat", 0.0)),
            "lon": _f(g("lon", 0.0)),

            # HA device_tracker expects these names for map placement
            "latitude": _f(g("lat", 0.0)),
            "longitude": _f(g("lon", 0.0)),
            "gps_accuracy": _f(horiz_acc),  # HA compatibility

            "alt": _f(g("alt", 0.0)),
            "height": _f(g("height", 0.0)),
            "pressure_altitude": _f_or_none(g("pressure_altitude", None)),
            "speed": _f(g("speed", 0.0)),
            "vspeed": _f(g("vspeed", 0.0)),
            "speed_multiplier": _f_or_none(g("speed_multiplier", None)),
            "direction": _f(g("direction", 0.0)),
            "rssi": _f(g("rssi", 0.0)),
            "pilot_lat": _f(g("pilot_lat", 0.0)),
            "pilot_lon": _f(g("pilot_lon", 0.0)),
            "home_lat": _f(g("home_lat", 0.0)),
            "home_lon": _f(g("home_lon", 0.0)),
            "mac": g("mac", ""),
            "id_type": g("id_type", ""),
            "ua_type": g("ua_type", None),
            "ua_type_name": g("ua_type_name", ""),
            "caa_id": g("caa_id", ""),
            "operator_id_type": g("operator_id_type", ""),
            "operator_id": g("operator_id", ""),
            "op_status": g("op_status", ""),
            "height_type": g("height_type", ""),
            "ew_dir": g("ew_dir", ""),
            "timestamp": g("timestamp", ""),
            "rid_timestamp": g("rid_timestamp", g("timestamp", "")),
            "observed_at": g("observed_at", None),
            "index": g("index", 0),
            "runtime": g("runtime", 0),
            "seen_by": g("seen_by", None),
            "last_update_time": g("last_update_time", None),
            "track_type": "drone",
            # accuracy fields (RID spec strings)
            "horizontal_accuracy": g("horizontal_accuracy", ""),
            "vertical_accuracy": g("vertical_accuracy", ""),
            "baro_accuracy": g("baro_accuracy", ""),
            "speed_accuracy": g("speed_accuracy", ""),
            "timestamp_accuracy": g("timestamp_accuracy", ""),
            # radio
            "freq": freq,
            "freq_mhz": freq_mhz,
            "transport": g("transport", ""),
        }
        return state

    # ─────────────────────────── Home Assistant discovery ─────────────────────────

    def _publish_ha_sensors(self, drone_id: str, state_topic: str, sample: Dict[str, Any]) -> None:
        """
        Rich per-drone sensors (lat/lon/alt/speed/etc.) — mirrors your ZMQ script style.
        """
        base_unique = f"{self.ha_device_base}_{drone_id}"
        device = {
            "identifiers": [f"{self.ha_device_base}:{drone_id}"],
            "name": f"{drone_id}",
        }

        def sensor(uid_suffix: str, name: str, template: str, unit: Optional[str] = None,
                   device_class: Optional[str] = None, icon: Optional[str] = None):
            uid = f"{base_unique}_{uid_suffix}"
            topic = f"{self.ha_prefix}/sensor/{uid}/config"
            payload = {
                "name": name,
                "state_topic": state_topic,
                "unique_id": uid,
                "device": device,
                "value_template": template,
            }
            if unit:
                payload["unit_of_measurement"] = unit
            if device_class:
                payload["device_class"] = device_class
            if icon:
                payload["icon"] = icon
            self.client.publish(topic, json.dumps(payload), qos=self.qos, retain=True)

        # Core kinematics / position
        sensor("lat", "Latitude", "{{ value_json.lat | float | default(0) }}", "°", icon="mdi:map-marker")
        sensor("lon", "Longitude", "{{ value_json.lon | float | default(0) }}", "°", icon="mdi:map-marker")
        sensor("alt", "Altitude", "{{ value_json.alt | float | default(0) }}", "m", device_class="distance", icon="mdi:map-marker-distance")
        sensor("speed", "Speed", "{{ value_json.speed | float | default(0) }}", "m/s", device_class="speed", icon="mdi:speedometer")
        sensor("vspeed", "Vertical Speed", "{{ value_json.vspeed | float | default(0) }}", "m/s", icon="mdi:axis-z-arrow")
        sensor("height", "AGL", "{{ value_json.height | float | default(0) }}", "m", icon="mdi:altimeter")
        sensor("dir", "Course", "{{ value_json.direction | float | default(0) }}", "°", icon="mdi:compass")

        # Pilot/Home
        sensor("pilot_lat", "Pilot Latitude", "{{ value_json.pilot_lat | float | default(0) }}", "°", icon="mdi:account")
        sensor("pilot_lon", "Pilot Longitude", "{{ value_json.pilot_lon | float | default(0) }}", "°", icon="mdi:account")
        sensor("home_lat", "Home Latitude", "{{ value_json.home_lat | float | default(0) }}", "°", icon="mdi:home")
        sensor("home_lon", "Home Longitude", "{{ value_json.home_lon | float | default(0) }}", "°", icon="mdi:home")

        # Radio / link — exact template requested
        sensor("rssi", "Signal (RSSI)", "{{ value_json.rssi | float | default(0) }}", "dBm", device_class="signal_strength", icon="mdi:wifi")
        sensor("freq", "Radio Freq (MHz)", "{{ value_json.freq_mhz | float(0) }}", "MHz", icon="mdi:radio-tower")

        # Metadata
        sensor("ua_type", "UA Type", "{{ value_json.ua_type_name | default('') }}", icon="mdi:airplane")
        sensor("op_id", "Operator ID", "{{ value_json.operator_id | default('') }}", icon="mdi:id-card")
        sensor("transport", "Transport", "{{ value_json.transport | default('') }}", icon="mdi:transit-connection-variant")
        sensor("description", "Description", "{{ value_json.description | default('') }}", icon="mdi:information-outline")

        # Friendly description on device page
        sensor("main", "Drone", "{{ value_json.description | default('Drone') }}", icon="mdi:drone")

    def _publish_ha_device_tracker(self, drone_id: str, attr_topic: str, sample: Dict[str, Any]) -> None:
        """
        Minimal HA discovery for a map dot: one MQTT device_tracker per drone.
        We publish 'online' availability + default 'not_home' state; attributes live on per-drone JSON topic.
        """
        base_unique = f"{self.ha_device_base}_{drone_id}"
        device = {
            "identifiers": [f"{self.ha_device_base}:{drone_id}"],
            "name": f"{drone_id}",
        }

        drone_avail, pilot_avail, home_avail = self._availability_topics(drone_id)
        cfg_topic = f"{self.ha_prefix}/device_tracker/{base_unique}/config"
        state_topic = f"{attr_topic}/state"

        # Use entity name == drone_id (e.g., "drone-XYZ")
        payload = {
            "name": f"{drone_id}",
            "unique_id": base_unique,
            "device": device,                     # groups under the same device
            "source_type": "gps",
            "state_topic": state_topic,           # textual state (we set 'not_home' initially)
            "json_attributes_topic": attr_topic,  # lat/lon/etc. are attributes
            "icon": "mdi:drone",
            # Availability
            "availability_topic": drone_avail,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        # Retain discovery + reset state so HA derives zone from coords + availability online
        self.client.publish(cfg_topic, json.dumps(payload), qos=self.qos, retain=True)
        self.client.publish(state_topic, "None", qos=self.qos, retain=True)
        self.client.publish(drone_avail, "online", qos=self.qos, retain=True)

        # --- Pilot tracker (pilot-XYZ) ---
        tail = _tail_of_drone_id(drone_id)
        pilot_name = f"pilot-{tail}"
        pilot_unique = f"{base_unique}_pilot"
        pilot_cfg_topic = f"{self.ha_prefix}/device_tracker/{pilot_unique}/config"
        pilot_attr_topic = f"{attr_topic}/pilot_attrs"
        pilot_state_topic = f"{attr_topic}/pilot_state"
        pilot_payload = {
            "name": pilot_name,
            "unique_id": pilot_unique,
            "device": device,             # same device grouping
            "source_type": "gps",
            "state_topic": pilot_state_topic,
            "json_attributes_topic": pilot_attr_topic,
            "icon": "mdi:account",
            # Availability
            "availability_topic": pilot_avail,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        self.client.publish(pilot_cfg_topic, json.dumps(pilot_payload), qos=self.qos, retain=True)
        self.client.publish(pilot_state_topic, "None", qos=self.qos, retain=True)
        self.client.publish(pilot_avail, "offline", qos=self.qos, retain=True)

        # --- Home tracker (home-XYZ) ---
        home_name = f"home-{tail}"
        home_unique = f"{base_unique}_home"
        home_cfg_topic = f"{self.ha_prefix}/device_tracker/{home_unique}/config"
        home_attr_topic = f"{attr_topic}/home_attrs"
        home_state_topic = f"{attr_topic}/home_state"
        home_payload = {
            "name": home_name,
            "unique_id": home_unique,
            "device": device,
            "source_type": "gps",
            "state_topic": home_state_topic,
            "json_attributes_topic": home_attr_topic,
            "icon": "mdi:home",
            # Availability
            "availability_topic": home_avail,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
        self.client.publish(home_cfg_topic, json.dumps(home_payload), qos=self.qos, retain=True)
        self.client.publish(home_state_topic, "None", qos=self.qos, retain=True)
        self.client.publish(home_avail, "offline", qos=self.qos, retain=True)

    # ─────────────────────────── System device (WarDragon kit) ───────────────────

    def publish_system(self, status_message: Dict[str, Any]) -> None:
        try:
            gps = status_message.get("gps_data", {}) or {}
            sysstats = status_message.get("system_stats", {}) or {}
            temps = status_message.get("ant_sdr_temps", {}) or {}

            serial = status_message.get("serial_number", "unknown")
            lat = _f_or_zero(gps.get("latitude", 0.0))
            lon = _f_or_zero(gps.get("longitude", 0.0))
            alt = _f_or_zero(gps.get("altitude", 0.0))
            speed = _f_or_zero(gps.get("speed", 0.0))
            track = _f_or_zero(gps.get("track", 0.0))
            gps_fix = bool(gps.get("gps_fix", False))
            time_source = gps.get("time_source", None)
            gpsd_time_utc = gps.get("time_utc", None)

            cpu = _f_or_zero(sysstats.get("cpu_usage", 0.0))
            mem = sysstats.get("memory", {}) or {}
            disk = sysstats.get("disk", {}) or {}
            mem_total_mb = _f_or_zero(mem.get("total", 0.0)) / (1024 * 1024)
            mem_avail_mb = _f_or_zero(mem.get("available", 0.0)) / (1024 * 1024)
            disk_total_mb = _f_or_zero(disk.get("total", 0.0)) / (1024 * 1024)
            disk_used_mb  = _f_or_zero(disk.get("used", 0.0)) / (1024 * 1024)
            temp_c = _f_or_zero(sysstats.get("temperature", 0.0))
            uptime_s = _f_or_zero(sysstats.get("uptime", 0.0))

            pluto_temp = _f_or_none(temps.get("pluto_temp"))
            zynq_temp  = _f_or_none(temps.get("zynq_temp"))

            # Multi-kit scoping: skip kit-level publishes entirely until kit_id
            # is resolved. This avoids polluting retained state with a placeholder
            # kit identity during the startup window.
            kit_id = self._kit_id()
            if not kit_id:
                # Defer system publishing until kit_id is known. The kit serial
                # comes via the same wardragon_monitor pipeline that fed this
                # status_message; if the message is being processed, the kit_id
                # cache should also have been written, so this branch is rare.
                return

            if self.ha_enabled and not self._ha_system_announced:
                self._publish_ha_system_discovery()
                self._ha_system_announced = True

            attrs = {
                "id": f"wardragon-{serial}",
                "latitude": lat, "longitude": lon, "hae": alt,
                "cpu_usage": cpu,
                "memory_total_mb": round(mem_total_mb, 1),
                "memory_available_mb": round(mem_avail_mb, 1),
                "disk_total_mb": round(disk_total_mb, 1),
                "disk_used_mb": round(disk_used_mb, 1),
                "temperature_c": temp_c,
                "uptime_s": uptime_s,
                "pluto_temp_c": pluto_temp,
                "zynq_temp_c": zynq_temp,
                "speed_mps": speed,
                "track_deg": track,
                "gps_fix": gps_fix,
                "time_source": time_source,
                "gpsd_time_utc": gpsd_time_utc,
                "updated": int(time.time()),
            }
            scoped_base = f"{self._sys_base}/{kit_id}"
            self.client.publish(f"{scoped_base}/attrs", json.dumps(attrs), qos=self.qos, retain=False)
            self.client.publish(f"{scoped_base}/state", "online", qos=self.qos, retain=False)
            self.client.publish(f"{scoped_base}/availability", "online", qos=self.qos, retain=True)

        except Exception as e:
            _log.warning("publish_system failed: %s", e)

    def _publish_ha_system_discovery(self) -> None:
        # Multi-kit scoping: each kit registers as its own HA device with unique
        # IDs derived from kit_id. Skip discovery entirely if kit_id is not yet
        # known; publish_system retries this on every status cycle until it
        # succeeds (gated by self._ha_system_announced).
        kit_id = self._kit_id()
        if not kit_id:
            return

        device = {
            "identifiers": [f"{self.ha_device_base}:{kit_id}:system"],
            "name": f"WarDragon {kit_id}",
            "manufacturer": "CEMAXECUTER",
            "model": "WarDragon",
        }
        unique_base = f"{self.ha_device_base}_{kit_id}_system"
        scoped_sys_base = f"{self._sys_base}/{kit_id}"
        avail = f"{scoped_sys_base}/availability"
        state_topic = f"{scoped_sys_base}/state"
        attrs_topic = f"{scoped_sys_base}/attrs"

        # device_tracker for kit GPS position
        dt_cfg_topic = f"{self.ha_prefix}/device_tracker/{unique_base}/config"
        dt_payload = {
            "name": f"WarDragon {kit_id}",
            "unique_id": unique_base,
            "device": device,
            "source_type": "gps",
            "state_topic": state_topic,
            "json_attributes_topic": attrs_topic,
            "availability_topic": avail,
            "payload_available": "online",
            "payload_not_available": "offline",
            "icon": "mdi:router-wireless",
        }
        self.client.publish(dt_cfg_topic, json.dumps(dt_payload), qos=self.qos, retain=True)
        self.client.publish(state_topic, "not_home", qos=self.qos, retain=True)
        self.client.publish(avail, "online", qos=self.qos, retain=True)

        def sensor(uid_suffix: str, name: str, template: str, unit: Optional[str] = None,
                   device_class: Optional[str] = None, icon: Optional[str] = None):
            uid = f"{self.ha_device_base}_{kit_id}_system_{uid_suffix}"
            cfg = {
                "name": name,
                "unique_id": uid,
                "device": device,
                "state_topic": attrs_topic,
                "value_template": template,
            }
            if unit: cfg["unit_of_measurement"] = unit
            if device_class: cfg["device_class"] = device_class
            if icon: cfg["icon"] = icon
            self.client.publish(f"{self.ha_prefix}/sensor/{uid}/config", json.dumps(cfg), qos=self.qos, retain=True)

        # core kit sensors
        sensor("cpu", "CPU Usage", "{{ value_json.cpu_usage|float(0) }}", "%", None, "mdi:cpu-64-bit")
        sensor("mem_free", "Memory Available", "{{ value_json.memory_available_mb|float(0) }}", "MB", None, "mdi:memory")
        sensor("mem_total", "Memory Total", "{{ value_json.memory_total_mb|float(0) }}", "MB", None, "mdi:memory")
        sensor("disk_used", "Disk Used", "{{ value_json.disk_used_mb|float(0) }}", "MB", None, "mdi:harddisk")
        sensor("disk_total", "Disk Total", "{{ value_json.disk_total_mb|float(0) }}", "MB", None, "mdi:harddisk")
        sensor("temp", "System Temp", "{{ value_json.temperature_c|float(0) }}", "°C", "temperature", "mdi:thermometer")
        sensor("uptime", "Uptime", "{{ (value_json.uptime_s|float(0))/3600 }}", "h", None, "mdi:timer-outline")
        sensor("speed", "Ground Speed", "{{ value_json.speed_mps|float(0) }}", "m/s", "speed", "mdi:speedometer")
        sensor("track", "Course", "{{ value_json.track_deg|float(0) }}", "°", None, "mdi:compass")
        sensor("pluto_temp", "Pluto Temp", "{{ value_json.pluto_temp_c | float(0) }}", "°C", "temperature", "mdi:thermometer")
        sensor("zynq_temp", "Zynq Temp", "{{ value_json.zynq_temp_c | float(0) }}", "°C", "temperature", "mdi:thermometer")


# ────────────────────────────────────────────────
# Small helpers
# ────────────────────────────────────────────────

def _get_attr(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

def _f(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def _f_or_zero(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def _f_or_none(x):
    try:
        return float(x)
    except Exception:
        return None

def _fmt_freq_mhz(freq: Any) -> Optional[float]:
    try:
        f = float(freq)
    except Exception:
        return None
    if f > 1e5:  # looks like Hz
        f = f / 1e6
    return round(f, 3)

def _slugify(val: str) -> str:
    safe = []
    for ch in val:
        if ch.isalnum() or ch in ("-", "_"):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "unknown"

def _tail_of_drone_id(drone_id: str) -> str:
    """Return 'XYZ' from 'drone-XYZ' (or the original string if it lacks the prefix)."""
    return drone_id[len("drone-"):] if drone_id.startswith("drone-") else drone_id

def _json_default(o):
    try:
        return str(o)
    except Exception:
        return None
