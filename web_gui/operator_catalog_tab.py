import traceback
from typing import Optional

from nicegui import ui

from core.models.base_models import Operator


class OperatorCatalogTab:
    """Catalogo web operatori: layout allineato a Sensor / Datalogger / Preamplifier."""

    def __init__(self, eq_ctrl):
        self.eq_ctrl = eq_ctrl
        self.current_op: Optional[Operator] = None
        self.build_ui()
        self.refresh_list()

    def build_ui(self):
        with ui.grid(columns="250px 1fr 400px").style("width: 100%; height: 100%; gap: 0; margin: 0; padding: 0;"):
            # --- COLONNA 1: LISTA ---
            with ui.column().classes("h-full bg-slate-50 border-r p-4 flex flex-col no-wrap").style("overflow: hidden;"):
                ui.label("Operators").classes("font-bold text-slate-700 text-xs uppercase mb-2 shrink-0")
                self.op_list = ui.list().classes(
                    "w-full border rounded bg-white overflow-y-auto shadow-inner"
                ).style("flex: 1 1 0;")

                with ui.row().classes("w-full gap-1 mt-4 shrink-0"):
                    new_btn = ui.button("➕ New", on_click=self._prepare_new_operator).props("outline size=sm").classes(
                        "flex-grow bg-white"
                    )
                    new_btn.tooltip("Prepara una nuova agenzia/operatore responsabile della gestione e manutenzione di reti o stazioni sismiche.")

            # --- COLONNA 2: EDITOR ---
            with ui.column().classes("h-full p-8 bg-white flex flex-col no-wrap overflow-y-auto"):
                ui.label("Operator Editor").classes("text-2xl font-bold text-indigo-800 mb-6 shrink-0")

                with ui.card().classes("w-full p-6 mb-6 shadow-sm border-l-8 border-indigo-600 shrink-0"):
                    self.op_agency = ui.input("Agency / Entity").classes("w-full mb-2").props('placeholder="INGV" hint="Nome dell agenzia responsabile della rete sismica, stazione o distribuzione dei metadati FDSN."')
                    self.op_name = ui.input("Contact Name").classes("w-full mb-2").props('placeholder="Metadata Office" hint="Referente tecnico o ufficio responsabile della qualità dei metadati StationXML."')
                    self.op_email = ui.input("Email").classes("w-full mb-2").props('placeholder="metadata@example.org" hint="Contatto operativo per correzioni di inventario, response metadata o richieste FDSN."')
                    self.op_web = ui.input("Website").classes("w-full mb-2").props('placeholder="https://www.example.org" hint="URL istituzionale dell operatore o del data center responsabile della rete."')
                    self.op_phone = ui.input("Phone").classes("w-full").props('placeholder="39-3331234567" hint="Numero telefonico in formato FDSN country-subscriber, ad esempio 39-3331234567."')

                with ui.row().classes("w-full justify-between items-center pt-6 mt-6 border-t shrink-0"):
                    with ui.row().classes("gap-2"):
                        self.btn_op_clone = ui.button("👯 Clone", on_click=self._on_clone_clicked).props(
                            "outline color=purple"
                        )
                        self.btn_op_clone.tooltip("Clona l operatore creando una nuova riga database con ID distinto e suffisso (Copy).")
                        self.btn_op_clone.disable()

                        self.btn_op_replace = ui.button("🔄 Replace", on_click=self._on_replace_clicked).props(
                            "outline color=orange"
                        )
                        self.btn_op_replace.tooltip("Sposta riferimenti di reti e stazioni verso un operatore master preservando integrità e tracciabilità.")
                        self.btn_op_replace.disable()

                        self.btn_op_delete = ui.button("🗑️ Delete", on_click=self._on_delete_clicked).props(
                            "outline color=red"
                        )
                        self.btn_op_delete.tooltip("Elimina l operatore solo se nessuna rete o stazione lo referenzia ancora.")
                        self.btn_op_delete.disable()

                    save_btn = ui.button("💾 SAVE OPERATOR", on_click=self._save_operator, color="green").classes(
                        "px-10 h-12 font-bold shadow-md"
                    )
                    save_btn.tooltip("Persiste l operatore nel database SQLite per associare ownership e manutenzione a reti e stazioni.")

            # --- COLONNA 3: INFO ---
            with ui.column().classes("h-full p-6 bg-slate-50 border-l overflow-y-auto"):
                ui.label("Catalog actions").classes("font-bold text-slate-500 uppercase text-xs mb-4 shrink-0")
                ui.markdown(
                    "**Save** — scrive su `operator_catalog`.\n\n"
                    "**Clone** — crea una nuova riga (agency con suffisso «(Copy)») senza riusare l’ID.\n\n"
                    "**Replace** — sposta tutti i riferimenti da reti e stazioni verso un altro operatore, "
                    "poi elimina la riga corrente.\n\n"
                    "**Delete** — elimina solo se nessuna **rete** referenzia ancora l’operatore (vincolo applicativo)."
                ).classes("text-sm text-slate-600 leading-relaxed")

    def refresh_list(self):
        self.op_list.clear()
        with self.op_list:
            for op in self.eq_ctrl.get_all_operators():
                display = f"{op.agency} — {op.contact_name}" if op.contact_name else op.agency
                ui.item(display).props("clickable v-ripple").classes(
                    "cursor-pointer hover:bg-indigo-50 border-b w-full px-4 py-2"
                ).on("click", lambda _, oid=op.id: self._load_operator_by_id(oid))

    def _load_operator_by_id(self, op_id: int):
        try:
            if op_id is None:
                return
            self.btn_op_clone.enable()
            self.btn_op_replace.enable()
            self.btn_op_delete.enable()
            op = self.eq_ctrl.get_operator_by_id(int(op_id))
            if not op:
                ui.notify("Operatore non trovato.", type="warning")
                self._prepare_new_operator()
                return
            self._apply_operator_to_form(op)
        except Exception as e:
            traceback.print_exc()
            self._prepare_new_operator()
            ui.notify(f"Errore caricamento: {e}", type="negative")

    def _apply_operator_to_form(self, op: Operator):
        self.current_op = op
        self.op_agency.value = op.agency or ""
        self.op_name.value = op.contact_name or ""
        self.op_email.value = op.contact_email or ""
        self.op_web.value = op.website or ""
        self.op_phone.value = op.phone_number or ""
        self.btn_op_clone.enable()
        self.btn_op_replace.enable()
        self.btn_op_delete.enable()

    def _prepare_new_operator(self):
        self.current_op = Operator(agency="")
        self.op_agency.value = ""
        self.op_name.value = ""
        self.op_email.value = ""
        self.op_web.value = ""
        self.op_phone.value = ""
        self.btn_op_clone.disable()
        self.btn_op_replace.disable()
        self.btn_op_delete.disable()

    def _operator_from_form(self, op_id: Optional[int]) -> Operator:
        agency = (self.op_agency.value or "").strip()
        cc = int(self.current_op.phone_country_code) if self.current_op and self.current_op.phone_country_code is not None else 39
        ac = int(self.current_op.phone_area_code) if self.current_op and self.current_op.phone_area_code is not None else 0
        return Operator(
            id=op_id,
            agency=agency,
            contact_name=(self.op_name.value or "").strip() or None,
            contact_email=(self.op_email.value or "").strip() or None,
            website=(self.op_web.value or "").strip() or None,
            phone_country_code=cc,
            phone_area_code=ac,
            phone_number=(self.op_phone.value or "").strip() or None,
        )

    def _save_operator(self):
        try:
            op_id = self.current_op.id if self.current_op else None
            new_op = self._operator_from_form(op_id)
            if not new_op.agency:
                ui.notify("L’agenzia è obbligatoria.", type="negative")
                return
            saved = self.eq_ctrl.save_operator(new_op)
            if not saved:
                ui.notify("Salvataggio non riuscito (duplicato o errore DB?).", type="negative")
                return
            self.current_op = saved
            self.refresh_list()
            self._apply_operator_to_form(saved)
            ui.notify("Operatore salvato.", type="positive")
        except ValueError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore salvataggio: {e}", type="negative")

    def _on_clone_clicked(self):
        try:
            src = self._operator_from_form(None)
            if not src.agency:
                ui.notify("Inserisci almeno l’agenzia da duplicare.", type="warning")
                return
            data = src.model_dump()
            data["id"] = None
            data["agency"] = f"{src.agency} (Copy)"
            dup = Operator.model_validate(data)
            saved = self.eq_ctrl.save_operator(dup)
            if not saved:
                ui.notify("Duplicazione non riuscita (vincolo UNIQUE su agency/contatti?).", type="negative")
                return
            self.current_op = saved
            self.refresh_list()
            self._apply_operator_to_form(saved)
            ui.notify(f"Creato duplicato: {saved.agency}", type="positive")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore clone: {e}", type="negative")

    def _on_replace_clicked(self):
        if not self.current_op or not self.current_op.id:
            ui.notify("Seleziona un operatore salvato da sostituire.", type="warning")
            return
        others = {
            o.id: f"{o.agency} — {o.contact_name}" if o.contact_name else o.agency
            for o in self.eq_ctrl.get_all_operators()
            if o.id != self.current_op.id
        }
        if not others:
            ui.notify("Non ci sono altri operatori con cui sostituire.", type="warning")
            return

        with ui.dialog() as d, ui.card().classes("w-96 p-6"):
            ui.label("Replace operator").classes("text-lg font-bold mb-2 text-slate-800")
            ui.label(
                "Tutte le reti e le stazioni che usano l’operatore corrente punteranno al sostituto; "
                "questa riga verrà eliminata dal catalogo."
            ).classes("text-sm text-slate-600 mb-4")
            sel = ui.select(others, label="Operatore da mantenere", with_input=True).classes("w-full")
            sel.tooltip("Operatore master che erediterà i riferimenti di reti e stazioni prima della rimozione del duplicato.")
            with ui.row().classes("w-full justify-end mt-4 gap-2"):
                cancel_btn = ui.button("Annulla", on_click=d.close).props("flat")
                cancel_btn.tooltip("Annulla la sostituzione senza modificare riferimenti nel database.")
                confirm_btn = ui.button(
                    "Conferma",
                    color="orange",
                    on_click=lambda: self._run_replace(d, sel.value),
                ).classes("font-bold")
                confirm_btn.tooltip("Normalizza le relazioni spostando reti e stazioni dall operatore duplicato a quello master.")

        d.open()

    def _run_replace(self, dialog, new_id):
        if not new_id or not self.current_op or not self.current_op.id:
            ui.notify("Seleziona un operatore di destinazione.", type="warning")
            return
        old_id = int(self.current_op.id)
        try:
            nid = int(new_id)
        except (TypeError, ValueError):
            ui.notify("ID destinazione non valido.", type="negative")
            return
        if old_id == nid:
            dialog.close()
            return
        try:
            if not self.eq_ctrl.replace_operator(old_id, nid):
                ui.notify("Replace non eseguito (ID non valido?).", type="negative")
                return
            dialog.close()
            self.refresh_list()
            self._load_operator_by_id(nid)
            ui.notify("Sostituzione completata.", type="positive")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore replace: {e}", type="negative")

    async def _on_delete_clicked(self):
        if not self.current_op:
            ui.notify("Nessun operatore selezionato.", type="warning")
            return
        raw_id = getattr(self.current_op, "id", None)
        if raw_id is None:
            ui.notify("Eliminazione possibile solo per righe già salvate nel catalogo.", type="warning")
            return
        try:
            oid = int(raw_id)
        except (TypeError, ValueError):
            ui.notify("ID operatore non valido.", type="negative")
            return

        with ui.dialog() as dialog, ui.card():
            ui.label("Eliminare questo operatore?").classes("text-lg font-bold text-slate-800")
            ui.label(
                "Non è possibile se almeno una **rete** lo referenzia ancora. "
                "In quel caso usa Replace oppure aggiorna le reti."
            ).classes("text-sm text-slate-600 mt-2")
            with ui.row().classes("w-full justify-end mt-6 gap-2"):
                ui.button("Annulla", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Elimina", on_click=lambda: dialog.submit(True)).classes("bg-red-600 text-white font-bold")

        confirmed = await dialog
        if not confirmed:
            return

        try:
            if self.eq_ctrl.delete_operator(oid):
                ui.notify("Operatore eliminato.", type="info")
                self._prepare_new_operator()
                self.refresh_list()
            else:
                ui.notify("Nessuna riga eliminata.", type="warning")
        except ValueError as e:
            ui.notify(str(e), type="negative")
        except Exception as e:
            traceback.print_exc()
            ui.notify(f"Errore eliminazione: {e}", type="negative")
