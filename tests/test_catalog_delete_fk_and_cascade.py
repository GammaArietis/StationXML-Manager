"""
Integrità in cancellazione: il catalogo non va rimosso se ancora referenziato;
CASCADE rete → stazioni (schema SQLite).
"""

from __future__ import annotations

import pytest

from core.models.base_models import Channel, Datalogger, Network, Sensor, Station
from core.services.equipment_service import EquipmentInUseError


def test_delete_sensor_blocked_when_channel_fk_reference(app_stack):
    """Il service impedisce la DELETE se esiste un canale con sensor_id (coerenza inventario)."""
    svc = app_stack.equipment_service
    cha_dao = app_stack.cha_ctrl.dao

    sensor = svc.save_sensor(
        Sensor(
            manufacturer="FK_MFG",
            model="FK_SENSOR_MODEL_UNIQUE",
            sensitivity=1000.0,
            frequency=1.0,
        )
    )
    assert sensor and sensor.id

    net = app_stack.net_ctrl.save_network(
        Network(code="FK_NET_S", description="x", start_date="2020-01-01T00:00:00")
    )
    sta = app_stack.sta_ctrl.station_service.save_station(
        Station(
            network_id=net.id,
            code="S_FK",
            latitude=44.0,
            longitude=9.0,
            elevation=80.0,
            start_date="2020-01-01T00:00:00",
        )
    )
    assert sta and sta.id

    ch = Channel(
        station_id=sta.id,
        code="HHZ",
        location_code="",
        latitude=44.0,
        longitude=9.0,
        elevation=80.0,
        depth=0.0,
        azimuth=0.0,
        dip=0.0,
        sample_rate=100.0,
        start_date="2020-01-01T00:00:00",
        sensor_id=sensor.id,
    )
    assert cha_dao.insert(ch) and ch.id

    with pytest.raises(EquipmentInUseError):
        svc.delete_sensor(sensor.id)


def test_delete_datalogger_blocked_when_channel_fk_reference(app_stack):
    """Stesso vincolo applicativo per datalogger_id su channel."""
    svc = app_stack.equipment_service
    cha_dao = app_stack.cha_ctrl.dao

    dl = svc.save_datalogger(
        Datalogger(
            manufacturer="FK_DL_MFG",
            model="FK_DL_MODEL_UNIQUE",
            gain=32.0,
        )
    )
    assert dl and dl.id

    net = app_stack.net_ctrl.save_network(
        Network(code="FK_NET_D", description="x", start_date="2020-01-01T00:00:00")
    )
    sta = app_stack.sta_ctrl.station_service.save_station(
        Station(
            network_id=net.id,
            code="S_FKD",
            latitude=43.0,
            longitude=8.0,
            elevation=70.0,
            start_date="2020-01-01T00:00:00",
        )
    )
    assert sta and sta.id

    ch = Channel(
        station_id=sta.id,
        code="BHZ",
        location_code="",
        latitude=43.0,
        longitude=8.0,
        elevation=70.0,
        depth=0.0,
        azimuth=0.0,
        dip=0.0,
        sample_rate=20.0,
        start_date="2020-01-01T00:00:00",
        datalogger_id=dl.id,
    )
    assert cha_dao.insert(ch) and ch.id

    with pytest.raises(EquipmentInUseError):
        svc.delete_datalogger(dl.id)


def test_delete_network_cascades_stations(app_stack):
    """FK station.network_id → network ON DELETE CASCADE: eliminando la rete spariscono le stazioni."""
    sta_svc = app_stack.sta_ctrl.station_service
    net = app_stack.net_ctrl.save_network(
        Network(code="CASCADE_NET", description="cascade", start_date="2020-01-01T00:00:00")
    )
    assert net and net.id

    sta = sta_svc.save_station(
        Station(
            network_id=net.id,
            code="CHILD",
            latitude=42.0,
            longitude=12.0,
            elevation=50.0,
            start_date="2020-01-01T00:00:00",
        )
    )
    assert sta and sta.id
    assert len(sta_svc.get_stations_by_network(net.id)) == 1

    assert app_stack.net_ctrl.delete_network(net.id) is True

    assert sta_svc.get_station_by_id(sta.id) is None
    assert sta_svc.get_stations_by_network(net.id) == []
