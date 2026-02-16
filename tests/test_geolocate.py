"""Tests for geolocation enrichment."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from geolocate import is_private_ip, lookup_ip


# ── Private IP detection ─────────────────────────────────────────────


class TestIsPrivateIp:
    def test_rfc1918_class_a(self):
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_rfc1918_class_b(self):
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_rfc1918_class_c(self):
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_loopback(self):
        assert is_private_ip("127.0.0.1") is True

    def test_link_local(self):
        assert is_private_ip("169.254.1.1") is True

    def test_public_ipv4(self):
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("93.184.216.34") is False

    def test_documentation_ips_are_reserved(self):
        # RFC 5737 TEST-NET ranges are reserved, Python treats them as such
        assert is_private_ip("203.0.113.50") is True
        assert is_private_ip("198.51.100.23") is True
        assert is_private_ip("192.0.2.100") is True

    def test_ipv6_loopback(self):
        assert is_private_ip("::1") is True

    def test_ipv6_link_local(self):
        assert is_private_ip("fe80::1") is True

    def test_public_ipv6(self):
        assert is_private_ip("2001:4860:4860::8888") is False

    def test_invalid_ip(self):
        assert is_private_ip("not-an-ip") is False
        assert is_private_ip("evil.example.com") is False


# ── IP Lookup (requires GeoLite2 DB — skipped if not available) ──────


def _has_geodb():
    """Check if GeoLite2 database is available for testing."""
    db_path = os.path.join(os.path.dirname(__file__), "..", "data", "GeoLite2-City.mmdb")
    return os.path.isfile(db_path)


@pytest.mark.skipif(not _has_geodb(), reason="GeoLite2 database not available")
class TestLookupIpWithGeoDB:
    """These tests only run when the GeoLite2 DB is present."""

    @pytest.fixture
    def reader(self):
        import geoip2.database
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "GeoLite2-City.mmdb")
        r = geoip2.database.Reader(db_path)
        yield r
        r.close()

    def test_known_public_ip(self, reader):
        """Google DNS should resolve to US."""
        result = lookup_ip(reader, "8.8.8.8")
        assert result["country_code"] == "US"
        assert result["latitude"] is not None
        assert result["longitude"] is not None

    def test_private_ip_marked_correctly(self, reader):
        result = lookup_ip(reader, "192.168.1.1")
        assert result["country_code"] == "XX"
        assert result["country"] == "Private"

    def test_loopback_marked_private(self, reader):
        result = lookup_ip(reader, "127.0.0.1")
        assert result["country_code"] == "XX"
        assert result["country"] == "Private"


class TestLookupIpPrivateOnly:
    """Tests that work without GeoLite2 DB by only testing private IPs."""

    @pytest.fixture
    def mock_reader(self):
        """A None reader — lookup_ip short-circuits for private IPs before using it."""
        return None

    def test_private_10_network(self, mock_reader):
        result = lookup_ip(mock_reader, "10.0.0.1")
        assert result["ip"] == "10.0.0.1"
        assert result["country_code"] == "XX"
        assert result["country"] == "Private"
        assert result["city"] == "Private Network"

    def test_private_172_network(self, mock_reader):
        result = lookup_ip(mock_reader, "172.16.5.10")
        assert result["country"] == "Private"

    def test_private_192_network(self, mock_reader):
        result = lookup_ip(mock_reader, "192.168.0.1")
        assert result["country"] == "Private"
