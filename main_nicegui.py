import os
import queue

from utils.open_files_limit import maximize_open_files_limit
from utils.logging_config import configure_application_logging
from core.database import init_database

maximize_open_files_limit()
configure_application_logging()
init_database()

import tempfile
import traceback
import time
import asyncio
from utils.geocoding_client import fetch_geography_from_coords
from utils.geology_client import fetch_geology_from_coords
import urllib.request
import json
from nicegui import app as nicegui_app
from nicegui import ui, run
import io
from utils.yasmine_client import YasmineClient

# --- 1. IMPORT MODULI E CONTROLLER ---
from web_api.main_web import app, net_dao, sta_dao, cha_dao, equ_dao, sta_svc, cha_svc

from controllers.network_controller import NetworkController
from controllers.station_controller import StationController
from controllers.channel_controller import ChannelController
from controllers.equipment_controller import EquipmentController

from web_gui.network_view import NetworkView
from web_gui.station_view import StationView
from web_gui.channel_view import ChannelView
from web_gui.catalog_dialog import CatalogDialog  # clone/replace/delete: web_gui/*_catalog_tab.py
from web_gui.math_deduplicator_dialog import MathDeduplicatorDialog
from web_gui.progress_utils import job_progress_fraction, job_progress_percent, yield_ui

# Import del Parser e dell'Exporter
from importer.stationxml_parser import StationXMLImportError, StationXMLParser
from exporter.stationxml_builder import StationXMLExporter
from controllers.stationxml_export_controller import StationXMLWebExportController


# --- 2. STATO WEB PER SESSIONE ---
class SessionAppState:
    """Proxy compatibile con i controller, backed by NiceGUI per-user storage."""

    def __init__(self, storage):
        self._storage = storage

    @property
    def current_network(self):
        return self._storage.get('current_network_id')

    @current_network.setter
    def current_network(self, value):
        self._storage['current_network_id'] = value
        self._storage['current_station_id'] = None
        self._storage['current_channel_id'] = None

    @property
    def current_station(self):
        return self._storage.get('current_station_id')

    @current_station.setter
    def current_station(self, value):
        self._storage['current_station_id'] = value
        self._storage['current_channel_id'] = None

    @property
    def current_channel(self):
        return self._storage.get('current_channel_id')

    @current_channel.setter
    def current_channel(self, value):
        self._storage['current_channel_id'] = value

    def mark_clean(self, *args, **kwargs):
        """Accetta qualsiasi argomento per evitare TypeError dai controller."""
        self._storage['dirty'] = False

    def mark_dirty(self, *args, **kwargs):
        """Accetta qualsiasi argomento per evitare TypeError dai controller."""
        self._storage['dirty'] = True


def _ensure_user_storage_defaults() -> None:
    user_storage = nicegui_app.storage.user
    user_storage.setdefault('current_network_id', None)
    user_storage.setdefault('current_station_id', None)
    user_storage.setdefault('current_channel_id', None)
    user_storage.setdefault('tree_expanded_ids', [])
    user_storage.setdefault('tree_selected_id', None)
    user_storage.setdefault('dirty', False)


