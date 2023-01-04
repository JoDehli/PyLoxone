"""Discovery of miniservers on the local network."""

from __future__ import annotations

import asyncio
import contextlib
import re
import socket
from asyncio.tasks import wait_for


async def discover(timeout: int = 5) -> tuple[str, int, str] | None:
    """
    Attempt to discover a miniserver on the local network.

    Returns a tuple of (IPv4_address:string, port:int, response:string) if a
    miniserver is found on the local network within `timeout` seconds (default 5).
    If no miniserver is found, returns `None`. Response is the response from the
    miniserver, which contains other useful information, such as the serial number,
    firmware version etc.
    """
    # A miniserver will respond on port 7071 to a UDP packet broadcast to port 7070
    # For details, see https://github.com/sarnau/Inside-The-Loxone-Miniserver/blob/
    #   master/LoxoneMiniserverNetworking.md
    #
    # This regex is good enough to find an IPv4 address and port in the response string
    r = re.compile(r"^LoxLIVE:.* ((?:[0-9]{1,3}\.){3}[0-9]{1,3}):(\d+) ")

    loop = asyncio.get_running_loop()
    with socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    ) as read_sock:
        read_sock.setblocking(False)
        read_sock.bind(("0.0.0.0", 7071))
        with socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        ) as write_sock:
            write_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # broadcast 3 packets of 0x00 byte to UDP port 7070 (UDP is unreliable)
            for _ in range(3):
                write_sock.sendto(b"\x00", ("255.255.255.255", 7070))
            with contextlib.suppress(asyncio.TimeoutError):
                response = (
                    await wait_for(loop.sock_recv(read_sock, 1024), timeout)
                ).decode()
                # Look for a Loxone Response.
                if (found := re.match(r, response)) is not None:
                    (ip, port) = found.groups()
                    return (ip, int(port), response)
            return None
