import sys
import logging
from PyQt6.QtWidgets import QApplication

# 1. Import DAOs
from database.db_manager import DatabaseManager
from database.daos.network_dao import NetworkDAO
from database.daos.station_dao import StationDAO
from database.daos.channel_dao import ChannelDAO
from database.daos.equipment_dao import EquipmentDAO

# 2. Import Controllers
from controllers.network_controller import NetworkController
from controllers.station_controller import StationController
from controllers.channel_controller import ChannelController
from controllers.equipment_controller import EquipmentController

# 3. Import Core & UI
from core.config import get_settings
from core.state import AppState
from ui.main_window import MainWindow
from utils.logging_config import configure_application_logging

# Setup Logging (console + app.log)
configure_application_logging()
logger = logging.getLogger("App")

def main():
    app = QApplication(sys.argv)
    
    settings = get_settings()
    db_manager = DatabaseManager(settings.database_path)
    
    try:
        db_manager.initialize_database(settings.schema_path)
    except FileNotFoundError:
        logger.critical(f"SQL Schema not found!")
        sys.exit(1)
        
    # Initialize Global State
    app_state = AppState()
    
    # Initialize DAOs
    net_dao = NetworkDAO(db_manager)
    sta_dao = StationDAO(db_manager)
    cha_dao = ChannelDAO(db_manager)
    equ_dao = EquipmentDAO(db_manager)
    
    # Initialize Controllers
    net_ctrl = NetworkController(net_dao, app_state)
    sta_ctrl = StationController(sta_dao, app_state)
    cha_ctrl = ChannelController(cha_dao, sta_dao, app_state)
    equ_ctrl = EquipmentController(equ_dao) # Manages catalogs
    
    # --- THESE ARE THE TWO MISSING LINES ---
    sta_ctrl.set_channel_controller(cha_ctrl)
    sta_ctrl.set_equipment_controller(equ_ctrl)
    # -----------------------------------------------
    cha_ctrl.set_equipment_controller(equ_ctrl)
    
    # Start Interface (Pass all necessary controllers)
    window = MainWindow(app_state, net_ctrl, sta_ctrl, cha_ctrl, equ_ctrl)
    window.show()
    
    logger.info("StationXML Manager system ready.")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()