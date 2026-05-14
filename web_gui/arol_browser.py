from nicegui import ui
import traceback

class AROLBrowser:
    def __init__(self, arol_client, category='dataloggers'):
        self.client = arol_client
        self.category = category
        self.selected_obj = None

    def open(self, callback):
        self.selected_obj = None

        with ui.dialog() as dialog, ui.card().classes('w-[850px] h-[550px] flex flex-col no-wrap'):
            ui.label(f'AROL Library - {self.category}').classes('text-xl font-bold mb-4 shrink-0')
            
            with ui.row().classes('w-full flex-grow gap-4 no-wrap overflow-hidden'):
                with ui.column().classes('w-1/3 h-full border rounded bg-slate-50 flex flex-col no-wrap'):
                    ui.label('Manufacturers').classes('text-xs font-bold uppercase text-slate-600 p-2 bg-slate-200 w-full shrink-0')
                    mfg_cont = ui.column().classes('w-full flex-grow overflow-y-auto gap-0 bg-white')
                
                with ui.column().classes('w-1/3 h-full border rounded bg-slate-50 flex flex-col no-wrap'):
                    ui.label('Models (YAML)').classes('text-xs font-bold uppercase text-slate-600 p-2 bg-slate-200 w-full shrink-0')
                    model_cont = ui.column().classes('w-full flex-grow overflow-y-auto gap-0 bg-white')
                
                with ui.column().classes('w-1/3 h-full border rounded flex flex-col no-wrap bg-slate-50'):
                    ui.label('Metadata Preview').classes('text-xs font-bold uppercase text-slate-600 p-2 bg-slate-200 w-full shrink-0')
                    with ui.scroll_area().classes('w-full flex-grow p-4'):
                        preview = ui.markdown('Select a model to view details...').classes('text-sm text-slate-600')

            with ui.row().classes('w-full justify-end mt-4 gap-2 shrink-0 border-t pt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat text-red')
                btn_import = ui.button('IMPORT MODEL', on_click=lambda: (callback(self.selected_obj), dialog.close())).props('color=green')
                btn_import.disable()

            def load_mfgs():
                try:
                    mfgs = self.client.get_manufacturers(self.category)
                    with mfg_cont:
                        for m in mfgs:
                            ui.label(m).classes('w-full p-3 border-b cursor-pointer hover:bg-blue-50 transition-colors').on('click', lambda _, mfg=m: load_models(mfg))
                except Exception as e:
                    with mfg_cont:
                        ui.label(f"Errore caricamento: {e}").classes('text-red-500 p-2')

            def load_models(mfg):
                model_cont.clear()
                self.selected_obj = None
                btn_import.disable()
                preview.set_content('Select a model...')
                
                try:
                    models = self.client.get_models(self.category, mfg)
                    with model_cont:
                        for mod in models:
                            ui.label(mod).classes('w-full p-3 border-b cursor-pointer hover:bg-blue-50 transition-colors text-sm').on('click', lambda _, m=mfg, md=mod: update_preview(m, md))
                except Exception as e:
                    with model_cont:
                        ui.label(f"Errore: {e}").classes('text-red-500 p-2')

            def update_preview(mfg, model):
                try:
                    # FIX: Aggiunto blocco try/except profondo per scovare errori Pydantic
                    self.selected_obj = self.client.load_component(self.category, mfg, model)
                    if self.selected_obj:
                        desc = getattr(self.selected_obj, 'description', 'No description available.')
                        if not desc: desc = "No description provided."
                        preview.set_content(f"**{mfg} - {model}**\n\n---\n\n{desc}")
                        btn_import.enable()
                    else:
                        preview.set_content("❌ Error: AROL ha restituito un oggetto vuoto. Controlla il YAML.")
                        btn_import.disable()
                except Exception as e:
                    traceback.print_exc()
                    preview.set_content(f"❌ **Errore validazione modello YAML:**\n\n```text\n{e}\n```")
                    btn_import.disable()

            load_mfgs()
            
        dialog.open()
