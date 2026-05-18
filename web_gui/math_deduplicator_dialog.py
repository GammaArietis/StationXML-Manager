import asyncio
import json
import queue
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from nicegui import ui, run

from core.config import get_settings
from web_gui.progress_utils import job_progress_fraction, job_progress_percent, yield_ui
from utils.equipment_math_hash import get_datalogger_hash, get_preamplifier_hash, get_sensor_hash
from utils.nrl_client import NRLManager
from utils.nrl_local_index import (
    collect_datalogger_leaf_paths,
    collect_sensor_leaf_paths,
    merge_datalogger_path_into_cache,
    merge_sensor_path_into_cache,
)


def _run_nrl_local_index_build(progress_queue: queue.SimpleQueue) -> None:
    """Eseguito in worker thread: riempie progress_queue con ('p', done, total, msg) poi ('ok', cache) o ('err', str)."""
    try:
        manager = NRLManager()
        sensor_paths = collect_sensor_leaf_paths(manager)
        datalogger_paths = collect_datalogger_leaf_paths(manager)
        total = len(sensor_paths) + len(datalogger_paths)
        if total == 0:
            progress_queue.put(("p", 1, 1, "Nessun percorso foglia NRL da indicizzare."))
            progress_queue.put(("ok", {"sensors": {}, "dataloggers": {}}))
            return
        cache: dict = {"sensors": {}, "dataloggers": {}}
        step = 0
        for path in sensor_paths:
            merge_sensor_path_into_cache(manager, path, cache)
            step += 1
            tail = " → ".join(path[-3:]) if path else ""
            progress_queue.put(("p", step, total, f"Sensore {step}/{total} {tail}"))
        n_s = len(sensor_paths)
        for j, path in enumerate(datalogger_paths, start=1):
            merge_datalogger_path_into_cache(manager, path, cache)
            step = n_s + j
            tail = " → ".join(path[-3:]) if path else ""
            progress_queue.put(("p", step, total, f"Datalogger {j}/{len(datalogger_paths)} (passo {step}/{total}) {tail}"))
        progress_queue.put(("ok", cache))
    except Exception as e:
        progress_queue.put(("err", str(e)))


