"""Bulk NRL catalog refresh: merged NRL payload must persist, not the stale in-memory row."""

from __future__ import annotations

import json

import pytest

from core.models.base_models import Datalogger, PoleZero, ResponseFilter, Sensor


class _FakeNRLManager:
    """Stub NRL client returning predetermined Sensor / Datalogger models."""

    def __init__(self, sensor: Sensor | None = None, datalogger: Datalogger | None = None) -> None:
        self._sensor = sensor
        self._datalogger = datalogger

    def fetch_sensor(self, keys: list[str]) -> Sensor | None:
        return self._sensor

    def fetch_datalogger(self, keys: list[str]) -> Datalogger | None:
        return self._datalogger


def test_apply_nrl_to_catalog_sensor_merges_fresh_payload_before_save(app_stack):
    eq = app_stack.eq_ctrl
    sta = app_stack.sta_ctrl
    dao = app_stack.equ_dao

    saved = eq.save_sensor(
        Sensor(
            manufacturer="CatMfg",
            model="CatModel",
            sensitivity=1.0,
            frequency=1.0,
            nrl_path="Leaf->Node->Root",
            poles=[],
            zeros=[],
        )
    )
    assert saved and saved.id is not None

    nrl_fresh = Sensor(
        manufacturer="NRL_MFG",
        model="NRL_MODEL",
        sensitivity=888.0,
        frequency=12.5,
        normalization_factor=2.0,
        normalization_freq=4.0,
        nrl_path="should-not-persist-as-is",
        poles=[PoleZero(0.25, -0.25)],
        zeros=[PoleZero(0.0, 0.0)],
        type="BB",
        description="from nrl",
    )
    fake_nrl = _FakeNRLManager(sensor=nrl_fresh)

    assert sta._apply_nrl_to_catalog_item(saved, fake_nrl, is_sensor=True) is True

    reloaded = dao.get_sensor_by_id(saved.id)
    assert reloaded is not None
    assert reloaded.id == saved.id
    assert reloaded.manufacturer == "NRL_MFG"
    assert reloaded.model == "NRL_MODEL"
    assert reloaded.description == "from nrl"
    assert reloaded.sensitivity == pytest.approx(888.0)
    assert reloaded.frequency == pytest.approx(12.5)
    assert reloaded.normalization_factor == pytest.approx(2.0)
    assert reloaded.normalization_freq == pytest.approx(4.0)
    assert reloaded.nrl_path == "Leaf->Node->Root"
    assert reloaded.type == "BB"
    assert len(reloaded.poles) == 1
    assert reloaded.poles[0].real_val == pytest.approx(0.25)
    assert reloaded.poles[0].imag_val == pytest.approx(-0.25)
    assert len(reloaded.zeros) == 1


def test_apply_nrl_to_catalog_datalogger_merges_fresh_payload_before_save(app_stack):
    eq = app_stack.eq_ctrl
    sta = app_stack.sta_ctrl
    dao = app_stack.equ_dao

    saved = eq.save_datalogger(
        Datalogger(
            manufacturer="CatDL",
            model="CatDLModel",
            gain=1.0,
            nrl_path="A->B",
            filters=[],
        )
    )
    assert saved and saved.id is not None

    coeff = json.dumps({"type": "FIR", "coefficients": [1.0, 0.0, -1.0]}, separators=(",", ":"))
    nrl_fresh = Datalogger(
        manufacturer="NRL_DL",
        model="NRL_DL_MODEL",
        gain=64.0,
        base_hardware_delay=0.01,
        base_hardware_correction=0.02,
        nrl_path="wrong",
        filters=[
            ResponseFilter(
                stage_number=1,
                filter_type="FIR",
                coefficients=coeff,
                decimation_factor=2,
                input_sample_rate=100.0,
                output_sample_rate=50.0,
                estimated_delay=0.1,
                correction_applied=0.2,
            )
        ],
    )
    fake_nrl = _FakeNRLManager(datalogger=nrl_fresh)

    assert sta._apply_nrl_to_catalog_item(saved, fake_nrl, is_sensor=False) is True

    reloaded = dao.get_datalogger_by_id(saved.id)
    assert reloaded is not None
    assert reloaded.id == saved.id
    assert reloaded.manufacturer == "NRL_DL"
    assert reloaded.model == "NRL_DL_MODEL"
    assert reloaded.gain == pytest.approx(64.0)
    assert reloaded.base_hardware_delay == pytest.approx(0.01)
    assert reloaded.nrl_path == "A->B"
    assert len(reloaded.filters) == 1
    assert reloaded.filters[0].stage_number == 1
    assert reloaded.filters[0].input_sample_rate == pytest.approx(100.0)


def test_apply_nrl_to_catalog_noop_when_fetch_returns_none(app_stack):
    eq = app_stack.eq_ctrl
    sta = app_stack.sta_ctrl
    dao = app_stack.equ_dao

    saved = eq.save_sensor(
        Sensor(
            manufacturer="Z",
            model="Z1",
            sensitivity=3.14,
            frequency=1.0,
            nrl_path="P->Q",
            poles=[],
            zeros=[],
        )
    )
    assert saved and saved.id

    fake_nrl = _FakeNRLManager(sensor=None)
    assert sta._apply_nrl_to_catalog_item(saved, fake_nrl, is_sensor=True) is False

    reloaded = dao.get_sensor_by_id(saved.id)
    assert reloaded is not None
    assert reloaded.sensitivity == pytest.approx(3.14)
