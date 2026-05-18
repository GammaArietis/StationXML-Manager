"""StationXML export packaging: one XML per station, optionally zipped."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from exporter.stationxml_builder import StationXMLExporter

ProgressCallback = Optional[Callable[[int, int, str], None]]
CancelCallback = Optional[Callable[[], bool]]


class StationXMLWebExportController:
    """
    Encapsulates export rules used by the web UI.

    Export policy:
      - one selected station -> one XML payload;
      - multiple selected stations -> ZIP containing one XML per station.
    """

    def __init__(self, net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl) -> None:
        self._exporter = StationXMLExporter(net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl)

    @property
    def exporter(self) -> StationXMLExporter:
        return self._exporter

    def write_station_xml_files_to_directory(
        self,
        selected_rows: List[Any],
        output_dir: str,
        *,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[List[str]]:
        """Write one StationXML file per selected station into output_dir."""
        if not selected_rows:
            raise ValueError("Nessuna stazione selezionata")
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        written: List[str] = []
        total = len(selected_rows)
        for idx, row in enumerate(selected_rows, start=1):
            if cancel_callback and cancel_callback():
                return None
            station_id = int(row["id"] if isinstance(row, dict) else row)
            filename = self._exporter.station_xml_filename(station_id, used)
            path = target_dir / filename
            if progress_callback:
                progress_callback(idx, total, f"Writing {filename}…")
            inv = self._exporter.build_station_inventory(
                station_id,
                output_path=str(path),
                validate=True,
                progress_callback=None,
                cancel_callback=cancel_callback,
            )
            if inv is None:
                return None
            written.append(str(path))
        return written

    def build_download(
        self,
        selected_rows: List[Any],
        *,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[Tuple[bytes, str]]:
        if not selected_rows:
            raise ValueError("Nessuna stazione selezionata")

        ids = [int(r["id"] if isinstance(r, dict) else r) for r in selected_rows]
        if len(ids) > 1:
            payload = self._exporter.build_zip_bytes_for_station_ids(
                ids,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )
            if payload is None:
                return None
            return payload, "stations_export.zip"

        station_id = ids[0]
        payload = self._exporter.build_stationxml_bytes(
            station_id,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )
        if payload is None:
            return None
        return payload, self._exporter.station_xml_filename(station_id)
