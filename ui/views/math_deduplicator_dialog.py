import shutil
from datetime import datetime

import json
import hashlib
import logging
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                             QWidget, QTreeWidget, QTreeWidgetItem, QPushButton,
                             QLabel, QComboBox, QMessageBox, QProgressDialog, QLineEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from utils.signals import app_signals
from utils.nrl_client import NRLManager

logger = logging.getLogger(__name__)

# =====================================================================
# GLOBAL HASHING FUNCTIONS (Shared between UI and Indexer)
# =====================================================================

def _format_sig(val):
    """Formats a number to 4 significant digits to avoid losing tiny poles."""
    if val is None: return "0"
    return f"{float(val):.4g}"
    
def get_sensor_hash(s):
    import hashlib
    sens = _format_sig(s.sensitivity)
    freq = _format_sig(s.frequency)
    a0 = _format_sig(s.normalization_factor)
    
    in_units = (s.input_units or "").strip().upper()
    out_units = (s.output_units or "").strip().upper()
    pz_type = (s.pz_transfer_function_type or "").strip().upper()
    
    # Support for attribute names (to avoid crashes)
    try:
        p_list = sorted([f"{_format_sig(p.real_val)},{_format_sig(p.imag_val)}" for p in s.poles])
        z_list = sorted([f"{_format_sig(z.real_val)},{_format_sig(z.imag_val)}" for z in s.zeros])
    except AttributeError:
        p_list = sorted([f"{_format_sig(p.real)},{_format_sig(p.imag)}" for p in s.poles])
        z_list = sorted([f"{_format_sig(z.real)},{_format_sig(z.imag)}" for z in s.zeros])
        
    # Build the fingerprint ONLY for Poles and Zeros
    pz_raw = f"{a0}_{pz_type}_P:{'|'.join(p_list)}_Z:{'|'.join(z_list)}"
    pz_hash = hashlib.sha256(pz_raw.encode()).hexdigest()[:8]
    
    # Return a two-compartment hash
    return f"SENS_G_{sens}_PZ_{pz_hash}"

def get_datalogger_hash(d):
    import hashlib, json
    gain = f"{float(d.gain or 0.0):.4f}"
    hw_d = f"{float(getattr(d, 'base_hardware_delay', 0.0) or 0.0):.4f}"
    f_hash = ""
    
    sorted_filters = sorted(d.filters, key=lambda x: getattr(x, 'stage_number', 0))
    
    for i, f in enumerate(sorted_filters, 1):
        rate = f"{float(f.input_sample_rate or 0.0):.2f}"
        raw = getattr(f, 'coefficients', '{}') or '{}'
        try:
            p = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(p, list): p = {"type": "FIR", "coefficients": p}
            
            t = p.get("type", "FIR")
            def _n(l): return "|".join([f"{float(v or 0.0):.6e}" for v in l])
            
            if t == "IIR":
                c = f"N:{_n(p.get('numerators', []))}D:{_n(p.get('denominators', []))}"
            elif t == "POLES":
                z = "|".join(sorted([f"{float(v[0] or 0.0):.4f},{float(v[1] or 0.0):.4f}" for v in p.get('zeros', [])]))
                pp = "|".join(sorted([f"{float(v[0] or 0.0):.4f},{float(v[1] or 0.0):.4f}" for v in p.get('poles', [])]))
                c = f"Z:{z}P:{pp}"
            else:
                c = f"C:{_n(p.get('coefficients', []))}"
            
            s_hash = hashlib.sha256(f"{t}_{f.decimation_factor}_{rate}_{c}".encode()).hexdigest()[:8]
            f_hash += f"S{i}_{s_hash}|"
        except:
            f_hash += f"S{i}_ERR|"
        
    return f"G_{gain}_H_{hw_d}_F_{f_hash}"
    
def get_preamplifier_hash(p):
    """
    Generates a unique hash based on the cascade of analog stages.
    """
    if not p:
        return "none"
    
    stages_data = []
    
    if hasattr(p, 'analog_stages') and p.analog_stages:
        for stage in p.analog_stages:
            stage_info = {
                "gain": float(stage.stage_gain),
                "poles": sorted([(float(pz.real_val), float(pz.imag_val)) for pz in stage.poles]),
                "zeros": sorted([(float(pz.real_val), float(pz.imag_val)) for pz in stage.zeros])
            }
            stages_data.append(stage_info)
    else:
        stages_data = [{"gain": 1.0, "poles": [], "zeros": []}]

    imprint = json.dumps(stages_data, sort_keys=True)
    return hashlib.sha256(imprint.encode()).hexdigest()

