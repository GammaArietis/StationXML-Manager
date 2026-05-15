"""Logica di dominio stazioni: hash sync Yasmine, salvataggio con validazione, refresh catalogo NRL."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, List, Optional, Protocol, Tuple

from core.models.base_models import Datalogger, Sensor, Station
from core.services.equipment_service import EquipmentService
from core.validators.geo_validators import ValidationError, validate_coordinates
from database.daos.channel_dao import ChannelDAO
from database.daos.station_dao import StationDAO

logger = logging.getLogger(__name__)


def calculate_station_hash(station: Station) -> str:
    """Impronta SHA-256 sui campi chiave usata per confrontare lo stato locale con Yasmine."""
    raw_data = (
        f"{station.code}_{station.network_id}_{station.latitude}_{station.longitude}_"
        f"{station.elevation}_{station.start_date}"
    )
    return hashlib.sha256(raw_data.encode("utf-8")).hexdigest()


class _NrlManagerLike(Protocol):
    def fetch_sensor(self, keys: list[str]) -> Any: ...

    def fetch_datalogger(self, keys: list[str]) -> Any: ...


class StationService:
    """
    Punto unico per persistenza e regole stazione (senza AppState / GUI).
    Desktop e Web usano il controller che delega qui.
    """

    def __init__(self, station_dao: StationDAO) -> None:
        self._dao = station_dao

    def get_station_by_id(self, station_id: int) -> Optional[Station]:
        return self._dao.get_by_id(station_id)

    def get_stations_by_network(self, network_id: int) -> List[Station]:
        return self._dao.get_by_network_id(network_id)

    def get_all_stations(self) -> List[Station]:
        return self._dao.get_all()

    def delete_station(self, station_id: int) -> bool:
        return self._dao.delete(station_id)

    def save_station(self, station: Station) -> Optional[Station]:
        """
        Valida coordinate, insert/update e invalida sync Yasmine su update riuscito.
        """
        validate_coordinates(station.latitude, station.longitude, station.elevation)
        if station.id is None:
            return self._dao.insert(station)
        success = self._dao.update(station)
        if not success:
            return None
        self._dao.update_sync_hash(station.id, "NEEDS_SYNC")
        logger.info("Synchronization invalidated for %s (data modified).", station.code)
        return station

    def get_sync_status(self, station: Station) -> Tuple[str, str, str]:
        if not station.id:
            return ("NEW", "⚪", "Station not yet saved in local DB")
        record = self._dao.get_sync_state(station.id)
        current_hash = calculate_station_hash(station)
        if not record:
            return ("UNSYNCED", "⚪", "Never sent to Yasmine")
        yasmine_id = record["yasmine_node_id"]
        saved_hash = record["local_xml_hash"]
        timestamp = record["sync_timestamp"]
        if current_hash == saved_hash:
            return (
                "SYNCED",
                "🟢",
                f"Aligned with Yasmine (ID: {yasmine_id}) - Last upload: {timestamp}",
            )
        return ("MODIFIED", "🔴", "Modified locally. Yasmine archive is out of date!")

    def mark_as_synced(self, station: Station, yasmine_node_id: str) -> bool:
        if not station.id:
            return False
        current_hash = calculate_station_hash(station)
        return self._dao.upsert_sync_state(station.id, yasmine_node_id, current_hash)

    @staticmethod
    def _merge_nrl_sensor_into_catalog(catalog: Sensor, nrl: Sensor) -> Sensor:
        payload = nrl.model_dump()
        payload["id"] = catalog.id
        payload["nrl_path"] = catalog.nrl_path
        return Sensor.model_validate(payload)

    @staticmethod
    def _merge_nrl_datalogger_into_catalog(catalog: Datalogger, nrl: Datalogger) -> Datalogger:
        payload = nrl.model_dump()
        payload["id"] = catalog.id
        payload["nrl_path"] = catalog.nrl_path
        return Datalogger.model_validate(payload)

    def apply_nrl_to_catalog_item(
        self,
        equipment: object,
        nrl_mgr: _NrlManagerLike,
        *,
        equipment_service: EquipmentService,
        is_sensor: bool = True,
    ) -> bool:
        """Scarica da NRL, merge su record catalogo (mantiene id/nrl_path), salva via EquipmentService."""
        try:
            path = getattr(equipment, "nrl_path", None)
            if not path:
                return False
            keys = [k.strip() for k in path.split("->")]
            data = nrl_mgr.fetch_sensor(keys) if is_sensor else nrl_mgr.fetch_datalogger(keys)
            if not data:
                return False
            if is_sensor:
                if not isinstance(equipment, Sensor) or not isinstance(data, Sensor):
                    logger.error(
                        "NRL sync sensor: attesi Sensor, tipi=%s / %s",
                        type(equipment),
                        type(data),
                    )
                    return False
                merged = self._merge_nrl_sensor_into_catalog(equipment, data)
                equipment_service.save_sensor(merged)
            else:
                if not isinstance(equipment, Datalogger) or not isinstance(data, Datalogger):
                    logger.error(
                        "NRL sync datalogger: attesi Datalogger, tipi=%s / %s",
                        type(equipment),
                        type(data),
                    )
                    return False
                merged = self._merge_nrl_datalogger_into_catalog(equipment, data)
                equipment_service.save_datalogger(merged)
            return True
        except Exception as e:
            logger.error("NRL Error on %s: %s", getattr(equipment, "model", equipment), e)
        return False

    def run_nrl_catalog_refresh(
        self,
        *,
        equipment_service: EquipmentService,
        channel_dao: ChannelDAO,
        nrl_mgr: Optional[_NrlManagerLike] = None,
        progress_queue: Optional[Any] = None,
    ) -> int:
        """
        Aggiorna tutti i sensori/datalogger con nrl_path da NRL e marca le stazioni colpite.
        Restituisce il numero di stazioni con semaforo rosso aggiornato.
        """
        if nrl_mgr is None:
            from utils.nrl_client import NRLManager

            nrl_mgr = NRLManager()

        def _progress(done: int, total: int, msg: str) -> None:
            if progress_queue is not None:
                progress_queue.put(("p", done, total, msg))

        dl_nrl = equipment_service.list_dataloggers_with_nrl_path()
        sn_nrl = equipment_service.list_sensors_with_nrl_path()
        stations = self._dao.get_all()
        total_steps = len(dl_nrl) + len(sn_nrl) + len(stations)
        if total_steps <= 0:
            total_steps = 1

        done = 0
        updated_dataloggers: set[int] = set()
        for dl in dl_nrl:
            if self.apply_nrl_to_catalog_item(
                dl, nrl_mgr, equipment_service=equipment_service, is_sensor=False
            ):
                updated_dataloggers.add(dl.id)
            done += 1
            model = getattr(dl, "model", "?")
            _progress(done, total_steps, f"Datalogger {model} — {done}/{total_steps}")

        updated_sensors: set[int] = set()
        for sn in sn_nrl:
            if self.apply_nrl_to_catalog_item(
                sn, nrl_mgr, equipment_service=equipment_service, is_sensor=True
            ):
                updated_sensors.add(sn.id)
            done += 1
            model = getattr(sn, "model", "?")
            _progress(done, total_steps, f"Sensore {model} — {done}/{total_steps}")

        if not updated_dataloggers and not updated_sensors:
            logger.info("No updates required for the catalog.")
            _progress(total_steps, total_steps, "Nessun aggiornamento al catalogo.")
            return 0

        red_lights_count = 0
        for station in stations:
            channels = channel_dao.get_by_station_id(station.id)
            station_needs_sync = False
            for cha in channels:
                if cha.datalogger_id in updated_dataloggers or cha.sensor_id in updated_sensors:
                    station_needs_sync = True
                    break
            if station_needs_sync:
                self._dao.update_sync_hash(station.id, "NRL_CATALOG_MODIFIED")
                red_lights_count += 1
            done += 1
            code = getattr(station, "code", "?")
            _progress(done, total_steps, f"Stazione {code} — {done}/{total_steps}")

        logger.info(
            "=== REFRESH COMPLETED === Instruments updated: %s, RED Stations: %s",
            len(updated_dataloggers) + len(updated_sensors),
            red_lights_count,
        )
        return red_lights_count

    def run_nrl_refresh_for_station(
        self,
        station_id: int,
        *,
        equipment_service: EquipmentService,
        channel_dao: ChannelDAO,
        nrl_mgr: Optional[_NrlManagerLike] = None,
    ) -> bool:
        """
        Re-apply NRL metadata for sensors/dataloggers used by channels on one station.
        Marks the station out-of-sync when any catalog item changes.
        """
        if nrl_mgr is None:
            from utils.nrl_client import NRLManager

            nrl_mgr = NRLManager()

        channels = channel_dao.get_by_station_id(station_id)
        sensor_ids = {c.sensor_id for c in channels if c.sensor_id}
        datalogger_ids = {c.datalogger_id for c in channels if c.datalogger_id}

        changed = False
        for sid in sensor_ids:
            sn = equipment_service.get_sensor(sid)
            if sn and getattr(sn, "nrl_path", None):
                if self.apply_nrl_to_catalog_item(
                    sn, nrl_mgr, equipment_service=equipment_service, is_sensor=True
                ):
                    changed = True

        for did in datalogger_ids:
            dl = equipment_service.get_datalogger(did)
            if dl and getattr(dl, "nrl_path", None):
                if self.apply_nrl_to_catalog_item(
                    dl, nrl_mgr, equipment_service=equipment_service, is_sensor=False
                ):
                    changed = True

        if changed:
            self._dao.update_sync_hash(station_id, "NRL_CATALOG_MODIFIED")
        return changed
