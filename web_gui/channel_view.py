import json
from datetime import datetime

from nicegui import ui

from core.models.base_models import Channel
from utils.fdsn_coordinates import resolve_channel_position

class ChannelView:
    def __init__(self, cha_ctrl, eq_ctrl, on_save, sta_ctrl=None):
        self.cha_ctrl = cha_ctrl
        self.eq_ctrl = eq_ctrl
        self.sta_ctrl = sta_ctrl
        self.on_save = on_save
        self._start_date_raw_value = None
        self._end_date_raw_value = None
        self._parent_station_id = None

    @staticmethod
    def _nrl_status_icon(item) -> str:
        return '🟢' if getattr(item, 'nrl_path', None) else '🔴'

    @staticmethod
    def _datetime_display_value(raw_value) -> str:
        """Render stored ISO dates in a stable text format for NiceGUI binding."""
        if raw_value is None:
            return ""
        value = str(raw_value).strip()
        if not value:
            return ""
        value = value.replace("T", " ")
        if len(value) == 16:
            return f"{value}:00"
        return value[:19] if len(value) >= 19 else value

    @staticmethod
    def _normalize_datetime_text(raw_value) -> str | None:
        """Normalize text/picker values to YYYY-MM-DD HH:MM:SS, or None if empty."""
        if raw_value is None:
            return None
        value = str(raw_value).strip().replace("T", " ")
        if not value:
            return None
        if len(value) == 10:
            value = f"{value} 00:00:00"
        elif len(value) == 16:
            value = f"{value}:00"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        raise ValueError("Use format YYYY-MM-DD HH:MM:SS")

    @staticmethod
    def _split_datetime_parts(raw_value) -> tuple[str | None, str | None]:
        value = ChannelView._datetime_display_value(raw_value)
        if not value:
            return None, None
        return value[:10], value[11:16] if len(value) >= 16 else None

    def _set_datetime_date_part(self, attr_name: str, date_value: str | None) -> None:
        if not date_value:
            return
        current = self._datetime_display_value(getattr(self, attr_name, ""))
        time_part = current[11:19] if len(current) >= 19 else "00:00:00"
        setattr(self, attr_name, f"{date_value} {time_part}")

    def _set_datetime_time_part(self, attr_name: str, time_value: str | None) -> None:
        if not time_value:
            return
        current = self._datetime_display_value(getattr(self, attr_name, ""))
        date_part = current[:10] if len(current) >= 10 else datetime.now().strftime("%Y-%m-%d")
        clean_time = str(time_value).strip()
        if len(clean_time) == 5:
            clean_time = f"{clean_time}:00"
        setattr(self, attr_name, f"{date_part} {clean_time}")

    def _build_datetime_input(self, label: str, attr_name: str, enabled_checkbox):
        date_part, time_part = self._split_datetime_parts(getattr(self, attr_name, ""))
        with ui.input(label).props(
            'mask="####-##-## ##:##:##" placeholder="YYYY-MM-DD HH:MM:SS" '
            'hint="Data e ora di inizio o fine validità dell epoca strumentale espresse in tempo coordinato universale (UTC)."'
        ).classes('w-1/3') as input_field:
            input_field.bind_value(self, attr_name)
            with input_field.add_slot('append'):
                with ui.button(icon='calendar_month').props('flat round dense') as calendar_btn:
                    calendar_btn.tooltip('Apri selettori calendario e orologio per compilare il timestamp UTC dell epoca canale.')
                    with ui.menu():
                        ui.date(
                            value=date_part,
                            on_change=lambda e: self._set_datetime_date_part(attr_name, e.value),
                        )
                        ui.time(
                            value=time_part,
                            on_change=lambda e: self._set_datetime_time_part(attr_name, e.value),
                        ).props('format24h')
        input_field.bind_enabled_from(enabled_checkbox, 'value')
        return input_field

    def _on_end_set_changed(self) -> None:
        if self.end_set.value:
            if not str(self._end_date_raw_value or "").strip():
                current_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self._end_date_raw_value = current_ts
                self.end_in.value = current_ts
        else:
            self._end_date_raw_value = ""
            self.end_in.value = ""

    def _station_coords(self, station_id):
        if not self.sta_ctrl or not station_id:
            return None, None, None
        station = self.sta_ctrl.get_station_by_id(station_id)
        if not station:
            return None, None, None
        return station.latitude, station.longitude, station.elevation

    def _display_channel_coords(self, channel: Channel):
        st_lat, st_lon, st_elev = self._station_coords(channel.station_id)
        return resolve_channel_position(
            channel.latitude,
            channel.longitude,
            channel.elevation,
            st_lat,
            st_lon,
            st_elev,
        )

    def _copy_station_coords_to_form(self):
        lat, lon, elev = self._station_coords(self._parent_station_id)
        if lat is None and lon is None and elev is None:
            ui.notify("Station coordinates not available.", type='warning')
            return
        if lat is not None:
            self.lat_in.value = lat
        if lon is not None:
            self.lon_in.value = lon
        if elev is not None:
            self.elev_in.value = elev
        ui.notify("Coordinates copied from station.", type='info')

    def build_ui(self, channel: Channel):
        ui.label(f'〰️ Channel: {channel.code}').classes('text-3xl font-bold text-slate-800 mb-6')
        self._parent_station_id = channel.station_id
        self._start_date_raw_value = self._datetime_display_value(channel.start_date)
        self._end_date_raw_value = self._datetime_display_value(channel.end_date)
        disp_lat, disp_lon, disp_elev = self._display_channel_coords(channel)
        
        # --- BLOCCO 1: IDENTIFICATIVI E TIPI ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm border-t-4 border-orange-500'):
            ui.label('Identifiers & Types').classes('text-lg font-bold mb-4 text-orange-700')
            with ui.row().classes('w-full gap-4'):
                self.code_in = ui.input('Channel Code (*)', value=channel.code).classes('w-1/4').props(
                    'uppercase placeholder="HHZ, BHN, LHE" '
                    'hint="Codice di tre caratteri del canale sismico secondo lo standard SEED (Banda, Strumento, Orientamento)."'
                )
                self.loc_in = ui.input('Location Code', value=channel.location_code or "").classes('w-1/4').props(
                    'placeholder="--" hint="Codice location FDSN a due caratteri; usare vuoto o -- per installazione principale."'
                )
                self.depth_in = ui.number('Depth (m)', value=channel.depth or 0.0).classes('w-1/4').props(
                    'placeholder="0.0" hint="Profondità del sensore rispetto al riferimento stazione, espressa in metri."'
                )
                
            with ui.row().classes('w-full gap-4 mt-4'):
                types_options = ["CONTINUOUS,GEOPHYSICAL", "TRIGGERED,GEOPHYSICAL", "SYNTHETIC,GEOPHYSICAL",
                                 "CONTINUOUS,HEALTH", "CONTINUOUS,WEATHER", "CONTINUOUS,FLAG"]
                # with_input=True permette di scrivere tipi custom se non in lista
                self.types_in = ui.select(types_options, label='Channel Types (FDSN)', value=channel.types or "CONTINUOUS,GEOPHYSICAL", with_input=True).classes('flex-grow')
                self.types_in.tooltip('Classificazione FDSN del canale: continuità del flusso e dominio fisico del dato, ad esempio GEOPHYSICAL o HEALTH.')
            with ui.row().classes('w-full gap-4 mt-4'):
                self.restr_in = ui.select(
                    ['open', 'closed', 'partial'],
                    label='Restricted Status',
                    value=getattr(channel, 'restricted_status', None) or 'open',
                ).classes('w-1/3')
                self.restr_in.tooltip('Stato FDSN restrictedStatus applicato all epoca canale e ai dati sismici associati.')

        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Position (FDSN)').classes('text-lg font-bold mb-4 text-slate-700')
            with ui.row().classes('w-full gap-4 items-end'):
                self.lat_in = ui.number(
                    'Latitude',
                    value=disp_lat if disp_lat is not None else 0.0,
                    format='%.5f',
                    step=0.00001,
                ).classes('w-1/5').props(
                    'placeholder="41.8902" '
                    'hint="Quota del canale in gradi decimali WGS84; se omessa in StationXML si eredita dalla stazione."'
                )
                self.lon_in = ui.number(
                    'Longitude',
                    value=disp_lon if disp_lon is not None else 0.0,
                    format='%.5f',
                    step=0.00001,
                ).classes('w-1/5').props(
                    'placeholder="12.4922" '
                    'hint="Longitudine del canale in gradi decimali WGS84."'
                )
                self.elev_in = ui.number(
                    'Elevation (m)',
                    value=disp_elev if disp_elev is not None else 0.0,
                ).classes('w-1/5').props(
                    'placeholder="-100.0" '
                    'hint="Elevazione assoluta del sensore in metri sul livello medio del mare (m s.l.m.)."'
                )
                copy_btn = ui.button('Copy from station', on_click=self._copy_station_coords_to_form).props('outline')
                copy_btn.tooltip('Copia latitudine, longitudine ed elevazione dalla stazione parent.')

        # --- BLOCCO 2: PARAMETRI TECNICI ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Technical Parameters').classes('text-lg font-bold mb-4 text-slate-700')
            with ui.row().classes('w-full gap-4'):
                self.sr_in = ui.number('Sample Rate (Hz)', value=channel.sample_rate or 100.0).classes('w-1/5').props(
                    'placeholder="100.0" hint="Frequenza di campionamento digitalizzata espressa in Hertz (Hz)."'
                )
                self.drift_in = ui.number('Clock Drift (s/s)', value=getattr(channel, 'clock_drift', 0.0) or 0.0, format='%.6f').classes('w-1/5').props(
                    'placeholder="0.000000" hint="Deriva nominale dell orologio del datalogger espressa in secondi per secondo o campione secondo il metadato disponibile."'
                )
                self.azi_in = ui.number('Azimuth (°)', value=channel.azimuth or 0.0).classes('w-1/5')
                self.azi_in.tooltip('Azimuth sismologico: gradi in senso orario dal Nord geografico WGS84 (0-360).')
                self.dip_in = ui.number('Dip (°)', value=channel.dip or -90.0).classes('w-1/5')
                self.dip_in.tooltip('Angolo verticale del componente: -90 Up, 0 orizzontale, +90 Down secondo convenzione FDSN/SEED.')

            with ui.row().classes('w-full gap-4 mt-4 items-center'):
                self.cal_units_in = ui.select(["", "V", "A", "COUNTS", "m/s", "m/s**2"], label='Calibration Units', value=getattr(channel, 'calibration_units', ""), with_input=True).classes('w-1/4')
                self.cal_units_in.tooltip('Unità fisiche usate per la calibrazione: m/s per velocimetri, m/s**2 per accelerometri, COUNTS per segnali digitali.')
                self.sens_in = ui.input('Forced Total Sensitivity', value=str(getattr(channel, 'overall_sensitivity', '') or '')).classes('w-1/3').props(
                    'placeholder="1.234567e+09" hint="Sensibilità totale canale; se vuota viene calcolata moltiplicando i gain degli stadi strumentali."'
                )
                calc_btn = ui.button('🧮 Calculate', on_click=self._calc_sensitivity, color='info').classes('mt-2')
                calc_btn.tooltip('Ricalcola la sensibilità totale combinando sensor, preamplificatore e datalogger secondo la catena strumentale.')

        # --- BLOCCO 3: STRUMENTAZIONE (CATALOGHI E SERIALI) ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm bg-slate-50'):
            ui.label('Instrumentation & Serials').classes('text-lg font-bold mb-4 text-slate-700')
            
            sensors = {None: '⚪ --- No Sensor ---'}
            for s in self.eq_ctrl.get_all_sensors():
                sensors[s.id] = f"{self._nrl_status_icon(s)} {s.manufacturer} {s.model}"
            
            loggers = {None: '⚪ --- No Datalogger ---'}
            for l in self.eq_ctrl.get_all_dataloggers():
                loggers[l.id] = f"{self._nrl_status_icon(l)} {l.manufacturer} {l.model}"
            
            preamps = {None: '--- No Pre-Amp ---'}
            for p in self.eq_ctrl.get_all_preamplifiers(): preamps[p.id] = f"{p.manufacturer} {p.model}"

            with ui.row().classes('w-full gap-4 items-center'):
                self.sensor_cb = ui.select(sensors, label='Sensor', value=channel.sensor_id, with_input=True).classes('w-1/2')
                self.sensor_cb.tooltip('Seleziona un modello validato dall inventario centralizzato. Qualsiasi modifica a questa strumentazione sul canale corrente verrà automaticamente estesa ai canali fratelli della terna (Z, N, E) tramite Triad Sync per preservare l integrità del set di sensori.')
                self.sensor_sn = ui.input('Sensor S/N', value=channel.sensor_serial_number or "").classes('w-1/3').props(
                    'placeholder="1234" hint="Numero seriale fisico del sensore installato, utile per tracciabilità metrologica e manutenzione."'
                )

            with ui.row().classes('w-full gap-4 mt-2 items-center'):
                self.logger_cb = ui.select(loggers, label='Datalogger', value=channel.datalogger_id, with_input=True).classes('w-1/2')
                self.logger_cb.tooltip('Seleziona un modello validato dall inventario centralizzato. Il datalogger definisce gain digitale, decimazioni, delay, correction e sample rate del canale.')
                self.logger_sn = ui.input('Datalogger S/N', value=channel.datalogger_serial_number or "").classes('w-1/3').props(
                    'placeholder="5678" hint="Numero seriale del digitalizzatore associato alla catena di acquisizione del canale."'
                )

            with ui.row().classes('w-full gap-4 mt-2 items-center'):
                self.preamp_cb = ui.select(preamps, label='Pre-Amplifier', value=getattr(channel, 'pre_amplifier_id', None), with_input=True).classes('w-2/5')
                self.preamp_cb.tooltip('Seleziona un preamplificatore validato dall inventario centralizzato per rappresentare lo stadio analogico tra sensore e datalogger.')
                self.preamp_sn = ui.input('Pre-Amp S/N', value=getattr(channel, 'pre_amplifier_serial_number', "")).classes('w-1/5').props(
                    'placeholder="SN-999" hint="Numero seriale del preamplificatore o condizionatore analogico installato."'
                )
                self.preamp_gain = ui.number('Pre-Amp Gain', value=getattr(channel, 'pre_amplifier_gain', 1.0) or 1.0).classes('w-1/5').props(
                    'placeholder="1.0" hint="Gain lineare dello stadio preamplificatore applicato alla sensibilità totale del canale."'
                )

        # --- BLOCCO 4: DATE ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Epoch Dates').classes('text-lg font-bold mb-4 text-slate-700')
            with ui.column().classes('w-full gap-4'):
                with ui.row().classes('w-full gap-4 items-end'):
                    self.start_set = ui.checkbox(
                        'Set start date',
                        value=bool(channel.start_date and str(channel.start_date).strip()),
                    ).classes('shrink-0')
                    self.start_set.tooltip('Abilita la data UTC di inizio validità dell epoca strumentale del canale.')
                    self.start_in = self._build_datetime_input(
                        'Start Date (YYYY-MM-DD HH:MM:SS)',
                        '_start_date_raw_value',
                        self.start_set,
                    )
                with ui.row().classes('w-full gap-4 items-end'):
                    self.end_set = ui.checkbox(
                        'Set end date',
                        value=bool(channel.end_date and str(channel.end_date).strip()),
                        on_change=lambda _: self._on_end_set_changed(),
                    ).classes('shrink-0')
                    self.end_set.tooltip('Spuntando questo campo, viene iniettato il timestamp UTC corrente (Smart Default) per chiudere visivamente l epoca e predisporre la terna alla sincronizzazione.')
                    self.end_in = self._build_datetime_input(
                        'End Date (YYYY-MM-DD HH:MM:SS)',
                        '_end_date_raw_value',
                        self.end_set,
                    )

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
                        v = ui.input('Text', value=c_val).classes('flex-grow').props('hint="Annotazione FDSN dell epoca canale: calibrazione, sostituzione strumento, orientamento o qualità del segnale."')
                        st = ui.input('Start', value=c_start).classes('w-32').props('placeholder=YYYY-MM-DD hint="Data UTC di inizio validità del commento canale."')
                        en = ui.input('End', value=c_end).classes('w-32').props('placeholder=YYYY-MM-DD hint="Data UTC di fine validità del commento canale."')
                        sub = ui.input('Subject', value=c_sub).classes('w-32').props('placeholder="calibration" hint="Categoria tecnica della nota: calibration, orientation, maintenance o response."')
                        auth = ui.input('Author', value=c_auth).classes('w-48').props('placeholder="INGV Metadata Office" hint="Autore o agenzia responsabile della nota StationXML."')
                        btn_remove = ui.button(icon='delete', color='red').props('flat dense')
                        btn_remove.tooltip('Rimuove questa annotazione dalla serializzazione StationXML del canale.')
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

            add_comment_btn = ui.button('+ Add Comment', on_click=lambda: add_comment_row(), color='blue').classes('mt-4').props('outline')
            add_comment_btn.tooltip('Aggiunge una nota FDSN con finestra temporale UTC per documentare eventi tecnici dell epoca canale.')

        # --- BLOCCO 6: AZIONI ---
        with ui.row().classes('w-full justify-between mt-6'):
            with ui.row().classes('gap-4'):
                del_btn = ui.button('🗑️ Delete', color='red', on_click=lambda: self.delete(channel.id)).props('outline')
                del_btn.tooltip('Elimina l epoca canale corrente dal database rispettando i vincoli di integrità della stazione.')
                clone_btn = ui.button('👯 Clone Epoch', color='purple', on_click=lambda: self._clone()).props('outline')
                clone_btn.tooltip('Duplica l epoca del canale per creare una nuova finestra temporale StationXML mantenendo la catena strumentale di partenza.')
            save_btn = ui.button('💾 Save Channel', on_click=lambda: self.save(channel), color='green').classes('px-10 font-bold')
            save_btn.tooltip('Persiste le modifiche correnti sul database SQLite attivando i vincoli di integrità e aggiornando in modo atomico i canali fratelli.')

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
        self._start_date_raw_value = ""
        self._end_date_raw_value = ""
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
        channel.latitude = self.lat_in.value
        channel.longitude = self.lon_in.value
        channel.elevation = self.elev_in.value
        channel.depth = self.depth_in.value
        channel.sample_rate = self.sr_in.value
        channel.azimuth = self.azi_in.value
        channel.dip = self.dip_in.value
        try:
            channel.start_date = (
                self._normalize_datetime_text(self._start_date_raw_value)
                if self.start_set.value else None
            )
            channel.end_date = (
                self._normalize_datetime_text(self._end_date_raw_value)
                if self.end_set.value else None
            )
        except ValueError as e:
            ui.notify(f"Invalid epoch date: {e}", type='negative')
            return
        channel.sensor_id = self.sensor_cb.value
        channel.datalogger_id = self.logger_cb.value
        channel.overall_sensitivity = final_sens
        channel.sensor_serial_number = self.sensor_sn.value or None
        channel.datalogger_serial_number = self.logger_sn.value or None
        channel.types = self.types_in.value
        channel.restricted_status = self.restr_in.value
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
            result = self.cha_ctrl.save_channel_with_triad_sync(channel)
            saved_channel = result.get("channel") if isinstance(result, dict) else None
            if not saved_channel:
                ui.notify("Save failed: channel was not updated in the database.", type='negative')
                return
            synced_channels = result.get("synced_channels", []) if isinstance(result, dict) else []
            ui.notify(f"Channel {code} saved successfully!", type='positive')
            if synced_channels:
                ui.notify(
                    f"Data sincronizzata anche per i canali fratelli: {', '.join(synced_channels)}.",
                    type="info",
                )
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
