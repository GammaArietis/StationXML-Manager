import traceback
import numpy as np
from nicegui import ui, run
from core.models.base_models import Sensor, PoleZero
from core.services.equipment_service import EquipmentInUseError
from web_gui.nrl_browser import NRLBrowser
from web_gui.arol_browser import AROLBrowser

class SensorCatalogTab:
    def __init__(self, eq_ctrl):
        self.eq_ctrl = eq_ctrl
        self.current_sensor = None
        self._selected_sensor_id = None
        self.zeros_inputs = []
        self.poles_inputs = []
        self._is_loading = False
        
        self.nrl_browser = NRLBrowser(self.eq_ctrl.nrl_manager, 'sensor')
        # FIX: AROL è case-sensitive, deve essere 'Sensors' con la S maiuscola!
        self.arol_browser = AROLBrowser(self.eq_ctrl.arol_client, 'Sensors')
        
        self.build_ui()
        self.refresh_list()

    def build_ui(self):
        with ui.grid(columns='250px 1fr 400px').style('width: 100%; height: 100%; gap: 0;'):
            
            # --- COLONNA 1: LISTA ---
            with ui.column().classes('bg-slate-50 p-4 border-r overflow-hidden flex flex-col no-wrap'):
                ui.label('Sensors').classes('font-bold text-xs uppercase mb-2 shrink-0')
                self.model_list = ui.list().classes('w-full border rounded bg-white overflow-y-auto flex-grow shadow-inner')
                with ui.row().classes('w-full mt-4 shrink-0 gap-1'):
                    ui.button('➕ New', on_click=self._prepare_new).props('outline size=sm').classes('flex-grow bg-white')
                    ui.button('🌐 NRL', on_click=self._on_nrl_clicked).props('outline size=sm').classes('flex-grow bg-white')
                    ui.button('🌐 AROL', on_click=self._on_arol_clicked).props('outline size=sm').classes('flex-grow bg-white')

            # --- COLONNA 2: EDITOR ---
            with ui.column().classes('p-8 overflow-y-auto'):
                ui.label('Sensor Editor').classes('text-2xl font-bold text-green-800 mb-6 shrink-0')
                
                with ui.card().classes('w-full p-6 border-l-8 border-green-600 shadow-sm mb-6'):
                    with ui.row().classes('w-full gap-4'):
                        self.mfg_input = ui.input('Manufacturer').classes('w-1/3')
                        self.model_input = ui.input('Model').classes('w-1/3')
                        self.type_input = ui.select(["SENSOR", "VBB", "BB", "SP", "SM"], label='Type').classes('flex-grow')
                    
                    with ui.row().classes('w-full gap-4 mt-4'):
                        self.sens_input = ui.number('Sensitivity', format='%.2e', on_change=self._update_plot).classes('w-1/2')
                        self.freq_input = ui.number('Norm. Frequency (Hz)', value=1.0, on_change=self._update_plot).classes('flex-grow')
                    
                    with ui.row().classes('w-full gap-4 mt-4 items-center'):
                        self.in_units = ui.input('Input Units', value='m/s').classes('w-1/4')
                        ui.label('→').classes('text-lg font-bold text-slate-400')
                        self.out_units = ui.input('Output Units', value='V').classes('w-1/4')
                        self.pz_type = ui.select(["LAPLACE (RADIANS/SECOND)", "LAPLACE (HERTZ)"], label='PZ Type', on_change=self._update_plot).classes('flex-grow')
                    
                    self.desc_input = ui.textarea('Description').classes('w-full mt-4').props('rows=2 outlined')
                
                ui.label('Poles and Zeros').classes('text-lg font-bold mt-4 shrink-0')
                with ui.row().classes('w-full gap-4 mt-2'):
                    with ui.column().classes('flex-grow p-4 bg-slate-50 border rounded'):
                        ui.label('Zeros').classes('text-xs font-bold text-slate-500 uppercase text-center w-full')
                        self.zt_cont = ui.column().classes('w-full gap-1')
                        ui.button('+ Add Zero', on_click=lambda: self._add_row(self.zt_cont, self.zeros_inputs)).props('flat dense size=sm color=blue')
                    
                    with ui.column().classes('flex-grow p-4 bg-slate-50 border rounded'):
                        ui.label('Poles').classes('text-xs font-bold text-slate-500 uppercase text-center w-full')
                        self.pt_cont = ui.column().classes('w-full gap-1')
                        ui.button('+ Add Pole', on_click=lambda: self._add_row(self.pt_cont, self.poles_inputs)).props('flat dense size=sm color=blue')
                
                with ui.row().classes('w-full justify-between items-center pt-6 mt-6 border-t shrink-0'):
                    with ui.row().classes('gap-2'):
                        self.btn_sens_clone = ui.button('👯 Clone', on_click=self._on_clone_clicked).props('outline color=purple')
                        self.btn_sens_replace = ui.button('🔄 Replace', on_click=self._on_replace_clicked).props('outline color=orange')
                        self.btn_sens_delete = ui.button('🗑️ Delete', on_click=self._on_delete_clicked).props('outline color=red')
                    ui.button('💾 SAVE SENSOR', on_click=self._on_save_clicked, color='green').classes('px-10 h-12 font-bold shadow-md')
                self._set_sensor_action_buttons(False)

            # --- COLONNA 3: PLOT ---
            with ui.column().classes('p-6 bg-slate-50 border-l overflow-y-auto'):
                ui.label('Frequency Response (Bode Plot)').classes('font-bold text-slate-500 uppercase text-xs mb-4')
                self.plot_container = ui.column().classes('w-full items-center mt-2')

    def _set_sensor_action_buttons(self, enabled: bool) -> None:
        for b in (self.btn_sens_clone, self.btn_sens_replace, self.btn_sens_delete):
            if enabled:
                b.enable()
            else:
                b.disable()

    def refresh_list(self):
        self.model_list.clear()
        with self.model_list:
            for s in self.eq_ctrl.get_all_sensors():
                icon = "🟢" if getattr(s, 'nrl_path', None) else "🔴"
                ui.item(f"{icon} {s.manufacturer} {s.model}") \
                    .props('clickable v-ripple') \
                    .classes('border-b w-full px-4 py-2 hover:bg-green-50') \
                    .on('click', lambda e, sid=s.id: self._load_sensor(sid))

    def _load_sensor(self, sid):
        try:
            if sid is None:
                return
            self._selected_sensor_id = int(sid)
            self._set_sensor_action_buttons(True)
            self._is_loading = True
            self.current_sensor = self.eq_ctrl.get_sensor(int(sid))
            if self.current_sensor:
                self._populate_ui_from_sensor(self.current_sensor)
            else:
                self._set_sensor_action_buttons(False)
            self._is_loading = False
            self._update_plot()
        except Exception as e:
            traceback.print_exc()
            self._set_sensor_action_buttons(False)
            ui.notify(f"Errore caricamento: {e}", type="negative")

    def _populate_ui_from_sensor(self, sensor):
        # FIX: Popolazione ultra-resiliente per gestire oggetti NRL/AROL non perfettamente formattati
        self.mfg_input.value = getattr(sensor, 'manufacturer', '') or ""
        self.model_input.value = getattr(sensor, 'model', '') or ""
        
        t = str(getattr(sensor, 'type', '') or "SENSOR").upper()
        self.type_input.value = t if t in ["SENSOR", "VBB", "BB", "SP", "SM"] else "SENSOR"
        
        self.desc_input.value = getattr(sensor, 'description', '') or ""
        self.sens_input.value = float(getattr(sensor, 'sensitivity', 0.0) or 0.0)
        self.freq_input.value = float(getattr(sensor, 'frequency', 1.0) or 1.0)
        self.in_units.value = getattr(sensor, 'input_units', '') or "m/s"
        self.out_units.value = getattr(sensor, 'output_units', '') or "V"
        
        pz = str(getattr(sensor, 'pz_transfer_function_type', '') or "LAPLACE (RADIANS/SECOND)").upper()
        self.pz_type.value = "LAPLACE (HERTZ)" if "HERTZ" in pz else "LAPLACE (RADIANS/SECOND)"
        
        self.zt_cont.clear(); self.zeros_inputs.clear()
        for z in (getattr(sensor, 'zeros', []) or []):
            # Intercetta 'real' se manca 'real_val'
            rv = getattr(z, 'real_val', getattr(z, 'real', 0.0))
            iv = getattr(z, 'imag_val', getattr(z, 'imag', 0.0))
            self._add_row(self.zt_cont, self.zeros_inputs, float(rv or 0.0), float(iv or 0.0))
        
        self.pt_cont.clear(); self.poles_inputs.clear()
        for p in (getattr(sensor, 'poles', []) or []):
            rv = getattr(p, 'real_val', getattr(p, 'real', 0.0))
            iv = getattr(p, 'imag_val', getattr(p, 'imag', 0.0))
            self._add_row(self.pt_cont, self.poles_inputs, float(rv or 0.0), float(iv or 0.0))

    def _add_row(self, container, registry, r=0.0, i=0.0):
        with container:
            with ui.row().classes('w-full no-wrap items-center gap-1 border-b pb-1') as row:
                rv = ui.number(value=r, on_change=self._update_plot).props('dense size=xs step=any').classes('w-20')
                iv = ui.number(value=i, on_change=self._update_plot).props('dense size=xs step=any').classes('w-20')
                ui.button(icon='delete', on_click=lambda: (row.delete(), registry.remove((rv, iv)), self._update_plot())).props('flat dense size=xs color=red')
                registry.append((rv, iv))

    def _on_save_clicked(self):
        if not self.current_sensor: return
        try:
            pole_pairs = [(float(r.value or 0), float(i.value or 0)) for r, i in self.poles_inputs]
            zero_pairs = [(float(r.value or 0), float(i.value or 0)) for r, i in self.zeros_inputs]
            
            merged_sensor = self.eq_ctrl.equipment_service.merge_sensor_from_web_fields(
                base=self.current_sensor,
                manufacturer=self.mfg_input.value,
                model=self.model_input.value,
                type_=self.type_input.value,
                description=self.desc_input.value,
                sensitivity=float(self.sens_input.value or 0.0),
                frequency=float(self.freq_input.value or 1.0),
                input_units=self.in_units.value,
                output_units=self.out_units.value,
                pz_transfer_function_type=self.pz_type.value,
                zero_pairs=zero_pairs,
                pole_pairs=pole_pairs
            )
            
            self.eq_ctrl.save_sensor(merged_sensor)
            self.current_sensor = merged_sensor
            ui.notify("Sensor Saved Successfully!", type='positive')
            self.refresh_list()
        except Exception as e:
            ui.notify(f"Save Error: {e}", type='negative')

    def _on_clone_clicked(self):
        sid = self._selected_sensor_id
        if sid is None and self.current_sensor and getattr(self.current_sensor, "id", None):
            sid = int(self.current_sensor.id)
        if sid is None:
            ui.notify("Seleziona un sensore salvato nel catalogo.", type="warning")
            return
        try:
            src = self.eq_ctrl.get_sensor(int(sid))
            if not src:
                ui.notify("Sensore non trovato.", type="negative")
                return
            dup = self.eq_ctrl.clone_sensor_model(src)
            saved = self.eq_ctrl.save_sensor(dup)
            if not saved:
                ui.notify("Salvataggio del duplicato non riuscito.", type="negative")
                return
            self.refresh_list()
            self._load_sensor(saved.id)
            ui.notify(f"Duplicato creato in catalogo: {saved.model}", type="positive")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore duplicazione: {e}", type="negative")

    def _on_replace_clicked(self):
        sid = self._selected_sensor_id or (int(self.current_sensor.id) if self.current_sensor and self.current_sensor.id else None)
        if not sid:
            return
        others = {s.id: f"{s.manufacturer} {s.model}" for s in self.eq_ctrl.get_all_sensors() if s.id != sid}
        if not others:
            ui.notify("Nessun altro sensore nel catalogo.", type="warning")
            return
        with ui.dialog() as d, ui.card().classes('w-96 p-6'):
            ui.label('Replace Sensor').classes('text-lg font-bold mb-4')
            sel = ui.select(others, label="Select replacement").classes('w-full')
            ui.button('Confirm Replace', color='orange', on_click=lambda: (
                self.eq_ctrl.replace_equipment('sensor', sid, sel.value),
                d.close(),
                self.refresh_list(),
                self._prepare_new()
            )).classes('w-full mt-4')
        d.open()

    async def _on_delete_clicked(self):
        sid = self._selected_sensor_id or (
            int(self.current_sensor.id) if self.current_sensor and getattr(self.current_sensor, "id", None) else None
        )
        if sid is None:
            ui.notify("Nessun sensore selezionato.", type="warning")
            return
        ch = (
            self.current_sensor
            if (self.current_sensor and getattr(self.current_sensor, "id", None) == sid)
            else self.eq_ctrl.get_sensor(int(sid))
        )
        display = (
            f"{getattr(ch, 'manufacturer', '')} {getattr(ch, 'model', '')}".strip()
            if ch
            else f"ID {sid}"
        )
        if not display:
            display = f"ID {sid}"

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
            ok = self.eq_ctrl.delete_sensor(int(sid))
            if not ok:
                ui.notify("Eliminazione non eseguita (nessuna riga nel database).", type="warning")
                return
            ui.notify("Sensore eliminato dal catalogo.", type="info")
            self._prepare_new()
            self.refresh_list()
        except EquipmentInUseError as e:
            ui.notify(str(e), type="negative")
        except ValueError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore eliminazione: {e}", type="negative")

    def _prepare_new(self):
        self.current_sensor = Sensor(manufacturer="", model="")
        self._selected_sensor_id = None
        self._set_sensor_action_buttons(False)
        self._populate_ui_from_sensor(self.current_sensor)
        self.plot_container.clear()

    # --- NRL / AROL ---
    async def _on_nrl_clicked(self):
        query = f"{self.mfg_input.value or ''} {self.model_input.value or ''}".strip()
        await self.nrl_browser.open(callback=self._finalize_external_import, search_query=query)

    def _on_arol_clicked(self):
        self.arol_browser.open(callback=self._finalize_external_import)

    def _finalize_external_import(self, downloaded_sensor):
        if not downloaded_sensor: return
        try:
            # FIX: Invece di far validare subito a Pydantic (che schianta se NRL ha i campi vecchi),
            # popoliamo la UI brutalmente e poi chiamiamo Save che costruisce l'oggetto perfetto!
            self.current_sensor = downloaded_sensor
            self._populate_ui_from_sensor(self.current_sensor)
            self._update_plot()
            self._on_save_clicked()
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Import Data Error: {e}", type='negative')

    # --- PLOT GRAFICO CON PROTEZIONE ERRORI ---
    def _update_plot(self):
        if self._is_loading: return
        self.plot_container.clear()
        with self.plot_container:
            with ui.pyplot(figsize=(4, 6)) as plot:
                try:
                    p = [complex(float(rv.value or 0), float(iv.value or 0)) for rv, iv in self.poles_inputs]
                    z = [complex(float(rv.value or 0), float(iv.value or 0)) for rv, iv in self.zeros_inputs]
                    gain = float(self.sens_input.value or 1.0)
                    is_hertz = "HERTZ" in str(self.pz_type.value or "").upper()
                    
                    f = np.logspace(-2, 2, 500); w = 2 * np.pi * f; s = 1j * w
                    
                    if is_hertz:
                        p = [cp * 2 * np.pi for cp in p]
                        z = [cz * 2 * np.pi for cz in z]

                    h = np.ones_like(s, dtype=complex)
                    for zero in z: h *= (s - zero)
                    for pole in p: h /= (s - pole)
                    
                    f_ref = float(self.freq_input.value or 1.0)
                    s_ref = 1j * 2 * np.pi * f_ref
                    h_ref = np.ones(1, dtype=complex)
                    
                    for zero in z: h_ref *= (s_ref - zero)
                    for pole in p: h_ref /= (s_ref - pole)
                    
                    if np.abs(h_ref[0]) > 1e-12:
                        a0 = gain / np.abs(h_ref[0])
                        h *= a0
                    
                    ax1 = plot.fig.add_subplot(211)
                    ax1.loglog(f, np.abs(h), color='blue', lw=1.5)
                    ax1.grid(True, which="both", alpha=0.3)
                    ax1.set_ylabel("Amplitude")
                    
                    ax2 = plot.fig.add_subplot(212)
                    ax2.semilogx(f, np.angle(h, deg=True), color='green', lw=1.5)
                    ax2.grid(True, which="both", alpha=0.3)
                    ax2.set_ylabel("Phase (deg)")
                    ax2.set_xlabel("Frequency (Hz)")
                    
                    plot.fig.tight_layout()
                except Exception as e:
                    ui.label(f"Plot Not Available (Mathematical Error: {str(e)})").classes('text-red-500 text-xs italic p-4')
