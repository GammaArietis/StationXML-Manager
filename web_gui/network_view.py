import json

from nicegui import ui

from core.models.base_models import Network
from web_gui.date_form_helpers import datetime_local_to_db, iso_to_datetime_local_field

class NetworkView:
    def __init__(self, net_ctrl, eq_ctrl, on_save):
        self.net_ctrl = net_ctrl
        self.eq_ctrl = eq_ctrl
        self.on_save = on_save
        # Niente più self.container nell'__init__!
        
    def build_ui(self, network: Network):
        """Disegna l'interfaccia nel contesto corrente (workspace)"""
        
        ui.label(f'📁 Network: {network.code}').classes('text-3xl font-bold text-slate-800 mb-6')
        
        # --- BLOCCO 1: DATI GENERALI ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm border-t-4 border-blue-600'):
            ui.label('General Data').classes('text-lg font-bold mb-4 text-blue-800')
            
            with ui.row().classes('w-full gap-4'):
                self.code_in = ui.input('Network Code (*)', value=network.code).classes('w-1/4').props('uppercase maxlength=10')
                self.desc_in = ui.input('Description', value=network.description).classes('flex-grow')
                
            with ui.row().classes('w-full gap-4 mt-4 items-center'):
                self.doi_in = ui.input('Network DOI', value=getattr(network, 'doi', '')).classes('w-1/3')
                self.restr_in = ui.select(['open', 'closed', 'partial'], label='Restricted Status', value=network.restricted_status or 'open').classes('w-1/3')
                
                operators = {None: '--- No Operator ---'}
                for op in self.eq_ctrl.get_all_operators():
                    operators[op.id] = f"{op.agency} ({op.contact_name})" if op.contact_name else op.agency
                self.op_in = ui.select(operators, label='Operator', value=network.operator_id).classes('w-1/3')

        # --- BLOCCO 2: DATE DI OPERATIVITA' ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Operating Dates').classes('text-lg font-bold mb-4 text-slate-700')
            with ui.column().classes('w-full gap-4'):
                with ui.row().classes('w-full gap-4 items-end'):
                    self.start_set = ui.checkbox(
                        'Set start date',
                        value=bool(network.start_date and str(network.start_date).strip()),
                    ).classes('shrink-0')
                    self.start_in = ui.input(
                        'Start Date',
                        value=iso_to_datetime_local_field(network.start_date),
                    ).props('type=datetime-local').classes('w-1/3')
                    self.start_in.bind_enabled_from(self.start_set, 'value')
                with ui.row().classes('w-full gap-4 items-end'):
                    self.end_set = ui.checkbox(
                        'Set end date',
                        value=bool(network.end_date and str(network.end_date).strip()),
                    ).classes('shrink-0')
                    self.end_in = ui.input(
                        'End Date',
                        value=iso_to_datetime_local_field(network.end_date),
                    ).props('type=datetime-local').classes('w-1/3')
                    self.end_in.bind_enabled_from(self.end_set, 'value')

        # --- BLOCCO 3: COMMENTI FDSN ---
        with ui.card().classes('w-full p-6 mb-4 shadow-sm'):
            ui.label('Network Comments (FDSN)').classes('text-lg font-bold mb-4 text-slate-700')
            
            self.comments_container = ui.column().classes('w-full gap-2')
            self.comments_ui_elements = []
            
            try:
                loaded_comments = json.loads(network.comments) if network.comments else []
            except:
                loaded_comments = []
                
            def add_comment_row(c_val="", c_start="", c_end="", c_sub="", c_auth=""):
                with self.comments_container:
                    with ui.row().classes('w-full gap-2 items-center bg-slate-50 p-2 rounded border') as row:
                        v = ui.input('Text', value=c_val).classes('flex-grow')
                        st = ui.input('Start', value=c_start).classes('w-32').props('placeholder=YYYY-MM-DD')
                        en = ui.input('End', value=c_end).classes('w-32').props('placeholder=YYYY-MM-DD')
                        sub = ui.input('Subject', value=c_sub).classes('w-32')
                        auth = ui.input('Author (Name/Agency)', value=c_auth).classes('w-48')
                        
                        btn_remove = ui.button(icon='delete', color='red').props('flat dense')
                        item_tuple = (v, st, en, sub, auth)
                        self.comments_ui_elements.append(item_tuple)
                        btn_remove.on('click', lambda r=row, it=item_tuple: remove_comment_row(r, it))

            def remove_comment_row(row_element, item_tuple):
                row_element.delete()
                if item_tuple in self.comments_ui_elements:
                    self.comments_ui_elements.remove(item_tuple)

            for c in loaded_comments:
                auth_str = c.get('author_name', '')
                if c.get('author_agency'):
                    auth_str += f" ({c.get('author_agency')})"
                add_comment_row(c.get('value',''), c.get('begin_date',''), c.get('end_date',''), c.get('subject',''), auth_str)

            ui.button('+ Add Comment', on_click=lambda: add_comment_row(), color='blue').classes('mt-4').props('outline')

        # --- BLOCCO 4: AZIONI ---
        with ui.row().classes('w-full justify-end gap-4 mt-6'):
            ui.button('🗑️ Delete Network', color='red', on_click=lambda: self.delete(network.id)).props('outline')
            ui.button('💾 Save Network', on_click=lambda: self.save(network), color='green').classes('px-10 font-bold')

    def save(self, network):
        network.code = self.code_in.value.strip().upper() if self.code_in.value else ""
        if not network.code:
            ui.notify("Network Code is required!", type='negative')
            return
            
        network.description = self.desc_in.value
        network.doi = self.doi_in.value
        network.restricted_status = self.restr_in.value
        network.operator_id = self.op_in.value
        network.start_date = datetime_local_to_db(bool(self.start_set.value), self.start_in.value)
        network.end_date = datetime_local_to_db(bool(self.end_set.value), self.end_in.value)
        
        c_list = []
        for v, st, en, sub, auth in self.comments_ui_elements:
            val_text = v.value.strip() if v.value else ""
            if not val_text: continue
            
            auth_text = auth.value.strip() if auth.value else ""
            author_name = auth_text
            author_agency = ""
            if "(" in auth_text and ")" in auth_text:
                parts = auth_text.split("(")
                author_name = parts[0].strip()
                author_agency = parts[1].replace(")", "").strip()

            c_list.append({
                "value": val_text, "begin_date": st.value.strip() if st.value else "",
                "end_date": en.value.strip() if en.value else "", "subject": sub.value.strip() if sub.value else "",
                "author_name": author_name, "author_agency": author_agency
            })
            
        network.comments = json.dumps(c_list) if c_list else None
        
        try:
            self.net_ctrl.save_network(network)
            ui.notify("Network saved successfully!", type='positive')
            self.on_save()
        except Exception as e:
            ui.notify(f"Error saving network: {e}", type='negative')
            
    async def delete(self, net_id):
        with ui.dialog() as dialog, ui.card():
            ui.label('Are you sure? Deleting the network will erase ALL connected stations and channels!').classes('text-lg font-bold text-slate-800')
            with ui.row().classes('w-full justify-end mt-4 gap-2'):
                ui.button('Cancel', on_click=lambda: dialog.submit(False)).props('flat text-color=grey')
                ui.button('Yes, Delete', on_click=lambda: dialog.submit(True)).classes('bg-red-600 text-white font-bold')
                
        # Aspettiamo che l'utente clicchi uno dei due bottoni
        result = await dialog
        
        if result:
            try:
                self.net_ctrl.delete_network(net_id)
                ui.notify("Network deleted.", type='info')
                self.on_save()
            except Exception as e:
                ui.notify(f"Error during deletion: {e}", type='negative')
