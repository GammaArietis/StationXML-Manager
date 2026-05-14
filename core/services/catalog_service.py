"""Catalogo strumenti e operatori: validazioni e orchestrazione DAO (UI-agnostic)."""

from __future__ import annotations

import logging
from typing import List, Optional

from core.models.base_models import Datalogger, Operator, Preamplifier, Sensor
from core.services.equipment_service import EquipmentInUseError, EquipmentService, EquipmentSummary
from database.daos.equipment_dao import EquipmentDAO

logger = logging.getLogger(__name__)

__all__ = ["CatalogService", "EquipmentInUseError"]


class CatalogService:
    """
    Punto unico per il catalogo equipment + operatori.
    Incapsula `EquipmentService` (sensori/datalogger con integrità cancellazione) e il DAO per il resto.
    """

    def __init__(self, dao: EquipmentDAO) -> None:
        self._dao = dao
        self._equipment = EquipmentService(dao)

    @property
    def equipment(self) -> EquipmentService:
        return self._equipment

    def save_sensor(self, sensor: Sensor) -> Optional[Sensor]:
        if not sensor.manufacturer or not sensor.model:
            raise ValueError("Manufacturer and Model are required for the Sensor.")
        return self._equipment.save_sensor(sensor)

    def save_datalogger(self, datalogger: Datalogger) -> Optional[Datalogger]:
        if not datalogger.manufacturer or not datalogger.model:
            raise ValueError("Manufacturer and Model are required for the Datalogger.")
        return self._equipment.save_datalogger(datalogger)

    def delete_sensor(self, sensor_id: int) -> bool:
        return self._equipment.delete_sensor(sensor_id)

    def delete_datalogger(self, datalogger_id: int) -> bool:
        return self._equipment.delete_datalogger(datalogger_id)

    def replace_equipment(self, category: str, old_id: int, new_id: int) -> bool:
        return self._dao.replace_equipment(category, old_id, new_id)

    def list_operators(self) -> List[Operator]:
        return self._dao.get_all_operators()

    def save_operator(self, operator: Operator) -> Optional[Operator]:
        if not operator.agency:
            raise ValueError("Agency is required.")
        return self._dao.save_operator(operator)

    def delete_operator(self, op_id: int) -> bool:
        return self._dao.delete_operator(op_id)

    def get_operator_by_id(self, op_id: int) -> Optional[Operator]:
        return self._dao.get_operator_by_id(op_id)

    def get_operator_by_details(
        self, agency: str, contact_name: str, contact_email: str
    ) -> Optional[Operator]:
        return self._dao.get_operator_by_details(agency, contact_name, contact_email)

    def replace_operator(self, old_id: int, new_id: int) -> bool:
        return self._dao.replace_operator(old_id, new_id)

    def list_preamplifiers(self) -> List[Preamplifier]:
        return self._dao.get_all_preamplifiers()

    def save_preamplifier(self, preamp: Preamplifier) -> Optional[Preamplifier]:
        return self._dao.save_preamplifier(preamp)

    def delete_preamplifier(self, preamp_id: int) -> bool:
        return self._dao.delete_preamplifier(preamp_id)

    def get_preamplifier_by_id(self, preamp_id: int) -> Optional[Preamplifier]:
        return self._dao.get_preamplifier_by_id(preamp_id)

    def get_equipment_summary(self) -> EquipmentSummary:
        return self._equipment.get_equipment_summary()