@ui.page('/')
def index():
    _ensure_user_storage_defaults()
    user_storage = nicegui_app.storage.user
    app_state = SessionAppState(user_storage)

    # Controller per-sessione: nessun riferimento mutabile cross-utente.
    net_ctrl = NetworkController(net_dao, app_state)
    sta_ctrl = StationController(sta_dao, app_state)
    cha_ctrl = ChannelController(cha_dao, sta_dao, app_state)
    eq_ctrl = EquipmentController(equ_dao)

    sta_ctrl.set_channel_controller(cha_ctrl)
    sta_ctrl.set_equipment_controller(eq_ctrl)
    cha_ctrl.set_equipment_controller(eq_ctrl)

    export_web_ctrl = StationXMLWebExportController(net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl)
    node_lookup = {}

    # --- 3. LOGICA DI IMPORTAZIONE (FIX: Lettura byte e gestione errori) ---
    async def handle_import_upload(e):
        tmp_path = None
        try:
            # Recupero del contenuto (content o file)
            content = getattr(e, 'content', None) or getattr(e, 'file', None)
            if not content:
                ui.notify("Errore: File non leggibile", type='negative')
                return

            # Lettura asincrona obbligatoria per NiceGUI moderno
            file_bytes = await content.read() if hasattr(content, 'read') else content

            with tempfile.NamedTemporaryFile(delete=False, suffix='.xml') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            prog_col.set_visibility(True)
            prog_bar.value = 0.0
            prog_lbl.text = '0% — Preparing…'

            progress_q: queue.SimpleQueue = queue.SimpleQueue()
            loop = asyncio.get_running_loop()

            def run_import_sync() -> bool:
                parser = StationXMLParser(net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl)

                def progress_cb(current: int, total: int, message: str) -> None:
                    progress_q.put((current, total, message))

                return parser.import_file(tmp_path, progress_callback=progress_cb)

            fut = loop.run_in_executor(None, run_import_sync)

            def apply_progress(current: int, total: int, message: str) -> None:
                if total <= 0:
                    prog_bar.value = 0.0
                    prog_lbl.text = message
                else:
                    frac = min(1.0, max(0.0, current / total)) if total else 0.0
                    prog_bar.value = frac
                    pct = int(100 * current / total) if total else 0
                    prog_lbl.text = f'{pct}% — {message}'

            while True:
                drained = False
                while True:
                    try:
                        cur, tot, msg = progress_q.get_nowait()
                        drained = True
                        apply_progress(cur, tot, msg)
                    except queue.Empty:
                        break
                if fut.done():
                    while True:
                        try:
                            cur, tot, msg = progress_q.get_nowait()
                            apply_progress(cur, tot, msg)
                        except queue.Empty:
                            break
                    break
                if not drained:
                    await asyncio.sleep(0.04)

            exc = fut.exception()
            if exc is not None:
                raise exc
            ok = bool(fut.result())

            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
                tmp_path = None

            prog_col.set_visibility(False)

            if ok:
                ui.notify('Importazione completata con successo!', type='positive')
                build_tree()
                import_dialog.close()
            else:
                ui.notify('Importazione non completata (vedi log).', type='warning')

        except StationXMLImportError as ex:
            traceback.print_exc()
            ui.notify(f'Errore import StationXML: {ex}', type='negative', multi_line=True)
            prog_col.set_visibility(False)
        except Exception as ex:
            traceback.print_exc()
            ui.notify(f'Errore: {str(ex)}', type='negative')
            prog_col.set_visibility(False)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    with ui.dialog() as import_dialog, ui.card().classes('p-6 w-full max-w-lg'):
        ui.label('Import StationXML').classes('text-xl font-bold mb-4')
        prog_col = ui.column().classes('w-full gap-2')
        with prog_col:
            prog_bar = ui.linear_progress(value=0.0).classes('w-full')
            prog_lbl = ui.label('').classes('text-sm text-slate-600 break-words')
        prog_col.set_visibility(False)
        ui.upload(label='Trascina file XML qui', on_upload=handle_import_upload, auto_upload=True).classes('w-full')
        ui.button('Chiudi', on_click=import_dialog.close).props('flat').classes('mt-4')

    # --- 4. LOGICA DI ESPORTAZIONE (controller + formato) ---
    def show_export_panel():
        workspace.clear()
        with workspace:
            ui.label('Esportazione Stazioni').classes('text-2xl font-bold mb-4')
            ui.label(
                'Seleziona una o più stazioni. Una stazione genera un XML diretto; '
                'più stazioni generano uno ZIP con un XML per stazione.'
            ).classes('text-slate-600 mb-2')

            rows = []
            for net in net_ctrl.get_all_networks():
                for sta in sta_svc.get_stations_by_network(net.id):
                    rows.append({'id': sta.id, 'net': net.code, 'sta': sta.code})

            export_table = ui.table(
                columns=[
                    {'name': 'net', 'label': 'Network', 'field': 'net', 'align': 'left'},
                    {'name': 'sta', 'label': 'Station', 'field': 'sta', 'align': 'left'},
                ],
                rows=rows,
                selection='multiple',
                row_key='id',
            ).classes('w-full mb-4')

            export_prog_col = ui.column().classes('w-full gap-2 mb-4')
            with export_prog_col:
                export_prog_bar = ui.linear_progress(value=0.0).classes('w-full')
                export_prog_lbl = ui.label('').classes('text-sm text-slate-600 break-words')
            export_prog_col.set_visibility(False)

            async def handle_export_click():
                selected = export_table.selected
                if not selected:
                    ui.notify('Seleziona almeno una stazione!', type='warning')
                    return
                try:
                    export_prog_col.set_visibility(True)
                    export_prog_bar.value = 0.0
                    export_prog_lbl.text = '0% — Avvio export…'

                    progress_q: queue.SimpleQueue = queue.SimpleQueue()
                    loop = asyncio.get_running_loop()

                    def apply_export_progress(current: int, total: int, message: str) -> None:
                        if total <= 0:
                            export_prog_bar.value = 0.0
                            export_prog_lbl.text = message
                        else:
                            frac = min(1.0, max(0.0, current / total)) if total else 0.0
                            export_prog_bar.value = frac
                            pct = int(100 * current / total) if total else 0
                            export_prog_lbl.text = f'{pct}% — {message}'

                    async def pump_until_done(fut):
                        while True:
                            drained = False
                            while True:
                                try:
                                    cur, tot, msg = progress_q.get_nowait()
                                    drained = True
                                    apply_export_progress(cur, tot, msg)
                                except queue.Empty:
                                    break
                            if fut.done():
                                while True:
                                    try:
                                        cur, tot, msg = progress_q.get_nowait()
                                        apply_export_progress(cur, tot, msg)
                                    except queue.Empty:
                                        break
                                break
                            if not drained:
                                await asyncio.sleep(0.04)

                    def run_export_sync():
                        def progress_cb(current: int, total: int, message: str) -> None:
                            progress_q.put((current, total, message))

                        return export_web_ctrl.build_download(
                            selected,
                            progress_callback=progress_cb,
                            cancel_callback=None,
                        )

                    fut = loop.run_in_executor(None, run_export_sync)
                    await pump_until_done(fut)

                    exc = fut.exception()
                    if exc is not None:
                        raise exc
                    bundle = fut.result()

                    export_prog_col.set_visibility(False)

                    if bundle is None:
                        ui.notify('Export non completato.', type='warning')
                        return
                    data, fname = bundle
                    ui.download(data, filename=fname)
                    ui.notify('Download pronto!', type='positive')
                except Exception as ex:
                    traceback.print_exc()
                    ui.notify(f'Errore Export: {str(ex)}', type='negative')
                    export_prog_col.set_visibility(False)

            with ui.row().classes('w-full justify-end'):
                ui.button('SCARICA', on_click=handle_export_click).classes(
                    'bg-orange-600 text-white font-bold'
                )

    # --- LOGICA DI ARRICCHIMENTO (ENRICH NET) USANDO I TUOI CLIENT ---
    async def handle_enrich_net():
        stazioni = []
        for net in net_ctrl.get_all_networks():
            stazioni.extend(sta_svc.get_stations_by_network(net.id))

        if not stazioni:
            ui.notify('Nessuna stazione presente nel database!', type='warning')
            return

        with ui.dialog() as confirm_dialog, ui.card().classes('p-6'):
            ui.label('Conferma Enrich Network').classes('text-xl font-bold text-slate-800')
            ui.label(
                "Vuoi procedere con l'arricchimento dei dati della Rete? Questa operazione aggiornerà "
                'i metadati esistenti calcolando le informazioni mancanti.'
            ).classes('mt-2')

            with ui.row().classes('w-full justify-end mt-4 gap-2'):
                ui.button('Annulla', on_click=lambda: confirm_dialog.submit(False)).props('flat text-color=grey')
                ui.button('Conferma', on_click=lambda: confirm_dialog.submit(True)).classes(
                    'bg-blue-600 text-white font-bold'
                )

        if not await confirm_dialog:
            return

        await _run_enrich_net_after_confirm(stazioni)

    async def _run_enrich_net_after_confirm(stazioni):
        # Setup Dialog e Barra di Progresso
        with ui.dialog() as enrich_dialog, ui.card().classes('p-6 w-96'):
            ui.label('🌍 Arricchimento Geografico/Geologico').classes('text-xl font-bold mb-4')
            progress_bar = ui.linear_progress(value=0).classes('w-full')
            status_label = ui.label('Inizializzazione...').classes('text-sm text-slate-500 mt-2')

        enrich_dialog.open()

        error_flags = {"DATA_NOT_FOUND", "API_ERROR", "NETWORK_ERROR"}
        updated_count = 0
        totale = len(stazioni)
        progress_bar.set_value(job_progress_fraction(0, totale))
        status_label.set_text(f"Avvio — 0/{totale} ({job_progress_percent(0, totale):.2f}%)")
        await yield_ui()

        for i, sta in enumerate(stazioni):
            done = i + 1
            status_label.set_text(
                f"Stazione {sta.code} — completati {i}/{totale} ({job_progress_percent(i, totale):.2f}%) · geografia/geologia…"
            )
            await yield_ui()

            if sta.latitude is not None and sta.longitude is not None:
                start_time = time.time()
                changed = False

                geo_res = await run.io_bound(fetch_geology_from_coords, sta.latitude, sta.longitude)
                if geo_res and geo_res not in error_flags and sta.geology != geo_res:
                    sta.geology = geo_res
                    changed = True

                osm_res = await run.io_bound(fetch_geography_from_coords, sta.latitude, sta.longitude)
                if isinstance(osm_res, dict):
                    mapped_fields = {
                        "country": osm_res.get("country", ""),
                        "region": osm_res.get("region", ""),
                        "county": osm_res.get("county", ""),
                        "town": osm_res.get("town", ""),
                        "description": osm_res.get("description", ""),
                    }
                    for field_name, value in mapped_fields.items():
                        if getattr(sta, field_name, None) != value:
                            setattr(sta, field_name, value)
                            changed = True

                if changed:
                    sta_svc.save_station(sta)
                    updated_count += 1

                elapsed = time.time() - start_time
                wait_time = max(0, 2.0 - elapsed)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

            progress_bar.set_value(job_progress_fraction(done, totale))
            pct_done = job_progress_percent(done, totale)
            status_label.set_text(
                f"Completato: {sta.code} — {done}/{totale} ({pct_done:.2f}%)"
            )
            await yield_ui()

        progress_bar.set_value(1.0)
        status_label.set_text(f"Fine — {totale}/{totale} ({job_progress_percent(totale, totale):.2f}%)")
        await yield_ui()

        enrich_dialog.close()
        ui.notify(f'Arricchimento completato! Aggiornate {updated_count} stazioni.', type='positive')

        build_tree()
        workspace.clear()
    # --- LOGICA DI UPDATE NRL GLOBALE ---
    async def handle_update_nrl():
        with ui.dialog() as confirm_dialog, ui.card().classes('p-6'):
            ui.label('Conferma Update NRL').classes('text-xl font-bold text-slate-800')
            ui.label('Vuoi aggiornare tutti i sensori NRL? I dati matematici verranno ri-scaricati dalla libreria locale.').classes('mt-2')
            
            with ui.row().classes('w-full justify-end mt-4 gap-2'):
                ui.button('Annulla', on_click=lambda: confirm_dialog.submit(False)).props('flat text-color=grey')
                ui.button('Sì, Aggiorna', on_click=lambda: confirm_dialog.submit(True)).classes('bg-green-600 text-white font-bold')

        result = await confirm_dialog
        
        if result:
            with ui.dialog() as nrl_work_dialog, ui.card().classes("p-8 w-[min(440px,92vw)]"):
                ui.label("🔄 Aggiornamento catalogo NRL").classes("text-xl font-bold text-slate-800 mb-2")
                ui.label(
                    "Aggiornamento di sensori/datalogger con percorso NRL e canali collegati. "
                    "L’operazione può richiedere diversi minuti."
                ).classes("text-sm text-slate-600 mb-4")
                progress_bar = ui.linear_progress(value=0).classes("w-full")
                nrl_work_status = ui.label("Avvio…").classes("text-xs text-slate-500 mt-3")

            nrl_work_dialog.open()
            await yield_ui()
            count = 0
            prog_q: queue.SimpleQueue = queue.SimpleQueue()

            def _run_nrl_catalog_update():
                return sta_ctrl.update_all_nrl_sensors(progress_queue=prog_q)

            try:
                task = asyncio.create_task(run.io_bound(_run_nrl_catalog_update))
                progress_bar.set_value(job_progress_fraction(0, 1))
                nrl_work_status.set_text(f"0/1 ({job_progress_percent(0, 1):.2f}%) — inizializzazione…")
                await yield_ui()
                while not task.done():
                    try:
                        while True:
                            item = prog_q.get_nowait()
                            if item[0] == "p":
                                _, done, total, msg = item
                                progress_bar.set_value(job_progress_fraction(done, total))
                                pct = job_progress_percent(done, total)
                                nrl_work_status.set_text(f"{msg} — {pct:.2f}%")
                    except queue.Empty:
                        pass
                    await yield_ui()
                    await asyncio.sleep(0.02)
                count = await task
                try:
                    while True:
                        item = prog_q.get_nowait()
                        if item[0] == "p":
                            _, done, total, msg = item
                            progress_bar.set_value(job_progress_fraction(done, total))
                            pct = job_progress_percent(done, total)
                            nrl_work_status.set_text(f"{msg} — {pct:.2f}%")
                except queue.Empty:
                    pass
                progress_bar.set_value(1.0)
                nrl_work_status.set_text(f"Completato — 100.00%")
                await yield_ui()
                await asyncio.sleep(0.25)
                if count > 0:
                    ui.notify(
                        f"Aggiornamento completato: {count} stazioni modificate.",
                        type="positive",
                    )
                    build_tree()
                else:
                    ui.notify("Nessuna stazione aveva bisogno di aggiornamenti.", type="info")
            except Exception as e:
                traceback.print_exc()
                ui.notify(f"Errore durante l'aggiornamento NRL: {e}", type="negative")
            finally:
                nrl_work_dialog.close()
            
    async def handle_bulk_sync_yasmine():
        all_stations = []
        for net in net_ctrl.get_all_networks():
            all_stations.extend(sta_svc.get_stations_by_network(net.id))

        red_stations = []
        for sta in all_stations:
            status, icon, _ = sta_ctrl.get_sync_status(sta)
            if icon in ["🔴", "⚪"]:
                red_stations.append(sta)

        if not red_stations:
            ui.notify('Tutto sincronizzato! 🟢', type='positive')
            return

        with ui.dialog() as confirm_dialog, ui.card().classes('p-6'):
            ui.label('Conferma Sync Yasmine').classes('text-xl font-bold text-slate-800')
            ui.label(
                'Vuoi procedere con la sincronizzazione verso Yasmine? I metadati della rete verranno '
                'inviati al server remoto.'
            ).classes('mt-2')

            with ui.row().classes('w-full justify-end mt-4 gap-2'):
                ui.button('Annulla', on_click=lambda: confirm_dialog.submit(False)).props('flat text-color=grey')
                ui.button('Conferma', on_click=lambda: confirm_dialog.submit(True)).classes(
                    'bg-purple-600 text-white font-bold'
                )

        if not await confirm_dialog:
            return

        await _run_bulk_sync_yasmine_after_confirm(red_stations)

    async def _run_bulk_sync_yasmine_after_confirm(red_stations):
        from utils.yasmine_client import YasmineClient

        client = YasmineClient()
        exporter = StationXMLExporter(net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl)

        with ui.dialog() as sync_dialog, ui.card().classes('p-6 w-96'):
            ui.label('🚀 Yasmine Bulk Sync').classes('text-xl font-bold mb-2')
            progress_bar = ui.linear_progress(value=0).classes('w-full')
            status_label = ui.label('Connessione a Yasmine...').classes('text-xs mt-2')
        sync_dialog.open()

        try:
            status_label.set_text("Connessione a Yasmine…")
            await yield_ui()
            remote_list = await run.io_bound(client.get_all_imported_xmls)
            success_count = 0
            totale = len(red_stations)
            progress_bar.set_value(job_progress_fraction(0, totale))
            status_label.set_text(f"Pronto — 0/{totale} ({job_progress_percent(0, totale):.2f}%)")
            await yield_ui()

            for i, station in enumerate(red_stations):
                done = i + 1
                pct = job_progress_percent(done - 1, totale)
                status_label.set_text(
                    f"{station.code}: controllo duplicati — {done - 1}/{totale} ({pct:.2f}%)"
                )
                await yield_ui()

                existing_item = next(
                    (
                        item
                        for item in remote_list
                        if isinstance(item, dict) and item.get("name") == station.code
                    ),
                    None,
                )

                if existing_item:
                    status_label.set_text(
                        f"{station.code}: rimozione versione precedente — "
                        f"{job_progress_percent(done - 1, totale):.2f}%"
                    )
                    await yield_ui()
                    old_id = existing_item.get("id")
                    await run.io_bound(client.delete_xml, old_id)

                status_label.set_text(
                    f"{station.code}: generazione XML — {job_progress_percent(done - 1, totale):.2f}%"
                )
                await yield_ui()
                inv = await run.io_bound(exporter.build_inventory, target_station_id=station.id)
                out_stream = io.BytesIO()
                inv.write(out_stream, format="STATIONXML", validate=True)
                xml_bytes = out_stream.getvalue()

                status_label.set_text(
                    f"{station.code}: invio a Yasmine — {job_progress_percent(done - 1, totale):.2f}%"
                )
                await yield_ui()
                new_id = await run.io_bound(client.upload_xml, xml_bytes, station.code)

                if new_id:
                    await run.io_bound(sta_ctrl.mark_as_synced, station, new_id)
                    success_count += 1

                progress_bar.set_value(job_progress_fraction(done, totale))
                pct_done = job_progress_percent(done, totale)
                status_label.set_text(
                    f"Completato: {station.code} — {done}/{totale} ({pct_done:.2f}%)"
                )
                await yield_ui()

            progress_bar.set_value(1.0)
            status_label.set_text(
                f"Fine — {totale}/{totale} ({job_progress_percent(totale, totale):.2f}%)"
            )
            await yield_ui()

            sync_dialog.close()
            ui.notify(f'Sincronizzazione completata: {success_count} stazioni.', type='positive')
            build_tree()

        except Exception as e:
            sync_dialog.close()
            traceback.print_exc()
            ui.notify(f'Errore critico durante il sync: {str(e)}', type='negative')

    async def handle_recalculate_all_sensitivities():
        try:
            updated = await run.io_bound(cha_ctrl.recalculate_all_sensitivities)
            ui.notify(f"Sensitività ricalcolate per {updated} canali.", type="positive")
            build_tree()
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore ricalcolo sensibilità: {e}", type="negative")

    # --- 5. HEADER ---
    with ui.header().classes('bg-slate-800 text-white shadow-lg flex-col p-0'):
        with ui.row().classes('w-full p-4 items-center'):
            ui.label('🌍 StationXML Web Manager').classes('text-2xl font-bold')
        with ui.row().classes('w-full bg-slate-700 p-2 gap-2 items-center flex-wrap'):
            ui.button('⚙️ Catalog', on_click=lambda: CatalogDialog(eq_ctrl, on_catalog_closed=build_tree).open()).props('outline color=white size=sm')
            ui.button('📥 Import', on_click=import_dialog.open).props('flat color=white size=sm')
            ui.button('💾 Export', on_click=show_export_panel).props('flat color=white size=sm')
            ui.space()
            ui.button('🌍 Enrich Net', on_click=handle_enrich_net).props('flat color=blue-3 size=sm')
            ui.button('🔄 Update NRL', on_click=handle_update_nrl).props('flat color=green-3 size=sm')
            ui.button('🚀 Sync Yasmine', on_click=handle_bulk_sync_yasmine).props('flat color=purple-3 size=sm')
            ui.button('🧮 Recalc Sens', on_click=handle_recalculate_all_sensitivities).props('flat color=cyan-3 size=sm')
            ui.button('🔍 Find Duplicates', on_click=lambda: MathDeduplicatorDialog(eq_ctrl, build_tree).open()).props('flat color=orange-3 size=sm')

    # --- 6. SPLITTER ---
    with ui.splitter(value=25).classes('w-full h-[calc(100vh-115px)] no-wrap') as main_splitter:
        with main_splitter.before:
            with ui.column().classes('w-full h-full bg-slate-50 border-r m-0 p-0'):
                with ui.row().classes('w-full p-4 items-center justify-between border-b bg-slate-100'):
                    ui.label('Hierarchy').classes('text-sm font-bold text-slate-500 uppercase')
                    ui.button(icon='refresh', on_click=lambda: build_tree()).props('flat round size=sm')
                with ui.row().classes('w-full px-2 pt-2 gap-1'):
                    ui.button('+ Net', on_click=lambda: prepare_new('network')).props('outline size=sm').classes('flex-grow')
                    ui.button('+ Sta', on_click=lambda: prepare_new('station')).props('outline size=sm').classes('flex-grow')
                    ui.button('+ Cha', on_click=lambda: prepare_new('channel')).props('outline size=sm').classes('flex-grow')
                tree_search = ui.input(
                    placeholder='Filtra stazione...',
                    on_change=lambda _: build_tree(),
                ).props('dense clearable').classes('w-full px-2 pt-2')
                tree_container = ui.column().classes('w-full p-2 overflow-y-auto')
        with main_splitter.after:
            workspace = ui.column().classes('w-full h-full p-8 bg-white overflow-y-auto')

    # Viste modulari
    net_view = NetworkView(net_ctrl, eq_ctrl, lambda: build_tree())
    sta_view = StationView(sta_ctrl, eq_ctrl, net_ctrl, cha_ctrl, lambda: build_tree())
    cha_view = ChannelView(cha_ctrl, eq_ctrl, lambda: build_tree(), sta_ctrl)

    # --- 7. LOGICA ALBERO ---
    def prepare_new(entity_type):
        workspace.clear()
        with workspace:
            if entity_type == 'network':
                from core.models.base_models import Network
                net_view.build_ui(Network(code=""))
            elif entity_type == 'station':
                if not app_state.current_network:
                    ui.notify("Seleziona prima una Rete!", type='warning')
                    return
                from core.models.base_models import Station
                new_sta = Station(network_id=app_state.current_network, code="")
                sta_view.build_ui(new_sta)
            elif entity_type == 'channel':
                if not app_state.current_station:
                    ui.notify("Seleziona prima una Stazione!", type='warning')
                    return
                from core.models.base_models import Channel
                new_cha = Channel(station_id=app_state.current_station, code="")
                cha_view.build_ui(new_cha)

    def handle_selection(event):
        if not event.value: return
        user_storage['tree_selected_id'] = event.value
        node = node_lookup.get(event.value)
        if not node:
            return
        if node['type'] == 'network': app_state.current_network = node['data'].id
        elif node['type'] == 'station':
            app_state.current_network = node['data'].network_id
            app_state.current_station = node['data'].id
        elif node['type'] == 'channel':
            if node.get('network_id') is not None:
                app_state.current_network = node['network_id']
            app_state.current_station = node['data'].station_id
            app_state.current_channel = node['data'].id
        workspace.clear()
        with workspace:
            if node['type'] == 'network': net_view.build_ui(node['data'])
            elif node['type'] == 'station': sta_view.build_ui(node['data'])
            elif node['type'] == 'channel': cha_view.build_ui(node['data'])

    def build_tree():
        tree_container.clear()
        node_lookup.clear()
        filter_text = ((tree_search.value if 'tree_search' in locals() else '') or '').strip().lower()
        tree_data = []
        for net in net_ctrl.get_all_networks():
            net_id = f'n_{net.id}'
            net_node = {'id': net_id, 'label': f'📁 {net.code}', 'children': []}
            node_lookup[net_id] = {'type': 'network', 'data': net}
            
            for sta in sta_svc.get_stations_by_network(net.id):
                sta_id = f's_{sta.id}'
                
                # --- QUI È IL FIX MAGICO ---
                # Richiama il tuo controller per leggere il database "sync_state" separato
                # get_sync_status() restituisce tre valori: sync_state_object, ICONA ("🟢" o "🔴"), yasmine_id
                _, icon, _ = sta_ctrl.get_sync_status(sta)
                station_label_text = f'{sta.code} {sta.site_name or ""}'.lower()
                if filter_text and filter_text not in station_label_text:
                    continue
                
                sta_node = {'id': sta_id, 'label': f'{icon} {sta.code}', 'children': []}
                node_lookup[sta_id] = {'type': 'station', 'data': sta}
                
                for cha in cha_svc.get_channels_by_station(sta.id):
                    cha_id = f'c_{cha.id}'
                    node_lookup[cha_id] = {
                        'type': 'channel',
                        'data': cha,
                        'network_id': net.id,
                    }
                    loc = cha.location_code if cha.location_code else "--"
                    sta_node['children'].append({'id': cha_id, 'label': f'〰️ {cha.code} ({loc})'})
                net_node['children'].append(sta_node)
            if net_node['children'] or not filter_text:
                tree_data.append(net_node)
            
        with tree_container:
            tree = ui.tree(tree_data, label_key='label', on_select=handle_selection).props('dense')
            tree_expanded_ids = set(user_storage.get('tree_expanded_ids') or [])
            if filter_text:
                tree.expand()
            elif tree_expanded_ids:
                tree._props['expanded'] = list(tree_expanded_ids)
            else:
                tree.expand()
            if user_storage.get('tree_selected_id'):
                tree._props['selected'] = user_storage['tree_selected_id']

            def _remember_expanded(e):
                args = getattr(e, 'args', None)
                if isinstance(args, list):
                    user_storage['tree_expanded_ids'] = list(args)

            tree.on('update:expanded', _remember_expanded)

    build_tree()

# --- 8. AVVIO ---
ui.run_with(
    app,
    title="StationXML Manager",
    mount_path='/',
    storage_secret=os.environ.get(
        'NICEGUI_STORAGE_SECRET',
        'stationxml-manager-v1-web-session-storage-secret-2026',
    ),
)
