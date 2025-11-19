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
import struct
import logging
import time
import threading
from typing import Optional, List, Tuple
from tak_client import TAKClient
from tak_udp_client import TAKUDPClient

logger = logging.getLogger(__name__)

try:
    import netifaces
except ImportError:
    logger.warning(
        "`netifaces` module not found. Interface name resolution may not be available."
    )
    netifaces = None

# Skip this exact IP (SDR link that should not carry multicast)
SKIP_IFACE_IPS = {"172.31.100.1"}

def _is_docker_iface(name: str) -> bool:
    """Return True for common Docker bridge/veth names; tun/tap are allowed."""
    return name == "docker0" or name.startswith("br-") or name.startswith("veth")


def resolve_interface_to_ip(interface: str) -> Optional[str]:
    """
    Attempts to resolve a given string to an IP address.
    If it's already an IP, returns it.
    If it's an interface name and we can get its IP, return that.
    Otherwise, return None.
    """
    # First, try if the interface string is a valid IP address
    try:
        socket.inet_pton(socket.AF_INET, interface)
        return interface  # It's a valid IP address
    except OSError:
        pass  # Not a valid IP, try resolving as interface name

    if netifaces:
        # Attempt to get the IP of the interface by name
        if interface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(interface)
            # We look for IPv4 addresses under netifaces.AF_INET
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip_addr = addr_info.get("addr")
                    if ip_addr:
                        return ip_addr
        logger.error(f"Interface '{interface}' not found or has no IPv4 address.")
    else:
        logger.error(
            "Cannot resolve interface name to IP without `netifaces`. "
            "Please provide an IP address directly or install netifaces."
        )

    return None


