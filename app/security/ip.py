"""Trusted client-IP resolution and canonical network parsing.

The direct socket peer is authoritative unless it belongs to a configured trusted
proxy network. In that case only X-Forwarded-For is considered, and trusted hops are
peeled from right to left. X-Real-IP is deliberately never authoritative.
"""

from collections.abc import Iterable, Mapping, Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

type IpAddress = IPv4Address | IPv6Address
type IpNetwork = IPv4Network | IPv6Network


def normalize_ip(value: str | IPv4Address | IPv6Address) -> IpAddress:
    """Parse an IP and collapse IPv4-mapped IPv6 to its canonical IPv4 address."""
    address = ip_address(value)
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def normalize_network(value: str | IpNetwork) -> IpNetwork:
    """Parse a host or network with host bits normalized to the network boundary."""
    network = ip_network(value, strict=False)
    if isinstance(network, IPv6Network) and network.network_address.ipv4_mapped is not None:
        mapped = network.network_address.ipv4_mapped
        prefix = max(0, network.prefixlen - 96)
        return ip_network(f"{mapped}/{prefix}", strict=False)
    return network


def address_in_networks(address: IpAddress, networks: Iterable[IpNetwork]) -> bool:
    """Return whether an address belongs to at least one same-family network."""
    return any(address.version == network.version and address in network for network in networks)


class TrustedClientIpResolver:
    """Resolve a caller IP without granting authority to untrusted forwarding headers."""

    def __init__(self, trusted_proxy_cidrs: Sequence[IpNetwork]) -> None:
        self._trusted_proxies = tuple(normalize_network(network) for network in trusted_proxy_cidrs)

    def resolve(
        self,
        peer_host: str | None,
        headers: Mapping[str, str] | None = None,
        forwarded_values: Sequence[str] | None = None,
    ) -> IpAddress | None:
        """Use a valid peer, optionally peeling a fully parseable trusted proxy chain."""
        if peer_host is None:
            return None
        try:
            peer = normalize_ip(peer_host)
        except ValueError:
            return None
        if not address_in_networks(peer, self._trusted_proxies):
            return peer

        values = list(forwarded_values or ())
        if not values and headers is not None:
            forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
            if forwarded is not None:
                values.append(forwarded)
        if not values:
            return peer

        parts = [part.strip() for value in values for part in value.split(",")]
        if not parts or any(not part for part in parts):
            return peer
        try:
            chain = [normalize_ip(part) for part in parts]
        except ValueError:
            return peer

        current = peer
        for candidate in reversed(chain):
            if not address_in_networks(current, self._trusted_proxies):
                break
            current = candidate
        return current
