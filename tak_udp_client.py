"""
MIT License

Copyright (c) 2024 cemaxecuter

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

[License Text]
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
