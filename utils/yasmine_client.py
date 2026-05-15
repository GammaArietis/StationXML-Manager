import logging
import re
import time
from typing import List, Optional, Union

import requests

from utils.logging_config import log_network_error

logger = logging.getLogger(__name__)

YASMINE_INTER_REQUEST_DELAY_SEC = 0.85


class YasmineClient:
    """
    Client for HTTP communication with Yasmine REST APIs (SCADA).
    Manages exploration, deletion, and uploading of StationXML files.
    """

    def __init__(self, base_url: Optional[str] = None):
        if base_url is None:
            from core.config import get_settings

            base_url = get_settings().yasmine_base_url
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/xml/"
        self.import_url = f"{self.base_url}/api/xml/ie/"
        self._session = requests.Session()
        self._cached_list: Optional[List[dict]] = None

    def invalidate_cache(self) -> None:
        self._cached_list = None

    def _parse_file_list(self, res_json) -> List[dict]:
        if isinstance(res_json, dict) and "data" in res_json:
            data = res_json["data"]
            return data if isinstance(data, list) else []
        if isinstance(res_json, list):
            return res_json
        return []

    def get_all_files(self, force_refresh: bool = False) -> List[dict]:
        if self._cached_list is None or force_refresh:
            try:
                response = self._session.get(self.api_url, timeout=30)
                response.raise_for_status()
                self._cached_list = self._parse_file_list(response.json())
            except Exception as e:
                log_network_error(logger, "Yasmine", e, detail="get_all_files")
                return []
        return self._cached_list or []

    @staticmethod
    def _normalize_remote_name(name: object) -> str:
        raw = str(name or "").strip().upper()
        if raw.endswith(".XML"):
            raw = raw[:-4]
        return raw

    def find_existing_xml_in_list(
        self,
        station_code: str,
        file_list: List[dict],
        *,
        network_code: Optional[str] = None,
    ) -> Optional[str]:
        """
        Find a remote XML entry for a station (by code, legacy NETWORK_CODE_sync, or NETWORK_STATION).
        """
        code = self._normalize_remote_name(station_code)
        net = (network_code or "").strip().upper()
        legacy_sync = f"{net}_{code}_SYNC" if net else None
        legacy_pair = f"{net}_{code}" if net else None

        for item in file_list:
            if not isinstance(item, dict):
                continue
            remote = self._normalize_remote_name(item.get("name"))
            if remote == code:
                return str(item.get("id") or item.get("name"))
            if legacy_sync and remote == legacy_sync:
                return str(item.get("id") or item.get("name"))
            if legacy_pair and remote == legacy_pair:
                return str(item.get("id") or item.get("name"))
            if net and legacy_pair and legacy_pair in remote:
                return str(item.get("id") or item.get("name"))
        return None

    def find_existing_xml(
        self, network_code: str, station_code: str, *, force_refresh: bool = False
    ) -> Optional[str]:
        lista_file = self.get_all_files(force_refresh=force_refresh)
        return self.find_existing_xml_in_list(
            station_code, lista_file, network_code=network_code
        )

    def get_all_imported_xmls(self, *, force_refresh: bool = True) -> List[dict]:
        try:
            response = self._session.get(self.api_url, timeout=10)
            if response.status_code == 200:
                files = self._parse_file_list(response.json())
                if force_refresh:
                    self._cached_list = files
                return files
            return []
        except Exception as e:
            log_network_error(logger, "Yasmine", e, detail="get_all_imported_xmls")
            return []

    def delete_remote_for_station(
        self, station_code: str, file_list: List[dict], *, network_code: Optional[str] = None
    ) -> bool:
        item_id = self.find_existing_xml_in_list(
            station_code, file_list, network_code=network_code
        )
        if not item_id:
            return True
        return self.delete_xml(item_id)

    def delete_xml(self, item_id) -> bool:
        base_url = self.api_url.rstrip("/")
        url = f"{base_url}/{item_id}"
        try:
            numeric_id = item_id
            if isinstance(item_id, str) and item_id.isdigit():
                numeric_id = int(item_id)
            response = self._session.delete(
                url, json={"id": numeric_id}, timeout=10
            )
            ok = response.status_code in [200, 204]
            if ok:
                self.invalidate_cache()
            return ok
        except Exception as e:
            log_network_error(logger, "Yasmine", e, detail=f"delete_xml id={item_id}")
            return False

    def lookup_remote_id(
        self,
        station_code: str,
        *,
        retries: int = 6,
        delay_sec: float = 0.45,
    ) -> Optional[Union[int, str]]:
        """Poll Yasmine file list until the station entry appears (bulk uploads need this)."""
        norm = self._normalize_remote_name(station_code)
        for attempt in range(retries):
            for item in self.get_all_imported_xmls(force_refresh=True):
                if not isinstance(item, dict):
                    continue
                if self._normalize_remote_name(item.get("name")) == norm:
                    remote_id = item.get("id")
                    if remote_id is not None:
                        return remote_id
            if attempt < retries - 1:
                time.sleep(delay_sec)
        return None

    def upload_xml(self, xml_bytes: bytes, station_code: str) -> Optional[Union[int, str]]:
        base_url = self.api_url.rstrip("/")
        url = f"{base_url}/ie/"
        code = re.sub(r"[^\w\-.]", "", str(station_code).strip()) or station_code

        files = {"xml-path": (f"{code}.xml", xml_bytes, "text/xml")}
        data = {"name": code}

        try:
            response = self._session.post(url, files=files, data=data, timeout=30)
            if response.status_code not in [200, 201]:
                logger.error("Yasmine upload error: %s", response.status_code)
                return None

            logger.info("Upload of %s completed. Retrieving ID...", code)
            self.invalidate_cache()
            new_id = self.lookup_remote_id(code)
            if new_id is not None:
                logger.info("ID %s successfully retrieved for %s.", new_id, code)
                return new_id

            # Upload OK but list lagging — still allow local sync (same as manual single send).
            logger.warning(
                "File uploaded for %s but ID not in list yet; using station code as node id.",
                code,
            )
            return code
        except Exception as e:
            log_network_error(logger, "Yasmine", e, detail=f"upload_xml station={code}")
            return None
