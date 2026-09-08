"""Trusted client-IP resolution and CIDR normalization tests."""

from ipaddress import ip_address, ip_network

import pytest

from app.core.config import Settings
from app.security.ip import (
    TrustedClientIpResolver,
    address_in_networks,
    normalize_ip,
    normalize_network,
)


@pytest.mark.parametrize(
    ("peer", "expected"),
    [("203.0.113.9", "203.0.113.9"), ("2001:db8::9", "2001:db8::9")],
)
def test_direct_ipv4_and_ipv6_peers(peer: str, expected: str) -> None:
    assert str(TrustedClientIpResolver([]).resolve(peer)) == expected


@pytest.mark.parametrize(
    ("network", "match", "miss"),
    [
        ("203.0.113.9/32", "203.0.113.9", "203.0.113.10"),
        ("2001:db8::9/128", "2001:db8::9", "2001:db8::10"),
        ("10.0.0.0/8", "10.2.3.4", "11.2.3.4"),
        ("2001:db8::/32", "2001:db8:1::1", "2001:db9::1"),
    ],
)
def test_individual_and_network_cidr_match_and_miss(network: str, match: str, miss: str) -> None:
    parsed = normalize_network(network)
    assert address_in_networks(normalize_ip(match), [parsed])
    assert not address_in_networks(normalize_ip(miss), [parsed])


def test_untrusted_peer_cannot_spoof_forwarded_headers() -> None:
    resolver = TrustedClientIpResolver([ip_network("10.0.0.0/8")])

    assert resolver.resolve("203.0.113.5", {"x-forwarded-for": "192.0.2.99"}) == ip_address(
        "203.0.113.5"
    )


def test_trusted_proxy_chain_is_peeled_from_right_and_ignores_spoofed_leftmost() -> None:
    resolver = TrustedClientIpResolver([ip_network("10.0.0.0/8"), ip_network("192.0.2.0/24")])

    assert resolver.resolve(
        "10.0.0.4", forwarded_values=["198.51.100.99, 203.0.113.8, 192.0.2.3"]
    ) == ip_address("203.0.113.8")


def test_multiple_forwarded_header_values_and_whitespace_are_supported() -> None:
    resolver = TrustedClientIpResolver([ip_network("10.0.0.0/8")])

    assert resolver.resolve(
        "10.0.0.4", forwarded_values=[" 198.51.100.9 ", " 10.0.0.3 "]
    ) == ip_address("198.51.100.9")


@pytest.mark.parametrize("forwarded", ["bad-ip", "198.51.100.8,", ",198.51.100.8"])
def test_malformed_forwarded_chain_from_trusted_proxy_is_unresolved(forwarded: str) -> None:
    resolver = TrustedClientIpResolver([ip_network("10.0.0.0/8")])

    assert resolver.resolve("10.0.0.4", forwarded_values=[forwarded]) is None


def test_x_real_ip_is_never_authoritative() -> None:
    resolver = TrustedClientIpResolver([ip_network("10.0.0.0/8")])

    assert resolver.resolve("10.0.0.4", {"x-real-ip": "198.51.100.9"}) is None


def test_trusted_proxy_without_forwarded_chain_is_unresolved() -> None:
    resolver = TrustedClientIpResolver([ip_network("10.0.0.0/8")])

    assert resolver.resolve("10.0.0.4") is None


def test_ipv4_mapped_ipv6_is_normalized() -> None:
    assert normalize_ip("::ffff:192.0.2.8") == ip_address("192.0.2.8")
    assert normalize_network("::ffff:192.0.2.8/128") == ip_network("192.0.2.8/32")


@pytest.mark.parametrize("peer", [None, "not-an-ip"])
def test_absent_or_invalid_peer_is_unresolved(peer: str | None) -> None:
    assert TrustedClientIpResolver([]).resolve(peer) is None


def test_invalid_trusted_proxy_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="valid IPv4 or IPv6 CIDRs"):
        Settings(_env_file=None, trusted_proxy_cidrs=["invalid"])


def test_configured_networks_are_normalized() -> None:
    settings = Settings(
        _env_file=None,
        trusted_proxy_cidrs=["10.2.3.4/8"],
        ip_emergency_bypass_cidrs=["2001:db8::9/64"],
    )

    assert settings.trusted_proxy_cidrs == [ip_network("10.0.0.0/8")]
    assert settings.ip_emergency_bypass_cidrs == [ip_network("2001:db8::/64")]


def test_non_local_security_failure_policies_must_fail_closed() -> None:
    with pytest.raises(ValueError, match="must fail closed"):
        Settings(
            _env_file=None,
            environment="production",
            allowed_hosts=["api.example.com"],
            cors_allowed_origins=["https://example.com"],
            ip_allowlist_fail_closed=False,
        )
