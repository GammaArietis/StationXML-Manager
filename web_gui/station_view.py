import io
import json
import traceback
from datetime import datetime
from typing import Callable, Optional

from nicegui import ui, run

from core.models.base_models import Station
from web_gui.date_form_helpers import datetime_local_to_db, iso_to_datetime_local_field
from exporter.stationxml_builder import StationXMLExporter
from utils.geocoding_client import fetch_geography_from_coords
from utils.geology_client import fetch_geology_from_coords
from utils.yasmine_client import YasmineClient
from utils.fdsn_seed_codes import (
    get_fdsn_band_code,
    get_instrument_code,
    is_broadband_from_poles,
)


class StationView:
    def __init__(self, sta_ctrl, eq_ctrl, net_ctrl, cha_ctrl, on_save: Callable[[], None]):
        self.sta_ctrl = sta_ctrl
        self.eq_ctrl = eq_ctrl
        self.net_ctrl = net_ctrl
        self.cha_ctrl = cha_ctrl
        self.on_save = on_save

    def build_ui(self, station: Station):
        ui.label(f"📡 Station: {station.code}").classes("text-3xl font-bold text-slate-800 mb-6")

        # --- BLOCCO 1: METADATI GENERALI ---
        with ui.card().classes("w-full p-6 mb-4 shadow-sm border-t-4 border-blue-600"):
            ui.label("General Metadata").classes("text-lg font-bold mb-4 text-blue-800")
            with ui.row().classes("w-full gap-4"):
                self.code_in = ui.input("Station Code (*)", value=station.code).classes("w-1/4").props("uppercase maxlength=10")
                self.site_in = ui.input("Site Name", value=station.site_name or "").classes("flex-grow")
                self.restr_in = ui.select(
                    ["open", "closed", "partial"],
                    label="Restricted",
                    value=station.restricted_status or "open",
                ).classes("w-32")

            with ui.row().classes("w-full gap-4 mt-4 items-center"):
                operators = {None: "--- No Operator ---"}
                for op in self.eq_ctrl.get_all_operators():
                    operators[op.id] = f"{op.agency} ({op.contact_name})" if op.contact_name else op.agency
                self.op_in = ui.select(operators, label="Operator", value=station.operator_id).classes("w-1/3")

                self.vault_in = ui.select(
                    ["Vault", "Borehole", "Surface", "Cave", "Underwater", "Tunnel", "Building", "Bunker"],
                    label="Vault",
                    value=station.vault or "Vault",
                    with_input=True,
                ).classes("w-1/3")

        # --- BLOCCO 2: COORDINATE E GEOLOGIA ---
        with ui.card().classes("w-full p-6 mb-4 shadow-sm"):
            ui.label("Coordinates & Geology").classes("text-lg font-bold mb-4 text-slate-700")
            with ui.row().classes("w-full gap-4 items-center"):
                self.lat_in = ui.number("Latitude", value=station.latitude or 0.0, format="%.5f", step=0.00001).classes("w-1/6")
                self.lon_in = ui.number("Longitude", value=station.longitude or 0.0, format="%.5f", step=0.00001).classes("w-1/6")
                self.elev_in = ui.number("Elevation (m)", value=station.elevation or 0.0).classes("w-1/6")
                self.water_in = ui.number("Water Level", value=getattr(station, "water_level", 0.0) or 0.0).classes("w-1/6")

            with ui.row().classes("w-full gap-4 mt-4 items-center"):
                self.geol_in = ui.input("Geology", value=station.geology or "").classes("flex-grow")

        # --- BLOCCO 3: INDIRIZZO E LUOGO ---
        with ui.card().classes("w-full p-6 mb-4 shadow-sm"):
            ui.label("Address & Location").classes("text-lg font-bold mb-4 text-slate-700")
            self.desc_in = ui.input("Extended Site Description", value=getattr(station, "description", "") or "").classes("w-full mb-4")
            with ui.row().classes("w-full gap-4"):
                self.town_in = ui.input("Town", value=getattr(station, "town", "") or "").classes("w-1/5")
                self.county_in = ui.input("County", value=getattr(station, "county", "") or "").classes("w-1/5")
                self.region_in = ui.input("Region", value=getattr(station, "region", "") or "").classes("w-1/5")
                self.country_in = ui.input("Country", value=getattr(station, "country", "") or "").classes("w-1/5")

        # --- BLOCCO 4: DATE ---
        with ui.card().classes("w-full p-6 mb-4 shadow-sm"):
            ui.label("Operating Dates").classes("text-lg font-bold mb-4 text-slate-700")
            with ui.column().classes("w-full gap-4"):
                with ui.row().classes("w-full gap-4 items-end"):
                    self.start_set = ui.checkbox(
                        "Set start date",
                        value=bool(station.start_date and str(station.start_date).strip()),
                    ).classes("shrink-0")
                    self.start_in = ui.input(
                        "Start Date",
                        value=iso_to_datetime_local_field(station.start_date),
                    ).props("type=datetime-local").classes("w-1/3")
                    self.start_in.bind_enabled_from(self.start_set, "value")
                with ui.row().classes("w-full gap-4 items-end"):
                    self.end_set = ui.checkbox(
                        "Set end date",
                        value=bool(station.end_date and str(station.end_date).strip()),
                    ).classes("shrink-0")
                    self.end_in = ui.input(
                        "End Date",
                        value=iso_to_datetime_local_field(station.end_date),
                    ).props("type=datetime-local").classes("w-1/3")
                    self.end_in.bind_enabled_from(self.end_set, "value")

        # --- BLOCCO 5: COMMENTI FDSN ---
        with ui.card().classes("w-full p-6 mb-4 shadow-sm"):
            ui.label("Station Comments (FDSN)").classes("text-lg font-bold mb-4 text-slate-700")
            self.comments_container = ui.column().classes("w-full gap-2")
            self.comments_ui_elements = []

            try:
                loaded_comments = json.loads(station.comments) if station.comments else []
            except Exception:
                loaded_comments = []

            def add_comment_row(c_val="", c_start="", c_end="", c_sub="", c_auth=""):
                with self.comments_container:
                    with ui.row().classes("w-full gap-2 items-center bg-slate-50 p-2 rounded border") as row:
                        v = ui.input("Text", value=c_val).classes("flex-grow")
                        st = ui.input("Start", value=c_start).classes("w-32").props("placeholder=YYYY-MM-DD")
                        en = ui.input("End", value=c_end).classes("w-32").props("placeholder=YYYY-MM-DD")
                        sub = ui.input("Subject", value=c_sub).classes("w-32")
                        auth = ui.input("Author", value=c_auth).classes("w-48")
                        btn_remove = ui.button(icon="delete", color="red").props("flat dense")
                        item_tuple = (v, st, en, sub, auth)
                        self.comments_ui_elements.append(item_tuple)
                        btn_remove.on("click", lambda r=row, it=item_tuple: remove_comment_row(r, it))

            def remove_comment_row(row_element, item_tuple):
                row_element.delete()
                if item_tuple in self.comments_ui_elements:
                    self.comments_ui_elements.remove(item_tuple)

            for c in loaded_comments:
                auth_str = c.get("author_name", "")
                if c.get("author_agency"):
                    auth_str += f" ({c.get('author_agency')})"
                add_comment_row(
                    c.get("value", ""),
                    c.get("begin_date", ""),
                    c.get("end_date", ""),
                    c.get("subject", ""),
                    auth_str,
                )

            ui.button("+ Add Comment", on_click=lambda: add_comment_row(), color="blue").classes("mt-4").props("outline")

        # --- Lookup da coordinate (definiti dopo tutti i campi usati in UI) ---
        async def _run_geology():
            lat = float(self.lat_in.value or 0.0)
            lon = float(self.lon_in.value or 0.0)
            if lat == 0.0 and lon == 0.0:
                ui.notify("Imposta latitudine e longitudine valide (non 0,0).", type="warning")
                return
            try:
                res: Optional[str] = await run.io_bound(fetch_geology_from_coords, lat, lon)
            except Exception as e:
                traceback.print_exc()
                ui.notify(f"Errore geologia: {e}", type="negative")
                return
            if not res or res in ("DATA_NOT_FOUND", "API_ERROR", "NETWORK_ERROR"):
                ui.notify(f"Geologia non disponibile ({res or 'vuoto'}).", type="warning")
                return
            self.geol_in.value = res
            ui.notify("Campo Geology aggiornato da Macrostrat.", type="positive")

        async def _run_geography():
            lat = float(self.lat_in.value or 0.0)
            lon = float(self.lon_in.value or 0.0)
            if lat == 0.0 and lon == 0.0:
                ui.notify("Imposta latitudine e longitudine valide (non 0,0).", type="warning")
                return
            try:
                res = await run.io_bound(fetch_geography_from_coords, lat, lon)
            except Exception as e:
                traceback.print_exc()
                ui.notify(f"Errore geografia: {e}", type="negative")
                return
            if not isinstance(res, dict):
                ui.notify(f"Geografia non disponibile ({res}).", type="warning")
                return
            self.town_in.value = res.get("town", "") or ""
            self.county_in.value = res.get("county", "") or ""
            self.region_in.value = res.get("region", "") or ""
            self.country_in.value = res.get("country", "") or ""
            desc = res.get("description", "") or ""
            if desc:
                self.desc_in.value = desc
            ui.notify("Indirizzo / luogo aggiornati da OpenStreetMap.", type="positive")

        async def _run_yasmine_sync():
            if not station.id:
                ui.notify("Salva la stazione nel database prima di inviarla a Yasmine.", type="warning")
                return
            net = self.net_ctrl.get_network_by_id(station.network_id)
            if not net:
                ui.notify("Network non trovato per questa stazione.", type="negative")
                return

            ui.notify("Connessione a Yasmine…", type="info")

            def _sync_job():
                db_sta = self.sta_ctrl.get_station_by_id(station.id)
                if not db_sta:
                    raise RuntimeError("Stazione non trovata nel DB.")
                client = YasmineClient()
                exporter = StationXMLExporter(self.net_ctrl, self.sta_ctrl, self.cha_ctrl, self.eq_ctrl)
                inv = exporter.build_inventory(target_station_id=db_sta.id)
                buf = io.BytesIO()
                inv.write(buf, format="STATIONXML", validate=True)
                xml_bytes = buf.getvalue()
                remote = client.get_all_files(force_refresh=True)
                if not client.delete_remote_for_station(
                    db_sta.code, remote, network_code=net.code
                ):
                    raise RuntimeError("Impossibile rimuovere il file esistente su Yasmine.")
                new_id = client.upload_xml(xml_bytes, db_sta.code)
                if not new_id:
                    raise RuntimeError("Upload Yasmine fallito (nessun ID restituito).")
                self.sta_ctrl.mark_as_synced(db_sta, str(new_id))
                return str(new_id), f"{db_sta.code}.xml"

            try:
                yid, fname = await run.io_bound(_sync_job)
                ui.notify(f"Caricato su Yasmine: {fname} (id={yid}).", type="positive", timeout=5000)
                self.on_save()
            except Exception as e:
                traceback.print_exc()
                ui.notify(f"Errore Yasmine: {e}", type="negative", multi_line=True)

        def _open_auto_channels_dialog():
            if not station.id:
                ui.notify("Salva la stazione prima di generare i canali.", type="warning")
                return

            dl_options = {
                d.id: f"{d.manufacturer} {d.model}"
                for d in self.eq_ctrl.get_all_dataloggers()
                if d.id is not None
            }
            sensor_options = {
                s.id: f"{s.manufacturer} {s.model}"
                for s in self.eq_ctrl.get_all_sensors()
                if s.id is not None
            }
            if not dl_options or not sensor_options:
                ui.notify("Servono almeno un datalogger e un sensore nel catalogo.", type="warning")
                return

            with ui.dialog() as dialog, ui.card().classes("p-6 w-[min(520px,92vw)]"):
                ui.label("⚡ Auto-Generate 3 Channels").classes("text-xl font-bold mb-4")
                sample_rate_display = ui.input("Detected Sample Rate", value="N/A").props("readonly").classes("w-full mt-2")

                def _update_sample_rate_preview(_=None):
                    if not dl_sel.value:
                        sample_rate_display.value = "N/A"
                    else:
                        sample_rate = self.cha_ctrl.get_datalogger_sample_rate(int(dl_sel.value))
                        is_bb = sensor_type.value == "bb"
                        proposed_band = get_fdsn_band_code(
                            sample_rate,
                            is_bb,
                            instrument_code=inst_in.value,
                        )
                        band_sel.value = proposed_band
                        band_sel.update()
                        sample_rate_display.value = f"{sample_rate:.6g} Hz"
                    sample_rate_display.update()

                dl_sel = ui.select(
                    dl_options,
                    label="Datalogger",
                    with_input=True,
                    on_change=_update_sample_rate_preview,
                ).classes("w-full")

                sensor_sel = ui.select(
                    sensor_options,
                    label="Sensor",
                    with_input=True,
                    on_change=lambda e: _sync_sensor_fdsn_defaults(e),
                ).classes("w-full mt-2")
                depth_in = ui.number("Depth", value=0.0).classes("w-full mt-2")
                start_time_in = ui.input(
                    "Start Time",
                    value=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                ).props("type=datetime-local").classes("w-full mt-2")
                band_sel = ui.select(
                    ["F", "C", "H", "B", "M", "L", "V", "U", "R", "E", "S", "G"],
                    label="Band Code (1st Letter)",
                    value="H",
                ).classes("w-full mt-2")
                inst_in = ui.input(
                    "Instrument Code",
                    value="H",
                    on_change=_update_sample_rate_preview,
                ).props("maxlength=1").classes("w-full mt-2")
                sensor_type = ui.select(
                    {"bb": "Broad Band (BB)", "sp": "Short Period (SP)"},
                    label="Sensor Type",
                    value="bb",
                    on_change=_update_sample_rate_preview,
                ).classes("w-full mt-2")

                def _sync_sensor_fdsn_defaults(_=None):
                    if not sensor_sel.value:
                        return
                    sensor = self.eq_ctrl.get_sensor(int(sensor_sel.value))
                    if not sensor:
                        return
                    inst_in.value = get_instrument_code(getattr(sensor, "input_units", ""))
                    inst_in.update()
                    is_bb = is_broadband_from_poles(
                        getattr(sensor, "poles", []),
                        pz_transfer_function_type=getattr(
                            sensor,
                            "pz_transfer_function_type",
                            "LAPLACE (RADIANS/SECOND)",
                        ),
                    )
                    sensor_type.value = "bb" if is_bb else "sp"
                    sensor_type.update()
                    _update_sample_rate_preview()
                _sync_sensor_fdsn_defaults()
                _update_sample_rate_preview()

                def _generate():
                    if not dl_sel.value or not sensor_sel.value:
                        ui.notify("Seleziona datalogger e sensore.", type="warning")
                        return
                    try:
                        created = self.cha_ctrl.auto_generate_triaxial_channels(
                            station.id,
                            int(dl_sel.value),
                            int(sensor_sel.value),
                            float(depth_in.value or 0.0),
                            (inst_in.value or "H").strip(),
                            sensor_type.value == "bb",
                            datetime_local_to_db(True, start_time_in.value),
                            band_code=band_sel.value,
                        )
                        dialog.close()
                        ui.notify(f"Creati {len(created)} canali.", type="positive")
                        self.on_save()
                    except Exception as e:
                        traceback.print_exc()
                        ui.notify(f"Errore generazione canali: {e}", type="negative")

                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("Annulla", on_click=dialog.close).props("flat")
                    ui.button("Genera", color="teal", on_click=_generate).classes("font-bold")

            dialog.open()

        async def _confirm_delete():
            await self.delete(station.id)

        with ui.row().classes("w-full gap-2 items-center mt-2 mb-2"):
            ui.label("Geologia / geografia da coordinate:").classes("text-sm text-slate-600")
            ui.button("🌍 Get Geology", on_click=_run_geology).props("outline color=info")
            ui.button("📍 Auto-fill Geog.", on_click=_run_geography).props("outline color=warning")

        # --- BLOCCO 6: AZIONI ---
        with ui.row().classes("w-full justify-between mt-8"):
            with ui.row().classes("gap-4"):
                ui.button("🗑️ Delete Station", color="red", on_click=_confirm_delete).props("outline")
                ui.button("☁️ Send to Yasmine", color="deep-purple", on_click=_run_yasmine_sync).props("outline")
                ui.button("⚡ Auto-Generate 3 Channels", color="teal", on_click=_open_auto_channels_dialog).props("outline")
            ui.button("💾 Save Station", on_click=lambda: self.save(station), color="green").classes("px-10 font-bold h-12")

    def save(self, station):
        code = self.code_in.value.strip().upper() if self.code_in.value else ""
        if not code:
            ui.notify("Station Code is required!", type="negative")
            return

        station.code = code
        station.site_name = self.site_in.value
        station.restricted_status = self.restr_in.value
        station.operator_id = self.op_in.value
        station.vault = self.vault_in.value

        station.latitude = self.lat_in.value
        station.longitude = self.lon_in.value
        station.elevation = self.elev_in.value
        station.geology = self.geol_in.value

        if hasattr(station, "water_level"):
            station.water_level = self.water_in.value
        if hasattr(station, "description"):
            station.description = self.desc_in.value

        station.town = self.town_in.value
        station.county = self.county_in.value
        station.region = self.region_in.value
        station.country = self.country_in.value

        station.start_date = datetime_local_to_db(bool(self.start_set.value), self.start_in.value)
        station.end_date = datetime_local_to_db(bool(self.end_set.value), self.end_in.value)

        c_list = []
        for v, st, en, sub, auth in self.comments_ui_elements:
            val_text = v.value.strip() if v.value else ""
            if not val_text:
                continue

            auth_text = auth.value.strip() if auth.value else ""
            author_name = auth_text
            author_agency = ""
            if "(" in auth_text and ")" in auth_text:
                parts = auth_text.split("(")
                author_name = parts[0].strip()
                author_agency = parts[1].replace(")", "").strip()

            c_list.append(
                {
                    "value": val_text,
                    "begin_date": st.value.strip() if st.value else "",
                    "end_date": en.value.strip() if en.value else "",
                    "subject": sub.value.strip() if sub.value else "",
                    "author_name": author_name,
                    "author_agency": author_agency,
                }
            )

        station.comments = json.dumps(c_list) if c_list else None

        try:
            self.sta_ctrl.save_station(station)
            ui.notify(f"Station {code} saved successfully!", type="positive")
            self.on_save()
        except Exception as e:
            ui.notify(f"Error saving station: {e}", type="negative")

    async def delete(self, sta_id):
        with ui.dialog() as dialog, ui.card():
            ui.label(
                "Eliminare questa stazione? Tutti i canali associati verranno rimossi."
            ).classes("text-lg font-bold text-slate-800")
            with ui.row().classes("w-full justify-end mt-4 gap-2"):
                ui.button("Annulla", on_click=lambda: dialog.submit(False)).props("flat text-color=grey")
                ui.button("Elimina", on_click=lambda: dialog.submit(True)).classes("bg-red-600 text-white font-bold")

        result = await dialog

        if result:
            try:
                self.sta_ctrl.delete_station(sta_id)
                ui.notify("Stazione eliminata.", type="info")
                self.on_save()
            except Exception as e:
                ui.notify(f"Errore durante l'eliminazione: {e}", type="negative")
