from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt
import logging

from utils.signals import app_signals

logger = logging.getLogger(__name__)

class TreeNav(QTreeWidget):
    """
    Widget for the 3-level navigation tree: Network > Station > Channel.
    """
    def __init__(self, network_ctrl, station_ctrl, channel_ctrl):
        super().__init__()
        self.net_ctrl = network_ctrl
        self.sta_ctrl = station_ctrl
        self.cha_ctrl = channel_ctrl
        
        self.setHeaderLabel("StationXML Hierarchy")
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        
        # Connect user click
        self.itemClicked.connect(self._on_item_clicked)
        
        # Populate tree on startup
        self.refresh_tree()

    def refresh_tree(self):
        """Reloads the entire hierarchy from the database."""
        self.clear()
        
        # 1. LOAD NETWORKS
        networks = self.net_ctrl.get_all_networks()
        
        for net in networks:
            net_text = f"Net: {net.code}"
            if net.description:
                net_text += f" - {net.description}"
                
            net_item = QTreeWidgetItem(self, [net_text])
            net_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "network", "id": net.id})
            
            # 2. LOAD STATIONS (Network Children)
            stations = self.sta_ctrl.get_stations_by_network(net.id)
            for sta in stations:
                # ==========================================
                # SCADA LOGIC: Yasmine state calculation
                # ==========================================
                status_code, icon, tooltip = self.sta_ctrl.get_sync_status(sta)
                
                sta_text = f"{icon} Sta: {sta.code}"
                if sta.site_name:
                    sta_text += f" ({sta.site_name})"
                    
                sta_item = QTreeWidgetItem(net_item, [sta_text])
                sta_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "station", "id": sta.id})
                
                # Add explanatory tooltip (appears on mouse hover)
                sta_item.setToolTip(0, tooltip)
                
                # Color the row for immediate visual feedback
                if status_code == "MODIFIED":
                    sta_item.setForeground(0, Qt.GlobalColor.darkRed)
                elif status_code == "SYNCED":
                    sta_item.setForeground(0, Qt.GlobalColor.darkGreen)
                # ==========================================

                # 3. LOAD CHANNELS (Station Children)
                channels = self.cha_ctrl.get_channels_by_station(sta.id)
                for cha in channels:
                    display_loc = cha.location_code if cha.location_code else "--"
                    start_year = cha.start_date[:4] if cha.start_date else "Unknown start"
                    
                    cha_text = f"Ch: {cha.code} ({display_loc}) [{start_year}]"
                    
                    cha_item = QTreeWidgetItem(sta_item, [cha_text])
                    cha_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "channel", "id": cha.id})
            
            # Expand networks by default
            net_item.setExpanded(True)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handles click on a node and emits the appropriate signal."""
        node_data = item.data(0, Qt.ItemDataRole.UserRole)
        
        if not node_data:
            return

        node_type = node_data["type"]
        node_id = node_data["id"]

        if node_type == "network":
            logger.debug(f"Selected Network ID: {node_id}")
            app_signals.network_selected.emit(node_id)
            
        elif node_type == "station":
            logger.debug(f"Selected Station ID: {node_id}")
            app_signals.station_selected.emit(node_id)

        elif node_type == "channel":
            logger.debug(f"Selected Channel ID: {node_id}")
            # Emit signal to load channel form on the right
            app_signals.channel_selected.emit(node_id)