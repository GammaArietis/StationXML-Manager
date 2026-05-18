import os
import json
import re
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QLabel, QMessageBox, QProgressBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from utils.nrl_client import NRLManager

class NRLWorker(QThread):
    finished_options = pyqtSignal(list)
    finished_download = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, manager, action_type, equip_type, keys):
        super().__init__()
        self.manager = manager
        self.action_type = action_type
        self.equip_type = equip_type
        self.keys = keys

    def run(self):
        try:
            if self.action_type == 'options':
                if self.equip_type == 'sensor':
                    opts = self.manager.get_sensor_options(*self.keys)
                else:
                    opts = self.manager.get_datalogger_options(*self.keys)
                self.finished_options.emit(opts if opts is not None else [])
                
            elif self.action_type == 'download':
                if self.equip_type == 'sensor':
                    result = self.manager.fetch_sensor(self.keys)
                else:
                    result = self.manager.fetch_datalogger(self.keys)
                self.finished_download.emit(result)
        except Exception as e:
            self.error.emit(str(e))

class NRLBrowserDialog(QDialog):
    def __init__(self, equip_type, search_query="", parent=None):
        super().__init__(parent)
        self.equip_type = equip_type
        self.search_query = search_query
        self.setWindowTitle(f"NRL Library - {equip_type.upper()}")
        self.setToolTip("Navigazione del catalogo ufficiale delle risposte strumentali Nominal Response Library. Consente l'importazione diretta di poli, zeri e stadi di decimazione standard.")
        self.resize(550, 500)
        
        self.nrl_manager = NRLManager()
        self.current_keys = []
        self.downloaded_item = None
        self.btn_suggestion = None
        
        self._setup_ui()
        self._try_suggest_match() 
        self._load_options()

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)

        self.lbl_path = QLabel("Path: /")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setToolTip("Percorso gerarchico NRL corrente: manufacturer, modello, gain, sample rate o variante di response stage.")
        self.lbl_path.setStyleSheet("font-weight: bold; color: #333;")
        self.main_layout.addWidget(self.lbl_path)
        
        self.list_widget = QListWidget()
        self.list_widget.setToolTip("Doppio clic su una voce per scendere nella gerarchia NRL fino alla configurazione strumentale importabile.")
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.main_layout.addWidget(self.list_widget)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(2)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.main_layout.addWidget(self.progress)
        
        btn_layout = QHBoxLayout()
        self.btn_back = QPushButton("⬅ Back")
        self.btn_back.setToolTip("Torna al livello superiore della gerarchia NRL mantenendo il percorso di risposta strumentale.")
        self.btn_back.clicked.connect(self._go_back)
        
        self.btn_download = QPushButton("⬇ Download and Import")
        self.btn_download.setToolTip("Importa il modello NRL selezionato convertendo risposta, poli/zeri, gain e stadi digitali nel catalogo locale.")
        self.btn_download.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 5px 15px;")
        self.btn_download.clicked.connect(self._download_item)
        self.btn_download.hide()
        
        btn_layout.addWidget(self.btn_back)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_download)
        
        self.main_layout.addLayout(btn_layout)

    def _try_suggest_match(self):
        """Intelligent Suggestion Engine (Max Overlap)"""
        if not self.search_query:
            return
            
        cache_path = "data/nrl_math_cache.json"
        if not os.path.exists(cache_path):
            return

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                
            group = cache.get('sensors' if self.equip_type == 'sensor' else 'dataloggers', {})
            
            stopwords = {"SENSOR", "SENS", "INGV", "VEL", "ACC", "XYZ", "MODEL", "DATALOGGER", "LOGGER", "ACQ", "NONE"}
            query_words = {w for w in re.findall(r'\w+', self.search_query.upper()) if len(w) > 1 and w not in stopwords}
            
            if not query_words:
                return

            best_match_path = None
            max_overlap = 0

            for n_hash, n_names in group.items():
                for full_name in n_names:
                    nrl_words = {w for w in re.findall(r'\w+', full_name.upper()) if len(w) > 1 and w not in stopwords}
                    overlap = len(query_words & nrl_words)
                    
                    if overlap > max_overlap:
                        max_overlap = overlap
                        best_match_path = full_name 

            if best_match_path and max_overlap > 0:
                parts = [p.strip() for p in best_match_path.split("->")]
                display_name = f"{parts[0]} {parts[1]}" if len(parts) > 1 else parts[0]
                
                self.btn_suggestion = QPushButton(f"💡 Suggestion Found: {display_name}\nClick to automatically import this model")
                self.btn_suggestion.setToolTip("Suggerimento basato sull'indice matematico locale NRL: importa la risposta nominale più compatibile con marca/modello corrente.")
                self.btn_suggestion.setStyleSheet("""
                    QPushButton {
                        background-color: #FFF9C4; 
                        color: #000; 
                        font-weight: bold; 
                        padding: 10px; 
                        border: 2px solid #FBC02D; 
                        border-radius: 6px;
                    }
                    QPushButton:hover { background-color: #FFF59D; }
                """)
                self.btn_suggestion.clicked.connect(lambda: self._apply_suggestion(parts))
                
                self.main_layout.insertWidget(0, self.btn_suggestion)
                
        except Exception as e:
            print(f"Error during NRL suggestion: {e}")

    def _apply_suggestion(self, path_parts):
        """Bypasses navigation and directly starts the download"""
        self.current_keys = path_parts
        if self.btn_suggestion:
            self.btn_suggestion.hide()
        self._download_item()

    def _update_ui_state(self, loading=False, is_leaf=False):
        self.progress.setVisible(loading)
        self.list_widget.setEnabled(not loading)
        self.btn_back.setEnabled(len(self.current_keys) > 0 and not loading)
        
        path_str = " -> ".join(self.current_keys) if self.current_keys else "Home"
        
        if is_leaf:
            self.list_widget.hide()
            self.btn_download.show()
            self.lbl_path.setText(f"<span style='color: green;'>Ready Configuration:</span><br>{path_str}")
        else:
            self.list_widget.show()
            self.btn_download.hide()
            self.lbl_path.setText(f"Path: {path_str}")

    def _load_options(self):
        self._update_ui_state(loading=True)
        self.worker = NRLWorker(self.nrl_manager, 'options', self.equip_type, self.current_keys)
        self.worker.finished_options.connect(self._on_options_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_options_loaded(self, options):
        self.list_widget.clear()
        if not options:
            self._update_ui_state(loading=False, is_leaf=True)
            return
        self.list_widget.addItems(options)
        self._update_ui_state(loading=False, is_leaf=False)

    def _on_item_double_clicked(self, item):
        self.current_keys.append(item.text())
        self._load_options()

    def _go_back(self):
        if self.current_keys:
            self.current_keys.pop()
            self._load_options()

    def _download_item(self):
        self._update_ui_state(loading=True, is_leaf=True)
        self.btn_download.setEnabled(False)
        self.btn_back.setEnabled(False)
        
        self.worker = NRLWorker(self.nrl_manager, 'download', self.equip_type, self.current_keys)
        self.worker.finished_download.connect(self._on_download_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_download_finished(self, result_item):
        self._update_ui_state(loading=False, is_leaf=True)
        if result_item:
            self.downloaded_item = result_item
            QMessageBox.information(self, "Success", "Import completed!")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Error in download.")
            self.btn_download.setEnabled(True)
            self.btn_back.setEnabled(True)

    def _on_error(self, err_msg):
        self._update_ui_state(loading=False, is_leaf=False)
        QMessageBox.critical(self, "Error", f"Error: {err_msg}")
        self._go_back()