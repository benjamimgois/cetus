"""Reusable UI widgets for Cetus."""

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QPushButton, QMenu


__all__ = ['FlatComboButton', '_CollapsibleGroupBox']


class FlatComboButton(QPushButton):
    """Drop-in replacement for QComboBox using a flat QPushButton + QMenu.

    Supports the most common QComboBox API:
      addItem / addItems / insertItem / clear / count / itemText
      currentText / setCurrentText / currentIndex / setCurrentIndex / findText
      currentTextChanged signal
      setPlaceholderText / setToolTip / setFixedWidth / setMinimumWidth / setMaximumWidth

    External setStyleSheet() calls targeting "QComboBox { ... }" have no
    effect on a QPushButton subclass, so existing per-combo stylesheets are
    automatically ignored and the consistent dark look is preserved.
    """

    currentTextChanged = pyqtSignal(str)

    _BTN_STYLE = """
        QPushButton {
            background-color: #f5f5f5;
            color: #333333;
            border: 1px solid #cccccc;
            border-radius: 6px;
            padding: 3px 10px 3px 8px;
            font-size: 10pt;
            font-weight: normal;
            text-align: left;
        }
        QPushButton:hover {
            background-color: #eeeeee;
            border-color: #aaaaaa;
        }
        QPushButton:pressed {
            background-color: #e0e0e0;
        }
    """
    _MENU_STYLE = """
        QMenu {
            background-color: #ffffff;
            color: #333333;
            border: 1px solid #cccccc;
            border-radius: 6px;
            padding: 4px 0px;
        }
        QMenu::item {
            padding: 6px 20px 6px 10px;
        }
        QMenu::item:selected {
            background-color: #e8e8e8;
            border-radius: 6px;
        }
        QMenu::item:checked {
            color: #1976d2;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._current = ''
        self._placeholder = ''
        self._display_func = None   # optional callable(raw_value) -> display string
        self._menu = QMenu(self)
        self._menu.setStyleSheet(self._MENU_STYLE)
        super().setStyleSheet(self._BTN_STYLE)
        self.setFixedHeight(35)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._show_menu)

    # ── internal ──────────────────────────────────────────────────────────

    def _show_menu(self):
        pos = self.mapToGlobal(QPoint(0, self.height()))
        self._menu.exec(pos)

    def _select(self, text, emit=True):
        old = self._current
        self._current = text
        self._refresh_display()
        if emit and text != old:
            self.currentTextChanged.emit(text)

    def _refresh_display(self):
        raw = self._current if self._current else self._placeholder
        label = self._display_func(raw) if (self._display_func and self._current) else raw
        super().setText(f"  {label}  ▾")
        for action in self._menu.actions():
            action.setChecked(action.text() == self._current)

    def _rebuild_menu(self):
        self._menu.clear()
        for text in self._items:
            action = self._menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(text == self._current)
            action.triggered.connect(lambda checked, t=text: self._select(t))

    # ── QComboBox-compatible API ───────────────────────────────────────────

    def addItem(self, text, userData=None):
        if text not in self._items:
            self._items.append(text)
            action = self._menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, t=text: self._select(t))
        if not self._current:
            self._select(text, emit=False)

    def addItems(self, items):
        for item in items:
            self.addItem(item)

    def insertItem(self, idx, text, userData=None):
        if text not in self._items:
            self._items.insert(idx, text)
            self._rebuild_menu()
        if not self._current:
            self._select(text, emit=False)

    def clear(self):
        self._items.clear()
        self._menu.clear()
        self._current = ''
        self._refresh_display()

    def count(self):
        return len(self._items)

    def currentText(self):
        return self._current

    def currentIndex(self):
        try:
            return self._items.index(self._current)
        except ValueError:
            return -1

    def setCurrentText(self, text):
        if text not in self._items:
            self.addItem(text)
        self._select(text, emit=False)

    def setCurrentIndex(self, idx):
        if 0 <= idx < len(self._items):
            self._select(self._items[idx], emit=False)

    def findText(self, text, flags=None):
        try:
            return self._items.index(text)
        except ValueError:
            return -1

    def itemText(self, idx):
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return ''

    def setPlaceholderText(self, text):
        self._placeholder = text
        if not self._current:
            self._refresh_display()

    # QPushButton overrides to keep our style intact
    def setStyleSheet(self, _):
        pass  # external stylesheets targeting QComboBox have no effect here

    def setText(self, _):
        pass  # label is managed internally via _refresh_display


class _CollapsibleGroupBox(QGroupBox):
    """QGroupBox whose title bar acts as a collapse/expand toggle.
    Click anywhere on the title text (top ~20 px) to toggle visibility of content.
    The title prefix '▾ ' / '▸ ' reflects the current state.
    """
    toggle_requested = pyqtSignal()

    def mousePressEvent(self, event):
        title_height = self.fontMetrics().height() + 10
        if event.position().y() <= title_height:
            self.toggle_requested.emit()
        else:
            super().mousePressEvent(event)

    def setCursor_hand(self):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
