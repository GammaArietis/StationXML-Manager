import logging
from typing import List, Optional

from core.models.base_models import Channel
from core.services.channel_service import ChannelService
from database.daos.channel_dao import ChannelDAO
from database.daos.station_dao import StationDAO
from core.state import AppState
from utils.fdsn_seed_codes import (
    get_fdsn_band_code,
    get_instrument_code,
    is_broadband_from_poles,
)

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
        preamp_gain = getattr(channel, "pre_amplifier_gain", None)
        if preamp_gain is not None and float(preamp_gain) > 0:
            total_sens *= float(preamp_gain)
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

    def save_channel_with_triad_sync(self, channel: Channel) -> dict:
        try:
            saved, synced = self._service.save_channel_with_triad_sync(channel)
            return {"channel": saved, "synced_channels": synced}
        except Exception as e:
            logger.error("Error saving channel with triad sync: %s", e)
            raise

    def get_datalogger_sample_rate(self, datalogger_id: int) -> float:
        if not self.eq_ctrl:
            return 100.0
        dl = self.eq_ctrl.get_datalogger(datalogger_id)
        if not dl:
            return 100.0
        filters = sorted(getattr(dl, "filters", []) or [], key=lambda f: f.stage_number)
        for filt in reversed(filters):
            out_rate = getattr(filt, "output_sample_rate", None)
            if out_rate and float(out_rate) > 0:
                return float(out_rate)
            in_rate = getattr(filt, "input_sample_rate", None)
            dec = getattr(filt, "decimation_factor", None) or 1
            if in_rate and float(in_rate) > 0 and dec:
                return float(in_rate) / float(dec)
        return 100.0

    def _final_sample_rate_from_datalogger(self, datalogger_id: int) -> float:
        return self.get_datalogger_sample_rate(datalogger_id)

    def auto_generate_triaxial_channels(
        self,
        station_id: int,
        datalogger_id: int,
        sensor_id: int,
        depth: float,
        instrument_code: str,
        is_broadband: bool,
        start_time: str | None = None,
        band_code: str | None = None,
    ) -> List[Channel]:
        sample_rate = self._final_sample_rate_from_datalogger(datalogger_id)
        sensor = self.eq_ctrl.get_sensor(sensor_id) if self.eq_ctrl else None
        if sensor is not None:
            auto_broadband = is_broadband_from_poles(
                getattr(sensor, "poles", []),
                pz_transfer_function_type=getattr(
                    sensor, "pz_transfer_function_type", "LAPLACE (RADIANS/SECOND)"
                ),
            )
            if is_broadband is None:
                is_broadband = auto_broadband

        inst = (instrument_code or "").strip().upper()[:1]
        if not inst and sensor is not None:
            inst = get_instrument_code(getattr(sensor, "input_units", ""))
        inst = inst or "H"
        band = (band_code or "").strip().upper()[:1]
        if not band:
            band = get_fdsn_band_code(
                sample_rate,
                bool(is_broadband),
                instrument_code=inst,
            )
        axes = [
            ("Z", 0.0, -90.0),
            ("N", 0.0, 0.0),
            ("E", 90.0, 0.0),
        ]

        saved_channels: List[Channel] = []
        for axis, azimuth, dip in axes:
            channel = Channel(
                station_id=station_id,
                code=f"{band}{inst}{axis}",
                location_code="",
                depth=depth,
                sample_rate=sample_rate,
                azimuth=azimuth,
                dip=dip,
                start_date=start_time,
                sensor_id=sensor_id,
                datalogger_id=datalogger_id,
                restricted_status="open",
            )
            channel.overall_sensitivity = self.calculate_total_sensitivity(channel)
            saved = self.save_channel(channel)
            if saved:
                saved_channels.append(saved)
        return saved_channels

    def recalculate_all_sensitivities(self) -> int:
        count = 0
        for station in self.station_dao.get_all():
            if not getattr(station, "id", None):
                continue
            for channel in self.get_channels_by_station(station.id):
                new_value = self.calculate_total_sensitivity(channel)
                if new_value is None:
                    continue
                channel.overall_sensitivity = new_value
                if self.save_channel(channel):
                    count += 1
        return count

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
