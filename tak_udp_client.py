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

import socket
import logging

logger = logging.getLogger(__name__)

class TAKUDPClient:
    """Client for sending CoT messages to TAK server via UDP."""

    def __init__(self, tak_host: str, tak_port: int):
        self.tak_host = tak_host
        self.tak_port = tak_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.debug(f"Initialized TAKUDPClient for {self.tak_host}:{self.tak_port}")

    # Added Properties
    @property
    def host(self) -> str:
        """Returns the TAK server host."""
        return self.tak_host

    @property
    def port(self) -> int:
        """Returns the TAK server port."""
        return self.tak_port

    def send(self, cot_xml: bytes):
        """Sends a CoT XML message to the TAK server via UDP."""
        try:
            self.sock.sendto(cot_xml, (self.tak_host, self.tak_port))
            logger.debug(f"Sent CoT message via UDP to {self.tak_host}:{self.tak_port}")
        except Exception as e:
            logger.error(f"Error sending CoT message via UDP: {e}")

    def close(self):
        """Closes the UDP socket."""
        try:
            self.sock.close()
            logger.debug("Closed TAKUDPClient socket")
        except Exception as e:
            logger.error(f"Error closing TAKUDPClient socket: {e}")
