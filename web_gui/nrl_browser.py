from nicegui import ui, run
import traceback
import json
import os
import re


class NRLBrowser:
    def __init__(self, nrl_manager, equip_type="datalogger"):
        self.manager = nrl_manager
        self.equip_type = equip_type
        self.path = []

    async def open(self, callback, search_query=""):
        self.path = []
        with ui.dialog() as dialog, ui.card().classes("w-[600px] h-[700px] flex flex-col no-wrap"):
            title = ui.label(f"NRL Library - {self.equip_type.upper()}").classes("text-xl font-bold shrink-0")
            title.tooltip("Navigazione del catalogo ufficiale delle risposte strumentali Nominal Response Library. Consente l importazione diretta di poli, zeri e stadi di decimazione standard.")

            suggestion_container = ui.column().classes("w-full shrink-0")

            path_lbl = ui.label("Path: Home").classes("text-xs font-mono text-blue-600 mb-2 shrink-0")
            container = ui.column().classes("flex-grow w-full border rounded overflow-y-auto gap-0 bg-slate-50")

            def _options_func():
                return (
                    self.manager.get_sensor_options
                    if self.equip_type == "sensor"
                    else self.manager.get_datalogger_options
                )

            def _fetch_func():
                return (
                    self.manager.fetch_sensor
                    if self.equip_type == "sensor"
                    else self.manager.fetch_datalogger
                )

            async def download():
                ui.notify("Scaricamento in corso...", icon="cloud_download")
                try:
                    func = _fetch_func()
                    try:
                        result = await run.io_bound(func, self.path)
                    except TypeError:
                        result = await run.io_bound(func, *self.path)

                    if result:
                        callback(result)
                        dialog.close()
                    else:
                        ui.notify("Nessun dato restituito da NRL", type="warning")
                except Exception as e:
                    traceback.print_exc()
                    ui.notify(f"Errore download: {e}", type="negative")

            async def _siblings_after_current():
                """Lista livello padre; serve per il pulsante Avanti (stesso livello)."""
                if not self.path:
                    return None, None
                parent = tuple(self.path[:-1])
                cur = self.path[-1]
                func = _options_func()
                sib = await run.io_bound(func, *parent)
                if not sib:
                    return cur, []
                if not isinstance(sib, list):
                    return cur, []
                return cur, sib

            async def refresh():
                container.clear()
                path_lbl.set_text(f"Path: {' -> '.join(self.path) if self.path else 'Home'}")
                try:
                    func = _options_func()
                    opts = await run.io_bound(func, *self.path)
                    with container:
                        if not opts:
                            ui.icon("check_circle", color="green").classes("text-6xl m-auto mt-10")
                            import_btn = ui.button("⬇ IMPORTA MODELLO", on_click=download).classes(
                                "w-3/4 m-auto mt-4 h-12 shadow-lg"
                            )
                            import_btn.tooltip("Importa il modello NRL selezionato convertendo risposta, poli/zeri, gain e stadi digitali nel catalogo locale.")
                        else:
                            for opt in opts:

                                def make_row_handler(o):
                                    async def row_click(_=None):
                                        if not o:
                                            return
                                        self.path = [*self.path, o]
                                        await refresh()

                                    return row_click

                                with ui.row().classes(
                                    "w-full p-3 border-b hover:bg-blue-100 cursor-pointer bg-white"
                                ).on("click", make_row_handler(opt)):
                                    ui.icon("folder", color="blue-400")
                                    ui.label(opt).classes("flex-grow font-medium")
                except Exception as e:
                    with container:
                        ui.label(f"Errore: {e}").classes("text-red-500 p-4")

                if len(self.path) > 0:
                    btn_back.enable()
                else:
                    btn_back.disable()

                cur, sib = await _siblings_after_current()
                can_forward = False
                if cur is not None and sib and cur in sib:
                    i = sib.index(cur)
                    can_forward = (i + 1) < len(sib)
                if can_forward:
                    btn_forward.enable()
                else:
                    btn_forward.disable()

            async def go_parent():
                if not self.path:
                    return
                self.path = self.path[:-1]
                await refresh()

            async def go_forward_sibling():
                if not self.path:
                    return
                parent = self.path[:-1]
                cur = self.path[-1]
                func = _options_func()
                sib = await run.io_bound(func, *parent)
                if not sib or not isinstance(sib, list):
                    return
                try:
                    i = sib.index(cur)
                except ValueError:
                    return
                if i + 1 >= len(sib):
                    return
                self.path = [*parent, sib[i + 1]]
                await refresh()

            with ui.row().classes("w-full justify-between mt-4 pt-4 border-t"):
                btn_back = ui.button("⬅ Indietro", on_click=go_parent).props("flat")
                btn_back.tooltip("Torna al livello superiore della gerarchia NRL mantenendo il percorso di risposta strumentale.")
                btn_forward = ui.button("➡ Avanti", on_click=go_forward_sibling).props("flat")
                btn_forward.tooltip("Avanza al modello fratello nello stesso livello NRL per confrontare risposte nominali simili.")
                close_btn = ui.button("Chiudi", on_click=dialog.close).props("flat text-red")
                close_btn.tooltip("Chiude il browser NRL senza importare nuovi coefficienti o risposte strumentali.")

            if search_query and len(search_query) >= 3:

                async def apply_suggestion_parts(parts):
                    self.path = list(parts)
                    await download()

                self._render_suggestion(suggestion_container, search_query, apply_suggestion_parts)

            await refresh()
        dialog.open()

    def _render_suggestion(self, container, query, apply_async):
        cache_path = "data/nrl_math_cache.json"
        if not os.path.exists(cache_path):
            return
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            group = cache.get("sensors" if self.equip_type == "sensor" else "dataloggers", {})
            q_words = {w for w in re.findall(r"\w+", query.upper()) if len(w) > 1}
            best_match, max_overlap = None, 0
            for n_names in group.values():
                for full_name in n_names:
                    n_words = {w for w in re.findall(r"\w+", full_name.upper()) if len(w) > 1}
                    overlap = len(q_words & n_words)
                    if overlap > max_overlap:
                        max_overlap, best_match = overlap, full_name
            if best_match and max_overlap > 0:
                parts = [p.strip() for p in best_match.split("->")]

                async def on_suggest():
                    await apply_async(parts)

                with container:
                    with ui.button(on_click=on_suggest).classes(
                        "w-full bg-yellow-50 border-2 border-yellow-200 rounded-lg p-3 text-left no-caps shadow-md mb-4"
                    ) as suggest_btn:
                        suggest_btn.tooltip("Suggerimento basato sull indice matematico locale NRL: prova ad aprire/importare la risposta nominale più compatibile.")
                        hint = " ".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")
                        ui.label(f"💡 Suggerimento: {hint}").classes("font-bold text-black")
        except Exception:
            pass
