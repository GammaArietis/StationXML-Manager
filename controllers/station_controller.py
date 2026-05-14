import logging
from typing import Any, List, Optional, Tuple

from core.models.base_models import Station
from core.services.station_service import StationService, calculate_station_hash
from database.daos.station_dao import StationDAO
from core.state import AppState
from core.validators.geo_validators import ValidationError

logger = logging.getLogger(__name__)

# Compatibilità import esistenti (hash definito in core.services.station_service)
__all__ = ["StationController", "calculate_station_hash"]


class StationController:
    def __init__(self, dao: StationDAO, app_state: AppState) -> None:
        self.dao = dao
        self.state = app_state
        self._service = StationService(dao)
        self.cha_ctrl = None
        self.equ_ctrl = None

    @property
    def station_service(self) -> StationService:
        return self._service

    def set_channel_controller(self, cha_ctrl: object) -> None:
        self.cha_ctrl = cha_ctrl

    def set_equipment_controller(self, equ_ctrl: object) -> None:
        self.equ_ctrl = equ_ctrl

    def get_stations_by_network(self, network_id: int) -> List[Station]:
        return self._service.get_stations_by_network(network_id)

    def save_station(self, station: Station) -> Optional[Station]:
        try:
            saved_sta = self._service.save_station(station)
            if saved_sta:
                self.state.mark_clean()
            return saved_sta
        except ValidationError as ve:
            logger.warning("Station validation failed: %s", ve)
            raise
        except Exception as e:
            logger.error("Critical error saving station: %s", e)
            raise

    def get_station_by_id(self, station_id: int) -> Optional[Station]:
        return self._service.get_station_by_id(station_id)

    def delete_station(self, station_id: int) -> bool:
        success = self._service.delete_station(station_id)
        if success and self.state._current_station_id == station_id:
            self.state._current_station_id = None
            self.state.mark_clean()
        return success

    def get_sync_status(self, station: Station) -> Tuple[str, str, str]:
        return self._service.get_sync_status(station)

    def mark_as_synced(self, station: Station, yasmine_node_id: str) -> bool:
        return self._service.mark_as_synced(station, yasmine_node_id)

    def update_all_nrl_sensors(self, progress_queue: Optional[Any] = None) -> int:
        if not self.cha_ctrl or not self.equ_ctrl:
            logger.error("Missing controllers in StationController!")
            return 0
        return self._service.run_nrl_catalog_refresh(
            equipment_service=self.equ_ctrl.equipment_service,
            channel_dao=self.cha_ctrl.dao,
            progress_queue=progress_queue,
        )

    def _apply_nrl_to_catalog_item(self, equipment: object, nrl_mgr: object, is_sensor: bool = True) -> bool:
        """Delega al service (test e tooling legacy)."""
        if not self.equ_ctrl:
            return False
        return self._service.apply_nrl_to_catalog_item(
            equipment,
            nrl_mgr,
            equipment_service=self.equ_ctrl.equipment_service,
            is_sensor=is_sensor,
        )

    def _apply_nrl_to_channel(self, channel: object, nrl_path: Optional[str], nrl_mgr: object) -> bool:
        try:
            if not nrl_path:
                return False
            keys = [k.strip() for k in nrl_path.split("->")]
            data = nrl_mgr.fetch_sensor(keys) or nrl_mgr.fetch_datalogger(keys)
            if data and self.cha_ctrl:
                return self.cha_ctrl.apply_nrl_data(channel.id, data)
        except Exception as e:
            logger.error("NRL Error on channel %s: %s", getattr(channel, "code", channel), e)
        return False
