"""Miscellaneous UI dialogs and editors for Cetus."""

import os
import re
from pathlib import Path

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

from cetuslib.utils import load_svg_pixmap


__all__ = [
    'StickyNoteDialog',
    'VendorReferenceDialog',
    'FileTextEditor',
]


class _QuickNoteEditor(QTextEdit):
    """QTextEdit with formatting helpers for the Quick Notes dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_name = ''
        self._device_ip   = ''

    def set_device_info(self, name, ip):
        self._device_name = name
        self._device_ip   = ip

    def _insert_marker(self):
        from datetime import datetime
        now    = datetime.now()
        name   = self._device_name or '—'
        ip     = self._device_ip   or '—'
        stamp  = now.strftime('%Y-%m-%d  %H:%M')
        marker = f'\n── {name}  {ip}  {stamp} ──\n'
        self.textCursor().insertText(marker)

    def _toggle_bold(self):
        fmt = self.currentCharFormat()
        weight = QFont.Weight.Normal if fmt.fontWeight() == QFont.Weight.Bold else QFont.Weight.Bold
        self.setFontWeight(weight)

    def _toggle_bullet(self):
        cursor = self.textCursor()
        lst = cursor.currentList()
        if lst:
            # Remove bullet: reset block to default
            block_fmt = cursor.blockFormat()
            block_fmt.setIndent(0)
            cursor.setBlockFormat(block_fmt)
            cursor.setBlockCharFormat(QTextCharFormat())
        else:
            list_fmt = QTextListFormat()
            list_fmt.setStyle(QTextListFormat.Style.ListDisc)
            cursor.createList(list_fmt)

    def _pick_color(self, btn_ref=None):
        _colors = [
            ('#3e2723', 'Black'),
            ('#e53935', 'Red'),
            ('#1565C0', 'Blue'),
            ('#2E7D32', 'Green'),
            ('#F9A825', 'Yellow'),
        ]
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #FFF9C4;
                border: 1px solid #F9A825;
                padding: 4px;
            }
            QMenu::item {
                color: #3e2723;
                padding: 5px 14px 5px 8px;
                border-radius: 4px;
                font-size: 10pt;
            }
            QMenu::item:selected { background: #ffe566; }
        """)
        for hex_color, label in _colors:
            # Build a small coloured square as icon
            pix = QPixmap(14, 14)
            pix.fill(QColor(hex_color))
            action = menu.addAction(QIcon(pix), label)
            action.triggered.connect(lambda checked, c=hex_color: self.setTextColor(QColor(c)))
        pos = btn_ref.mapToGlobal(btn_ref.rect().bottomLeft()) if btn_ref else self.cursor().pos()
        menu.exec(pos)



