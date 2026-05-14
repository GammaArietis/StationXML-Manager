"""Web-oriented StationXML export: single inventory vs ZIP (one XML per station)."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, Tuple

from exporter.stationxml_builder import StationXMLExporter


class StationXMLExportLayout(str, Enum):
    """Export packaging for NiceGUI / API consumers."""

    SINGLE_INVENTORY = "single"
    ZIP_PER_STATION = "zip"


class StationXMLWebExportController:
    """
    Encapsulates export rules used by the web UI.

    Single inventory (legacy):
      - exactly one selected station -> inventory limited to that station;
      - multiple (or ambiguous) selection -> full DB inventory (``target_station_id=None``).

    ZIP per station:
      - one StationXML per selected row, filenames ``{station_code}.xml`` (disambiguated in ZIP).
    """

    def __init__(self, net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl) -> None:
        self._exporter = StationXMLExporter(net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl)

    @property
    def exporter(self) -> StationXMLExporter:
        return self._exporter

    def build_download(
        self,
        selected_rows: List[Any],
        *,
        layout: StationXMLExportLayout,
    ) -> Tuple[bytes, str]:
        if not selected_rows:
            raise ValueError("Nessuna stazione selezionata")

        if layout == StationXMLExportLayout.ZIP_PER_STATION:
            ids = [int(r["id"]) for r in selected_rows]
            payload = self._exporter.build_zip_bytes_for_station_ids(ids)
            return payload, "stations_export.zip"

        target_id: Optional[int] = selected_rows[0]["id"] if len(selected_rows) == 1 else None
        inv = self._exporter.build_inventory(target_station_id=target_id)
        payload = self._exporter.inventory_to_stationxml_bytes(inv)
        return payload, "inventory_export.xml"
