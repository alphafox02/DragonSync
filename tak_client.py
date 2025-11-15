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

import socket
import ssl
import logging
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)

class TAKClient:
    """Client for connecting to a TAK server using TLS and sending CoT messages."""

    def __init__(self, tak_host: str, tak_port: int, tak_tls_context: Optional[ssl.SSLContext],
                 max_retries: int = -1, backoff_factor: float = 2.0, max_backoff: float = 60.0):
        self.tak_host = tak_host
        self.tak_port = tak_port
        self.tak_tls_context = tak_tls_context
        self.sock = None
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self.retry_count = 0
        self.connecting_lock = threading.Lock()

    @property
    def host(self) -> str:
        """Returns the TAK server host."""
        return self.tak_host

    @property
    def port(self) -> int:
        """Returns the TAK server port."""
        return self.tak_port

    def connect(self):
        """Establishes a connection to the TAK server with exponential backoff capped at max_backoff."""
        while self.max_retries == -1 or self.retry_count < self.max_retries:
            try:
                self.sock = socket.create_connection((self.tak_host, self.tak_port), timeout=10)
                if self.tak_tls_context:
                    self.sock = self.tak_tls_context.wrap_socket(self.sock, server_hostname=self.tak_host)
                logger.debug("Connected to TAK server via TCP/TLS")
                self.retry_count = 0  # Reset retry count after a successful connection
                return
            except Exception as e:
                wait_time = min(self.backoff_factor ** self.retry_count, self.max_backoff)
                logger.error(f"Error connecting to TAK server: {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                self.retry_count += 1

        logger.critical("Max retries exceeded. Failed to connect to TAK server via TCP/TLS.")
        self.sock = None

    def run_connect_loop(self):
        """
        Continuously attempts to connect to the TAK server in the background.
        This method should be run in a separate daemon thread.
        """
        while True:
            if not self.sock:
                with self.connecting_lock:
                    # Double-check inside the lock to avoid race conditions.
                    if not self.sock:
                        self.connect()
            time.sleep(1)  # Check every second if connection is available

    def send(self, cot_xml: bytes):
        """Sends a CoT XML message to the TAK server via TCP/TLS."""
        try:
            if not self.sock:
                logger.error("No socket available to send CoT message via TCP/TLS.")
                return
            self.sock.sendall(cot_xml)
            logger.debug(f"Sent CoT message via TCP/TLS: {cot_xml}")
        except Exception as e:
            logger.error(f"Error sending CoT message via TCP/TLS: {e}")
            self.close()

    def close(self):
        """Closes the connection to the TAK server."""
        if self.sock:
            try:
                self.sock.close()
                logger.debug("Closed TAKClient TCP/TLS socket")
            except Exception as e:
                logger.error(f"Error closing TAKClient TCP/TLS socket: {e}")
            finally:
                self.sock = None