# =====================================================================
# NRL INDEXING ENGINE (Background Thread)
# =====================================================================
class NRLIndexerThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished_indexing = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.manager = NRLManager()

    def run(self):
        cache = {'sensors': {}, 'dataloggers': {}}
        try:
            # --- 1. SENSOR SCAN ---
            self.progress.emit(0, 0, "Mapping NRL Sensors tree in progress...")
            sensor_paths = []
            queue = [[]]
            while queue:
                curr = queue.pop(0)
                try:
                    opts = self.manager.get_sensor_options(*curr)
                    if opts is None:
                        sensor_paths.append(curr)
                    else:
                        for o in opts: queue.append(curr + [o])
                except Exception as e:
                    logger.warning(f"Ignored faulty NRL path {'/'.join(curr)}: {e}")

            total_s = len(sensor_paths)
            for i, path in enumerate(sensor_paths):
                path_str = " -> ".join(path)
                self.progress.emit(i, total_s, f"Calculating math: {path_str}")
                try:
                    model = self.manager.fetch_sensor(path)
                    if model:
                        h = get_sensor_hash(model)
                        if h not in cache['sensors']: cache['sensors'][h] = []
                        if path_str not in cache['sensors'][h]:
                            cache['sensors'][h].append(path_str)
                except Exception as e:
                    logger.warning(f"Unable to calculate hash for {path_str}: {e}")

            # --- 2. DATALOGGER SCAN ---
            self.progress.emit(0, 0, "Mapping NRL Dataloggers tree in progress...")
            dl_paths = []
            queue = [[]]
            while queue:
                curr = queue.pop(0)
                try:
                    opts = self.manager.get_datalogger_options(*curr)
                    if opts is None:
                        dl_paths.append(curr)
                    else:
                        for o in opts: queue.append(curr + [o])
                except Exception as e:
                    logger.warning(f"Ignored faulty NRL path {'/'.join(curr)}: {e}")

            total_d = len(dl_paths)
            for i, path in enumerate(dl_paths):
                path_str = " -> ".join(path)
                self.progress.emit(i, total_d, f"Calculating math: {path_str}")
                try:
                    model = self.manager.fetch_datalogger(path)
                    if model:
                        h = get_datalogger_hash(model)
                        if h not in cache['dataloggers']: cache['dataloggers'][h] = []
                        if path_str not in cache['dataloggers'][h]:
                            cache['dataloggers'][h].append(path_str)
                except Exception as e:
                    logger.warning(f"Unable to calculate hash for {path_str}: {e}")

            self.finished_indexing.emit(cache)
            
        except Exception as e:
            logger.error(f"Critical error in NRL indexing: {e}")
            self.finished_indexing.emit(cache)

