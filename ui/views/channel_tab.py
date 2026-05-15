import json
import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QMessageBox, QDoubleSpinBox, QComboBox,
                             QDateTimeEdit, QCheckBox, QHBoxLayout, QFrame, QTextEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox)
from PyQt6.QtCore import Qt, QDateTime
from core.models.base_models import Channel
from utils.qt_numeric_input import apply_c_double_validator, parse_float_text
from utils.signals import app_signals

logger = logging.getLogger(__name__)


def _nrl_status_icon(has_nrl_path: bool | None) -> str:
    """🟢 linked to NRL, 🔴 manual/no path, ⚪ no instrument selected."""
    if has_nrl_path is None:
        return "⚪"
    return "🟢" if has_nrl_path else "🔴"


class ChannelTab(QWidget):
    def __init__(self, channel_ctrl, equip_ctrl, station_ctrl=None):
        super().__init__()
        self.cha_ctrl = channel_ctrl
        self.eq_ctrl = equip_ctrl
        self.sta_ctrl = station_ctrl
        self.current_channel_id = None
        self.parent_station_id = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form = QFormLayout()

        # --- Identifiers & Types (FDSN) ---
        identifiers_group = QGroupBox("Identifiers & Types")
        identifiers_form = QFormLayout(identifiers_group)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("E.g. HHZ")
        self.loc_input = QLineEdit()
        self.loc_input.setPlaceholderText('Empty or "--" for default location')

        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(0, 10000)
        self.depth_input.setSuffix(" m")

        identifiers_form.addRow("Channel Code (e.g. HHZ):", self.code_input)
        identifiers_form.addRow("Location Code:", self.loc_input)
        identifiers_form.addRow("Depth:", self.depth_input)

        self.types_combo = QComboBox()
        self.types_combo.setEditable(True)
        self.types_combo.addItems([
            "CONTINUOUS,GEOPHYSICAL",
            "TRIGGERED,GEOPHYSICAL",
            "SYNTHETIC,GEOPHYSICAL",
            "CONTINUOUS,HEALTH",
            "TRIGGERED,HEALTH",
            "SYNTHETIC,HEALTH",
            "CONTINUOUS,WEATHER",
            "TRIGGERED,WEATHER",
            "SYNTHETIC,WEATHER",
            "CONTINUOUS,FLAG",
            "TRIGGERED,FLAG",
            "SYNTHETIC,FLAG"
        ])
        self.types_combo.setCurrentIndex(0)

        self.restricted_combo = QComboBox()
        self.restricted_combo.addItems(["open", "closed", "partial"])
        self.restricted_combo.setCurrentIndex(0)

        identifiers_form.addRow("Channel Types (FDSN):", self.types_combo)
        identifiers_form.addRow("Restricted Status:", self.restricted_combo)
        comm_group = QGroupBox("Channel Comments (FDSN)")
        comm_lay = QVBoxLayout(comm_group)
        
        self.comm_table = QTableWidget(0, 5)
        self.comm_table.setHorizontalHeaderLabels(["Text", "Start (YYYY-MM-DD)", "End", "Subject", "Author (Name/Agency)"])
        self.comm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        comm_lay.addWidget(self.comm_table)
        
        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add Comment")
        add_btn.clicked.connect(self._add_comment_row)
        rem_btn = QPushButton("- Remove Row")
        rem_btn.clicked.connect(self._remove_comment_row)
        btns.addWidget(add_btn)
        btns.addWidget(rem_btn)
        comm_lay.addLayout(btns)

        # Technical Parameters
        self.sample_rate = QDoubleSpinBox()
        self.sample_rate.setRange(0, 5000)
        self.sample_rate.setValue(100.0)
        self.sample_rate.setSuffix(" Hz")

        self.clock_drift = QDoubleSpinBox()
        self.clock_drift.setRange(-1.0, 1.0)
        self.clock_drift.setDecimals(6)
        self.clock_drift.setSingleStep(0.0001)
        self.clock_drift.setSuffix(" s/sample")
        self.clock_drift.setToolTip("Clock drift (often 0.0 or 0.0001)")

        self.cal_units_combo = QComboBox()
        self.cal_units_combo.setEditable(True)
        self.cal_units_combo.addItems(["", "V", "A", "COUNTS", "m/s", "m/s**2"])
        self.cal_units_combo.setToolTip("Units of measure used for calibration (optional)")

        # Orientation
        self.azimuth = QDoubleSpinBox()
        self.azimuth.setRange(0, 360)
        self.dip = QDoubleSpinBox()
        self.dip.setRange(-90, 90)

        # Total sensitivity + recalculate (same row as web: field + action button)
        self.overall_sens_input = QLineEdit()
        self.overall_sens_input.setPlaceholderText("Leave empty for automatic calculation")
        apply_c_double_validator(self.overall_sens_input)
        self.calc_sens_btn = QPushButton("Recalculate Total Sensitivity")
        self.calc_sens_btn.setStyleSheet("background-color: #0277BD; color: white; font-weight: bold;")
        self.calc_sens_btn.clicked.connect(self._on_calc_sensitivity_clicked)
        sens_layout = QHBoxLayout()
        sens_layout.setContentsMargins(0, 0, 0, 0)
        sens_layout.addWidget(self.overall_sens_input, 1)
        sens_layout.addWidget(self.calc_sens_btn)
        sens_row = QWidget()
        sens_row.setLayout(sens_layout)

        # Dates
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

        # Catalogs and Serial Inputs
        self.sensor_combo = QComboBox()
        self.sensor_serial_input = QLineEdit()
        self.sensor_serial_input.setPlaceholderText("E.g. 1234")

        self.datalogger_combo = QComboBox()
        self.datalogger_serial_input = QLineEdit()
        self.datalogger_serial_input.setPlaceholderText("E.g. 5678")

        self.update_nrl_btn = QPushButton("Update NRL (this station)")
        self.update_nrl_btn.setToolTip(
            "Re-apply local NRL metadata for sensors/dataloggers used by this station."
        )
        self.update_nrl_btn.clicked.connect(self._on_update_nrl_station_clicked)

        # Pre-Amplifier Section
        self.preamp_combo = QComboBox()
        self.preamp_sn_input = QLineEdit()
        self.preamp_sn_input.setPlaceholderText("E.g. SN-999")
        self.preamp_gain_input = QDoubleSpinBox()
        self.preamp_gain_input.setRange(0.0001, 1000000.0)
        self.preamp_gain_input.setValue(1.0)
        
        # --- FORM COMPOSITION ---
        form.addRow(identifiers_group)
        form.addRow(comm_group)
        
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(line1)

        form.addRow("Sample Rate:", self.sample_rate)
        form.addRow("Clock Drift:", self.clock_drift)
        form.addRow("Azimuth / Dip:", self._create_geo_layout())
        
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(line2)

        form.addRow("Sensor:", self.sensor_combo)
        form.addRow("Sensor S/N:", self.sensor_serial_input)
        form.addRow("Datalogger:", self.datalogger_combo)
        form.addRow("Datalogger S/N:", self.datalogger_serial_input)
        form.addRow("", self.update_nrl_btn)

        form.addRow("Pre-Amp Model:", self.preamp_combo)
        form.addRow("Pre-Amp S/N:", self.preamp_sn_input)
        form.addRow("Pre-Amp Gain:", self.preamp_gain_input)

        form.addRow("Total Sensitivity:", sens_row)
        form.addRow("Calibration Units:", self.cal_units_combo)
        
        form.addRow("Start Date (Epoch):", start_layout)
        form.addRow("End Date (Epoch):", end_layout)

        layout.addLayout(form)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.delete_btn = QPushButton("Delete Channel")
        self.delete_btn.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.delete_btn.setFixedWidth(130)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.hide()

        self.clone_btn = QPushButton("Clone Epoch")
        self.clone_btn.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.clone_btn.setFixedWidth(130)
        self.clone_btn.clicked.connect(self._on_clone_clicked)
        self.clone_btn.hide()
        
        self.save_btn = QPushButton("Save Channel")
        self.save_btn.setFixedWidth(150)
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.clone_btn)
        btn_layout.addWidget(self.save_btn)
        
        layout.addLayout(btn_layout)

    def _on_update_nrl_station_clicked(self):
        if not self.parent_station_id:
            QMessageBox.warning(self, "Warning", "Open a channel belonging to a station first.")
            return
        if not self.sta_ctrl:
            QMessageBox.warning(self, "Warning", "Station controller not available.")
            return

        from PyQt6.QtWidgets import QApplication

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            changed = self.sta_ctrl.update_nrl_for_station(self.parent_station_id)
            app_signals.equipment_updated.emit()
            app_signals.station_updated.emit()
            self.refresh_catalog_combos()
            if changed:
                QMessageBox.information(
                    self,
                    "NRL Updated",
                    "Instruments for this station were refreshed from NRL.\n"
                    "The station sync indicator is now red until you send to Yasmine.",
                )
            else:
                QMessageBox.information(
                    self, "NRL", "No catalog changes were required for this station."
                )
        except Exception as e:
            logger.error("Station NRL refresh failed: %s", e)
            QMessageBox.critical(self, "Error", f"NRL update failed:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def _create_geo_layout(self):
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addWidget(self.azimuth)
        h_layout.addWidget(self.dip)
        container = QWidget()
        container.setLayout(h_layout)
        return container

    def _add_comment_row(self):
        row = self.comm_table.rowCount()
        self.comm_table.insertRow(row)
        for i in range(5):
            self.comm_table.setItem(row, i, QTableWidgetItem(""))

    def _remove_comment_row(self):
        row = self.comm_table.currentRow()
        if row >= 0:
            self.comm_table.removeRow(row)

    def _load_comments(self, comments_json):
        self.comm_table.setRowCount(0)
        if not comments_json: return
        
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
            row = self.comm_table.rowCount()
            self.comm_table.insertRow(row)
            self.comm_table.setItem(row, 0, QTableWidgetItem(str(comments_json)))

    @staticmethod
    def _sensor_combo_label(sensor) -> str:
        icon = _nrl_status_icon(bool(getattr(sensor, "nrl_path", None)))
        return f"{icon} {sensor.manufacturer} {sensor.model}"

    @staticmethod
    def _datalogger_combo_label(datalogger) -> str:
        icon = _nrl_status_icon(bool(getattr(datalogger, "nrl_path", None)))
        return f"{icon} {datalogger.manufacturer} {datalogger.model}"

    def populate_sensor_combo(self, selected_id=None) -> None:
        if selected_id is None:
            selected_id = self.sensor_combo.currentData()
        self.sensor_combo.clear()
        self.sensor_combo.addItem(f"{_nrl_status_icon(None)} --- No Sensor ---", None)
        for sensor in self.eq_ctrl.get_all_sensors():
            self.sensor_combo.addItem(self._sensor_combo_label(sensor), sensor.id)
        if selected_id is not None:
            idx = self.sensor_combo.findData(selected_id)
            if idx >= 0:
                self.sensor_combo.setCurrentIndex(idx)

    def populate_datalogger_combo(self, selected_id=None) -> None:
        if selected_id is None:
            selected_id = self.datalogger_combo.currentData()
        self.datalogger_combo.clear()
        self.datalogger_combo.addItem(
            f"{_nrl_status_icon(None)} --- No Datalogger ---", None
        )
        for datalogger in self.eq_ctrl.get_all_dataloggers():
            self.datalogger_combo.addItem(
                self._datalogger_combo_label(datalogger), datalogger.id
            )
        if selected_id is not None:
            idx = self.datalogger_combo.findData(selected_id)
            if idx >= 0:
                self.datalogger_combo.setCurrentIndex(idx)

    def refresh_catalog_combos(self):
        sensor_id = self.sensor_combo.currentData()
        datalogger_id = self.datalogger_combo.currentData()
        preamp_id = self.preamp_combo.currentData()

        self.sensor_combo.blockSignals(True)
        self.datalogger_combo.blockSignals(True)
        self.preamp_combo.blockSignals(True)

        self.populate_sensor_combo(sensor_id)
        self.populate_datalogger_combo(datalogger_id)

        self.preamp_combo.clear()
        self.preamp_combo.addItem("--- No Pre-Amp ---", None)
        for p in self.eq_ctrl.get_all_preamplifiers():
            p_id = p.id if hasattr(p, 'id') else p.get('id')
            p_mfg = p.manufacturer if hasattr(p, 'manufacturer') else p.get('manufacturer')
            p_mod = p.model if hasattr(p, 'model') else p.get('model')
            self.preamp_combo.addItem(f"{p_mfg} {p_mod}", p_id)

        if sensor_id is not None:
            idx = self.sensor_combo.findData(sensor_id)
            if idx >= 0:
                self.sensor_combo.setCurrentIndex(idx)
        if datalogger_id is not None:
            idx = self.datalogger_combo.findData(datalogger_id)
            if idx >= 0:
                self.datalogger_combo.setCurrentIndex(idx)
        if preamp_id is not None:
            idx = self.preamp_combo.findData(preamp_id)
            if idx >= 0:
                self.preamp_combo.setCurrentIndex(idx)

        self.sensor_combo.blockSignals(False)
        self.datalogger_combo.blockSignals(False)
        self.preamp_combo.blockSignals(False)

    def prepare_new_channel(self, station_id: int):
        self.current_channel_id = None
        self.parent_station_id = station_id
        self.code_input.clear()
        self.loc_input.clear()
        self.comm_table.setRowCount(0)
        self.types_combo.setCurrentIndex(0)
        self.restricted_combo.setCurrentIndex(0)
        self.depth_input.setValue(0.0)
        self.sample_rate.setValue(100.0)
        self.azimuth.setValue(0.0)
        self.dip.setValue(-90.0)
        self.overall_sens_input.clear()
        self.clock_drift.setValue(0.0)
        self.cal_units_combo.setCurrentIndex(0)
        self.preamp_gain_input.setValue(1.0)
        self.preamp_sn_input.clear()
        self.sensor_serial_input.clear()
        self.datalogger_serial_input.clear()
        self.start_check.setChecked(False)
        self.end_check.setChecked(False)
        self.sensor_combo.setCurrentIndex(0)
        self.datalogger_combo.setCurrentIndex(0)
        self.delete_btn.hide()
        self.clone_btn.hide()

    def load_channel_data(self, channel: Channel):
        self.current_channel_id = channel.id
        self.parent_station_id = channel.station_id
        self.code_input.setText(channel.code)
        self.loc_input.setText(channel.location_code or "")
        
        self._load_comments(channel.comments)
        
        val_types = getattr(channel, 'types', "CONTINUOUS,GEOPHYSICAL") or "CONTINUOUS,GEOPHYSICAL"
        idx_types = self.types_combo.findText(val_types)
        if idx_types >= 0: self.types_combo.setCurrentIndex(idx_types)
        else: self.types_combo.setEditText(val_types)

        rs = getattr(channel, "restricted_status", None) or "open"
        idx_rs = self.restricted_combo.findText(rs)
        if idx_rs >= 0:
            self.restricted_combo.setCurrentIndex(idx_rs)
        else:
            self.restricted_combo.setCurrentIndex(0)

        self.depth_input.setValue(channel.depth if channel.depth is not None else 0.0)
        self.sample_rate.setValue(channel.sample_rate if channel.sample_rate is not None else 0.0)
        self.azimuth.setValue(channel.azimuth if channel.azimuth is not None else 0.0)
        self.dip.setValue(channel.dip if channel.dip is not None else 0.0)

        self.sensor_serial_input.setText(channel.sensor_serial_number or "")
        self.datalogger_serial_input.setText(channel.datalogger_serial_number or "")
        
        sens_val = getattr(channel, 'overall_sensitivity', None)
        self.overall_sens_input.setText(str(sens_val) if sens_val else "")

        self.clock_drift.setValue(getattr(channel, 'clock_drift', 0.0) or 0.0)
        cal_val = getattr(channel, 'calibration_units', "") or ""
        idx_cal = self.cal_units_combo.findText(cal_val)
        if idx_cal >= 0: self.cal_units_combo.setCurrentIndex(idx_cal)
        else: self.cal_units_combo.setEditText(cal_val)

        self.preamp_sn_input.setText(channel.pre_amplifier_serial_number or "")
        self.preamp_gain_input.setValue(channel.pre_amplifier_gain if channel.pre_amplifier_gain is not None else 1.0)

        self.refresh_catalog_combos()

        if hasattr(channel, 'pre_amplifier_id') and channel.pre_amplifier_id:
            idx = self.preamp_combo.findData(channel.pre_amplifier_id)
            if idx >= 0: self.preamp_combo.setCurrentIndex(idx)
            
        if channel.sensor_id:
            idx = self.sensor_combo.findData(channel.sensor_id)
            if idx >= 0: self.sensor_combo.setCurrentIndex(idx)
            
        if channel.datalogger_id:
            idx = self.datalogger_combo.findData(channel.datalogger_id)
            if idx >= 0: self.datalogger_combo.setCurrentIndex(idx)

        if channel.start_date:
            self.start_check.setChecked(True)
            self.start_input.setDateTime(QDateTime.fromString(channel.start_date, "yyyy-MM-ddTHH:mm:ss"))
        else: self.start_check.setChecked(False)

        if channel.end_date:
            self.end_check.setChecked(True)
            self.end_input.setDateTime(QDateTime.fromString(channel.end_date, "yyyy-MM-ddTHH:mm:ss"))
        else: self.end_check.setChecked(False)
        
        self.delete_btn.show()
        self.clone_btn.show()

    def _on_clone_clicked(self):
        self.current_channel_id = None
        self.end_check.setChecked(False)
        self.start_check.setChecked(True)
        self.start_input.setDateTime(QDateTime.currentDateTime())
        self.delete_btn.hide()
        self.clone_btn.hide()
        QMessageBox.information(self, "Cloned", "Data copied. Choose Start Date and click Save!")

    def _on_save_clicked(self):
        code = self.code_input.text().strip().upper()
        if not code:
            QMessageBox.warning(self, "Error", "Channel code is required!")
            return
        if self.parent_station_id is None:
            QMessageBox.critical(self, "Error", "Missing Station ID!")
            return
            
        raw_loc = self.loc_input.text().strip()
        final_loc = "" if (raw_loc == "--" or raw_loc == "") else raw_loc

        sens_text = self.overall_sens_input.text().strip()
        final_sens = None
        if sens_text:
            final_sens, sens_err = parse_float_text(
                sens_text, "Total Sensitivity", allow_empty=False
            )
            if sens_err:
                QMessageBox.warning(self, "Error", sens_err)
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

        new_cha = Channel(
            id=self.current_channel_id,
            station_id=self.parent_station_id,
            code=code,
            location_code=final_loc,
            depth=self.depth_input.value(),
            sample_rate=self.sample_rate.value(),
            azimuth=self.azimuth.value(),
            dip=self.dip.value(),
            start_date=start_str,
            end_date=end_str,
            sensor_id=self.sensor_combo.currentData(),
            datalogger_id=self.datalogger_combo.currentData(),
            overall_sensitivity=final_sens,
            sensor_serial_number=self.sensor_serial_input.text().strip() or None,
            datalogger_serial_number=self.datalogger_serial_input.text().strip() or None,
            types=self.types_combo.currentText().strip(),
            restricted_status=self.restricted_combo.currentText(),
            clock_drift=self.clock_drift.value(),
            calibration_units=self.cal_units_combo.currentText().strip() or None,
            pre_amplifier_id=self.preamp_combo.currentData(),
            pre_amplifier_serial_number=self.preamp_sn_input.text().strip() or None,
            pre_amplifier_gain=self.preamp_gain_input.value(),
            comments=comments_json
        )
        
        try:
            if self.cha_ctrl.save_channel(new_cha):
                QMessageBox.information(self, "Success", f"Channel {code} saved!")
                app_signals.channel_updated.emit()
                self.delete_btn.show()
                self.clone_btn.show()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save error: {str(e)}")

    def _on_delete_clicked(self):
        if not self.current_channel_id: return
        msg = "Delete this channel?"
        reply = QMessageBox.question(self, "Confirm", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if self.cha_ctrl.delete_channel(self.current_channel_id):
                    app_signals.channel_updated.emit()
                    self.code_input.clear()
                    self.delete_btn.hide()
                    self.clone_btn.hide()
                    QMessageBox.information(self, "Deleted", "Channel removed.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error: {e}")
                
    def _on_calc_sensitivity_clicked(self):
        s_id = self.sensor_combo.currentData()
        p_id = self.preamp_combo.currentData()
        d_id = self.datalogger_combo.currentData()
        
        if not s_id:
            QMessageBox.warning(self, "Warning", "Select at least one Sensor to calculate sensitivity.")
            return
            
        temp_cha = Channel(
            sensor_id=s_id,
            pre_amplifier_id=p_id,
            datalogger_id=d_id,
            pre_amplifier_gain=self.preamp_gain_input.value(),
        )

        try:
            calc_val = self.cha_ctrl.calculate_total_sensitivity(temp_cha)

            if calc_val is not None and calc_val > 0:
                self.overall_sens_input.setText(f"{calc_val:.6e}")
                QMessageBox.information(
                    self,
                    "Calculation Successful",
                    f"Total sensitivity: {calc_val:.6e}\n\n"
                    "Product of sensor sensitivity and all stage gains "
                    "(pre-amp stages, channel pre-amp gain, datalogger).",
                )
            else:
                QMessageBox.warning(self, "Calculation Error",
                    "Unable to calculate. Verify that the selected instruments "
                    "have their Gain and Sensitivity values correctly set in the catalog.")
        except Exception as e:
            logger.error(f"Error during manual sensitivity calculation: {e}")
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")