class StickyNoteDialog(QDialog):
    """Shared floating quick-notes editor.
    Single note shared across all devices — right-click to insert a device marker."""

    def __init__(self, config, device_name='', device_ip='', parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle('Quick Notes')
        self.setMinimumSize(400, 340)
        self.resize(460, 420)
        self.setWindowFlags(
            self.windowFlags() |
            Qt.WindowType.WindowStaysOnTopHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(0)

        title_bar = QLabel('  📌  Quick Notes')
        title_bar.setFixedHeight(28)
        title_bar.setStyleSheet("""
            QLabel {
                background-color: #F9A825;
                color: #3e2723;
                font-size: 9pt;
                font-weight: bold;
                padding-left: 6px;
                border-top-left-radius: 6px;
            }
        """)
        title_row.addWidget(title_bar, 1)

        marker_btn = QPushButton('📍')
        marker_btn.setFixedSize(28, 28)
        marker_btn.setFlat(True)
        marker_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        marker_btn.setToolTip('Insert device marker')
        marker_btn.setStyleSheet("""
            QPushButton {
                background-color: #F9A825;
                color: #3e2723;
                border: none;
                font-size: 13pt;
                border-top-right-radius: 6px;
            }
            QPushButton:hover { background-color: #e69a00; }
            QPushButton:pressed { background-color: #cc8800; }
        """)
        marker_btn.clicked.connect(lambda: self._editor._insert_marker())
        title_row.addWidget(marker_btn)

        title_widget = QWidget()
        title_widget.setLayout(title_row)
        title_widget.setFixedHeight(28)
        layout.addWidget(title_widget)

        # ── Formatting toolbar ────────────────────────────────────────────────
        _tb_btn_style = """
            QPushButton {
                background-color: #FFF176;
                color: #3e2723;
                border: none;
                border-right: 1px solid #F9A825;
                font-size: 11pt;
                font-weight: bold;
                min-width: 32px;
                max-width: 44px;
                height: 26px;
                padding: 0 6px;
            }
            QPushButton:hover   { background-color: #ffe566; }
            QPushButton:pressed { background-color: #F9A825; }
        """
        toolbar = QWidget()
        toolbar.setFixedHeight(28)
        toolbar.setStyleSheet('background-color: #FFF176; border-bottom: 1px solid #F9A825;')
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(4, 1, 4, 1)
        tb_layout.setSpacing(0)

        self._bold_btn   = QPushButton('B')
        self._bold_btn.setToolTip('Bold')
        self._bold_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bold_btn.setStyleSheet(_tb_btn_style + 'QPushButton { font-style: normal; }')
        self._bold_btn.clicked.connect(lambda: self._editor._toggle_bold())

        bullet_btn = QPushButton('•  List')
        bullet_btn.setToolTip('Bullet list')
        bullet_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bullet_btn.setStyleSheet(_tb_btn_style)
        bullet_btn.clicked.connect(lambda: self._editor._toggle_bullet())

        color_btn = QPushButton('A')
        color_btn.setToolTip('Text colour')
        color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        color_btn.setStyleSheet(_tb_btn_style + """
            QPushButton { text-decoration: underline; color: #e53935;
                          border-right: none; }
        """)
        color_btn.clicked.connect(lambda: self._editor._pick_color(color_btn))

        tb_layout.addWidget(self._bold_btn)
        tb_layout.addWidget(bullet_btn)
        tb_layout.addWidget(color_btn)
        tb_layout.addStretch()
        layout.addWidget(toolbar)

        self._editor = _QuickNoteEditor()
        self._editor.setPlaceholderText('Write your notes here…')
        self._editor.setStyleSheet("""
            QTextEdit {
                background-color: #FFF9C4;
                color: #3e2723;
                border: none;
                font-size: 10pt;
                font-family: sans-serif;
                padding: 8px;
            }
        """)
        self._editor.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self._editor, 1)

        self.setStyleSheet("""
            QDialog {
                background-color: #FFF9C4;
                border: 1px solid #F9A825;
                border-radius: 6px;
            }
        """)

        if config:
            saved = config.get_quick_notes()
            if saved.strip().startswith('<'):
                self._editor.setHtml(saved)
            else:
                self._editor.setPlainText(saved)

        self._editor.set_device_info(device_name, device_ip)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save)
        self._editor.textChanged.connect(self._save_timer.start)

    def set_device_info(self, name, ip):
        """Update current device context (called when active terminal changes)."""
        self._editor.set_device_info(name, ip)

    def _save(self):
        if self._config:
            self._config.set_quick_notes(self._editor.toHtml())



