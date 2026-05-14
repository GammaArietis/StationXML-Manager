"""Equipment catalog business logic shared by PyQt6 and NiceGUI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from pydantic import ValidationError

from core.models.base_models import (
    Datalogger,
    Operator,
    PoleZero,
    Preamplifier,
    ResponseFilter,
    Sensor,
)
from database.daos.equipment_dao import EquipmentDAO
from utils.logging_config import log_pydantic_validation

logger = logging.getLogger(__name__)


class EquipmentInUseError(ValueError):
    """Raised when catalog equipment is still referenced by one or more channels."""

    pass


@dataclass(frozen=True)
class EquipmentSummary:
    """Catalog size and how many distinct catalog items are assigned to channels."""

    total_sensors: int
    total_dataloggers: int
    sensors_assigned_to_channels: int
    dataloggers_assigned_to_channels: int


def pole_zeros_from_pairs(pairs: Sequence[Tuple[float, float]]) -> List[PoleZero]:
    return [PoleZero(real_val=float(r), imag_val=float(i)) for r, i in pairs]


class EquipmentService:
    """Validates Pydantic models and persists via DAO (no GUI dependencies)."""

    def __init__(self, dao: EquipmentDAO) -> None:
        self._dao = dao

    def list_sensors(self) -> List[Sensor]:
        return self._dao.get_all_sensors()

    def list_dataloggers(self) -> List[Datalogger]:
        return self._dao.get_all_dataloggers()

    def list_sensors_with_nrl_path(self) -> List[Sensor]:
        return self._dao.get_sensors_with_nrl_path()

    def list_dataloggers_with_nrl_path(self) -> List[Datalogger]:
        return self._dao.get_dataloggers_with_nrl_path()

    def get_sensor(self, sensor_id: int) -> Optional[Sensor]:
        return self._dao.get_sensor_by_id(sensor_id)

    def get_datalogger(self, datalogger_id: int) -> Optional[Datalogger]:
        return self._dao.get_datalogger_by_id(datalogger_id)

    def get_operator_by_agency(self, agency: str) -> Optional[Operator]:
        """Resolve operator catalog row by agency name (used after StationXML / NRL metadata)."""
        return self._dao.get_operator_by_agency(agency or "")

    def count_channels_using_sensor(self, sensor_id: int) -> int:
        return self._dao.count_channels_using_sensor(sensor_id)

    def count_channels_using_datalogger(self, datalogger_id: int) -> int:
        return self._dao.count_channels_using_datalogger(datalogger_id)

    def get_equipment_summary(self) -> EquipmentSummary:
        """Totals for sensors/dataloggers and how many distinct catalog rows are linked to channels."""
        ts, td, sc, dc = self._dao.get_equipment_summary_counts()
        return EquipmentSummary(
            total_sensors=ts,
            total_dataloggers=td,
            sensors_assigned_to_channels=sc,
            dataloggers_assigned_to_channels=dc,
        )

    def delete_sensor(self, sensor_id: int) -> bool:
        """Remove a catalog sensor only if no channel references it."""
        n = self._dao.count_channels_using_sensor(sensor_id)
        if n > 0:
            msg = (
                f"Cannot delete sensor: {n} active channel(s) still reference it "
                "(inventory DB). Remove or reassign those channels first."
            )
            logger.warning(msg)
            raise EquipmentInUseError(msg)
        try:
            return self._dao.delete_sensor(sensor_id)
        except ValueError as e:
            logger.warning("delete_sensor refused: %s", e)
            raise EquipmentInUseError(str(e)) from e

    def delete_datalogger(self, datalogger_id: int) -> bool:
        """Remove a catalog datalogger only if no channel references it."""
        n = self._dao.count_channels_using_datalogger(datalogger_id)
        if n > 0:
            msg = (
                f"Cannot delete datalogger: {n} active channel(s) still reference it "
                "(inventory DB). Remove or reassign those channels first."
            )
            logger.warning(msg)
            raise EquipmentInUseError(msg)
        try:
            return self._dao.delete_datalogger(datalogger_id)
        except ValueError as e:
            logger.warning("delete_datalogger refused: %s", e)
            raise EquipmentInUseError(str(e)) from e

    def save_sensor(self, sensor: Sensor) -> Optional[Sensor]:
        try:
            validated = Sensor.model_validate(sensor.model_dump())
        except ValidationError as e:
            log_pydantic_validation(logger, e, "save_sensor")
            raise
        return self._dao.save_sensor(validated)

    def save_datalogger(self, dl: Datalogger) -> Optional[Datalogger]:
        try:
            normalized_filters = [
                ResponseFilter.model_validate(f.model_dump()) for f in dl.filters
            ]
            payload = dl.model_dump()
            payload["filters"] = [f.model_dump() for f in normalized_filters]
            validated = Datalogger.model_validate(payload)
        except ValidationError as e:
            log_pydantic_validation(logger, e, "save_datalogger")
            raise
        return self._dao.save_datalogger(validated)

    def clone_sensor(self, sensor: Sensor) -> Sensor:
        data = sensor.model_dump()
        data["id"] = None
        for z in data.get("zeros") or []:
            if isinstance(z, dict):
                z["id"] = None
        for p in data.get("poles") or []:
            if isinstance(p, dict):
                p["id"] = None
        if data.get("model"):
            data["model"] = f"{data['model']} (Copy)"
        return Sensor.model_validate(data)

    def sensor_after_external_import(self, sensor: Optional[Sensor]) -> Optional[Sensor]:
        """Validate and normalize a sensor returned by NRL or AROL before UI binding."""
        if sensor is None:
            return None
        try:
            return Sensor.model_validate(sensor.model_dump())
        except ValidationError as e:
            log_pydantic_validation(logger, e, "sensor_after_external_import")
            raise

    def clone_datalogger(self, dl: Datalogger) -> Datalogger:
        data = dl.model_dump()
        data["id"] = None
        for f in data.get("filters") or []:
            if isinstance(f, dict):
                f["id"] = None
        if data.get("model"):
            data["model"] = f"{data['model']} (Copy)"
        return Datalogger.model_validate(data)

    def clone_preamplifier(self, pa: Preamplifier) -> Preamplifier:
        """Deep copy for a new catalog row (clears preamp and nested stage/PZ ids)."""
        data = pa.model_dump()
        data["id"] = None
        if data.get("model"):
            data["model"] = f"{data['model']} (Copy)"
        for st in data.get("analog_stages") or []:
            if isinstance(st, dict):
                st["id"] = None
                for pz in st.get("poles") or []:
                    if isinstance(pz, dict):
                        pz["id"] = None
                for pz in st.get("zeros") or []:
                    if isinstance(pz, dict):
                        pz["id"] = None
        return Preamplifier.model_validate(data)

    def merge_sensor_from_pyqt_editor(
        self,
        base: Optional[Sensor],
        *,
        manufacturer: str,
        model: str,
        description: str,
        type_: str,
        sensitivity: float,
        frequency: float,
        input_units: str,
        output_units: str,
        pz_transfer_function_type: str,
        pole_pairs: Sequence[Tuple[float, float]],
        zero_pairs: Sequence[Tuple[float, float]],
    ) -> Sensor:
        data = base.model_dump() if base else {}
        data.update(
            {
                "manufacturer": manufacturer or "",
                "model": model or "",
                "description": description or None,
                "type": type_ or None,
                "sensitivity": sensitivity,
                "frequency": frequency,
                "input_units": input_units or "m/s",
                "output_units": output_units or "V",
                "pz_transfer_function_type": pz_transfer_function_type,
                "poles": [p.model_dump() for p in pole_zeros_from_pairs(pole_pairs)],
                "zeros": [z.model_dump() for z in pole_zeros_from_pairs(zero_pairs)],
            }
        )
        try:
            return Sensor.model_validate(data)
        except ValidationError as e:
            log_pydantic_validation(logger, e, "merge_sensor_from_pyqt_editor")
            raise

    def merge_sensor_from_web_fields(
        self,
        base: Optional[Sensor],
        *,
        manufacturer: str,
        model: str,
        sensitivity: Optional[float],
        frequency: Optional[float],
        zero_pairs: Sequence[Tuple[float, float]],
        pole_pairs: Sequence[Tuple[float, float]],
        type_: Optional[str] = None,
        description: Optional[str] = None,
        normalization_factor: Optional[float] = None,
        normalization_freq: Optional[float] = None,
        input_units: str = "m/s",
        output_units: str = "V",
        pz_transfer_function_type: str = "LAPLACE (RADIANS/SECOND)",
        nrl_path: Optional[str] = None,
    ) -> Sensor:
        data = base.model_dump() if base else {}
        data.update(
            {
                "manufacturer": manufacturer or "",
                "model": model or "",
                "sensitivity": sensitivity,
                "frequency": frequency,
                "zeros": [z.model_dump() for z in pole_zeros_from_pairs(zero_pairs)],
                "poles": [p.model_dump() for p in pole_zeros_from_pairs(pole_pairs)],
            }
        )
        if type_ is not None:
            data["type"] = type_
        if description is not None:
            data["description"] = description
        if normalization_factor is not None:
            data["normalization_factor"] = normalization_factor
        if normalization_freq is not None:
            data["normalization_freq"] = normalization_freq
        data["input_units"] = input_units
        data["output_units"] = output_units
        data["pz_transfer_function_type"] = pz_transfer_function_type
        if nrl_path is not None:
            data["nrl_path"] = nrl_path
        try:
            return Sensor.model_validate(data)
        except ValidationError as e:
            log_pydantic_validation(logger, e, "merge_sensor_from_web_fields")
            raise

    def merge_datalogger_from_web_fields(
        self,
        base: Optional[Datalogger],
        *,
        manufacturer: str,
        model: str,
        gain: Optional[float],
        filters: List[ResponseFilter],
        description: Optional[str] = None,
        max_clock_drift: Optional[float] = None,
        base_hardware_delay: Optional[float] = None,
        base_hardware_correction: Optional[float] = None,
        nrl_path: Optional[str] = None,
    ) -> Datalogger:
        data = base.model_dump() if base else {}
        try:
            norm_filters = [ResponseFilter.model_validate(f.model_dump()) for f in filters]
            data.update(
                {
                    "manufacturer": manufacturer or "",
                    "model": model or "",
                    "gain": gain,
                    "filters": [f.model_dump() for f in norm_filters],
                }
            )
            if description is not None:
                data["description"] = description
            if max_clock_drift is not None:
                data["max_clock_drift"] = max_clock_drift
            if base_hardware_delay is not None:
                data["base_hardware_delay"] = base_hardware_delay
            if base_hardware_correction is not None:
                data["base_hardware_correction"] = base_hardware_correction
            if nrl_path is not None:
                data["nrl_path"] = nrl_path
            return Datalogger.model_validate(data)
        except ValidationError as e:
            log_pydantic_validation(logger, e, "merge_datalogger_from_web_fields")
            raise
