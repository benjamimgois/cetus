"""Automation tab UI for Cetus — mass command execution over SSH/Telnet."""

import base64
import os
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QComboBox, QPushButton, QPlainTextEdit, QLineEdit, QCheckBox, QSpinBox,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFileDialog, QDialog, QAbstractItemView, QApplication,
)

from cetuslib.automation_worker import (
    MAX_TARGETS,
    STATUS_PENDING, STATUS_RUNNING, STATUS_OK,
    STATUS_ERROR, STATUS_TIMEOUT, STATUS_CANCELLED,
    parse_targets, AutomationManager,
)
from cetuslib.vendors import VENDOR_MENU


__all__ = ['AutomationTab', 'LogViewerDialog']


STATUS_COLORS = {
    STATUS_PENDING: '#9e9e9e',
    STATUS_RUNNING: '#f9a825',
    STATUS_OK: '#2e7d32',
    STATUS_ERROR: '#c62828',
    STATUS_TIMEOUT: '#ef6c00',
    STATUS_CANCELLED: '#607d8b',
}

_GROUP_STYLE = """
    QGroupBox {
        font-weight: bold; font-size: 9pt;
        border: 1px solid #c8c8c8; border-radius: 8px;
        margin-top: 6px; padding-top: 4px;
        background-color: #f9f9f9;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #455A64; }
"""

_LABEL_STYLE = "color: #555; font-size: 9pt; font-weight: normal;"


