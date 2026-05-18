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
        self._filter_text = ""
        
        self.setHeaderLabel("StationXML Hierarchy")
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        
        # Connect user click
        self.itemClicked.connect(self._on_item_clicked)
        
        # Populate tree on startup
        self.refresh_tree()

    def refresh_tree(self):
        """Reloads the entire hierarchy from the database."""
        expanded_keys = self._expanded_keys()
        selected_key = self._selected_key()
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
            
            # Expand networks by default, or restore previous explicit state.
            net_key = ("network", net.id)
            net_item.setExpanded(net_key in expanded_keys or not expanded_keys)

        self._apply_filter()
        self._restore_expanded_and_selected(expanded_keys, selected_key)

    def set_filter_text(self, text: str):
        self._filter_text = (text or "").strip().lower()
        self._apply_filter()

    def _item_key(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None
        return (data.get("type"), data.get("id"))

    def _walk_items(self):
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            yield item
            for i in range(item.childCount()):
                stack.append(item.child(i))

    def _expanded_keys(self):
        return {self._item_key(item) for item in self._walk_items() if item.isExpanded()}

    def _selected_key(self):
        item = self.currentItem()
        return self._item_key(item) if item else None

    def _restore_expanded_and_selected(self, expanded_keys, selected_key):
        for item in self._walk_items():
            key = self._item_key(item)
            if key in expanded_keys:
                item.setExpanded(True)
            if selected_key and key == selected_key:
                self.setCurrentItem(item)
                self.scrollToItem(item)

    def _apply_filter(self):
        needle = self._filter_text
        for i in range(self.topLevelItemCount()):
            net_item = self.topLevelItem(i)
            any_station_visible = False
            for j in range(net_item.childCount()):
                sta_item = net_item.child(j)
                station_match = not needle or needle in sta_item.text(0).lower()
                sta_item.setHidden(not station_match)
                any_station_visible = any_station_visible or station_match
                for k in range(sta_item.childCount()):
                    sta_item.child(k).setHidden(not station_match)
            net_item.setHidden(bool(needle and not any_station_visible))
            if needle and any_station_visible:
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