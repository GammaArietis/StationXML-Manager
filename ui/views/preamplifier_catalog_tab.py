import numpy as np
from scipy import signal
import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QSplitter, QMessageBox, QLabel, QDoubleSpinBox,
                             QListWidget, QListWidgetItem, QComboBox, QGroupBox)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.models.base_models import Preamplifier, AnalogStage, PoleZero
from ui.components.searchable_dialog import SearchableItemDialog
from utils.qt_numeric_input import parse_pz_table_pairs
from utils.signals import app_signals

logger = logging.getLogger(__name__)

class PreamplifierCatalogTab(QWidget):
    def __init__(self, equip_ctrl):
        super().__init__()
        self.eq_ctrl = equip_ctrl
        self.current_preamp = None
        self._selected_preamp_id = None
        self._setup_ui()
        self.refresh_list()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- LEFT: LIST ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("<b>Preamplifiers in Catalog</b>"))
        self.model_list = QListWidget()
        self.model_list.setToolTip("Doppio clic o selezione di una riga per caricare i metadati dettagliati del preamplificatore nel pannello di editing laterale.")
        self.model_list.itemClicked.connect(self._load_selected_preamp)
        left_layout.addWidget(self.model_list)
        
        self.new_model_btn = QPushButton("➕ New Preamplifier")
        self.new_model_btn.setToolTip("Prepara un nuovo preamplificatore o condizionatore analogico con stadi, gain e risposta in frequenza.")
        self.new_model_btn.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.new_model_btn.clicked.connect(self._prepare_new_model)
        left_layout.addWidget(self.new_model_btn)
        self.splitter.addWidget(left_widget)
        
        # --- CENTER: EDITOR ---
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        
        info_group = QGroupBox("General Data")
        info_form = QFormLayout(info_group)
        self.mfg_input = QLineEdit(); self.model_input = QLineEdit(); self.desc_input = QLineEdit()
        self.mfg_input.setPlaceholderText("Kinemetrics / Custom Lab")
        self.mfg_input.setToolTip("Costruttore o laboratorio responsabile del preamplificatore analogico.")
        self.model_input.setPlaceholderText("EpiSensor Preamp / Analog Gain Stage")
        self.model_input.setToolTip("Modello del preamplificatore o stadio di condizionamento tra sensore e datalogger.")
        self.desc_input.setPlaceholderText("Analog conditioning stage with unity gain")
        self.desc_input.setToolTip("Descrizione tecnica dello stadio analogico, gain, filtri e condizioni di accoppiamento sensore-datalogger.")
        info_form.addRow("Manufacturer:", self.mfg_input)
        info_form.addRow("Model:", self.model_input)
        info_form.addRow("Description:", self.desc_input)
        editor_layout.addWidget(info_group)

        # Stage Configuration
        stage_group = QGroupBox("Analog Stages")
        stage_layout = QVBoxLayout(stage_group)
        
        sel_lay = QHBoxLayout()
        self.stage_combo = QComboBox()
        self.stage_combo.setToolTip("Seleziona lo stadio analogico della catena di risposta del preamplificatore.")
        self.stage_combo.currentIndexChanged.connect(self._on_stage_selection_changed)
        sel_lay.addWidget(QLabel("Stage:")); sel_lay.addWidget(self.stage_combo, 1)
        
        add_st = QPushButton("+"); add_st.clicked.connect(self._add_new_stage)
        add_st.setToolTip("Aggiunge uno stadio analogico con gain, unità e poli/zeri alla risposta del preamplificatore.")
        rem_st = QPushButton("-"); rem_st.clicked.connect(self._remove_current_stage)
        rem_st.setToolTip("Rimuove lo stadio analogico selezionato dalla risposta del preamplificatore.")
        sel_lay.addWidget(add_st); sel_lay.addWidget(rem_st)
        stage_layout.addLayout(sel_lay)

        sf = QFormLayout()
        self.s_gain = QDoubleSpinBox(); self.s_gain.setRange(0, 1e12); self.s_gain.setDecimals(4)
        self.s_gain.setToolTip("Gain lineare tensione/tensione dello stadio analogico, incluso nella sensibilità totale.")
        sf.addRow("Stage Gain:", self.s_gain)
        stage_layout.addLayout(sf)

        # PZ Tables
        tables_lay = QHBoxLayout()
        z_lay = QVBoxLayout(); z_lay.addWidget(QLabel("<b>Zeros</b>")); self.zt = self._create_pz_table(); z_lay.addWidget(self.zt)
        p_lay = QVBoxLayout(); p_lay.addWidget(QLabel("<b>Poles</b>")); self.pt = self._create_pz_table(); p_lay.addWidget(self.pt)
        tables_lay.addLayout(z_lay); tables_lay.addLayout(p_lay)
        stage_layout.addLayout(tables_lay)
        
        pz_btns = QHBoxLayout()
        az = QPushButton("+ Zero"); az.clicked.connect(lambda: self._add_row(self.zt))
        az.setToolTip("Aggiunge uno zero complesso allo stadio analogico selezionato.")
        ap = QPushButton("+ Pole"); ap.clicked.connect(lambda: self._add_row(self.pt))
        ap.setToolTip("Aggiunge un polo complesso allo stadio analogico selezionato.")
        dp = QPushButton("- Remove Row"); dp.clicked.connect(self._remove_selected_row)
        dp.setToolTip("Rimuove il polo/zero selezionato dalla risposta dello stadio analogico.")
        pz_btns.addWidget(az); pz_btns.addWidget(ap); pz_btns.addWidget(dp)
        stage_layout.addLayout(pz_btns)
        editor_layout.addWidget(stage_group)

        self.save_btn = QPushButton("💾 SAVE TO CATALOG")
        self.save_btn.setToolTip("Persiste il preamplificatore nel database SQLite con stadi analogici, gain e risposta complessa.")
        self.save_btn.setStyleSheet("background-color: #2E7D32; color: white; height: 35px; font-weight: bold;")
        self.save_btn.clicked.connect(self._on_save_clicked)
        editor_layout.addWidget(self.save_btn)

        danger_layout = QHBoxLayout()
        self.clone_btn = QPushButton("👯 Clone")
        self.clone_btn.setToolTip("Clona il preamplificatore creando una nuova riga catalogo senza riusare l'ID originale.")
        self.clone_btn.setStyleSheet("background-color: #8E24AA; color: white;")
        self.clone_btn.clicked.connect(self._on_clone_clicked)
        self.clone_btn.setEnabled(False)
        self.replace_btn = QPushButton("🔄 Replace")
        self.replace_btn.setToolTip("Sposta i riferimenti dei canali verso un preamplificatore master normalizzando il catalogo.")
        self.replace_btn.setStyleSheet("background-color: #F57C00; color: white;")
        self.replace_btn.clicked.connect(self._on_replace_clicked)
        self.replace_btn.setEnabled(False)
        self.delete_btn = QPushButton("🗑️ Delete")
        self.delete_btn.setToolTip("Elimina il preamplificatore solo se non referenziato da canali o vincoli applicativi.")
        self.delete_btn.setStyleSheet("background-color: #C62828; color: white;")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setEnabled(False)
        danger_layout.addWidget(self.clone_btn)
        danger_layout.addWidget(self.replace_btn)
        danger_layout.addWidget(self.delete_btn)
        editor_layout.addLayout(danger_layout)
        
        self.splitter.addWidget(editor_widget)

        # --- RIGHT: PLOT ---
        plot_cont = QWidget(); plot_lay = QVBoxLayout(plot_cont)
        self.canvas = FigureCanvas(Figure(figsize=(5, 4)))
        self.ax_mag = self.canvas.figure.add_subplot(211); self.ax_phase = self.canvas.figure.add_subplot(212)
        plot_lay.addWidget(QLabel("<b>Frequency Response</b>")); plot_lay.addWidget(self.canvas)
        self.splitter.addWidget(plot_cont)
        
        layout.addWidget(self.splitter)

    def _create_pz_table(self):
        t = QTableWidget(0, 2); t.setHorizontalHeaderLabels(["Real", "Imaginary"])
        t.setToolTip("Doppio clic per modificare parte reale e immaginaria dei poli/zeri dello stadio analogico.")
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); return t

    def _add_row(self, t, r=0.0, i=0.0):
        row = t.rowCount(); t.insertRow(row); t.setItem(row,0,QTableWidgetItem(str(r))); t.setItem(row,1,QTableWidgetItem(str(i)))

    def _remove_selected_row(self):
        for t in [self.zt, self.pt]:
            if t.hasFocus() and t.currentRow() >= 0:
                t.removeRow(t.currentRow())

    def refresh_list(self):
        self.model_list.clear()
        for p in self.eq_ctrl.get_all_preamplifiers():
            item = QListWidgetItem(f"{p.manufacturer} {p.model}"); item.setData(Qt.ItemDataRole.UserRole, p); self.model_list.addItem(item)

    def _prepare_new_model(self):
        self.current_preamp = Preamplifier(manufacturer="", model="")
        self._selected_preamp_id = None
        self.mfg_input.clear(); self.model_input.clear(); self.desc_input.clear()
        self.stage_combo.clear(); self.zt.setRowCount(0); self.pt.setRowCount(0)
        self.clone_btn.setEnabled(False); self.replace_btn.setEnabled(False); self.delete_btn.setEnabled(False)
        self._add_new_stage()

    def _load_selected_preamp(self, item):
        p_brief = item.data(Qt.ItemDataRole.UserRole)
        pid = getattr(p_brief, "id", None)
        self._selected_preamp_id = pid
        self.clone_btn.setEnabled(bool(pid))
        self.replace_btn.setEnabled(bool(pid))
        self.delete_btn.setEnabled(bool(pid))

        self.current_preamp = self.eq_ctrl.get_preamplifier_by_id(p_brief.id)
        self.mfg_input.setText(self.current_preamp.manufacturer)
        self.model_input.setText(self.current_preamp.model)
        self.desc_input.setText(self.current_preamp.description or "")
        self._refresh_stage_combo()
        self._update_total_plot()

    def _on_stage_selection_changed(self, idx):
        if idx < 0 or not self.current_preamp.analog_stages: return
        s = self.current_preamp.analog_stages[idx]
        self.s_gain.setValue(s.stage_gain)
        self.zt.setRowCount(0); self.pt.setRowCount(0)
        for pz in s.poles: self._add_row(self.pt, pz.real_val, pz.imag_val)
        for pz in s.zeros: self._add_row(self.zt, pz.real_val, pz.imag_val)

    def _add_new_stage(self):
        new_s = AnalogStage(stage_sequence=len(self.current_preamp.analog_stages)+1, name="Stage")
        self.current_preamp.analog_stages.append(new_s); self._refresh_stage_combo()

    def _remove_current_stage(self):
        if len(self.current_preamp.analog_stages) > 1:
            self.current_preamp.analog_stages.pop(self.stage_combo.currentIndex())
            self._refresh_stage_combo()

    def _refresh_stage_combo(self):
        self.stage_combo.blockSignals(True); self.stage_combo.clear()
        for i, s in enumerate(self.current_preamp.analog_stages): self.stage_combo.addItem(f"Stage {i+1}")
        self.stage_combo.blockSignals(False); self.stage_combo.setCurrentIndex(0); self._on_stage_selection_changed(0)

    def _select_preamp_row_by_id(self, preamp_id: int) -> None:
        for i in range(self.model_list.count()):
            it = self.model_list.item(i)
            p = it.data(Qt.ItemDataRole.UserRole)
            if p is not None and getattr(p, "id", None) == preamp_id:
                self.model_list.setCurrentItem(it)
                self.model_list.scrollToItem(it)
                return

    def _on_clone_clicked(self):
        pid = self._selected_preamp_id
        if pid is None and self.current_preamp and self.current_preamp.id:
            pid = self.current_preamp.id
        if pid is None:
            QMessageBox.warning(self, "Clone", "Select a saved catalog preamplifier first.")
            return
        src = self.eq_ctrl.get_preamplifier_by_id(pid)
        if not src:
            QMessageBox.warning(self, "Clone", "Preamplifier not found in catalog.")
            return
        dup = self.eq_ctrl.clone_preamplifier_model(src)
        saved = self.eq_ctrl.save_preamplifier(dup)
        if not saved:
            QMessageBox.warning(self, "Clone", "Could not save the duplicate (unique constraint?).")
            return
        self.refresh_list()
        self._select_preamp_row_by_id(saved.id)
        self.current_preamp = saved
        self._selected_preamp_id = saved.id
        self._refresh_stage_combo()
        self.clone_btn.setEnabled(True)
        self.replace_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        QMessageBox.information(self, "Cloned", f"Created in catalog: {saved.manufacturer} {saved.model}")
        app_signals.equipment_updated.emit()

    def _on_save_clicked(self):
        if not self.current_preamp:
            return
        idx = self.stage_combo.currentIndex()
        if idx >= 0:
            s = self.current_preamp.analog_stages[idx]
            s.stage_gain = self.s_gain.value()
            pole_pairs, pole_err = parse_pz_table_pairs(self.pt, "Poles")
            if pole_err:
                QMessageBox.warning(self, "Error", pole_err)
                return
            zero_pairs, zero_err = parse_pz_table_pairs(self.zt, "Zeros")
            if zero_err:
                QMessageBox.warning(self, "Error", zero_err)
                return
            s.poles = [PoleZero(r, i) for r, i in pole_pairs]
            s.zeros = [PoleZero(r, i) for r, i in zero_pairs]
        
        self.current_preamp.manufacturer = self.mfg_input.text()
        self.current_preamp.model = self.model_input.text()
        if self.eq_ctrl.save_preamplifier(self.current_preamp):
            self.refresh_list()
            self._update_total_plot()
            app_signals.equipment_updated.emit()

    def _on_delete_clicked(self):
        pid = self._selected_preamp_id or (
            self.current_preamp.id if self.current_preamp and self.current_preamp.id else None
        )
        if not pid:
            return
        pa = (
            self.current_preamp
            if (self.current_preamp and getattr(self.current_preamp, "id", None) == pid)
            else self.eq_ctrl.get_preamplifier_by_id(pid)
        )
        display = f"{pa.manufacturer} {pa.model}".strip() if pa else str(pid)
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
        if self.eq_ctrl.delete_preamplifier(pid):
            self.refresh_list()
            self._prepare_new_model()
            app_signals.equipment_updated.emit()

    def _on_replace_clicked(self):
        pid = self._selected_preamp_id or (
            self.current_preamp.id if self.current_preamp and self.current_preamp.id else None
        )
        if not pid:
            return
        others = [p for p in self.eq_ctrl.get_all_preamplifiers() if p.id != pid]
        if not others:
            QMessageBox.information(self, "Replace", "No other preamplifiers in the catalog.")
            return
        choices = [(f"{p.manufacturer} {p.model}", p.id) for p in others]
        new_id, ok = SearchableItemDialog.get_item(
            choices,
            title="Replace Preamplifier",
            placeholder="Cerca...",
            parent=self,
        )
        if ok and new_id:
            if self.eq_ctrl.replace_equipment('preamplifier', pid, new_id):
                self.refresh_list()
                self._prepare_new_model()
                app_signals.equipment_updated.emit()

    def _update_total_plot(self):
        self.ax_mag.clear(); self.ax_phase.clear()
        if not self.current_preamp.analog_stages: return
        w = np.logspace(-2, 3, 1000) * 2 * np.pi
        total_h = np.ones_like(w, dtype=complex)
        for s in self.current_preamp.analog_stages:
            sys = signal.lti([complex(z.real_val, z.imag_val) for z in s.zeros],
                             [complex(p.real_val, p.imag_val) for p in s.poles] if s.poles else [complex(-1e9,0)],
                             s.stage_gain)
            _, h = signal.freqresp(sys, w=w); total_h *= h
        f = w/(2*np.pi)
        self.ax_mag.semilogx(f, 20*np.log10(np.abs(total_h))); self.ax_mag.grid(True)
        self.ax_phase.semilogx(f, np.degrees(np.unwrap(np.angle(total_h)))); self.ax_phase.grid(True)
        self.canvas.draw()