# =====================================================================
# MAIN DIALOG WINDOW
# =====================================================================
class MathDeduplicatorDialog:

    def __init__(self, eq_ctrl, build_tree_callback=None):
        self.eq_ctrl = eq_ctrl
        self.build_tree_callback = build_tree_callback
        
        self.sensor_groups = {}
        self.datalogger_groups = {}
        self.preamp_groups = {}
        
        self.cache_file = Path("data/nrl_math_cache.json")
        self.nrl_cache = {'sensors': {}, 'dataloggers': {}}
        self._load_cache()
        
        self.current_category = None
        self.current_group_items = []
        
        # 1. FORZIAMO IL DIALOG a non avere limiti interni
        self.dialog = ui.dialog()

    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.nrl_cache = json.load(f)
            except: pass

    def open(self):
        # 2. FORZIAMO LA CARD con misure fisse in CSS puro (scavalca tutto)
        with self.dialog, ui.card().style('width: 95vw; max-width: 1400px; height: 90vh; display: flex; flex-direction: column;').classes('p-6 bg-slate-50'):
            with ui.row().classes('w-full items-center justify-between mb-2'):
                ui.label('🔍 Mathematical Deduplicator & NRL Recognition').classes('text-2xl font-bold text-slate-800')
                ui.button(icon='close', on_click=self.dialog.close).props('flat round text-color=grey')

            # Info bar
            info_label = ui.label('Questo strumento raggruppa sensori e datalogger basandosi sui parametri matematici.').classes('text-white bg-slate-800 p-3 rounded mb-4 shadow text-sm')
            info_label.tooltip('Modulo di analisi matematica per la fusione di record strumentali identici. Identifica i duplicati tramite hash dei coefficienti e normalizza le relazioni nel DB sismico senza perdita di informazioni.')
            
            self.btn_nrl_index = ui.button(
                '🛠️ Generate Local NRL Index',
                on_click=self._generate_nrl_index,
            ).classes('bg-purple-700 text-white font-bold mb-4 w-64 shadow')
            self.btn_nrl_index.tooltip('Calcola un indice locale NRL basato su impronte matematiche di poli, zeri e coefficienti per riconoscere strumenti nominalmente equivalenti.')

            self.search_input = ui.input(
                placeholder='Filtra duplicati per marca/modello...',
                on_change=lambda _: self._scan_database(),
            ).props('dense clearable hint="Filtra gruppi duplicati usando manufacturer/model mantenendo l analisi basata su hash matematici della risposta strumentale."').classes('w-full mb-4 shrink-0')

            # Tabs
            with ui.tabs().classes('w-full text-slate-700 font-bold') as tabs:
                tab_sen = ui.tab('Sensors')
                tab_dat = ui.tab('Dataloggers')
                tab_pre = ui.tab('PreAmps')

            # 3. IL SEGRETO DELLO SCROLL: min-h-0 impedisce al box di esplodere verso il basso
            with ui.tab_panels(tabs, value=tab_sen).classes('w-full flex-grow border bg-white rounded flex flex-col min-h-0'):
                
                # Le liste ora DEBBONO scorrere se superano lo spazio
                with ui.tab_panel(tab_sen).classes('w-full h-full overflow-y-auto overflow-x-auto p-4'):
                    self.tree_sen = ui.tree([], label_key='label', on_select=lambda e: self._on_group_selected('sensor', e.value)).classes('min-w-max').props('default-expand-all')
                
                with ui.tab_panel(tab_dat).classes('w-full h-full overflow-y-auto overflow-x-auto p-4'):
                    self.tree_dat = ui.tree([], label_key='label', on_select=lambda e: self._on_group_selected('datalogger', e.value)).classes('min-w-max').props('default-expand-all')
                
                with ui.tab_panel(tab_pre).classes('w-full h-full overflow-y-auto overflow-x-auto p-4'):
                    self.tree_pre = ui.tree([], label_key='label', on_select=lambda e: self._on_group_selected('preamplifier', e.value)).classes('min-w-max').props('default-expand-all')

            # Sezione Azioni (Bloccata in fondo perché gli altri elementi sono flex-grow)
            ui.separator().classes('my-4')
            with ui.row().classes('w-full items-center gap-4 bg-slate-200 p-4 rounded shadow-inner'):
                ui.label('Master to keep:').classes('font-bold text-lg')
                self.combo_master = ui.select(options={}, label='Seleziona il modello da mantenere', with_input=True).classes('flex-grow bg-white')
                self.combo_master.tooltip('Record strumentale master che conserverà le relazioni canale dopo la fusione dei duplicati matematicamente equivalenti.')
                self.btn_merge = ui.button('🔗 Merge Group', on_click=self._perform_merge).classes('bg-green-700 text-white font-bold px-6')
                self.btn_merge.tooltip('Fonde il gruppo duplicato aggiornando le foreign key nel DB sismico e preservando le informazioni strumentali equivalenti.')
                self.btn_merge.disable()

        self._scan_database()
        self.dialog.open()
        
    async def _generate_nrl_index(self):
        if getattr(self, '_nrl_index_busy', False):
            return
        self._nrl_index_busy = True
        self.btn_nrl_index.disable()

        with ui.dialog() as index_dialog, ui.card().classes('p-8 w-[min(420px,92vw)]'):
            ui.label('🛠️ Generazione indice NRL locale').classes('text-xl font-bold text-slate-800 mb-2')
            ui.label(
                'Scansione della libreria NRL e calcolo delle impronte matematiche. '
                'Attendere…'
            ).classes('text-sm text-slate-600 mb-4')
            progress_bar = ui.linear_progress(value=0).classes('w-full')
            index_status = ui.label('Inizializzazione…').classes('text-xs text-slate-500 mt-3')

        index_dialog.open()
        await yield_ui()
        prog_q: queue.SimpleQueue = queue.SimpleQueue()
        new_cache = None
        try:
            task = asyncio.create_task(run.io_bound(_run_nrl_local_index_build, prog_q))
            progress_bar.set_value(job_progress_fraction(0, 1))
            index_status.set_text(f"0/1 ({job_progress_percent(0, 1):.2f}%) — avvio worker…")
            await yield_ui()
            err_msg = None
            while not task.done():
                try:
                    while True:
                        item = prog_q.get_nowait()
                        if item[0] == "p":
                            _, done, tot, msg = item
                            progress_bar.set_value(job_progress_fraction(done, tot))
                            pct = job_progress_percent(done, tot)
                            index_status.set_text(f"{msg} — {pct:.2f}%")
                        elif item[0] == "ok":
                            new_cache = item[1]
                        elif item[0] == "err":
                            err_msg = item[1]
                except queue.Empty:
                    pass
                await yield_ui()
                await asyncio.sleep(0.02)
            await task
            try:
                while True:
                    item = prog_q.get_nowait()
                    if item[0] == "p":
                        _, done, tot, msg = item
                        progress_bar.set_value(job_progress_fraction(done, tot))
                        pct = job_progress_percent(done, tot)
                        index_status.set_text(f"{msg} — {pct:.2f}%")
                    elif item[0] == "ok":
                        new_cache = item[1]
                    elif item[0] == "err":
                        err_msg = item[1]
            except queue.Empty:
                pass
            if err_msg:
                raise RuntimeError(err_msg)
            if new_cache is None:
                raise RuntimeError("Indice NRL: nessun risultato dal worker.")
            self.nrl_cache = new_cache
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.nrl_cache, f, indent=4)
            progress_bar.set_value(1.0)
            index_status.set_text('Indice salvato — 100.00%')
            await yield_ui()
            await asyncio.sleep(0.25)
            ui.notify('NRL Index generato correttamente.', type='positive')
            self._scan_database()
        except Exception as e:
            traceback.print_exc()
            ui.notify(f'Errore durante la generazione dell\'indice: {e}', type='negative')
        finally:
            index_dialog.close()
            self._nrl_index_busy = False
            self.btn_nrl_index.enable()

    def _scan_database(self):
        """Rigenera gli alberi UI."""
        needle = ((self.search_input.value if hasattr(self, 'search_input') else '') or '').strip().lower()

        def group_matches(items) -> bool:
            if not needle:
                return True
            return any(
                needle in f"{getattr(it, 'manufacturer', '')} {getattr(it, 'model', '')}".lower()
                for it in items
            )

        self.sensor_groups.clear()
        self.datalogger_groups.clear()
        self.preamp_groups.clear()
        
        # 1. SENSORI
        tree_data_s = []
        for s in self.eq_ctrl.get_all_sensors():
            h = get_sensor_hash(s)
            if h not in self.sensor_groups: self.sensor_groups[h] = []
            self.sensor_groups[h].append(s)
        for h, items in self.sensor_groups.items():
            if not group_matches(items):
                continue
            matched = h in self.nrl_cache.get('sensors', {})
            title = f"🌟 PERFECT NRL MATCH | {len(items)} loc." if matched else f"Gruppo ({len(items)} modelli)"
            group_node = {'id': f"grp_{h}", 'label': title, 'children': []}
            for it in items:
                icon = "🟢" if getattr(it, 'nrl_path', None) else "🔴"
                group_node['children'].append({'id': str(it.id), 'label': f"{icon} {it.manufacturer} {it.model} (ID: {it.id})"})
            tree_data_s.append(group_node)
        
        # 2. DATALOGGER
        tree_data_d = []
        for d in self.eq_ctrl.get_all_dataloggers():
            h = get_datalogger_hash(d)
            if h not in self.datalogger_groups: self.datalogger_groups[h] = []
            self.datalogger_groups[h].append(d)
        for h, items in self.datalogger_groups.items():
            if not group_matches(items):
                continue
            matched = h in self.nrl_cache.get('dataloggers', {})
            title = f"🌟 PERFECT NRL MATCH | {len(items)} loc." if matched else f"Gruppo ({len(items)} modelli)"
            group_node = {'id': f"grp_{h}", 'label': title, 'children': []}
            for it in items:
                icon = "🟢" if getattr(it, 'nrl_path', None) else "🔴"
                group_node['children'].append({'id': str(it.id), 'label': f"{icon} {it.manufacturer} {it.model} (ID: {it.id})"})
            tree_data_d.append(group_node)

        # 3. PREAMPLIFICATORI
        tree_data_p = []
        for p in self.eq_ctrl.get_all_preamplifiers():
            h = get_preamplifier_hash(p)
            if h not in self.preamp_groups: self.preamp_groups[h] = []
            self.preamp_groups[h].append(p)
        for h, items in self.preamp_groups.items():
            if not group_matches(items):
                continue
            title = f"Gruppo ({len(items)} modelli)" if len(items) > 1 else "Modello Singolo"
            group_node = {'id': f"grp_{h}", 'label': title, 'children': []}
            for it in items:
                mfg, mod = getattr(it, 'manufacturer', ''), getattr(it, 'model', '')
                group_node['children'].append({'id': str(it.id), 'label': f"🔴 {mfg} {mod} (ID: {it.id})"})
            tree_data_p.append(group_node)

        # Update UI e Auto-Espansione
        self.tree_sen._props['nodes'] = tree_data_s
        self.tree_sen.update()
        self.tree_sen.expand()
        self.tree_dat._props['nodes'] = tree_data_d
        self.tree_dat.update()
        self.tree_dat.expand()
        self.tree_pre._props['nodes'] = tree_data_p
        self.tree_pre.update()
        self.tree_pre.expand()

    def _on_group_selected(self, category, node_id):
        self.combo_master.options.clear()
        self.combo_master.value = None
        self.btn_merge.disable()
        if not node_id: return
        self.current_category = category
        group_dict = self.sensor_groups if category == 'sensor' else self.datalogger_groups if category == 'datalogger' else self.preamp_groups
        for h, items in group_dict.items():
            if node_id == f"grp_{h}" or any(str(it.id) == str(node_id) for it in items):
                self.current_group_items = items
                break
        if not self.current_group_items: return
        options = {eq.id: f"{'🟢' if getattr(eq, 'nrl_path', None) else '🔴'} {eq.manufacturer} {eq.model} (ID: {eq.id})" for eq in self.current_group_items}
        self.combo_master.options = options
        self.combo_master.update()
        self.btn_merge.enable()

    def _perform_merge(self):
        master_id = self.combo_master.value
        if not master_id: return
        slaves = [eq for eq in self.current_group_items if eq.id != master_id]
        if not slaves:
            ui.notify("Nessun duplicato da unire.", type='warning')
            return
        try:
            db_path = get_settings().database_path
            if db_path.exists():
                backup_dir = Path("backups")
                backup_dir.mkdir(exist_ok=True)
                backup_file = backup_dir / f"stationxml_pre_merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                shutil.copy2(db_path, backup_file)
                ui.notify(f"Backup creato: {backup_file.name}", type="info")
        except Exception: pass
        success = 0
        for slave in slaves:
            if self.eq_ctrl.replace_equipment(self.current_category, slave.id, master_id):
                success += 1
        ui.notify(f"Merge completato! {success} modelli eliminati.", type='positive')
        self._scan_database()
        if self.build_tree_callback: self.build_tree_callback()
