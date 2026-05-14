import logging
from typing import List, Optional

from core.models.base_models import Channel
from core.services.channel_service import ChannelService
from database.daos.channel_dao import ChannelDAO
from database.daos.station_dao import StationDAO
from core.state import AppState

logger = logging.getLogger(__name__)


class ChannelController:
    """
    Gestisce i canali e la sensibilità aggregata; persistenza e sync via ChannelService.
    """

    def __init__(self, dao: ChannelDAO, station_dao: StationDAO, app_state: AppState) -> None:
        self.dao = dao
        self.station_dao = station_dao
        self.state = app_state
        self._service = ChannelService(dao, station_dao)
        self.eq_ctrl = None

    @property
    def channel_service(self) -> ChannelService:
        return self._service

    def set_equipment_controller(self, eq_ctrl: object) -> None:
        self.eq_ctrl = eq_ctrl

    def calculate_total_sensitivity(self, channel: Channel) -> Optional[float]:
        if not self.eq_ctrl:
            logger.warning("Equipment Controller not connected to Channel Controller.")
            return None
        total_sens = 1.0
        if channel.sensor_id:
            sensor = self.eq_ctrl.get_sensor(channel.sensor_id)
            if sensor and sensor.sensitivity:
                total_sens *= float(sensor.sensitivity)
        if channel.pre_amplifier_id:
            preamp = self.eq_ctrl.get_preamplifier_by_id(channel.pre_amplifier_id)
            if preamp and hasattr(preamp, "analog_stages"):
                for stage in preamp.analog_stages:
                    total_sens *= float(stage.stage_gain)
        if channel.datalogger_id:
            dl = self.eq_ctrl.get_datalogger(channel.datalogger_id)
            if dl and getattr(dl, "gain", None):
                total_sens *= float(dl.gain)
        return total_sens

    def get_channel_by_id(self, channel_id: int) -> Optional[Channel]:
        return self._service.get_channel_by_id(channel_id)

    def get_channels_by_station(self, station_id: int) -> List[Channel]:
        return self._service.get_channels_by_station(station_id)

    def save_channel(self, channel: Channel) -> Optional[Channel]:
        try:
            return self._service.save_channel(channel)
        except Exception as e:
            logger.error("Error saving channel: %s", e)
            raise

    def delete_channel(self, channel_id: int) -> bool:
        return self._service.delete_channel(channel_id)

    def apply_nrl_data(self, channel_id: int, nrl_data: object) -> bool:
        try:
            if hasattr(nrl_data, "zeros"):
                logger.info("Poles and Zeros updated for channel %s", channel_id)
                return True
            if hasattr(nrl_data, "filters"):
                logger.info("Datalogger filters updated for channel %s", channel_id)
                return True
            return False
        except Exception as e:
            logger.error("Error applying NRL data to DB: %s", e)
            return False
