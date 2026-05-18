import logging
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget)
from ui.views.sensor_catalog_tab import SensorCatalogTab
from ui.views.preamplifier_catalog_tab import PreamplifierCatalogTab
from ui.views.datalogger_catalog_tab import DataloggerCatalogTab
from ui.views.operator_catalog_tab import OperatorCatalogTab

logger = logging.getLogger(__name__)

class CatalogDialog(QDialog):
    def __init__(self, eq_ctrl, parent=None):
        super().__init__(parent)
        self.eq_ctrl = eq_ctrl
        self.setWindowTitle("Equipment and Operators Catalog")
        self.setToolTip("Catalogo centralizzato di sensori, datalogger, preamplificatori e operatori usato per costruire risposte StationXML coerenti.")
        self.resize(1200, 850)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setToolTip("Seleziona il dominio di catalogo da curare: sensori, datalogger, preamplificatori o operatori FDSN.")
        
        # Load the 4 definitive external modules
        self.sensor_tab = SensorCatalogTab(self.eq_ctrl)
        self.datalogger_tab = DataloggerCatalogTab(self.eq_ctrl)
        self.preamp_tab = PreamplifierCatalogTab(self.eq_ctrl)
        self.op_tab = OperatorCatalogTab(self.eq_ctrl)
        
        self.tabs.addTab(self.sensor_tab, "Sensors")
        self.tabs.addTab(self.datalogger_tab, "Dataloggers")
        self.tabs.addTab(self.preamp_tab, "Preamplifiers")
        self.tabs.addTab(self.op_tab, "Operators / Agencies")
        
        layout.addWidget(self.tabs)