"""Web-oriented StationXML export: single inventory vs ZIP (one XML per station)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, List, Optional, Tuple

from exporter.stationxml_builder import StationXMLExporter

ProgressCallback = Optional[Callable[[int, int, str], None]]
CancelCallback = Optional[Callable[[], bool]]


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

    def write_single_inventory_xml_to_path(
        self,
        selected_rows: List[Any],
        output_path: str,
        *,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[str]:
        """
        Scrive un unico inventario StationXML direttamente su disco (senza buffer bytes in RAM).
        Stessa logica di scope di ``build_download`` per layout single.
        Restituisce ``output_path`` in caso di successo, ``None`` se annullato.
        """
        if not selected_rows:
            raise ValueError("Nessuna stazione selezionata")
        target_id: Optional[int] = selected_rows[0]["id"] if len(selected_rows) == 1 else None
        inv = self._exporter.build_inventory(
            target_id,
            output_path=output_path,
            validate=True,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )
        if inv is None:
            return None
        return output_path

    def build_download(
        self,
        selected_rows: List[Any],
        *,
        layout: StationXMLExportLayout,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[Tuple[bytes, str]]:
        if not selected_rows:
            raise ValueError("Nessuna stazione selezionata")

        if layout == StationXMLExportLayout.ZIP_PER_STATION:
            ids = [int(r["id"]) for r in selected_rows]
            payload = self._exporter.build_zip_bytes_for_station_ids(
                ids,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )
            if payload is None:
                return None
            return payload, "stations_export.zip"

        target_id: Optional[int] = selected_rows[0]["id"] if len(selected_rows) == 1 else None
        inv = self._exporter.build_inventory(
            target_id,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )
        if inv is None:
            return None
        payload = self._exporter.inventory_to_stationxml_bytes(inv)
        return payload, "inventory_export.xml"
