import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

class AppState:
    """
    Tracks the global state of the application.
    Maintains a reference to the currently selected item and checks
    if there are pending modifications not yet saved in the database.
    """
    def __init__(self):
        self._current_network_id: Optional[int] = None
        self._current_station_id: Optional[int] = None
        self._current_channel_id: Optional[int] = None
        
        # Vital flag: True if the user modified a field but hasn't saved
        self.is_dirty: bool = False

    def mark_dirty(self):
        """Marks the current state as modified (e.g., when the user types in a text box)."""
        if not self.is_dirty:
            logger.debug("Application state: Unsaved modifications (DIRTY).")
            self.is_dirty = True

    def mark_clean(self):
        """Restores the state to clean (e.g., after saving to the database)."""
        if self.is_dirty:
            logger.debug("Application state: Saved (CLEAN).")
            self.is_dirty = False

    def can_navigate_away(self) -> bool:
        """
        The Controller will call this function before changing screens.
        If it returns False, the Controller will show a popup: "Do you want to save before leaving?".
        """
        return not self.is_dirty

    # --- Properties to track current selection ---
    
    @property
    def current_network(self) -> Optional[int]:
        return self._current_network_id

    @current_network.setter
    def current_network(self, net_id: int):
        self._current_network_id = net_id
        # Reset children when the parent network changes
        self._current_station_id = None
        self._current_channel_id = None