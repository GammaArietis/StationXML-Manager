import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QSplitter, QMessageBox, QLabel, QListWidget,
                             QListWidgetItem, QGroupBox)
from PyQt6.QtCore import Qt
from core.models.base_models import Operator
from ui.components.searchable_dialog import SearchableItemDialog
from utils.signals import app_signals

logger = logging.getLogger(__name__)

class OperatorCatalogTab(QWidget):
    def __init__(self, equip_ctrl):
        super().__init__()
        self.eq_ctrl = equip_ctrl
        self.current_op = None
        self._selected_op_id = None
        self._setup_ui()
        self.refresh_list()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- LEFT: List ---
        left_widget = QWidget(); left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("<b>Operators / Managers</b>"))
        
        self.op_list = QListWidget()
        self.op_list.itemClicked.connect(self._load_selected_operator)
        left_layout.addWidget(self.op_list)
        
        self.new_btn = QPushButton("➕ New Operator")
        self.new_btn.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.new_btn.clicked.connect(self._prepare_new_operator)
        left_layout.addWidget(self.new_btn)
        self.splitter.addWidget(left_widget)
        
        # --- RIGHT: Editor ---
        editor_widget = QWidget(); editor_layout = QVBoxLayout(editor_widget)
        info_group = QGroupBox("Operator Contact Sheet")
        form = QFormLayout(info_group)
        
        self.agency_input = QLineEdit()
        self.name_input = QLineEdit()
        self.email_input = QLineEdit()
        self.web_input = QLineEdit()
        self.phone_input = QLineEdit()
        
        form.addRow("Agency / Entity:", self.agency_input)
        form.addRow("Contact Name:", self.name_input)
        form.addRow("Email:", self.email_input)
        form.addRow("Website:", self.web_input)
        form.addRow("Phone:", self.phone_input)
        
        editor_layout.addWidget(info_group)
        
        self.save_btn = QPushButton("💾 SAVE TO CATALOG")
        self.save_btn.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; height: 35px;")
        self.save_btn.clicked.connect(self._on_save_clicked)
        editor_layout.addWidget(self.save_btn)
        
        danger_layout = QHBoxLayout()
        self.clone_btn = QPushButton("👯 Clone"); self.clone_btn.setStyleSheet("background-color: #8E24AA; color: white;"); self.clone_btn.clicked.connect(self._on_clone_clicked); self.clone_btn.setEnabled(False)
        self.replace_btn = QPushButton("🔄 Replace"); self.replace_btn.setStyleSheet("background-color: #F57C00; color: white;"); self.replace_btn.clicked.connect(self._on_replace_clicked); self.replace_btn.setEnabled(False)
        self.delete_btn = QPushButton("🗑️ Delete"); self.delete_btn.setStyleSheet("background-color: #C62828; color: white;"); self.delete_btn.clicked.connect(self._on_delete_clicked); self.delete_btn.setEnabled(False)
        danger_layout.addWidget(self.clone_btn); danger_layout.addWidget(self.replace_btn); danger_layout.addWidget(self.delete_btn)
        editor_layout.addLayout(danger_layout)
        
        editor_layout.addStretch()
        self.splitter.addWidget(editor_widget)
        self.splitter.setSizes([350, 650]); layout.addWidget(self.splitter)

    def refresh_list(self):
        """Reloads the list displaying 'Entity - Manager'."""
        self.op_list.clear()
        operators = self.eq_ctrl.get_all_operators()
        for op in operators:
            display_text = op.agency
            if op.contact_name:
                display_text = f"{op.agency} — {op.contact_name}"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, op)
            self.op_list.addItem(item)

    def _prepare_new_operator(self):
        self.current_op = Operator(agency="")
        self._selected_op_id = None
        self.agency_input.clear(); self.name_input.clear(); self.email_input.clear()
        self.web_input.clear(); self.phone_input.clear(); self.op_list.clearSelection()
        self.clone_btn.setEnabled(False); self.replace_btn.setEnabled(False); self.delete_btn.setEnabled(False)

    def _load_selected_operator(self, item):
        op_brief = item.data(Qt.ItemDataRole.UserRole)
        oid = getattr(op_brief, "id", None)
        self._selected_op_id = oid
        self.current_op = self.eq_ctrl.get_operator_by_id(oid) if oid else op_brief
        if not self.current_op:
            self.current_op = op_brief
        self.agency_input.setText(self.current_op.agency)
        self.name_input.setText(self.current_op.contact_name or "")
        self.email_input.setText(self.current_op.contact_email or "")
        self.web_input.setText(self.current_op.website or "")
        self.phone_input.setText(self.current_op.phone_number or "")
        self.clone_btn.setEnabled(bool(oid))
        self.replace_btn.setEnabled(bool(oid))
        self.delete_btn.setEnabled(bool(oid))

    def _select_op_row_by_id(self, operator_id: int) -> None:
        for i in range(self.op_list.count()):
            it = self.op_list.item(i)
            op = it.data(Qt.ItemDataRole.UserRole)
            if op is not None and getattr(op, "id", None) == operator_id:
                self.op_list.setCurrentItem(it)
                self.op_list.scrollToItem(it)
                self._load_selected_operator(it)
                return

    def _on_clone_clicked(self):
        oid = self._selected_op_id
        if oid is None and self.current_op and self.current_op.id:
            oid = self.current_op.id
        if oid is None:
            QMessageBox.warning(self, "Clone", "Select a saved catalog operator first.")
            return
        src = self.eq_ctrl.get_operator_by_id(oid)
        if not src:
            QMessageBox.warning(self, "Clone", "Operator not found in catalog.")
            return
        dup = self.eq_ctrl.clone_operator_model(src)
        saved = self.eq_ctrl.save_operator(dup)
        if not saved:
            QMessageBox.warning(
                self, "Clone", "Could not save the duplicate (unique constraint?)."
            )
            return
        self.refresh_list()
        self._select_op_row_by_id(saved.id)
        self.current_op = saved
        self._selected_op_id = saved.id
        self.clone_btn.setEnabled(True)
        self.replace_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        QMessageBox.information(self, "Cloned", f"Created in catalog: {saved.agency}")
        app_signals.equipment_updated.emit()

    @staticmethod
    def _operator_display_label(op: Operator) -> str:
        if op.contact_name:
            return f"{op.agency} — {op.contact_name}"
        return op.agency

    def _on_replace_clicked(self):
        oid = self._selected_op_id or (self.current_op.id if self.current_op else None)
        if not oid:
            return
        others = [o for o in self.eq_ctrl.get_all_operators() if o.id != oid]
        if not others:
            QMessageBox.information(self, "Replace", "No other operators in the catalog.")
            return
        choices = [(self._operator_display_label(o), o.id) for o in others]
        new_id, ok = SearchableItemDialog.get_item(
            choices,
            title="Replace Operator",
            placeholder="Cerca...",
            parent=self,
        )
        if ok and new_id:
            if self.eq_ctrl.replace_operator(oid, new_id):
                self.refresh_list()
                self._select_op_row_by_id(new_id)
                app_signals.equipment_updated.emit()
                app_signals.network_updated.emit()
                app_signals.station_updated.emit()

    def _on_save_clicked(self):
        agency = self.agency_input.text().strip()
        if not agency:
            QMessageBox.warning(self, "Error", "Agency is required.")
            return
            
        op_id = self.current_op.id if self.current_op else None
        new_op = Operator(
            id=op_id, agency=agency,
            contact_name=self.name_input.text().strip(),
            contact_email=self.email_input.text().strip(),
            website=self.web_input.text().strip(),
            phone_number=self.phone_input.text().strip()
        )
        
        if self.eq_ctrl.save_operator(new_op):
            self.refresh_list()
            app_signals.equipment_updated.emit()

    def _on_delete_clicked(self):
        if self.current_op and self.current_op.id:
            if QMessageBox.question(self, "Delete", f"Delete {self.current_op.agency}?") == QMessageBox.StandardButton.Yes:
                if self.eq_ctrl.delete_operator(self.current_op.id):
                    self._prepare_new_operator(); self.refresh_list(); app_signals.equipment_updated.emit()
