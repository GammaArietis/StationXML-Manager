"""StationXML import via ObsPy + StationXMLParser."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("obspy")

from obspy import UTCDateTime
from obspy.core.inventory import Channel, Inventory, Network, Site, Station


def _write_minimal_stationxml(path: Path) -> None:
    ch = Channel(
        code="HHZ",
        location_code="00",
        latitude=45.0,
        longitude=9.0,
        elevation=100.0,
        depth=0.0,
        azimuth=0.0,
        dip=-90.0,
        sample_rate=100.0,
        start_date=UTCDateTime("2020-01-01T00:00:00"),
    )
    sta = Station(
        code="TST1",
        latitude=45.0,
        longitude=9.0,
        elevation=100.0,
        start_date=UTCDateTime("2020-01-01T00:00:00"),
        channels=[ch],
    )
    sta.site = Site(name="Pytest Site")
    net = Network(
        code="XX",
        description="Pytest network",
        start_date=UTCDateTime("2020-01-01T00:00:00"),
        stations=[sta],
    )
    inv = Inventory(networks=[net], sender="PYTEST")
    inv.write(str(path), format="STATIONXML")


def test_stationxml_parser_imports_network_station_channel(app_stack, tmp_path: Path):
    xml_path = tmp_path / "minimal.xml"
    _write_minimal_stationxml(xml_path)

    ok = app_stack.parser.import_file(str(xml_path))
    assert ok is True

    nets = app_stack.net_ctrl.get_all_networks()
    assert len(nets) == 1
    assert nets[0].code == "XX"

    stas = app_stack.sta_ctrl.get_stations_by_network(nets[0].id)
    assert len(stas) == 1
    assert stas[0].code == "TST1"
    assert abs(stas[0].latitude - 45.0) < 1e-6

    chans = app_stack.cha_ctrl.get_channels_by_station(stas[0].id)
    assert len(chans) == 1
    assert chans[0].code == "HHZ"
    assert chans[0].sample_rate == 100.0
    assert abs(chans[0].latitude - 45.0) < 1e-6
    assert abs(chans[0].longitude - 9.0) < 1e-6


def _write_obs_with_placeholder_channel_coords(path: Path) -> None:
    """ObsPy skips channels missing lat/lon/elev/depth; use 0,0 placeholders."""
    ch = Channel(
        code="HHZ",
        location_code="00",
        latitude=0.0,
        longitude=0.0,
        elevation=0.0,
        depth=0.0,
        azimuth=0.0,
        dip=-90.0,
        sample_rate=100.0,
        start_date=UTCDateTime("2020-01-01T00:00:00"),
    )
    sta = Station(
        code="OBS1",
        latitude=42.2364,
        longitude=14.9315,
        elevation=-100.0,
        start_date=UTCDateTime("2020-01-01T00:00:00"),
        channels=[ch],
    )
    sta.site = Site(name="OBS1")
    sta.water_level = 100.0
    net = Network(
        code="YY",
        description="Pytest OBS network",
        start_date=UTCDateTime("2020-01-01T00:00:00"),
        stations=[sta],
    )
    inv = Inventory(networks=[net], sender="PYTEST")
    inv.write(str(path), format="STATIONXML")


def test_stationxml_parser_inherits_station_coordinates_on_channel(app_stack, tmp_path: Path):
    xml_path = tmp_path / "placeholder_channel_coords.xml"
    _write_obs_with_placeholder_channel_coords(xml_path)

    ok = app_stack.parser.import_file(str(xml_path))
    assert ok is True

    yy_net = next(net for net in app_stack.net_ctrl.get_all_networks() if net.code == "YY")
    stas = app_stack.sta_ctrl.get_stations_by_network(yy_net.id)
    assert len(stas) == 1
    assert stas[0].code == "OBS1"

    chans = app_stack.cha_ctrl.get_channels_by_station(stas[0].id)
    assert len(chans) == 1
    assert abs(chans[0].latitude - 42.2364) < 1e-6
    assert abs(chans[0].longitude - 14.9315) < 1e-6
    assert abs(chans[0].elevation - (-100.0)) < 1e-6
