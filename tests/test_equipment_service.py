"""EquipmentService integrity (e.g. delete blocked when channels reference catalog)."""

from __future__ import annotations

import pytest

from core.models.base_models import Channel, Network, Sensor, Station
from core.services.equipment_service import EquipmentInUseError


def test_delete_sensor_blocked_when_channel_references_it(app_stack):
    svc = app_stack.equipment_service
    cha_dao = app_stack.cha_ctrl.dao

    saved = svc.save_sensor(
        Sensor(
            manufacturer="TESTMFG",
            model="TESTMODEL_UNIQUE_PY",
            sensitivity=1200.0,
            frequency=1.0,
        )
    )
    assert saved is not None and saved.id is not None

    net = app_stack.net_ctrl.save_network(
        Network(code="YY", description="t", start_date="2020-01-01T00:00:00")
    )
    assert net and net.id

    sta = app_stack.sta_ctrl.save_station(
        Station(
            network_id=net.id,
            code="S1",
            latitude=46.0,
            longitude=10.0,
            elevation=50.0,
            start_date="2020-01-01T00:00:00",
        )
    )
    assert sta and sta.id

    ch = Channel(
        station_id=sta.id,
        code="BHZ",
        location_code="",
        latitude=46.0,
        longitude=10.0,
        elevation=50.0,
        depth=0.0,
        azimuth=0.0,
        dip=0.0,
        sample_rate=20.0,
        start_date="2020-01-01T00:00:00",
        sensor_id=saved.id,
    )
    inserted = cha_dao.insert(ch)
    assert inserted and inserted.id

    with pytest.raises(EquipmentInUseError):
        svc.delete_sensor(saved.id)


def test_delete_sensor_succeeds_when_unused(app_stack):
    svc = app_stack.equipment_service
    saved = svc.save_sensor(
        Sensor(
            manufacturer="TESTMFG2",
            model="TESTMODEL_ORPHAN_PY",
            sensitivity=800.0,
            frequency=1.0,
        )
    )
    assert saved and saved.id
    assert svc.delete_sensor(saved.id) is True