# =====================================================================
# MAIN DIALOG WINDOW
# =====================================================================
class MathDeduplicatorDialog(QDialog):
    def __init__(self, eq_ctrl, parent=None):
        super().__init__(parent)
        self.eq_ctrl = eq_ctrl
        self.setWindowTitle("🔍 Mathematical Deduplicator & NRL Recognition")
        self.resize(1000, 700)
        
        self.sensor_groups = {}
        self.datalogger_groups = {}
        self.preamp_groups = {}
        
        self.cache_file = Path("data/nrl_math_cache.json")
        self.nrl_cache = {'sensors': {}, 'dataloggers': {}}
        self._load_cache()
        
        self._setup_ui()
        self._scan_database()

    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.nrl_cache = json.load(f)
            except:
                pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        info_text = ("This tool groups sensors and dataloggers based on their <b>math</b>. "
                     "If you generate the Local NRL Index, the software will automatically recognize your instruments!")
        lbl_info = QLabel(info_text)
        lbl_info.setWordWrap(True)
        lbl_info.setToolTip("Modulo di analisi matematica per la fusione di record strumentali identici. Identifica i duplicati tramite hash dei coefficienti e normalizza le relazioni nel DB sismico senza perdita di informazioni.")
        lbl_info.setStyleSheet("background-color: #212121; color: #FFFFFF; padding: 10px; border-radius: 5px; border: 1px solid #1976D2;")
        header_layout.addWidget(lbl_info, 1)
        
        self.btn_index = QPushButton("🛠️ Generate Local NRL Index")
        self.btn_index.setToolTip("Calcola un indice locale NRL basato su impronte matematiche di poli, zeri e coefficienti per riconoscere strumenti nominalmente equivalenti.")
        self.btn_index.setStyleSheet("background-color: #673AB7; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.btn_index.clicked.connect(self._generate_nrl_index)
        header_layout.addWidget(self.btn_index)
        layout.addLayout(header_layout)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filtra duplicati per marca/modello...")
        self.search_input.setToolTip("Filtra gruppi duplicati usando manufacturer/model mantenendo l'analisi basata su hash matematici della risposta strumentale.")
        self.search_input.textChanged.connect(self._filter_duplicate_trees)
        layout.addWidget(self.search_input)
        
        self.tabs = QTabWidget()
        
        self.tab_sensors = QWidget()
        lay_s = QVBoxLayout(self.tab_sensors)
        self.tree_sensors = QTreeWidget()
        self.tree_sensors.setHeaderLabels(["Model", "ID", "Poles/Zeros"])
        self.tree_sensors.setToolTip("Doppio clic o selezione di una riga per analizzare gruppi di sensori equivalenti tramite hash di poli, zeri e sensibilità.")
        self.tree_sensors.itemSelectionChanged.connect(lambda: self._on_group_selected('sensor'))
        lay_s.addWidget(self.tree_sensors)
        
        self.tab_dataloggers = QWidget()
        lay_d = QVBoxLayout(self.tab_dataloggers)
        self.tree_dataloggers = QTreeWidget()
        self.tree_dataloggers.setHeaderLabels(["Model", "ID", "Gain / Filters"])
        self.tree_dataloggers.setToolTip("Doppio clic o selezione di una riga per analizzare datalogger equivalenti tramite gain, coefficienti e stadi di decimazione.")
        self.tree_dataloggers.itemSelectionChanged.connect(lambda: self._on_group_selected('datalogger'))
        lay_d.addWidget(self.tree_dataloggers)

        self.tab_preamps = QWidget()
        lay_p = QVBoxLayout(self.tab_preamps)
        self.tree_preamps = QTreeWidget()
        self.tree_preamps.setHeaderLabels(["Model", "ID", "Poles/Zeros"])
        self.tree_preamps.setToolTip("Doppio clic o selezione di una riga per analizzare preamplificatori equivalenti tramite stadi analogici, gain e poli/zeri.")
        self.tree_preamps.itemSelectionChanged.connect(lambda: self._on_group_selected('preamplifier'))
        lay_p.addWidget(self.tree_preamps)
        
        self.tabs.addTab(self.tab_sensors, "Duplicate Sensors")
        self.tabs.addTab(self.tab_dataloggers, "Duplicate Dataloggers")
        self.tabs.addTab(self.tab_preamps, "Duplicate PreAmps")
        layout.addWidget(self.tabs)
        
        action_layout = QHBoxLayout()
        self.lbl_action = QLabel("<b>Master to keep:</b>")
        self.combo_master = QComboBox()
        self.combo_master.setToolTip("Record strumentale master che conserverà le relazioni canale dopo la fusione dei duplicati matematicamente equivalenti.")
        self.combo_master.setEnabled(False)
        
        self.btn_merge = QPushButton("🔗 Merge Group")
        self.btn_merge.setToolTip("Fonde il gruppo duplicato aggiornando le foreign key nel DB sismico e preservando le informazioni strumentali equivalenti.")
        self.btn_merge.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; padding: 5px 15px;")
        self.btn_merge.setEnabled(False)
        self.btn_merge.clicked.connect(self._perform_merge)
        
        action_layout.addWidget(self.lbl_action)
        action_layout.addWidget(self.combo_master, 1)
        action_layout.addWidget(self.btn_merge)
        layout.addLayout(action_layout)

    def _generate_nrl_index(self):
        msg = "This process will calculate the math of ALL instruments in your local NRL folder to create an internal search engine. It may take a few minutes. Proceed?"
        if QMessageBox.question(self, "Start Indexing", msg) != QMessageBox.StandardButton.Yes:
            return

        self.btn_index.setEnabled(False)
        self.progress_dlg = QProgressDialog("Starting NRL scan...", "Cancel", 0, 100, self)
        self.progress_dlg.setWindowTitle("NRL Indexing")
        self.progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dlg.setAutoClose(True)

        self.indexer_thread = NRLIndexerThread()
        self.indexer_thread.progress.connect(self._update_progress)
        self.indexer_thread.finished_indexing.connect(self._on_indexing_finished)
        self.indexer_thread.start()

    def _update_progress(self, current, total, message):
        if self.progress_dlg.wasCanceled():
            self.indexer_thread.terminate()
            self.btn_index.setEnabled(True)
            return
        self.progress_dlg.setMaximum(total if total > 0 else 100)
        self.progress_dlg.setValue(current)
        self.progress_dlg.setLabelText(message)

    def _on_indexing_finished(self, cache_data):
        self.progress_dlg.close()
        self.btn_index.setEnabled(True)
        self.nrl_cache = cache_data
        
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.nrl_cache, f, indent=4)
            
        QMessageBox.information(self, "Completed", "NRL Index generated successfully! Automatic recognition is active.")
        self._scan_database()

    def _scan_database(self):

        def analyze_datalogger_match(db_hash, db_model, nrl_cache):
            matches = {
                "PERFECT": [],       
                "PARTIAL": [],       
                "SUGGESTION": [],    
                "TEXT_ONLY": []      
            }

            def extract_components(h):
                try:
                    parts = h.split("_F_")
                    gain = float(parts[0].split("_")[1])
                    filters = [f.split("_")[1] for f in parts[1].split("|") if "_" in f]
                    return gain, "|".join(filters)
                except:
                    return 0.0, ""

            db_gain, db_filters_seq = extract_components(db_hash)
            
            if not db_filters_seq:
                db_filters_seq = "EMPTY"

            for nrl_hash, nrl_names in nrl_cache.items():
                if db_hash == nrl_hash:
                    matches["PERFECT"].extend(nrl_names)
                    continue

                nrl_gain, nrl_filters_seq = extract_components(nrl_hash)
                
                if db_filters_seq != "EMPTY":
                    if db_filters_seq in nrl_filters_seq or nrl_filters_seq in db_filters_seq:
                        if abs(db_gain - nrl_gain) < 0.001:
                            matches["PARTIAL"].extend(nrl_names)
                        else:
                            matches["SUGGESTION"].extend(nrl_names)
            
            if not matches["PERFECT"] and not matches["PARTIAL"] and not matches["SUGGESTION"]:
                if db_model:
                    clean_db_name = db_model.split("[")[0].strip().upper()
                    if len(clean_db_name) > 2:
                        for nrl_names_list in nrl_cache.values():
                            for name in nrl_names_list:
                                if clean_db_name in name.upper():
                                    if name not in matches["TEXT_ONLY"]:
                                        matches["TEXT_ONLY"].append(name)
                                        
            return matches

        def analyze_sensor_match(db_hash, sensor_obj, nrl_cache):
            matches = {"PERFECT": [], "PARTIAL": [], "SUGGESTION": [], "TEXT_ONLY": []}
            try:
                db_pz_hash = db_hash.split("_PZ_")[1]
            except:
                db_pz_hash = None

            for nrl_hash, nrl_names in nrl_cache.items():
                if db_hash == nrl_hash:
                    matches["PERFECT"].extend(nrl_names)
                elif db_pz_hash and f"_PZ_{db_pz_hash}" in nrl_hash:
                    matches["PARTIAL"].extend(nrl_names)
            
            if not matches["PERFECT"] and not matches["PARTIAL"] and not matches["SUGGESTION"]:
                mfg = str(getattr(sensor_obj, 'manufacturer', '') or '').upper()
                mod = str(getattr(sensor_obj, 'model', '') or '').upper()
                mod_clean = mod.split("-")[0].split(" ")[0] if mod else ""
                
                if mfg and mod_clean and mfg != "UNKNOWN":
                    for nrl_names in nrl_cache.values():
                        for name in nrl_names:
                            name_up = name.upper()
                            if mfg in name_up and mod_clean in name_up:
                                if name not in matches["TEXT_ONLY"]:
                                    matches["TEXT_ONLY"].append(name)
            return matches
        
        def extract_unique_models(nrl_path_list):
            unique_models = set()
            for path_str in nrl_path_list:
                parts = path_str.split(" -> ")
                if len(parts) >= 2:
                    unique_models.add(f"{parts[0]} {parts[1]}")
                else:
                    unique_models.add(path_str)
            return sorted(list(unique_models))

        self.tree_sensors.clear()
        self.tree_dataloggers.clear()
        self.tree_preamps.clear()
        
        self.sensor_groups.clear()
        self.datalogger_groups.clear()
        self.preamp_groups.clear()
        
        self.combo_master.clear()
        self.btn_merge.setEnabled(False)

        # ==========================================
        # 1. SENSORS
        # ==========================================
        for s in self.eq_ctrl.get_all_sensors():
            h = get_sensor_hash(s)
            if h not in self.sensor_groups: self.sensor_groups[h] = []
            self.sensor_groups[h].append(s)
            
        for h, items in self.sensor_groups.items():
            sens_cache = self.nrl_cache.get('sensors', {})
            match_results = analyze_sensor_match(h, items[0], sens_cache)
            
            if match_results["PERFECT"]:
                unique_count = len(extract_unique_models(match_results['PERFECT']))
                group_title = f"🌟 PERFECT ({unique_count} NRL variants) | {len(items)} loc."
                group_color = Qt.GlobalColor.darkGreen
            elif match_results["PARTIAL"]:
                unique_count = len(extract_unique_models(match_results['PARTIAL']))
                group_title = f"⚠️ WRONG GAIN (Correct poles) ({unique_count} variants) | {len(items)} loc."
                group_color = Qt.GlobalColor.darkYellow
            elif match_results["SUGGESTION"]:
                unique_count = len(extract_unique_models(match_results['SUGGESTION']))
                group_title = f"❌ ANOMALOUS (Poles/Zeros rounding) ({unique_count} variants) | {len(items)} loc."
                group_color = Qt.GlobalColor.red
            elif match_results["TEXT_ONLY"]:
                unique_count = len(extract_unique_models(match_results['TEXT_ONLY']))
                group_title = f"⚪ TEXT ONLY (Math missing/corrupted) ({unique_count} variants) | {len(items)} loc."
                group_color = Qt.GlobalColor.gray
            else:
                group_title = f"Group ({len(items)} local models)" if len(items) > 1 else "Single Model"
                group_color = None

            group_item = QTreeWidgetItem(self.tree_sensors, [group_title, "", f"Poles: {len(items[0].poles)} | Zeros: {len(items[0].zeros)}"])
            if group_color:
                group_item.setForeground(0, group_color)
            group_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "sensor_group", "hash": h, "items": items})
            
            if match_results["PERFECT"]:
                for match in extract_unique_models(match_results["PERFECT"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"✨ [PERFECT] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.darkGreen)
            elif match_results["PARTIAL"]:
                for match in extract_unique_models(match_results["PARTIAL"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"⚠️ [SUGGESTED - WRONG GAIN] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.darkYellow)
            elif match_results["SUGGESTION"]:
                for match in extract_unique_models(match_results["SUGGESTION"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"❌ [SUGGESTED - CORRUPTED] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.red)
            elif match_results["TEXT_ONLY"]:
                for match in extract_unique_models(match_results["TEXT_ONLY"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"⚪ [SUGGESTED - NAME ONLY] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.gray)
                
            for s in items:
                is_nrl = bool(getattr(s, 'nrl_path', None))
                icon = "🟢" if is_nrl else "🔴"
                QTreeWidgetItem(group_item, [f"{icon} {s.manufacturer} {s.model}", str(s.id), ""])
            group_item.setExpanded(True)


        # ==========================================
        # 2. DATALOGGERS
        # ==========================================
        for d in self.eq_ctrl.get_all_dataloggers():
            h = get_datalogger_hash(d)
            if h not in self.datalogger_groups: self.datalogger_groups[h] = []
            self.datalogger_groups[h].append(d)
            
        for h, items in self.datalogger_groups.items():
            dl_cache = self.nrl_cache.get('dataloggers', {})
            match_results = analyze_datalogger_match(h, items[0].model, dl_cache)

            if match_results["PERFECT"]:
                group_title = f"🌟 PERFECT ({len(extract_unique_models(match_results['PERFECT']))} NRL variants) | {len(items)} loc."
                group_color = Qt.GlobalColor.darkGreen
            elif match_results["PARTIAL"]:
                group_title = f"⚠️ PARTIAL (Missing stages) | {len(items)} loc."
                group_color = Qt.GlobalColor.darkYellow
            elif match_results["SUGGESTION"]:
                group_title = f"❌ ANOMALOUS (Different Gain/Stages) | {len(items)} loc."
                group_color = Qt.GlobalColor.red
            elif match_results["TEXT_ONLY"]:
                group_title = f"⚪ TEXT ONLY (Math missing/corrupted) | {len(items)} loc."
                group_color = Qt.GlobalColor.gray
            else:
                group_title = f"Group ({len(items)} local models)" if len(items) > 1 else "Single Model"
                group_color = None

            group_item = QTreeWidgetItem(self.tree_dataloggers, [group_title, "", f"Gain: {items[0].gain}"])
            if group_color:
                group_item.setForeground(0, group_color)
            group_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "datalogger_group", "hash": h, "items": items})
            
            if match_results["PERFECT"]:
                for match in extract_unique_models(match_results["PERFECT"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"✨ [PERFECT] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.darkGreen)
            elif match_results["PARTIAL"]:
                for match in extract_unique_models(match_results["PARTIAL"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"⚠️ [SUGGESTED - PARTIAL] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.darkYellow)
            elif match_results["SUGGESTION"]:
                for match in extract_unique_models(match_results["SUGGESTION"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"❌ [SUGGESTED - CORRUPTED] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.red)
            elif match_results["TEXT_ONLY"]:
                for match in extract_unique_models(match_results["TEXT_ONLY"]):
                    nrl_item = QTreeWidgetItem(group_item, [f"⚪ [SUGGESTED - NAME ONLY] {match}", "-", "-"])
                    nrl_item.setForeground(0, Qt.GlobalColor.gray)

            for d in items:
                is_nrl = bool(getattr(d, 'nrl_path', None))
                icon = "🟢" if is_nrl else "🔴"
                QTreeWidgetItem(group_item, [f"{icon} {d.manufacturer} {d.model}", str(d.id), ""])
            group_item.setExpanded(True)


        # ==========================================
        # 3. PREAMPLIFIERS
        # ==========================================
        for p in self.eq_ctrl.get_all_preamplifiers():
            h = get_preamplifier_hash(p)
            if h not in self.preamp_groups: self.preamp_groups[h] = []
            self.preamp_groups[h].append(p)
            
        for h, items in self.preamp_groups.items():
            first_p = items[0]
            total_poles = 0
            total_zeros = 0
            
            if hasattr(first_p, 'analog_stages') and first_p.analog_stages:
                for stage in first_p.analog_stages:
                    total_poles += len(stage.poles)
                    total_zeros += len(stage.zeros)
            
            group_title = f"Group ({len(items)} local models)" if len(items) > 1 else "Single Model"
            group_item = QTreeWidgetItem(self.tree_preamps, [group_title, "", f"Total Poles: {total_poles} | Total Zeros: {total_zeros}"])
            group_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "preamplifier_group", "hash": h, "items": items})
            
            for p in items:
                mfg = getattr(p, 'manufacturer', '')
                mod = getattr(p, 'model', '')
                p_id = getattr(p, 'id', '')
                QTreeWidgetItem(group_item, [f"🔴 {mfg} {mod}", str(p_id), ""])
            group_item.setExpanded(True)

        self.tree_sensors.resizeColumnToContents(0)
        self.tree_dataloggers.resizeColumnToContents(0)
        self.tree_preamps.resizeColumnToContents(0)
        self._filter_duplicate_trees(self.search_input.text())

    def _filter_duplicate_trees(self, text: str):
        needle = (text or "").strip().lower()
        for tree in (self.tree_sensors, self.tree_dataloggers, self.tree_preamps):
            for i in range(tree.topLevelItemCount()):
                group = tree.topLevelItem(i)
                group_match = needle in group.text(0).lower() if needle else True
                child_match = False
                for j in range(group.childCount()):
                    child = group.child(j)
                    visible = not needle or needle in child.text(0).lower()
                    child.setHidden(not visible)
                    child_match = child_match or visible
                group.setHidden(bool(needle and not (group_match or child_match)))
                if needle and (group_match or child_match):
                    group.setExpanded(True)

    def _on_group_selected(self, category):
        if category == 'sensor': tree = self.tree_sensors
        elif category == 'datalogger': tree = self.tree_dataloggers
        else: tree = self.tree_preamps
        
        selected = tree.selectedItems()
        self.combo_master.clear()
        self.btn_merge.setEnabled(False)
        self.combo_master.setEnabled(False)
        
        if not selected: return
        item = selected[0]
        if item.parent(): item = item.parent()
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data: return
        
        self.combo_master.setEnabled(True)
        self.btn_merge.setEnabled(True)
        self.current_group_category = category
        self.current_group_items = data["items"]
        
        for equip in self.current_group_items:
            mfg = getattr(equip, 'manufacturer', equip.get('manufacturer', '') if isinstance(equip, dict) else '')
            mod = getattr(equip, 'model', equip.get('model', '') if isinstance(equip, dict) else '')
            e_id = getattr(equip, 'id', equip.get('id', '') if isinstance(equip, dict) else '')
            desc = getattr(equip, 'description', equip.get('description', '') if isinstance(equip, dict) else '')
            
            is_nrl = "NRL" in (desc or "").upper()
            icon = "🟢" if is_nrl else "🔴"
            self.combo_master.addItem(f"{icon} {mfg} {mod} (ID: {e_id})", e_id)

    def _perform_merge(self):
        master_id = self.combo_master.currentData()
        if not master_id: return
        
        slaves = [eq for eq in self.current_group_items if eq.id != master_id]
        
        confirm = QMessageBox.question(self, "Confirm Merge",
            f"You are about to merge {len(slaves)} models into the selected Master.\n\n"
            f"The merged models will be deleted from the catalog and the channels will be updated.\nProceed?")
            
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                from core.config import get_settings

                db_path = get_settings().database_path
                if db_path.exists():
                    backup_dir = Path("backups")
                    backup_dir.mkdir(exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_file = backup_dir / f"stationxml_pre_merge_{timestamp}.db"
                    shutil.copy2(db_path, backup_file)
                    logger.info(f"Security backup created: {backup_file}")
            except Exception as e:
                logger.error(f"Unable to create backup: {e}")
            
            affected_stations = set()
            try:
                main_window = self.parent()
                if main_window and hasattr(main_window, 'sta_ctrl'):
                    with main_window.sta_ctrl.dao.db.get_connection() as conn:
                        cursor = conn.cursor()
                        col_name = f"{self.current_group_category}_id"
                        for slave in slaves:
                            cursor.execute(f"SELECT DISTINCT station_id FROM channel WHERE {col_name} = ?", (slave.id,))
                            rows = cursor.fetchall()
                            for r in rows: affected_stations.add(r[0])
            except Exception as e:
                logger.error(f"Error searching for stations: {e}")

            success_count = 0
            for slave in slaves:
                if self.eq_ctrl.replace_equipment(self.current_group_category, slave.id, master_id):
                    success_count += 1
                    
            if affected_stations and main_window and hasattr(main_window, 'sta_ctrl'):
                for st_id in affected_stations:
                    main_window.sta_ctrl.dao.update_sync_hash(st_id, "FORCED_INVALIDATION")
                    
            QMessageBox.information(self, "Completed", f"Merge completed.\n{success_count} models deleted.\n(Backup saved in 'backups/')")
            app_signals.equipment_updated.emit()
            
            if affected_stations:
                app_signals.station_updated.emit()
                
            self._scan_database()