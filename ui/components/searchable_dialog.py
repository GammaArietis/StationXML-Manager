from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class SearchableItemDialog(QDialog):
    """Small item picker with live case-insensitive filtering."""

    def __init__(
        self,
        items: Iterable[Tuple[str, Any]],
        *,
        title: str = "Select item",
        placeholder: str = "Cerca...",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 520)
        self.selected_data = None

        layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(placeholder)
        self.search_input.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_input)

        self.item_list = QListWidget()
        self.item_list.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self.item_list, 1)

        for label, data in items:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.item_list.addItem(item)

        if self.item_list.count() > 0:
            self.item_list.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _filter_items(self, text: str) -> None:
        needle = (text or "").strip().lower()
        first_visible = None
        for i in range(self.item_list.count()):
            item = self.item_list.item(i)
            item.setHidden(bool(needle and needle not in item.text().lower()))
            if first_visible is None and not item.isHidden():
                first_visible = item
        if first_visible is not None:
            self.item_list.setCurrentItem(first_visible)

    def _accept_item(self, item: QListWidgetItem) -> None:
        self.item_list.setCurrentItem(item)
        self.accept()

    def accept(self) -> None:
        item = self.item_list.currentItem()
        if item is None or item.isHidden():
            return
        self.selected_data = item.data(Qt.ItemDataRole.UserRole)
        super().accept()

    @staticmethod
    def get_item(
        items: Iterable[Tuple[str, Any]],
        *,
        title: str = "Select item",
        placeholder: str = "Cerca...",
        parent=None,
    ) -> tuple[Optional[Any], bool]:
        dialog = SearchableItemDialog(
            items,
            title=title,
            placeholder=placeholder,
            parent=parent,
        )
        ok = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.selected_data, ok
