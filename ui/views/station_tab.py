import json 
import logging

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout,
                             QLineEdit, QPushButton, QMessageBox,
                             QDateTimeEdit, QCheckBox, QHBoxLayout,
                             QDoubleSpinBox, QComboBox, QFrame, QTextEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
                             QDialog, QDialogButtonBox)
from PyQt6.QtCore import Qt, QDateTime

from utils.geology_client import fetch_geology_from_coords
from utils.geocoding_client import fetch_geography_from_coords

from core.models.base_models import Station
from utils.signals import app_signals
from core.validators.geo_validators import ValidationError
from utils.fdsn_seed_codes import (
    get_fdsn_band_code,
    get_instrument_code,
    is_broadband_from_poles,
)

logger = logging.getLogger(__name__)

class StationTab(QWidget):
    """
    Screen for inserting and editing data of a Seismic Station.
    """
    def __init__(self, station_ctrl, equip_ctrl, channel_ctrl=None):
        super().__init__()
        self.sta_ctrl = station_ctrl
        self.eq_ctrl = equip_ctrl
        self.cha_ctrl = channel_ctrl
        self.current_station_id = None
        self.parent_network_id = None
        
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout = QFormLayout()
        
        # 1. Base Text Fields
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("ZOE o MDN")
        self.code_input.setToolTip("Codice identificativo internazionale della stazione sismica (da 3 a 5 caratteri maiuscoli).")
        self.code_input.setMaxLength(10)
        
        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText("Palermo, Sicily, Italy")
        self.site_input.setToolTip("Descrizione geografica o toponimo del sito di installazione del sensore sismico.")
        
        # --- FDSN COMMENTS TABLE ---
        comm_group = QGroupBox("Comments (FDSN)")
        comm_lay = QVBoxLayout(comm_group)
        
        self.comm_table = QTableWidget(0, 5)
        self.comm_table.setHorizontalHeaderLabels(["Text", "Start (YYYY-MM-DD)", "End", "Subject", "Author (Name/Agency)"])
        self.comm_table.setToolTip("Doppio clic o selezione di una riga per caricare annotazioni FDSN della stazione con intervallo UTC.")
        self.comm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        comm_lay.addWidget(self.comm_table)
        
        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add Comment"); add_btn.setToolTip("Aggiunge una nota FDSN su manutenzione, rumore di sito, relocation o qualità del metadata stazione."); add_btn.clicked.connect(self._add_comment_row)
        rem_btn = QPushButton("- Remove Row"); rem_btn.setToolTip("Rimuove la nota FDSN selezionata dalla serializzazione StationXML della stazione."); rem_btn.clicked.connect(self._remove_comment_row)
        btns.addWidget(add_btn); btns.addWidget(rem_btn)
        comm_lay.addLayout(btns)

        self.operator_combo = QComboBox()
        self.operator_combo.setToolTip("Agenzia responsabile della gestione, manutenzione e qualità dei metadati della stazione.")

        self.restricted_combo = QComboBox()
        self.restricted_combo.addItems(["open", "closed", "partial"])
        self.restricted_combo.setToolTip("Stato FDSN restrictedStatus applicato alla stazione e alle sue epoche operative.")

        self.vault_input = QComboBox()
        self.vault_input.setEditable(True)
        self.vault_input.setToolTip("Tipologia di installazione fisica del sensore: vault, borehole, superficie o altra infrastruttura sismologica.")
        self.vault_input.addItems([
            "Vault", "Borehole", "Surface", "Cave",
            "Underwater", "Tunnel", "Building", "Bunker"
        ])

        self.geology_input = QComboBox()
        self.geology_input.setEditable(True)
        self.geology_input.setToolTip("Litologia locale del sito sismico, utile per interpretare risposta di sito, rumore e accoppiamento sensore-suolo.")
        self.geology_input.addItems([
            "Rock", "Sedimentary Rock", "Metamorphic Rock", "Igneous Rock",
            "Alluvium", "Consolidated Sediment", "Unconsolidated Sediment",
            "Limestone", "Basalt", "Granite", "Clay", "Sand", "Gravel", "Soil"
        ])

        self.btn_fetch_geology = QPushButton("🌍 Get from Lat/Lon")
        self.btn_fetch_geology.setToolTip("Interroga servizi geologici esterni usando coordinate WGS84 per stimare la litologia del sito sismico.")
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
        self.lat_input.setToolTip("Coordinata geografica espressa in gradi decimali secondo lo standard geodetico WGS84. Esempio: 41.8902.")
        
        self.lon_input = QDoubleSpinBox()
        self.lon_input.setDecimals(5)
        self.lon_input.setRange(-180.0, 180.0)
        self.lon_input.setToolTip("Coordinata geografica espressa in gradi decimali secondo lo standard geodetico WGS84. Esempio: 12.4922.")
        
        self.elev_input = QDoubleSpinBox()
        self.elev_input.setDecimals(1)
        self.elev_input.setRange(-15000.0, 10000.0)
        self.elev_input.setSuffix(" m")
        self.elev_input.setToolTip("Elevazione altimetrica del caposaldo della stazione espressa in metri sul livello medio del mare (m s.l.m.).")

        self.water_level_input = QDoubleSpinBox()
        self.water_level_input.setDecimals(1)
        self.water_level_input.setRange(-15000.0, 10000.0)
        self.water_level_input.setSuffix(" m")
        self.water_level_input.setToolTip("Quota del livello idrico rispetto al riferimento della stazione, in metri, per installazioni in pozzo o ambienti sommersi.")

        # Advanced geographic fields
        self.site_desc_input = QLineEdit()
        self.site_desc_input.setPlaceholderText("Palermo, Sicily, Italy")
        self.site_desc_input.setToolTip("Descrizione geografica o toponimo del sito di installazione del sensore sismico.")
        
        self.btn_fetch_geography = QPushButton("📍 Auto-fill Locations from Lat/Lon")
        self.btn_fetch_geography.setToolTip("Ricava toponimi e campi geografici dalle coordinate WGS84 per migliorare la descrizione StationXML del sito.")
        self.btn_fetch_geography.setStyleSheet("background-color: #F57C00; color: white; font-weight: bold;")
        self.btn_fetch_geography.clicked.connect(self._auto_fill_geography)
        
        desc_layout = QHBoxLayout()
        desc_layout.setContentsMargins(0, 0, 0, 0)
        desc_layout.addWidget(self.site_desc_input)
        desc_layout.addWidget(self.btn_fetch_geography)

        self.town_input = QLineEdit()
        self.town_input.setPlaceholderText("Palermo")
        self.town_input.setToolTip("Comune o località amministrativa associata alle coordinate WGS84 della stazione.")
        self.county_input = QLineEdit()
        self.county_input.setPlaceholderText("Palermo")
        self.county_input.setToolTip("Provincia o contea usata per contestualizzare il sito di installazione sismica.")
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("Sicily")
        self.region_input.setToolTip("Regione geografica o amministrativa del sito sismico.")
        self.country_input = QLineEdit()
        self.country_input.setPlaceholderText("Italy")
        self.country_input.setToolTip("Paese associato alla localizzazione WGS84 della stazione.")

        # 3. Dates
        start_layout = QHBoxLayout()
        self.start_check = QCheckBox("Set")
        self.start_check.setToolTip("Abilita la data UTC di inizio validità dell'epoca stazione.")
        self.start_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_input.setDisplayFormat("yyyy-MM-ddTHH:mm:ss")
        self.start_input.setToolTip("Data e ora di inizio validità dell'epoca strumentale espresse in tempo coordinato universale (UTC).")
        self.start_input.setCalendarPopup(True)
        self.start_input.setEnabled(False)
        self.start_check.toggled.connect(self.start_input.setEnabled)
        start_layout.addWidget(self.start_check)
        start_layout.addWidget(self.start_input)
        
        end_layout = QHBoxLayout()
        self.end_check = QCheckBox("Set")
        self.end_check.setToolTip("Spuntando questo campo viene chiusa l'epoca della stazione con una data UTC esplicita per preservare la storia operativa FDSN.")
        self.end_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_input.setDisplayFormat("yyyy-MM-ddTHH:mm:ss")
        self.end_input.setToolTip("Data e ora di fine validità dell'epoca strumentale espresse in tempo coordinato universale (UTC).")
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
        self.delete_btn.setToolTip("Elimina la stazione e i canali associati rispettando i vincoli gerarchici del database SQLite.")
        self.delete_btn.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.delete_btn.setFixedWidth(130)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.hide()
        
        self.sync_yasmine_btn = QPushButton("☁️ Send to Yasmine")
        self.sync_yasmine_btn.setToolTip("Esporta la singola stazione in StationXML e la sincronizza con l'archivio Yasmine mantenendo lo stato di allineamento.")
        self.sync_yasmine_btn.setStyleSheet("background-color: #673AB7; color: white; font-weight: bold;")
        self.sync_yasmine_btn.setFixedWidth(150)
        self.sync_yasmine_btn.clicked.connect(self._on_sync_yasmine_clicked)
        self.sync_yasmine_btn.hide()

        self.auto_channels_btn = QPushButton("⚡ Auto-Generate 3 Channels")
        self.auto_channels_btn.setToolTip("Genera una terna SEED Z/N/E coerente con sample rate, risposta del sensore e convenzioni FDSN.")
        self.auto_channels_btn.setStyleSheet("background-color: #00897B; color: white; font-weight: bold;")
        self.auto_channels_btn.setFixedWidth(210)
        self.auto_channels_btn.clicked.connect(self._on_auto_generate_channels_clicked)
        self.auto_channels_btn.hide()
        
        self.save_btn = QPushButton("Save Station")
        self.save_btn.setToolTip("Persiste le modifiche correnti sul database SQLite attivando i relativi vincoli di integrità.")
        self.save_btn.setFixedWidth(150)
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.sync_yasmine_btn)
        btn_layout.addWidget(self.auto_channels_btn)
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
        self.auto_channels_btn.show()

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
        self.auto_channels_btn.hide()

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
                self.auto_channels_btn.show()
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
                    self.auto_channels_btn.hide()
                    QMessageBox.information(self, "Deleted", "Station successfully removed.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error during deletion: {e}")

    def _on_auto_generate_channels_clicked(self):
        if not self.current_station_id:
            QMessageBox.warning(self, "Warning", "Save/select a station before generating channels.")
            return
        if not self.cha_ctrl:
            QMessageBox.warning(self, "Warning", "Channel controller not available.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Auto-Generate 3 Channels")
        layout = QFormLayout(dialog)

        dl_combo = QComboBox()
        dl_combo.setEditable(True)
        dl_combo.setToolTip("Seleziona un datalogger validato dall'inventario centralizzato; il sample rate determina il Band Code SEED proposto.")
        for d in self.eq_ctrl.get_all_dataloggers():
            dl_combo.addItem(f"{d.manufacturer} {d.model}", d.id)

        sensor_combo = QComboBox()
        sensor_combo.setEditable(True)
        sensor_combo.setToolTip("Seleziona un modello validato dall'inventario centralizzato. La classificazione fisica del sensore guida Instrument Code e Sensor Type FDSN.")
        for s in self.eq_ctrl.get_all_sensors():
            sensor_combo.addItem(f"{s.manufacturer} {s.model}", s.id)

        depth_input = QDoubleSpinBox()
        depth_input.setRange(0, 10000)
        depth_input.setSuffix(" m")
        depth_input.setToolTip("Profondità del sensore rispetto al riferimento stazione, espressa in metri.")

        sample_rate_label = QLineEdit()
        sample_rate_label.setReadOnly(True)
        sample_rate_label.setPlaceholderText("100.0 Hz")
        sample_rate_label.setToolTip("Frequenza finale di campionamento estratta dalla catena di decimazione del datalogger, espressa in Hertz (Hz).")

        inst_code = QComboBox()
        inst_code.setEditable(True)
        inst_code.addItems(["H", "L", "N", "G", "M"])
        inst_code.setToolTip("Seconda lettera SEED: H per velocimetri, N per accelerometri, secondo input units e standard FDSN.")

        band_code = QComboBox()
        band_code.setEditable(True)
        band_code.addItems(["F", "C", "H", "B", "M", "L", "V", "U", "R", "E", "S", "G"])
        band_code.setToolTip("Prima lettera SEED: codifica la banda di frequenza del canale in funzione del sample rate e della risposta fisica dello strumento.")

        sensor_type = QComboBox()
        sensor_type.addItem("Broad Band (BB)", True)
        sensor_type.addItem("Short Period (SP)", False)
        sensor_type.setToolTip("Classificazione broadband o short-period usata per proporre il Band Code SEED; resta modificabile manualmente prima della generazione.")

        start_time_input = QDateTimeEdit(QDateTime.currentDateTime())
        start_time_input.setDisplayFormat("yyyy-MM-ddTHH:mm:ss")
        start_time_input.setCalendarPopup(True)
        start_time_input.setToolTip("Data e ora di inizio validità dei tre canali generati, in tempo coordinato universale (UTC).")

        def _update_sample_rate_preview():
            datalogger_id = dl_combo.currentData()
            if datalogger_id is None:
                sample_rate_label.setText("N/A")
                return
            sample_rate = self.cha_ctrl.get_datalogger_sample_rate(datalogger_id)
            is_bb = bool(sensor_type.currentData())
            proposed_band = get_fdsn_band_code(
                sample_rate,
                is_bb,
                instrument_code=inst_code.currentText(),
            )
            idx_band = band_code.findText(proposed_band)
            if idx_band < 0:
                band_code.addItem(proposed_band)
                idx_band = band_code.findText(proposed_band)
            if idx_band >= 0:
                band_code.setCurrentIndex(idx_band)
            sample_rate_label.setText(f"{sample_rate:.6g} Hz")

        dl_combo.currentIndexChanged.connect(_update_sample_rate_preview)

        def _sync_sensor_fdsn_defaults():
            sensor_id = sensor_combo.currentData()
            if sensor_id is None:
                return
            sensor = self.eq_ctrl.get_sensor(sensor_id)
            if not sensor:
                return

            code = get_instrument_code(getattr(sensor, "input_units", ""))
            idx_code = inst_code.findText(code)
            if idx_code < 0:
                inst_code.addItem(code)
                idx_code = inst_code.findText(code)
            if idx_code >= 0:
                inst_code.setCurrentIndex(idx_code)

            is_bb = is_broadband_from_poles(
                getattr(sensor, "poles", []),
                pz_transfer_function_type=getattr(
                    sensor, "pz_transfer_function_type", "LAPLACE (RADIANS/SECOND)"
                ),
            )
            idx_type = sensor_type.findData(bool(is_bb))
            if idx_type >= 0:
                sensor_type.setCurrentIndex(idx_type)
            _update_sample_rate_preview()

        sensor_combo.currentIndexChanged.connect(_sync_sensor_fdsn_defaults)
        sensor_type.currentIndexChanged.connect(_update_sample_rate_preview)
        inst_code.currentTextChanged.connect(_update_sample_rate_preview)
        _sync_sensor_fdsn_defaults()
        _update_sample_rate_preview()

        layout.addRow("Datalogger:", dl_combo)
        layout.addRow("Detected Sample Rate:", sample_rate_label)
        layout.addRow("Band Code (1st Letter):", band_code)
        layout.addRow("Sensor:", sensor_combo)
        layout.addRow("Depth:", depth_input)
        layout.addRow("Start Time:", start_time_input)
        layout.addRow("Instrument Code:", inst_code)
        layout.addRow("Sensor Type:", sensor_type)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dl_combo.currentData() is None or sensor_combo.currentData() is None:
            QMessageBox.warning(self, "Warning", "Select both datalogger and sensor.")
            return

        try:
            created = self.cha_ctrl.auto_generate_triaxial_channels(
                self.current_station_id,
                dl_combo.currentData(),
                sensor_combo.currentData(),
                depth_input.value(),
                inst_code.currentText().strip(),
                bool(sensor_type.currentData()),
                start_time_input.dateTime().toString("yyyy-MM-ddTHH:mm:ss"),
                band_code=band_code.currentText().strip(),
            )
        except Exception as e:
            logger.error("Auto-generate channels failed: %s", e)
            QMessageBox.critical(self, "Error", f"Unable to generate channels:\n{e}")
            return

        app_signals.channel_updated.emit()
        app_signals.station_updated.emit()
        QMessageBox.information(self, "Channels Created", f"Created {len(created)} channel(s).")

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