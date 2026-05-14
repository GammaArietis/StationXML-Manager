import json

from nicegui import ui

from core.models.base_models import Channel
from web_gui.date_form_helpers import datetime_local_to_db, iso_to_datetime_local_field

class ChannelView:
    def __init__(self, cha_ctrl, eq_ctrl, on_save):
        self.cha_ctrl = cha_ctrl
        self.eq_ctrl = eq_ctrl
        self.on_save = on_save

    def build_ui(self, channel: Channel):
        ui.label(f'〰️ Channel: {channel.code}').classes('text-3xl font-bold text-slate-800 mb-6')
        
        # --- BLOCCO 1: IDENTIFICATIVI E TIPI ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm border-t-4 border-orange-500'):
            ui.label('Identifiers & Types').classes('text-lg font-bold mb-4 text-orange-700')
            with ui.row().classes('w-full gap-4'):
                self.code_in = ui.input('Channel Code (*)', value=channel.code).classes('w-1/4').props('uppercase')
                self.loc_in = ui.input('Location Code', value=channel.location_code or "").classes('w-1/4').props('placeholder="--"')
                self.depth_in = ui.number('Depth (m)', value=channel.depth or 0.0).classes('w-1/4')
                
            with ui.row().classes('w-full gap-4 mt-4'):
                types_options = ["CONTINUOUS,GEOPHYSICAL", "TRIGGERED,GEOPHYSICAL", "SYNTHETIC,GEOPHYSICAL",
                                 "CONTINUOUS,HEALTH", "CONTINUOUS,WEATHER", "CONTINUOUS,FLAG"]
                # with_input=True permette di scrivere tipi custom se non in lista
                self.types_in = ui.select(types_options, label='Channel Types (FDSN)', value=channel.types or "CONTINUOUS,GEOPHYSICAL", with_input=True).classes('flex-grow')

        # --- BLOCCO 2: PARAMETRI TECNICI ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Technical Parameters').classes('text-lg font-bold mb-4 text-slate-700')
            with ui.row().classes('w-full gap-4'):
                self.sr_in = ui.number('Sample Rate (Hz)', value=channel.sample_rate or 100.0).classes('w-1/5')
                self.drift_in = ui.number('Clock Drift (s/s)', value=getattr(channel, 'clock_drift', 0.0) or 0.0, format='%.6f').classes('w-1/5')
                self.azi_in = ui.number('Azimuth (°)', value=channel.azimuth or 0.0).classes('w-1/5')
                self.dip_in = ui.number('Dip (°)', value=channel.dip or -90.0).classes('w-1/5')

            with ui.row().classes('w-full gap-4 mt-4 items-center'):
                self.cal_units_in = ui.select(["", "V", "A", "COUNTS", "m/s", "m/s**2"], label='Calibration Units', value=getattr(channel, 'calibration_units', ""), with_input=True).classes('w-1/4')
                self.sens_in = ui.input('Forced Total Sensitivity', value=str(getattr(channel, 'overall_sensitivity', '') or '')).classes('w-1/3').props('placeholder="Leave empty for auto"')
                ui.button('🧮 Calculate', on_click=self._calc_sensitivity, color='info').classes('mt-2')

        # --- BLOCCO 3: STRUMENTAZIONE (CATALOGHI E SERIALI) ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm bg-slate-50'):
            ui.label('Instrumentation & Serials').classes('text-lg font-bold mb-4 text-slate-700')
            
            sensors = {None: '--- No Sensor ---'}
            for s in self.eq_ctrl.get_all_sensors(): sensors[s.id] = f"{s.manufacturer} {s.model}"
            
            loggers = {None: '--- No Datalogger ---'}
            for l in self.eq_ctrl.get_all_dataloggers(): loggers[l.id] = f"{l.manufacturer} {l.model}"
            
            preamps = {None: '--- No Pre-Amp ---'}
            for p in self.eq_ctrl.get_all_preamplifiers(): preamps[p.id] = f"{p.manufacturer} {p.model}"

            with ui.row().classes('w-full gap-4 items-center'):
                self.sensor_cb = ui.select(sensors, label='Sensor', value=channel.sensor_id).classes('w-1/2')
                self.sensor_sn = ui.input('Sensor S/N', value=channel.sensor_serial_number or "").classes('w-1/3')

            with ui.row().classes('w-full gap-4 mt-2 items-center'):
                self.logger_cb = ui.select(loggers, label='Datalogger', value=channel.datalogger_id).classes('w-1/2')
                self.logger_sn = ui.input('Datalogger S/N', value=channel.datalogger_serial_number or "").classes('w-1/3')

            with ui.row().classes('w-full gap-4 mt-2 items-center'):
                self.preamp_cb = ui.select(preamps, label='Pre-Amplifier', value=getattr(channel, 'pre_amplifier_id', None)).classes('w-2/5')
                self.preamp_sn = ui.input('Pre-Amp S/N', value=getattr(channel, 'pre_amplifier_serial_number', "")).classes('w-1/5')
                self.preamp_gain = ui.number('Pre-Amp Gain', value=getattr(channel, 'pre_amplifier_gain', 1.0) or 1.0).classes('w-1/5')

        # --- BLOCCO 4: DATE ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Epoch Dates').classes('text-lg font-bold mb-4 text-slate-700')
            with ui.column().classes('w-full gap-4'):
                with ui.row().classes('w-full gap-4 items-end'):
                    self.start_set = ui.checkbox(
                        'Set start date',
                        value=bool(channel.start_date and str(channel.start_date).strip()),
                    ).classes('shrink-0')
                    self.start_in = ui.input(
                        'Start Date',
                        value=iso_to_datetime_local_field(channel.start_date),
                    ).props('type=datetime-local').classes('w-1/3')
                    self.start_in.bind_enabled_from(self.start_set, 'value')
                with ui.row().classes('w-full gap-4 items-end'):
                    self.end_set = ui.checkbox(
                        'Set end date',
                        value=bool(channel.end_date and str(channel.end_date).strip()),
                    ).classes('shrink-0')
                    self.end_in = ui.input(
                        'End Date',
                        value=iso_to_datetime_local_field(channel.end_date),
                    ).props('type=datetime-local').classes('w-1/3')
                    self.end_in.bind_enabled_from(self.end_set, 'value')

        # --- BLOCCO 5: COMMENTI FDSN ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Channel Comments (FDSN)').classes('text-lg font-bold mb-4 text-slate-700')
            self.comments_container = ui.column().classes('w-full gap-2')
            self.comments_ui_elements = []
            
            try: loaded_comments = json.loads(channel.comments) if channel.comments else []
            except: loaded_comments = []
                
            def add_comment_row(c_val="", c_start="", c_end="", c_sub="", c_auth=""):
                with self.comments_container:
                    with ui.row().classes('w-full gap-2 items-center bg-slate-50 p-2 rounded border') as row:
                        v = ui.input('Text', value=c_val).classes('flex-grow')
                        st = ui.input('Start', value=c_start).classes('w-32').props('placeholder=YYYY-MM-DD')
                        en = ui.input('End', value=c_end).classes('w-32').props('placeholder=YYYY-MM-DD')
                        sub = ui.input('Subject', value=c_sub).classes('w-32')
                        auth = ui.input('Author', value=c_auth).classes('w-48')
                        btn_remove = ui.button(icon='delete', color='red').props('flat dense')
                        item_tuple = (v, st, en, sub, auth)
                        self.comments_ui_elements.append(item_tuple)
                        btn_remove.on('click', lambda r=row, it=item_tuple: remove_comment_row(r, it))

            def remove_comment_row(row_element, item_tuple):
                row_element.delete()
                if item_tuple in self.comments_ui_elements: self.comments_ui_elements.remove(item_tuple)

            for c in loaded_comments:
                auth_str = c.get('author_name', '')
                if c.get('author_agency'): auth_str += f" ({c.get('author_agency')})"
                add_comment_row(c.get('value',''), c.get('begin_date',''), c.get('end_date',''), c.get('subject',''), auth_str)

            ui.button('+ Add Comment', on_click=lambda: add_comment_row(), color='blue').classes('mt-4').props('outline')

        # --- BLOCCO 6: AZIONI ---
        with ui.row().classes('w-full justify-between mt-6'):
            with ui.row().classes('gap-4'):
                ui.button('🗑️ Delete', color='red', on_click=lambda: self.delete(channel.id)).props('outline')
                ui.button('👯 Clone Epoch', color='purple', on_click=lambda: self._clone()).props('outline')
            ui.button('💾 Save Channel', on_click=lambda: self.save(channel), color='green').classes('px-10 font-bold')

    def _calc_sensitivity(self):
        s_id = self.sensor_cb.value
        p_id = self.preamp_cb.value
        d_id = self.logger_cb.value
        
        if not s_id:
            ui.notify("Select at least one Sensor to calculate sensitivity.", type='warning')
            return
            
        temp_cha = Channel(sensor_id=s_id, pre_amplifier_id=p_id, datalogger_id=d_id)
        try:
            calc_val = self.cha_ctrl.calculate_total_sensitivity(temp_cha)
            if calc_val is not None:
                self.sens_in.value = f"{calc_val:.6e}"
                ui.notify(f"Sensitivity calculated: {calc_val:.6e}", type='positive')
            else:
                ui.notify("Unable to calculate. Verify instrument gains in catalog.", type='negative')
        except Exception as e:
            ui.notify(f"Calculation Error: {e}", type='negative')

    def _clone(self):
        # Replica il comportamento del clone desktop: epoch senza date finché l'utente non le imposta
        self.start_set.value = False
        self.end_set.value = False
        self.start_in.value = ""
        self.end_in.value = ""
        ui.notify(
            "Date epoch azzerate. Spunta «Set start date», imposta l'inizio e salva per creare un nuovo epoch.",
            type="info",
        )

    def save(self, channel):
        code = self.code_in.value.strip().upper() if self.code_in.value else ""
        if not code:
            ui.notify("Channel code is required!", type='negative')
            return
            
        raw_loc = self.loc_in.value.strip() if self.loc_in.value else ""
        final_loc = "" if raw_loc == "--" else raw_loc
        
        sens_text = self.sens_in.value.strip() if self.sens_in.value else ""
        final_sens = None
        if sens_text:
            try: final_sens = float(sens_text)
            except ValueError:
                ui.notify("Invalid sensitivity format!", type='negative')
                return

        channel.code = code
        channel.location_code = final_loc
        channel.depth = self.depth_in.value
        channel.sample_rate = self.sr_in.value
        channel.azimuth = self.azi_in.value
        channel.dip = self.dip_in.value
        channel.start_date = datetime_local_to_db(bool(self.start_set.value), self.start_in.value)
        channel.end_date = datetime_local_to_db(bool(self.end_set.value), self.end_in.value)
        channel.sensor_id = self.sensor_cb.value
        channel.datalogger_id = self.logger_cb.value
        channel.overall_sensitivity = final_sens
        channel.sensor_serial_number = self.sensor_sn.value or None
        channel.datalogger_serial_number = self.logger_sn.value or None
        channel.types = self.types_in.value
        channel.clock_drift = self.drift_in.value
        channel.calibration_units = self.cal_units_in.value or None
        
        # Gestione sicura del pre-amplificatore (se esiste nel modello DB)
        if hasattr(channel, 'pre_amplifier_id'):
            channel.pre_amplifier_id = self.preamp_cb.value
            channel.pre_amplifier_serial_number = self.preamp_sn.value or None
            channel.pre_amplifier_gain = self.preamp_gain.value

        # Commenti
        c_list = []
        for v, st, en, sub, auth in self.comments_ui_elements:
            val_text = v.value.strip() if v.value else ""
            if not val_text: continue
            auth_text = auth.value.strip() if auth.value else ""
            author_name = auth_text; author_agency = ""
            if "(" in auth_text and ")" in auth_text:
                parts = auth_text.split("(")
                author_name = parts[0].strip(); author_agency = parts[1].replace(")", "").strip()

            c_list.append({
                "value": val_text, "begin_date": st.value.strip() if st.value else "",
                "end_date": en.value.strip() if en.value else "", "subject": sub.value.strip() if sub.value else "",
                "author_name": author_name, "author_agency": author_agency
            })
            
        channel.comments = json.dumps(c_list) if c_list else None
        
        try:
            self.cha_ctrl.save_channel(channel)
            ui.notify(f"Channel {code} saved successfully!", type='positive')
            self.on_save()
        except Exception as e:
            ui.notify(f"Save error: {e}", type='negative')

    async def delete(self, cha_id):
        with ui.dialog() as dialog, ui.card():
            ui.label('Are you sure you want to delete this epoch?').classes('text-lg font-bold text-slate-800')
            with ui.row().classes('w-full justify-end mt-4 gap-2'):
                ui.button('Cancel', on_click=lambda: dialog.submit(False)).props('flat text-color=grey')
                ui.button('Yes, Delete', on_click=lambda: dialog.submit(True)).classes('bg-red-600 text-white font-bold')
                
        result = await dialog
        
        if result:
            try:
                self.cha_ctrl.delete_channel(cha_id)
                ui.notify("Channel deleted.", type='info')
                self.on_save()
            except Exception as e:
                ui.notify(f"Error: {e}", type='negative')
