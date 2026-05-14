import json 
import logging

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout,
                             QLineEdit, QPushButton, QMessageBox,
                             QDateTimeEdit, QCheckBox, QHBoxLayout,
                             QDoubleSpinBox, QComboBox, QFrame, QTextEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox)
from PyQt6.QtCore import Qt, QDateTime

from utils.geology_client import fetch_geology_from_coords
from utils.geocoding_client import fetch_geography_from_coords

from core.models.base_models import Station
from utils.signals import app_signals
from core.validators.geo_validators import ValidationError

logger = logging.getLogger(__name__)

class StationTab(QWidget):
    """
    Screen for inserting and editing data of a Seismic Station.
    """
    def __init__(self, station_ctrl, equip_ctrl):
        super().__init__()
        self.sta_ctrl = station_ctrl
        self.eq_ctrl = equip_ctrl
        self.current_station_id = None
        self.parent_network_id = None
        
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout = QFormLayout()
        
        # 1. Base Text Fields
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("E.g. ROME")
        self.code_input.setMaxLength(10)
        
        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText("E.g. Rome - INGV Headquarters")
        
        # --- FDSN COMMENTS TABLE ---
        comm_group = QGroupBox("Comments (FDSN)")
        comm_lay = QVBoxLayout(comm_group)
        
        self.comm_table = QTableWidget(0, 5)
        self.comm_table.setHorizontalHeaderLabels(["Text", "Start (YYYY-MM-DD)", "End", "Subject", "Author (Name/Agency)"])
        self.comm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        comm_lay.addWidget(self.comm_table)
        
        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add Comment"); add_btn.clicked.connect(self._add_comment_row)
        rem_btn = QPushButton("- Remove Row"); rem_btn.clicked.connect(self._remove_comment_row)
        btns.addWidget(add_btn); btns.addWidget(rem_btn)
        comm_lay.addLayout(btns)

        self.operator_combo = QComboBox()

        self.restricted_combo = QComboBox()
        self.restricted_combo.addItems(["open", "closed", "partial"])

        self.vault_input = QComboBox()
        self.vault_input.setEditable(True)
        self.vault_input.addItems([
            "Vault", "Borehole", "Surface", "Cave",
            "Underwater", "Tunnel", "Building", "Bunker"
        ])

        self.geology_input = QComboBox()
        self.geology_input.setEditable(True)
        self.geology_input.addItems([
            "Rock", "Sedimentary Rock", "Metamorphic Rock", "Igneous Rock",
            "Alluvium", "Consolidated Sediment", "Unconsolidated Sediment",
            "Limestone", "Basalt", "Granite", "Clay", "Sand", "Gravel", "Soil"
        ])

        self.btn_fetch_geology = QPushButton("🌍 Get from Lat/Lon")
        self.btn_fetch_geology.setStyleSheet("background-color: #0288D1; color: white; font-weight: bold;")
        self.btn_fetch_geology.clicked.connect(self._auto_fill_geology)
        
        geo_layout = QHBoxLayout()
        geo_layout.setContentsMargins(0, 0, 0, 0)
        geo_layout.addWidget(self.geology_input)
        geo_layout.addWidget(self.btn_fetch_geology)

        # 2. Numeric Fields (Coordinates)
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setDecimals(5)
        self.lat_input.setRange(-90.0, 90.0)
        
        self.lon_input = QDoubleSpinBox()
        self.lon_input.setDecimals(5)
        self.lon_input.setRange(-180.0, 180.0)
        
        self.elev_input = QDoubleSpinBox()
        self.elev_input.setDecimals(1)
        self.elev_input.setRange(-15000.0, 10000.0)
        self.elev_input.setSuffix(" m")

        self.water_level_input = QDoubleSpinBox()
        self.water_level_input.setDecimals(1)
        self.water_level_input.setRange(-15000.0, 10000.0)
        self.water_level_input.setSuffix(" m")

        # Advanced geographic fields
        self.site_desc_input = QLineEdit()
        self.site_desc_input.setPlaceholderText("Street, district, or landmark")
        
        self.btn_fetch_geography = QPushButton("📍 Auto-fill Locations from Lat/Lon")
        self.btn_fetch_geography.setStyleSheet("background-color: #F57C00; color: white; font-weight: bold;")
        self.btn_fetch_geography.clicked.connect(self._auto_fill_geography)
        
        desc_layout = QHBoxLayout()
        desc_layout.setContentsMargins(0, 0, 0, 0)
        desc_layout.addWidget(self.site_desc_input)
        desc_layout.addWidget(self.btn_fetch_geography)

        self.town_input = QLineEdit()
        self.town_input.setPlaceholderText("E.g. Erice")
        self.county_input = QLineEdit()
        self.county_input.setPlaceholderText("E.g. Trapani")
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("E.g. Sicily")
        self.country_input = QLineEdit()
        self.country_input.setPlaceholderText("E.g. Italy")

        # 3. Dates
        start_layout = QHBoxLayout()
        self.start_check = QCheckBox("Set")
        self.start_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_input.setDisplayFormat("yyyy-MM-ddTHH:mm:ss")
        self.start_input.setCalendarPopup(True)
        self.start_input.setEnabled(False)
        self.start_check.toggled.connect(self.start_input.setEnabled)
        start_layout.addWidget(self.start_check)
        start_layout.addWidget(self.start_input)
        
        end_layout = QHBoxLayout()
        self.end_check = QCheckBox("Set")
        self.end_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_input.setDisplayFormat("yyyy-MM-ddTHH:mm:ss")
        self.end_input.setCalendarPopup(True)
        self.end_input.setEnabled(False)
        self.end_check.toggled.connect(self.end_input.setEnabled)
        end_layout.addWidget(self.end_check)
        end_layout.addWidget(self.end_input)

        # Form Layout Construction
        form_layout.addRow("Station Code (*):", self.code_input)
        form_layout.addRow("Site Name:", self.site_input)
        form_layout.addRow(comm_group)
        form_layout.addRow("Operator:", self.operator_combo)
        form_layout.addRow("Restricted Status:", self.restricted_combo)
        form_layout.addRow("Vault:", self.vault_input)
        
        form_layout.addRow("Latitude (°):", self.lat_input)
        form_layout.addRow("Longitude (°):", self.lon_input)
        form_layout.addRow("Elevation:", self.elev_input)
        form_layout.addRow("Water Level:", self.water_level_input)
        
        form_layout.addRow("Site Geology:", geo_layout)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        form_layout.addRow(line)
        
        # Geographic block
        form_layout.addRow("Extended Site Description:", desc_layout)
        form_layout.addRow("Town/City:", self.town_input)
        form_layout.addRow("County/Province:", self.county_input)
        form_layout.addRow("Region:", self.region_input)
        form_layout.addRow("Country:", self.country_input)
        
        form_layout.addRow(QFrame())
        form_layout.addRow("Start Date:", start_layout)
        form_layout.addRow("End Date:", end_layout)
        
        main_layout.addLayout(form_layout)
        
        # ==========================================
        # BUTTONS (Delete, Yasmine and Save)
        # ==========================================
        btn_layout = QHBoxLayout()
        
        self.delete_btn = QPushButton("Delete Station")
        self.delete_btn.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.delete_btn.setFixedWidth(130)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.hide()
        
        self.sync_yasmine_btn = QPushButton("☁️ Send to Yasmine")
        self.sync_yasmine_btn.setStyleSheet("background-color: #673AB7; color: white; font-weight: bold;")
        self.sync_yasmine_btn.setFixedWidth(150)
        self.sync_yasmine_btn.clicked.connect(self._on_sync_yasmine_clicked)
        self.sync_yasmine_btn.hide()
        
        self.save_btn = QPushButton("Save Station")
        self.save_btn.setFixedWidth(150)
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.sync_yasmine_btn)
        btn_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(btn_layout)
        
    def _add_comment_row(self):
        row = self.comm_table.rowCount()
        self.comm_table.insertRow(row)
        for i in range(5):
            self.comm_table.setItem(row, i, QTableWidgetItem(""))

    def _remove_comment_row(self):
        row = self.comm_table.currentRow()
        if row >= 0:
            self.comm_table.removeRow(row)

    def refresh_catalog_combos(self):
        self.operator_combo.clear()
        self.operator_combo.addItem("--- No Operator ---", None)
        for op in self.eq_ctrl.get_all_operators():
            label = op.agency
            if op.contact_name:
                label += f" ({op.contact_name})"
            
            self.operator_combo.addItem(label, op.id)

    def load_station_data(self, station: Station):
        """Fills the form with data from an existing station."""
        self.current_station_id = station.id
        self.parent_network_id = station.network_id
        
        self.code_input.setText(station.code)
        self.site_input.setText(station.site_name or "")
        
        self.comm_table.setRowCount(0)
        comments_json = station.comments
        
        if comments_json:
            try:
                comments = json.loads(comments_json)
                for c in comments:
                    row = self.comm_table.rowCount()
                    self.comm_table.insertRow(row)
                    self.comm_table.setItem(row, 0, QTableWidgetItem(c.get("value", "")))
                    self.comm_table.setItem(row, 1, QTableWidgetItem(c.get("begin_date", "")))
                    self.comm_table.setItem(row, 2, QTableWidgetItem(c.get("end_date", "")))
                    self.comm_table.setItem(row, 3, QTableWidgetItem(c.get("subject", "")))
                    
                    a_name = c.get('author_name', '')
                    a_ag = c.get('author_agency', '')
                    author_str = f"{a_name} ({a_ag})" if a_name or a_ag else ""
                    self.comm_table.setItem(row, 4, QTableWidgetItem(author_str.strip()))
            except json.JSONDecodeError:
                self._add_comment_row()
                self.comm_table.setItem(0, 0, QTableWidgetItem(str(comments_json)))
        
        val_v = station.vault or "Vault"
        idx_v = self.vault_input.findText(val_v)
        if idx_v >= 0: self.vault_input.setCurrentIndex(idx_v)
        else: self.vault_input.setEditText(val_v)

        val_g = station.geology or ""
        idx_g = self.geology_input.findText(val_g)
        if idx_g >= 0: self.geology_input.setCurrentIndex(idx_g)
        else: self.geology_input.setEditText(val_g)
        
        idx_res = self.restricted_combo.findText(station.restricted_status or "open")
        if idx_res >= 0: self.restricted_combo.setCurrentIndex(idx_res)
        
        self.lat_input.setValue(station.latitude if station.latitude is not None else 0.0)
        self.lon_input.setValue(station.longitude if station.longitude is not None else 0.0)
        self.elev_input.setValue(station.elevation if station.elevation is not None else 0.0)

        self.water_level_input.setValue(getattr(station, 'water_level', 0.0) or 0.0)
        self.site_desc_input.setText(getattr(station, 'description', "") or "")
        self.town_input.setText(getattr(station, 'town', "") or "")
        self.county_input.setText(getattr(station, 'county', "") or "")
        self.region_input.setText(getattr(station, 'region', "") or "")
        self.country_input.setText(getattr(station, 'country', "") or "")
        
        self.refresh_catalog_combos()
        if station.operator_id:
            idx = self.operator_combo.findData(station.operator_id)
            if idx >= 0: self.operator_combo.setCurrentIndex(idx)

        if station.start_date:
            dt = QDateTime.fromString(station.start_date, "yyyy-MM-ddTHH:mm:ss")
            if dt.isValid(): self.start_input.setDateTime(dt)
            self.start_check.setChecked(True)
        else:
            self.start_check.setChecked(False)

        if station.end_date:
            dt = QDateTime.fromString(station.end_date, "yyyy-MM-ddTHH:mm:ss")
            if dt.isValid(): self.end_input.setDateTime(dt)
            self.end_check.setChecked(True)
        else:
            self.end_check.setChecked(False)
            
        self.delete_btn.show()
        self.sync_yasmine_btn.show()

    def prepare_new_station(self, network_id: int):
        """Prepares an empty form to add a new station."""
        self.current_station_id = None
        self.parent_network_id = network_id
        
        self.code_input.clear()
        self.site_input.clear()
        
        self.comm_table.setRowCount(0)
        
        self.vault_input.clear()
        self.geology_input.clear()
        self.restricted_combo.setCurrentIndex(0)
        
        self.lat_input.setValue(0.0)
        self.lon_input.setValue(0.0)
        self.elev_input.setValue(0.0)
        
        self.water_level_input.setValue(0.0)
        self.site_desc_input.clear()
        self.town_input.clear()
        self.county_input.clear()
        self.region_input.clear()
        self.country_input.clear()
        
        self.refresh_catalog_combos()
        self.operator_combo.setCurrentIndex(0)

        self.start_input.setDateTime(QDateTime.currentDateTime())
        self.start_check.setChecked(False)
        self.end_input.setDateTime(QDateTime.currentDateTime())
        self.end_check.setChecked(False)
        
        self.delete_btn.hide()
        self.sync_yasmine_btn.hide()

    def _on_save_clicked(self):
        code = self.code_input.text().strip().upper()
        if not code:
            QMessageBox.warning(self, "Error", "Station Code is required!")
            return
        if self.parent_network_id is None:
            QMessageBox.warning(self, "Error", "Parent network not identified!")
            return

        start_str = self.start_input.dateTime().toString("yyyy-MM-ddTHH:mm:ss") if self.start_check.isChecked() else None
        end_str = self.end_input.dateTime().toString("yyyy-MM-ddTHH:mm:ss") if self.end_check.isChecked() else None
        
        comments_list = []
        for row in range(self.comm_table.rowCount()):
            val_item = self.comm_table.item(row, 0)
            val_text = val_item.text().strip() if val_item else ""
            if not val_text: continue

            bd = self.comm_table.item(row, 1); bd_text = bd.text().strip() if bd else ""
            ed = self.comm_table.item(row, 2); ed_text = ed.text().strip() if ed else ""
            sub = self.comm_table.item(row, 3); sub_text = sub.text().strip() if sub else ""
            auth = self.comm_table.item(row, 4); auth_text = auth.text().strip() if auth else ""

            author_name = auth_text
            author_agency = ""
            if "(" in auth_text and ")" in auth_text:
                parts = auth_text.split("(")
                author_name = parts[0].strip()
                author_agency = parts[1].replace(")", "").strip()

            comments_list.append({
                "value": val_text,
                "begin_date": bd_text,
                "end_date": ed_text,
                "subject": sub_text,
                "author_name": author_name,
                "author_agency": author_agency
            })

        comments_json = json.dumps(comments_list) if comments_list else None

        station_data = Station(
            id=self.current_station_id,
            network_id=self.parent_network_id,
            code=code,
            site_name=self.site_input.text().strip() or None,
            latitude=self.lat_input.value(),
            longitude=self.lon_input.value(),
            elevation=self.elev_input.value(),
            start_date=start_str,
            end_date=end_str,
            operator_id=self.operator_combo.currentData(),
            vault=self.vault_input.currentText().strip() or None,
            geology=self.geology_input.currentText().strip() or None,
            restricted_status=self.restricted_combo.currentText(),
            
            water_level=self.water_level_input.value(),
            description=self.site_desc_input.text().strip() or None,
            town=self.town_input.text().strip() or None,
            county=self.county_input.text().strip() or None,
            region=self.region_input.text().strip() or None,
            country=self.country_input.text().strip() or None,
            comments=comments_json
        )
        
        try:
            saved_sta = self.sta_ctrl.save_station(station_data)
            if saved_sta:
                self.current_station_id = saved_sta.id
                QMessageBox.information(self, "Success", f"Station {saved_sta.code} saved!")
                app_signals.station_updated.emit()
                self.delete_btn.show()
                self.sync_yasmine_btn.show()
        except ValidationError as ve:
            QMessageBox.warning(self, "Validation Error", str(ve))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unable to save the station:\n{str(e)}")

    def _on_delete_clicked(self):
        if not self.current_station_id: return
        
        msg = "Delete the station and all its connected channels?\nThis action is irreversible."
        reply = QMessageBox.question(self, "Confirm Deletion", msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if self.sta_ctrl.delete_station(self.current_station_id):
                    app_signals.station_updated.emit()
                    self.code_input.clear()
                    self.delete_btn.hide()
                    self.sync_yasmine_btn.hide()
                    QMessageBox.information(self, "Deleted", "Station successfully removed.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error during deletion: {e}")

    def _on_sync_yasmine_clicked(self):
        if not self.current_station_id:
            return
            
        station = self.sta_ctrl.get_station_by_id(self.current_station_id)
        if not station: return

        status_code, icon, _ = self.sta_ctrl.get_sync_status(station)
        
        if status_code == "SYNCED":
            QMessageBox.information(
                self, "Already Synchronized",
                "This station is already perfectly aligned with the official Yasmine archive.\nNo upload needed."
            )
            return
            
        elif status_code == "MODIFIED":
            reply = QMessageBox.question(
                self, "Overwrite Yasmine",
                "You have modified this station locally compared to what is archived on Yasmine.\nDo you want to overwrite the official inventory with this new data?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
                
        self.sync_yasmine_btn.setText("⏳ Sending...")
        self.sync_yasmine_btn.setEnabled(False)
        
        app_signals.sync_yasmine_requested.emit(self.current_station_id)
        
        self.sync_yasmine_btn.setText("☁️ Send to Yasmine")
        self.sync_yasmine_btn.setEnabled(True)
    
    def _auto_fill_geology(self):
        try:
            lat = self.lat_input.value()
            lon = self.lon_input.value()
        except Exception:
            QMessageBox.warning(self, "Warning", "Ensure Latitude and Longitude are valid.")
            return

        if lat == 0.0 and lon == 0.0:
            QMessageBox.warning(self, "Warning", "Coordinates are 0.0, impossible to determine geology.")
            return

        self.btn_fetch_geology.setText("⏳ Searching...")
        self.btn_fetch_geology.setEnabled(False)
        
        geology_result = fetch_geology_from_coords(lat, lon)
        
        self.btn_fetch_geology.setText("🌍 Get from Lat/Lon")
        self.btn_fetch_geology.setEnabled(True)

        if geology_result in ["API_ERROR", "NETWORK_ERROR"]:
            QMessageBox.critical(self, "Error", "Unable to contact geological server (Macrostrat). Check connection.")
        elif geology_result == "DATA_NOT_FOUND":
            QMessageBox.information(self, "No Data", "No geological info found for these coordinates.")
        elif geology_result == "":
            pass
        else:
            self.geology_input.setCurrentText(geology_result)
            self.geology_input.setStyleSheet("")
            
    def _auto_fill_geography(self):
        try:
            lat = self.lat_input.value()
            lon = self.lon_input.value()
        except Exception:
            QMessageBox.warning(self, "Warning", "Ensure Latitude and Longitude are valid.")
            return

        if lat == 0.0 and lon == 0.0:
            QMessageBox.warning(self, "Warning", "Invalid coordinates (0.0).")
            return

        self.btn_fetch_geography.setText("⏳ Geocoding...")
        self.btn_fetch_geography.setEnabled(False)
        
        geo_result = fetch_geography_from_coords(lat, lon)
        
        self.btn_fetch_geography.setText("📍 Auto-fill Locations from Lat/Lon")
        self.btn_fetch_geography.setEnabled(True)

        if geo_result in ["API_ERROR", "NETWORK_ERROR"]:
            QMessageBox.critical(self, "Error", "Unable to contact OpenStreetMap. Check connection.")
        elif geo_result == "DATA_NOT_FOUND":
            QMessageBox.information(self, "No Data", "Unable to resolve address for these coordinates.")
        elif geo_result:
            self.town_input.setText(geo_result.get("town", ""))
            self.county_input.setText(geo_result.get("county", ""))
            self.region_input.setText(geo_result.get("region", ""))
            self.country_input.setText(geo_result.get("country", ""))
            
            if not self.site_desc_input.text():
                self.site_desc_input.setText(geo_result.get("description", ""))