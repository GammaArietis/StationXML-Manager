"""Unit tests for FDSN channel coordinate inheritance."""

from utils.fdsn_coordinates import resolve_channel_position


def test_resolve_channel_position_inherits_missing_values():
    lat, lon, elev = resolve_channel_position(None, None, None, 42.0, 14.0, -100.0)
    assert lat == 42.0
    assert lon == 14.0
    assert elev == -100.0


def test_resolve_channel_position_keeps_explicit_channel_values():
    lat, lon, elev = resolve_channel_position(43.0, 15.0, -90.0, 42.0, 14.0, -100.0)
    assert lat == 43.0
    assert lon == 15.0
    assert elev == -90.0


def test_resolve_channel_position_fixes_zero_zero_placeholder():
    lat, lon, elev = resolve_channel_position(0.0, 0.0, 0.0, 42.2364, 14.9315, -100.0)
    assert lat == 42.2364
    assert lon == 14.9315
    assert elev == -100.0
