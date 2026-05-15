from typing import List, Optional

from core.models.base_models import Datalogger, Operator, Preamplifier, Sensor
from core.services.catalog_service import CatalogService
from core.services.equipment_service import EquipmentService, EquipmentSummary
from database.daos.equipment_dao import EquipmentDAO

from utils.nrl_client import NRLManager
from utils.arol_client import AROLClient


class EquipmentController:
    """Thin adapter: stato NRL/AROL in UI + delega al CatalogService (logica di dominio)."""

    def __init__(self, dao: EquipmentDAO) -> None:
        self.dao = dao
        self._catalog = CatalogService(dao)
        self.nrl_manager = NRLManager()
        self.arol_client = AROLClient()

    @property
    def equipment_service(self) -> EquipmentService:
        return self._catalog.equipment

    @property
    def catalog_service(self) -> CatalogService:
        return self._catalog

    def get_all_sensors(self) -> List[Sensor]:
        return self._catalog.equipment.list_sensors()

    def get_all_dataloggers(self) -> List[Datalogger]:
        return self._catalog.equipment.list_dataloggers()

    def get_sensors_with_nrl_path(self) -> List[Sensor]:
        return self._catalog.equipment.list_sensors_with_nrl_path()

    def get_dataloggers_with_nrl_path(self) -> List[Datalogger]:
        return self._catalog.equipment.list_dataloggers_with_nrl_path()

    def save_sensor(self, sensor: Sensor) -> Optional[Sensor]:
        return self._catalog.save_sensor(sensor)

    def save_datalogger(self, datalogger: Datalogger) -> Optional[Datalogger]:
        return self._catalog.save_datalogger(datalogger)

    def clone_sensor_model(self, sensor: Sensor) -> Sensor:
        return self._catalog.equipment.clone_sensor(sensor)

    def clone_datalogger_model(self, dl: Datalogger) -> Datalogger:
        return self._catalog.equipment.clone_datalogger(dl)

    def clone_preamplifier_model(self, pa: Preamplifier) -> Preamplifier:
        return self._catalog.equipment.clone_preamplifier(pa)

    def clone_operator_model(self, operator: Operator) -> Operator:
        return self._catalog.equipment.clone_operator(operator)

    def delete_sensor(self, sensor_id: int) -> bool:
        return self._catalog.delete_sensor(sensor_id)

    def delete_datalogger(self, datalogger_id: int) -> bool:
        return self._catalog.delete_datalogger(datalogger_id)

    def get_all_operators(self) -> List[Operator]:
        return self._catalog.list_operators()

    def get_operator_by_agency(self, agency: str) -> Optional[Operator]:
        return self._catalog.equipment.get_operator_by_agency(agency)

    def get_operator_by_details(self, agency: str, contact_name: str, contact_email: str) -> Optional[Operator]:
        return self._catalog.get_operator_by_details(agency, contact_name, contact_email)

    def save_operator(self, operator: Operator) -> Optional[Operator]:
        return self._catalog.save_operator(operator)

    def delete_operator(self, op_id: int) -> bool:
        return self._catalog.delete_operator(op_id)

    def get_operator_by_id(self, op_id: int) -> Optional[Operator]:
        return self._catalog.get_operator_by_id(op_id)

    def replace_operator(self, old_id: int, new_id: int) -> bool:
        return self._catalog.replace_operator(old_id, new_id)

    def get_all_preamplifiers(self) -> List[Preamplifier]:
        return self._catalog.list_preamplifiers()

    def save_preamplifier(self, preamp_data: Preamplifier) -> Optional[Preamplifier]:
        return self._catalog.save_preamplifier(preamp_data)

    def delete_preamplifier(self, preamp_id: int) -> bool:
        return self._catalog.delete_preamplifier(preamp_id)

    def get_preamplifier_by_id(self, preamp_id: int) -> Optional[Preamplifier]:
        return self._catalog.get_preamplifier_by_id(preamp_id)

    def get_equipment_summary(self) -> EquipmentSummary:
        return self._catalog.get_equipment_summary()

    def replace_equipment(self, category: str, old_id: int, new_id: int) -> bool:
        return self._catalog.replace_equipment(category, old_id, new_id)

    def get_sensor(self, sensor_id: int) -> Optional[Sensor]:
        return self._catalog.equipment.get_sensor(sensor_id)

    def get_sensor_by_id(self, sensor_id: int) -> Optional[Sensor]:
        return self._catalog.equipment.get_sensor(sensor_id)

    def get_datalogger(self, datalogger_id: int) -> Optional[Datalogger]:
        return self._catalog.equipment.get_datalogger(datalogger_id)

    def get_datalogger_by_id(self, datalogger_id: int) -> Optional[Datalogger]:
        return self._catalog.equipment.get_datalogger(datalogger_id)

    def auto_classify_sensor_type(self, sensor: Sensor) -> str:
        unit_up = str(sensor.input_units or "").strip().upper()
        if "M/S**2" in unit_up:
            return "SM"
        if "PA" in unit_up:
            return "PRESSURE"
        if "RAD" in unit_up:
            return "TILTMETER"
        if "T" in unit_up or "TESLA" in unit_up:
            return "MAGNETOMETER"
        if "M/S" in unit_up and sensor.poles:
            import math

            valid_poles = []
            for p in sensor.poles:
                real_val = getattr(p, "real_val", getattr(p, "real", 0.0))
                imag_val = getattr(p, "imag_val", getattr(p, "imag", 0.0))
                magnitude = math.sqrt(real_val**2 + imag_val**2)
                if magnitude > 1e-6:
                    valid_poles.append(magnitude)
            if valid_poles:
                min_mag = min(valid_poles)
                is_hertz = "HERTZ" in str(sensor.pz_transfer_function_type or "").upper()
                fc = min_mag if is_hertz else (min_mag / (2 * math.pi))
                if fc <= 0.02:
                    return "VBB"
                if fc <= 0.2:
                    return "BB"
                if fc >= 1.0:
                    return "SP"
                return "BB"
        return "SENSOR"
