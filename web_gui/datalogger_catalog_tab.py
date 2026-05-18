import traceback, json, re
import numpy as np
from scipy import signal
from nicegui import ui, run
from core.models.base_models import Datalogger, ResponseFilter
from core.services.equipment_service import EquipmentInUseError
from web_gui.nrl_browser import NRLBrowser
from web_gui.arol_browser import AROLBrowser

class DataloggerCatalogTab:
    def __init__(self, eq_ctrl):
        self.eq_ctrl = eq_ctrl
        self.current_dl = None
        self.current_stage = None
        self.stages_data = []
        self._is_loading = False
        self._selected_dl_id = None
        
        self.nrl_browser = NRLBrowser(self.eq_ctrl.nrl_manager, 'datalogger')
        self.arol_browser = AROLBrowser(self.eq_ctrl.arol_client, 'dataloggers')
        
        self.build_ui()
        self.refresh_list()

    def build_ui(self):
        # Funzione per calcolare in tempo reale l'Out Rate se scrivi nell'editor
        def _auto_calc_out(e):
            if self._is_loading: return
            i_r = self.f_in_rate.value or 0.0
            dec = self.f_decimation.value or 1.0
            if dec > 0:
                self.f_out_rate.value = i_r / dec

        with ui.grid(columns='250px 1fr 400px').style('width: 100%; height: 100%; gap: 0;'):
            
            # --- COLONNA 1: LISTA ---
            with ui.column().classes('bg-slate-50 p-4 border-r overflow-hidden flex flex-col no-wrap'):
                ui.label('Dataloggers').classes('font-bold text-xs uppercase mb-2 shrink-0')
                self.search_input = ui.input(
                    placeholder='Cerca per marca/modello...',
                    on_change=lambda _: self.refresh_list(),
                ).props('dense clearable').classes('w-full mb-2 shrink-0')
                self.model_list = ui.list().classes('w-full border rounded bg-white overflow-y-auto flex-grow shadow-inner')
                with ui.row().classes('w-full mt-4 shrink-0 gap-1'):
                    ui.button('➕ New', on_click=self._prepare_new).props('outline size=sm').classes('flex-grow bg-white')
                    ui.button('🌐 NRL', on_click=self._on_nrl_clicked).props('outline size=sm').classes('flex-grow bg-white')
                    ui.button('🌐 AROL', on_click=self._on_arol_clicked).props('outline size=sm').classes('flex-grow bg-white')

            # --- COLONNA 2: EDITOR ---
            with ui.column().classes('p-8 overflow-y-auto'):
                ui.label('Datalogger Editor').classes('text-2xl font-bold text-blue-800 mb-6 shrink-0')
                
                with ui.card().classes('w-full p-6 border-l-8 border-blue-600 shadow-sm mb-6'):
                    with ui.row().classes('w-full gap-4'):
                        self.mfg_input = ui.input('Manufacturer').classes('w-1/3')
                        self.model_input = ui.input('Model').classes('flex-grow')
                    
                    self.desc_input = ui.textarea('Description').classes('w-full mt-4').props('rows=2 outlined')
                    
                    with ui.row().classes('w-full gap-4 mt-4'):
                        self.gain_input = ui.number('Gain (Counts/V)', format='%.4e').classes('w-1/3')
                        self.drift_input = ui.number('Clock Drift (s/s)', format='%.8f').classes('w-1/3')
                        self.delay_input = ui.number('Base Delay (s)', format='%.4f').classes('w-1/3')

                ui.label('Acquisition Chain (Stages and Filters)').classes('text-lg font-bold mt-4 shrink-0')
                self.stages_cont = ui.column().classes('w-full gap-2 border rounded p-4 bg-slate-50 shadow-inner mt-2')
                ui.button('➕ Add Filter Stage', on_click=self._add_stage).props('outline size=sm color=blue').classes('mt-2')

                with ui.row().classes('w-full justify-between items-center pt-6 mt-6 border-t shrink-0'):
                    with ui.row().classes('gap-2'):
                        self.btn_dl_clone = ui.button('👯 Clone', on_click=self._on_clone_clicked).props('outline color=purple')
                        self.btn_dl_replace = ui.button('🔄 Replace', on_click=self._on_replace_clicked).props('outline color=orange')
                        self.btn_dl_delete = ui.button('🗑️ Delete', on_click=self._on_delete_clicked).props('outline color=red')
                    ui.button('💾 SAVE DATALOGGER', on_click=self._on_save_clicked, color='green').classes('px-10 h-12 font-bold shadow-md')
                self._set_dl_action_buttons(False)

            # --- COLONNA 3: DSP ---
            with ui.column().classes('p-6 bg-slate-50 border-l overflow-y-auto'):
                ui.label('Stage Editor & Plot').classes('font-bold text-slate-500 uppercase text-xs mb-4 shrink-0')
                
                self.stage_panel = ui.column().classes('w-full gap-4 shrink-0')
                with self.stage_panel:
                    ui.label('Select a stage from the chain...').classes('text-slate-400 italic text-center w-full mt-4').bind_visibility_from(self, 'current_stage', backward=lambda x: x is None)
                    
                    self.f_type = ui.select(['FIR', 'COEFFICIENTS', 'A/D'], label='Type').classes('w-full')
                    with ui.row().classes('w-full gap-2'):
                        self.f_in_rate = ui.number('In Rate (Hz)', on_change=_auto_calc_out).classes('w-[48%]')
                        self.f_out_rate = ui.number('Out Rate (Hz)').classes('w-[48%]')
                    with ui.row().classes('w-full gap-2 mt-2'):
                        self.f_decimation = ui.number('Decimation', on_change=_auto_calc_out).classes('w-[32%]')
                        self.f_delay = ui.number('Delay (s)').classes('w-[32%]')
                        self.f_delay.tooltip('Estimated Delay and Applied Correction in seconds')
                        self.f_correction = ui.number('Correction (s)').classes('w-[32%]')
                        self.f_correction.tooltip('Estimated Delay and Applied Correction in seconds')

                    self.f_coeffs = ui.textarea('Coefficients (JSON)').classes('w-full mt-2 font-mono text-xs').props('rows=5 outlined')
                    ui.button('Apply to Stage & Plot', on_click=self._apply_stage_changes).props('color=blue').classes('w-full')
                
                self.plot_container = ui.column().classes('w-full items-center mt-6 shrink-0')
                self.stage_panel.set_visibility(False)

    def _set_dl_action_buttons(self, enabled: bool) -> None:
        for b in (self.btn_dl_clone, self.btn_dl_replace, self.btn_dl_delete):
            if enabled:
                b.enable()
            else:
                b.disable()

    # --- WIRING AL NUOVO SERVICE LAYER ---
    def refresh_list(self):
        needle = ((self.search_input.value if hasattr(self, 'search_input') else '') or '').strip().lower()
        self.model_list.clear()
        with self.model_list:
            for dl in self.eq_ctrl.get_all_dataloggers():
                searchable = f"{dl.manufacturer} {dl.model}".lower()
                if needle and needle not in searchable:
                    continue
                icon = "🟢" if getattr(dl, 'nrl_path', None) else "🔴"
                ui.item(f"{icon} {dl.manufacturer} {dl.model}") \
                    .props('clickable v-ripple') \
                    .classes('border-b w-full px-4 py-2 hover:bg-blue-50') \
                    .on('click', lambda e, did=dl.id: self._load_dl(did))

    def _load_dl(self, dl_id):
        try:
            if dl_id is None:
                return
            self._selected_dl_id = int(dl_id)
            self._set_dl_action_buttons(True)
            self._is_loading = True
            self.current_dl = self.eq_ctrl.get_datalogger(int(dl_id))
            if self.current_dl:
                self._populate_ui_from_dl(self.current_dl)
            else:
                self._set_dl_action_buttons(False)
            self._is_loading = False
        except Exception as e:
            traceback.print_exc()
            self._set_dl_action_buttons(False)
            ui.notify(f"Errore caricamento: {e}", type="negative")

    def _populate_ui_from_dl(self, dl):
        self.mfg_input.value = dl.manufacturer or ""
        self.model_input.value = dl.model or ""
        self.desc_input.value = dl.description or ""
        self.gain_input.value = float(dl.gain or 0.0)
        self.drift_input.value = float(dl.max_clock_drift or 0.0)
        self.delay_input.value = float(dl.base_hardware_delay or 0.0)
        
        self.stages_data = [f for f in (dl.filters or [])]
        self.current_stage = None
        self._render_stages()
        self.stage_panel.set_visibility(False)
        self.plot_container.clear()

    def _on_save_clicked(self):
        if not self.current_dl: return
        try:
            merged_dl = self.eq_ctrl.equipment_service.merge_datalogger_from_web_fields(
                base=self.current_dl,
                manufacturer=self.mfg_input.value,
                model=self.model_input.value,
                description=self.desc_input.value,
                gain=float(self.gain_input.value or 0.0),
                max_clock_drift=float(self.drift_input.value or 0.0),
                base_hardware_delay=float(self.delay_input.value or 0.0),
                filters=self.stages_data
            )
            
            self.eq_ctrl.save_datalogger(merged_dl)
            self.current_dl = merged_dl
            ui.notify("Datalogger Saved Successfully!", type='positive')
            self.refresh_list()
        except Exception as e:
            ui.notify(f"Save Error: {e}", type='negative')

    def _prepare_new(self):
        self.current_dl = Datalogger(manufacturer="", model="")
        self._selected_dl_id = None
        self._set_dl_action_buttons(False)
        self._populate_ui_from_dl(self.current_dl)

    def _on_clone_clicked(self):
        did = self._selected_dl_id
        if did is None and self.current_dl and getattr(self.current_dl, "id", None):
            did = int(self.current_dl.id)
        if did is None:
            ui.notify("Seleziona un datalogger salvato nel catalogo.", type="warning")
            return
        try:
            src = self.eq_ctrl.get_datalogger(int(did))
            if not src:
                ui.notify("Datalogger non trovato.", type="negative")
                return
            dup = self.eq_ctrl.clone_datalogger_model(src)
            saved = self.eq_ctrl.save_datalogger(dup)
            if not saved:
                ui.notify("Salvataggio del duplicato non riuscito.", type="negative")
                return
            self.refresh_list()
            self._load_dl(saved.id)
            ui.notify(f"Duplicato creato in catalogo: {saved.model}", type="positive")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore duplicazione: {e}", type="negative")

    def _on_replace_clicked(self):
        did = self._selected_dl_id or (int(self.current_dl.id) if self.current_dl and self.current_dl.id else None)
        if not did:
            return
        others = {d.id: f"{d.manufacturer} {d.model}" for d in self.eq_ctrl.get_all_dataloggers() if d.id != did}
        if not others:
            ui.notify("Nessun altro datalogger nel catalogo.", type="warning")
            return
        with ui.dialog() as d, ui.card().classes('w-96 p-6'):
            ui.label('Replace Datalogger').classes('text-lg font-bold mb-4')
            sel = ui.select(others, label="Select replacement", with_input=True).classes('w-full')
            ui.button('Confirm Replace', color='orange', on_click=lambda: (
                self.eq_ctrl.replace_equipment('datalogger', did, sel.value),
                d.close(),
                self.refresh_list(),
                self._prepare_new()
            )).classes('w-full mt-4')
        d.open()

    async def _on_delete_clicked(self):
        did = self._selected_dl_id or (
            int(self.current_dl.id) if self.current_dl and getattr(self.current_dl, "id", None) else None
        )
        if did is None:
            ui.notify("Nessun datalogger selezionato.", type="warning")
            return
        dl = (
            self.current_dl
            if (self.current_dl and getattr(self.current_dl, "id", None) == did)
            else self.eq_ctrl.get_datalogger(int(did))
        )
        display = (
            f"{getattr(dl, 'manufacturer', '')} {getattr(dl, 'model', '')}".strip()
            if dl
            else f"ID {did}"
        )
        if not display:
            display = f"ID {did}"

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md p-6"):
            ui.label("Conferma eliminazione").classes("text-lg font-bold text-slate-800")
            ui.label(
                f"Sei sicuro di voler eliminare {display}? Questa azione è irreversibile."
            ).classes("text-sm text-slate-700 mt-2")
            with ui.row().classes("w-full justify-end mt-6 gap-2"):
                ui.button("Annulla", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Elimina", on_click=lambda: dialog.submit(True)).classes(
                    "bg-red-600 text-white font-bold"
                )

        confirmed = await dialog
        if not confirmed:
            return

        try:
            ok = self.eq_ctrl.delete_datalogger(int(did))
            if not ok:
                ui.notify("Eliminazione non eseguita (nessuna riga nel database).", type="warning")
                return
            ui.notify("Datalogger eliminato dal catalogo.", type="info")
            self._prepare_new()
            self.refresh_list()
        except EquipmentInUseError as e:
            ui.notify(str(e), type="negative")
        except ValueError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore eliminazione: {e}", type="negative")

    # --- STAGE MANAGEMENT ---
    def _add_stage(self):
        s = ResponseFilter(stage_number=len(self.stages_data)+1, filter_type='FIR', coefficients="[]")
        self.stages_data.append(s)
        self._render_stages()

    def _render_stages(self):
        self.stages_cont.clear()
        for i, f in enumerate(sorted(self.stages_data, key=lambda x: getattr(x, 'stage_number', 0))):
            f.stage_number = i + 1
            
            i_rate = getattr(f, 'input_sample_rate', None)
            o_rate = getattr(f, 'output_sample_rate', None)
            d_fact = getattr(f, 'decimation_factor', None)
            
            d_val = float(d_fact) if d_fact else 1.0
            if d_val == 0.0: d_val = 1.0
            
            if i_rate and (not o_rate or o_rate == 0.0):
                o_rate = i_rate / d_val
            elif o_rate and (not i_rate or i_rate == 0.0):
                i_rate = o_rate * d_val
                
            in_str = f"In: {i_rate:.2f}Hz" if i_rate else "In: N/A"
            out_str = f"Out: {o_rate:.2f}Hz" if o_rate else "Out: N/A"
            
            bg = 'bg-blue-100 border-blue-400' if self.current_stage == f else 'bg-white hover:bg-slate-50'
            with self.stages_cont:
                with ui.row().classes(f'w-full items-center p-3 border rounded shadow-sm gap-2 cursor-pointer {bg}').on('click', lambda _, st=f: self._edit_stage(st)) as row:
                    ui.label(f"S{f.stage_number}").classes('font-bold w-8 text-blue-700')
                    ui.label(f.filter_type).classes('w-20 text-xs font-mono')
                    ui.label(f"{in_str} → {out_str}").classes('flex-grow text-xs text-slate-500')
                    ui.button(icon='delete', on_click=lambda e, st=f, r=row: (r.delete(), self.stages_data.remove(st), self._render_stages())).props('flat dense color=red size=sm')

    def _edit_stage(self, stage):
        self._is_loading = True
        self.current_stage = stage
        self._render_stages()
        self.stage_panel.set_visibility(True)
        
        i_rate = stage.input_sample_rate or 0.0
        o_rate = stage.output_sample_rate or 0.0
        dec = stage.decimation_factor or 1.0
        if dec == 0: dec = 1.0
        if i_rate and not o_rate: o_rate = i_rate / dec

        self.f_type.value = stage.filter_type
        self.f_in_rate.value = i_rate
        self.f_out_rate.value = o_rate
        self.f_decimation.value = stage.decimation_factor
        self.f_delay.value = stage.estimated_delay
        self.f_correction.value = stage.correction_applied
        
        try:
            self.f_coeffs.value = json.dumps(json.loads(stage.coefficients), indent=2) if stage.coefficients else "[]"
        except:
            self.f_coeffs.value = stage.coefficients
        self._is_loading = False
        self._update_plot()

    def _apply_stage_changes(self):
        if not self.current_stage: return
        self.current_stage.filter_type = self.f_type.value
        self.current_stage.input_sample_rate = self.f_in_rate.value
        self.current_stage.output_sample_rate = self.f_out_rate.value
        self.current_stage.decimation_factor = self.f_decimation.value or 1
        self.current_stage.estimated_delay = self.f_delay.value or 0.0
        self.current_stage.correction_applied = self.f_correction.value or 0.0
        self.current_stage.coefficients = self.f_coeffs.value
        self._render_stages()
        self._update_plot()

    # --- PLOT GRAFICO (Omni-Parser per Coefficienti FIR) ---
    # --- PLOT GRAFICO (Omni-Parser + Linea di Nyquist) ---
    def _update_plot(self):
        self.plot_container.clear()
        if not self.current_stage or self.current_stage.filter_type.upper() in ['A/D', 'A-D', 'DIGITIZER']: return
        
        try:
            raw_str = (self.f_coeffs.value or "").strip()
            if not raw_str or raw_str == "[]":
                with self.plot_container:
                    ui.label("No coefficients to plot.").classes("text-slate-400 italic p-4")
                return

            coeffs = []
            
            # 1. Prova a decodificare come JSON
            try:
                raw_json = json.loads(raw_str)
                def find_array(obj):
                    if isinstance(obj, list): return obj
                    if isinstance(obj, dict):
                        for k in ['numerators', 'coefficients', 'numerator']:
                            for key in obj.keys():
                                if k in key.lower():
                                    val = obj[key]
                                    if isinstance(val, list): return val
                                    if isinstance(val, dict): return find_array(val)
                        for v in obj.values():
                            res = find_array(v)
                            if res: return res
                    return []
                coeffs = find_array(raw_json)
            except:
                # 2. Estrazione bruta tramite Regex
                tokens = re.findall(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', raw_str)
                coeffs = tokens

            coeffs = [float(c) for c in coeffs if c]

            if not coeffs:
                with self.plot_container:
                    ui.label("No numerical FIR coefficients found in the data.").classes("text-slate-400 italic p-4")
                return

            with self.plot_container:
                with ui.pyplot(figsize=(3.8, 5)) as plot:
                    ax1 = plot.fig.add_subplot(211)
                    ax1.plot(coeffs, color='blue')
                    ax1.set_title("Impulse Response", fontsize=9)
                    ax1.grid(True, alpha=0.3)
                    
                    ax2 = plot.fig.add_subplot(212)
                    w, h = signal.freqz(coeffs, worN=2000)
                    
                    fs = float(self.f_in_rate.value or 2.0)
                    if fs <= 0: fs = 2.0
                    f_hz = (w / np.pi) * (fs / 2)
                    
                    h_mag = np.abs(h)
                    h_mag[h_mag == 0] = 1e-12
                    
                    ax2.plot(f_hz, 20 * np.log10(h_mag), color='red')
                    
                    # --- LINEA VERDE DI NYQUIST (Out Rate / 2) ---
                    f_out = float(self.f_out_rate.value or 0.0)
                    if f_out > 0:
                        f_nyq = f_out / 2.0
                        ax2.axvline(x=f_nyq, color='green', linestyle='--', linewidth=1.5, label=f'Nyquist ({f_nyq:g} Hz)')
                        ax2.legend(loc='lower left', fontsize=8)

                    ax2.grid(True, ls=':')
                    ax2.set_xlabel("Frequency (Hz)")
                    ax2.set_ylabel("Magnitude (dB)")
                    plot.fig.tight_layout()
        except Exception as e:
            with self.plot_container:
                ui.label(f"Plot Error: {str(e)}").classes('text-red-500 text-xs italic p-4')

    # ==========================================
    # --- NRL (IMPORTAZIONE DIRETTA) ---
    # ==========================================
    async def _on_nrl_clicked(self):
        query = f"{self.mfg_input.value or ''} {self.model_input.value or ''}".strip()
        await self.nrl_browser.open(callback=self._finalize_nrl_import, search_query=query)

    def _finalize_nrl_import(self, downloaded_dl):
        if not downloaded_dl: return
        try:
            self.current_dl = downloaded_dl
            self._populate_ui_from_dl(self.current_dl)
            self._on_save_clicked()
        except Exception as e:
            ui.notify(f"NRL Import Error: {e}", type='negative')

    # ==========================================
    # --- AROL (COMPOSIZIONE A CICLO MULTI-STADIO) ---
    # ==========================================
    def _on_arol_clicked(self):
        ui.notify("AROL: Seleziona il primo stadio (es. Analogico)", type='info')
        self.arol_browser.open(callback=self._handle_arol_first)

    def _handle_arol_first(self, dl):
        if not dl: return
        self.current_dl = dl
        self._populate_ui_from_dl(self.current_dl)
        self._ask_for_more_stages()

    def _ask_for_more_stages(self):
        with ui.dialog() as d, ui.card().classes('p-6'):
            ui.label("Composizione Catena AROL").classes('text-lg font-bold text-blue-800')
            ui.label("Vuoi aggiungere un altro stadio (es. digitale/FIR) a questa catena?")
            with ui.row().classes('w-full justify-end mt-4 gap-2'):
                ui.button("No, Salva e Chiudi", on_click=lambda: (d.close(), self._finalize_arol())).props('flat text-red')
                ui.button("Sì, Aggiungi Stadio", on_click=lambda: (d.close(), self._open_arol_next())).props('color=blue')
        d.open()

    def _open_arol_next(self):
        ui.notify("AROL: Seleziona lo stadio successivo", type='info')
        self.arol_browser.open(callback=self._handle_arol_next)

    def _handle_arol_next(self, next_dl):
        if not next_dl:
            # Se l'utente chiude la finestra AROL senza scegliere, salva quello che ha già
            self._finalize_arol()
            return
            
        # 1. Accoda i filtri aggiornando il numero dello stadio
        off = len(self.current_dl.filters)
        for i, f in enumerate(next_dl.filters):
            f.stage_number = off + i + 1
            self.current_dl.filters.append(f)
            
        # 2. Moltiplica i Gain
        if next_dl.gain:
            self.current_dl.gain = (self.current_dl.gain or 1.0) * next_dl.gain
            
        # 3. Fonde i nomi in modo intelligente
        p1 = self.current_dl.model or ""
        p2 = next_dl.model or ""
        
        prefix = p1.split('-')[0].split('_')[0]
        if p2.startswith(prefix):
            p2 = p2.replace(prefix, '').lstrip('-_')
        
        self.current_dl.model = f"{p1}_{p2}"
        
        # Aggiorna la UI e fa ripartire la domanda (Ciclo!)
        self._populate_ui_from_dl(self.current_dl)
        self._ask_for_more_stages()

    def _finalize_arol(self):
        self._on_save_clicked()
        ui.notify(f"Catena {self.current_dl.model} completata e salvata!", type='positive')
