import logging
import json
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
                             QSplitter, QMessageBox, QLabel, QDoubleSpinBox, QListWidget,
                             QListWidgetItem, QGroupBox, QInputDialog, QTextEdit, QComboBox)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.models.base_models import Sensor
from ui.views.nrl_dialog import NRLBrowserDialog
from utils.qt_numeric_input import parse_pz_table_pairs
from utils.signals import app_signals

from utils.arol_client import AROLClient
from ui.views.arol_dialog import AROLBrowserDialog

logger = logging.getLogger(__name__)

class SensorCatalogTab(QWidget):
    def __init__(self, equip_ctrl):
        super().__init__()
        self.eq_ctrl = equip_ctrl
        self.current_sensor = None
        self._selected_sensor_id = None
        self._setup_ui()
        self.refresh_list()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- LEFT: List ---
        left_widget = QWidget(); left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("<b>Sensors in Catalog</b>"))
        self.model_list = QListWidget();
        self.model_list.itemClicked.connect(self._load_selected_sensor)
        self.model_list.itemDoubleClicked.connect(self._on_nrl_clicked)
        left_layout.addWidget(self.model_list)
        
        btns = QHBoxLayout()
        self.new_btn = QPushButton("➕ New"); self.new_btn.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.new_btn.clicked.connect(self._prepare_new_model)
        
        self.nrl_btn = QPushButton("🌐 NRL");
        self.nrl_btn.clicked.connect(self._on_nrl_clicked)
        self.arol_btn = QPushButton("🌐 AROL");self.arol_btn.clicked.connect(self._on_import_arol_clicked)
        
        btns.addWidget(self.new_btn)
        btns.addWidget(self.nrl_btn)
        btns.addWidget(self.arol_btn)
        
        left_layout.addLayout(btns)
        self.splitter.addWidget(left_widget)
        
        # --- CENTER: Editor ---
        editor_widget = QWidget(); editor_layout = QVBoxLayout(editor_widget)
        info_group = QGroupBox("Technical Data")
        info_form = QFormLayout(info_group)
        
        self.mfg_input = QLineEdit()
        self.model_input = QLineEdit()
        self.type_input = QComboBox(); self.type_input.addItems(["SENSOR", "VBB", "BB", "SP", "SM"]); self.type_input.setEditable(True)
        self.desc_input = QTextEdit(); self.desc_input.setMaximumHeight(50)
        self.sens_input = QDoubleSpinBox(); self.sens_input.setRange(0, 1e15); self.sens_input.setDecimals(2)
        self.freq_input = QDoubleSpinBox(); self.freq_input.setRange(0, 10000); self.freq_input.setDecimals(4)
        
        units_layout = QHBoxLayout()
        self.in_units = QLineEdit("m/s"); self.out_units = QLineEdit("V")
        units_layout.addWidget(self.in_units); units_layout.addWidget(QLabel("→")); units_layout.addWidget(self.out_units)
        self.pz_type = QComboBox(); self.pz_type.addItems(["LAPLACE (RADIANS/SECOND)", "LAPLACE (HERTZ)"])
        
        info_form.addRow("Manufacturer:", self.mfg_input)
        info_form.addRow("Model:", self.model_input)
        info_form.addRow("Type:", self.type_input)
        info_form.addRow("Sensitivity:", self.sens_input)
        info_form.addRow("Frequency:", self.freq_input)
        info_form.addRow("Units In/Out:", units_layout)
        info_form.addRow("PZ Type:", self.pz_type)
        info_form.addRow("Description:", self.desc_input)
        
        editor_layout.addWidget(info_group)

        pz_group = QGroupBox("Poles and Zeros")
        pz_layout = QHBoxLayout(pz_group)
        z_lay = QVBoxLayout(); z_lay.addWidget(QLabel("<b>Zeros</b>")); self.zt = self._create_pz_table(); z_lay.addWidget(self.zt)
        p_lay = QVBoxLayout(); p_lay.addWidget(QLabel("<b>Poles</b>")); self.pt = self._create_pz_table(); p_lay.addWidget(self.pt)
        pz_layout.addLayout(z_lay); pz_layout.addLayout(p_lay); editor_layout.addWidget(pz_group)
        
        pz_btns = QHBoxLayout()
        az = QPushButton("+ Zero"); az.clicked.connect(lambda: self._add_row(self.zt))
        ap = QPushButton("+ Pole"); ap.clicked.connect(lambda: self._add_row(self.pt))
        dp = QPushButton("- Remove Row"); dp.clicked.connect(self._remove_selected_row)
        pz_btns.addWidget(az); pz_btns.addWidget(ap); pz_btns.addWidget(dp); editor_layout.addLayout(pz_btns)

        self.save_btn = QPushButton("💾 SAVE TO CATALOG"); self.save_btn.setStyleSheet("background-color: #2E7D32; color: white; height: 35px; font-weight: bold;")
        self.save_btn.clicked.connect(self._on_save_clicked); editor_layout.addWidget(self.save_btn)
        
        danger_layout = QHBoxLayout()
        self.clone_btn = QPushButton("👯 Clone"); self.clone_btn.setStyleSheet("background-color: #8E24AA; color: white;"); self.clone_btn.clicked.connect(self._on_clone_clicked); self.clone_btn.setEnabled(False)
        self.replace_btn = QPushButton("🔄 Replace"); self.replace_btn.setStyleSheet("background-color: #F57C00; color: white;"); self.replace_btn.clicked.connect(self._on_replace_clicked); self.replace_btn.setEnabled(False)
        self.delete_btn = QPushButton("🗑️ Delete"); self.delete_btn.setStyleSheet("background-color: #C62828; color: white;"); self.delete_btn.clicked.connect(self._on_delete_clicked); self.delete_btn.setEnabled(False)
        danger_layout.addWidget(self.clone_btn); danger_layout.addWidget(self.replace_btn); danger_layout.addWidget(self.delete_btn)
        editor_layout.addLayout(danger_layout); self.splitter.addWidget(editor_widget)

        # --- RIGHT: Plot ---
        plot_cont = QWidget(); plot_lay = QVBoxLayout(plot_cont)
        plot_lay.addWidget(QLabel("<b>Bode Response</b>"))
        self.canvas = FigureCanvas(Figure(figsize=(5, 4)))
        self.ax_mag = self.canvas.figure.add_subplot(211); self.ax_phase = self.canvas.figure.add_subplot(212)
        plot_lay.addWidget(self.canvas); self.splitter.addWidget(plot_cont)
        
        self.splitter.setSizes([200, 500, 400]); layout.addWidget(self.splitter)

    def _create_pz_table(self):
        t = QTableWidget(0, 2); t.setHorizontalHeaderLabels(["Real", "Imaginary"])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); return t

    def _add_row(self, t, r=0.0, i=0.0):
        row = t.rowCount(); t.insertRow(row); t.setItem(row,0,QTableWidgetItem(str(r))); t.setItem(row,1,QTableWidgetItem(str(i)))

    def _remove_selected_row(self):
        for t in [self.zt, self.pt]:
            if t.hasFocus() and t.currentRow() >= 0: t.removeRow(t.currentRow())

    def _prepare_new_model(self):
        self.current_sensor = Sensor(manufacturer="", model="")
        self._selected_sensor_id = None
        self.mfg_input.clear(); self.model_input.clear(); self.desc_input.clear()
        self.sens_input.setValue(0.0); self.freq_input.setValue(0.0)
        self.zt.setRowCount(0); self.pt.setRowCount(0); self.model_list.clearSelection()
        self.clone_btn.setEnabled(False); self.replace_btn.setEnabled(False); self.delete_btn.setEnabled(False)
        self.ax_mag.clear(); self.ax_phase.clear(); self.canvas.draw()

    def _load_selected_sensor(self, item):
        s_brief = item.data(Qt.ItemDataRole.UserRole)
        sid = getattr(s_brief, "id", None)
        self._selected_sensor_id = sid
        self.clone_btn.setEnabled(bool(sid))
        self.replace_btn.setEnabled(bool(sid))
        self.delete_btn.setEnabled(bool(sid))

        self.current_sensor = self.eq_ctrl.get_sensor(s_brief.id)
        if not self.current_sensor:
            self.clone_btn.setEnabled(False)
            self.replace_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return

        self._fill_ui_from_sensor(self.current_sensor)

    def _fill_ui_from_sensor(self, sensor):
        self.mfg_input.setText(sensor.manufacturer)
        self.model_input.setText(sensor.model)
        self.desc_input.setPlainText(sensor.description or "")
        self.sens_input.setValue(sensor.sensitivity or 0.0)
        self.freq_input.setValue(sensor.frequency or 0.0)
        self.in_units.setText(sensor.input_units or "m/s")
        self.out_units.setText(sensor.output_units or "V")
        
        index = self.type_input.findText(sensor.type or "SENSOR")
        self.type_input.setCurrentIndex(index if index >= 0 else 0)
        
        idx_pz = self.pz_type.findText(sensor.pz_transfer_function_type or "", Qt.MatchFlag.MatchContains)
        if idx_pz >= 0: self.pz_type.setCurrentIndex(idx_pz)
        
        self.zt.setRowCount(0); self.pt.setRowCount(0)
        for z in sensor.zeros: self._add_row(self.zt, z.real_val, z.imag_val)
        for p in sensor.poles: self._add_row(self.pt, p.real_val, p.imag_val)
        
        self._update_plot()

    def _update_plot(self):
        self.ax_mag.clear(); self.ax_phase.clear()
        if not self.current_sensor:
            self.canvas.draw(); return

        try:
            p = [complex(pz.real_val, pz.imag_val) for pz in self.current_sensor.poles]
            z = [complex(pz.real_val, pz.imag_val) for pz in self.current_sensor.zeros]
            gain = self.current_sensor.sensitivity or 1.0
            is_hertz = "HERTZ" in (self.current_sensor.pz_transfer_function_type or "").upper()
            
            f = np.logspace(-2, 2, 500); w = 2 * np.pi * f; s = 1j * w
            if is_hertz:
                p = [cp * 2 * np.pi for cp in p]; z = [cz * 2 * np.pi for cz in z]

            h = np.ones_like(s, dtype=complex)
            for zero in z: h *= (s - zero)
            for pole in p: h /= (s - pole)
            
            f_ref = self.current_sensor.frequency or 1.0; s_ref = 1j * 2 * np.pi * f_ref
            h_ref = np.ones(1, dtype=complex)
            for zero in z: h_ref *= (s_ref - zero)
            for pole in p: h_ref /= (s_ref - pole)
            
            a0 = gain / np.abs(h_ref[0]); h *= a0
            self.ax_mag.loglog(f, np.abs(h), color='blue', lw=1.5)
            self.ax_phase.semilogx(f, np.angle(h, deg=True), color='green', lw=1.5)
            self.canvas.figure.tight_layout(); self.canvas.draw()
        except Exception as e:
            logger.error(f"Bode Error: {e}"); self.canvas.draw()

    def _on_import_arol_clicked(self):
        client = AROLClient()
        dialog = AROLBrowserDialog(client, category='Sensors', parent=self)
        
        if dialog.exec():
            sensor = dialog.selected_object
            if sensor:
                self.current_sensor = sensor
                self._fill_ui_from_sensor(self.current_sensor)
                
                if self.eq_ctrl.save_sensor(self.current_sensor):
                    self.refresh_list()
                    QMessageBox.information(self, "AROL", f"Sensor {sensor.model} imported!")
                    
    def _on_save_clicked(self):
        if not self.current_sensor:
            return
        pole_pairs, pole_err = parse_pz_table_pairs(self.pt, "Poles")
        if pole_err:
            QMessageBox.warning(self, "Error", pole_err)
            return
        zero_pairs, zero_err = parse_pz_table_pairs(self.zt, "Zeros")
        if zero_err:
            QMessageBox.warning(self, "Error", zero_err)
            return
        merged = self.eq_ctrl.equipment_service.merge_sensor_from_pyqt_editor(
            self.current_sensor,
            manufacturer=self.mfg_input.text().strip(),
            model=self.model_input.text().strip(),
            description=self.desc_input.toPlainText().strip(),
            type_=self.type_input.currentText(),
            sensitivity=self.sens_input.value(),
            frequency=self.freq_input.value(),
            input_units=self.in_units.text().strip(),
            output_units=self.out_units.text().strip(),
            pz_transfer_function_type=self.pz_type.currentText(),
            pole_pairs=pole_pairs,
            zero_pairs=zero_pairs,
        )
        self.current_sensor = merged

        if self.eq_ctrl.save_sensor(self.current_sensor):
            QMessageBox.information(self, "OK", "Sensor saved.")
            self.refresh_list(); self._update_plot(); app_signals.equipment_updated.emit()

    def _select_sensor_row_by_id(self, sensor_id: int) -> None:
        for i in range(self.model_list.count()):
            it = self.model_list.item(i)
            s = it.data(Qt.ItemDataRole.UserRole)
            if s is not None and getattr(s, "id", None) == sensor_id:
                self.model_list.setCurrentItem(it)
                self.model_list.scrollToItem(it)
                return

    def _on_clone_clicked(self):
        sid = self._selected_sensor_id
        if sid is None and self.current_sensor and self.current_sensor.id:
            sid = self.current_sensor.id
        if sid is None:
            QMessageBox.warning(self, "Clone", "Select a saved catalog sensor first.")
            return
        src = self.eq_ctrl.get_sensor(sid)
        if not src:
            QMessageBox.warning(self, "Clone", "Sensor not found in catalog.")
            return
        dup = self.eq_ctrl.clone_sensor_model(src)
        saved = self.eq_ctrl.save_sensor(dup)
        if not saved:
            QMessageBox.warning(self, "Clone", "Could not save the duplicate (unique constraint?).")
            return
        self.refresh_list()
        self._select_sensor_row_by_id(saved.id)
        self.current_sensor = saved
        self._selected_sensor_id = saved.id
        self._fill_ui_from_sensor(saved)
        self.clone_btn.setEnabled(True)
        self.replace_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        QMessageBox.information(self, "Cloned", f"Created in catalog: {saved.manufacturer} {saved.model}")

    def _on_delete_clicked(self):
        sid = self._selected_sensor_id or (
            self.current_sensor.id if self.current_sensor and self.current_sensor.id else None
        )
        if not sid:
            QMessageBox.warning(self, "Elimina", "Seleziona un sensore salvato nel catalogo.")
            return
        ch = (
            self.current_sensor
            if (self.current_sensor and getattr(self.current_sensor, "id", None) == sid)
            else self.eq_ctrl.get_sensor(sid)
        )
        display = (
            f"{ch.manufacturer} {ch.model}".strip()
            if ch
            else str(sid)
        )
        msg = f"Sei sicuro di voler eliminare {display}? Questa azione è irreversibile."
        if (
            QMessageBox.question(
                self,
                "Conferma eliminazione",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            if self.eq_ctrl.delete_sensor(sid):
                self._prepare_new_model()
                self.refresh_list()
                app_signals.equipment_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Impossibile eliminare", str(e))

    def _on_replace_clicked(self):
        sid = self._selected_sensor_id or (self.current_sensor.id if self.current_sensor else None)
        if not sid:
            return
        others = [s for s in self.eq_ctrl.get_all_sensors() if s.id != sid]
        if not others:
            QMessageBox.information(self, "Replace", "No other sensors in the catalog.")
            return
        names = [f"{s.manufacturer} {s.model}" for s in others]
        t, ok = QInputDialog.getItem(self, "Replace", "Replace with:", names, 0, False)
        if ok and t:
            if self.eq_ctrl.replace_equipment('sensor', sid, others[names.index(t)].id):
                self._prepare_new_model(); self.refresh_list(); app_signals.equipment_updated.emit()
                
    def refresh_list(self):
        self.model_list.clear()
        for s in self.eq_ctrl.get_all_sensors():
            is_nrl = bool(getattr(s, 'nrl_path', None))
            icon = "🟢" if is_nrl else "🔴"
            
            item = QListWidgetItem(f"{icon} {s.manufacturer} {s.model}")
            item.setData(Qt.ItemDataRole.UserRole, s)
            self.model_list.addItem(item)

    def _on_nrl_clicked(self):
        mfg = self.mfg_input.text().strip()
        mod = self.model_input.text().strip()
        
        query = f"{mfg} {mod}".strip()
        if not query and self.current_sensor:
            query = f"{self.current_sensor.manufacturer} {self.current_sensor.model}"

        if not query:
            QMessageBox.warning(self, "Warning", "Select an instrument or write a name to search in NRL.")
            return

        dialog = NRLBrowserDialog('sensor', search_query=query, parent=self)
        
        if dialog.exec():
            if hasattr(dialog, 'downloaded_item') and dialog.downloaded_item:
                self.current_sensor = dialog.downloaded_item
                self._fill_ui_from_sensor(self.current_sensor)
                self._on_save_clicked()