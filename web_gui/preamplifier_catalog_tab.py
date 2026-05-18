import traceback
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from nicegui import ui
from core.models.base_models import Preamplifier, AnalogStage, PoleZero

class PreamplifierCatalogTab:
    def __init__(self, eq_ctrl):
        self.eq_ctrl = eq_ctrl
        self.current_pre = None
        self.current_stage = None
        self.stages_data = []
        self._is_loading = False
        self._selected_preamp_id = None
        
        self.s_zeros_ui = []
        self.s_poles_ui = []
        
        self.build_ui()
        self.refresh_list()

    def build_ui(self):
        # GRID principale: 250px | Flessibile | 400px
        with ui.grid(columns='250px 1fr 400px').style('width: 100%; height: 100%; gap: 0; margin: 0; padding: 0;'):
            
            # --- COLONNA 1: LISTA ---
            with ui.column().classes('h-full bg-slate-50 border-r p-4 flex flex-col no-wrap').style('overflow: hidden;'):
                ui.label('Preamplifiers').classes('font-bold text-slate-700 text-xs uppercase mb-2 shrink-0')
                self.model_list = ui.list().classes('w-full border rounded bg-white overflow-y-auto shadow-inner').style('flex: 1 1 0;')
                
                with ui.row().classes('w-full gap-1 mt-4 shrink-0'):
                    ui.button('➕ New', on_click=self._prepare_new_model).props('flat size=sm color=blue').classes('flex-grow border bg-white')

            # --- COLONNA 2: EDITOR CENTRALE (Layout Bloccato) ---
            with ui.column().classes('h-full p-8 bg-white flex flex-col no-wrap overflow-hidden'):
                ui.label('Preamplifier Editor').classes('text-2xl font-bold text-blue-800 mb-6 shrink-0')
                
                # Area Scorrevole Superiore (Dati e Stadi)
                with ui.column().classes('w-full flex-grow overflow-y-auto pr-2'):
                    with ui.card().classes('w-full p-6 mb-6 shadow-sm border-l-8 border-orange-500 shrink-0'):
                        with ui.row().classes('w-full gap-4'):
                            self.mfg_input = ui.input('Manufacturer').classes('w-1/3')
                            self.model_input = ui.input('Model').classes('flex-grow')
                    
                    self.desc_input = ui.textarea('Description').classes('w-full mb-6 shrink-0').props('rows=2 outlined')

                    ui.label('Analog Conditioning Stages').classes('text-lg font-bold text-slate-700 mb-2 shrink-0')
                    self.stages_cont = ui.column().classes('w-full gap-2 border rounded p-4 bg-slate-50 shadow-inner mb-2')
                    
                    ui.button('➕ Add Analog Stage', on_click=self._add_stage).props('outline color=orange size=sm').classes('shrink-0 mb-4')

                # AREA AZIONI (Footer sempre visibile)
                with ui.row().classes('w-full justify-between items-center pt-6 border-t shrink-0'):
                    with ui.row().classes('gap-2'):
                        self.clone_btn = ui.button('👯 Clone', on_click=self._on_clone_clicked).props('outline color=purple')
                        self.clone_btn.disable()
                        
                        self.replace_btn = ui.button('🔄 Replace', on_click=self._on_replace_clicked).props('outline color=orange')
                        self.replace_btn.disable()
                        
                        self.delete_btn = ui.button('🗑️ Delete', on_click=self._on_delete_clicked).props('outline color=red')
                        self.delete_btn.disable()
                        
                    ui.button('💾 SAVE PREAMP', on_click=self._on_save_clicked, color='green').classes('px-10 h-12 font-bold shadow-md')

            # --- COLONNA 3: DETTAGLIO STAGE & PLOT ---
            with ui.column().classes('h-full p-6 bg-slate-50 border-l overflow-y-auto flex flex-col no-wrap'):
                ui.label('Analog Stage Editor').classes('font-bold text-slate-500 mb-4 uppercase text-xs shrink-0')
                
                self.stage_editor_cont = ui.column().classes('w-full gap-4 shrink-0')
                with self.stage_editor_cont:
                    ui.label('Select a stage to edit.').classes('text-slate-400 italic text-center w-full mt-4').bind_visibility_from(self, 'current_stage', backward=lambda x: x is None)
                    
                    self.s_name = ui.input('Stage Name', on_change=self._sync_to_list).classes('w-full')
                    self.s_name.set_visibility(False)
                    
                    with ui.row().classes('w-full gap-2'):
                        self.s_gain = ui.number('Gain (V/V)', format='%.4e', on_change=self._on_gain_change).classes('flex-grow')
                        self.s_gain.set_visibility(False)
                        self.s_in_u = ui.input('In Units').classes('w-1/4')
                        self.s_in_u.set_visibility(False)
                        self.s_out_u = ui.input('Out Units').classes('w-1/4')
                        self.s_out_u.set_visibility(False)
                    
                    self.s_pz_title = ui.label('Stage Poles & Zeros').classes('font-bold mt-2')
                    self.s_pz_title.set_visibility(False)
                    
                    with ui.row().classes('w-full gap-2 items-start'):
                        self.s_zt_col = ui.column().classes('w-[48%] border p-2 bg-white rounded')
                        self.s_zt_col.set_visibility(False)
                        self.s_pt_col = ui.column().classes('w-[48%] border p-2 bg-white rounded')
                        self.s_pt_col.set_visibility(False)
                    
                    self.apply_btn = ui.button('Apply & Refresh Plot', on_click=self._apply_stage_changes).props('color=orange').classes('w-full mt-2')
                    self.apply_btn.set_visibility(False)

                ui.label('Total Frequency Response').classes('font-bold text-slate-500 mt-8 mb-2 uppercase text-[10px] shrink-0')
                self.plot_container = ui.column().classes('w-full items-center shrink-0')

    def _on_gain_change(self):
        if not self._is_loading and self.current_stage:
            self.current_stage.stage_gain = self.s_gain.value
            self._render_stages()
            self._update_plot()

    def _sync_to_list(self):
        if not self._is_loading and self.current_stage:
            self.current_stage.name = self.s_name.value
            self._render_stages()

    def refresh_list(self):
        self.model_list.clear()
        preamps = self.eq_ctrl.get_all_preamplifiers()
        with self.model_list:
            for pre in preamps:
                item = ui.item(f"🔌 {pre.manufacturer} {pre.model}").classes('cursor-pointer hover:bg-orange-50 border-b w-full px-4 py-2')
                item.props('clickable')
                item.on('click', lambda _, pid=pre.id: self._load_selected_preamp(pid))

    def _load_selected_preamp(self, pid):
        try:
            self._selected_preamp_id = int(pid)
            self.clone_btn.enable()
            self.delete_btn.enable()
            self.replace_btn.enable()

            self.current_pre = self.eq_ctrl.get_preamplifier_by_id(int(pid))
            if not self.current_pre:
                return
            self.mfg_input.value = str(self.current_pre.manufacturer or "")
            self.model_input.value = str(self.current_pre.model or "")
            self.desc_input.value = str(self.current_pre.description or "")
            self.stages_data = [s for s in (self.current_pre.analog_stages or [])]
            self.current_stage = None
            self._render_stages()
            self._clear_stage_editor()
            self._update_plot()
        except: traceback.print_exc()

    def _render_stages(self):
        self.stages_cont.clear()
        self.stages_data.sort(key=lambda x: x.stage_sequence)
        with self.stages_cont:
            for i, stage in enumerate(self.stages_data):
                stage.stage_sequence = i + 1
                bg = 'bg-orange-100 border-orange-400' if self.current_stage == stage else 'bg-white'
                with ui.row().classes(f'w-full items-center p-3 border rounded shadow-sm gap-2 cursor-pointer hover:bg-orange-50 transition-colors {bg}').on('click', lambda _, s=stage: self._edit_stage(s)):
                    ui.label(f"S{stage.stage_sequence}").classes('font-bold w-8 text-orange-600')
                    ui.label(stage.name or "Analog Stage").classes('flex-grow text-sm font-medium')
                    ui.label(f"Gain: {stage.stage_gain}").classes('w-24 text-xs text-slate-500 text-right')
                    ui.button(icon='delete', on_click=lambda e, s=stage: self._delete_stage(s)).props('flat dense color=red size=sm')

    def _edit_stage(self, stage):
        self._is_loading = True
        self.current_stage = stage
        self._render_stages()
        
        for el in [self.s_name, self.s_gain, self.s_in_u, self.s_out_u, self.s_pz_title, self.s_zt_col, self.s_pt_col, self.apply_btn]:
            el.set_visibility(True)
            
        self.s_name.value = stage.name
        self.s_gain.value = stage.stage_gain
        self.s_in_u.value = stage.input_units or "V"
        self.s_out_u.value = stage.output_units or "V"
        
        self._render_pz_tables(stage)
        self._is_loading = False
        self._update_plot()

    def _render_pz_tables(self, stage):
        self.s_zt_col.clear(); self.s_zeros_ui.clear()
        self.s_pt_col.clear(); self.s_poles_ui.clear()
        with self.s_zt_col:
            ui.label('Zeros').classes('text-[10px] font-bold text-center w-full uppercase text-slate-400')
            for z in (stage.zeros or []): self._add_pz_row(self.s_zt_col, self.s_zeros_ui, z.real_val, z.imag_val)
            ui.button('+ Z', on_click=lambda: self._add_pz_row(self.s_zt_col, self.s_zeros_ui)).props('flat dense size=sm color=orange')
        with self.s_pt_col:
            ui.label('Poles').classes('text-[10px] font-bold text-center w-full uppercase text-slate-400')
            for p in (stage.poles or []): self._add_pz_row(self.s_pt_col, self.s_poles_ui, p.real_val, p.imag_val)
            ui.button('+ P', on_click=lambda: self._add_pz_row(self.s_pt_col, self.s_poles_ui)).props('flat dense size=sm color=orange')

    def _add_pz_row(self, container, registry, r=0.0, i=0.0):
        with container:
            with ui.row().classes('w-full items-center no-wrap gap-1 border-b pb-1 mb-1') as row:
                rv = ui.number(value=r, on_change=lambda: self._update_plot()).props('dense size=xs step=any').classes('w-14')
                iv = ui.number(value=i, on_change=lambda: self._update_plot()).props('dense size=xs step=any').classes('w-14')
                ui.button(icon='remove', on_click=lambda: self._remove_pz_row(row, registry, (rv, iv))).props('flat dense color=red size=sm')
                registry.append((rv, iv))

    def _remove_pz_row(self, row, registry, item):
        row.delete()
        if item in registry: registry.remove(item)
        self._update_plot()

    def _update_plot(self):
        if self._is_loading: return
        self.plot_container.clear()
        if not self.stages_data: return
        with self.plot_container:
            with ui.pyplot(figsize=(3.5, 5)) as plot:
                ax_mag = plot.fig.add_subplot(211); ax_phase = plot.fig.add_subplot(212)
                try:
                    w = np.logspace(-2, 3, 1000) * 2 * np.pi
                    total_h = np.ones_like(w, dtype=complex)
                    for s in self.stages_data:
                        if s == self.current_stage:
                            g = float(self.s_gain.value or 1.0)
                            z = [complex(float(rv.value or 0), float(iv.value or 0)) for rv, iv in self.s_zeros_ui]
                            p = [complex(float(rv.value or 0), float(iv.value or 0)) for rv, iv in self.s_poles_ui]
                        else:
                            g = float(s.stage_gain or 1.0)
                            z = [complex(pz.real_val, pz.imag_val) for pz in (s.zeros or [])]
                            p = [complex(pz.real_val, pz.imag_val) for pz in (s.poles or [])]
                        if not p: p = [complex(-1e9, 0)]
                        sys = signal.lti(z, p, g)
                        _, h = signal.freqresp(sys, w=w); total_h *= h
                    f = w / (2 * np.pi)
                    ax_mag.semilogx(f, 20 * np.log10(np.abs(total_h) + 1e-12), color='blue')
                    ax_mag.set_ylabel("dB", fontsize=8); ax_mag.grid(True, which='both', ls=':', alpha=0.5)
                    ax_phase.semilogx(f, np.degrees(np.unwrap(np.angle(total_h))), color='green')
                    ax_phase.set_xlabel("Hz", fontsize=8); ax_phase.grid(True, which='both', ls=':', alpha=0.5)
                    plot.fig.tight_layout()
                except: pass

    def _apply_stage_changes(self):
        if not self.current_stage: return
        self.current_stage.name = self.s_name.value
        self.current_stage.stage_gain = self.s_gain.value
        self.current_stage.zeros = [PoleZero(real_val=float(rv.value or 0), imag_val=float(iv.value or 0)) for rv, iv in self.s_zeros_ui]
        self.current_stage.poles = [PoleZero(real_val=float(rv.value or 0), imag_val=float(iv.value or 0)) for rv, iv in self.s_poles_ui]
        self._render_stages(); self._update_plot()
        ui.notify("Stage applied")

    def _add_stage(self):
        s = AnalogStage(stage_sequence=len(self.stages_data)+1, name="Analog Stage", stage_gain=1.0)
        self.stages_data.append(s); self._render_stages(); self._edit_stage(s)

    def _delete_stage(self, s):
        if s in self.stages_data: self.stages_data.remove(s)
        self.current_stage = None; self._render_stages(); self._clear_stage_editor(); self._update_plot()

    def _on_save_clicked(self):
        if not self.current_pre: return
        self.current_pre.manufacturer = self.mfg_input.value
        self.current_pre.model = self.model_input.value
        self.current_pre.description = self.desc_input.value
        self.current_pre.analog_stages = self.stages_data
        if self.eq_ctrl.save_preamplifier(self.current_pre):
            ui.notify("Preamplifier saved!"); self.refresh_list()

    def _prepare_new_model(self):
        self.current_pre = Preamplifier(manufacturer="", model="")
        self._selected_preamp_id = None
        self.mfg_input.value = ""; self.model_input.value = ""; self.desc_input.value = ""
        self.stages_data = []
        self._render_stages(); self._clear_stage_editor(); self._update_plot()
        self.clone_btn.disable(); self.delete_btn.disable(); self.replace_btn.disable()

    def _on_clone_clicked(self):
        pid = self._selected_preamp_id
        if pid is None and self.current_pre and getattr(self.current_pre, "id", None):
            pid = int(self.current_pre.id)
        if pid is None:
            ui.notify("Seleziona un preamplificatore salvato nel catalogo.", type="warning")
            return
        try:
            src = self.eq_ctrl.get_preamplifier_by_id(int(pid))
            if not src:
                ui.notify("Preamplifier non trovato.", type="negative")
                return
            dup = self.eq_ctrl.clone_preamplifier_model(src)
            saved = self.eq_ctrl.save_preamplifier(dup)
            if not saved:
                ui.notify("Salvataggio del duplicato non riuscito.", type="negative")
                return
            self.refresh_list()
            self._load_selected_preamp(saved.id)
            ui.notify(f"Duplicato creato in catalogo: {saved.model}", type="positive")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore duplicazione: {e}", type="negative")

    async def _on_delete_clicked(self):
        pid = self._selected_preamp_id or (
            int(self.current_pre.id) if self.current_pre and getattr(self.current_pre, "id", None) else None
        )
        if not pid:
            ui.notify("Nessun preamplificatore selezionato.", type="warning")
            return
        pa = (
            self.current_pre
            if (self.current_pre and getattr(self.current_pre, "id", None) == pid)
            else self.eq_ctrl.get_preamplifier_by_id(int(pid))
        )
        display = (
            f"{getattr(pa, 'manufacturer', '')} {getattr(pa, 'model', '')}".strip()
            if pa
            else f"ID {pid}"
        )
        if not display:
            display = f"ID {pid}"

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
            if self.eq_ctrl.delete_preamplifier(int(pid)):
                ui.notify("Preamplificatore eliminato dal catalogo.", type="info")
                self._prepare_new_model()
                self.refresh_list()
        except ValueError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore eliminazione: {e}", type="negative")

    def _on_replace_clicked(self):
        pid = self._selected_preamp_id or (
            int(self.current_pre.id) if self.current_pre and getattr(self.current_pre, "id", None) else None
        )
        if not pid:
            ui.notify("Seleziona un preamplificatore salvato.", type="warning")
            return
        others = [p for p in self.eq_ctrl.get_all_preamplifiers() if p.id != pid]
        opts = {p.id: f"{p.manufacturer} {p.model}" for p in others}
        if not opts:
            ui.notify("Nessun altro preamplificatore nel catalogo.", type="warning")
            return
        with ui.dialog() as d, ui.card().classes('w-96 p-6'):
            ui.label('Replace Preamplifier').classes('text-lg font-bold mb-4')
            sel = ui.select(opts, label="Select replacement", with_input=True).classes('w-full')
            with ui.row().classes('w-full justify-end mt-4'):
                ui.button('Cancel', on_click=d.close).props('flat')
                ui.button('Confirm', color='orange', on_click=lambda: (
                    self.eq_ctrl.replace_equipment('preamplifier', pid, sel.value),
                    d.close(),
                    self.refresh_list(),
                    self._prepare_new_model(),
                ))
        d.open()

    def _clear_stage_editor(self):
        self.current_stage = None
        for el in [self.s_name, self.s_gain, self.s_in_u, self.s_out_u, self.s_pz_title, self.s_zt_col, self.s_pt_col, self.apply_btn]:
            el.set_visibility(False)
