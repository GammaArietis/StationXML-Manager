from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QLabel, QPushButton, QDialogButtonBox, QMessageBox)
from PyQt6.QtCore import Qt

class AROLBrowserDialog(QDialog):
    def __init__(self, arol_client, category='sensors', parent=None):
        super().__init__(parent)
        self.client = arol_client
        self.category = category
        self.selected_object = None
        
        self.setWindowTitle(f"Browse AROL Library - {category.capitalize()}")
        self.setMinimumSize(600, 400)
        
        self._setup_ui()
        self._load_manufacturers()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel(f"Select an atomic component from <b>AROL</b> ({self.category}):"))
        
        lists_layout = QHBoxLayout()
        
        mfg_lay = QVBoxLayout()
        mfg_lay.addWidget(QLabel("Manufacturer:"))
        self.mfg_list = QListWidget()
        self.mfg_list.currentRowChanged.connect(self._on_mfg_selected)
        mfg_lay.addWidget(self.mfg_list)
        lists_layout.addLayout(mfg_lay)
        
        model_lay = QVBoxLayout()
        model_lay.addWidget(QLabel("Model (YAML):"))
        self.model_list = QListWidget()
        self.model_list.currentRowChanged.connect(self._on_model_selected)
        model_lay.addWidget(self.model_list)
        lists_layout.addLayout(model_lay)
        
        layout.addLayout(lists_layout)
        
        layout.addWidget(QLabel("Metadata Preview:"))
        self.preview_label = QLabel("<i>Select a model to see the description...</i>")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("background-color: #2c2c2c; padding: 10px; border-radius: 5px;")
        layout.addWidget(self.preview_label)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _load_manufacturers(self):
        mfgs = self.client.get_manufacturers(self.category)
        if not mfgs:
            QMessageBox.warning(self, "Empty Library", f"No manufacturers found in AROL/{self.category}")
            return
        self.mfg_list.addItems(mfgs)

    def _on_mfg_selected(self, index):
        self.model_list.clear()
        self.preview_label.setText("...")
        if index < 0: return
        
        mfg = self.mfg_list.currentItem().text()
        models = self.client.get_models(self.category, mfg)
        self.model_list.addItems(models)

    def _on_model_selected(self, index):
        if index < 0: return
        
        mfg = self.mfg_list.currentItem().text()
        model = self.model_list.currentItem().text()
        
        obj = self.client.load_component(self.category, mfg, model)
        if obj:
            desc = getattr(obj, 'description', 'No description available.')
            self.preview_label.setText(f"<b>{model}</b><br>{desc}")
        else:
            self.preview_label.setText("Error loading YAML file.")

    def _on_accept(self):
        if not self.mfg_list.currentItem() or not self.model_list.currentItem():
            QMessageBox.warning(self, "Warning", "Select both a manufacturer and a model!")
            return
            
        mfg = self.mfg_list.currentItem().text()
        model = self.model_list.currentItem().text()
        
        self.selected_object = self.client.load_component(self.category, mfg, model)
        self.accept()