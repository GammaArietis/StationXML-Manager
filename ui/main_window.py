from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QStackedWidget, QMessageBox, QFileDialog, QSplitter, QLabel,
                             QDialog, QRadioButton, QComboBox, QDialogButtonBox, QProgressDialog, QApplication,
                             QGroupBox, QButtonGroup)
from PyQt6.QtCore import Qt
import logging
import time
import io

from PyQt6.QtGui import QAction
from utils.geocoding_client import fetch_geography_from_coords
from utils.geology_client import fetch_geology_from_coords

from ui.widgets.tree_nav import TreeNav
from ui.views.network_tab import NetworkTab
from ui.views.station_tab import StationTab
from ui.views.channel_tab import ChannelTab
from utils.signals import app_signals
from ui.views.catalog_dialog import CatalogDialog
from exporter.stationxml_builder import StationXMLExporter
from importer.stationxml_parser import StationXMLParser
from controllers.stationxml_export_controller import StationXMLWebExportController
from ui.views.math_deduplicator_dialog import MathDeduplicatorDialog
from ui.job_system import Job, JobRunner
from utils.yasmine_client import YasmineClient

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, app_state, net_ctrl, sta_ctrl, cha_ctrl, equ_ctrl):
        super().__init__()
        self.state = app_state
        self.net_ctrl = net_ctrl
        self.sta_ctrl = sta_ctrl
        self.cha_ctrl = cha_ctrl
        self.equ_ctrl = equ_ctrl
        self._export_web = StationXMLWebExportController(net_ctrl, sta_ctrl, cha_ctrl, equ_ctrl)
        self._import_progress_dialog = None
        self._export_progress_dialog = None
        
        self.setWindowTitle("StationXML Manager")
        self.resize(1200, 800)
        self._job_runner = JobRunner(self)
        self._bulk_progress = None
        self._bulk_yasmine_progress = None
        
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)
        
        # Left panel: tree and actions.
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Creation buttons.
        creation_layout = QHBoxLayout()
        self.add_net_btn = QPushButton("+ Network")
        self.add_sta_btn = QPushButton("+ Station")
        self.add_cha_btn = QPushButton("+ Channel")
        self.catalog_btn = QPushButton("⚙️ Equipment Catalog")
        
        # Tools menu.
        menubar = self.menuBar()
        tools_menu = menubar.addMenu("&Tools")

        bulk_enrich_action = QAction("🌍 Enrich Current Network Stations", self)
        bulk_enrich_action.setStatusTip("Download geographic and geological data for all stations in the selected network")
        bulk_enrich_action.triggered.connect(self._bulk_enrich_network_stations)
        tools_menu.addAction(bulk_enrich_action)
        
        dedup_action = QAction("🔍 Find and Merge Duplicates (Math-Match)", self)
        dedup_action.setStatusTip("Group identical instruments by physical/mathematical parameters")
        dedup_action.triggered.connect(self._open_math_deduplicator)
        tools_menu.addAction(dedup_action)
        
        nrl_update_action = QAction("🔄 Update Metadata from Local NRL", self)
        nrl_update_action.setStatusTip("Reload Poles/Zeros for all stations tagged 'NRL: '")
        nrl_update_action.triggered.connect(self._handle_global_nrl_update)
        tools_menu.addAction(nrl_update_action)
        
        bulk_sync_action = QAction("🚀 Sync Red Stations with Yasmine", self)
        bulk_sync_action.setStatusTip("Massively send all updated XML files to the Yasmine server")
        bulk_sync_action.triggered.connect(self._handle_bulk_yasmine_sync)
        tools_menu.addAction(bulk_sync_action)
        
        self.add_sta_btn.setEnabled(False)
        self.add_cha_btn.setEnabled(False)
        
        self.add_net_btn.clicked.connect(self._show_new_network_form)
        self.add_sta_btn.clicked.connect(self._show_new_station_form)
        self.add_cha_btn.clicked.connect(self._show_new_channel_form)
        self.catalog_btn.clicked.connect(self._show_catalog_dialog)
        
        creation_layout.addWidget(self.add_net_btn)
        creation_layout.addWidget(self.add_sta_btn)
        creation_layout.addWidget(self.add_cha_btn)
        creation_layout.addWidget(self.catalog_btn)

        # Import/Export buttons.
        io_layout = QHBoxLayout()
        self.import_btn = QPushButton("📥 Import XML")
        self.import_btn.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.import_btn.clicked.connect(self._import_xml)

        self.export_btn = QPushButton("💾 Export XML")
        self.export_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        self.export_btn.clicked.connect(self._export_xml)

        io_layout.addWidget(self.import_btn)
        io_layout.addWidget(self.export_btn)
        
        # Tree navigation bound to entity controllers.
        self.tree_nav = TreeNav(self.net_ctrl, self.sta_ctrl, self.cha_ctrl)
        
        left_layout.addLayout(creation_layout)
        left_layout.addLayout(io_layout)
        left_layout.addWidget(self.tree_nav)
        
        # Right panel: workspace tabs.
        self.workspace = QStackedWidget()
        
        # Workspace index 0: welcome.
        welcome_label = QLabel("Select an item on the left to begin.")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.workspace.addWidget(welcome_label)
        
        # Workspace index 1: network form.
        self.network_tab = NetworkTab(self.net_ctrl, self.equ_ctrl)
        self.workspace.addWidget(self.network_tab)
        
        # Workspace index 2: station form.
        self.station_tab = StationTab(self.sta_ctrl, self.equ_ctrl)
        self.workspace.addWidget(self.station_tab)
        
        # Workspace index 3: channel form.
        self.channel_tab = ChannelTab(self.cha_ctrl, self.equ_ctrl)
        self.workspace.addWidget(self.channel_tab)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(self.workspace)
        splitter.setSizes([300, 900])
        

    def _connect_signals(self):
        # Tree refresh
        app_signals.network_updated.connect(self.tree_nav.refresh_tree)
        app_signals.station_updated.connect(self.tree_nav.refresh_tree)
        app_signals.channel_updated.connect(self.tree_nav.refresh_tree)
        app_signals.equipment_updated.connect(self.channel_tab.refresh_catalog_combos)
        
        # Yasmine
        app_signals.sync_yasmine_requested.connect(self._sync_station_to_yasmine)
        
        # Item selection
        app_signals.network_selected.connect(self._on_network_selected)
        app_signals.station_selected.connect(self._on_station_selected)
        app_signals.channel_selected.connect(self._on_channel_selected)
        
    def _on_network_selected(self, network_id: int):
        self.state.current_network = network_id
        self.add_sta_btn.setEnabled(True)
        self.add_cha_btn.setEnabled(False)
        
        network = self.net_ctrl.get_network_by_id(network_id)
        if network:
            self.network_tab.load_network_data(network)
            self.workspace.setCurrentIndex(1)

    def _on_station_selected(self, station_id: int):
        self.state.current_station = station_id
        self.add_cha_btn.setEnabled(True)
        
        station = self.sta_ctrl.get_station_by_id(station_id)
        if station:
            self.state.current_network = station.network_id
            self.station_tab.load_station_data(station)
            self.workspace.setCurrentIndex(2)

    def _on_channel_selected(self, channel_id: int):
        channel = self.cha_ctrl.get_channel_by_id(channel_id)
        if channel:
            self.state.current_station = channel.station_id
            self.channel_tab.load_channel_data(channel)
            self.workspace.setCurrentIndex(3)

    def _show_new_network_form(self):
        self.network_tab.prepare_new_network()
        self.workspace.setCurrentIndex(1)

    def _show_new_station_form(self):
        if self.state.current_network:
            self.station_tab.prepare_new_station(self.state.current_network)
            self.workspace.setCurrentIndex(2)

    def _show_new_channel_form(self):
        if self.state.current_station:
            self.channel_tab.refresh_catalog_combos()
            self.channel_tab.prepare_new_channel(self.state.current_station)
            self.workspace.setCurrentIndex(3)
        else:
            QMessageBox.warning(self, "Warning", "Select a station first!")

    def _show_catalog_dialog(self):
        dialog = CatalogDialog(self.equ_ctrl, self)
        dialog.exec()
    
    def _import_xml(self):
        """Select and import StationXML / Dataless in a background thread with progress UI."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Seismic Metadata",
            "",
            "Seismic Metadata (*.xml *.dataless);;StationXML Files (*.xml);;Dataless SEED (*.dataless);;All Files (*)",
        )

        if not file_path:
            return

        if self._job_runner.is_running("stationxml_import"):
            QMessageBox.information(self, "Import", "An import is already in progress.")
            return

        self._import_progress_dialog = QProgressDialog(self)
        self._import_progress_dialog.setWindowTitle("StationXML import")
        self._import_progress_dialog.setLabelText("Preparing…")
        self._import_progress_dialog.setCancelButtonText("Cancel")
        self._import_progress_dialog.setRange(0, 0)
        self._import_progress_dialog.setMinimumDuration(0)
        self._import_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._import_progress_dialog.setAutoClose(False)
        self._import_progress_dialog.setAutoReset(False)
        self._import_progress_dialog.show()

        self.import_btn.setEnabled(False)
        self._import_progress_dialog.canceled.connect(
            lambda: self._job_runner.cancel_job("stationxml_import")
        )
        self._job_runner.run_job(
            Job(
                name="stationxml_import",
                function=self._job_stationxml_import,
                args=(file_path,),
            ),
            on_progress=self._on_stationxml_import_progress,
            on_finished=self._on_stationxml_import_finished,
            on_error=self._on_stationxml_import_error,
        )

    def _job_stationxml_import(self, file_path, report_progress=None, is_cancelled=None):
        parser = StationXMLParser(self.net_ctrl, self.sta_ctrl, self.cha_ctrl, self.equ_ctrl)

        def progress_cb(current: int, total: int, message: str) -> None:
            if report_progress:
                report_progress((current, total, message))

        cancel_cb = is_cancelled if is_cancelled is not None else lambda: False
        return parser.import_file(
            file_path,
            progress_callback=progress_cb,
            cancel_callback=cancel_cb,
        )

    def _on_stationxml_import_progress(self, payload):
        current, total, message = payload
        dlg = self._import_progress_dialog
        if not dlg:
            return
        dlg.setLabelText(message)
        if total <= 0:
            dlg.setRange(0, 0)
        else:
            dlg.setRange(0, total)
            dlg.setValue(min(current, total))
        pct = int(100 * current / total) if total else 0
        dlg.setWindowTitle(f"StationXML import — {pct}%")

    def _on_stationxml_import_finished(self, success):
        dlg = self._import_progress_dialog
        if dlg:
            dlg.close()
            self._import_progress_dialog = None
        self.import_btn.setEnabled(True)

        if success:
            QMessageBox.information(
                self,
                "Import completed",
                "XML file successfully imported into the database!",
            )
            app_signals.network_updated.emit()
            app_signals.equipment_updated.emit()
        else:
            QMessageBox.warning(
                self,
                "Import stopped",
                "The import did not complete successfully (cancelled, validation error, or parser error). "
                "Check the application log for details.",
            )

    def _on_stationxml_import_error(self, err: str):
        dlg = self._import_progress_dialog
        if dlg:
            dlg.close()
            self._import_progress_dialog = None
        self.import_btn.setEnabled(True)
        QMessageBox.critical(self, "Import error", f"An error occurred during import:\n{err}")
            
    def _export_xml(self):
        """Shows export options and saves StationXML (single file or ZIP per station)."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Export Options")
        layout = QVBoxLayout(dialog)

        grp_scope = QGroupBox("Scope")
        scope_layout = QVBoxLayout(grp_scope)
        radio_all = QRadioButton("Export entire database (all networks and stations)")
        radio_all.setChecked(True)
        radio_single = QRadioButton("Export a single station (choose below):")
        combo_stations = QComboBox()
        combo_stations.setEnabled(False)

        networks = self.net_ctrl.get_all_networks()
        for net in networks:
            stations = self.sta_ctrl.get_stations_by_network(net.id)
            for sta in stations:
                label = f"{net.code}.{sta.code} ({sta.site_name or 'No site name'})"
                combo_stations.addItem(label, sta.id)

        if combo_stations.count() == 0:
            combo_stations.addItem("No stations available")
            radio_single.setEnabled(False)

        def toggle_combo():
            combo_stations.setEnabled(radio_single.isChecked())

        radio_single.toggled.connect(toggle_combo)
        scope_layout.addWidget(radio_all)
        scope_layout.addWidget(radio_single)
        scope_layout.addWidget(combo_stations)
        layout.addWidget(grp_scope)

        grp_format = QGroupBox("Output format")
        fmt_layout = QVBoxLayout(grp_format)
        radio_fmt_single = QRadioButton("Single StationXML file (.xml) — classic inventory")
        radio_fmt_single.setChecked(True)
        radio_fmt_zip = QRadioButton("ZIP archive: one .xml per station ({station_code}.xml inside the archive)")
        fmt_layout.addWidget(radio_fmt_single)
        fmt_layout.addWidget(radio_fmt_zip)
        fmt_group = QButtonGroup(dialog)
        fmt_group.addButton(radio_fmt_single)
        fmt_group.addButton(radio_fmt_zip)
        layout.addWidget(grp_format)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if self._job_runner.is_running("stationxml_export"):
            QMessageBox.information(self, "Export", "An export is already in progress.")
            return

        def _all_station_ids() -> list:
            ids: list = []
            for net in self.net_ctrl.get_all_networks():
                for sta in self.sta_ctrl.get_stations_by_network(net.id):
                    ids.append(sta.id)
            return ids

        use_zip = radio_fmt_zip.isChecked()

        if use_zip:
            if radio_all.isChecked():
                station_ids = _all_station_ids()
            else:
                sid = combo_stations.currentData()
                if sid is None:
                    QMessageBox.warning(self, "Export", "No station selected for export.")
                    return
                station_ids = [int(sid)]
            if not station_ids:
                QMessageBox.warning(self, "Export", "No stations to export.")
                return
            default_name = "stations_export.zip"
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save ZIP archive",
                default_name,
                "ZIP Archives (*.zip);;All Files (*)",
            )
            if not file_path:
                return
            spec = {"mode": "zip", "path": file_path, "station_ids": station_ids, "zip": True}
        else:
            target_station_id = None
            if radio_single.isChecked() and combo_stations.count() > 0:
                target_station_id = combo_stations.currentData()
                if target_station_id is None:
                    QMessageBox.warning(self, "Export", "No station selected for export.")
                    return

            default_name = (
                f"inventory_{combo_stations.currentText().split(' ')[0]}.xml"
                if target_station_id
                else "inventory_full.xml"
            )
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save StationXML file",
                default_name,
                "StationXML Files (*.xml);;All Files (*)",
            )
            if not file_path:
                return
            spec = {
                "mode": "single",
                "path": file_path,
                "target_station_id": target_station_id,
                "zip": False,
            }

        self._export_progress_dialog = QProgressDialog(self)
        self._export_progress_dialog.setWindowTitle("StationXML export")
        self._export_progress_dialog.setLabelText("Starting…")
        self._export_progress_dialog.setCancelButtonText("Cancel")
        self._export_progress_dialog.setRange(0, 0)
        self._export_progress_dialog.setMinimumDuration(0)
        self._export_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress_dialog.setAutoClose(False)
        self._export_progress_dialog.setAutoReset(False)
        self._export_progress_dialog.show()

        self.export_btn.setEnabled(False)
        self._export_progress_dialog.canceled.connect(
            lambda: self._job_runner.cancel_job("stationxml_export")
        )
        self._job_runner.run_job(
            Job(
                name="stationxml_export",
                function=self._job_stationxml_export,
                args=(spec,),
            ),
            on_progress=self._on_stationxml_export_progress,
            on_finished=self._on_stationxml_export_finished,
            on_error=self._on_stationxml_export_error,
        )

    def _job_stationxml_export(self, spec, report_progress=None, is_cancelled=None):
        exporter = self._export_web.exporter
        exporter.validation_warnings.clear()

        def cb(cur: int, tot: int, msg: str) -> None:
            if report_progress:
                report_progress((cur, tot, msg))

        cancel = is_cancelled if is_cancelled is not None else (lambda: False)

        if spec["mode"] == "single":
            inv = exporter.build_inventory(
                spec.get("target_station_id"),
                output_path=spec["path"],
                validate=True,
                progress_callback=cb,
                cancel_callback=cancel,
            )
            if inv is None:
                return {"ok": False, "cancelled": True, "zip": False}
            return {"ok": True, "cancelled": False, "path": spec["path"], "zip": False}

        data = exporter.build_zip_bytes_for_station_ids(
            spec["station_ids"],
            progress_callback=cb,
            cancel_callback=cancel,
        )
        if data is None:
            return {"ok": False, "cancelled": True, "zip": True}
        with open(spec["path"], "wb") as fh:
            fh.write(data)
        return {"ok": True, "cancelled": False, "path": spec["path"], "zip": True}

    def _on_stationxml_export_progress(self, payload):
        current, total, message = payload
        dlg = self._export_progress_dialog
        if not dlg:
            return
        dlg.setLabelText(message)
        if total <= 0:
            dlg.setRange(0, 0)
        else:
            dlg.setRange(0, total)
            dlg.setValue(min(current, total))
        pct = int(100 * current / total) if total else 0
        dlg.setWindowTitle(f"StationXML export — {pct}%")

    def _on_stationxml_export_finished(self, result: dict):
        dlg = self._export_progress_dialog
        if dlg:
            dlg.close()
            self._export_progress_dialog = None
        self.export_btn.setEnabled(True)

        if not result.get("ok"):
            if result.get("cancelled"):
                return
            QMessageBox.warning(
                self,
                "Export",
                "The export did not complete successfully. Check the application log.",
            )
            return

        self._show_export_result_dialog(
            self._export_web.exporter,
            result["path"],
            is_zip=result.get("zip", False),
        )

    def _on_stationxml_export_error(self, err: str):
        dlg = self._export_progress_dialog
        if dlg:
            dlg.close()
            self._export_progress_dialog = None
        self.export_btn.setEnabled(True)
        QMessageBox.critical(self, "Export error", f"An error occurred during export:\n{err}")

    def _show_export_result_dialog(self, exporter: StationXMLExporter, file_path: str, *, is_zip: bool) -> None:
        """Shared success / warning dialog after export."""
        if exporter.validation_warnings:
            unrecognized = ", ".join(exporter.validation_warnings)
            kind = "ZIP archive" if is_zip else "StationXML file"
            msg = (
                f"{kind} generated in:\n{file_path}\n\n"
                "⚠️ WARNING:\nNon-standard units of measure detected:\n"
                f"[{unrecognized}]\n\n"
                "The file is valid, but the FDSN validator might flag errors on these units."
            )
            QMessageBox.warning(self, "Export Completed with Warnings", msg)
        else:
            QMessageBox.information(
                self,
                "Success",
                f"Export completed successfully with no FDSN unit warnings!\nSaved to:\n{file_path}",
            )

    def _bulk_enrich_network_stations(self):
        if self._job_runner.is_running("bulk_enrich"):
            QMessageBox.information(self, "In Progress", "Bulk enrich is already running.")
            return

        network_id = self.network_tab.current_network_id
        
        if not network_id:
            QMessageBox.warning(self, "Warning", "Please select a network first.")
            return

        stations = self.sta_ctrl.get_stations_by_network(network_id)
        if not stations:
            QMessageBox.information(self, "Info", "No stations found for this network.")
            return

        msg = f"About to enrich {len(stations)} stations. Operation takes approx {len(stations) * 1.2:.1f} seconds to respect API limits.\nProceed?"
        if QMessageBox.question(self, "Confirm", msg) != QMessageBox.StandardButton.Yes:
            return

        self._bulk_progress = QProgressDialog("Downloading geographic and geological data...", "Cancel", 0, len(stations), self)
        self._bulk_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._bulk_progress.setMinimumDuration(0)
        self._bulk_progress.setValue(0)
        self._bulk_progress.canceled.connect(lambda: self._job_runner.cancel_job("bulk_enrich"))
        self._job_runner.run_job(
            Job(name="bulk_enrich", function=self._job_bulk_enrich, args=(stations,)),
            on_progress=self._on_bulk_enrich_progress,
            on_finished=self._on_bulk_enrich_finished,
            on_error=self._on_bulk_enrich_failed,
        )

    def closeEvent(self, event):
        self._job_runner.shutdown(wait_ms=3000)
        super().closeEvent(event)

    def _job_bulk_enrich(self, stations, report_progress=None, is_cancelled=None):
        updates = []
        error_flags = {"DATA_NOT_FOUND", "API_ERROR", "NETWORK_ERROR"}

        for i, sta in enumerate(stations):
            if is_cancelled and is_cancelled():
                return {"updates": updates, "cancelled": True}

            start_time = time.time()
            changed_fields = {}

            geo_res = fetch_geology_from_coords(sta.latitude, sta.longitude)
            if geo_res and geo_res not in error_flags and sta.geology != geo_res:
                changed_fields["geology"] = geo_res

            osm_res = fetch_geography_from_coords(sta.latitude, sta.longitude)
            if isinstance(osm_res, dict):
                mapped_fields = {
                    "country": osm_res.get("country", ""),
                    "region": osm_res.get("region", ""),
                    "county": osm_res.get("county", ""),
                    "town": osm_res.get("town", ""),
                    "description": osm_res.get("description", ""),
                }
                for field_name, value in mapped_fields.items():
                    if getattr(sta, field_name, None) != value:
                        changed_fields[field_name] = value

            if changed_fields:
                updates.append((sta, changed_fields))

            elapsed = time.time() - start_time
            wait_time = max(0, 2.0 - elapsed)
            if wait_time > 0:
                time.sleep(wait_time)

            if report_progress:
                report_progress({"current": i + 1, "total": len(stations), "station_code": sta.code})

        return {"updates": updates, "cancelled": False}

    def _on_bulk_enrich_progress(self, payload):
        if self._bulk_progress:
            self._bulk_progress.setMaximum(payload["total"])
            self._bulk_progress.setValue(payload["current"])
            self._bulk_progress.setLabelText(f"Downloading data for station {payload['station_code']}...")

    def _on_bulk_enrich_finished(self, payload):
        updates = payload["updates"]
        cancelled = payload["cancelled"]
        updated_count = 0
        for station, changed_fields in updates:
            for field_name, value in changed_fields.items():
                setattr(station, field_name, value)
            self.sta_ctrl.save_station(station)
            updated_count += 1

        app_signals.station_updated.emit()

        if self._bulk_progress:
            self._bulk_progress.setValue(self._bulk_progress.maximum())
            self._bulk_progress.close()

        self._bulk_progress = None

        if cancelled:
            QMessageBox.information(self, "Cancelled", f"Operation cancelled. Updated {updated_count} stations.")
        else:
            QMessageBox.information(self, "Completed", f"Updated {updated_count} stations.")

    def _on_bulk_enrich_failed(self, error_message):
        logger.error(f"Bulk enrich failed: {error_message}")
        if self._bulk_progress:
            self._bulk_progress.close()
        self._bulk_progress = None
        QMessageBox.critical(self, "Error", f"Bulk enrich failed:\n{error_message}")
        
    def _open_math_deduplicator(self):
        dialog = MathDeduplicatorDialog(self.equ_ctrl, self)
        dialog.exec()
        
    def _sync_station_to_yasmine(self, station_id: int):
        """Generates XML in memory, checks Yasmine, and performs Check-and-Replace."""
        if self._job_runner.is_running("sync_station_to_yasmine"):
            QMessageBox.information(self, "In Progress", "A station sync is already running.")
            return

        self._job_runner.run_job(
            Job(
                name="sync_station_to_yasmine",
                function=self._job_sync_station_to_yasmine,
                args=(station_id,),
            ),
            on_finished=self._on_sync_station_to_yasmine_finished,
            on_error=self._on_sync_station_to_yasmine_failed,
        )

    def _job_sync_station_to_yasmine(self, station_id, report_progress=None, is_cancelled=None):
        station = self.sta_ctrl.get_station_by_id(station_id)
        if not station:
            return None
        network = self.net_ctrl.get_network_by_id(station.network_id)
        if not network:
            return None

        client = YasmineClient()
        exporter = StationXMLExporter(self.net_ctrl, self.sta_ctrl, self.cha_ctrl, self.equ_ctrl)
        inv = exporter.build_inventory(target_station_id=station_id)

        out_stream = io.BytesIO()
        inv.write(out_stream, format="STATIONXML", validate=True)
        xml_bytes = out_stream.getvalue()

        filename = f"{network.code}_{station.code}_sync.xml"
        existing_id = client.find_existing_xml(network.code, station.code)
        if existing_id:
            client.delete_xml(existing_id)
            logger.info(f"Old XML file {existing_id} removed from Yasmine.")

        new_yasmine_id = client.upload_xml(xml_bytes, filename)
        self.sta_ctrl.mark_as_synced(station, new_yasmine_id)
        return {"station_code": station.code, "new_yasmine_id": new_yasmine_id}

    def _on_sync_station_to_yasmine_finished(self, payload):
        if not payload:
            return
        QMessageBox.information(
            self, "Sync Successful",
            f"Station {payload['station_code']} successfully archived on Yasmine!\n(Yasmine ID: {payload['new_yasmine_id']})"
        )
        app_signals.station_updated.emit()

    def _on_sync_station_to_yasmine_failed(self, error_message):
        QMessageBox.critical(self, "Sync Error", f"Unable to communicate with Yasmine:\n{error_message}")
            
    def _handle_global_nrl_update(self):
        """Performs global refresh and shows result."""
        confirm = QMessageBox.question(
            self, "Confirm NRL Refresh",
            "Do you want to update all NRL sensors? Changes will also be sent to Yasmine.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                count = self.sta_ctrl.update_all_nrl_sensors()
                
                if count > 0:
                    app_signals.station_updated.emit()
                
                QApplication.restoreOverrideCursor()
                QMessageBox.information(self, "Completed", f"Update finished.\nStations to resend to Yasmine: {count}")
            except Exception as e:
                QApplication.restoreOverrideCursor()
                logger.error(f"Error during global refresh: {e}")
                QMessageBox.critical(self, "Error", f"An error occurred: {e}")
                
    def _handle_bulk_yasmine_sync(self):
        """Finds all red traffic light stations and bulk-sends them to Yasmine."""
        if self._job_runner.is_running("bulk_yasmine_sync"):
            QMessageBox.information(self, "In Progress", "Bulk Yasmine sync is already running.")
            return

        all_stations = self.sta_ctrl.dao.get_all()
        red_stations = []
        
        from core.services.station_service import calculate_station_hash
        for sta in all_stations:
            current_hash = calculate_station_hash(sta)
            if getattr(sta, 'sync_hash', None) != current_hash:
                red_stations.append(sta)
                
        if not red_stations:
            QMessageBox.information(self, "Sync", "Everything is aligned! 🟢")
            return
            
        confirm = QMessageBox.question(self, "Bulk Upload", f"Update {len(red_stations)} stations?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if confirm == QMessageBox.StandardButton.Yes:
            self._bulk_yasmine_progress = QProgressDialog("Synchronizing...", "Cancel", 0, len(red_stations), self)
            self._bulk_yasmine_progress.setValue(0)
            self._bulk_yasmine_progress.show()
            self._bulk_yasmine_progress.canceled.connect(lambda: self._job_runner.cancel_job("bulk_yasmine_sync"))
            self._job_runner.run_job(
                Job(
                    name="bulk_yasmine_sync",
                    function=self._job_bulk_yasmine_sync,
                    args=(red_stations,),
                ),
                on_progress=self._on_bulk_yasmine_sync_progress,
                on_finished=self._on_bulk_yasmine_sync_finished,
                on_error=self._on_bulk_yasmine_sync_failed,
            )

    def _job_bulk_yasmine_sync(self, red_stations, report_progress=None, is_cancelled=None):
        from core.services.station_service import calculate_station_hash

        client = YasmineClient()
        exporter = StationXMLExporter(self.net_ctrl, self.sta_ctrl, self.cha_ctrl, self.equ_ctrl)
        remote_list = client.get_all_imported_xmls()

        success_count = 0
        consecutive_errors = 0
        interrupted_by_server = False

        for i, station in enumerate(red_stations):
            if is_cancelled and is_cancelled():
                break

            network = self.net_ctrl.get_network_by_id(station.network_id)
            if report_progress:
                report_progress({"current": i, "total": len(red_stations), "station_code": station.code})

            try:
                inv = exporter.build_inventory(target_station_id=station.id)
                out_stream = io.BytesIO()
                inv.write(out_stream, format="STATIONXML", validate=True)
                xml_bytes = out_stream.getvalue()

                old_name_format = f"{network.code}_{station.code}_sync"
                existing_item = next((item for item in remote_list if isinstance(item, dict) and
                                     (item.get('name') == station.code or item.get('name') == old_name_format)), None)

                if existing_item:
                    existing_item = next((item for item in remote_list if isinstance(item, dict) and item.get('name') == station.code), None)
                    if existing_item:
                        old_id = existing_item.get('id')
                        client.delete_xml(old_id)

                new_id = client.upload_xml(xml_bytes, station.code)

                if new_id is not None:
                    current_hash = calculate_station_hash(station)
                    station.sync_hash = current_hash

                    self.sta_ctrl.dao.upsert_sync_state(station.id, new_id, current_hash)
                    self.sta_ctrl.mark_as_synced(station, new_id)

                    success_count += 1
                    consecutive_errors = 0
                else:
                    logger.error(f"No ID returned by Yasmine for {station.code}")
                    consecutive_errors += 1

            except Exception as e:
                logger.error(f"Failure on {station.code}: {e}")
                consecutive_errors += 1

            if consecutive_errors >= 3:
                interrupted_by_server = True
                break

        return {"success_count": success_count, "interrupted_by_server": interrupted_by_server}

    def _on_bulk_yasmine_sync_progress(self, payload):
        if self._bulk_yasmine_progress:
            self._bulk_yasmine_progress.setMaximum(payload["total"])
            self._bulk_yasmine_progress.setValue(payload["current"])
            self._bulk_yasmine_progress.setLabelText(f"Sending {payload['station_code']}...")

    def _on_bulk_yasmine_sync_finished(self, payload):
        success_count = payload["success_count"]
        interrupted_by_server = payload["interrupted_by_server"]
        app_signals.station_updated.emit()
        if self._bulk_yasmine_progress:
            self._bulk_yasmine_progress.setValue(self._bulk_yasmine_progress.maximum())
            self._bulk_yasmine_progress.close()
        if interrupted_by_server:
            QMessageBox.critical(self, "Critical Error", "Sync interrupted: Yasmine is not responding correctly.")
        QMessageBox.information(self, "Finished", f"Completed. Successes: {success_count}")
        self._bulk_yasmine_progress = None

    def _on_bulk_yasmine_sync_failed(self, error_message):
        logger.error(f"Bulk Yasmine sync failed: {error_message}")
        if self._bulk_yasmine_progress:
            self._bulk_yasmine_progress.close()
        QMessageBox.critical(self, "Error", f"Bulk sync failed:\n{error_message}")
        self._bulk_yasmine_progress = None