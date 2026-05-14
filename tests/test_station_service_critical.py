"""Salvataggio stazione via StationService: persistenza, update e validazione coordinate."""

from __future__ import annotations

import pytest

from core.models.base_models import Network, Station
from core.validators.geo_validators import ValidationError


def test_station_service_insert_persists_and_reload(app_stack):
    sta_svc = app_stack.sta_ctrl.station_service
    net = app_stack.net_ctrl.save_network(
        Network(code="NET_ST", description="test", start_date="2020-01-01T00:00:00")
    )
    assert net and net.id

    sta = Station(
        network_id=net.id,
        code="ABC",
        latitude=46.0,
        longitude=11.0,
        elevation=120.0,
        start_date="2020-01-01T00:00:00",
        site_name="Test Site",
    )
    saved = sta_svc.save_station(sta)
    assert saved is not None and saved.id is not None

    reloaded = sta_svc.get_station_by_id(saved.id)
    assert reloaded is not None
    assert reloaded.code == "ABC"
    assert reloaded.network_id == net.id
    assert reloaded.latitude == pytest.approx(46.0)
    assert reloaded.site_name == "Test Site"


def test_station_service_update_persists_changes(app_stack):
    sta_svc = app_stack.sta_ctrl.station_service
    net = app_stack.net_ctrl.save_network(
        Network(code="NET_UP", description="t", start_date="2020-01-01T00:00:00")
    )
    assert net and net.id

    sta = Station(
        network_id=net.id,
        code="UP1",
        latitude=45.0,
        longitude=10.0,
        elevation=100.0,
        start_date="2020-01-01T00:00:00",
    )
    saved = sta_svc.save_station(sta)
    assert saved and saved.id

    saved.description = "after update"
    saved.elevation = 105.0
    updated = sta_svc.save_station(saved)
    assert updated is not None

    again = sta_svc.get_station_by_id(saved.id)
    assert again is not None
    assert again.description == "after update"
    assert again.elevation == pytest.approx(105.0)


def test_station_service_save_rejects_invalid_latitude(app_stack):
    sta_svc = app_stack.sta_ctrl.station_service
    net = app_stack.net_ctrl.save_network(
        Network(code="NET_BAD", description="t", start_date="2020-01-01T00:00:00")
    )
    assert net and net.id

    bad = Station(
        network_id=net.id,
        code="BAD",
        latitude=99.0,
        longitude=10.0,
        elevation=0.0,
        start_date="2020-01-01T00:00:00",
    )
    with pytest.raises(ValidationError, match="latitude"):
        sta_svc.save_station(bad)


def test_station_service_update_missing_row_returns_none(app_stack):
    sta_svc = app_stack.sta_ctrl.station_service
    ghost = Station(
        id=999_999,
        network_id=1,
        code="GHOST",
        latitude=0.0,
        longitude=0.0,
        elevation=0.0,
        start_date="2020-01-01T00:00:00",
    )
    assert sta_svc.save_station(ghost) is None
