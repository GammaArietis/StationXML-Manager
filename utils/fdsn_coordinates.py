"""FDSN StationXML coordinate inheritance helpers."""

from __future__ import annotations

from typing import Optional, Tuple


def channel_position_needs_station_fallback(
    channel_lat: Optional[float],
    channel_lon: Optional[float],
    station_lat: Optional[float],
    station_lon: Optional[float],
) -> bool:
    """True when channel lat/lon are absent or look like import placeholders (0, 0)."""
    if channel_lat is None or channel_lon is None:
        return True
    if channel_lat == 0.0 and channel_lon == 0.0:
        if station_lat is None or station_lon is None:
            return False
        if abs(station_lat) > 1e-9 or abs(station_lon) > 1e-9:
            return True
    return False


def resolve_channel_position(
    channel_lat: Optional[float],
    channel_lon: Optional[float],
    channel_elev: Optional[float],
    station_lat: Optional[float],
    station_lon: Optional[float],
    station_elev: Optional[float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Inherit station lat/lon/elevation when channel values are missing (FDSN default)."""
    lat, lon, elev = channel_lat, channel_lon, channel_elev

    if channel_position_needs_station_fallback(lat, lon, station_lat, station_lon):
        lat, lon = None, None
        if elev is None or (
            elev == 0.0 and station_elev is not None and station_elev != 0.0
        ):
            elev = None

    return (
        lat if lat is not None else station_lat,
        lon if lon is not None else station_lon,
        elev if elev is not None else station_elev,
    )
