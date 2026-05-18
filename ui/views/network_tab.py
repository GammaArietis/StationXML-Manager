import json
import logging

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout,
                             QLineEdit, QPushButton, QMessageBox,
                             QDateTimeEdit, QCheckBox, QHBoxLayout, QComboBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox)
from PyQt6.QtCore import Qt, QDateTime

from core.models.base_models import Network
from utils.signals import app_signals

logger = logging.getLogger(__name__)

class NetworkTab(QWidget):
    def __init__(self, network_ctrl, equip_ctrl):
        super().__init__()
        self.net_ctrl = network_ctrl
        self.eq_ctrl = equip_ctrl
        self.current_network_id = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        form_layout = QFormLayout()
        
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("IV o IU")
        self.code_input.setToolTip("Codice univoco della rete sismica permanente o temporanea registrato presso FDSN (2 caratteri).")
        self.code_input.setMaxLength(10)
        
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Italian National Seismic Network")
        self.desc_input.setToolTip("Nome esteso o istituzione responsabile della gestione e manutenzione della rete sismica.")

        self.doi_input = QLineEdit()
        self.doi_input.setPlaceholderText("10.13127/SD/X0ZHL9RE6W")
        self.doi_input.setToolTip("Identificatore DOI persistente della rete o del dataset secondo le pratiche di citazione FDSN.")
        
        # --- FDSN COMMENTS GROUP ---
        comm_group = QGroupBox("Network Comments (FDSN)")
        comm_lay = QVBoxLayout(comm_group)
        
        self.comm_table = QTableWidget(0, 5)
        self.comm_table.setHorizontalHeaderLabels(["Text", "Start (YYYY-MM-DD)", "End", "Subject", "Author (Name/Agency)"])
        self.comm_table.setToolTip("Doppio clic o selezione di una riga per caricare o correggere annotazioni FDSN con intervallo UTC nel metadata network.")
        self.comm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        comm_lay.addWidget(self.comm_table)
        
        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add Comment")
        add_btn.setToolTip("Aggiunge una nota FDSN con finestra temporale UTC per documentare eventi operativi della rete.")
        add_btn.clicked.connect(self._add_comment_row)
        rem_btn = QPushButton("- Remove Row")
        rem_btn.setToolTip("Rimuove la nota FDSN selezionata dalla serializzazione StationXML della rete.")
        rem_btn.clicked.connect(self._remove_comment_row)
        btns.addWidget(add_btn)
        btns.addWidget(rem_btn)
        comm_lay.addLayout(btns)

        self.operator_combo = QComboBox()
        self.operator_combo.setToolTip("Agenzia responsabile della gestione operativa, manutenzione e distribuzione dei metadati della rete.")

        self.restricted_combo = QComboBox()
        self.restricted_combo.addItems(["open", "closed", "partial"])
        self.restricted_combo.setToolTip("Stato FDSN restrictedStatus: definisce se metadati e dati associati sono pubblici, chiusi o parzialmente vincolati.")
        
        start_layout = QHBoxLayout()
        self.start_check = QCheckBox("Set")
        self.start_check.setToolTip("Abilita la serializzazione della data di inizio validità della rete in tempo coordinato universale (UTC).")
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
        self.end_check.setToolTip("Spuntando questo campo viene chiusa l'epoca FDSN della rete con una data UTC esplicita.")
        self.end_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_input.setDisplayFormat("yyyy-MM-ddTHH:mm:ss")
        self.end_input.setToolTip("Data e ora di fine validità dell'epoca strumentale espresse in tempo coordinato universale (UTC).")
        self.end_input.setCalendarPopup(True)
        self.end_input.setEnabled(False)
        self.end_check.toggled.connect(self.end_input.setEnabled)
        end_layout.addWidget(self.end_check)
        end_layout.addWidget(self.end_input)

        form_layout.addRow("Network Code (*):", self.code_input)
        form_layout.addRow("Description:", self.desc_input)
        form_layout.addRow("Network DOI:", self.doi_input)
        form_layout.addRow(comm_group)
        form_layout.addRow("Operator:", self.operator_combo)
        form_layout.addRow("Restricted Status:", self.restricted_combo)
        form_layout.addRow("Start Date:", start_layout)
        form_layout.addRow("End Date:", end_layout)
        
        main_layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        
        self.delete_btn = QPushButton("Delete Network")
        self.delete_btn.setToolTip("Elimina la rete e la gerarchia sismica associata rispettando i vincoli di integrità del database SQLite.")
        self.delete_btn.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.delete_btn.setFixedWidth(120)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.hide()
        
        self.save_btn = QPushButton("Save Network")
        self.save_btn.setToolTip("Persiste le modifiche correnti sul database SQLite attivando i relativi vincoli di integrità.")
        self.save_btn.setFixedWidth(150)
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.delete_btn)
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

    def refresh_catalog_combos(self):
        self.operator_combo.clear()
        self.operator_combo.addItem("--- No Operator ---", None)
        for op in self.eq_ctrl.get_all_operators():
            label = op.agency
            if op.contact_name:
                label += f" ({op.contact_name})"
            self.operator_combo.addItem(label, op.id)

    def load_network_data(self, network: Network):
        self.current_network_id = network.id
        self.code_input.setText(network.code)
        self.desc_input.setText(network.description or "")
        self.doi_input.setText(getattr(network, 'doi', "") or "")
        
        self._load_comments(network.comments)
        
        idx_res = self.restricted_combo.findText(network.restricted_status or "open")
        if idx_res >= 0: self.restricted_combo.setCurrentIndex(idx_res)

        self.refresh_catalog_combos()
        if network.operator_id:
            idx = self.operator_combo.findData(network.operator_id)
            if idx >= 0: self.operator_combo.setCurrentIndex(idx)
        
        if network.start_date:
            self.start_check.setChecked(True)
            self.start_input.setDateTime(QDateTime.fromString(network.start_date, "yyyy-MM-ddTHH:mm:ss"))
        else:
            self.start_check.setChecked(False)
            
        if network.end_date:
            self.end_check.setChecked(True)
            self.end_input.setDateTime(QDateTime.fromString(network.end_date, "yyyy-MM-ddTHH:mm:ss"))
        else:
            self.end_check.setChecked(False)
        
        self.delete_btn.show()

    def prepare_new_network(self):
        self.current_network_id = None
        self.code_input.clear()
        self.desc_input.clear()
        self.doi_input.clear()
        self.comm_table.setRowCount(0)
        
        self.refresh_catalog_combos()
        self.operator_combo.setCurrentIndex(0)
        self.restricted_combo.setCurrentIndex(0)
        
        self.start_input.setDateTime(QDateTime.currentDateTime())
        self.start_check.setChecked(False)
        self.end_input.setDateTime(QDateTime.currentDateTime())
        self.end_check.setChecked(False)
        
        self.delete_btn.hide()

    def _on_save_clicked(self):
        code = self.code_input.text().strip().upper()
        if not code:
            QMessageBox.warning(self, "Error", "Network Code is required!")
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

        network_data = Network(
            id=self.current_network_id,
            code=code,
            description=self.desc_input.text().strip() or None,
            doi=self.doi_input.text().strip() or None,
            start_date=start_str,
            end_date=end_str,
            operator_id=self.operator_combo.currentData(),
            restricted_status=self.restricted_combo.currentText(),
            comments=comments_json
        )
        
        try:
            saved_net = self.net_ctrl.save_network(network_data)
            if saved_net:
                self.current_network_id = saved_net.id
                QMessageBox.information(self, "Success", f"Network {saved_net.code} saved!")
                app_signals.network_updated.emit()
                self.delete_btn.show()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unable to save:\n{str(e)}")
            
    def _on_delete_clicked(self):
        if not self.current_network_id: return
        msg = "Are you sure? Deleting the network will erase ALL connected stations and channels!"
        reply = QMessageBox.question(self, "Confirm Deletion", msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if self.net_ctrl.delete_network(self.current_network_id):
                    app_signals.network_updated.emit()
                    self.prepare_new_network()
                    QMessageBox.information(self, "Deleted", "Network deleted successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error during deletion: {e}")