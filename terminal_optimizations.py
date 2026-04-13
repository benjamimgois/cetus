"""
Terminal rendering optimizations for OpenGrid
Provides performance improvements for the TerminalWidget
"""
import time
from typing import List, Tuple, Optional
from PyQt6.QtGui import QTextCursor, QColor
from PyQt6.QtWidgets import QTextEdit


class TerminalRenderOptimizer:
    """Optimizes terminal rendering to reduce CPU usage"""
    
    def __init__(self, terminal_widget: QTextEdit):
        self.terminal = terminal_widget
        self.last_render_time = 0
        self.render_interval = 0.05  # 20 FPS minimum when active
        self.idle_interval = 0.5     # 2 FPS when idle
        self.last_html_content = ""
        self.dirty_regions = []  # Track which parts of screen changed
        
    def should_render(self) -> bool:
        """Determine if we should render based on time and activity"""
        now = time.time()
        
        # If we have selection or mouse pressed, don't render (already handled in render_screen)
        if self.terminal.textCursor().hasSelection() or self.terminal.mouse_pressed:
            return False
            
        # If in scrollback mode, reduce frequency
        if self.terminal._in_scrollback_mode:
            interval = self.idle_interval
        else:
            # Check if there's been recent activity
            time_since_last_render = now - self.last_render_time
            if time_since_last_render < self.render_interval:
                return False
            interval = self.render_interval
            
        if now - self.last_render_time >= interval:
            self.last_render_time = now
            return True
        return False
    
    def render_if_needed(self) -> bool:
        """Render terminal if needed, returns True if rendered"""
        if not self.should_render():
            return False
            
        # Import here to avoid circular imports
        from opengrid import pyte
        
        # Skip if pyte is locked (worker thread is updating)
        if not self.terminal._pyte_lock.acquire(blocking=False):
            return False
            
        try:
            # Check if content actually changed
            current_hash = self._get_screen_hash()
            if hasattr(self, '_last_screen_hash') and self._last_screen_hash == current_hash:
                return False  # No change
            self._last_screen_hash = current_hash
            
            # Perform optimized render
            self._optimized_render_screen()
            return True
        finally:
            self.terminal._pyte_lock.release()
    
    def _get_screen_hash(self) -> int:
        """Get a hash of the current screen content for change detection"""
        # Simple hash based on visible content and cursor position
        hash_val = hash((self.terminal.screen.cursor.x, 
                        self.terminal.screen.cursor.y,
                        self.terminal.screen.columns,
                        self.terminal.screen.lines))
        
        # Include a sample of lines to detect changes
        for y in [0, self.terminal.screen.lines//2, self.terminal.screen.lines-1]:
            if 0 <= y < self.terminal.screen.lines:
                line = self.terminal.screen.buffer[y]
                line_hash = hash(tuple((x, char.data, char.fg, char.bg) 
                                     for x, char in enumerate(line) 
                                     if x < min(10, self.terminal.screen.columns)))
                hash_val ^= line_hash
        
        return hash_val
    
    def _optimized_render_screen(self):
        """Optimized version of render_screen that minimizes work"""
        # Only proceed if we need to update
        if not getattr(self.terminal, '_render_needed', True):
            return
            
        self.terminal._render_needed = False
        
        # Fast path: if no ANSI colors and no special rendering needed
        if (not self._has_ansi_colors() and 
            self.terminal.vendor == "Default" and 
            not self.terminal._in_scrollback_mode and
            not self.terminal._search_active):
            self._fast_render()
            return
            
        # Otherwise use existing render but with optimizations
        self.terminal.render_screen()
    
    def _has_ansi_colors(self) -> bool:
        """Quick check if screen has ANSI colors"""
        # Check just a few lines for performance
        lines_to_check = min(5, self.terminal.screen.lines)
        for y in range(lines_to_check):
            line = self.terminal.screen.buffer[y]
            for x in range(min(20, self.terminal.screen.columns)):  # Check first 20 chars
                char = line[x]
                if char.fg != 'default' or char.bg != 'default' or char.bold or char.italics or char.underscore or char.reverse:
                    return True
        return False
    
    def _fast_render(self):
        """Fast rendering for plain text without colors"""
        # Build plain text efficiently
        lines = []
        for y in range(self.terminal.screen.lines):
            line = self.terminal.screen.buffer[y]
            line_text = ''.join(char.data for char in line).rstrip()
            lines.append(line_text)
        
        # Join with newlines and escape HTML
        import re
        text_content = '\n'.join(lines)
        text_content = text_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text_content = text_content.replace(' ', '&nbsp;')  # Preserve spaces
        
        # Wrap in pre tag
        html = f'<pre style="margin: 0; padding: 0; color: #e0e0e0; background-color: #0a0a0a; line-height: 1.2;">{text_content}</pre>'
        
        # Only update if content changed
        if html != self.last_html_content:
            self.terminal.setUpdatesEnabled(False)
            self.terminal.setHtml(html)
            self.terminal.document().setDocumentMargin(0)
            self.terminal.setUpdatesEnabled(True)
            self.last_html_content = html
            
            # Restore cursor position
            cursor = self.terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.terminal.setTextCursor(cursor)


def apply_terminal_optimizations(terminal_widget):
    """Apply optimizations to a terminal widget"""
    optimizer = TerminalRenderOptimizer(terminal_widget)
    
    # Replace the refresh timer connection
    try:
        terminal_widget.refresh_timer.timeout.disconnect()
    except TypeError:
        pass  # Was not connected
    
    terminal_widget.refresh_timer.timeout.connect(lambda: optimizer.render_if_needed())
    
    # Store optimizer reference to prevent garbage collection
    terminal_widget._render_optimizer = optimizer
    
    return optimizer