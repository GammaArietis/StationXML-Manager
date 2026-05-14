from PyQt6.QtCore import QObject, pyqtSignal

class GlobalSignals(QObject):
    """
    Collects all global application signals (Event Bus).
    Allows distant components to communicate without knowing each other directly.
    """
    
    # --- Navigation Signals (Tree Clicks) ---
    network_selected = pyqtSignal(int)  # Passes the network ID
    station_selected = pyqtSignal(int)  # Passes the station ID
    channel_selected = pyqtSignal(int)  # Passes the channel ID
    sync_yasmine_requested = pyqtSignal(int)  # Passes the station ID
    
    # --- Data Update Signals ---
    # When we save data in the right form, the tree on the left 
    # must refresh to show the new name or new element.
    network_updated = pyqtSignal()
    station_updated = pyqtSignal()
    channel_updated = pyqtSignal()
    
    equipment_updated = pyqtSignal()

# Create the global instance (Singleton) that will be imported everywhere
app_signals = GlobalSignals()