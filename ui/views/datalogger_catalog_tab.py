import logging
import json
import csv
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
                             QSplitter, QMessageBox, QLabel, QDoubleSpinBox, QListWidget,
                             QListWidgetItem, QGroupBox, QFileDialog, QInputDialog, QTextEdit,
                             QAbstractItemView)
from PyQt6.QtCore import Qt

from core.models.base_models import Datalogger, ResponseFilter
from ui.views.fir_plot_dialog import FirPlotDialog
from ui.views.nrl_dialog import NRLBrowserDialog
from utils.signals import app_signals

logger = logging.getLogger(__name__)

class DataloggerCatalogTab(QWidget):
    def __init__(self, equip_ctrl):
        super().__init__()
        self.eq_ctrl = equip_ctrl
        self.current_dl = None
        self._selected_dl_id = None
        self._setup_ui()
        self.refresh_list()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ==========================================
        # LEFT: List and Commands
        # ==========================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        left_layout.addWidget(QLabel("<b>Dataloggers in Catalog</b>"))
        self.model_list = QListWidget()
        self.model_list.itemClicked.connect(self._load_selected_dl)
        self.model_list.itemDoubleClicked.connect(self._on_nrl_clicked)
        left_layout.addWidget(self.model_list)
        
        creation_layout = QHBoxLayout()
        self.new_btn = QPushButton("➕ New")
        self.new_btn.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.new_btn.clicked.connect(self._prepare_new_model)
        
        self.nrl_btn = QPushButton("🌐 Import NRL")
        self.nrl_btn.clicked.connect(self._on_nrl_clicked)
        
        self.arol_btn = QPushButton("🌐 Import AROL")
        self.arol_btn.clicked.connect(self._on_import_arol_clicked)
        
        creation_layout.addWidget(self.new_btn)
        creation_layout.addWidget(self.nrl_btn)
        creation_layout.addWidget(self.arol_btn)
        left_layout.addLayout(creation_layout)
        
        self.splitter.addWidget(left_widget)
        
        # ==========================================
        # RIGHT: Editor and Analysis
        # ==========================================
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        
        # 1. General Data
        info_group = QGroupBox("General Datalogger Data")
        info_form = QFormLayout(info_group)
        self.mfg_input = QLineEdit()
        self.model_input = QLineEdit()
        
        self.desc_input = QTextEdit()
        self.desc_input.setMaximumHeight(50)
        
        self.gain_input = QDoubleSpinBox()
        self.gain_input.setRange(0, 1e12); self.gain_input.setDecimals(4)
        
        self.drift_input = QDoubleSpinBox()
        self.drift_input.setRange(0, 1.0); self.drift_input.setDecimals(8)
        
        info_form.addRow("Manufacturer:", self.mfg_input)
        info_form.addRow("Model:", self.model_input)
        info_form.addRow("Description:", self.desc_input)
        info_form.addRow("A/D Gain (Counts/V):", self.gain_input)
        info_form.addRow("Max Clock Drift (s/s):", self.drift_input)
        editor_layout.addWidget(info_group)

        # 2. Acquisition Chain
        stage_group = QGroupBox("Acquisition Chain (Stages and Filters)")
        stage_layout = QVBoxLayout(stage_group)
        
        self.stages_table = QTableWidget(0, 8)
        self.stages_table.setHorizontalHeaderLabels([
            "Stage", "Type", "Gain", "Rate In (Hz)", "Rate Out (Hz)", "Decim.",
            "Delay (s)", "Correction (s)",
        ])
        self.stages_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stages_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.stages_table.itemSelectionChanged.connect(self._on_stage_selected)
        self.stages_table.itemChanged.connect(self._on_stage_cell_changed)
        stage_layout.addWidget(self.stages_table)

        stage_row_btns = QHBoxLayout()
        add_stage_btn = QPushButton("+ Add Row")
        add_stage_btn.clicked.connect(self._add_stage_row)
        rem_stage_btn = QPushButton("- Remove Row")
        rem_stage_btn.clicked.connect(self._remove_stage_row)
        stage_row_btns.addWidget(add_stage_btn)
        stage_row_btns.addWidget(rem_stage_btn)
        stage_layout.addLayout(stage_row_btns)

        stage_layout.addWidget(QLabel("<b>Selected Stage Coefficients (JSON):</b>"))
        self.coeffs_edit = QTextEdit()
        self.coeffs_edit.setPlaceholderText("Select a stage from the table to view or edit its FIR/IIR coefficients...")
        self.coeffs_edit.setMaximumHeight(80)
        self.coeffs_edit.textChanged.connect(self._on_coeffs_edited)
        stage_layout.addWidget(self.coeffs_edit)
        
        ana_btns = QHBoxLayout()
        self.plot_btn = QPushButton("📈 FIR/IIR Plots")
        self.plot_btn.clicked.connect(self._on_plot_clicked)
        self.plot_btn.setEnabled(False)
        
        self.export_btn = QPushButton("📤 Export Report (CSV)")
        self.export_btn.clicked.connect(self._on_export_clicked)
        self.export_btn.setEnabled(False)
        
        ana_btns.addWidget(self.plot_btn)
        ana_btns.addWidget(self.export_btn)
        stage_layout.addLayout(ana_btns)
        
        editor_layout.addWidget(stage_group)

        # 3. Catalog Actions
        self.save_btn = QPushButton("💾 SAVE TO CATALOG")
        self.save_btn.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; height: 35px;")
        self.save_btn.clicked.connect(self._on_save_clicked)
        editor_layout.addWidget(self.save_btn)
        
        danger_layout = QHBoxLayout()
        self.clone_btn = QPushButton("👯 Clone Model"); self.clone_btn.setStyleSheet("background-color: #8E24AA; color: white;"); self.clone_btn.clicked.connect(self._on_clone_clicked); self.clone_btn.setEnabled(False)
        self.replace_btn = QPushButton("🔄 Replace Everywhere"); self.replace_btn.setStyleSheet("background-color: #F57C00; color: white;"); self.replace_btn.clicked.connect(self._on_replace_clicked); self.replace_btn.setEnabled(False)
        self.delete_btn = QPushButton("🗑️ Delete"); self.delete_btn.setStyleSheet("background-color: #C62828; color: white;"); self.delete_btn.clicked.connect(self._on_delete_clicked); self.delete_btn.setEnabled(False)
        
        danger_layout.addWidget(self.clone_btn); danger_layout.addWidget(self.replace_btn); danger_layout.addWidget(self.delete_btn)
        editor_layout.addLayout(danger_layout)
        
        self.splitter.addWidget(editor_widget)
        self.splitter.setSizes([300, 700])
        layout.addWidget(self.splitter)

    def _prepare_new_model(self):
        self.current_dl = Datalogger(manufacturer="", model="")
        self._selected_dl_id = None
        self.mfg_input.clear(); self.model_input.clear(); self.desc_input.clear()
        self.gain_input.setValue(0.0); self.drift_input.setValue(0.0)
        self.stages_table.setRowCount(0); self.coeffs_edit.clear()
        self.model_list.clearSelection()
        
        self.plot_btn.setEnabled(False); self.export_btn.setEnabled(False)
        self.clone_btn.setEnabled(False); self.replace_btn.setEnabled(False); self.delete_btn.setEnabled(False)

    def _load_selected_dl(self, item):
        dl_brief = item.data(Qt.ItemDataRole.UserRole)
        did = getattr(dl_brief, "id", None)
        self._selected_dl_id = did
        self.clone_btn.setEnabled(bool(did))
        self.replace_btn.setEnabled(bool(did))
        self.delete_btn.setEnabled(bool(did))

        self.current_dl = self.eq_ctrl.get_datalogger(dl_brief.id)
        if not self.current_dl:
            self.clone_btn.setEnabled(False)
            self.replace_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        self._fill_ui_from_datalogger(self.current_dl)

    def _editable_delay_correction_item(self, value: float) -> QTableWidgetItem:
        item = QTableWidgetItem(f"{value:.6g}")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _on_stage_cell_changed(self, item: QTableWidgetItem):
        col = item.column()
        if col not in (6, 7):
            return
        row = item.row()
        stage_item = self.stages_table.item(row, 0)
        if not stage_item:
            return
        filt = stage_item.data(Qt.ItemDataRole.UserRole)
        if not filt:
            return
        try:
            if col == 6:
                filt.estimated_delay = float(item.text().strip() or 0)
            else:
                filt.correction_applied = float(item.text().strip() or 0)
        except ValueError:
            pass

    def _add_stage_row(self):
        if not self.current_dl:
            self.current_dl = Datalogger(manufacturer="", model="")
        if self.current_dl.filters is None:
            self.current_dl.filters = []
        next_num = len(self.current_dl.filters) + 1
        self.current_dl.filters.append(
            ResponseFilter(
                stage_number=next_num,
                filter_type="FIR",
                coefficients="[]",
            )
        )
        self._fill_ui_from_datalogger(self.current_dl)

    def _remove_stage_row(self):
        if not self.current_dl or not self.current_dl.filters:
            return
        row = self.stages_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Remove Row", "Select a stage row to remove.")
            return
        stage_item = self.stages_table.item(row, 0)
        if not stage_item:
            return
        filt = stage_item.data(Qt.ItemDataRole.UserRole)
        if filt in self.current_dl.filters:
            self.current_dl.filters.remove(filt)
        for i, f in enumerate(
            sorted(self.current_dl.filters, key=lambda x: x.stage_number), start=1
        ):
            f.stage_number = i
        self._fill_ui_from_datalogger(self.current_dl)

    def _on_stage_selected(self):
        row = self.stages_table.currentRow()
        if row < 0: return
        
        stage_item = self.stages_table.item(row, 0)
        if not stage_item: return
        f = stage_item.data(Qt.ItemDataRole.UserRole)
        
        self.coeffs_edit.blockSignals(True)
        try:
            parsed = json.loads(f.coefficients)
            self.coeffs_edit.setPlainText(json.dumps(parsed, indent=4))
        except:
            self.coeffs_edit.setPlainText(f.coefficients)
        self.coeffs_edit.blockSignals(False)

    def _on_coeffs_edited(self):
        row = self.stages_table.currentRow()
        if row < 0: return
        f = self.stages_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        f.coefficients = self.coeffs_edit.toPlainText().strip()

    def _on_plot_clicked(self):
        if not self.current_dl or not self.current_dl.filters: return
        plot_filters = [f for f in self.current_dl.filters if f.filter_type.upper() not in ['A/D', 'A-D', 'DIGITIZER']]
        if not plot_filters:
            QMessageBox.information(self, "Plot", "This datalogger only contains the A/D stage.\nThere are no FIR or IIR filters to plot.")
            return
        FirPlotDialog(self.current_dl.model, plot_filters, self).exec()

    def _select_dl_row_by_id(self, datalogger_id: int) -> None:
        for i in range(self.model_list.count()):
            it = self.model_list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole)
            if d is not None and getattr(d, "id", None) == datalogger_id:
                self.model_list.setCurrentItem(it)
                self.model_list.scrollToItem(it)
                return

    def _on_clone_clicked(self):
        did = self._selected_dl_id
        if did is None and self.current_dl and self.current_dl.id:
            did = self.current_dl.id
        if did is None:
            QMessageBox.warning(self, "Clone", "Select a saved catalog datalogger first.")
            return
        src = self.eq_ctrl.get_datalogger(did)
        if not src:
            QMessageBox.warning(self, "Clone", "Datalogger not found in catalog.")
            return
        dup = self.eq_ctrl.clone_datalogger_model(src)
        saved = self.eq_ctrl.save_datalogger(dup)
        if not saved:
            QMessageBox.warning(self, "Clone", "Could not save the duplicate (unique constraint?).")
            return
        self.refresh_list()
        self._select_dl_row_by_id(saved.id)
        self.current_dl = saved
        self._selected_dl_id = saved.id
        self._fill_ui_from_datalogger(saved)
        self.clone_btn.setEnabled(True)
        self.replace_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        QMessageBox.information(self, "Cloned", f"Created in catalog: {saved.manufacturer} {saved.model}")
        app_signals.equipment_updated.emit()

    def _on_import_arol_clicked(self):
        from utils.arol_client import AROLClient
        from ui.views.arol_dialog import AROLBrowserDialog
        client = AROLClient()

        d1 = AROLBrowserDialog(client, category='Dataloggers', parent=self)
        d1.setWindowTitle("AROL (1/2): Select Analog Stage")
        if not d1.exec(): return
        dl_final = d1.selected_object

        res = QMessageBox.question(self, "Composition",
                                 "Do you want to add the digital part (FIR) now?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if res == QMessageBox.StandardButton.Yes:
            d2 = AROLBrowserDialog(client, category='Dataloggers', parent=self)
            d2.setWindowTitle("AROL (2/2): Select Digital Stage (FIR)")
            if d2.exec():
                digitizer = d2.selected_object
                if digitizer:
                    off = len(dl_final.filters)
                    for i, f in enumerate(digitizer.filters):
                        f.stage_number = off + i + 1
                        dl_final.filters.append(f)
                    dl_final.gain *= digitizer.gain
                    
                    p1 = dl_final.model 
                    p2 = digitizer.model 
                    
                    prefix = p1.split('-')[0].split('_')[0]
                    if p2.startswith(prefix):
                        p2 = p2.replace(prefix, '').lstrip('-_')
                    
                    dl_final.model = f"{p1}_{p2}"
                    
        self.current_dl = dl_final
        self._fill_ui_from_datalogger(self.current_dl)
        
        if self.eq_ctrl.save_datalogger(self.current_dl):
            self.refresh_list()
            QMessageBox.information(self, "AROL", f"Model {self.current_dl.model} created and saved!")
            
    def _on_export_clicked(self):
        if not self.current_dl: return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", f"Report_{self.current_dl.model}.csv", "CSV (*.csv)")
        if path:
            try:
                with open(path, 'w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(["Datalogger", self.current_dl.manufacturer, self.current_dl.model])
                    w.writerow([
                        "Stage", "Type", "Gain", "Rate In (Hz)", "Rate Out (Hz)",
                        "Decimation", "Delay (s)", "Correction (s)",
                    ])
                    for r in range(self.stages_table.rowCount()):
                        w.writerow([
                            self.stages_table.item(r, c).text()
                            if self.stages_table.item(r, c)
                            else ""
                            for c in range(8)
                        ])
                QMessageBox.information(self, "OK", "CSV Report generated!")
            except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def _on_save_clicked(self):
        if not self.current_dl: return
        self.current_dl.manufacturer = self.mfg_input.text().strip()
        self.current_dl.model = self.model_input.text().strip()
        self.current_dl.description = self.desc_input.toPlainText().strip()
        self.current_dl.gain = self.gain_input.value()
        self.current_dl.max_clock_drift = self.drift_input.value()
        
        if self.eq_ctrl.save_datalogger(self.current_dl):
            QMessageBox.information(self, "Success", "Datalogger saved in catalog.")
            self.refresh_list(); app_signals.equipment_updated.emit()

    def _on_delete_clicked(self):
        did = self._selected_dl_id or (self.current_dl.id if self.current_dl and self.current_dl.id else None)
        if not did:
            QMessageBox.warning(self, "Elimina", "Seleziona un datalogger salvato nel catalogo.")
            return
        dl = (
            self.current_dl
            if (self.current_dl and getattr(self.current_dl, "id", None) == did)
            else self.eq_ctrl.get_datalogger(did)
        )
        display = f"{dl.manufacturer} {dl.model}".strip() if dl else str(did)
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
            if self.eq_ctrl.delete_datalogger(did):
                self._prepare_new_model()
                self.refresh_list()
                app_signals.equipment_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Impossibile eliminare", str(e))

    def _on_replace_clicked(self):
        did = self._selected_dl_id or (self.current_dl.id if self.current_dl else None)
        if not did:
            return
        others = [d for d in self.eq_ctrl.get_all_dataloggers() if d.id != did]
        if not others:
            QMessageBox.information(self, "Replace", "No other dataloggers in the catalog.")
            return
        names = [f"{d.manufacturer} {d.model}" for d in others]
        target, ok = QInputDialog.getItem(self, "Replace", "Replace with:", names, 0, False)
        if ok and target:
            if self.eq_ctrl.replace_equipment('datalogger', did, others[names.index(target)].id):
                self._prepare_new_model(); self.refresh_list(); app_signals.equipment_updated.emit()
    
    def _fill_ui_from_datalogger(self, dl):
        self.mfg_input.setText(dl.manufacturer or "")
        self.model_input.setText(dl.model or "")
        self.desc_input.setPlainText(dl.description or "")
        self.gain_input.setValue(dl.gain or 0.0)
        self.drift_input.setValue(dl.max_clock_drift or 0.0)
        
        self.stages_table.blockSignals(True)
        self.stages_table.setRowCount(0)

        for f in sorted(dl.filters, key=lambda x: x.stage_number):
            r = self.stages_table.rowCount()
            self.stages_table.insertRow(r)
            
            g_val = 1.0
            try:
                parsed = json.loads(f.coefficients)
                if 'data' in parsed and 'gain' in parsed['data']:
                    g_val = parsed['data']['gain'].get('value', 1.0)
                else:
                    g_val = parsed.get('stage_gain', 1.0)
            except:
                pass
            
            item_stage = QTableWidgetItem(str(f.stage_number))
            item_stage.setData(Qt.ItemDataRole.UserRole, f)
            
            i_rate = getattr(f, 'input_sample_rate', None)
            o_rate = getattr(f, 'output_sample_rate', None)
            d_fact = getattr(f, 'decimation_factor', None)
            
            d_val = float(d_fact) if d_fact else 1.0
            if d_val == 0.0: d_val = 1.0
            
            if i_rate and (not o_rate or o_rate == 0.0):
                o_rate = i_rate / d_val
            elif o_rate and (not i_rate or i_rate == 0.0):
                i_rate = o_rate * d_val
                
            in_str = f"{i_rate:.2f}" if i_rate else "N/A"
            out_str = f"{o_rate:.2f}" if o_rate else "N/A"
            dec_str = str(d_fact) if d_fact is not None else "1"

            self.stages_table.setItem(r, 0, item_stage)
            self.stages_table.setItem(r, 1, QTableWidgetItem(f.filter_type))
            self.stages_table.setItem(r, 2, QTableWidgetItem(f"{g_val:.4g}"))
            self.stages_table.setItem(r, 3, QTableWidgetItem(in_str))
            self.stages_table.setItem(r, 4, QTableWidgetItem(out_str))
            self.stages_table.setItem(r, 5, QTableWidgetItem(dec_str))
            delay_val = float(getattr(f, "estimated_delay", 0.0) or 0.0)
            corr_val = float(getattr(f, "correction_applied", 0.0) or 0.0)
            self.stages_table.setItem(r, 6, self._editable_delay_correction_item(delay_val))
            self.stages_table.setItem(r, 7, self._editable_delay_correction_item(corr_val))

        self.stages_table.blockSignals(False)
        self.coeffs_edit.clear()

        has_filters = len(dl.filters) > 0
        self.plot_btn.setEnabled(has_filters)
        self.export_btn.setEnabled(has_filters)

    def refresh_list(self):
        self.model_list.clear()
        for d in self.eq_ctrl.get_all_dataloggers():
            is_nrl = bool(getattr(d, 'nrl_path', None))
            icon = "🟢" if is_nrl else "🔴"
            
            item = QListWidgetItem(f"{icon} {d.manufacturer} {d.model}")
            item.setData(Qt.ItemDataRole.UserRole, d)
            self.model_list.addItem(item)

    def _on_nrl_clicked(self):
        mfg = self.mfg_input.text().strip()
        mod = self.model_input.text().strip()
        
        query = f"{mfg} {mod}".strip()
        if not query and self.current_dl:
            query = f"{self.current_dl.manufacturer} {self.current_dl.model}"

        if not query:
            QMessageBox.warning(self, "Warning", "Select an instrument or write a name to search in NRL.")
            return

        dialog = NRLBrowserDialog('datalogger', search_query=query, parent=self)
        
        if dialog.exec() == 1:
            if hasattr(dialog, 'downloaded_item') and dialog.downloaded_item:
                self.current_dl = dialog.downloaded_item
                self._fill_ui_from_datalogger(self.current_dl)
                self._on_save_clicked()