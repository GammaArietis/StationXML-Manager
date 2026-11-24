"""A station that changes network is one StationXML, not one file per network."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("obspy")

from obspy import UTCDateTime, read_inventory
from obspy.core.inventory import Channel, Inventory, Network, Site, Station

from controllers.stationxml_export_controller import StationXMLWebExportController
from exporter.stationxml_builder import StationXMLExporter


def _channel(code: str, start: str, end: str | None) -> Channel:
    return Channel(
        code=code,
        location_code="",
        latitude=37.578,
        longitude=13.216,
        elevation=949.0,
        depth=0.0,
        azimuth=0.0,
        dip=-90.0,
        sample_rate=20.0,
        start_date=UTCDateTime(start),
        end_date=UTCDateTime(end) if end else None,
    )


def _station(code, lat, lon, start, end, channel) -> Station:
    sta = Station(
        code=code,
        latitude=lat,
        longitude=lon,
        elevation=949.0,
        start_date=UTCDateTime(start),
        end_date=UTCDateTime(end) if end else None,
        channels=[channel],
    )
    sta.site = Site(name="Caltabellotta")
    return sta


def _network(code: str, station: Station) -> Network:
    return Network(
        code=code,
        description=code,
        start_date=UTCDateTime("1988-01-01T00:00:00"),
        stations=[station],
    )


def _exporter(app_stack) -> StationXMLExporter:
    return StationXMLExporter(
        app_stack.net_ctrl,
        app_stack.sta_ctrl,
        app_stack.cha_ctrl,
        app_stack.eq_ctrl,
    )


def _import_cltb_history(app_stack, tmp_path: Path):
    mn = _network(
        "MN",
        _station(
            "CLTB",
            37.578,
            13.216,
            "2000-09-07T00:00:00",
            "2023-06-29T10:10:00",
            _channel("BHZ", "2000-09-07T00:00:00", "2023-06-29T10:10:00"),
        ),
    )
    iv = _network(
        "IV",
        _station(
            "CLTB",
            37.578,
            13.216,
            "2023-06-29T10:10:00",
            None,
            _channel("HHZ", "2023-06-29T10:10:00", None),
        ),
    )
    other = _network(
        "ZZ",
        _station(
            "CLTB",
            10.0,
            10.0,
            "2015-01-01T00:00:00",
            None,
            _channel("LHZ", "2015-01-01T00:00:00", None),
        ),
    )
    path = tmp_path / "cltb_history.xml"
    Inventory(networks=[iv, mn, other], source="TEST").write(str(path), format="STATIONXML")
    assert app_stack.parser.import_file(str(path)) is True
    return path


def _stations_by_network(app_stack):
    found = {}
    for net in app_stack.net_ctrl.get_all_networks():
        for sta in app_stack.sta_ctrl.get_stations_by_network(net.id):
            found[net.code] = sta
    return found


def test_export_joins_network_epochs_of_the_same_site(app_stack, tmp_path: Path):
    _import_cltb_history(app_stack, tmp_path)
    rows = _stations_by_network(app_stack)
    exporter = _exporter(app_stack)

    inv = exporter.build_station_inventory(rows["IV"].id, validate=False)
    assert [net.code for net in inv.networks] == ["MN", "IV"]
    assert inv.networks[0].stations[0].channels[0].code == "BHZ"
    assert inv.networks[1].stations[0].channels[0].code == "HHZ"
    assert inv.networks[0].stations[0].end_date == UTCDateTime("2023-06-29T10:10:00")
    assert inv.networks[1].stations[0].end_date is None

    far = exporter.build_station_inventory(rows["ZZ"].id, validate=False)
    assert [net.code for net in far.networks] == ["ZZ"]
    assert far.networks[0].stations[0].channels[0].code == "LHZ"


def test_download_of_both_rows_is_one_stationxml(app_stack, tmp_path: Path):
    _import_cltb_history(app_stack, tmp_path)
    rows = _stations_by_network(app_stack)
    ctrl = StationXMLWebExportController(
        app_stack.net_ctrl,
        app_stack.sta_ctrl,
        app_stack.cha_ctrl,
        app_stack.eq_ctrl,
    )

    payload, filename = ctrl.build_download(
        [{"id": rows["IV"].id}, {"id": rows["MN"].id}]
    )
    assert filename == "CLTB.xml"
    loaded = read_inventory(io.BytesIO(payload))
    assert [net.code for net in loaded.networks] == ["MN", "IV"]


def test_zip_keeps_distinct_sites_apart(app_stack, tmp_path: Path):
    _import_cltb_history(app_stack, tmp_path)
    rows = _stations_by_network(app_stack)
    exporter = _exporter(app_stack)

    blob = exporter.build_zip_bytes_for_station_ids(
        [rows["MN"].id, rows["IV"].id, rows["ZZ"].id]
    )
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        combined = read_inventory(io.BytesIO(archive.read("CLTB.xml")))
        other = read_inventory(io.BytesIO(archive.read("CLTB_1.xml")))

    assert names == ["CLTB.xml", "CLTB_1.xml"]
    assert [net.code for net in combined.networks] == ["MN", "IV"]
    assert [net.code for net in other.networks] == ["ZZ"]
