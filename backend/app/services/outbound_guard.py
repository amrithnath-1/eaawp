"""
Outbound-host guard for customer-supplied DATABASE hosts (Phase K): a tenant administrator must not be able to turn
"test connection" / "query" into a probe of this platform's own network or of cloud metadata services.

ALWAYS blocked: link-local (169.254.0.0/16, fe80::/10 - includes cloud metadata), multicast, unspecified, reserved,
                metadata hostnames, *.internal.
Blocked in PRODUCTION only (so a developer can use a database on their own machine): loopback and private ranges
                (10/8, 172.16/12, 192.168/16, fc00::/7, localhost, *.local). Production can opt out with ALLOW_PRIVATE_DB_HOSTS=true
                (for a company whose database really lives on the same private network as the platform).
Known limit: the name is resolved here and again by the driver, so DNS rebinding is only partly mitigated.
"""
from __future__ import annotations

import ipaddress
import socket

from app.config import settings

_ALWAYS_HOSTS = {"metadata", "metadata.google.internal", "169.254.169.254", "0.0.0.0"}


class HostNotAllowed(ValueError):
    pass


def _private_blocked() -> bool:
    return str(settings.environment).lower() == "production" and not getattr(settings, "allow_private_db_hosts", False)


def validate_db_host(host: str) -> None:
    h = (host or "").strip().lower().strip("[]")
    if not h or len(h) > 255:
        raise HostNotAllowed("Enter a database host name or IP address.")
    if h in _ALWAYS_HOSTS or h.endswith(".internal"):
        raise HostNotAllowed("That host is not allowed (internal or cloud-metadata address).")
    block_private = _private_blocked()
    if block_private and (h == "localhost" or h.endswith(".local") or h.endswith(".localhost")):
        raise HostNotAllowed("Private or local hosts are not allowed in production. Use a publicly reachable database host.")
    try:
        infos = socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return  # unresolvable names fail naturally at connect time and reveal nothing
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise HostNotAllowed("That host resolves to a blocked address (link-local, multicast or reserved).")
        if block_private and (ip.is_loopback or ip.is_private):
            raise HostNotAllowed("That host resolves to a private or loopback address, which is not allowed in production.")
