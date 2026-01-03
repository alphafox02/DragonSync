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
"""
Minimal read-only HTTP API for DragonSync/WarDragon.

Endpoints:
  GET /status   -> system health and kit info
  GET /drones   -> list of drone/aircraft tracks (from DroneManager)
  GET /signals  -> list of signal alerts (from SignalManager)
  GET /update/check -> git update availability (read-only)

Notes:
  - This is intentionally minimal; no dependencies beyond the standard library.
  - Bind address/port can be configured via environment variables:
        DRAGONSYNC_API_HOST (default: 0.0.0.0)
        DRAGONSYNC_API_PORT (default: 8088)
  - Authentication is not implemented; consider gating by network ACLs or
    adding a simple token check if exposed beyond trusted LAN.
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class APIServer(BaseHTTPRequestHandler):
    manager = None
    signal_manager = None
    system_status_provider = None  # callable -> obj or obj directly
    kit_id_provider = None  # callable -> str
    config_provider = None  # callable -> dict (sanitized)
    update_check_provider = None  # callable -> dict

    def _write_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        try:
            data = json.dumps(payload, default=str).encode("utf-8")
        except Exception as e:
            logger.error("API JSON serialization failed: %s", e)
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/status"):
            self._handle_status()
        elif self.path.startswith("/drones"):
            self._handle_drones()
        elif self.path.startswith("/signals"):
            self._handle_signals()
        elif self.path.startswith("/config"):
            self._handle_config()
        elif self.path.startswith("/update/check"):
            self._handle_update_check()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_status(self) -> None:
        status_obj = self.__class__.system_status_provider
        if callable(status_obj):
            try:
                status_obj = status_obj()
            except Exception as e:
                logger.error("API status provider failed: %s", e)
                status_obj = None
        if status_obj is None:
            self._write_json({"error": "system status unavailable"}, status=503)
            return
        try:
            status = status_obj.to_dict()
        except Exception as e:
            logger.error("API status render failed: %s", e)
            self._write_json({"error": "status unavailable"}, status=500)
            return
        kit_id = None
        if self.kit_id_provider:
            try:
                kit_id = self.kit_id_provider()
            except Exception:
                kit_id = None
        if kit_id:
            status["kit_id"] = kit_id
        self._write_json(status)

    def _handle_drones(self) -> None:
        if self.manager is None:
            self._write_json({"error": "drone manager unavailable"}, status=503)
            return
        try:
            drones: List[Dict[str, Any]] = self.manager.export_tracks()
        except Exception as e:
            logger.error("API drone export failed: %s", e)
            self._write_json({"error": "drones unavailable"}, status=500)
            return
        self._write_json({"drones": drones})

    def _handle_signals(self) -> None:
        if self.signal_manager is None:
            self._write_json({"error": "signal manager unavailable"}, status=503)
            return
        try:
            signals: List[Dict[str, Any]] = self.signal_manager.export_signals()
        except Exception as e:
            logger.error("API signal export failed: %s", e)
            self._write_json({"error": "signals unavailable"}, status=500)
            return
        self._write_json({"signals": signals})

    def _handle_config(self) -> None:
        if self.__class__.config_provider is None:
            self._write_json({"error": "config unavailable"}, status=503)
            return
        try:
            cfg = self.__class__.config_provider()
        except Exception as e:
            logger.error("API config render failed: %s", e)
            self._write_json({"error": "config unavailable"}, status=500)
            return
        self._write_json(cfg)

    def _handle_update_check(self) -> None:
        provider = self.__class__.update_check_provider
        if provider is None:
            self._write_json({"error": "update check unavailable"}, status=503)
            return
        try:
            result = provider() if callable(provider) else provider
        except Exception as e:
            logger.error("API update check failed: %s", e)
            self._write_json({"error": "update check failed"}, status=500)
            return
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid update response"}
        self._write_json(result)


def serve_api(manager, system_status_provider, kit_id_provider, config_provider=None, update_check_provider=None,
              signal_manager=None,
              host: str = None, port: int = None):
    """
    Start the API server in a background thread.
    """
    host = host or os.environ.get("DRAGONSYNC_API_HOST", "0.0.0.0")
    port = port or int(os.environ.get("DRAGONSYNC_API_PORT", "8088"))
    APIServer.manager = manager
    APIServer.signal_manager = signal_manager
    APIServer.system_status_provider = system_status_provider
    APIServer.kit_id_provider = kit_id_provider
    APIServer.config_provider = config_provider
    APIServer.update_check_provider = update_check_provider

    server = ThreadedHTTPServer((host, port), APIServer)
    logger.info("DragonSync API listening on %s:%s", host, port)
    return server
