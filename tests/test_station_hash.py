"""Station fingerprint uses SHA-256 (stable length, stronger than MD5)."""

from __future__ import annotations

from core.services.station_service import calculate_station_hash
from core.models.base_models import Station


def test_calculate_station_hash_sha256_hex_length():
    s = Station(
        network_id=1,
        code="ROM",
        latitude=41.9,
        longitude=12.5,
        elevation=50.0,
        start_date="2020-01-01T00:00:00",
    )
    h = calculate_station_hash(s)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_calculate_station_hash_changes_with_coordinates():
    base = dict(
        network_id=1,
        code="ROM",
        latitude=41.9,
        longitude=12.5,
        elevation=50.0,
        start_date="2020-01-01T00:00:00",
    )
    a = calculate_station_hash(Station(**base))
    b = calculate_station_hash(Station(**{**base, "latitude": 42.0}))
    assert a != b
