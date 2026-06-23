"""Terminal widgets and dialogs for Cetus."""

import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import pyte
from pyte import escape as pyte_escape

try:
    from PyQt6.QtSvg import QSvgRenderer
    SVG_AVAILABLE = True
except ImportError:
    SVG_AVAILABLE = False

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

from cetuslib.utils import load_svg_icon, load_svg_pixmap, load_svg_icon_dual


__all__ = [
    'TerminalWidget',
    'TerminalDialog',
    'TerminalTabbedWindow',
    'DetachedTerminalWindow',
    'DetachableTabBar',
]


class _CursorOverlay(QWidget):
    """Transparent widget that sits on top of TerminalWidget's viewport and
    draws only the cursor block.  This avoids calling setHtml() on every
    blink tick, which replaced the full document and caused line flickering."""

    def __init__(self, terminal):
        from PyQt6.QtCore import Qt as _Qt
        super().__init__(terminal.viewport())
        self._t = terminal
        self.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(_Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(terminal.viewport().rect())
        self.raise_()

    def paintEvent(self, event):
        t = self._t
        if not t._cursor_visible or t._in_scrollback_mode:
            return
        from PyQt6.QtGui import QPainter, QColor, QFontMetricsF, QTextCursor
        from PyQt6.QtCore import QRectF

        # Use QTextEdit.cursorRect() so Qt's own layout engine gives us the
        # exact pixel position — avoids any discrepancy with averageCharWidth().
        doc = t.document()
        block = doc.findBlockByNumber(t._cur_y)
        if not block.isValid():
            return
        tc = QTextCursor(block)
        if t._cur_x > 0:
            tc.movePosition(QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.MoveAnchor, t._cur_x)
        # cursorRect() returns viewport coordinates directly
        cr = t.cursorRect(tc)

        fm = QFontMetricsF(t.font())
        char_width = fm.averageCharWidth()
        em = fm.ascent() + fm.descent()
        rect = QRectF(cr.x(), cr.y(), char_width, em)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        try:
            with t._pyte_lock:
                ch = t.screen.buffer[t._cur_y][t._cur_x].data
        except Exception:
            ch = ' '
        if ch and ch != ' ':
            painter.fillRect(rect, QColor('#e0e0e0'))
            painter.setPen(QColor('#0a0a0a'))
            painter.setFont(t.font())
            painter.drawText(rect, ch)
        else:
            painter.fillRect(rect, QColor('#e0e0e0'))
        painter.end()



class _AcItemDelegate(QStyledItemDelegate):
    """Renders autocomplete items with command highlighted and description muted."""

    def paint(self, painter, option, index):
        from PyQt6.QtGui import QFont, QColor, QPalette
        painter.save()

        # Background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor('#363a4f'))
        else:
            painter.fillRect(option.rect, QColor('#1e2030'))

        cmd  = index.data(Qt.ItemDataRole.UserRole) or ''
        desc = index.data(Qt.ItemDataRole.UserRole + 1) or ''

        x = option.rect.x() + 10
        y = option.rect.y()
        h = option.rect.height()

        # Command — monospace, normal weight, accent colour when selected
        cmd_font = QFont('Monospace', 9)
        cmd_font.setWeight(QFont.Weight.Normal)
        painter.setFont(cmd_font)
        cmd_color = QColor('#89dceb') if (option.state & QStyle.StateFlag.State_Selected) else QColor('#cdd6f4')
        painter.setPen(cmd_color)
        fm_cmd = painter.fontMetrics()
        painter.drawText(x, y, fm_cmd.horizontalAdvance(cmd), h,
                         Qt.AlignmentFlag.AlignVCenter, cmd)
        x += fm_cmd.horizontalAdvance(cmd)

        # Separator + description — sans-serif, smaller, italic, muted gray
        if desc:
            sep = '   \u2014   '
            desc_font = QFont('Sans Serif', 8)
            desc_font.setItalic(True)
            painter.setFont(desc_font)
            painter.setPen(QColor('#585b70'))
            fm_desc = painter.fontMetrics()
            painter.drawText(x, y, fm_desc.horizontalAdvance(sep + desc), h,
                             Qt.AlignmentFlag.AlignVCenter, sep + desc)

        painter.restore()

    def sizeHint(self, option, index):
        from PyQt6.QtCore import QSize
        return QSize(option.rect.width(), 22)



class _TopCmdsDelegate(QStyledItemDelegate):
    """Renders top-commands list items: rank badge + command text + usage count."""

    _RANK_COLORS = ['#f9e2af', '#89dceb', '#a6e3a1']  # gold, cyan, green for top 3

    def paint(self, painter, option, index):
        from PyQt6.QtGui import QFont, QColor
        painter.save()

        row = index.row()
        cmd   = index.data(Qt.ItemDataRole.UserRole) or ''
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0

        # Background
        if option.state & QStyle.StateFlag.State_Selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor('#1e2030'))
        else:
            bg = '#181825' if row % 2 == 0 else '#141420'
            painter.fillRect(option.rect, QColor(bg))

        x = option.rect.x()
        y = option.rect.y()
        h = option.rect.height()
        w = option.rect.width()

        # Rank badge (left gutter, 26px wide)
        rank_color = self._RANK_COLORS[row] if row < 3 else '#45475a'
        rank_font = QFont('Sans Serif', 7)
        rank_font.setBold(True)
        painter.setFont(rank_font)
        painter.setPen(QColor(rank_color))
        painter.drawText(x + 2, y, 22, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         f'#{row + 1}')

        # Command text
        cmd_font = QFont('Monospace', 9)
        painter.setFont(cmd_font)
        cmd_color = QColor('#89dceb') if (option.state & QStyle.StateFlag.State_Selected or
                                          option.state & QStyle.StateFlag.State_MouseOver) else QColor('#cdd6f4')
        painter.setPen(cmd_color)
        fm = painter.fontMetrics()
        count_str = f'×{count}'
        from PyQt6.QtGui import QFontMetrics
        count_w = QFontMetrics(QFont('Sans Serif', 7)).horizontalAdvance(count_str) + 4
        cmd_x = x + 28
        cmd_w = w - 28 - count_w - 8
        painter.drawText(cmd_x, y, cmd_w, h, Qt.AlignmentFlag.AlignVCenter, fm.elidedText(cmd, Qt.TextElideMode.ElideRight, cmd_w))

        # Usage count (right-aligned)
        count_font = QFont('Sans Serif', 7)
        painter.setFont(count_font)
        painter.setPen(QColor('#585b70'))
        painter.drawText(x + w - count_w - 4, y, count_w + 4, h,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count_str)

        painter.restore()

    def sizeHint(self, option, index):
        from PyQt6.QtCore import QSize
        return QSize(option.rect.width(), 30)



class TerminalWidget(QTextEdit):
    """Terminal widget using pyte for proper VT100/ANSI emulation"""

    send_input       = pyqtSignal(str)
    size_changed     = pyqtSignal(int, int)  # columns, lines
    data_received    = pyqtSignal()          # emitted on each screen render (main thread)
    command_executed = pyqtSignal(str)       # emitted with the command text when Enter is pressed

    def __init__(self, parent=None, columns=120, lines=40):
        super().__init__(parent)
        self.setReadOnly(True)  # Terminal handles all input
        self.font_size = 10  # Default font size
        self.vendor = "Default"  # Default vendor for syntax highlighting
        self.setFont(QFont("Monospace", self.font_size))

        # Track mouse state for selection
        self.mouse_pressed = False

        # Configure line wrap mode to prevent weird selection behavior
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # Set word wrap mode for better text selection
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)

        # Prevent Tab from being used for focus navigation
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTabChangesFocus(False)

        # Initialize pyte terminal emulator with scrollback history
        self.screen = pyte.HistoryScreen(columns, lines, history=5000)
        self.stream = pyte.Stream(self.screen)
        self.stream.use_utf8 = False  # Enable charset switching for DEC Special Graphics (nano, etc.)

        # Lock protecting all pyte state (screen/stream) from concurrent access.
        # The SSH/Telnet worker thread feeds pyte directly; the main thread renders.
        import threading as _threading
        self._pyte_lock = _threading.Lock()

        # Scrollback buffer: pre-rendered HTML lines that scrolled off the top
        self._scrollback_lines = []
        self._scrollback_cache = ""
        self._scrollback_dirty = False
        self._max_scrollback = 5000
        self._render_needed = True  # Dirty flag to avoid redundant setHtml calls
        self._in_scrollback_mode = False  # True when user is browsing history
        self._search_active = False  # True when search is active, freezes display updates
        self._in_alt_screen = False  # True when in alternate screen mode (nano, vim, htop…)
        self._saved_screen_state = None  # Saved buffer+cursor when entering alt screen
        self._line_height_px: float = 0.0  # Exact px line-height to fill viewport with no gaps

        # State for stripping escape sequences not handled by pyte (DCS, SOS, PM, APC)
        self._in_unhandled_escape = False
        self._escape_discard_buffer = ""

        # Debug: capture last 500KB of raw terminal feed for diagnosis
        self._feed_log = []
        self._feed_log_size = 0

        # Refresh timer for rendering
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.render_screen)
        self.refresh_timer.start(50)  # Refresh every 50ms (20 fps for snappier terminal)

        # Viewport size tracker: recalculates PTY dimensions when the widget
        # gets its final layout size (after Qt's layout engine settles).
        # Runs separately from render_screen to avoid clearing pyte's buffer mid-render.
        self._last_vp_size = (0, 0)
        self._vp_check_timer = QTimer()
        self._vp_check_timer.timeout.connect(self._check_viewport_size)
        self._vp_check_timer.start(150)

        # Cursor position (pyte column/row) — written in render_screen (main thread),
        # read in _CursorOverlay.paintEvent (also main thread).
        self._cur_x = 0
        self._cur_y = 0

        # Root-mode: when True the default foreground color is red.
        # Detected by scanning visible screen text for "root@" prompts.
        self._root_mode = False

        # Cursor blink timer — only repaints the overlay, never calls setHtml
        self._cursor_visible = True
        self._blink_timer = QTimer()
        self._blink_timer.timeout.connect(self._on_blink)
        self._blink_timer.start(530)

        self._DBG = False  # set True to enable per-phase timing to stderr

        # Apply terminal styling — padding via setContentsMargins so Qt shrinks
        # the viewport by the exact amount, making _recalculate_size accurate.
        self.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a;
                color: #e0e0e0;
                border: none;
            }
        """)
        self.setContentsMargins(10, 6, 10, 6)
        self.document().setDocumentMargin(0)

        # Cursor overlay — drawn on top of the viewport, updated only on blink
        self._cursor_overlay = _CursorOverlay(self)
        # Resize overlay whenever the viewport resizes
        self.viewport().installEventFilter(self)

        # Detect manual scrollbar drag: if user moves scrollbar away from
        # the bottom, freeze auto-scroll (same effect as scrolling up with wheel).
        self.verticalScrollBar().sliderMoved.connect(self._on_slider_moved)

        # ── Autocomplete state ────────────────────────────────────────────
        self._ac_buffer   = ""    # chars typed since last Enter / Ctrl-C
        self._ac_commands = []    # [(cmd, desc), …] for current vendor
        self._ac_popup    = None  # QFrame overlay, created lazily
        self._ac_sel      = 0     # highlighted row index in popup
        self._ac_pending_buffer = ""   # buffer queued for debounced update
        self._ac_update_timer = QTimer()
        self._ac_update_timer.setSingleShot(True)
        self._ac_update_timer.timeout.connect(self._ac_do_update)

        # ── Render line cache ─────────────────────────────────────────────
        self._render_line_cache: dict[int, str] = {}
        self._render_line_cache_cols = 0

        # ── Syntax highlight compiled regex cache ─────────────────────────
        self._hl_re_cache: dict[str, re.Pattern] | None = None

    def _on_slider_moved(self, value):
        """Called when the user drags the scrollbar manually."""
        if not self._in_scrollback_mode:
            scrollbar = self.verticalScrollBar()
            if value < scrollbar.maximum():
                if self._scrollback_lines:
                    self._enter_scrollback_mode()
                else:
                    self._in_scrollback_mode = True

    def eventFilter(self, obj, event):
        """Resize cursor overlay whenever the viewport is resized."""
        from PyQt6.QtCore import QEvent
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            self._cursor_overlay.setGeometry(self.viewport().rect())
        return super().eventFilter(obj, event)

    def event(self, event):
        """Intercept Tab key before focus handling"""
        if event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Tab:
                self.send_input.emit('\t')
                event.accept()
                return True
        return super().event(event)

    def wheelEvent(self, event):
        """Enter scrollback mode when user scrolls up"""
        if event.angleDelta().y() > 0 and not self._in_scrollback_mode:
            if self._scrollback_lines:
                self._enter_scrollback_mode()
        super().wheelEvent(event)
        # After Qt has moved the scrollbar: if the user actually moved away from
        # the bottom (e.g. current screen is taller than viewport), freeze
        # auto-scroll.  We check *after* super() so we know whether there was
        # anything to scroll to.  Full-screen TUIs like htop fill the viewport
        # exactly (maximum ≈ 0) so the scrollbar never moves and the flag is
        # never set — avoiding the snap-back problem.
        if event.angleDelta().y() > 0 and not self._in_scrollback_mode:
            scrollbar = self.verticalScrollBar()
            if scrollbar.value() < scrollbar.maximum():
                self._in_scrollback_mode = True

    def _enter_scrollback_mode(self):
        """Inject scrollback into document so user can browse history"""
        # Rebuild cache if new history lines arrived since the last rebuild
        if self._scrollback_dirty:
            self._scrollback_cache = '\n'.join(self._scrollback_lines)
            self._scrollback_dirty = False

        with self._pyte_lock:
            screen_lines = []
            for y in range(self.screen.lines):
                screen_lines.append(self._render_line(self.screen.buffer[y], self.screen.columns))

        _lh = f"{self._line_height_px:.4f}px" if self._line_height_px > 0 else "1.0"
        pre_open = f'<pre style="margin: 0; padding: 0; line-height: {_lh}; user-select: text; -webkit-user-select: text;">'
        if self._scrollback_cache:
            full_html = pre_open + self._scrollback_cache + '\n' + '\n'.join(screen_lines) + '</pre>'
        else:
            full_html = pre_open + '\n'.join(screen_lines) + '</pre>'

        self.setUpdatesEnabled(False)
        self.setHtml(full_html)
        self.document().setDocumentMargin(0)
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.setUpdatesEnabled(True)
        self._in_scrollback_mode = True

    def mousePressEvent(self, event):
        """Track mouse press for selection"""
        self.mouse_pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Track mouse release after selection and auto-copy selected text."""
        self.mouse_pressed = False
        super().mouseReleaseEvent(event)
        cursor = self.textCursor()
        if cursor.hasSelection():
            QApplication.clipboard().setText(cursor.selectedText().replace('\u2029', '\n'))
            # Show a brief tooltip near the cursor to confirm the copy
            QToolTip.showText(self.mapToGlobal(event.pos()), 'Copied to clipboard', self, QRect(), 800)

    def contextMenuEvent(self, event):
        """Show right-click context menu with copy, paste and export options"""
        # Pre-fetch clipboard text before showing menu to avoid delay on paste
        clipboard_text = QApplication.clipboard().text()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #585b70;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #45475a;
            }
        """)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(self.textCursor().hasSelection())
        paste_action = menu.addAction("Paste")
        paste_action.setEnabled(bool(clipboard_text))
        menu.addSeparator()
        export_action = menu.addAction("Export to file...")

        action = menu.exec(event.globalPos())
        # Reset mouse_pressed since the release happened over the menu, not the terminal
        self.mouse_pressed = False

        if action == copy_action:
            text = self.textCursor().selectedText()
            if text:
                QApplication.clipboard().setText(text.replace('\u2029', '\n'))
        elif action == paste_action:
            self._paste_clipboard(clipboard_text)
        elif action == export_action:
            self._export_terminal()

    def _paste_clipboard(self, text):
        """Paste clipboard text into the terminal"""
        if text:
            # Convert clipboard line endings to terminal CR
            text = text.replace('\r\n', '\r').replace('\n', '\r')
            # Wrap in bracketed paste markers if the remote side enabled it
            if (2004 << 5) in self.screen.mode:
                text = '\x1b[200~' + text + '\x1b[201~'
            self.send_input.emit(text)

    def _export_terminal(self):
        """Export full terminal content (scrollback + current screen) to a text file"""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Terminal", "", "Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        # Build plain text from scrollback HTML lines
        import re
        tag_re = re.compile(r'<[^>]+>')
        lines = []
        for html_line in self._scrollback_lines:
            plain = tag_re.sub('', html_line)
            plain = plain.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
            lines.append(plain)
        # Append current screen content
        for y in range(self.screen.lines):
            row = self.screen.buffer[y]
            line = ''.join(row[x].data for x in range(self.screen.columns)).rstrip()
            lines.append(line)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press and send to picocom"""
        key = event.key()
        modifiers = event.modifiers()
        text = event.text()

        # Build key sequence to send
        sequence = ""

        # Handle Ctrl+Shift combinations
        if modifiers & Qt.KeyboardModifier.ControlModifier and modifiers & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_V:
                clipboard_text = QApplication.clipboard().text()
                self._paste_clipboard(clipboard_text)
                return
            elif key == Qt.Key.Key_C:
                text_sel = self.textCursor().selectedText()
                if text_sel:
                    QApplication.clipboard().setText(text_sel.replace('\u2029', '\n'))
                return
            elif key == Qt.Key.Key_D:
                self._dump_feed_log()
                return

        # Handle Ctrl combinations
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_F:
                # Focus search input in parent dialog
                dialog = self.parent()
                if hasattr(dialog, 'search_input'):
                    dialog.search_input.setFocus()
                    dialog.search_input.selectAll()
                return
            elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                # Generate control character: Ctrl+A=\x01, Ctrl+O=\x0f, etc.
                sequence = chr(key - Qt.Key.Key_A + 1)

        # Handle special keys
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if self._ac_buffer.strip() and not self._is_password_prompt():
                self.command_executed.emit(self._ac_buffer.strip())
            self._ac_buffer = ""
            self._ac_hide()
            sequence = '\r'
        elif key == Qt.Key.Key_Backspace:
            if self._ac_buffer:
                self._ac_buffer = self._ac_buffer[:-1]
                self._ac_update()
            sequence = '\x7f'
        elif key == Qt.Key.Key_Tab:
            sequence = '\t'
        elif key == Qt.Key.Key_Escape:
            if self._ac_popup and self._ac_popup.isVisible():
                self._ac_hide()
                return          # consume Escape — don't send to device
            sequence = '\x1b'
        elif key == Qt.Key.Key_Up:
            if self._ac_popup and self._ac_popup.isVisible():
                self._ac_navigate(-1)
                return
            sequence = '\x1b[A'
        elif key == Qt.Key.Key_Down:
            if self._ac_popup and self._ac_popup.isVisible():
                self._ac_navigate(1)
                return
            sequence = '\x1b[B'
        elif key == Qt.Key.Key_Right:
            if self._ac_popup and self._ac_popup.isVisible():
                self._ac_commit_sel()
                return
            sequence = '\x1b[C'
        elif key == Qt.Key.Key_Left:
            sequence = '\x1b[D'
        elif key == Qt.Key.Key_Home:
            sequence = '\x1b[H'
        elif key == Qt.Key.Key_End:
            sequence = '\x1b[F'
        elif key == Qt.Key.Key_Delete:
            sequence = '\x1b[3~'
        elif key == Qt.Key.Key_PageUp:
            sequence = '\x1b[5~'
        elif key == Qt.Key.Key_PageDown:
            sequence = '\x1b[6~'
        elif text:
            sequence = text
            # Track printable input for autocomplete (ignore control chars)
            if len(text) == 1 and text.isprintable():
                self._ac_buffer += text
                self._ac_update()

        # Clear / trim buffer on line-editing control sequences
        if sequence == '\x03':          # Ctrl+C — clear line
            self._ac_buffer = ""
            self._ac_hide()
        elif sequence in ('\x15', '\x0b'):  # Ctrl+U (kill line) / Ctrl+K (kill to end)
            self._ac_buffer = ""
            self._ac_hide()
        elif sequence == '\x17':        # Ctrl+W — kill last word
            if ' ' in self._ac_buffer:
                self._ac_buffer = self._ac_buffer.rsplit(' ', 1)[0] + ' '
            else:
                self._ac_buffer = ""
            self._ac_update()

        # Send sequence to picocom/SSH
        if sequence:
            # Exit search mode when user sends input to terminal
            if self._search_active:
                self._search_active = False
                self._in_scrollback_mode = False
                self._render_needed = True
                self.setExtraSelections([])
                dialog = self.parent()
                if hasattr(dialog, 'search_input'):
                    dialog.search_input.clear()
                    dialog.search_status.clear()
                    dialog._search_matches = []
            # Scroll-to-bottom on keystroke (Konsole / GNOME Terminal behaviour):
            # exit scrollback mode so the user can see the response to their input.
            if self._in_scrollback_mode:
                self._in_scrollback_mode = False
                self._render_needed = True
            self.send_input.emit(sequence)

    # Regex to match complete DCS/SOS/PM/APC sequences (not handled by pyte 0.8.x)
    import re as _re
    _UNHANDLED_SEQ_RE = _re.compile(
        r'\x1bP[^\x1b]*(?:\x1b\\|\x07)'    # DCS: ESC P ... ST/BEL
        r'|\x1bX[^\x1b]*(?:\x1b\\|\x07)'   # SOS: ESC X ... ST/BEL
        r'|\x1b\^[^\x1b]*(?:\x1b\\|\x07)'  # PM:  ESC ^ ... ST/BEL
        r'|\x1b_[^\x1b]*(?:\x1b\\|\x07)'   # APC: ESC _ ... ST/BEL
        r'|\$<\d+[/*]?>'                    # terminfo padding ($<N>)
    )

    def _strip_unhandled_sequences(self, text):
        """Strip DCS/SOS/PM/APC sequences that pyte doesn't handle.

        These sequences leak their content as visible text in pyte 0.8.x.
        This also handles sequences split across multiple data chunks.
        """
        import re

        # If we're inside an unfinished sequence from a previous chunk,
        # discard everything until the terminator (ST or BEL)
        if self._in_unhandled_escape:
            match = re.search(r'\x1b\\|\x07', text)
            if match:
                self._in_unhandled_escape = False
                text = text[match.end():]
            else:
                return ''  # Still inside sequence, discard all

        # Prepend any buffered ESC from previous chunk boundary
        if self._escape_discard_buffer:
            text = self._escape_discard_buffer + text
            self._escape_discard_buffer = ""

        # Strip complete sequences in one pass
        text = self._UNHANDLED_SEQ_RE.sub('', text)

        # Check for partial sequence (starter found but no terminator)
        for starter in ('\x1bP', '\x1bX', '\x1b^', '\x1b_'):
            idx = text.find(starter)
            if idx != -1:
                self._in_unhandled_escape = True
                text = text[:idx]
                break

        # Handle lone ESC at the very end (could be start of ESC P/X/^/_)
        if text.endswith('\x1b'):
            self._escape_discard_buffer = '\x1b'
            text = text[:-1]

        return text

    def _on_blink(self):
        """Toggle cursor visibility — only repaints the overlay, never setHtml."""
        self._cursor_visible = not self._cursor_visible
        self._cursor_overlay.update()

    def _save_screen_state(self):
        """Save the current pyte buffer and cursor for alternate screen restore."""
        state = []
        for y in range(self.screen.lines):
            line = []
            for x in range(self.screen.columns):
                line.append(self.screen.buffer[y][x])
            state.append(line)
        return state, (self.screen.cursor.x, self.screen.cursor.y)

    def _restore_screen_state(self, saved):
        """Restore pyte buffer and cursor from a saved state."""
        saved_lines, (cursor_x, cursor_y) = saved
        for y, line in enumerate(saved_lines):
            for x, char in enumerate(line):
                self.screen.buffer[y][x] = char
        self.screen.cursor.x = cursor_x
        self.screen.cursor.y = cursor_y

    def _enter_alt_screen(self):
        """Save current buffer and switch to a clean alternate screen."""
        self._saved_screen_state = self._save_screen_state()
        self._in_alt_screen = True
        # pyte resize() does nothing when dimensions are unchanged,
        # so manually clear every cell to default_char so the TUI
        # starts from a blank slate (OpenCode and many TUIs don't
        # send ESC[2J after ESC[?1049h, they assume the alt screen is
        # already empty).
        for y in range(self.screen.lines):
            line = self.screen.buffer[y]
            for x in range(self.screen.columns):
                line[x] = self.screen.default_char
        # Reset history queues so TUI output doesn't pollute scrollback
        self.screen.history.top.clear()
        self.screen.history.bottom.clear()
        self.screen._reset_history()
        self._scrollback_lines.clear()
        self._scrollback_cache = ""
        self._scrollback_dirty = False
        self._render_line_cache.clear()
        self._render_line_cache_cols = 0

    def _exit_alt_screen(self):
        """Restore the saved buffer and exit alternate screen."""
        self._in_alt_screen = False
        if self._saved_screen_state:
            self._restore_screen_state(self._saved_screen_state)
            self._saved_screen_state = None
        self._render_line_cache.clear()
        self._render_line_cache_cols = 0
        self._render_needed = True

    def _dump_feed_log(self, path="/tmp/cetus_feed_debug.log"):
        """Save the last ~500KB of raw terminal feed for debugging."""
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as f:
                f.write("".join(self._feed_log))
            print(f"[CETUS DEBUG] Feed log saved to {path}")
        except Exception as e:
            print(f"[CETUS DEBUG] Failed to save feed log: {e}")

    def feed_from_worker(self, text):
        """Feed raw SSH/Telnet bytes to pyte — called from worker thread, NOT main thread.

        Strips unhandled escape sequences, acquires the pyte lock, feeds the stream,
        then marks render as needed.  No Qt calls are made here so it is thread-safe.
        """
        import time as _t
        if self._DBG:
            self._dbg_feed_calls += 1
            t0 = _t.perf_counter()

        # Debug: accumulate raw feed for diagnosis
        self._feed_log.append(text)
        self._feed_log_size += len(text)
        MAX_LOG = 500000
        while self._feed_log_size > MAX_LOG and self._feed_log:
            self._feed_log_size -= len(self._feed_log.pop(0))

        text = self._strip_unhandled_sequences(text)

        if self._DBG:
            t1 = _t.perf_counter()
            self._dbg_feed_strip_ms += (t1 - t0) * 1000

        # Detect alternate-screen mode (full-screen TUIs: nano, vim, htop …)
        # ESC[?1049h → enter alt screen   ESC[?1049l → leave alt screen
        # ESC[?1047h → enter alt screen (legacy)  ESC[?1047l → leave alt screen (legacy)
        # ESC[?1048h → save cursor         ESC[?1048l → restore cursor
        if '\x1b[?1049h' in text or '\x1b[?1047h' in text:
            with self._pyte_lock:
                self._enter_alt_screen()
        if '\x1b[?1049l' in text or '\x1b[?1047l' in text:
            with self._pyte_lock:
                self._exit_alt_screen()

        if text:
            # Cap feed size so the lock is held for at most ~90ms per call.
            # pyte is pure-Python (~735 KB/s measured). 64KB ≈ 87ms → still fine
            # for a 20fps render loop. 8KB was too small for TUI frames (OpenCode,
            # htop, vim) which redraw the entire screen and can easily exceed 8KB.
            # When truncated, the ESC[2J / ESC[H at the start of the frame gets
            # lost, causing the new frame to overlay the old one → garbled display.
            MAX_FEED_BYTES = 65536  # 64 KB
            if len(text) > MAX_FEED_BYTES:
                text = text[-MAX_FEED_BYTES:]
                # TUI apps redraw using cursor positioning, not newlines.
                # Align to the first frame-start marker in the truncated chunk.
                # The old 1024-byte window was too small for large frames.
                aligned = False
                for _marker in ('\x1b[2J', '\x1b[H', '\x1b[1;1H', '\x1b[?1049h', '\x1b[?1047h'):
                    _idx = text.find(_marker)
                    if _idx >= 0:
                        text = text[_idx:]
                        aligned = True
                        break
                if not aligned:
                    nl = text.find('\n')  # fallback: align to line boundary
                    if nl >= 0:
                        text = text[nl + 1:]

            if self._DBG:
                self._dbg_feed_bytes += len(text)  # bytes actually fed to pyte (after cap)
                t2 = _t.perf_counter()
            with self._pyte_lock:
                self.stream.feed(text)
            if self._DBG:
                self._dbg_feed_pyte_ms += (_t.perf_counter() - t2) * 1000
            self._render_needed = True  # bool write is atomic under CPython GIL

        if self._DBG:
            self._dbg_report_if_due(_t.perf_counter())

    def append_output(self, text):
        """Feed text to pyte terminal emulator (main-thread path, e.g. local echo)."""
        text = self._strip_unhandled_sequences(text)
        if text:
            if '\x1b[?1049h' in text or '\x1b[?1047h' in text:
                with self._pyte_lock:
                    self._enter_alt_screen()
            if '\x1b[?1049l' in text or '\x1b[?1047l' in text:
                with self._pyte_lock:
                    self._exit_alt_screen()
            with self._pyte_lock:
                self.stream.feed(text)
            self._render_needed = True

    def set_vendor(self, vendor):
        """Set the vendor for syntax highlighting and pre-compile regexes."""
        self.vendor = vendor
        self._render_line_cache.clear()
        self._render_line_cache_cols = 0
        keywords = self.get_vendor_keywords()
        if keywords:
            # Pre-compile one big alternation for all keywords (~10x faster than 150 separate re.sub)
            keyword_pattern = r'\b(' + '|'.join(re.escape(kw) for kw in keywords) + r')\b'
            self._hl_re_cache = {
                'keywords': re.compile(keyword_pattern, re.IGNORECASE),
                'ip': re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b'),
                'mac': re.compile(r'\b([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}|[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})\b'),
                'number': re.compile(r'(?<![\d\x5C.])\b(\d+)\b(?![\d\x5C.])'),
                'prompt': re.compile(r'^([\[<]?[A-Za-z0-9_-]+[\]>]?(?:[#]|&gt;))', re.MULTILINE),
            }
        else:
            self._hl_re_cache = None

    # ── Autocomplete ──────────────────────────────────────────────────────────

    def set_autocomplete_commands(self, cmd_list):
        """Replace the command list used for autocomplete.

        cmd_list: iterable of (command_string, description_string) tuples.
        """
        self._ac_commands = list(cmd_list)
        self._ac_hide()
        self._ac_buffer = ""

    def _ac_create_popup(self):
        """Create the floating autocomplete popup (called once, lazily)."""
        from PyQt6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QLabel
        popup = QFrame(self.viewport())
        popup.setWindowFlags(Qt.WindowType.Widget)
        popup.setStyleSheet("""
            QFrame {
                background: #1e2030;
                border: 1px solid #444860;
                border-radius: 6px;
            }
            QListWidget {
                background: transparent;
                border: none;
                color: #cdd6f4;
                font-family: Monospace;
                font-size: 9pt;
                outline: none;
            }
            QListWidget::item {
                padding: 3px 10px;
            }
            QListWidget::item:selected {
                background: #363a4f;
                color: #89dceb;
            }
            QScrollBar:vertical {
                background: #1e2030;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #444860;
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6e7194;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0px; }
        """)
        vbox = QVBoxLayout(popup)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        lst = QListWidget()
        lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lst.setItemDelegate(_AcItemDelegate(lst))
        lst.itemClicked.connect(lambda item: self._ac_commit_item(item))
        vbox.addWidget(lst)
        hint = QLabel("  → Tab/Enter complete   ↑↓ navigate   Esc close")
        hint.setStyleSheet("""
            QLabel {
                background: #161622;
                color: #6e7194;
                font-size: 8pt;
                padding: 2px 6px;
                border-top: 1px solid #444860;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }
        """)
        hint.setFixedHeight(18)
        vbox.addWidget(hint)
        popup.hide()
        self._ac_popup = popup
        self._ac_list  = lst
        self._ac_hint  = hint

    def _ac_update(self):
        """Debounce wrapper: schedule actual popup rebuild after typing pauses."""
        self._ac_pending_buffer = self._ac_buffer
        if self._ac_update_timer.isActive():
            self._ac_update_timer.stop()
        if not self._ac_commands or not self._ac_buffer:
            self._ac_hide()
            return
        self._ac_update_timer.start(80)  # 80 ms debounce

    def _ac_do_update(self):
        """Recompute matching commands and refresh the popup (called by timer)."""
        buffer = self._ac_pending_buffer
        if not self._ac_commands or not buffer:
            self._ac_hide()
            return

        needle = buffer.lower()
        matches = [(cmd, desc) for cmd, desc in self._ac_commands
                   if cmd.lower().startswith(needle)][:30]

        if not matches:
            self._ac_hide()
            return

        if self._ac_popup is None:
            self._ac_create_popup()

        from PyQt6.QtWidgets import QListWidgetItem
        self._ac_list.clear()
        for cmd, desc in matches:
            item = QListWidgetItem()
            item.setText(cmd)   # used by delegate as fallback / accessibility
            item.setData(Qt.ItemDataRole.UserRole, cmd)
            item.setData(Qt.ItemDataRole.UserRole + 1, desc)
            self._ac_list.addItem(item)

        row_h    = 22
        hint_h   = 18
        max_vis  = 8
        visible  = min(len(matches), max_vis)
        pop_w    = min(900, max(400, max(len(cmd) * 8 + len(desc) * 7 + 40 for cmd, desc in matches)))
        list_h   = visible * row_h + 4
        pop_h    = list_h + hint_h

        # Position just above the bottom-right of the viewport
        vp = self.viewport()
        x  = vp.width() - pop_w - 10
        y  = vp.height() - pop_h - 26   # ~26px above the bottom line
        if y < 4:
            y = 4

        # Update hint text: show total count when there are more than visible
        total = len(matches)
        if total > max_vis:
            hint_text = f"  → Tab/Enter complete   ↑↓ navigate   Esc close   ({total} results)"
        else:
            hint_text = "  → Tab/Enter complete   ↑↓ navigate   Esc close"
        if hasattr(self, '_ac_hint'):
            self._ac_hint.setText(hint_text)

        self._ac_popup.setFixedSize(pop_w, pop_h)
        self._ac_list.setFixedHeight(list_h)
        self._ac_popup.move(x, y)
        self._ac_popup.show()
        self._ac_popup.raise_()
        self._ac_popup.update()

        # Restore / clamp selection
        self._ac_sel = max(0, min(self._ac_sel, self._ac_list.count() - 1))
        self._ac_list.setCurrentRow(self._ac_sel)
        self._ac_list.scrollToItem(self._ac_list.currentItem())

    def _ac_navigate(self, delta):
        """Move selection up (-1) or down (+1) in the popup."""
        if self._ac_popup is None or not self._ac_popup.isVisible():
            return
        count = self._ac_list.count()
        if count == 0:
            return
        self._ac_sel = (self._ac_sel + delta) % count
        self._ac_list.setCurrentRow(self._ac_sel)

    def _ac_commit_sel(self):
        """Commit the currently selected popup item."""
        if self._ac_popup is None or not self._ac_popup.isVisible():
            return
        item = self._ac_list.currentItem()
        if item:
            self._ac_commit_item(item)

    def _ac_commit_item(self, item):
        """Replace typed buffer with the chosen command and send to terminal."""
        cmd = item.data(Qt.ItemDataRole.UserRole)
        if cmd is None:
            return
        # Erase what the user typed so far
        backspaces = '\x7f' * len(self._ac_buffer)
        if backspaces:
            self.send_input.emit(backspaces)
        # Send the full command
        self.send_input.emit(cmd)
        self._ac_buffer = cmd
        self._ac_hide()

    def _ac_hide(self):
        """Hide the autocomplete popup and cancel any pending debounced update."""
        if self._ac_update_timer.isActive():
            self._ac_update_timer.stop()
        if self._ac_popup and self._ac_popup.isVisible():
            self._ac_popup.hide()
        self._ac_sel = 0

    _PASSWORD_PROMPT_RE = re.compile(
        r'(password|passwd|passphrase|contraseña|senha|pin|secret'
        r'|enter.*pass|retype|confirm.*pass'
        r'|\[sudo\]'
        r'|authentication required'
        r'|new.*password|current.*password'
        r'|private key)',
        re.IGNORECASE,
    )

    def _is_password_prompt(self):
        """Return True if the current terminal line looks like a password prompt.

        Checks the visible line at the cursor row and the line immediately
        above it, covering multi-line prompts like sudo's '[sudo] password for user:'.
        """
        try:
            with self._pyte_lock:
                rows_to_check = {self.screen.cursor.y}
                if self.screen.cursor.y > 0:
                    rows_to_check.add(self.screen.cursor.y - 1)
                for row in rows_to_check:
                    line = self.screen.buffer.get(row, {})
                    text = ''.join(c.data for c in line.values())
                    if self._PASSWORD_PROMPT_RE.search(text):
                        return True
        except Exception:
            pass
        return False

    # ─────────────────────────────────────────────────────────────────────────

    def get_vendor_keywords(self):
        """Get keywords specific to the selected vendor"""
        # Common keywords for all vendors
        common = ['vlan', 'ip', 'ipv6', 'address', 'shutdown', 'route', 'static',
                  'permit', 'deny', 'any', 'host', 'password', 'secret', 'description',
                  'protocol', 'snmp', 'community', 'version', 'dhcp', 'server', 'pool',
                  'gateway', 'dns', 'lease', 'ntp', 'authentication', 'key', 'logging']

        # Cisco IOS/IOS-XE specific
        cisco = common + [
            'interface', 'no', 'router', 'bgp', 'ospf', 'eigrp', 'rip', 'isis',
            'access-list', 'line', 'vty', 'console', 'enable', 'service', 'hostname',
            'banner', 'switchport', 'mode', 'trunk', 'access', 'native', 'allowed',
            'spanning-tree', 'portfast', 'bpduguard', 'channel-group', 'lacp', 'pagp',
            'ssh', 'telnet', 'http', 'https', 'aaa', 'radius', 'tacacs',
            'port-security', 'maximum', 'violation', 'sticky', 'aging', 'time',
            'show', 'running-config', 'startup-config', 'brief', 'status', 'summary',
            'detail', 'controllers', 'inventory', 'copy', 'write', 'erase', 'reload',
            'configure', 'terminal', 'end', 'exit', 'crypto', 'isakmp', 'ipsec'
        ]

        # Huawei VRP specific
        huawei = common + [
            'display', 'system-view', 'quit', 'return', 'save', 'undo', 'sysname',
            'interface', 'user-interface', 'authentication-mode', 'aaa', 'local-user',
            'privilege', 'level', 'acl', 'rule', 'source', 'destination', 'basic',
            'advanced', 'mac-address', 'port-isolate', 'eth-trunk', 'mode', 'lacp',
            'stp', 'bpdu', 'edged-port', 'ssh', 'telnet', 'client', 'server',
            'cipher', 'hmac', 'exchange', 'dh-exchange', 'header', 'dot1x', 'vlan',
            'batch', 'port', 'hybrid', 'trunk', 'access', 'voice-vlan', 'qinq',
            'current-configuration', 'saved-configuration', 'startup', 'next'
        ]

        # H3C Comware specific
        h3c = common + [
            'display', 'system-view', 'quit', 'return', 'save', 'undo', 'sysname',
            'interface', 'user-interface', 'authentication-mode', 'local-user',
            'authorization-mode', 'accounting-mode', 'acl', 'rule', 'basic', 'advanced',
            'link-aggregation', 'lacp', 'stp', 'bpdu-protection', 'edge-port',
            'ssh', 'telnet', 'server', 'port-security', 'mac-address', 'port',
            'hybrid', 'trunk', 'access', 'voice', 'current-configuration', 'lldp'
        ]

        # Juniper Junos specific
        juniper = common + [
            'set', 'delete', 'show', 'commit', 'rollback', 'configure', 'edit',
            'top', 'up', 'interfaces', 'protocols', 'routing-options', 'firewall',
            'security', 'zones', 'policies', 'nat', 'chassis', 'system', 'services'
        ]

        # TP-Link TL-SG series (IOS-like CLI)
        tplink = common + [
            'interface', 'vlan', 'no', 'show', 'end', 'exit', 'hostname', 'description',
            'switchport', 'general', 'allowed', 'tagged', 'untagged', 'pvid',
            'gigabitEthernet', 'tengigabitEthernet', 'port-channel',
            'ip', 'address', 'address-alloc', 'dhcp', 'route',
            'spanning-tree', 'mode', 'rstp', 'mstp', 'stp', 'max-hops', 'priority',
            'snmp-server', 'community', 'read-only', 'read-write', 'viewDefault',
            'system-time', 'ntp', 'dst', 'jumbo-size',
            'user', 'name', 'privilege', 'admin', 'secret',
            'serial_port', 'baud_rate', 'write', 'save', 'copy',
            'running-config', 'startup-config', 'tftp', 'firmware',
            'port-security', 'mac-address', 'storm-control', 'broadcast',
            'lacp', 'link-aggregation', 'lldp', 'cdp',
            'logging', 'trap', 'enable', 'disable', 'ipv6',
        ]

        # D-Link specific
        dlink = common + [
            'create', 'delete', 'config', 'show', 'enable', 'disable', 'vlan',
            'ports', 'stp', 'igmp', 'snmp', 'fdb', 'address_binding', 'vlanname',
            'link_aggregation', 'group', 'master', 'member', 'lacp', 'state',
            'traffic_control', 'broadcast', 'multicast', 'unicast', 'action',
            'access_profile', 'access_list', 'packet_content_mask', 'profile_id',
            'bpdu_tunnel', 'tunnel_mac', 'loopdetect', 'recover_timer', 'interval',
            'safeguard_engine', 'rising_threshold', 'falling_threshold', 'mode',
            'download', 'upload', 'save', 'reboot', 'reset', 'factory_default',
            'ip_source_guard', 'verify_source', 'trust', 'max_dynamic_hosts',
            'traffic_segmentation', 'forward_list', 'block', 'mirror', 'session',
            'source', 'destination', 'port_mirror', 'flow_mirror', 'cpu_filter'
        ]

        # Brocade Fabric OS specific
        brocade = common + [
            'switchshow', 'switchname', 'switchdisable', 'switchenable', 'configshow',
            'configupload', 'configdownload', 'configdefault', 'fabricshow',
            'portshow', 'portcfgshow', 'portdisable', 'portenable', 'portname',
            'portcfgpersistentdisable', 'portcfgpersistentenable', 'switchportshow',
            'aliacreate', 'aliadd', 'aliremove', 'alidelete', 'alishow',
            'zonecreate', 'zoneadd', 'zoneremove', 'zonedelete', 'zoneshow',
            'cfgcreate', 'cfgadd', 'cfgremove', 'cfgdelete', 'cfgshow', 'cfgenable',
            'cfgdisable', 'cfgsave', 'cfgclear', 'defzone', 'nozoning',
            'firmwareshow', 'firmwaredownload', 'firmwaredownloadstatus', 'version',
            'licenseshow', 'licenseadd', 'licenseremove', 'licenseport',
            'ipaddrset', 'ipaddrshow', 'nsshow', 'nsallshow', 'nscamshow',
            'reboot', 'fastboot', 'hashow', 'failover', 'setcontext',
            'tsclockserver', 'tstimezone', 'date', 'uptime', 'diagshow', 'supportshow'
        ]

        # Datacom specific (Brazilian manufacturer)
        datacom = common + [
            'show', 'configure', 'interface', 'vlan', 'no', 'router', 'bgp', 'ospf',
            'eigrp', 'rip', 'access-list', 'line', 'vty', 'console', 'enable',
            'service', 'hostname', 'banner', 'switchport', 'mode', 'trunk', 'access',
            'spanning-tree', 'portfast', 'port-channel', 'lacp', 'etherchannel',
            'ssh', 'telnet', 'http', 'snmp-server', 'ntp', 'clock', 'timezone',
            'aaa', 'radius', 'tacacs', 'local-user', 'privilege', 'level',
            'qos', 'class-map', 'policy-map', 'service-policy', 'trust', 'dscp',
            'write', 'memory', 'reload', 'copy', 'running-config', 'startup-config',
            'erase', 'boot', 'system', 'flash', 'tftp', 'ftp', 'upload', 'download',
            'mac', 'mac-address-table', 'aging-time', 'storm-control', 'broadcast',
            'errdisable', 'recovery', 'cause', 'interval', 'speed', 'duplex', 'mtu',
            'description', 'default-gateway', 'ip-address', 'subnet-mask', 'vrf'
        ]

        # Fortinet FortiOS specific (Firewall)
        fortinet = common + [
            'config', 'end', 'next', 'edit', 'delete', 'show', 'get', 'set', 'unset',
            'execute', 'diagnose', 'purge', 'rename', 'clone', 'append', 'clear',
            'system', 'global', 'interface', 'admin', 'settings', 'ha', 'dns',
            'firewall', 'policy', 'address', 'addrgrp', 'service', 'custom',
            'schedule', 'recurring', 'onetime', 'ippool', 'vip', 'central-snat',
            'router', 'static', 'bgp', 'ospf', 'rip', 'multicast', 'policy-route',
            'vpn', 'ipsec', 'phase1-interface', 'phase2-interface', 'ssl',
            'ssl-web-portal', 'tunnel-mode', 'web-mode', 'certificate', 'local',
            'user', 'local', 'radius', 'ldap', 'group', 'peer', 'peergrp',
            'antivirus', 'profile', 'webfilter', 'ips', 'sensor', 'application',
            'list', 'control', 'emailfilter', 'dlp', 'filefilter', 'voip',
            'waf', 'profile', 'signature', 'protocol-options', 'ssh-filter',
            'log', 'fortianalyzer', 'forticloud', 'syslogd', 'memory', 'disk',
            'backup', 'restore', 'reboot', 'shutdown', 'factoryreset', 'revision',
            'debug', 'flow', 'trace', 'sniffer', 'packet', 'top', 'performance',
            'status', 'arp', 'session', 'route', 'neighbor', 'hardware', 'nic'
        ]

        # Aruba (ArubaOS / ArubaOS-CX)
        aruba = common + [
            'show', 'configure', 'terminal', 'interface', 'vlan', 'no', 'router', 'bgp',
            'ospf', 'rip', 'access-list', 'line', 'vty', 'console', 'enable',
            'hostname', 'banner', 'switchport', 'mode', 'trunk', 'access',
            'spanning-tree', 'port-channel', 'lacp',
            'aaa', 'radius-server', 'tacacs-server', 'local-user', 'group',
            'wlan', 'ssid-profile', 'ap-group', 'ap-name', 'virtual-controller',
            'cluster', 'controller-ip', 'master-redundancy',
            'firewall', 'policy', 'user-role', 'captive-portal', 'web-server',
            'crypto', 'pki', 'certificate', 'isakmp',
            'aruba-central', 'mobility-controller', 'mobility-master',
            'stacking', 'member', 'vsf',
            'write', 'memory', 'reload', 'copy', 'running-config', 'startup-config',
            'backup', 'restore', 'flash', 'tftp', 'ftp', 'boot',
            'logging', 'trap', 'buffered', 'facility',
            'speed', 'duplex', 'mtu', 'lldp', 'cdp',
            'qos', 'trust', 'dscp', 'queue', 'scheduler-policy',
            'debug', 'monitor', 'session', 'destination',
            'vrf', 'default-gateway', 'management', 'oobm'
        ]

        # Linux - bash commands and common utilities
        linux = [
            'ls', 'cd', 'pwd', 'mkdir', 'rmdir', 'rm', 'cp', 'mv', 'touch', 'cat',
            'less', 'more', 'head', 'tail', 'grep', 'find', 'locate', 'which', 'whereis',
            'chmod', 'chown', 'chgrp', 'umask', 'ln', 'file', 'stat', 'du', 'df',
            'tar', 'gzip', 'gunzip', 'bzip2', 'bunzip2', 'zip', 'unzip', 'xz',
            'ps', 'top', 'htop', 'kill', 'killall', 'pkill', 'bg', 'fg', 'jobs',
            'systemctl', 'service', 'journalctl', 'dmesg', 'uname', 'hostname',
            'ifconfig', 'ip', 'route', 'netstat', 'ss', 'ping', 'traceroute', 'dig',
            'nslookup', 'host', 'curl', 'wget', 'ssh', 'scp', 'rsync', 'ftp', 'sftp',
            'nmap', 'nc', 'netcat', 'tcpdump', 'wireshark', 'tshark',
            'apt', 'apt-get', 'dpkg', 'yum', 'dnf', 'rpm', 'pacman', 'zypper',
            'flatpak', 'snap', 'snapd',
            'podman', 'buildah', 'skopeo',
            'sudo', 'su', 'useradd', 'userdel', 'usermod', 'groupadd', 'groupdel',
            'adduser', 'deluser', 'passwd', 'gpasswd', 'chpasswd',
            'who', 'w', 'last', 'id', 'groups', 'finger', 'whoami',
            'echo', 'printf', 'read', 'export', 'env', 'set', 'unset', 'alias',
            'history', 'source', 'exec', 'exit', 'logout', 'clear', 'reset',
            'man', 'info', 'help', 'apropos', 'whatis', 'type', 'command',
            'mount', 'umount', 'fdisk', 'mkfs', 'fsck', 'lsblk', 'blkid',
            'cron', 'crontab', 'at', 'batch', 'sleep', 'watch', 'time', 'date',
            'awk', 'sed', 'cut', 'sort', 'uniq', 'wc', 'tr', 'tee', 'xargs',
            'vim', 'nano', 'emacs', 'vi', 'gedit', 'pico',
            'make', 'gcc', 'g++', 'python', 'python3', 'perl', 'ruby', 'node',
            'git', 'svn', 'docker', 'kubectl', 'systemd', 'init', 'uptime', 'free'
        ]

        # MikroTik RouterOS
        mikrotik = common + [
            'interface', 'bridge', 'ether', 'wlan', 'vlan', 'bonding', 'vrrp', 'gre',
            'eoip', 'ipip', 'ovpn-client', 'ovpn-server', 'l2tp-client', 'l2tp-server',
            'pptp-client', 'pptp-server', 'pppoe-client', 'pppoe-server', 'sstp-client',
            'wireless', 'security-profiles', 'registration-table', 'access-list',
            'address', 'firewall', 'filter', 'nat', 'mangle', 'raw', 'connection-tracking',
            'route', 'routing', 'bgp', 'ospf', 'rip', 'mpls', 'vpls',
            'queue', 'simple', 'tree', 'type',
            'system', 'identity', 'clock', 'scheduler', 'script', 'resource', 'routerboard',
            'user', 'group', 'aaa', 'radius',
            'tool', 'bandwidth-test', 'flood-ping', 'netwatch', 'torch', 'sniffer',
            'profile', 'traceroute', 'ping', 'fetch', 'email',
            'export', 'import', 'backup', 'restore', 'reset-configuration',
            'print', 'set', 'add', 'remove', 'enable', 'disable', 'move', 'find', 'get',
            'where', 'detail', 'brief', 'terse', 'count-only', 'follow',
            'log', 'action', 'topic',
            'certificate', 'crl', 'scep',
            'dhcp-client', 'dhcp-server', 'lease', 'network', 'pool',
            'dns', 'static', 'cache',
            'neighbor', 'discovery', 'lldp', 'cdp', 'mndp',
            'snmp', 'community', 'trap',
            'port', 'serial-console', 'console',
            'upgrade', 'package', 'reboot'
        ]

        # Windows - PowerShell and CMD commands
        windows = [
            'Get-', 'Set-', 'New-', 'Remove-', 'Start-', 'Stop-', 'Restart-', 'Test-',
            'Get-Process', 'Get-Service', 'Get-EventLog', 'Get-NetIPAddress', 'Get-NetRoute',
            'Get-NetAdapter', 'Get-NetFirewallRule', 'Get-WmiObject', 'Get-ChildItem',
            'Set-ExecutionPolicy', 'Set-NetIPAddress', 'Set-Service', 'Set-NetFirewallRule',
            'New-NetIPAddress', 'New-NetRoute', 'New-LocalUser', 'New-Item', 'New-SmbShare',
            'Remove-Item', 'Remove-NetRoute', 'Remove-LocalUser',
            'Invoke-Command', 'Enter-PSSession', 'Exit-PSSession',
            'Import-Module', 'Export-Csv', 'Out-File', 'Select-Object', 'Where-Object',
            'ForEach-Object', 'Sort-Object', 'Measure-Object', 'Format-Table', 'Format-List',
            'ipconfig', 'ping', 'tracert', 'netstat', 'nslookup', 'pathping', 'route',
            'net', 'netsh', 'arp', 'hostname', 'systeminfo', 'tasklist', 'taskkill',
            'sc', 'reg', 'regedit', 'sfc', 'chkdsk', 'diskpart', 'format', 'xcopy', 'robocopy',
            'dir', 'cd', 'md', 'rd', 'del', 'copy', 'move', 'ren', 'type', 'cls', 'echo',
            'shutdown', 'restart', 'logoff', 'runas', 'gpupdate', 'gpresult', 'wmic',
            'powershell', 'cmd', 'mstsc', 'mmc', 'eventvwr', 'perfmon', 'msconfig',
            'winrm', 'winscp', 'certmgr', 'certlm', 'netplwiz', 'lusrmgr',
            'firewall', 'defender', 'antivirus', 'windows', 'update', 'service', 'driver',
        ]

        # FreeBSD - shell and system commands
        freebsd = [
            'ls', 'cd', 'pwd', 'mkdir', 'rmdir', 'rm', 'cp', 'mv', 'touch', 'cat',
            'less', 'more', 'head', 'tail', 'grep', 'find', 'which', 'whereis', 'locate',
            'chmod', 'chown', 'chgrp', 'ln', 'file', 'stat', 'du', 'df',
            'tar', 'gzip', 'gunzip', 'bzip2', 'bunzip2', 'xz', 'zstd',
            'ps', 'top', 'htop', 'kill', 'killall', 'pkill', 'bg', 'fg', 'jobs',
            'service', 'sysrc', 'rc-update', 'dmesg', 'uname', 'hostname', 'sysctl',
            'ifconfig', 'route', 'netstat', 'sockstat', 'ping', 'traceroute', 'dig',
            'nslookup', 'host', 'curl', 'wget', 'fetch', 'ssh', 'scp', 'rsync', 'ftp', 'sftp',
            'pkg', 'pkg install', 'pkg remove', 'pkg update', 'pkg upgrade', 'pkg search',
            'pkg info', 'pkg audit', 'ports', 'make', 'make install', 'make clean',
            'portsnap', 'freebsd-update', 'bsdinstall',
            'sudo', 'su', 'pw', 'pw useradd', 'pw userdel', 'pw usermod', 'pw groupadd',
            'passwd', 'who', 'w', 'last', 'id', 'groups',
            'echo', 'printf', 'read', 'export', 'env', 'set', 'unset', 'alias',
            'history', 'source', 'exec', 'exit', 'logout', 'clear', 'reset',
            'man', 'info', 'apropos', 'whatis',
            'mount', 'umount', 'fdisk', 'gpart', 'newfs', 'fsck', 'camcontrol', 'geom',
            'zfs', 'zpool', 'zfs create', 'zfs destroy', 'zfs snapshot', 'zfs rollback',
            'zpool create', 'zpool destroy', 'zpool status', 'zpool scrub',
            'glabel', 'gmirror', 'gstripe', 'gconcat',
            'pf', 'pfctl', 'ipfw', 'natd', 'ppp', 'mpd5',
            'cron', 'crontab', 'at', 'sleep', 'watch', 'time', 'date',
            'awk', 'sed', 'cut', 'sort', 'uniq', 'wc', 'tr', 'tee', 'xargs',
            'vim', 'nano', 'ee', 'vi',
            'jail', 'jls', 'jexec', 'ezjail', 'iocage', 'bastille',
            'truss', 'ktrace', 'kdump', 'dtrace', 'pmcstat',
            'bhyve', 'bhyvectl', 'bhyveload', 'vm-bhyve',
            'kldload', 'kldunload', 'kldstat', 'loader', 'boot',
            'pciconf', 'usbconfig', 'devinfo', 'devd',
        ]

        # Default - no highlighting (empty list)
        default = []

        vendor_keywords = {
            'Default': default,
            'Linux': linux,
            'Windows': windows,
            'FreeBSD': freebsd,
            'Cisco': cisco,
            'Huawei': huawei,
            'H3C': h3c,
            'Juniper': juniper,
            'D-Link': dlink,
            'TP-Link': tplink,
            'Brocade': brocade,
            'Datacom': datacom,
            'Fortinet': fortinet,
            'Aruba': aruba,
            'MikroTik': mikrotik
        }

        return vendor_keywords.get(self.vendor, default)

    def insert_cursor_at_position(self, html_text, raw_text, cursor_pos):
        """Insert cursor highlight at specific position in HTML text"""
        import re

        # If cursor is beyond text length, add it at the end
        if cursor_pos >= len(raw_text):
            return html_text + '<span style="color: #0a0a0a; background-color: #e0e0e0;">█</span>'

        # Build a map of raw text positions to HTML positions
        # We need to find where in the HTML the cursor_pos character appears
        raw_idx = 0
        html_idx = 0
        in_tag = False

        while html_idx < len(html_text) and raw_idx < len(raw_text):
            if html_text[html_idx] == '<':
                in_tag = True
                html_idx += 1
            elif html_text[html_idx] == '>':
                in_tag = False
                html_idx += 1
            elif in_tag:
                html_idx += 1
            else:
                # Check for HTML entities
                if html_text[html_idx:html_idx+5] == '&amp;':
                    if raw_idx == cursor_pos:
                        # Insert cursor here
                        return (html_text[:html_idx] +
                               '<span style="color: #0a0a0a; background-color: #e0e0e0;">&amp;</span>' +
                               html_text[html_idx+5:])
                    raw_idx += 1
                    html_idx += 5
                elif html_text[html_idx:html_idx+4] == '&lt;':
                    if raw_idx == cursor_pos:
                        return (html_text[:html_idx] +
                               '<span style="color: #0a0a0a; background-color: #e0e0e0;">&lt;</span>' +
                               html_text[html_idx+4:])
                    raw_idx += 1
                    html_idx += 4
                elif html_text[html_idx:html_idx+4] == '&gt;':
                    if raw_idx == cursor_pos:
                        return (html_text[:html_idx] +
                               '<span style="color: #0a0a0a; background-color: #e0e0e0;">&gt;</span>' +
                               html_text[html_idx+4:])
                    raw_idx += 1
                    html_idx += 4
                else:
                    if raw_idx == cursor_pos:
                        # Insert cursor here
                        char = html_text[html_idx]
                        if char == ' ':
                            char = '&nbsp;'
                        return (html_text[:html_idx] +
                               f'<span style="color: #0a0a0a; background-color: #e0e0e0;">{char}</span>' +
                               html_text[html_idx+1:])
                    raw_idx += 1
                    html_idx += 1

        return html_text

    def apply_syntax_highlighting(self, text):
        """Apply syntax highlighting for network equipment commands.
        Uses pre-compiled regexes from _hl_re_cache when available."""

        # Don't highlight if text is empty or whitespace
        if not text.strip():
            return text

        # Escape HTML
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        cache = self._hl_re_cache
        if cache:
            text = cache['keywords'].sub(r'<span style="color: #00ffff; font-weight: bold;">\1</span>', text)
            text = cache['ip'].sub(r'<span style="color: #00ff00; font-weight: bold;">\1</span>', text)
            text = cache['mac'].sub(r'<span style="color: #00ff88; font-weight: bold;">\1</span>', text)
            text = cache['number'].sub(r'<span style="color: #ffff00;">\1</span>', text)
            text = cache['prompt'].sub(r'<span style="color: #ff00ff; font-weight: bold;">\1</span>', text)
        else:
            # Fallback (Default vendor — no keyword highlighting)
            import re
            text = re.sub(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b',
                          r'<span style="color: #00ff00; font-weight: bold;">\1</span>', text)
            text = re.sub(r'\b([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}|[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})\b',
                          r'<span style="color: #00ff88; font-weight: bold;">\1</span>', text)
            text = re.sub(r'(?<![\d\.])\b(\d+)\b(?![\d\.])',
                          r'<span style="color: #ffff00;">\1</span>', text)
            text = re.sub(r'^([\[<]?[A-Za-z0-9_-]+[\]>]?(?:[#]|&gt;))',
                          r'<span style="color: #ff00ff; font-weight: bold;">\1</span>', text, flags=re.MULTILINE)

        return text

    def get_ansi_color(self, color, is_background=False, bold=False):
        """Convert pyte color to HTML color code.

        Pyte stores colors as:
          - str 'default'            → terminal default fg/bg
          - str named  e.g. 'red'   → basic 8 + bright ANSI names
          - str 6-char hex e.g. 'ff0000' → 256-color AND 24-bit true-color
          - int                      → legacy fallback (older pyte versions)
        """
        # xterm-compatible 16-color palette
        ansi_colors = {
            'black':         '#000000',
            'red':           '#cd0000',
            'green':         '#00cd00',
            'brown':         '#cdcd00',   # dark yellow
            'blue':          '#0000ee',
            'magenta':       '#cd00cd',
            'cyan':          '#00cdcd',
            'white':         '#e5e5e5',
            # Bright / high-intensity (AIXTERM 90-97 / 100-107)
            'brightblack':   '#7f7f7f',
            'brightred':     '#ff0000',
            'brightgreen':   '#00ff00',
            'brightyellow':  '#ffff00',
            'brightbrown':   '#ffff00',   # pyte names bright-yellow as brightbrown
            'brightblue':    '#5c5cff',
            'brightmagenta': '#ff00ff',
            'bfightmagenta': '#ff00ff',   # pyte typo in BG_AIXTERM
            'brightcyan':    '#00ffff',
            'brightwhite':   '#ffffff',
        }

        default_fg = '#ff4444' if getattr(self, '_root_mode', False) else '#e0e0e0'
        default_bg = 'transparent'

        if color == 'default':
            # Bold + default fg → bright white (matches VTE 'intense colors' default)
            if bold and not is_background:
                return '#ffffff'
            return default_bg if is_background else default_fg

        if isinstance(color, str):
            # 6-char hex string: pyte stores 256-color AND 24-bit true-color this way
            # e.g. 'ff0000' (red), '1e90ff' (dodger blue), '87afff' (256-color)
            if len(color) == 6:
                try:
                    int(color, 16)
                    return f'#{color}'
                except ValueError:
                    pass
            # Bold-is-bright: VTE/Konsole default — bold + basic named color → bright variant.
            # Only applies to foreground (background colors are never brightened).
            if bold and not is_background:
                color = {
                    'black': 'brightblack', 'red': 'brightred', 'green': 'brightgreen',
                    'brown': 'brightyellow', 'blue': 'brightblue',
                    'magenta': 'brightmagenta', 'cyan': 'brightcyan', 'white': 'brightwhite',
                }.get(color, color)
            return ansi_colors.get(color, default_bg if is_background else default_fg)

        # Integer fallback for older pyte versions
        if isinstance(color, int):
            if color < 16:
                color_names = ['black', 'red', 'green', 'brown', 'blue', 'magenta', 'cyan', 'white',
                               'brightblack', 'brightred', 'brightgreen', 'brightyellow',
                               'brightblue', 'brightmagenta', 'brightcyan', 'brightwhite']
                return ansi_colors.get(color_names[color], default_bg if is_background else default_fg)
            elif color < 232:
                color -= 16
                r = (color // 36) * 51
                g = ((color % 36) // 6) * 51
                b = (color % 6) * 51
                return f'#{r:02x}{g:02x}{b:02x}'
            else:
                gray = 8 + (color - 232) * 10
                return f'#{gray:02x}{gray:02x}{gray:02x}'

        return default_bg if is_background else default_fg

    def _render_line(self, line_buffer, columns, cursor_x=None):
        """Render a single line (from screen buffer or history) to an HTML string.

        Args:
            line_buffer: dict-like mapping column index to pyte Char objects
            columns: number of columns to render
            cursor_x: if not None, draw cursor block at this column
        """
        raw_line = ""
        has_ansi_colors = False
        fp_parts = []  # for line-cache fingerprint

        for x in range(columns):
            char = line_buffer[x]
            raw_line += char.data
            if char.fg != 'default' or char.bg != 'default' or char.bold or char.italics or char.underscore or char.reverse:
                has_ansi_colors = True
            fp_parts.append((char.data, char.fg, char.bg, char.bold, char.italics, char.underscore, char.reverse))

        fingerprint = tuple(fp_parts)
        if self._render_line_cache_cols == columns and fingerprint in self._render_line_cache:
            return self._render_line_cache[fingerprint]

        if has_ansi_colors:
            line = ""
            x = 0
            while x < columns:
                char = line_buffer[x]

                fg_color = self.get_ansi_color(char.fg, is_background=False, bold=char.bold)
                bg_color = self.get_ansi_color(char.bg, is_background=True)

                styles = [f'color: {fg_color}']
                if bg_color != 'transparent':
                    styles.append(f'background-color: {bg_color}')
                if char.bold:
                    styles.append('font-weight: bold')
                if char.italics:
                    styles.append('font-style: italic')
                if char.underscore:
                    styles.append('text-decoration: underline')
                if char.reverse:
                    styles = [f'color: {bg_color if bg_color != "transparent" else "#0a0a0a"}',
                             f'background-color: {fg_color}']

                is_cursor = (cursor_x is not None and x == cursor_x)

                if is_cursor:
                    char_data = char.data
                    if char_data == ' ' or char_data == '':
                        char_data = '█'
                        styles = ['color: #e0e0e0', 'background-color: transparent']
                    else:
                        char_data = char_data.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        styles = ['color: #0a0a0a', 'background-color: #e0e0e0']
                    style_str = '; '.join(styles)
                    line += f'<span style="{style_str}">{char_data}</span>'
                    x += 1
                else:
                    style_str = '; '.join(styles)
                    group_text = ""

                    while x < columns:
                        if cursor_x is not None and x == cursor_x:
                            break

                        next_char = line_buffer[x]
                        next_fg = self.get_ansi_color(next_char.fg, is_background=False, bold=next_char.bold)
                        next_bg = self.get_ansi_color(next_char.bg, is_background=True)

                        next_styles = [f'color: {next_fg}']
                        if next_bg != 'transparent':
                            next_styles.append(f'background-color: {next_bg}')
                        if next_char.bold:
                            next_styles.append('font-weight: bold')
                        if next_char.italics:
                            next_styles.append('font-style: italic')
                        if next_char.underscore:
                            next_styles.append('text-decoration: underline')
                        if next_char.reverse:
                            next_styles = [f'color: {next_bg if next_bg != "transparent" else "#0a0a0a"}',
                                         f'background-color: {next_fg}']

                        next_style_str = '; '.join(next_styles)

                        if next_style_str != style_str:
                            break

                        char_text = next_char.data.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        if char_text == ' ':
                            char_text = '&nbsp;'
                        group_text += char_text
                        x += 1

                    if group_text:
                        line += f'<span style="{style_str}">{group_text}</span>'
            self._render_line_cache[fingerprint] = line
            self._render_line_cache_cols = columns
            return line
        else:
            if self.vendor == "Default":
                # No highlighting — show original terminal text as-is
                highlighted_line = raw_line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            else:
                highlighted_line = self.apply_syntax_highlighting(raw_line)
            if cursor_x is not None:
                highlighted_line = self.insert_cursor_at_position(highlighted_line, raw_line, cursor_x)
            self._render_line_cache[fingerprint] = highlighted_line
            self._render_line_cache_cols = columns
            return highlighted_line

    def render_screen(self):
        """Render pyte screen buffer to QTextEdit with ANSI color support and syntax highlighting"""
        # Don't update if user is selecting text or mouse is pressed
        if self.textCursor().hasSelection() or self.mouse_pressed:
            return

        import time as _t
        _t_render_start = _t.perf_counter() if self._DBG else 0

        # ── pyte state access under lock ──────────────────────────────────────
        # Non-blocking: if the worker is currently feeding pyte, skip this render
        # cycle instead of blocking the Qt event loop. The timer fires again in 100ms.
        if not self._pyte_lock.acquire(blocking=False):
            return
        screen_lines = None
        try:
            _t_locked = _t.perf_counter() if self._DBG else 0

            # Drain history lines with a strict time budget (5ms).
            # _render_line costs ~0.4ms/line, so ≈12 lines per tick at 10fps.
            # A line-count cap (80) caused 33ms drain time even when idle.
            # Skip draining while in alternate screen: TUI apps (nano, vim) do
            # not produce scrollback and the history.top may contain stale lines.
            if not self._in_alt_screen:
                DRAIN_BUDGET_S = 0.005  # 5ms budget per render tick
                _t_drain_start = _t.perf_counter()
                while self.screen.history.top:
                    if _t.perf_counter() - _t_drain_start >= DRAIN_BUDGET_S:
                        break
                    history_line = self.screen.history.top.popleft()
                    rendered = self._render_line(history_line, self.screen.columns)
                    self._scrollback_lines.append(rendered)
                    self._scrollback_dirty = True
                    # Do NOT set _render_needed here: history drain only updates the
                    # scrollback buffer, not the visible screen. Setting it caused
                    # spurious setHtml calls every 100ms even when the terminal was idle.

            _t_history_done = _t.perf_counter() if self._DBG else 0

            # Trim scrollback if it exceeds max
            if len(self._scrollback_lines) > self._max_scrollback:
                self._scrollback_lines = self._scrollback_lines[-self._max_scrollback:]
                self._scrollback_dirty = True

            # Rebuild scrollback cache only when the user is viewing it or searching
            if self._scrollback_dirty and (self._in_scrollback_mode or self._search_active):
                self._scrollback_cache = '\n'.join(self._scrollback_lines)
                self._scrollback_dirty = False

            # Freeze display while search is active
            if self._search_active:
                if self._DBG:
                    self._dbg_render_skipped += 1
                return

            # In scrollback mode: exit only when the scrollbar is at the very
            # bottom (value >= maximum).  The old <= 10 threshold caused false
            # exits for full-screen TUIs (htop) whose scrollbar.maximum() is
            # only a few pixels due to font-rounding.
            if self._in_scrollback_mode:
                scrollbar = self.verticalScrollBar()
                if scrollbar.value() >= scrollbar.maximum():
                    self._in_scrollback_mode = False
                    self._render_needed = True
                else:
                    if self._DBG:
                        self._dbg_render_skipped += 1
                    return  # Frozen while browsing history

            # Nothing changed since last render — skip setHtml entirely
            if not self._render_needed:
                if self._DBG:
                    self._dbg_render_skipped += 1
                return
            self._render_needed = False

            # Render current screen under lock — cursor is drawn by the overlay,
            # not embedded in HTML, so _render_line never receives cursor_x here.
            cursor_x = self.screen.cursor.x
            cursor_y = self.screen.cursor.y

            # Detect root session by checking only the cursor line and the line
            # immediately above it (the active prompt area). Scanning the entire
            # screen would cause false positives from historical root@ output
            # that is still visible after exiting root.
            _prompt_text = ''
            _scan_cols = min(120, self.screen.columns)
            for _chk_y in range(max(0, cursor_y - 1), min(self.screen.lines, cursor_y + 1)):
                _lb = self.screen.buffer[_chk_y]
                for _x in range(_scan_cols):
                    _prompt_text += _lb[_x].data
                _prompt_text += '\n'
            _has_root_prompt    = 'root@' in _prompt_text
            _has_any_user_prompt = bool(re.search(r'\w+@\w', _prompt_text))
            if _has_root_prompt:
                _new_root = True
            elif _has_any_user_prompt:
                # Non-root user@host prompt visible → exit root mode
                _new_root = False
            else:
                # No user@host prompt (e.g., interactive question / SSH auth)
                # — keep current state to avoid flickering
                _new_root = self._root_mode
            if _new_root != self._root_mode:
                self._root_mode = _new_root
                self._render_needed = True
                self._render_line_cache.clear()
                self._render_line_cache_cols = 0

            screen_lines = []
            for y in range(self.screen.lines):
                screen_lines.append(self._render_line(self.screen.buffer[y], self.screen.columns))

            _t_lines_done = _t.perf_counter() if self._DBG else 0
        finally:
            self._pyte_lock.release()
        # ── lock released — Qt calls below are main-thread only ───────────────
        if screen_lines is None:
            return

        # Update widget stylesheet if root mode changed since last render
        if getattr(self, '_applied_root_mode', None) != self._root_mode:
            fg = '#ff4444' if self._root_mode else '#e0e0e0'
            self.setStyleSheet(f"""
                QTextEdit {{
                    background-color: #0a0a0a;
                    color: {fg};
                    border: none;
                }}
            """)
            self._applied_root_mode = self._root_mode

        _lh = f"{self._line_height_px:.4f}px" if self._line_height_px > 0 else "1.0"
        _fg = '#ff4444' if self._root_mode else '#e0e0e0'
        pre_open = f'<pre style="margin: 0; padding: 0; color: {_fg}; line-height: {_lh}; user-select: text; -webkit-user-select: text;">'
        new_html = pre_open + '\n'.join(screen_lines) + '</pre>'

        self.setUpdatesEnabled(False)
        self.setHtml(new_html)
        self.document().setDocumentMargin(0)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)

        # Scroll to follow output.
        # • Alternate screen (nano, vim, htop …): always show from the top — the TUI
        #   owns the full viewport and positions its own cursor.
        # • After `clear` (cursor_y == 0): scroll to top to avoid sub-pixel rounding
        #   pushing line 0 just above the visible area.
        # • Normal live output: scroll to bottom so new lines stay visible.
        scrollbar = self.verticalScrollBar()
        if self._in_alt_screen or cursor_y == 0:
            scrollbar.setValue(0)
        else:
            scrollbar.setValue(scrollbar.maximum())

        # Update cursor overlay position and trigger its repaint
        self._cur_x = cursor_x
        self._cur_y = cursor_y
        self._cursor_overlay.setGeometry(self.viewport().rect())
        self._cursor_overlay.raise_()
        self._cursor_overlay.update()

        self.setUpdatesEnabled(True)
        self.data_received.emit()

        if self._DBG:
            _now = _t.perf_counter()
            self._dbg_render_calls += 1
            self._dbg_render_history_ms += (_t_history_done - _t_locked) * 1000
            self._dbg_render_lines_ms  += (_t_lines_done  - _t_history_done) * 1000
            self._dbg_render_sethtml_ms += (_now - _t_lines_done) * 1000
            self._dbg_render_total_ms  += (_now - _t_render_start) * 1000
            self._dbg_report_if_due(_now)

    def resizeEvent(self, event):
        """Recalculate terminal dimensions when widget is resized"""
        super().resizeEvent(event)
        # Skip resize recalculation when updates are disabled (triggered by setHtml)
        if not self.updatesEnabled():
            return
        self._recalculate_size()
        # Reposition autocomplete popup if it is open
        if self._ac_popup and self._ac_popup.isVisible():
            self._ac_update()

    def _check_viewport_size(self):
        """Periodically check if the viewport size changed and recalculate PTY dimensions if so.
        Runs on a separate timer from render_screen to avoid interfering with the pyte buffer."""
        vp = self.viewport()
        cur = (vp.width(), vp.height())
        if cur != self._last_vp_size and cur[0] > 0 and cur[1] > 0:
            self._last_vp_size = cur
            self._recalculate_size()

    def _recalculate_size(self):
        """Calculate columns and lines from widget size and font metrics, then resize pyte screen"""
        from PyQt6.QtGui import QFontMetricsF
        fm = QFontMetricsF(self.font())
        char_width = fm.averageCharWidth()
        char_height = fm.height()
        if char_width <= 0 or char_height <= 0:
            return
        # Margins are handled via setContentsMargins (shrinks the viewport) and
        # documentMargin=0 (set after every setHtml). The viewport dimensions are
        # therefore the exact usable text area — no further subtraction needed.
        viewport = self.viewport()
        available_width = viewport.width()
        available_height = viewport.height()
        cols = max(40, int(available_width / char_width))
        # Qt's HTML renderer interprets CSS `line-height: 1.2` as
        # fm.height() * 1.2, where fm.height() = ascent + descent (the full
        # bounding-box height of the font, NOT the CSS pt→px conversion).
        # Using css_font_px = pointSizeF * dpi / 72 gave ~16px where the
        # real rendered line height was ~19.2px, causing row overflows.
        line_height = char_height * 1.2
        rows = max(10, int(available_height / line_height))
        # Store the exact px height that divides the viewport evenly into `rows`
        # so the HTML CSS can use it and leave no unused gap at the bottom.
        self._line_height_px = available_height / rows
        with self._pyte_lock:
            if cols != self.screen.columns or rows != self.screen.lines:
                self.screen.resize(rows, cols)
                self._render_needed = True
        if self._render_needed:
            self.size_changed.emit(cols, rows)

    def _dbg_report_if_due(self, now):
        """Print accumulated timing stats to stderr every 2 seconds."""
        import sys
        elapsed = now - self._dbg_t0
        if elapsed < 2.0:
            return
        rc = self._dbg_render_calls or 1
        fc = self._dbg_feed_calls or 1
        print(
            f"\n[TERM DBG] ── {elapsed:.1f}s window ──────────────────────────────\n"
            f"  feed_from_worker : {self._dbg_feed_calls} calls, "
            f"{self._dbg_feed_bytes/1024:.1f} KB total\n"
            f"    strip_seq      : {self._dbg_feed_strip_ms/fc:.2f} ms/call avg "
            f"({self._dbg_feed_strip_ms:.1f} ms total)\n"
            f"    pyte.feed()    : {self._dbg_feed_pyte_ms/fc:.2f} ms/call avg "
            f"({self._dbg_feed_pyte_ms:.1f} ms total)\n"
            f"  render_screen    : {self._dbg_render_calls} rendered, "
            f"{self._dbg_render_skipped} skipped\n"
            f"    history drain  : {self._dbg_render_history_ms/rc:.2f} ms/render avg\n"
            f"    _render_line×N : {self._dbg_render_lines_ms/rc:.2f} ms/render avg\n"
            f"    setHtml+cursor : {self._dbg_render_sethtml_ms/rc:.2f} ms/render avg\n"
            f"    total          : {self._dbg_render_total_ms/rc:.2f} ms/render avg "
            f"({self._dbg_render_total_ms:.0f} ms total)\n"
            f"──────────────────────────────────────────────────────────────────",
            file=sys.stderr, flush=True
        )
        # Reset accumulators
        self._dbg_t0 = now
        self._dbg_feed_calls = self._dbg_feed_bytes = 0
        self._dbg_feed_strip_ms = self._dbg_feed_pyte_ms = 0.0
        self._dbg_render_calls = self._dbg_render_skipped = 0
        self._dbg_render_history_ms = self._dbg_render_lines_ms = 0.0
        self._dbg_render_sethtml_ms = self._dbg_render_total_ms = 0.0

    def increase_font_size(self):
        """Increase terminal font size"""
        if self.font_size < 24:  # Maximum font size limit
            self.font_size += 1
            self.setFont(QFont("Monospace", self.font_size))
            self._recalculate_size()

    def decrease_font_size(self):
        """Decrease terminal font size"""
        if self.font_size > 6:  # Minimum font size limit
            self.font_size -= 1
            self.setFont(QFont("Monospace", self.font_size))
            self._recalculate_size()






















class _DisconnectOverlay(QWidget):
    """Semi-transparent overlay shown over the terminal when the session ends."""

    reconnect_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setStyleSheet(
            "background-color: rgba(18, 18, 18, 230);"
            " border-radius: 14px;"
            " border: 1px solid #333333;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 24, 36, 24)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("⊘")
        icon_lbl.setStyleSheet("color: #e53935; font-size: 40pt; background: transparent; border: none;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        msg_lbl = QLabel("Session terminated")
        msg_lbl.setStyleSheet("color: #e0e0e0; font-size: 13pt; font-weight: bold; background: transparent; border: none;")
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        close_btn = QPushButton("Close tab")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #c0c0c0;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 10pt;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #222222; }
        """)
        close_btn.clicked.connect(self._on_close)

        card_layout.addWidget(icon_lbl)
        card_layout.addWidget(msg_lbl)
        card_layout.addSpacing(4)
        card_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        outer.addWidget(card)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        painter.end()

    def _on_close(self):
        # Close the parent TerminalDialog tab
        parent = self.parent()
        if parent:
            parent.close()



class TerminalDialog(QWidget):
    """Widget containing the embedded terminal (lives inside TerminalTabbedWindow tabs
    or, when detached, inside a DetachedTerminalWindow)."""

    # Signal for thread-safe terminal output
    ssh_output_received = pyqtSignal(str)
    # Emitted when the terminal is actually closed (accepted close event)
    terminal_closed = pyqtSignal()
    # Emitted when the remote session closes unexpectedly (not user-initiated)
    session_disconnected = pyqtSignal()

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Cetus Terminal")
        self.setMinimumSize(400, 300)
        self.banner_color = None   # assigned by TerminalTabbedWindow.add_terminal
        self.process = None
        self.sudo_process = None
        self.config = config
        # SSH-related attributes
        self.ssh_client = None
        self.ssh_channel = None
        self.ssh_read_thread = None
        self.ssh_running = False
        # Telnet-related attributes
        self.telnet_client = None
        self.telnet_read_thread = None
        self.telnet_running = False
        # Serial (pyserial) attributes for Windows
        self.serial_conn = None
        self.serial_read_thread = None
        self.serial_running = False
        self.connection_type = 'serial'
        self._note_name = ''       # profile name of current device
        self._note_ip   = ''       # IP of current device
        self._sticky_note_dlg = None  # open StickyNoteDialog instance (if any)

        self.init_ui()

        # Connect SSH output signal to terminal
        self.ssh_output_received.connect(self._on_ssh_output)

    def resizeEvent(self, event):
        """Recalculate PTY size whenever the widget is resized (e.g. tab area changes)."""
        super().resizeEvent(event)
        QTimer.singleShot(0, self.terminal._recalculate_size)
        if hasattr(self, '_disconnect_overlay') and self._disconnect_overlay.isVisible():
            self._disconnect_overlay.resize(self.terminal.size())
            self._disconnect_overlay.move(self.terminal.pos())

    def showEvent(self, event):
        """Recalculate PTY size when this tab becomes visible."""
        super().showEvent(event)
        QTimer.singleShot(0, self.terminal._recalculate_size)
        QTimer.singleShot(300, self.terminal._recalculate_size)

    def get_icon_path(self, icon_name, subdir='icons'):
        """Get the path to an icon for different installation types"""
        # Check for PyInstaller / PyOxidizer / cx_Freeze bundle
        if getattr(sys, '_MEIPASS', None):
            bundle_path = os.path.join(sys._MEIPASS, f'assets/{subdir}/{icon_name}')
            if os.path.exists(bundle_path):
                return bundle_path
        # Check for Flatpak
        flatpak_path = f'/app/share/io.github.benjamimgois.cetus/{subdir}/{icon_name}'
        if os.path.exists(flatpak_path):
            return flatpak_path
        # Check for AppImage
        if os.environ.get('APPDIR'):
            appdir = os.environ.get('APPDIR')
            appimage_path = os.path.join(appdir, f'usr/share/cetus/{subdir}/{icon_name}')
            if os.path.exists(appimage_path):
                return appimage_path
        # Local/development assets (prioritized over system install)
        assets_path = os.path.join(os.path.dirname(__file__), f'assets/{subdir}/{icon_name}')
        if os.path.exists(assets_path):
            return assets_path
        # Check for system installation (AUR, Debian, etc.)
        system_path = f'/usr/share/cetus/{subdir}/{icon_name}'
        if os.path.exists(system_path):
            return system_path
        # Try root directory (legacy)
        root_path = os.path.join(os.path.dirname(__file__), icon_name)
        if os.path.exists(root_path):
            return root_path
        return None

    def set_connection_status(self, user='', host='', color='#4caf50', connected=True, name=''):
        """Update the status bar to reflect the current connection state."""
        if connected:
            self._conn_dot.setStyleSheet(f"color: {color}; font-size: 9pt; background: transparent;")
            label = f"{user}@{host}" if user and host else (host or "Conectado")
            self._conn_label.setText(label)
            self._conn_label.setStyleSheet("color: #c8c8c8; font-size: 8pt; background: transparent;")
            self._session_start_time = time.monotonic()
            self._note_name = name or host
            self._note_ip   = host
            if self._sticky_note_dlg and self._sticky_note_dlg.isVisible():
                self._sticky_note_dlg.set_device_info(self._note_name, self._note_ip)
        else:
            self._conn_dot.setStyleSheet("color: #e53935; font-size: 9pt; background: transparent;")
            self._conn_label.setText("Session terminated")
            self._conn_label.setStyleSheet("color: #888888; font-size: 8pt; background: transparent;")
            self._session_start_time = None
            self._session_timer_label.setText("")

    def _update_session_timer(self):
        """Tick the session duration counter in the status bar."""
        if self._session_start_time is not None:
            elapsed = int(time.monotonic() - self._session_start_time)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self._session_timer_label.setText(
                f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            )

    def _on_session_ended(self):
        """Called via session_disconnected signal — update status and show overlay."""
        self.set_connection_status(connected=False)
        self._disconnect_overlay.resize(self.terminal.size())
        self._disconnect_overlay.move(self.terminal.pos())
        self._disconnect_overlay.show()
        self._disconnect_overlay.raise_()

    def get_arrow_icon_path(self):
        """Get the path to arrow_down.svg"""
        return self.get_icon_path('arrow_down.svg') or ''

    def get_vendor_icon_path(self, vendor):
        """Get the path to vendor icon SVG"""
        vendor_file = vendor.lower().replace(' ', '') + '.svg'
        path = self.get_icon_path(vendor_file, 'vendors')
        if path:
            return path
        # Fallback to default
        return self.get_icon_path('default.svg', 'vendors') or ''

    @staticmethod
    def get_vendor_reference():
        """Get structured vendor command reference for the quick reference guide."""
        return {
            'Cisco': {
                'Navigation': [
                    ('enable', 'Enter privileged EXEC mode'),
                    ('configure terminal', 'Enter global configuration mode'),
                    ('exit', 'Exit current mode / go back one level'),
                    ('end', 'Return to privileged EXEC mode'),
                ],
                'Show Commands': [
                    ('show running-config', 'Display current active configuration'),
                    ('show startup-config', 'Display saved configuration'),
                    ('show ip interface brief', 'Quick overview of interfaces and IPs'),
                    ('show interfaces', 'Detailed interface statistics'),
                    ('show interfaces <iface> status', 'Show port status and speed'),
                    ('show vlan brief', 'Display VLAN summary table'),
                    ('show vlan id <id>', 'Show specific VLAN details'),
                    ('show ip route', 'Display IP routing table'),
                    ('show ip route summary', 'Routing table summary by protocol'),
                    ('show mac address-table', 'Display MAC address table'),
                    ('show mac address-table vlan <id>', 'MAC table filtered by VLAN'),
                    ('show version', 'System hardware and software information'),
                    ('show cdp neighbors', 'Display directly connected Cisco devices'),
                    ('show cdp neighbors detail', 'CDP neighbors with IPs and platform'),
                    ('show spanning-tree', 'Display STP status'),
                    ('show spanning-tree vlan <id>', 'STP status for specific VLAN'),
                    ('show ip arp', 'Display ARP table'),
                    ('show ip dhcp binding', 'Display active DHCP leases'),
                    ('show ip dhcp pool', 'Display DHCP pool configuration'),
                    ('show ip dhcp conflict', 'Show IP addresses with DHCP conflicts'),
                    ('show access-lists', 'Display all ACLs'),
                    ('show ip access-lists <name>', 'Display specific IP ACL'),
                    ('show etherchannel summary', 'Show LACP/PAgP port-channel summary'),
                    ('show etherchannel <id> detail', 'Detailed port-channel information'),
                    ('show ip vrf', 'List all configured VRFs'),
                    ('show ip vrf interfaces', 'Show interfaces assigned to VRFs'),
                    ('show ip route vrf <name>', 'Display routing table for a VRF'),
                    ('show logging', 'Display system log buffer'),
                    ('show clock', 'Show system date and time'),
                ],
                'Interfaces': [
                    ('interface GigabitEthernet0/1', 'Enter interface config mode'),
                    ('interface range GigabitEthernet0/1 - 10', 'Enter config mode for range of interfaces'),
                    ('ip address <ip> <mask>', 'Assign IP address to interface'),
                    ('no shutdown', 'Enable the interface'),
                    ('shutdown', 'Disable the interface'),
                    ('switchport mode access', 'Set port as access mode'),
                    ('switchport mode trunk', 'Set port as trunk mode'),
                    ('switchport access vlan <id>', 'Assign access VLAN'),
                    ('switchport trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('switchport nonegotiate', 'Disable DTP negotiation'),
                    ('spanning-tree portfast', 'Enable PortFast on access port'),
                    ('spanning-tree bpduguard enable', 'Enable BPDU Guard on port'),
                    ('ip helper-address <ip>', 'Forward DHCP broadcasts to server'),
                    ('description <text>', 'Set interface description'),
                ],
                'VLANs': [
                    ('vlan <id>', 'Create or enter VLAN configuration'),
                    ('name <vlan-name>', 'Assign a name to the VLAN'),
                    ('switchport trunk allowed vlan <ids>', 'Set allowed VLANs on trunk'),
                    ('switchport trunk allowed vlan add <id>', 'Add VLAN to trunk allowed list'),
                    ('switchport trunk allowed vlan remove <id>', 'Remove VLAN from trunk allowed list'),
                    ('show vlan brief', 'Display VLAN summary table'),
                ],
                'ACLs': [
                    ('ip access-list standard <name>', 'Create named standard ACL'),
                    ('ip access-list extended <name>', 'Create named extended ACL'),
                    ('permit ip <src> <wildcard> <dst> <wildcard>', 'Permit IP traffic (extended ACL)'),
                    ('deny ip <src> <wildcard> <dst> <wildcard>', 'Deny IP traffic (extended ACL)'),
                    ('permit tcp <src> <wc> <dst> <wc> eq <port>', 'Permit TCP to specific port'),
                    ('deny icmp any any', 'Deny all ICMP traffic'),
                    ('permit any', 'Permit all (standard ACL)'),
                    ('ip access-group <name> in', 'Apply ACL inbound on interface'),
                    ('ip access-group <name> out', 'Apply ACL outbound on interface'),
                    ('show access-lists', 'Display all configured ACLs with hit counts'),
                    ('show ip access-lists <name>', 'Display specific IP ACL'),
                    ('no ip access-list extended <name>', 'Delete a named ACL'),
                ],
                'DHCP': [
                    ('ip dhcp pool <name>', 'Create DHCP pool'),
                    ('network <net> <mask>', 'Define pool network (inside pool config)'),
                    ('default-router <ip>', 'Set default gateway for DHCP clients'),
                    ('dns-server <ip1> <ip2>', 'Set DNS servers for DHCP clients'),
                    ('lease <days> <hours> <minutes>', 'Set DHCP lease duration'),
                    ('ip dhcp excluded-address <start> <end>', 'Exclude IP range from DHCP pool'),
                    ('ip dhcp relay information trust-all', 'Trust DHCP relay agent info'),
                    ('show ip dhcp binding', 'Display active DHCP leases'),
                    ('show ip dhcp pool', 'Display DHCP pool details'),
                    ('show ip dhcp conflict', 'Show conflicting DHCP addresses'),
                    ('clear ip dhcp binding *', 'Clear all DHCP bindings'),
                    ('no ip dhcp pool <name>', 'Delete DHCP pool'),
                ],
                'LACP / EtherChannel': [
                    ('interface port-channel <id>', 'Create port-channel interface'),
                    ('interface GigabitEthernet0/1', 'Enter member interface'),
                    ('channel-group <id> mode active', 'Add to LACP port-channel (active)'),
                    ('channel-group <id> mode passive', 'Add to LACP port-channel (passive)'),
                    ('channel-group <id> mode on', 'Add to static EtherChannel (no negotiation)'),
                    ('channel-protocol lacp', 'Force LACP protocol on port-channel'),
                    ('lacp port-priority <0-65535>', 'Set LACP port priority (lower = preferred)'),
                    ('lacp system-priority <0-65535>', 'Set LACP system priority'),
                    ('show etherchannel summary', 'Display port-channel summary and state'),
                    ('show etherchannel <id> detail', 'Detailed info for a specific port-channel'),
                    ('show lacp neighbor', 'Show LACP neighbor information'),
                    ('show lacp internal', 'Show local LACP parameters'),
                ],
                'VRF': [
                    ('ip vrf <name>', 'Create VRF (legacy syntax)'),
                    ('vrf definition <name>', 'Create VRF (modern syntax)'),
                    ('rd <asn>:<id>', 'Set route distinguisher (inside VRF config)'),
                    ('route-target export <rt>', 'Set export route-target'),
                    ('route-target import <rt>', 'Set import route-target'),
                    ('interface <iface>', 'Enter interface'),
                    ('ip vrf forwarding <name>', 'Assign interface to VRF (legacy)'),
                    ('vrf forwarding <name>', 'Assign interface to VRF (modern)'),
                    ('ip address <ip> <mask>', 'Assign IP (must re-enter after VRF assignment)'),
                    ('ip route vrf <name> <net> <mask> <gw>', 'Add static route in VRF'),
                    ('show ip vrf', 'List all VRFs'),
                    ('show ip route vrf <name>', 'Display routing table for VRF'),
                    ('ping vrf <name> <ip>', 'Ping within a specific VRF'),
                ],
                'VRRP': [
                    ('interface <iface>', 'Enter interface for VRRP config'),
                    ('vrrp <group> ip <virtual-ip>', 'Set virtual IP for VRRP group'),
                    ('vrrp <group> priority <0-255>', 'Set VRRP priority (default 100; higher = master)'),
                    ('vrrp <group> preempt', 'Enable preemption (default enabled)'),
                    ('vrrp <group> preempt delay minimum <sec>', 'Set preempt delay in seconds'),
                    ('vrrp <group> timers advertise <sec>', 'Set advertisement interval (default 1s)'),
                    ('vrrp <group> authentication text <key>', 'Set plain-text VRRP authentication'),
                    ('vrrp <group> track <object> decrement <val>', 'Track object and decrement priority'),
                    ('vrrp <group> description <text>', 'Set VRRP group description'),
                    ('show vrrp', 'Display all VRRP groups and states'),
                    ('show vrrp brief', 'VRRP summary (master/backup state per interface)'),
                    ('show vrrp interface <iface>', 'VRRP details for specific interface'),
                    ('debug vrrp all', 'Enable full VRRP debug output'),
                ],
                'Routing': [
                    ('ip route <net> <mask> <next-hop>', 'Add static route'),
                    ('router ospf <id>', 'Enable OSPF routing process'),
                    ('router bgp <asn>', 'Enable BGP routing process'),
                    ('network <net> <wildcard> area <id>', 'Advertise network in OSPF'),
                ],
                'Spanning-Tree': [
                    ('spanning-tree mode rapid-pvst', 'Enable Rapid PVST+ (per-VLAN RSTP)'),
                    ('spanning-tree mode mst', 'Enable MST (802.1s)'),
                    ('spanning-tree vlan <id> priority <0-61440>', 'Set STP priority for VLAN'),
                    ('spanning-tree vlan <id> root primary', 'Set switch as root for VLAN (priority 24576)'),
                    ('spanning-tree vlan <id> root secondary', 'Set switch as secondary root (priority 28672)'),
                    ('spanning-tree portfast', 'Enable PortFast on access port'),
                    ('spanning-tree portfast default', 'Enable PortFast on all access ports'),
                    ('spanning-tree bpduguard enable', 'Enable BPDU Guard on port'),
                    ('spanning-tree bpdufilter enable', 'Enable BPDU Filter on port'),
                    ('spanning-tree guard root', 'Enable Root Guard on port'),
                    ('spanning-tree guard loop', 'Enable Loop Guard on port'),
                    ('spanning-tree link-type point-to-point', 'Set link type for faster convergence'),
                    ('spanning-tree cost <1-200000000>', 'Set STP port cost manually'),
                    ('spanning-tree vlan <id> cost <cost>', 'Set STP cost for specific VLAN'),
                    ('show spanning-tree', 'Display STP status for all VLANs'),
                    ('show spanning-tree vlan <id>', 'STP status for specific VLAN'),
                    ('show spanning-tree summary', 'STP summary and mode'),
                    ('show spanning-tree detail', 'Detailed STP information'),
                    ('show spanning-tree interface <iface>', 'STP status for specific interface'),
                    ('show spanning-tree interface <iface> detail', 'Detailed STP port info'),
                    ('show spanning-tree mst configuration', 'Display MST region configuration'),
                    ('show spanning-tree mst <id> detail', 'Detailed MST instance info'),
                    ('show spanning-tree inconsistentports', 'Show ports in inconsistent STP state'),
                    ('show spanning-tree blockedports', 'Show all blocked ports by STP'),
                    ('clear spanning-tree counters', 'Reset STP counters'),
                ],
                'Debug': [
                    ('debug ip icmp', 'Debug ICMP packets'),
                    ('debug ip ospf hello', 'Debug OSPF hello packets'),
                    ('debug ip ospf adj', 'Debug OSPF adjacency events'),
                    ('debug ip bgp updates', 'Debug BGP update messages'),
                    ('debug all', 'Enable all debug output (dangerous — high CPU)'),
                    ('undebug all', 'Disable all debug output'),
                    ('terminal monitor', 'Enable console logging for debug messages'),
                    ('show debugging', 'Display active debug flags'),
                ],
                'Log': [
                    ('logging console', 'Enable logging to console'),
                    ('logging buffered <size>', 'Set local log buffer size'),
                    ('logging <ip>', 'Send logs to remote syslog server'),
                    ('logging trap <level>', 'Set syslog severity level (0-7)'),
                    ('service timestamps log datetime', 'Add timestamps to log messages'),
                    ('show logging', 'Display system log buffer'),
                    ('clear logging', 'Clear the logging buffer'),
                ],
                'LLDP': [
                    ('lldp run', 'Enable LLDP globally'),
                    ('lldp transmit', 'Enable LLDP transmission on port'),
                    ('lldp receive', 'Enable LLDP reception on port'),
                    ('show lldp neighbors', 'Display LLDP neighbors'),
                    ('show lldp neighbors detail', 'Detailed LLDP neighbor information'),
                    ('show lldp interface', 'LLDP status per interface'),
                ],
                'DHCP Server': [
                    ('ip dhcp pool <name>', 'Create DHCP pool'),
                    ('network <net> <mask>', 'Define pool network (inside pool config)'),
                    ('default-router <ip>', 'Set default gateway for DHCP clients'),
                    ('dns-server <ip1> <ip2>', 'Set DNS servers for DHCP clients'),
                    ('lease <days> <hours> <minutes>', 'Set DHCP lease duration'),
                    ('ip dhcp excluded-address <start> <end>', 'Exclude IP range from DHCP pool'),
                    ('show ip dhcp binding', 'Display active DHCP leases'),
                    ('show ip dhcp pool', 'Display DHCP pool configuration'),
                    ('clear ip dhcp binding *', 'Clear all DHCP bindings'),
                ],
                'DHCP Snooping': [
                    ('ip dhcp snooping', 'Enable DHCP Snooping globally'),
                    ('ip dhcp snooping vlan <id>', 'Enable DHCP Snooping on VLAN'),
                    ('ip dhcp snooping trust', 'Set port as trusted (uplink)'),
                    ('ip dhcp snooping limit rate <pps>', 'Limit DHCP packets per second on untrusted port'),
                    ('show ip dhcp snooping', 'Display DHCP Snooping status'),
                    ('show ip dhcp snooping binding', 'Display DHCP Snooping binding table'),
                ],
                'NTP': [
                    ('ntp server <ip>', 'Configure NTP server'),
                    ('ntp source <iface>', 'Set source interface for NTP packets'),
                    ('ntp authenticate', 'Enable NTP authentication'),
                    ('ntp authentication-key <id> md5 <key>', 'Configure NTP authentication key'),
                    ('show ntp status', 'Display NTP synchronization status'),
                    ('show ntp associations', 'Display NTP server associations'),
                ],
                '802.1X': [
                    ('dot1x system-auth-control', 'Enable 802.1X globally'),
                    ('dot1x port-control auto', 'Enable 802.1X on port (auto-authenticate)'),
                    ('dot1x port-control force-authorized', 'Force port authorized (bypass 802.1X)'),
                    ('authentication periodic', 'Enable re-authentication'),
                    ('authentication timer reauthenticate <sec>', 'Set re-authentication interval'),
                    ('show dot1x all summary', 'Display 802.1X port status summary'),
                ],
                'sFlow / NetFlow': [
                    ('sflow enable', 'Enable sFlow globally'),
                    ('sflow collector <ip> <port>', 'Configure sFlow collector'),
                    ('sflow polling-interval <sec>', 'Set sFlow polling interval'),
                    ('ip flow-export destination <ip> <port>', 'Configure NetFlow exporter'),
                    ('ip flow-export version 9', 'Set NetFlow export version'),
                    ('ip flow-cache timeout active 1', 'Set active flow timeout (minutes)'),
                    ('show flow-sampler', 'Display sFlow/NetFlow sampler status'),
                ],
                'OSPF': [
                    ('router ospf <id>', 'Enable OSPF routing process'),
                    ('network <net> <wildcard> area <id>', 'Advertise network in OSPF area'),
                    ('area <id> stub', 'Configure stub area'),
                    ('area <id> nssa', 'Configure NSSA area'),
                    ('area <id> stub no-summary', 'Configure totally stubby area'),
                    ('area <id> nssa no-summary', 'Configure totally NSSA'),
                    ('default-information originate', 'Advertise default route into OSPF'),
                    ('default-information originate always', 'Always advertise default route'),
                    ('passive-interface <iface>', 'Suppress OSPF hellos on interface'),
                    ('passive-interface default', 'Make all interfaces passive by default'),
                    ('auto-cost reference-bandwidth <mbps>', 'Set reference bandwidth for cost calc'),
                    ('maximum-paths <n>', 'Set max equal-cost paths (default 4)'),
                    ('log-adjacency-changes', 'Log OSPF neighbor state changes'),
                    ('show ip ospf', 'Display OSPF process information'),
                    ('show ip ospf neighbor', 'Display OSPF neighbors'),
                    ('show ip ospf neighbor detail', 'Detailed OSPF neighbor info'),
                    ('show ip ospf interface', 'Display OSPF interface status'),
                    ('show ip ospf interface brief', 'Brief OSPF interface summary'),
                    ('show ip ospf database', 'Display OSPF LSDB'),
                    ('show ip ospf database router', 'Show Type-1 LSAs'),
                    ('show ip ospf database network', 'Show Type-2 LSAs'),
                    ('show ip ospf database summary', 'Show Type-3 LSAs'),
                    ('show ip ospf database external', 'Show Type-5 LSAs'),
                    ('show ip ospf database nssa-external', 'Show Type-7 LSAs'),
                    ('show ip ospf border-routers', 'Display OSPF internal ABR/ASBR routes'),
                    ('show ip ospf virtual-links', 'Display OSPF virtual links'),
                    ('show ip ospf traffic', 'Display OSPF packet statistics'),
                    ('show ip ospf statistics', 'Display OSPF SPF statistics'),
                    ('clear ip ospf process', 'Reset OSPF process'),
                    ('debug ip ospf hello', 'Debug OSPF hello packets'),
                    ('debug ip ospf adj', 'Debug OSPF adjacency events'),
                    ('debug ip ospf events', 'Debug OSPF events'),
                    ('debug ip ospf lsa', 'Debug OSPF LSA generation'),
                ],
                'BGP': [
                    ('router bgp <asn>', 'Enable BGP routing process'),
                    ('bgp router-id <ip>', 'Set BGP router ID'),
                    ('bgp log-neighbor-changes', 'Log BGP neighbor state changes'),
                    ('neighbor <ip> remote-as <asn>', 'Configure BGP neighbor'),
                    ('neighbor <ip> description <text>', 'Set neighbor description'),
                    ('neighbor <ip> update-source <iface>', 'Set update source interface'),
                    ('neighbor <ip> ebgp-multihop <ttl>', 'Set eBGP multihop TTL'),
                    ('neighbor <ip> password <key>', 'Set MD5 authentication for neighbor'),
                    ('neighbor <ip> timers <keepalive> <holdtime>', 'Set BGP timers'),
                    ('neighbor <ip> soft-reconfiguration inbound', 'Enable soft reconfiguration inbound'),
                    ('neighbor <ip> route-map <name> in', 'Apply route-map to inbound updates'),
                    ('neighbor <ip> route-map <name> out', 'Apply route-map to outbound updates'),
                    ('neighbor <ip> prefix-list <name> in', 'Apply prefix-list to inbound updates'),
                    ('neighbor <ip> prefix-list <name> out', 'Apply prefix-list to outbound updates'),
                    ('neighbor <ip> distribute-list <acl> in', 'Apply distribute-list inbound'),
                    ('neighbor <ip> distribute-list <acl> out', 'Apply distribute-list outbound'),
                    ('neighbor <ip> filter-list <as-path-acl> in', 'Apply AS-path filter inbound'),
                    ('neighbor <ip> filter-list <as-path-acl> out', 'Apply AS-path filter outbound'),
                    ('neighbor <ip> weight <0-65535>', 'Set BGP weight for neighbor'),
                    ('neighbor <ip> next-hop-self', 'Set next-hop to self for neighbor'),
                    ('neighbor <ip> send-community', 'Send community attribute to neighbor'),
                    ('neighbor <ip> activate', 'Activate neighbor in address-family'),
                    ('network <net> mask <mask>', 'Advertise network in BGP'),
                    ('network <net> mask <mask> route-map <name>', 'Advertise network with route-map'),
                    ('aggregate-address <net> <mask>', 'Create aggregate/summary route'),
                    ('aggregate-address <net> <mask> summary-only', 'Advertise only the aggregate'),
                    ('redistribute connected', 'Redistribute connected routes into BGP'),
                    ('redistribute static', 'Redistribute static routes into BGP'),
                    ('redistribute ospf <id> match internal external', 'Redistribute OSPF into BGP'),
                    ('redistribute rip', 'Redistribute RIP into BGP'),
                    ('default-information originate', 'Advertise default route in BGP'),
                    ('maximum-paths <n>', 'Set max equal-cost BGP paths'),
                    ('maximum-paths ibgp <n>', 'Set max iBGP equal-cost paths'),
                    ('distance bgp <external> <internal> <local>', 'Set BGP administrative distances'),
                    ('address-family ipv4 unicast', 'Enter IPv4 unicast address-family'),
                    ('address-family ipv6 unicast', 'Enter IPv6 unicast address-family'),
                    ('address-family vpnv4 unicast', 'Enter VPNv4 address-family (MPLS)'),
                    ('show ip bgp', 'Display BGP routing table'),
                    ('show ip bgp summary', 'Display BGP neighbor summary'),
                    ('show ip bgp neighbors', 'Display detailed BGP neighbor info'),
                    ('show ip bgp neighbors <ip>', 'Detailed info for specific neighbor'),
                    ('show ip bgp neighbors <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('show ip bgp neighbors <ip> received-routes', 'Routes received from neighbor'),
                    ('show ip bgp neighbors <ip> routes', 'Routes from neighbor in BGP table'),
                    ('show ip bgp <net>', 'Show BGP entry for specific network'),
                    ('show ip bgp <net> <mask> longer-prefixes', 'Show more-specific routes'),
                    ('show ip bgp regexp <regex>', 'Show routes matching AS-path regex'),
                    ('show ip bgp community <community>', 'Show routes with community'),
                    ('show ip bgp community-list <name>', 'Show routes matching community-list'),
                    ('show ip bgp dampened-paths', 'Show dampened (flapping) routes'),
                    ('show ip bgp scan', 'Show BGP scanner status'),
                    ('show ip bgp vpnv4 all', 'Show all VPNv4 routes (MPLS)'),
                    ('show ip bgp ipv6 unicast', 'Show IPv6 BGP table'),
                    ('show ip bgp ipv6 unicast summary', 'Show IPv6 BGP neighbor summary'),
                    ('show ip protocols', 'Display active routing protocols including BGP'),
                    ('clear ip bgp *', 'Reset all BGP sessions (hard reset)'),
                    ('clear ip bgp <ip>', 'Reset specific BGP session'),
                    ('clear ip bgp <ip> soft in', 'Soft reset inbound for neighbor'),
                    ('clear ip bgp <ip> soft out', 'Soft reset outbound for neighbor'),
                    ('clear ip bgp * soft', 'Soft reset all BGP sessions'),
                    ('debug ip bgp', 'Enable BGP debug (all events)'),
                    ('debug ip bgp updates', 'Debug BGP update messages'),
                    ('debug ip bgp keepalives', 'Debug BGP keepalive messages'),
                    ('debug ip bgp neighbor <ip>', 'Debug specific BGP neighbor'),
                ],
                'Port Statistics': [
                    ('show interfaces', 'Detailed interface statistics for all ports'),
                    ('show interfaces <iface>', 'Statistics for specific interface'),
                    ('show interfaces <iface> counters', 'Packet counters for interface'),
                    ('show interfaces <iface> counters errors', 'Error counters for interface'),
                    ('show interfaces status', 'Port status summary (up/down, speed, duplex)'),
                    ('show interfaces status err-disabled', 'Show err-disabled ports'),
                    ('show interfaces trunk', 'Display trunk ports and allowed VLANs'),
                    ('show interfaces switchport', 'Display switchport configuration'),
                    ('show interfaces <iface> switchport', 'Switchport config for specific port'),
                    ('show interfaces transceiver', 'Display SFP/SFP+ transceiver info'),
                    ('show interfaces transceiver detail', 'Detailed transceiver diagnostics (DDM)'),
                    ('show interfaces transceiver thresholds', 'Display SFP alarm thresholds'),
                    ('show controllers ethernet-controller', 'Display controller-level stats'),
                    ('show storm-control', 'Display storm control status on all ports'),
                    ('show storm-control <iface>', 'Storm control status for specific port'),
                    ('show port-security', 'Display port-security status on all ports'),
                    ('show port-security interface <iface>', 'Port-security for specific port'),
                    ('show port-security address', 'Display all secure MAC addresses'),
                    ('show cdp interface', 'CDP status per interface'),
                    ('show lldp interface', 'LLDP status per interface'),
                    ('show mac address-table interface <iface>', 'MAC addresses on specific port'),
                    ('show mac address-table count', 'MAC address table size per VLAN'),
                    ('show mac address-table aging-time', 'MAC aging time configuration'),
                    ('show errdisable recovery', 'Display err-disable recovery settings'),
                    ('show errdisable flap-values', 'Display link-flap detection values'),
                    ('clear counters', 'Clear all interface counters'),
                    ('clear counters <iface>', 'Clear counters for specific interface'),
                    ('clear mac address-table dynamic', 'Clear all dynamic MAC entries'),
                    ('clear mac address-table dynamic interface <iface>', 'Clear MACs on specific port'),
                ],
                'IS-IS': [
                    ('router isis', 'Enable IS-IS routing process'),
                    ('net <nsap>', 'Set IS-IS Network Entity Title (NET)'),
                    ('is-type level-1', 'Set IS-IS level to L1 only'),
                    ('is-type level-2-only', 'Set IS-IS level to L2 only'),
                    ('metric-style wide', 'Enable wide metrics (required for MPLS/TE)'),
                    ('metric-style wide level-1', 'Enable wide metrics for L1'),
                    ('metric-style wide level-2', 'Enable wide metrics for L2'),
                    ('log-adjacency-changes', 'Log IS-IS adjacency changes'),
                    ('spf-interval <n>', 'Set SPF calculation interval'),
                    ('interface <iface>', 'Enter interface config'),
                    ('ip router isis', 'Enable IS-IS on interface'),
                    ('isis circuit-type level-1', 'Set IS-IS circuit type to L1'),
                    ('isis circuit-type level-2-only', 'Set IS-IS circuit type to L2 only'),
                    ('isis network point-to-point', 'Set interface as point-to-point'),
                    ('isis metric <1-16777214>', 'Set IS-IS interface metric'),
                    ('isis metric <1-16777214> level-1', 'Set IS-IS L1 interface metric'),
                    ('isis metric <1-16777214> level-2', 'Set IS-IS L2 interface metric'),
                    ('isis hello-interval <sec>', 'Set IS-IS hello interval'),
                    ('isis hello-multiplier <n>', 'Set IS-IS hello multiplier'),
                    ('isis priority <0-127>', 'Set IS-IS DIS priority'),
                    ('isis passive', 'Enable IS-IS passive mode on interface'),
                    ('redistribute connected', 'Redistribute connected routes into IS-IS'),
                    ('redistribute static', 'Redistribute static routes into IS-IS'),
                    ('redistribute ospf <id>', 'Redistribute OSPF into IS-IS'),
                    ('redistribute bgp <asn>', 'Redistribute BGP into IS-IS'),
                    ('default-information originate', 'Advertise default route into IS-IS'),
                    ('show isis neighbors', 'Display IS-IS neighbors'),
                    ('show isis neighbors detail', 'Detailed IS-IS neighbor info'),
                    ('show isis database', 'Display IS-IS link-state database'),
                    ('show isis database detail', 'Detailed LSP information'),
                    ('show isis database verbose', 'Verbose LSP display with TLVs'),
                    ('show isis database level-1', 'Display L1 LSDB'),
                    ('show isis database level-2', 'Display L2 LSDB'),
                    ('show isis hostname', 'Display IS-IS hostname mapping'),
                    ('show isis interface', 'Display IS-IS interface status'),
                    ('show isis interface brief', 'Brief IS-IS interface summary'),
                    ('show isis ipv6 route', 'Display IS-IS IPv6 routes'),
                    ('show isis route', 'Display IS-IS routing table'),
                    ('show isis spf-log', 'Display SPF calculation history'),
                    ('show isis traffic', 'Display IS-IS packet statistics'),
                    ('clear isis neighbors', 'Reset IS-IS adjacencies'),
                    ('debug isis adj-packets', 'Debug IS-IS adjacency packets'),
                    ('debug isis spf-events', 'Debug IS-IS SPF events'),
                    ('debug isis updates', 'Debug IS-IS LSP updates'),
                ],
                'RIP': [
                    ('router rip', 'Enable RIP routing process'),
                    ('version 2', 'Use RIPv2 (supports VLSM/CIDR)'),
                    ('network <net>', 'Advertise network in RIP'),
                    ('no auto-summary', 'Disable automatic route summarization'),
                    ('passive-interface <iface>', 'Stop sending RIP updates on interface'),
                    ('passive-interface default', 'Make all interfaces passive by default'),
                    ('neighbor <ip>', 'Send unicast RIP updates to neighbor'),
                    ('timers basic <update> <invalid> <holddown> <flush>', 'Adjust RIP timers'),
                    ('default-information originate', 'Advertise default route in RIP'),
                    ('default-metric <1-16>', 'Set default metric for redistributed routes'),
                    ('maximum-paths <n>', 'Set max equal-cost RIP paths'),
                    ('distance <1-255>', 'Set RIP administrative distance'),
                    ('redistribute connected', 'Redistribute connected routes into RIP'),
                    ('redistribute static', 'Redistribute static routes into RIP'),
                    ('redistribute ospf <id> metric <n>', 'Redistribute OSPF into RIP'),
                    ('redistribute bgp <asn> metric <n>', 'Redistribute BGP into RIP'),
                    ('offset-list <acl> <in|out> <n>', 'Add to RIP metric for matched routes'),
                    ('distribute-list <acl> in', 'Filter incoming RIP updates'),
                    ('distribute-list <acl> out', 'Filter outgoing RIP updates'),
                    ('show ip rip database', 'Display RIP routing database'),
                    ('show ip protocols', 'Display active routing protocols including RIP'),
                    ('show ip rip', 'Display RIP process information'),
                    ('debug ip rip', 'Debug RIP update packets'),
                    ('debug ip rip events', 'Debug RIP events'),
                ],
                'QoS / CoS / DSCP': [
                    ('mls qos', 'Enable QoS globally'),
                    ('class-map match-any <name>', 'Create class map for traffic classification'),
                    ('policy-map <name>', 'Create policy map'),
                    ('class <name>', 'Reference class map in policy'),
                    ('set dscp <value>', 'Set DSCP value in policy'),
                    ('set cos <value>', 'Set 802.1p CoS value in policy'),
                    ('police <bps> exceed-action drop', 'Police traffic — drop exceeding packets'),
                    ('service-policy input <name>', 'Apply policy inbound on interface'),
                    ('service-policy output <name>', 'Apply policy outbound on interface'),
                    ('show policy-map interface', 'Display QoS policy on interfaces'),
                ],
                'Trunk': [
                    ('interface <iface>', 'Enter interface config mode'),
                    ('switchport mode trunk', 'Set port as trunk'),
                    ('switchport trunk allowed vlan <ids>', 'Set allowed VLANs on trunk'),
                    ('switchport trunk allowed vlan add <id>', 'Add VLAN to trunk allowed list'),
                    ('switchport trunk allowed vlan remove <id>', 'Remove VLAN from trunk allowed list'),
                    ('switchport trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('switchport trunk encapsulation dot1q', 'Set trunk encapsulation to 802.1Q'),
                    ('switchport nonegotiate', 'Disable DTP negotiation'),
                    ('show interfaces trunk', 'Display trunk ports and allowed VLANs'),
                ],
                'System': [
                    ('hostname <name>', 'Set device hostname'),
                    ('copy running-config startup-config', 'Save configuration'),
                    ('write memory', 'Save configuration (shorthand)'),
                    ('reload', 'Reboot the device'),
                ],
                'Users': [
                    ('username <name> privilege <0-15> password <pass>', 'Create local user with privilege level'),
                    ('username <name> privilege <0-15> secret <pass>', 'Create user with encrypted password'),
                    ('username <name> privilege 15 secret <pass>', 'Create admin user (privilege 15)'),
                    ('no username <name>', 'Delete a local user'),
                    ('show users', 'Display active terminal sessions'),
                    ('show running-config | include username', 'List all configured local users'),
                ],
                'SSH': [
                    ('ip ssh version 2', 'Enable SSH version 2 only'),
                    ('ip ssh time-out <sec>', 'Set SSH session timeout'),
                    ('ip ssh authentication-retries <n>', 'Set max authentication retries'),
                    ('crypto key generate rsa modulus <bits>', 'Generate RSA key pair for SSH'),
                    ('crypto key generate ecdsa <curve>', 'Generate ECDSA key for SSH'),
                    ('show ip ssh', 'Display SSH configuration and status'),
                    ('line vty 0 15', 'Enter VTY line configuration'),
                    ('transport input ssh', 'Allow only SSH on VTY lines'),
                    ('transport input telnet ssh', 'Allow both Telnet and SSH on VTY lines'),
                    ('ip ssh server algorithm mac hmac-sha2-256', 'Set SSH MAC algorithm'),
                ],
                'Telnet': [
                    ('telnet <ip>', 'Initiate Telnet client session to remote host'),
                    ('line vty 0 15', 'Enter VTY line configuration'),
                    ('transport input telnet', 'Allow only Telnet on VTY lines'),
                    ('transport input none', 'Disable remote access on VTY lines'),
                    ('no telnet server enable', 'Disable Telnet server (IOS-XE)'),
                    ('show line vty 0', 'Display VTY line configuration'),
                ],
                'SNMP': [
                    ('snmp-server community <name> ro', 'Configure read-only SNMP community'),
                    ('snmp-server community <name> rw', 'Configure read-write SNMP community'),
                    ('snmp-server location <text>', 'Set SNMP system location'),
                    ('snmp-server contact <text>', 'Set SNMP system contact'),
                    ('snmp-server host <ip> version 2c <community>', 'Send traps to SNMP host (v2c)'),
                    ('snmp-server host <ip> version 3 priv <user>', 'Send traps to SNMP host (v3)'),
                    ('snmp-server enable traps', 'Enable all SNMP traps'),
                    ('show snmp community', 'Display SNMP community strings'),
                    ('show snmp contact', 'Display SNMP contact string'),
                    ('show snmp location', 'Display SNMP location string'),
                ],
                'Firmware': [
                    ('show version', 'Display current IOS version and hardware'),
                    ('show flash:', 'List files in flash memory'),
                    ('verify /md5 flash:<file>', 'Verify MD5 checksum of file in flash'),
                    ('copy tftp://<ip>/<file> flash:', 'Download firmware from TFTP to flash'),
                    ('copy tftp: flash:', 'Interactive TFTP copy to flash'),
                    ('boot system flash:<file>', 'Set boot image for next reload'),
                    ('no boot system', 'Remove all configured boot images'),
                    ('reload', 'Reboot to apply new firmware'),
                ],
            },
            'Huawei': {
                'Navigation': [
                    ('system-view', 'Enter system/global configuration mode'),
                    ('quit', 'Exit current view / go back one level'),
                    ('return', 'Return to user view from any view'),
                ],
                'Display Commands': [
                    ('display current-configuration', 'Show current running configuration'),
                    ('display saved-configuration', 'Show saved configuration'),
                    ('display ip interface brief', 'Quick overview of interfaces'),
                    ('display interface', 'Detailed interface information'),
                    ('display interface brief', 'Brief status of all interfaces'),
                    ('display vlan', 'Display all VLANs'),
                    ('display vlan <id>', 'Show specific VLAN details'),
                    ('display ip routing-table', 'Display routing table'),
                    ('display ip routing-table protocol static', 'Show static routes only'),
                    ('display mac-address', 'Display MAC address table'),
                    ('display mac-address vlan <id>', 'MAC table filtered by VLAN'),
                    ('display arp', 'Display ARP table'),
                    ('display dhcp server all', 'Show all DHCP server configs'),
                    ('display dhcp server ip-in-use', 'Display active DHCP leases'),
                    ('display dhcp server statistics', 'Show DHCP server statistics'),
                    ('display acl all', 'Display all configured ACLs'),
                    ('display acl <number>', 'Display specific ACL'),
                    ('display lacp brief', 'Show LACP port-channel summary'),
                    ('display eth-trunk <id>', 'Detailed Eth-Trunk information'),
                    ('display ip vpn-instance', 'List all VPN-instances (VRFs)'),
                    ('display ip routing-table vpn-instance <name>', 'Routing table for a VRF'),
                    ('display version', 'Show system version information'),
                    ('display clock', 'Show system date and time'),
                    ('display logbuffer', 'Show system log buffer'),
                ],
                'Interfaces': [
                    ('interface GigabitEthernet0/0/1', 'Enter interface view'),
                    ('ip address <ip> <mask>', 'Assign IP address'),
                    ('undo shutdown', 'Enable the interface'),
                    ('shutdown', 'Disable the interface'),
                    ('port link-type trunk', 'Set port as trunk'),
                    ('port link-type access', 'Set port as access'),
                    ('port default vlan <id>', 'Assign access VLAN'),
                    ('port trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('port trunk allow-pass vlan all', 'Allow all VLANs on trunk'),
                    ('dhcp select relay', 'Enable DHCP relay on interface'),
                    ('dhcp relay server-ip <ip>', 'Set DHCP server for relay'),
                    ('description <text>', 'Set interface description'),
                ],
                'VLANs': [
                    ('vlan <id>', 'Create or enter VLAN view'),
                    ('vlan batch <start> to <end>', 'Create VLANs in batch'),
                    ('port trunk allow-pass vlan <ids>', 'Allow VLANs on trunk'),
                    ('undo vlan <id>', 'Delete a VLAN'),
                    ('display vlan', 'Show all VLANs and their ports'),
                ],
                'ACLs': [
                    ('acl number <2000-2999>', 'Create basic (standard) ACL'),
                    ('acl number <3000-3999>', 'Create advanced (extended) ACL'),
                    ('acl name <name> basic', 'Create named basic ACL'),
                    ('acl name <name> advanced', 'Create named advanced ACL'),
                    ('rule permit source <ip> <wildcard>', 'Permit source (basic ACL)'),
                    ('rule deny source <ip> <wildcard>', 'Deny source (basic ACL)'),
                    ('rule permit tcp source <src> <wc> destination <dst> <wc> destination-port eq <port>', 'Permit TCP to port (advanced ACL)'),
                    ('rule deny ip source any destination any', 'Deny all IP traffic'),
                    ('traffic-filter inbound acl <number>', 'Apply ACL inbound on interface'),
                    ('traffic-filter outbound acl <number>', 'Apply ACL outbound on interface'),
                    ('display acl all', 'Show all ACLs with hit counts'),
                    ('undo acl number <number>', 'Delete an ACL'),
                ],
                'DHCP': [
                    ('dhcp enable', 'Enable DHCP globally'),
                    ('ip pool <name>', 'Create DHCP address pool'),
                    ('network <net> mask <mask>', 'Set pool network (inside pool)'),
                    ('gateway-list <ip>', 'Set default gateway for pool'),
                    ('dns-list <ip1> <ip2>', 'Set DNS servers for pool'),
                    ('lease day <n>', 'Set lease duration in days'),
                    ('excluded-ip-address <start> <end>', 'Exclude IP range from pool'),
                    ('display dhcp server ip-in-use', 'Show active DHCP leases'),
                    ('display dhcp server pool', 'Show DHCP pool details'),
                    ('reset dhcp server ip-in-use all', 'Clear all DHCP bindings'),
                ],
                'LACP / Eth-Trunk': [
                    ('interface Eth-Trunk <id>', 'Create or enter Eth-Trunk interface'),
                    ('mode lacp-static', 'Set Eth-Trunk to LACP static mode'),
                    ('mode lacp-dynamic', 'Set Eth-Trunk to LACP dynamic mode'),
                    ('mode manual load-balance', 'Set Eth-Trunk to manual mode'),
                    ('interface GigabitEthernet0/0/1', 'Enter member interface'),
                    ('eth-trunk <id>', 'Add interface to Eth-Trunk'),
                    ('lacp priority <0-65535>', 'Set LACP priority on interface'),
                    ('lacp system-id priority <0-65535>', 'Set system LACP priority'),
                    ('display eth-trunk <id>', 'Show Eth-Trunk details and members'),
                    ('display lacp brief', 'Show LACP status summary'),
                ],
                'VRF (VPN-Instance)': [
                    ('ip vpn-instance <name>', 'Create VPN-instance (VRF)'),
                    ('ipv4-family', 'Enter IPv4 address-family (inside vpn-instance)'),
                    ('route-distinguisher <asn>:<id>', 'Set route distinguisher'),
                    ('vpn-target <rt> export-extcommunity', 'Set export route-target'),
                    ('vpn-target <rt> import-extcommunity', 'Set import route-target'),
                    ('interface <iface>', 'Enter interface'),
                    ('ip binding vpn-instance <name>', 'Bind interface to VPN-instance'),
                    ('ip address <ip> <mask>', 'Assign IP after VPN binding'),
                    ('ip route-static vpn-instance <name> <net> <mask> <gw>', 'Add static route in VPN-instance'),
                    ('display ip vpn-instance', 'List all VPN-instances'),
                    ('display ip routing-table vpn-instance <name>', 'Show VRF routing table'),
                ],
                'VRRP': [
                    ('interface <iface>', 'Enter interface for VRRP config'),
                    ('vrrp vrid <group> virtual-ip <ip>', 'Set virtual IP for VRRP group'),
                    ('vrrp vrid <group> priority <0-255>', 'Set VRRP priority (default 100; higher = master)'),
                    ('vrrp vrid <group> preempt-mode timer delay <sec>', 'Set preemption delay'),
                    ('undo vrrp vrid <group> preempt-mode', 'Disable preemption'),
                    ('vrrp vrid <group> timer advertise <sec>', 'Set advertisement interval'),
                    ('vrrp vrid <group> authentication-mode simple plain <key>', 'Set plain-text auth'),
                    ('vrrp vrid <group> track interface <iface> reduced <val>', 'Track interface and reduce priority'),
                    ('vrrp vrid <group> description <text>', 'Set VRRP group description'),
                    ('display vrrp', 'Display all VRRP groups'),
                    ('display vrrp brief', 'VRRP summary (master/backup state)'),
                    ('display vrrp interface <iface>', 'VRRP details for specific interface'),
                    ('display vrrp statistics', 'Show VRRP packet statistics'),
                ],
                'Routing': [
                    ('ip route-static <net> <mask> <next-hop>', 'Add static route'),
                    ('ospf <id>', 'Enable OSPF process'),
                    ('bgp <asn>', 'Enable BGP process'),
                ],
                'System': [
                    ('sysname <name>', 'Set device hostname'),
                    ('save', 'Save current configuration'),
                    ('undo <command>', 'Negate/remove a configuration'),
                    ('reboot', 'Reboot the device'),
                ],
                'Users': [
                    ('aaa', 'Enter AAA configuration view'),
                    ('local-user <name> password cipher <pass>', 'Create local user with encrypted password'),
                    ('local-user <name> service-type ssh terminal', 'Set user access types (SSH + terminal)'),
                    ('local-user <name> service-type telnet ssh', 'Set user access types (Telnet + SSH)'),
                    ('local-user <name> level <0-15>', 'Set user privilege level (0-15)'),
                    ('local-user <name> level 15', 'Set user as administrator (level 15)'),
                    ('undo local-user <name>', 'Delete a local user'),
                    ('display local-user', 'List all configured local users'),
                ],
                'SSH': [
                    ('ssh server enable', 'Enable SSH server'),
                    ('ssh server compatible-ssh1x enable', 'Enable SSHv1 compatibility (not recommended)'),
                    ('ssh server port <port>', 'Change SSH server port (default 22)'),
                    ('public-key local create rsa', 'Generate RSA key pair for SSH'),
                    ('public-key local create ecdsa', 'Generate ECDSA key pair for SSH'),
                    ('display ssh server status', 'Display SSH server status'),
                    ('display ssh server session', 'Display active SSH sessions'),
                    ('user-interface vty 0 4', 'Enter VTY line configuration'),
                    ('authentication-mode aaa', 'Use AAA authentication for VTY'),
                    ('protocol inbound ssh', 'Allow only SSH on VTY lines'),
                ],
                'Telnet': [
                    ('telnet server enable', 'Enable Telnet server'),
                    ('telnet server disable', 'Disable Telnet server'),
                    ('user-interface vty 0 4', 'Enter VTY line configuration'),
                    ('authentication-mode aaa', 'Use AAA authentication for VTY'),
                    ('protocol inbound telnet', 'Allow only Telnet on VTY lines'),
                    ('protocol inbound all', 'Allow all protocols on VTY lines'),
                    ('display telnet server status', 'Display Telnet server status'),
                ],
                'SNMP': [
                    ('snmp-agent', 'Enable SNMP agent'),
                    ('snmp-agent community read <name>', 'Configure read-only SNMP community'),
                    ('snmp-agent community write <name>', 'Configure read-write SNMP community'),
                    ('snmp-agent sys-info location <text>', 'Set SNMP system location'),
                    ('snmp-agent sys-info contact <text>', 'Set SNMP system contact'),
                    ('snmp-agent target-host trap address udp-domain <ip> params securityname <name>', 'Send traps to SNMP host'),
                    ('snmp-agent extend error-code enable', 'Enable extended error codes'),
                    ('display snmp-agent community', 'Display SNMP community strings'),
                    ('display snmp-agent sys-info', 'Display SNMP system information'),
                ],

                'Spanning-Tree': [
                    ('stp mode stp', 'Enable STP (802.1D) mode'),
                    ('stp mode rstp', 'Enable RSTP (802.1w) mode'),
                    ('stp mode mstp', 'Enable MSTP (802.1s) mode (default)'),
                    ('stp region-configuration', 'Enter MST region configuration'),
                    ('region-name <name>', 'Set MST region name'),
                    ('revision-level <n>', 'Set MST revision level'),
                    ('instance <id> vlan <vlan-list>', 'Map VLANs to MST instance'),
                    ('active region-configuration', 'Activate MST region config'),
                    ('display stp region-configuration', 'Show MST region configuration'),
                    ('stp priority <0-61440>', 'Set bridge priority (step 4096)'),
                    ('stp instance <id> priority <0-61440>', 'Set MST instance priority'),
                    ('stp root primary', 'Set as primary root (priority 0)'),
                    ('stp root secondary', 'Set as secondary root (priority 4096)'),
                    ('stp instance <id> root primary', 'Set as root for MST instance'),
                    ('stp edged-port enable', 'Enable Edge Port (PortFast equivalent)'),
                    ('stp bpdu-protection', 'Enable BPDU protection globally'),
                    ('stp root-protection', 'Enable Root Protection on port'),
                    ('stp loop-protection', 'Enable Loop Protection on port'),
                    ('stp tc-protection', 'Enable TC-BPDU attack protection'),
                    ('stp tc-protection threshold <n>', 'Set TC-BPDU threshold per second'),
                    ('stp cost <cost>', 'Set STP port cost on interface'),
                    ('stp port priority <0-240>', 'Set STP port priority on interface'),
                    ('stp instance <id> cost <cost>', 'Set cost for MST instance'),
                    ('stp point-to-point auto', 'Set link type to auto-detect'),
                    ('stp point-to-point force-true', 'Force link type as point-to-point'),
                    ('stp max-hops <n>', 'Set MSTP max hops (default 20)'),
                    ('stp timer hello <n>', 'Set hello timer (1-10 seconds)'),
                    ('stp timer forward-delay <n>', 'Set forward delay (4-30 seconds)'),
                    ('stp timer max-age <n>', 'Set max age timer (6-40 seconds)'),
                    ('undo stp enable', 'Disable STP globally'),
                    ('display stp', 'Display STP global status'),
                    ('display stp brief', 'STP brief port status summary'),
                    ('display stp interface <iface>', 'STP status for specific interface'),
                    ('display stp instance <id>', 'Display MST instance status'),
                    ('display stp instance <id> brief', 'Brief MST instance port status'),
                    ('display stp abnormal-port', 'Show ports in abnormal STP state'),
                    ('display stp tc', 'Display TC-BPDU statistics'),
                    ('display stp topology-change', 'Display topology change statistics'),
                    ('reset stp statistics', 'Clear STP statistics'),
                ],
                'Port Statistics': [
                    ('display interface', 'Display statistics for all interfaces'),
                    ('display interface brief', 'Brief status of all interfaces'),
                    ('display interface <iface>', 'Detailed statistics for specific interface'),
                    ('display interface <iface> brief', 'Brief status for specific interface'),
                    ('display interface transceiver', 'Display optical transceiver info'),
                    ('display interface transceiver verbose', 'Detailed transceiver diagnostics'),
                    ('display interface transceiver manuinfo', 'Display transceiver manufacturing info'),
                    ('display counters inbound interface', 'Display inbound traffic counters'),
                    ('display counters outbound interface', 'Display outbound traffic counters'),
                    ('display counters interface <iface>', 'Counters for specific interface'),
                    ('display interface <iface> counters', 'Packet counters for interface'),
                    ('display interface <iface> counters error', 'Error counters for interface'),
                    ('display interface <iface> counters broadcast', 'Broadcast packet counters'),
                    ('display interface <iface> counters multicast', 'Multicast packet counters'),
                    ('display interface <iface> counters unicast', 'Unicast packet counters'),
                    ('display interface <iface> counters crc-error', 'CRC error counters'),
                    ('display interface <iface> statistics', 'Traffic statistics for interface'),
                    ('display interface <iface> description', 'Interface descriptions'),
                    ('display eth-trunk <id>', 'Show Eth-Trunk details and members'),
                    ('display lacp statistics', 'Display LACP statistics'),
                    ('display lldp neighbor brief', 'LLDP neighbor summary'),
                    ('display mac-address', 'Display MAC address table'),
                    ('display mac-address interface <iface>', 'MAC addresses on specific port'),
                    ('display mac-address summary', 'MAC address table summary'),
                    ('display error-down recovery', 'Display err-down recovery settings'),
                    ('display error-down record', 'Display err-down history'),
                    ('reset counters interface', 'Clear all interface counters'),
                    ('reset counters interface <iface>', 'Clear counters for specific interface'),
                ],
                'Debug': [
                    ('terminal monitor', 'Enable terminal monitoring'),
                    ('terminal debugging', 'Enable debug output to terminal'),
                    ('debugging ip icmp', 'Debug ICMP packets'),
                    ('debugging ospf packet', 'Debug OSPF packets'),
                    ('undo debugging all', 'Disable all debug output'),
                    ('display debugging', 'Display active debug flags'),
                ],
                'Log': [
                    ('info-center enable', 'Enable information center (logging)'),
                    ('info-center loghost <ip>', 'Send logs to remote syslog server'),
                    ('info-center source default channel loghost log level debugging', 'Set syslog severity level'),
                    ('display logbuffer', 'Display system log buffer'),
                    ('display trapbuffer', 'Display trap (event) buffer'),
                ],
                'LLDP': [
                    ('lldp enable', 'Enable LLDP globally'),
                    ('lldp enable interface <iface>', 'Enable LLDP on interface'),
                    ('display lldp neighbor brief', 'Display LLDP neighbors (brief)'),
                    ('display lldp neighbor', 'Display LLDP neighbors (detailed)'),
                ],
                'DHCP Server': [
                    ('dhcp enable', 'Enable DHCP globally'),
                    ('ip pool <name>', 'Create DHCP address pool'),
                    ('network <net> mask <mask>', 'Set pool network (inside pool)'),
                    ('gateway-list <ip>', 'Set default gateway for clients'),
                    ('dns-list <ip1> <ip2>', 'Set DNS servers for clients'),
                    ('lease day <n>', 'Set lease duration in days'),
                    ('display dhcp server ip-in-use', 'Show active DHCP leases'),
                    ('display dhcp server pool', 'Show DHCP pool details'),
                ],
                'DHCP Snooping': [
                    ('dhcp snooping enable', 'Enable DHCP Snooping globally'),
                    ('dhcp snooping enable vlan <id>', 'Enable DHCP Snooping on VLAN'),
                    ('dhcp snooping trusted interface <iface>', 'Set interface as trusted'),
                    ('display dhcp snooping', 'Display DHCP Snooping status'),
                    ('display dhcp snooping binding', 'Display DHCP Snooping binding table'),
                ],
                'NTP': [
                    ('ntp-service unicast-server <ip>', 'Configure NTP server'),
                    ('ntp-service source-interface <iface>', 'Set source interface for NTP'),
                    ('display ntp-service status', 'Display NTP synchronization status'),
                    ('display ntp-service sessions', 'Display NTP sessions'),
                ],
                '802.1X': [
                    ('dot1x enable', 'Enable 802.1X globally'),
                    ('dot1x enable interface <iface>', 'Enable 802.1X on interface'),
                    ('dot1x authentication-method eap', 'Set EAP authentication method'),
                    ('dot1x reauthenticate interface <iface>', 'Trigger re-authentication'),
                    ('display dot1x', 'Display 802.1X status'),
                ],
                'sFlow / NetStream': [
                    ('sflow agent ip <ip>', 'Set sFlow agent IP'),
                    ('sflow collector <id> ip <ip>', 'Configure sFlow collector'),
                    ('sflow sampling-rate <n> interface <iface>', 'Set sFlow sampling rate'),
                    ('netstream sampler random packets <n> inbound', 'Configure NetStream sampling'),
                    ('netstream export ip host <ip> <port>', 'Configure NetStream exporter'),
                    ('display sflow', 'Display sFlow configuration'),
                ],
                'OSPF': [
                    ('ospf <id>', 'Enable OSPF process'),
                    ('ospf <id> router-id <ip>', 'Enable OSPF with router ID'),
                    ('area <id>', 'Enter OSPF area configuration'),
                    ('network <net> <wildcard>', 'Advertise network in OSPF'),
                    ('stub', 'Configure stub area'),
                    ('nssa', 'Configure NSSA area'),
                    ('stub no-summary', 'Configure totally stubby area'),
                    ('nssa no-summary', 'Configure totally NSSA'),
                    ('default-route-advertise', 'Advertise default route'),
                    ('default-route-advertise always', 'Always advertise default route'),
                    ('silent-interface <iface>', 'Suppress OSPF hellos on interface'),
                    ('bandwidth-reference <mbps>', 'Set reference bandwidth for cost calc'),
                    ('maximum load-balancing <n>', 'Set max equal-cost paths'),
                    ('log-peer-change', 'Log OSPF neighbor state changes'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route rip', 'Redistribute RIP into OSPF'),
                    ('import-route bgp', 'Redistribute BGP into OSPF'),
                    ('interface <iface>', 'Enter interface view'),
                    ('ospf cost <cost>', 'Set OSPF interface cost'),
                    ('ospf network-type broadcast', 'Set as broadcast network type'),
                    ('ospf network-type p2p', 'Set as point-to-point'),
                    ('ospf timer hello <sec>', 'Set hello interval'),
                    ('ospf dr-priority <n>', 'Set DR priority'),
                    ('ospf bfd enable', 'Enable BFD for OSPF'),
                    ('display ospf', 'Display OSPF process information'),
                    ('display ospf peer', 'Display OSPF neighbors'),
                    ('display ospf peer verbose', 'Detailed OSPF neighbor info'),
                    ('display ospf interface', 'Display OSPF interface status'),
                    ('display ospf interface brief', 'Brief OSPF interface summary'),
                    ('display ospf lsdb', 'Display OSPF LSDB'),
                    ('display ospf lsdb router', 'Show Type-1 LSAs'),
                    ('display ospf lsdb network', 'Show Type-2 LSAs'),
                    ('display ospf lsdb summary', 'Show Type-3 LSAs'),
                    ('display ospf lsdb ase', 'Show Type-5 LSAs'),
                    ('display ospf lsdb nssa', 'Show Type-7 LSAs'),
                    ('display ospf routing', 'Display OSPF routing table'),
                    ('display ospf brief', 'OSPF process brief summary'),
                    ('display ospf error', 'Display OSPF error statistics'),
                    ('display ospf packet', 'Display OSPF packet statistics'),
                    ('display ospf spf-results', 'Display SPF calculation results'),
                    ('reset ospf <id> statistics', 'Clear OSPF statistics'),
                    ('reset ospf <id> process', 'Reset OSPF process'),
                ],
                'BGP': [
                    ('bgp <asn>', 'Enable BGP process'),
                    ('router-id <ip>', 'Set BGP router ID'),
                    ('peer <ip> as-number <asn>', 'Configure BGP neighbor'),
                    ('peer <ip> description <text>', 'Set neighbor description'),
                    ('peer <ip> connect-interface <iface>', 'Set update source interface'),
                    ('peer <ip> ebgp-max-hop <ttl>', 'Set eBGP multihop TTL'),
                    ('peer <ip> password simple <key>', 'Set MD5 authentication'),
                    ('peer <ip> timer <keepalive> <holdtime>', 'Set BGP timers'),
                    ('peer <ip> route-policy <name> import', 'Apply route-policy to inbound'),
                    ('peer <ip> route-policy <name> export', 'Apply route-policy to outbound'),
                    ('peer <ip> ip-prefix <name> import', 'Apply prefix-list inbound'),
                    ('peer <ip> ip-prefix <name> export', 'Apply prefix-list outbound'),
                    ('peer <ip> as-path-filter <n> import', 'Apply AS-path filter inbound'),
                    ('peer <ip> as-path-filter <n> export', 'Apply AS-path filter outbound'),
                    ('peer <ip> preferred-value <0-65535>', 'Set preferred value for neighbor'),
                    ('peer <ip> next-hop-local', 'Set next-hop to self'),
                    ('peer <ip> advertise-community', 'Send community attribute'),
                    ('peer <ip> enable', 'Activate neighbor in IPv4 unicast AF'),
                    ('ipv4-family unicast', 'Enter IPv4 unicast address-family'),
                    ('ipv6-family unicast', 'Enter IPv6 unicast address-family'),
                    ('network <net> <mask>', 'Advertise network in BGP'),
                    ('aggregate <net> <mask>', 'Create aggregate route'),
                    ('aggregate <net> <mask> detail-suppressed', 'Advertise only the aggregate'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route ospf', 'Redistribute OSPF into BGP'),
                    ('import-route rip', 'Redistribute RIP into BGP'),
                    ('default-route-advertise', 'Advertise default route'),
                    ('maximum load-balancing <n>', 'Set max equal-cost BGP paths'),
                    ('display bgp all', 'Display all BGP routing tables'),
                    ('display bgp routing-table', 'Display BGP IPv4 unicast routing table'),
                    ('display bgp routing-table summary', 'BGP routing table summary'),
                    ('display bgp peer', 'Display BGP neighbor summary'),
                    ('display bgp peer <ip> verbose', 'Detailed neighbor info'),
                    ('display bgp peer <ip> routes', 'Routes from specific neighbor'),
                    ('display bgp peer <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('display bgp routing-table <net>', 'Show BGP entry for network'),
                    ('display bgp routing-table community <community>', 'Routes with community'),
                    ('display bgp routing-table regexp <regex>', 'Routes matching AS-path regex'),
                    ('display bgp routing-table dampened', 'Show dampened routes'),
                    ('display bgp ipv6 routing-table', 'Show IPv6 BGP table'),
                    ('display bgp ipv6 peer', 'Show IPv6 BGP neighbors'),
                    ('display bgp error', 'Display BGP error statistics'),
                    ('reset bgp all', 'Reset all BGP sessions'),
                    ('reset bgp <ip>', 'Reset specific BGP session'),
                    ('reset bgp all soft', 'Soft reset all BGP sessions'),
                ],
                'IS-IS': [
                    ('isis <id>', 'Enable IS-IS process'),
                    ('network-entity <nsap>', 'Set IS-IS Network Entity Title (NET)'),
                    ('is-level level-1', 'Set IS-IS level to L1 only'),
                    ('is-level level-2', 'Set IS-IS level to L2 only'),
                    ('cost-style wide', 'Enable wide metrics'),
                    ('cost-style compatible', 'Enable compatible wide/narrow metrics'),
                    ('log-peer-change', 'Log IS-IS adjacency changes'),
                    ('maximum load-balancing <n>', 'Set max equal-cost paths'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route ospf', 'Redistribute OSPF into IS-IS'),
                    ('import-route bgp', 'Redistribute BGP into IS-IS'),
                    ('import-route rip', 'Redistribute RIP into IS-IS'),
                    ('default-route-advertise', 'Advertise default route into IS-IS'),
                    ('interface <iface>', 'Enter interface view'),
                    ('isis enable <id>', 'Enable IS-IS on interface'),
                    ('isis circuit-type level-1', 'Set circuit type to L1'),
                    ('isis circuit-type level-2', 'Set circuit type to L2 only'),
                    ('isis cost <cost>', 'Set IS-IS interface cost'),
                    ('isis timer hello <sec>', 'Set hello interval'),
                    ('isis dis-priority <n>', 'Set DIS priority'),
                    ('isis network-type broadcast', 'Set as broadcast network'),
                    ('isis network-type p2p', 'Set as point-to-point'),
                    ('isis bfd enable', 'Enable BFD for IS-IS'),
                    ('isis silent', 'Enable silent mode on interface'),
                    ('display isis', 'Display IS-IS process information'),
                    ('display isis peer', 'Display IS-IS neighbors'),
                    ('display isis peer verbose', 'Detailed IS-IS neighbor info'),
                    ('display isis lsdb', 'Display IS-IS link-state database'),
                    ('display isis lsdb verbose', 'Verbose LSP display with TLVs'),
                    ('display isis lsdb level-1', 'Display L1 LSDB'),
                    ('display isis lsdb level-2', 'Display L2 LSDB'),
                    ('display isis route', 'Display IS-IS routing table'),
                    ('display isis interface', 'Display IS-IS interface status'),
                    ('display isis interface brief', 'Brief IS-IS interface summary'),
                    ('display isis spf-results', 'Display SPF calculation results'),
                    ('display isis error', 'Display IS-IS error statistics'),
                    ('display isis packet statistics', 'Display IS-IS packet stats'),
                    ('reset isis <id> statistics', 'Clear IS-IS statistics'),
                ],
                'RIP': [
                    ('rip <id>', 'Enable RIP process'),
                    ('version 2', 'Use RIPv2'),
                    ('network <net>', 'Advertise network in RIP'),
                    ('undo summary', 'Disable automatic route summarization'),
                    ('silent-interface <iface>', 'Stop sending RIP updates on interface'),
                    ('default-route-advertise', 'Advertise default route in RIP'),
                    ('default-route-advertise cost <n>', 'Advertise default with cost'),
                    ('maximum load-balancing <n>', 'Set max equal-cost RIP paths'),
                    ('preference <1-255>', 'Set RIP administrative distance'),
                    ('timer update <sec>', 'Set update timer'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route ospf', 'Redistribute OSPF into RIP'),
                    ('import-route bgp', 'Redistribute BGP into RIP'),
                    ('interface <iface>', 'Enter interface view'),
                    ('rip version <1|2>', 'Set RIP version on interface'),
                    ('rip authentication-mode simple cipher <key>', 'Set RIP authentication'),
                    ('rip metricin <n>', 'Set input metric adjustment'),
                    ('rip metricout <n>', 'Set output metric adjustment'),
                    ('display rip <id>', 'Display RIP process information'),
                    ('display rip <id> database', 'Display RIP routing database'),
                    ('display rip <id> route', 'Display RIP routing table'),
                    ('display rip <id> neighbor', 'Display RIP neighbors'),
                    ('display rip <id> interface', 'Display RIP interface status'),
                    ('display rip <id> status', 'Display RIP status and timers'),
                    ('reset rip <id> process', 'Reset RIP process'),
                ],
                'QoS / CoS / DSCP': [
                    ('traffic classifier <name> operator or', 'Create traffic classifier'),
                    ('traffic behavior <name>', 'Create traffic behavior'),
                    ('traffic policy <name>', 'Create traffic policy'),
                    ('classifier <name> behavior <name>', 'Bind classifier and behavior in policy'),
                    ('remark dscp <value>', 'Remark DSCP value in behavior'),
                    ('car cir <bps> pir <bps>', 'Configure Committed/Peak Information Rate'),
                    ('traffic-policy <name> inbound', 'Apply policy inbound on interface'),
                    ('traffic-policy <name> outbound', 'Apply policy outbound on interface'),
                    ('display traffic-policy applied-record', 'Display QoS policy application status'),
                ],
                'Trunk': [
                    ('interface <iface>', 'Enter interface view'),
                    ('port link-type trunk', 'Set port as trunk'),
                    ('port trunk allow-pass vlan <ids>', 'Allow VLANs on trunk'),
                    ('port trunk pvid vlan <id>', 'Set native/PVID VLAN on trunk'),
                    ('port trunk allow-pass vlan all', 'Allow all VLANs on trunk'),
                    ('display port vlan', 'Display VLAN configuration per port'),
                ],
                'Firmware': [
                    ('display version', 'Show current VRP version and hardware'),
                    ('dir', 'List files in current storage'),
                    ('tftp <ip> get <remote-file> <local-file>', 'Download firmware from TFTP server'),
                    ('startup system-software <file>', 'Set firmware image for next boot'),
                    ('display startup', 'Show next boot software file'),
                    ('reboot', 'Reboot to apply new firmware'),
                ],
            },
            'H3C': {
                'Navigation': [
                    ('system-view', 'Enter system view'),
                    ('quit', 'Exit current view'),
                    ('return', 'Return to user view'),
                ],
                'Display Commands': [
                    ('display current-configuration', 'Show running configuration'),
                    ('display saved-configuration', 'Show saved configuration'),
                    ('display interface brief', 'Quick interface overview'),
                    ('display interface <iface>', 'Detailed interface information'),
                    ('display vlan all', 'Display all VLANs'),
                    ('display vlan <id>', 'Show specific VLAN details'),
                    ('display ip routing-table', 'Show routing table'),
                    ('display ip routing-table protocol static', 'Show static routes'),
                    ('display arp', 'Display ARP table'),
                    ('display mac-address', 'Display MAC address table'),
                    ('display mac-address vlan <id>', 'MAC table filtered by VLAN'),
                    ('display dhcp server ip-in-use', 'Show active DHCP leases'),
                    ('display dhcp server pool', 'Show DHCP pool details'),
                    ('display acl all', 'Show all configured ACLs'),
                    ('display link-aggregation summary', 'Show LACP/aggregation summary'),
                    ('display link-aggregation verbose <id>', 'Detailed aggregation group info'),
                    ('display ip vpn-instance', 'List configured VPN-instances (VRFs)'),
                    ('display ip routing-table vpn-instance <name>', 'VRF routing table'),
                    ('display version', 'Show system version'),
                    ('display clock', 'Show system clock'),
                    ('display logbuffer', 'Show log buffer'),
                ],
                'Interfaces': [
                    ('interface GigabitEthernet1/0/1', 'Enter interface view'),
                    ('ip address <ip> <mask>', 'Assign IP address'),
                    ('undo shutdown', 'Enable interface'),
                    ('shutdown', 'Disable interface'),
                    ('port link-type trunk', 'Set as trunk'),
                    ('port link-type access', 'Set as access'),
                    ('port access vlan <id>', 'Assign access VLAN'),
                    ('port trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('port trunk permit vlan all', 'Allow all VLANs on trunk'),
                    ('dhcp select relay', 'Enable DHCP relay on interface'),
                    ('dhcp relay server-address <ip>', 'Set DHCP server for relay'),
                    ('description <text>', 'Set interface description'),
                ],
                'VLANs': [
                    ('vlan <id>', 'Create or enter VLAN view'),
                    ('vlan <start> to <end>', 'Create a range of VLANs'),
                    ('name <name>', 'Assign name to VLAN'),
                    ('port trunk permit vlan <ids>', 'Allow specific VLANs on trunk'),
                    ('undo vlan <id>', 'Delete a VLAN'),
                    ('display vlan all', 'Show all VLANs'),
                ],
                'ACLs': [
                    ('acl basic <2000-2999>', 'Create basic (standard) ACL'),
                    ('acl advanced <3000-3999>', 'Create advanced (extended) ACL'),
                    ('acl name <name> basic', 'Create named basic ACL'),
                    ('acl name <name> advanced', 'Create named advanced ACL'),
                    ('rule permit source <ip> <wildcard>', 'Permit source (basic ACL)'),
                    ('rule deny source <ip> <wildcard>', 'Deny source (basic ACL)'),
                    ('rule permit tcp source <src> <wc> destination <dst> <wc> destination-port eq <port>', 'Permit TCP to port'),
                    ('rule deny ip source any destination any', 'Deny all IP'),
                    ('packet-filter inbound ipv6-acl <number>', 'Apply ACL inbound on interface'),
                    ('packet-filter outbound acl <number>', 'Apply ACL outbound on interface'),
                    ('display acl all', 'Show all ACLs'),
                    ('undo acl <number>', 'Delete an ACL'),
                ],
                'DHCP': [
                    ('dhcp enable', 'Enable DHCP globally'),
                    ('dhcp server ip-pool <name>', 'Create DHCP pool'),
                    ('network <net> mask <mask>', 'Set pool network'),
                    ('gateway-list <ip>', 'Set default gateway for clients'),
                    ('dns-list <ip1> <ip2>', 'Set DNS servers for clients'),
                    ('expired day <n>', 'Set lease duration in days'),
                    ('dhcp server forbidden-ip <start> <end>', 'Exclude IP range from pool'),
                    ('display dhcp server ip-in-use', 'Show active DHCP leases'),
                    ('display dhcp server pool', 'Show pool configuration'),
                    ('reset dhcp server ip-in-use pool <name>', 'Clear leases for a pool'),
                ],
                'LACP / Link-Aggregation': [
                    ('interface Bridge-Aggregation <id>', 'Create aggregation interface (L2)'),
                    ('interface Route-Aggregation <id>', 'Create aggregation interface (L3)'),
                    ('link-aggregation mode dynamic', 'Set to LACP dynamic mode'),
                    ('interface GigabitEthernet1/0/1', 'Enter member interface'),
                    ('port link-aggregation group <id>', 'Add port to aggregation group'),
                    ('lacp port-priority <0-65535>', 'Set LACP port priority'),
                    ('lacp system-priority <0-65535>', 'Set LACP system priority'),
                    ('display link-aggregation summary', 'Show all aggregation groups'),
                    ('display link-aggregation verbose <id>', 'Detailed aggregation info'),
                ],
                'VRF (VPN-Instance)': [
                    ('ip vpn-instance <name>', 'Create VPN-instance'),
                    ('ipv4-family', 'Enter IPv4 address-family'),
                    ('route-distinguisher <asn>:<id>', 'Set route distinguisher'),
                    ('vpn-target <rt> export-extcommunity', 'Set export route-target'),
                    ('vpn-target <rt> import-extcommunity', 'Set import route-target'),
                    ('interface <iface>', 'Enter interface'),
                    ('ip binding vpn-instance <name>', 'Bind interface to VPN-instance'),
                    ('ip address <ip> <mask>', 'Assign IP after VPN binding'),
                    ('ip route-static vpn-instance <name> <net> <mask> <gw>', 'Add static route in VPN-instance'),
                    ('display ip vpn-instance', 'List all VPN-instances'),
                    ('display ip routing-table vpn-instance <name>', 'Show VRF routing table'),
                ],
                'VRRP': [
                    ('interface <iface>', 'Enter interface for VRRP config'),
                    ('vrrp vrid <group> virtual-ip <ip>', 'Set virtual IP for VRRP group'),
                    ('vrrp vrid <group> priority <0-255>', 'Set VRRP priority (default 100; higher = master)'),
                    ('vrrp vrid <group> preempt-mode timer delay <sec>', 'Set preemption delay'),
                    ('undo vrrp vrid <group> preempt-mode', 'Disable preemption'),
                    ('vrrp vrid <group> timer advertise <sec>', 'Set advertisement interval'),
                    ('vrrp vrid <group> authentication-mode simple plain <key>', 'Set plain-text auth'),
                    ('vrrp vrid <group> track interface <iface> reduced <val>', 'Track interface, reduce priority on failure'),
                    ('display vrrp', 'Display all VRRP groups'),
                    ('display vrrp brief', 'VRRP summary table'),
                    ('display vrrp verbose', 'Detailed VRRP information'),
                ],
                'System': [
                    ('sysname <name>', 'Set hostname'),
                    ('save', 'Save configuration'),
                    ('undo <command>', 'Negate configuration'),
                    ('reboot', 'Reboot device'),
                ],
                'Users': [
                    ('local-user <name>', 'Create or enter local user view'),
                    ('password cipher <pass>', 'Set encrypted password for user'),
                    ('password simple <pass>', 'Set plaintext password for user'),
                    ('service-type ssh telnet terminal', 'Set user access types'),
                    ('authorization-attribute level <0-3>', 'Set user privilege level (0-3)'),
                    ('undo local-user <name>', 'Delete a local user'),
                    ('display local-user', 'List all configured local users'),
                ],
                'SSH': [
                    ('ssh server enable', 'Enable SSH server'),
                    ('ssh server port <port>', 'Change SSH server port'),
                    ('public-key local create rsa', 'Generate RSA key pair'),
                    ('public-key local create ecdsa', 'Generate ECDSA key pair'),
                    ('display ssh server status', 'Display SSH server status'),
                    ('user-interface vty 0 4', 'Enter VTY line configuration'),
                    ('authentication-mode scheme', 'Use AAA (HWTACACS/RADIUS/local) for VTY'),
                    ('protocol inbound ssh', 'Allow only SSH on VTY lines'),
                ],
                'Telnet': [
                    ('telnet server enable', 'Enable Telnet server'),
                    ('telnet server disable', 'Disable Telnet server'),
                    ('user-interface vty 0 4', 'Enter VTY line configuration'),
                    ('authentication-mode scheme', 'Use AAA for VTY authentication'),
                    ('protocol inbound telnet', 'Allow only Telnet on VTY lines'),
                    ('display telnet server status', 'Display Telnet server status'),
                ],
                'SNMP': [
                    ('snmp-agent', 'Enable SNMP agent'),
                    ('snmp-agent community read <name>', 'Configure read-only community'),
                    ('snmp-agent community write <name>', 'Configure read-write community'),
                    ('snmp-agent sys-info location <text>', 'Set SNMP system location'),
                    ('snmp-agent sys-info contact <text>', 'Set SNMP system contact'),
                    ('snmp-agent target-host trap address udp-domain <ip> params securityname <name>', 'Configure trap host'),
                    ('display snmp-agent community', 'Display SNMP communities'),
                    ('display snmp-agent sys-info', 'Display SNMP system info'),
                ],

                'Spanning-Tree': [
                    ('stp mode stp', 'Enable STP (802.1D) mode'),
                    ('stp mode rstp', 'Enable RSTP (802.1w) mode'),
                    ('stp mode mstp', 'Enable MSTP (802.1s) mode (default)'),
                    ('stp region-configuration', 'Enter MST region configuration'),
                    ('region-name <name>', 'Set MST region name'),
                    ('revision-level <n>', 'Set MST revision level'),
                    ('instance <id> vlan <vlan-list>', 'Map VLANs to MST instance'),
                    ('active region-configuration', 'Activate MST region config'),
                    ('display stp region-configuration', 'Show MST region configuration'),
                    ('stp priority <0-61440>', 'Set bridge priority (step 4096)'),
                    ('stp instance <id> priority <0-61440>', 'Set MST instance priority'),
                    ('stp root primary', 'Set as primary root (priority 0)'),
                    ('stp root secondary', 'Set as secondary root (priority 4096)'),
                    ('stp edged-port enable', 'Enable Edge Port (PortFast equivalent)'),
                    ('stp bpdu-protection', 'Enable BPDU protection globally'),
                    ('stp root-protection', 'Enable Root Protection on port'),
                    ('stp loop-protection', 'Enable Loop Protection on port'),
                    ('stp tc-protection', 'Enable TC-BPDU attack protection'),
                    ('stp cost <cost>', 'Set STP port cost on interface'),
                    ('stp port priority <0-240>', 'Set STP port priority'),
                    ('stp max-hops <n>', 'Set MSTP max hops (default 20)'),
                    ('undo stp enable', 'Disable STP globally'),
                    ('display stp', 'Display STP global status'),
                    ('display stp brief', 'STP brief port status summary'),
                    ('display stp interface <iface>', 'STP status for specific interface'),
                    ('display stp instance <id>', 'Display MST instance status'),
                    ('display stp abnormal-port', 'Show ports in abnormal STP state'),
                    ('display stp tc', 'Display TC-BPDU statistics'),
                    ('reset stp statistics', 'Clear STP statistics'),
                ],
                'Port Statistics': [
                    ('display interface', 'Display statistics for all interfaces'),
                    ('display interface brief', 'Brief status of all interfaces'),
                    ('display interface <iface>', 'Detailed statistics for specific interface'),
                    ('display interface transceiver', 'Display optical transceiver info'),
                    ('display interface transceiver verbose', 'Detailed transceiver diagnostics'),
                    ('display counters inbound interface', 'Display inbound traffic counters'),
                    ('display counters outbound interface', 'Display outbound traffic counters'),
                    ('display interface <iface> counters', 'Packet counters for interface'),
                    ('display interface <iface> counters error', 'Error counters for interface'),
                    ('display interface <iface> statistics', 'Traffic statistics for interface'),
                    ('display link-aggregation summary', 'Show LACP/aggregation summary'),
                    ('display link-aggregation verbose <id>', 'Detailed aggregation group info'),
                    ('display lacp statistics', 'Display LACP statistics'),
                    ('display lldp neighbor brief', 'LLDP neighbor summary'),
                    ('display mac-address interface <iface>', 'MAC addresses on specific port'),
                    ('display mac-address summary', 'MAC address table summary'),
                    ('reset counters interface <iface>', 'Clear counters for specific interface'),
                ],
                'OSPF': [
                    ('ospf <id>', 'Enable OSPF process'),
                    ('ospf <id> router-id <ip>', 'Enable OSPF with router ID'),
                    ('area <id>', 'Enter OSPF area configuration'),
                    ('network <net> <wildcard>', 'Advertise network in OSPF'),
                    ('stub', 'Configure stub area'),
                    ('nssa', 'Configure NSSA area'),
                    ('stub no-summary', 'Configure totally stubby area'),
                    ('default-route-advertise', 'Advertise default route'),
                    ('default-route-advertise always', 'Always advertise default route'),
                    ('silent-interface <iface>', 'Suppress OSPF hellos on interface'),
                    ('maximum load-balancing <n>', 'Set max equal-cost paths'),
                    ('log-peer-change', 'Log OSPF neighbor state changes'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route rip', 'Redistribute RIP into OSPF'),
                    ('import-route bgp', 'Redistribute BGP into OSPF'),
                    ('interface <iface>', 'Enter interface view'),
                    ('ospf cost <cost>', 'Set OSPF interface cost'),
                    ('ospf network-type p2p', 'Set as point-to-point'),
                    ('ospf timer hello <sec>', 'Set hello interval'),
                    ('ospf dr-priority <n>', 'Set DR priority'),
                    ('ospf bfd enable', 'Enable BFD for OSPF'),
                    ('display ospf', 'Display OSPF process information'),
                    ('display ospf peer', 'Display OSPF neighbors'),
                    ('display ospf peer verbose', 'Detailed OSPF neighbor info'),
                    ('display ospf interface', 'Display OSPF interface status'),
                    ('display ospf interface brief', 'Brief OSPF interface summary'),
                    ('display ospf lsdb', 'Display OSPF LSDB'),
                    ('display ospf lsdb router', 'Show Type-1 LSAs'),
                    ('display ospf lsdb network', 'Show Type-2 LSAs'),
                    ('display ospf lsdb summary', 'Show Type-3 LSAs'),
                    ('display ospf lsdb ase', 'Show Type-5 LSAs'),
                    ('display ospf routing', 'Display OSPF routing table'),
                    ('display ospf brief', 'OSPF process brief summary'),
                    ('display ospf error', 'Display OSPF error statistics'),
                    ('reset ospf <id> statistics', 'Clear OSPF statistics'),
                    ('reset ospf <id> process', 'Reset OSPF process'),
                ],
                'BGP': [
                    ('bgp <asn>', 'Enable BGP process'),
                    ('router-id <ip>', 'Set BGP router ID'),
                    ('peer <ip> as-number <asn>', 'Configure BGP neighbor'),
                    ('peer <ip> description <text>', 'Set neighbor description'),
                    ('peer <ip> connect-interface <iface>', 'Set update source interface'),
                    ('peer <ip> ebgp-max-hop <ttl>', 'Set eBGP multihop TTL'),
                    ('peer <ip> password simple <key>', 'Set MD5 authentication'),
                    ('peer <ip> route-policy <name> import', 'Apply route-policy to inbound'),
                    ('peer <ip> route-policy <name> export', 'Apply route-policy to outbound'),
                    ('peer <ip> ip-prefix <name> import', 'Apply prefix-list inbound'),
                    ('peer <ip> ip-prefix <name> export', 'Apply prefix-list outbound'),
                    ('peer <ip> preferred-value <0-65535>', 'Set preferred value'),
                    ('peer <ip> next-hop-local', 'Set next-hop to self'),
                    ('peer <ip> advertise-community', 'Send community attribute'),
                    ('peer <ip> enable', 'Activate neighbor in IPv4 unicast AF'),
                    ('ipv4-family unicast', 'Enter IPv4 unicast address-family'),
                    ('ipv6-family unicast', 'Enter IPv6 unicast address-family'),
                    ('network <net> <mask>', 'Advertise network in BGP'),
                    ('aggregate <net> <mask>', 'Create aggregate route'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route ospf', 'Redistribute OSPF into BGP'),
                    ('import-route rip', 'Redistribute RIP into BGP'),
                    ('default-route-advertise', 'Advertise default route'),
                    ('maximum load-balancing <n>', 'Set max equal-cost BGP paths'),
                    ('display bgp routing-table', 'Display BGP IPv4 unicast routing table'),
                    ('display bgp routing-table summary', 'BGP routing table summary'),
                    ('display bgp peer', 'Display BGP neighbor summary'),
                    ('display bgp peer <ip> verbose', 'Detailed neighbor info'),
                    ('display bgp peer <ip> routes', 'Routes from specific neighbor'),
                    ('display bgp peer <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('display bgp ipv6 routing-table', 'Show IPv6 BGP table'),
                    ('reset bgp all', 'Reset all BGP sessions'),
                    ('reset bgp <ip>', 'Reset specific BGP session'),
                    ('reset bgp all soft', 'Soft reset all BGP sessions'),
                ],
                'IS-IS': [
                    ('isis <id>', 'Enable IS-IS process'),
                    ('network-entity <nsap>', 'Set IS-IS Network Entity Title (NET)'),
                    ('is-level level-1', 'Set IS-IS level to L1 only'),
                    ('is-level level-2', 'Set IS-IS level to L2 only'),
                    ('cost-style wide', 'Enable wide metrics'),
                    ('cost-style compatible', 'Enable compatible wide/narrow metrics'),
                    ('log-peer-change', 'Log IS-IS adjacency changes'),
                    ('maximum load-balancing <n>', 'Set max equal-cost paths'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route ospf', 'Redistribute OSPF into IS-IS'),
                    ('import-route bgp', 'Redistribute BGP into IS-IS'),
                    ('import-route rip', 'Redistribute RIP into IS-IS'),
                    ('default-route-advertise', 'Advertise default route into IS-IS'),
                    ('interface <iface>', 'Enter interface view'),
                    ('isis enable <id>', 'Enable IS-IS on interface'),
                    ('isis circuit-type level-1', 'Set circuit type to L1'),
                    ('isis circuit-type level-2', 'Set circuit type to L2 only'),
                    ('isis cost <cost>', 'Set IS-IS interface cost'),
                    ('isis timer hello <sec>', 'Set hello interval'),
                    ('isis dis-priority <n>', 'Set DIS priority'),
                    ('isis network-type p2p', 'Set as point-to-point'),
                    ('isis bfd enable', 'Enable BFD for IS-IS'),
                    ('display isis', 'Display IS-IS process information'),
                    ('display isis peer', 'Display IS-IS neighbors'),
                    ('display isis peer verbose', 'Detailed IS-IS neighbor info'),
                    ('display isis lsdb', 'Display IS-IS link-state database'),
                    ('display isis lsdb verbose', 'Verbose LSP display with TLVs'),
                    ('display isis route', 'Display IS-IS routing table'),
                    ('display isis interface', 'Display IS-IS interface status'),
                    ('display isis spf-results', 'Display SPF calculation results'),
                    ('display isis error', 'Display IS-IS error statistics'),
                    ('reset isis <id> statistics', 'Clear IS-IS statistics'),
                ],
                'RIP': [
                    ('rip <id>', 'Enable RIP process'),
                    ('version 2', 'Use RIPv2'),
                    ('network <net>', 'Advertise network in RIP'),
                    ('undo summary', 'Disable automatic route summarization'),
                    ('silent-interface <iface>', 'Stop sending RIP updates on interface'),
                    ('default-route-advertise', 'Advertise default route in RIP'),
                    ('maximum load-balancing <n>', 'Set max equal-cost RIP paths'),
                    ('preference <1-255>', 'Set RIP administrative distance'),
                    ('import-route connected', 'Redistribute connected routes'),
                    ('import-route static', 'Redistribute static routes'),
                    ('import-route ospf', 'Redistribute OSPF into RIP'),
                    ('import-route bgp', 'Redistribute BGP into RIP'),
                    ('interface <iface>', 'Enter interface view'),
                    ('rip version <1|2>', 'Set RIP version on interface'),
                    ('rip authentication-mode simple cipher <key>', 'Set RIP authentication'),
                    ('display rip <id>', 'Display RIP process information'),
                    ('display rip <id> database', 'Display RIP routing database'),
                    ('display rip <id> route', 'Display RIP routing table'),
                    ('display rip <id> neighbor', 'Display RIP neighbors'),
                    ('display rip <id> interface', 'Display RIP interface status'),
                    ('reset rip <id> process', 'Reset RIP process'),
                ],
                'Debug': [
                    ('terminal monitor', 'Enable terminal monitoring'),
                    ('terminal debugging', 'Enable debug output to terminal'),
                    ('debugging ip icmp', 'Debug ICMP packets'),
                    ('debugging ospf packet', 'Debug OSPF packets'),
                    ('undo debugging all', 'Disable all debug output'),
                    ('display debugging', 'Display active debug flags'),
                ],
                'Log': [
                    ('info-center enable', 'Enable information center (logging)'),
                    ('info-center loghost <ip>', 'Send logs to remote syslog server'),
                    ('display logbuffer', 'Display system log buffer'),
                    ('display trapbuffer', 'Display trap (event) buffer'),
                ],
                'LLDP': [
                    ('lldp enable', 'Enable LLDP globally'),
                    ('lldp enable interface <iface>', 'Enable LLDP on interface'),
                    ('display lldp neighbor brief', 'Display LLDP neighbors (brief)'),
                    ('display lldp neighbor', 'Display LLDP neighbors (detailed)'),
                ],
                'DHCP Server': [
                    ('dhcp enable', 'Enable DHCP globally'),
                    ('ip pool <name>', 'Create DHCP address pool'),
                    ('network <net> mask <mask>', 'Set pool network (inside pool)'),
                    ('gateway-list <ip>', 'Set default gateway for clients'),
                    ('dns-list <ip1> <ip2>', 'Set DNS servers for clients'),
                    ('lease day <n>', 'Set lease duration in days'),
                    ('display dhcp server ip-in-use', 'Show active DHCP leases'),
                ],
                'DHCP Snooping': [
                    ('dhcp snooping enable', 'Enable DHCP Snooping globally'),
                    ('dhcp snooping enable vlan <id>', 'Enable DHCP Snooping on VLAN'),
                    ('dhcp snooping trusted interface <iface>', 'Set interface as trusted'),
                    ('display dhcp snooping', 'Display DHCP Snooping status'),
                ],
                'NTP': [
                    ('ntp-service unicast-server <ip>', 'Configure NTP server'),
                    ('ntp-service source-interface <iface>', 'Set source interface for NTP'),
                    ('display ntp-service status', 'Display NTP synchronization status'),
                ],
                '802.1X': [
                    ('dot1x enable', 'Enable 802.1X globally'),
                    ('dot1x enable interface <iface>', 'Enable 802.1X on interface'),
                    ('display dot1x', 'Display 802.1X status'),
                ],
                'sFlow / NetStream': [
                    ('sflow agent ip <ip>', 'Set sFlow agent IP'),
                    ('sflow collector <id> ip <ip>', 'Configure sFlow collector'),
                    ('sflow sampling-rate <n> interface <iface>', 'Set sFlow sampling rate'),
                    ('display sflow', 'Display sFlow configuration'),
                ],
                'QoS / CoS / DSCP': [
                    ('traffic classifier <name> operator or', 'Create traffic classifier'),
                    ('traffic behavior <name>', 'Create traffic behavior'),
                    ('traffic policy <name>', 'Create traffic policy'),
                    ('classifier <name> behavior <name>', 'Bind classifier and behavior in policy'),
                    ('remark dscp <value>', 'Remark DSCP value in behavior'),
                    ('car cir <bps> pir <bps>', 'Configure Committed/Peak Information Rate'),
                    ('traffic-policy <name> inbound', 'Apply policy inbound on interface'),
                    ('traffic-policy <name> outbound', 'Apply policy outbound on interface'),
                ],
                'Trunk': [
                    ('interface <iface>', 'Enter interface view'),
                    ('port link-type trunk', 'Set port as trunk'),
                    ('port trunk allow-pass vlan <ids>', 'Allow VLANs on trunk'),
                    ('port trunk pvid vlan <id>', 'Set native/PVID VLAN on trunk'),
                    ('display port vlan', 'Display VLAN configuration per port'),
                ],
                'Firmware': [
                    ('display version', 'Show current Comware version'),
                    ('dir', 'List files in storage'),
                    ('tftp <ip> get <remote-file>', 'Download firmware via TFTP'),
                    ('boot-loader file flash:/<file> main', 'Set main boot image'),
                    ('display boot-loader', 'Show current and next boot images'),
                    ('reboot', 'Reboot to apply new firmware'),
                ],
            },
            'Juniper': {
                'Navigation': [
                    ('configure', 'Enter configuration mode'),
                    ('edit <path>', 'Navigate to configuration hierarchy'),
                    ('top', 'Go to top of configuration hierarchy'),
                    ('up', 'Go up one level in hierarchy'),
                    ('exit', 'Exit current mode'),
                ],
                'Show Commands': [
                    ('show configuration', 'Display full configuration'),
                    ('show configuration | display set', 'Show config in set-format commands'),
                    ('show interfaces terse', 'Quick interface overview'),
                    ('show interfaces <iface> detail', 'Detailed interface information'),
                    ('show route', 'Display routing table'),
                    ('show route table <instance>.inet.0', 'Routing table for a routing-instance'),
                    ('show arp', 'Display ARP table'),
                    ('show ethernet-switching table', 'Display MAC address table'),
                    ('show vlans', 'Display VLAN information'),
                    ('show spanning-tree interface', 'Show STP interface status'),
                    ('show dhcp server binding', 'Show active DHCP leases'),
                    ('show dhcp relay statistics', 'DHCP relay statistics'),
                    ('show firewall', 'Display firewall filter counters'),
                    ('show firewall filter <name>', 'Show specific filter hit counts'),
                    ('show lacp interfaces', 'Show LACP interface status'),
                    ('show lacp statistics interfaces <iface>', 'LACP statistics per interface'),
                    ('show chassis hardware', 'Display hardware inventory'),
                    ('show system uptime', 'Display system uptime'),
                    ('show bgp summary', 'Display BGP neighbor summary'),
                    ('show ospf neighbor', 'Display OSPF neighbors'),
                    ('show log messages | last 50', 'Show last 50 system log entries'),
                ],
                'Configuration': [
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix>', 'Assign IP'),
                    ('set interfaces <iface> unit 0 family inet filter input <name>', 'Apply firewall filter inbound'),
                    ('set interfaces <iface> unit 0 family inet filter output <name>', 'Apply firewall filter outbound'),
                    ('set routing-options static route <net> next-hop <ip>', 'Add static route'),
                    ('set firewall filter <name> term <term> ...', 'Configure firewall filter'),
                    ('delete <path>', 'Remove a configuration statement'),
                    ('commit', 'Apply configuration changes'),
                    ('commit check', 'Verify configuration without applying'),
                    ('rollback <n>', 'Rollback to a previous configuration'),
                ],
                'VLANs': [
                    ('set vlans <name> vlan-id <id>', 'Create VLAN'),
                    ('set vlans <name> l3-interface irb.<id>', 'Assign L3 interface to VLAN'),
                    ('set interfaces <iface> unit 0 family ethernet-switching vlan members <name>', 'Assign access VLAN'),
                    ('set interfaces <iface> unit 0 family ethernet-switching interface-mode trunk', 'Set port as trunk'),
                    ('set interfaces <iface> unit 0 family ethernet-switching vlan members [<v1> <v2>]', 'Set trunk allowed VLANs'),
                    ('set interfaces irb unit <id> family inet address <ip/prefix>', 'Assign IP to IRB (SVI)'),
                    ('show vlans', 'Show all VLANs'),
                ],
                'Firewall Filters (ACLs)': [
                    ('set firewall filter <name> term <term> from source-address <net/prefix>', 'Match source address'),
                    ('set firewall filter <name> term <term> from destination-address <net/prefix>', 'Match destination address'),
                    ('set firewall filter <name> term <term> from protocol tcp', 'Match protocol'),
                    ('set firewall filter <name> term <term> from destination-port <port>', 'Match destination port'),
                    ('set firewall filter <name> term <term> then accept', 'Action: accept'),
                    ('set firewall filter <name> term <term> then discard', 'Action: discard (silent drop)'),
                    ('set firewall filter <name> term <term> then reject', 'Action: reject (ICMP unreachable)'),
                    ('set firewall filter <name> term <term> then count <counter>', 'Action: count matched packets'),
                    ('set interfaces <iface> unit 0 family inet filter input <name>', 'Apply filter inbound'),
                    ('set interfaces <iface> unit 0 family inet filter output <name>', 'Apply filter outbound'),
                    ('show firewall filter <name>', 'Show filter counters'),
                ],
                'DHCP': [
                    ('set system services dhcp-local-server group <name> interface <iface>', 'Enable DHCP server on interface'),
                    ('set access address-assignment pool <name> family inet network <net/prefix>', 'Set pool network'),
                    ('set access address-assignment pool <name> family inet range <name> low <ip> high <ip>', 'Set IP range in pool'),
                    ('set access address-assignment pool <name> family inet dhcp-attributes router <ip>', 'Set default gateway'),
                    ('set access address-assignment pool <name> family inet dhcp-attributes name-server [<ip1> <ip2>]', 'Set DNS servers'),
                    ('set access address-assignment pool <name> family inet dhcp-attributes maximum-lease-time <sec>', 'Set max lease time'),
                    ('set forwarding-options helpers bootp server <ip>', 'Configure DHCP relay helper'),
                    ('set forwarding-options helpers bootp interface <iface>', 'Apply DHCP relay on interface'),
                    ('show dhcp server binding', 'Show active DHCP leases'),
                ],
                'LACP / Aggregated Ethernet': [
                    ('set chassis aggregated-devices ethernet device-count <n>', 'Set number of AE interfaces'),
                    ('set interfaces ae<id> aggregated-ether-options lacp active', 'Enable LACP active mode'),
                    ('set interfaces ae<id> aggregated-ether-options lacp passive', 'Enable LACP passive mode'),
                    ('set interfaces <iface> ether-options 802.3ad ae<id>', 'Add interface to AE group'),
                    ('set interfaces ae<id> unit 0 family inet address <ip/prefix>', 'Assign IP to AE interface'),
                    ('set interfaces ae<id> aggregated-ether-options minimum-links <n>', 'Set minimum active links'),
                    ('show lacp interfaces', 'Show LACP status for all AE interfaces'),
                    ('show interfaces ae<id> detail', 'Detailed AE interface info'),
                ],
                'VRF (Routing-Instance)': [
                    ('set routing-instances <name> instance-type vrf', 'Create VRF routing-instance'),
                    ('set routing-instances <name> interface <iface>.0', 'Assign interface to VRF'),
                    ('set routing-instances <name> route-distinguisher <asn>:<id>', 'Set route distinguisher'),
                    ('set routing-instances <name> vrf-target target:<asn>:<id>', 'Set VRF route-target'),
                    ('set routing-instances <name> routing-options static route <net> next-hop <ip>', 'Add static route in VRF'),
                    ('show route table <name>.inet.0', 'Display VRF routing table'),
                    ('show routing-instances', 'List all routing instances'),
                    ('ping routing-instance <name> <ip>', 'Ping within a specific VRF'),
                ],
                'VRRP': [
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> virtual-address <vip>', 'Create VRRP group with virtual IP'),
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> priority <0-255>', 'Set VRRP priority (default 100)'),
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> preempt', 'Enable preemption'),
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> advertise-interval <ms>', 'Set advertisement interval (milliseconds)'),
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> authentication-type simple', 'Enable simple authentication'),
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> authentication-key <key>', 'Set authentication key'),
                    ('set interfaces <iface> unit 0 family inet address <ip/prefix> vrrp-group <id> track interface <iface2> priority-cost <val>', 'Track interface, reduce priority on failure'),
                    ('show vrrp', 'Display all VRRP groups and states'),
                    ('show vrrp detail', 'Detailed VRRP information'),
                    ('show vrrp interface <iface>', 'VRRP state for specific interface'),
                    ('show vrrp statistics', 'VRRP packet statistics'),
                ],
                'System': [
                    ('set system host-name <name>', 'Set hostname'),
                    ('request system reboot', 'Reboot the device'),
                    ('request system snapshot', 'Create system snapshot'),
                ],
                'Users': [
                    ('set system login user <name> class super-user', 'Create super-user class account'),
                    ('set system login user <name> class operator', 'Create operator class account'),
                    ('set system login user <name> authentication encrypted-password <hash>', 'Set encrypted password'),
                    ('set system login user <name> authentication plain-text-password <pass>', 'Set plaintext password'),
                    ('delete system login user <name>', 'Delete a user account'),
                    ('show system login', 'Display configured login users'),
                ],
                'SSH': [
                    ('set system services ssh', 'Enable SSH service'),
                    ('set system services ssh protocol-version v2', 'Enable SSH version 2 only'),
                    ('set system services ssh root-login allow', 'Allow root login via SSH'),
                    ('set system services ssh root-login deny', 'Deny root login via SSH'),
                    ('set system services ssh rate-limit <n>', 'Set max unauthenticated connections per minute'),
                    ('show system services ssh', 'Display SSH service configuration'),
                ],
                'Telnet': [
                    ('set system services telnet', 'Enable Telnet service'),
                    ('delete system services telnet', 'Disable Telnet service'),
                    ('show system services telnet', 'Display Telnet service configuration'),
                ],
                'SNMP': [
                    ('set snmp community <name> authorization read-only', 'Create read-only SNMP community'),
                    ('set snmp community <name> authorization read-write', 'Create read-write SNMP community'),
                    ('set snmp location <text>', 'Set SNMP system location'),
                    ('set snmp contact <text>', 'Set SNMP system contact'),
                    ('set snmp trap-options source-address <ip>', 'Set source address for SNMP traps'),
                    ('set snmp target-parameters <name> parameters message-processing-model v2c', 'Configure SNMP v2c target parameters'),
                    ('show snmp community', 'Display SNMP communities'),
                    ('show snmp statistics', 'Display SNMP statistics'),
                ],

                'Spanning-Tree': [
                    ('set protocols stp interface <iface> disable', 'Disable STP on interface'),
                    ('set protocols rstp interface <iface> edge', 'Set port as edge port (PortFast)'),
                    ('set protocols rstp interface <iface> no-root-port', 'Enable Root Protection'),
                    ('set protocols rstp bridge-priority <0-61440>', 'Set bridge priority'),
                    ('set protocols mstp interface <iface> edge', 'Set MSTP edge port'),
                    ('set protocols mstp configuration-name <name>', 'Set MST region name'),
                    ('set protocols mstp revision-level <n>', 'Set MST revision level'),
                    ('set protocols mstp interface <iface> cost <cost>', 'Set MSTP port cost'),
                    ('show spanning-tree bridge', 'Display STP bridge information'),
                    ('show spanning-tree bridge brief', 'Brief STP bridge summary'),
                    ('show spanning-tree interface', 'Show STP interface status'),
                    ('show spanning-tree interface <iface>', 'STP status for specific interface'),
                    ('show spanning-tree statistics', 'Display STP statistics'),
                    ('show spanning-tree statistics interface <iface>', 'STP stats for interface'),
                    ('show spanning-tree topology', 'Display spanning-tree topology'),
                    ('clear spanning-tree statistics', 'Clear STP statistics'),
                ],
                'Port Statistics': [
                    ('show interfaces', 'Display statistics for all interfaces'),
                    ('show interfaces terse', 'Brief interface status summary'),
                    ('show interfaces <iface>', 'Detailed statistics for specific interface'),
                    ('show interfaces <iface> detail', 'Verbose interface details'),
                    ('show interfaces <iface> media', 'Display media/transceiver info'),
                    ('show interfaces diagnostics optics <iface>', 'Display optical DDM diagnostics'),
                    ('show interfaces statistics', 'Show interface packet statistics'),
                    ('show interfaces <iface> statistics', 'Statistics for specific interface'),
                    ('show interfaces queue <iface>', 'Display queue statistics'),
                    ('show interfaces errors', 'Show interface error counters'),
                    ('show interfaces <iface> errors', 'Error counters for specific interface'),
                    ('show interfaces <iface> descriptions', 'Interface descriptions'),
                    ('show lacp interfaces', 'Show LACP interface status'),
                    ('show lacp statistics interfaces <iface>', 'LACP statistics per interface'),
                    ('show ethernet-switching table', 'Display MAC address table'),
                    ('show ethernet-switching table interface <iface>', 'MACs on specific port'),
                    ('show ethernet-switching table summary', 'MAC table summary'),
                    ('show lldp neighbor', 'Display LLDP neighbors'),
                    ('show lldp interface', 'LLDP status per interface'),
                    ('show chassis alarms', 'Display chassis alarm status'),
                    ('clear interfaces statistics <iface>', 'Clear interface statistics'),
                ],
                'OSPF': [
                    ('set protocols ospf area <id> interface <iface>', 'Enable OSPF on interface'),
                    ('set protocols ospf area <id> interface <iface> metric <cost>', 'Set OSPF interface cost'),
                    ('set protocols ospf area <id> interface <iface> interface-type p2p', 'Set as point-to-point'),
                    ('set protocols ospf area <id> interface <iface> interface-type nbma', 'Set as NBMA'),
                    ('set protocols ospf area <id> stub', 'Configure stub area'),
                    ('set protocols ospf area <id> nssa', 'Configure NSSA area'),
                    ('set protocols ospf area <id> stub no-summaries', 'Configure totally stubby area'),
                    ('set protocols ospf export <policy>', 'Export routes into OSPF'),
                    ('set protocols ospf reference-bandwidth <bw>', 'Set reference bandwidth'),
                    ('set protocols ospf spf-options delay <ms>', 'Set SPF delay'),
                    ('set policy-options policy-statement <name> term <t> from protocol ospf', 'Match OSPF routes'),
                    ('set policy-options policy-statement <name> term <t> then accept', 'Accept matched routes'),
                    ('show ospf neighbor', 'Display OSPF neighbors'),
                    ('show ospf neighbor detail', 'Detailed OSPF neighbor info'),
                    ('show ospf interface', 'Display OSPF interface status'),
                    ('show ospf database', 'Display OSPF LSDB'),
                    ('show ospf database router', 'Show Type-1 LSAs'),
                    ('show ospf database network', 'Show Type-2 LSAs'),
                    ('show ospf database summary', 'Show Type-3 LSAs'),
                    ('show ospf database external', 'Show Type-5 LSAs'),
                    ('show ospf route', 'Display OSPF routing table'),
                    ('show ospf overview', 'OSPF process overview'),
                    ('show ospf statistics', 'Display OSPF statistics'),
                    ('show ospf statistics interface', 'OSPF interface statistics'),
                    ('clear ospf neighbor', 'Reset OSPF adjacencies'),
                    ('clear ospf database', 'Clear OSPF LSDB'),
                ],
                'BGP': [
                    ('set protocols bgp group <name> type external', 'Create eBGP group'),
                    ('set protocols bgp group <name> type internal', 'Create iBGP group'),
                    ('set protocols bgp group <name> neighbor <ip>', 'Add BGP neighbor'),
                    ('set protocols bgp group <name> neighbor <ip> description <text>', 'Set neighbor description'),
                    ('set protocols bgp group <name> local-address <ip>', 'Set update source'),
                    ('set protocols bgp group <name> multihop <ttl>', 'Set eBGP multihop'),
                    ('set protocols bgp group <name> authentication-key <key>', 'Set MD5 auth'),
                    ('set protocols bgp group <name> local-as <asn>', 'Set local AS'),
                    ('set protocols bgp group <name> peer-as <asn>', 'Set peer AS'),
                    ('set protocols bgp group <name> export <policy>', 'Apply export policy'),
                    ('set protocols bgp group <name> import <policy>', 'Apply import policy'),
                    ('set protocols bgp group <name> family inet unicast', 'Enable IPv4 unicast AF'),
                    ('set protocols bgp group <name> family inet6 unicast', 'Enable IPv6 unicast AF'),
                    ('set protocols bgp group <name> advertise-external', 'Advertise external routes to iBGP'),
                    ('set protocols bgp group <name> multipath', 'Enable BGP multipath'),
                    ('set policy-options policy-statement <name> term <t> from protocol bgp', 'Match BGP routes'),
                    ('set policy-options policy-statement <name> term <t> from community <comm>', 'Match community'),
                    ('set policy-options policy-statement <name> term <t> then local-preference <n>', 'Set local-pref'),
                    ('set policy-options policy-statement <name> term <t> then community add <comm>', 'Add community'),
                    ('show bgp summary', 'Display BGP neighbor summary'),
                    ('show bgp neighbor', 'Display BGP neighbor details'),
                    ('show bgp neighbor <ip>', 'Detailed info for specific neighbor'),
                    ('show route protocol bgp', 'Display BGP routes'),
                    ('show route receive-protocol bgp <ip>', 'Routes received from neighbor'),
                    ('show route advertising-protocol bgp <ip>', 'Routes advertised to neighbor'),
                    ('show route protocol bgp <net>', 'Show BGP entry for network'),
                    ('show route protocol bgp community <community>', 'Routes with community'),
                    ('show route protocol bgp detail', 'Detailed BGP route info'),
                    ('show route summary protocol bgp', 'BGP route summary'),
                    ('show bgp neighbor <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('clear bgp neighbor', 'Reset all BGP sessions'),
                    ('clear bgp neighbor <ip>', 'Reset specific BGP session'),
                    ('clear bgp neighbor <ip> soft', 'Soft reset BGP session'),
                ],
                'IS-IS': [
                    ('set protocols isis interface <iface>', 'Enable IS-IS on interface'),
                    ('set protocols isis interface <iface> level 1 disable', 'Disable L1 on interface'),
                    ('set protocols isis interface <iface> level 2 disable', 'Disable L2 on interface'),
                    ('set protocols isis interface <iface> metric <cost>', 'Set IS-IS interface cost'),
                    ('set protocols isis interface <iface> interface-type p2p', 'Set as point-to-point'),
                    ('set protocols isis level 1 wide-metrics-only', 'Enable wide metrics for L1'),
                    ('set protocols isis level 2 wide-metrics-only', 'Enable wide metrics for L2'),
                    ('set protocols isis spf-options delay <ms>', 'Set SPF delay'),
                    ('set protocols isis export <policy>', 'Export routes into IS-IS'),
                    ('set protocols isis overload', 'Set overload bit'),
                    ('show isis adjacency', 'Display IS-IS neighbors/adjacencies'),
                    ('show isis adjacency detail', 'Detailed IS-IS neighbor info'),
                    ('show isis interface', 'Display IS-IS interface status'),
                    ('show isis database', 'Display IS-IS link-state database'),
                    ('show isis database detail', 'Verbose LSP display with TLVs'),
                    ('show isis database extensive', 'Extensive LSP display'),
                    ('show isis route', 'Display IS-IS routing table'),
                    ('show isis spf', 'Display SPF calculation results'),
                    ('show isis statistics', 'Display IS-IS statistics'),
                    ('show isis overview', 'IS-IS process overview'),
                    ('clear isis adjacency', 'Reset IS-IS adjacencies'),
                    ('clear isis database', 'Clear IS-IS LSDB'),
                ],
                'RIP': [
                    ('set protocols rip group <name> neighbor <iface>', 'Enable RIP on interface'),
                    ('set protocols rip group <name> neighbor <iface> send version-2', 'Send RIPv2'),
                    ('set protocols rip group <name> neighbor <iface> receive version-2', 'Receive RIPv2'),
                    ('set protocols rip group <name> export <policy>', 'Export routes into RIP'),
                    ('set protocols rip traceoptions file rip.log', 'Enable RIP tracing'),
                    ('set protocols rip traceoptions flag all', 'Trace all RIP events'),
                    ('set policy-options policy-statement <name> term <t> from protocol rip', 'Match RIP routes'),
                    ('show rip neighbor', 'Display RIP neighbors'),
                    ('show rip route', 'Display RIP routing table'),
                    ('show rip statistics', 'Display RIP statistics'),
                    ('show rip statistics interface', 'RIP interface statistics'),
                    ('clear rip neighbor', 'Reset RIP neighbors'),
                ],
                'QoS / CoS / DSCP': [
                    ('set class-of-service interfaces <iface> shaping-rate <bps>', 'Set interface shaping rate'),
                    ('set class-of-service interfaces <iface> unit 0 classifiers dscp <name>', 'Apply DSCP classifier'),
                    ('set class-of-service forwarding-class <name> queue-num <n>', 'Define forwarding class'),
                    ('set class-of-service classifiers dscp <name> forwarding-class <fc> loss-priority <lp>', 'DSCP classifier'),
                    ('set class-of-service schedulers <name> transmit-rate <pct>', 'Set scheduler transmit rate'),
                    ('set class-of-service scheduler-maps <name> forwarding-class <fc> scheduler <sched>', 'Map scheduler'),
                    ('show class-of-service interface <iface>', 'Display CoS config on interface'),
                    ('show class-of-service queue <iface>', 'Display queue statistics'),
                ],
                'Trunk': [
                    ('set interfaces <iface> unit 0 family ethernet-switching interface-mode trunk', 'Set as trunk'),
                    ('set interfaces <iface> unit 0 family ethernet-switching vlan members <v1> <v2>', 'Set allowed VLANs'),
                    ('show interfaces <iface> switching', 'Display switching config for interface'),
                ],
                'Firmware': [
                    ('show version', 'Display Junos version and hardware'),
                    ('show system storage', 'Show available disk space'),
                    ('file list /var/tmp/', 'List files in /var/tmp'),
                    ('request system software add /var/tmp/<file>', 'Install firmware from local file'),
                    ('request system software add <tftp-url>', 'Install firmware from TFTP/HTTP URL'),
                    ('request system software add no-validate /var/tmp/<file>', 'Install without signature check'),
                    ('request system reboot', 'Reboot to apply new firmware'),
                    ('request system software rollback', 'Roll back to previous firmware'),
                ],
            },
            'D-Link': {
                'Basic': [
                    ('enable admin', 'Enter admin mode'),
                    ('config', 'Enter configuration mode'),
                    ('save', 'Save configuration'),
                    ('reboot', 'Reboot the switch'),
                ],
                'Show Commands': [
                    ('show switch', 'Display switch information'),
                    ('show ports', 'Display port status'),
                    ('show vlan', 'Display VLAN information'),
                    ('show fdb', 'Display MAC address table'),
                    ('show iproute', 'Display routing table'),
                ],
                'VLANs': [
                    ('create vlan <id> tag <id>', 'Create a tagged VLAN'),
                    ('config vlan <id> add tagged <ports>', 'Add tagged ports to VLAN'),
                    ('config vlan <id> add untagged <ports>', 'Add untagged ports to VLAN'),
                    ('delete vlan <id>', 'Delete a VLAN'),
                ],
                'Ports': [
                    ('config ports <range> state enable', 'Enable ports'),
                    ('config ports <range> state disable', 'Disable ports'),
                    ('config ports <range> speed auto', 'Set port auto-negotiation'),
                    ('config ports <range> description <text>', 'Set port description'),
                ],
                'System': [
                    ('config ipif System ipaddress <ip>/<mask>', 'Set management IP'),
                    ('reset', 'Reset to factory defaults'),
                ],
                'Users': [
                    ('create account admin <name>', 'Create administrator account (L2/L3 switches)'),
                    ('create account user <name>', 'Create read-only user account'),
                    ('show account', 'Display configured user accounts'),
                    ('config account <name> delete', 'Delete a user account'),
                ],
                'SSH': [
                    ('enable ssh', 'Enable SSH server'),
                    ('config ssh algorithm cipher high', 'Set SSH to use strong ciphers only'),
                    ('config ssh algorithm hmac high', 'Set SSH to use strong HMAC only'),
                    ('config ssh authmode password', 'Use password authentication for SSH'),
                    ('config ssh authmode publickey', 'Use public key authentication for SSH'),
                    ('show ssh', 'Display SSH configuration and status'),
                ],
                'Telnet': [
                    ('enable telnet', 'Enable Telnet server'),
                    ('disable telnet', 'Disable Telnet server'),
                    ('show telnet', 'Display Telnet server status'),
                ],
                'SNMP': [
                    ('create snmp community <name> <ro|rw>', 'Create SNMP community (read-only or read-write)'),
                    ('enable snmp', 'Enable SNMP agent'),
                    ('config snmp system_name <name>', 'Set SNMP system name'),
                    ('config snmp system_location <text>', 'Set SNMP system location'),
                    ('config snmp system_contact <text>', 'Set SNMP system contact'),
                    ('show snmp community', 'Display SNMP communities'),
                ],

                'Spanning-Tree': [
                    ('enable stp', 'Enable STP globally'),
                    ('config stp mode rstp', 'Enable RSTP mode'),
                    ('config stp mode mstp', 'Enable MSTP mode'),
                    ('config stp priority <0-61440>', 'Set bridge priority'),
                    ('config stp port <ports> edge enable', 'Enable Edge Port (PortFast)'),
                    ('config stp port <ports> bpdu_guard enable', 'Enable BPDU Guard on ports'),
                    ('config stp port <ports> bpdu_filter enable', 'Enable BPDU Filter on ports'),
                    ('config stp port <ports> path_cost <cost>', 'Set STP port cost'),
                    ('config stp port <ports> priority <0-240>', 'Set STP port priority'),
                    ('config stp tx_hold_count <n>', 'Set transmit hold count'),
                    ('config stp hello_time <sec>', 'Set hello time'),
                    ('config stp max_age <sec>', 'Set max age timer'),
                    ('config stp forward_delay <sec>', 'Set forward delay'),
                    ('show spanningtree', 'Display STP status'),
                    ('show spanningtree port', 'Display STP port status'),
                    ('show spanningtree port <ports>', 'STP status for specific ports'),
                    ('show spanningtree topology', 'Display STP topology'),
                    ('show spanningtree statistics', 'Display STP statistics'),
                    ('show spanningtree statistics port <ports>', 'STP stats for ports'),
                    ('clear spanningtree statistics', 'Clear STP statistics'),
                ],
                'Port Statistics': [
                    ('show ports', 'Display port status'),
                    ('show ports description', 'Display port descriptions'),
                    ('show ports config', 'Display port configuration'),
                    ('show ports config <ports>', 'Config for specific ports'),
                    ('show counters ethernet', 'Display Ethernet counters'),
                    ('show counters ethernet <ports>', 'Counters for specific ports'),
                    ('show counters ethernet errors', 'Display Ethernet error counters'),
                    ('show counters ethernet errors <ports>', 'Error counters for ports'),
                    ('show counters ethernet broadcast', 'Broadcast packet counters'),
                    ('show counters ethernet multicast', 'Multicast packet counters'),
                    ('show counters ethernet unicast', 'Unicast packet counters'),
                    ('show sfp', 'Display SFP transceiver info'),
                    ('show sfp <ports>', 'SFP info for specific ports'),
                    ('show fdb', 'Display MAC address table'),
                    ('show fdb port <ports>', 'MAC addresses on specific ports'),
                    ('show lldp port', 'LLDP port status'),
                    ('show lldp neighbors', 'Display LLDP neighbors'),
                    ('clear counters ethernet', 'Clear all Ethernet counters'),
                    ('clear counters ethernet <ports>', 'Clear counters for specific ports'),
                ],
                'OSPF': [
                    ('config ospf enable', 'Enable OSPF globally'),
                    ('config ospf router_id <ip>', 'Set OSPF router ID'),
                    ('config ospf area <id>', 'Configure OSPF area'),
                    ('config ospf area <id> type stub', 'Configure stub area'),
                    ('config ospf area <id> type nssa', 'Configure NSSA area'),
                    ('config ospf port <iface> area <id>', 'Enable OSPF on interface'),
                    ('config ospf port <iface> cost <cost>', 'Set OSPF interface cost'),
                    ('config ospf port <iface> priority <n>', 'Set DR priority'),
                    ('config ospf port <iface> hello <sec>', 'Set hello interval'),
                    ('config ospf port <iface> retransmit <sec>', 'Set retransmit interval'),
                    ('config ospf default_route_advertise enable', 'Advertise default route'),
                    ('show ospf', 'Display OSPF status'),
                    ('show ospf neighbor', 'Display OSPF neighbors'),
                    ('show ospf neighbor detail', 'Detailed OSPF neighbor info'),
                    ('show ospf port', 'Display OSPF interface status'),
                    ('show ospf lsdb', 'Display OSPF LSDB'),
                    ('show ospf route', 'Display OSPF routing table'),
                    ('show ospf statistics', 'Display OSPF statistics'),
                ],
                'RIP': [
                    ('config rip enable', 'Enable RIP globally'),
                    ('config rip version v2', 'Use RIPv2'),
                    ('config rip port <iface> enable', 'Enable RIP on interface'),
                    ('config rip default_route_advertise enable', 'Advertise default route'),
                    ('show rip', 'Display RIP status'),
                    ('show rip route', 'Display RIP routing table'),
                    ('show rip neighbor', 'Display RIP neighbors'),
                    ('show rip statistics', 'Display RIP statistics'),
                ],
                'Debug': [
                    ('debug enable', 'Enable debug mode'),
                    ('debug module <module>', 'Enable debug for specific module'),
                    ('debug disable', 'Disable debug mode'),
                    ('show debug', 'Display active debug settings'),
                ],
                'Log': [
                    ('show log', 'Display system log'),
                    ('show log severity <level>', 'Filter log by severity'),
                    ('clear log', 'Clear system log'),
                ],
                'LLDP': [
                    ('enable lldp', 'Enable LLDP globally'),
                    ('config lldp port <ports> enable', 'Enable LLDP on ports'),
                    ('show lldp neighbors', 'Display LLDP neighbors'),
                    ('show lldp neighbors detail', 'Detailed LLDP neighbor info'),
                    ('show lldp port', 'LLDP port status'),
                ],
                'DHCP Server': [
                    ('enable dhcp_server', 'Enable DHCP server'),
                    ('config dhcp_server ipif <name> pool start <ip> end <ip>', 'Set DHCP pool range'),
                    ('config dhcp_server ipif <name> gateway <ip>', 'Set default gateway'),
                    ('config dhcp_server ipif <name> dns <ip>', 'Set DNS server'),
                    ('show dhcp_server', 'Display DHCP server status'),
                    ('show dhcp_server client', 'Show active DHCP leases'),
                ],
                'DHCP Snooping': [
                    ('enable dhcp_snooping', 'Enable DHCP Snooping'),
                    ('config dhcp_snooping vlan <id> enable', 'Enable on VLAN'),
                    ('config dhcp_snooping port <ports> trusted', 'Set port as trusted'),
                    ('show dhcp_snooping', 'Display DHCP Snooping status'),
                ],
                'NTP': [
                    ('config sntp server <ip>', 'Configure SNTP/NTP server'),
                    ('config sntp mode unicast', 'Set SNTP mode to unicast'),
                    ('show sntp', 'Display SNTP configuration'),
                ],
                '802.1X': [
                    ('enable 802.1x', 'Enable 802.1X globally'),
                    ('config 802.1x port <ports> enable', 'Enable 802.1X on ports'),
                    ('config 802.1x port <ports> auth_mode auto', 'Set auto authentication mode'),
                    ('show 802.1x', 'Display 802.1X status'),
                    ('show 802.1x port <ports>', '802.1X status for specific ports'),
                ],
                'sFlow': [
                    ('enable sflow', 'Enable sFlow globally'),
                    ('config sflow collector ip <ip> port <port>', 'Configure sFlow collector'),
                    ('config sflow port <ports> sampling_rate <n>', 'Set sFlow sampling rate'),
                    ('show sflow', 'Display sFlow configuration'),
                ],
                'QoS': [
                    ('enable qoS', 'Enable QoS globally'),
                    ('config qoS mode dscp', 'Set QoS mode to DSCP'),
                    ('config qoS port <ports> trust dscp', 'Trust DSCP on port'),
                    ('config qoS port <ports> queue <n> weight <w>', 'Set queue weight'),
                    ('show qoS', 'Display QoS configuration'),
                    ('show qoS port <ports>', 'QoS config for specific ports'),
                ],
                'Trunk': [
                    ('config trunk <ports> group <id>', 'Add ports to trunk group'),
                    ('show trunk', 'Display trunk configuration'),
                ],
                'Firmware': [
                    ('show firmware information', 'Display current firmware version'),
                    ('download firmware_fromTFTP <ip> <file>', 'Download and install firmware from TFTP'),
                    ('config firmware image_id <1|2>', 'Select active firmware image'),
                    ('show flash', 'Show flash memory usage'),
                    ('reboot system', 'Reboot to apply new firmware'),
                ],
            },
            'Brocade': {
                'Switch Info': [
                    ('switchshow', 'Display switch summary and port status'),
                    ('switchname', 'Display or set switch name'),
                    ('fabricshow', 'Display fabric topology'),
                    ('version', 'Show firmware version'),
                    ('uptime', 'Show switch uptime'),
                ],
                'Port Management': [
                    ('portshow <port>', 'Display detailed port information'),
                    ('portenable <port>', 'Enable a port'),
                    ('portdisable <port>', 'Disable a port'),
                    ('portcfgshow <port>', 'Display port configuration'),
                    ('portname <port> <name>', 'Set port name'),
                ],
                'Zoning': [
                    ('zoneshow', 'Display zone configuration'),
                    ('zonecreate <name>, "<member>;<member>"', 'Create a new zone'),
                    ('zoneadd <name>, "<member>"', 'Add member to zone'),
                    ('cfgcreate <name>, "<zone>;<zone>"', 'Create zone configuration'),
                    ('cfgenable <name>', 'Enable a zone configuration'),
                    ('cfgsave', 'Save the zone configuration'),
                ],
                'Alias': [
                    ('alishow', 'Display aliases'),
                    ('alicreate <name>, "<wwn>"', 'Create a device alias'),
                    ('aliadd <name>, "<wwn>"', 'Add WWN to alias'),
                ],
                'System': [
                    ('configshow', 'Display switch configuration'),
                    ('configupload', 'Upload configuration to remote server'),
                    ('configdownload', 'Download configuration from remote server'),
                    ('ipaddrshow', 'Display IP addressing'),
                    ('reboot', 'Reboot the switch'),
                ],
                'Users': [
                    ('userconfig --add <name> -r admin', 'Create admin user (Fabric OS 7.x+)'),
                    ('userconfig --add <name> -r user', 'Create read-only user'),
                    ('userconfig --change <name> -p <pass>', 'Change user password'),
                    ('userconfig --delete <name>', 'Delete a user account'),
                    ('userconfig --show', 'Display all configured users'),
                ],
                'SSH': [
                    ('sshutil enable', 'Enable SSH server'),
                    ('sshutil allowusers <name>', 'Allow specific user(s) to use SSH'),
                    ('sshutil denyusers <name>', 'Deny specific user(s) from using SSH'),
                    ('sshutil show', 'Display SSH configuration'),
                ],
                'Telnet': [
                    ('ipfilter --addrule -p tcp -P allow -S <ip>/32 -D <switch_ip>/32 -d 23', 'Allow Telnet from specific IP (via IP Filter)'),
                    ('ipfilter --show', 'Display IP filter rules'),
                    ('telnetd -d', 'Disable Telnet server'),
                    ('telnetd -e', 'Enable Telnet server'),
                ],
                'SNMP': [
                    ('snmpconfig --set snmpv1', 'Configure SNMPv1/v2c settings'),
                    ('snmpconfig --set snmpv3', 'Configure SNMPv3 settings'),
                    ('snmpconfig --show', 'Display SNMP configuration'),
                    ('snmpconfig --enable snmpv1', 'Enable SNMPv1'),
                    ('snmpconfig --disable snmpv1', 'Disable SNMPv1'),
                    ('snmpconfig --set rocommunity <name>', 'Set read-only SNMP community'),
                    ('snmpconfig --set rwcommunity <name>', 'Set read-write SNMP community'),
                ],

                'Spanning-Tree': [
                    ('fabricrstp --enable', 'Enable Fabric RSTP'),
                    ('fabricrstp --disable', 'Disable Fabric RSTP'),
                    ('fabricrstp --show', 'Display Fabric RSTP status'),
                    ('fabricrstp --root', 'Set switch as root bridge'),
                    ('fabricrstp --priority <0-61440>', 'Set bridge priority'),
                    ('portcfgstconfig --show <port>', 'Show STP port configuration'),
                    ('portcfgstconfig --enable <port>', 'Enable STP on port'),
                    ('portcfgstconfig --disable <port>', 'Disable STP on port'),
                    ('portcfgstconfig --priority <port> <0-240>', 'Set STP port priority'),
                    ('portcfgstconfig --cost <port> <cost>', 'Set STP port cost'),
                    ('portcfgstconfig --edge <port>', 'Set port as edge port'),
                    ('portcfgstconfig --bpduguard <port>', 'Enable BPDU Guard on port'),
                ],
                'Port Statistics': [
                    ('portshow <port>', 'Display detailed port information'),
                    ('portshow', 'Display status of all ports'),
                    ('portstats64show <port>', 'Display 64-bit port statistics'),
                    ('portstats64show', 'Display 64-bit statistics for all ports'),
                    ('porterrshow <port>', 'Display port error counters'),
                    ('porterrshow', 'Display error counters for all ports'),
                    ('porterrclear <port>', 'Clear port error counters'),
                    ('portperfshow', 'Display port performance counters'),
                    ('portperfshow <port>', 'Performance counters for specific port'),
                    ('portlogdump <port>', 'Display port event log'),
                    ('portlogdump', 'Display port event logs for all ports'),
                    ('sfpshow <port>', 'Display SFP transceiver info'),
                    ('sfpshow', 'Display SFP info for all ports'),
                    ('sfpshow --dom <port>', 'Display SFP DDM diagnostics'),
                    ('switchshow', 'Display switch summary and port status'),
                    ('fabricshow', 'Display fabric topology'),
                    ('islshow', 'Display ISL (Inter-Switch Link) status'),
                    ('islshow <port>', 'ISL status for specific port'),
                    ('portcfgshow <port>', 'Display port configuration'),
                    ('portcfgshow', 'Display configuration for all ports'),
                    ('portcfgname <port> <name>', 'Set port name'),
                    ('portname <port> <name>', 'Set port alias'),
                    ('portdisable <port>', 'Disable a port'),
                    ('portenable <port>', 'Enable a port'),
                    ('portcfgspeed <port> <speed>', 'Set port speed'),
                    ('portcfgtrunkport <port> <0|1>', 'Configure port as trunk-capable'),
                    ('trunkshow', 'Display trunk group status'),
                    ('portcrcshow <port>', 'Display CRC error counters'),
                    ('portresetstats <port>', 'Reset port statistics'),
                ],
                'F-Port Trunking': [
                    ('portcfgfporttrunkarea --show', 'Show F-port trunk area config'),
                    ('portcfgfporttrunkarea --add <port_list>', 'Add ports to F-port trunk area'),
                    ('portcfgfporttrunkarea --remove <port_list>', 'Remove ports from F-port trunk area'),
                ],
                'Firmware': [
                    ('version', 'Display current Fabric OS firmware version'),
                    ('firmwareshow', 'Display firmware version on all blades/CPs'),
                    ('firmwaredownload -s <ip> <user> <pass> <file>', 'Download firmware via SCP'),
                    ('firmwaredownload -p <ip> <user> <pass> <file>', 'Download firmware via FTP'),
                    ('firmwarecommit', 'Commit new firmware (if auto-commit disabled)'),
                    ('reboot', 'Reboot to apply firmware'),
                ],
            },
            'Datacom': {
                'Navigation': [
                    ('enable', 'Enter privileged mode'),
                    ('configure', 'Enter global configuration mode'),
                    ('exit', 'Exit current mode'),
                    ('end', 'Return to privileged mode'),
                ],
                'Show Commands': [
                    ('show running-config', 'Display current configuration'),
                    ('show startup-config', 'Display saved configuration'),
                    ('show interface brief', 'Quick interface overview'),
                    ('show interface <iface>', 'Detailed interface information'),
                    ('show vlan', 'Display all VLANs'),
                    ('show vlan id <id>', 'Show specific VLAN details'),
                    ('show ip route', 'Display routing table'),
                    ('show ip route summary', 'Routing table summary'),
                    ('show arp', 'Display ARP table'),
                    ('show mac-address-table', 'Display MAC table'),
                    ('show mac-address-table vlan <id>', 'MAC table filtered by VLAN'),
                    ('show ip dhcp binding', 'Display active DHCP leases'),
                    ('show ip dhcp pool', 'Display DHCP pool configuration'),
                    ('show access-lists', 'Display all ACLs'),
                    ('show etherchannel summary', 'Show port-channel summary'),
                    ('show spanning-tree', 'Display STP status'),
                    ('show version', 'Show system version'),
                    ('show clock', 'Show system clock'),
                    ('show logging', 'Display system log'),
                ],
                'Interfaces': [
                    ('interface gigaethernet 0/<n>', 'Enter interface config'),
                    ('interface range gigaethernet 0/<start> to 0/<end>', 'Enter range of interfaces'),
                    ('ip address <ip>/<prefix>', 'Assign IP address'),
                    ('no shutdown', 'Enable interface'),
                    ('shutdown', 'Disable interface'),
                    ('switchport mode trunk', 'Set as trunk port'),
                    ('switchport mode access', 'Set as access port'),
                    ('switchport access vlan <id>', 'Assign access VLAN'),
                    ('switchport trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('switchport trunk allowed vlan <ids>', 'Set allowed VLANs on trunk'),
                    ('ip helper-address <ip>', 'Forward DHCP broadcasts to server'),
                    ('description <text>', 'Set interface description'),
                ],
                'VLANs': [
                    ('vlan <id>', 'Create or enter VLAN config'),
                    ('name <vlan-name>', 'Assign name to VLAN'),
                    ('switchport trunk allowed vlan add <id>', 'Add VLAN to trunk'),
                    ('switchport trunk allowed vlan remove <id>', 'Remove VLAN from trunk'),
                    ('no vlan <id>', 'Delete a VLAN'),
                    ('show vlan', 'Show all VLANs'),
                ],
                'ACLs': [
                    ('ip access-list standard <name>', 'Create standard ACL'),
                    ('ip access-list extended <name>', 'Create extended ACL'),
                    ('permit ip <src> <wildcard> <dst> <wildcard>', 'Permit IP traffic'),
                    ('deny ip <src> <wildcard> <dst> <wildcard>', 'Deny IP traffic'),
                    ('permit tcp <src> <wc> <dst> <wc> eq <port>', 'Permit TCP to port'),
                    ('deny any', 'Deny all (implicit — adds explicit deny)'),
                    ('ip access-group <name> in', 'Apply ACL inbound on interface'),
                    ('ip access-group <name> out', 'Apply ACL outbound on interface'),
                    ('show access-lists', 'Show all ACLs with hit counts'),
                    ('no ip access-list extended <name>', 'Delete ACL'),
                ],
                'DHCP': [
                    ('ip dhcp pool <name>', 'Create DHCP pool'),
                    ('network <net> <mask>', 'Set pool network'),
                    ('default-router <ip>', 'Set default gateway for clients'),
                    ('dns-server <ip1> <ip2>', 'Set DNS servers'),
                    ('lease <days>', 'Set lease duration'),
                    ('ip dhcp excluded-address <start> <end>', 'Exclude IPs from pool'),
                    ('show ip dhcp binding', 'Show active DHCP leases'),
                    ('show ip dhcp pool', 'Show pool details'),
                    ('clear ip dhcp binding *', 'Clear all DHCP bindings'),
                ],
                'LACP / Port-Channel': [
                    ('interface port-channel <id>', 'Create port-channel interface'),
                    ('interface gigaethernet 0/<n>', 'Enter member interface'),
                    ('channel-group <id> mode active', 'Add to LACP port-channel (active)'),
                    ('channel-group <id> mode passive', 'Add to LACP port-channel (passive)'),
                    ('channel-group <id> mode on', 'Add to static port-channel'),
                    ('show etherchannel summary', 'Show port-channel summary'),
                    ('show etherchannel <id> detail', 'Detailed port-channel info'),
                ],
                'VRF': [
                    ('ip vrf <name>', 'Create VRF'),
                    ('rd <asn>:<id>', 'Set route distinguisher'),
                    ('interface <iface>', 'Enter interface'),
                    ('ip vrf forwarding <name>', 'Assign interface to VRF'),
                    ('ip address <ip> <mask>', 'Assign IP after VRF assignment'),
                    ('ip route vrf <name> <net> <mask> <gw>', 'Add static route in VRF'),
                    ('show ip vrf', 'List all VRFs'),
                    ('show ip route vrf <name>', 'Show VRF routing table'),
                ],
                'VRRP': [
                    ('interface <iface>', 'Enter interface for VRRP config'),
                    ('vrrp <group> ip <virtual-ip>', 'Set virtual IP for VRRP group'),
                    ('vrrp <group> priority <0-255>', 'Set VRRP priority (default 100; higher = master)'),
                    ('vrrp <group> preempt', 'Enable preemption'),
                    ('vrrp <group> timers advertise <sec>', 'Set advertisement interval'),
                    ('vrrp <group> authentication text <key>', 'Set plain-text authentication'),
                    ('vrrp <group> track <iface> decrement <val>', 'Reduce priority when interface goes down'),
                    ('show vrrp', 'Display all VRRP groups and states'),
                    ('show vrrp brief', 'VRRP summary table'),
                    ('show vrrp interface <iface>', 'VRRP details for specific interface'),
                ],
                'System': [
                    ('hostname <name>', 'Set device hostname'),
                    ('write memory', 'Save configuration'),
                    ('copy running-config startup-config', 'Save configuration'),
                    ('reload', 'Reboot the device'),
                ],
                'Users': [
                    ('username <name> privilege <0-15> password <pass>', 'Create local user with privilege level'),
                    ('username <name> privilege 15 secret <pass>', 'Create admin user with encrypted password'),
                    ('no username <name>', 'Delete a local user'),
                    ('show users', 'Display active terminal sessions'),
                    ('show running-config | include username', 'List all configured local users'),
                ],
                'SSH': [
                    ('ip ssh server enable', 'Enable SSH server'),
                    ('ip ssh version 2', 'Enable SSH version 2 only'),
                    ('crypto key generate rsa', 'Generate RSA key pair for SSH'),
                    ('line vty 0 15', 'Enter VTY line configuration'),
                    ('transport input ssh', 'Allow only SSH on VTY lines'),
                    ('show ip ssh', 'Display SSH configuration'),
                ],
                'Telnet': [
                    ('telnet <ip>', 'Initiate Telnet client session'),
                    ('line vty 0 15', 'Enter VTY line configuration'),
                    ('transport input telnet', 'Allow only Telnet on VTY lines'),
                    ('transport input none', 'Disable remote access on VTY lines'),
                    ('show line vty 0', 'Display VTY line configuration'),
                ],
                'SNMP': [
                    ('snmp-server community <name> ro', 'Configure read-only SNMP community'),
                    ('snmp-server community <name> rw', 'Configure read-write SNMP community'),
                    ('snmp-server location <text>', 'Set SNMP system location'),
                    ('snmp-server contact <text>', 'Set SNMP system contact'),
                    ('snmp-server host <ip> version 2c <community>', 'Send traps to SNMP host (v2c)'),
                    ('show snmp community', 'Display SNMP community strings'),
                    ('show snmp contact', 'Display SNMP contact string'),
                    ('show snmp location', 'Display SNMP location string'),
                ],

                'Spanning-Tree': [
                    ('spanning-tree mode rapid-pvst', 'Enable Rapid PVST+ mode'),
                    ('spanning-tree mode mst', 'Enable MST mode'),
                    ('spanning-tree vlan <id> priority <0-61440>', 'Set STP priority for VLAN'),
                    ('spanning-tree vlan <id> root primary', 'Set as primary root for VLAN'),
                    ('spanning-tree vlan <id> root secondary', 'Set as secondary root for VLAN'),
                    ('spanning-tree portfast', 'Enable PortFast on access port'),
                    ('spanning-tree portfast default', 'Enable PortFast on all access ports'),
                    ('spanning-tree bpduguard enable', 'Enable BPDU Guard on port'),
                    ('spanning-tree guard root', 'Enable Root Guard on port'),
                    ('spanning-tree cost <cost>', 'Set STP port cost'),
                    ('show spanning-tree', 'Display STP status'),
                    ('show spanning-tree vlan <id>', 'STP status for specific VLAN'),
                    ('show spanning-tree summary', 'STP summary and mode'),
                    ('show spanning-tree interface <iface>', 'STP status for specific interface'),
                    ('show spanning-tree detail', 'Detailed STP information'),
                    ('clear spanning-tree counters', 'Reset STP counters'),
                ],
                'Port Statistics': [
                    ('show interface', 'Display statistics for all interfaces'),
                    ('show interface brief', 'Brief interface status summary'),
                    ('show interface <iface>', 'Detailed statistics for specific interface'),
                    ('show interface <iface> counters', 'Packet counters for interface'),
                    ('show interface status', 'Port status summary'),
                    ('show interface transceiver', 'Display SFP transceiver info'),
                    ('show interface transceiver detail', 'Detailed transceiver diagnostics'),
                    ('show mac-address-table', 'Display MAC address table'),
                    ('show mac-address-table interface <iface>', 'MAC addresses on specific port'),
                    ('show lldp neighbor', 'Display LLDP neighbors'),
                    ('clear counters', 'Clear all interface counters'),
                    ('clear counters <iface>', 'Clear counters for specific interface'),
                ],
                'OSPF': [
                    ('router ospf <id>', 'Enable OSPF routing process'),
                    ('network <net> <wildcard> area <id>', 'Advertise network in OSPF area'),
                    ('area <id> stub', 'Configure stub area'),
                    ('area <id> nssa', 'Configure NSSA area'),
                    ('default-information originate', 'Advertise default route into OSPF'),
                    ('passive-interface <iface>', 'Suppress OSPF hellos on interface'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('show ip ospf neighbor', 'Display OSPF neighbors'),
                    ('show ip ospf interface', 'Display OSPF interface status'),
                    ('show ip ospf database', 'Display OSPF LSDB'),
                    ('show ip ospf', 'Display OSPF process information'),
                    ('show ip ospf brief', 'OSPF process brief summary'),
                    ('show ip route ospf', 'Display OSPF routes in routing table'),
                    ('clear ip ospf process', 'Reset OSPF process'),
                ],
                'BGP': [
                    ('router bgp <asn>', 'Enable BGP routing process'),
                    ('bgp router-id <ip>', 'Set BGP router ID'),
                    ('neighbor <ip> remote-as <asn>', 'Configure BGP neighbor'),
                    ('neighbor <ip> description <text>', 'Set neighbor description'),
                    ('neighbor <ip> update-source <iface>', 'Set update source interface'),
                    ('neighbor <ip> ebgp-multihop <ttl>', 'Set eBGP multihop'),
                    ('neighbor <ip> password <key>', 'Set MD5 authentication'),
                    ('neighbor <ip> next-hop-self', 'Set next-hop to self'),
                    ('neighbor <ip> activate', 'Activate neighbor in address-family'),
                    ('network <net> mask <mask>', 'Advertise network in BGP'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute ospf <id>', 'Redistribute OSPF into BGP'),
                    ('default-information originate', 'Advertise default route'),
                    ('address-family ipv4 unicast', 'Enter IPv4 unicast address-family'),
                    ('show ip bgp', 'Display BGP routing table'),
                    ('show ip bgp summary', 'Display BGP neighbor summary'),
                    ('show ip bgp neighbors', 'Display BGP neighbor details'),
                    ('show ip bgp neighbors <ip>', 'Detailed info for specific neighbor'),
                    ('show ip bgp neighbors <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('show ip bgp neighbors <ip> routes', 'Routes from neighbor'),
                    ('show ip route bgp', 'Display BGP routes in routing table'),
                    ('clear ip bgp *', 'Reset all BGP sessions'),
                    ('clear ip bgp <ip>', 'Reset specific BGP session'),
                    ('clear ip bgp * soft', 'Soft reset all BGP sessions'),
                ],
                'IS-IS': [
                    ('router isis', 'Enable IS-IS routing process'),
                    ('net <nsap>', 'Set IS-IS Network Entity Title (NET)'),
                    ('is-type level-1', 'Set IS-IS level to L1 only'),
                    ('is-type level-2-only', 'Set IS-IS level to L2 only'),
                    ('metric-style wide', 'Enable wide metrics'),
                    ('interface <iface>', 'Enter interface config'),
                    ('ip router isis', 'Enable IS-IS on interface'),
                    ('isis circuit-type level-1', 'Set circuit type to L1'),
                    ('isis circuit-type level-2-only', 'Set circuit type to L2 only'),
                    ('isis metric <cost>', 'Set IS-IS interface cost'),
                    ('isis network point-to-point', 'Set as point-to-point'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute ospf <id>', 'Redistribute OSPF into IS-IS'),
                    ('default-information originate', 'Advertise default route'),
                    ('show isis neighbors', 'Display IS-IS neighbors'),
                    ('show isis database', 'Display IS-IS link-state database'),
                    ('show isis interface', 'Display IS-IS interface status'),
                    ('show isis route', 'Display IS-IS routing table'),
                    ('clear isis neighbors', 'Reset IS-IS adjacencies'),
                ],
                'RIP': [
                    ('router rip', 'Enable RIP routing process'),
                    ('version 2', 'Use RIPv2'),
                    ('network <net>', 'Advertise network in RIP'),
                    ('no auto-summary', 'Disable automatic route summarization'),
                    ('passive-interface <iface>', 'Stop sending RIP updates on interface'),
                    ('default-information originate', 'Advertise default route in RIP'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute ospf <id> metric <n>', 'Redistribute OSPF into RIP'),
                    ('show ip rip database', 'Display RIP routing database'),
                    ('show ip route rip', 'Display RIP routes in routing table'),
                    ('debug ip rip', 'Debug RIP update packets'),
                ],
                'Debug': [
                    ('debug all', 'Enable all debug (dangerous)'),
                    ('undebug all', 'Disable all debug'),
                    ('terminal monitor', 'Enable console logging for debug'),
                    ('show debugging', 'Display active debug flags'),
                ],
                'Log': [
                    ('logging console', 'Enable logging to console'),
                    ('logging buffered <size>', 'Set local log buffer size'),
                    ('logging <ip>', 'Send logs to remote syslog server'),
                    ('service timestamps log datetime', 'Add timestamps to log messages'),
                    ('show logging', 'Display system log buffer'),
                    ('clear logging', 'Clear the logging buffer'),
                ],
                'LLDP': [
                    ('lldp run', 'Enable LLDP globally'),
                    ('lldp transmit', 'Enable LLDP transmission on port'),
                    ('lldp receive', 'Enable LLDP reception on port'),
                    ('show lldp neighbors', 'Display LLDP neighbors'),
                    ('show lldp neighbors detail', 'Detailed LLDP neighbor information'),
                    ('show lldp interface', 'LLDP status per interface'),
                ],
                'DHCP Server': [
                    ('ip dhcp pool <name>', 'Create DHCP pool'),
                    ('network <net> <mask>', 'Define pool network'),
                    ('default-router <ip>', 'Set default gateway for clients'),
                    ('dns-server <ip1> <ip2>', 'Set DNS servers'),
                    ('lease <days> <hours> <minutes>', 'Set DHCP lease duration'),
                    ('ip dhcp excluded-address <start> <end>', 'Exclude IP range from pool'),
                    ('show ip dhcp binding', 'Display active DHCP leases'),
                    ('show ip dhcp pool', 'Display DHCP pool configuration'),
                    ('clear ip dhcp binding *', 'Clear all DHCP bindings'),
                ],
                'DHCP Snooping': [
                    ('ip dhcp snooping', 'Enable DHCP Snooping globally'),
                    ('ip dhcp snooping vlan <id>', 'Enable DHCP Snooping on VLAN'),
                    ('ip dhcp snooping trust', 'Set port as trusted (uplink)'),
                    ('ip dhcp snooping limit rate <pps>', 'Limit DHCP packets per second'),
                    ('show ip dhcp snooping', 'Display DHCP Snooping status'),
                    ('show ip dhcp snooping binding', 'Display DHCP Snooping binding table'),
                ],
                'NTP': [
                    ('ntp server <ip>', 'Configure NTP server'),
                    ('ntp source <iface>', 'Set source interface for NTP'),
                    ('show ntp status', 'Display NTP synchronization status'),
                    ('show ntp associations', 'Display NTP server associations'),
                ],
                '802.1X': [
                    ('dot1x system-auth-control', 'Enable 802.1X globally'),
                    ('dot1x port-control auto', 'Enable 802.1X on port'),
                    ('dot1x port-control force-authorized', 'Force port authorized'),
                    ('show dot1x all summary', 'Display 802.1X port status summary'),
                ],
                'sFlow': [
                    ('sflow enable', 'Enable sFlow globally'),
                    ('sflow collector <ip> <port>', 'Configure sFlow collector'),
                    ('sflow sampling-rate <n> interface <iface>', 'Set sFlow sampling rate'),
                    ('show flow-sampler', 'Display sFlow status'),
                ],
                'QoS / CoS / DSCP': [
                    ('mls qos', 'Enable QoS globally'),
                    ('class-map match-any <name>', 'Create class map'),
                    ('policy-map <name>', 'Create policy map'),
                    ('class <name>', 'Reference class map in policy'),
                    ('set dscp <value>', 'Set DSCP value in policy'),
                    ('service-policy input <name>', 'Apply policy inbound'),
                    ('service-policy output <name>', 'Apply policy outbound'),
                    ('show policy-map interface', 'Display QoS policy on interfaces'),
                ],
                'Trunk': [
                    ('interface <iface>', 'Enter interface config mode'),
                    ('switchport mode trunk', 'Set port as trunk'),
                    ('switchport trunk allowed vlan <ids>', 'Set allowed VLANs on trunk'),
                    ('switchport trunk allowed vlan add <id>', 'Add VLAN to trunk'),
                    ('switchport trunk allowed vlan remove <id>', 'Remove VLAN from trunk'),
                    ('switchport trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('switchport nonegotiate', 'Disable DTP negotiation'),
                    ('show interfaces trunk', 'Display trunk ports and allowed VLANs'),
                ],
                'Firmware': [
                    ('show version', 'Display current firmware version'),
                    ('show flash:', 'List files in flash'),
                    ('copy tftp: flash:', 'Interactive TFTP copy to flash'),
                    ('copy tftp://<ip>/<file> flash:<file>', 'Download firmware from TFTP'),
                    ('boot system flash <file>', 'Set boot image'),
                    ('reload', 'Reboot to apply new firmware'),
                ],
            },
            'Fortinet': {
                'Navigation': [
                    ('config <section>', 'Enter a configuration section'),
                    ('edit <entry>', 'Edit or create an entry'),
                    ('next', 'Move to next entry (in edit mode)'),
                    ('end', 'Exit current configuration section'),
                    ('abort', 'Discard changes and exit section'),
                ],
                'Show/Get Commands': [
                    ('get system status', 'Display system status and firmware info'),
                    ('get system interface', 'Display interface configuration'),
                    ('get router info routing-table all', 'Display full routing table'),
                    ('get firewall policy', 'Display firewall policies'),
                    ('get vpn ipsec tunnel summary', 'Display VPN tunnel status'),
                    ('show full-configuration', 'Show complete configuration'),
                    ('diagnose sys session list', 'Display active sessions'),
                ],
                'Firewall Policies': [
                    ('config firewall policy', 'Enter firewall policy config'),
                    ('set srcintf <iface>', 'Set source interface'),
                    ('set dstintf <iface>', 'Set destination interface'),
                    ('set srcaddr <name>', 'Set source address object'),
                    ('set dstaddr <name>', 'Set destination address object'),
                    ('set action accept', 'Allow traffic'),
                    ('set schedule always', 'Set schedule'),
                    ('set service ALL', 'Set service'),
                ],
                'Interfaces': [
                    ('config system interface', 'Enter interface configuration'),
                    ('edit <iface>', 'Select interface to edit'),
                    ('set ip <ip> <mask>', 'Assign IP address'),
                    ('set allowaccess ping https ssh', 'Set management access'),
                    ('set status up', 'Enable interface'),
                ],
                'VPN': [
                    ('config vpn ipsec phase1-interface', 'Configure VPN phase1'),
                    ('config vpn ipsec phase2-interface', 'Configure VPN phase2'),
                    ('diagnose vpn tunnel list', 'Display tunnel details'),
                ],
                'Users': [
                    ('config system admin', 'Enter admin/user configuration'),
                    ('edit <name>', 'Create or edit an admin user'),
                    ('set accprofile super_admin', 'Assign super_admin profile (full access)'),
                    ('set accprofile prof_admin', 'Assign prof_admin profile (limited)'),
                    ('set password <pass>', 'Set user password'),
                    ('set trusthost1 <ip>/<mask>', 'Restrict login from specific subnet'),
                    ('next', 'Save user and exit edit mode'),
                    ('end', 'Exit configuration section'),
                    ('show system admin', 'Display all configured admin users'),
                ],
                'SSH': [
                    ('config system ssh', 'Enter SSH configuration'),
                    ('set port <port>', 'Set SSH listening port (default 22)'),
                    ('set algorithm cipher high', 'Require strong ciphers only'),
                    ('set algorithm hmac high', 'Require strong HMAC only'),
                    ('set allow-public-key enable', 'Allow public key authentication'),
                    ('end', 'Exit configuration section'),
                    ('show system ssh', 'Display SSH configuration'),
                ],
                'Telnet': [
                    ('config system telnet', 'Enter Telnet configuration'),
                    ('set port <port>', 'Set Telnet listening port (default 23)'),
                    ('set status enable', 'Enable Telnet server'),
                    ('set status disable', 'Disable Telnet server'),
                    ('end', 'Exit configuration section'),
                    ('show system telnet', 'Display Telnet configuration'),
                ],
                'SNMP': [
                    ('config system snmp community', 'Enter SNMP community configuration'),
                    ('edit <name>', 'Create or edit a community'),
                    ('set hosts <ip>/32', 'Allow queries from specific host'),
                    ('set hosts all', 'Allow queries from any host'),
                    ('set name <name>', 'Set community name'),
                    ('set trap-v2c-status enable', 'Enable v2c traps'),
                    ('next', 'Save community and exit edit mode'),
                    ('end', 'Exit configuration section'),
                    ('show system snmp community', 'Display SNMP communities'),
                    ('execute snmp-get <version> <community> <oid> <ip>', 'Test SNMP GET from CLI'),
                ],
                'System': [
                    ('execute backup config tftp <file> <ip>', 'Backup config via TFTP'),
                    ('execute restore config tftp <file> <ip>', 'Restore config via TFTP'),
                    ('execute reboot', 'Reboot the FortiGate'),
                    ('execute factoryreset', 'Factory reset'),
                    ('diagnose debug enable', 'Enable debug output'),
                ],

                'Spanning-Tree': [
                    ('config system switch-interface', 'Enter switch interface config (for STP on FortiSwitch)'),
                    ('set stp-status enable', 'Enable STP on switch interface'),
                    ('set stp-mode rstp', 'Set STP mode to RSTP'),
                    ('set stp-mode mstp', 'Set STP mode to MSTP'),
                    ('set stp-priority <0-61440>', 'Set bridge priority'),
                    ('config switch-controller managed-switch', 'Enter managed switch config'),
                    ('edit <switch-name>', 'Select switch to configure'),
                    ('set stp-state enabled', 'Enable STP on managed switch'),
                    ('set stp-mode rstp', 'Set RSTP mode'),
                    ('config stp-instance', 'Enter STP instance config'),
                    ('set priority <0-61440>', 'Set STP priority'),
                    ('next', 'Save and exit edit mode'),
                    ('end', 'Exit configuration section'),
                    ('get system switch-interface', 'Display switch interface STP status'),
                    ('diagnose switch-controller stp summary', 'Display STP summary'),
                    ('diagnose switch-controller stp port-state', 'Display STP port states'),
                    ('diagnose switch-controller stp topology', 'Display STP topology'),
                ],
                'Port Statistics': [
                    ('get system interface', 'Display interface configuration'),
                    ('diagnose hardware deviceinfo nic <iface>', 'Display NIC info'),
                    ('diagnose netlink interface list', 'List all network interfaces'),
                    ('diagnose netlink interface stat name=<iface>', 'Interface statistics'),
                    ('get switch-controller managed-switch', 'Display managed switch info'),
                    ('diagnose switch-controller port list', 'List all switch ports'),
                    ('diagnose switch-controller port status', 'Display port status'),
                    ('diagnose switch-controller port counters', 'Display port counters'),
                    ('diagnose switch-controller sfp list', 'Display SFP transceiver info'),
                    ('diagnose switch-controller sfp <port>', 'SFP info for specific port'),
                    ('diagnose switch-controller mac-list', 'Display MAC address table'),
                    ('diagnose switch-controller lldp neighbor', 'Display LLDP neighbors'),
                    ('diagnose sys session list', 'Display active sessions'),
                    ('diagnose sys session stats', 'Display session statistics'),
                    ('diagnose firewall statistics', 'Display firewall statistics'),
                    ('diagnose hardware sysinfo nic', 'Display all NIC hardware info'),
                ],
                'OSPF': [
                    ('config router ospf', 'Enter OSPF configuration'),
                    ('set router-id <ip>', 'Set OSPF router ID'),
                    ('set default-information-originate enable', 'Advertise default route'),
                    ('set default-information-originate always enable', 'Always advertise default'),
                    ('config area', 'Enter OSPF area configuration'),
                    ('edit "<area-id>"', 'Select OSPF area'),
                    ('set type stub', 'Configure stub area'),
                    ('set type nssa', 'Configure NSSA area'),
                    ('next', 'Save area config'),
                    ('config network', 'Enter OSPF network configuration'),
                    ('edit <n>', 'Create OSPF network entry'),
                    ('set prefix <net>/<mask>', 'Set network prefix'),
                    ('set area "<area-id>"', 'Assign to area'),
                    ('set "passive-interface" enable', 'Set as passive interface'),
                    ('next', 'Save network entry'),
                    ('end', 'Exit configuration section'),
                    ('get router info ospf neighbor', 'Display OSPF neighbors'),
                    ('get router info ospf database', 'Display OSPF LSDB'),
                    ('get router info routing-table ospf', 'Display OSPF routes'),
                    ('get router info ospf interface', 'Display OSPF interface status'),
                    ('diagnose ip router ospf all', 'Display all OSPF info'),
                    ('diagnose ip router ospf neighbor', 'Display OSPF neighbors (diagnostic)'),
                    ('diagnose ip router ospf route', 'Display OSPF routes (diagnostic)'),
                    ('diagnose ip router ospf spf', 'Display SPF calculation results'),
                ],
                'BGP': [
                    ('config router bgp', 'Enter BGP configuration'),
                    ('set as <asn>', 'Set local AS number'),
                    ('set router-id <ip>', 'Set BGP router ID'),
                    ('config neighbor', 'Enter BGP neighbor configuration'),
                    ('edit "<ip>"', 'Select BGP neighbor'),
                    ('set remote-as <asn>', 'Set neighbor AS number'),
                    ('set description <text>', 'Set neighbor description'),
                    ('set update-source <iface>', 'Set update source interface'),
                    ('set ebgp-enforce-multihop enable', 'Enable eBGP multihop'),
                    ('set password <key>', 'Set MD5 authentication'),
                    ('set next-hop-self enable', 'Set next-hop to self'),
                    ('set soft-reconfiguration enable', 'Enable soft reconfiguration'),
                    ('set route-map-in <name>', 'Apply route-map inbound'),
                    ('set route-map-out <name>', 'Apply route-map outbound'),
                    ('set prefix-list-in <name>', 'Apply prefix-list inbound'),
                    ('set prefix-list-out <name>', 'Apply prefix-list outbound'),
                    ('next', 'Save neighbor config'),
                    ('config network', 'Enter BGP network configuration'),
                    ('edit <n>', 'Create BGP network entry'),
                    ('set prefix <net>/<mask>', 'Set network prefix'),
                    ('next', 'Save network entry'),
                    ('config redistribute', 'Enter redistribution config'),
                    ('edit "connected"', 'Redistribute connected routes'),
                    ('set status enable', 'Enable redistribution'),
                    ('set route-map <name>', 'Apply route-map to redistribution'),
                    ('next', 'Save redistribution'),
                    ('end', 'Exit configuration section'),
                    ('get router info bgp summary', 'Display BGP neighbor summary'),
                    ('get router info bgp neighbors', 'Display BGP neighbor details'),
                    ('get router info bgp network', 'Display BGP network entries'),
                    ('get router info routing-table bgp', 'Display BGP routes'),
                    ('get router info bgp neighbors <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('get router info bgp neighbors <ip> routes', 'Routes from neighbor'),
                    ('diagnose ip router bgp all', 'Display all BGP info'),
                    ('diagnose ip router bgp neighbor', 'Display BGP neighbors (diagnostic)'),
                    ('diagnose ip router bgp route', 'Display BGP routes (diagnostic)'),
                    ('execute router clear bgp all', 'Reset all BGP sessions'),
                    ('execute router clear bgp <ip>', 'Reset specific BGP session'),
                ],
                'RIP': [
                    ('config router rip', 'Enter RIP configuration'),
                    ('set default-information-originate enable', 'Advertise default route'),
                    ('config network', 'Enter RIP network configuration'),
                    ('edit <n>', 'Create RIP network entry'),
                    ('set prefix <net>/<mask>', 'Set network prefix'),
                    ('next', 'Save network entry'),
                    ('config interface', 'Enter RIP interface configuration'),
                    ('edit "<iface>"', 'Select RIP interface'),
                    ('set status enable', 'Enable RIP on interface'),
                    ('set send-version <1|2>', 'Set RIP send version'),
                    ('set receive-version <1|2>', 'Set RIP receive version'),
                    ('next', 'Save interface config'),
                    ('config redistribute', 'Enter redistribution config'),
                    ('edit "connected"', 'Redistribute connected routes'),
                    ('set status enable', 'Enable redistribution'),
                    ('next', 'Save redistribution'),
                    ('end', 'Exit configuration section'),
                    ('get router info rip neighbor', 'Display RIP neighbors'),
                    ('get router info rip database', 'Display RIP database'),
                    ('get router info routing-table rip', 'Display RIP routes'),
                    ('diagnose ip router rip all', 'Display all RIP info'),
                ],
                'System': [
                    ('execute backup config tftp <file> <ip>', 'Backup config via TFTP'),
                    ('execute restore config tftp <file> <ip>', 'Restore config via TFTP'),
                    ('execute reboot', 'Reboot the FortiGate'),
                    ('execute factoryreset', 'Factory reset'),
                    ('diagnose debug enable', 'Enable debug output'),
                    ('diagnose debug disable', 'Disable debug output'),
                    ('diagnose debug reset', 'Reset debug settings'),
                    ('diagnose debug console timestamp enable', 'Enable debug timestamps'),
                ],
                'Firmware': [
                    ('get system status', 'Show current FortiOS firmware version'),
                    ('execute restore image tftp <file> <ip>', 'Upgrade firmware from TFTP server'),
                    ('execute restore image ftp <file> <ip> <user> <pass>', 'Upgrade firmware from FTP'),
                    ('execute restore image usb <file>', 'Upgrade firmware from USB'),
                    ('execute reboot', 'Reboot to apply new firmware'),
                ],
            },
            'Aruba': {
                'Navigation': [
                    ('enable', 'Enter privileged mode'),
                    ('configure terminal', 'Enter global configuration mode'),
                    ('exit', 'Exit current mode'),
                    ('end', 'Return to privileged mode'),
                ],
                'Show Commands': [
                    ('show running-config', 'Display current configuration'),
                    ('show interfaces brief', 'Quick interface overview'),
                    ('show vlan', 'Display VLAN information'),
                    ('show ip route', 'Display routing table'),
                    ('show version', 'Show system version'),
                    ('show ap database', 'Show access point database'),
                    ('show wlan ssid-profile', 'Show wireless SSID profiles'),
                ],
                'Interfaces': [
                    ('interface <iface>', 'Enter interface config'),
                    ('ip address <ip>/<prefix>', 'Assign IP address'),
                    ('no shutdown', 'Enable interface'),
                    ('vlan trunk native <id>', 'Set native VLAN on trunk'),
                    ('vlan trunk allowed <ids>', 'Set allowed VLANs'),
                ],
                'Wireless': [
                    ('wlan ssid-profile <name>', 'Configure SSID profile'),
                    ('ap-group <name>', 'Configure AP group'),
                    ('aaa authentication dot1x <name>', 'Configure 802.1X authentication'),
                ],
                'Users': [
                    ('mgmt-user <name> <pass>', 'Create management user (ArubaOS-Switch)'),
                    ('show running-config | include mgmt-user', 'List configured management users'),
                    ('no mgmt-user <name>', 'Delete a management user'),
                ],
                'SSH': [
                    ('ip ssh', 'Enable SSH server'),
                    ('ip ssh version 2', 'Enable SSH version 2 only'),
                    ('ip ssh port <port>', 'Change SSH server port'),
                    ('ip ssh filetransfer', 'Enable SCP/SFTP file transfer'),
                    ('show ip ssh', 'Display SSH configuration'),
                ],
                'Telnet': [
                    ('telnet-server', 'Enable Telnet server'),
                    ('no telnet-server', 'Disable Telnet server'),
                    ('show telnet-server', 'Display Telnet server status'),
                ],
                'SNMP': [
                    ('snmp-server community <name> ro', 'Configure read-only SNMP community'),
                    ('snmp-server community <name> rw', 'Configure read-write SNMP community'),
                    ('snmp-server host <ip> version 2c <community>', 'Send traps to SNMP host (v2c)'),
                    ('snmp-server location <text>', 'Set SNMP system location'),
                    ('snmp-server contact <text>', 'Set SNMP system contact'),
                    ('show snmp-server', 'Display SNMP configuration'),
                ],
                'System': [
                    ('hostname <name>', 'Set device hostname'),
                    ('write memory', 'Save configuration'),
                    ('boot system flash primary', 'Set boot image'),
                    ('reload', 'Reboot the device'),
                ],

                'Spanning-Tree': [
                    ('spanning-tree', 'Enable STP globally'),
                    ('spanning-tree mode rstp', 'Enable RSTP mode'),
                    ('spanning-tree mode mstp', 'Enable MSTP mode'),
                    ('spanning-tree priority <0-61440>', 'Set bridge priority'),
                    ('spanning-tree force-version rstp-operation', 'Force RSTP operation'),
                    ('spanning-tree force-version stp-operation', 'Force STP operation'),
                    ('spanning-tree config-name <name>', 'Set MST region name'),
                    ('spanning-tree config-revision <n>', 'Set MST revision level'),
                    ('spanning-tree instance <id> vlan <vlan-list>', 'Map VLANs to MST instance'),
                    ('spanning-tree activate', 'Activate spanning-tree config'),
                    ('interface <iface>', 'Enter interface config'),
                    ('spanning-tree admin-edge-port', 'Set port as admin edge (PortFast)'),
                    ('spanning-tree bpdu-protection', 'Enable BPDU Guard on port'),
                    ('spanning-tree root-protection', 'Enable Root Protection on port'),
                    ('spanning-tree cost <cost>', 'Set STP port cost'),
                    ('spanning-tree priority <0-240>', 'Set STP port priority'),
                    ('spanning-tree force-version stp-operation', 'Force STP on port'),
                    ('show spanning-tree', 'Display STP status'),
                    ('show spanning-tree brief', 'STP brief summary'),
                    ('show spanning-tree detail', 'Detailed STP information'),
                    ('show spanning-tree interface <iface>', 'STP status for specific interface'),
                    ('show spanning-tree mst-config', 'Display MST configuration'),
                    ('show spanning-tree mst <id>', 'Display MST instance status'),
                    ('show spanning-tree topology-change', 'Display topology change history'),
                    ('clear spanning-tree counters', 'Clear STP counters'),
                ],
                'Port Statistics': [
                    ('show interfaces', 'Display interface status'),
                    ('show interfaces brief', 'Brief interface overview'),
                    ('show interfaces <iface>', 'Detailed interface information'),
                    ('show interfaces <iface> transceiver', 'Display SFP transceiver info'),
                    ('show interfaces <iface> transceiver detail', 'Detailed transceiver diagnostics'),
                    ('show mac-address', 'Display MAC address table'),
                    ('show mac-address <iface>', 'MAC addresses on specific port'),
                    ('show mac-address count', 'MAC address table count'),
                    ('show lldp info remote-device', 'Display LLDP neighbors'),
                    ('show lldp info remote-device <iface>', 'LLDP neighbors for specific port'),
                    ('show lacp <trunk-id>', 'Display LACP trunk status'),
                    ('show lacp statistics <trunk-id>', 'LACP statistics'),
                    ('show statistics <iface>', 'Traffic statistics for interface'),
                    ('show statistics mac <iface>', 'MAC-layer statistics'),
                    ('clear statistics <iface>', 'Clear interface statistics'),
                    ('show tech', 'Display comprehensive technical information'),
                ],
                'OSPF': [
                    ('router ospf', 'Enable OSPF routing process'),
                    ('router-id <ip>', 'Set OSPF router ID'),
                    ('area <id> stub', 'Configure stub area'),
                    ('area <id> nssa', 'Configure NSSA area'),
                    ('area <id> range <net> <mask>', 'Configure area range summarization'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute rip', 'Redistribute RIP into OSPF'),
                    ('redistribute bgp', 'Redistribute BGP into OSPF'),
                    ('default-information originate', 'Advertise default route'),
                    ('passive-interface <iface>', 'Suppress OSPF hellos on interface'),
                    ('interface <iface>', 'Enter interface config'),
                    ('ip ospf cost <cost>', 'Set OSPF interface cost'),
                    ('ip ospf priority <n>', 'Set DR priority'),
                    ('ip ospf hello-interval <sec>', 'Set hello interval'),
                    ('ip ospf dead-interval <sec>', 'Set dead interval'),
                    ('ip ospf network point-to-point', 'Set as point-to-point'),
                    ('ip ospf network broadcast', 'Set as broadcast'),
                    ('show ip ospf', 'Display OSPF process information'),
                    ('show ip ospf neighbor', 'Display OSPF neighbors'),
                    ('show ip ospf neighbor detail', 'Detailed OSPF neighbor info'),
                    ('show ip ospf database', 'Display OSPF LSDB'),
                    ('show ip ospf interface', 'Display OSPF interface status'),
                    ('show ip ospf route', 'Display OSPF routing table'),
                    ('show ip route ospf', 'Display OSPF routes in routing table'),
                    ('clear ip ospf process', 'Reset OSPF process'),
                ],
                'BGP': [
                    ('router bgp <asn>', 'Enable BGP routing process'),
                    ('bgp router-id <ip>', 'Set BGP router ID'),
                    ('neighbor <ip> remote-as <asn>', 'Configure BGP neighbor'),
                    ('neighbor <ip> description <text>', 'Set neighbor description'),
                    ('neighbor <ip> update-source <iface>', 'Set update source interface'),
                    ('neighbor <ip> ebgp-multihop <ttl>', 'Set eBGP multihop'),
                    ('neighbor <ip> password <key>', 'Set MD5 authentication'),
                    ('neighbor <ip> next-hop-self', 'Set next-hop to self'),
                    ('neighbor <ip> soft-reconfiguration inbound', 'Enable soft reconfiguration inbound'),
                    ('neighbor <ip> route-map <name> in', 'Apply route-map inbound'),
                    ('neighbor <ip> route-map <name> out', 'Apply route-map outbound'),
                    ('neighbor <ip> distribute-list <acl> in', 'Apply distribute-list inbound'),
                    ('neighbor <ip> distribute-list <acl> out', 'Apply distribute-list outbound'),
                    ('network <net> mask <mask>', 'Advertise network in BGP'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute ospf', 'Redistribute OSPF into BGP'),
                    ('redistribute rip', 'Redistribute RIP into BGP'),
                    ('default-information originate', 'Advertise default route'),
                    ('address-family ipv4 unicast', 'Enter IPv4 unicast address-family'),
                    ('address-family ipv6 unicast', 'Enter IPv6 unicast address-family'),
                    ('show ip bgp', 'Display BGP routing table'),
                    ('show ip bgp summary', 'Display BGP neighbor summary'),
                    ('show ip bgp neighbors', 'Display BGP neighbor details'),
                    ('show ip bgp neighbors <ip>', 'Detailed info for specific neighbor'),
                    ('show ip bgp neighbors <ip> advertised-routes', 'Routes advertised to neighbor'),
                    ('show ip bgp neighbors <ip> routes', 'Routes from neighbor'),
                    ('show ip route bgp', 'Display BGP routes in routing table'),
                    ('clear ip bgp *', 'Reset all BGP sessions'),
                    ('clear ip bgp <ip>', 'Reset specific BGP session'),
                    ('clear ip bgp * soft', 'Soft reset all BGP sessions'),
                ],
                'IS-IS': [
                    ('router isis', 'Enable IS-IS routing process'),
                    ('net <nsap>', 'Set IS-IS Network Entity Title (NET)'),
                    ('is-type level-1', 'Set IS-IS level to L1 only'),
                    ('is-type level-2-only', 'Set IS-IS level to L2 only'),
                    ('metric-style wide', 'Enable wide metrics'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute ospf', 'Redistribute OSPF into IS-IS'),
                    ('redistribute bgp', 'Redistribute BGP into IS-IS'),
                    ('redistribute rip', 'Redistribute RIP into IS-IS'),
                    ('default-information originate', 'Advertise default route'),
                    ('interface <iface>', 'Enter interface config'),
                    ('ip router isis', 'Enable IS-IS on interface'),
                    ('isis circuit-type level-1', 'Set circuit type to L1'),
                    ('isis circuit-type level-2-only', 'Set circuit type to L2 only'),
                    ('isis metric <cost>', 'Set IS-IS interface cost'),
                    ('isis network point-to-point', 'Set as point-to-point'),
                    ('show isis neighbors', 'Display IS-IS neighbors'),
                    ('show isis neighbors detail', 'Detailed IS-IS neighbor info'),
                    ('show isis database', 'Display IS-IS link-state database'),
                    ('show isis interface', 'Display IS-IS interface status'),
                    ('show isis route', 'Display IS-IS routing table'),
                    ('clear isis neighbors', 'Reset IS-IS adjacencies'),
                ],
                'RIP': [
                    ('router rip', 'Enable RIP routing process'),
                    ('version 2', 'Use RIPv2'),
                    ('network <net>', 'Advertise network in RIP'),
                    ('no auto-summary', 'Disable automatic route summarization'),
                    ('passive-interface <iface>', 'Stop sending RIP updates on interface'),
                    ('default-information originate', 'Advertise default route in RIP'),
                    ('redistribute connected', 'Redistribute connected routes'),
                    ('redistribute static', 'Redistribute static routes'),
                    ('redistribute ospf', 'Redistribute OSPF into RIP'),
                    ('redistribute bgp', 'Redistribute BGP into RIP'),
                    ('interface <iface>', 'Enter interface config'),
                    ('ip rip send version <1|2>', 'Set RIP send version'),
                    ('ip rip receive version <1|2>', 'Set RIP receive version'),
                    ('ip rip authentication mode md5', 'Set RIP MD5 authentication'),
                    ('ip rip authentication key-chain <name>', 'Set RIP key chain'),
                    ('show ip rip', 'Display RIP process information'),
                    ('show ip rip database', 'Display RIP routing database'),
                    ('show ip rip neighbor', 'Display RIP neighbors'),
                    ('show ip route rip', 'Display RIP routes in routing table'),
                    ('debug ip rip', 'Debug RIP update packets'),
                ],
                'System': [
                    ('hostname <name>', 'Set device hostname'),
                    ('write memory', 'Save configuration'),
                    ('boot system flash primary', 'Set boot image'),
                    ('reload', 'Reboot the device'),
                ],
                'Firmware': [
                    ('show version', 'Display current ArubaOS version'),
                    ('show image version', 'Show firmware images on all partitions'),
                    ('copy tftp flash <ip> <file> primary', 'Copy firmware from TFTP to primary partition'),
                    ('copy tftp flash <ip> <file> secondary', 'Copy firmware from TFTP to secondary partition'),
                    ('boot system flash primary', 'Boot from primary partition'),
                    ('boot system flash secondary', 'Boot from secondary partition'),
                    ('reload', 'Reboot to apply new firmware'),
                ],
            },
            'Linux': {
                'File System': [
                    ('ls -la', 'List files with details and hidden files'),
                    ('cd <dir>', 'Change directory'),
                    ('pwd', 'Print working directory'),
                    ('mkdir -p <dir>', 'Create directory (with parents)'),
                    ('cp -r <src> <dst>', 'Copy files/directories recursively'),
                    ('mv <src> <dst>', 'Move or rename files'),
                    ('rm -rf <path>', 'Remove files/directories recursively'),
                    ('find <dir> -name "<pattern>"', 'Search for files by name'),
                    ('du -sh <dir>', 'Show directory size'),
                    ('df -h', 'Show disk space usage'),
                ],
                'Text Processing': [
                    ('grep -r "<pattern>" <dir>', 'Search text in files recursively'),
                    ('cat <file>', 'Display file content'),
                    ('less <file>', 'View file with pagination'),
                    ('head -n <N> <file>', 'Show first N lines'),
                    ('tail -f <file>', 'Follow file updates in real time'),
                    ('awk \'{print $1}\' <file>', 'Process text columns'),
                    ('sed \'s/old/new/g\' <file>', 'Find and replace in file'),
                    ('wc -l <file>', 'Count lines in file'),
                ],
                'Networking': [
                    ('ip addr show', 'Display IP addresses'),
                    ('ip addr add <ip>/<prefix> dev <iface>', 'Assign IP address to interface'),
                    ('ip link set <iface> up', 'Bring interface up'),
                    ('ip link set <iface> down', 'Bring interface down'),
                    ('ip route show', 'Display routing table'),
                    ('ss -tulnp', 'Show listening ports with processes'),
                    ('ping <host>', 'Test connectivity'),
                    ('traceroute <host>', 'Trace route to host'),
                    ('dig <domain>', 'DNS lookup'),
                    ('curl -v <url>', 'Make HTTP request with verbose output'),
                    ('ssh <user>@<host>', 'Connect via SSH'),
                    ('scp <src> <user>@<host>:<dst>', 'Copy file to remote host'),
                    ('nmap <host>', 'Scan open ports on host'),
                    ('nmap -sV <host>', 'Detect service versions on open ports'),
                    ('nmap -sn <net>/<prefix>', 'Ping scan — discover live hosts in subnet'),
                    ('nmap -p <port1>,<port2> <host>', 'Scan specific ports'),
                    ('nmap -A <host>', 'Aggressive scan (OS, version, scripts, traceroute)'),
                    ('nmap -oN <file> <host>', 'Save scan output to file'),
                ],
                'Netstat': [
                    ('netstat -tulnp', 'List all listening TCP/UDP ports with process names'),
                    ('netstat -an', 'Show all connections and listening ports (numeric)'),
                    ('netstat -tnp', 'Show active TCP connections with process names'),
                    ('netstat -unp', 'Show active UDP connections with process names'),
                    ('netstat -l', 'List only listening sockets'),
                    ('netstat -lt', 'List only listening TCP sockets'),
                    ('netstat -lu', 'List only listening UDP sockets'),
                    ('netstat -lx', 'List only listening Unix domain sockets'),
                    ('netstat -r', 'Display the kernel routing table'),
                    ('netstat -rn', 'Display routing table (numeric addresses)'),
                    ('netstat -i', 'Show network interface statistics'),
                    ('netstat -ie', 'Show extended interface statistics (like ifconfig)'),
                    ('netstat -s', 'Show summary statistics per protocol'),
                    ('netstat -st', 'Show TCP protocol statistics'),
                    ('netstat -su', 'Show UDP protocol statistics'),
                    ('netstat -g', 'Show multicast group memberships'),
                    ('netstat -c', 'Continuously refresh output every second'),
                    ('netstat -p', 'Show PID and program name for each socket'),
                    ('netstat -tulnp | grep <port>', 'Find which process is using a specific port'),
                    ('netstat -tulnp | grep <program>', 'Find ports used by a specific program'),
                ],
                'Static Routes': [
                    ('ip route add <net>/<prefix> via <gw>', 'Add static route via gateway'),
                    ('ip route add <net>/<prefix> dev <iface>', 'Add static route via interface'),
                    ('ip route add default via <gw>', 'Add default gateway'),
                    ('ip route del <net>/<prefix>', 'Delete static route'),
                    ('ip route show', 'Display routing table'),
                    ('ip route get <ip>', 'Show which route is used to reach an IP'),
                ],
                'VLANs': [
                    ('ip link add link <iface> name <iface>.<id> type vlan id <id>', 'Create VLAN sub-interface'),
                    ('ip link set <iface>.<id> up', 'Bring VLAN interface up'),
                    ('ip addr add <ip>/<prefix> dev <iface>.<id>', 'Assign IP to VLAN interface'),
                    ('ip link del <iface>.<id>', 'Delete VLAN interface'),
                    ('ip -d link show <iface>.<id>', 'Show VLAN interface details'),
                    ('modprobe 8021q', 'Load 802.1Q VLAN kernel module'),
                ],
                'NAT / iptables': [
                    ('iptables -t nat -A POSTROUTING -o <iface> -j MASQUERADE', 'Enable MASQUERADE NAT on interface'),
                    ('iptables -t nat -A PREROUTING -p tcp --dport <port> -j DNAT --to <ip>:<port>', 'Port forwarding (DNAT)'),
                    ('iptables -A FORWARD -i <in> -o <out> -j ACCEPT', 'Allow forwarding between interfaces'),
                    ('iptables -t nat -L -n -v', 'List NAT rules'),
                    ('iptables -L -n -v --line-numbers', 'List all rules with line numbers'),
                    ('iptables -D <chain> <line>', 'Delete rule by line number'),
                    ('iptables -F', 'Flush all filter rules'),
                    ('iptables -t nat -F', 'Flush all NAT rules'),
                    ('iptables-save > /etc/iptables/rules.v4', 'Persist rules (iptables-persistent)'),
                    ('iptables-restore < /etc/iptables/rules.v4', 'Restore saved rules'),
                    ('echo 1 > /proc/sys/net/ipv4/ip_forward', 'Enable IP forwarding (temporary)'),
                    ('sysctl -w net.ipv4.ip_forward=1', 'Enable IP forwarding (runtime)'),
                ],
                'Docker': [
                    ('docker ps', 'List running containers'),
                    ('docker ps -a', 'List all containers (including stopped)'),
                    ('docker images', 'List local images'),
                    ('docker run -d --name <name> -p <host>:<cont> <image>', 'Run container in background with port mapping'),
                    ('docker run -it --rm <image> bash', 'Run interactive container (auto-remove on exit)'),
                    ('docker exec -it <name> bash', 'Open shell in running container'),
                    ('docker logs -f <name>', 'Follow container logs'),
                    ('docker stop <name>', 'Stop a running container'),
                    ('docker rm <name>', 'Remove a stopped container'),
                    ('docker rmi <image>', 'Remove an image'),
                    ('docker pull <image>', 'Download image from registry'),
                    ('docker build -t <name>:<tag> .', 'Build image from Dockerfile'),
                    ('docker inspect <name>', 'Show container/image details (JSON)'),
                    ('docker network ls', 'List Docker networks'),
                    ('docker volume ls', 'List Docker volumes'),
                    ('docker-compose up -d', 'Start services defined in docker-compose.yml'),
                    ('docker-compose down', 'Stop and remove containers from compose file'),
                    ('docker stats', 'Live resource usage per container'),
                ],
                'Process Management': [
                    ('ps aux', 'List all running processes'),
                    ('top', 'Interactive process viewer'),
                    ('kill <pid>', 'Terminate a process by PID'),
                    ('systemctl status <service>', 'Check service status'),
                    ('systemctl restart <service>', 'Restart a service'),
                    ('journalctl -u <service> -f', 'Follow service logs'),
                ],
                'System': [
                    ('uname -a', 'Display system information'),
                    ('hostname', 'Show hostname'),
                    ('uptime', 'Show system uptime and load'),
                    ('free -h', 'Display memory usage'),
                    ('sudo <command>', 'Run command as root'),
                    ('chmod <mode> <file>', 'Change file permissions'),
                    ('chown <user>:<group> <file>', 'Change file ownership'),
                ],
                'Podman': [
                    ('podman ps', 'List running containers'),
                    ('podman ps -a', 'List all containers (including stopped)'),
                    ('podman images', 'List local images'),
                    ('podman run -d --name <name> -p <host>:<cont> <image>', 'Run container in background with port mapping'),
                    ('podman run -it --rm <image> bash', 'Run interactive container (auto-remove on exit)'),
                    ('podman exec -it <name> bash', 'Open shell in running container'),
                    ('podman logs -f <name>', 'Follow container logs'),
                    ('podman stop <name>', 'Stop a running container'),
                    ('podman rm <name>', 'Remove a stopped container'),
                    ('podman rmi <image>', 'Remove an image'),
                    ('podman pull <image>', 'Download image from registry'),
                    ('podman build -t <name>:<tag> .', 'Build image from Containerfile/Dockerfile'),
                    ('podman inspect <name>', 'Show container/image details (JSON)'),
                    ('podman network ls', 'List Podman networks'),
                    ('podman volume ls', 'List Podman volumes'),
                    ('podman stats', 'Live resource usage per container'),
                    ('podman pod ls', 'List pods'),
                    ('podman pod create --name <name>', 'Create a new pod'),
                    ('podman generate systemd --name <name> --files', 'Generate systemd unit for container'),
                    ('podman play kube <file>.yaml', 'Deploy pod from Kubernetes YAML'),
                ],
                'APT (Debian/Ubuntu)': [
                    ('apt update', 'Refresh package index'),
                    ('apt upgrade', 'Upgrade all installed packages'),
                    ('apt full-upgrade', 'Upgrade packages and handle dependency changes'),
                    ('apt install <package>', 'Install a package'),
                    ('apt remove <package>', 'Remove a package (keep config files)'),
                    ('apt purge <package>', 'Remove package and its config files'),
                    ('apt autoremove', 'Remove unused dependency packages'),
                    ('apt search <keyword>', 'Search for packages by keyword'),
                    ('apt show <package>', 'Show package details'),
                    ('apt list --installed', 'List all installed packages'),
                    ('apt list --upgradable', 'List packages with available upgrades'),
                    ('dpkg -l', 'List all installed packages (dpkg)'),
                    ('dpkg -i <file>.deb', 'Install a .deb package file'),
                    ('dpkg --remove <package>', 'Remove an installed .deb package'),
                    ('apt-cache policy <package>', 'Show installed and candidate version'),
                ],
                'DNF (Fedora/RHEL)': [
                    ('dnf check-update', 'Check for available updates'),
                    ('dnf upgrade', 'Upgrade all installed packages'),
                    ('dnf install <package>', 'Install a package'),
                    ('dnf remove <package>', 'Remove a package'),
                    ('dnf autoremove', 'Remove unused dependency packages'),
                    ('dnf search <keyword>', 'Search for packages by keyword'),
                    ('dnf info <package>', 'Show package details'),
                    ('dnf list installed', 'List all installed packages'),
                    ('dnf list available', 'List available packages in repositories'),
                    ('dnf repolist', 'List enabled repositories'),
                    ('dnf history', 'Show transaction history'),
                    ('dnf history undo <id>', 'Undo a previous transaction'),
                    ('dnf group list', 'List available package groups'),
                    ('dnf group install "<group>"', 'Install a package group'),
                    ('rpm -qa', 'List all installed RPM packages'),
                    ('rpm -ivh <file>.rpm', 'Install an RPM package file'),
                ],
                'Pacman (Arch Linux)': [
                    ('pacman -Syu', 'Synchronize repositories and upgrade all packages'),
                    ('pacman -S <package>', 'Install a package'),
                    ('pacman -R <package>', 'Remove a package'),
                    ('pacman -Rs <package>', 'Remove package and unneeded dependencies'),
                    ('pacman -Rns <package>', 'Remove package, deps and config files'),
                    ('pacman -Ss <keyword>', 'Search for packages in repositories'),
                    ('pacman -Si <package>', 'Show package information from repository'),
                    ('pacman -Qi <package>', 'Show information for installed package'),
                    ('pacman -Ql <package>', 'List files installed by a package'),
                    ('pacman -Qo <file>', 'Find which package owns a file'),
                    ('pacman -Q', 'List all installed packages'),
                    ('pacman -Qdt', 'List orphaned (unneeded) packages'),
                    ('pacman -Sc', 'Clean package cache (keep latest version)'),
                    ('pacman -Scc', 'Clean entire package cache'),
                    ('pacman -U <file>.pkg.tar.zst', 'Install a local package file'),
                ],
                'Flatpak': [
                    ('flatpak install <remote> <app-id>', 'Install a Flatpak application'),
                    ('flatpak install flathub <app-id>', 'Install from Flathub repository'),
                    ('flatpak uninstall <app-id>', 'Uninstall a Flatpak application'),
                    ('flatpak uninstall --unused', 'Remove unused runtimes and extensions'),
                    ('flatpak update', 'Update all installed Flatpak applications'),
                    ('flatpak update <app-id>', 'Update a specific application'),
                    ('flatpak list', 'List installed Flatpak applications and runtimes'),
                    ('flatpak list --app', 'List installed applications only'),
                    ('flatpak search <keyword>', 'Search for applications in configured remotes'),
                    ('flatpak info <app-id>', 'Show information about an installed application'),
                    ('flatpak run <app-id>', 'Run a Flatpak application'),
                    ('flatpak remotes', 'List configured remote repositories'),
                    ('flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo', 'Add Flathub remote'),
                    ('flatpak remote-delete <remote>', 'Remove a remote repository'),
                    ('flatpak override --user --filesystem=home <app-id>', 'Grant filesystem access to an application'),
                    ('flatpak override --user --reset <app-id>', 'Reset all overrides for an application'),
                ],
                'Snap': [
                    ('snap install <package>', 'Install a snap package'),
                    ('snap install --classic <package>', 'Install a classic (unconfined) snap'),
                    ('snap remove <package>', 'Remove a snap package'),
                    ('snap refresh', 'Update all installed snaps'),
                    ('snap refresh <package>', 'Update a specific snap'),
                    ('snap list', 'List all installed snaps'),
                    ('snap find <keyword>', 'Search for snaps in the store'),
                    ('snap info <package>', 'Show detailed information about a snap'),
                    ('snap run <package>', 'Run a snap application'),
                    ('snap services', 'List snap service daemons'),
                    ('snap start <package>.<service>', 'Start a snap service'),
                    ('snap stop <package>.<service>', 'Stop a snap service'),
                    ('snap enable <package>', 'Enable a disabled snap'),
                    ('snap disable <package>', 'Disable a snap without removing it'),
                    ('snap revert <package>', 'Revert snap to the previous version'),
                    ('snap connections <package>', 'List interfaces connected to a snap'),
                ],
                'User Management': [
                    ('useradd <username>', 'Create a new user account'),
                    ('useradd -m <username>', 'Create user with home directory'),
                    ('useradd -m -s /bin/bash <username>', 'Create user with home dir and bash shell'),
                    ('useradd -m -G <group1>,<group2> <username>', 'Create user and add to groups'),
                    ('useradd -m -u <uid> <username>', 'Create user with specific UID'),
                    ('adduser <username>', 'Interactive user creation (Debian/Ubuntu)'),
                    ('passwd <username>', 'Set or change user password'),
                    ('passwd -l <username>', 'Lock a user account'),
                    ('passwd -u <username>', 'Unlock a user account'),
                    ('usermod -aG <group> <username>', 'Add user to a supplementary group'),
                    ('usermod -aG sudo <username>', 'Grant sudo privileges to user'),
                    ('usermod -s /bin/bash <username>', 'Change user login shell'),
                    ('usermod -l <newname> <oldname>', 'Rename a user account'),
                    ('usermod -d <homedir> -m <username>', 'Move user home directory'),
                    ('userdel <username>', 'Delete a user account'),
                    ('userdel -r <username>', 'Delete user and their home directory'),
                    ('groupadd <group>', 'Create a new group'),
                    ('groupdel <group>', 'Delete a group'),
                    ('gpasswd -d <username> <group>', 'Remove user from a group'),
                    ('id <username>', 'Show user UID, GID and groups'),
                    ('whoami', 'Show current logged-in username'),
                    ('w', 'Show who is logged in and what they are doing'),
                    ('last', 'Show last login history'),
                    ('cat /etc/passwd', 'List all user accounts'),
                    ('cat /etc/group', 'List all groups'),
                ],
            },
            'MikroTik': {
                'Navigation': [
                    ('/', 'Go to root menu'),
                    ('..', 'Go up one level'),
                    ('?', 'Show available commands'),
                    ('print', 'Display items in current section'),
                    ('print detail', 'Display items with full details'),
                ],
                'Interfaces': [
                    ('/interface print', 'List all interfaces'),
                    ('/interface print stats', 'Show interface traffic counters'),
                    ('/interface enable <n>', 'Enable an interface'),
                    ('/interface disable <n>', 'Disable an interface'),
                    ('/interface set <n> name=<name>', 'Rename an interface'),
                    ('/interface bridge add name=<name>', 'Create a bridge'),
                    ('/interface bridge port add bridge=<br> interface=<iface>', 'Add port to bridge'),
                    ('/interface vlan add name=<name> vlan-id=<id> interface=<iface>', 'Create VLAN interface'),
                    ('/interface vlan print', 'List VLAN interfaces'),
                ],
                'IP Addressing': [
                    ('/ip address add address=<ip>/<prefix> interface=<iface>', 'Add IP address'),
                    ('/ip address print', 'List IP addresses'),
                    ('/ip route add dst-address=<net>/<prefix> gateway=<gw>', 'Add static route'),
                    ('/ip route print', 'Display routing table'),
                    ('/ip arp print', 'Display ARP table'),
                    ('/ip dns set servers=<ip>', 'Set DNS servers'),
                    ('/ip dhcp-client add interface=<iface> disabled=no', 'Enable DHCP client'),
                    ('/ip dhcp-client print', 'Show DHCP client status'),
                ],
                'DHCP Server': [
                    ('/ip pool add name=<name> ranges=<start>-<end>', 'Create IP pool'),
                    ('/ip dhcp-server add name=<name> interface=<iface> address-pool=<pool> disabled=no', 'Create DHCP server'),
                    ('/ip dhcp-server network add address=<net>/<prefix> gateway=<gw> dns-server=<ip>', 'Configure DHCP network options'),
                    ('/ip dhcp-server lease print', 'Show active DHCP leases'),
                    ('/ip dhcp-server lease make-static <n>', 'Convert dynamic lease to static'),
                    ('/ip dhcp-server print', 'List DHCP server instances'),
                    ('/ip dhcp-server remove <n>', 'Delete DHCP server'),
                ],
                'LACP / Bonding': [
                    ('/interface bonding add name=<name> slaves=<iface1>,<iface2> mode=802.3ad', 'Create LACP bond (802.3ad)'),
                    ('/interface bonding add name=<name> slaves=<iface1>,<iface2> mode=active-backup', 'Create active-backup bond'),
                    ('/interface bonding set <n> lacp-rate=fast', 'Set LACP rate to fast'),
                    ('/interface bonding set <n> transmit-hash-policy=layer-2-and-3', 'Set LACP hash policy'),
                    ('/interface bonding print detail', 'Show bonding details and LACP state'),
                    ('/interface bonding monitor <n>', 'Live monitoring of bond status'),
                ],
                'VRF': [
                    ('/ip vrf add name=<name> interfaces=<iface>', 'Create VRF and assign interface'),
                    ('/ip vrf print', 'List all VRFs'),
                    ('/ip route add dst-address=<net>/<prefix> gateway=<gw> routing-table=<vrf>', 'Add route in VRF'),
                    ('/ip route print routing-table=<vrf>', 'Show routes in VRF'),
                    ('/ip address add address=<ip>/<prefix> interface=<iface>', 'Assign IP to VRF interface'),
                    ('/routing/route/print where routing-table=<vrf>', 'Show VRF routes (RouterOS v7)'),
                ],
                'Firewall': [
                    ('/ip firewall filter add chain=input action=accept protocol=tcp dst-port=<port>', 'Accept TCP on input chain'),
                    ('/ip firewall filter add chain=forward action=accept src-address=<net>/<prefix>', 'Accept from source subnet (forward)'),
                    ('/ip firewall filter add chain=input action=drop', 'Drop all (catch-all at end of input)'),
                    ('/ip firewall filter add chain=forward action=drop', 'Drop all (catch-all at end of forward)'),
                    ('/ip firewall nat add chain=srcnat action=masquerade out-interface=<iface>', 'Enable NAT masquerade on interface'),
                    ('/ip firewall nat add chain=dstnat protocol=tcp dst-port=<port> action=dst-nat to-addresses=<ip>', 'Port forwarding (DNAT)'),
                    ('/ip firewall address-list add list=<name> address=<net>/<prefix>', 'Add address to firewall list'),
                    ('/ip firewall filter add chain=input src-address-list=<name> action=drop', 'Drop traffic from address list'),
                    ('/ip firewall filter print', 'Display filter rules with counters'),
                    ('/ip firewall nat print', 'Display NAT rules'),
                    ('/ip firewall filter reset-counters-all', 'Reset all filter rule counters'),
                ],
                'Packet Filter (Mangle)': [
                    ('/ip firewall mangle add chain=prerouting action=mark-packet new-packet-mark=<name> passthrough=no', 'Mark packets in prerouting'),
                    ('/ip firewall mangle add chain=forward action=mark-connection new-connection-mark=<name>', 'Mark connections'),
                    ('/ip firewall mangle add chain=prerouting src-address=<net>/<prefix> action=mark-routing new-routing-mark=<vrf>', 'Policy-based routing mark'),
                    ('/ip firewall mangle print', 'Display mangle rules'),
                ],
                'VRRP': [
                    ('/ip vrrp add interface=<iface> vrid=<id> address=<virtual-ip>', 'Create VRRP group on interface'),
                    ('/ip vrrp set <n> priority=<0-255>', 'Set VRRP priority (default 100; higher = master)'),
                    ('/ip vrrp set <n> preemption-mode=yes', 'Enable preemption'),
                    ('/ip vrrp set <n> interval=<sec>', 'Set advertisement interval (seconds)'),
                    ('/ip vrrp set <n> authentication=simple password=<key>', 'Set simple authentication'),
                    ('/ip vrrp set <n> on-backup="<script>"', 'Script to run when becoming backup'),
                    ('/ip vrrp set <n> on-master="<script>"', 'Script to run when becoming master'),
                    ('/ip vrrp print', 'List all VRRP instances'),
                    ('/ip vrrp print detail', 'Detailed VRRP information'),
                    ('/ip vrrp monitor <n>', 'Live monitoring of VRRP state'),
                ],
                'Wireless': [
                    ('/interface wireless print', 'Display wireless interfaces'),
                    ('/interface wireless security-profiles print', 'Show security profiles'),
                    ('/interface wireless set <n> ssid=<name> ...', 'Configure wireless'),
                ],
                'System': [
                    ('/system identity set name=<name>', 'Set device identity/hostname'),
                    ('/system resource print', 'Display system resources (CPU, memory)'),
                    ('/system backup save name=<name>', 'Create configuration backup'),
                    ('/export', 'Export configuration to terminal'),
                    ('/log print', 'Display system log'),
                    ('/system clock print', 'Show system clock'),
                    ('/system reboot', 'Reboot the device'),
                    ('/system package update install', 'Install available updates'),
                ],
                'Users': [
                    ('/user add name=<name> password=<pass> group=full', 'Create user with full privileges'),
                    ('/user add name=<name> password=<pass> group=read', 'Create read-only user'),
                    ('/user add name=<name> password=<pass> group=write', 'Create read-write user'),
                    ('/user remove <name>', 'Delete a user'),
                    ('/user print', 'List all configured users'),
                    ('/user set <name> disabled=yes', 'Disable a user account'),
                    ('/user set <name> disabled=no', 'Enable a user account'),
                ],
                'SSH': [
                    ('/ip ssh set enabled=yes', 'Enable SSH server'),
                    ('/ip ssh set strong-crypto=yes', 'Enable strong cryptography'),
                    ('/ip ssh set forwarding-enabled=both', 'Enable SSH forwarding'),
                    ('/ip ssh set host-key-size=4096', 'Set RSA host key size to 4096 bits'),
                    ('/ip ssh print', 'Display SSH configuration'),
                    ('/ip ssh export', 'Export SSH configuration to script'),
                ],
                'Telnet': [
                    ('/ip service set telnet disabled=yes', 'Disable Telnet server'),
                    ('/ip service set telnet disabled=no', 'Enable Telnet server'),
                    ('/ip service set telnet port=2323', 'Change Telnet server port'),
                    ('/ip service print', 'Display all IP services status'),
                ],
                'SNMP': [
                    ('/snmp community add name=<name> addresses=<ip>/32', 'Create SNMP community restricted to IP'),
                    ('/snmp community add name=<name>', 'Create SNMP community (no IP restriction)'),
                    ('/snmp set enabled=yes', 'Enable SNMP agent'),
                    ('/snmp set location=<text>', 'Set SNMP system location'),
                    ('/snmp set contact=<text>', 'Set SNMP system contact'),
                    ('/snmp set trap-version=2', 'Set SNMP trap version to v2c'),
                    ('/snmp print', 'Display SNMP configuration'),
                    ('/snmp community print', 'List SNMP communities'),
                ],

                'Spanning-Tree': [
                    ('/interface bridge set <n> protocol=stp', 'Enable STP (802.1D) on bridge'),
                    ('/interface bridge set <n> protocol=rstp', 'Enable RSTP on bridge'),
                    ('/interface bridge set <n> protocol=mstp', 'Enable MSTP on bridge'),
                    ('/interface bridge set <n> priority=<0-65535>', 'Set bridge priority'),
                    ('/interface bridge set <n> max-message-age=<time>', 'Set max message age'),
                    ('/interface bridge set <n> forward-delay=<time>', 'Set forward delay'),
                    ('/interface bridge set <n> hello-time=<time>', 'Set hello time'),
                    ('/interface bridge set <n> max-hops=<n>', 'Set MSTP max hops'),
                    ('/interface bridge set <n> region-name=<name>', 'Set MST region name'),
                    ('/interface bridge set <n> region-revision=<n>', 'Set MST revision level'),
                    ('/interface bridge port set <n> priority=<0-240>', 'Set port priority'),
                    ('/interface bridge port set <n> path-cost=<cost>', 'Set port path cost'),
                    ('/interface bridge port set <n> edge=auto', 'Set edge port auto-detect'),
                    ('/interface bridge port set <n> edge=yes', 'Force edge port (PortFast)'),
                    ('/interface bridge port set <n> point-to-point=yes', 'Force point-to-point link'),
                    ('/interface bridge port set <n> guard=none', 'Disable port guard'),
                    ('/interface bridge port set <n> guard=root', 'Enable Root Guard'),
                    ('/interface bridge port set <n> guard=bpdu-guard', 'Enable BPDU Guard'),
                    ('/interface bridge msti set <n> bridge=<br> identifier=<id> priority=<pri>', 'Configure MST instance'),
                    ('/interface bridge msti port set <n> priority=<0-240>', 'Set MSTI port priority'),
                    ('/interface bridge msti port set <n> path-cost=<cost>', 'Set MSTI port cost'),
                    ('/interface bridge port print', 'Display bridge port status and STP state'),
                    ('/interface bridge port print where bridge=<br>', 'Bridge ports for specific bridge'),
                    ('/interface bridge print', 'Display bridge configuration'),
                    ('/interface bridge monitor <n>', 'Live monitor bridge status'),
                ],
                'Port Statistics': [
                    ('/interface print', 'List all interfaces'),
                    ('/interface print stats', 'Show interface traffic counters'),
                    ('/interface print detail', 'Detailed interface information'),
                    ('/interface ethernet print', 'List Ethernet interfaces'),
                    ('/interface ethernet print stats', 'Ethernet traffic counters'),
                    ('/interface ethernet print detail', 'Detailed Ethernet info'),
                    ('/interface ethernet monitor <n>', 'Live monitor Ethernet interface'),
                    ('/interface ethernet poe monitor <n>', 'PoE status for interface'),
                    ('/interface sfp print', 'Display SFP transceiver info'),
                    ('/interface ethernet sfp print', 'Ethernet SFP info'),
                    ('/interface bridge host print', 'Display MAC address table (bridge hosts)'),
                    ('/interface bridge host print where bridge=<br>', 'MACs on specific bridge'),
                    ('/interface bridge host print stats', 'MAC table with traffic stats'),
                    ('/interface lldp neighbor print', 'Display LLDP neighbors'),
                    ('/interface lldp neighbor print detail', 'Detailed LLDP neighbor info'),
                    ('/interface bonding print', 'Display bonding/LACP status'),
                    ('/interface bonding print detail', 'Detailed bonding info'),
                    ('/interface bonding monitor <n>', 'Live monitor bond status'),
                    ('/interface reset-counters', 'Reset all interface counters'),
                    ('/interface reset-counters <n>', 'Reset counters for specific interface'),
                    ('/tool bandwidth-server print', 'Display bandwidth server status'),
                    ('/tool bandwidth-test', 'Run bandwidth test'),
                    ('/interface queue tree print', 'Display queue tree statistics'),
                    ('/interface queue simple print', 'Display simple queue statistics'),
                ],
                'OSPF': [
                    ('/routing/ospf/instance add name=<name> router-id=<ip>', 'Create OSPF instance'),
                    ('/routing/ospf/instance set <n> distribute-default=always', 'Always advertise default'),
                    ('/routing/ospf/area add name=<area> instance=<name>', 'Create OSPF area'),
                    ('/routing/ospf/area set <n> type=stub', 'Configure stub area'),
                    ('/routing/ospf/area set <n> type=nssa', 'Configure NSSA area'),
                    ('/routing/ospf/area set <n> default-cost=<cost>', 'Set default cost for stub/NSSA'),
                    ('/routing/ospf/interface add interface=<iface> instance=<name> area=<area>', 'Enable OSPF on interface'),
                    ('/routing/ospf/interface set <n> cost=<cost>', 'Set OSPF interface cost'),
                    ('/routing/ospf/interface set <n> priority=<n>', 'Set DR priority'),
                    ('/routing/ospf/interface set <n> hello-interval=<sec>', 'Set hello interval'),
                    ('/routing/ospf/interface set <n> retransmit-interval=<sec>', 'Set retransmit interval'),
                    ('/routing/ospf/interface set <n> network-type=broadcast', 'Set as broadcast'),
                    ('/routing/ospf/interface set <n> network-type=point-to-point', 'Set as P2P'),
                    ('/routing/ospn/interface set <n> passive=yes', 'Set as passive interface'),
                    ('/routing/ospf/neighboring add interface=<iface> address=<ip>', 'Add OSPF neighbor (NBMA)'),
                    ('/routing/ospn/asbr add', 'Enable ASBR redistribution'),
                    ('/routing/ospf/asbr set <n> redistribute-connected=yes', 'Redistribute connected'),
                    ('/routing/ospf/asbr set <n> redistribute-static=yes', 'Redistribute static'),
                    ('/routing/ospf/asbr set <n> redistribute-bgp=yes', 'Redistribute BGP'),
                    ('/routing/ospf/asbr set <n> redistribute-other-ospf=yes', 'Redistribute other OSPF'),
                    ('/routing/ospf/asbr set <n> default-originate=always', 'Advertise default route'),
                    ('/routing/ospf/instance print', 'Display OSPF instances'),
                    ('/routing/ospf/area print', 'Display OSPF areas'),
                    ('/routing/ospf/interface print', 'Display OSPF interfaces'),
                    ('/routing/ospf/neighbor print', 'Display OSPF neighbors'),
                    ('/routing/ospf/neighbor print detail', 'Detailed OSPF neighbor info'),
                    ('/routing/ospf/lsdb print', 'Display OSPF LSDB'),
                    ('/routing/ospf/route print', 'Display OSPF routing table'),
                    ('/routing/ospf/instance-stats print', 'Display OSPF statistics'),
                    ('/routing/ospf/neighbor-stats print', 'Display OSPF neighbor statistics'),
                    ('/routing/ospf/traffic print', 'Display OSPF traffic statistics'),
                ],
                'BGP': [
                    ('/routing/bgp/connection add name=<name> remote-as=<asn> remote-address=<ip>', 'Create BGP connection'),
                    ('/routing/bgp/connection set <n> name=<text>', 'Set connection name'),
                    ('/routing/bgp/connection set <n> local-as=<asn>', 'Set local AS'),
                    ('/routing/bgp/connection set <n> local-role=rs-client', 'Set local role'),
                    ('/routing/bgp/connection set <n> tcp-md5-key=<key>', 'Set MD5 authentication'),
                    ('/routing/bgp/connection set <n> hold-time=<time>', 'Set hold time'),
                    ('/routing/bgp/connection set <n> keepalive-time=<time>', 'Set keepalive time'),
                    ('/routing/bgp/connection set <n> update-source=<iface>', 'Set update source'),
                    ('/routing/bgp/connection set <n> multihop=yes', 'Enable eBGP multihop'),
                    ('/routing/bgp/connection set <n> nexthop-choice=force-self', 'Set next-hop to self'),
                    ('/routing/bgp/connection set <n> address-families=ip', 'Enable IPv4 unicast AF'),
                    ('/routing/bgp/connection set <n> address-families=ipv6', 'Enable IPv6 unicast AF'),
                    ('/routing/bgp/template add name=<tpl> output.default-originate=always', 'Always advertise default'),
                    ('/routing/bgp/template set <n> output.network=<networks>', 'Set output networks'),
                    ('/routing/bgp/template set <n> input.accept-dummy=yes', 'Accept dummy routes'),
                    ('/routing/bgp/template set <n> input.allow-as=yes', 'Allow own AS in path'),
                    ('/routing/bgp/template set <n> input.filter=<chain>', 'Apply input filter chain'),
                    ('/routing/bgp/template set <n> output.filter=<chain>', 'Apply output filter chain'),
                    ('/routing/bgp/connection print', 'Display BGP connections'),
                    ('/routing/bgp/connection print detail', 'Detailed BGP connection info'),
                    ('/routing/bgp/connections/print where remote-address=<ip>', 'Specific BGP neighbor'),
                    ('/routing/bgp/route print', 'Display BGP routing table'),
                    ('/routing/bgp/route print where bgp-as-path=<regex>', 'Routes matching AS-path'),
                    ('/routing/bgp/route print where bgp-communities=<comm>', 'Routes with community'),
                    ('/routing/bgp/advertisements print', 'Display advertised routes'),
                    ('/routing/bgp/peer-stats print', 'Display BGP peer statistics'),
                    ('/routing/bgp/vpn print', 'Display BGP VPN info'),
                    ('/routing/bgp/connection disable <n>', 'Disable BGP connection'),
                    ('/routing/bgp/connection enable <n>', 'Enable BGP connection'),
                    ('/routing/bgp/connection remove <n>', 'Remove BGP connection'),
                ],
                'RIP': [
                    ('/routing/rip/interface add interface=<iface>', 'Enable RIP on interface'),
                    ('/routing/rip/interface set <n> receive-version=2', 'Receive RIPv2'),
                    ('/routing/rip/interface set <n> send-version=2', 'Send RIPv2'),
                    ('/routing/rip/interface set <n> authentication=password', 'Set RIP authentication'),
                    ('/routing/rip/interface set <n> authentication-key=<key>', 'Set RIP auth key'),
                    ('/routing/rip/neighbor add address=<ip>', 'Add RIP neighbor'),
                    ('/routing/rip/instance add redistribute-connected=yes', 'Redistribute connected'),
                    ('/routing/rip/instance add redistribute-static=yes', 'Redistribute static'),
                    ('/routing/rip/instance add originate-default=yes', 'Advertise default route'),
                    ('/routing/rip/interface print', 'Display RIP interfaces'),
                    ('/routing/rip/neighbor print', 'Display RIP neighbors'),
                    ('/routing/rip/route print', 'Display RIP routing table'),
                    ('/routing/rip/instance print', 'Display RIP instances'),
                ],
                'System': [
                    ('/system identity set name=<name>', 'Set device identity/hostname'),
                    ('/system resource print', 'Display system resources (CPU, memory)'),
                    ('/system backup save name=<name>', 'Create configuration backup'),
                    ('/export', 'Export configuration to terminal'),
                    ('/log print', 'Display system log'),
                    ('/system clock print', 'Show system clock'),
                    ('/system reboot', 'Reboot the device'),
                    ('/system package update install', 'Install available updates'),
                ],
                'Firmware': [
                    ('/system package print', 'List installed packages and versions'),
                    ('/system package update check-for-updates', 'Check for available updates'),
                    ('/system package update download', 'Download available updates'),
                    ('/system package update install', 'Install downloaded updates and reboot'),
                    ('/tool fetch url="http://<ip>/<file>" dst-path=<file>', 'Download file via HTTP'),
                    ('/tool fetch address=<ip> src-path=<file> mode=tftp dst-path=<file>', 'Download file via TFTP'),
                    ('/system package add file=<file>', 'Install package from local file'),
                    ('/system routerboard upgrade', 'Upgrade RouterBOARD firmware'),
                    ('/system routerboard print', 'Show RouterBOARD firmware version'),
                    ('/system reboot', 'Reboot to apply new firmware'),
                ],
            },
            'Windows': {
                'Network (CMD)': [
                    ('ipconfig', 'Display IP configuration for all adapters'),
                    ('ipconfig /all', 'Detailed IP config including MAC and DHCP'),
                    ('ipconfig /release', 'Release DHCP lease'),
                    ('ipconfig /renew', 'Renew DHCP lease'),
                    ('ipconfig /flushdns', 'Flush DNS resolver cache'),
                    ('ping <host>', 'Test ICMP reachability'),
                    ('tracert <host>', 'Trace route to destination'),
                    ('pathping <host>', 'Combined ping and tracert analysis'),
                    ('netstat -an', 'Show all active connections and listening ports'),
                    ('netstat -r', 'Display routing table'),
                    ('route print', 'Print routing table'),
                    ('route add <net> mask <mask> <gw>', 'Add a static route'),
                    ('arp -a', 'Display ARP cache'),
                    ('nslookup <host>', 'DNS lookup'),
                    ('netsh interface ip show config', 'Show interface IP configuration'),
                    ('netsh wlan show profiles', 'Show saved Wi-Fi profiles'),
                    ('netsh advfirewall show allprofiles', 'Show firewall profile status'),
                ],
                'Network (PowerShell)': [
                    ('Get-NetIPAddress', 'List all IP addresses'),
                    ('Get-NetAdapter', 'List network adapters'),
                    ('Get-NetRoute', 'Display routing table'),
                    ('Get-NetTCPConnection', 'Show active TCP connections'),
                    ('Get-DnsClientCache', 'Show DNS client cache'),
                    ('Clear-DnsClientCache', 'Flush DNS cache'),
                    ('Test-NetConnection <host> -Port <port>', 'Test TCP connectivity to port'),
                    ('Test-Connection <host>', 'Ping using PowerShell'),
                    ('Resolve-DnsName <host>', 'DNS lookup'),
                    ('Get-NetFirewallRule | Where-Object Enabled -eq True', 'List active firewall rules'),
                    ('New-NetIPAddress -IPAddress <ip> -PrefixLength <n> -InterfaceIndex <idx>', 'Set static IP'),
                    ('New-NetRoute -DestinationPrefix <net>/<prefix> -NextHop <gw>', 'Add static route'),
                ],
                'System (CMD)': [
                    ('systeminfo', 'Display detailed system information'),
                    ('hostname', 'Show computer name'),
                    ('whoami', 'Show current user and domain'),
                    ('tasklist', 'List running processes'),
                    ('taskkill /PID <pid> /F', 'Force-kill process by PID'),
                    ('sc query', 'List all services'),
                    ('sc start <service>', 'Start a service'),
                    ('sc stop <service>', 'Stop a service'),
                    ('net user', 'List local users'),
                    ('net localgroup administrators', 'List Administrators group members'),
                    ('net share', 'List network shares'),
                    ('gpupdate /force', 'Force Group Policy refresh'),
                    ('gpresult /r', 'Show applied Group Policy results'),
                    ('sfc /scannow', 'Scan and repair system files'),
                    ('chkdsk C: /f', 'Check and fix disk errors'),
                    ('shutdown /r /t 0', 'Restart immediately'),
                    ('shutdown /s /t 0', 'Shutdown immediately'),
                    ('logoff', 'Log off current session'),
                ],
                'System (PowerShell)': [
                    ('Get-Process', 'List running processes'),
                    ('Stop-Process -Id <pid> -Force', 'Kill a process by PID'),
                    ('Get-Service', 'List all services'),
                    ('Start-Service <name>', 'Start a service'),
                    ('Stop-Service <name>', 'Stop a service'),
                    ('Restart-Service <name>', 'Restart a service'),
                    ('Get-EventLog -LogName System -Newest 20', 'Show 20 latest System events'),
                    ('Get-WinEvent -LogName System -MaxEvents 20', 'Show events (newer cmdlet)'),
                    ('Get-LocalUser', 'List local users'),
                    ('New-LocalUser -Name <name> -Password (Read-Host -AsSecureString)', 'Create local user'),
                    ('Add-LocalGroupMember -Group Administrators -Member <user>', 'Add user to Admins'),
                    ('Get-Disk', 'List physical disks'),
                    ('Get-Partition', 'List disk partitions'),
                    ('Get-Volume', 'List volumes with free space'),
                    ('Get-WindowsUpdate', 'Check for updates (requires PSWindowsUpdate)'),
                    ('Install-Module PSWindowsUpdate', 'Install Windows Update PS module'),
                ],
                'File & Directory': [
                    ('dir', 'List directory contents'),
                    ('dir /s /b *.log', 'Find all .log files recursively'),
                    ('cd <path>', 'Change directory'),
                    ('md <name>', 'Create directory'),
                    ('rd /s /q <name>', 'Remove directory recursively and quietly'),
                    ('del /f /q <file>', 'Force-delete file(s)'),
                    ('copy <src> <dst>', 'Copy file'),
                    ('move <src> <dst>', 'Move file'),
                    ('ren <old> <new>', 'Rename file or directory'),
                    ('type <file>', 'Display text file contents'),
                    ('xcopy <src> <dst> /e /i /h', 'Copy directory tree'),
                    ('robocopy <src> <dst> /mir', 'Mirror directory (robust copy)'),
                    ('icacls <path>', 'Display file/folder permissions'),
                    ('icacls <path> /grant <user>:(F)', 'Grant full control to user'),
                    ('attrib +h <file>', 'Hide a file'),
                ],
                'Remote & RDP': [
                    ('mstsc /v:<host>', 'Open Remote Desktop to host'),
                    ('mstsc /v:<host>:<port>', 'RDP to specific port'),
                    ('mstsc /admin', 'Connect in console/admin session mode'),
                    ('Enter-PSSession -ComputerName <host>', 'Start interactive PowerShell remoting'),
                    ('Invoke-Command -ComputerName <host> -ScriptBlock { <cmd> }', 'Run command remotely'),
                    ('winrm quickconfig', 'Enable WinRM (PS remoting)'),
                    ('Enable-PSRemoting -Force', 'Enable PowerShell remoting'),
                ],
                'Registry': [
                    ('reg query HKLM\\SOFTWARE\\...', 'Query registry key'),
                    ('reg add HKLM\\... /v <val> /t REG_DWORD /d <data>', 'Add/update registry value'),
                    ('reg delete HKLM\\... /v <val> /f', 'Delete registry value'),
                    ('reg export HKLM\\... <file>.reg', 'Export registry key to file'),
                    ('reg import <file>.reg', 'Import registry file'),
                ],
            },
            'FreeBSD': {
                'Navigation & Files': [
                    ('ls -la', 'List directory contents with details'),
                    ('cd <path>', 'Change directory'),
                    ('pwd', 'Print working directory'),
                    ('mkdir -p <path>', 'Create directory tree'),
                    ('rm -rf <path>', 'Remove directory recursively'),
                    ('cp -r <src> <dst>', 'Copy directory recursively'),
                    ('mv <src> <dst>', 'Move or rename'),
                    ('find / -name <file>', 'Find file by name'),
                    ('less <file>', 'Page through a file'),
                    ('cat <file>', 'Display file contents'),
                    ('tail -f <file>', 'Follow a file in real time'),
                    ('chmod 755 <file>', 'Set file permissions'),
                    ('chown <user>:<group> <file>', 'Change file ownership'),
                ],
                'Package Management (pkg)': [
                    ('pkg update', 'Update package repository index'),
                    ('pkg upgrade', 'Upgrade all installed packages'),
                    ('pkg install <pkg>', 'Install a package'),
                    ('pkg remove <pkg>', 'Remove a package'),
                    ('pkg search <term>', 'Search for packages'),
                    ('pkg info', 'List all installed packages'),
                    ('pkg info <pkg>', 'Show package details'),
                    ('pkg audit -F', 'Check installed packages for vulnerabilities'),
                    ('pkg clean', 'Clean package cache'),
                ],
                'Ports (Source Builds)': [
                    ('portsnap fetch update', 'Update Ports tree'),
                    ('cd /usr/ports/<cat>/<name> && make install clean', 'Install port from source'),
                    ('make config', 'Configure build options for a port'),
                    ('make deinstall', 'Remove a port'),
                    ('make search name=<term>', 'Search ports tree'),
                    ('portmaster <cat>/<name>', 'Upgrade a port with portmaster'),
                ],
                'System Updates': [
                    ('freebsd-update fetch', 'Fetch binary security/errata patches'),
                    ('freebsd-update install', 'Apply fetched patches'),
                    ('freebsd-update upgrade -r <release>', 'Upgrade to a new FreeBSD release'),
                    ('uname -r', 'Show running kernel version'),
                    ('freebsd-version', 'Show installed/running FreeBSD version'),
                ],
                'Network': [
                    ('ifconfig', 'Show all network interfaces'),
                    ('ifconfig <iface> <ip>/<prefix>', 'Set IP address'),
                    ('ifconfig <iface> up', 'Bring interface up'),
                    ('ifconfig <iface> down', 'Bring interface down'),
                    ('route show', 'Display routing table'),
                    ('route add default <gw>', 'Set default gateway'),
                    ('netstat -rn', 'Display routing table (numeric)'),
                    ('netstat -an', 'Show all sockets'),
                    ('sockstat -4l', 'Show listening IPv4 sockets with PIDs'),
                    ('ping <host>', 'Test ICMP reachability'),
                    ('traceroute <host>', 'Trace route to host'),
                    ('dig <host>', 'DNS lookup'),
                    ('fetch <url>', 'Download file with fetch'),
                ],
                'Services (rc)': [
                    ('service <name> start', 'Start a service'),
                    ('service <name> stop', 'Stop a service'),
                    ('service <name> restart', 'Restart a service'),
                    ('service <name> status', 'Check service status'),
                    ('service -e', 'List all enabled services'),
                    ('sysrc <name>_enable="YES"', 'Enable service at boot (rc.conf)'),
                    ('sysrc <name>_enable="NO"', 'Disable service at boot'),
                    ('sysrc -a', 'Show all rc.conf settings'),
                ],
                'ZFS': [
                    ('zpool status', 'Show pool health and vdev layout'),
                    ('zpool list', 'List pools with size and usage'),
                    ('zpool create <pool> <dev>', 'Create a new pool'),
                    ('zpool destroy <pool>', 'Destroy a pool'),
                    ('zpool scrub <pool>', 'Start data integrity scrub'),
                    ('zfs list', 'List all datasets'),
                    ('zfs create <pool>/<dataset>', 'Create a new dataset'),
                    ('zfs destroy <pool>/<dataset>', 'Destroy a dataset'),
                    ('zfs snapshot <pool>/<dataset>@<snap>', 'Create a snapshot'),
                    ('zfs rollback <pool>/<dataset>@<snap>', 'Rollback to snapshot'),
                    ('zfs send <snap> | zfs receive <dst>', 'Replicate dataset'),
                    ('zfs set compression=lz4 <dataset>', 'Enable LZ4 compression'),
                    ('zfs get all <dataset>', 'Show all dataset properties'),
                ],
                'Jails': [
                    ('jls', 'List running jails'),
                    ('jexec <jid> <cmd>', 'Execute command inside jail'),
                    ('jail -c ...', 'Start a jail (legacy)'),
                    ('jail -r <name>', 'Remove/stop a jail'),
                    ('iocage list', 'List iocage jails'),
                    ('iocage create -n <name> -r <release>', 'Create iocage jail'),
                    ('iocage start <name>', 'Start iocage jail'),
                    ('iocage stop <name>', 'Stop iocage jail'),
                    ('iocage console <name>', 'Open shell in iocage jail'),
                ],
                'Kernel & Devices': [
                    ('kldload <module>', 'Load a kernel module'),
                    ('kldunload <module>', 'Unload a kernel module'),
                    ('kldstat', 'List loaded kernel modules'),
                    ('sysctl <key>', 'Read a sysctl variable'),
                    ('sysctl -w <key>=<val>', 'Set a sysctl variable'),
                    ('dmesg', 'Show kernel boot messages'),
                    ('pciconf -lv', 'List PCI devices with details'),
                    ('usbconfig list', 'List USB devices'),
                    ('devinfo -r', 'Show device resource info'),
                ],
                'Disk & Storage': [
                    ('gpart show', 'Show partition tables'),
                    ('gpart add -t freebsd-ufs -a 1m da0', 'Add UFS partition'),
                    ('newfs /dev/<part>', 'Create UFS filesystem'),
                    ('fsck -y /dev/<part>', 'Check and repair filesystem'),
                    ('mount /dev/<part> /mnt', 'Mount filesystem'),
                    ('umount /mnt', 'Unmount filesystem'),
                    ('df -h', 'Show disk space usage'),
                    ('du -sh <path>', 'Show directory size'),
                    ('camcontrol devlist', 'List SCSI/SATA/NVMe devices'),
                    ('geom disk list', 'List disk geometry'),
                ],
                'System': [
                    ('uname -a', 'Show kernel name, release, and version'),
                    ('sysctl hw.model', 'Show CPU model'),
                    ('sysctl hw.physmem', 'Show physical memory'),
                    ('top', 'Interactive process viewer'),
                    ('ps aux', 'List all processes'),
                    ('kill -9 <pid>', 'Force-kill a process'),
                    ('shutdown -r now', 'Reboot immediately'),
                    ('shutdown -p now', 'Poweroff immediately'),
                    ('date', 'Show current date and time'),
                    ('w', 'Show who is logged in and load'),
                    ('last', 'Show login history'),
                    ('id', 'Show current user identity'),
                    ('pw useradd <name> -m -s /bin/sh', 'Create user with home dir'),
                    ('pw passwd <name>', 'Set user password'),
                    ('pw groupmod wheel -m <name>', 'Add user to wheel group'),
                ],
                'Firewall (pf)': [
                    ('pfctl -e', 'Enable pf firewall'),
                    ('pfctl -d', 'Disable pf firewall'),
                    ('pfctl -f /etc/pf.conf', 'Load pf ruleset from file'),
                    ('pfctl -sr', 'Show current rules'),
                    ('pfctl -sa', 'Show all pf state (rules, NAT, state)'),
                    ('pfctl -ss', 'Show state table'),
                    ('pfctl -si', 'Show pf statistics'),
                    ('pfctl -F all', 'Flush all rules and state'),
                ],
            },
            'TP-Link': {
                'Basic': [
                    ('enable', 'Enter privileged mode'),
                    ('configure', 'Enter global configuration mode'),
                    ('exit', 'Exit current mode'),
                    ('end', 'Return to privileged mode'),
                    ('write', 'Save configuration'),
                    ('show running-config', 'Show active configuration'),
                    ('show version', 'Show firmware and hardware info'),
                ],
                'Interfaces': [
                    ('interface gigabitethernet 1/0/<n>', 'Enter interface config mode'),
                    ('ip address <ip> <mask>', 'Assign IP to routed interface'),
                    ('switchport mode access', 'Set port to access mode'),
                    ('switchport access vlan <id>', 'Assign access VLAN'),
                    ('switchport mode trunk', 'Set port to trunk mode'),
                    ('switchport trunk allowed vlan <list>', 'Set allowed VLANs on trunk'),
                    ('no shutdown', 'Enable the interface'),
                    ('description <text>', 'Set interface description'),
                ],
                'VLANs': [
                    ('vlan <id>', 'Create VLAN'),
                    ('name <name>', 'Name the VLAN'),
                    ('show vlan', 'Display VLAN table'),
                    ('interface vlan <id>', 'Enter SVI config mode'),
                ],
                'Routing': [
                    ('ip route 0.0.0.0 0.0.0.0 <gw>', 'Add default route'),
                    ('ip route <net> <mask> <gw>', 'Add static route'),
                    ('show ip route', 'Display routing table'),
                    ('router ospf', 'Enter OSPF config mode'),
                    ('network <net> <wildcard>', 'Announce network in OSPF'),
                ],
                'DHCP': [
                    ('ip dhcp pool <name>', 'Create DHCP pool'),
                    ('network <subnet> <mask>', 'Define pool subnet'),
                    ('gateway <ip>', 'Set default gateway for clients'),
                    ('dns-server <ip>', 'Set DNS server for clients'),
                    ('ip dhcp excluded-address <start> <end>', 'Exclude IPs from pool'),
                    ('show ip dhcp binding', 'Show DHCP leases'),
                ],
                'Users': [
                    ('user name <name> privilege admin', 'Create administrator user'),
                    ('user name <name> privilege operator', 'Create operator user'),
                    ('user name <name> password <pass>', 'Set user password'),
                    ('show users', 'Display configured users'),
                    ('no user name <name>', 'Delete a user'),
                ],
                'SSH': [
                    ('ip ssh server enable', 'Enable SSH server'),
                    ('ip ssh version 2', 'Enable SSH version 2 only'),
                    ('show ip ssh', 'Display SSH configuration'),
                ],
                'Telnet': [
                    ('ip telnet server enable', 'Enable Telnet server'),
                    ('no ip telnet server', 'Disable Telnet server'),
                    ('show telnet status', 'Display Telnet server status'),
                ],
                'SNMP': [
                    ('snmp-server community <name> ro', 'Configure read-only SNMP community'),
                    ('snmp-server community <name> rw', 'Configure read-write SNMP community'),
                    ('snmp-server location <text>', 'Set SNMP system location'),
                    ('snmp-server contact <text>', 'Set SNMP system contact'),
                    ('snmp-server host <ip> version 2c <community>', 'Send traps to SNMP host (v2c)'),
                    ('snmp-server enable traps', 'Enable all SNMP traps'),
                    ('show snmp community', 'Display SNMP community strings'),
                ],
                'Security': [
                    ('ip ssh server enable', 'Enable SSH server'),
                    ('no ip telnet server', 'Disable Telnet'),
                    ('acl number <3000>', 'Create extended ACL'),
                    ('rule <n> deny protocol tcp src any dst any d-port 23', 'Block Telnet in ACL'),
                    ('packet-filter <acl> in', 'Apply ACL to interface inbound'),
                ],

                'Spanning-Tree': [
                    ('spanning-tree', 'Enable STP globally'),
                    ('spanning-tree mode rstp', 'Enable RSTP mode'),
                    ('spanning-tree mode mstp', 'Enable MSTP mode'),
                    ('spanning-tree priority <0-61440>', 'Set bridge priority'),
                    ('spanning-tree mst configuration', 'Enter MST region configuration'),
                    ('instance <id> vlan <vlan-list>', 'Map VLANs to MST instance'),
                    ('name <name>', 'Set MST region name'),
                    ('revision <n>', 'Set MST revision level'),
                    ('exit', 'Exit MST config mode'),
                    ('interface <iface>', 'Enter interface config'),
                    ('spanning-tree portfast', 'Enable PortFast on port'),
                    ('spanning-tree bpduguard enable', 'Enable BPDU Guard on port'),
                    ('spanning-tree guard root', 'Enable Root Guard on port'),
                    ('spanning-tree guard loop', 'Enable Loop Guard on port'),
                    ('spanning-tree cost <cost>', 'Set STP port cost'),
                    ('spanning-tree priority <0-240>', 'Set STP port priority'),
                    ('show spanning-tree', 'Display STP status'),
                    ('show spanning-tree interface <iface>', 'STP status for specific interface'),
                    ('show spanning-tree summary', 'STP summary and mode'),
                    ('show spanning-tree statistics', 'Display STP statistics'),
                    ('clear spanning-tree counters', 'Clear STP counters'),
                ],
                'Port Statistics': [
                    ('show interfaces status', 'Display port status summary'),
                    ('show interfaces <iface>', 'Detailed interface statistics'),
                    ('show interfaces <iface> counters', 'Packet counters for interface'),
                    ('show interfaces <iface> description', 'Interface description'),
                    ('show monitor counters', 'Display interface traffic counters'),
                    ('show mac-address-table', 'Display MAC address table'),
                    ('show mac-address-table interface <iface>', 'MAC addresses on specific port'),
                    ('show lldp neighbors', 'Display LLDP neighbors'),
                    ('show lldp neighbors interface <iface>', 'LLDP neighbors for specific port'),
                    ('show storm-control', 'Display storm control settings'),
                    ('clear counters', 'Clear all interface counters'),
                    ('clear counters <iface>', 'Clear counters for specific interface'),
                ],
                'OSPF': [
                    ('router ospf', 'Enable OSPF routing process'),
                    ('router-id <ip>', 'Set OSPF router ID'),
                    ('area <id> stub', 'Configure stub area'),
                    ('area <id> nssa', 'Configure NSSA area'),
                    ('default-information originate', 'Advertise default route'),
                    ('passive-interface default', 'Make all interfaces passive'),
                    ('interface <iface>', 'Enter interface config'),
                    ('ip ospf cost <cost>', 'Set OSPF interface cost'),
                    ('ip ospf priority <n>', 'Set DR priority'),
                    ('ip ospf network point-to-point', 'Set as point-to-point'),
                    ('ip ospf hello-interval <sec>', 'Set hello interval'),
                    ('ip ospf dead-interval <sec>', 'Set dead interval'),
                    ('show ip ospf neighbor', 'Display OSPF neighbors'),
                    ('show ip ospf interface', 'Display OSPF interface status'),
                    ('show ip ospf database', 'Display OSPF LSDB'),
                    ('show ip route ospf', 'Display OSPF routes in routing table'),
                ],
                'RIP': [
                    ('router rip', 'Enable RIP routing process'),
                    ('version 2', 'Use RIPv2'),
                    ('network <net>', 'Advertise network in RIP'),
                    ('no auto-summary', 'Disable automatic route summarization'),
                    ('passive-interface <iface>', 'Stop sending RIP updates on interface'),
                    ('show ip rip database', 'Display RIP routing database'),
                ],
                'Debug': [
                    ('debug all', 'Enable all debug (dangerous)'),
                    ('undebug all', 'Disable all debug'),
                    ('show debugging', 'Display active debug flags'),
                ],
                'Log': [
                    ('show logging', 'Display system log buffer'),
                    ('logging <ip>', 'Send logs to remote syslog server'),
                    ('clear logging', 'Clear the logging buffer'),
                ],
                'LLDP': [
                    ('lldp enable', 'Enable LLDP globally'),
                    ('lldp transmit', 'Enable LLDP transmission'),
                    ('lldp receive', 'Enable LLDP reception'),
                    ('show lldp neighbors', 'Display LLDP neighbors'),
                    ('show lldp local-info', 'Display local LLDP info'),
                ],
                'DHCP Server': [
                    ('ip dhcp pool <name>', 'Create DHCP pool'),
                    ('network <net> <mask>', 'Define pool network'),
                    ('default-router <ip>', 'Set default gateway'),
                    ('dns-server <ip>', 'Set DNS server'),
                    ('ip dhcp excluded-address <start> <end>', 'Exclude IPs from pool'),
                    ('show ip dhcp binding', 'Show DHCP leases'),
                ],
                'DHCP Snooping': [
                    ('ip dhcp snooping', 'Enable DHCP Snooping'),
                    ('ip dhcp snooping vlan <id>', 'Enable DHCP Snooping on VLAN'),
                    ('ip dhcp snooping trust', 'Set port as trusted'),
                    ('show ip dhcp snooping', 'Display DHCP Snooping status'),
                ],
                'NTP': [
                    ('ntp server <ip>', 'Configure NTP server'),
                    ('show ntp status', 'Display NTP synchronization status'),
                ],
                '802.1X': [
                    ('dot1x enable', 'Enable 802.1X globally'),
                    ('dot1x port-control auto', 'Enable 802.1X on port'),
                    ('show dot1x', 'Display 802.1X status'),
                ],
                'sFlow': [
                    ('sflow enable', 'Enable sFlow'),
                    ('sflow collector <ip> <port>', 'Configure sFlow collector'),
                    ('sflow sampling-rate <n>', 'Set sFlow sampling rate'),
                ],
                'QoS': [
                    ('mls qos', 'Enable QoS globally'),
                    ('class-map match-any <name>', 'Create class map'),
                    ('policy-map <name>', 'Create policy map'),
                    ('class <name>', 'Reference class map in policy'),
                    ('set dscp <value>', 'Set DSCP value'),
                    ('service-policy input <name>', 'Apply policy inbound'),
                ],
                'Trunk': [
                    ('interface <iface>', 'Enter interface config'),
                    ('switchport mode trunk', 'Set port as trunk'),
                    ('switchport trunk allowed vlan <list>', 'Set allowed VLANs on trunk'),
                    ('switchport trunk native vlan <id>', 'Set native VLAN on trunk'),
                    ('show interfaces trunk', 'Display trunk ports'),
                ],
                'Firmware': [
                    ('show version', 'Display current firmware version and hardware info'),
                    ('copy tftp opcode <ip> <filename>', 'Download and install firmware from TFTP'),
                    ('copy tftp startup-config <ip> <filename>', 'Restore startup config from TFTP'),
                    ('copy startup-config tftp <ip> <filename>', 'Backup startup config to TFTP'),
                    ('write', 'Save current configuration'),
                    ('reboot', 'Reboot to apply new firmware'),
                ],
            },
            'Default': {},
        }

    BANNER_COLORS = [
        "#4caf50",  # green
        "#2196F3",  # blue
        "#ff9800",  # orange
        "#9c27b0",  # purple
        "#e91e63",  # pink
        "#00bcd4",  # cyan
        "#ff5722",  # deep orange
        "#3f51b5",  # indigo
    ]
    _banner_index = 0

    def set_profile_name(self, name):
        """Show the profile name banner at the top of the terminal"""
        if name:
            color = self.banner_color or self.BANNER_COLORS[0]
            self.profile_label.setText(f"  {name}")
            self.profile_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {color};
                    color: #ffffff;
                    font-size: 11pt;
                    font-weight: bold;
                    padding: 4px 10px;
                }}
            """)
            self.profile_label.setVisible(False)  # only shown when detached

    def init_ui(self):
        """Initialize the terminal dialog UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Profile name banner (hidden by default)
        self.profile_label = QLabel()
        self.profile_label.setVisible(False)
        layout.addWidget(self.profile_label)

        # Determine initial vendor before creating terminal widget
        _VENDORS = ['Default', 'Linux', 'Cisco', 'Huawei', 'H3C', 'Juniper',
                    'D-Link', 'Brocade', 'Datacom', 'Fortinet', 'Aruba', 'MikroTik', 'TP-Link']
        initial_vendor = 'Default'
        if self.config:
            saved_vendor = self.config.get('vendor')
            if saved_vendor in _VENDORS:
                initial_vendor = saved_vendor

        # Terminal widget
        self.terminal = TerminalWidget()
        self.terminal.send_input.connect(self.send_to_process)
        self.terminal.size_changed.connect(self._on_terminal_resized)
        self.terminal.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.terminal.set_vendor(initial_vendor)
        self._apply_autocomplete_commands(initial_vendor)

        # Command frequency counter (cmd → use count) for Top Commands panel
        self._cmd_counter = self._load_cmd_counter()
        self.terminal.command_executed.connect(self._record_command)

        # Top Commands side panel (hidden by default)
        self._topcmds_panel = self._build_topcmds_panel()
        self._topcmds_panel.setVisible(False)

        _terminal_row = QHBoxLayout()
        _terminal_row.setContentsMargins(0, 0, 0, 0)
        _terminal_row.setSpacing(0)
        _terminal_row.addWidget(self.terminal, 1)
        _terminal_row.addWidget(self._topcmds_panel)
        _terminal_row_widget = QWidget()
        _terminal_row_widget.setContentsMargins(0, 0, 0, 0)
        _terminal_row_widget.setLayout(_terminal_row)
        layout.addWidget(_terminal_row_widget, 1)

        # ── Status bar ─────────────────────────────────────────────────────────
        self._status_bar = QWidget()
        self._status_bar.setFixedHeight(24)
        self._status_bar.setStyleSheet("background-color: #111111; border-top: 1px solid #252525;")
        _sb_layout = QHBoxLayout(self._status_bar)
        _sb_layout.setContentsMargins(10, 0, 10, 0)
        _sb_layout.setSpacing(6)

        self._conn_dot = QLabel("●")
        self._conn_dot.setStyleSheet("color: #3a3a3a; font-size: 9pt; background: transparent;")
        self._conn_label = QLabel("Não conectado")
        self._conn_label.setStyleSheet("color: #606060; font-size: 8pt; background: transparent;")
        self._session_timer_label = QLabel("")
        self._session_timer_label.setStyleSheet("color: #505050; font-size: 8pt; background: transparent;")

        _sb_layout.addWidget(self._conn_dot)
        _sb_layout.addWidget(self._conn_label)
        _sb_layout.addStretch()
        _sb_layout.addWidget(self._session_timer_label)
        layout.addWidget(self._status_bar)

        self._session_start_time = None
        self._session_elapsed_timer = QTimer()
        self._session_elapsed_timer.timeout.connect(self._update_session_timer)
        self._session_elapsed_timer.start(1000)

        # ── Gradient separator ─────────────────────────────────────────────────
        _grad_sep = QWidget()
        _grad_sep.setFixedHeight(6)
        _grad_sep.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #252525, stop:1 #1e1e1e);"
        )
        layout.addWidget(_grad_sep)

        # ── Control buttons ────────────────────────────────────────────────────
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(10, 5, 10, 10)

        # Font size buttons
        self.font_decrease_btn = QPushButton("A-")
        self.font_decrease_btn.setAutoDefault(False)
        self.font_decrease_btn.setMinimumHeight(35)
        self.font_decrease_btn.setMaximumWidth(50)
        self.font_decrease_btn.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        self.font_decrease_btn.clicked.connect(self.terminal.decrease_font_size)
        self.font_decrease_btn.setStyleSheet("""
            QPushButton {
                background-color: #455a64;
                color: #cfd8dc;
                border: none;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #546e7a;
            }
            QPushButton:pressed {
                background-color: #37474f;
            }
        """)

        self.font_increase_btn = QPushButton("A+")
        self.font_increase_btn.setAutoDefault(False)
        self.font_increase_btn.setMinimumHeight(35)
        self.font_increase_btn.setMaximumWidth(50)
        self.font_increase_btn.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        self.font_increase_btn.clicked.connect(self.terminal.increase_font_size)
        self.font_increase_btn.setStyleSheet("""
            QPushButton {
                background-color: #455a64;
                color: #cfd8dc;
                border: none;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #546e7a;
            }
            QPushButton:pressed {
                background-color: #37474f;
            }
        """)

        # Vendor selector — flat button with icon + name + ▾, opens a QMenu
        self._current_vendor = initial_vendor

        self.vendor_btn = QPushButton()
        self.vendor_btn.setFixedHeight(35)
        self.vendor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vendor_btn.setToolTip("Select vendor / syntax highlight")
        self.vendor_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: #e0e0e0;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                padding: 4px 10px 4px 4px;
                font-size: 10pt;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #383838;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
        """)

        # Build QMenu for vendor selection
        self._vendor_menu = QMenu(self)
        self._vendor_menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #484848;
                border-radius: 6px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 7px 20px 7px 10px;
            }
            QMenu::item:selected {
                background-color: #3a3a3a;
                border-radius: 6px;
            }
            QMenu::item:checked {
                color: #64b5f6;
            }
        """)
        for v in _VENDORS:
            action = self._vendor_menu.addAction(v)
            action.setCheckable(True)
            _ip = self.get_vendor_icon_path(v)
            _pm = load_svg_pixmap(_ip, 18)
            if _pm and not _pm.isNull():
                action.setIcon(QIcon(_pm))
            action.triggered.connect(lambda checked, name=v: self.change_vendor(name))

        self.vendor_btn.clicked.connect(self._show_vendor_menu)
        self.update_vendor_icon(initial_vendor)

        # Quick reference button — notebook icon
        self.quickref_btn = QPushButton()
        self.quickref_btn.setFixedSize(36, 36)
        self.quickref_btn.setFlat(True)
        self.quickref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quickref_btn.setToolTip("Quick reference guide")
        self.quickref_btn.setStyleSheet("""
            QPushButton { border: none; border-radius: 6px; padding: 2px; background-color: transparent; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #4a4a4a; }
        """)
        _qr_icon_path = self.get_icon_path('quickref.svg')
        _qr_pixmap = load_svg_pixmap(_qr_icon_path, 28)
        if _qr_pixmap and not _qr_pixmap.isNull():
            self.quickref_btn.setIcon(QIcon(_qr_pixmap))
            self.quickref_btn.setIconSize(QSize(28, 28))
        self.quickref_btn.clicked.connect(self.open_vendor_reference)

        # Sticky note button
        self.stickynote_btn = QPushButton()
        self.stickynote_btn.setFixedSize(36, 36)
        self.stickynote_btn.setFlat(True)
        self.stickynote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stickynote_btn.setToolTip("Quick notes")
        self.stickynote_btn.setStyleSheet("""
            QPushButton { border: none; border-radius: 6px; padding: 2px; background-color: transparent; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #4a4a4a; }
        """)
        _sn_icon_path = self.get_icon_path('stickynote.svg')
        _sn_pixmap = load_svg_pixmap(_sn_icon_path, 28)
        if _sn_pixmap and not _sn_pixmap.isNull():
            self.stickynote_btn.setIcon(QIcon(_sn_pixmap))
            self.stickynote_btn.setIconSize(QSize(28, 28))
        self.stickynote_btn.clicked.connect(self.open_sticky_note)

        def _make_vsep():
            s = QFrame()
            s.setFrameShape(QFrame.Shape.VLine)
            s.setFixedWidth(1)
            s.setStyleSheet("background-color: #333333; border: none;")
            return s

        # Top Commands toggle button
        self.topcmds_btn = QPushButton()
        self.topcmds_btn.setFixedSize(36, 36)
        self.topcmds_btn.setFlat(True)
        self.topcmds_btn.setCheckable(True)
        self.topcmds_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topcmds_btn.setToolTip("Top used commands")
        self.topcmds_btn.setStyleSheet("""
            QPushButton { border: none; border-radius: 6px; padding: 2px; background-color: transparent; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #4a4a4a; }
            QPushButton:checked { background-color: #2a3a4a; }
        """)
        _tc_icon_path = self.get_icon_path('topcmds.svg')
        _tc_pixmap = load_svg_pixmap(_tc_icon_path, 28)
        if _tc_pixmap and not _tc_pixmap.isNull():
            self.topcmds_btn.setIcon(QIcon(_tc_pixmap))
            self.topcmds_btn.setIconSize(QSize(28, 28))
        self.topcmds_btn.clicked.connect(self._toggle_topcmds_panel)

        # Group 1 – font size
        button_layout.addWidget(self.font_decrease_btn)
        button_layout.addSpacing(6)
        button_layout.addWidget(self.font_increase_btn)
        button_layout.addSpacing(10)
        button_layout.addWidget(_make_vsep())
        button_layout.addSpacing(10)
        # Group 2 – vendor
        button_layout.addWidget(self.vendor_btn)
        button_layout.addSpacing(6)
        button_layout.addWidget(self.quickref_btn)
        button_layout.addSpacing(6)
        button_layout.addWidget(self.topcmds_btn)
        button_layout.addSpacing(10)
        button_layout.addWidget(_make_vsep())
        button_layout.addStretch()

        # Search widgets (centered)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.search_input.setMinimumHeight(35)
        self.search_input.setMaximumWidth(200)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #5a5a5a;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 10pt;
            }
            QLineEdit:focus {
                border: 1px solid #707070;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._search_next)

        search_nav_style = """
            QPushButton {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #5a5a5a;
                border-radius: 6px;
                font-size: 10pt;
                min-width: 0px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #454545;
            }
        """

        self.search_prev_btn = QPushButton()
        self.search_prev_btn.setAutoDefault(False)
        self.search_prev_btn.setFixedSize(30, 35)
        self.search_prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_prev_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.search_prev_btn.setToolTip("Previous match")
        self.search_prev_btn.setStyleSheet(search_nav_style)
        self.search_prev_btn.clicked.connect(self._search_prev)

        self.search_next_btn = QPushButton()
        self.search_next_btn.setAutoDefault(False)
        self.search_next_btn.setFixedSize(30, 35)
        self.search_next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_next_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.search_next_btn.setToolTip("Next match")
        self.search_next_btn.setStyleSheet(search_nav_style)
        self.search_next_btn.clicked.connect(self._search_next)

        self.search_status = QLabel()
        self.search_status.setStyleSheet("color: #b0b0b0; font-size: 9pt;")

        # Group 3 – search + quick notes
        button_layout.addWidget(self.search_input)
        button_layout.addSpacing(4)
        button_layout.addWidget(self.search_prev_btn)
        button_layout.addWidget(self.search_next_btn)
        button_layout.addSpacing(6)
        button_layout.addWidget(self.search_status)
        button_layout.addSpacing(6)
        button_layout.addWidget(self.stickynote_btn)

        button_bar = QWidget()
        button_bar.setStyleSheet("background-color: #1e1e1e;")
        button_bar.setLayout(button_layout)
        layout.addWidget(button_bar)

        # ── Disconnect overlay ─────────────────────────────────────────────────
        self._disconnect_overlay = _DisconnectOverlay(self)
        self._disconnect_overlay.hide()
        self.session_disconnected.connect(self._on_session_ended)

        self.setLayout(layout)

    def keyPressEvent(self, event):
        """Handle Ctrl+F to focus search input"""
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.search_input.setFocus()
            self.search_input.selectAll()
        elif event.key() == Qt.Key.Key_Escape and self.search_input.hasFocus():
            self.search_input.clear()
            self.search_status.clear()
            self._search_matches = []
            self.terminal.setExtraSelections([])
            # Exit search mode: unfreeze display and scroll to bottom
            self.terminal._search_active = False
            self.terminal._in_scrollback_mode = False
            self.terminal._render_needed = True
            self.terminal.setFocus()
        else:
            super().keyPressEvent(event)

    def _on_search_changed(self, text):
        """Live search as the user types"""
        self._search_matches = []
        self._search_match_idx = -1
        if not text:
            self.search_status.clear()
            self.terminal.setExtraSelections([])
            # Exit search mode: unfreeze display and scroll to bottom
            self.terminal._search_active = False
            self.terminal._in_scrollback_mode = False
            self.terminal._render_needed = True
            return
        # Enter search mode: inject full scrollback into document and freeze updates
        self.terminal._search_active = True
        if not self.terminal._in_scrollback_mode:
            self.terminal._enter_scrollback_mode()
        lines = self._get_terminal_lines()
        matches = []
        lower_query = text.lower()
        for i, line in enumerate(lines):
            idx = 0
            lower_line = line.lower()
            while True:
                pos = lower_line.find(lower_query, idx)
                if pos == -1:
                    break
                matches.append((i, pos))
                idx = pos + 1
        self._search_matches = matches
        if not matches:
            self.search_status.setText("No results")
            return
        self._search_match_idx = 0
        self._show_search_result()

    def _get_terminal_lines(self):
        """Get all terminal lines (scrollback + current screen) as plain text list"""
        import re
        tag_re = re.compile(r'<[^>]+>')
        lines = []
        for html_line in self.terminal._scrollback_lines:
            plain = tag_re.sub('', html_line)
            plain = plain.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
            lines.append(plain)
        for y in range(self.terminal.screen.lines):
            row = self.terminal.screen.buffer[y]
            line = ''.join(row[x].data for x in range(self.terminal.screen.columns)).rstrip()
            lines.append(line)
        return lines

    def _search_next(self):
        """Navigate to next search match"""
        if not getattr(self, '_search_matches', None):
            return
        self._search_match_idx = (self._search_match_idx + 1) % len(self._search_matches)
        self._show_search_result()

    def _search_prev(self):
        """Navigate to previous search match"""
        if not getattr(self, '_search_matches', None):
            return
        self._search_match_idx = (self._search_match_idx - 1) % len(self._search_matches)
        self._show_search_result()

    def _show_search_result(self):
        """Scroll to and highlight all search matches using ExtraSelections"""
        matches = self._search_matches
        idx = self._search_match_idx
        self.search_status.setText(f"{idx + 1}/{len(matches)}")

        query = self.search_input.text()
        query_len = len(query)

        # Build ExtraSelections for all matches
        doc = self.terminal.document()
        selections = []
        current_sel = None
        for i, (line_num, col) in enumerate(matches):
            block = doc.findBlockByLineNumber(line_num)
            if not block.isValid():
                continue
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + col)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, query_len)

            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            if i == idx:
                # Current match: bright orange
                fmt.setBackground(QColor("#ff9800"))
                fmt.setForeground(QColor("#000000"))
                nav_cursor = QTextCursor(block)
                nav_cursor.setPosition(block.position() + col)
                current_sel = nav_cursor
            else:
                # Other matches: yellow
                fmt.setBackground(QColor("#ffeb3b"))
                fmt.setForeground(QColor("#000000"))
            sel.format = fmt
            sel.cursor = cursor
            selections.append(sel)

        self.terminal.setExtraSelections(selections)

        # Scroll to current match
        if current_sel:
            # Move cursor to match position and scroll to it
            current_sel.clearSelection()
            self.terminal.setTextCursor(current_sel)
            self.terminal.ensureCursorVisible()

    def update_vendor_icon(self, vendor):
        """Update the vendor button icon and label."""
        icon_path = self.get_vendor_icon_path(vendor)
        pixmap = load_svg_pixmap(icon_path, 20)
        if not (pixmap and not pixmap.isNull()):
            fallback_path = self.get_vendor_icon_path('Default')
            pixmap = load_svg_pixmap(fallback_path, 20)
        if pixmap and not pixmap.isNull():
            self.vendor_btn.setIcon(QIcon(pixmap))
            self.vendor_btn.setIconSize(QSize(20, 20))
        self.vendor_btn.setText(f"  {vendor}  ▾")
        # Tick the active item in the menu
        for action in self._vendor_menu.actions():
            action.setChecked(action.text() == vendor)

    def _show_vendor_menu(self):
        """Show the vendor QMenu anchored below the vendor button."""
        from PyQt6.QtCore import QPoint
        pos = self.vendor_btn.mapToGlobal(QPoint(0, self.vendor_btn.height()))
        self._vendor_menu.exec(pos)

    # ── Top Commands panel ────────────────────────────────────────────────────

    def _build_topcmds_panel(self):
        """Build the collapsible right-side Top Commands panel."""
        panel = QWidget()
        panel.setFixedWidth(230)
        panel.setStyleSheet("background-color: #141414; border-left: 1px solid #2a2a2a;")

        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #2a2a2a;")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(10, 0, 6, 0)
        hdr_layout.setSpacing(4)

        self._topcmds_title_lbl = QLabel("Top Commands")
        self._topcmds_title_lbl.setStyleSheet("color: #89b4fa; font-size: 9pt; font-weight: bold; background: transparent; border: none;")
        title_lbl = self._topcmds_title_lbl
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()

        clear_btn = QPushButton("🗑")
        clear_btn.setFixedSize(20, 20)
        clear_btn.setFlat(True)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Clear command history")
        clear_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #585b70; border: none; font-size: 9pt; }
            QPushButton:hover { color: #f38ba8; }
        """)
        clear_btn.clicked.connect(self._clear_topcmds)
        hdr_layout.addWidget(clear_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #585b70; border: none; font-size: 9pt; }
            QPushButton:hover { color: #cdd6f4; }
        """)
        close_btn.clicked.connect(lambda: self._toggle_topcmds_panel(False))
        hdr_layout.addWidget(close_btn)
        vbox.addWidget(header)

        # List
        self._topcmds_list = QListWidget()
        self._topcmds_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._topcmds_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                color: #cdd6f4;
                font-family: Monospace;
                font-size: 9pt;
                outline: none;
            }
            QListWidget::item {
                padding: 5px 10px;
                border-bottom: 1px solid #1e1e1e;
            }
            QListWidget::item:hover {
                background-color: #1e2030;
                color: #89dceb;
            }
            QListWidget::item:selected {
                background-color: #2a3a4a;
                color: #89dceb;
            }
            QScrollBar:vertical {
                background: #141414; width: 5px; border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: #2a2a2a; border-radius: 2px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        self._topcmds_list.itemClicked.connect(self._topcmds_send)
        vbox.addWidget(self._topcmds_list, 1)

        # Footer hint
        hint = QLabel("Click to paste and run")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("""
            background-color: #111111;
            color: #45475a;
            font-size: 8pt;
            padding: 4px;
            border-top: 1px solid #2a2a2a;
        """)
        hint.setFixedHeight(20)
        vbox.addWidget(hint)

        return panel

    def _record_command(self, cmd):
        """Increment the frequency counter for cmd under the current vendor, persist and refresh."""
        if not cmd:
            return
        vendor = self._current_vendor
        vendor_cmds = self._cmd_counter.setdefault(vendor, {})
        vendor_cmds[cmd] = vendor_cmds.get(cmd, 0) + 1
        self._save_cmd_counter()
        self._refresh_topcmds_list()

    def _refresh_topcmds_list(self):
        """Rebuild the top-10 list for the current vendor, sorted by frequency."""
        if hasattr(self, '_topcmds_title_lbl'):
            self._topcmds_title_lbl.setText(f"Top — {self._current_vendor}")
        vendor_cmds = self._cmd_counter.get(self._current_vendor, {})
        top10 = sorted(vendor_cmds.items(), key=lambda x: x[1], reverse=True)[:10]
        self._topcmds_list.clear()
        for rank, (cmd, count) in enumerate(top10, 1):
            item = QListWidgetItem()
            item.setText(cmd)
            item.setToolTip(f"Used {count} time{'s' if count != 1 else ''}")
            item.setData(Qt.ItemDataRole.UserRole, cmd)
            item.setData(Qt.ItemDataRole.UserRole + 1, count)
            self._topcmds_list.addItem(item)
        self._topcmds_list.setItemDelegate(_TopCmdsDelegate(self._topcmds_list))

    def _topcmds_send(self, item):
        """Send the selected command to the terminal and execute it."""
        cmd = item.data(Qt.ItemDataRole.UserRole)
        if cmd:
            self.terminal.send_input.emit(cmd + '\r')
            self._topcmds_list.clearSelection()

    def _cmd_history_path(self):
        """Return the path to the persistent command history file."""
        try:
            return os.path.join(self.config.config_dir, 'cmd_history.json')
        except Exception:
            return os.path.join(Path.home(), '.config', 'cetus', 'cmd_history.json')

    def _load_cmd_counter(self):
        """Load the per-vendor command frequency counters from disk.

        Returns a dict of {vendor: {cmd: count}}.
        Handles migration from the old flat {cmd: count} format by moving
        existing entries under the 'Default' vendor key.
        """
        path = self._cmd_history_path()
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Migrate old flat format: values are ints, not dicts
                    if data and all(isinstance(v, int) for v in data.values()):
                        return {'Default': {str(k): int(v) for k, v in data.items()}}
                    # Normal nested format
                    return {
                        vendor: {str(cmd): int(cnt) for cmd, cnt in cmds.items()}
                        for vendor, cmds in data.items()
                        if isinstance(cmds, dict)
                    }
        except Exception as e:
            print(f"[topcmds] Could not load cmd_history.json: {e}")
        return {}

    def _save_cmd_counter(self):
        """Persist the command frequency counter to disk."""
        path = self._cmd_history_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._cmd_counter, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[topcmds] Could not save cmd_history.json: {e}")

    def _clear_topcmds(self):
        """Clear the counter for the current vendor, refresh the list and persist."""
        self._cmd_counter.pop(self._current_vendor, None)
        self._topcmds_list.clear()
        self._save_cmd_counter()

    def _toggle_topcmds_panel(self, checked=None):
        """Show or hide the Top Commands panel."""
        if checked is None:
            checked = not self._topcmds_panel.isVisible()
        self._topcmds_panel.setVisible(checked)
        self.topcmds_btn.setChecked(bool(checked))

    def open_vendor_reference(self):
        """Open the vendor quick reference guide dialog"""
        vendor = self._current_vendor
        reference_data = self.get_vendor_reference().get(vendor, {})
        icon_path = self.get_vendor_icon_path(vendor)
        dialog = VendorReferenceDialog(
            vendor, reference_data, icon_path, parent=self,
            send_command_callback=self.terminal.send_input.emit,
        )
        dialog.show()

    def open_sticky_note(self):
        """Open (or bring to front) the shared Quick Notes window."""
        if self._sticky_note_dlg and self._sticky_note_dlg.isVisible():
            self._sticky_note_dlg.set_device_info(self._note_name, self._note_ip)
            self._sticky_note_dlg.raise_()
            self._sticky_note_dlg.activateWindow()
            return
        self._sticky_note_dlg = StickyNoteDialog(
            config=self.config,
            device_name=self._note_name,
            device_ip=self._note_ip,
            parent=self,
        )
        self._sticky_note_dlg.show()

    def change_vendor(self, vendor):
        """Change the syntax highlighting vendor"""
        self._current_vendor = vendor
        self.terminal.set_vendor(vendor)
        self.update_vendor_icon(vendor)
        self._apply_autocomplete_commands(vendor)
        self._refresh_topcmds_list()

        # Save vendor selection
        if self.config:
            self.config.set('vendor', vendor)

    def _apply_autocomplete_commands(self, vendor):
        """Load the quick-reference commands for *vendor* into the terminal autocomplete."""
        ref  = TerminalDialog.get_vendor_reference().get(vendor, {})
        cmds = [(cmd, desc) for cat_cmds in ref.values() for cmd, desc in cat_cmds]
        self.terminal.set_autocomplete_commands(cmds)

    def start_picocom(self, cmd):
        """Start serial connection via picocom (Linux) or pyserial (Windows)"""
        if sys.platform == 'win32':
            return self._start_pyserial(cmd)
        # Linux path - use picocom via QProcess
        password, ok = QInputDialog.getText(
            self, "Sudo Password Required",
            "Please enter your sudo password to access serial port:",
            QLineEdit.EchoMode.Password
        )
        if not ok or not password:
            self.terminal.append_output("[CANCELLED] Password not provided\n")
            return False

        # Create the process
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)

        # Build sudo command
        picocom_cmd = ' '.join(cmd)
        full_cmd = ['sudo', '-S'] + cmd

        # Start process
        self.terminal.append_output(f"Starting: {picocom_cmd}\n")

        self.process.start(full_cmd[0], full_cmd[1:])

        if not self.process.waitForStarted(3000):
            self.terminal.append_output("\n[ERROR] Failed to start picocom\n")
            return False

        # Send password to sudo
        self.process.write((password + '\n').encode())
        password = None  # Clear password from memory

        self.terminal.append_output("Connecting...\n\n")

        return True

    def _start_pyserial(self, cmd):
        """Start serial connection using pyserial on Windows.
        cmd is the picocom command list; we parse parameters from it."""
        try:
            import serial
        except ImportError:
            self.terminal.append_output("[ERROR] pyserial not installed. Run: pip install pyserial\n")
            return False

        # Parse picocom-style command to extract params
        # cmd format: ['picocom', '-b', '9600', '-d', '8', '-p', 'n', '-f', 'n', 'COM3']
        port = cmd[-1]
        baudrate = '9600'
        databits = 8
        parity = serial.PARITY_NONE
        stopbits = serial.STOPBITS_ONE
        flow = serial.XOFF

        i = 0
        while i < len(cmd) - 1:
            if cmd[i] == '-b' and i + 1 < len(cmd):
                baudrate = cmd[i + 1]
            elif cmd[i] == '-d' and i + 1 < len(cmd):
                databits = int(cmd[i + 1])
            elif cmd[i] == '-p' and i + 1 < len(cmd):
                p = cmd[i + 1].lower()
                parity = {'n': serial.PARITY_NONE, 'e': serial.PARITY_EVEN, 'o': serial.PARITY_ODD}.get(p, serial.PARITY_NONE)
            elif cmd[i] == '-f' and i + 1 < len(cmd):
                f = cmd[i + 1].lower()
                flow = {'h': serial.XON, 's': serial.XOFF, 'n': False}.get(f, False)
            i += 1

        try:
            self.serial_conn = serial.Serial(
                port=port,
                baudrate=int(baudrate),
                bytesize={5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}.get(databits, serial.EIGHTBITS),
                parity=parity,
                stopbits={1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}.get(stopbits, serial.STOPBITS_ONE),
                xonxoff=(flow == serial.XOFF),
                rtscts=(flow == serial.XON),
                timeout=0.1
            )
            self.serial_running = True
            self.connection_type = 'serial'

            # Start read thread
            self.serial_read_thread = threading.Thread(target=self._pyserial_read_loop, daemon=True)
            self.serial_read_thread.start()

            self.terminal.append_output(f"Connected to {port} @ {baudrate} baud\n\n")
            return True
        except Exception as e:
            self.terminal.append_output(f"[ERROR] Failed to open serial port: {e}\n")
            return False

    def _pyserial_read_loop(self):
        """Background thread that reads from serial port and emits to terminal."""
        while self.serial_running and self.serial_conn and self.serial_conn.is_open:
            try:
                data = self.serial_conn.read(1024)
                if data:
                    text = data.decode('utf-8', errors='replace')
                    # Use signal for thread-safe GUI update
                    self.ssh_output_received.emit(text)
            except Exception:
                break
        self.serial_running = False

    def start_debug_mode(self):
        """Start terminal in debug mode with simulated Cisco router output"""
        self.setWindowTitle("Cetus Terminal [DEBUG MODE]")

        # Simulated Cisco router configuration
        cisco_output = """\r
\r
Router>\x1b[33menable\x1b[0m\r
Password: \r
Router#\x1b[33mshow running-config\x1b[0m\r
Building configuration...\r
\r
Current configuration : 1584 bytes\r
!\r
! Last configuration change at 14:32:15 UTC Mon Jan 15 2024\r
!\r
version 15.1\r
service timestamps debug datetime msec\r
service timestamps log datetime msec\r
no service password-encryption\r
!\r
hostname \x1b[36mRouter\x1b[0m\r
!\r
boot-start-marker\r
boot-end-marker\r
!\r
enable secret 5 $1$mERr$hx5rVt7rPNoS4wqbXKX7m0\r
!\r
no aaa new-model\r
!\r
interface \x1b[36mGigabitEthernet0/0\x1b[0m\r
 description \x1b[32mWAN Connection to ISP\x1b[0m\r
 ip address \x1b[33m203.0.113.1\x1b[0m \x1b[33m255.255.255.252\x1b[0m\r
 duplex auto\r
 speed auto\r
!\r
interface \x1b[36mGigabitEthernet0/1\x1b[0m\r
 description \x1b[32mLAN Network\x1b[0m\r
 ip address \x1b[33m192.168.1.1\x1b[0m \x1b[33m255.255.255.0\x1b[0m\r
 duplex auto\r
 speed auto\r
!\r
interface \x1b[36mGigabitEthernet0/2\x1b[0m\r
 description \x1b[32mDMZ Network\x1b[0m\r
 ip address \x1b[33m10.0.0.1\x1b[0m \x1b[33m255.255.255.0\x1b[0m\r
 duplex auto\r
 speed auto\r
!\r
ip route \x1b[33m0.0.0.0\x1b[0m \x1b[33m0.0.0.0\x1b[0m \x1b[33m203.0.113.2\x1b[0m\r
!\r
ip access-list extended \x1b[36mINBOUND_ACL\x1b[0m\r
 \x1b[32mpermit\x1b[0m tcp any any eq \x1b[33m22\x1b[0m\r
 \x1b[32mpermit\x1b[0m tcp any any eq \x1b[33m80\x1b[0m\r
 \x1b[32mpermit\x1b[0m tcp any any eq \x1b[33m443\x1b[0m\r
 \x1b[31mdeny\x1b[0m ip any any log\r
!\r
line con 0\r
 logging synchronous\r
line aux 0\r
line vty 0 4\r
 login local\r
 transport input ssh\r
!\r
end\r
\r
Router#\x1b[33mshow ip interface brief\x1b[0m\r
Interface              IP-Address      OK? Method Status                Protocol\r
GigabitEthernet0/0     \x1b[33m203.0.113.1\x1b[0m     YES NVRAM  \x1b[32mup\x1b[0m                    \x1b[32mup\x1b[0m\r
GigabitEthernet0/1     \x1b[33m192.168.1.1\x1b[0m     YES NVRAM  \x1b[32mup\x1b[0m                    \x1b[32mup\x1b[0m\r
GigabitEthernet0/2     \x1b[33m10.0.0.1\x1b[0m        YES NVRAM  \x1b[32mup\x1b[0m                    \x1b[32mup\x1b[0m\r
\r
Router#\x1b[33mshow version\x1b[0m\r
Cisco IOS Software, C2900 Software (C2900-UNIVERSALK9-M), Version 15.1(4)M4\r
Technical Support: http://www.cisco.com/techsupport\r
Copyright (c) 1986-2012 by Cisco Systems, Inc.\r
\r
ROM: System Bootstrap, Version 15.0(1r)M9\r
\r
Router uptime is \x1b[33m2 days, 14 hours, 32 minutes\x1b[0m\r
System returned to ROM by power-on\r
System image file is "flash:c2900-universalk9-mz.SPA.151-4.M4.bin"\r
\r
Cisco CISCO2911/K9 (revision 1.0) with \x1b[33m512000K/62464K\x1b[0m bytes of memory.\r
Processor board ID FTX1524A0WZ\r
3 Gigabit Ethernet interfaces\r
DRAM configuration is 64 bits wide with parity disabled.\r
256K bytes of non-volatile configuration memory.\r
\r
Router#_\r
"""

        # Feed the simulated output to the terminal
        self.terminal.append_output(cisco_output)

    def send_to_process(self, text):
        """Send input to the active connection (picocom/pyserial, SSH, or Telnet)"""
        if self.connection_type == 'ssh':
            self.send_to_ssh(text)
        elif self.connection_type == 'telnet':
            self.send_to_telnet(text)
        elif sys.platform == 'win32' and self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.write(text.encode())
        elif self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write(text.encode())

    def start_ssh(self, host, port, username, password=None, key_path=None):
        """Start SSH connection using paramiko"""
        if not SSH_AVAILABLE:
            self.terminal.append_output("[ERROR] paramiko library not installed\n")
            self.terminal.append_output("Install with: pip install paramiko\n")
            return False

        self.connection_type = 'ssh'
        self.setWindowTitle(f"Cetus Terminal - SSH: {username}@{host}")

        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            self.terminal.append_output(f"Connecting to {host}:{port}...\n")

            if key_path:
                # Key-based authentication
                key = paramiko.RSAKey.from_private_key_file(key_path)
                self.ssh_client.connect(
                    host, port=int(port), username=username, pkey=key,
                    timeout=10, banner_timeout=15, auth_timeout=15,
                    allow_agent=False, look_for_keys=False
                )
            else:
                # Password authentication
                self.ssh_client.connect(
                    host, port=int(port), username=username, password=password,
                    timeout=10, banner_timeout=15, auth_timeout=15,
                    allow_agent=False, look_for_keys=False
                )

            # Request a pseudo-terminal with actual widget dimensions
            cols = self.terminal.screen.columns
            rows = self.terminal.screen.lines
            # Open session manually so we can inject env vars between PTY and shell
            # requests (invoke_shell high-level API doesn't allow this).
            _transport = self.ssh_client.get_transport()
            self.ssh_channel = _transport.open_session()
            self.ssh_channel.get_pty(term='xterm', width=cols, height=rows)
            try:
                # COLORTERM=truecolor tells nano/vim/etc. to use full 24-bit colour.
                # Without it, some apps fall back to bold-only highlighting even when
                # TERM=xterm.  Many SSH servers restrict AcceptEnv so we
                # silently ignore failures.
                self.ssh_channel.set_environment_variable('COLORTERM', 'truecolor')
            except Exception:
                pass
            self.ssh_channel.invoke_shell()
            self.ssh_channel.settimeout(0.1)
            self.ssh_running = True

            # Start read thread
            self.ssh_read_thread = threading.Thread(target=self._ssh_read_loop, daemon=True)
            self.ssh_read_thread.start()

            self.terminal.append_output(f"Connected to {host}\n\n")
            # Ensure terminal has focus for keyboard input
            self.terminal.setFocus()
            return True

        except paramiko.AuthenticationException:
            self.terminal.append_output("[ERROR] Authentication failed\n")
            return False
        except paramiko.SSHException as e:
            self.terminal.append_output(f"[ERROR] SSH error: {e}\n")
            return False
        except Exception as e:
            self.terminal.append_output(f"[ERROR] Connection failed: {e}\n")
            return False

    def _ssh_read_loop(self):
        """Background thread to read SSH output"""
        import time
        buf = []
        last_emit = time.monotonic()
        BATCH_INTERVAL = 0.05  # emit at most 20x/s

        while self.ssh_running and self.ssh_channel:
            try:
                if self.ssh_channel.recv_ready():
                    data = self.ssh_channel.recv(16384)
                    if data:
                        buf.append(data.decode('utf-8', errors='replace'))
                now = time.monotonic()
                if buf and (now - last_emit >= BATCH_INTERVAL or not self.ssh_channel.recv_ready()):
                    # Feed pyte HERE in the worker thread — avoids blocking the main thread
                    self.terminal.feed_from_worker(''.join(buf))
                    buf.clear()
                    last_emit = now
                elif not buf:
                    time.sleep(0.01)
            except socket.timeout:
                continue
            except Exception as e:
                if self.ssh_running:
                    self.ssh_output_received.emit(f"\n[SSH Error: {e}]\n")
                break
        # Unexpected disconnect (server closed connection while we were still running)
        if self.ssh_running:
            self.ssh_running = False
            self.session_disconnected.emit()

    def _on_ssh_output(self, text):
        """Slot for error/status messages that need to appear in the terminal."""
        self.terminal.append_output(text)

    def send_to_ssh(self, text):
        """Send input to SSH channel"""
        if self.ssh_channel and self.ssh_running:
            try:
                self.ssh_channel.send(text.encode('utf-8'))
            except Exception as e:
                msg = str(e).lower()
                if any(k in msg for k in ('closed', 'not connected', 'eof', 'broken pipe')):
                    return  # channel teardown — not a real error
                self.terminal.append_output(f"\n[Send error: {e}]\n")

    def _on_terminal_resized(self, cols, rows):
        """Notify the remote PTY about the new terminal size"""
        if self.ssh_channel and self.ssh_running:
            try:
                self.ssh_channel.resize_pty(width=cols, height=rows)
            except Exception:
                pass
        if self.telnet_client and self.telnet_running:
            try:
                # Send Telnet NAWS (Negotiate About Window Size)
                import struct
                naws = struct.pack('!HH', cols, rows)
                self.telnet_client.get_socket().sendall(
                    b'\xff\xfa\x1f' + naws + b'\xff\xf0'
                )
            except Exception:
                pass

    def disconnect_ssh(self):
        """Disconnect SSH session"""
        self.ssh_running = False
        if self.ssh_channel:
            try:
                self.ssh_channel.close()
            except:
                pass
            self.ssh_channel = None
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except:
                pass
            self.ssh_client = None

    def start_telnet(self, host, port, username=None):
        """Start Telnet connection"""
        if not TELNET_AVAILABLE:
            self.terminal.append_output("[ERROR] telnetlib not available\n")
            self.terminal.append_output("Install with: pip install standard-telnetlib\n")
            return False
        self.connection_type = 'telnet'
        self.setWindowTitle(f"Cetus Terminal - Telnet: {host}")

        try:
            self.terminal.append_output(f"Connecting to {host}:{port}...\n")
            self.telnet_client = telnetlib.Telnet(host, int(port), timeout=10)
            self.telnet_running = True

            # Start read thread
            self.telnet_read_thread = threading.Thread(target=self._telnet_read_loop, daemon=True)
            self.telnet_read_thread.start()

            self.terminal.append_output(f"Connected to {host}\n\n")
            # Ensure terminal has focus for keyboard input
            self.terminal.setFocus()
            return True

        except Exception as e:
            self.terminal.append_output(f"[ERROR] Connection failed: {e}\n")
            return False

    def _telnet_read_loop(self):
        """Background thread to read Telnet output"""
        import time
        buf = []
        last_emit = time.monotonic()
        BATCH_INTERVAL = 0.05

        while self.telnet_running and self.telnet_client:
            try:
                data = self.telnet_client.read_very_eager()
                if data:
                    buf.append(data.decode('utf-8', errors='replace'))
                now = time.monotonic()
                if buf and (now - last_emit >= BATCH_INTERVAL or not data):
                    self.terminal.feed_from_worker(''.join(buf))
                    buf.clear()
                    last_emit = now
                elif not buf:
                    time.sleep(0.01)
            except EOFError:
                if self.telnet_running:
                    self.ssh_output_received.emit("\n[Connection closed by remote host]\n")
                break
            except Exception as e:
                if self.telnet_running:
                    self.ssh_output_received.emit(f"\n[Telnet Error: {e}]\n")
                break
        # Unexpected disconnect
        if self.telnet_running:
            self.telnet_running = False
            self.session_disconnected.emit()

    def send_to_telnet(self, text):
        """Send input to Telnet connection"""
        if self.telnet_client and self.telnet_running:
            try:
                self.telnet_client.write(text.encode('utf-8'))
            except Exception as e:
                msg = str(e).lower()
                if any(k in msg for k in ('closed', 'not connected', 'eof', 'broken pipe')):
                    return  # connection teardown — not a real error
                self.terminal.append_output(f"\n[Send error: {e}]\n")

    def disconnect_telnet(self):
        """Disconnect Telnet session"""
        self.telnet_running = False
        if self.telnet_client:
            try:
                self.telnet_client.close()
            except:
                pass
            self.telnet_client = None
    
    def handle_stdout(self):
        """Handle standard output from picocom"""
        if self.process:
            data = self.process.readAllStandardOutput()
            text = bytes(data).decode('utf-8', errors='replace')
            self.terminal.append_output(text)
    
    def handle_stderr(self):
        """Handle standard error from picocom"""
        if self.process:
            data = self.process.readAllStandardError()
            text = bytes(data).decode('utf-8', errors='replace')
            self.terminal.append_output(text)
    
    def process_finished(self, exit_code, exit_status):
        """Handle process termination"""
        self.terminal.append_output(f"\n\n[Process terminated with exit code {exit_code}]\n")
        self.terminal.append_output("You can close this window.\n")
    def disconnect(self):
        """Disconnect from serial port, SSH, or Telnet"""
        if self.connection_type == 'ssh':
            self.disconnect_ssh()
        elif self.connection_type == 'telnet':
            self.disconnect_telnet()
        elif sys.platform == 'win32' and self.serial_conn:
            # Close pyserial connection on Windows
            self.serial_running = False
            try:
                self.serial_conn.close()
            except Exception:
                pass
            self.serial_conn = None
        elif self.process and self.process.state() == QProcess.ProcessState.Running:
            # Send Ctrl+A Ctrl+X to exit picocom gracefully
            self.process.write(b'\x01\x18')

            # Wait a bit for graceful exit
            if not self.process.waitForFinished(2000):
                # Force terminate if needed
                self.process.terminate()
                if not self.process.waitForFinished(1000):
                    self.process.kill()

        self.close()
    
    def showEvent(self, event):
        super().showEvent(event)
        # Clear transient parent so the WM treats this as a fully independent window
        if self.windowHandle():
            self.windowHandle().setTransientParent(None)

    def closeEvent(self, event):
        """Handle window close event"""
        is_connected = False
        if self.connection_type == 'ssh':
            is_connected = self.ssh_running
        elif self.connection_type == 'telnet':
            is_connected = self.telnet_running
        elif sys.platform == 'win32' and self.serial_conn:
            is_connected = self.serial_conn.is_open
        elif self.process:
            is_connected = self.process.state() == QProcess.ProcessState.Running

        if is_connected:
            reply = QMessageBox.question(
                self,
                'Confirm Exit',
                'Connection is still active. Disconnect and close?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.disconnect()
                event.accept()
                self.terminal_closed.emit()
            else:
                event.ignore()
        else:
            event.accept()
            self.terminal_closed.emit()


_TEXT_EXTENSIONS = {
    '.txt', '.cfg', '.conf', '.log', '.ini', '.py', '.sh', '.bash', '.zsh',
    '.json', '.yaml', '.yml', '.xml', '.html', '.htm', '.css', '.js', '.ts',
    '.md', '.rst', '.csv', '.env', '.toml', '.service', '.rules', '.list',
    '.repo', '.bat', '.ps1', '.c', '.h', '.cpp', '.java', '.go', '.rb',
    '.php', '.sql', '.diff', '.patch', '.gitignore', '.gitconfig',
}



class DetachableTabBar(QTabBar):
    """QTabBar with right-click context menu to detach a tab into its own window.
    Draws a per-tab coloured indicator strip at the top of each tab."""
    detach_requested = pyqtSignal(int)
    close_requested  = pyqtSignal(int)   # emitted by context-menu "Fechar aba"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_colors: dict[int, QColor] = {}
        self._tab_activity: set[int] = set()  # indices with unread activity

    def set_tab_color(self, index: int, color: str):
        self._tab_colors[index] = QColor(color)
        self.update()

    def set_tab_activity(self, index: int, active: bool):
        if active:
            self._tab_activity.add(index)
        else:
            self._tab_activity.discard(index)
        self.update()

    def paintEvent(self, event):
        # Let Qt draw the default tab chrome (text, close button, selection bg…)
        super().paintEvent(event)
        # Overlay a coloured strip at the top of each tab + activity dot
        painter = QPainter(self)
        for i in range(self.count()):
            rect = self.tabRect(i)
            is_selected = (i == self.currentIndex())
            color = self._tab_colors.get(i)
            if color:
                strip = QColor(color)
                if not is_selected:
                    strip.setAlpha(140)
                painter.fillRect(rect.left(), rect.top(), rect.width(), 3 if is_selected else 2, strip)
            # Activity indicator: small bright dot in top-right corner of inactive tabs
            if i in self._tab_activity and not is_selected:
                dot_color = self._tab_colors.get(i, QColor('#ffffff'))
                dot = QColor(dot_color)
                dot.setAlpha(255)
                painter.setBrush(dot)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(rect.right() - 14, rect.top() + 5, 7, 7)
        painter.end()

    def contextMenuEvent(self, event):
        idx = self.tabAt(event.pos())
        if idx >= 0:
            menu = QMenu(self)
            detach_act = menu.addAction("Detach to independent window")
            menu.addSeparator()
            close_act = menu.addAction("Close tab")
            chosen = menu.exec(event.globalPos())
            if chosen == detach_act:
                self.detach_requested.emit(idx)
            elif chosen == close_act:
                self.close_requested.emit(idx)



class DetachedTerminalWindow(QMainWindow):
    """Standalone window that wraps a TerminalDialog after it has been detached
    from the tabbed view."""

    def __init__(self, dialog: 'TerminalDialog', title: str, reattach_callback=None):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1200, 720)
        self._dialog = dialog
        self._reattach_callback = reattach_callback
        self._reattaching = False  # prevents closeEvent from closing the dialog during reattach

        # Menu bar with a window management option
        win_menu = self.menuBar().addMenu("Window")
        reattach_act = win_menu.addAction("Reattach as tab")
        reattach_act.triggered.connect(self._reattach)

        # Re-parent the dialog widget into this window
        dialog.setParent(self)
        self.setCentralWidget(dialog)
        dialog.show()
        QTimer.singleShot(100, dialog.terminal._recalculate_size)

    def _reattach(self):
        """Move the dialog back into the tabbed window as a new tab."""
        if self._reattach_callback:
            self._reattaching = True
            self._reattach_callback(self._dialog, self.windowTitle(), self)
            self.close()

    def closeEvent(self, event):
        if self._reattaching:
            # Dialog is being moved back to a tab — do not close it
            event.accept()
            return
        # Normal close: delegate to TerminalDialog (handles disconnect confirmation)
        if self._dialog.close():
            event.accept()
        else:
            event.ignore()



class _OverflowTiledWindow(QMainWindow):
    """Standalone window for overflow tiled terminals (groups beyond the first 4).
    Closing it returns all terminals to the main TerminalTabbedWindow as tabs."""

    def __init__(self, tiled_widget, group, main_win):
        super().__init__()
        self.setWindowTitle("Cetus — Terminais")
        self._group = group
        self._main_win = main_win
        self.resize(main_win.width(), main_win.height())
        self.setCentralWidget(tiled_widget)

    def closeEvent(self, event):
        for dialog, label, color in self._group:
            self._main_win._reinsert_tab(dialog, label, color)
        if self in self._main_win._overflow_tiled_windows:
            self._main_win._overflow_tiled_windows.remove(self)
        super().closeEvent(event)



class TerminalTabbedWindow(QMainWindow):
    """Single window that hosts all SSH/Telnet terminal sessions as tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cetus — Terminais")
        self.resize(1280, 750)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)

        tab_bar = DetachableTabBar()
        self.tab_widget.setTabBar(tab_bar)
        tab_bar.detach_requested.connect(self._detach_tab)
        tab_bar.close_requested.connect(self._close_tab)

        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # QStackedWidget lets us swap between tab view and tiled grid view
        self._stack = QStackedWidget()
        self._stack.addWidget(self.tab_widget)   # index 0
        self.setCentralWidget(self._stack)

        self._detached_windows: list = []
        self._tiled_mode = False
        self._tiled_info: list = []          # list of (dialog, label, color_str) in tiled mode
        self._overflow_tiled_windows: list = []  # _OverflowTiledWindow instances for groups 2, 3, …

        # Grid-view toggle button — placed as the left corner widget of the tab bar
        self._tile_btn = QToolButton()
        self._tile_btn.setFixedSize(28, 28)
        self._tile_btn.setToolTip("Grid mode (up to 4 simultaneous terminals)")
        self._tile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tile_btn.setStyleSheet(
            "QToolButton { border: none; background: transparent; border-radius: 6px; padding: 4px; }"
            "QToolButton:hover { background: #2a2a2a; }"
            "QToolButton:checked { background: #1a3a4a; }"
        )
        self._tile_btn.setIcon(self._make_grid_icon(active=False))
        self._tile_btn.clicked.connect(self._toggle_tiled_mode)
        self.tab_widget.setCornerWidget(self._tile_btn, Qt.Corner.TopLeftCorner)

        self._close_btn_icon = self._make_close_btn_icon()
        self._apply_tab_style()

    def _on_tab_changed(self, index: int):
        """Recalculate PTY size when the user switches to a tab."""
        widget = self.tab_widget.widget(index)
        if widget and hasattr(widget, 'terminal'):
            QTimer.singleShot(50, widget.terminal._recalculate_size)
        # Clear activity indicator for the newly focused tab
        self.tab_widget.tabBar().set_tab_activity(index, False)

    def _apply_tab_style(self):
        # NOTE: no 'color:' rule here — text colour is set per-tab via
        # setTabTextColor() so it matches each terminal's banner colour.
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 0; background: #0a0a0a; }
            QTabBar::tab {
                background: #1a1a1a;
                padding: 8px 20px 6px 38px;
                border: none;
                border-right: 1px solid #2a2a2a;
                min-width: 140px;
            }
            QTabBar::tab:selected {
                background: #0d0d0d;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected { background: #212121; }
        """)

    # ── Tiled / grid mode ─────────────────────────────────────────────────────

    def _make_grid_icon(self, active=False):
        """Draw a simple 2×2 grid icon; blue when active, grey otherwise."""
        size = 16
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        color = QColor('#4fc3f7') if active else QColor('#909090')
        p.setPen(color)
        m, mid = 1, size // 2
        p.drawRect(m, m, size - 2 * m - 1, size - 2 * m - 1)
        p.drawLine(mid, m, mid, size - m - 1)
        p.drawLine(m, mid, size - m - 1, mid)
        p.end()
        return QIcon(px)

    def _make_close_btn_icon(self):
        """Draw a small light-coloured '×' icon for the tab close button."""
        size = 16
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#bbbbbb'), 1.8))
        m = 4
        p.drawLine(m, m, size - m, size - m)
        p.drawLine(size - m, m, m, size - m)
        p.end()
        return QIcon(px)

    def _add_tab_close_btn(self, index: int):
        """Attach a tiny '×' button to the right side of a tab."""
        btn = QToolButton(self.tab_widget)
        btn.setIcon(self._close_btn_icon)
        btn.setIconSize(QSize(12, 12))
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QToolButton { border: none; background: transparent; border-radius: 4px; }"
            "QToolButton:hover { background-color: #ff4444; }"
        )
        btn.setToolTip("Close tab")

        def _on_close_clicked():
            # Resolve the tab index dynamically because earlier tabs may
            # have been closed since this button was created.
            bar = self.tab_widget.tabBar()
            for i in range(bar.count()):
                if bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                    self._close_tab(i)
                    return

        btn.clicked.connect(_on_close_clicked)
        self.tab_widget.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def _toggle_tiled_mode(self):
        if self._tiled_mode:
            self._exit_tiled_mode()
        elif self.tab_widget.count() >= 2:
            self._enter_tiled_mode()

    def _enter_tiled_mode(self):
        """Move all tabs into split-screen grid view(s).
        First 4 go into the main window; every additional group of 4 gets
        its own _OverflowTiledWindow."""
        n_total = self.tab_widget.count()

        # Capture all tab data while indices are still correct, then remove.
        tab_bar = self.tab_widget.tabBar()
        all_info = []
        for i in range(n_total):
            dialog = self.tab_widget.widget(i)
            label  = self.tab_widget.tabText(i)
            color  = tab_bar._tab_colors.get(i)
            color_str = color.name() if color else '#4fc3f7'
            all_info.append((dialog, label, color_str))
        for _ in range(n_total):
            self.tab_widget.removeTab(0)

        # Main window: first group of up to 4
        self._tiled_info = all_info[:4]
        tiled_widget = self._build_tiled_widget(self._tiled_info)
        self._stack.addWidget(tiled_widget)
        self._stack.setCurrentWidget(tiled_widget)
        self._tiled_mode = True
        self._tile_btn.setIcon(self._make_grid_icon(active=True))
        for dialog, _, _ in self._tiled_info:
            QTimer.singleShot(200, dialog.terminal._recalculate_size)

        # Overflow groups: one new window per group of 4
        self._overflow_tiled_windows = []
        for start in range(4, n_total, 4):
            group = all_info[start:start + 4]
            exit_cb_ref = []  # mutable cell for forward reference

            def _make_overflow_exit(grp):
                def _exit():
                    for dialog, label, color in grp:
                        self._reinsert_tab(dialog, label, color)
                    if win in self._overflow_tiled_windows:
                        self._overflow_tiled_windows.remove(win)
                    win.close()
                return _exit

            tw = self._build_tiled_widget(group, exit_callback=_make_overflow_exit(group))
            win = _OverflowTiledWindow(tw, group, self)
            win.show()
            self._overflow_tiled_windows.append(win)
            for dialog, _, _ in group:
                QTimer.singleShot(200, dialog.terminal._recalculate_size)

    def _make_tiled_panel(self, dialog: 'TerminalDialog', label: str, color: str) -> QWidget:
        """Wrap a dialog in a panel with a colored title bar showing the host label."""
        panel = QWidget()
        panel.setStyleSheet("background: #0a0a0a;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar with host colour accent
        title_bar = QWidget()
        title_bar.setFixedHeight(26)
        title_bar.setStyleSheet(
            f"background: #161616; border-bottom: 2px solid {color};"
        )
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(8, 0, 6, 0)
        tb_layout.setSpacing(4)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 9px; background: transparent;")
        tb_layout.addWidget(dot)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #e0e0e0; font-size: 13px; font-weight: bold; background: transparent;")
        tb_layout.addWidget(lbl)
        tb_layout.addStretch()

        layout.addWidget(title_bar)

        # Right-click on the title bar to close this terminal
        def _title_context_menu(pos, dlg=dialog):
            menu = QMenu(title_bar)
            close_act = menu.addAction("Close terminal")
            if menu.exec(title_bar.mapToGlobal(pos)) == close_act:
                dlg.close()
        title_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        title_bar.customContextMenuRequested.connect(_title_context_menu)

        # removeTab() hides the widget — must show() after reparenting into a splitter
        dialog.show()
        layout.addWidget(dialog)

        return panel

    def _build_tiled_widget(self, info: list, exit_callback=None) -> QWidget:
        """Return a QWidget containing the terminals arranged in a labelled grid.

        info: list of (dialog, label, color_str) tuples.
        Layout rules:
          1  → full screen
          2  → side by side (Q1 | Q2)
          3  → top row (Q1 | Q2), bottom row (Q3+Q4 full width)
          4  → 2×2 grid
        exit_callback: callable connected to the exit button (defaults to self._exit_tiled_mode).
        """
        _SPLITTER_STYLE = """
            QSplitter::handle:horizontal { background: #2a2a2a; width: 4px; }
            QSplitter::handle:vertical   { background: #2a2a2a; height: 4px; }
            QSplitter::handle:hover      { background: #4fc3f7; }
        """

        panels = [self._make_tiled_panel(d, lbl, col) for d, lbl, col in info]

        container = QWidget()
        container.setStyleSheet("background: #0a0a0a;")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Thin header bar with exit-tiled-mode button (always visible in tiled mode)
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background: #111111; border-bottom: 1px solid #2a2a2a;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(0)
        exit_btn = QToolButton()
        exit_btn.setFixedSize(24, 24)
        exit_btn.setIcon(self._make_grid_icon(active=True))
        exit_btn.setToolTip("Exit grid view")
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.setStyleSheet(
            "QToolButton { border: none; background: transparent; border-radius: 6px; padding: 2px; }"
            "QToolButton:hover { background: #2a2a2a; }"
        )
        exit_btn.clicked.connect(exit_callback or self._exit_tiled_mode)
        header_layout.addWidget(exit_btn)
        header_layout.addStretch()
        outer.addWidget(header)

        n = len(panels)
        if n == 1:
            outer.addWidget(panels[0])
        elif n == 2:
            spl = QSplitter(Qt.Orientation.Horizontal)
            spl.setStyleSheet(_SPLITTER_STYLE)
            spl.addWidget(panels[0])
            spl.addWidget(panels[1])
            spl.setSizes([1, 1])
            outer.addWidget(spl)
        elif n == 3:
            # Q1+Q2 on top, Q3+Q4 (terminal 3 full width) on bottom
            vspl = QSplitter(Qt.Orientation.Vertical)
            vspl.setStyleSheet(_SPLITTER_STYLE)
            top = QSplitter(Qt.Orientation.Horizontal)
            top.setStyleSheet(_SPLITTER_STYLE)
            top.addWidget(panels[0])
            top.addWidget(panels[1])
            top.setSizes([1, 1])
            vspl.addWidget(top)
            vspl.addWidget(panels[2])
            vspl.setSizes([1, 1])
            outer.addWidget(vspl)
        else:  # n == 4
            vspl = QSplitter(Qt.Orientation.Vertical)
            vspl.setStyleSheet(_SPLITTER_STYLE)
            top = QSplitter(Qt.Orientation.Horizontal)
            top.setStyleSheet(_SPLITTER_STYLE)
            top.addWidget(panels[0])
            top.addWidget(panels[1])
            top.setSizes([1, 1])
            bot = QSplitter(Qt.Orientation.Horizontal)
            bot.setStyleSheet(_SPLITTER_STYLE)
            bot.addWidget(panels[2])
            bot.addWidget(panels[3])
            bot.setSizes([1, 1])
            vspl.addWidget(top)
            vspl.addWidget(bot)
            vspl.setSizes([1, 1])
            outer.addWidget(vspl)

        return container

    def _exit_tiled_mode(self):
        """Restore all tiled terminals (main window + overflow windows) to tabs."""
        if not self._tiled_mode:
            return

        # Close overflow windows first — their closeEvent returns terminals to tabs
        for win in list(getattr(self, '_overflow_tiled_windows', [])):
            win.close()
        self._overflow_tiled_windows = []

        tiled_widget = self._stack.widget(1)

        # Re-insert main-window dialogs as tabs
        for dialog, label, color in self._tiled_info:
            self._reinsert_tab(dialog, label, color)

        self._stack.removeWidget(tiled_widget)
        tiled_widget.deleteLater()

        self._stack.setCurrentWidget(self.tab_widget)
        self._tiled_mode = False
        self._tiled_info = []
        self._tile_btn.setIcon(self._make_grid_icon(active=False))

        # Recalculate PTY sizes after layout settles
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if w and hasattr(w, 'terminal'):
                QTimer.singleShot(200, w.terminal._recalculate_size)

    def _reinsert_tab(self, dialog: 'TerminalDialog', label: str, color: str):
        """Add dialog back to the tab widget without reconnecting signals."""
        tab_bar: DetachableTabBar = self.tab_widget.tabBar()
        idx = self.tab_widget.addTab(dialog, label)
        tab_bar.setTabTextColor(idx, QColor(color))
        tab_bar.set_tab_color(idx, color)
        self._add_tab_close_btn(idx)
        self.tab_widget.setCurrentIndex(idx)

    # ── End tiled mode ─────────────────────────────────────────────────────────

    def _find_dialog_idx(self, dialog: 'TerminalDialog'):
        """Return the tab index for dialog, or None if not found."""
        for i in range(self.tab_widget.count()):
            if self.tab_widget.widget(i) is dialog:
                return i
        return None

    def _on_tab_data(self, dialog: 'TerminalDialog'):
        """Flash the activity indicator when data arrives in a non-active tab."""
        idx = self._find_dialog_idx(dialog)
        if idx is None or idx == self.tab_widget.currentIndex():
            return
        self.tab_widget.tabBar().set_tab_activity(idx, True)

    def add_terminal(self, dialog: 'TerminalDialog', label: str, color: str):
        """Add a terminal dialog as a new tab."""
        # Exit tiled mode so the new terminal is immediately visible
        if self._tiled_mode:
            self._exit_tiled_mode()
        tab_bar: DetachableTabBar = self.tab_widget.tabBar()
        idx = self.tab_widget.addTab(dialog, label)
        # Colour the tab text AND draw the indicator strip via paintEvent
        tab_bar.setTabTextColor(idx, QColor(color))
        tab_bar.set_tab_color(idx, color)
        self._add_tab_close_btn(idx)
        self.tab_widget.setCurrentIndex(idx)
        # Connect terminal_closed to auto-remove this tab
        dialog.terminal_closed.connect(lambda: self._remove_tab_for_dialog(dialog))
        # Connect activity indicator
        dialog.terminal.data_received.connect(lambda d=dialog: self._on_tab_data(d))
        QTimer.singleShot(200, dialog.terminal._recalculate_size)
        QTimer.singleShot(250, dialog.terminal.setFocus)

    def _remove_tab_for_dialog(self, dialog: 'TerminalDialog'):
        """Remove the tab that contains *dialog* (called via terminal_closed signal)."""
        if self._tiled_mode:
            # Exit tiled mode first; the closed dialog won't be re-added
            self._tiled_info = [(d, l, c) for d, l, c in self._tiled_info if d is not dialog]
            self._exit_tiled_mode()
            return
        for i in range(self.tab_widget.count()):
            if self.tab_widget.widget(i) is dialog:
                self.tab_widget.removeTab(i)
                break
        if self.tab_widget.count() == 0:
            self.close()

    def _close_tab(self, index: int):
        """Called when user clicks the tab's × button."""
        widget = self.tab_widget.widget(index)
        # Trigger TerminalDialog.closeEvent (asks for confirmation if connected).
        # terminal_closed signal will call _remove_tab_for_dialog on acceptance.
        widget.close()

    def _reattach_dialog(self, dialog: 'TerminalDialog', label: str, win: 'DetachedTerminalWindow'):
        """Move a detached dialog back into the tab bar."""
        # Remove from the detached-windows list so the cleanup lambda is a no-op
        if win in self._detached_windows:
            self._detached_windows.remove(win)
        # Hide the profile-name banner (only shown when detached)
        dialog.profile_label.setVisible(False)
        # Bring the tabbed window back if it was hidden
        if not self.isVisible():
            self.show()
        self.add_terminal(dialog, label, dialog.banner_color or '#4fc3f7')
        self.raise_()
        self.activateWindow()

    def _detach_tab(self, index: int):
        """Detach the tab at *index* into its own floating window."""
        dialog = self.tab_widget.widget(index)
        label = self.tab_widget.tabText(index)

        # Disconnect the auto-remove handler (the tab no longer owns this dialog)
        try:
            dialog.terminal_closed.disconnect(lambda: self._remove_tab_for_dialog(dialog))
        except Exception:
            pass

        self.tab_widget.removeTab(index)

        dialog.profile_label.setVisible(True)  # show banner in detached window

        win = DetachedTerminalWindow(dialog, label,
                                     reattach_callback=self._reattach_dialog)
        # Keep reference so window isn't garbage-collected
        self._detached_windows.append(win)
        # Clean up reference when the detached window eventually closes
        dialog.terminal_closed.connect(lambda: self._detached_windows.remove(win)
                                        if win in self._detached_windows else None)
        win.show()

        if self.tab_widget.count() == 0:
            self.hide()

    def closeEvent(self, event):
        """Close all terminal tabs (with per-terminal confirmation)."""
        while self.tab_widget.count() > 0:
            widget = self.tab_widget.widget(0)
            if not widget.close():
                event.ignore()
                return
            # If terminal_closed fired synchronously, the tab was already removed.
            # Guard against it still being present:
            if self.tab_widget.count() > 0 and self.tab_widget.widget(0) is widget:
                self.tab_widget.removeTab(0)
        event.accept()