class VendorReferenceDialog(QDialog):
    """Quick reference guide dialog for vendor commands"""

    def __init__(self, vendor, reference_data, icon_path=None, parent=None,
                 send_command_callback=None):
        super().__init__(parent)
        self.vendor = vendor
        self.reference_data = reference_data
        self._send_cmd_cb = send_command_callback  # callable(str) → sends to terminal
        self.setWindowTitle(f"{vendor} - Quick Reference")
        self.setMinimumSize(620, 500)
        self.resize(680, 600)
        self.init_ui(icon_path)

    def init_ui(self, icon_path):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QLineEdit {
                background-color: #313244; color: #cdd6f4;
                border: 1px solid #585b70; border-radius: 6px;
                padding: 8px; font-size: 10pt;
            }
            QLineEdit:focus { border: 2px solid #89b4fa; }
            QScrollArea { border: none; background-color: #1e1e2e; }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header: vendor icon + title
        header_layout = QHBoxLayout()
        if icon_path:
            icon_label = QLabel()
            pixmap = load_svg_pixmap(icon_path, 40)
            if pixmap and not pixmap.isNull():
                icon_label.setPixmap(pixmap)
            icon_label.setFixedSize(48, 48)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(icon_label)

        title = QLabel(f"{self.vendor} Quick Reference")
        title.setStyleSheet("color: #89b4fa; font-size: 14pt; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Search filter
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter commands...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_commands)
        layout.addWidget(self.search_input)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: #1e1e2e;")
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(4)
        self.content_widget.setLayout(self.content_layout)
        scroll.setWidget(self.content_widget)
        layout.addWidget(scroll, 1)

        # Build category sections
        self.category_widgets = []
        if self.reference_data:
            self._build_categories()
        else:
            empty_label = QLabel("No quick reference data available for this vendor.")
            empty_label.setStyleSheet("color: #6c7086; font-size: 11pt; padding: 20px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(empty_label)

        self.content_layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setAutoDefault(False)
        close_btn.setMinimumHeight(35)
        close_btn.setMaximumWidth(120)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #585b70; color: #cdd6f4;
                border: none; border-radius: 6px;
                padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #6c7086; }
        """)
        close_btn.clicked.connect(self.close)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _build_categories(self):
        for category, commands in self.reference_data.items():
            cat_label = QLabel(category)
            cat_label.setStyleSheet("""
                color: #a6e3a1; font-size: 11pt; font-weight: bold;
                padding: 6px 0 2px 0;
                border-bottom: 1px solid #45475a;
            """)
            self.content_layout.addWidget(cat_label)

            cmd_widgets = []
            for cmd, desc in commands:
                row = QHBoxLayout()
                row.setContentsMargins(8, 2, 8, 2)
                row.setSpacing(6)

                # Send-to-terminal button (only shown when a callback is available)
                if self._send_cmd_cb is not None:
                    send_btn = QToolButton()
                    send_btn.setText("▶")
                    send_btn.setFixedSize(24, 24)
                    send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    send_btn.setToolTip("Send command to terminal")
                    send_btn.setStyleSheet("""
                        QToolButton {
                            background-color: #313244; color: #a6e3a1;
                            border: 1px solid #45475a; border-radius: 5px;
                            font-size: 9pt; font-weight: bold;
                        }
                        QToolButton:hover { background-color: #45475a; color: #a6e3a1; }
                        QToolButton:pressed { background-color: #585b70; }
                    """)
                    _cmd = cmd  # capture for lambda
                    send_btn.clicked.connect(lambda checked, c=_cmd: self._send_cmd_cb(c + '\n'))
                    row.addWidget(send_btn)

                cmd_label = QLabel(cmd)
                cmd_label.setStyleSheet(
                    "color: #f9e2af; font-family: 'Monospace'; font-size: 10pt; "
                    "background-color: #313244; border-radius: 6px; padding: 3px 6px;"
                )
                cmd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                cmd_label.setMinimumWidth(280)

                desc_label = QLabel(desc)
                desc_label.setStyleSheet("color: #bac2de; font-size: 9pt;")
                desc_label.setWordWrap(True)

                row.addWidget(cmd_label)
                row.addWidget(desc_label, 1)

                container = QWidget()
                container.setLayout(row)
                self.content_layout.addWidget(container)
                cmd_widgets.append((cmd_label, desc_label, container))

            self.category_widgets.append((cat_label, cmd_widgets))

    def _filter_commands(self, text):
        query = text.lower().strip()
        for cat_label, cmd_widgets in self.category_widgets:
            category_visible = False
            for cmd_label, desc_label, container in cmd_widgets:
                if not query:
                    container.setVisible(True)
                    category_visible = True
                else:
                    match = (query in cmd_label.text().lower()
                             or query in desc_label.text().lower())
                    container.setVisible(match)
                    if match:
                        category_visible = True
            cat_label.setVisible(category_visible)





class FileEditorHighlighter(QSyntaxHighlighter):
    """Dark-theme syntax highlighter for the text file editor."""

    def __init__(self, document):
        super().__init__(document)

        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        # Order matters: more specific patterns first
        self._rules = []

        # IP addresses (before plain numbers)
        self._rules.append((
            re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?\b'),
            fmt('#4ec9b0', bold=True)   # teal
        ))

        # Section headers  [section]
        self._rules.append((
            re.compile(r'^\s*\[.*\]\s*$'),
            fmt('#c586c0', bold=True)   # purple
        ))

        # Keywords — Python / shell / network config
        _kw = (
            'if', 'else', 'elif', 'for', 'while', 'def', 'class', 'return',
            'import', 'from', 'as', 'in', 'not', 'and', 'or', 'True', 'False',
            'None', 'pass', 'break', 'continue', 'try', 'except', 'finally',
            'with', 'lambda', 'yield', 'global', 'del', 'raise', 'assert',
            'echo', 'export', 'source', 'alias', 'function',
            'interface', 'router', 'ip', 'no', 'shutdown', 'description',
            'vlan', 'switchport', 'access', 'trunk', 'permit', 'deny',
        )
        self._rules.append((
            re.compile(r'\b(' + '|'.join(_kw) + r')\b'),
            fmt('#569cd6', bold=True)   # blue
        ))

        # Double-quoted strings
        self._rules.append((re.compile(r'"[^"\n\\]*(?:\\.[^"\n\\]*)*"'), fmt('#ce9178')))
        # Single-quoted strings
        self._rules.append((re.compile(r"'[^'\n\\]*(?:\\.[^'\n\\]*)*'"), fmt('#ce9178')))

        # Numbers (standalone, not part of IP)
        self._rules.append((re.compile(r'(?<!\d)\b\d+(?:\.\d+)?\b(?!\.)'), fmt('#b5cea8')))

        # Comments — hash, double-slash, semicolon
        _comment_fmt = fmt('#6a9955', italic=True)
        self._rules.append((re.compile(r'#[^\n]*'),  _comment_fmt))
        self._rules.append((re.compile(r'//[^\n]*'), _comment_fmt))
        self._rules.append((re.compile(r';[^\n]*'),  _comment_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)



class FileTextEditor(QDialog):
    """Simple dark text editor with syntax highlighting."""

    def __init__(self, filename, content, parent=None, save_callback=None):
        super().__init__(parent)
        self._filename = filename
        self._save_callback = save_callback   # callable(str) or None for read-only

        self.setWindowTitle(f"Edit — {filename}")
        self.resize(900, 650)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Monospace", 10))
        self._editor.setPlainText(content)
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                selection-background-color: #264f78;
            }
        """)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._highlighter = FileEditorHighlighter(self._editor.document())
        layout.addWidget(self._editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        if save_callback:
            save_btn = QPushButton("Save")
            save_btn.setFixedWidth(90)
            save_btn.setStyleSheet("""
                QPushButton { background-color: #9C27B0; color: white; border: none;
                    border-radius: 6px; padding: 6px 12px; font-weight: bold; }
                QPushButton:hover { background-color: #7B1FA2; }
            """)
            save_btn.clicked.connect(self._save)
            btn_row.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #555555; color: white; border: none;
                border-radius: 6px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #444444; }
        """)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _save(self):
        try:
            self._save_callback(self._editor.toPlainText())
            self.setWindowTitle(f"Edit — {self._filename}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))





