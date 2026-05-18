from nicegui import ui
from web_gui.operator_catalog_tab import OperatorCatalogTab
from web_gui.sensor_catalog_tab import SensorCatalogTab
from web_gui.datalogger_catalog_tab import DataloggerCatalogTab
from web_gui.preamplifier_catalog_tab import PreamplifierCatalogTab

class CatalogDialog:
    def __init__(self, eq_ctrl, on_catalog_closed):
        self.eq_ctrl = eq_ctrl
        self.on_catalog_closed = on_catalog_closed
        
        with ui.dialog().classes('w-full max-w-full') as self.dialog:
            # Stili inline forzati per non far scappare il layout
            with ui.card().style('width: 95vw; height: 90vh; max-width: none; padding: 0; display: flex; flex-direction: column; overflow: hidden;'):
                
                with ui.row().classes('w-full bg-slate-800 text-white p-4 items-center justify-between m-0'):
                    title = ui.label('⚙️ Equipment & Operators Catalog').classes('text-xl font-bold')
                    title.tooltip('Catalogo centralizzato di sensori, datalogger, preamplificatori e operatori usato per costruire risposte StationXML coerenti.')
                    close_btn = ui.button(icon='close', on_click=self.dialog.close).props('flat round text-white')
                    close_btn.tooltip('Chiude il catalogo mantenendo i record strumentali salvati nel database SQLite.')
                
                with ui.tabs().classes('w-full bg-slate-100 text-slate-700 m-0') as tabs:
                    self.tab_sens = ui.tab('Sensors')
                    self.tab_sens.tooltip('Sensori con unità fisiche, sensibilità, poli e zeri.')
                    self.tab_log = ui.tab('Dataloggers')
                    self.tab_log.tooltip('Digitalizzatori con gain, clock drift, stadi FIR e decimazioni.')
                    self.tab_pre = ui.tab('Preamplifiers')
                    self.tab_pre.tooltip('Preamplificatori e stadi analogici che contribuiscono alla sensibilità totale.')
                    self.tab_op = ui.tab('Operators')
                    self.tab_op.tooltip('Agenzie e contatti responsabili di reti, stazioni e metadati FDSN.')
                
                # flex-grow permette al tab di riempire lo spazio "sotto", senza sbordare
                with ui.tab_panels(tabs, value=self.tab_sens).classes('w-full flex-grow p-0 m-0'):
                    with ui.tab_panel(self.tab_sens).classes('w-full h-full p-0 m-0 overflow-hidden'):
                        self.sensor_tab = SensorCatalogTab(self.eq_ctrl)
                        
                    with ui.tab_panel(self.tab_log).classes('w-full h-full p-0 m-0 overflow-hidden'):
                        self.datalogger_tab = DataloggerCatalogTab(self.eq_ctrl)
                        
                    with ui.tab_panel(self.tab_pre).classes('w-full h-full p-0 m-0 overflow-hidden'):
                        self.preamp_tab = PreamplifierCatalogTab(self.eq_ctrl)
                        
                    with ui.tab_panel(self.tab_op).classes('w-full h-full p-0 m-0 overflow-hidden'):
                        self.operator_tab = OperatorCatalogTab(self.eq_ctrl)

        self.dialog.on('hide', self.on_catalog_closed)

    def open(self):
        self.dialog.open()
