"""Shared fixtures: temp SQLite DB + wired controllers for integration tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from controllers.channel_controller import ChannelController
from controllers.equipment_controller import EquipmentController
from controllers.network_controller import NetworkController
from controllers.station_controller import StationController
from core.state import AppState
from database.db_manager import DatabaseManager
from database.daos.channel_dao import ChannelDAO
from database.daos.equipment_dao import EquipmentDAO
from database.daos.network_dao import NetworkDAO
from database.daos.station_dao import StationDAO
from importer.stationxml_parser import StationXMLParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_stationxml.db"
    db = DatabaseManager(db_path)
    db.initialize_database(SCHEMA_PATH)
    return db_path


@pytest.fixture
def app_stack(temp_db: Path):
    """Full controller stack + StationXMLParser (same wiring as desktop main)."""
    db = DatabaseManager(temp_db)
    app_state = AppState()

    net_dao = NetworkDAO(db)
    sta_dao = StationDAO(db)
    cha_dao = ChannelDAO(db)
    equ_dao = EquipmentDAO(db)

    net_ctrl = NetworkController(net_dao, app_state)
    sta_ctrl = StationController(sta_dao, app_state)
    cha_ctrl = ChannelController(cha_dao, sta_dao, app_state)
    eq_ctrl = EquipmentController(equ_dao)

    sta_ctrl.set_channel_controller(cha_ctrl)
    sta_ctrl.set_equipment_controller(eq_ctrl)
    cha_ctrl.set_equipment_controller(eq_ctrl)

    parser = StationXMLParser(net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl)

    return SimpleNamespace(
        db=db,
        app_state=app_state,
        net_ctrl=net_ctrl,
        sta_ctrl=sta_ctrl,
        cha_ctrl=cha_ctrl,
        eq_ctrl=eq_ctrl,
        equ_dao=equ_dao,
        equipment_service=eq_ctrl.equipment_service,
        parser=parser,
    )
