"""
window_selector.py - Dialog for selecting a target window.

Shows a searchable list of all open windows with columns for
Application, Title, PID, and Dimensions.
The user picks one and clicks "Select".  They can also click
"Refresh" to re-enumerate windows without closing the dialog.
"""

from __future__ import annotations

from PyQt6.QtCore import QSortFilterProxyModel, Qt
from PyQt6.QtGui import QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
)

from panopticon.utils.platform import WindowInfo, list_windows


class WindowSelectorDialog(QDialog):
    """
    Modal dialog that lets the user pick a window to monitor.

    Usage:
        dlg = WindowSelectorDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            window = dlg.selected_window
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Window")
        self.setMinimumSize(620, 420)
        self.selected_window: WindowInfo | None = None
        self._windows: list[WindowInfo] = []

        self._build_ui()
        self._load_windows()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header label
        header = QLabel("Select a window to monitor:")
        font = QFont()
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by application, title, or PID...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search)

        # Table model  (Application | Title | PID | Dimensions)
        self._model = QStandardItemModel(0, 4)
        self._model.setHorizontalHeaderLabels(["Application", "Title", "PID", "Dimensions"])

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search all columns

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.doubleClicked.connect(self._on_double_click)
        self._tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._tree)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._status_label)

        # Bottom buttons
        btn_layout = QHBoxLayout()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._load_windows)
        btn_layout.addWidget(self._refresh_btn)

        btn_layout.addStretch()

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("Select")
        self._ok_btn.setEnabled(False)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        btn_layout.addWidget(self._button_box)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_windows(self):
        self._refresh_btn.setEnabled(False)
        self._status_label.setText("Enumerating windows...")
        self._model.removeRows(0, self._model.rowCount())

        try:
            self._windows = list_windows()
        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._refresh_btn.setEnabled(True)
            return

        for win in self._windows:
            app_item = QStandardItem(win.application or "")
            app_item.setData(win)  # store WindowInfo on the first item

            title_item = QStandardItem(win.title)

            pid_item = QStandardItem(str(win.pid) if win.pid else "")
            pid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            dim_str = f"{win.width} × {win.height}" if win.is_valid_geometry else "unknown"
            dim_item = QStandardItem(dim_str)
            dim_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            for item in (title_item, pid_item, dim_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self._model.appendRow([app_item, title_item, pid_item, dim_item])

        count = self._model.rowCount()
        self._status_label.setText(f"{count} window{'s' if count != 1 else ''} found.")
        self._refresh_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------

    def _on_filter_changed(self, text: str):
        self._proxy.setFilterFixedString(text)

    def _on_selection_changed(self):
        indexes = self._tree.selectionModel().selectedRows()
        self._ok_btn.setEnabled(bool(indexes))

    def _on_double_click(self, _index):
        indexes = self._tree.selectionModel().selectedRows()
        if indexes:
            self._accept_row(indexes[0])

    def _on_accept(self):
        indexes = self._tree.selectionModel().selectedRows()
        if indexes:
            self._accept_row(indexes[0])

    def _accept_row(self, proxy_index):
        source_index = self._proxy.mapToSource(proxy_index)
        item = self._model.item(source_index.row(), 0)
        if item:
            self.selected_window = item.data()
            self.accept()