class LogViewerDialog(QDialog):
    """Read-only viewer for a host log with metadata header."""

    def __init__(self, ip, meta, log_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Log — {ip}')
        self.resize(720, 500)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        content = ''
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as fh:
                content = fh.read()
        except OSError as exc:
            content = f'<failed to read {log_path}: {exc}>'

        layout = QVBoxLayout(self)
        header = QLabel(meta)
        header.setTextFormat(Qt.TextFormat.PlainText)
        header.setStyleSheet("color:#455A64; font-size:9pt; font-weight:bold;")
        layout.addWidget(header)

        viewer = QPlainTextEdit()
        viewer.setPlainText(content)
        viewer.setReadOnly(True)
        viewer.setFont(self._mono_font())
        layout.addWidget(viewer, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton('Save as…')
        save_btn.clicked.connect(lambda: self._save_as(log_path))
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    @staticmethod
    def _mono_font():
        from PyQt6.QtGui import QFont
        font = QFont('Monospace')
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        return font

    def _save_as(self, log_path):
        suggested = os.path.join(
            os.path.expanduser('~'), os.path.basename(log_path or 'automation.log'))
        dest, _filter = QFileDialog.getSaveFileName(
            self, 'Save log', suggested, 'Log files (*.log);;All files (*)')
        if dest:
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as src, \
                        open(dest, 'w', encoding='utf-8') as out:
                    out.write(src.read())
            except OSError as exc:
                QMessageBox.warning(self, 'Cetus', f'Failed to save: {exc}')


class AutomationTab(QWidget):
    """Automation tab: mass command execution against a list of network hosts."""

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self._config = config_manager
        self._manager = None
        self._run_started_at = 0.0
        self._total = 0
        self._done = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        layout.addWidget(self._build_targets_group())
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_commands_group())
        layout.addWidget(self._build_results_group(), 1)
        layout.addLayout(self._build_bottom_bar())

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_run_button)

        self._load_remembered_credentials()
        self._update_run_enabled()

        QApplication.instance().aboutToQuit.connect(self._on_app_quit)

    def _on_app_quit(self):
        if self._manager is not None:
            try:
                self._manager.cancel()
                self._manager.wait(15000)
            except RuntimeError:
                pass  # already destroyed

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_targets_group(self):
        group = QGroupBox('Targets')
        group.setStyleSheet(_GROUP_STYLE)
        v = QVBoxLayout(group)
        v.setContentsMargins(8, 6, 8, 6)

        hint = QLabel('One target per line: 192.168.15.1  ·  192.168.15.1-45 (last-octet range)  ·  10.0.0.5-10.0.0.7 (full range)')
        hint.setStyleSheet(_LABEL_STYLE)
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.targets_edit = QPlainTextEdit()
        self.targets_edit.setPlaceholderText('192.168.15.1\n192.168.15.2-10')
        self.targets_edit.setMaximumHeight(88)
        self.targets_edit.textChanged.connect(self._update_run_enabled)
        v.addWidget(self.targets_edit)
        return group

    def _build_connection_group(self):
        group = QGroupBox('Connection')
        group.setStyleSheet(_GROUP_STYLE)
        grid = QGridLayout(group)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        user_label = QLabel('Username:')
        user_label.setStyleSheet(_LABEL_STYLE)
        self.user_edit = QLineEdit()
        grid.addWidget(user_label, 0, 0)
        grid.addWidget(self.user_edit, 0, 1)

        pass_label = QLabel('Password:')
        pass_label.setStyleSheet(_LABEL_STYLE)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(pass_label, 0, 2)
        grid.addWidget(self.pass_edit, 0, 3)

        self.remember_cb = QCheckBox('Remember')
        self.remember_cb.setToolTip(
            'Stores the username and password in the Cetus settings.\n'
            'Warning: the password is stored base64-encoded (not encrypted).')
        self.remember_cb.setStyleSheet("color: #555; font-size: 9pt;")
        grid.addWidget(self.remember_cb, 1, 0)

        type_label = QLabel('Connection:')
        type_label.setStyleSheet(_LABEL_STYLE)
        self.conn_combo = QComboBox()
        self.conn_combo.addItems(['SSH', 'Telnet'])
        grid.addWidget(type_label, 1, 1)
        grid.addWidget(self.conn_combo, 1, 2)

        port_label = QLabel('Port:')
        port_label.setStyleSheet(_LABEL_STYLE)
        self.port_edit = QLineEdit('22')
        self.port_edit.setFixedWidth(70)
        self.conn_combo.currentIndexChanged.connect(self._on_conn_type_changed)
        grid.addWidget(port_label, 1, 3)
        grid.addWidget(self.port_edit, 1, 4)
        grid.setColumnStretch(4, 1)

        vendor_label = QLabel('Vendor:')
        vendor_label.setStyleSheet(_LABEL_STYLE)
        self.vendor_combo = QComboBox()
        for _key, label in VENDOR_MENU:
            self.vendor_combo.addItem(label)
        grid.addWidget(vendor_label, 2, 0)
        grid.addWidget(self.vendor_combo, 2, 1)
        grid.setColumnStretch(1, 1)

        vendor_hint = QLabel('Autodetect identifies the vendor from the prompt after login; select manually if unsure.')
        vendor_hint.setStyleSheet(_LABEL_STYLE)
        vendor_hint.setWordWrap(True)
        grid.addWidget(vendor_hint, 2, 2, 1, 3)
        return group

    def _build_commands_group(self):
        group = QGroupBox('Commands')
        group.setStyleSheet(_GROUP_STYLE)
        v = QVBoxLayout(group)
        v.setContentsMargins(8, 6, 8, 6)

        self.commands_edit = QPlainTextEdit()
        self.commands_edit.setPlaceholderText(
            'One command per line. Lines starting with # are comments.\n'
            'E.g.:\nsystem-view\nospf 1\nbandwidth-reference 10000\nquit\nsave')
        self.commands_edit.setMaximumHeight(110)
        self.commands_edit.textChanged.connect(self._update_run_enabled)
        v.addWidget(self.commands_edit)

        timing_row = QHBoxLayout()
        sleep_label = QLabel('Wait between commands:')
        sleep_label.setStyleSheet(_LABEL_STYLE)
        self.sleep_spin = QDoubleSpinBox()
        self.sleep_spin.setRange(0.0, 60.0)
        self.sleep_spin.setSingleStep(0.5)
        self.sleep_spin.setValue(1.0)
        self.sleep_spin.setSuffix(' s')
        self.sleep_spin.setToolTip(
            'Minimum wait after the prompt of each command is detected.\n'
            'Prompt detection is the actual completion criterion.')
        timing_row.addWidget(sleep_label)
        timing_row.addWidget(self.sleep_spin)

        timeout_label = QLabel('Timeout per command:')
        timeout_label.setStyleSheet(_LABEL_STYLE)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setSuffix(' s')
        self.timeout_spin.setToolTip('Maximum time to wait for the prompt after each command.')
        timing_row.addWidget(timeout_label)
        timing_row.addWidget(self.timeout_spin)

        mode_label = QLabel('Mode:')
        mode_label.setStyleSheet(_LABEL_STYLE)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('Serial')
        self.mode_combo.addItem('Parallel')
        timing_row.addWidget(mode_label)
        timing_row.addWidget(self.mode_combo)

        pool_label = QLabel('Simultaneous connections:')
        pool_label.setStyleSheet(_LABEL_STYLE)
        self.pool_spin = QSpinBox()
        self.pool_spin.setRange(2, 20)
        self.pool_spin.setValue(5)
        self.pool_spin.setEnabled(False)
        self.mode_combo.currentIndexChanged.connect(
            lambda idx: self.pool_spin.setEnabled(idx == 1))
        timing_row.addWidget(pool_label)
        timing_row.addWidget(self.pool_spin)
        timing_row.addStretch(1)
        v.addLayout(timing_row)
        return group

    def _build_results_group(self):
        group = QGroupBox('Results')
        group.setStyleSheet(_GROUP_STYLE)
        v = QVBoxLayout(group)
        v.setContentsMargins(8, 6, 8, 6)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['IP', 'Duration', 'Status', 'Message'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self._open_log)
        v.addWidget(self.table)

        hint = QLabel('Double-click a row to open the host log.')
        hint.setStyleSheet(_LABEL_STYLE)
        v.addWidget(hint)
        return group

    def _build_bottom_bar(self):
        row = QHBoxLayout()
        self._log_hint_label = QLabel('')
        self._log_hint_label.setStyleSheet(_LABEL_STYLE)
        self.run_btn = QPushButton('▶  Run')
        self.run_btn.setFixedHeight(34)
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._on_run_clicked)
        row.addWidget(self._log_hint_label, 1)
        row.addWidget(self.run_btn)
        return row

    # ------------------------------------------------------------------ #
    # Credential persistence
    # ------------------------------------------------------------------ #
    def _load_remembered_credentials(self):
        if bool(self._config.get('automation_remember')):
            self.remember_cb.setChecked(True)
            self.user_edit.setText(self._config.get('automation_user') or '')
            encoded = self._config.get('automation_password') or ''
            try:
                self.pass_edit.setText(base64.b64decode(encoded).decode('utf-8'))
            except Exception:
                pass

    def _store_credentials(self):
        remember = self.remember_cb.isChecked()
        self._config.set('automation_remember', remember)
        if remember:
            self._config.set('automation_user', self.user_edit.text().strip())
            self._config.set(
                'automation_password',
                base64.b64encode(self.pass_edit.text().encode('utf-8')).decode('ascii'))
        else:
            self._config.set('automation_user', '')
            self._config.set('automation_password', '')

    # ------------------------------------------------------------------ #
    # Run control
    # ------------------------------------------------------------------ #
    def _on_conn_type_changed(self, index):
        self.port_edit.setText('22' if index == 0 else '23')

    def _collect_targets(self):
        """Expand targets; returns (ips, None) or (None, error_message)."""
        ips, invalid = parse_targets(self.targets_edit.toPlainText())
        if not ips:
            return None, 'No valid targets were provided.'
        if invalid:
            listing = '\n'.join(f'  • {line} — {reason}' for line, reason in invalid[:10])
            if len(invalid) > 10:
                listing += f'\n  … and {len(invalid) - 10} more line(s)'
            return None, f'{len(invalid)} invalid line(s) in the target list:\n{listing}'
        if len(ips) > MAX_TARGETS:
            return None, (f'Target list exceeds the limit of {MAX_TARGETS} hosts '
                          f'({len(ips)} expanded). Reduce the range.')
        return ips, None

    def _collect_commands(self):
        cmds = []
        for line in self.commands_edit.toPlainText().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                cmds.append(stripped)
        return cmds

    def _update_run_enabled(self):
        if self._manager is not None:
            return
        has_targets = bool(self.targets_edit.toPlainText().strip())
        has_commands = bool(self._collect_commands())
        self.run_btn.setEnabled(has_targets and has_commands)

    def _on_run_clicked(self):
        if self._manager is not None:
            self._manager.cancel()
            return

        ips, error = self._collect_targets()
        if error:
            QMessageBox.warning(self, 'Automation', error)
            return
        commands = self._collect_commands()
        if not commands:
            QMessageBox.warning(self, 'Automation', 'No commands to execute.')
            return

        self._store_credentials()

        settings = {
            'conn_type': 'ssh' if self.conn_combo.currentIndex() == 0 else 'telnet',
            'port': self.port_edit.text().strip() or ('22' if self.conn_combo.currentIndex() == 0 else '23'),
            'username': self.user_edit.text().strip(),
            'password': self.pass_edit.text(),
            'vendor_key': VENDOR_MENU[self.vendor_combo.currentIndex()][0],
            'commands': commands,
            'min_gap': self.sleep_spin.value(),
            'cmd_timeout': self.timeout_spin.value(),
            'parallel': self.mode_combo.currentIndex() == 1,
            'pool_size': self.pool_spin.value(),
        }

        self._total = len(ips)
        self._done = 0
        self._run_started_at = time.monotonic()
        self._manager = AutomationManager(ips, settings)
        self._manager.row_started.connect(self._on_row_started)
        self._manager.row_finished.connect(self._on_row_finished)
        self._manager.progress_changed.connect(self._on_progress)
        self._manager.run_finished.connect(self._on_run_finished)
        # Keep the reference until the thread is fully done: dropping it in
        # _on_run_finished would destroy the QThread while its thread is
        # still winding down ("QThread: Destroyed while thread is still
        # running" — fatal on Qt 6).
        self._manager.finished.connect(self._manager.deleteLater)
        self._manager.destroyed.connect(self._on_manager_destroyed)

        self._populate_table(ips)
        self._set_form_enabled(False)
        self._timer.start()
        self._update_run_button()
        self._manager.start()

    def _populate_table(self, ips):
        self.table.setRowCount(len(ips))
        for row, ip in enumerate(ips):
            self._set_row_text(row, ip, '—', STATUS_PENDING, '')

    def _set_row_text(self, row, ip, dur, status, msg, log_path=''):
        def item(text):
            return QTableWidgetItem(text)
        self.table.setItem(row, 0, item(ip))
        self.table.setItem(row, 1, item(dur))
        status_item = item(status)
        status_item.setForeground(QColor(STATUS_COLORS.get(status, '#000000')))
        self.table.setItem(row, 2, status_item)
        self.table.setItem(row, 3, item(msg))
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, log_path)

    def _row_for_ip(self, ip):
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 0)
            if it and it.text() == ip:
                return row
        return None

    def _set_form_enabled(self, enabled):
        for w in (self.targets_edit, self.user_edit, self.pass_edit,
                  self.remember_cb, self.conn_combo, self.port_edit,
                  self.vendor_combo, self.commands_edit, self.sleep_spin,
                  self.timeout_spin, self.mode_combo, self.pool_spin):
            w.setEnabled(enabled)
        if enabled:
            self.pool_spin.setEnabled(self.mode_combo.currentIndex() == 1)
            self._update_run_enabled()

    # ------------------------------------------------------------------ #
    # Manager signal slots (main thread only)
    # ------------------------------------------------------------------ #
    def _on_row_started(self, ip):
        row = self._row_for_ip(ip)
        if row is not None:
            self._set_row_text(row, ip, '…', STATUS_RUNNING, '')

    def _on_row_finished(self, ip, duration, status, message, vendor, log_path):
        row = self._row_for_ip(ip)
        if row is None:
            return
        dur_text = f'{duration:.1f} s' if duration > 0 else '—'
        self._set_row_text(row, ip, dur_text, status, message, log_path)
        if log_path:
            self._log_hint_label.setText(f'Logs: {os.path.dirname(log_path)}')

    def _on_progress(self, done, total):
        self._done, self._total = done, total
        self._update_run_button()

    def _on_run_finished(self, run_dir, duration):
        self._timer.stop()
        self._set_form_enabled(True)
        self.run_btn.setText('▶  Run')
        self._log_hint_label.setText(
            f'Run finished in {duration:.1f} s — logs in {run_dir}')

    def _on_manager_destroyed(self):
        self._manager = None
        self._update_run_enabled()

    def _update_run_button(self):
        if self._manager is None:
            self.run_btn.setText('▶  Run')
            return
        elapsed = int(time.monotonic() - self._run_started_at)
        mm, ss = divmod(elapsed, 60)
        hh, mm = divmod(mm, 60)
        clock = f'{hh:02d}:{mm:02d}:{ss:02d}' if hh else f'{mm:02d}:{ss:02d}'
        self.run_btn.setText(f'⏹  Stop    {clock} · {self._done}/{self._total}')

    # ------------------------------------------------------------------ #
    def _open_log(self, item):
        if item is None or item.column() != 0:
            return
        log_path = item.data(Qt.ItemDataRole.UserRole) or ''
        if not log_path or not os.path.exists(log_path):
            return
        row = item.row()
        ip = self.table.item(row, 0).text()
        status = self.table.item(row, 2).text()
        dur = self.table.item(row, 1).text()
        msg = self.table.item(row, 3).text()
        meta = (
            f'Host: {ip}    Status: {status}    Duration: {dur}\n'
            f'File: {log_path}'
            + (f'\n{msg}' if msg else '')
        )
        dlg = LogViewerDialog(ip, meta, log_path, self)
        dlg.show()