class CotMessenger:
    """Handles sending CoT messages to TAK servers and multicast addresses."""
    def __init__(
        self,
        tak_client: Optional[TAKClient] = None,
        tak_udp_client: Optional[TAKUDPClient] = None,
        multicast_address: Optional[str] = None,
        multicast_port: Optional[int] = None,
        enable_multicast: bool = False,
        multicast_interface: Optional[str] = None,
        multicast_ttl: int = 1,
        enable_receive: bool = False
    ):
        """
        Initializes the CotMessenger.

        :param tak_client: Instance of TAKClient for TCP/TLS communication.
        :param tak_udp_client: Instance of TAKUDPClient for UDP communication.
        :param multicast_address: Multicast address to send CoT messages.
        :param multicast_port: Multicast port to send CoT messages.
        :param enable_multicast: Flag to enable multicast sending.
        :param multicast_interface: The network interface (IP or name) to use for sending multicast traffic. If "0.0.0.0", send on all available interfaces.
        :param multicast_ttl: TTL for multicast packets.
        :param enable_receive: Flag to enable receiving multicast CoT messages.
        """
        self.tak_client = tak_client
        self.tak_udp_client = tak_udp_client
        self.multicast_address = multicast_address
        self.multicast_port = multicast_port
        self.enable_multicast = enable_multicast
        self.multicast_interface = multicast_interface
        self.multicast_ttl = multicast_ttl
        self.multicast_sockets: List[Tuple[socket.socket, str]] = []  # List of (socket, interface_ip) tuples
        self.enable_receive = enable_receive
        self.receive_socket: Optional[socket.socket] = None
        self.receive_thread: Optional[threading.Thread] = None
        self.running = False

        # NEW: track when we last scanned interfaces for multicast sockets
        self._last_iface_scan: float = 0.0  # NEW

        if self.enable_multicast and self.multicast_address and self.multicast_port:
            try:
                ttl_packed = struct.pack("b", self.multicast_ttl)

                if self.multicast_interface == "0.0.0.0":
                    if netifaces:
                        for iface in netifaces.interfaces():
                            # Skip docker-style interfaces by name (docker0/br-*/veth*)
                            if _is_docker_iface(iface):
                                logger.debug(f"Skipping multicast TX on docker-like iface '{iface}'")
                                continue

                            addrs = netifaces.ifaddresses(iface)
                            if netifaces.AF_INET in addrs:
                                for addr_info in addrs[netifaces.AF_INET]:
                                    ip_addr = addr_info.get("addr")
                                    # Keep original behavior; skip link-local only
                                    if ip_addr and not ip_addr.startswith("169.254"):
                                        # Skip specific SDR IP(s) if present
                                        if ip_addr in SKIP_IFACE_IPS:
                                            logger.debug(f"Skipping multicast TX on iface '{iface}' ip '{ip_addr}' (in SKIP_IFACE_IPS)")
                                            continue

                                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl_packed)
                                        packed_if = socket.inet_aton(ip_addr)
                                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed_if)
                                        if ip_addr == "127.0.0.1":
                                            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
                                            logger.debug("Enabled IP_MULTICAST_LOOP on loopback")
                                        self.multicast_sockets.append((sock, ip_addr))
                                        logger.debug(f"Initialized multicast socket for interface {iface} with IP {ip_addr}")
                        if not self.multicast_sockets:
                            logger.error("No valid IPv4 interfaces found for multicast sending.")
                    else:
                        logger.error("netifaces module is required to enumerate interfaces when multicast_interface is 0.0.0.0.")
                else:
                    interface_ip = resolve_interface_to_ip(self.multicast_interface) if self.multicast_interface else None
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl_packed)
                    if interface_ip:
                        packed_if = socket.inet_aton(interface_ip)
                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed_if)
                        if interface_ip == "127.0.0.1":
                            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
                            logger.debug("Enabled IP_MULTICAST_LOOP on loopback")
                        logger.debug(f"Set multicast interface to {interface_ip}")
                    self.multicast_sockets.append((sock, interface_ip or "default"))
                    logger.debug(
                        f"Initialized multicast socket for {self.multicast_address}:{self.multicast_port} using interface '{self.multicast_interface}'"
                    )

                logger.debug(
                    f"Initialized {len(self.multicast_sockets)} multicast socket(s) for "
                    f"{self.multicast_address}:{self.multicast_port} with TTL {self.multicast_ttl}"
                )
                # NEW: record that we’ve just done a scan
                self._last_iface_scan = time.time()  # NEW
            except Exception as e:
                logger.error(f"Failed to initialize multicast socket(s): {e}")
        else:
            if self.enable_multicast:
                logger.error(
                    "Multicast address or port not provided. Multicast will not be enabled."
                )
            else:
                logger.debug(
                    "Multicast is not enabled. Skipping multicast socket initialization."
                )

        # Initialize receiver if enabled
        if self.enable_receive and self.multicast_address and self.multicast_port:
            self._setup_receiver()

    # NEW: helper to periodically refresh multicast sockets when using 0.0.0.0
    def _refresh_multicast_sockets_if_needed(self, refresh_interval: float = 30.0) -> None:
        """
        Refresh multicast sockets if they have not been initialized or if enough
        time has passed since the last interface scan (for 0.0.0.0 mode).
        """
        if not self.enable_multicast:
            return

        now = time.time()
        if (
            not self.multicast_sockets
            or (
                self.multicast_interface == "0.0.0.0"
                and self._last_iface_scan
                and (now - self._last_iface_scan) > refresh_interval
            )
        ):
            # Close any existing sockets before rebuilding
            for sock, iface_ip in self.multicast_sockets:
                try:
                    sock.close()
                    logger.debug(f"Closed stale multicast socket for interface {iface_ip} during refresh.")
                except Exception as e:
                    logger.error(f"Error closing multicast socket during refresh for {iface_ip}: {e}")

            self.multicast_sockets = []

            if not (self.multicast_address and self.multicast_port):
                logger.error("Cannot refresh multicast sockets without multicast address and port.")
                return

            try:
                ttl_packed = struct.pack("b", self.multicast_ttl)

                if self.multicast_interface == "0.0.0.0":
                    if netifaces:
                        for iface in netifaces.interfaces():
                            # Skip docker-style interfaces by name (docker0/br-*/veth*)
                            if _is_docker_iface(iface):
                                logger.debug(f"Skipping multicast TX on docker-like iface '{iface}' (refresh)")
                                continue

                            addrs = netifaces.ifaddresses(iface)
                            if netifaces.AF_INET in addrs:
                                for addr_info in addrs[netifaces.AF_INET]:
                                    ip_addr = addr_info.get("addr")
                                    # Keep original behavior; skip link-local only
                                    if ip_addr and not ip_addr.startswith("169.254"):
                                        # Skip specific SDR IP(s) if present
                                        if ip_addr in SKIP_IFACE_IPS:
                                            logger.debug(f"Skipping multicast TX on iface '{iface}' ip '{ip_addr}' (in SKIP_IFACE_IPS, refresh)")
                                            continue

                                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl_packed)
                                        packed_if = socket.inet_aton(ip_addr)
                                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed_if)
                                        if ip_addr == "127.0.0.1":
                                            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
                                            logger.debug("Enabled IP_MULTICAST_LOOP on loopback (refresh)")
                                        self.multicast_sockets.append((sock, ip_addr))
                                        logger.debug(f"Refreshed multicast socket for interface {iface} with IP {ip_addr}")
                        if not self.multicast_sockets:
                            logger.error("No valid IPv4 interfaces found for multicast sending during refresh.")
                    else:
                        logger.error("netifaces module is required to enumerate interfaces when multicast_interface is 0.0.0.0.")
                else:
                    interface_ip = resolve_interface_to_ip(self.multicast_interface) if self.multicast_interface else None
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl_packed)
                    if interface_ip:
                        packed_if = socket.inet_aton(interface_ip)
                        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed_if)
                        if interface_ip == "127.0.0.1":
                            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
                            logger.debug("Enabled IP_MULTICAST_LOOP on loopback (refresh)")
                        logger.debug(f"Set multicast interface to {interface_ip} (refresh)")
                    self.multicast_sockets.append((sock, interface_ip or "default"))
                    logger.debug(
                        f"Refreshed multicast socket(s) for {self.multicast_address}:{self.multicast_port} using interface '{self.multicast_interface}'"
                    )

                self._last_iface_scan = now
                logger.debug(
                    f"Refreshed {len(self.multicast_sockets)} multicast socket(s) for "
                    f"{self.multicast_address}:{self.multicast_port} with TTL {self.multicast_ttl}"
                )
            except Exception as e:
                logger.error(f"Failed to refresh multicast socket(s): {e}")

    def _setup_receiver(self):
        """Sets up the multicast receiver socket."""
        try:
            self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.receive_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.receive_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # Some systems don't support SO_REUSEPORT

            # Bind to the multicast port on all interfaces
            self.receive_socket.bind(('', self.multicast_port))

            # Join the multicast group
            group = socket.inet_aton(self.multicast_address)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            self.receive_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Disable loopback to avoid receiving own messages
            self.receive_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)

            logger.debug(f"Initialized multicast receiver on {self.multicast_address}:{self.multicast_port}")
        except Exception as e:
            logger.error(f"Failed to initialize multicast receiver: {e}")
            self.receive_socket = None

    def start_receiver(self):
        """Starts the receiver thread if enabled and socket is set up."""
        if self.enable_receive and self.receive_socket:
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            logger.debug("Started multicast receiver thread")

    def _receive_loop(self):
        """Loop to receive and process incoming CoT messages."""
        while self.running:
            try:
                data, addr = self.receive_socket.recvfrom(4096)  # Buffer size for CoT XML
                if data:
                    # For now, just log the received CoT (future: parse/process)
                    logger.info(f"Received CoT message from {addr}: {data.decode('utf-8', errors='ignore')}")
                    # Future expansion: Parse with lxml, update state, etc.
            except Exception as e:
                logger.error(f"Error receiving CoT message: {e}")

    def send_cot(
        self, cot_xml: bytes, retry_count: int = 3, retry_delay: float = 1.0
    ):
        """
        Sends a CoT message to TAK servers and multicast addresses with retry logic.

        :param cot_xml: The CoT XML message in bytes.
        :param retry_count: Number of retry attempts for sending.
        :param retry_delay: Delay between retries in seconds.
        """
        logger.debug("send_cot method called.")
        logger.debug(
            f"Multicast Enabled: {self.enable_multicast}, Multicast Sockets: {len(self.multicast_sockets)} initialized"
        )

        # Sending to TAK server via TCP/TLS
        if self.tak_client:
            for attempt in range(1, retry_count + 1):
                try:
                    self.tak_client.send(cot_xml)
                    logger.info(
                        f"Sent CoT message to TAK server via TCP/TLS at {self.tak_client.host}:{self.tak_client.port}"
                    )
                    break
                except Exception as e:
                    logger.error(
                        f"Attempt {attempt}: Failed to send CoT message via TCP/TLS: {e}"
                    )
                    if attempt < retry_count:
                        time.sleep(retry_delay)
                    else:
                        logger.critical(
                            "Exceeded maximum retries for sending CoT message via TCP/TLS."
                        )
        elif self.tak_udp_client:
            for attempt in range(1, retry_count + 1):
                try:
                    self.tak_udp_client.send(cot_xml)
                    logger.info(
                        f"Sent CoT message to TAK server via UDP at {self.tak_udp_client.host}:{self.tak_udp_client.port}"
                    )
                    break
                except Exception as e:
                    logger.error(
                        f"Attempt {attempt}: Failed to send CoT message via UDP: {e}"
                    )
                    if attempt < retry_count:
                        time.sleep(retry_delay)
                    else:
                        logger.critical(
                            "Exceeded maximum retries for sending CoT message via UDP."
                        )
        else:
            logger.debug(
                "No TAK client configured. Skipping sending CoT message to TAK server."
            )

        # NEW: ensure multicast sockets are up-to-date before sending
        self._refresh_multicast_sockets_if_needed()  # NEW

        # Sending to multicast address(es)
        if self.enable_multicast and self.multicast_sockets:
            logger.debug(
                f"Attempting to send CoT message via multicast to {self.multicast_address}:{self.multicast_port} on {len(self.multicast_sockets)} interface(s)"
            )
            for sock, iface_ip in self.multicast_sockets:
                for attempt in range(1, retry_count + 1):
                    try:
                        sock.sendto(
                            cot_xml, (self.multicast_address, self.multicast_port)
                        )
                        logger.info(
                            f"Sent CoT message to multicast address {self.multicast_address}:{self.multicast_port} using interface IP '{iface_ip}'."
                        )
                        break
                    except Exception as e:
                        logger.error(
                            f"Attempt {attempt}: Failed to send CoT message via multicast on interface {iface_ip}: {e}"
                        )
                        if attempt < retry_count:
                            time.sleep(retry_delay)
                        else:
                            logger.critical(
                                f"Exceeded maximum retries for sending CoT message via multicast on interface {iface_ip}."
                            )
        else:
            logger.debug(
                "Multicast is not enabled or no multicast sockets initialized. Skipping sending CoT message to multicast."
            )

    def close(self):
        """Closes persistent multicast sockets and TAK clients if initialized."""
        if self.enable_receive:
            self.running = False
            if self.receive_thread and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=5)
                logger.debug("Stopped receive thread")
            if self.receive_socket:
                try:
                    self.receive_socket.close()
                    logger.debug("Closed receive socket")
                except Exception as e:
                    logger.error(f"Error closing receive socket: {e}")

        for sock, iface_ip in self.multicast_sockets:
            try:
                sock.close()
                logger.debug(f"Closed multicast socket for interface {iface_ip}.")
            except Exception as e:
                logger.error(f"Error closing multicast socket for {iface_ip}: {e}")

        self.multicast_sockets = []

        # Close TAK clients if they exist
        if self.tak_client:
            try:
                self.tak_client.close()
                logger.debug("Closed TAK TCP/TLS client.")
            except Exception as e:
                logger.error(f"Error closing TAK TCP/TLS client: {e}")

        if self.tak_udp_client:
            try:
                self.tak_udp_client.close()
                logger.debug("Closed TAK UDP client.")
            except Exception as e:
                logger.error(f"Error closing TAK UDP client: {e}")
