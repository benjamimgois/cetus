"""Application entrypoint and main window for Cetus."""

import csv
import glob
import ipaddress
import json
import math
import os
import platform
import re
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

import pyte
from PyQt6.QtCore import Qt, QProcess, pyqtSignal, QTimer, QThread, QSize, QPointF, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QFont, QTextCursor, QKeyEvent, QTextBlockFormat, QTextCharFormat, QColor, QBrush, QPixmap, QIcon, QTextOption, QPainter, QPainterPath, QLinearGradient, QPen, QRadialGradient, QImage, QSyntaxHighlighter, QTextListFormat
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QFormLayout, QMessageBox,
    QTextEdit, QPlainTextEdit, QDialog, QInputDialog, QLineEdit,
    QGraphicsDropShadowEffect, QCheckBox, QFileDialog,
    QStackedWidget, QRadioButton, QButtonGroup, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy,
    QMenu, QScrollArea, QTabWidget, QTabBar, QFrame, QToolButton, QListWidget, QListWidgetItem,
    QProgressBar, QSpinBox, QSplitter, QStyle, QDialogButtonBox, QStyledItemDelegate,
    QToolTip
)

try:
    from PyQt6.QtSerialPort import QSerialPortInfo
    SERIAL_PORT_AVAILABLE = True
except ImportError:
    SERIAL_PORT_AVAILABLE = False

try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False

try:
    import telnetlib
    TELNET_AVAILABLE = True
except ImportError:
    telnetlib = None
    TELNET_AVAILABLE = False

from cetuslib.config import ConfigManager
from cetuslib.constants import VERSION_LABEL
from cetuslib.network import (
    IperfGraphWidget, SignalHistoryWidget, WifiChannelChart,
    WifiHeatmapWidget, RouteVisualizationWidget, LatencyGraphWidget, PingGraphWidget
)
from cetuslib.terminal import (
    TerminalWidget, TerminalDialog, TerminalTabbedWindow,
    DetachedTerminalWindow, DetachableTabBar
)
from cetuslib.ui.dialogs import StickyNoteDialog, VendorReferenceDialog, FileTextEditor
from cetuslib.ui.profiles import SshProfilesTree, SerialProfilesTree
from cetuslib.ui.widgets import FlatComboButton, _CollapsibleGroupBox
from cetuslib.utils import (
    TFTPHandler, TFTPServer, load_svg_pixmap, load_svg_icon, load_svg_icon_dual,
    run_tftp_server_standalone, get_network_interfaces, _get_mac_vendor
)
from cetuslib.workers import (
    ScanWorker, ConnectionWorker, TracerouteWorker, GeoFlagWorker,
    NmapDiscoverWorker, MtrWorker, PingWorker, PingTCPWorker,
    Iperf3DiscoverWorker, Iperf3Worker, SpeedTestWorker, _SimplePingWorker,
    DeviceImageWorker, FileConnectWorker, FileListWorker, FileTransferWorker,
    TcpdumpWorker, DnsResolverWorker, WiFiScanWorker
)


__all__ = ['SerialTerminalGUI', 'main']


class SerialTerminalGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Cetus v{VERSION_LABEL}")
        self.setMinimumSize(600, 780)
        self.resize(750, 780)
        self.terminal_dialog = None
        self.open_terminals = []  # Track multiple open terminals
        self._terminal_manager: TerminalTabbedWindow | None = None
        self.tftp_process = None
        self._ft_protocol = 'SSH'
        self._ft_mode = 'Client'
        self._ft_conn = None
        self._ft_connect_time = None
        self._ft_local_path = os.path.expanduser('~')
        self._ft_remote_path = '/'
        self._ft_local_history = [os.path.expanduser('~')]
        self._ft_local_history_idx = 0
        self._ft_remote_history = ['/']
        self._ft_remote_history_idx = 0
        self._ftp_srv_process = None
        self._smb_srv_service = 'smb'
        self._pending_profile_name = None
        self._pending_vendor = None
        self._pending_terminal_mode = None
        self.config = ConfigManager()

        self.geo_flag_worker = GeoFlagWorker()
        self.geo_flag_worker.flag_resolved.connect(self._on_geo_flag_resolved)
        self.geo_flag_worker.start()

        self.init_ui()
        self.load_settings()
        self.apply_styles()

    def _enable_table_tooltips(self, table):
        """Enable automatic tooltips on table cells showing full text on hover"""
        table.setMouseTracking(True)
        table.cellEntered.connect(lambda row, col, t=table:
            t.setToolTip(t.item(row, col).text() if t.item(row, col) else ""))

    def init_ui(self):
        """Initialize the user interface with vertical tabs"""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main horizontal layout (tabs on left, content on right)
        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(0)
        main_h_layout.setContentsMargins(0, 0, 0, 0)

        # === LEFT SIDE: Vertical Tab Bar ===
        self.tab_widget = QWidget()
        self.tab_widget.setFixedWidth(62)
        self.tab_widget.setStyleSheet("""
            QWidget {
                background-color: #263238;
                border-right: 1px solid #1a2327;
            }
        """)

        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(0, 12, 0, 12)
        tab_layout.setSpacing(4)

        # Style for tab buttons with left indicator bar
        tab_btn_style = """
            QPushButton {{
                background-color: transparent;
                border: none;
                border-left: 3px solid transparent;
                border-radius: 0px;
                padding: 3px 6px;
                margin: 0px;
            }}
            QPushButton:hover {{
                background-color: #37474f;
                border-left: 3px solid #78909c;
            }}
            QPushButton:checked {{
                background-color: #37474f;
                border-left: 3px solid {color};
            }}
        """

        icon_size = 36

        # TFTP tab button
        self.tftp_tab_btn = QPushButton()
        self.tftp_tab_btn.setFixedSize(62, 52)
        tftp_icon_path = self.get_tab_icon_path('filetransfer.svg')
        tftp_icon = load_svg_icon(tftp_icon_path, icon_size) if tftp_icon_path else None
        if tftp_icon:
            self.tftp_tab_btn.setIcon(tftp_icon)
            self.tftp_tab_btn.setIconSize(self.tftp_tab_btn.size() * 0.7)
        else:
            self.tftp_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_DriveNetIcon))
        self.tftp_tab_btn.setToolTip("File Transfer")
        self.tftp_tab_btn.setCheckable(True)
        self.tftp_tab_btn.clicked.connect(lambda: self.switch_tab(7))
        self.tftp_tab_btn.setStyleSheet(tab_btn_style.format(color='#9C27B0'))

        # Serial tab button
        self.serial_tab_btn = QPushButton()
        self.serial_tab_btn.setFixedSize(62, 52)
        serial_icon_path = self.get_tab_icon_path('serial-port-white.svg')
        serial_icon = load_svg_icon(serial_icon_path, icon_size) if serial_icon_path else None
        if serial_icon:
            self.serial_tab_btn.setIcon(serial_icon)
            self.serial_tab_btn.setIconSize(self.serial_tab_btn.size() * 0.7)
        else:
            self.serial_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_DriveHDIcon))
        self.serial_tab_btn.setToolTip("Serial Connection")
        self.serial_tab_btn.setCheckable(True)
        self.serial_tab_btn.clicked.connect(lambda: self.switch_tab(1))  # Serial stays at 1
        self.serial_tab_btn.setStyleSheet(tab_btn_style.format(color='#2196F3'))

        # Remote Access tab button
        self.ssh_tab_btn = QPushButton()
        self.ssh_tab_btn.setFixedSize(62, 52)
        ssh_icon_path = self.get_tab_icon_path('remote.svg')
        ssh_icon = load_svg_icon(ssh_icon_path, icon_size) if ssh_icon_path else None
        if ssh_icon:
            self.ssh_tab_btn.setIcon(ssh_icon)
            self.ssh_tab_btn.setIconSize(self.ssh_tab_btn.size() * 0.7)
        else:
            self.ssh_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_ComputerIcon))
        self.ssh_tab_btn.setToolTip("Remote Access")
        self.ssh_tab_btn.setCheckable(True)
        self.ssh_tab_btn.setChecked(True)
        self.ssh_tab_btn.clicked.connect(lambda: self.switch_tab(0))
        self.ssh_tab_btn.setStyleSheet(tab_btn_style.format(color='#4CAF50'))

        # IP Scanner tab button
        self.ipscan_tab_btn = QPushButton()
        self.ipscan_tab_btn.setFixedSize(62, 52)
        ipscan_icon_path = self.get_tab_icon_path('ipscan.svg')
        ipscan_icon = load_svg_icon(ipscan_icon_path, icon_size) if ipscan_icon_path else None
        if ipscan_icon:
            self.ipscan_tab_btn.setIcon(ipscan_icon)
            self.ipscan_tab_btn.setIconSize(self.ipscan_tab_btn.size() * 0.7)
        else:
            self.ipscan_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_DriveNetIcon))
        self.ipscan_tab_btn.setToolTip("IP Scanner")
        self.ipscan_tab_btn.setCheckable(True)
        self.ipscan_tab_btn.clicked.connect(lambda: self.switch_tab(2))
        self.ipscan_tab_btn.setStyleSheet(tab_btn_style.format(color='#ef5350'))

        # SNMP tab button
        self.snmp_tab_btn = QPushButton()
        self.snmp_tab_btn.setFixedSize(62, 52)
        snmp_icon_path = self.get_tab_icon_path('snmp.svg')
        snmp_icon = load_svg_icon(snmp_icon_path, icon_size) if snmp_icon_path else None
        if snmp_icon:
            self.snmp_tab_btn.setIcon(snmp_icon)
            self.snmp_tab_btn.setIconSize(self.snmp_tab_btn.size() * 0.7)
        else:
            self.snmp_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_ComputerIcon))
        self.snmp_tab_btn.setToolTip("SNMP Queries")
        self.snmp_tab_btn.setCheckable(True)
        self.snmp_tab_btn.clicked.connect(lambda: self.switch_tab(4))
        self.snmp_tab_btn.setStyleSheet(tab_btn_style.format(color='#FF9800'))

        # Traceroute tab button
        self.traceroute_tab_btn = QPushButton()
        self.traceroute_tab_btn.setFixedSize(62, 52)
        traceroute_icon_path = self.get_tab_icon_path('traceroute.svg')
        traceroute_icon = load_svg_icon(traceroute_icon_path, icon_size) if traceroute_icon_path else None
        if traceroute_icon:
            self.traceroute_tab_btn.setIcon(traceroute_icon)
            self.traceroute_tab_btn.setIconSize(self.traceroute_tab_btn.size() * 0.7)
        else:
            self.traceroute_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_ArrowForward))
        self.traceroute_tab_btn.setToolTip("Traceroute")
        self.traceroute_tab_btn.setCheckable(True)
        self.traceroute_tab_btn.clicked.connect(lambda: self.switch_tab(3))
        self.traceroute_tab_btn.setStyleSheet(tab_btn_style.format(color='#00BCD4'))

        tab_layout.addWidget(self.ssh_tab_btn)
        tab_layout.addWidget(self.serial_tab_btn)
        tab_layout.addWidget(self.ipscan_tab_btn)
        tab_layout.addWidget(self.traceroute_tab_btn)
        tab_layout.addWidget(self.snmp_tab_btn)

        # WiFi Site Survey tab button (index 6)
        self.wifi_tab_btn = QPushButton()
        self.wifi_tab_btn.setFixedSize(62, 52)
        wifi_icon_path = self.get_tab_icon_path('wifi.svg')
        wifi_icon = load_svg_icon(wifi_icon_path, icon_size) if wifi_icon_path else None
        if wifi_icon:
            self.wifi_tab_btn.setIcon(wifi_icon)
            self.wifi_tab_btn.setIconSize(self.wifi_tab_btn.size() * 0.7)
        else:
            self.wifi_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_DriveNetIcon))
        self.wifi_tab_btn.setToolTip("WiFi Site Survey")
        self.wifi_tab_btn.setCheckable(True)
        self.wifi_tab_btn.clicked.connect(lambda: self.switch_tab(5))
        self.wifi_tab_btn.setStyleSheet(tab_btn_style.format(color='#E91E63'))

        tab_layout.addWidget(self.wifi_tab_btn)

        # iPerf3 tab button (index 6)
        self.iperf_tab_btn = QPushButton()
        self.iperf_tab_btn.setFixedSize(62, 52)
        iperf_icon_path = self.get_tab_icon_path('speed.svg')
        iperf_icon = load_svg_icon(iperf_icon_path, icon_size) if iperf_icon_path else None
        if iperf_icon:
            self.iperf_tab_btn.setIcon(iperf_icon)
            self.iperf_tab_btn.setIconSize(self.iperf_tab_btn.size() * 0.7)
        else:
            self.iperf_tab_btn.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_MediaVolume))
        self.iperf_tab_btn.setToolTip("Speed Test\nBandwidth test via speedtest.net or iPerf3")
        self.iperf_tab_btn.setCheckable(True)
        self.iperf_tab_btn.clicked.connect(lambda: self.switch_tab(6))
        self.iperf_tab_btn.setStyleSheet(tab_btn_style.format(color='#00897B'))
        tab_layout.addWidget(self.iperf_tab_btn)

        self.traffic_tab_btn = QPushButton()
        self.traffic_tab_btn.setFixedSize(62, 52)
        _traffic_icon_path = self.get_tab_icon_path('traffic.svg')
        _traffic_icon = load_svg_icon(_traffic_icon_path, icon_size) if _traffic_icon_path else None
        if _traffic_icon:
            self.traffic_tab_btn.setIcon(_traffic_icon)
            self.traffic_tab_btn.setIconSize(self.traffic_tab_btn.size() * 0.7)
        self.traffic_tab_btn.setToolTip("Traffic Monitor\nLive packet capture via tcpdump")
        self.traffic_tab_btn.setCheckable(True)
        self.traffic_tab_btn.clicked.connect(lambda: self.switch_tab(8))
        self.traffic_tab_btn.setStyleSheet(tab_btn_style.format(color='#AD1457'))
        tab_layout.addWidget(self.traffic_tab_btn)

        tab_layout.addWidget(self.tftp_tab_btn)

        tab_layout.addStretch()

        # Settings button (bottom of sidebar)
        self.settings_tab_btn = QPushButton()
        self.settings_tab_btn.setFixedSize(62, 52)
        settings_icon_path = self.get_tab_icon_path('settings.svg')
        settings_icon = load_svg_icon(settings_icon_path, icon_size) if settings_icon_path else None
        if settings_icon:
            self.settings_tab_btn.setIcon(settings_icon)
            self.settings_tab_btn.setIconSize(self.settings_tab_btn.size() * 0.55)
        self.settings_tab_btn.setToolTip("Settings")
        self.settings_tab_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 0px;
                color: #aaaaaa;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.08);
                color: white;
            }
            QPushButton:pressed {
                background-color: rgba(255,255,255,0.15);
            }
        """)
        self.settings_tab_btn.clicked.connect(self._show_settings_menu)
        tab_layout.addWidget(self.settings_tab_btn)

        self.tab_widget.setLayout(tab_layout)

        # === RIGHT SIDE: Stacked Widget for Content ===
        self.content_stack = QStackedWidget()

        # Create SSH configuration page (index 0)
        self.ssh_page = self.create_ssh_page()
        self.content_stack.addWidget(self.ssh_page)

        # Create Serial configuration page (index 1)
        self.serial_page = self.create_serial_page()
        self.content_stack.addWidget(self.serial_page)

        # Create IP Scanner page (index 2)
        self.ipscan_page = self.create_ipscan_page()
        self.content_stack.addWidget(self.ipscan_page)

        # Create Traceroute page (index 3)
        self.traceroute_page = self.create_traceroute_page()
        self.content_stack.addWidget(self.traceroute_page)

        # Create SNMP page (index 4)
        self.snmp_page = self.create_snmp_page()
        self.content_stack.addWidget(self.snmp_page)

        # Create WiFi Site Survey page (index 5)
        self.wifi_page = self.create_wifi_page()
        self.content_stack.addWidget(self.wifi_page)

        # Create iPerf3 page (index 6)
        self.iperf_page = self.create_iperf_page()
        self.content_stack.addWidget(self.iperf_page)

        # Create File Transfer page (index 7)
        self.tftp_page = self.create_filetransfer_page()
        self.content_stack.addWidget(self.tftp_page)

        # Create Traffic Monitor page (index 8)
        self.traffic_page = self.create_traffic_monitor_page()
        self.content_stack.addWidget(self.traffic_page)

        # Add to main layout
        main_h_layout.addWidget(self.tab_widget)
        main_h_layout.addWidget(self.content_stack, 1)

        central_widget.setLayout(main_h_layout)

        # Update port list
        self.update_port_list()

    def switch_tab(self, index):
        """Switch between tabs."""
        self.content_stack.setCurrentIndex(index)
        self.ssh_tab_btn.setChecked(index == 0)
        self.serial_tab_btn.setChecked(index == 1)
        self.ipscan_tab_btn.setChecked(index == 2)
        self.traceroute_tab_btn.setChecked(index == 3)
        self.snmp_tab_btn.setChecked(index == 4)
        self.wifi_tab_btn.setChecked(index == 5)
        self.iperf_tab_btn.setChecked(index == 6)
        self.tftp_tab_btn.setChecked(index == 7)
        self.traffic_tab_btn.setChecked(index == 8)
        modes = {0: 'ssh', 1: 'serial', 2: 'ipscan', 3: 'snmp',
                 4: 'traceroute', 5: 'wifi', 6: 'iperf', 7: 'tftp', 8: 'traffic'}
        self.config.set('connection_mode', modes.get(index, 'ssh'))

    def _show_settings_menu(self):
        """Show settings popup menu with Import/Export config and About."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #263238;
                border: 1px solid #37474f;
                color: #eceff1;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 8px 20px 8px 12px;
            }
            QMenu::item:selected {
                background-color: #37474f;
            }
            QMenu::separator {
                height: 1px;
                background: #37474f;
                margin: 4px 8px;
            }
        """)

        import_action = QAction("Import Config", self)
        import_action.triggered.connect(self._import_config)
        menu.addAction(import_action)

        export_action = QAction("Export Config", self)
        export_action.triggered.connect(self._export_config)
        menu.addAction(export_action)

        remmina_action = QAction("Import from Remmina", self)
        remmina_action.triggered.connect(self._import_remmina)
        menu.addAction(remmina_action)

        menu.addSeparator()

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about_dialog)
        menu.addAction(about_action)

        # Position menu above the button
        btn = self.settings_tab_btn
        pos = btn.mapToGlobal(btn.rect().topLeft())
        menu.adjustSize()
        pos.setY(pos.y() - menu.sizeHint().height())
        menu.exec(pos)

    def _toggle_theme(self):
        """Toggle between light and dark themes"""
        current_theme = self.config.get('theme')
        if current_theme == '':
            current_theme = 'light'
        new_theme = 'dark' if current_theme == 'light' else 'light'
        self.config.set('theme', new_theme)
        self.apply_styles()

    def _import_remmina(self):
        """Import SSH, VNC and RDP profiles from Remmina .remmina files."""
        import configparser
        from PyQt6.QtWidgets import (QFileDialog, QMessageBox, QDialog,
                                      QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QScrollArea, QWidget,
                                      QCheckBox, QFrame)
        from PyQt6.QtCore import Qt

        # Protocol mapping: Remmina name → Cetus name, default port
        SUPPORTED = {
            'SSH':    ('SSH',    '22'),
            'VNC':    ('VNC',    '5900'),
            'RDP':    ('RDP',    '3389'),
            'TELNET': ('Telnet', '23'),
        }

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Remmina profile files",
            os.path.expanduser("~/.local/share/remmina"),
            "Remmina Files (*.remmina);;All Files (*)"
        )
        if not files:
            return

        parsed = []
        skipped_protocols = []
        for path in files:
            cfg = configparser.RawConfigParser()
            try:
                cfg.read(path, encoding='utf-8')
            except Exception:
                continue
            if not cfg.has_section('remmina'):
                continue

            remmina_proto = cfg.get('remmina', 'protocol', fallback='').upper()
            if remmina_proto not in SUPPORTED:
                proto_name = cfg.get('remmina', 'name', fallback=os.path.basename(path))
                skipped_protocols.append(f"{proto_name} ({remmina_proto or 'unknown'})")
                continue

            og_protocol, default_port = SUPPORTED[remmina_proto]
            name     = cfg.get('remmina', 'name',     fallback='').strip() or os.path.basename(path)
            server   = cfg.get('remmina', 'server',   fallback='').strip()
            username = cfg.get('remmina', 'username', fallback='').strip()
            group    = cfg.get('remmina', 'group',    fallback='').strip() or 'Default'
            raw_pw   = cfg.get('remmina', 'password', fallback='').strip()

            # Parse host:port — Remmina may include port in server field
            if ':' in server:
                host, port = server.rsplit(':', 1)
                if not port.isdigit():
                    host, port = server, default_port
            else:
                host, port = server, default_port

            # SSH-specific fields
            key_path = ''
            auth_method = 'password'
            if og_protocol == 'SSH':
                key_path = cfg.get('remmina', 'ssh_privatekey', fallback='').strip()
                ssh_auth = cfg.get('remmina', 'ssh_auth', fallback='0').strip()
                # ssh_auth: 0=password, 1=publickey, 2=ssh-agent, 3=kerberos
                if ssh_auth == '1' or key_path:
                    auth_method = 'key'

            # Remmina stores "." when password lives in the system keyring — skip those
            password = raw_pw if raw_pw and raw_pw != '.' else ''

            parsed.append({
                'name': name, 'host': host, 'port': port,
                'username': username, 'auth_method': auth_method,
                'key_path': key_path, 'group': group,
                'password': password, 'protocol': og_protocol,
            })

        if not parsed:
            msg = "No supported profiles found in the selected files."
            if skipped_protocols:
                msg += "\n\nSkipped (unsupported protocols):\n" + "\n".join(f"  • {s}" for s in skipped_protocols)
            QMessageBox.information(self, "Import from Remmina", msg)
            return

        # Preview dialog — user can deselect individual profiles
        dlg = QDialog(self)
        dlg.setWindowTitle("Import from Remmina")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet("background-color: #263238; color: #eceff1;")
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 16)

        title = QLabel(f"Found <b>{len(parsed)}</b> profile(s) to import:")
        title.setStyleSheet("font-size: 13px;")
        lay.addWidget(title)

        # Protocol color badges
        proto_colors = {'SSH': '#4CAF50', 'VNC': '#2196F3', 'RDP': '#FF9800', 'Telnet': '#9C27B0'}

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: 1px solid #37474f; background: #1c2b30; }")
        scroll_area.setMaximumHeight(280)
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: #1c2b30;")
        scroll_lay = QVBoxLayout(scroll_widget)
        scroll_lay.setSpacing(2)
        scroll_lay.setContentsMargins(8, 8, 8, 8)

        checkboxes = []
        for p in parsed:
            color = proto_colors.get(p['protocol'], '#78909c')
            user_part = f"{p['username']}@" if p['username'] else ''
            label = (f"[<span style='color:{color}'>{p['protocol']}</span>]  "
                     f"{p['name']}  —  {user_part}{p['host']}:{p['port']}  "
                     f"<span style='color:#78909c'>[{p['group']}]</span>")
            cb = QCheckBox()
            cb.setChecked(True)
            cb.setStyleSheet("QCheckBox { color: #eceff1; padding: 2px; } QCheckBox::indicator { width: 14px; height: 14px; }")
            cb.setProperty('profile', p)
            lbl = QLabel(label)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setStyleSheet("color: #eceff1; font-size: 12px;")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(cb)
            row.addWidget(lbl)
            row.addStretch()
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row_widget.setLayout(row)
            # clicking the label also toggles the checkbox
            lbl.mousePressEvent = lambda _ev, c=cb: c.setChecked(not c.isChecked())
            scroll_lay.addWidget(row_widget)
            checkboxes.append(cb)

        scroll_area.setWidget(scroll_widget)
        lay.addWidget(scroll_area)

        if skipped_protocols:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color: #37474f;")
            lay.addWidget(sep)
            skip_lbl = QLabel("Skipped (unsupported protocols):\n" + "\n".join(f"  • {s}" for s in skipped_protocols))
            skip_lbl.setStyleSheet("color: #78909c; font-size: 11px;")
            lay.addWidget(skip_lbl)

        note = QLabel("Profiles with the same name will be updated. Passwords stored in the system keyring will not be imported.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #78909c; font-size: 11px;")
        lay.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("QPushButton { background: #37474f; color: #eceff1; border: none; padding: 6px 18px; border-radius: 4px; } QPushButton:hover { background: #455a64; }")
        cancel_btn.clicked.connect(dlg.reject)
        import_btn = QPushButton("Import Selected")
        import_btn.setStyleSheet("QPushButton { background: #4CAF50; color: white; border: none; padding: 6px 18px; border-radius: 4px; } QPushButton:hover { background: #43A047; }")
        import_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(import_btn)
        lay.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = [cb.property('profile') for cb in checkboxes if cb.isChecked()]
        if not selected:
            return

        for p in selected:
            self.config.save_ssh_profile(
                name=p['name'], host=p['host'], port=p['port'],
                username=p['username'], auth_method=p['auth_method'],
                key_path=p['key_path'], protocol=p['protocol'],
                vendor='Default', group=p['group'],
                password=p['password'],
                terminal_mode=p.get('terminal_mode', 'auto')
            )

        if hasattr(self, 'refresh_ssh_profiles'):
            self.refresh_ssh_profiles()

        counts = {}
        for p in selected:
            counts[p['protocol']] = counts.get(p['protocol'], 0) + 1
        summary = ', '.join(f"{v} {k}" for k, v in sorted(counts.items()))
        QMessageBox.information(
            self, "Import from Remmina",
            f"Successfully imported {len(selected)} profile(s): {summary}."
        )

    def _export_config(self):
        """Export settings.json to a user-chosen location."""
        import shutil
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        src = self.config.config_file
        dst, _ = QFileDialog.getSaveFileName(
            self,
            "Export Config",
            "cetus_config.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if not dst:
            return
        try:
            shutil.copy2(src, dst)
            QMessageBox.information(self, "Export Config", f"Configuration exported to:\n{dst}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not export configuration:\n{e}")

    def _import_config(self):
        """Import a settings.json from a user-chosen file."""
        import shutil
        import json
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        src, _ = QFileDialog.getOpenFileName(
            self,
            "Import Config",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        if not src:
            return

        # Validate JSON before overwriting
        try:
            with open(src, 'r') as f:
                json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Invalid configuration file:\n{e}")
            return

        reply = QMessageBox.question(
            self,
            "Import Config",
            "This will replace your current configuration.\nRestart may be required for all changes to take effect.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            shutil.copy2(src, self.config.config_file)
            self.config.settings = self.config.load()
            QMessageBox.information(
                self,
                "Import Config",
                "Configuration imported successfully.\nSome changes may require a restart to take effect."
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Could not import configuration:\n{e}")

    def _show_about_dialog(self):
        """Show the About Cetus dialog."""
        import os
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
        from PyQt6.QtGui import QPixmap, QFont, QCursor
        from PyQt6.QtCore import Qt, QSize

        dlg = QDialog(self)
        dlg.setWindowTitle("About Cetus")
        dlg.setFixedSize(500, 400)
        dlg.setStyleSheet("QDialog { background-color: #1e1e2e; }")

        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header banner ────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(100)
        header.setStyleSheet("background-color: #12121f;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(24, 0, 24, 0)

        app_icon_path = self.get_icon_path('cetus-64.png')
        app_pix = QPixmap(app_icon_path).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if app_icon_path else None
        if app_pix and not app_pix.isNull():
            icon_lbl = QLabel()
            icon_lbl.setPixmap(app_pix)
            icon_lbl.setFixedSize(60, 60)
            h_lay.addWidget(icon_lbl)
        h_lay.addSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        app_name = QLabel("Cetus")
        app_name.setStyleSheet("color: #ffffff; font-size: 20pt; font-weight: bold; background: transparent;")
        version_lbl = QLabel("v1.7  ·  Network Management Toolkit")
        version_lbl.setStyleSheet("color: #8888aa; font-size: 9pt; background: transparent;")
        title_col.addStretch()
        title_col.addWidget(app_name)
        title_col.addWidget(version_lbl)
        title_col.addStretch()
        h_lay.addLayout(title_col)
        h_lay.addStretch()
        root.addWidget(header)

        # ── Body ─────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background-color: #1e1e2e;")
        b_lay = QVBoxLayout(body)
        b_lay.setContentsMargins(24, 20, 24, 20)
        b_lay.setSpacing(16)

        # Description
        desc = QLabel(
            "Cetus is an open-source network management GUI built with PyQt6.\n"
            "It integrates SSH, Serial, TFTP/FTP/SMB file transfer, IP scanning,\n"
            "SNMP queries, Traceroute, WiFi survey and bandwidth testing\n"
            "into a single, unified interface."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccccdd; font-size: 9.5pt; background: transparent; line-height: 1.5;")
        b_lay.addWidget(desc)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: #333355;")
        b_lay.addWidget(div)

        # Author row
        author_row = QHBoxLayout()
        author_row.setSpacing(16)

        # Photo
        _appdir = os.environ.get('APPDIR', '')
        _local = os.path.dirname(os.path.abspath(__file__))
        photo_paths = [
            os.path.join(_local, 'assets', 'photo.png'),
            os.path.join(_local, 'assets', 'photo.jpg'),
            os.path.join(_appdir, 'usr/share/cetus/photo.png') if _appdir else '',
            '/usr/share/cetus/photo.png',
        ]
        photo_pix = None
        for p in photo_paths:
            if os.path.exists(p):
                photo_pix = QPixmap(p)
                break

        photo_lbl = QLabel()
        photo_lbl.setFixedSize(72, 72)
        photo_lbl.setStyleSheet("""
            QLabel {
                border-radius: 36px;
                border: 2px solid #9C27B0;
                background-color: #2a2a3e;
            }
        """)
        if photo_pix and not photo_pix.isNull():
            scaled = photo_pix.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
            # Crop to circle via mask
            from PyQt6.QtGui import QBitmap, QPainter
            mask = QBitmap(72, 72)
            mask.fill(Qt.GlobalColor.color0)
            p = QPainter(mask)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(0, 0, 72, 72, Qt.GlobalColor.color1)
            p.end()
            scaled.setMask(mask)
            photo_lbl.setPixmap(scaled)
        else:
            # Placeholder initials
            ph_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'assets', 'icons', 'about.svg')
            ph_pix = load_svg_pixmap(ph_icon_path, 40) if os.path.exists(ph_icon_path) else None
            if ph_pix:
                photo_lbl.setPixmap(ph_pix)
            photo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_row.addWidget(photo_lbl)

        author_col = QVBoxLayout()
        author_col.setSpacing(4)
        author_col.addStretch()

        name_lbl = QLabel("Benjamim Gois")
        name_lbl.setStyleSheet("color: #ffffff; font-size: 12pt; font-weight: bold; background: transparent;")
        author_col.addWidget(name_lbl)

        role_lbl = QLabel("Developer")
        role_lbl.setStyleSheet("color: #8888aa; font-size: 9pt; background: transparent;")
        author_col.addWidget(role_lbl)

        gh_btn = QPushButton("  github.com/benjamimgois/opengrid")
        _gh_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'assets', 'icons', 'ssh_icon.svg')
        gh_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #9C27B0;
                font-size: 9pt;
                text-align: left;
                padding: 0;
            }
            QPushButton:hover { color: #ce93d8; text-decoration: underline; }
        """)
        gh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        gh_btn.clicked.connect(lambda: (
            __import__('PyQt6.QtGui', fromlist=['QDesktopServices']).QDesktopServices.openUrl(
                __import__('PyQt6.QtCore', fromlist=['QUrl']).QUrl(
                    'https://github.com/benjamimgois/opengrid'))
        ))
        author_col.addWidget(gh_btn)
        author_col.addStretch()
        author_row.addLayout(author_col)
        author_row.addStretch()
        b_lay.addLayout(author_row)

        # Divider
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet("color: #333355;")
        b_lay.addWidget(div2)

        # License / tech row
        tech_lbl = QLabel("Python 3  ·  PyQt6  ·  GPL-3.0")
        tech_lbl.setStyleSheet("color: #666688; font-size: 8.5pt; background: transparent;")
        tech_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_lay.addWidget(tech_lbl)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #9C27B0; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 10pt; }
            QPushButton:hover { background-color: #7B1FA2; }
        """)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        b_lay.addLayout(btn_row)

        root.addWidget(body)
        dlg.exec()

    def create_serial_page(self):
        """Create the serial connection configuration page"""
        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        # Standard width for all comboboxes
        combo_width = 200

        # Port configuration group
        port_group = QGroupBox("Port Configuration")
        port_outer = QVBoxLayout()
        port_outer.setContentsMargins(12, 8, 12, 10)
        port_outer.setSpacing(8)

        port_field_width = 200
        _SERIAL_COLOR = '#2196F3'
        _port_type_style = f"""
            QPushButton {{
                background-color: #d8d8d8; border: 1px solid #b0b0b0;
                border-radius: 6px; color: #444444; font-size: 9pt; padding: 3px 10px;
            }}
            QPushButton:checked {{
                background-color: {_SERIAL_COLOR}; border-color: {_SERIAL_COLOR};
                color: white; font-weight: bold;
            }}
            QPushButton:hover:!checked {{ background-color: #c8c8c8; }}
        """

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet("color: #555555;")
            return l

        # ── Row 1: Type  Port  Debug ──────────────────────────────────────────
        _row1 = QHBoxLayout()
        _row1.setSpacing(6)
        _row1.addWidget(_lbl("Type:"))
        self._port_type_btns = {}
        for _ptype in ('USB', 'Serial'):
            _btn = QPushButton(_ptype)
            _btn.setCheckable(True)
            _btn.setFixedWidth(85)
            _btn.setFixedHeight(26)
            _btn.setStyleSheet(_port_type_style)
            _btn.setToolTip("Select the type of serial port")
            _btn.clicked.connect(lambda _c, t=_ptype: self._port_type_clicked(t))
            self._port_type_btns[_ptype] = _btn
            _row1.addWidget(_btn)
        self._port_type_btns['USB'].setChecked(True)
        self._port_type_icons = {
            'USB':    self.get_icon_path('usb.svg'),
            'Serial': self.get_icon_path('serial_port.svg'),
        }
        _usb_ico = load_svg_icon_dual(self._port_type_icons['USB'], 24, '#444444', '#ffffff')
        if _usb_ico:
            self._port_type_btns['USB'].setIcon(_usb_ico)
            self._port_type_btns['USB'].setIconSize(QSize(24, 24))
        _serial_ico = load_svg_icon_dual(self._port_type_icons['Serial'], 14, '#444444', '#ffffff')
        if _serial_ico:
            self._port_type_btns['Serial'].setIcon(_serial_ico)
            self._port_type_btns['Serial'].setIconSize(QSize(14, 14))
        _row1.addSpacing(20)
        _row1.addWidget(_lbl("Port:"))
        self.port = FlatComboButton()
        self.port.setFixedWidth(port_field_width)
        self.port.setToolTip("Select the serial port to connect")
        _row1.addWidget(self.port)
        _row1.addStretch()
        self.debug_checkbox = QCheckBox("Debug Mode")
        self.debug_checkbox.setToolTip("Simulate Cisco router — enable to test terminal without a real device")
        self.debug_checkbox.setStyleSheet("""
            QCheckBox { color: #606060; font-size: 9pt; spacing: 4px; }
            QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #d0d0d0;
                border-radius: 3px; background-color: #f5f5f5; }
            QCheckBox::indicator:checked { background-color: #2196F3; border-color: #2196F3; }
            QCheckBox::indicator:hover   { border-color: #2196F3; }
        """)
        _row1.addWidget(self.debug_checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        port_outer.addLayout(_row1)

        # ── Separator ─────────────────────────────────────────────────────────
        _sep = QFrame()
        _sep.setFrameShape(QFrame.Shape.HLine)
        _sep.setStyleSheet("QFrame { color: #dddddd; }")
        port_outer.addWidget(_sep)

        # ── Comm params: Baud Rate / Config / Flow Control stacked ───────────
        _comm_form = QFormLayout()
        _comm_form.setSpacing(4)
        _comm_form.setContentsMargins(0, 0, 0, 0)
        _comm_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.baudrate = FlatComboButton()
        self.baudrate.addItems([
            '300', '1200', '2400', '4800', '9600', '19200',
            '38400', '57600', '115200', '230400', '460800', '921600'
        ])
        self.baudrate.setCurrentText('9600')
        self.baudrate.setFixedWidth(combo_width)
        self.baudrate.setToolTip("Communication speed in bits per second")
        self.baudrate.setStyleSheet("""
            QComboBox { border: 2px solid #2196F3; background-color: #E3F2FD; }
            QComboBox:hover { border: 2px solid #1976D2; background-color: #BBDEFB; }
        """)
        _comm_form.addRow(_lbl("Baud Rate:"), self.baudrate)

        self.serial_config = FlatComboButton()
        self.serial_config.addItems(['8N1', '8E1', '8O1', '8N2', '7N1', '7E1', '7O1'])
        self.serial_config.setCurrentText('8N1')
        self.serial_config.setFixedWidth(combo_width)
        self.serial_config.setToolTip(
            "Serial frame format: Data bits + Parity (N=None, E=Even, O=Odd) + Stop bits\n"
            "Default: 8N1 (8 data bits, no parity, 1 stop bit)"
        )
        _comm_form.addRow(_lbl("Config:"), self.serial_config)

        self.flow = FlatComboButton()
        self.flow.addItems(['None', 'Hardware (RTS/CTS)', 'Software (XON/XOFF)'])
        self.flow.setCurrentText('None')
        self.flow.setFixedWidth(combo_width)
        self.flow.setToolTip("Flow control method (usually None)")
        _comm_form.addRow(_lbl("Flow Control:"), self.flow)

        _comm_row = QHBoxLayout()
        _comm_row.addLayout(_comm_form)
        _comm_row.addStretch()
        port_outer.addLayout(_comm_row)

        port_group.setLayout(port_outer)

        # Add shadow effect to port group
        shadow1 = QGraphicsDropShadowEffect()
        shadow1.setBlurRadius(15)
        shadow1.setXOffset(0)
        shadow1.setYOffset(2)
        shadow1.setColor(QColor(0, 0, 0, 30))
        port_group.setGraphicsEffect(shadow1)

        main_layout.addWidget(port_group)

        # === Quick Connect (Saved Profiles) ===
        profiles_group = QGroupBox("Quick Connect")
        profiles_layout = QVBoxLayout()
        profiles_layout.setContentsMargins(10, 2, 10, 8)
        profiles_layout.setSpacing(6)

        self.serial_profiles_tree = SerialProfilesTree()
        self.serial_profiles_tree.setColumnCount(5)
        self.serial_profiles_tree.setHeaderLabels(["Name", "Port", "Baud", "Config", "Vendor"])
        self.serial_profiles_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.serial_profiles_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.serial_profiles_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.serial_profiles_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.serial_profiles_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.serial_profiles_tree.setColumnWidth(1, 110)
        self.serial_profiles_tree.setColumnWidth(2, 62)
        self.serial_profiles_tree.setColumnWidth(3, 50)
        self.serial_profiles_tree.setColumnWidth(4, 42)
        for col in range(5):
            self.serial_profiles_tree.headerItem().setTextAlignment(
                col, Qt.AlignmentFlag.AlignCenter)
        self.serial_profiles_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.serial_profiles_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.serial_profiles_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.serial_profiles_tree.setRootIsDecorated(False)
        self.serial_profiles_tree.setIndentation(14)
        self.serial_profiles_tree.itemDoubleClicked.connect(self.load_serial_profile_from_tree)
        self.serial_profiles_tree.itemExpanded.connect(self._serial_group_expanded)
        self.serial_profiles_tree.itemCollapsed.connect(self._serial_group_collapsed)
        self.serial_profiles_tree.reordered.connect(self._serial_tree_save_order)
        self.serial_profiles_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
            }
            QTreeWidget::item {
                padding: 2px 2px;
                min-height: 36px;
            }
            QTreeWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QTreeWidget::branch {
                image: none;
                background: transparent;
            }
            QHeaderView::section {
                background-color: #d0d0d0;
                color: #333333;
                padding: 4px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
                qproperty-alignment: AlignCenter;
            }
        """)
        profiles_layout.addWidget(self.serial_profiles_tree)
        self.serial_profiles_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.serial_profiles_tree.customContextMenuRequested.connect(self._serial_profile_context_menu)

        serial_btn_layout = QHBoxLayout()
        serial_btn_layout.setSpacing(8)

        self.save_serial_profile_btn = QPushButton("Save")
        self.save_serial_profile_btn.setFixedWidth(110)
        self.save_serial_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_serial_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #78909c;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #607d8b;
            }
        """)
        self.save_serial_profile_btn.clicked.connect(self.save_current_serial_profile)

        self.delete_serial_profile_btn = QPushButton("Delete")
        self.delete_serial_profile_btn.setFixedWidth(110)
        self.delete_serial_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_serial_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #9e9e9e;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        self.delete_serial_profile_btn.clicked.connect(self.delete_serial_profile)

        serial_btn_layout.addStretch()
        serial_btn_layout.addWidget(self.save_serial_profile_btn)
        serial_btn_layout.addWidget(self.delete_serial_profile_btn)
        serial_btn_layout.addStretch()
        profiles_layout.addLayout(serial_btn_layout)

        profiles_group.setLayout(profiles_layout)

        shadow3 = QGraphicsDropShadowEffect()
        shadow3.setBlurRadius(15)
        shadow3.setXOffset(0)
        shadow3.setYOffset(2)
        shadow3.setColor(QColor(0, 0, 0, 30))
        profiles_group.setGraphicsEffect(shadow3)

        main_layout.addWidget(profiles_group, 1)

        # Status with LED indicator (above connect button)
        status_layout = QHBoxLayout()
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.setSpacing(8)

        self.status_led = QLabel("●")
        self.status_led.setStyleSheet("color: #2196F3; font-size: 14px;")

        self.status_label = QLabel("Ready to connect")
        self.status_label.setStyleSheet("color: #2196F3; font-size: 10pt;")

        status_layout.addWidget(self.status_led)
        status_layout.addWidget(self.status_label)

        status_widget = QWidget()
        status_widget.setLayout(status_layout)
        main_layout.addWidget(status_widget)

        # Connect button (bottom)
        self.connect_btn = QPushButton("CONNECT")
        self.connect_btn.setMinimumHeight(40)
        self.connect_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        self.connect_btn.clicked.connect(self.connect)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.connect_btn.setGraphicsEffect(_btn_shadow)
        _serial_conn_ico = load_svg_icon_dual(self._port_type_icons.get('USB'), 18, '#ffffff', '#ffffff')
        if _serial_conn_ico:
            self.connect_btn.setIcon(_serial_conn_ico)
            self.connect_btn.setIconSize(QSize(18, 18))
            self.connect_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        main_layout.addWidget(self.connect_btn)

        page.setLayout(main_layout)

        # Load saved serial profiles
        self.refresh_serial_profiles()

        return page

    # ──────────────────────────────────────────────────────────────────────
    # TRAFFIC MONITOR
    # ──────────────────────────────────────────────────────────────────────
    _TRAFFIC_COLOR = '#AD1457'

    _LAYER_ICON = {
        'All': 'layer_all.svg',
        'L2':  'layer_l2.svg',
        'L3':  'layer_l3.svg',
        'L4':  'layer_l4.svg',
        'L7':  'layer_l7.svg',
    }

    _FILTER_ICON = {
        # All layer
        'All Traffic': 'proto_all.svg',
        'Non-ARP':     'proto_nonarp.svg',
        'Large pkts':  'proto_largepkt.svg',
        # L2
        'ARP':         'proto_arp.svg',
        'Broadcast':   'proto_broadcast.svg',
        'Multicast':   'proto_multicast.svg',
        'VLAN':        'proto_vlan.svg',
        'STP':         'proto_stp.svg',
        'Non-IP':      'proto_nonip.svg',
        # L3
        'ICMP':        'proto_icmp.svg',
        'ICMPv6':      'proto_icmpv6.svg',
        'OSPF':        'proto_ospf.svg',
        'IPv4':        'proto_ipv4.svg',
        'IPv6':        'proto_ipv6.svg',
        'Fragmented':  'proto_fragmented.svg',
        # L4
        'TCP':         'proto_tcp.svg',
        'UDP':         'proto_udp.svg',
        'TCP SYN':     'proto_tcp_syn.svg',
        'TCP RST':     'proto_tcp_rst.svg',
        'TCP FIN':     'proto_tcp_fin.svg',
        # L7
        'HTTP':        'proto_http.svg',
        'HTTPS':       'proto_https.svg',
        'DNS':         'proto_dns.svg',
        'SSH':         'ssh2.svg',
        'Telnet':      'telnet.svg',
        'FTP':         'ftp.svg',
        'DHCP':        'proto_dhcp.svg',
        'SNMP':        'snmp.svg',
        'RDP':         'rdp.svg',
        'BGP':         'proto_bgp.svg',
        'SIP':         'proto_sip.svg',
        'SMB':         'smb.svg',
    }

    # bg_color, text_color per protocol
    _PROTO_COLORS = {
        'ARP':    ('#FFF3E0', '#E65100'),
        'ICMP':   ('#E0F7FA', '#006064'),
        'ICMPv6': ('#B2EBF2', '#006064'),
        'TCP':    ('#E3F2FD', '#0D47A1'),
        'UDP':    ('#F3E5F5', '#4A148C'),
        'DNS':    ('#E8F5E9', '#1B5E20'),
        'HTTP':   ('#E0F2F1', '#004D40'),
        'HTTPS':  ('#DCEDC8', '#33691E'),
        'DHCP':   ('#FFF9C4', '#F57F17'),
        'SSH':    ('#C8E6C9', '#1B5E20'),
        'Telnet': ('#FFCDD2', '#B71C1C'),
        'FTP':    ('#FFE0B2', '#BF360C'),
        'SMTP':   ('#FCE4EC', '#880E4F'),
        'SNMP':   ('#F8BBD0', '#880E4F'),
        'RDP':    ('#EDE7F6', '#4527A0'),
        'VNC':    ('#D1C4E9', '#4527A0'),
        'SMB':    ('#FFE0B2', '#BF360C'),
        'OSPF':   ('#EFEBE9', '#4E342E'),
        'BGP':    ('#E8EAF6', '#1A237E'),
        'STP':    ('#ECEFF1', '#37474F'),
        'SIP':    ('#FFF8E1', '#F57F17'),
        'IPv6':   ('#EDE7F6', '#311B92'),
        'Other':  ('#F5F5F5', '#424242'),
    }

    _PORT_PROTO = {
        20: 'FTP', 21: 'FTP', 22: 'SSH', 23: 'Telnet', 25: 'SMTP',
        53: 'DNS', 67: 'DHCP', 68: 'DHCP', 69: 'FTP', 80: 'HTTP',
        110: 'SMTP', 143: 'SMTP', 161: 'SNMP', 162: 'SNMP',
        179: 'BGP', 443: 'HTTPS', 445: 'SMB', 139: 'SMB',
        587: 'SMTP', 993: 'SMTP', 995: 'SMTP', 3389: 'RDP',
        5060: 'SIP', 5061: 'SIP', 5900: 'VNC', 8080: 'HTTP', 8443: 'HTTPS',
    }

    _LAYER_FILTERS = {
        'All': [
            ("All Traffic", "",                                                    "Capture everything"),
            ("Non-ARP",     "not arp and not icmp",                               "Exclude ARP and ICMP"),
            ("Large pkts",  "greater 1400",                                        "Packets > 1400 bytes"),
        ],
        'L2': [
            ("ARP",         "arp",                                                 "ARP requests / replies"),
            ("Broadcast",   "broadcast",                                           "Broadcast frames"),
            ("Multicast",   "multicast",                                           "Multicast frames"),
            ("VLAN",        "vlan",                                                "VLAN-tagged (802.1Q)"),
            ("STP",         "stp",                                                 "Spanning Tree Protocol"),
            ("Non-IP",      "not ip and not ip6",                                  "Non-IP Ethernet frames"),
        ],
        'L3': [
            ("ICMP",        "icmp",                                                "ICMP (ping, unreachable)"),
            ("ICMPv6",      "icmp6",                                               "ICMPv6"),
            ("OSPF",        "proto ospf",                                          "OSPF routing protocol"),
            ("IPv4",        "ip",                                                  "All IPv4 packets"),
            ("IPv6",        "ip6",                                                 "All IPv6 packets"),
            ("Fragmented",  "ip[6:2] & 0x1fff != 0",                              "Fragmented IP packets"),
        ],
        'L4': [
            ("TCP",         "tcp",                                                 "All TCP traffic"),
            ("UDP",         "udp",                                                 "All UDP traffic"),
            ("TCP SYN",     "tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0", "New connections"),
            ("TCP RST",     "tcp[tcpflags] & tcp-rst != 0",                       "TCP resets"),
            ("TCP FIN",     "tcp[tcpflags] & tcp-fin != 0",                       "TCP connection closes"),
        ],
        'L7': [
            ("HTTP",        "tcp port 80 or tcp port 8080",                       "HTTP web traffic"),
            ("HTTPS",       "tcp port 443",                                        "HTTPS encrypted"),
            ("DNS",         "port 53",                                             "DNS queries/responses"),
            ("SSH",         "tcp port 22",                                         "SSH connections"),
            ("Telnet",      "tcp port 23",                                         "Telnet (plaintext)"),
            ("FTP",         "tcp port 20 or tcp port 21",                         "FTP control/data"),
            ("DHCP",        "port 67 or port 68",                                  "DHCP leases"),
            ("SNMP",        "port 161 or port 162",                                "SNMP queries/traps"),
            ("RDP",         "tcp port 3389",                                       "RDP remote desktop"),
            ("BGP",         "tcp port 179",                                        "BGP routing"),
            ("SIP",         "port 5060 or port 5061",                             "SIP VoIP signalling"),
            ("SMB",         "tcp port 445 or tcp port 139",                       "SMB file sharing"),
        ],
    }

    def create_traffic_monitor_page(self):
        """Create the Traffic Monitor page with table view and layer-organised filters."""
        self._traffic_worker       = None
        self._traffic_packet_count = 0
        self._traffic_row_buffer   = []
        self._traffic_proto_stats  = {}
        self._traffic_dns_cache    = {}
        self._traffic_dns_pending  = set()
        self._traffic_dns_workers  = []
        try:
            self._traffic_local_ips = {addr for _iface, addr, _pfx in (get_network_interfaces() or []) if addr}
        except Exception:
            self._traffic_local_ips = set()

        _C     = self._TRAFFIC_COLOR
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── Config group ──────────────────────────────────────────────────
        cfg_group = QGroupBox("Capture Configuration")
        cfg_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold; font-size: 9pt;
                border: 1px solid #c8c8c8; border-radius: 8px;
                margin-top: 6px; padding-top: 4px;
                background-color: #f9f9f9;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {_C}; }}
        """)
        cfg_layout = QFormLayout(cfg_group)
        cfg_layout.setVerticalSpacing(4)
        cfg_layout.setContentsMargins(8, 5, 8, 6)
        cfg_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        _iface_widget = QWidget()
        _iface_row    = QHBoxLayout(_iface_widget)
        _iface_row.setContentsMargins(0, 0, 0, 0)
        _iface_row.setSpacing(8)

        self._traffic_iface_combo = FlatComboButton()
        _interfaces  = get_network_interfaces()
        _iface_names = [iface for iface, _ip, _pfx in _interfaces] if _interfaces else []
        self._traffic_iface_combo.addItems(_iface_names if _iface_names else ['any'])
        self._traffic_iface_combo.setFixedWidth(160)
        _iface_row.addWidget(self._traffic_iface_combo)

        _snap_tip = (
            "<b>Snap Length</b> — número máximo de bytes capturados por pacote.<br><br>"
            "<b>96–256</b> &nbsp;→ cabeçalhos apenas (Ethernet + IP + TCP/UDP + início do payload).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Menor uso de CPU/memória; ideal para identificar protocolo e IPs.<br>"
            "<b>512–1500</b> → inclui boa parte do payload; útil para inspecionar HTTP, DNS, etc.<br>"
            "<b>65535</b> &nbsp;&nbsp;&nbsp;→ captura o pacote inteiro (sem limite)."
        )
        _snap_label = QLabel("Snap len:")
        _snap_label.setStyleSheet("color: #555; font-size: 9pt;")
        self._traffic_snaplen_combo = FlatComboButton()
        self._traffic_snaplen_combo.addItems(["96", "256", "512", "1500", "65535"])
        self._traffic_snaplen_combo.setCurrentText("256")
        self._traffic_snaplen_combo.setToolTip(_snap_tip)
        self._traffic_snaplen_combo.setFixedWidth(80)
        _iface_row.addWidget(_snap_label)
        _iface_row.addWidget(self._traffic_snaplen_combo)

        self._traffic_sudo_cb = QCheckBox("sudo")
        self._traffic_sudo_cb.setToolTip("Run tcpdump with sudo (required on most systems)")
        self._traffic_sudo_cb.setChecked(True)
        self._traffic_sudo_cb.setStyleSheet(f"""
            QCheckBox {{ color: #333; font-size: 9pt; spacing: 4px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #c0c0c0;
                border-radius: 3px; background: #f5f5f5; }}
            QCheckBox::indicator:checked {{ background-color: {_C}; border-color: {_C}; }}
        """)
        _iface_row.addWidget(self._traffic_sudo_cb)

        self._traffic_resolve_cb = QCheckBox("Resolve hosts")
        self._traffic_resolve_cb.setToolTip("Resolve IP addresses to hostnames via reverse DNS (may add latency)")
        self._traffic_resolve_cb.setChecked(False)
        self._traffic_resolve_cb.setStyleSheet(f"""
            QCheckBox {{ color: #333; font-size: 9pt; spacing: 4px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #c0c0c0;
                border-radius: 3px; background: #f5f5f5; }}
            QCheckBox::indicator:checked {{ background-color: {_C}; border-color: {_C}; }}
        """)
        _iface_row.addWidget(self._traffic_resolve_cb)
        _iface_row.addStretch()
        cfg_layout.addRow("Interface:", _iface_widget)

        _filter_widget = QWidget()
        _filter_row    = QHBoxLayout(_filter_widget)
        _filter_row.setContentsMargins(0, 0, 0, 0)
        _filter_row.setSpacing(6)
        self._traffic_filter_input = QLineEdit()
        self._traffic_filter_input.setPlaceholderText("tcpdump filter expression  (e.g. tcp port 80)")
        self._traffic_filter_input.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid #d0d0d0; border-radius: 6px; padding: 2px 8px;
                background: #f5f5f5; color: #333; font-size: 9pt; font-family: monospace; }}
            QLineEdit:focus {{ border: 2px solid {_C}; }}
        """)
        self._traffic_filter_input.returnPressed.connect(self._traffic_start_stop)
        _filter_row.addWidget(self._traffic_filter_input)
        cfg_layout.addRow("Filter:", _filter_widget)

        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        cfg_group.setGraphicsEffect(_shadow)
        layout.addWidget(cfg_group)

        # ── Quick Filters (layer-organised) ──────────────────────────────
        _qf_group = QGroupBox("Quick Filters")
        _qf_group.setStyleSheet(f"""
            QGroupBox {{ font-weight: bold; font-size: 9pt;
                border: 1px solid #c8c8c8; border-radius: 8px;
                margin-top: 6px; padding-top: 4px; background-color: #f9f9f9; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {_C}; }}
        """)
        _qf_outer = QVBoxLayout(_qf_group)
        _qf_outer.setContentsMargins(8, 4, 8, 6)
        _qf_outer.setSpacing(4)

        # Layer selector row
        _layer_row_w  = QWidget()
        _layer_row_lo = QHBoxLayout(_layer_row_w)
        _layer_row_lo.setContentsMargins(0, 0, 0, 0)
        _layer_row_lo.setSpacing(4)

        # Layer selector — tab-underline style (visually distinct from filter chips)
        _layer_btn_style = f"""
            QPushButton {{
                border: none;
                border-bottom: 3px solid transparent;
                border-radius: 0px;
                padding: 5px 14px 4px 14px;
                background: transparent;
                color: #666;
                font-size: 9pt;
                font-weight: bold;
                min-height: 28px;
            }}
            QPushButton:hover {{
                color: {_C};
                background: rgba(84, 110, 122, 0.08);
            }}
            QPushButton:checked {{
                color: {_C};
                border-bottom: 3px solid {_C};
                background: rgba(84, 110, 122, 0.10);
            }}
        """
        _layer_label = {
            'All': 'All',
            'L2':  'Layer 2',
            'L3':  'Layer 3',
            'L4':  'Layer 4',
            'L7':  'Layer 7',
        }
        _layer_tooltip = {
            'All': '<b>All</b> — captura todos os pacotes sem filtro por camada.',
            'L2':  '<b>Layer 2 — Data Link</b><br>Frames Ethernet: ARP, Broadcast, Multicast, VLAN (802.1Q), STP.',
            'L3':  '<b>Layer 3 — Network</b><br>Pacotes IP: ICMP, ICMPv6, IPv4, IPv6, OSPF, fragmentação.',
            'L4':  '<b>Layer 4 — Transport</b><br>Segmentos TCP e UDP, incluindo flags SYN, RST e FIN.',
            'L7':  '<b>Layer 7 — Application</b><br>Protocolos de aplicação: HTTP, HTTPS, DNS, SSH, Telnet, FTP, DHCP, SNMP, RDP, BGP, SIP, SMB.',
        }
        self._traffic_layer_btns = {}
        for _ln in self._LAYER_FILTERS:
            _lb = QPushButton(_layer_label.get(_ln, _ln))
            _lb.setCheckable(True)
            _lb.setChecked(_ln == 'All')
            _lb.setToolTip(_layer_tooltip.get(_ln, ''))
            _lb.setStyleSheet(_layer_btn_style)
            _lb.setCursor(Qt.CursorShape.PointingHandCursor)
            _lb_icon_path = self.get_tab_icon_path(self._LAYER_ICON.get(_ln, ''))
            if _lb_icon_path:
                _lb_icon = load_svg_icon_dual(_lb_icon_path, 14, color_off='#888888', color_on=_C)
                if _lb_icon:
                    _lb.setIcon(_lb_icon)
                    _lb.setIconSize(QSize(14, 14))
            _lb.clicked.connect(lambda _, ln=_ln: self._traffic_layer_selected(ln))
            _layer_row_lo.addWidget(_lb)
            self._traffic_layer_btns[_ln] = _lb
        _layer_row_lo.addStretch()
        _qf_outer.addWidget(_layer_row_w)

        # Protocol filter chips — pill shape, clearly different from layer tabs
        _filter_btn_style = f"""
            QPushButton {{
                border: 1px solid #dde0e2;
                border-radius: 10px;
                padding: 2px 9px;
                background: #f5f6f7;
                color: #555;
                font-size: 8pt;
            }}
            QPushButton:hover {{
                background: #e8eaec;
                border-color: #b0bec5;
                color: #333;
            }}
            QPushButton:checked {{
                background: {_C};
                color: white;
                border-color: {_C};
                font-weight: bold;
            }}
        """
        self._traffic_filter_stack = QStackedWidget()
        for _ln, _filters in self._LAYER_FILTERS.items():
            _pg_w  = QWidget()
            _pg_lo = QHBoxLayout(_pg_w)
            _pg_lo.setContentsMargins(0, 0, 0, 0)
            _pg_lo.setSpacing(4)
            for _label, _expr, _tip in _filters:
                _fb = QPushButton(_label)
                _fb.setCheckable(True)
                _fb.setChecked(_label == 'All Traffic')
                _fb.setToolTip(_tip)
                _fb.setStyleSheet(_filter_btn_style)
                _fb.setCursor(Qt.CursorShape.PointingHandCursor)
                _fb_icon_path = self.get_tab_icon_path(self._FILTER_ICON.get(_label, ''))
                if _fb_icon_path:
                    _fb_icon = load_svg_icon_dual(_fb_icon_path, 13)
                    if _fb_icon:
                        _fb.setIcon(_fb_icon)
                        _fb.setIconSize(QSize(13, 13))
                _fb.clicked.connect(lambda _, e=_expr, b=_fb: self._traffic_preset_clicked(e, b))
                _pg_lo.addWidget(_fb)
            _pg_lo.addStretch()
            self._traffic_filter_stack.addWidget(_pg_w)
        _qf_outer.addWidget(self._traffic_filter_stack)

        _shadow2 = QGraphicsDropShadowEffect()
        _shadow2.setBlurRadius(15); _shadow2.setXOffset(0); _shadow2.setYOffset(2)
        _shadow2.setColor(QColor(0, 0, 0, 30))
        _qf_group.setGraphicsEffect(_shadow2)
        layout.addWidget(_qf_group)

        # ── Protocol stats bar ────────────────────────────────────────────
        from PyQt6.QtWidgets import QScrollArea, QFrame
        _stats_outer_w = QWidget()
        _stats_outer_w.setFixedHeight(28)
        _stats_outer_lo = QHBoxLayout(_stats_outer_w)
        _stats_outer_lo.setContentsMargins(2, 0, 2, 0)
        _stats_outer_lo.setSpacing(0)
        _stats_scroll = QScrollArea()
        _stats_scroll.setWidgetResizable(True)
        _stats_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _stats_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _stats_scroll.setFixedHeight(28)
        _stats_inner_w = QWidget()
        self._traffic_stats_layout = QHBoxLayout(_stats_inner_w)
        self._traffic_stats_layout.setContentsMargins(0, 2, 0, 2)
        self._traffic_stats_layout.setSpacing(4)
        self._traffic_stats_layout.addStretch()
        _stats_scroll.setWidget(_stats_inner_w)
        _stats_outer_lo.addWidget(_stats_scroll)
        layout.addWidget(_stats_outer_w)

        # ── Results group (wraps search + table + bottom bar + packet desc) ──
        _traffic_results_group = QGroupBox("Packets")
        _traffic_results_layout = QVBoxLayout(_traffic_results_group)
        _traffic_results_layout.setContentsMargins(8, 4, 8, 8)
        _traffic_results_layout.setSpacing(6)

        # ── Post-capture text filter ──────────────────────────────────────
        self._traffic_search_input = QLineEdit()
        self._traffic_search_input.setPlaceholderText("Filter captured packets by IP, protocol or text…")
        self._traffic_search_input.setClearButtonEnabled(True)
        self._traffic_search_input.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid #d0d0d0; border-radius: 6px; padding: 2px 8px;
                background: #f5f5f5; color: #333; font-size: 9pt; }}
            QLineEdit:focus {{ border: 2px solid {_C}; }}
        """)
        self._traffic_search_input.textChanged.connect(self._traffic_filter_table)
        _traffic_results_layout.addWidget(self._traffic_search_input)

        # ── Packet table ──────────────────────────────────────────────────
        self._traffic_sort_state = {}   # col → Qt.SortOrder or absent (=unsorted)
        self._traffic_table = QTableWidget(0, 8)  # col 7 hidden: original order
        self._traffic_table.setHorizontalHeaderLabels(
            ['Time', 'Source', 'Destination', 'Protocol', 'Layer', 'Len', 'Info', '_seq'])
        self._traffic_table.setColumnHidden(7, True)
        self._traffic_table.setSortingEnabled(False)
        self._traffic_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._traffic_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._traffic_table.setAlternatingRowColors(False)
        self._traffic_table.verticalHeader().setVisible(False)
        self._traffic_table.verticalHeader().setDefaultSectionSize(20)
        _hdr = self._traffic_table.horizontalHeader()
        _hdr.setSortIndicatorShown(True)
        _hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        _hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        _hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._traffic_table.setColumnWidth(0, 110)
        self._traffic_table.setColumnWidth(1, 145)
        self._traffic_table.setColumnWidth(2, 145)
        self._traffic_table.setColumnWidth(3, 75)
        self._traffic_table.setColumnWidth(4, 45)
        self._traffic_table.setColumnWidth(5, 50)
        self._traffic_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                gridline-color: #e8e8e8;
                font-size: 8pt;
                font-family: monospace;
            }}
            QTableWidget::item {{ padding: 1px 4px; }}
            QTableWidget::item:selected {{ background-color: {_C}; color: white; }}
            QHeaderView::section {{
                background-color: #f0f0f0; color: #333;
                padding: 4px 6px; border: none;
                border-right: 1px solid #e0e0e0;
                border-bottom: 1px solid #d0d0d0;
                font-weight: bold; font-size: 8pt;
                cursor: pointer;
            }}
            QHeaderView::section:hover {{ background-color: #e0e0e0; }}
        """)
        _hdr.sectionClicked.connect(self._traffic_sort_by_col)
        self._traffic_table.itemSelectionChanged.connect(self._traffic_on_row_selected)
        self._traffic_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._traffic_table.customContextMenuRequested.connect(self._traffic_context_menu)
        _traffic_results_layout.addWidget(self._traffic_table, 1)

        # Flush timer for batch row inserts (150 ms)
        self._traffic_flush_timer = QTimer()
        self._traffic_flush_timer.setInterval(150)
        self._traffic_flush_timer.timeout.connect(self._traffic_flush_rows)

        # ── Bottom status + Clear ─────────────────────────────────────────
        _bottom    = QWidget()
        _bottom_lo = QHBoxLayout(_bottom)
        _bottom_lo.setContentsMargins(0, 0, 0, 0)
        _bottom_lo.setSpacing(8)

        self._traffic_status_lbl = QLabel("Packets: 0")
        self._traffic_status_lbl.setStyleSheet("color: #555; font-size: 9pt;")
        _bottom_lo.addWidget(self._traffic_status_lbl)
        _bottom_lo.addStretch()

        _export_btn = QPushButton("Export CSV")
        _export_btn.setFixedWidth(100)
        _export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _export_btn.setToolTip("Save visible rows to a CSV file")
        _export_btn.setStyleSheet(f"""
            QPushButton {{ border: 1px solid {_C}; border-radius: 6px; padding: 4px 12px;
                background: #fff; color: {_C}; font-size: 9pt; font-weight: bold; }}
            QPushButton:hover {{ background: {_C}; color: white; }}
        """)
        _export_btn.clicked.connect(self._traffic_export_csv)
        _bottom_lo.addWidget(_export_btn)

        _clear_btn = QPushButton("Clear")
        _clear_btn.setFixedWidth(80)
        _clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _clear_btn.setStyleSheet(f"""
            QPushButton {{ border: 1px solid #c0c0c0; border-radius: 6px; padding: 4px 12px;
                background: #f0f0f0; color: #333; font-size: 9pt; }}
            QPushButton:hover {{ background: #e0e0e0; }}
        """)
        _clear_btn.clicked.connect(self._traffic_clear)
        _bottom_lo.addWidget(_clear_btn)
        _traffic_results_layout.addWidget(_bottom)

        # ── Packet description label ──────────────────────────────────────
        self._traffic_packet_desc = QLabel("")
        self._traffic_packet_desc.setWordWrap(True)
        self._traffic_packet_desc.setStyleSheet(f"""
            QLabel {{
                color: #37474F;
                background: #ECEFF1;
                border: 1px solid #CFD8DC;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 8pt;
            }}
        """)
        self._traffic_packet_desc.setMinimumHeight(30)
        self._traffic_packet_desc.hide()
        _traffic_results_layout.addWidget(self._traffic_packet_desc)

        _shadow3 = QGraphicsDropShadowEffect()
        _shadow3.setBlurRadius(15); _shadow3.setXOffset(0); _shadow3.setYOffset(2)
        _shadow3.setColor(QColor(0, 0, 0, 30))
        _traffic_results_group.setGraphicsEffect(_shadow3)
        _traffic_results_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(_traffic_results_group, 1)

        # ── Big START button ──────────────────────────────────────────────
        self._traffic_start_btn = QPushButton("START CAPTURE")
        self._traffic_start_btn.setFixedHeight(48)
        self._traffic_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._traffic_start_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self._traffic_start_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {_C}; color: white; border: none;
                border-radius: 8px; font-weight: bold; font-size: 11pt; }}
            QPushButton:hover   {{ background-color: #880E4F; }}
            QPushButton:pressed {{ background-color: #6A0F3E; }}
        """)
        self._traffic_start_btn.clicked.connect(self._traffic_start_stop)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self._traffic_start_btn.setGraphicsEffect(_btn_shadow)
        _arp_ico = load_svg_icon_dual(self.get_icon_path('proto_arp.svg'), 18, '#ffffff', '#ffffff')
        if _arp_ico:
            self._traffic_start_btn.setIcon(_arp_ico)
            self._traffic_start_btn.setIconSize(QSize(18, 18))
            self._traffic_start_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self._traffic_start_btn)

        return page

    @staticmethod
    def _traffic_parse_line(line):
        """Parse a tcpdump -e -n output line into (time, src, dst, proto, layer, len, info)."""
        import re
        line = line.strip()
        if not line:
            return None

        # Expected format (tcpdump -e -n):
        #   HH:MM:SS.ffffff  SRC_MAC > DST_MAC, ethertype TYPE (0xNNNN), length NNN: payload
        m = re.match(
            r'^(\d\d:\d\d:\d\d\.\d+)\s+'
            r'(\S+)\s+>\s+(\S+),\s+'
            r'ethertype\s+(\S+)\s+\([^)]+\),\s+'
            r'length\s+(\d+):\s*(.*)',
            line, re.IGNORECASE,
        )
        if not m:
            return None

        time_s, src_mac, dst_mac, eth_type, length, rest = m.groups()
        src, dst, proto, layer = src_mac, dst_mac, eth_type, 'L2'

        if eth_type in ('IPv4', 'IPv6'):
            layer = 'L3'
            proto = 'IPv4' if eth_type == 'IPv4' else 'IPv6'

            # Payload starts with:  SRC_ADDR.PORT > DST_ADDR.PORT: flags...
            # Use non-greedy + ": " boundary to handle IPv6 colons correctly.
            ip_m = re.match(r'(\S+)\s+>\s+(.+?):\s(.*)', rest)
            if ip_m:
                src_ep, dst_ep, rest = ip_m.groups()

                def _split_ep(ep):
                    """Return (address, port_int_or_None). Port follows last dot."""
                    dot = ep.rfind('.')
                    if dot < 0:
                        return ep, None
                    tail = ep[dot + 1:]
                    # For plain IPv4 (3 dots) the last segment is the 4th octet, not a port
                    if tail.isdigit() and ep.count('.') != 3:
                        return ep[:dot], int(tail)
                    return ep, None

                src_ip, src_port = _split_ep(src_ep)
                dst_ip, dst_port = _split_ep(dst_ep)
                src, dst = src_ip, dst_ip

                # Map well-known port → application-layer protocol name
                proto_from_port = None
                for _p in (dst_port, src_port):
                    if _p and _p in SerialTerminalGUI._PORT_PROTO:
                        proto_from_port = SerialTerminalGUI._PORT_PROTO[_p]
                        break

                # Identify transport / application protocol from payload hint
                rest_up = rest.upper()
                if rest.startswith('Flags') or 'SEQ' in rest_up:
                    l4 = proto_from_port or 'TCP'
                elif rest.startswith('UDP'):
                    l4 = proto_from_port or 'UDP'
                elif 'ICMP' in rest_up:
                    l4 = 'ICMPv6' if eth_type == 'IPv6' else 'ICMP'
                elif 'OSPF' in rest_up:
                    l4 = 'OSPF'
                elif proto_from_port:
                    l4 = proto_from_port
                else:
                    l4 = None

                if l4:
                    proto = l4
                    layer = 'L4' if l4 in ('TCP', 'UDP', 'ICMP', 'ICMPv6', 'OSPF') else 'L7'

        elif eth_type == 'ARP':
            proto, layer = 'ARP',  'L2'
        elif eth_type == 'LLDP':
            proto, layer = 'LLDP', 'L2'

        info = (rest or '')[:100]
        return (time_s, src, dst, proto, layer, length, info)

    def _traffic_flush_rows(self):
        """Batch-insert buffered rows into the packet table (called every 150 ms)."""
        if not self._traffic_row_buffer:
            return
        rows = self._traffic_row_buffer[:]
        self._traffic_row_buffer.clear()

        tbl = self._traffic_table
        tbl.setUpdatesEnabled(False)
        _resolve = self._traffic_resolve_cb.isChecked()
        for time_s, src, dst, proto, layer, length, info in rows:
            # Protocol stats
            self._traffic_proto_stats[proto] = self._traffic_proto_stats.get(proto, 0) + 1

            bg_hex, fg_hex = self._PROTO_COLORS.get(proto, self._PROTO_COLORS['Other'])
            bg = QColor(bg_hex)
            fg = QColor(fg_hex)
            _own_src = src in self._traffic_local_ips
            _own_dst = dst in self._traffic_local_ips

            # Apply DNS cache lookup (display hostname if already resolved)
            _src_display = self._traffic_dns_cache.get(src, src) if _resolve else src
            _dst_display = self._traffic_dns_cache.get(dst, dst) if _resolve else dst

            _tooltip = self._traffic_describe_packet(proto, src, dst, info)

            row_idx = tbl.rowCount()
            tbl.insertRow(row_idx)
            _own_fg = QColor('#1565C0')
            for col, text in enumerate([time_s, _src_display, _dst_display, proto, layer, str(length), info]):
                item = QTableWidgetItem(text)
                item.setBackground(QBrush(bg))
                if (col == 1 and _own_src) or (col == 2 and _own_dst):
                    item.setForeground(QBrush(_own_fg))
                    f = item.font(); f.setBold(True); item.setFont(f)
                else:
                    item.setForeground(QBrush(fg))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(_tooltip)
                # Store original IP for later DNS update
                if col == 1:
                    item.setData(Qt.ItemDataRole.UserRole, src)
                elif col == 2:
                    item.setData(Qt.ItemDataRole.UserRole, dst)
                tbl.setItem(row_idx, col, item)
            # Hidden column 7: zero-padded sequence for restore-sort
            seq_item = QTableWidgetItem(f'{self._traffic_packet_count:010d}')
            seq_item.setFlags(seq_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(row_idx, 7, seq_item)

            # Queue DNS resolution for new IPs
            if _resolve:
                for _ip in (src, dst):
                    if _ip and '.' in _ip and _ip not in self._traffic_dns_cache and _ip not in self._traffic_dns_pending:
                        self._traffic_resolve_start(_ip)
        tbl.setUpdatesEnabled(True)
        self._traffic_update_stats()

        # Cap table at 3 000 rows — discard oldest
        excess = tbl.rowCount() - 3000
        if excess > 0:
            tbl.setUpdatesEnabled(False)
            for _ in range(excess):
                tbl.removeRow(0)
            tbl.setUpdatesEnabled(True)

        tbl.scrollToBottom()

    def _traffic_layer_selected(self, layer_name):
        """Switch the filter-button panel to the chosen OSI layer."""
        for name, btn in self._traffic_layer_btns.items():
            btn.setChecked(name == layer_name)
        layer_names = list(self._LAYER_FILTERS.keys())
        if layer_name in layer_names:
            self._traffic_filter_stack.setCurrentIndex(layer_names.index(layer_name))

    def _traffic_preset_clicked(self, expr, clicked_btn):
        """Apply a quick-filter preset button."""
        for i in range(self._traffic_filter_stack.count()):
            for btn in self._traffic_filter_stack.widget(i).findChildren(QPushButton):
                btn.setChecked(False)
        clicked_btn.setChecked(True)
        self._traffic_filter_input.setText(expr)

    def _traffic_clear(self):
        self._traffic_table.setRowCount(0)
        self._traffic_row_buffer.clear()
        self._traffic_packet_count = 0
        self._traffic_proto_stats.clear()
        self._traffic_status_lbl.setText("Packets: 0")
        self._traffic_search_input.clear()
        self._traffic_update_stats()

    def _traffic_start_stop(self):
        if self._traffic_worker and self._traffic_worker.isRunning():
            self._traffic_flush_timer.stop()
            self._traffic_flush_rows()
            self._traffic_worker.stop()
            self._traffic_worker.wait(2000)
            self._traffic_worker = None
            self._traffic_start_btn.setText("START CAPTURE")
            self._traffic_start_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {self._TRAFFIC_COLOR}; color: white; border: none;
                    border-radius: 8px; font-weight: bold; font-size: 11pt; }}
                QPushButton:hover   {{ background-color: #455a64; }}
                QPushButton:pressed {{ background-color: #37474f; }}
            """)
            return

        iface    = self._traffic_iface_combo.currentText()
        filt     = self._traffic_filter_input.text().strip()
        snap_len = int(self._traffic_snaplen_combo.currentText())
        use_sudo = self._traffic_sudo_cb.isChecked()

        sudo_pw = None
        if use_sudo:
            from PyQt6.QtWidgets import QInputDialog
            pw, ok = QInputDialog.getText(
                self, "sudo password",
                "Enter sudo password for tcpdump:",
                QLineEdit.EchoMode.Password
            )
            if not ok:
                return
            sudo_pw = pw

        self._traffic_packet_count = 0
        self._traffic_row_buffer.clear()
        self._traffic_table.setRowCount(0)
        self._traffic_proto_stats.clear()
        self._traffic_dns_cache.clear()
        self._traffic_dns_pending.clear()
        self._traffic_status_lbl.setText("Packets: 0")
        self._traffic_update_stats()

        self._traffic_worker = TcpdumpWorker(iface, filt, snap_len, sudo_pw)
        self._traffic_worker.line_received.connect(self._traffic_on_line)
        self._traffic_worker.packet_count_updated.connect(self._traffic_on_count)
        self._traffic_worker.error_occurred.connect(self._traffic_on_error)
        self._traffic_worker.start()
        self._traffic_flush_timer.start()

        self._traffic_start_btn.setText("STOP CAPTURE")
        self._traffic_start_btn.setStyleSheet("""
            QPushButton { background-color: #c62828; color: white; border: none;
                border-radius: 8px; font-weight: bold; font-size: 11pt; }
            QPushButton:hover { background-color: #b71c1c; }
        """)

    def _traffic_on_line(self, line):
        parsed = self._traffic_parse_line(line)
        if parsed:
            self._traffic_row_buffer.append(parsed)

    def _traffic_on_count(self, count):
        self._traffic_packet_count = count
        self._traffic_status_lbl.setText(f"Packets: {count}")

    def _traffic_on_error(self, msg):
        from PyQt6.QtWidgets import QMessageBox
        self._traffic_flush_timer.stop()
        if self._traffic_worker:
            self._traffic_worker = None
        self._traffic_start_btn.setText("START CAPTURE")
        self._traffic_start_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {self._TRAFFIC_COLOR}; color: white; border: none;
                border-radius: 8px; font-weight: bold; font-size: 11pt; }}
            QPushButton:hover {{ background-color: #455a64; }}
        """)
        QMessageBox.warning(self, "tcpdump error", msg)

    def _traffic_sort_by_col(self, col):
        """Cycle sort on column header click: ascending → descending → original order."""
        if col >= 7:   # ignore hidden sequence column
            return
        tbl   = self._traffic_table
        state = self._traffic_sort_state.get(col)
        hdr   = tbl.horizontalHeader()
        if state is None:
            # First click → ascending
            tbl.sortItems(col, Qt.SortOrder.AscendingOrder)
            self._traffic_sort_state = {col: Qt.SortOrder.AscendingOrder}
            hdr.setSortIndicator(col, Qt.SortOrder.AscendingOrder)
            hdr.setSortIndicatorShown(True)
        elif state == Qt.SortOrder.AscendingOrder:
            # Second click → descending
            tbl.sortItems(col, Qt.SortOrder.DescendingOrder)
            self._traffic_sort_state = {col: Qt.SortOrder.DescendingOrder}
            hdr.setSortIndicator(col, Qt.SortOrder.DescendingOrder)
        else:
            # Third click → restore capture order (sort by hidden seq column)
            tbl.sortItems(7, Qt.SortOrder.AscendingOrder)
            self._traffic_sort_state = {}
            hdr.setSortIndicatorShown(False)

    def _traffic_on_row_selected(self):
        """Update packet description label when a row is selected."""
        row = self._traffic_table.currentRow()
        if row < 0:
            self._traffic_packet_desc.hide()
            return

        def _cell(c):
            item = self._traffic_table.item(row, c)
            return item.text() if item else ''

        proto = _cell(3)
        src   = _cell(1)
        dst   = _cell(2)
        info  = _cell(6)
        length = _cell(5)
        time_s = _cell(0)

        desc = self._traffic_describe_packet(proto, src, dst, info)
        self._traffic_packet_desc.setText(f'[{time_s}]  {desc}  •  {length} bytes')
        self._traffic_packet_desc.show()

    @staticmethod
    def _traffic_describe_packet(proto, src, dst, info):
        """Return a human-readable description for a captured packet."""
        il = info.lower()

        def _arp():
            if 'request' in il:
                # Extract "who-has X tell Y" if present
                import re
                m = re.search(r'who-has\s+(\S+)', info)
                target = m.group(1).rstrip(',') if m else dst
                return f'ARP Request: who has {target}? Sent by {src}'
            return f'ARP Reply: {src} reports its MAC address'

        def _icmp():
            if 'request' in il or 'echo' in il and 'reply' not in il:
                return f'Ping request from {src} → {dst}'
            if 'reply' in il:
                return f'Ping reply from {src} → {dst}'
            if 'unreachable' in il:
                return f'ICMP Unreachable: {src} could not reach {dst}'
            if 'redirect' in il:
                return f'ICMP Redirect from {src}'
            return f'ICMP message from {src} → {dst}'

        def _tcp():
            if 'flags [s]' in il or ('[s,' in il) or ('syn' in il and 'ack' not in il):
                return f'TCP SYN: {src} is opening a connection to {dst}'
            if 'flags [s.]' in il or ('syn' in il and 'ack' in il):
                return f'TCP SYN-ACK: {dst} accepted the connection from {src}'
            if '[r' in il or 'rst' in il:
                return f'TCP Reset: connection between {src} and {dst} was abruptly closed'
            if '[f' in il or 'fin' in il:
                return f'TCP FIN: {src} is closing the connection to {dst}'
            return f'TCP data exchange between {src} and {dst}'

        def _dns():
            import re
            # Query
            m = re.search(r'\?\s+(\S+)', info)
            if m:
                return f'DNS Query from {src}: resolving "{m.group(1).rstrip(".")}"'
            # Response with IP
            m2 = re.search(r'A\s+([\d.]+)', info)
            if m2:
                return f'DNS Response from {src}: resolved to {m2.group(1)}'
            return f'DNS traffic between {src} and {dst}'

        def _dhcp():
            if 'discover' in il:
                return f'DHCP Discover: {src} is broadcasting to find a DHCP server'
            if 'offer' in il:
                return f'DHCP Offer: server {src} is proposing an IP address'
            if 'request' in il:
                return f'DHCP Request: {src} is requesting IP address confirmation'
            if 'ack' in il:
                return f'DHCP ACK: server confirmed IP address assignment to {dst}'
            if 'nak' in il or 'nack' in il:
                return f'DHCP NAK: server {src} refused the request from {dst}'
            return f'DHCP message between {src} and {dst}'

        def _http():
            import re
            m = re.match(r'(GET|POST|PUT|DELETE|HEAD|PATCH|OPTIONS)\s+(\S+)', info, re.I)
            if m:
                return f'HTTP {m.group(1).upper()} {m.group(2)} from {src} to {dst}'
            if re.match(r'HTTP/\d', info):
                m2 = re.search(r'HTTP/[\d.]+ (\d{3})', info)
                code = m2.group(1) if m2 else '?'
                return f'HTTP Response {code} from {src} to {dst}'
            return f'HTTP traffic between {src} and {dst}'

        def _ospf():
            if 'hello' in il:
                return f'OSPF Hello: router {src} is advertising its presence on the link'
            if 'lsa' in il or 'update' in il:
                return f'OSPF LSA Update from {src}: routing topology change'
            if 'dbdesc' in il or 'database' in il:
                return f'OSPF Database Description from {src}'
            return f'OSPF routing protocol message from {src}'

        def _sip():
            import re
            m = re.match(r'(INVITE|BYE|REGISTER|ACK|CANCEL|OPTIONS|PRACK)\s', info, re.I)
            if m:
                method = m.group(1).upper()
                actions = {
                    'INVITE': f'SIP INVITE: {src} is initiating a call to {dst}',
                    'BYE': f'SIP BYE: {src} is ending the call with {dst}',
                    'REGISTER': f'SIP REGISTER: {src} is registering with {dst}',
                    'ACK': f'SIP ACK: {src} confirmed the call setup with {dst}',
                    'CANCEL': f'SIP CANCEL: {src} cancelled the call to {dst}',
                }
                return actions.get(method, f'SIP {method} from {src} to {dst}')
            return f'SIP VoIP signalling between {src} and {dst}'

        dispatch = {
            'ARP':    _arp,
            'ICMP':   _icmp,
            'ICMPv6': lambda: f'ICMPv6 message from {src} → {dst}' + (f': {info[:60]}' if info else ''),
            'TCP':    _tcp,
            'UDP':    lambda: f'UDP datagram from {src} → {dst}',
            'DNS':    _dns,
            'HTTP':   _http,
            'HTTPS':  lambda: f'HTTPS encrypted traffic between {src} and {dst}',
            'DHCP':   _dhcp,
            'SSH':    lambda: f'SSH encrypted session between {src} and {dst}',
            'Telnet': lambda: f'Telnet (cleartext) session from {src} to {dst}',
            'FTP':    lambda: f'FTP file transfer control/data between {src} and {dst}',
            'SMTP':   lambda: f'SMTP email message from {src} to {dst}',
            'SNMP':   lambda: (
                f'SNMP query from {src} to {dst}' if '161' in dst
                else f'SNMP trap from {src} to {dst}'
            ),
            'RDP':    lambda: f'RDP remote desktop session from {src} to {dst}',
            'VNC':    lambda: f'VNC remote desktop session from {src} to {dst}',
            'SMB':    lambda: f'SMB file sharing traffic between {src} and {dst}',
            'OSPF':   _ospf,
            'BGP':    lambda: f'BGP routing protocol exchange between {src} and {dst}',
            'STP':    lambda: f'STP BPDU from {src} — spanning-tree topology message',
            'SIP':    _sip,
            'LLDP':   lambda: f'LLDP: {src} is announcing its identity and capabilities',
            'IPv4':   lambda: f'IPv4 packet from {src} to {dst}',
            'IPv6':   lambda: f'IPv6 packet from {src} to {dst}',
        }
        fn = dispatch.get(proto)
        if fn:
            try:
                return fn()
            except Exception:
                pass
        return f'{proto} traffic from {src} to {dst}' + (f' — {info[:60]}' if info else '')

    def _traffic_update_stats(self):
        """Rebuild the protocol statistics bar with per-protocol counters."""
        lay = self._traffic_stats_layout
        # Remove all widgets except the trailing stretch
        while lay.count() > 1:
            child = lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        # Add badges sorted by count (top 14 protos)
        sorted_protos = sorted(self._traffic_proto_stats.items(), key=lambda x: -x[1])[:14]
        for proto, count in sorted_protos:
            bg_h, fg_h = self._PROTO_COLORS.get(proto, self._PROTO_COLORS['Other'])
            lbl = QLabel(f'{proto}: {count}')
            lbl.setStyleSheet(f"""
                QLabel {{
                    background: {bg_h}; color: {fg_h};
                    border-radius: 8px; padding: 1px 7px;
                    font-size: 8pt; font-weight: bold;
                }}
            """)
            lay.insertWidget(lay.count() - 1, lbl)

    def _traffic_filter_table(self, text):
        """Show/hide table rows based on search text (post-capture filter)."""
        tbl    = self._traffic_table
        needle = text.strip().lower()
        for row in range(tbl.rowCount()):
            if not needle:
                tbl.setRowHidden(row, False)
                continue
            visible = any(
                needle in (tbl.item(row, col).text().lower() if tbl.item(row, col) else '')
                for col in range(7)
            )
            tbl.setRowHidden(row, not visible)

    def _traffic_context_menu(self, pos):
        """Right-click context menu for the packet table."""
        from PyQt6.QtWidgets import QMenu
        row = self._traffic_table.rowAt(pos.y())
        if row < 0:
            return
        def _cell(c):
            item = self._traffic_table.item(row, c)
            return item.text() if item else ''
        src   = _cell(1)
        dst   = _cell(2)
        proto = _cell(3)
        menu  = QMenu(self)
        menu.addAction(f'Copy source  [{src}]',
                       lambda: QApplication.clipboard().setText(src))
        menu.addAction(f'Copy dest  [{dst}]',
                       lambda: QApplication.clipboard().setText(dst))
        menu.addSeparator()
        menu.addAction('Filter by source IP',
                       lambda: self._traffic_search_input.setText(src))
        menu.addAction('Filter by dest IP',
                       lambda: self._traffic_search_input.setText(dst))
        menu.addAction('Filter by protocol',
                       lambda: self._traffic_search_input.setText(proto))
        menu.addSeparator()
        full_row = '\t'.join(_cell(c) for c in range(7))
        menu.addAction('Copy full row',
                       lambda: QApplication.clipboard().setText(full_row))
        menu.exec(self._traffic_table.viewport().mapToGlobal(pos))

    def _traffic_export_csv(self):
        """Export visible table rows to a CSV file."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Traffic to CSV", "traffic_capture.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        tbl     = self._traffic_table
        headers = ['Time', 'Source', 'Destination', 'Protocol', 'Layer', 'Len', 'Info']
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                exported = 0
                for row in range(tbl.rowCount()):
                    if tbl.isRowHidden(row):
                        continue
                    writer.writerow([
                        tbl.item(row, col).text() if tbl.item(row, col) else ''
                        for col in range(7)
                    ])
                    exported += 1
            QMessageBox.information(self, "Export Complete", f"Exported {exported} rows to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))

    def _traffic_resolve_start(self, ip):
        """Start a background DNS resolution worker for the given IP."""
        self._traffic_dns_pending.add(ip)
        worker = DnsResolverWorker(ip)
        worker.resolved.connect(self._traffic_on_dns_resolved)
        self._traffic_dns_workers.append(worker)
        worker.finished.connect(lambda: self._traffic_dns_workers.remove(worker)
                                if worker in self._traffic_dns_workers else None)
        worker.start()

    def _traffic_on_dns_resolved(self, ip, hostname):
        """Cache resolved hostname and update matching cells in the table."""
        self._traffic_dns_pending.discard(ip)
        self._traffic_dns_cache[ip] = hostname
        if hostname == ip:
            return   # no change to display
        tbl = self._traffic_table
        tbl.setUpdatesEnabled(False)
        for row in range(tbl.rowCount()):
            for col in (1, 2):
                item = tbl.item(row, col)
                if item and item.data(Qt.ItemDataRole.UserRole) == ip:
                    item.setText(hostname)
        tbl.setUpdatesEnabled(True)

    def create_filetransfer_page(self):
        """Create the File Transfer page (SSH/SMB/FTP/TFTP, Server/Client modes)"""
        PURPLE = '#9C27B0'

        def _toggle_style(color):
            return f"""
                QPushButton {{
                    background-color: #d8d8d8;
                    border: 1px solid #b0b0b0;
                    border-radius: 6px;
                    color: #444444;
                    font-size: 9pt;
                    padding: 3px 10px;
                }}
                QPushButton:checked {{
                    background-color: {color};
                    border-color: {color};
                    color: white;
                    font-weight: bold;
                }}
                QPushButton:hover:!checked {{
                    background-color: #c8c8c8;
                }}
            """

        _tree_style = """
            QTreeWidget {
                background-color: #f3e8fb;
                border: 1px solid #cba8e0;
                border-radius: 6px;
                color: #2a1a3a;
                font-size: 9pt;
            }
            QTreeWidget::item {
                padding: 3px 4px;
                background-color: transparent;
            }
            QTreeWidget::item:alternate {
                background-color: #e8d8f5;
            }
            QTreeWidget::item:selected {
                background-color: #7B1FA2;
                color: white;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #e0c8f0;
            }
            QHeaderView::section {
                background-color: #cba8e0;
                color: #2a1a3a;
                padding: 4px 6px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
            }
        """
        local_tree_style = _tree_style
        remote_tree_style = """
            QTreeWidget {
                background-color: #f0f0f0;
                border: 1px solid #c0c0c0;
                border-radius: 6px;
                color: #2a2a2a;
                font-size: 9pt;
            }
            QTreeWidget::item {
                padding: 3px 4px;
                background-color: transparent;
            }
            QTreeWidget::item:alternate {
                background-color: #e4e4e4;
            }
            QTreeWidget::item:selected {
                background-color: #757575;
                color: white;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #dcdcdc;
            }
            QHeaderView::section {
                background-color: #c8c8c8;
                color: #2a2a2a;
                padding: 4px 6px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
            }
        """

        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        # ── Transfer Options group ───────────────────────────────────────
        options_group = QGroupBox("Mode")
        options_layout = QVBoxLayout()
        options_layout.setContentsMargins(8, 6, 8, 8)
        options_layout.setSpacing(6)

        # Segmented Server | Client selector (same style as Speed Test / iPerf3)
        _mode_btn_style = f"""
            QPushButton {{
                background-color: #e8e8e8;
                border: none;
                color: #555555;
                font-size: 10pt;
                font-weight: bold;
                padding: 4px 24px;
                min-height: 32px;
                min-width: 110px;
            }}
            QPushButton:checked     {{ background-color: {PURPLE}; color: white; }}
            QPushButton:hover:!checked {{ background-color: #d8d8d8; }}
        """
        self._ft_mode_client_btn = QPushButton("Client")
        self._ft_mode_client_btn.setCheckable(True)
        self._ft_mode_client_btn.setChecked(True)
        self._ft_mode_client_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ft_mode_client_btn.setToolTip(
            "<b>Client mode</b><br>"
            "Cetus connects to a remote server and transfers files.<br>"
            "You initiate the upload or download to/from the target host."
        )
        self._ft_mode_client_btn.setStyleSheet(
            _mode_btn_style + "QPushButton { border-radius: 5px 0px 0px 5px; }"
        )
        _ft_client_ico_path = self.get_icon_path('speed_client.svg')
        _ft_client_ico = load_svg_icon_dual(_ft_client_ico_path, 18, '#555555', '#ffffff') if _ft_client_ico_path else None
        if _ft_client_ico:
            self._ft_mode_client_btn.setIcon(_ft_client_ico)
            self._ft_mode_client_btn.setIconSize(QSize(18, 18))

        self._ft_mode_server_btn = QPushButton("Server")
        self._ft_mode_server_btn.setCheckable(True)
        self._ft_mode_server_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ft_mode_server_btn.setToolTip(
            "<b>Server mode</b><br>"
            "Cetus starts a local server (TFTP/FTP/SCP/SMB) on this machine.<br>"
            "Remote devices can then connect and push or pull files."
        )
        self._ft_mode_server_btn.setStyleSheet(
            _mode_btn_style + "QPushButton { border-radius: 0px 5px 5px 0px; }"
        )
        _ft_server_ico_path = self.get_icon_path('speed_server.svg')
        _ft_server_ico = load_svg_icon_dual(_ft_server_ico_path, 18, '#555555', '#ffffff') if _ft_server_ico_path else None
        if _ft_server_ico:
            self._ft_mode_server_btn.setIcon(_ft_server_ico)
            self._ft_mode_server_btn.setIconSize(QSize(18, 18))
        _mode_sep = QFrame()
        _mode_sep.setFixedWidth(1)
        _mode_sep.setStyleSheet("background-color: #b0b0b0; border: none;")
        _mode_wrap = QFrame()
        _mode_wrap.setStyleSheet(
            "QFrame { border: 1px solid #b0b0b0; border-radius: 6px; background: transparent; }"
        )
        _mode_inner = QHBoxLayout(_mode_wrap)
        _mode_inner.setContentsMargins(0, 0, 0, 0)
        _mode_inner.setSpacing(0)
        _mode_inner.addWidget(self._ft_mode_client_btn)
        _mode_inner.addWidget(_mode_sep)
        _mode_inner.addWidget(self._ft_mode_server_btn)
        self._ft_mode_client_btn.clicked.connect(lambda: self._ft_mode_changed('Client'))
        self._ft_mode_server_btn.clicked.connect(lambda: self._ft_mode_changed('Server'))

        mode_sel_row = QHBoxLayout()
        mode_sel_row.addStretch()
        mode_sel_row.addWidget(_mode_wrap)
        mode_sel_row.addStretch()
        options_layout.addLayout(mode_sel_row)

        options_group.setLayout(options_layout)

        options_shadow = QGraphicsDropShadowEffect()
        options_shadow.setBlurRadius(15)
        options_shadow.setXOffset(0)
        options_shadow.setYOffset(2)
        options_shadow.setColor(QColor(0, 0, 0, 30))
        options_group.setGraphicsEffect(options_shadow)

        main_layout.addWidget(options_group)

        # ── Main stacked widget: Server panel (0) / Client panel (1) ───
        self._ft_stack = QStackedWidget()

        # ── SERVER PANEL ────────────────────────────────────────────────
        server_panel = QWidget()
        server_layout = QVBoxLayout()
        server_layout.setContentsMargins(0, 0, 0, 0)
        server_layout.setSpacing(6)

        # "Server" group wraps Protocol selector + per-protocol stack
        srv_group = QGroupBox("Server")
        srv_group_layout = QVBoxLayout()
        srv_group_layout.setContentsMargins(8, 6, 8, 8)
        srv_group_layout.setSpacing(6)

        srv_proto_row = QHBoxLayout()
        srv_proto_row.setSpacing(4)
        srv_proto_lbl = QLabel("Protocol:")
        srv_proto_lbl.setStyleSheet("font-size: 9pt; color: #333333;")
        srv_proto_row.addWidget(srv_proto_lbl)
        self._ft_proto_icons = {
            'SSH':  self.get_icon_path('ssh2.svg'),
            'SMB':  self.get_icon_path('smb.svg'),
            'FTP':  self.get_icon_path('ftp.svg'),
            'TFTP': self.get_icon_path('TFTP.svg'),
        }
        _proto_icons = self._ft_proto_icons
        self._ft_srv_proto_btns = {}
        for _proto in ('SSH', 'SMB', 'FTP', 'TFTP'):
            _pb = QPushButton(_proto)
            _pb.setCheckable(True)
            _pb.setFixedWidth(90)
            _pb.setFixedHeight(24)
            _pb.setCursor(Qt.CursorShape.PointingHandCursor)
            _pb.setStyleSheet(_toggle_style(PURPLE))
            _pb.clicked.connect(lambda _c, p=_proto: self._ft_proto_changed(p))
            if _proto_icons.get(_proto):
                _pb.setIcon(load_svg_icon_dual(_proto_icons[_proto], 14))
                _pb.setIconSize(QSize(14, 14))
            self._ft_srv_proto_btns[_proto] = _pb
            srv_proto_row.addWidget(_pb)
        self._ft_srv_proto_btns['SSH'].setChecked(True)
        srv_proto_row.addStretch()
        srv_group_layout.addLayout(srv_proto_row)

        # Inner stack per-protocol server UI
        self._ft_server_stack = QStackedWidget()

        # Index 0: TFTP server UI (existing widgets)
        tftp_server_widget = QWidget()
        tftp_server_vbox = QVBoxLayout()
        tftp_server_vbox.setContentsMargins(0, 0, 0, 0)
        tftp_server_vbox.setSpacing(6)

        combo_width = 200

        tftp_group = QGroupBox()
        tftp_layout = QFormLayout()
        tftp_layout.setVerticalSpacing(4)
        tftp_layout.setContentsMargins(8, 5, 8, 6)
        tftp_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tftp_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.tftp_interface = FlatComboButton()
        self.tftp_interface.setFixedWidth(combo_width)
        self.tftp_interface.setToolTip("Select network interface for TFTP server")
        self.tftp_interface.setStyleSheet("QComboBox { font-size: 8pt; }")
        tftp_layout.addRow("Interface:", self.tftp_interface)

        tftp_dir_layout = QHBoxLayout()
        tftp_dir_layout.setContentsMargins(0, 0, 0, 0)
        tftp_dir_layout.setSpacing(2)

        self.tftp_directory = QLineEdit()
        self.tftp_directory.setFixedWidth(combo_width)
        self.tftp_directory.setPlaceholderText("/path/to/directory")
        default_tftp_dir = os.environ.get('HOME', str(Path.home()))
        self.tftp_directory.setText(default_tftp_dir)
        self.tftp_directory.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tftp_directory.setToolTip("Directory containing firmware files")
        self.tftp_directory.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
        """)

        self.tftp_browse_btn = QPushButton()
        self.tftp_browse_btn.setFixedSize(28, 28)
        self.tftp_browse_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon))
        self.tftp_browse_btn.setToolTip("Browse for directory")
        self.tftp_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tftp_browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #bdbdbd;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
                border: 1px solid #9e9e9e;
            }
            QPushButton:pressed {
                background-color: #bdbdbd;
            }
        """)
        self.tftp_browse_btn.clicked.connect(self.browse_tftp_directory)

        tftp_dir_layout.addWidget(self.tftp_directory)
        tftp_dir_layout.addWidget(self.tftp_browse_btn)
        tftp_dir_layout.addStretch()

        tftp_dir_widget = QWidget()
        tftp_dir_widget.setContentsMargins(0, 0, 0, 0)
        tftp_dir_widget.setLayout(tftp_dir_layout)
        tftp_layout.addRow("Directory:", tftp_dir_widget)

        tftp_group.setLayout(tftp_layout)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 30))
        tftp_group.setGraphicsEffect(shadow)

        tftp_server_vbox.addWidget(tftp_group)

        # Initialize TFTP server instance
        self.tftp_server = None

        files_group = QGroupBox("Directory Contents")
        files_layout = QVBoxLayout()
        files_layout.setContentsMargins(10, 2, 10, 8)
        files_layout.setSpacing(6)

        self.tftp_files_table = QTableWidget()
        self.tftp_files_table.setColumnCount(3)
        self.tftp_files_table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        self.tftp_files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tftp_files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tftp_files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tftp_files_table.setColumnWidth(1, 80)
        self.tftp_files_table.setColumnWidth(2, 130)
        self.tftp_files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tftp_files_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tftp_files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tftp_files_table.verticalHeader().setVisible(False)
        self.tftp_files_table.setStyleSheet("""
            QTableWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
                gridline-color: #d0d0d0;
            }
            QTableWidget::item {
                padding: 4px;
                background-color: #e8e8e8;
            }
            QTableWidget::item:selected {
                background-color: #9C27B0;
                color: white;
            }
            QHeaderView::section {
                background-color: #d0d0d0;
                color: #333333;
                padding: 4px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
            }
        """)
        files_layout.addWidget(self.tftp_files_table)
        self._enable_table_tooltips(self.tftp_files_table)

        refresh_btn_layout = QHBoxLayout()
        refresh_btn_layout.addStretch()
        self.tftp_refresh_btn = QPushButton("Refresh")
        self.tftp_refresh_btn.setFixedWidth(90)
        self.tftp_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tftp_refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #78909c;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #607d8b;
            }
        """)
        self.tftp_refresh_btn.clicked.connect(self.refresh_tftp_files)
        refresh_btn_layout.addWidget(self.tftp_refresh_btn)
        refresh_btn_layout.addStretch()
        files_layout.addLayout(refresh_btn_layout)

        files_group.setLayout(files_layout)

        shadow2 = QGraphicsDropShadowEffect()
        shadow2.setBlurRadius(15)
        shadow2.setXOffset(0)
        shadow2.setYOffset(2)
        shadow2.setColor(QColor(0, 0, 0, 30))
        files_group.setGraphicsEffect(shadow2)

        tftp_server_vbox.addWidget(files_group, 1)
        tftp_server_widget.setLayout(tftp_server_vbox)
        self._ft_server_stack.addWidget(tftp_server_widget)   # index 0: TFTP

        # ── Index 1: FTP Server page ────────────────────────────────────
        ftp_srv_widget = QWidget()
        ftp_srv_vbox = QVBoxLayout()
        ftp_srv_vbox.setContentsMargins(0, 0, 0, 0)
        ftp_srv_vbox.setSpacing(6)

        ftp_srv_group = QGroupBox()
        ftp_srv_form = QFormLayout()
        ftp_srv_form.setVerticalSpacing(4)
        ftp_srv_form.setContentsMargins(8, 5, 8, 8)
        ftp_srv_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._ftp_srv_dir = QLineEdit(os.path.expanduser('~'))
        self._ftp_srv_dir.setFixedWidth(combo_width)
        self._ftp_srv_dir.setReadOnly(True)
        self._ftp_srv_dir.setStyleSheet("""
            QLineEdit { border:1px solid #d0d0d0; border-radius:6px; padding:2px 8px;
                        background:#f5f5f5; color:#333333; font-size:9pt; }""")
        ftp_browse_btn = QPushButton()
        ftp_browse_btn.setFixedSize(28, 28)
        ftp_browse_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon))
        ftp_browse_btn.setStyleSheet("""QPushButton{background:#e0e0e0;border:1px solid #bdbdbd;border-radius:6px;}
            QPushButton:hover{background:#d0d0d0;}""")
        ftp_browse_btn.clicked.connect(lambda: (
            d := QFileDialog.getExistingDirectory(self, "FTP Root Directory", self._ftp_srv_dir.text()),
            self._ftp_srv_dir.setText(d) if d else None
        ))
        ftp_dir_row = QHBoxLayout()
        ftp_dir_row.setContentsMargins(0, 0, 0, 0)
        ftp_dir_row.setSpacing(4)
        ftp_dir_row.addWidget(self._ftp_srv_dir)
        ftp_dir_row.addWidget(ftp_browse_btn)
        ftp_dir_row.addStretch()
        ftp_dir_w = QWidget(); ftp_dir_w.setContentsMargins(0,0,0,0); ftp_dir_w.setLayout(ftp_dir_row)
        self._ftp_srv_interface = FlatComboButton()
        self._ftp_srv_interface.setFixedWidth(combo_width)
        self._ftp_srv_interface.setToolTip("Select network interface for FTP server")
        self._ftp_srv_interface.setStyleSheet("QComboBox { font-size: 8pt; }")
        ftp_srv_form.addRow("Interface:", self._ftp_srv_interface)

        ftp_srv_form.addRow("Directory:", ftp_dir_w)

        self._ftp_srv_port = QLineEdit("21")
        self._ftp_srv_port.setFixedWidth(80)
        self._ftp_srv_port.setStyleSheet("""
            QLineEdit { border:1px solid #d0d0d0; border-radius:6px; padding:2px 8px;
                        background:#f5f5f5; color:#333333; font-size:9pt; }""")
        ftp_srv_form.addRow("Port:", self._ftp_srv_port)

        self._ftp_srv_user = QLineEdit("anonymous")
        self._ftp_srv_user.setFixedWidth(combo_width)
        self._ftp_srv_user.setStyleSheet("""
            QLineEdit { border:1px solid #d0d0d0; border-radius:6px; padding:2px 8px;
                        background:#f5f5f5; color:#333333; font-size:9pt; }""")
        ftp_srv_form.addRow("Username:", self._ftp_srv_user)

        self._ftp_srv_pass = QLineEdit()
        self._ftp_srv_pass.setFixedWidth(combo_width)
        self._ftp_srv_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._ftp_srv_pass.setPlaceholderText("Leave blank for anonymous")
        self._ftp_srv_pass.setStyleSheet("""
            QLineEdit { border:1px solid #d0d0d0; border-radius:6px; padding:2px 8px;
                        background:#f5f5f5; color:#333333; font-size:9pt; }""")
        ftp_srv_form.addRow("Password:", self._ftp_srv_pass)

        ftp_srv_group.setLayout(ftp_srv_form)
        ftp_shadow = QGraphicsDropShadowEffect()
        ftp_shadow.setBlurRadius(15); ftp_shadow.setXOffset(0); ftp_shadow.setYOffset(2)
        ftp_shadow.setColor(QColor(0, 0, 0, 30))
        ftp_srv_group.setGraphicsEffect(ftp_shadow)
        ftp_srv_vbox.addWidget(ftp_srv_group)

        try:
            import pyftpdlib  # noqa: F401
            ftp_note = QLabel("pyftpdlib \u2713 installed")
            ftp_note.setStyleSheet("font-size: 8pt; color: #4CAF50; padding: 2px 4px;")
        except ImportError:
            ftp_note = QLabel("Requires: <b>pyftpdlib</b>  —  <code>pip install pyftpdlib</code>")
            ftp_note.setStyleSheet("font-size: 8pt; color: #f44336; padding: 2px 4px;")
        ftp_srv_vbox.addWidget(ftp_note)
        ftp_srv_vbox.addStretch()
        ftp_srv_widget.setLayout(ftp_srv_vbox)
        self._ft_server_stack.addWidget(ftp_srv_widget)   # index 1: FTP

        # ── Index 2: SSH Server page ─────────────────────────────────────
        ssh_srv_widget = QWidget()
        ssh_srv_vbox = QVBoxLayout()
        ssh_srv_vbox.setContentsMargins(0, 0, 0, 0)
        ssh_srv_vbox.setSpacing(6)

        # SSH config group (Interface + Directory)
        ssh_cfg_group = QGroupBox()
        ssh_cfg_form = QFormLayout()
        ssh_cfg_form.setVerticalSpacing(4)
        ssh_cfg_form.setContentsMargins(8, 5, 8, 6)
        ssh_cfg_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ssh_cfg_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._ssh_srv_interface = FlatComboButton()
        self._ssh_srv_interface.setFixedWidth(combo_width)
        self._ssh_srv_interface.setToolTip("Select network interface for SSH/SFTP server")
        self._ssh_srv_interface.setStyleSheet("QComboBox { font-size: 8pt; }")
        ssh_cfg_form.addRow("Interface:", self._ssh_srv_interface)

        self._ssh_srv_dir = QLineEdit(os.path.expanduser('~'))
        self._ssh_srv_dir.setFixedWidth(combo_width)
        self._ssh_srv_dir.setReadOnly(True)
        self._ssh_srv_dir.setStyleSheet("""
            QLineEdit { border:1px solid #d0d0d0; border-radius:6px; padding:2px 8px;
                        background:#f5f5f5; color:#333333; font-size:9pt; }""")
        ssh_browse_btn = QPushButton()
        ssh_browse_btn.setFixedSize(28, 28)
        ssh_browse_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon))
        ssh_browse_btn.setStyleSheet("""QPushButton{background:#e0e0e0;border:1px solid #bdbdbd;border-radius:6px;}
            QPushButton:hover{background:#d0d0d0;}""")
        ssh_browse_btn.clicked.connect(lambda: (
            d := QFileDialog.getExistingDirectory(self, "SSH/SFTP Root Directory", self._ssh_srv_dir.text()),
            self._ssh_srv_dir.setText(d) if d else None
        ))
        ssh_dir_row = QHBoxLayout()
        ssh_dir_row.setContentsMargins(0, 0, 0, 0)
        ssh_dir_row.setSpacing(4)
        ssh_dir_row.addWidget(self._ssh_srv_dir)
        ssh_dir_row.addWidget(ssh_browse_btn)
        ssh_dir_row.addStretch()
        ssh_dir_w = QWidget(); ssh_dir_w.setContentsMargins(0, 0, 0, 0); ssh_dir_w.setLayout(ssh_dir_row)
        ssh_cfg_form.addRow("Directory:", ssh_dir_w)

        ssh_cfg_group.setLayout(ssh_cfg_form)
        ssh_cfg_shadow = QGraphicsDropShadowEffect()
        ssh_cfg_shadow.setBlurRadius(15); ssh_cfg_shadow.setXOffset(0); ssh_cfg_shadow.setYOffset(2)
        ssh_cfg_shadow.setColor(QColor(0, 0, 0, 30))
        ssh_cfg_group.setGraphicsEffect(ssh_cfg_shadow)
        ssh_srv_vbox.addWidget(ssh_cfg_group)

        ssh_srv_group = QGroupBox()
        ssh_srv_inner = QVBoxLayout()
        ssh_srv_inner.setContentsMargins(12, 10, 12, 12)
        ssh_srv_inner.setSpacing(8)

        ssh_info = QLabel(
            "<b>SSH Server (sshd) — File transfer via SFTP</b><br><br>"
            "The SSH server is managed by your system's OpenSSH service.<br>"
            "File transfers use the <b>SFTP</b> subsystem (SSH File Transfer Protocol).<br>"
            "Cetus can show its status and start/stop it via systemctl."
        )
        ssh_info.setWordWrap(True)
        ssh_info.setStyleSheet("font-size: 9pt; color: #333333;")
        ssh_srv_inner.addWidget(ssh_info)

        self._ssh_srv_status_lbl = QLabel("Status: unknown")
        self._ssh_srv_status_lbl.setStyleSheet("font-size: 9pt; color: #555555; padding: 4px 0;")
        ssh_srv_inner.addWidget(self._ssh_srv_status_lbl)

        ssh_btn_row = QHBoxLayout()
        ssh_check_btn = QPushButton("Check Status")
        ssh_check_btn.setFixedWidth(120)
        ssh_check_btn.setStyleSheet("""QPushButton{background:#78909c;color:white;border:none;
            border-radius:6px;padding:5px 10px;font-weight:bold;}
            QPushButton:hover{background:#607d8b;}""")
        ssh_check_btn.clicked.connect(self._ft_ssh_srv_check_status)
        ssh_btn_row.addWidget(ssh_check_btn)
        ssh_btn_row.addStretch()
        ssh_srv_inner.addLayout(ssh_btn_row)
        ssh_srv_inner.addStretch()
        ssh_srv_group.setLayout(ssh_srv_inner)

        ssh_shadow = QGraphicsDropShadowEffect()
        ssh_shadow.setBlurRadius(15); ssh_shadow.setXOffset(0); ssh_shadow.setYOffset(2)
        ssh_shadow.setColor(QColor(0, 0, 0, 30))
        ssh_srv_group.setGraphicsEffect(ssh_shadow)
        ssh_srv_vbox.addWidget(ssh_srv_group)
        ssh_srv_vbox.addStretch()
        ssh_srv_widget.setLayout(ssh_srv_vbox)
        self._ft_server_stack.addWidget(ssh_srv_widget)   # index 2: SSH

        # ── Index 3: SMB Server page ─────────────────────────────────────
        smb_srv_widget = QWidget()
        smb_srv_vbox = QVBoxLayout()
        smb_srv_vbox.setContentsMargins(0, 0, 0, 0)
        smb_srv_vbox.setSpacing(6)

        _smb_le = """QLineEdit { border:1px solid #d0d0d0; border-radius:6px; padding:2px 8px;
                                  background:#f5f5f5; color:#333333; font-size:9pt; }"""

        # ── Share config ──
        smb_cfg_group = QGroupBox("Share Configuration")
        smb_cfg_form = QFormLayout()
        smb_cfg_form.setVerticalSpacing(5)
        smb_cfg_form.setContentsMargins(10, 8, 10, 10)
        smb_cfg_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        smb_cfg_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._smb_srv_interface = FlatComboButton()
        self._smb_srv_interface.setFixedWidth(combo_width)
        self._smb_srv_interface.setStyleSheet("QComboBox { font-size: 8pt; }")
        smb_cfg_form.addRow("Interface:", self._smb_srv_interface)

        # Directory + browse
        self._smb_srv_dir = QLineEdit(os.path.expanduser('~'))
        self._smb_srv_dir.setFixedWidth(combo_width)
        self._smb_srv_dir.setReadOnly(True)
        self._smb_srv_dir.setStyleSheet(_smb_le)
        smb_browse_btn = QPushButton()
        smb_browse_btn.setFixedSize(28, 28)
        smb_browse_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon))
        smb_browse_btn.setStyleSheet("""QPushButton{background:#e0e0e0;border:1px solid #bdbdbd;border-radius:6px;}
            QPushButton:hover{background:#d0d0d0;}""")
        smb_browse_btn.clicked.connect(lambda: (
            d := QFileDialog.getExistingDirectory(self, "SMB Share Directory", self._smb_srv_dir.text()),
            self._smb_srv_dir.setText(d) if d else None
        ))
        smb_dir_row = QHBoxLayout()
        smb_dir_row.setContentsMargins(0, 0, 0, 0); smb_dir_row.setSpacing(4)
        smb_dir_row.addWidget(self._smb_srv_dir); smb_dir_row.addWidget(smb_browse_btn); smb_dir_row.addStretch()
        smb_dir_w = QWidget(); smb_dir_w.setContentsMargins(0,0,0,0); smb_dir_w.setLayout(smb_dir_row)
        smb_cfg_form.addRow("Directory:", smb_dir_w)

        self._smb_share_name = QLineEdit("cetus-share")
        self._smb_share_name.setFixedWidth(combo_width)
        self._smb_share_name.setStyleSheet(_smb_le)
        self._smb_share_name.setToolTip("Name visible on the network (no spaces)")
        smb_cfg_form.addRow("Share Name:", self._smb_share_name)

        self._smb_comment = QLineEdit("Cetus shared folder")
        self._smb_comment.setFixedWidth(combo_width)
        self._smb_comment.setStyleSheet(_smb_le)
        smb_cfg_form.addRow("Comment:", self._smb_comment)

        self._smb_workgroup = QLineEdit("WORKGROUP")
        self._smb_workgroup.setFixedWidth(120)
        self._smb_workgroup.setStyleSheet(_smb_le)
        self._smb_workgroup.setToolTip("Windows workgroup name (default: WORKGROUP)")
        smb_cfg_form.addRow("Workgroup:", self._smb_workgroup)

        self._smb_valid_users = QLineEdit()
        self._smb_valid_users.setFixedWidth(combo_width)
        self._smb_valid_users.setPlaceholderText("Leave blank to allow all users")
        self._smb_valid_users.setStyleSheet(_smb_le)
        self._smb_valid_users.setToolTip("Space-separated list of allowed users")
        smb_cfg_form.addRow("Valid Users:", self._smb_valid_users)

        _smb_chk_style = """
            QCheckBox { font-size: 9pt; color: #333333; background: transparent; }
            QCheckBox::indicator {
                width: 15px; height: 15px;
                border: 1px solid #b0b0b0;
                border-radius: 3px;
                background: #f5f5f5;
            }
            QCheckBox::indicator:checked {
                background: #9C27B0;
                border-color: #7B1FA2;
                image: none;
            }
            QCheckBox::indicator:hover { border-color: #9C27B0; }
        """
        smb_flags_row = QHBoxLayout()
        smb_flags_row.setContentsMargins(0, 0, 0, 0); smb_flags_row.setSpacing(18)
        self._smb_guest_ok = QCheckBox("Guest access")
        self._smb_guest_ok.setChecked(True)
        self._smb_guest_ok.setStyleSheet(_smb_chk_style)
        self._smb_read_only = QCheckBox("Read only")
        self._smb_read_only.setChecked(False)
        self._smb_read_only.setStyleSheet(_smb_chk_style)
        smb_flags_row.addWidget(self._smb_guest_ok)
        smb_flags_row.addWidget(self._smb_read_only)
        smb_flags_row.addStretch()
        smb_flags_w = QWidget(); smb_flags_w.setContentsMargins(0,0,0,0); smb_flags_w.setLayout(smb_flags_row)
        smb_cfg_form.addRow("Options:", smb_flags_w)

        smb_cfg_group.setLayout(smb_cfg_form)
        smb_cfg_shadow = QGraphicsDropShadowEffect()
        smb_cfg_shadow.setBlurRadius(15); smb_cfg_shadow.setXOffset(0); smb_cfg_shadow.setYOffset(2)
        smb_cfg_shadow.setColor(QColor(0, 0, 0, 30))
        smb_cfg_group.setGraphicsEffect(smb_cfg_shadow)
        smb_srv_vbox.addWidget(smb_cfg_group)

        # ── Status ──
        smb_srv_group = QGroupBox()
        smb_srv_inner = QVBoxLayout()
        smb_srv_inner.setContentsMargins(12, 8, 12, 10)
        smb_srv_inner.setSpacing(6)

        self._smb_srv_status_lbl = QLabel("Status: unknown")
        self._smb_srv_status_lbl.setStyleSheet("font-size: 9pt; color: #555555; padding: 2px 0;")
        smb_srv_inner.addWidget(self._smb_srv_status_lbl)

        smb_btn_row = QHBoxLayout()
        smb_check_btn = QPushButton("Check Status")
        smb_check_btn.setFixedWidth(120)
        smb_check_btn.setStyleSheet("""QPushButton{background:#78909c;color:white;border:none;
            border-radius:6px;padding:5px 10px;font-weight:bold;}
            QPushButton:hover{background:#607d8b;}""")
        smb_check_btn.clicked.connect(self._ft_smb_srv_check_status)
        smb_btn_row.addWidget(smb_check_btn)
        smb_btn_row.addStretch()
        smb_srv_inner.addLayout(smb_btn_row)
        smb_srv_group.setLayout(smb_srv_inner)

        smb_shadow = QGraphicsDropShadowEffect()
        smb_shadow.setBlurRadius(15); smb_shadow.setXOffset(0); smb_shadow.setYOffset(2)
        smb_shadow.setColor(QColor(0, 0, 0, 30))
        smb_srv_group.setGraphicsEffect(smb_shadow)
        smb_srv_vbox.addWidget(smb_srv_group)
        smb_srv_vbox.addStretch()
        smb_srv_widget.setLayout(smb_srv_vbox)
        self._ft_server_stack.addWidget(smb_srv_widget)   # index 3: SMB

        # Populate all interface combos now that all four have been created
        self.update_network_interfaces()

        srv_group_layout.addWidget(self._ft_server_stack, 1)
        srv_group.setLayout(srv_group_layout)

        srv_group_shadow = QGraphicsDropShadowEffect()
        srv_group_shadow.setBlurRadius(15)
        srv_group_shadow.setXOffset(0)
        srv_group_shadow.setYOffset(2)
        srv_group_shadow.setColor(QColor(0, 0, 0, 30))
        srv_group.setGraphicsEffect(srv_group_shadow)

        server_layout.addWidget(srv_group, 1)
        server_panel.setLayout(server_layout)

        # ── CLIENT PANEL ─────────────────────────────────────────────────
        client_panel = QWidget()
        client_layout = QVBoxLayout()
        client_layout.setContentsMargins(0, 0, 0, 0)
        client_layout.setSpacing(6)

        # Connection group
        conn_group = QGroupBox("Connection")
        conn_form = QFormLayout()
        conn_form.setVerticalSpacing(4)
        conn_form.setContentsMargins(8, 6, 8, 8)
        conn_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        field_style = """
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border: 1px solid #9C27B0;
            }
        """

        self._ft_host_input = QLineEdit()
        self._ft_host_input.setPlaceholderText("IP or hostname")
        self._ft_host_input.setFixedWidth(200)
        self._ft_host_input.setStyleSheet(field_style)

        self._ft_port_input = QLineEdit("69")
        self._ft_port_input.setFixedWidth(60)
        self._ft_port_input.setStyleSheet(field_style)

        _ft_quick_btn = QPushButton()
        _ft_quick_btn.setIcon(QIcon(self.get_arrow_icon_path()))
        _ft_quick_btn.setIconSize(QSize(16, 16))
        _ft_quick_btn.setFixedWidth(28)
        _ft_quick_btn.setFixedHeight(self._ft_host_input.sizeHint().height() or 24)
        _ft_quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ft_quick_btn.setToolTip("Load SSH profile")
        _ft_quick_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #e8e8e8; border: 1px solid #b0b0b0; }
            QPushButton:pressed { background-color: #d8d8d8; }
        """)

        def _ft_show_hosts_menu():
            menu = QMenu(_ft_quick_btn)
            menu.setStyleSheet("""
                QMenu { background-color: #ffffff; border: 1px solid #d0d0d0; }
                QMenu::item { padding: 4px 16px; color: #333333; font-size: 9pt; }
                QMenu::item:selected { background-color: #9C27B0; color: white; }
            """)
            ssh_profiles = self.config.get_ssh_profiles()
            if ssh_profiles:
                for profile in ssh_profiles:
                    name = profile.get('name', '')
                    host = profile.get('host', '')
                    port = str(profile.get('port', 22))
                    user = profile.get('username', '')
                    proto = profile.get('protocol', 'SSH')
                    raw_pw = profile.get('password', '')
                    try:
                        import base64 as _b64
                        password = _b64.b64decode(raw_pw.encode()).decode() if raw_pw else ''
                    except Exception:
                        password = raw_pw
                    if name and host:
                        action = menu.addAction(f"{name}  —  {host}")
                        action.setData((host, port, user, proto, password))
            else:
                no_action = menu.addAction("No SSH profiles saved")
                no_action.setEnabled(False)
            chosen = menu.exec(_ft_quick_btn.mapToGlobal(_ft_quick_btn.rect().bottomLeft()))
            if chosen and chosen.data():
                host, port, user, proto, password = chosen.data()
                self._ft_host_input.setText(host)
                self._ft_port_input.setText(port)
                if user:
                    self._ft_user_input.setText(user)
                if password:
                    self._ft_pass_input.setText(password)
                # Switch protocol toggle to match profile
                if proto in self._ft_cli_proto_btns:
                    self._ft_proto_changed(proto)

        _ft_quick_btn.clicked.connect(_ft_show_hosts_menu)

        # Protocol selector inside Connection group
        cli_proto_row = QHBoxLayout()
        cli_proto_row.setContentsMargins(0, 0, 0, 0)
        cli_proto_row.setSpacing(4)
        _proto_icons = self._ft_proto_icons
        self._ft_cli_proto_btns = {}
        for _proto in ('SSH', 'SMB', 'FTP', 'TFTP'):
            _pb = QPushButton(_proto)
            _pb.setCheckable(True)
            _pb.setFixedWidth(90)
            _pb.setFixedHeight(24)
            _pb.setCursor(Qt.CursorShape.PointingHandCursor)
            _pb.setStyleSheet(_toggle_style(PURPLE))
            _pb.clicked.connect(lambda _c, p=_proto: self._ft_proto_changed(p))
            if _proto_icons.get(_proto):
                _pb.setIcon(load_svg_icon_dual(_proto_icons[_proto], 14))
                _pb.setIconSize(QSize(14, 14))
            self._ft_cli_proto_btns[_proto] = _pb
            cli_proto_row.addWidget(_pb)
        self._ft_cli_proto_btns['SSH'].setChecked(True)
        cli_proto_row.addStretch()
        cli_proto_widget = QWidget()
        cli_proto_widget.setContentsMargins(0, 0, 0, 0)
        cli_proto_widget.setLayout(cli_proto_row)
        conn_form.addRow("Protocol:", cli_proto_widget)

        host_row = QHBoxLayout()
        host_row.setContentsMargins(0, 0, 0, 0)
        host_row.setSpacing(4)
        host_row.addWidget(self._ft_host_input)
        host_row.addWidget(_ft_quick_btn)
        host_row.addSpacing(8)
        host_row.addWidget(QLabel("Port:"))
        host_row.addWidget(self._ft_port_input)
        host_row.addStretch()
        host_widget = QWidget()
        host_widget.setContentsMargins(0, 0, 0, 0)
        host_widget.setLayout(host_row)
        conn_form.addRow("Host:", host_widget)

        self._ft_user_input = QLineEdit()
        self._ft_user_input.setFixedWidth(200)
        self._ft_user_input.setPlaceholderText("username")
        self._ft_user_input.setStyleSheet(field_style)
        conn_form.addRow("Username:", self._ft_user_input)

        self._ft_pass_input = QLineEdit()
        self._ft_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._ft_pass_input.setFixedWidth(200)
        self._ft_pass_input.setPlaceholderText("password")
        self._ft_pass_input.setStyleSheet(field_style)
        conn_form.addRow("Password:", self._ft_pass_input)

        conn_group.setLayout(conn_form)

        conn_shadow = QGraphicsDropShadowEffect()
        conn_shadow.setBlurRadius(15)
        conn_shadow.setXOffset(0)
        conn_shadow.setYOffset(2)
        conn_shadow.setColor(QColor(0, 0, 0, 30))
        conn_group.setGraphicsEffect(conn_shadow)

        client_layout.addWidget(conn_group)

        # File Browser group
        browser_group = QGroupBox("File Browser")
        browser_outer = QVBoxLayout()
        browser_outer.setContentsMargins(8, 6, 8, 8)
        browser_outer.setSpacing(4)

        browser_h = QHBoxLayout()
        browser_h.setSpacing(6)

        # LEFT: local tree
        local_col = QVBoxLayout()
        local_col.setSpacing(2)

        _local_top = QHBoxLayout()
        _local_top.setContentsMargins(0, 0, 0, 0)
        _local_top.setSpacing(4)
        local_header = QLabel("Local Computer")
        local_header.setStyleSheet("font-size: 9pt; font-weight: bold; color: #333333;")
        _local_top.addWidget(local_header)
        _local_top.addStretch()
        _nav_btn_style = """
            QPushButton {
                background: #f0f0f0; border: 1px solid #cccccc;
                border-radius: 4px; font-size: 11pt; color: #444444;
                padding: 0px 4px; min-width: 24px; min-height: 20px;
            }
            QPushButton:hover { background: #e0e0e0; border-color: #aaaaaa; }
            QPushButton:pressed { background: #d0d0d0; }
            QPushButton:disabled { color: #bbbbbb; border-color: #e0e0e0; }
        """
        self._ft_local_back_btn = QPushButton("‹")
        self._ft_local_back_btn.setToolTip("Back")
        self._ft_local_back_btn.setStyleSheet(_nav_btn_style)
        self._ft_local_back_btn.setEnabled(False)
        self._ft_local_back_btn.clicked.connect(self._ft_local_go_back)
        self._ft_local_fwd_btn = QPushButton("›")
        self._ft_local_fwd_btn.setToolTip("Forward")
        self._ft_local_fwd_btn.setStyleSheet(_nav_btn_style)
        self._ft_local_fwd_btn.setEnabled(False)
        self._ft_local_fwd_btn.clicked.connect(self._ft_local_go_forward)
        self._ft_local_home_btn = QPushButton("⌂")
        self._ft_local_home_btn.setToolTip("Home directory")
        self._ft_local_home_btn.setStyleSheet(_nav_btn_style)
        self._ft_local_home_btn.clicked.connect(lambda: self._ft_navigate_local(os.path.expanduser('~')))
        _local_top.addWidget(self._ft_local_back_btn)
        _local_top.addWidget(self._ft_local_fwd_btn)
        _local_top.addWidget(self._ft_local_home_btn)
        local_col.addLayout(_local_top)

        self._ft_local_path_label = QLabel(self._ft_local_path)
        self._ft_local_path_label.setStyleSheet("font-size: 8pt; color: #555555;")
        self._ft_local_path_label.setWordWrap(True)
        local_col.addWidget(self._ft_local_path_label)
        self._ft_local_tree = QTreeWidget()
        self._ft_local_tree.setColumnCount(3)
        self._ft_local_tree.setHeaderLabels(["Name", "Size", "Modified"])
        self._ft_local_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._ft_local_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._ft_local_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._ft_local_tree.setColumnWidth(1, 70)
        self._ft_local_tree.setColumnWidth(2, 110)
        self._ft_local_tree.setStyleSheet(local_tree_style)
        self._ft_local_tree.setAlternatingRowColors(True)
        self._ft_local_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._ft_local_tree.itemDoubleClicked.connect(self._ft_local_double_clicked)
        self._ft_local_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._ft_local_tree.customContextMenuRequested.connect(self._ft_local_context_menu)
        local_col.addWidget(self._ft_local_tree, 1)
        browser_h.addLayout(local_col, 1)

        # CENTER: arrow buttons
        arrow_col = QVBoxLayout()
        arrow_col.setSpacing(8)
        arrow_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        _arrow_btn_style = """
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11pt;
                font-weight: bold;
                padding: 0px 0px 0px 0px;
                text-align: center;
                qproperty-flat: false;
            }
            QPushButton:hover { background-color: #7B1FA2; }
            QPushButton:pressed { background-color: #4A148C; }
            QPushButton:disabled { background-color: #cccccc; color: #888888; }
        """
        self._ft_upload_btn = QPushButton("▶")
        self._ft_upload_btn.setToolTip("Upload to remote")
        self._ft_upload_btn.setFixedSize(36, 36)
        self._ft_upload_btn.setStyleSheet(_arrow_btn_style)
        self._ft_upload_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._ft_upload_btn.clicked.connect(self._ft_upload)
        self._ft_download_btn = QPushButton("◀")
        self._ft_download_btn.setToolTip("Download from remote")
        self._ft_download_btn.setFixedSize(36, 36)
        self._ft_download_btn.setStyleSheet(_arrow_btn_style)
        self._ft_download_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._ft_download_btn.clicked.connect(self._ft_download)
        arrow_col.addStretch()
        arrow_col.addWidget(self._ft_upload_btn)
        arrow_col.addWidget(self._ft_download_btn)
        arrow_col.addStretch()
        browser_h.addLayout(arrow_col)

        # RIGHT: remote tree
        remote_col = QVBoxLayout()
        remote_col.setSpacing(2)

        _remote_top = QHBoxLayout()
        _remote_top.setContentsMargins(0, 0, 0, 0)
        _remote_top.setSpacing(4)
        remote_header = QLabel("Remote Computer")
        remote_header.setStyleSheet("font-size: 9pt; font-weight: bold; color: #333333;")
        _remote_top.addWidget(remote_header)
        _remote_top.addStretch()
        self._ft_remote_back_btn = QPushButton("‹")
        self._ft_remote_back_btn.setToolTip("Back")
        self._ft_remote_back_btn.setStyleSheet(_nav_btn_style)
        self._ft_remote_back_btn.setEnabled(False)
        self._ft_remote_back_btn.clicked.connect(self._ft_remote_go_back)
        self._ft_remote_fwd_btn = QPushButton("›")
        self._ft_remote_fwd_btn.setToolTip("Forward")
        self._ft_remote_fwd_btn.setStyleSheet(_nav_btn_style)
        self._ft_remote_fwd_btn.setEnabled(False)
        self._ft_remote_fwd_btn.clicked.connect(self._ft_remote_go_forward)
        self._ft_remote_home_btn = QPushButton("⌂")
        self._ft_remote_home_btn.setToolTip("Home directory")
        self._ft_remote_home_btn.setStyleSheet(_nav_btn_style)
        self._ft_remote_home_btn.clicked.connect(self._ft_remote_go_home)
        _remote_top.addWidget(self._ft_remote_back_btn)
        _remote_top.addWidget(self._ft_remote_fwd_btn)
        _remote_top.addWidget(self._ft_remote_home_btn)
        remote_col.addLayout(_remote_top)

        self._ft_remote_path_label = QLabel("/")
        self._ft_remote_path_label.setStyleSheet("font-size: 8pt; color: #555555;")
        self._ft_remote_path_label.setWordWrap(True)
        remote_col.addWidget(self._ft_remote_path_label)
        self._ft_remote_tree = QTreeWidget()
        self._ft_remote_tree.setColumnCount(3)
        self._ft_remote_tree.setHeaderLabels(["Name", "Size", "Modified"])
        self._ft_remote_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._ft_remote_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._ft_remote_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._ft_remote_tree.setColumnWidth(1, 70)
        self._ft_remote_tree.setColumnWidth(2, 110)
        self._ft_remote_tree.setStyleSheet(remote_tree_style)
        self._ft_remote_tree.setAlternatingRowColors(True)
        self._ft_remote_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._ft_remote_tree.itemDoubleClicked.connect(self._ft_remote_double_clicked)
        self._ft_remote_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._ft_remote_tree.customContextMenuRequested.connect(self._ft_remote_context_menu)
        remote_col.addWidget(self._ft_remote_tree, 1)
        browser_h.addLayout(remote_col, 1)

        browser_outer.addLayout(browser_h, 1)

        # Status bar inside browser group
        self._ft_status_label = QLabel("Not connected")
        self._ft_status_label.setStyleSheet("color: #888888; font-size: 9pt;")
        browser_outer.addWidget(self._ft_status_label)

        self._ft_progress_bar = QProgressBar()
        self._ft_progress_bar.setRange(0, 100)
        self._ft_progress_bar.setValue(0)
        self._ft_progress_bar.setFixedHeight(14)
        self._ft_progress_bar.setVisible(False)
        self._ft_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #c0c0c0; border-radius: 6px;
                background: #f0f0f0; text-align: center; font-size: 8pt;
            }
            QProgressBar::chunk { background: #9C27B0; border-radius: 5px; }
        """)
        browser_outer.addWidget(self._ft_progress_bar)

        self._ft_progress_info = QLabel()
        self._ft_progress_info.setStyleSheet("color: #555555; font-size: 8pt;")
        self._ft_progress_info.setVisible(False)
        browser_outer.addWidget(self._ft_progress_info)

        browser_group.setLayout(browser_outer)

        browser_shadow = QGraphicsDropShadowEffect()
        browser_shadow.setBlurRadius(15)
        browser_shadow.setXOffset(0)
        browser_shadow.setYOffset(2)
        browser_shadow.setColor(QColor(0, 0, 0, 30))
        browser_group.setGraphicsEffect(browser_shadow)

        client_layout.addWidget(browser_group, 1)
        client_panel.setLayout(client_layout)

        # Add panels to main stack
        self._ft_stack.addWidget(server_panel)   # index 0: Server
        self._ft_stack.addWidget(client_panel)   # index 1: Client
        self._ft_stack.setCurrentIndex(1)        # Client is default

        main_layout.addWidget(self._ft_stack, 1)

        # ── Collapsible log ─────────────────────────────────────────────
        self._ft_log_toggle_btn = QPushButton("▶  Log")
        self._ft_log_toggle_btn.setCheckable(True)
        self._ft_log_toggle_btn.setChecked(False)
        self._ft_log_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ft_log_toggle_btn.setToolTip("Click to expand / collapse the log")
        self._ft_log_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #252535;
                border: 1px solid #333345;
                border-radius: 6px;
                color: #78909C;
                font-size: 8pt;
                font-weight: bold;
                padding: 4px 10px;
                text-align: left;
            }
            QPushButton:checked {
                background-color: #1a2030;
                border-color: #7B1FA2;
                color: #ce93d8;
                border-radius: 4px 4px 0px 0px;
            }
            QPushButton:hover { border-color: #9C27B0; color: #ce93d8; }
        """)
        self._ft_log = QPlainTextEdit()
        self._ft_log.setReadOnly(True)
        self._ft_log.setMaximumBlockCount(2000)
        self._ft_log.setFixedHeight(110)
        self._ft_log.setFont(QFont("Monospace", 8))
        self._ft_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1a1a2e;
                color: #c8c8c8;
                border: 1px solid #7B1FA2;
                border-top: none;
                border-radius: 0px 0px 4px 4px;
            }
        """)
        self._ft_log.setVisible(False)

        def _ft_toggle_log():
            open_ = self._ft_log_toggle_btn.isChecked()
            self._ft_log.setVisible(open_)
            self._ft_log_toggle_btn.setText("▼  Log" if open_ else "▶  Log")

        self._ft_log_toggle_btn.clicked.connect(_ft_toggle_log)
        main_layout.addWidget(self._ft_log_toggle_btn)
        main_layout.addWidget(self._ft_log)

        # ── Action button (full-width at bottom) ────────────────────────
        self.tftp_btn = QPushButton("START TFTP")
        self.tftp_btn.setMinimumHeight(45)
        self.tftp_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.tftp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tftp_btn.clicked.connect(self._ft_action_btn_clicked)
        self.tftp_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
            QPushButton:pressed {
                background-color: #4A148C;
            }
        """)
        _ft_conn_ico = load_svg_icon_dual(self._ft_proto_icons.get(self._ft_protocol), 18, '#ffffff', '#ffffff')
        if _ft_conn_ico:
            self.tftp_btn.setIcon(_ft_conn_ico)
            self.tftp_btn.setIconSize(QSize(18, 18))
            self.tftp_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.tftp_btn.setGraphicsEffect(_btn_shadow)
        main_layout.addWidget(self.tftp_btn)

        # ── Status/duration timer ────────────────────────────────────────
        self._ft_status_timer = QTimer(self)
        self._ft_status_timer.timeout.connect(self._ft_update_duration)

        page.setLayout(main_layout)

        # Set default protocol
        self._ft_proto_changed('SSH')

        # Load initial local file list and TFTP file list
        self._ft_refresh_local()
        self.refresh_tftp_files()

        return page

    def create_ipscan_page(self):
        """Create the IP Scanner page for network host discovery"""
        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        combo_width = 200

        # === Scan Configuration Group ===
        scan_group = QGroupBox("Scan Configuration")
        scan_layout = QFormLayout()
        scan_layout.setVerticalSpacing(4)
        scan_layout.setContentsMargins(8, 5, 8, 6)
        scan_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scan_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Network input: IP address + subnet mask combo
        net_input_layout = QHBoxLayout()
        net_input_layout.setContentsMargins(0, 0, 0, 0)
        net_input_layout.setSpacing(6)

        self.scan_network_input = QLineEdit()
        self.scan_network_input.setFixedWidth(186)
        self.scan_network_input.setFixedHeight(35)
        self.scan_network_input.setPlaceholderText("192.168.1.0")
        self.scan_network_input.setToolTip("Network or host IP address")
        self.scan_network_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border: 2px solid #ef5350;
            }
        """)

        _cidr_to_decimal = {
            "8": "/8  (255.0.0.0)", "16": "/16  (255.255.0.0)",
            "20": "/20  (255.255.240.0)", "21": "/21  (255.255.248.0)",
            "22": "/22  (255.255.252.0)", "23": "/23  (255.255.254.0)",
            "24": "/24  (255.255.255.0)", "25": "/25  (255.255.255.128)",
            "26": "/26  (255.255.255.192)", "27": "/27  (255.255.255.224)",
            "28": "/28  (255.255.255.240)", "29": "/29  (255.255.255.248)",
            "30": "/30  (255.255.255.252)", "32": "/32  (255.255.255.255)",
        }

        self.scan_mask_combo = FlatComboButton()
        self.scan_mask_combo.addItems(["8", "16", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "32"])
        self.scan_mask_combo.setCurrentText("24")
        self.scan_mask_combo.setFixedWidth(186)
        self.scan_mask_combo.setToolTip("Subnet mask (CIDR prefix length)")
        self.scan_mask_combo._display_func = lambda v: _cidr_to_decimal.get(v, f"/{v}")
        self.scan_mask_combo._refresh_display()

        self.scan_dns_checkbox = QCheckBox("DNS Lookup")
        self.scan_dns_checkbox.setToolTip("Resolve hostnames via reverse DNS (slower)")
        self.scan_dns_checkbox.setChecked(False)
        self.scan_dns_checkbox.setStyleSheet("""
            QCheckBox {
                color: #333333;
                font-size: 9pt;
                spacing: 4px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                background-color: #f5f5f5;
            }
            QCheckBox::indicator:checked {
                background-color: #ef5350;
                border-color: #ef5350;
            }
            QCheckBox::indicator:hover {
                border-color: #ef5350;
            }
        """)

        net_input_layout.addWidget(self.scan_network_input)
        net_input_layout.addWidget(self.scan_mask_combo)
        net_input_layout.addSpacing(10)
        net_input_layout.addWidget(self.scan_dns_checkbox)
        net_widget = QWidget()
        net_widget.setContentsMargins(0, 0, 0, 0)
        net_widget.setLayout(net_input_layout)

        # Auto-detect network on startup
        self._scan_auto_detect_network()

        # Method selector - toggle buttons
        method_widget = QWidget()
        method_layout = QHBoxLayout()
        method_layout.setContentsMargins(0, 0, 0, 0)
        method_layout.setSpacing(6)

        method_btn_style = """
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 12px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:checked {
                background-color: #ef5350;
                color: #ffffff;
                border: 1px solid #ef5350;
                font-weight: bold;
            }
        """

        def _proto_icon(name, color_on='#ffffff'):
            p = self.get_icon_path(f'proto_{name.lower()}.svg')
            return load_svg_icon_dual(p, 16, '#555555', color_on) if p else None

        _scan_color_on = '#ef5350'
        for _proto, _attr, _checked, _cb in [
            ('ARP',  'scan_method_arp_btn',  False, lambda: self._scan_method_btn_clicked("ARP")),
            ('ICMP', 'scan_method_icmp_btn', True,  lambda: self._scan_method_btn_clicked("ICMP")),
            ('TCP',  'scan_method_tcp_btn',  False, lambda: self._scan_method_btn_clicked("TCP")),
            ('UDP',  'scan_method_udp_btn',  False, lambda: self._scan_method_btn_clicked("UDP")),
        ]:
            _b = QPushButton(_proto)
            _b.setCheckable(True)
            _b.setChecked(_checked)
            _b.setFixedWidth(90)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(method_btn_style)
            _ico = _proto_icon(_proto, '#ffffff')
            if _ico:
                _b.setIcon(_ico)
                _b.setIconSize(QSize(16, 16))
            _b.clicked.connect(_cb)
            setattr(self, _attr, _b)

        method_layout.addWidget(self.scan_method_arp_btn)
        method_layout.addWidget(self.scan_method_icmp_btn)
        method_layout.addWidget(self.scan_method_tcp_btn)
        method_layout.addWidget(self.scan_method_udp_btn)
        method_layout.addStretch()
        method_widget.setLayout(method_layout)
        scan_layout.addRow("Method:", method_widget)
        scan_layout.addRow("Network:", net_widget)

        # Store method buttons for easy access
        self.scan_method_buttons = {
            'ICMP': self.scan_method_icmp_btn,
            'TCP': self.scan_method_tcp_btn,
            'UDP': self.scan_method_udp_btn,
            'ARP': self.scan_method_arp_btn
        }
        self.scan_current_method = "ICMP"
        self._scan_method_icons = {m: self.get_icon_path(f'proto_{m.lower()}.svg') for m in ('ARP', 'ICMP', 'TCP', 'UDP')}

        # Ports input (hidden for ICMP) with quick presets button
        self.scan_ports_label = QLabel("Ports:")
        self.scan_ports_input = QLineEdit()
        self.scan_ports_input.setPlaceholderText("22,80,443 or 1-1024")
        self.scan_ports_input.setToolTip("Comma-separated ports or range (e.g. 22,80,443 or 1-1024)")
        self.scan_ports_input.setText("22,23,80,139,443,445,3389")
        self.scan_ports_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border: 2px solid #ef5350;
            }
        """)

        # Common ports quick preset button
        _common_ports = [
            ("Default Ports", "22,23,80,139,443,445,3389"),
            ("---", None),
            ("SSH (22)", "22"),
            ("Telnet (23)", "23"),
            ("FTP (20-21)", "20,21"),
            ("HTTP (80)", "80"),
            ("HTTPS (443)", "443"),
            ("DNS (53)", "53"),
            ("SMTP (25)", "25"),
            ("POP3 (110)", "110"),
            ("IMAP (143)", "143"),
            ("SNMP (161)", "161"),
            ("SMB (139,445)", "139,445"),
            ("RDP (3389)", "3389"),
            ("VNC (5900)", "5900"),
            ("MySQL (3306)", "3306"),
            ("PostgreSQL (5432)", "5432"),
            ("MongoDB (27017)", "27017"),
            ("---", None),
            ("Common Web Ports", "80,443,8080,8443"),
            ("Common Mail Ports", "25,110,143,587,993,995"),
            ("Common Database Ports", "1433,3306,5432,27017"),
            ("Top 100 Ports", "1-100"),
            ("Top 1000 Ports", "1-1000"),
        ]

        _ports_quick_btn = QPushButton()
        _ports_quick_btn.setIcon(QIcon(self.get_arrow_icon_path()))
        _ports_quick_btn.setIconSize(QSize(16, 16))
        _ports_quick_btn.setFixedWidth(28)
        _ports_quick_btn.setFixedHeight(self.scan_ports_input.sizeHint().height() or 24)
        _ports_quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _ports_quick_btn.setToolTip("Common ports presets")
        _ports_quick_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
                border: 1px solid #b0b0b0;
            }
            QPushButton:pressed {
                background-color: #d8d8d8;
            }
        """)

        def _show_ports_menu():
            menu = QMenu(_ports_quick_btn)
            for label, ports in _common_ports:
                if ports is None:
                    menu.addSeparator()
                else:
                    action = menu.addAction(label)
                    action.setData(ports)
            chosen = menu.exec(
                _ports_quick_btn.mapToGlobal(_ports_quick_btn.rect().bottomLeft())
            )
            if chosen and chosen.data():
                new_ports = chosen.data()
                if chosen.text() == "Default Ports":
                    self.scan_ports_input.setText(new_ports)
                else:
                    current_text = self.scan_ports_input.text().strip()
                    if current_text:
                        # Add to existing ports if not already present
                        existing_ports = set(current_text.split(','))
                        new_ports_list = new_ports.split(',')
                        for port in new_ports_list:
                            if port not in existing_ports:
                                current_text += ',' + port
                        self.scan_ports_input.setText(current_text)
                    else:
                        self.scan_ports_input.setText(new_ports)

        _ports_quick_btn.clicked.connect(_show_ports_menu)

        _ports_widget = QWidget()
        _ports_widget.setFixedWidth(4 * 90 + 3 * 6)  # align right edge with UDP button
        _ports_layout = QHBoxLayout(_ports_widget)
        _ports_layout.setContentsMargins(0, 0, 0, 0)
        _ports_layout.setSpacing(4)
        _ports_layout.addWidget(self.scan_ports_input)
        _ports_layout.addWidget(_ports_quick_btn)

        self.scan_ports_label.setVisible(False)
        _ports_widget.setVisible(False)
        self._ports_widget = _ports_widget  # Store reference for visibility control
        scan_layout.addRow(self.scan_ports_label, _ports_widget)

        # Timeout and DNS option in a row
        options_layout = QHBoxLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(15)

        timeout_label = QLabel("Timeout:")
        self.scan_timeout_combo = FlatComboButton()
        self.scan_timeout_combo.addItems(["1s", "2s", "3s", "5s"])
        self.scan_timeout_combo.setCurrentIndex(3)
        self.scan_timeout_combo.setFixedWidth(80)

        options_layout.addWidget(timeout_label)
        options_layout.addWidget(self.scan_timeout_combo)
        options_layout.addStretch()

        options_widget = QWidget()
        options_widget.setContentsMargins(0, 0, 0, 0)
        options_widget.setLayout(options_layout)
        scan_layout.addRow(options_widget)

        scan_group.setLayout(scan_layout)
        scan_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 30))
        scan_group.setGraphicsEffect(shadow)

        main_layout.addWidget(scan_group)

        # === Results Group ===
        self.scan_results_group = QGroupBox("Results")
        results_layout = QVBoxLayout()
        results_layout.setContentsMargins(10, 2, 10, 8)
        results_layout.setSpacing(6)

        self.scan_results_table = QTableWidget()
        self.scan_results_table.setColumnCount(6)
        self.scan_results_table.setHorizontalHeaderLabels(["", "IP Address", "Status", "Latency (ms)", "Hostname", "MAC Vendor"])
        self.scan_results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.scan_results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.scan_results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.scan_results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.scan_results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.scan_results_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.scan_results_table.setColumnWidth(0, 36)
        self.scan_results_table.setColumnWidth(3, 100)
        self.scan_results_table.setColumnHidden(4, True)
        self.scan_results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.scan_results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.scan_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.scan_results_table.verticalHeader().setVisible(False)
        self.scan_results_table.verticalHeader().setDefaultSectionSize(30)
        self.scan_results_table.setIconSize(QSize(26, 26))
        self.scan_results_table.setSortingEnabled(True)
        self.scan_results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.scan_results_table.customContextMenuRequested.connect(self._scan_context_menu)
        self.scan_results_table.setStyleSheet("""
            QTableWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
                gridline-color: #d0d0d0;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #ef5350;
                color: white;
            }
            QHeaderView::section {
                background-color: #d0d0d0;
                color: #333333;
                padding: 4px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
            }
        """)
        results_layout.addWidget(self.scan_results_table)
        self._enable_table_tooltips(self.scan_results_table)

        # Occupancy bar (replaces the old Export CSV / Clear buttons —
        # those actions moved to the right-click context menu on the table)
        actions_layout = QHBoxLayout()
        actions_layout.addStretch()

        # Network occupancy bar
        self.scan_occupancy_bar = QProgressBar()
        self.scan_occupancy_bar.setFixedWidth(200)
        self.scan_occupancy_bar.setFixedHeight(20)
        self.scan_occupancy_bar.setRange(0, 100)
        self.scan_occupancy_bar.setValue(0)
        self.scan_occupancy_bar.setTextVisible(True)
        self.scan_occupancy_bar.setFormat("Occupancy: 0% (0 / 0)")
        self.scan_occupancy_bar.setStyleSheet("""
            QProgressBar {
                background-color: #e0e0e0;
                border: 1px solid #b0b0b0;
                border-radius: 6px;
                text-align: center;
                font-size: 9pt;
                color: #333333;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 6px;
            }
        """)
        actions_layout.addWidget(self.scan_occupancy_bar)

        actions_layout.addStretch()
        results_layout.addLayout(actions_layout)

        self.scan_results_group.setLayout(results_layout)
        self.scan_results_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        shadow2 = QGraphicsDropShadowEffect()
        shadow2.setBlurRadius(15)
        shadow2.setXOffset(0)
        shadow2.setYOffset(2)
        shadow2.setColor(QColor(0, 0, 0, 30))
        self.scan_results_group.setGraphicsEffect(shadow2)

        main_layout.addWidget(self.scan_results_group, 1)

        # Initialize scanner state
        self.scan_worker = None

        # === SCAN Button (full-width at bottom) ===
        self.scan_btn = QPushButton("SCAN")
        self.scan_btn.setMinimumHeight(45)
        self.scan_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef5350;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        self.scan_btn.clicked.connect(self._start_scan)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.scan_btn.setGraphicsEffect(_btn_shadow)
        _scan_ico = load_svg_icon_dual(self._scan_method_icons.get('ICMP'), 18, '#ffffff', '#ffffff')
        if _scan_ico:
            self.scan_btn.setIcon(_scan_ico)
            self.scan_btn.setIconSize(QSize(18, 18))
            self.scan_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        main_layout.addWidget(self.scan_btn)

        page.setLayout(main_layout)

        # Initialize field visibility based on default method
        self._scan_method_changed(self.scan_current_method)

        return page

    def create_snmp_page(self):
        """Create the SNMP query page"""
        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        # Image state
        self._snmp_img_worker         = None
        self._snmp_device_pixmap_full = None

        # Connection group
        conn_group = QGroupBox("SNMP Connection")
        conn_layout = QFormLayout()
        conn_layout.setVerticalSpacing(4)
        conn_layout.setContentsMargins(8, 5, 8, 6)
        conn_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        conn_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        conn_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        snmp_line_edit_style = """
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border: 2px solid #FF9800;
            }
        """

        self.snmp_host_input = QLineEdit()
        self.snmp_host_input.setPlaceholderText("192.168.1.1")
        self.snmp_host_input.setStyleSheet(snmp_line_edit_style)

        _snmp_tool_btn_style = """
            QToolButton {
                border: 1px solid #cccccc; border-radius: 3px;
                background-color: #f5f5f5; color: #444444;
                font-size: 9pt; padding: 0px 4px;
            }
            QToolButton:hover { background-color: #e0e0e0; }
            QToolButton:pressed { background-color: #cccccc; }
        """

        self.snmp_ip_profiles_btn = QToolButton()
        self.snmp_ip_profiles_btn.setText("▾")
        self.snmp_ip_profiles_btn.setFixedSize(22, 22)
        self.snmp_ip_profiles_btn.setToolTip("Select from SSH profiles")
        self.snmp_ip_profiles_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_ip_profiles_btn.setStyleSheet(_snmp_tool_btn_style)
        self.snmp_ip_profiles_btn.clicked.connect(self._snmp_show_ip_menu)

        snmp_host_widget = QWidget()
        snmp_host_layout = QHBoxLayout()
        snmp_host_layout.setContentsMargins(0, 0, 0, 0)
        snmp_host_layout.setSpacing(4)
        snmp_host_layout.addWidget(self.snmp_host_input)
        snmp_host_layout.addWidget(self.snmp_ip_profiles_btn)
        snmp_host_widget.setLayout(snmp_host_layout)
        conn_layout.addRow("Host:", snmp_host_widget)

        # Community + Version inline
        community_version_widget = QWidget()
        community_version_layout = QHBoxLayout()
        community_version_layout.setContentsMargins(0, 0, 0, 0)
        community_version_layout.setSpacing(6)

        self.snmp_community_input = QLineEdit()
        self.snmp_community_input.setText("public")
        self.snmp_community_input.setStyleSheet(snmp_line_edit_style)

        self.snmp_community_hist_btn = QToolButton()
        self.snmp_community_hist_btn.setText("▾")
        self.snmp_community_hist_btn.setFixedSize(22, 22)
        self.snmp_community_hist_btn.setToolTip("Community history")
        self.snmp_community_hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_community_hist_btn.setStyleSheet(_snmp_tool_btn_style)
        self.snmp_community_hist_btn.clicked.connect(self._snmp_show_community_menu)

        community_version_layout.addWidget(self.snmp_community_input)
        community_version_layout.addWidget(self.snmp_community_hist_btn)
        community_version_widget.setLayout(community_version_layout)
        conn_layout.addRow("Community:", community_version_widget)

        # Version buttons (below Community)
        version_widget = QWidget()
        version_layout = QHBoxLayout()
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.setSpacing(6)

        version_btn_style = """
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 12px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:checked {
                background-color: #FF9800;
                color: #ffffff;
                border: 1px solid #FF9800;
                font-weight: bold;
            }
        """

        self.snmp_version_v2c_btn = QPushButton("v2c")
        self.snmp_version_v2c_btn.setCheckable(True)
        self.snmp_version_v2c_btn.setChecked(True)
        self.snmp_version_v2c_btn.setFixedWidth(90)
        self.snmp_version_v2c_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_version_v2c_btn.setStyleSheet(version_btn_style)
        self.snmp_version_v2c_btn.clicked.connect(lambda: self._snmp_version_btn_clicked("v2c"))

        self.snmp_version_v1_btn = QPushButton("v1")
        self.snmp_version_v1_btn.setCheckable(True)
        self.snmp_version_v1_btn.setFixedWidth(90)
        self.snmp_version_v1_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_version_v1_btn.setStyleSheet(version_btn_style)
        self.snmp_version_v1_btn.clicked.connect(lambda: self._snmp_version_btn_clicked("v1"))

        self.snmp_version_v3_btn = QPushButton("v3")
        self.snmp_version_v3_btn.setCheckable(True)
        self.snmp_version_v3_btn.setFixedWidth(90)
        self.snmp_version_v3_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_version_v3_btn.setStyleSheet(version_btn_style)
        self.snmp_version_v3_btn.clicked.connect(lambda: self._snmp_version_btn_clicked("v3"))

        version_layout.addWidget(self.snmp_version_v1_btn)
        version_layout.addWidget(self.snmp_version_v2c_btn)
        version_layout.addWidget(self.snmp_version_v3_btn)
        version_layout.addStretch()
        version_widget.setLayout(version_layout)
        conn_layout.addRow("Version:", version_widget)

        # Store version buttons for easy access
        self.snmp_version_buttons = {
            'v2c': self.snmp_version_v2c_btn,
            'v1': self.snmp_version_v1_btn,
            'v3': self.snmp_version_v3_btn
        }
        self.snmp_current_version = "v2c"

        # SNMPv3 fields (initially hidden)
        # Username
        self.snmp_v3_username_input = QLineEdit()
        self.snmp_v3_username_input.setPlaceholderText("username")
        self.snmp_v3_username_input.setStyleSheet(snmp_line_edit_style)
        self.snmp_v3_username_label = QLabel("Username:")
        conn_layout.addRow(self.snmp_v3_username_label, self.snmp_v3_username_input)

        # Auth Protocol + Auth Password
        v3_auth_widget = QWidget()
        v3_auth_layout = QHBoxLayout()
        v3_auth_layout.setContentsMargins(0, 0, 0, 0)
        v3_auth_layout.setSpacing(6)

        self.snmp_v3_auth_proto_combo = FlatComboButton()
        self.snmp_v3_auth_proto_combo.addItems(["None", "MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"])
        self.snmp_v3_auth_proto_combo.setFixedWidth(100)
        self.snmp_v3_auth_proto_combo.setToolTip("Authentication protocol")

        auth_pass_label = QLabel("password:")
        auth_pass_label.setStyleSheet("color: #888888; font-size: 9pt;")
        auth_pass_label.setFixedWidth(65)

        self.snmp_v3_auth_pass_input = QLineEdit()
        self.snmp_v3_auth_pass_input.setPlaceholderText("auth password")
        self.snmp_v3_auth_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.snmp_v3_auth_pass_input.setStyleSheet(snmp_line_edit_style)

        v3_auth_layout.addWidget(self.snmp_v3_auth_proto_combo)
        v3_auth_layout.addWidget(auth_pass_label)
        v3_auth_layout.addWidget(self.snmp_v3_auth_pass_input)
        v3_auth_layout.addStretch()
        v3_auth_widget.setLayout(v3_auth_layout)
        self.snmp_v3_auth_label = QLabel("Auth:")
        conn_layout.addRow(self.snmp_v3_auth_label, v3_auth_widget)

        # Privacy Protocol + Privacy Password
        v3_priv_widget = QWidget()
        v3_priv_layout = QHBoxLayout()
        v3_priv_layout.setContentsMargins(0, 0, 0, 0)
        v3_priv_layout.setSpacing(6)

        self.snmp_v3_priv_proto_combo = FlatComboButton()
        self.snmp_v3_priv_proto_combo.addItems(["None", "DES", "3DES", "AES", "AES192", "AES256"])
        self.snmp_v3_priv_proto_combo.setFixedWidth(100)
        self.snmp_v3_priv_proto_combo.setToolTip("Privacy protocol")

        priv_pass_label = QLabel("password:")
        priv_pass_label.setStyleSheet("color: #888888; font-size: 9pt;")
        priv_pass_label.setFixedWidth(65)

        self.snmp_v3_priv_pass_input = QLineEdit()
        self.snmp_v3_priv_pass_input.setPlaceholderText("priv password")
        self.snmp_v3_priv_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.snmp_v3_priv_pass_input.setStyleSheet(snmp_line_edit_style)

        v3_priv_layout.addWidget(self.snmp_v3_priv_proto_combo)
        v3_priv_layout.addWidget(priv_pass_label)
        v3_priv_layout.addWidget(self.snmp_v3_priv_pass_input)
        v3_priv_layout.addStretch()
        v3_priv_widget.setLayout(v3_priv_layout)
        self.snmp_v3_priv_label = QLabel("Privacy:")
        conn_layout.addRow(self.snmp_v3_priv_label, v3_priv_widget)

        # Initially hide v3 fields
        self.snmp_v3_username_label.setVisible(False)
        self.snmp_v3_username_input.setVisible(False)
        self.snmp_v3_auth_label.setVisible(False)
        v3_auth_widget.setVisible(False)
        self.snmp_v3_priv_label.setVisible(False)
        v3_priv_widget.setVisible(False)

        # Store v3 widgets for easy access
        self.snmp_v3_widgets = {
            'username_label': self.snmp_v3_username_label,
            'username_input': self.snmp_v3_username_input,
            'auth_label': self.snmp_v3_auth_label,
            'auth_widget': v3_auth_widget,
            'priv_label': self.snmp_v3_priv_label,
            'priv_widget': v3_priv_widget
        }

        # ── Device image (right side of conn_group) ──────────────────────
        _sep = QFrame()
        _sep.setFrameShape(QFrame.Shape.VLine)
        _sep.setFrameShadow(QFrame.Shadow.Sunken)
        _sep.setStyleSheet("color: #d0d0d0;")

        self.snmp_device_img = QLabel()
        self.snmp_device_img.setFixedSize(160, 80)
        self.snmp_device_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.snmp_device_img.setStyleSheet(
            "border: 1px solid #e0e0e0; border-radius: 6px; background: #fafafa;")
        self.snmp_device_img.setToolTip("Click to enlarge")
        self.snmp_device_img.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_device_img.installEventFilter(self)

        self.snmp_device_name_lbl = QLabel()
        self.snmp_device_name_lbl.setStyleSheet("color: #888888; font-size: 7.5pt;")
        self.snmp_device_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.snmp_device_name_lbl.setFixedWidth(160)

        _img_vbox = QVBoxLayout()
        _img_vbox.setSpacing(2)
        _img_vbox.setContentsMargins(6, 0, 4, 0)
        _img_vbox.addStretch()
        _img_vbox.addWidget(self.snmp_device_img, 0, Qt.AlignmentFlag.AlignCenter)
        _img_vbox.addWidget(self.snmp_device_name_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        _img_vbox.addStretch()
        _img_widget = QWidget()
        _img_widget.setLayout(_img_vbox)

        # Seed with default icon
        self._snmp_update_device_image('Default', '')

        # Wrap form + image in an outer HBox
        _form_widget = QWidget()
        _form_widget.setLayout(conn_layout)
        _conn_h = QHBoxLayout()
        _conn_h.setContentsMargins(0, 0, 0, 0)
        _conn_h.setSpacing(0)
        _conn_h.addWidget(_form_widget, 1)
        _conn_h.addWidget(_sep)
        _conn_h.addWidget(_img_widget)
        conn_group.setLayout(_conn_h)
        conn_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        conn_group.setGraphicsEffect(_shadow)
        main_layout.addWidget(conn_group)

        # Query group
        query_group = QGroupBox("Query Configuration")
        query_layout = QFormLayout()
        query_layout.setVerticalSpacing(4)
        query_layout.setContentsMargins(8, 5, 8, 6)
        query_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        query_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Type buttons
        type_widget = QWidget()
        type_layout = QHBoxLayout()
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(6)

        type_btn_style = """
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 12px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:checked {
                background-color: #FF9800;
                color: #ffffff;
                border: 1px solid #FF9800;
                font-weight: bold;
            }
        """

        for _label, _attr, _checked, _snmpcmd, _icokey in [
            ('WALK',    'snmp_type_walk_btn',    True,  'snmpwalk',    'snmp_walk'),
            ('GET',     'snmp_type_get_btn',     False, 'snmpget',     'snmp_get'),
            ('GETNEXT', 'snmp_type_getnext_btn', False, 'snmpgetnext', 'snmp_getnext'),
        ]:
            _b = QPushButton(_label)
            _b.setCheckable(True)
            _b.setChecked(_checked)
            _b.setFixedWidth(90)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(type_btn_style)
            _p = self.get_icon_path(f'{_icokey}.svg')
            _ico = load_svg_icon_dual(_p, 16, '#555555', '#ffffff') if _p else None
            if _ico:
                _b.setIcon(_ico)
                _b.setIconSize(QSize(16, 16))
            _b.clicked.connect(lambda _c, _cmd=_snmpcmd: self._snmp_type_btn_clicked(_cmd))
            setattr(self, _attr, _b)

        type_layout.addWidget(self.snmp_type_walk_btn)
        type_layout.addWidget(self.snmp_type_get_btn)
        type_layout.addWidget(self.snmp_type_getnext_btn)
        type_layout.addStretch()
        type_widget.setLayout(type_layout)
        query_layout.addRow("Type:", type_widget)

        # Store type buttons for easy access
        self.snmp_type_buttons = {
            'snmpwalk': self.snmp_type_walk_btn,
            'snmpget': self.snmp_type_get_btn,
            'snmpgetnext': self.snmp_type_getnext_btn
        }
        self.snmp_current_type = "snmpwalk"
        self._snmp_type_icons = {
            'snmpwalk':    self.get_icon_path('snmp_walk.svg'),
            'snmpget':     self.get_icon_path('snmp_get.svg'),
            'snmpgetnext': self.get_icon_path('snmp_getnext.svg'),
        }

        self.snmp_oid_input = QLineEdit()
        self.snmp_oid_input.setPlaceholderText(".1.3.6.1.2.1.1")
        self.snmp_oid_input.setStyleSheet(snmp_line_edit_style)
        query_layout.addRow("OID:", self.snmp_oid_input)

        query_group.setLayout(query_layout)
        query_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        query_group.setGraphicsEffect(_shadow)
        main_layout.addWidget(query_group)

        # Results
        self.snmp_results_group = QGroupBox("Results")
        results_layout = QVBoxLayout()
        results_layout.setContentsMargins(10, 2, 10, 8)
        results_layout.setSpacing(6)

        self.snmp_results_table = QTableWidget()
        self.snmp_results_table.setColumnCount(4)
        self.snmp_results_table.setHorizontalHeaderLabels(["Family Tree", "OID", "Value", "Type"])
        self.snmp_results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.snmp_results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.snmp_results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.snmp_results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.snmp_results_table.setColumnWidth(3, 95)
        self.snmp_results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.snmp_results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.snmp_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.snmp_results_table.verticalHeader().setVisible(False)
        self.snmp_results_table.setSortingEnabled(True)
        self.snmp_results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.snmp_results_table.customContextMenuRequested.connect(self._snmp_context_menu)
        self.snmp_results_table.setStyleSheet("""
            QTableWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
                gridline-color: #d0d0d0;
            }
            QTableWidget::item {
                padding: 2px;
            }
            QTableWidget::item:selected {
                background-color: #FF9800;
                color: white;
            }
            QHeaderView::section {
                background-color: #d0d0d0;
                color: #333333;
                padding: 2px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
            }
        """)
        # Index panel (right side) — "Index"
        index_panel = QWidget()
        index_panel.setFixedWidth(185)
        index_panel_layout = QVBoxLayout(index_panel)
        index_panel_layout.setContentsMargins(0, 0, 0, 0)
        index_panel_layout.setSpacing(4)

        family_tree_label = QLabel("Index")
        family_tree_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        family_tree_label.setFixedHeight(22)
        family_tree_label.setStyleSheet("""
            QLabel {
                background-color: #d0d0d0;
                color: #333333;
                font-weight: bold;
                font-size: 9pt;
                border-radius: 6px;
            }
        """)
        index_panel_layout.addWidget(family_tree_label)

        self.snmp_index_list = QListWidget()
        self.snmp_index_list.setSpacing(1)
        self.snmp_index_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_index_list.setToolTip("Click to navigate to the OID family")
        # No ::item rule — lets setItemWidget colors render without interference
        self.snmp_index_list.setStyleSheet("""
            QListWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                outline: none;
            }
        """)
        self.snmp_index_list.itemClicked.connect(self._snmp_index_item_clicked)
        index_panel_layout.addWidget(self.snmp_index_list)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.setSpacing(4)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_label = QLabel("Search:")
        search_label.setStyleSheet("color: #333333; font-size: 9pt;")
        search_label.setFixedWidth(48)
        self.snmp_search_input = QLineEdit()
        self.snmp_search_input.setPlaceholderText("Filter by OID or value...")
        self.snmp_search_input.setClearButtonEnabled(True)
        self.snmp_search_input.setFixedHeight(26)
        self.snmp_search_input.setStyleSheet("""
            QLineEdit {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 6px;
                color: #333333;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #FF9800;
            }
        """)
        self.snmp_search_input.textChanged.connect(self._snmp_filter_results)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.snmp_search_input)
        results_layout.addLayout(search_layout)

        table_index_layout = QHBoxLayout()
        table_index_layout.setSpacing(6)
        table_index_layout.setContentsMargins(0, 0, 0, 0)
        table_index_layout.addWidget(self.snmp_results_table, 1)
        table_index_layout.addWidget(index_panel)
        results_layout.addLayout(table_index_layout)
        self._enable_table_tooltips(self.snmp_results_table)
        self.snmp_results_group.setLayout(results_layout)
        self.snmp_results_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        self.snmp_results_group.setGraphicsEffect(_shadow)
        main_layout.addWidget(self.snmp_results_group, 1)

        # Execute button (full-width at bottom)
        self.snmp_execute_btn = QPushButton("SNMP WALK")
        self.snmp_execute_btn.setMinimumHeight(45)
        self.snmp_execute_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.snmp_execute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.snmp_execute_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)
        self.snmp_execute_btn.clicked.connect(self.execute_snmp_query)
        self.snmp_execute_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.snmp_execute_btn.setGraphicsEffect(_btn_shadow)
        _snmp_ico = load_svg_icon_dual(self._snmp_type_icons.get('snmpwalk'), 18, '#ffffff', '#ffffff')
        if _snmp_ico:
            self.snmp_execute_btn.setIcon(_snmp_ico)
            self.snmp_execute_btn.setIconSize(QSize(18, 18))
            self.snmp_execute_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        main_layout.addWidget(self.snmp_execute_btn)

        page.setLayout(main_layout)
        return page

    def create_traceroute_page(self):
        """Create the Traceroute page for route discovery and visualization"""
        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        combo_width = 200

        # === Traceroute Configuration Group ===
        config_group = QGroupBox("Traceroute Configuration")
        config_layout = QFormLayout()
        config_layout.setVerticalSpacing(4)
        config_layout.setContentsMargins(8, 5, 8, 6)
        config_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        config_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        traceroute_line_edit_style = """
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border: 2px solid #00BCD4;
            }
        """

        # Target input + quick-target button
        self.traceroute_target_input = QLineEdit()
        self.traceroute_target_input.setPlaceholderText("192.168.1.1 or example.com")
        self.traceroute_target_input.setToolTip("Target IP address or hostname")
        self.traceroute_target_input.setFont(QFont("Sans Serif", 9))
        self.traceroute_target_input.setStyleSheet(traceroute_line_edit_style)
        # Align right edge with the TCP method button:
        # ICMP(90) + gap(4) + TCP(90) = 184 px from the start of the field column.
        self.traceroute_target_input.setFixedWidth(184)

        _quick_targets = [
            ("Google DNS",          "8.8.8.8"),
            ("Google DNS Alt",      "8.8.4.4"),
            ("Cloudflare DNS",      "1.1.1.1"),
            ("Cloudflare DNS Alt",  "1.0.0.1"),
            ("Quad9 DNS",           "9.9.9.9"),
            ("OpenDNS",             "208.67.222.222"),
            ("Level3 DNS",          "4.2.2.2"),
            ("Comodo DNS",          "8.26.56.26"),
            ("AdGuard DNS",         "94.140.14.14"),
            ("CleanBrowsing DNS",   "185.228.168.9"),
            ("---",                 None),
            ("Google",              "www.google.com"),
            ("Facebook",            "www.facebook.com"),
            ("Amazon AWS",          "aws.amazon.com"),
            ("Cloudflare",          "www.cloudflare.com"),
            ("GitHub",              "github.com"),
        ]

        _quick_btn = QPushButton()
        _quick_btn.setIcon(QIcon(self.get_arrow_icon_path()))
        _quick_btn.setIconSize(QSize(16, 16))
        _quick_btn.setFixedWidth(28)
        _quick_btn.setFixedHeight(self.traceroute_target_input.sizeHint().height() or 24)
        _quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _quick_btn.setToolTip("Quick target presets")
        _quick_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
                border: 1px solid #b0b0b0;
            }
            QPushButton:pressed {
                background-color: #d8d8d8;
            }
        """)

        def _show_quick_menu():
            menu = QMenu(_quick_btn)

            # Add predefined quick targets
            for label, ip in _quick_targets:
                if ip is None:
                    menu.addSeparator()
                else:
                    action = menu.addAction(f"{label}  —  {ip}")
                    action.setData(ip)

            # Add SSH profiles from Quick Connect
            ssh_profiles = self.config.get_ssh_profiles()
            if ssh_profiles:
                menu.addSeparator()
                for profile in ssh_profiles:
                    name = profile.get('name', '')
                    host = profile.get('host', '')
                    if name and host:
                        action = menu.addAction(f"{name}  —  {host}")
                        action.setData(host)

            chosen = menu.exec(
                _quick_btn.mapToGlobal(_quick_btn.rect().bottomLeft())
            )
            if chosen and chosen.data():
                self.traceroute_target_input.setText(chosen.data())

        _quick_btn.clicked.connect(_show_quick_menu)

        # DNS Lookup checkbox
        self.traceroute_dns_checkbox = QCheckBox("DNS Lookup")
        self.traceroute_dns_checkbox.setToolTip("Resolve hostnames via reverse DNS")
        self.traceroute_dns_checkbox.setChecked(True)
        self.traceroute_dns_checkbox.setStyleSheet("""
            QCheckBox {
                color: #333333;
                font-size: 9pt;
                spacing: 4px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                background-color: #f5f5f5;
            }
            QCheckBox::indicator:checked {
                background-color: #00BCD4;
                border-color: #00BCD4;
            }
            QCheckBox::indicator:hover {
                border-color: #00BCD4;
            }
        """)

        _target_widget = QWidget()
        _target_layout = QHBoxLayout(_target_widget)
        _target_layout.setContentsMargins(0, 0, 0, 0)
        _target_layout.setSpacing(8)
        # Auto-show graph checkbox — lives next to DNS Lookup
        self.traceroute_autograph_checkbox = QCheckBox("Auto-show graph")
        self.traceroute_autograph_checkbox.setChecked(True)
        self.traceroute_autograph_checkbox.setToolTip(
            "Automatically open the Latency Graph when traceroute starts and update it in real time"
        )
        self.traceroute_autograph_checkbox.setStyleSheet("""
            QCheckBox { color: #333333; font-size: 9pt; spacing: 5px; }
            QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid #d0d0d0; background: #f5f5f5; }
            QCheckBox::indicator:checked { background: #00BCD4; border-color: #00BCD4; }
            QCheckBox::indicator:hover { border-color: #00BCD4; }
        """)

        _target_layout.addWidget(self.traceroute_target_input)
        _target_layout.addWidget(_quick_btn)
        _target_layout.addWidget(self.traceroute_dns_checkbox)
        _target_layout.addWidget(self.traceroute_autograph_checkbox)
        _target_layout.addStretch()


        # Method selector (ICMP/TCP/UDP) — toggle buttons in tab cyan colour
        _tr_method_btn_style = """
            QPushButton {
                border: 1px solid #d0d0d0; border-radius: 6px;
                padding: 4px 12px; background-color: #f5f5f5;
                color: #333333; font-size: 9pt; font-weight: normal;
            }
            QPushButton:hover { background-color: #e8e8e8; }
            QPushButton:checked {
                background-color: #00BCD4; color: #ffffff;
                border: 1px solid #00BCD4; font-weight: bold;
            }
        """
        _tr_method_widget = QWidget()
        _tr_method_layout = QHBoxLayout(_tr_method_widget)
        _tr_method_layout.setContentsMargins(0, 0, 0, 0)
        _tr_method_layout.setSpacing(4)

        def _tr_proto_icon(name):
            p = self.get_icon_path(f'proto_{name}.svg')
            return load_svg_icon_dual(p, 16, '#555555', '#ffffff') if p else None

        for _proto, _attr, _checked, _icon_key in [
            ('ICMP',      'traceroute_method_icmp_btn',     True,  'icmp'),
            ('TCP',       'traceroute_method_tcp_btn',      False, 'tcp'),
            ('UDP',       'traceroute_method_udp_btn',      False, 'udp'),
            ('Ping ICMP', 'traceroute_method_pingicmp_btn', False, 'icmp'),
            ('Ping TCP',  'traceroute_method_pingtcp_btn',  False, 'tcp'),
        ]:
            _b = QPushButton(_proto)
            _b.setCheckable(True)
            _b.setChecked(_checked)
            _b.setFixedWidth(90)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(_tr_method_btn_style)
            _ico = _tr_proto_icon(_icon_key)
            if _ico:
                _b.setIcon(_ico)
                _b.setIconSize(QSize(16, 16))
            setattr(self, _attr, _b)

        self._traceroute_method_btns = {
            'ICMP': self.traceroute_method_icmp_btn,
            'TCP':        self.traceroute_method_tcp_btn,
            'UDP':        self.traceroute_method_udp_btn,
            'Ping ICMP':  self.traceroute_method_pingicmp_btn,
            'Ping TCP':   self.traceroute_method_pingtcp_btn,
        }
        self.traceroute_current_method = 'ICMP'
        self._traceroute_method_icons = {
            'ICMP':      self.get_icon_path('proto_icmp.svg'),
            'TCP':       self.get_icon_path('proto_tcp.svg'),
            'UDP':       self.get_icon_path('proto_udp.svg'),
            'Ping ICMP': self.get_icon_path('proto_icmp.svg'),
            'Ping TCP':  self.get_icon_path('proto_tcp.svg'),
        }

        def _tr_method_btn_clicked(m):
            for _k, _b in self._traceroute_method_btns.items():
                _b.setChecked(_k == m)
            self.traceroute_current_method = m
            self._traceroute_method_changed(m)

        self.traceroute_method_icmp_btn.clicked.connect(lambda: _tr_method_btn_clicked('ICMP'))
        self.traceroute_method_tcp_btn.clicked.connect(lambda: _tr_method_btn_clicked('TCP'))
        self.traceroute_method_udp_btn.clicked.connect(lambda: _tr_method_btn_clicked('UDP'))
        self.traceroute_method_pingicmp_btn.clicked.connect(lambda: _tr_method_btn_clicked('Ping ICMP'))
        self.traceroute_method_pingtcp_btn.clicked.connect(lambda: _tr_method_btn_clicked('Ping TCP'))

        _tr_method_layout.addWidget(self.traceroute_method_icmp_btn)
        _tr_method_layout.addWidget(self.traceroute_method_tcp_btn)
        _tr_method_layout.addWidget(self.traceroute_method_udp_btn)
        _tr_method_layout.addWidget(self.traceroute_method_pingicmp_btn)
        _tr_method_layout.addWidget(self.traceroute_method_pingtcp_btn)
        _tr_method_layout.addStretch()
        config_layout.addRow("Method:", _tr_method_widget)
        config_layout.addRow("Target:", _target_widget)

        # Proxy — internal state
        self._proxy_enabled = False
        self._proxy_type = "SOCKS5"
        self._proxy_host = ""
        self._proxy_port = ""

        self.traceroute_proxy_btn = QPushButton("Configure...")
        self.traceroute_proxy_btn.setFixedWidth(90)
        self.traceroute_proxy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.traceroute_proxy_btn.setToolTip("Configure proxy settings for traceroute")
        self.traceroute_proxy_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #333333;
                border: 1px solid #bdbdbd;
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #bdbdbd;
            }
        """)
        self.traceroute_proxy_btn.clicked.connect(self._open_proxy_settings_dialog)
        config_layout.addRow("Proxy:", self.traceroute_proxy_btn)

        # Port input (hidden by default, shown when TCP/UDP selected) with quick presets
        self.traceroute_port_label = QLabel("Port:")
        self.traceroute_port_input = QLineEdit()
        self.traceroute_port_input.setPlaceholderText("80, 443, 53, etc.")
        self.traceroute_port_input.setToolTip("Target port for TCP/UDP traceroute (1-65535)")
        self.traceroute_port_input.setText("80")
        self.traceroute_port_input.setStyleSheet(traceroute_line_edit_style)

        _tr_common_ports = [
            ("HTTP (80)", "80"),
            ("HTTPS (443)", "443"),
            ("DNS (53)", "53"),
            ("SSH (22)", "22"),
            ("Telnet (23)", "23"),
            ("FTP (21)", "21"),
            ("SMTP (25)", "25"),
            ("POP3 (110)", "110"),
            ("IMAP (143)", "143"),
            ("SNMP (161)", "161"),
            ("RDP (3389)", "3389"),
            ("VNC (5900)", "5900"),
            ("MySQL (3306)", "3306"),
            ("PostgreSQL (5432)", "5432"),
        ]

        _tr_ports_quick_btn = QPushButton()
        _tr_ports_quick_btn.setIcon(QIcon(self.get_arrow_icon_path()))
        _tr_ports_quick_btn.setIconSize(QSize(16, 16))
        _tr_ports_quick_btn.setFixedWidth(28)
        _tr_ports_quick_btn.setFixedHeight(self.traceroute_port_input.sizeHint().height() or 24)
        _tr_ports_quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _tr_ports_quick_btn.setToolTip("Common ports presets")
        _tr_ports_quick_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
                border: 1px solid #b0b0b0;
            }
            QPushButton:pressed {
                background-color: #d8d8d8;
            }
        """)

        def _show_tr_ports_menu():
            menu = QMenu(_tr_ports_quick_btn)
            for label, port in _tr_common_ports:
                action = menu.addAction(label)
                action.setData(port)
            chosen = menu.exec(
                _tr_ports_quick_btn.mapToGlobal(_tr_ports_quick_btn.rect().bottomLeft())
            )
            if chosen and chosen.data():
                self.traceroute_port_input.setText(chosen.data())

        _tr_ports_quick_btn.clicked.connect(_show_tr_ports_menu)

        _tr_port_widget = QWidget()
        _tr_port_widget.setFixedWidth(combo_width)
        _tr_port_layout = QHBoxLayout(_tr_port_widget)
        _tr_port_layout.setContentsMargins(0, 0, 0, 0)
        _tr_port_layout.setSpacing(4)
        _tr_port_layout.addWidget(self.traceroute_port_input)
        _tr_port_layout.addWidget(_tr_ports_quick_btn)

        self.traceroute_port_label.setVisible(False)
        _tr_port_widget.setVisible(False)
        self._tr_port_widget = _tr_port_widget
        config_layout.addRow(self.traceroute_port_label, _tr_port_widget)

        # Packets | Interval (MTR) | Max Hops | Timeout — single inline row
        self.mtr_packets_label = QLabel("Packets:")
        self.mtr_packets_label.setStyleSheet("color: #555555; font-size: 8pt;")
        self.mtr_packets_label.setVisible(False)

        self.mtr_packets_combo = FlatComboButton()
        self.mtr_packets_combo.addItems(["10", "20", "50", "100", "200"])
        self.mtr_packets_combo.setCurrentText("10")
        self.mtr_packets_combo.setFixedWidth(80)
        self.mtr_packets_combo.setToolTip("Number of packets to send per hop")
        self.mtr_packets_combo.setVisible(False)
        self._mtr_pkt_widget = self.mtr_packets_combo

        self.mtr_interval_label = QLabel("Interval:")
        self.mtr_interval_label.setStyleSheet("color: #555555; font-size: 8pt;")
        self.mtr_interval_label.setVisible(False)
        self.mtr_interval_combo = FlatComboButton()
        self.mtr_interval_combo.addItems(["1s", "2s", "5s"])
        self.mtr_interval_combo.setCurrentText("1s")
        self.mtr_interval_combo.setFixedWidth(75)
        self.mtr_interval_combo.setToolTip("Probe interval between cycles")
        self.mtr_interval_combo.setVisible(False)

        self._hops_label = QLabel("Max Hops:")
        self._hops_label.setStyleSheet("color: #555555; font-size: 8pt;")
        self.traceroute_max_hops_combo = FlatComboButton()
        self.traceroute_max_hops_combo.addItems(["10", "15", "20", "25", "30"])
        self.traceroute_max_hops_combo.setCurrentText("30")
        self.traceroute_max_hops_combo.setFixedWidth(80)
        self.traceroute_max_hops_combo.setToolTip("Maximum number of hops")

        self._timeout_label = QLabel("Timeout:")
        self._timeout_label.setStyleSheet("color: #555555; font-size: 8pt;")
        self.traceroute_timeout_combo = FlatComboButton()
        self.traceroute_timeout_combo.addItems(["1s", "2s", "3s", "5s", "10s"])
        self.traceroute_timeout_combo.setCurrentText("5s")
        self.traceroute_timeout_combo.setFixedWidth(85)
        self.traceroute_timeout_combo.setToolTip("Timeout per hop")

        _pkt_row_widget = QWidget()
        _pkt_row_layout = QHBoxLayout(_pkt_row_widget)
        _pkt_row_layout.setContentsMargins(0, 0, 0, 0)
        _pkt_row_layout.setSpacing(6)
        _pkt_row_layout.addWidget(self.mtr_packets_label)
        _pkt_row_layout.addWidget(self.mtr_packets_combo)
        _pkt_row_layout.addWidget(self.mtr_interval_label)
        _pkt_row_layout.addWidget(self.mtr_interval_combo)
        _pkt_row_layout.addWidget(self._hops_label)
        _pkt_row_layout.addWidget(self.traceroute_max_hops_combo)
        _pkt_row_layout.addWidget(self._timeout_label)
        _pkt_row_layout.addWidget(self.traceroute_timeout_combo)
        _pkt_row_layout.addStretch()
        config_layout.addRow("", _pkt_row_widget)

        config_group.setLayout(config_layout)
        config_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 30))
        config_group.setGraphicsEffect(shadow)

        main_layout.addWidget(config_group)

        # Hidden data store for hop visualization (not added to any layout)
        self.traceroute_viz_widget = RouteVisualizationWidget()
        self._latency_graph_dialog = None
        self._latency_graph_widget = None
        self._traceroute_hop_stats = {}  # {hop_num: (loss_pct, stdev)}

        # === Results Group ===
        self.traceroute_results_group = QGroupBox("Results")
        results_layout = QVBoxLayout()
        results_layout.setContentsMargins(10, 2, 10, 8)
        results_layout.setSpacing(6)

        self.traceroute_results_table = QTableWidget()
        self.traceroute_results_table.setColumnCount(4)
        self.traceroute_results_table.setHorizontalHeaderLabels(
            ["Hop", "IP Address", "Hostname", "Latency (ms)"]
        )

        # Column resize modes
        self.traceroute_results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.traceroute_results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.traceroute_results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.traceroute_results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.traceroute_results_table.setColumnWidth(0, 60)
        self.traceroute_results_table.setColumnWidth(3, 100)

        # Selection and editing
        self.traceroute_results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.traceroute_results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.traceroute_results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.traceroute_results_table.verticalHeader().setVisible(False)
        self.traceroute_results_table.setSortingEnabled(True)

        # Context menu
        self.traceroute_results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.traceroute_results_table.customContextMenuRequested.connect(self._traceroute_context_menu)

        # Styling
        self.traceroute_results_table.setStyleSheet("""
            QTableWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
                gridline-color: #d0d0d0;
            }
            QTableWidget::item {
                padding: 4px;
                background-color: #e8e8e8;
            }
            QTableWidget::item:selected {
                background-color: #00BCD4;
                color: white;
            }
            QHeaderView::section {
                background-color: #d0d0d0;
                color: #333333;
                padding: 4px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
            }
        """)

        results_layout.addWidget(self.traceroute_results_table)
        self._enable_table_tooltips(self.traceroute_results_table)

        # Action buttons
        actions_layout = QHBoxLayout()

        btn_style = """
            QPushButton {
                background-color: #78909c;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #607d8b;
            }
        """

        self.traceroute_export_btn = QPushButton("Export CSV")
        self.traceroute_export_btn.setFixedWidth(110)
        self.traceroute_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.traceroute_export_btn.setStyleSheet(btn_style)
        self.traceroute_export_btn.clicked.connect(self._traceroute_export_csv)
        actions_layout.addWidget(self.traceroute_export_btn)

        self.traceroute_clear_btn = QPushButton("Clear")
        self.traceroute_clear_btn.setFixedWidth(110)
        self.traceroute_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.traceroute_clear_btn.setStyleSheet(btn_style)
        self.traceroute_clear_btn.clicked.connect(self._traceroute_clear_results)
        actions_layout.addWidget(self.traceroute_clear_btn)

        actions_layout.addStretch()

        # Route Visualization icon button (routegraph1.svg)
        viz_icon_path = self.get_tab_icon_path('routegraph1.svg')
        viz_icon = load_svg_icon(viz_icon_path, 22) if viz_icon_path else None
        self.traceroute_viz_btn = QPushButton()
        self.traceroute_viz_btn.setToolTip("Route Visualization")
        self.traceroute_viz_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.traceroute_viz_btn.setFixedSize(36, 36)
        if viz_icon:
            self.traceroute_viz_btn.setIcon(viz_icon)
            self.traceroute_viz_btn.setIconSize(QSize(22, 22))
        else:
            self.traceroute_viz_btn.setText("⊞")
        self.traceroute_viz_btn.setStyleSheet("""
            QPushButton {
                background-color: #546e7a;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #455a64; }
            QPushButton:pressed { background-color: #37474f; }
        """)
        self.traceroute_viz_btn.clicked.connect(self._show_route_visualization_dialog)
        actions_layout.addWidget(self.traceroute_viz_btn)

        # Latency graph icon button (routegraph2.svg)
        graph_icon_path = self.get_tab_icon_path('routegraph2.svg')
        graph_icon = load_svg_icon(graph_icon_path, 22) if graph_icon_path else None
        self.traceroute_graph_btn = QPushButton()
        self.traceroute_graph_btn.setToolTip("Latency Graph")
        self.traceroute_graph_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.traceroute_graph_btn.setFixedSize(36, 36)
        if graph_icon:
            self.traceroute_graph_btn.setIcon(graph_icon)
            self.traceroute_graph_btn.setIconSize(QSize(22, 22))
        else:
            self.traceroute_graph_btn.setText("📈")
        self.traceroute_graph_btn.setStyleSheet("""
            QPushButton {
                background-color: #546e7a;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #455a64; }
            QPushButton:pressed { background-color: #37474f; }
        """)
        self.traceroute_graph_btn.clicked.connect(self._show_latency_graph_dialog)
        actions_layout.addWidget(self.traceroute_graph_btn)
        results_layout.addLayout(actions_layout)

        self.traceroute_results_group.setLayout(results_layout)
        main_layout.addWidget(self.traceroute_results_group)

        # === TRACEROUTE Button (full-width at bottom) ===
        self.traceroute_btn = QPushButton("TRACEROUTE")
        self.traceroute_btn.setMinimumHeight(45)
        self.traceroute_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.traceroute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #00ACC1;
            }
            QPushButton:pressed {
                background-color: #0097A7;
            }
        """)
        self.traceroute_btn.clicked.connect(self._start_traceroute)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.traceroute_btn.setGraphicsEffect(_btn_shadow)
        _tr_ico = load_svg_icon_dual(self._traceroute_method_icons.get('ICMP'), 18, '#ffffff', '#ffffff')
        if _tr_ico:
            self.traceroute_btn.setIcon(_tr_ico)
            self.traceroute_btn.setIconSize(QSize(18, 18))
            self.traceroute_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        main_layout.addWidget(self.traceroute_btn)

        page.setLayout(main_layout)

        # Initialize field visibility based on default method
        self._traceroute_method_changed(self.traceroute_current_method)

        return page

    def execute_snmp_query(self):
        """Execute SNMP query using pysnmp"""
        host = self.snmp_host_input.text().strip()
        port = "161"
        oid = self.snmp_oid_input.text().strip()
        query_type = self.snmp_current_type
        version = self.snmp_current_version
        community = self.snmp_community_input.text().strip() or "public"

        # SNMPv3 parameters
        v3_username = self.snmp_v3_username_input.text().strip()
        v3_auth_proto = self.snmp_v3_auth_proto_combo.currentText()
        v3_auth_pass = self.snmp_v3_auth_pass_input.text().strip()
        v3_priv_proto = self.snmp_v3_priv_proto_combo.currentText()
        v3_priv_pass = self.snmp_v3_priv_pass_input.text().strip()

        if version != "v3":
            self.config.add_vuln_community(community)

        # Validation
        if not host:
            self.snmp_results_table.setRowCount(0)
            self.snmp_results_group.setTitle("Results — Error: Host is required")
            return

        # v3 requires username
        if version == "v3" and not v3_username:
            self.snmp_results_table.setRowCount(0)
            self.snmp_results_group.setTitle("Results — Error: Username is required for SNMPv3")
            return

        # OID is required only for snmpget, optional for snmpwalk
        if query_type == "snmpget" and not oid:
            self.snmp_results_table.setRowCount(0)
            self.snmp_results_group.setTitle("Results — Error: OID is required for snmpget")
            return

        # Use default OID for snmpwalk if not specified
        if query_type == "snmpwalk" and not oid:
            oid = ".1.3.6.1.2.1"  # Default: walk entire MIB-2 tree

        # For GETNEXT: derive OID from last row in table if field is empty
        if query_type == "snmpgetnext":
            if not oid:
                last_row = self.snmp_results_table.rowCount() - 1
                if last_row >= 0:
                    oid_item = self.snmp_results_table.item(last_row, 1)
                    oid = oid_item.text() if oid_item else ""
            if not oid:
                self.snmp_results_group.setTitle("Results — Error: OID is required for GETNEXT")
                return

        # Update UI — for GETNEXT keep existing rows; clear for other types
        self.snmp_results_group.setTitle(f"Results (executing {query_type}...)")
        self.snmp_execute_btn.setEnabled(False)

        if query_type != "snmpgetnext":
            self.snmp_search_input.blockSignals(True)
            self.snmp_search_input.clear()
            self.snmp_search_input.blockSignals(False)
            self.snmp_results_table.setRowCount(0)
            self._snmp_oid_family_colors = {}
            self._snmp_oid_color_index = 0
            self._snmp_family_first_row = {}
            self._snmp_family_counts = {}
            self.snmp_index_list.clear()
            self._snmp_update_device_image('Default', '')
            self._snmp_device_pixmap_full = None
        self._snmp_image_fetched = False
        if query_type == "snmpwalk":
            self.snmp_execute_btn.setText("Walking 0%")
        else:
            self.snmp_execute_btn.setText("Querying...")
        
        # Execute query in background thread
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class SNMPWorker(QThread):
            row_received = pyqtSignal(str, str, str)  # oid, value, type
            progress = pyqtSignal(int)  # percentage 0-100
            finished_result = pyqtSignal(str, bool)  # message, success

            def __init__(self, host, port, oid, query_type, version, community,
                         v3_username=None, v3_auth_proto=None, v3_auth_pass=None,
                         v3_priv_proto=None, v3_priv_pass=None):
                super().__init__()
                self.host = host
                self.port = int(port)
                self.oid = oid
                self.query_type = query_type
                self.version = version
                self.community = community
                self.v3_username = v3_username
                self.v3_auth_proto = v3_auth_proto
                self.v3_auth_pass = v3_auth_pass
                self.v3_priv_proto = v3_priv_proto
                self.v3_priv_pass = v3_priv_pass

            @staticmethod
            def _classify_type(value):
                """Classify SNMP value type"""
                type_name = type(value).__name__
                type_map = {
                    'Integer': 'Integer', 'Integer32': 'Integer',
                    'Counter32': 'Counter32', 'Counter64': 'Counter64',
                    'Gauge32': 'Gauge32', 'Unsigned32': 'Unsigned',
                    'TimeTicks': 'TimeTicks', 'IpAddress': 'IpAddress',
                    'OctetString': 'String', 'DisplayString': 'String',
                    'ObjectIdentity': 'OID', 'ObjectIdentifier': 'OID',
                    'Bits': 'Bits', 'Opaque': 'Opaque',
                }
                return type_map.get(type_name, type_name)

            @staticmethod
            def _format_value(val):
                """Convert SNMP value to a readable string.
                IpAddress is formatted as dotted decimal.
                OctetStrings with non-printable bytes are shown as colon-separated hex."""
                type_name = type(val).__name__
                if type_name == 'IpAddress':
                    try:
                        raw = val.asOctets()
                        if len(raw) == 4:
                            return '.'.join(str(b) for b in raw)
                    except Exception:
                        pass
                if type_name in ('OctetString', 'Bits', 'Opaque'):
                    try:
                        raw = val.asOctets()
                        if all(0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D) for b in raw):
                            return raw.decode('ascii', errors='replace').strip()
                        return ':'.join(f'{b:02X}' for b in raw)
                    except Exception:
                        pass
                return str(val)

            def _emit_varbind(self, varBind):
                self.row_received.emit(
                    str(varBind[0]),
                    SNMPWorker._format_value(varBind[1]),
                    SNMPWorker._classify_type(varBind[1])
                )

            def run(self):
                try:
                    import asyncio
                    from pysnmp.hlapi.v3arch.asyncio import (
                        SnmpEngine, CommunityData, UsmUserData, UdpTransportTarget,
                        ContextData, ObjectType, ObjectIdentity,
                        get_cmd, next_cmd, walk_cmd,
                        usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
                        usmHMAC128SHA224AuthProtocol, usmHMAC192SHA256AuthProtocol,
                        usmHMAC256SHA384AuthProtocol, usmHMAC384SHA512AuthProtocol,
                        usmDESPrivProtocol, usm3DESEDEPrivProtocol,
                        usmAesCfb128Protocol, usmAesCfb192Protocol, usmAesCfb256Protocol,
                        usmNoAuthProtocol, usmNoPrivProtocol
                    )

                    async def do_snmp_query():
                        # Determine auth_data based on version
                        if self.version == "v1":
                            auth_data = CommunityData(self.community, mpModel=0)
                        elif self.version == "v2c":
                            auth_data = CommunityData(self.community, mpModel=1)
                        elif self.version == "v3":
                            # Map protocol names to pysnmp objects
                            auth_protocols = {
                                "None": usmNoAuthProtocol,
                                "MD5": usmHMACMD5AuthProtocol,
                                "SHA": usmHMACSHAAuthProtocol,
                                "SHA224": usmHMAC128SHA224AuthProtocol,
                                "SHA256": usmHMAC192SHA256AuthProtocol,
                                "SHA384": usmHMAC256SHA384AuthProtocol,
                                "SHA512": usmHMAC384SHA512AuthProtocol,
                            }
                            priv_protocols = {
                                "None": usmNoPrivProtocol,
                                "DES": usmDESPrivProtocol,
                                "3DES": usm3DESEDEPrivProtocol,
                                "AES": usmAesCfb128Protocol,
                                "AES192": usmAesCfb192Protocol,
                                "AES256": usmAesCfb256Protocol,
                            }

                            auth_proto = auth_protocols.get(self.v3_auth_proto, usmNoAuthProtocol)
                            priv_proto = priv_protocols.get(self.v3_priv_proto, usmNoPrivProtocol)

                            auth_key = self.v3_auth_pass if self.v3_auth_pass else None
                            priv_key = self.v3_priv_pass if self.v3_priv_pass else None

                            auth_data = UsmUserData(
                                self.v3_username,
                                authKey=auth_key,
                                privKey=priv_key,
                                authProtocol=auth_proto,
                                privProtocol=priv_proto
                            )
                        else:
                            self.finished_result.emit(f"Unknown SNMP version: {self.version}", False)
                            return

                        count = 0

                        try:
                            engine = SnmpEngine()
                            target = await UdpTransportTarget.create(
                                (self.host, self.port),
                                timeout=2.0,
                                retries=1
                            )

                            if self.query_type in ("snmpget", "snmpgetnext"):
                                cmd_func = get_cmd if self.query_type == "snmpget" else next_cmd
                                errorIndication, errorStatus, errorIndex, varBinds = await cmd_func(
                                    engine,
                                    auth_data,
                                    target,
                                    ContextData(),
                                    ObjectType(ObjectIdentity(self.oid))
                                )

                                if errorIndication:
                                    self.finished_result.emit(f"Error: {errorIndication}", False)
                                    return
                                elif errorStatus:
                                    self.finished_result.emit(f"Error: {errorStatus.prettyPrint()} at {errorIndex and varBinds[int(errorIndex) - 1][0] or '?'}", False)
                                    return
                                else:
                                    for varBind in varBinds:
                                        self._emit_varbind(varBind)
                                        count += 1

                            else:  # snmpwalk
                                async for (errorIndication, errorStatus, errorIndex, varBinds) in walk_cmd(
                                    engine,
                                    auth_data,
                                    target,
                                    ContextData(),
                                    ObjectType(ObjectIdentity(self.oid)),
                                    lexicographicMode=False
                                ):
                                    if errorIndication:
                                        self.finished_result.emit(f"Error: {errorIndication}", False)
                                        return
                                    elif errorStatus:
                                        self.finished_result.emit(f"Error: {errorStatus.prettyPrint()} at {errorIndex and varBinds[int(errorIndex) - 1][0] or '?'}", False)
                                        return
                                    else:
                                        for varBind in varBinds:
                                            self._emit_varbind(varBind)
                                            count += 1
                                            self.progress.emit(min(count * 100 // 1000, 99))
                                            if count >= 1000:
                                                break
                                    if count >= 1000:
                                        break

                            if count > 0:
                                self.finished_result.emit("", True)
                            else:
                                self.finished_result.emit("No results returned", False)

                        finally:
                            engine.close_dispatcher()

                    asyncio.run(do_snmp_query())

                except ImportError as e:
                    self.finished_result.emit(
                        f"Error: pysnmp not installed or import failed\n\n{str(e)}\n\nInstall with: pip install pysnmp",
                        False
                    )
                except Exception as e:
                    self.finished_result.emit(f"Error: {str(e)}", False)

                # Create and start worker
        self.snmp_results_table.setSortingEnabled(False)
        self._snmp_last_host = host
        self._snmp_last_community = community
        self.snmp_worker = SNMPWorker(
            host, port, oid, query_type, version, community,
            v3_username, v3_auth_proto, v3_auth_pass, v3_priv_proto, v3_priv_pass
        )
        self.snmp_worker.row_received.connect(self._on_snmp_row)
        self.snmp_worker.progress.connect(lambda p: self.snmp_execute_btn.setText(f"Walking {p}%"))
        self.snmp_worker.finished_result.connect(self._on_snmp_finished)
        self.snmp_worker.start()
    
    # Known OID prefix → brief description (keys without leading dot)
    _OID_DESCRIPTIONS = {
        # System
        "1.3.6.1.2.1.1":       "System",
        "1.3.6.1.2.1.1.1":     "sysDescr",
        "1.3.6.1.2.1.1.2":     "sysObjectID",
        "1.3.6.1.2.1.1.3":     "sysUpTime",
        "1.3.6.1.2.1.1.4":     "sysContact",
        "1.3.6.1.2.1.1.5":     "sysName",
        "1.3.6.1.2.1.1.6":     "sysLocation",
        "1.3.6.1.2.1.1.7":     "sysServices",
        # Interfaces (IF-MIB)
        "1.3.6.1.2.1.2":       "Interfaces",
        "1.3.6.1.2.1.2.1":     "ifNumber",
        "1.3.6.1.2.1.2.2.1.1": "ifIndex",
        "1.3.6.1.2.1.2.2.1.2": "ifDescr",
        "1.3.6.1.2.1.2.2.1.3": "ifType",
        "1.3.6.1.2.1.2.2.1.4": "ifMtu",
        "1.3.6.1.2.1.2.2.1.5": "ifSpeed",
        "1.3.6.1.2.1.2.2.1.6": "ifPhysAddress (MAC)",
        "1.3.6.1.2.1.2.2.1.7": "ifAdminStatus",
        "1.3.6.1.2.1.2.2.1.8": "ifOperStatus",
        "1.3.6.1.2.1.2.2.1.9": "ifLastChange",
        "1.3.6.1.2.1.2.2.1.10":"ifInOctets",
        "1.3.6.1.2.1.2.2.1.11":"ifInUcastPkts",
        "1.3.6.1.2.1.2.2.1.12":"ifInNUcastPkts",
        "1.3.6.1.2.1.2.2.1.13":"ifInDiscards",
        "1.3.6.1.2.1.2.2.1.14":"ifInErrors",
        "1.3.6.1.2.1.2.2.1.16":"ifOutOctets",
        "1.3.6.1.2.1.2.2.1.17":"ifOutUcastPkts",
        "1.3.6.1.2.1.2.2.1.19":"ifOutDiscards",
        "1.3.6.1.2.1.2.2.1.20":"ifOutErrors",
        # IP
        "1.3.6.1.2.1.4":       "IP",
        "1.3.6.1.2.1.4.1":     "ipForwarding",
        "1.3.6.1.2.1.4.2":     "ipDefaultTTL",
        "1.3.6.1.2.1.4.3":     "ipInReceives",
        "1.3.6.1.2.1.4.20.1.1":"ipAdEntAddr",
        "1.3.6.1.2.1.4.20.1.2":"ipAdEntIfIndex",
        "1.3.6.1.2.1.4.20.1.3":"ipAdEntNetMask",
        "1.3.6.1.2.1.4.20.1.4":"ipAdEntBcastAddr",
        "1.3.6.1.2.1.4.21":    "ipRouteTable",
        "1.3.6.1.2.1.4.22":    "ARP (ipNetToMedia)",
        # TCP
        "1.3.6.1.2.1.6":       "TCP",
        "1.3.6.1.2.1.6.1":     "tcpRtoAlgorithm",
        "1.3.6.1.2.1.6.13":    "tcpConnTable",
        # UDP
        "1.3.6.1.2.1.7":       "UDP",
        "1.3.6.1.2.1.7.5":     "udpTable",
        # ICMP
        "1.3.6.1.2.1.5":       "ICMP",
        # SNMP
        "1.3.6.1.2.1.11":      "SNMP Stats",
        # Host Resources (HR-MIB)
        "1.3.6.1.2.1.25":      "Host Resources",
        "1.3.6.1.2.1.25.1":    "hrSystem",
        "1.3.6.1.2.1.25.2":    "hrStorage",
        "1.3.6.1.2.1.25.3":    "hrDevice",
        "1.3.6.1.2.1.25.4":    "hrSWRun",
        "1.3.6.1.2.1.25.5":    "hrSWRunPerf",
        "1.3.6.1.2.1.25.6":    "hrSWInstalled",
        # IF-MIB extended
        "1.3.6.1.2.1.31":      "IF-MIB Extended",
        "1.3.6.1.2.1.31.1.1.1.1": "ifName",
        "1.3.6.1.2.1.31.1.1.1.6": "ifHCInOctets",
        "1.3.6.1.2.1.31.1.1.1.10":"ifHCOutOctets",
        "1.3.6.1.2.1.31.1.1.1.15":"ifHighSpeed",
        "1.3.6.1.2.1.31.1.1.1.18":"ifAlias",
        # Enterprises
        "1.3.6.1.4.1":         "Enterprise (private)",
        "1.3.6.1.4.1.9":       "Cisco",
        "1.3.6.1.4.1.9.2":     "Cisco Local",
        "1.3.6.1.4.1.9.9":     "Cisco MIBs",
        "1.3.6.1.4.1.14988":   "MikroTik",
        "1.3.6.1.4.1.2636":    "Juniper",
        "1.3.6.1.4.1.2011":    "Huawei",
        "1.3.6.1.4.1.12356":   "Fortinet",
        "1.3.6.1.4.1.25506":   "HP/H3C",
        "1.3.6.1.4.1.311":     "Microsoft",
    }

    # Known OID prefix → detailed tooltip (human-readable explanation)
    _OID_TOOLTIPS = {
        # System
        "1.3.6.1.2.1.1":       "System Group (MIB-II)\nGeneral device information: name, description,\nlocation, contact and uptime.",
        "1.3.6.1.2.1.1.1":     "sysDescr\nFull text description of the device,\nincluding hardware, OS and firmware version.",
        "1.3.6.1.2.1.1.2":     "sysObjectID\nVendor enterprise OID that identifies\nthe device model.",
        "1.3.6.1.2.1.1.3":     "sysUpTime\nTime elapsed (in hundredths of a second) since\nthe last SNMP agent restart.",
        "1.3.6.1.2.1.1.4":     "sysContact\nName or email of the person responsible for the device.",
        "1.3.6.1.2.1.1.5":     "sysName\nAdministrative name of the device (hostname).",
        "1.3.6.1.2.1.1.6":     "sysLocation\nPhysical location of the device.",
        "1.3.6.1.2.1.1.7":     "sysServices\nOSI layers (bitmask) the device operates on\n(e.g. 78 = layers 1-4 and 7).",
        # Interfaces
        "1.3.6.1.2.1.2":       "Interfaces Group (MIB-II)\nInformation about all network interfaces\non the device.",
        "1.3.6.1.2.1.2.1":     "ifNumber\nTotal number of network interfaces present.",
        "1.3.6.1.2.1.2.2.1.1": "ifIndex\nUnique index identifying each interface.",
        "1.3.6.1.2.1.2.2.1.2": "ifDescr\nName or text description of the interface\n(e.g. 'eth0', 'GigabitEthernet0/1').",
        "1.3.6.1.2.1.2.2.1.3": "ifType\nPhysical type of the interface (e.g. ethernetCsmacd=6,\nsoftwareLoopback=24, ieee80211=71).",
        "1.3.6.1.2.1.2.2.1.4": "ifMtu\nMaximum bytes in a frame that can be\ntransmitted by the interface (MTU).",
        "1.3.6.1.2.1.2.2.1.5": "ifSpeed\nNominal interface speed in bits/s\n(e.g. 1000000000 = 1 Gbps).",
        "1.3.6.1.2.1.2.2.1.6": "ifPhysAddress (MAC)\nPhysical address of the interface (e.g. MAC address),\nstored as binary OctetString.",
        "1.3.6.1.2.1.2.2.1.7": "ifAdminStatus\nConfigured administrative state:\n1=up, 2=down, 3=testing.",
        "1.3.6.1.2.1.2.2.1.8": "ifOperStatus\nActual operational state of the interface:\n1=up, 2=down, 3=testing, 4=unknown.",
        "1.3.6.1.2.1.2.2.1.9": "ifLastChange\nSysUpTime at the time of the last\noperational state change.",
        "1.3.6.1.2.1.2.2.1.10":"ifInOctets\nTotal bytes received by the interface,\nincluding framing headers.",
        "1.3.6.1.2.1.2.2.1.11":"ifInUcastPkts\nUnicast packets received and delivered\nto an upper layer.",
        "1.3.6.1.2.1.2.2.1.12":"ifInNUcastPkts\nNon-unicast (broadcast/multicast) packets\nreceived and delivered.",
        "1.3.6.1.2.1.2.2.1.13":"ifInDiscards\nReceived packets discarded (no errors),\ne.g. buffer exhaustion.",
        "1.3.6.1.2.1.2.2.1.14":"ifInErrors\nPackets received with errors (CRC, alignment,\noverflow, etc.).",
        "1.3.6.1.2.1.2.2.1.16":"ifOutOctets\nTotal bytes transmitted by the interface,\nincluding framing headers.",
        "1.3.6.1.2.1.2.2.1.17":"ifOutUcastPkts\nUnicast packets requested by upper layer\nfor transmission.",
        "1.3.6.1.2.1.2.2.1.19":"ifOutDiscards\nOutgoing packets discarded without errors,\ne.g. output buffer exhaustion.",
        "1.3.6.1.2.1.2.2.1.20":"ifOutErrors\nPackets that failed transmission\ndue to errors.",
        # IP
        "1.3.6.1.2.1.4":       "IP Group (MIB-II)\nIP layer statistics and configuration,\nincluding routing and address table.",
        "1.3.6.1.2.1.4.1":     "ipForwarding\nIndicates whether the device acts as an IP router:\n1=forwarding, 2=notForwarding.",
        "1.3.6.1.2.1.4.2":     "ipDefaultTTL\nDefault TTL value inserted into IP datagrams.",
        "1.3.6.1.2.1.4.3":     "ipInReceives\nTotal IP datagrams received,\nincluding those with errors.",
        "1.3.6.1.2.1.4.20.1.1":"ipAdEntAddr\nIP address assigned to the interface.",
        "1.3.6.1.2.1.4.20.1.2":"ipAdEntIfIndex\nIndex of the interface to which the IP address belongs.",
        "1.3.6.1.2.1.4.20.1.3":"ipAdEntNetMask\nSubnet mask associated with the IP address.",
        "1.3.6.1.2.1.4.20.1.4":"ipAdEntBcastAddr\nLeast significant bit of the broadcast address.",
        "1.3.6.1.2.1.4.21":    "ipRouteTable\nIP routing table of the device.",
        "1.3.6.1.2.1.4.22":    "ARP (ipNetToMediaTable)\nARP table: mapping between IP addresses\nand physical (MAC) addresses.",
        # TCP / UDP / ICMP / SNMP
        "1.3.6.1.2.1.5":       "ICMP Group (MIB-II)\nCounters of ICMP messages sent and received\n(echo, redirect, unreachable, etc.).",
        "1.3.6.1.2.1.6":       "TCP Group (MIB-II)\nTCP layer parameters and statistics,\nincluding active connection table.",
        "1.3.6.1.2.1.6.1":     "tcpRtoAlgorithm\nRetransmission algorithm in use:\n1=other, 2=constant, 3=rsre, 4=vanj.",
        "1.3.6.1.2.1.6.13":    "tcpConnTable\nActive TCP connections: local address,\nlocal port, remote address, remote port and state.",
        "1.3.6.1.2.1.7":       "UDP Group (MIB-II)\nStatistics of UDP datagrams sent,\nreceived and with errors.",
        "1.3.6.1.2.1.7.5":     "udpTable\nActive UDP endpoints on the device.",
        "1.3.6.1.2.1.11":      "SNMP Group (MIB-II)\nStatistics of the SNMP agent itself:\npackets received, errors, gets, sets, traps.",
        # Host Resources
        "1.3.6.1.2.1.25":      "Host Resources MIB (RFC 2790)\nSystem resources: CPU, memory, disk,\nprocesses and installed software.",
        "1.3.6.1.2.1.25.1":    "hrSystem\nGeneral system information: uptime,\ndate/time and number of users.",
        "1.3.6.1.2.1.25.2":    "hrStorage\nStorage areas table: RAM,\nswap, filesystems and current usage.",
        "1.3.6.1.2.1.25.3":    "hrDevice\nDetected devices: processors,\nnetwork interfaces, disks and printers.",
        "1.3.6.1.2.1.25.4":    "hrSWRun\nRunning processes table:\nname, path, parameters and state.",
        "1.3.6.1.2.1.25.5":    "hrSWRunPerf\nPer-process performance:\nCPU time and real memory usage.",
        "1.3.6.1.2.1.25.6":    "hrSWInstalled\nSoftware installed on the system:\nname, version and installation date.",
        # IF-MIB Extended
        "1.3.6.1.2.1.31":      "IF-MIB Extended (RFC 2863)\nInterface table extensions with 64-bit\ncounters and additional information.",
        "1.3.6.1.2.1.31.1.1.1.1":  "ifName\nShort interface name (e.g. 'eth0', 'Gi0/1'),\nas shown by the operating system.",
        "1.3.6.1.2.1.31.1.1.1.6":  "ifHCInOctets\n64-bit counter of bytes received.\nReplaces ifInOctets on high-speed links.",
        "1.3.6.1.2.1.31.1.1.1.10": "ifHCOutOctets\n64-bit counter of bytes transmitted.\nReplaces ifOutOctets on high-speed links.",
        "1.3.6.1.2.1.31.1.1.1.15": "ifHighSpeed\nInterface speed in Mbps when\nifSpeed (32-bit) is not sufficient.",
        "1.3.6.1.2.1.31.1.1.1.18": "ifAlias\nDescriptive name assigned by the operator\nto the interface (configurable alias).",
        # Enterprises
        "1.3.6.1.4.1":         "Enterprise MIBs (private OIDs)\nTree of vendor-proprietary OIDs,\neach with its own exclusive sub-tree.",
        "1.3.6.1.4.1.9":       "Cisco Systems\nCisco proprietary MIBs: interfaces,\nVLANs, CDP, spanning tree, QoS, etc.",
        "1.3.6.1.4.1.9.2":     "Cisco Local MIB\nLocal Cisco device information:\nIOS version, memory and configuration.",
        "1.3.6.1.4.1.9.9":     "Cisco Enterprise MIBs\nCisco feature-specific MIBs:\nVTP, EIGRP, BGP, HSRP, among others.",
        "1.3.6.1.4.1.14988":   "MikroTik RouterOS\nMikroTik proprietary MIBs: wireless interfaces,\nqueues, health and licensing.",
        "1.3.6.1.4.1.2636":    "Juniper Networks\nJuniper proprietary MIBs: chassis,\nBGP, MPLS and routing statistics.",
        "1.3.6.1.4.1.2011":    "Huawei Technologies\nHuawei proprietary MIBs for routers,\nswitches and telecom equipment.",
        "1.3.6.1.4.1.12356":   "Fortinet\nFortiGate proprietary MIBs: VPN,\nfirewall, UTM and session statistics.",
        "1.3.6.1.4.1.25506":   "HP/H3C\nHP Networking / H3C proprietary MIBs\nfor ProCurve switches and routers.",
        "1.3.6.1.4.1.311":     "Microsoft\nMicrosoft proprietary MIBs for Windows\nServer systems and network services.",
    }

    @staticmethod
    def _snmp_describe_oid(oid):
        """Return a brief label and detailed tooltip for an OID, walking up the hierarchy."""
        key = oid.lstrip('.')
        while key:
            desc = SerialTerminalGUI._OID_DESCRIPTIONS.get(key)
            if desc:
                return desc
            if '.' in key:
                key = key.rsplit('.', 1)[0]
            else:
                break
        return "—"

    @staticmethod
    def _snmp_tooltip_oid(oid):
        """Return a detailed tooltip string for an OID, walking up the hierarchy."""
        key = oid.lstrip('.')
        while key:
            tip = SerialTerminalGUI._OID_TOOLTIPS.get(key)
            if tip:
                return tip
            if '.' in key:
                key = key.rsplit('.', 1)[0]
            else:
                break
        return oid

    # Pastel palette for OID family grouping (light background)
    _SNMP_FAMILY_PALETTE = [
        QColor(0xFF, 0xF0, 0x80),  # yellow
        QColor(0xA8, 0xD8, 0xFF),  # sky blue
        QColor(0xA8, 0xF0, 0xB8),  # mint green
        QColor(0xFF, 0xC8, 0x90),  # peach
        QColor(0xD8, 0xB8, 0xFF),  # lavender
        QColor(0xFF, 0xB8, 0xCC),  # rose
        QColor(0xA8, 0xF0, 0xE8),  # aqua
        QColor(0xFF, 0xE0, 0xA8),  # apricot
    ]

    def _on_snmp_row(self, oid, value, vtype):
        """Append a single SNMP result row to the table"""
        # Determine family: OID prefix without the last segment
        parts = oid.rsplit(".", 1)
        family = parts[0] if len(parts) == 2 else oid

        if not hasattr(self, "_snmp_oid_family_colors"):
            self._snmp_oid_family_colors = {}
            self._snmp_oid_color_index = 0
            self._snmp_family_first_row = {}
            self._snmp_family_counts = {}

        # Track family member count
        self._snmp_family_counts[family] = self._snmp_family_counts.get(family, 0) + 1

        is_new_family = family not in self._snmp_oid_family_colors
        if is_new_family:
            palette = self._SNMP_FAMILY_PALETTE
            self._snmp_oid_family_colors[family] = palette[
                self._snmp_oid_color_index % len(palette)
            ]
            self._snmp_oid_color_index += 1

        color = self._snmp_oid_family_colors[family]

        row = self.snmp_results_table.rowCount()
        self.snmp_results_table.insertRow(row)

        # Get family description for Family Tree column
        family_desc = ""
        if is_new_family:
            family_desc = self._snmp_describe_oid(family)

        # Add cells: Family Tree, OID, Value, Type
        for col, text in enumerate([family_desc, oid, value, vtype]):
            cell = QTableWidgetItem(text)
            cell.setBackground(color)
            self.snmp_results_table.setItem(row, col, cell)
            # Store family info in first column for later color update
            if col == 0:
                cell.setData(Qt.ItemDataRole.UserRole, family)

        if is_new_family:
            self._snmp_family_first_row[family] = row
            desc = self._snmp_describe_oid(family)
            tip = self._snmp_tooltip_oid(family)
            parts = family.lstrip('.').split('.')
            short = ('…' + '.'.join(parts[-4:])) if len(parts) > 4 else family

            # Build colored widget (setBackground() is suppressed by Qt stylesheets;
            # setItemWidget() is the reliable alternative)
            idx_widget = QWidget()
            idx_widget.setStyleSheet(
                f"QWidget {{ background-color: {color.name()}; }}"
                "QLabel { background: transparent; }"
            )
            # Tooltip on the widget (idx_item tooltip is never shown with setItemWidget)
            idx_widget.setToolTip(f"<b>{family}</b><hr>{tip}")
            wlayout = QVBoxLayout(idx_widget)
            wlayout.setContentsMargins(5, 3, 5, 3)
            wlayout.setSpacing(1)
            oid_lbl = QLabel(short)
            oid_lbl.setFont(QFont("Monospace", 8))
            oid_lbl.setStyleSheet("color: #444444;")
            oid_lbl.setWordWrap(True)
            desc_lbl = QLabel(desc)
            desc_lbl.setFont(QFont("Sans Serif", 8, QFont.Weight.Bold))
            desc_lbl.setStyleSheet("color: #111111;")
            wlayout.addWidget(oid_lbl)
            wlayout.addWidget(desc_lbl)

            idx_item = QListWidgetItem()
            idx_item.setData(Qt.ItemDataRole.UserRole, family)
            idx_item.setSizeHint(idx_widget.sizeHint())
            self.snmp_index_list.addItem(idx_item)
            self.snmp_index_list.setItemWidget(idx_item, idx_widget)
        self.snmp_results_group.setTitle(f"Results — {row + 1} entries")

        # Trigger device image fetch as soon as sysDescr arrives
        if not getattr(self, '_snmp_image_fetched', False):
            norm_oid = oid.lstrip('.')
            if norm_oid == '1.3.6.1.2.1.1.1.0':
                self._snmp_image_fetched = True
                vendor, model, _ = NmapDiscoverWorker._split_service_product(value) \
                    if value else ('', '', '')
                if vendor:
                    self._snmp_update_device_image(vendor, model)
                    self._snmp_fetch_device_image(vendor, model, value)

    def _on_snmp_finished(self, message, success):
        """Handle SNMP query completion"""
        label_map = {"snmpget": "SNMP GET", "snmpgetnext": "SNMP GETNEXT"}
        self.snmp_execute_btn.setText(label_map.get(self.snmp_current_type, "SNMP WALK"))
        self.snmp_execute_btn.setEnabled(True)

        # Save working community for this host
        if success:
            host = getattr(self, '_snmp_last_host', '')
            community = getattr(self, '_snmp_last_community', '')
            if host and community:
                self.config.set_snmp_ip_community(host, community)

        # For GETNEXT: update OID field with the returned OID so the next
        # click advances to the following entry in the MIB tree
        if success and self.snmp_current_type == "snmpgetnext":
            last_row = self.snmp_results_table.rowCount() - 1
            if last_row >= 0:
                oid_item = self.snmp_results_table.item(last_row, 1)
                if oid_item:
                    self.snmp_oid_input.setText(oid_item.text())

        # Update colors: families with only 1 member should be white
        if success and hasattr(self, "_snmp_family_counts"):
            white_color = QColor(255, 255, 255)
            for row in range(self.snmp_results_table.rowCount()):
                family_cell = self.snmp_results_table.item(row, 0)
                if family_cell:
                    family = family_cell.data(Qt.ItemDataRole.UserRole)
                    if family and self._snmp_family_counts.get(family, 0) == 1:
                        # Set white background for all columns in this row
                        for col in range(self.snmp_results_table.columnCount()):
                            cell = self.snmp_results_table.item(row, col)
                            if cell:
                                cell.setBackground(white_color)

            # Update index list: make single-member families white too
            for i in range(self.snmp_index_list.count()):
                item = self.snmp_index_list.item(i)
                family = item.data(Qt.ItemDataRole.UserRole)
                if family and self._snmp_family_counts.get(family, 0) == 1:
                    widget = self.snmp_index_list.itemWidget(item)
                    if widget:
                        widget.setStyleSheet(
                            "QWidget { background-color: #ffffff; }"
                            "QLabel { background: transparent; }"
                        )

        self.snmp_results_table.setSortingEnabled(True)
        if success:
            count = self.snmp_results_table.rowCount()
            self.snmp_results_group.setTitle(f"Results — {count} entries")
            # Fallback: if image not fetched yet (e.g. sysDescr not in walk), try now
            if not getattr(self, '_snmp_image_fetched', False):
                self._snmp_try_fetch_device_image()
        else:
            self.snmp_results_group.setTitle(f"Results — {message}")

    def _snmp_try_fetch_device_image(self):
        """Scan the results table for sysDescr/sysName and fetch the device image."""
        sys_descr = ''
        sys_name  = ''
        for row in range(self.snmp_results_table.rowCount()):
            oid_item = self.snmp_results_table.item(row, 1)
            val_item = self.snmp_results_table.item(row, 2)
            if not oid_item or not val_item:
                continue
            oid = oid_item.text()
            val = val_item.text()
            if oid.endswith('.1.3.6.1.2.1.1.1.0') or oid == '1.3.6.1.2.1.1.1.0':
                sys_descr = val
            elif oid.endswith('.1.3.6.1.2.1.1.5.0') or oid == '1.3.6.1.2.1.1.5.0':
                sys_name = val
        if not sys_descr and not sys_name:
            return
        from PyQt6.QtCore import QTimer
        # Use the same parser as NmapDiscoverWorker
        vendor, model, _ = NmapDiscoverWorker._split_service_product(sys_descr) \
            if sys_descr else ('', '', '')
        # Fallback: use first word of sysName
        if not vendor and sys_name:
            vendor = sys_name.split('.')[0].split('-')[0]
        if not vendor:
            return
        self._snmp_update_device_image(vendor, model or sys_name)
        self._snmp_fetch_device_image(vendor, model, sys_descr)

    def _snmp_update_device_image(self, vendor, model):
        """Show vendor SVG as placeholder."""
        _NORMALIZE = {
            'hp': 'Aruba', 'hpe': 'Aruba',
            'juniper networks': 'Juniper', 'h3c': 'H3C',
        }
        icon_vendor = _NORMALIZE.get(vendor.lower(), vendor)
        icon_path   = self.get_vendor_icon_path(icon_vendor)
        pixmap      = load_svg_pixmap(icon_path, 64)
        if pixmap and not pixmap.isNull():
            self.snmp_device_img.setPixmap(
                pixmap.scaled(64, 64,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation))
        else:
            self.snmp_device_img.clear()
        self.snmp_device_name_lbl.setText(model if model else vendor)

    def _snmp_fetch_device_image(self, vendor, model, raw_descr):
        """Launch web image search for the detected device."""
        import re
        if not model:
            hw_m = re.search(r'\b([A-Z]{1,5}[\d][\w\-/]{2,20})\b', raw_descr)
            model = hw_m.group(1) if hw_m else ''
        query = f'{vendor} {model}' if model else f'{vendor} switch'
        if self._snmp_img_worker and self._snmp_img_worker.isRunning():
            self._snmp_img_worker.terminate()
        self.snmp_device_img.setText("⏳")
        self.snmp_device_name_lbl.setText(model or vendor)
        self._snmp_img_worker = DeviceImageWorker(query)
        self._snmp_img_worker.image_ready.connect(self._snmp_on_image_ready)
        self._snmp_img_worker.image_error.connect(self._snmp_on_image_error)
        self._snmp_img_worker.start()

    def _snmp_on_image_ready(self, img_bytes):
        pm = QPixmap()
        if pm.loadFromData(img_bytes):
            self._snmp_device_pixmap_full = pm
            scaled = pm.scaled(160, 80,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            self.snmp_device_img.setPixmap(scaled)
            self.snmp_device_img.setText("")

    def _snmp_on_image_error(self):
        self.snmp_device_img.setText("")

    def _snmp_show_device_image_fullsize(self):
        pm = getattr(self, '_snmp_device_pixmap_full', None)
        if not pm or pm.isNull():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Device Image")
        dlg.setModal(False)
        lbl = QLabel(dlg)
        scaled = pm.scaled(600, 400,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        lbl.setPixmap(scaled)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(dlg)
        lay.addWidget(lbl)
        dlg.adjustSize()
        dlg.show()

    def _snmp_filter_results(self, text):
        """Show/hide rows in the SNMP results table based on OID or value match."""
        text = text.strip().lower()
        for row in range(self.snmp_results_table.rowCount()):
            if not text:
                self.snmp_results_table.setRowHidden(row, False)
                continue
            match = False
            for col in (1, 2):  # OID and Value columns
                item = self.snmp_results_table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            self.snmp_results_table.setRowHidden(row, not match)

    def _snmp_index_item_clicked(self, item):
        """Scroll the results table to the first row of the clicked OID family."""
        family = item.data(Qt.ItemDataRole.UserRole)
        first_row = getattr(self, "_snmp_family_first_row", {}).get(family)
        if first_row is not None:
            target = self.snmp_results_table.item(first_row, 1)  # OID column is now at index 1
            if target:
                self.snmp_results_table.scrollToItem(
                    target, QAbstractItemView.ScrollHint.PositionAtTop
                )

    def _snmp_context_menu(self, pos):
        """Show context menu for SNMP results table"""
        item = self.snmp_results_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        oid = self.snmp_results_table.item(row, 1).text()  # OID column is now at index 1
        value = self.snmp_results_table.item(row, 2).text()  # Value column is now at index 2

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #e8e8e8;
            }
            QMenu::separator {
                height: 1px;
                background-color: #d0d0d0;
                margin: 4px 8px;
            }
        """)

        copy_oid_action = menu.addAction("Copy OID")
        copy_value_action = menu.addAction("Copy Value")
        menu.addSeparator()
        copy_both_action = menu.addAction("Copy OID = Value")

        action = menu.exec(self.snmp_results_table.viewport().mapToGlobal(pos))

        if action == copy_oid_action:
            QApplication.clipboard().setText(oid)
        elif action == copy_value_action:
            QApplication.clipboard().setText(value)
        elif action == copy_both_action:
            QApplication.clipboard().setText(f"{oid} = {value}")

    def _snmp_version_btn_clicked(self, version):
        """Handle version button click - ensure only one button is checked"""
        for btn in self.snmp_version_buttons.values():
            btn.setChecked(False)
        self.snmp_version_buttons[version].setChecked(True)
        self.snmp_current_version = version
        is_v3 = (version == "v3")
        for widget in self.snmp_v3_widgets.values():
            widget.setVisible(is_v3)

    def _snmp_type_btn_clicked(self, query_type):
        """Handle type button click - ensure only one button is checked"""
        for btn in self.snmp_type_buttons.values():
            btn.setChecked(False)
        self.snmp_type_buttons[query_type].setChecked(True)
        self.snmp_current_type = query_type
        label_map = {"snmpwalk": "SNMP WALK", "snmpget": "SNMP GET", "snmpgetnext": "SNMP GETNEXT"}
        self.snmp_execute_btn.setText(label_map.get(query_type, "SNMP WALK"))
        _ico = load_svg_icon_dual(self._snmp_type_icons.get(query_type), 18, '#ffffff', '#ffffff')
        if _ico:
            self.snmp_execute_btn.setIcon(_ico)
            self.snmp_execute_btn.setIconSize(QSize(18, 18))
        else:
            self.snmp_execute_btn.setIcon(QIcon())

    def _snmp_show_ip_menu(self):
        """Show a dropdown of all SSH profiles so the user can pick a host."""
        profiles = self.config.get_ssh_profiles()
        menu = QMenu(self)
        if not profiles:
            act = menu.addAction("No SSH profiles registered")
            act.setEnabled(False)
        else:
            for p in profiles:
                name = p.get('name', '')
                host = p.get('host', '')
                label = f"{name}  ({host})" if name else host
                action = menu.addAction(label)
                action.setData(host)
        btn = self.snmp_ip_profiles_btn
        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if chosen and chosen.isEnabled():
            host = chosen.data()
            self.snmp_host_input.setText(host)
            saved_community = self.config.get_snmp_ip_community(host)
            if saved_community:
                self.snmp_community_input.setText(saved_community)

    def _snmp_show_community_menu(self):
        """Show a dropdown of previously used SNMP community strings."""
        history = self.config.get_vuln_community_history()
        menu = QMenu(self)
        if not history:
            act = menu.addAction("No history yet")
            act.setEnabled(False)
        else:
            for c in history:
                menu.addAction(c)
        btn = self.snmp_community_hist_btn
        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if chosen and chosen.isEnabled():
            self.snmp_community_input.setText(chosen.text())

    # =========================================================
    #  WiFi Site Survey
    # =========================================================

    def create_wifi_page(self):
        """Create the WiFi Site Survey page"""
        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        combo_style = """
            QComboBox {
                border: 1px solid #d0d0d0; border-radius: 6px;
                padding: 2px 8px; background-color: #f5f5f5;
                color: #333333; font-size: 9pt;
            }
            QComboBox:focus { border: 2px solid #E91E63; }
        """

        # === Configuration group ===
        config_group = QGroupBox("WiFi Configuration")

        _lbl_style = "color: #555555; font-size: 9pt;"

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet(_lbl_style)
            l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            l.setFixedWidth(90)
            return l

        # ── Widgets ──────────────────────────────────────────────────────────

        self.wifi_iface_combo = FlatComboButton()
        self.wifi_iface_combo.setMinimumWidth(120)
        self.wifi_iface_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wifi_iface_combo.setToolTip("WiFi interface to use for scanning")
        self.wifi_iface_combo.setStyleSheet(combo_style)

        _refresh_icon_path = self.get_tab_icon_path('refresh.svg')
        _refresh_icon = load_svg_icon(_refresh_icon_path, 14) if _refresh_icon_path else None
        refresh_iface_btn = QPushButton()
        if _refresh_icon:
            refresh_iface_btn.setIcon(_refresh_icon)
            refresh_iface_btn.setIconSize(QSize(14, 14))
        else:
            refresh_iface_btn.setText("↻")
        refresh_iface_btn.setFixedSize(26, 26)
        refresh_iface_btn.setToolTip("Refresh interface list")
        refresh_iface_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_iface_btn.setStyleSheet("""
            QPushButton { background-color: #e0e0e0; border: 1px solid #bdbdbd;
                          border-radius: 6px; }
            QPushButton:hover { background-color: #bdbdbd; }
        """)
        refresh_iface_btn.clicked.connect(self._wifi_refresh_interfaces)

        _toggle_style = """
            QPushButton {
                background-color: #3a3a4a; border: 1px solid #555566;
                border-radius: 6px; color: #8b949e; font-size: 8pt;
                padding: 2px 12px; min-width: 64px;
            }
            QPushButton:checked {
                background-color: #E91E63; border-color: #E91E63; color: white;
            }
            QPushButton:hover { border-color: #999aaa; }
        """

        def _wifi_ico(name):
            p = self.get_icon_path(f'wifi_{name}.svg')
            return load_svg_icon_dual(p, 14, '#8b949e', '#ffffff') if p else None

        # Band selector: 3 exclusive toggle buttons
        self.wifi_band_btn_24  = QPushButton("2.4 GHz")
        self.wifi_band_btn_5   = QPushButton("5 GHz")
        self.wifi_band_btn_both= QPushButton("Both")
        for _btn, _tip, _ico_name in [
            (self.wifi_band_btn_24,   "Show 2.4 GHz channels only",       '24ghz'),
            (self.wifi_band_btn_5,    "Show 5 GHz channels only",         '5ghz'),
            (self.wifi_band_btn_both, "Show both bands simultaneously",   'both'),
        ]:
            _btn.setCheckable(True)
            _btn.setFixedWidth(90)
            _btn.setFixedHeight(24)
            _btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _btn.setToolTip(_tip)
            _btn.setStyleSheet(_toggle_style)
            _ico = _wifi_ico(_ico_name)
            if _ico:
                _btn.setIcon(_ico)
                _btn.setIconSize(QSize(14, 14))
        self.wifi_band_btn_5.setChecked(True)    # default: 5 GHz

        def _on_band_btn(btn):
            """Exclusive selection: uncheck the other two, update chart and table."""
            for b in (self.wifi_band_btn_24, self.wifi_band_btn_5, self.wifi_band_btn_both):
                b.setChecked(b is btn)
            self._wifi_update_chart()
            self._wifi_update_table()

        self.wifi_band_btn_24.clicked.connect(lambda: _on_band_btn(self.wifi_band_btn_24))
        self.wifi_band_btn_5.clicked.connect(lambda:  _on_band_btn(self.wifi_band_btn_5))
        self.wifi_band_btn_both.clicked.connect(lambda: _on_band_btn(self.wifi_band_btn_both))

        self.wifi_refresh_combo = FlatComboButton()
        self.wifi_refresh_combo.addItems(["2s", "5s", "10s", "15s", "30s"])
        self.wifi_refresh_combo.setCurrentText("2s")
        self.wifi_refresh_combo.setFixedWidth(62)
        self.wifi_refresh_combo.setToolTip("Auto-refresh interval")
        self.wifi_refresh_combo.setStyleSheet(combo_style)

        self.wifi_toggle_channel_btn = QPushButton("Spectrum")
        self.wifi_toggle_channel_btn.setCheckable(True)
        self.wifi_toggle_channel_btn.setChecked(True)
        self.wifi_toggle_channel_btn.setFixedWidth(90)
        self.wifi_toggle_channel_btn.setFixedHeight(24)
        self.wifi_toggle_channel_btn.setStyleSheet(_toggle_style)
        self.wifi_toggle_channel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_toggle_channel_btn.setToolTip("Show/hide channel graph")
        _ico = _wifi_ico('spectrum')
        if _ico:
            self.wifi_toggle_channel_btn.setIcon(_ico)
            self.wifi_toggle_channel_btn.setIconSize(QSize(14, 14))

        self.wifi_toggle_history_btn = QPushButton("Power")
        self.wifi_toggle_history_btn.setCheckable(True)
        self.wifi_toggle_history_btn.setChecked(False)
        self.wifi_toggle_history_btn.setFixedWidth(90)
        self.wifi_toggle_history_btn.setFixedHeight(24)
        self.wifi_toggle_history_btn.setStyleSheet(_toggle_style)
        self.wifi_toggle_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_toggle_history_btn.setToolTip("Show/hide signal history")
        _ico = _wifi_ico('power')
        if _ico:
            self.wifi_toggle_history_btn.setIcon(_ico)
            self.wifi_toggle_history_btn.setIconSize(QSize(14, 14))

        # ── Single flat grid ──────────────────────────────────────────────────
        config_grid_widget = QWidget()
        config_grid = QGridLayout(config_grid_widget)
        config_grid.setVerticalSpacing(6)
        config_grid.setHorizontalSpacing(8)
        config_grid.setContentsMargins(0, 0, 0, 0)
        config_grid.setColumnStretch(1, 1)

        iface_cell = QWidget()
        iface_cell_layout = QHBoxLayout(iface_cell)
        iface_cell_layout.setContentsMargins(0, 0, 0, 0)
        iface_cell_layout.setSpacing(4)
        iface_cell_layout.addWidget(self.wifi_iface_combo)
        iface_cell_layout.addWidget(refresh_iface_btn)
        iface_cell_layout.addWidget(self.wifi_refresh_combo)
        iface_cell_layout.addStretch()

        band_cell = QWidget()
        band_cell_layout = QHBoxLayout(band_cell)
        band_cell_layout.setContentsMargins(0, 0, 0, 0)
        band_cell_layout.setSpacing(4)
        band_cell_layout.addWidget(self.wifi_band_btn_24)
        band_cell_layout.addWidget(self.wifi_band_btn_5)
        band_cell_layout.addWidget(self.wifi_band_btn_both)
        band_cell_layout.addStretch()

        self.wifi_toggle_heatmap_btn = QPushButton("Heatmap")
        self.wifi_toggle_heatmap_btn.setCheckable(True)
        self.wifi_toggle_heatmap_btn.setChecked(True)
        self.wifi_toggle_heatmap_btn.setFixedWidth(90)
        self.wifi_toggle_heatmap_btn.setFixedHeight(24)
        self.wifi_toggle_heatmap_btn.setStyleSheet(_toggle_style)
        self.wifi_toggle_heatmap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_toggle_heatmap_btn.setToolTip("Show/hide waterfall heatmap")
        _ico = _wifi_ico('heatmap')
        if _ico:
            self.wifi_toggle_heatmap_btn.setIcon(_ico)
            self.wifi_toggle_heatmap_btn.setIconSize(QSize(14, 14))

        graphs_cell = QWidget()
        graphs_cell_layout = QHBoxLayout(graphs_cell)
        graphs_cell_layout.setContentsMargins(0, 0, 0, 0)
        graphs_cell_layout.setSpacing(4)
        graphs_cell_layout.addWidget(self.wifi_toggle_channel_btn)
        graphs_cell_layout.addWidget(self.wifi_toggle_history_btn)
        graphs_cell_layout.addWidget(self.wifi_toggle_heatmap_btn)
        graphs_cell_layout.addStretch()

        self.wifi_noise_btn = QPushButton("White Noise")
        self.wifi_noise_btn.setCheckable(True)
        self.wifi_noise_btn.setChecked(True)
        self.wifi_noise_btn.setFixedWidth(90)
        self.wifi_noise_btn.setFixedHeight(24)
        self.wifi_noise_btn.setStyleSheet(_toggle_style)
        self.wifi_noise_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_noise_btn.setToolTip("Overlay animated white noise on spectrum")
        _ico = _wifi_ico('noise')
        if _ico:
            self.wifi_noise_btn.setIcon(_ico)
            self.wifi_noise_btn.setIconSize(QSize(14, 14))

        self.wifi_glow_btn = QPushButton("Glow")
        self.wifi_glow_btn.setCheckable(True)
        self.wifi_glow_btn.setChecked(False)
        self.wifi_glow_btn.setFixedWidth(90)
        self.wifi_glow_btn.setFixedHeight(24)
        self.wifi_glow_btn.setStyleSheet(_toggle_style)
        self.wifi_glow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_glow_btn.setToolTip("Show neon glow burst at signal peaks")
        _ico = _wifi_ico('glow')
        if _ico:
            self.wifi_glow_btn.setIcon(_ico)
            self.wifi_glow_btn.setIconSize(QSize(14, 14))

        self.wifi_scanlines_btn = QPushButton("Scanlines")
        self.wifi_scanlines_btn.setCheckable(True)
        self.wifi_scanlines_btn.setChecked(True)
        self.wifi_scanlines_btn.setFixedWidth(90)
        self.wifi_scanlines_btn.setFixedHeight(24)
        self.wifi_scanlines_btn.setStyleSheet(_toggle_style)
        self.wifi_scanlines_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_scanlines_btn.setToolTip("CRT scanlines overlay (retro style)")
        _ico = _wifi_ico('scanlines')
        if _ico:
            self.wifi_scanlines_btn.setIcon(_ico)
            self.wifi_scanlines_btn.setIconSize(QSize(14, 14))

        effects_cell = QWidget()
        effects_layout = QHBoxLayout(effects_cell)
        effects_layout.setContentsMargins(0, 0, 0, 0)
        effects_layout.setSpacing(4)
        effects_layout.addWidget(self.wifi_noise_btn)
        effects_layout.addWidget(self.wifi_glow_btn)
        effects_layout.addWidget(self.wifi_scanlines_btn)
        effects_layout.addStretch()

        self._hist_window_s = 120  # current power-scale window value (seconds)

        self._hist_audio_chk = QCheckBox("Audio feedback")
        self._hist_audio_chk.setChecked(True)
        self._hist_audio_chk.setToolTip(
            "Emit tones reflecting signal strength; distinct tone on signal loss")
        self._hist_audio_chk.setStyleSheet("color: #8b949e; font-size: 8pt;")

        _chk_style = "color: #8b949e; font-size: 8pt;"
        self._avoid_dfs_chk = QCheckBox("Avoid DFS Channels")
        self._avoid_dfs_chk.setChecked(True)
        self._avoid_dfs_chk.setToolTip(
            "When checked, DFS channels (52–140) are excluded from best-channel selection.\n"
            "Uncheck to allow DFS channels to be recommended.")
        self._avoid_dfs_chk.setStyleSheet(_chk_style)

        audio_dfs_cell = QWidget()
        audio_dfs_layout = QHBoxLayout(audio_dfs_cell)
        audio_dfs_layout.setContentsMargins(0, 0, 0, 0)
        audio_dfs_layout.setSpacing(16)
        audio_dfs_layout.addWidget(self._hist_audio_chk)
        audio_dfs_layout.addWidget(self._avoid_dfs_chk)
        audio_dfs_layout.addStretch()

        config_grid.addWidget(_lbl("Interface:"),    0, 0)
        config_grid.addWidget(iface_cell,            0, 1)
        config_grid.addWidget(_lbl("Band:"),         1, 0)
        config_grid.addWidget(band_cell,             1, 1)
        config_grid.addWidget(_lbl("Show:"),         2, 0)
        config_grid.addWidget(graphs_cell,           2, 1)
        config_grid.addWidget(_lbl("Effects:"),      3, 0)
        config_grid.addWidget(effects_cell,          3, 1)
        config_grid.addWidget(_lbl("Options:"),      4, 0)
        config_grid.addWidget(audio_dfs_cell,        4, 1)

        config_layout = QHBoxLayout()
        config_layout.setContentsMargins(12, 8, 12, 10)
        config_layout.addWidget(config_grid_widget)
        config_group.setLayout(config_layout)
        shadow1 = QGraphicsDropShadowEffect()
        shadow1.setBlurRadius(12); shadow1.setXOffset(0); shadow1.setYOffset(2)
        shadow1.setColor(QColor(0, 0, 0, 25))
        config_group.setGraphicsEffect(shadow1)
        main_layout.addWidget(config_group)

        # === Results table ===
        results_group = QGroupBox("Networks")
        results_layout = QVBoxLayout()
        results_layout.setContentsMargins(8, 4, 8, 6)
        results_layout.setSpacing(4)

        self.wifi_table = QTableWidget()
        self.wifi_table.setColumnCount(14)
        self.wifi_table.setHorizontalHeaderLabels(
            ["👁", "SSID", "BSSID", "Vendor", "Signal", "SNR", "Noise", "Ch", "BW", "WiFi", "Band", "Rate", "Security", "Score"]
        )
        # Column 0: Visibility checkbox
        self.wifi_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.wifi_table.setColumnWidth(0, 35)
        # Column 1: SSID
        self.wifi_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.wifi_table.setColumnWidth(1, 180)
        # Column 2: BSSID
        self.wifi_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.wifi_table.setColumnWidth(2, 130)
        # Column 3: Vendor (stretch)
        self.wifi_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        # Other columns: Signal(4), SNR(5), Noise(6), Ch(7), BW(8), WiFi(9), Band(10), Rate(11), Security(12), Score(13)
        for col, w in [(4, 110), (5, 110), (6, 75), (7, 40), (8, 60), (9, 62), (10, 55), (11, 100), (12, 110), (13, 55)]:
            self.wifi_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.wifi_table.setColumnWidth(col, w)
        self.wifi_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.wifi_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.wifi_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.wifi_table.setSortingEnabled(True)
        self.wifi_table.verticalHeader().setVisible(False)
        self.wifi_table.setAlternatingRowColors(True)
        self.wifi_table.setStyleSheet("""
            QTableWidget {
                background-color: #e8e8e8; border: 1px solid #d0d0d0;
                border-radius: 6px; color: #333333; font-size: 9pt;
                gridline-color: #d0d0d0; alternate-background-color: #f0f0f0;
            }
            QTableWidget::item { padding: 3px; }
            QTableWidget::item:selected { background-color: #E91E63; color: white; }
            QHeaderView::section {
                background-color: #d0d0d0; color: #333333; padding: 4px;
                border: none; font-weight: bold; font-size: 9pt;
            }
        """)
        results_layout.addWidget(self.wifi_table)

        # Connect double-click to show BSSID details
        self.wifi_table.itemDoubleClicked.connect(self._wifi_show_bssid_details)

        # Connect cell changed to handle visibility checkbox
        self.wifi_table.itemChanged.connect(self._wifi_visibility_changed)

        # Connect row selection to highlight the curve in the chart
        self.wifi_table.currentItemChanged.connect(self._wifi_table_selection_changed)

        results_group.setLayout(results_layout)
        shadow2 = QGraphicsDropShadowEffect()
        shadow2.setBlurRadius(12); shadow2.setXOffset(0); shadow2.setYOffset(2)
        shadow2.setColor(QColor(0, 0, 0, 25))
        results_group.setGraphicsEffect(shadow2)
        main_layout.addWidget(results_group, 3)

        # === Channel chart ===
        chart_group = QWidget()
        chart_group.setObjectName("channelUsagePanel")
        chart_group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(4, 2, 4, 2)
        chart_layout.setSpacing(0)

        # Band buttons connect via _on_band_btn (defined during widget creation)

        self.wifi_channel_chart = WifiChannelChart()
        self.wifi_channel_chart.carrier_clicked.connect(self._on_chart_carrier_clicked)
        self.wifi_noise_btn.toggled.connect(self.wifi_channel_chart.set_noise)
        self.wifi_glow_btn.toggled.connect(self.wifi_channel_chart.set_glow)
        self.wifi_scanlines_btn.toggled.connect(self.wifi_channel_chart.set_scanlines)

        chart_layout.addWidget(self.wifi_channel_chart)

        self.wifi_heatmap = WifiHeatmapWidget()
        chart_layout.addWidget(self.wifi_heatmap)

        chart_group.setLayout(chart_layout)
        chart_group.setStyleSheet("""
            QWidget#channelUsagePanel {
                background-color: #0D1117;
                border: 1px solid #2A3040;
                border-radius: 10px;
            }
            QWidget#channelUsagePanel QLabel {
                background: transparent;
                border: none;
            }
        """)
        shadow3 = QGraphicsDropShadowEffect()
        shadow3.setBlurRadius(20); shadow3.setXOffset(0); shadow3.setYOffset(4)
        shadow3.setColor(QColor(0, 0, 0, 70))
        chart_group.setGraphicsEffect(shadow3)

        # Keep reference so the close button eventFilter can find it
        self.wifi_chart_group = chart_group

        # Style for overlay X buttons (shared by both charts)
        _close_btn_style = """
            QPushButton {
                background-color: rgba(20,20,30,180);
                color: #8b949e; border: none; border-radius: 6px;
                font-size: 9pt; font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(200,40,40,200); color: white; }
        """
        self._close_channel_btn = QPushButton("✕", chart_group)
        self._close_channel_btn.setFixedSize(20, 20)
        self._close_channel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_channel_btn.setStyleSheet(_close_btn_style)
        self._close_channel_btn.clicked.connect(
            lambda: self._wifi_set_chart_visible('channel', False))
        self._close_channel_btn.raise_()
        chart_group.installEventFilter(self)

        # === Signal history widget (shown side-by-side when a network is selected) ===
        self.wifi_signal_history = SignalHistoryWidget()
        self.wifi_signal_history.setObjectName("signalHistoryPanel")
        self.wifi_signal_history.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.wifi_signal_history.setStyleSheet("""
            QWidget#signalHistoryPanel {
                background-color: #0D1117;
                border: 1px solid #2A3040;
                border-radius: 10px;
            }
        """)
        self._close_history_btn = QPushButton("✕", self.wifi_signal_history)
        self._close_history_btn.setFixedSize(20, 20)
        self._close_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_history_btn.setStyleSheet(_close_btn_style)
        self._close_history_btn.clicked.connect(
            lambda: self._wifi_set_chart_visible('history', False))
        self._close_history_btn.raise_()

        # Power-scale overlay: − label +
        _scale_btn_style = """
            QPushButton {
                background-color: rgba(233, 30, 99, 210);
                color: white; border: none; border-radius: 5px;
                font-size: 14pt; font-weight: bold;
            }
            QPushButton:hover   { background-color: rgba(233, 30, 99, 255); }
            QPushButton:pressed { background-color: rgba(160, 15, 65,  255); }
        """
        _scale_lbl_style = (
            "color: white; font-size: 9pt; font-weight: bold; "
            "background-color: rgba(15, 15, 25, 210); border-radius: 6px; "
            "border: 1px solid rgba(233,30,99,160); padding: 0px 4px;"
        )

        self._hist_scale_minus = QPushButton("−", self.wifi_signal_history)
        self._hist_scale_minus.setFixedSize(26, 26)
        self._hist_scale_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hist_scale_minus.setStyleSheet(_scale_btn_style)
        self._hist_scale_minus.setToolTip("Increase time window (zoom out)")

        self._hist_scale_lbl = QLabel(f"{self._hist_window_s}s", self.wifi_signal_history)
        self._hist_scale_lbl.setFixedSize(40, 26)
        self._hist_scale_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hist_scale_lbl.setStyleSheet(_scale_lbl_style)

        self._hist_scale_plus = QPushButton("+", self.wifi_signal_history)
        self._hist_scale_plus.setFixedSize(26, 26)
        self._hist_scale_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hist_scale_plus.setStyleSheet(_scale_btn_style)
        self._hist_scale_plus.setToolTip("Decrease time window (zoom in)")

        for _w in (self._hist_scale_minus, self._hist_scale_lbl, self._hist_scale_plus):
            _w.raise_()

        self.wifi_signal_history.installEventFilter(self)
        self.wifi_signal_history.hide()


        # Connect toggle buttons (defined in config section above)
        self.wifi_toggle_channel_btn.toggled.connect(
            lambda checked: self._wifi_set_chart_visible('channel', checked))
        self.wifi_toggle_history_btn.toggled.connect(
            lambda checked: self._wifi_set_chart_visible('history', checked))
        self.wifi_toggle_heatmap_btn.toggled.connect(
            lambda checked: self._wifi_set_chart_visible('heatmap', checked))

        # Wire power-scale overlay buttons
        def _hist_scale_step(delta):
            self._hist_window_s = max(30, min(600, self._hist_window_s + delta))
            self._hist_scale_lbl.setText(f'{self._hist_window_s}s')
            self.wifi_signal_history.set_window_s(self._hist_window_s)
        self._hist_scale_minus.clicked.connect(lambda: _hist_scale_step(+30))
        self._hist_scale_plus.clicked.connect(lambda: _hist_scale_step(-30))
        self._hist_audio_chk.toggled.connect(self.wifi_signal_history.set_audio)
        self._avoid_dfs_chk.toggled.connect(
            lambda checked: setattr(self.wifi_channel_chart, '_avoid_dfs', checked))
        self.wifi_scanlines_btn.toggled.connect(self.wifi_signal_history.set_scanlines)

        charts_row = QWidget()
        charts_layout = QHBoxLayout(charts_row)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(6)
        charts_layout.addWidget(chart_group, 1)
        charts_layout.addWidget(self.wifi_signal_history, 1)
        main_layout.addWidget(charts_row, 4)

        # === Bottom button row ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.wifi_export_btn = QPushButton("Export CSV")
        self.wifi_export_btn.setFixedWidth(110)
        self.wifi_export_btn.setFixedHeight(36)
        self.wifi_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_export_btn.setEnabled(False)
        self.wifi_export_btn.setStyleSheet("""
            QPushButton { background-color: #e0e0e0; color: #333333; border: none;
                          border-radius: 6px; padding: 6px 16px; font-size: 9pt; }
            QPushButton:hover { background-color: #bdbdbd; }
            QPushButton:disabled { color: #aaaaaa; }
        """)
        self.wifi_export_btn.clicked.connect(self._wifi_export_csv)
        _ico = load_svg_icon_dual(self.get_icon_path('wifi_export.svg'), 16, '#555555', '#555555')
        if _ico:
            self.wifi_export_btn.setIcon(_ico)
            self.wifi_export_btn.setIconSize(QSize(16, 16))

        self.wifi_scan_btn = QPushButton("Start Survey")
        self.wifi_scan_btn.setMinimumHeight(40)
        self.wifi_scan_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.wifi_scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #E91E63; color: #ffffff;
                border: none; border-radius: 8px;
                padding: 10px; font-weight: bold; font-size: 11pt;
            }
            QPushButton:hover { background-color: #C2185B; }
            QPushButton:disabled { background-color: #757575; }
        """)
        self.wifi_scan_btn.clicked.connect(self._start_wifi_scan)
        _ico = load_svg_icon_dual(self.get_icon_path('wifi_scan.svg'), 20, '#ffffff', '#ffffff')
        if _ico:
            self.wifi_scan_btn.setIcon(_ico)
            self.wifi_scan_btn.setIconSize(QSize(20, 20))

        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.wifi_scan_btn.setGraphicsEffect(_btn_shadow)
        btn_row.addWidget(self.wifi_export_btn)
        btn_row.addWidget(self.wifi_scan_btn, 1)

        # Status label
        self.wifi_status_label = QLabel("Ready — press SCAN to search for networks")
        self.wifi_status_label.setStyleSheet(
            "color: #777777; font-size: 8pt; padding: 2px 4px;"
        )
        self.wifi_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        main_layout.addLayout(btn_row)
        main_layout.addWidget(self.wifi_status_label)

        page.setLayout(main_layout)

        # Auto-refresh timer
        self._wifi_timer = None
        # Survey state
        self._wifi_survey_start    = None   # monotonic timestamp when survey started
        self._wifi_survey_ch_load  = {}     # accumulated channel loads across all scans
        self._wifi_elapsed_timer   = None   # QTimer that updates the button text every second

        # Populate interfaces on creation
        self._wifi_refresh_interfaces()

        return page

    def _start_traceroute(self):
        """Start or stop traceroute / MTR / ping operation"""
        # Check if ping is already running - toggle to stop
        if hasattr(self, 'ping_worker') and self.ping_worker and self.ping_worker.isRunning():
            self.ping_worker.stop()
            self.traceroute_btn.setText("Stopping...")
            self.traceroute_btn.setEnabled(False)
            return

        # Check if MTR is already running - toggle to stop
        if hasattr(self, 'mtr_worker') and self.mtr_worker and self.mtr_worker.isRunning():
            self.mtr_worker.stop()
            self.traceroute_btn.setText("Stopping...")
            self.traceroute_btn.setEnabled(False)
            return

        # Check if traceroute is already running - toggle to stop
        if hasattr(self, 'traceroute_worker') and self.traceroute_worker and self.traceroute_worker.isRunning():
            self.traceroute_worker.stop()
            self.traceroute_btn.setText("Stopping...")
            self.traceroute_btn.setEnabled(False)
            return

        method = self.traceroute_current_method

        # Branch to ping methods
        if method in ('Ping ICMP', 'Ping TCP'):
            self._start_ping()
            return

        # Branch to MTR if 'ICMP' or legacy 'MTR' is selected
        if method in ('MTR', 'ICMP'):
            self._start_mtr()
            return

        # Validate input
        target = self.traceroute_target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "Traceroute", "Please enter a target host or IP address.")
            return

        # Get parameters
        max_hops = int(self.traceroute_max_hops_combo.currentText())
        timeout = int(self.traceroute_timeout_combo.currentText().rstrip('s'))
        dns_lookup = self.traceroute_dns_checkbox.isChecked()
        method = self.traceroute_current_method

        # Get and validate port for TCP/UDP
        port = None
        if method in ('TCP', 'UDP'):
            port_text = self.traceroute_port_input.text().strip()
            if not port_text:
                QMessageBox.warning(self, "Traceroute", f"Please enter a port number for {method} traceroute.")
                return
            try:
                port = int(port_text)
                if port < 1 or port > 65535:
                    QMessageBox.warning(self, "Traceroute", "Port must be between 1 and 65535.")
                    return
            except ValueError:
                QMessageBox.warning(self, "Traceroute", "Invalid port number. Please enter a valid integer.")
                return

        # For TCP/UDP, check if traceroute has raw socket capability; grant it if needed
        if method in ('TCP', 'UDP'):
            if not self._ensure_traceroute_cap_net_raw():
                return  # User cancelled or wrong password

        # Clear previous results
        self.traceroute_results_table.setSortingEnabled(False)
        self.traceroute_results_table.setRowCount(0)
        self.traceroute_viz_widget.clear()
        self._traceroute_hop_stats = {}

        # Store method and port for status updates
        self._current_traceroute_method = method
        self._current_traceroute_port = port

        # Update status with method info
        if method in ('TCP', 'UDP'):
            self.traceroute_results_group.setTitle(f"Results (tracing via {method} port {port}...)")
        else:
            self.traceroute_results_group.setTitle(f"Results (tracing via {method}...)")

        # Update button state
        self.traceroute_btn.setText("Tracing 0%")
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #616161;
            }
        """)

        # Open latency graph immediately if auto-show is enabled
        if self.traceroute_autograph_checkbox.isChecked():
            self._show_latency_graph_dialog()

        # Create and start worker
        self.traceroute_worker = TracerouteWorker(target, max_hops, timeout, dns_lookup, method, port)
        self.traceroute_worker.hop_found.connect(self._on_traceroute_hop)
        self.traceroute_worker.route_progress.connect(
            lambda p: self.traceroute_btn.setText(f"Tracing {p}%")
        )
        self.traceroute_worker.route_finished.connect(self._on_traceroute_finished)
        self.traceroute_worker.route_error.connect(self._on_traceroute_error)
        self.traceroute_worker.start()

    def _on_traceroute_hop(self, hop_num, ip, hostname, latency, stdev):
        """Handle new traceroute hop"""
        row = self.traceroute_results_table.rowCount()
        self.traceroute_results_table.insertRow(row)

        # Hop number
        hop_item = QTableWidgetItem(str(hop_num))
        hop_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        hop_item.setData(Qt.ItemDataRole.UserRole, hop_num)
        self.traceroute_results_table.setItem(row, 0, hop_item)

        # Country
        cty_item = QTableWidgetItem("")
        cty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.traceroute_results_table.setItem(row, 1, cty_item)

        # IP address
        ip_item = QTableWidgetItem(ip)
        self.traceroute_results_table.setItem(row, 2, ip_item)

        # Hostname
        hostname_item = QTableWidgetItem(hostname)
        self.traceroute_results_table.setItem(row, 3, hostname_item)

        # Latency with color coding
        if ip == "*":
            latency_item = QTableWidgetItem("* * *")
            latency_item.setForeground(QColor("#9E9E9E"))
        else:
            latency_item = QTableWidgetItem(f"{latency:.1f}")
            latency_item.setData(Qt.ItemDataRole.UserRole, latency)
            if latency < 20:
                latency_item.setForeground(QColor("#4CAF50"))  # Green
            elif latency < 50:
                latency_item.setForeground(QColor("#FFC107"))  # Yellow
            elif latency < 100:
                latency_item.setForeground(QColor("#FF9800"))  # Orange
            else:
                latency_item.setForeground(QColor("#F44336"))  # Red
        latency_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.traceroute_results_table.setItem(row, 4, latency_item)

        # StDev column
        if ip == "*" or stdev == 0.0:
            stdev_item = QTableWidgetItem("—")
            stdev_item.setForeground(QColor("#9E9E9E"))
        else:
            stdev_item = QTableWidgetItem(f"{stdev:.1f}")
            stdev_item.setForeground(QColor("#80CBC4"))
        stdev_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.traceroute_results_table.setItem(row, 5, stdev_item)

        # Trigger geoip lookup
        self._trigger_geo_lookup(ip, is_mtr=False, hop_num=None, row_idx=row)

        # Save per-hop stats (loss N/A for single-pass traceroute)
        self._traceroute_hop_stats[hop_num] = (0.0, stdev)

        # Update visualization
        self.traceroute_viz_widget.add_hop(hop_num, ip, hostname, latency)

        # Refresh latency graph in real time if open
        if self._latency_graph_widget is not None:
            self._latency_graph_widget.hop_stats = self._traceroute_hop_stats
            self._latency_graph_widget.update()

        # Update group title with method info
        method = getattr(self, '_current_traceroute_method', 'ICMP')
        port = getattr(self, '_current_traceroute_port', None)

        if method in ('TCP', 'UDP') and port:
            self.traceroute_results_group.setTitle(f"Results (tracing via {method}:{port}... {row + 1} hops)")
        else:
            self.traceroute_results_group.setTitle(f"Results (tracing via {method}... {row + 1} hops)")

    def _on_traceroute_finished(self, total_hops, target_ip):
        """Handle traceroute completion"""
        # Include method info in final status
        method = getattr(self, '_current_traceroute_method', 'ICMP')
        port = getattr(self, '_current_traceroute_port', None)

        if method in ('TCP', 'UDP') and port:
            self.traceroute_results_group.setTitle(
                f"Results — {total_hops} hop{'s' if total_hops != 1 else ''} to {target_ip} via {method}:{port}"
            )
        else:
            self.traceroute_results_group.setTitle(
                f"Results — {total_hops} hop{'s' if total_hops != 1 else ''} to {target_ip} via {method}"
            )

        self.traceroute_results_table.setSortingEnabled(True)
        self._reset_traceroute_button()
        # Refresh final graph state; open only if not already visible
        if self._latency_graph_widget is not None:
            self._latency_graph_widget.update()
        elif self.traceroute_autograph_checkbox.isChecked():
            self._show_latency_graph_dialog()

    def _on_traceroute_error(self, error_msg):
        """Handle traceroute error"""
        QMessageBox.warning(self, "Traceroute", f"Traceroute error:\n\n{error_msg}")
        self._reset_traceroute_button()

    def _reset_traceroute_button(self):
        """Reset traceroute button to initial state"""
        self.traceroute_btn.setText("TRACEROUTE")
        self.traceroute_btn.setEnabled(True)
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #00ACC1;
            }
            QPushButton:pressed {
                background-color: #0097A7;
            }
        """)

    # ─── MTR methods ──────────────────────────────────────────────────────────

    def _trigger_geo_lookup(self, ip, is_mtr, hop_num, row_idx):
        """Enqueue IP for background Geo/Flag resolution"""
        if not ip or ip == "*":
            return
        self.geo_flag_worker.enqueue(ip, is_mtr, hop_num, row_idx)

    def _on_geo_flag_resolved(self, ip, cc, flag, hop_num, row_idx, is_mtr):
        """Callback when Geo IP is resolved to update the table directly safely from main thread."""
        t = self.traceroute_results_table
        if is_mtr:
            if hop_num in self._mtr_hop_rows:
                row = self._mtr_hop_rows[hop_num]
                ip_item = t.item(row, 2)
                if ip_item and ip_item.text() == ip:
                    cty_item = QTableWidgetItem(flag)
                    cty_item.setToolTip(cc)
                    cty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    t.setItem(row, 1, cty_item)
        else:
            if row_idx is not None and row_idx < t.rowCount():
                ip_item = t.item(row_idx, 2)
                if ip_item and ip_item.text() == ip:
                    cty_item = QTableWidgetItem(flag)
                    cty_item.setToolTip(cc)
                    cty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    t.setItem(row_idx, 1, cty_item)

    def _start_mtr(self):
        """Start MTR monitoring session"""
        target = self.traceroute_target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "MTR", "Please enter a target host or IP address.")
            return

        interval = int(self.mtr_interval_combo.currentText().rstrip('s'))
        packets = int(self.mtr_packets_combo.currentText())
        max_hops = int(self.traceroute_max_hops_combo.currentText())
        dns_lookup = self.traceroute_dns_checkbox.isChecked()

        self.traceroute_results_table.setSortingEnabled(False)
        self.traceroute_results_table.setRowCount(0)
        self._switch_table_to_mtr_mode()
        self.traceroute_viz_widget.clear()
        self._traceroute_hop_stats = {}
        self._mtr_hop_rows = {}      # hop_num (0-indexed) → row index
        self._mtr_target  = target
        self._mtr_cycle   = 0

        self.traceroute_results_group.setTitle(f"MTR — monitoring route to {target}…")

        # Button → STOP MTR (grey)
        self.traceroute_btn.setText("STOP MTR")
        self.traceroute_btn.setEnabled(True)
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #616161; }
            QPushButton:pressed { background-color: #424242; }
        """)

        # Open latency graph immediately if auto-show is enabled
        if self.traceroute_autograph_checkbox.isChecked():
            self._show_latency_graph_dialog()

        self.mtr_worker = MtrWorker(target, max_hops, interval, dns_lookup, packets)
        self.mtr_worker.hop_discovered.connect(self._on_mtr_hop_discovered)
        self.mtr_worker.hop_updated.connect(self._on_mtr_hop_updated)
        self.mtr_worker.cycle_complete.connect(self._on_mtr_cycle)
        self.mtr_worker.mtr_error.connect(self._on_mtr_error)
        self.mtr_worker.mtr_finished.connect(self._on_mtr_finished)
        self.mtr_worker.start()

    def _on_mtr_hop_discovered(self, hop_num, ip, hostname):
        """Insert or update a hop row in the MTR table"""
        t = self.traceroute_results_table
        # Update hostname if row already exists
        if hop_num in self._mtr_hop_rows:
            row = self._mtr_hop_rows[hop_num]
            t.item(row, 2).setText(ip)
            t.item(row, 3).setText(hostname)
            return

        # New hop — insert row
        row = t.rowCount()
        t.insertRow(row)
        self._mtr_hop_rows[hop_num] = row

        hop_item = QTableWidgetItem(str(hop_num + 1))   # display 1-indexed
        hop_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setItem(row, 0, hop_item)
        
        cty_item = QTableWidgetItem("")
        cty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setItem(row, 1, cty_item)
        
        t.setItem(row, 2, QTableWidgetItem(ip))
        t.setItem(row, 3, QTableWidgetItem(hostname))

        for col in range(4, 10):
            placeholder = QTableWidgetItem("—")
            placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setItem(row, col, placeholder)
            
        # Trigger geoip lookup
        self._trigger_geo_lookup(ip, is_mtr=True, hop_num=hop_num, row_idx=row)

    def _on_mtr_hop_updated(self, hop_num, loss_pct, avg, best, worst, stdev, sent):
        """Update statistics for an existing MTR hop row"""
        if hop_num not in self._mtr_hop_rows:
            return
        row = self._mtr_hop_rows[hop_num]
        t   = self.traceroute_results_table

        def _lat_color(ms):
            if ms < 20:   return QColor("#4CAF50")
            if ms < 50:   return QColor("#FFC107")
            if ms < 100:  return QColor("#FF9800")
            return QColor("#F44336")

        def _loss_color(pct):
            if pct == 0:   return QColor("#4CAF50")
            if pct < 5:    return QColor("#FFC107")
            if pct < 20:   return QColor("#FF9800")
            return QColor("#F44336")

        def _cell(text, color=None, align=Qt.AlignmentFlag.AlignCenter):
            item = QTableWidgetItem(text)
            item.setTextAlignment(align)
            if color:
                item.setForeground(color)
            return item

        loss_item = _cell(f"{loss_pct:.1f}%", _loss_color(loss_pct))
        snt_item  = _cell(str(sent))
        avg_item  = _cell(f"{avg:.1f}", _lat_color(avg))
        best_item = _cell(f"{best:.1f}", _lat_color(best))
        wrst_item = _cell(f"{worst:.1f}", _lat_color(worst))
        stdev_item = _cell(f"{stdev:.1f}")

        t.setItem(row, 4, loss_item)
        t.setItem(row, 5, snt_item)
        t.setItem(row, 6, avg_item)
        t.setItem(row, 7, best_item)
        t.setItem(row, 8, wrst_item)
        t.setItem(row, 9, stdev_item)

        # Keep visualization widget updated with current avg latency
        ip = t.item(row, 1).text() if t.item(row, 1) else "*"
        hostname = t.item(row, 2).text() if t.item(row, 2) else ip
        display_hop = hop_num + 1
        # Update existing hop or add — use a dict to avoid duplicates
        existing = next((i for i, h in enumerate(self.traceroute_viz_widget.hops)
                         if h[0] == display_hop), None)
        if existing is not None:
            self.traceroute_viz_widget.hops[existing] = (display_hop, ip, hostname, avg)
            self.traceroute_viz_widget.update()
        else:
            self.traceroute_viz_widget.add_hop(display_hop, ip, hostname, avg)

        # Save per-hop stats for graph
        self._traceroute_hop_stats[display_hop] = (loss_pct, stdev)

        # Refresh latency graph in real time if open
        if self._latency_graph_widget is not None:
            self._latency_graph_widget.hop_stats = self._traceroute_hop_stats
            self._latency_graph_widget.update()

    def _on_mtr_cycle(self, cycle_num):
        """Update title with current cycle count"""
        self._mtr_cycle = cycle_num
        target = getattr(self, '_mtr_target', '')
        self.traceroute_results_group.setTitle(
            f"MTR — cycle {cycle_num} → {target}"
        )

    def _on_mtr_error(self, msg):
        """Handle MTR error"""
        QMessageBox.warning(self, "MTR", msg)
        self._reset_mtr_button()

    def _on_mtr_finished(self):
        """Handle MTR completion (fixed cycles reached or stopped)"""
        cycles = getattr(self, '_mtr_cycle', 0)
        target = getattr(self, '_mtr_target', '')

        # Hide duplicate last hop: MTR probes one TTL beyond the destination,
        # causing the target IP to appear twice in consecutive rows.
        t = self.traceroute_results_table
        rc = t.rowCount()
        if rc >= 2:
            ip_last = t.item(rc - 1, 2)
            ip_prev = t.item(rc - 2, 2)
            if (ip_last and ip_prev
                    and ip_last.text() == ip_prev.text()
                    and ip_last.text() not in ('', '*')):
                t.setRowHidden(rc - 1, True)
                if self.traceroute_viz_widget.hops:
                    self.traceroute_viz_widget.hops.pop()
                    self.traceroute_viz_widget.update()

        self.traceroute_results_group.setTitle(
            f"MTR — {cycles} cycle{'s' if cycles != 1 else ''} to {target}"
        )
        self._reset_mtr_button()

        # Refresh or open latency graph when MTR finishes
        if self.traceroute_viz_widget.hops:
            if self._latency_graph_widget is not None:
                self._latency_graph_widget.update()
            elif self.traceroute_autograph_checkbox.isChecked():
                self._show_latency_graph_dialog()

    def _reset_mtr_button(self):
        """Reset button to 'TRACEROUTE' state after MTR (keeps MTR table columns)"""
        self.traceroute_btn.setText("TRACEROUTE")
        self.traceroute_btn.setEnabled(True)
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #00ACC1; }
            QPushButton:pressed { background-color: #0097A7; }
        """)

    # ──────────────────────────────────────────────────────────────────────────

    def _switch_table_to_mtr_mode(self):
        """Switch the traceroute results table to 10-column MTR statistics mode"""
        t = self.traceroute_results_table
        t.setColumnCount(10)
        t.setHorizontalHeaderLabels(
            ["Hop", "Cty", "IP Address", "Hostname", "Loss%", "Snt", "Avg", "Best", "Wrst", "StDev"]
        )
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col in range(4, 10):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            t.setColumnWidth(col, 72)
        t.setColumnWidth(0, 50)
        t.setColumnWidth(1, 40)
        # Hide Best and Worst columns; StDev remains visible
        for col in (7, 8):
            t.setColumnHidden(col, True)
        t.setColumnHidden(9, False)

    def _switch_table_to_traceroute_mode(self):
        """Restore the results table to standard 6-column traceroute mode"""
        t = self.traceroute_results_table
        t.setColumnCount(6)
        t.setHorizontalHeaderLabels(["Hop", "Cty", "IP Address", "Hostname", "Latency (ms)", "StDev (ms)"])
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(0, 60)
        t.setColumnWidth(1, 40)
        t.setColumnWidth(4, 100)
        t.setColumnWidth(5, 90)

    def _switch_table_to_ping_mode(self):
        """Switch the results table to 4-column ping mode"""
        t = self.traceroute_results_table
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(["#", "Status", "RTT (ms)", "Info"])
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        t.setColumnWidth(0, 45)
        t.setColumnWidth(1, 70)
        t.setColumnWidth(2, 90)

    def _apply_ping_btn_style(self):
        """Reset action button to PING state (cyan)"""
        self.traceroute_btn.setText("PING")
        self.traceroute_btn.setEnabled(True)
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #00ACC1; }
            QPushButton:pressed { background-color: #0097A7; }
        """)

    def _start_ping(self):
        """Start ICMP or TCP ping"""
        target = self.traceroute_target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "Ping", "Please enter a target host or IP address.")
            return

        method   = self.traceroute_current_method
        count    = int(self.mtr_packets_combo.currentText())
        interval = int(self.mtr_interval_combo.currentText().rstrip('s'))
        timeout  = int(self.traceroute_timeout_combo.currentText().rstrip('s'))

        port = None
        if method == 'Ping TCP':
            port_text = self.traceroute_port_input.text().strip()
            try:
                port = int(port_text) if port_text else 80
                if port < 1 or port > 65535:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Ping", "Invalid port number.")
                return

        self.traceroute_results_table.setSortingEnabled(False)
        self.traceroute_results_table.setRowCount(0)
        self._switch_table_to_ping_mode()

        if method == 'Ping TCP':
            self.traceroute_results_group.setTitle(f"Results — TCP ping to {target}:{port}")
            self.ping_worker = PingTCPWorker(target, port, count, interval, timeout)
        else:
            self.traceroute_results_group.setTitle(f"Results — ICMP ping to {target}")
            self.ping_worker = PingWorker(target, count, interval, timeout)

        self.ping_worker.ping_result.connect(self._on_ping_result)
        self.ping_worker.ping_finished.connect(self._on_ping_finished)
        self.ping_worker.ping_error.connect(self._on_ping_error)

        self._ping_count = count
        self._ping_results = []
        self.traceroute_btn.setText(f"STOP  0/{count}")
        self.traceroute_btn.setEnabled(True)
        self.traceroute_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #616161; }
            QPushButton:pressed { background-color: #424242; }
        """)
        self.ping_worker.start()

    def _on_ping_result(self, seq, success, rtt_ms, info):
        """Add one ping reply row to the table"""
        t = self.traceroute_results_table
        row = t.rowCount()
        t.insertRow(row)

        seq_item = QTableWidgetItem(str(seq))
        seq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setItem(row, 0, seq_item)

        if success:
            status_item = QTableWidgetItem("✓")
            status_item.setForeground(QColor("#4CAF50"))
        else:
            status_item = QTableWidgetItem("✗")
            status_item.setForeground(QColor("#F44336"))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setItem(row, 1, status_item)

        if success:
            rtt_item = QTableWidgetItem(f"{rtt_ms:.2f}")
            if rtt_ms < 20:
                rtt_item.setForeground(QColor("#4CAF50"))
            elif rtt_ms < 50:
                rtt_item.setForeground(QColor("#FFC107"))
            elif rtt_ms < 100:
                rtt_item.setForeground(QColor("#FF9800"))
            else:
                rtt_item.setForeground(QColor("#F44336"))
        else:
            rtt_item = QTableWidgetItem("—")
            rtt_item.setForeground(QColor("#9E9E9E"))
        rtt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setItem(row, 2, rtt_item)

        t.setItem(row, 3, QTableWidgetItem(info))

        self._ping_results.append((seq, success, rtt_ms))
        self.traceroute_btn.setText(f"STOP  {seq}/{self._ping_count}")
        t.scrollToBottom()

    def _on_ping_finished(self, sent, received, avg_ms):
        """Handle ping completion"""
        loss_pct = ((sent - received) / sent * 100) if sent > 0 else 0
        method = self.traceroute_current_method
        target = self.traceroute_target_input.text().strip()
        if method == 'Ping TCP':
            port = self.traceroute_port_input.text().strip() or '80'
            self.traceroute_results_group.setTitle(
                f"Results — TCP ping {target}:{port}  |  {received}/{sent} recv  "
                f"loss {loss_pct:.0f}%  avg {avg_ms:.2f} ms")
        else:
            self.traceroute_results_group.setTitle(
                f"Results — ICMP ping {target}  |  {received}/{sent} recv  "
                f"loss {loss_pct:.0f}%  avg {avg_ms:.2f} ms")
        self.traceroute_results_table.setSortingEnabled(True)
        self._apply_ping_btn_style()
        self._show_ping_graph_dialog()

    def _show_ping_graph_dialog(self):
        """Open a dialog showing ping RTT as a neon line chart"""
        results = getattr(self, '_ping_results', [])
        if not results:
            return
        method = self.traceroute_current_method
        target = self.traceroute_target_input.text().strip()
        port   = self.traceroute_port_input.text().strip() if method == 'Ping TCP' else None
        title  = f"Ping Graph — {target}:{port}" if port else f"Ping Graph — {target}"

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(820, 480)
        dialog.setMinimumSize(520, 320)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(PingGraphWidget(results), 1)
        dialog.setLayout(layout)
        dialog.exec()

    def _on_ping_error(self, error_msg):
        """Handle ping error"""
        QMessageBox.warning(self, "Ping", f"Ping error:\n\n{error_msg}")
        self._apply_ping_btn_style()

    def _traceroute_export_csv(self):
        """Export traceroute results to CSV file"""
        if self.traceroute_results_table.rowCount() == 0:
            QMessageBox.information(self, "Traceroute", "No results to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Traceroute Results", os.path.expanduser("~/traceroute_results.csv"),
            "CSV Files (*.csv)")

        if not file_path:
            return

        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.writer(f)
                # Write header
                writer.writerow(["Hop", "IP Address", "Hostname", "Latency (ms)"])
                # Write data rows
                for row in range(self.traceroute_results_table.rowCount()):
                    writer.writerow([
                        self.traceroute_results_table.item(row, col).text()
                        for col in range(4)
                    ])
            QMessageBox.information(self, "Traceroute", f"Results exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "Traceroute", f"Export failed: {e}")

    def _traceroute_clear_results(self):
        """Clear traceroute / MTR results"""
        self.traceroute_results_table.setRowCount(0)
        self.traceroute_viz_widget.clear()
        self.traceroute_results_group.setTitle("Results")
        self._mtr_hop_rows = {}
        self._mtr_cycle = 0

    def _show_route_visualization_dialog(self):
        """Open a dialog showing the route visualization with full space"""
        dialog = QDialog(self)
        target = self.traceroute_target_input.text().strip()
        dialog.setWindowTitle(f"Route Visualization — {target}" if target else "Route Visualization")
        dialog.resize(720, 520)
        dialog.setMinimumSize(500, 380)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Populate a fresh widget with current hop data
        viz = RouteVisualizationWidget()
        viz.setMinimumHeight(300)
        viz.setMaximumHeight(16777215)  # unrestricted in dialog
        for hop in self.traceroute_viz_widget.hops:
            viz.add_hop(*hop)

        scroll = QScrollArea()
        scroll.setWidget(viz)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #f5f5f5; }")
        layout.addWidget(scroll)

        if not self.traceroute_viz_widget.hops:
            empty_label = QLabel("No route data yet — run a traceroute first.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet("color: #888888; font-size: 10pt;")
            layout.addWidget(empty_label)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #78909c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #607d8b; }
        """)
        close_btn.clicked.connect(dialog.accept)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.setLayout(layout)
        dialog.exec()

    def _show_latency_graph_dialog(self):
        """Open (or raise) a non-modal dialog showing hop latencies as a smooth line chart"""
        # Reuse existing dialog if still open
        if self._latency_graph_dialog is not None and self._latency_graph_dialog.isVisible():
            self._latency_graph_dialog.raise_()
            self._latency_graph_dialog.activateWindow()
            return

        dialog = QDialog(self)
        target = self.traceroute_target_input.text().strip()
        dialog.setWindowTitle(f"Latency Graph — {target}" if target else "Latency Graph")
        dialog.resize(820, 520)
        dialog.setMinimumSize(520, 360)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        # Resolve local hostname and outbound IP once
        try:
            local_hostname = socket.gethostname()
        except Exception:
            local_hostname = "localhost"
        try:
            _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _s.connect(("8.8.8.8", 80))
            local_ip = _s.getsockname()[0]
            _s.close()
        except Exception:
            local_ip = "127.0.0.1"

        graph = LatencyGraphWidget(
            self.traceroute_viz_widget.hops,
            local_info=(local_hostname, local_ip),
            hop_stats=self._traceroute_hop_stats
        )
        layout.addWidget(graph, 1)

        dialog.setLayout(layout)

        def _on_closed():
            self._latency_graph_dialog = None
            self._latency_graph_widget = None

        dialog.finished.connect(_on_closed)

        self._latency_graph_dialog = dialog
        self._latency_graph_widget = graph

        dialog.show()

    def _traceroute_context_menu(self, pos):
        """Show context menu for traceroute results table"""
        item = self.traceroute_results_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        hop_num = self.traceroute_results_table.item(row, 0).text()
        ip = self.traceroute_results_table.item(row, 2).text() if self.traceroute_results_table.item(row, 2) else ""
        hostname = self.traceroute_results_table.item(row, 3).text() if self.traceroute_results_table.item(row, 3) else ""
        
        # MTR mode latencies are at column 6 (Avg). Standard traceroute is at 4. We can safely pick whatever is not empty.
        latency = ""
        lat_item = self.traceroute_results_table.item(row, 4) if self.traceroute_results_table.columnCount() == 5 else self.traceroute_results_table.item(row, 6)
        if lat_item:
            latency = lat_item.text()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #e8e8e8;
            }
            QMenu::separator {
                height: 1px;
                background-color: #d0d0d0;
                margin: 4px 8px;
            }
        """)

        http_action     = menu.addAction("Open in Browser (HTTP)")
        https_action    = menu.addAction("Open in Browser (HTTPS)")
        menu.addSeparator()
        ssh_action      = menu.addAction("Connect via SSH")
        telnet_action   = menu.addAction("Connect via Telnet")
        menu.addSeparator()
        ipscan_action   = menu.addAction("IP Scan (TCP)")
        snmpwalk_action = menu.addAction("SNMP Walk")
        menu.addSeparator()
        ip_details_action = menu.addAction("IP Details (Whois / Geo)")
        menu.addSeparator()
        copy_ip_action      = menu.addAction("Copy IP Address")
        copy_hostname_action = menu.addAction("Copy Hostname")
        copy_row_action     = menu.addAction("Copy Row")

        action = menu.exec(self.traceroute_results_table.viewport().mapToGlobal(pos))

        if action == http_action:
            import webbrowser
            webbrowser.open(f"http://{ip}")
        elif action == https_action:
            import webbrowser
            webbrowser.open(f"https://{ip}")
        elif action == ssh_action:
            self._scan_open_connection(ip, 'ssh')
        elif action == telnet_action:
            self._scan_open_connection(ip, 'telnet')
        elif action == ipscan_action:
            self.scan_network_input.setText(ip)
            self.scan_mask_combo.setCurrentText("32")
            self._scan_method_btn_clicked("TCP")
            self.switch_tab(2)
            self._start_scan()
        elif action == snmpwalk_action:
            self.snmp_host_input.setText(ip)
            self._snmp_type_btn_clicked("snmpwalk")
            self.switch_tab(4)
            self.execute_snmp_query()
        elif action == ip_details_action:
            self._show_ip_details_dialog(ip, hostname)
        elif action == copy_ip_action:
            QApplication.clipboard().setText(ip)
        elif action == copy_hostname_action:
            QApplication.clipboard().setText(hostname)
        elif action == copy_row_action:
            QApplication.clipboard().setText(f"Hop {hop_num}: {ip} ({hostname}) — {latency}")

    def _show_ip_details_dialog(self, ip, hostname):
        """Show a dialog with Whois and Geo IP information for the selected IP"""
        if not ip or ip in ("*", "localhost", "127.0.0.1"):
            QMessageBox.information(self, "IP Details", "Valid public IP address required.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"IP Details: {ip} ({hostname})")
        dialog.setMinimumSize(500, 400)
        dialog.setStyleSheet("QDialog { background-color: #0d1117; color: #c9d1e0; }")

        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #30363d; border-radius: 6px; }
            QTabBar::tab { background: #161b22; color: #8b949e; padding: 8px 16px; border: 1px solid #30363d; border-bottom: none; }
            QTabBar::tab:selected { background: #0d1117; color: #c9d1e0; border-top: 2px solid #58a6ff; font-weight: bold; }
        """)
        layout.addWidget(tabs)

        # Tab 1: Geo / Network (ip-api.com)
        geo_widget = QWidget()
        geo_layout = QVBoxLayout(geo_widget)
        geo_text = QTextEdit()
        geo_text.setReadOnly(True)
        geo_text.setStyleSheet("background-color: #010409; color: #e6edf3; font-family: monospace; border: none;")
        geo_layout.addWidget(geo_text)
        tabs.addTab(geo_widget, "Geo / Network")

        # Tab 2: Whois (local command)
        whois_widget = QWidget()
        whois_layout = QVBoxLayout(whois_widget)
        whois_text = QTextEdit()
        whois_text.setReadOnly(True)
        whois_text.setStyleSheet("background-color: #010409; color: #e6edf3; font-family: monospace; border: none;")
        whois_layout.addWidget(whois_text)
        tabs.addTab(whois_widget, "Whois Data")

        # Use QThread for background loading to avoid PyQt6 GUI lockups
        class GeoWorker(QThread):
            result_ready = pyqtSignal(str)
            def run(self):
                import urllib.request
                import json
                try:
                    # Quick check for private/bogon IPs
                    if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("127.") or ip.startswith("100.") or ip.startswith("172."):
                        self.result_ready.emit(f"IP: {ip}\n\nThis is a Private, Loopback, or CGNAT IP address.\nGeo-location APIs do not track internal addresses.")
                        return

                    url = f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=5) as response:
                        data = json.loads(response.read().decode('utf-8'))
                        
                    if data.get("status") == "success":
                        info = [
                            f"IP:      {data.get('query', ip)}",
                            f"ORG:     {data.get('org', '-')}",
                            f"ISP:     {data.get('isp', '-')}",
                            f"ASN:     {data.get('as', '-')}",
                            "-" * 40,
                            f"Country: {data.get('country', '-')}",
                            f"Region:  {data.get('regionName', '-')}",
                            f"City:    {data.get('city', '-')}",
                            f"TimeZ:   {data.get('timezone', '-')}",
                            f"Lat/Lon: {data.get('lat', '-')} / {data.get('lon', '-')}",
                        ]
                        self.result_ready.emit("\n".join(info))
                    else:
                        self.result_ready.emit(f"GeoIP Error: {data.get('message', 'Unknown error')}")
                except Exception as e:
                    self.result_ready.emit(f"Failed to fetch Geo IP info:\n{e}")

        class WhoisWorker(QThread):
            result_ready = pyqtSignal(str)
            def run(self):
                try:
                    import subprocess
                    result = subprocess.run(['whois', ip], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        out = result.stdout
                    else:
                        out = f"Whois command failed.\n{result.stderr}\n{result.stdout}"
                    self.result_ready.emit(out)
                except Exception as e:
                    self.result_ready.emit(f"Failed to run whois:\n{e}\n\nNote: Make sure 'whois' is installed (sudo apt install whois / sudo pacman -S whois)")

        geo_text.setPlainText("Loading Geo/Network information (ip-api.com)...")
        whois_text.setPlainText("Loading Whois data...")
        
        # Keep references to prevent garbage collection
        dialog._geo_worker = GeoWorker()
        dialog._whois_worker = WhoisWorker()
        
        dialog._geo_worker.result_ready.connect(geo_text.setPlainText)
        dialog._whois_worker.result_ready.connect(whois_text.setPlainText)
        
        dialog._geo_worker.start()
        dialog._whois_worker.start()

        from PyQt6.QtWidgets import QDialogButtonBox
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.exec()

    def _traceroute_method_changed(self, method):
        """Show/hide fields and switch table columns based on selected method"""
        is_mtr  = method in ('MTR', 'ICMP')
        is_ping = method in ('Ping ICMP', 'Ping TCP')
        is_port = method in ('TCP', 'UDP', 'Ping TCP')

        # Port row (TCP/UDP/Ping TCP only)
        self.traceroute_port_label.setVisible(is_port)
        self._tr_port_widget.setVisible(is_port)

        # Packets + Interval (MTR and Ping)
        show_pkt = is_mtr or is_ping
        self.mtr_interval_label.setVisible(show_pkt)
        self.mtr_interval_combo.setVisible(show_pkt)
        self.mtr_packets_label.setVisible(show_pkt)
        self._mtr_pkt_widget.setVisible(show_pkt)

        # Max Hops not relevant for ping
        self._hops_label.setVisible(not is_ping)
        self.traceroute_max_hops_combo.setVisible(not is_ping)

        # Switch table columns and button label
        if is_mtr:
            self.traceroute_results_table.setRowCount(0)
            self._switch_table_to_mtr_mode()
            self.traceroute_btn.setText("TRACEROUTE")
        elif is_ping:
            self.traceroute_results_table.setRowCount(0)
            self._switch_table_to_ping_mode()
            self._apply_ping_btn_style()
        else:
            self.traceroute_results_table.setRowCount(0)
            self._switch_table_to_traceroute_mode()
            self._reset_traceroute_button()

        # Update default port based on method
        if method == 'TCP':
            if not self.traceroute_port_input.text() or self.traceroute_port_input.text() == '53':
                self.traceroute_port_input.setText('80')
            self.traceroute_port_input.setPlaceholderText("80 (HTTP), 443 (HTTPS), 22 (SSH)")
        elif method == 'UDP':
            if not self.traceroute_port_input.text() or self.traceroute_port_input.text() == '80':
                self.traceroute_port_input.setText('53')
            self.traceroute_port_input.setPlaceholderText("53 (DNS), 123 (NTP), 161 (SNMP)")
        elif method == 'Ping TCP':
            if not self.traceroute_port_input.text():
                self.traceroute_port_input.setText('80')
            self.traceroute_port_input.setPlaceholderText("80 (HTTP), 443 (HTTPS), 22 (SSH)")
        _ico = load_svg_icon_dual(self._traceroute_method_icons.get(method), 18, '#ffffff', '#ffffff')
        if _ico:
            self.traceroute_btn.setIcon(_ico)
            self.traceroute_btn.setIconSize(QSize(18, 18))
        else:
            self.traceroute_btn.setIcon(QIcon())

    def _open_proxy_settings_dialog(self):
        """Open the proxy configuration dialog for traceroute"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Proxy Settings")
        dialog.setFixedWidth(340)
        dialog.setModal(True)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            QLabel {
                color: #333333;
                font-size: 9pt;
            }
            QCheckBox {
                color: #333333;
                font-size: 10pt;
            }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #bdbdbd;
                border-radius: 3px;
                background-color: #ffffff;
            }
            QCheckBox::indicator:checked {
                background-color: #00BCD4;
                border-color: #00BCD4;
            }
            QComboBox {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 9pt;
            }
            QComboBox:disabled {
                background-color: #eeeeee;
                color: #aaaaaa;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #333333;
                selection-background-color: #00BCD4;
                selection-color: #ffffff;
            }
            QLineEdit {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 9pt;
            }
            QLineEdit:focus { border: 2px solid #00BCD4; }
            QLineEdit:disabled { background-color: #eeeeee; color: #aaaaaa; }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Enable proxy checkbox
        enable_cb = QCheckBox("Enable Proxy")
        enable_cb.setChecked(self._proxy_enabled)
        layout.addWidget(enable_cb)

        # Form fields
        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        type_combo = FlatComboButton()
        type_combo.addItems(["SOCKS5", "SOCKS4", "HTTP"])
        type_combo.setCurrentText(self._proxy_type)
        type_combo.setEnabled(self._proxy_enabled)

        host_input = QLineEdit()
        host_input.setPlaceholderText("e.g. 127.0.0.1")
        host_input.setText(self._proxy_host)
        host_input.setEnabled(self._proxy_enabled)

        port_input = QLineEdit()
        port_input.setPlaceholderText("e.g. 9050")
        port_input.setText(self._proxy_port)
        port_input.setEnabled(self._proxy_enabled)

        form.addRow("Type:", type_combo)
        form.addRow("Host:", host_input)
        form.addRow("Port:", port_input)
        layout.addLayout(form)

        def _toggle(state):
            enabled = bool(state)
            type_combo.setEnabled(enabled)
            host_input.setEnabled(enabled)
            port_input.setEnabled(enabled)

        enable_cb.stateChanged.connect(_toggle)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(80)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4; color: #ffffff;
                border: none; border-radius: 6px; padding: 6px 12px; font-size: 9pt;
            }
            QPushButton:hover { background-color: #0097A7; }
        """)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0; color: #333333;
                border: none; border-radius: 6px; padding: 6px 12px; font-size: 9pt;
            }
            QPushButton:hover { background-color: #bdbdbd; }
        """)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._proxy_enabled = enable_cb.isChecked()
            self._proxy_type = type_combo.currentText()
            self._proxy_host = host_input.text().strip()
            self._proxy_port = port_input.text().strip()
            # Update button label to reflect active state
            if self._proxy_enabled and self._proxy_host:
                self.traceroute_proxy_btn.setText(
                    f"{self._proxy_type}  ON"
                )
                self.traceroute_proxy_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #00BCD4; color: #ffffff;
                        border: none; border-radius: 6px;
                        padding: 3px 10px; font-size: 9pt;
                    }
                    QPushButton:hover { background-color: #0097A7; }
                """)
            else:
                self.traceroute_proxy_btn.setText("Configure...")
                self.traceroute_proxy_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #e0e0e0; color: #333333;
                        border: 1px solid #bdbdbd; border-radius: 6px;
                        padding: 3px 10px; font-size: 9pt;
                    }
                    QPushButton:hover { background-color: #bdbdbd; }
                """)

    # =========================================================
    #  WiFi Site Survey — action methods
    # =========================================================

    def _wifi_refresh_interfaces(self):
        """Populate the interface combo with available WiFi interfaces."""
        import subprocess
        self.wifi_iface_combo.clear()
        self.wifi_iface_combo.addItem("(auto)")
        if sys.platform == 'win32':
            try:
                import subprocess
                result = subprocess.run(
                    ['netsh', 'wlan', 'show', 'interfaces'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.lower().startswith('name'):
                        parts = line.split(':', 1)
                        if len(parts) >= 2:
                            iface = parts[1].strip()
                            self.wifi_iface_combo.addItem(iface)
            except Exception:
                pass
        else:
            try:
                result = subprocess.run(
                    ['nmcli', '-t', '-f', 'DEVICE,TYPE', 'device'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    parts = line.split(':')
                    if len(parts) >= 2 and parts[1].strip() == 'wifi':
                        self.wifi_iface_combo.addItem(parts[0].strip())
            except Exception:
                # Fallback: read /sys/class/net
                try:
                    for iface in sorted(os.listdir('/sys/class/net')):
                        if os.path.exists(f'/sys/class/net/{iface}/wireless'):
                            self.wifi_iface_combo.addItem(iface)
                except Exception:
                    pass

    def _start_wifi_scan(self, _auto=False):
        """Start a WiFi scan. If called by the user (not auto-refresh) while a survey
        is active, finish the survey instead."""
        import time as _time

        # User-initiated click during an active survey → finish it
        if not _auto and self._wifi_survey_start is not None:
            self._wifi_finish_survey()
            return

        # Stop any lingering auto-refresh timer
        if self._wifi_timer and self._wifi_timer.isActive():
            self._wifi_timer.stop()

        iface = self.wifi_iface_combo.currentText()
        if iface == "(auto)":
            iface = ''

        # First scan of a new survey — initialise state
        if self._wifi_survey_start is None:
            self._wifi_survey_start   = _time.monotonic()
            self._wifi_survey_ch_load = {}
            self.wifi_channel_chart._frozen_best_ch_info = None

            # Start elapsed-time ticker on the button (updates every second)
            if self._wifi_elapsed_timer is None:
                from PyQt6.QtCore import QTimer
                self._wifi_elapsed_timer = QTimer(self)
                self._wifi_elapsed_timer.setInterval(1000)
                self._wifi_elapsed_timer.timeout.connect(self._wifi_update_elapsed_btn)
            self._wifi_elapsed_timer.start()
            self._wifi_update_elapsed_btn()  # immediate first update

        self.wifi_status_label.setText("Scanning for networks...")
        self.wifi_status_label.setStyleSheet("color: #1565c0; font-size: 8pt; padding: 2px 4px;")
        self.wifi_export_btn.setEnabled(False)
        self._wifi_new_networks = []

        self._wifi_worker = WiFiScanWorker(iface)
        self._wifi_worker.network_found.connect(self._on_wifi_network_found)
        self._wifi_worker.scan_finished.connect(self._on_wifi_scan_finished)
        self._wifi_worker.scan_error.connect(self._on_wifi_scan_error)
        self._wifi_worker.noise_floors_ready.connect(self.wifi_channel_chart.set_noise_floors)
        self._wifi_worker.start()

    def _on_wifi_network_found(self, net):
        """Buffer one discovered network (table is updated atomically on scan finish)."""
        self._wifi_new_networks.append(net)

    def _add_wifi_row(self, net):
        """Insert one network dict as a new row at the bottom of wifi_table."""
        row = self.wifi_table.rowCount()
        self.wifi_table.insertRow(row)

        # Col 0 — Visibility checkbox
        visibility_item = QTableWidgetItem()
        visibility_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        is_hidden = net['ssid'] in self.wifi_channel_chart._hidden_ssids
        visibility_item.setCheckState(Qt.CheckState.Unchecked if is_hidden else Qt.CheckState.Checked)
        self.wifi_table.setItem(row, 0, visibility_item)

        # Col 1 — SSID (with connected indicator as prefix)
        ssid_text = ("● " if net['in_use'] else "") + net['ssid']
        ssid_item = QTableWidgetItem(ssid_text)
        if net['in_use']:
            ssid_item.setForeground(QColor('#E91E63'))
        self.wifi_table.setItem(row, 1, ssid_item)

        # Col 2 — BSSID (with soft color for identification)
        bssid_item = QTableWidgetItem(net['bssid'])
        bssid_color = self._wifi_bssid_color(net['bssid'])
        bssid_item.setForeground(QColor(bssid_color))
        self.wifi_table.setItem(row, 2, bssid_item)

        # Col 3 — Vendor (pre-computed in worker thread)
        vendor = net.get('vendor', 'Unknown')
        vendor_item = QTableWidgetItem(vendor)
        vendor_item.setForeground(QColor('#555555') if vendor == 'Unknown' else QColor('#1a237e'))
        self.wifi_table.setItem(row, 3, vendor_item)

        # Col 4 — Signal bar + dBm
        sig_pct = net['signal_pct']
        bars = self._wifi_signal_bars(sig_pct)
        sig_item = QTableWidgetItem(f"{bars}  {net['dbm']} dBm")
        sig_item.setData(Qt.ItemDataRole.UserRole, sig_pct)
        if sig_pct >= 70:
            sig_item.setForeground(QColor('#2e7d32'))
        elif sig_pct >= 40:
            sig_item.setForeground(QColor('#f57f17'))
        else:
            sig_item.setForeground(QColor('#c62828'))
        self.wifi_table.setItem(row, 4, sig_item)

        # Col 5 — SNR progress bar (0–60 dB range)
        snr = net.get('snr', 0)
        snr_item = QTableWidgetItem()
        snr_item.setData(Qt.ItemDataRole.UserRole, snr)  # numeric sort
        self.wifi_table.setItem(row, 5, snr_item)
        snr_bar = QProgressBar()
        snr_bar.setRange(0, 60)
        snr_bar.setValue(min(snr, 60))
        snr_bar.setFormat(f"{snr} dB" if snr > 0 else "N/A")
        snr_bar.setTextVisible(True)
        snr_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if snr >= 40:
            _bar_color = '#2e7d32'
        elif snr >= 25:
            _bar_color = '#f57f17'
        else:
            _bar_color = '#c62828'
        snr_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #cccccc; border-radius: 3px;
                background: #f0f0f0; text-align: center;
                font-size: 8pt; color: #222222;
            }}
            QProgressBar::chunk {{ background: {_bar_color}; border-radius: 2px; }}
        """)
        self.wifi_table.setCellWidget(row, 5, snr_bar)

        # Col 6 — Noise floor (dBm, measured per channel or default)
        noise_floor = net.get('noise_floor', 0)
        noise_text = f"{noise_floor} dBm" if noise_floor else "N/A"
        noise_item = QTableWidgetItem(noise_text)
        noise_item.setData(Qt.ItemDataRole.UserRole, noise_floor)  # numeric sort
        noise_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        noise_item.setForeground(QColor('#78909c'))
        if net.get('noise_measured'):
            noise_item.setToolTip("Measured in real-time via iw survey dump")
        else:
            driver = net.get('noise_driver') or 'unknown'
            noise_item.setToolTip(f"Fallback default\nDriver: {driver} does not report noise via iw survey dump")
        self.wifi_table.setItem(row, 6, noise_item)

        # Col 7 — Channel
        ch_item = QTableWidgetItem(str(net['channel']))
        ch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wifi_table.setItem(row, 7, ch_item)

        # Col 8 — Bandwidth
        bandwidth = net.get('bandwidth', 20)
        bw_item = QTableWidgetItem(f"{bandwidth} MHz")
        bw_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if bandwidth >= 80:
            bw_item.setForeground(QColor('#1565c0'))
        elif bandwidth >= 40:
            bw_item.setForeground(QColor('#2e7d32'))
        else:
            bw_item.setForeground(QColor('#757575'))
        self.wifi_table.setItem(row, 8, bw_item)

        # Col 9 — WiFi generation
        wifi_gen = net.get('wifi_gen', '—')
        gen_item = QTableWidgetItem(wifi_gen)
        gen_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        _gen_colors = {'WiFi 7': '#7B1FA2', 'WiFi 6E': '#0277BD',
                       'WiFi 6': '#1565C0', 'WiFi 5': '#2E7D32', 'WiFi 4': '#757575'}
        gen_item.setForeground(QColor(_gen_colors.get(wifi_gen, '#9e9e9e')))
        self.wifi_table.setItem(row, 9, gen_item)

        # Col 10 — Band
        self.wifi_table.setItem(row, 10, QTableWidgetItem(net['band']))

        # Col 11 — Rate
        self.wifi_table.setItem(row, 11, QTableWidgetItem(net['rate']))

        # Col 12 — Security
        sec = net['security']
        sec_item = QTableWidgetItem(sec)
        if 'WPA3' in sec:
            sec_item.setForeground(QColor('#1565c0'))
        elif 'WPA2' in sec or 'WPA' in sec:
            sec_item.setForeground(QColor('#2e7d32'))
        elif sec == 'Open':
            sec_item.setForeground(QColor('#c62828'))
        self.wifi_table.setItem(row, 12, sec_item)

        self.wifi_table.setRowHeight(row, 24)

        # Col 13 — Channel congestion score (0–100, green → red)
        score = net.get('channel_score', 0)
        score_item = QTableWidgetItem(str(score))
        score_item.setData(Qt.ItemDataRole.UserRole, score)  # numeric sort
        score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if score <= 30:
            score_item.setForeground(QColor('#2e7d32'))
        elif score <= 60:
            score_item.setForeground(QColor('#f57f17'))
        else:
            score_item.setForeground(QColor('#c62828'))
        self.wifi_table.setItem(row, 13, score_item)

    # ── Chart visibility helpers ───────────────────────────────────────────────

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        # ── WiFi chart resize ──────────────────────────────────────────
        if event.type() == QEvent.Type.Resize:
            if obj is getattr(self, 'wifi_chart_group', None):
                btn = getattr(self, '_close_channel_btn', None)
                if btn:
                    btn.move(obj.width() - 24, 4)
            elif obj is getattr(self, 'wifi_signal_history', None):
                btn = getattr(self, '_close_history_btn', None)
                if btn:
                    btn.move(obj.width() - 24, 4)
                # Reposition power-scale overlay: − [120s] + at bottom-right
                _sm = getattr(self, '_hist_scale_minus', None)
                _sl = getattr(self, '_hist_scale_lbl',  None)
                _sp = getattr(self, '_hist_scale_plus',  None)
                if _sm and _sl and _sp:
                    _bw = obj.width()
                    _bh = obj.height()
                    # margin=8, btn=26, label=40, gap=4  → total=104px
                    _sp.move(_bw - 8  - 26,            _bh - 8 - 26)
                    _sl.move(_bw - 8  - 26 - 4 - 40,   _bh - 8 - 26)
                    _sm.move(_bw - 8  - 26 - 4 - 40 - 4 - 26, _bh - 8 - 26)
        # ── SNMP device image click ────────────────────────────────────
        if (event.type() == QEvent.Type.MouseButtonPress
                and obj is getattr(self, 'snmp_device_img', None)):
            self._snmp_show_device_image_fullsize()
            return True
        return super().eventFilter(obj, event)

    def _wifi_set_chart_visible(self, which, visible):
        """Show/hide a chart panel and keep toggle button in sync."""
        if which == 'channel':
            widget = getattr(self, 'wifi_chart_group', None)
            btn    = getattr(self, 'wifi_toggle_channel_btn', None)
        elif which == 'heatmap':
            widget = getattr(self, 'wifi_heatmap', None)
            btn    = getattr(self, 'wifi_toggle_heatmap_btn', None)
        else:
            widget = getattr(self, 'wifi_signal_history', None)
            btn    = getattr(self, 'wifi_toggle_history_btn', None)
        if widget:
            widget.setVisible(visible)
        if btn and btn.isChecked() != visible:
            btn.blockSignals(True)
            btn.setChecked(visible)
            btn.blockSignals(False)

    def _wifi_table_selection_changed(self, current, _previous):
        """Highlight the selected network's curve in the chart and show signal history."""
        if current is None:
            self.wifi_channel_chart.select_bssid(None)
            self._wifi_set_chart_visible('history', False)
            return
        bssid_item = self.wifi_table.item(current.row(), 2)
        ssid_item  = self.wifi_table.item(current.row(), 1)
        if bssid_item:
            bssid = bssid_item.text()
            ssid  = ssid_item.text().lstrip('● ') if ssid_item else ''
            self.wifi_channel_chart.select_bssid(bssid)
            self._wifi_show_signal_history(bssid, ssid)

    def _wifi_show_signal_history(self, bssid, ssid):
        """Show/update the signal history panel for the given BSSID."""
        if not hasattr(self, '_wifi_signal_history'):
            self._wifi_signal_history = {}
        h = self._wifi_signal_history.get(bssid, {})
        color = self.wifi_channel_chart._bssid_color(bssid, ssid)
        t_ref = getattr(self, '_wifi_history_t0', None)
        self.wifi_signal_history.set_network(
            bssid, ssid, h.get('points', []), color=color, t_ref=t_ref
        )

        already_visible = self.wifi_signal_history.isVisible()
        if not already_visible:
            # Slide-in animation: expand maximumWidth from 0 → unconstrained
            self.wifi_signal_history.setMaximumWidth(0)
            self.wifi_signal_history.show()
            # Sync toggle button
            btn = getattr(self, 'wifi_toggle_history_btn', None)
            if btn and not btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
            target = self.wifi_signal_history.parentWidget().width() // 2
            anim = QPropertyAnimation(self.wifi_signal_history, b'maximumWidth', self)
            anim.setDuration(300)
            anim.setStartValue(0)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self.wifi_signal_history.setMaximumWidth(16777215))
            # Keep reference so it isn't garbage-collected
            self._signal_history_anim = anim
            anim.start()

    def _on_chart_carrier_clicked(self, bssid, ssid):
        """Handle click on a carrier in the channel chart."""
        self.wifi_channel_chart.select_bssid(bssid)
        self._wifi_show_signal_history(bssid, ssid)
        # Sync table selection
        for row in range(self.wifi_table.rowCount()):
            item = self.wifi_table.item(row, 2)
            if item and item.text() == bssid:
                self.wifi_table.selectRow(row)
                break

    def _wifi_visibility_changed(self, item):
        """Handle visibility checkbox changes."""
        # Only process changes to column 0 (visibility checkboxes)
        if item.column() != 0:
            return

        # Get the SSID from column 1 of the same row
        ssid_item = self.wifi_table.item(item.row(), 1)
        if not ssid_item:
            return

        # Extract SSID (remove "● " prefix if present)
        ssid_text = ssid_item.text()
        if ssid_text.startswith("● "):
            ssid = ssid_text[2:]
        else:
            ssid = ssid_text

        # Update chart visibility
        if item.checkState() == Qt.CheckState.Checked:
            self.wifi_channel_chart.show_ssid(ssid)
        else:
            self.wifi_channel_chart.hide_ssid(ssid)

    def _on_wifi_scan_finished(self, total):
        """Handle scan completion — swap table contents atomically to avoid flicker."""
        import time as _time

        # Record signal history timestamp
        now = _time.monotonic()
        if not hasattr(self, '_wifi_history_t0'):
            self._wifi_history_t0 = now
        elapsed = round(now - self._wifi_history_t0, 1)

        if not hasattr(self, '_wifi_signal_history'):
            self._wifi_signal_history = {}  # bssid → {'ssid': str, 'points': [(t, dbm)]}

        # Compute per-channel score (0–100) first so history points can store it
        _ch_load: dict = {}
        for _n in self._wifi_new_networks:
            _c = _n.get('channel')
            if _c is not None:
                _ch_load[_c] = _ch_load.get(_c, 0) + _n.get('signal_pct', 0)
        _max_load = max(_ch_load.values()) if _ch_load else 1
        for net in self._wifi_new_networks:
            _ch = net.get('channel')
            _raw = _ch_load.get(_ch, 0) if _ch is not None else 0
            net['channel_score'] = min(100, round(_raw * 100 / max(_max_load, 1)))

        for net in self._wifi_new_networks:
            bssid = net['bssid']
            if bssid not in self._wifi_signal_history:
                self._wifi_signal_history[bssid] = {'ssid': net['ssid'], 'points': []}
            self._wifi_signal_history[bssid]['points'].append((elapsed, net['dbm'], net['channel_score']))

        # Refresh history widget if a network is currently selected
        if self.wifi_signal_history.isVisible() and self.wifi_signal_history._bssid:
            sel_bssid = self.wifi_signal_history._bssid
            h = self._wifi_signal_history.get(sel_bssid, {})
            self.wifi_signal_history.set_network(sel_bssid, h.get('ssid', ''), h.get('points', []))

        # Accumulate per-channel loads across the whole survey period
        for _n in self._wifi_new_networks:
            _c = _n.get('channel')
            if _c is not None:
                self._wifi_survey_ch_load[_c] = (
                    self._wifi_survey_ch_load.get(_c, 0) + _n.get('signal_pct', 0)
                )

        self._wifi_networks = list(self._wifi_new_networks)
        self._wifi_update_table()
        # Button stays as "Finish Survey  X:XX" during an active survey
        if self._wifi_survey_start is None:
            self.wifi_scan_btn.setText("Start Survey")
            self.wifi_scan_btn.setStyleSheet("""
                QPushButton { background-color: #E91E63; color: #ffffff; border: none;
                              border-radius: 8px; padding: 10px; font-weight: bold; font-size: 11pt; }
                QPushButton:hover { background-color: #C2185B; }
            """)
        self.wifi_export_btn.setEnabled(total > 0)

        visible = self.wifi_table.rowCount()
        if total == 0:
            self.wifi_status_label.setText(
                "No networks found — check that WiFi is enabled and the interface is up"
            )
            self.wifi_status_label.setStyleSheet(
                "color: #c62828; font-size: 8pt; padding: 2px 4px;"
            )
        else:
            hidden = total - visible
            msg = f"{visible} network(s) found"
            if hidden:
                msg += f"  ({hidden} hidden by filters)"
            self.wifi_status_label.setText(msg)
            self.wifi_status_label.setStyleSheet(
                "color: #2e7d32; font-size: 8pt; padding: 2px 4px;"
            )

        # Update channel chart and push new row to waterfall heatmap
        self._wifi_update_chart()
        if hasattr(self, 'wifi_heatmap'):
            self.wifi_heatmap.push_networks(self._wifi_networks, self._wifi_active_band_key())

        # Schedule auto-refresh
        interval_s = int(self.wifi_refresh_combo.currentText().rstrip('s'))
        if self._wifi_timer is None:
            from PyQt6.QtCore import QTimer
            self._wifi_timer = QTimer(self)
            self._wifi_timer.timeout.connect(lambda: self._start_wifi_scan(_auto=True))
        self._wifi_timer.start(interval_s * 1000)

    def _on_wifi_scan_error(self, msg):
        """Handle scan error."""
        self._wifi_survey_start = None  # abort survey on error
        if self._wifi_elapsed_timer:
            self._wifi_elapsed_timer.stop()
        self.wifi_scan_btn.setText("Start Survey")
        self.wifi_scan_btn.setStyleSheet("""
            QPushButton { background-color: #E91E63; color: #ffffff; border: none;
                          border-radius: 8px; padding: 10px; font-weight: bold; font-size: 11pt; }
            QPushButton:hover { background-color: #C2185B; }
        """)
        self.wifi_status_label.setText(f"Error: {msg}")
        self.wifi_status_label.setStyleSheet(
            "color: #c62828; font-size: 8pt; padding: 2px 4px;"
        )

    _SCAN_BTN_STYLE = """
        QPushButton { background-color: #E91E63; color: #ffffff; border: none;
                      border-radius: 8px; padding: 10px; font-weight: bold; font-size: 11pt; }
        QPushButton:hover { background-color: #C2185B; }
    """

    def _wifi_update_elapsed_btn(self):
        """Update the SCAN button text to show elapsed survey time."""
        import time as _time
        if self._wifi_survey_start is None:
            return
        elapsed = int(_time.monotonic() - self._wifi_survey_start)
        m, s = divmod(elapsed, 60)
        self.wifi_scan_btn.setText(f"Finish Survey  {m}:{s:02d}")
        self.wifi_scan_btn.setStyleSheet("""
            QPushButton { background-color: #F57C00; color: #ffffff; border: none;
                          border-radius: 8px; padding: 10px; font-weight: bold; font-size: 11pt; }
            QPushButton:hover { background-color: #E65100; }
        """)

    def _wifi_finish_survey(self):
        """Stop the survey and freeze the best channel computed from accumulated data."""
        # Stop timers and worker
        if self._wifi_elapsed_timer:
            self._wifi_elapsed_timer.stop()
        if self._wifi_timer and self._wifi_timer.isActive():
            self._wifi_timer.stop()
        if hasattr(self, '_wifi_worker') and self._wifi_worker and self._wifi_worker.isRunning():
            self._wifi_worker.stop()

        # Compute best channel from accumulated survey data
        ch_load = dict(self._wifi_survey_ch_load)
        band = self._wifi_active_band_key()
        _best_ch = None
        _best_reason = ''
        if ch_load:
            if band == '2.4GHz':
                _preferred  = [1, 6, 11, 13]
                _candidates = [c for c in _preferred if c not in ch_load]
                if _candidates:
                    _best_ch = min(_candidates, key=lambda c: abs(c - 7))
                    _best_reason = (
                        f"Non-overlapping channel with no networks detected\n"
                        f"over the entire survey period.\n"
                        f"Preferred: 1, 6, 11, 13. Ch {_best_ch} is quietest."
                    )
                else:
                    _best_ch = min(ch_load, key=lambda c: ch_load.get(c, 0))
                    _best_reason = (
                        f"All non-overlapping channels were active.\n"
                        f"Ch {_best_ch} had the lowest cumulative load "
                        f"({int(ch_load.get(_best_ch, 0))}) over the survey."
                    )
            else:
                _non_dfs = [36, 40, 44, 48, 149, 153, 157, 161, 165]
                _dfs     = [52, 56, 60, 64, 100, 104, 108, 112, 116,
                            120, 124, 128, 132, 136, 140]
                _avoid   = getattr(self.wifi_channel_chart, '_avoid_dfs', True)
                if _avoid:
                    _empty_nondfs = [c for c in _non_dfs if c not in ch_load]
                    _empty_dfs    = [c for c in _dfs    if c not in ch_load]
                    if _empty_nondfs:
                        _best_ch = min(_empty_nondfs,
                                       key=lambda c: sum(ch_load.get(n, 0)
                                                         for n in _non_dfs
                                                         if abs(n - c) <= 8))
                        _nb = sum(ch_load.get(n, 0) for n in _non_dfs
                                  if abs(n - _best_ch) <= 8 and n != _best_ch)
                        _best_reason = (
                            f"No networks on ch {_best_ch} during the entire survey.\n"
                            f"Non-DFS — no radar avoidance required.\n"
                            f"Neighbour load over survey: {int(_nb)}."
                        )
                    elif _empty_dfs:
                        _best_ch = min(_empty_dfs,
                                       key=lambda c: sum(ch_load.get(n, 0)
                                                         for n in list(ch_load)
                                                         if abs(n - c) <= 8))
                        _nb = sum(ch_load.get(n, 0) for n in list(ch_load)
                                  if abs(n - _best_ch) <= 8 and n != _best_ch)
                        _best_reason = (
                            f"No networks on ch {_best_ch} during the entire survey.\n"
                            f"DFS channel — radar avoidance may be required.\n"
                            f"All non-DFS channels were occupied.\n"
                            f"Neighbour load over survey: {int(_nb)}."
                        )
                    else:
                        _best_ch = min(_non_dfs, key=lambda c: ch_load.get(c, 0))
                        _best_reason = (
                            f"All channels active during survey.\n"
                            f"Ch {_best_ch} had the lowest cumulative load "
                            f"({int(ch_load.get(_best_ch, 0))}) among non-DFS channels."
                        )
                else:
                    _all_5g    = _non_dfs + _dfs
                    _empty_all = [c for c in _all_5g if c not in ch_load]
                    if _empty_all:
                        _best_ch = min(_empty_all,
                                       key=lambda c: sum(ch_load.get(n, 0)
                                                         for n in _all_5g
                                                         if abs(n - c) <= 8))
                        _nb = sum(ch_load.get(n, 0) for n in _all_5g
                                  if abs(n - _best_ch) <= 8 and n != _best_ch)
                        _dfs_note = " (DFS)" if _best_ch in _dfs else ""
                        _best_reason = (
                            f"No networks on ch {_best_ch}{_dfs_note} during the survey.\n"
                            f"DFS avoidance disabled — all channels considered.\n"
                            f"Neighbour load over survey: {int(_nb)}."
                        )
                    else:
                        _best_ch = min(_all_5g, key=lambda c: ch_load.get(c, 0))
                        _dfs_note = " (DFS)" if _best_ch in _dfs else ""
                        _best_reason = (
                            f"All channels active during survey.\n"
                            f"Ch {_best_ch}{_dfs_note} had the lowest cumulative load "
                            f"({int(ch_load.get(_best_ch, 0))}).\n"
                            f"DFS avoidance disabled."
                        )

        # Freeze result in chart
        if _best_ch is not None:
            self.wifi_channel_chart._frozen_best_ch_info = (_best_ch, _best_reason, ch_load)
            self.wifi_channel_chart.update()
            self.wifi_status_label.setText(
                f"Survey complete — recommended channel: {_best_ch}"
            )
            self.wifi_status_label.setStyleSheet(
                "color: #e65100; font-style: italic; font-size: 8pt; padding: 2px 4px;"
            )

        # Reset survey state and button
        self._wifi_survey_start   = None
        self._wifi_survey_ch_load = {}
        self.wifi_scan_btn.setText("Start Survey")
        self.wifi_scan_btn.setStyleSheet(self._SCAN_BTN_STYLE)

    def _wifi_active_band_key(self):
        """Return the currently selected band key string."""
        if self.wifi_band_btn_5.isChecked():
            return '5GHz'
        if self.wifi_band_btn_both.isChecked():
            return 'Both'
        return '2.4GHz'

    def _wifi_update_chart(self):
        """Refresh the channel chart with current scan data."""
        if not hasattr(self, '_wifi_networks'):
            return
        band_key = self._wifi_active_band_key()
        self.wifi_channel_chart.set_networks(self._wifi_networks, band_key)
        # Sync heatmap band (clears buffer only if band actually changed)
        if hasattr(self, 'wifi_heatmap'):
            self.wifi_heatmap.set_band(band_key)

    def _wifi_update_table(self):
        """Rebuild the results table from _wifi_networks filtered by the active band button."""
        if not hasattr(self, '_wifi_networks'):
            return
        if self.wifi_band_btn_5.isChecked():
            band_filter = '5GHz'
        elif self.wifi_band_btn_both.isChecked():
            band_filter = None  # show all
        else:
            band_filter = '2.4GHz'

        self.wifi_table.setUpdatesEnabled(False)
        self.wifi_table.blockSignals(True)
        self.wifi_table.setSortingEnabled(False)
        self.wifi_table.setRowCount(0)
        for net in self._wifi_networks:
            if band_filter is None or net.get('band') == band_filter:
                self._add_wifi_row(net)
        self.wifi_table.blockSignals(False)
        self.wifi_table.setSortingEnabled(True)
        self.wifi_table.setUpdatesEnabled(True)

    def _wifi_signal_bars(self, pct):
        """Return a 4-block bar indicator string for a signal percentage."""
        filled = round(pct / 25)   # 0–4 blocks
        return '▂▄▆█'[:filled].ljust(4, '_')

    def _wifi_bssid_color(self, bssid):
        """Generate a soft, consistent color for a BSSID using hash."""
        # Create a simple hash from the BSSID
        hash_val = sum(ord(c) for c in bssid.replace(':', ''))

        # Soft colors for text display
        colors = [
            '#6B8E23',  # Olive green
            '#4682B4',  # Steel blue
            '#8B4789',  # Purple
            '#CD853F',  # Peru (brown-orange)
            '#5F9EA0',  # Cadet blue
            '#9370DB',  # Medium purple
            '#3CB371',  # Medium sea green
            '#CD5C5C',  # Indian red
            '#4169E1',  # Royal blue
            '#DAA520',  # Goldenrod
            '#20B2AA',  # Light sea green
            '#BA55D3',  # Medium orchid
            '#FF8C00',  # Dark orange
            '#9932CC',  # Dark orchid
            '#8FBC8F',  # Dark sea green
        ]

        return colors[hash_val % len(colors)]

    def _wifi_show_bssid_details(self, item):
        """Show detailed BSSID information for the selected SSID."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QHeaderView, QLabel, QPushButton
        from PyQt6.QtCore import Qt

        if not hasattr(self, '_wifi_networks') or not self._wifi_networks:
            return

        # Get SSID from the clicked row
        row = item.row()
        ssid = self.wifi_table.item(row, 1).text().replace('● ', '')  # Remove connected indicator

        # Find all BSSIDs for this SSID
        bssid_list = []
        for net in self._wifi_networks:
            if net['ssid'] == ssid:
                bssid_list.append(net)

        if not bssid_list:
            return

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"BSSID Details for: {ssid}")
        dialog.setMinimumWidth(800)
        dialog.setMinimumHeight(400)

        layout = QVBoxLayout()

        # Header
        header = QLabel(f"<b>{len(bssid_list)} Access Point(s) broadcasting '{ssid}'</b>")
        header.setStyleSheet("font-size: 11pt; padding: 10px;")
        layout.addWidget(header)

        # Table
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(
            ["BSSID", "Signal", "SNR", "Channel", "BW", "Band", "Rate", "Security"]
        )
        table.setRowCount(len(bssid_list))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)

        # Column widths
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in [(1, 110), (2, 70), (3, 60), (4, 60), (5, 60), (6, 100), (7, 110)]:
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(col, w)

        # Populate table
        for i, net in enumerate(bssid_list):
            # BSSID with color
            bssid_item = QTableWidgetItem(net['bssid'])
            bssid_color = self._wifi_bssid_color(net['bssid'])
            bssid_item.setForeground(QColor(bssid_color))
            table.setItem(i, 0, bssid_item)

            # Signal
            sig_pct = net['signal_pct']
            bars = self._wifi_signal_bars(sig_pct)
            sig_item = QTableWidgetItem(f"{bars}  {net['dbm']} dBm")
            if sig_pct >= 70:
                sig_item.setForeground(QColor('#2e7d32'))
            elif sig_pct >= 40:
                sig_item.setForeground(QColor('#f57f17'))
            else:
                sig_item.setForeground(QColor('#c62828'))
            table.setItem(i, 1, sig_item)

            # SNR
            snr = net.get('snr', 0)
            snr_item = QTableWidgetItem(f"{snr} dB" if snr > 0 else "N/A")
            snr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if snr >= 40:
                snr_item.setForeground(QColor('#2e7d32'))
            elif snr >= 25:
                snr_item.setForeground(QColor('#f57f17'))
            elif snr > 0:
                snr_item.setForeground(QColor('#c62828'))
            table.setItem(i, 2, snr_item)

            # Channel
            ch_item = QTableWidgetItem(str(net['channel']))
            ch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 3, ch_item)

            # Bandwidth
            bandwidth = net.get('bandwidth', 20)
            bw_item = QTableWidgetItem(f"{bandwidth} MHz")
            bw_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if bandwidth >= 80:
                bw_item.setForeground(QColor('#1565c0'))
            elif bandwidth >= 40:
                bw_item.setForeground(QColor('#2e7d32'))
            else:
                bw_item.setForeground(QColor('#757575'))
            table.setItem(i, 4, bw_item)

            # Band
            table.setItem(i, 5, QTableWidgetItem(net['band']))

            # Rate
            table.setItem(i, 6, QTableWidgetItem(net['rate']))

            # Security
            sec = net['security']
            sec_item = QTableWidgetItem(sec)
            if 'WPA3' in sec:
                sec_item.setForeground(QColor('#1565c0'))
            elif 'WPA2' in sec or 'WPA' in sec:
                sec_item.setForeground(QColor('#2e7d32'))
            elif sec == 'Open':
                sec_item.setForeground(QColor('#c62828'))
            table.setItem(i, 7, sec_item)

        table.setStyleSheet("""
            QTableWidget {
                background-color: #f5f5f5;
                gridline-color: #d0d0d0;
                alternate-background-color: #ffffff;
            }
            QHeaderView::section {
                background-color: #e0e0e0;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
        """)

        layout.addWidget(table)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(dialog.close)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #E91E63;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #C2185B;
            }
        """)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.setLayout(layout)
        dialog.exec()

    def _wifi_export_csv(self):
        """Export the current scan results to a CSV file."""
        if not hasattr(self, '_wifi_networks') or not self._wifi_networks:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export WiFi Scan", "wifi_scan.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            import csv
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=['ssid', 'bssid', 'vendor', 'signal_pct', 'dbm', 'snr', 'noise_floor',
                                'channel', 'bandwidth', 'band', 'rate', 'security', 'in_use'],
                    extrasaction='ignore'
                )
                writer.writeheader()
                writer.writerows(self._wifi_networks)
            QMessageBox.information(self, "Export", f"Saved to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))

    def _create_styled_progress_bar(self):
        """Create a styled progress bar for the scanner"""
        from PyQt6.QtWidgets import QProgressBar
        bar = QProgressBar()
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setValue(0)
        bar.setStyleSheet("""
            QProgressBar {
                background-color: #e0e0e0;
                border: none;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #ef5350;
                border-radius: 6px;
            }
        """)
        return bar

    def _scan_method_btn_clicked(self, method):
        """Handle scan method button click - ensure only one button is checked"""
        for btn in self.scan_method_buttons.values():
            btn.setChecked(False)
        self.scan_method_buttons[method].setChecked(True)
        self.scan_current_method = method
        self._scan_method_changed(method)
        _ico = load_svg_icon_dual(self._scan_method_icons.get(method), 18, '#ffffff', '#ffffff')
        if _ico:
            self.scan_btn.setIcon(_ico)
            self.scan_btn.setIconSize(QSize(18, 18))
        else:
            self.scan_btn.setIcon(QIcon())

    def _scan_method_changed(self, method):
        """Show/hide ports field based on scan method"""
        show_ports = method in ('TCP', 'UDP')
        self.scan_ports_label.setVisible(show_ports)
        self._ports_widget.setVisible(show_ports)

    def _scan_auto_detect_network(self):
        """Auto-detect the network from the first active interface"""
        self._local_ip = None
        self._local_hostname = None
        interfaces = get_network_interfaces()
        if interfaces:
            iface, ip, prefix_len = interfaces[0]
            self._local_ip = ip
            try:
                self._local_hostname = socket.gethostname()
            except Exception:
                self._local_hostname = ""
            try:
                network = ipaddress.ip_network(f"{ip}/{prefix_len}", strict=False)
                self.scan_network_input.setText(str(network.network_address))
                self.scan_mask_combo.setCurrentText(str(prefix_len))
            except ValueError:
                parts = ip.split('.')
                if len(parts) == 4:
                    self.scan_network_input.setText(f"{parts[0]}.{parts[1]}.{parts[2]}.0")
                    self.scan_mask_combo.setCurrentText("24")

    def _parse_ports(self, text):
        """Parse port specification like '22,80,443' or '1-1024' into a list of ints"""
        ports = []
        for part in text.split(','):
            part = part.strip()
            if '-' in part:
                try:
                    start, end = part.split('-', 1)
                    ports.extend(range(int(start), int(end) + 1))
                except ValueError:
                    continue
            else:
                try:
                    ports.append(int(part))
                except ValueError:
                    continue
        return [p for p in ports if 1 <= p <= 65535]

    def _parse_targets(self, text):
        """Parse network specification into list of IP strings"""
        text = text.strip()
        if not text:
            return []
        # Try CIDR notation first
        try:
            network = ipaddress.ip_network(text, strict=False)
            return [str(ip) for ip in network.hosts()]
        except ValueError:
            pass
        # Try range notation: 192.168.1.1-254
        if '-' in text:
            try:
                base, end_part = text.rsplit('-', 1)
                end_octet = int(end_part)
                base_parts = base.split('.')
                if len(base_parts) == 4:
                    start_octet = int(base_parts[3])
                    prefix = '.'.join(base_parts[:3])
                    return [f"{prefix}.{i}" for i in range(start_octet, end_octet + 1)]
            except (ValueError, IndexError):
                pass
        # Single IP
        try:
            ipaddress.ip_address(text)
            return [text]
        except ValueError:
            return []

    def _ensure_traceroute_cap_net_raw(self):
        """Ensure traceroute binary has cap_net_raw for TCP/UDP probes.

        Returns True if capability is already set or was successfully granted.
        Returns False if the user cancelled or the password was wrong.
        """
        # Only check once per session
        if getattr(self, '_traceroute_cap_granted', False):
            return True

        # Check current capabilities of the traceroute binary
        traceroute_bin = '/usr/bin/traceroute'
        try:
            result = subprocess.run(
                ['getcap', traceroute_bin],
                capture_output=True, text=True, timeout=5
            )
            if 'cap_net_raw' in result.stdout:
                self._traceroute_cap_granted = True
                return True
        except FileNotFoundError:
            # getcap not available, proceed and let traceroute fail naturally
            return True
        except Exception:
            pass

        # Need to grant capability — ask for sudo password
        password = self._ask_sudo_password(
            "TCP/UDP traceroute requires raw socket access (cap_net_raw).\n"
            "This needs to be configured once with root privileges.\n\n"
            "Please enter your sudo password:"
        )
        if password is None:
            return False  # User cancelled

        # Run: sudo -S setcap cap_net_raw+ep /usr/bin/traceroute
        try:
            proc = subprocess.run(
                ['sudo', '-S', 'setcap', 'cap_net_raw+ep', traceroute_bin],
                input=password + '\n',
                capture_output=True, text=True, timeout=15
            )
            if proc.returncode == 0:
                self._traceroute_cap_granted = True
                return True
            else:
                err = proc.stderr.strip()
                if 'incorrect password' in err.lower() or 'authentication failure' in err.lower() or '3 incorrect' in err.lower():
                    QMessageBox.warning(self, "Traceroute", "Incorrect sudo password.\nTCP/UDP traceroute cancelled.")
                    return False
                elif 'read-only file system' in err.lower():
                    # Read-only filesystem - ask user if they want to continue with sudo
                    reply = QMessageBox.question(
                        self, "Traceroute - Read-only Filesystem",
                        "Cannot set capabilities on read-only filesystem.\n\n"
                        "Traceroute will require sudo password each time it runs.\n\n"
                        "Continue anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        # Mark as granted so we don't keep asking
                        self._traceroute_cap_granted = True
                        self._traceroute_needs_sudo = True  # Flag to use sudo for traceroute
                        return True
                    return False
                else:
                    QMessageBox.warning(
                        self, "Traceroute",
                        f"Failed to set traceroute capability.\n\n{err or 'Unknown error.'}\n\n"
                        "Try running manually:\n  sudo setcap cap_net_raw+ep /usr/bin/traceroute"
                    )
                    return False
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "Traceroute", "Timed out while trying to set capability.")
            return False
        except Exception as e:
            QMessageBox.warning(self, "Traceroute", f"Error: {e}")
            return False

    def _ask_sudo_password(self, message):
        """Show dialog to ask for sudo password. Returns password or None if cancelled."""
        password, ok = QInputDialog.getText(
            self, "Sudo Password Required", message, QLineEdit.EchoMode.Password
        )
        return password if (ok and password) else None

    def _start_scan(self):
        """Start or stop the network scan"""
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.scan_btn.setText("Stopping...")
            self.scan_btn.setEnabled(False)
            return

        ip_text = self.scan_network_input.text().strip()
        if not ip_text:
            QMessageBox.warning(self, "IP Scanner", "Please enter a network address.")
            return

        mask = self.scan_mask_combo.currentText()
        network_text = f"{ip_text}/{mask}"
        targets = self._parse_targets(network_text)
        if not targets:
            QMessageBox.warning(self, "IP Scanner", "Invalid network format.\nEnter a valid IP address.")
            return

        method = self.scan_current_method
        ports = []
        if method in ('TCP', 'UDP'):
            ports = self._parse_ports(self.scan_ports_input.text())
            if not ports:
                QMessageBox.warning(self, "IP Scanner", "Please enter valid port(s) for TCP/UDP scan.")
                return

        timeout = int(self.scan_timeout_combo.currentText().replace('s', ''))
        threads = 50

        # ARP scan requires root privileges for arping
        sudo_password = None
        if method == 'ARP':
            # Check if arping is available
            if not shutil.which('arping'):
                QMessageBox.warning(self, "IP Scanner",
                    "arping not found.\nInstall with: sudo pacman -S iputils")
                return
            # Test if arping works without sudo
            try:
                test = subprocess.run(
                    ['arping', '-c', '1', '-w', '1', targets[0]],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    timeout=3, text=True
                )
                if test.returncode != 0 and 'ermit' in (test.stderr or ''):
                    raise PermissionError
            except (PermissionError, subprocess.TimeoutExpired, OSError):
                # Need sudo - ask for password
                sudo_password = self._ask_sudo_password(
                    "ARP scan requires root privileges.\nPlease enter your sudo password:")
                if sudo_password is None:
                    return
                # Validate sudo password
                try:
                    validate = subprocess.run(
                        ['sudo', '-S', '-v'],
                        input=sudo_password + '\n',
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=5, text=True
                    )
                    if validate.returncode != 0:
                        QMessageBox.warning(self, "IP Scanner", "Invalid sudo password.")
                        return
                except Exception:
                    QMessageBox.warning(self, "IP Scanner", "Failed to validate sudo password.")
                    return

        # Show/hide Hostname column based on DNS checkbox
        dns_lookup = self.scan_dns_checkbox.isChecked()
        self.scan_results_table.setColumnHidden(3, not dns_lookup)

        # Clear previous results
        self.scan_results_table.setSortingEnabled(False)
        self.scan_results_table.setRowCount(0)
        self.scan_results_group.setTitle("Results (scanning...)")

        # Switch button to scanning mode
        self.scan_btn.setText("Scanning 0%")
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #616161;
            }
        """)

        self.scan_worker = ScanWorker(targets, method, ports, timeout, threads, sudo_password, dns_lookup)
        self.scan_worker.host_found.connect(self._on_scan_host_found)
        self.scan_worker.scan_progress.connect(lambda p: self.scan_btn.setText(f"Scanning {p}%"))
        self.scan_worker.scan_finished.connect(self._on_scan_finished)
        self.scan_worker.scan_error.connect(self._on_scan_error)
        self.scan_worker.start()

    def _detect_device_type(self, vendor, hostname, status, mac):
        """Heuristically identify device type from vendor name, hostname and open ports."""
        v = vendor.lower()
        h = hostname.lower()
        s = status.lower()

        # Firewall
        if any(k in v for k in ('fortinet', 'fortigate', 'palo alto', 'check point', 'watchguard', 'sophos', 'juniper srx', 'cisco asa')):
            return 'firewall'
        if any(k in h for k in ('firewall', 'fortigate', 'fw-', '-fw')):
            return 'firewall'

        # Access Point
        if any(k in v for k in ('ubiquiti', 'ruckus', 'aerohive', 'xirrus', 'engenius', 'cambium', 'meraki')):
            return 'ap'
        if any(k in h for k in ('ap-', '-ap', 'wap', 'access-point', 'unifi', 'arubaap')):
            return 'ap'

        # Switch
        if any(k in v for k in ('3com', 'extreme networks', 'brocade', 'foundry', 'datacom', 'allied telesis', 'dell networking')):
            return 'switch'
        if any(k in h for k in ('switch', 'sw-', '-sw')):
            return 'switch'

        # Router / Gateway
        if any(k in v for k in ('cisco', 'juniper', 'mikrotik', 'routerboard', 'netgear', 'tp-link', 'tplink', 'd-link', 'asus', 'linksys', 'belkin', 'zyxel', 'huawei', 'h3c', 'edgerouter', 'peplink')):
            return 'router'
        if any(k in h for k in ('router', 'gateway', 'gw-', '-gw', 'rtr-', '-rtr')):
            return 'router'

        # Printer
        if any(k in v for k in ('hewlett', 'canon', 'epson', 'lexmark', 'brother', 'xerox', 'ricoh', 'konica', 'kyocera', 'sharp', 'oki data', 'toshiba tec')):
            return 'printer'
        if any(k in h for k in ('printer', 'print', 'mfp', 'laserjet', 'officejet', 'pixma', 'workcent')):
            return 'printer'
        if '9100' in s or ':515' in s:
            return 'printer'

        # Apple devices
        if 'apple' in v:
            if any(k in h for k in ('iphone', 'ipad', 'ipod')):
                return 'iphone'
            return 'mac'

        # iPhone/iPad (hostname-based without Apple vendor)
        if any(k in h for k in ('iphone', 'ipad', 'ipod')):
            return 'iphone'

        # Android
        if any(k in v for k in ('samsung', 'xiaomi', 'oneplus', 'oppo', 'vivo', 'realme', 'motorola mobility', 'lg electronics', 'huawei device', 'honor device')):
            return 'android'
        if 'android' in h:
            return 'android'

        # TV / Smart TV
        if any(k in v for k in ('samsung', 'lg innotek', 'tcl', 'hisense', 'vizio', 'sony', 'philips')):
            if any(k in h for k in ('tv', 'television', 'smarttv', 'firetv', 'appletv', 'roku', 'chromecast')):
                return 'tv'
        if any(k in h for k in ('samsung-tv', 'lgtv', '-tv', 'smarttv', 'firetv', 'appletv', 'roku', 'chromecast')):
            return 'tv'

        # VoIP Phone
        if any(k in v for k in ('polycom', 'grandstream', 'yealink', 'snom', 'avaya', 'mitel', 'cisco ip phone')):
            return 'phone'
        if '5060' in s:
            return 'phone'

        # Windows PC
        if 'microsoft' in v:
            return 'pc_windows'
        if any(k in s for k in ('3389', ':445', ':139')):
            return 'pc_windows'
        if any(k in h for k in ('desktop', 'laptop', 'workstation', 'pc-', '-pc', 'win-', '-win', 'surface')):
            return 'pc_windows'

        # Linux
        if any(k in h for k in ('linux', 'ubuntu', 'debian', 'fedora', 'centos', 'raspberrypi', 'nas', 'server')):
            return 'pc_linux'
        if ':22' in s and not any(k in s for k in ('80', '443', '8080')):
            return 'pc_linux'

        # HP - could be PC or printer; port 9100 already caught above
        if 'hewlett' in v or 'hp inc' in v or 'hp enterprise' in v:
            return 'pc_windows'

        return 'unknown'

    def _get_device_icon(self, device_type):
        """Load and return a QIcon for the given device type string."""
        if device_type == 'unknown':
            return QIcon()
        path = self.get_icon_path(f'device_{device_type}.svg')
        if path:
            pixmap = load_svg_pixmap(path, 26)
            if pixmap and not pixmap.isNull():
                return QIcon(pixmap)
        return QIcon()

    def _on_scan_host_found(self, ip, status, latency, method, mac, vendor, hostname):
        """Add a discovered host to the results table"""
        row = self.scan_results_table.rowCount()
        self.scan_results_table.insertRow(row)

        device_type = self._detect_device_type(vendor, hostname, status, mac)
        device_icon = self._get_device_icon(device_type)

        # Col 0: device type icon (dedicated narrow column)
        icon_item = QTableWidgetItem()
        icon_item.setIcon(device_icon)
        icon_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_results_table.setItem(row, 0, icon_item)

        # Col 1: IP Address
        ip_item = QTableWidgetItem(ip)
        ip_item.setData(Qt.ItemDataRole.UserRole, sum(int(o) * (256 ** (3 - i)) for i, o in enumerate(ip.split('.'))))
        self.scan_results_table.setItem(row, 1, ip_item)

        # Col 2: Status
        self.scan_results_table.setItem(row, 2, QTableWidgetItem(status))

        # Col 3: Latency
        latency_item = QTableWidgetItem(f"{latency:.1f}")
        latency_item.setData(Qt.ItemDataRole.UserRole, latency)
        if latency >= 100:
            latency_item.setForeground(QColor("#F44336"))
        elif latency >= 50:
            latency_item.setForeground(QColor("#FF9800"))
        else:
            latency_item.setForeground(QColor("#4CAF50"))
        self.scan_results_table.setItem(row, 3, latency_item)

        # Col 4: Hostname
        hostname_item = QTableWidgetItem(hostname)
        hostname_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.scan_results_table.setItem(row, 4, hostname_item)

        # Col 5: MAC Vendor
        vendor_display = f"{vendor} ({mac})" if mac else vendor
        vendor_item = QTableWidgetItem(vendor_display)
        vendor_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.scan_results_table.setItem(row, 5, vendor_item)

        self.scan_results_group.setTitle(f"Results (scanning... {row + 1} hosts found)")


    def _on_scan_finished(self, total_found):
        """Handle scan completion"""
        self.scan_results_group.setTitle(f"Results — {total_found} host{'s' if total_found != 1 else ''} found")

        # Update occupancy bar
        try:
            net_addr = self.scan_network_input.text().strip()
            prefix = self.scan_mask_combo.currentText().strip()
            scanned_net = ipaddress.ip_network(f"{net_addr}/{prefix}", strict=False)
            total_ips = scanned_net.num_addresses
            # Subtract network and broadcast for IPv4
            if scanned_net.version == 4 and total_ips > 2:
                total_ips -= 2
            occupancy = int(total_found * 100 / total_ips) if total_ips else 0
            self.scan_occupancy_bar.setValue(min(occupancy, 100))
            self.scan_occupancy_bar.setFormat(f"Occupancy: {occupancy}% ({total_found} / {total_ips})")
            # Change colour based on occupancy
            if occupancy >= 90:
                colour = "#f44336"  # red
            elif occupancy >= 70:
                colour = "#ff9800"  # orange
            else:
                colour = "#4caf50"  # green
            self.scan_occupancy_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: #e0e0e0;
                    border: 1px solid #b0b0b0;
                    border-radius: 6px;
                    text-align: center;
                    font-size: 9pt;
                    color: #333333;
                }}
                QProgressBar::chunk {{
                    background-color: {colour};
                    border-radius: 6px;
                }}
            """)
        except Exception:
            pass

        # Sort rows numerically by IP (UserRole on col 1 holds the 32-bit integer).
        # sortItems() is text-based and would mis-order 10.0.0.2 after 10.0.0.100.
        row_count = self.scan_results_table.rowCount()
        rows = []
        for row in range(row_count):
            ip_item = self.scan_results_table.item(row, 1)
            ip_val = ip_item.data(Qt.ItemDataRole.UserRole) if ip_item else 0
            items = [self.scan_results_table.takeItem(row, col) for col in range(6)]
            rows.append((ip_val, items))

        rows.sort(key=lambda x: x[0])

        # Mark local device row only when it belongs to the scanned network
        local_ip = getattr(self, '_local_ip', None)
        local_hostname = getattr(self, '_local_hostname', None) or ''
        local_key = None
        if local_ip:
            try:
                net_addr = self.scan_network_input.text().strip()
                prefix = self.scan_mask_combo.currentText().strip()
                scanned_net = ipaddress.ip_network(f"{net_addr}/{prefix}", strict=False)
                if ipaddress.ip_address(local_ip) not in scanned_net:
                    local_ip = None  # different network — don't inject
            except Exception:
                local_ip = None
        if local_ip:
            try:
                local_key = sum(int(o) * (256 ** (3 - i)) for i, o in enumerate(local_ip.split('.')))
            except Exception:
                local_key = None

        # If local IP was not scanned, inject a row for it
        if local_key is not None and not any(ip_val == local_key for ip_val, _ in rows):
            _icon_item = QTableWidgetItem()
            _icon_item.setIcon(self._get_device_icon('pc_linux'))
            _icon_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            _icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            _ip_item = QTableWidgetItem(local_ip)
            _ip_item.setData(Qt.ItemDataRole.UserRole, local_key)
            _status_item = QTableWidgetItem("")
            _lat_item = QTableWidgetItem("0.0")
            _lat_item.setData(Qt.ItemDataRole.UserRole, 0.0)
            _host_item = QTableWidgetItem(local_hostname)
            _vendor_item = QTableWidgetItem("")
            rows.append((local_key, [_icon_item, _ip_item, _status_item, _lat_item, _host_item, _vendor_item]))
            rows.sort(key=lambda x: x[0])

        _bold_font = self.scan_results_table.font()
        _bold_font.setBold(True)

        self.scan_results_table.setRowCount(0)
        for ip_val, items in rows:
            r = self.scan_results_table.rowCount()
            self.scan_results_table.insertRow(r)
            is_local = local_key is not None and ip_val == local_key
            if is_local:
                # Force pc_linux icon
                _icon_item = QTableWidgetItem()
                _icon_item.setIcon(self._get_device_icon('pc_linux'))
                _icon_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                _icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                items[0] = _icon_item
                # Bold IP
                items[1].setFont(_bold_font)
                # "This device" status
                items[2] = QTableWidgetItem("  ★ This device")
            for col, item in enumerate(items):
                if item:
                    self.scan_results_table.setItem(r, col, item)

        self.scan_results_table.setSortingEnabled(True)
        self._reset_scan_button()

    def _on_scan_error(self, error_msg):
        """Handle scan error"""
        QMessageBox.warning(self, "IP Scanner", f"Scan error: {error_msg}")
        self._reset_scan_button()

    def _reset_scan_button(self):
        """Reset scan button to initial state"""
        self.scan_btn.setText("SCAN")
        self.scan_btn.setEnabled(True)
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef5350;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)

    def _scan_export_csv(self):
        """Export scan results to CSV file"""
        if self.scan_results_table.rowCount() == 0:
            QMessageBox.information(self, "IP Scanner", "No results to export.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Scan Results", os.path.expanduser("~/scan_results.csv"),
            "CSV Files (*.csv)")
        if not file_path:
            return
        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["IP Address", "Status", "Latency (ms)", "Hostname", "MAC Vendor"])
                for row in range(self.scan_results_table.rowCount()):
                    writer.writerow([
                        self.scan_results_table.item(row, col).text()
                        for col in range(1, 6)  # skip col 0 (icon)
                    ])
            QMessageBox.information(self, "IP Scanner", f"Results exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "IP Scanner", f"Export failed: {e}")


    def _scan_clear_results(self):
        """Clear scan results"""
        self.scan_results_table.setRowCount(0)
        self.scan_results_group.setTitle("Results")
        self.scan_occupancy_bar.setValue(0)
        self.scan_occupancy_bar.setFormat("Occupancy: 0% (0 / 0)")
        self.scan_occupancy_bar.setStyleSheet("""
            QProgressBar {
                background-color: #e0e0e0;
                border: 1px solid #b0b0b0;
                border-radius: 6px;
                text-align: center;
                font-size: 9pt;
                color: #333333;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 6px;
            }
        """)

    def _scan_context_menu(self, pos):
        """Show context menu for scan results table"""
        item = self.scan_results_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        ip = self.scan_results_table.item(row, 1).text()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #e8e8e8;
            }
            QMenu::separator {
                height: 1px;
                background-color: #d0d0d0;
                margin: 4px 8px;
            }
        """)

        http_action = menu.addAction("Open in Browser (HTTP)")
        https_action = menu.addAction("Open in Browser (HTTPS)")
        menu.addSeparator()
        ssh_action = menu.addAction("Connect via SSH")
        telnet_action = menu.addAction("Connect via Telnet")
        menu.addSeparator()
        snmpwalk_action = menu.addAction("SNMP Walk")
        tracert_action  = menu.addAction("Traceroute (ICMP MTR)")
        ping_action     = menu.addAction("PING ICMP")
        menu.addSeparator()
        add_ssh_action  = menu.addAction("Add to SSH List")
        menu.addSeparator()
        export_action   = menu.addAction("Export CSV")
        clear_action    = menu.addAction("Clear Results")
        menu.addSeparator()
        copy_action = menu.addAction("Copy IP Address")

        action = menu.exec(self.scan_results_table.viewport().mapToGlobal(pos))

        if action == http_action:
            import webbrowser
            webbrowser.open(f"http://{ip}")
        elif action == https_action:
            import webbrowser
            webbrowser.open(f"https://{ip}")
        elif action == ssh_action:
            self._scan_open_connection(ip, 'ssh')
        elif action == telnet_action:
            self._scan_open_connection(ip, 'telnet')
        elif action == snmpwalk_action:
            self.snmp_host_input.setText(ip)
            self._snmp_type_btn_clicked("snmpwalk")
            self.switch_tab(4)
            self.execute_snmp_query()
        elif action == tracert_action:
            self.traceroute_target_input.setText(ip)
            for _k, _b in self._traceroute_method_btns.items():
                _b.setChecked(_k == 'ICMP')
            self.traceroute_current_method = 'ICMP'
            self._traceroute_method_changed('ICMP')
            self.switch_tab(3)
            self._start_traceroute()
        elif action == ping_action:
            self.traceroute_target_input.setText(ip)
            for _k, _b in self._traceroute_method_btns.items():
                _b.setChecked(_k == 'Ping ICMP')
            self.traceroute_current_method = 'Ping ICMP'
            self._traceroute_method_changed('Ping ICMP')
            self.switch_tab(3)
            self._start_ping()
        elif action == add_ssh_action:
            self._add_ip_to_ssh_list(ip)
        elif action == export_action:
            self._scan_export_csv()
        elif action == clear_action:
            self._scan_clear_results()
        elif action == copy_action:
            QApplication.clipboard().setText(ip)

    def _ssh_profile_context_menu(self, pos):
        """Context menu for SSH Quick Connect tree — network tools or group actions."""
        item = self.ssh_profiles_tree.itemAt(pos)
        if not item:
            return
        profile = item.data(0, Qt.ItemDataRole.UserRole)

        # --- Group header context menu ---
        if not profile:
            menu = QMenu(self)
            menu.setStyleSheet("""
                QMenu {
                    background-color: #ffffff; color: #333333;
                    border: 1px solid #d0d0d0; border-radius: 6px; padding: 4px;
                }
                QMenu::item { padding: 6px 20px; border-radius: 3px; }
                QMenu::item:selected { background-color: #e8e8e8; }
            """)
            connect_all_action = menu.addAction("Connect to all devices")
            menu.addSeparator()
            rename_action = menu.addAction("Rename Group")
            action = menu.exec(self.ssh_profiles_tree.viewport().mapToGlobal(pos))
            if action == rename_action:
                self._rename_ssh_group(item)
            elif action == connect_all_action:
                self._connect_all_in_group(item)
            return

        ip = profile.get('host', '').strip()
        if not ip:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #e8e8e8;
            }
            QMenu::separator {
                height: 1px;
                background-color: #d0d0d0;
                margin: 4px 8px;
            }
        """)

        edit_action    = menu.addAction("Edit profile")
        menu.addSeparator()
        http_action    = menu.addAction("Open in Browser (HTTP)")
        https_action   = menu.addAction("Open in Browser (HTTPS)")
        menu.addSeparator()
        ipscan_action  = menu.addAction("IP Scan (TCP)")
        snmpwalk_action = menu.addAction("SNMP Walk")
        tracert_action = menu.addAction("Traceroute (ICMP MTR)")
        ping_action    = menu.addAction("PING ICMP")
        menu.addSeparator()
        copy_action = menu.addAction("Copy IP Address")
        menu.addSeparator()
        delete_action = menu.addAction("Remove from Quick Connect")

        action = menu.exec(self.ssh_profiles_tree.viewport().mapToGlobal(pos))

        if action == edit_action:
            self._edit_ssh_profile(profile)
            return
        elif action == delete_action:
            self.config.delete_ssh_profile(profile['name'])
            self.refresh_ssh_profiles()
            return
        elif action == http_action:
            import webbrowser
            webbrowser.open(f"http://{ip}")
        elif action == https_action:
            import webbrowser
            webbrowser.open(f"https://{ip}")
        elif action == ipscan_action:
            self.scan_network_input.setText(ip)
            self.scan_mask_combo.setCurrentText("32")
            self._scan_method_btn_clicked("TCP")
            self.switch_tab(2)
            self._start_scan()
        elif action == snmpwalk_action:
            self.snmp_host_input.setText(ip)
            self._snmp_type_btn_clicked("snmpwalk")
            self.switch_tab(4)
            self.execute_snmp_query()
        elif action == tracert_action:
            self.traceroute_target_input.setText(ip)
            for _k, _b in self._traceroute_method_btns.items():
                _b.setChecked(_k == 'ICMP')
            self.traceroute_current_method = 'ICMP'
            self._traceroute_method_changed('ICMP')
            self.switch_tab(3)
            self._start_traceroute()
        elif action == ping_action:
            self.traceroute_target_input.setText(ip)
            for _k, _b in self._traceroute_method_btns.items():
                _b.setChecked(_k == 'Ping ICMP')
            self.traceroute_current_method = 'Ping ICMP'
            self._traceroute_method_changed('Ping ICMP')
            self.switch_tab(3)
            self._start_ping()
        elif action == copy_action:
            QApplication.clipboard().setText(ip)

    def _on_save_password_toggled(self, state):
        """When 'Save password' is checked, persist username + password to the active profile."""
        profile_name = getattr(self, '_editing_profile_name', '') or getattr(self, '_pending_profile_name', '')
        if not profile_name:
            return
        import base64, json
        profiles = self.config.get_ssh_profiles()
        for p in profiles:
            if p.get('name') == profile_name:
                if state == Qt.CheckState.Checked.value:
                    pw = self.ssh_password.text()
                    p['password'] = base64.b64encode(pw.encode()).decode() if pw else ''
                    p['username'] = self.ssh_username.text()
                else:
                    p['password'] = ''
                break
        self.config.set('ssh_profiles', json.dumps(profiles))

    def _edit_ssh_profile(self, profile):
        """Populate the Remote Connection form with the selected profile for editing."""
        # Expand the Remote Connection collapsible section if it is collapsed
        if hasattr(self, 'ssh_rc_content') and not self.ssh_rc_content.isVisible():
            self._toggle_ssh_remote_connection()

        protocol = profile.get('protocol', 'SSH')
        self._ssh_protocol_btn_clicked(protocol)

        self.ssh_host.setText(profile.get('host', ''))
        self.ssh_port.setText(str(profile.get('port', '22')))
        self.ssh_username.setText(profile.get('username', ''))

        import base64
        raw_pw = profile.get('password', '')
        try:
            password = base64.b64decode(raw_pw.encode()).decode() if raw_pw else ''
        except Exception:
            password = raw_pw
        self.ssh_password.setText(password)
        self.ssh_save_password.blockSignals(True)
        self.ssh_save_password.setChecked(bool(password))
        self.ssh_save_password.blockSignals(False)

        vendor = profile.get('vendor', 'Default')
        if hasattr(self, 'vendor_combo_btn'):
            self.vendor_combo_btn.setText(vendor)
        self._current_vendor = vendor

        # Store original name/group so the Save dialog pre-fills them
        self._editing_profile_name  = profile.get('name', '')
        self._editing_profile_group = profile.get('group', 'Default')
        self._pending_terminal_mode = profile.get('terminal_mode', 'auto')

        # Scroll the form into view
        self.ssh_host.setFocus()

    def _add_ip_to_ssh_list(self, ip):
        """Add a scanned IP to the SSH Quick Connect list under group Default."""
        existing = [p.get('host') for p in self.config.get_ssh_profiles()]
        if ip in existing:
            QMessageBox.information(self, "SSH List", f"{ip} is already in the SSH list.")
            return
        self.config.save_ssh_profile(
            name=ip, host=ip, port='22', username='',
            auth_method='password', key_path='',
            protocol='SSH', vendor='Default', group='Default'
        )
        self.refresh_ssh_profiles()
        QMessageBox.information(self, "SSH List", f"{ip} added to Quick Connect (group Default).")

    def _scan_open_connection(self, host, protocol):
        """Open SSH or Telnet connection to a host from scan results"""
        if protocol == 'ssh':
            if not SSH_AVAILABLE:
                QMessageBox.critical(self, "Error",
                    "paramiko library is not installed.\n\nInstall with: pip install paramiko")
                return
            port = "22"
        else:
            if not TELNET_AVAILABLE:
                QMessageBox.critical(self, "Error",
                    "telnetlib is not available.\n\nInstall with: pip install standard-telnetlib")
                return
            port = "23"

        # Ask for username and password
        login_dialog = QDialog(self)
        login_dialog.setWindowTitle(f"{protocol.upper()} — {host}")
        login_dialog.setModal(True)

        dlg_layout = QVBoxLayout()
        dlg_layout.setSpacing(8)

        port_layout = QHBoxLayout()
        port_label = QLabel("Port:")
        port_input = QLineEdit(port)
        port_input.setFixedWidth(80)
        port_layout.addWidget(port_label)
        port_layout.addWidget(port_input)
        port_layout.addStretch()
        dlg_layout.addLayout(port_layout)

        username_input = QLineEdit()
        username_input.setPlaceholderText("Username")
        dlg_layout.addWidget(username_input)

        password_input = QLineEdit()
        password_input.setPlaceholderText("Password")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        dlg_layout.addWidget(password_input)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("Connect")
        ok_btn.clicked.connect(login_dialog.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(login_dialog.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        dlg_layout.addLayout(btn_layout)

        login_dialog.setLayout(dlg_layout)

        if login_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        username = username_input.text().strip()
        password = password_input.text()
        port = port_input.text().strip()

        if protocol == 'ssh' and not username:
            QMessageBox.warning(self, "Warning", "Username is required for SSH.")
            return

        # Launch connection via ConnectionWorker
        self._pending_profile_name = None
        self.connection_worker = ConnectionWorker(
            protocol, host, port, username, password
        )
        self.connection_worker.connection_ready.connect(self.on_connection_ready)
        self.connection_worker.connection_failed.connect(self.on_connection_failed)
        self.connection_worker.start()

    def create_ssh_page(self):
        """Create the SSH connection configuration page"""
        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        combo_width = 200

        # Style for QLineEdit fields (compact)
        line_edit_style = """
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
            }
        """

        # === Remote Connection Group (collapsible via title click) ===
        ssh_group = _CollapsibleGroupBox("▾  Remote Connection")
        ssh_group.setCursor_hand()
        ssh_group.toggle_requested.connect(self._toggle_ssh_remote_connection)
        self.ssh_rc_group = ssh_group
        ssh_group_layout = QVBoxLayout()
        ssh_group_layout.setContentsMargins(8, 2, 8, 6)
        ssh_group_layout.setSpacing(2)

        # Collapsible content widget
        self.ssh_rc_content = QWidget()
        ssh_layout = QFormLayout()
        ssh_layout.setVerticalSpacing(4)
        ssh_layout.setContentsMargins(0, 4, 0, 0)
        ssh_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Protocol selection (SSH/Telnet) - toggle buttons
        protocol_widget = QWidget()
        protocol_layout = QHBoxLayout()
        protocol_layout.setContentsMargins(0, 0, 0, 0)
        protocol_layout.setSpacing(6)

        protocol_btn_style = """
            QPushButton {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 12px;
                background-color: #f5f5f5;
                color: #333333;
                font-size: 9pt;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
            QPushButton:checked {
                background-color: #4CAF50;
                color: #ffffff;
                border: 1px solid #4CAF50;
                font-weight: bold;
            }
        """

        self._ra_proto_icons = {
            'SSH':    self.get_icon_path('ssh2.svg'),
            'Telnet': self.get_icon_path('telnet.svg'),
            'VNC':    self.get_icon_path('vnc.svg'),
            'RDP':    self.get_icon_path('rdp.svg'),
        }
        _ra_proto_icons = self._ra_proto_icons

        self.protocol_ssh_btn = QPushButton("SSH")
        self.protocol_ssh_btn.setCheckable(True)
        self.protocol_ssh_btn.setChecked(True)
        self.protocol_ssh_btn.setFixedWidth(90)
        self.protocol_ssh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.protocol_ssh_btn.setStyleSheet(protocol_btn_style)
        if _ra_proto_icons['SSH']:
            self.protocol_ssh_btn.setIcon(load_svg_icon_dual(_ra_proto_icons['SSH'], 14))
            self.protocol_ssh_btn.setIconSize(QSize(14, 14))
        self.protocol_ssh_btn.clicked.connect(lambda: self._ssh_protocol_btn_clicked("SSH"))

        self.protocol_telnet_btn = QPushButton("Telnet")
        self.protocol_telnet_btn.setCheckable(True)
        self.protocol_telnet_btn.setFixedWidth(90)
        self.protocol_telnet_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.protocol_telnet_btn.setStyleSheet(protocol_btn_style)
        if _ra_proto_icons['Telnet']:
            self.protocol_telnet_btn.setIcon(load_svg_icon_dual(_ra_proto_icons['Telnet'], 14))
            self.protocol_telnet_btn.setIconSize(QSize(14, 14))
        self.protocol_telnet_btn.clicked.connect(lambda: self._ssh_protocol_btn_clicked("Telnet"))

        self.protocol_vnc_btn = QPushButton("VNC")
        self.protocol_vnc_btn.setCheckable(True)
        self.protocol_vnc_btn.setFixedWidth(90)
        self.protocol_vnc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.protocol_vnc_btn.setStyleSheet(protocol_btn_style)
        if _ra_proto_icons['VNC']:
            self.protocol_vnc_btn.setIcon(load_svg_icon_dual(_ra_proto_icons['VNC'], 14))
            self.protocol_vnc_btn.setIconSize(QSize(14, 14))
        self.protocol_vnc_btn.clicked.connect(lambda: self._ssh_protocol_btn_clicked("VNC"))

        self.protocol_rdp_btn = QPushButton("RDP")
        self.protocol_rdp_btn.setCheckable(True)
        self.protocol_rdp_btn.setFixedWidth(90)
        self.protocol_rdp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.protocol_rdp_btn.setStyleSheet(protocol_btn_style)
        if _ra_proto_icons['RDP']:
            self.protocol_rdp_btn.setIcon(load_svg_icon_dual(_ra_proto_icons['RDP'], 14))
            self.protocol_rdp_btn.setIconSize(QSize(14, 14))
        self.protocol_rdp_btn.clicked.connect(lambda: self._ssh_protocol_btn_clicked("RDP"))

        protocol_layout.addWidget(self.protocol_ssh_btn)
        protocol_layout.addWidget(self.protocol_telnet_btn)
        protocol_layout.addWidget(self.protocol_vnc_btn)
        protocol_layout.addWidget(self.protocol_rdp_btn)
        protocol_layout.addStretch()
        protocol_widget.setLayout(protocol_layout)
        ssh_layout.addRow("Protocol:", protocol_widget)

        # Store protocol buttons for easy access
        self.ssh_protocol_buttons = {
            'SSH': self.protocol_ssh_btn,
            'Telnet': self.protocol_telnet_btn,
            'VNC': self.protocol_vnc_btn,
            'RDP': self.protocol_rdp_btn,
        }
        self.ssh_current_protocol = "SSH"

        # Host + Port inline
        host_port_widget = QWidget()
        host_port_layout = QHBoxLayout()
        host_port_layout.setContentsMargins(0, 0, 0, 0)
        host_port_layout.setSpacing(4)

        self.ssh_host = QLineEdit()
        self.ssh_host.setFixedWidth(combo_width)
        self.ssh_host.setPlaceholderText("192.168.1.1 or hostname")
        self.ssh_host.setToolTip("SSH/Telnet server hostname or IP address")
        self.ssh_host.setStyleSheet(line_edit_style)

        port_sep = QLabel(":")
        port_sep.setStyleSheet("color: #888888;")
        port_sep.setFixedWidth(8)

        self.ssh_port = QLineEdit()
        self.ssh_port.setFixedWidth(55)
        self.ssh_port.setText("22")
        self.ssh_port.setToolTip("SSH/Telnet port (default: 22 for SSH, 23 for Telnet)")
        self.ssh_port.setStyleSheet(line_edit_style)

        host_port_layout.addWidget(self.ssh_host)
        host_port_layout.addWidget(port_sep)
        host_port_layout.addWidget(self.ssh_port)
        host_port_layout.addStretch()
        host_port_widget.setLayout(host_port_layout)
        ssh_layout.addRow("Host:", host_port_widget)

        # Username
        self.ssh_username = QLineEdit()
        self.ssh_username.setFixedWidth(combo_width)
        self.ssh_username.setPlaceholderText("admin")
        self.ssh_username.setToolTip("Username for authentication")
        self.ssh_username.setStyleSheet(line_edit_style)
        ssh_layout.addRow("Username:", self.ssh_username)

        # Password (for both SSH and Telnet)
        self.ssh_password = QLineEdit()
        self.ssh_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_password.setFixedWidth(combo_width)
        self.ssh_password.setPlaceholderText("Leave blank to be prompted")
        self.ssh_password.setToolTip("Password for authentication (optional)")
        self.ssh_password.setStyleSheet(line_edit_style)

        self.ssh_save_password = QCheckBox("Save password")
        self.ssh_save_password.setToolTip("Save password in profile for automatic login")
        self.ssh_save_password.setStyleSheet(
            "QCheckBox { background: transparent; color: #333333; }"
            "QCheckBox::indicator { background: #ffffff; border: 1px solid #aaaaaa; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background: #4CAF50; border-color: #4CAF50; }"
        )

        _show_pw_btn = QToolButton()
        _show_pw_btn.setText("👁")
        _show_pw_btn.setFixedSize(28, 28)
        _show_pw_btn.setCheckable(True)
        _show_pw_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _show_pw_btn.setToolTip("Show / hide password")
        _show_pw_btn.setStyleSheet("""
            QToolButton { background: transparent; border: 1px solid #aaaaaa;
                          border-radius: 5px; font-size: 15px; color: #333333; }
            QToolButton:hover   { background: #e8e8e8; border-color: #888888; }
            QToolButton:checked { background: #e8f5e9; border-color: #81c784; color: #2e7d32; }
        """)
        _show_pw_btn.toggled.connect(
            lambda on: self.ssh_password.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        self.ssh_save_password.stateChanged.connect(self._on_save_password_toggled)

        _pw_row = QWidget()
        _pw_layout = QHBoxLayout(_pw_row)
        _pw_layout.setContentsMargins(0, 0, 0, 0)
        _pw_layout.setSpacing(6)
        _pw_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        _pw_layout.addWidget(self.ssh_password)
        _pw_layout.addWidget(_show_pw_btn)
        self.ssh_save_password.setFixedHeight(self.ssh_password.sizeHint().height())
        _pw_layout.addWidget(self.ssh_save_password)
        ssh_layout.addRow("Password:", _pw_row)

        # SSH Key checkbox (for SSH only)
        self.use_ssh_key = QCheckBox("Use SSH Key instead of password")
        self.use_ssh_key.setStyleSheet("""
            QCheckBox { color: #333333; font-size: 9pt; }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 2px solid #aaaaaa;
                background-color: #ffffff;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #4caf50;
                background-color: #4caf50;
            }
        """)
        self.use_ssh_key.toggled.connect(self.toggle_ssh_key)
        ssh_layout.addRow("", self.use_ssh_key)

        # SSH Key file field (hidden by default)
        self.ssh_key_widget = QWidget()
        key_layout = QHBoxLayout()
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(5)

        self.ssh_key_path = QLineEdit()
        self.ssh_key_path.setFixedWidth(combo_width - 30)
        self.ssh_key_path.setPlaceholderText("~/.ssh/id_rsa")
        self.ssh_key_path.setStyleSheet(line_edit_style)

        self.ssh_key_browse = QPushButton()
        self.ssh_key_browse.setFixedSize(24, 24)
        self.ssh_key_browse.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_FileIcon))
        self.ssh_key_browse.setToolTip("Browse for SSH key file")
        self.ssh_key_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ssh_key_browse.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #bdbdbd;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
                border: 1px solid #9e9e9e;
            }
        """)
        self.ssh_key_browse.clicked.connect(self.browse_ssh_key)

        key_layout.addWidget(self.ssh_key_path)
        key_layout.addWidget(self.ssh_key_browse)
        self.ssh_key_widget.setLayout(key_layout)
        self.ssh_key_widget.setVisible(False)
        ssh_layout.addRow("Key File:", self.ssh_key_widget)
        # Hide the "Key File:" label initially (shown only when SSH key is selected)
        _key_lbl = ssh_layout.labelForField(self.ssh_key_widget)
        if _key_lbl:
            _key_lbl.setVisible(False)

        # RDP resolution — only shown when RDP protocol is active
        self.rdp_res_widget = QWidget()
        _rdp_res_layout = QHBoxLayout(self.rdp_res_widget)
        _rdp_res_layout.setContentsMargins(0, 0, 0, 0)
        _rdp_res_layout.setSpacing(6)
        self.rdp_resolution = QComboBox()
        self.rdp_resolution.addItems([
            "Fullscreen", "1920x1080", "1600x900", "1366x768",
            "1280x800", "1280x720", "1024x768", "800x600", "Custom",
        ])
        self.rdp_resolution.setFixedWidth(130)
        self.rdp_resolution.setStyleSheet(line_edit_style)
        self.rdp_resolution.currentTextChanged.connect(self._on_rdp_resolution_changed)
        self.rdp_custom_w = QLineEdit()
        self.rdp_custom_w.setPlaceholderText("W")
        self.rdp_custom_w.setFixedWidth(55)
        self.rdp_custom_w.setStyleSheet(line_edit_style)
        self.rdp_custom_w.setVisible(False)
        _rdp_x_lbl = QLabel("×")
        _rdp_x_lbl.setStyleSheet("color: #888888;")
        _rdp_x_lbl.setVisible(False)
        self._rdp_x_lbl = _rdp_x_lbl
        self.rdp_custom_h = QLineEdit()
        self.rdp_custom_h.setPlaceholderText("H")
        self.rdp_custom_h.setFixedWidth(55)
        self.rdp_custom_h.setStyleSheet(line_edit_style)
        self.rdp_custom_h.setVisible(False)
        _rdp_depth_lbl = QLabel("Colors:")
        _rdp_depth_lbl.setStyleSheet("color: #555555; font-size: 9pt;")
        self.rdp_color_depth = QComboBox()
        self.rdp_color_depth.addItems(["32 bit", "24 bit", "16 bit", "15 bit", "8 bit"])
        self.rdp_color_depth.setFixedWidth(105)
        self.rdp_color_depth.setStyleSheet(line_edit_style)

        _rdp_res_layout.addWidget(self.rdp_resolution)
        _rdp_res_layout.addWidget(self.rdp_custom_w)
        _rdp_res_layout.addWidget(_rdp_x_lbl)
        _rdp_res_layout.addWidget(self.rdp_custom_h)
        _rdp_res_layout.addSpacing(12)
        _rdp_res_layout.addWidget(_rdp_depth_lbl)
        _rdp_res_layout.addWidget(self.rdp_color_depth)
        _rdp_res_layout.addStretch()
        self.rdp_res_widget.setVisible(False)
        ssh_layout.addRow("Resolution:", self.rdp_res_widget)
        self._rdp_res_lbl = ssh_layout.labelForField(self.rdp_res_widget)
        if self._rdp_res_lbl:
            self._rdp_res_lbl.setVisible(False)

        # Save button inside Remote Connection
        self.save_profile_btn = QPushButton("Save")
        self.save_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #78909c;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 5px 18px;
            }
            QPushButton:hover { background-color: #607d8b; }
        """)
        self.save_profile_btn.clicked.connect(self.save_current_ssh_profile)
        _save_row = QHBoxLayout()
        _save_row.setContentsMargins(0, 4, 0, 0)
        _save_row.addStretch()
        _save_row.addWidget(self.save_profile_btn)
        ssh_layout.addRow("", _save_row_w := QWidget())
        _save_row_w.setLayout(_save_row)

        self.ssh_rc_content.setLayout(ssh_layout)
        ssh_group_layout.addWidget(self.ssh_rc_content)
        ssh_group.setLayout(ssh_group_layout)

        # Restore collapsed state from config
        if self.config.get('ssh_rc_collapsed'):
            self.ssh_rc_content.setVisible(False)
            self.ssh_rc_group.setTitle("▸  Remote Connection")

        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 30))
        ssh_group.setGraphicsEffect(shadow)
        ssh_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        main_layout.addWidget(ssh_group)

        # === Saved Profiles Group ===
        profiles_group = QGroupBox("Quick Connect")
        profiles_layout = QVBoxLayout()
        profiles_layout.setContentsMargins(10, 2, 10, 8)
        profiles_layout.setSpacing(6)

        # Profiles tree
        self.ssh_profiles_tree = SshProfilesTree()
        self.ssh_profiles_tree.setColumnCount(5)
        self.ssh_profiles_tree.setHeaderLabels(["Name", "IP", "Port", "Protocol", "Vendor"])
        self.ssh_profiles_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.ssh_profiles_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.ssh_profiles_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.ssh_profiles_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.ssh_profiles_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.ssh_profiles_tree.setColumnWidth(1, 150)
        self.ssh_profiles_tree.setColumnWidth(2, 38)
        self.ssh_profiles_tree.setColumnWidth(3, 62)
        self.ssh_profiles_tree.setColumnWidth(4, 42)
        # Center-align all column headers
        for col in range(5):
            self.ssh_profiles_tree.headerItem().setTextAlignment(
                col, Qt.AlignmentFlag.AlignCenter)
        self.ssh_profiles_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ssh_profiles_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ssh_profiles_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ssh_profiles_tree.setRootIsDecorated(False)
        self.ssh_profiles_tree.setIndentation(14)
        self.ssh_profiles_tree.itemDoubleClicked.connect(self.load_ssh_profile_from_tree)
        self.ssh_profiles_tree.itemExpanded.connect(self._ssh_group_expanded)
        self.ssh_profiles_tree.itemCollapsed.connect(self._ssh_group_collapsed)
        self.ssh_profiles_tree.reordered.connect(self._ssh_tree_save_order)
        self.ssh_profiles_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #e8e8e8;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
            }
            QTreeWidget::item {
                padding: 2px 2px;
                min-height: 36px;
            }
            QTreeWidget::item:selected {
                background-color: #4caf50;
                color: white;
            }
            QTreeWidget::branch {
                image: none;
                background: transparent;
            }
            QHeaderView::section {
                background-color: #d0d0d0;
                color: #333333;
                padding: 4px;
                border: none;
                font-weight: bold;
                font-size: 9pt;
                qproperty-alignment: AlignCenter;
            }
        """)
        profiles_layout.addWidget(self.ssh_profiles_tree)
        self.ssh_profiles_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ssh_profiles_tree.customContextMenuRequested.connect(self._ssh_profile_context_menu)


        profiles_group.setLayout(profiles_layout)

        # Add shadow
        shadow3 = QGraphicsDropShadowEffect()
        shadow3.setBlurRadius(15)
        shadow3.setXOffset(0)
        shadow3.setYOffset(2)
        shadow3.setColor(QColor(0, 0, 0, 30))
        profiles_group.setGraphicsEffect(shadow3)

        profiles_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(profiles_group, 1)

        # Connect SSH button (full-width at bottom)
        self.ssh_connect_btn = QPushButton("CONNECT SSH")
        self.ssh_connect_btn.setMinimumHeight(45)
        self.ssh_connect_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.ssh_connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ssh_connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
            QPushButton:pressed {
                background-color: #388e3c;
            }
        """)
        self.ssh_connect_btn.clicked.connect(self.connect_ssh)
        _conn_icon = load_svg_icon_dual(self._ra_proto_icons.get('SSH'), 18, '#ffffff', '#ffffff')
        if _conn_icon:
            self.ssh_connect_btn.setIcon(_conn_icon)
            self.ssh_connect_btn.setIconSize(QSize(18, 18))
            self.ssh_connect_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.ssh_connect_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.ssh_connect_btn.setGraphicsEffect(_btn_shadow)
        main_layout.addWidget(self.ssh_connect_btn)

        page.setLayout(main_layout)

        # Load saved SSH profiles
        self.refresh_ssh_profiles()

        return page

    def get_icon_path(self, icon_name):
        """Get the path to an icon from assets/icons for different installation types"""
        # Local repo assets take priority so in-repo changes are always reflected
        # without requiring a system-wide reinstall.
        assets_path = os.path.join(os.path.dirname(__file__), f'assets/icons/{icon_name}')
        if os.path.exists(assets_path):
            return assets_path
        # Check for PyInstaller / PyOxidizer / cx_Freeze bundle
        if getattr(sys, '_MEIPASS', None):
            bundle_path = os.path.join(sys._MEIPASS, f'assets/icons/{icon_name}')
            if os.path.exists(bundle_path):
                return bundle_path
        # Check for Flatpak
        flatpak_path = f'/app/share/io.github.benjamimgois.cetus/icons/{icon_name}'
        if os.path.exists(flatpak_path):
            return flatpak_path
        # Check for AppImage
        if os.environ.get('APPDIR'):
            appdir = os.environ.get('APPDIR')
            appimage_path = os.path.join(appdir, f'usr/share/cetus/icons/{icon_name}')
            if os.path.exists(appimage_path):
                return appimage_path
        # Check for system installation (AUR, Debian, etc.)
        system_path = f'/usr/share/cetus/icons/{icon_name}'
        if os.path.exists(system_path):
            return system_path
        # Legacy: root directory
        root_path = os.path.join(os.path.dirname(__file__), icon_name)
        if os.path.exists(root_path):
            return root_path
        return None

    def get_arrow_icon_path(self):
        """Get the path to arrow_down.svg"""
        return self.get_icon_path('arrow_down.svg') or ''

    def get_tab_icon_path(self, icon_name):
        """Get the path to tab icons"""
        return self.get_icon_path(icon_name)

    def get_vendor_icon_path(self, vendor):
        """Get the path to vendor icon SVG"""
        vendor_file = vendor.lower().replace(' ', '') + '.svg'
        # Check multiple install paths for vendors subdir
        for base in [
            '/app/share/io.github.benjamimgois.cetus/vendors',
            os.path.join(os.environ.get('APPDIR', ''), 'usr/share/cetus/vendors'),
            os.path.join(os.path.dirname(__file__), 'assets/vendors'),
            '/usr/share/cetus/vendors',
        ]:
            path = os.path.join(base, vendor_file)
            if os.path.exists(path):
                return path
        # Fallback to generic
        for base in [
            '/app/share/io.github.benjamimgois.cetus/vendors',
            os.path.join(os.environ.get('APPDIR', ''), 'usr/share/cetus/vendors'),
            os.path.join(os.path.dirname(__file__), 'assets/vendors'),
            '/usr/share/cetus/vendors',
        ]:
            path = os.path.join(base, 'default.svg')
            if os.path.exists(path):
                return path
        return None

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(50, self._restore_terminals)

    def _restore_terminals(self):
        for terminal in list(self.open_terminals):
            terminal.show()

    def apply_styles(self):
        """Apply theme based on current settings"""
        theme = self.config.get('theme')
        if theme == 'dark':
            self.apply_dark_theme()
        else:
            self.apply_light_theme()

    def apply_light_theme(self):
        """Apply modern light theme to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
        """)

    def apply_dark_theme(self):
        """Apply dark theme to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            QGroupBox, QFrame {
                border: 1px solid #404040;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 18px;
                padding-left: 6px;
                padding-right: 6px;
                padding-bottom: 6px;
                background-color: #3c3f41;
                color: #d4d4d4;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                color: #d4d4d4;
                font-size: 10pt;
                font-weight: bold;
                background-color: #3c3f41;
            }
            QComboBox {
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 4px 28px 4px 10px;
                background-color: #404040;
                min-height: 24px;
                color: #d4d4d4;
                font-size: 10pt;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #555555;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
                background-color: transparent;
            }
            QComboBox::down-arrow {
                image: url(""" + self.get_arrow_icon_path() + """);
                width: 12px;
                height: 12px;
            }
            QComboBox:hover {
                border: 1px solid #777777;
                background-color: #4a4a4a;
            }
            QComboBox:focus {
                border: 2px solid #4caf50;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #555555;
                border-radius: 6px;
                background-color: #404040;
                selection-background-color: #5a5a5a;
                selection-color: #d4d4d4;
                color: #d4d4d4;
                padding: 4px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px;
                min-height: 24px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #4a4a4a;
            }
            QPushButton {
                background-color: #4caf50;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
            QPushButton:pressed {
                background-color: #388e3c;
            }
            QLabel {
                color: #d4d4d4;
            }
            QFormLayout QLabel {
                color: #b0b0b0;
                font-size: 9pt;
            }
            QLineEdit {
                border: 1px solid #555555;
                border-radius: 6px;
                background-color: #404040;
                color: #d4d4d4;
                font-size: 9pt;
                padding: 2px 8px;
            }
            QLineEdit:hover {
                border-color: #777777;
                background-color: #4a4a4a;
            }
            QCheckBox {
                spacing: 5px;
                font-size: 9pt;
                color: #d4d4d4;
            }
            QCheckBox:hover {
                color: #ffffff;
            }
            QDialog, QMessageBox, QInputDialog {
                background-color: palette(window);
                color: palette(window-text);
            }
            QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {
                color: palette(window-text);
                font-size: 9pt;
                font-weight: normal;
            }
            QDialog QLineEdit, QInputDialog QLineEdit {
                background-color: palette(base);
                color: palette(text);
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 9pt;
            }
            QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
                background-color: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 4px 12px;
                min-width: 60px;
                font-weight: normal;
                font-size: 9pt;
            }
            QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
                background-color: palette(light);
            }
            QDialog QPushButton:default, QMessageBox QPushButton:default, QInputDialog QPushButton:default {
                border: 2px solid palette(highlight);
            }
            QToolTip {
                background-color: #424242;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 9pt;
            }
            QScrollBar:vertical {
                background: #2b2b2b;
                width: 8px;
                border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #555555;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #777777;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #2b2b2b;
                height: 8px;
                border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal {
                background: #555555;
                border-radius: 4px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #777777;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QTabWidget::pane {
                border: 1px solid #404040;
                background-color: #3c3f41;
            }
            QTabBar::tab {
                background-color: #2b2b2b;
                color: #d4d4d4;
                padding: 8px 16px;
                border: 1px solid #404040;
            }
            QTabBar::tab:selected {
                background-color: #3c3f41;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #4a4a4a;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #d4d4d4;
            }
            QTextEdit, QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #404040;
            }
            QTableWidget, QTreeWidget {
                background-color: #2b2b2b;
                color: #d4d4d4;
                gridline-color: #404040;
            }
            QHeaderView::section {
                background-color: #3c3f41;
                color: #d4d4d4;
                border: 1px solid #404040;
                padding: 4px;
            }
            QListWidget {
                background-color: #2b2b2b;
                color: #d4d4d4;
                border: 1px solid #404040;
            }
            QListWidget::item:selected {
                background-color: #4caf50;
                color: #ffffff;
            }
            QProgressBar {
                background-color: #404040;
                color: #d4d4d4;
                border: 1px solid #555555;
                border-radius: 4px;
                text-color: #d4d4d4;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
            }
            QSpinBox {
                background-color: #404040;
                color: #d4d4d4;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #555555;
                color: #d4d4d4;
                border-radius: 3px;
            }
            QRadioButton {
                color: #d4d4d4;
            }
            QRadioButton:checked {
                color: #4caf50;
            }
            QMenuBar {
                background-color: #2b2b2b;
                color: #d4d4d4;
            }
            QMenuBar::item:selected {
                background-color: #404040;
            }
        """)

    def apply_light_theme(self):
        """Apply modern light theme to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QGroupBox {
                border: 1px solid #e8e8e8;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 18px;
                padding-left: 6px;
                padding-right: 6px;
                padding-bottom: 6px;
                background-color: #ffffff;
                color: #2c2c2c;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                color: #2c2c2c;
                font-size: 10pt;
                font-weight: bold;
                background-color: #ffffff;
            }
            QComboBox {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 28px 4px 10px;
                background-color: #fafafa;
                min-height: 24px;
                color: #2c2c2c;
                font-size: 10pt;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 25px;
                border-left: 1px solid #d0d0d0;
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
                background-color: transparent;
            }
            QComboBox::down-arrow {
                image: url(""" + self.get_arrow_icon_path() + """);
                width: 12px;
                height: 12px;
            }
            QComboBox:hover {
                border: 1px solid #a0a0a0;
                background-color: #ffffff;
            }
            QComboBox:focus {
                border: 2px solid #4caf50;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background-color: #ffffff;
                selection-background-color: #e8f5e9;
                selection-color: #2c2c2c;
                color: #2c2c2c;
                padding: 4px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px;
                min-height: 24px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #f5f5f5;
            }
            QPushButton {
                background-color: #4caf50;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
            QPushButton:pressed {
                background-color: #388e3c;
            }
            QLabel {
                color: #2c2c2c;
            }
            QFormLayout QLabel {
                color: #4a4a4a;
                font-size: 9pt;
            }
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background-color: #fafafa;
                color: #2c2c2c;
                font-size: 9pt;
                padding: 2px 8px;
            }
            QLineEdit:hover {
                border-color: #a0a0a0;
                background-color: #ffffff;
            }
            QCheckBox {
                spacing: 5px;
                font-size: 9pt;
                color: #2c2c2c;
            }
            QCheckBox:hover {
                color: #1a1a1a;
            }
            QDialog, QMessageBox, QInputDialog {
                background-color: palette(window);
                color: palette(window-text);
            }
            QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {
                color: palette(window-text);
                font-size: 9pt;
                font-weight: normal;
            }
            QDialog QLineEdit, QInputDialog QLineEdit {
                background-color: palette(base);
                color: palette(text);
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 4px 6px;
                font-size: 9pt;
            }
            QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
                background-color: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 4px 12px;
                min-width: 60px;
                font-weight: normal;
                font-size: 9pt;
            }
            QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
                background-color: palette(light);
            }
            QDialog QPushButton:default, QMessageBox QPushButton:default, QInputDialog QPushButton:default {
                border: 2px solid palette(highlight);
            }
            QToolTip {
                background-color: #424242;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 9pt;
            }
            QScrollBar:vertical {
                background: #f0f0f0;
                width: 8px;
                border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #c8c8c8;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a0a0a0;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #f0f0f0;
                height: 8px;
                border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal {
                background: #c8c8c8;
                border-radius: 4px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #a0a0a0;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

    def load_settings(self):
        """Load saved settings and apply to ComboBoxes"""
        # Load and set port type
        port_type = self.config.get('port_type') or 'USB'
        self._port_type_clicked(port_type if port_type in self._port_type_btns else 'USB')

        # Load and set baudrate
        baudrate = self.config.get('baudrate')
        index = self.baudrate.findText(baudrate)
        if index >= 0:
            self.baudrate.setCurrentIndex(index)

        # Load and set serial_config (with backward compat for old individual keys)
        serial_config_saved = self.config.get('serial_config')
        if serial_config_saved:
            idx = self.serial_config.findText(serial_config_saved)
            if idx >= 0:
                self.serial_config.setCurrentIndex(idx)
        else:
            # Reconstruct from legacy individual keys
            databits = self.config.get('databits') or '8'
            parity = self.config.get('parity') or 'None'
            stopbits = self.config.get('stopbits') or '1'
            config_text = self._build_serial_config_text(databits, parity, stopbits)
            idx = self.serial_config.findText(config_text)
            if idx >= 0:
                self.serial_config.setCurrentIndex(idx)

        # Load and set flow
        flow_saved = self.config.get('flow')
        if flow_saved:
            idx = self.flow.findText(flow_saved)
            if idx >= 0:
                self.flow.setCurrentIndex(idx)

        # Connect signals to save settings when changed
        self.baudrate.currentTextChanged.connect(lambda text: self.config.set('baudrate', text))
        self.serial_config.currentTextChanged.connect(lambda text: self.config.set('serial_config', text))
        self.flow.currentTextChanged.connect(lambda text: self.config.set('flow', text))

    def _port_type_clicked(self, ptype):
        """Handle port type toggle button selection (USB / Serial)."""
        for t, btn in self._port_type_btns.items():
            btn.setChecked(t == ptype)
        self.config.set('port_type', ptype)
        self.update_port_list()
        _ico = load_svg_icon_dual(self._port_type_icons.get(ptype), 18, '#ffffff', '#ffffff')
        if _ico:
            self.connect_btn.setIcon(_ico)
            self.connect_btn.setIconSize(QSize(18, 18))
        else:
            self.connect_btn.setIcon(QIcon())

    def update_port_list(self):
        """Update the list of available ports (cross-platform)"""
        self.port.clear()

        if sys.platform == 'win32':
            # On Windows, use QSerialPortInfo to list COM ports
            try:
                from PyQt6.QtSerialPort import QSerialPortInfo
                ports = [info.portName() for info in QSerialPortInfo.availablePorts()]
            except Exception:
                ports = []
        else:
            port_type = next((t for t, b in self._port_type_btns.items() if b.isChecked()), 'USB')
            # Use glob to search for ports based on type
            if port_type == 'Serial':
                pattern = '/dev/ttyS*'
            else:  # USB
                pattern = '/dev/ttyUSB*'
            ports = sorted(glob.glob(pattern))

        if ports:
            self.port.addItems(ports)
            self.status_label.setText(f"{len(ports)} port(s) found")
            self.status_label.setStyleSheet("color: #2196F3; font-size: 10pt;")
            self.status_led.setStyleSheet("color: #2196F3; font-size: 14px;")
        else:
            self.port.addItem("No ports found")
            self.status_label.setText("No serial ports available")
            self.status_label.setStyleSheet("color: #ff9800; font-size: 10pt;")
            self.status_led.setStyleSheet("color: #ff9800; font-size: 14px;")

    def update_network_interfaces(self):
        """Update the list of network interfaces"""
        interfaces = get_network_interfaces()
        combos = [
            self.tftp_interface,
            self._ftp_srv_interface,
            self._ssh_srv_interface,
            self._smb_srv_interface,
        ]
        for combo in combos:
            combo.clear()
            if interfaces:
                for iface, ip, *_ in interfaces:
                    combo.addItem(f"{iface} ({ip})", ip)
            else:
                combo.addItem("No interfaces found", "")

    def browse_tftp_directory(self):
        """Open dialog to select TFTP directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select TFTP Directory",
            self.tftp_directory.text()
        )
        if directory:
            self.tftp_directory.setText(directory)
            self.refresh_tftp_files()

    def refresh_tftp_files(self):
        """Refresh the TFTP directory file listing"""
        self.tftp_files_table.setRowCount(0)
        directory = self.tftp_directory.text()
        if not os.path.isdir(directory):
            return
        try:
            from datetime import datetime
            entries = sorted(os.listdir(directory))
            for name in entries:
                filepath = os.path.join(directory, name)
                if not os.path.isfile(filepath):
                    continue
                row = self.tftp_files_table.rowCount()
                self.tftp_files_table.insertRow(row)
                self.tftp_files_table.setItem(row, 0, QTableWidgetItem(name))
                # Format size
                size = os.path.getsize(filepath)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                self.tftp_files_table.setItem(row, 1, QTableWidgetItem(size_str))
                # Format date
                mtime = os.path.getmtime(filepath)
                date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                self.tftp_files_table.setItem(row, 2, QTableWidgetItem(date_str))
        except OSError:
            pass

    def toggle_tftp_server(self):
        """Start or stop the TFTP server"""
        if self.tftp_process is not None:
            # Stop server
            self.tftp_process.terminate()
            self.tftp_process.wait()
            self.tftp_process = None
            self.tftp_btn.setText("START TFTP")
            self.tftp_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 4px 16px;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
            """)
            self.tftp_interface.setEnabled(True)
            self.tftp_directory.setEnabled(True)
            self.tftp_browse_btn.setEnabled(True)
        else:
            # Get selected interface IP
            ip = self.tftp_interface.currentData()
            if not ip:
                QMessageBox.warning(self, "Warning", "No network interface selected")
                return

            directory = self.tftp_directory.text()
            if not os.path.isdir(directory):
                QMessageBox.warning(self, "Warning", "Invalid TFTP directory")
                return

            # Build command to run TFTP server
            script_path = os.path.abspath(__file__)
            if sys.platform == 'win32':
                # Windows: no sudo needed; run directly
                cmd = [sys.executable, script_path, '--tftp-server', ip, '69', directory]
            else:
                password, ok = QInputDialog.getText(
                    self, "Sudo Password Required",
                    "TFTP port 69 requires root privileges.\nPlease enter your sudo password:",
                    QLineEdit.EchoMode.Password
                )
                if not ok or not password:
                    return
                cmd = ['sudo', '-S', sys.executable, script_path, '--tftp-server', ip, '69', directory]

            try:
                # Redirect TFTP server output to terminal for debugging
                print(f"[Cetus] Starting TFTP server on {ip}:69")
                print(f"[Cetus] Directory: {directory}")
                
                self.tftp_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=None,  # Inherit parent's stdout (terminal)
                    stderr=None,  # Inherit parent's stderr (terminal)
                    text=False
                )
                # Send password (Linux only)
                if sys.platform != 'win32' and 'password' in locals() and password:
                    self.tftp_process.stdin.write((password + '\n').encode())
                    self.tftp_process.stdin.flush()
                    self.tftp_process.stdin.close()  # Close stdin after sending password
                    password = None  # Clear from memory

                # Wait a moment to check if server started
                import time
                time.sleep(2.0)  # Increased timeout to allow server to start

                if self.tftp_process.poll() is not None:
                    # Process ended, probably failed
                    QMessageBox.critical(
                        self,
                        "Error",
                        f"Failed to start TFTP server.\n\nCheck terminal output for error details."
                    )
                    self.tftp_process = None
                    return

                print(f"[Cetus] TFTP server started successfully")
                
                QMessageBox.information(
                    self,
                    "TFTP Server",
                    f"TFTP server started on {ip}:69\n\n"
                    f"Directory: {directory}\n\n"
                    f"Check terminal for debug messages."
                )

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to start TFTP server.\n\n{str(e)}"
                )
                self.tftp_process = None
                return

            self.tftp_btn.setText("STOP TFTP")
            self.tftp_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 4px 16px;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
            """)
            self.tftp_interface.setEnabled(False)
            self.tftp_directory.setEnabled(False)
            self.tftp_browse_btn.setEnabled(False)

    def _ft_proto_changed(self, proto):
        self._ft_protocol = proto
        # Sync both button sets
        for p, btn in self._ft_srv_proto_btns.items():
            btn.setChecked(p == proto)
        for p, btn in self._ft_cli_proto_btns.items():
            btn.setChecked(p == proto)
        # Update default port
        ports = {'SSH': '22', 'FTP': '21', 'TFTP': '69', 'SMB': '445'}
        self._ft_port_input.setText(ports.get(proto, '22'))
        # Show correct server panel
        proto_idx = {'TFTP': 0, 'FTP': 1, 'SSH': 2, 'SMB': 3}
        self._ft_server_stack.setCurrentIndex(proto_idx.get(proto, 0))
        # Update bottom button label
        if self._ft_mode == 'Server':
            if proto == 'TFTP':
                self._ft_set_action_btn(self.tftp_process is not None, 'TFTP')
            elif proto == 'FTP':
                self._ft_set_action_btn(getattr(self, '_ftp_srv_process', None) is not None, 'FTP')
            elif proto == 'SSH':
                self._ft_set_action_btn(False, 'SSH')   # check_status corrects this
                self._ft_ssh_srv_check_status()
            elif proto == 'SMB':
                self._ft_set_action_btn(False, 'SMB')   # check_status corrects this
                self._ft_smb_srv_check_status()
        else:
            connected = self._ft_conn is not None
            self.tftp_btn.setText("DISCONNECT" if connected else f"CONNECT {proto}")
            self.tftp_btn.setStyleSheet("""
                QPushButton { background-color: #9C27B0; color: white; border: none;
                    border-radius: 8px; padding: 12px; font-weight: bold; font-size: 11pt; }
                QPushButton:hover { background-color: #7B1FA2; }
                QPushButton:pressed { background-color: #4A148C; }""")
            _ico = load_svg_icon_dual(self._ft_proto_icons.get(proto), 18, '#ffffff', '#ffffff')
            if _ico:
                self.tftp_btn.setIcon(_ico)
                self.tftp_btn.setIconSize(QSize(18, 18))
            else:
                self.tftp_btn.setIcon(QIcon())

    def _ft_mode_changed(self, mode):
        self._ft_mode = mode
        # Update segmented buttons
        self._ft_mode_server_btn.setChecked(mode == 'Server')
        self._ft_mode_client_btn.setChecked(mode == 'Client')
        self._ft_stack.setCurrentIndex(0 if mode == 'Server' else 1)
        if mode == 'Server':
            proto = self._ft_protocol
            if proto == 'TFTP':
                self._ft_set_action_btn(self.tftp_process is not None, 'TFTP')
            elif proto == 'FTP':
                self._ft_set_action_btn(getattr(self, '_ftp_srv_process', None) is not None, 'FTP')
            elif proto == 'SSH':
                self._ft_set_action_btn(False, 'SSH')
                self._ft_ssh_srv_check_status()
            elif proto == 'SMB':
                self._ft_set_action_btn(False, 'SMB')
                self._ft_smb_srv_check_status()
        else:
            connected = self._ft_conn is not None
            self.tftp_btn.setText("DISCONNECT" if connected else f"CONNECT {self._ft_protocol}")

    def _ft_action_btn_clicked(self):
        if self._ft_mode == 'Server':
            if self._ft_protocol == 'TFTP':
                self.toggle_tftp_server()
            elif self._ft_protocol == 'FTP':
                self._ft_ftp_srv_toggle()
            elif self._ft_protocol == 'SSH':
                self._ft_ssh_srv_toggle()
            elif self._ft_protocol == 'SMB':
                self._ft_smb_srv_toggle()
        else:
            if self._ft_conn is not None:
                self._ft_client_disconnect()
            else:
                self._ft_client_connect()

    # ── FTP Server ────────────────────────────────────────────────────────
    def _ft_ftp_srv_toggle(self):
        if getattr(self, '_ftp_srv_process', None) is not None:
            self._ftp_srv_process.terminate()
            try:
                self._ftp_srv_process.wait(timeout=3)
            except Exception:
                self._ftp_srv_process.kill()
            self._ftp_srv_process = None
            self.tftp_btn.setText("START FTP")
            self.tftp_btn.setStyleSheet("""
                QPushButton { background-color: #9C27B0; color: white; border: none;
                    border-radius: 8px; padding: 12px; font-weight: bold; font-size: 11pt; }
                QPushButton:hover { background-color: #7B1FA2; }""")
            self._ftp_srv_dir.setEnabled(True)
            self._ftp_srv_port.setEnabled(True)
            self._ftp_srv_user.setEnabled(True)
            self._ftp_srv_pass.setEnabled(True)
            return
        try:
            port = int(self._ftp_srv_port.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Warning", "Invalid port number."); return
        directory = self._ftp_srv_dir.text().strip()
        if not os.path.isdir(directory):
            QMessageBox.warning(self, "Warning", "Invalid directory."); return
        user = self._ftp_srv_user.text().strip() or 'anonymous'
        pw   = self._ftp_srv_pass.text()
        try:
            import pyftpdlib  # noqa: F401 — just check it's installed
        except ImportError:
            QMessageBox.critical(self, "Missing dependency",
                "pyftpdlib is required for FTP server.\n\nInstall with:\n  pip install pyftpdlib")
            return
        script = (
            "import sys, os\n"
            "from pyftpdlib.handlers import FTPHandler\n"
            "from pyftpdlib.servers import FTPServer\n"
            "from pyftpdlib.authorizers import DummyAuthorizer\n"
            f"auth = DummyAuthorizer()\n"
            f"auth.add_user({user!r}, {pw!r}, {directory!r}, perm='elradfmwMT')\n"
            f"auth.add_anonymous({directory!r})\n"
            "h = FTPHandler\n"
            "h.authorizer = auth\n"
            f"srv = FTPServer(('0.0.0.0', {port}), h)\n"
            "srv.serve_forever()\n"
        )
        import tempfile, subprocess
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
        tf.write(script); tf.close()
        if port < 1024:
            cmd = ['pkexec', sys.executable, tf.name]
        else:
            cmd = [sys.executable, tf.name]
        try:
            self._ftp_srv_process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            import time; time.sleep(1.2)
            if self._ftp_srv_process.poll() is not None:
                QMessageBox.critical(self, "Error",
                    f"FTP server failed to start on port {port}.\n\n"
                    "Tip: ports below 1024 require administrator privileges (pkexec).\n"
                    "You can also use port 2121 to avoid this requirement.")
                self._ftp_srv_process = None; return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return
        self.tftp_btn.setText("STOP FTP")
        self.tftp_btn.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white; border: none;
                border-radius: 8px; padding: 12px; font-weight: bold; font-size: 11pt; }
            QPushButton:hover { background-color: #d32f2f; }""")
        self._ftp_srv_dir.setEnabled(False)
        self._ftp_srv_port.setEnabled(False)
        self._ftp_srv_user.setEnabled(False)
        self._ftp_srv_pass.setEnabled(False)

    def _ft_log_append(self, text):
        import datetime
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self._ft_log.appendPlainText(f"[{ts}] {text}")
        self._ft_log.verticalScrollBar().setValue(self._ft_log.verticalScrollBar().maximum())

    def _ft_set_action_btn(self, running: bool, proto: str):
        """Update the action button text and colour to reflect running state."""
        if running:
            self.tftp_btn.setText(f"STOP {proto}")
            self.tftp_btn.setStyleSheet("""
                QPushButton { background-color: #f44336; color: white; border: none;
                    border-radius: 8px; padding: 12px; font-weight: bold; font-size: 11pt; }
                QPushButton:hover { background-color: #d32f2f; }
                QPushButton:pressed { background-color: #b71c1c; }""")
        else:
            self.tftp_btn.setText(f"START {proto}")
            self.tftp_btn.setStyleSheet("""
                QPushButton { background-color: #9C27B0; color: white; border: none;
                    border-radius: 8px; padding: 12px; font-weight: bold; font-size: 11pt; }
                QPushButton:hover { background-color: #7B1FA2; }
                QPushButton:pressed { background-color: #4A148C; }""")
        _ico = load_svg_icon_dual(self._ft_proto_icons.get(proto), 18, '#ffffff', '#ffffff')
        if _ico:
            self.tftp_btn.setIcon(_ico)
            self.tftp_btn.setIconSize(QSize(18, 18))
        else:
            self.tftp_btn.setIcon(QIcon())

    # ── SSH Server (systemctl) ────────────────────────────────────────────
    def _ft_ssh_srv_check_status(self):
        import subprocess
        try:
            r = subprocess.run(['systemctl', 'is-active', 'sshd'], capture_output=True, text=True, timeout=5)
            status = r.stdout.strip()
            color = '#4CAF50' if status == 'active' else '#f44336'
            self._ssh_srv_status_lbl.setText(f"Status: <span style='color:{color};font-weight:bold'>{status}</span>")
            if self._ft_mode == 'Server' and self._ft_protocol == 'SSH':
                self._ft_set_action_btn(status == 'active', 'SSH')
        except Exception as e:
            self._ssh_srv_status_lbl.setText(f"Status: error — {e}")

    def _ft_ssh_srv_toggle(self):
        import subprocess, time
        try:
            r = subprocess.run(['systemctl', 'is-active', 'sshd'], capture_output=True, text=True, timeout=5)
            if r.stdout.strip() == 'active':
                self._ft_log_append("Stopping sshd via pkexec...")
                res = subprocess.run(['pkexec', 'systemctl', 'stop', 'sshd'],
                                     capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                    err = (res.stderr or res.stdout or "pkexec returned error").strip()
                    self._ft_log_append(f"ERROR stop sshd: {err}")
                    QMessageBox.warning(self, "SSH Server", f"Failed to stop SSH service:\n{err}"); return
                self._ft_set_action_btn(False, 'SSH')
                self._ft_log_append("sshd stopped.")
            else:
                self._ft_log_append("Starting sshd via pkexec...")
                res = subprocess.run(['pkexec', 'systemctl', 'start', 'sshd'],
                                     capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                    err = (res.stderr or res.stdout or "pkexec returned error").strip()
                    self._ft_log_append(f"ERROR start sshd: {err}")
                    QMessageBox.warning(self, "SSH Server", f"Failed to start SSH service:\n{err}"); return
                self._ft_set_action_btn(True, 'SSH')
                self._ft_log_append("sshd started.")
            time.sleep(1.0)
            self._ft_ssh_srv_check_status()
        except Exception as e:
            self._ft_log_append(f"EXCEPTION: {e}")
            QMessageBox.warning(self, "SSH Server", str(e))

    # ── SMB Server (systemctl) ────────────────────────────────────────────
    def _ft_smb_srv_check_status(self):
        import subprocess
        self._smb_srv_service = None
        for svc in ('smb', 'smbd', 'samba', 'nmb'):
            try:
                # is-enabled returns 'not-found' for non-existent units
                enabled = subprocess.run(['systemctl', 'is-enabled', svc],
                                         capture_output=True, text=True, timeout=5).stdout.strip()
                if enabled == 'not-found':
                    continue
                active = subprocess.run(['systemctl', 'is-active', svc],
                                        capture_output=True, text=True, timeout=5).stdout.strip()
                color = '#4CAF50' if active == 'active' else '#f44336'
                self._smb_srv_status_lbl.setText(
                    f"Service <b>{svc}</b>: <span style='color:{color};font-weight:bold'>{active}</span>")
                self._smb_srv_service = svc
                if self._ft_mode == 'Server' and self._ft_protocol == 'SMB':
                    self._ft_set_action_btn(active == 'active', 'SMB')
                return
            except Exception:
                continue
        self._smb_srv_status_lbl.setText("Status: Samba service not found")
        self._ft_log_append("SMB: service not found (tried smb, smbd, samba, nmb)")

    def _ft_smb_apply_config(self):
        """Write share block + workgroup to /etc/samba/smb.conf via pkexec."""
        import subprocess, tempfile, os, getpass
        share      = self._smb_share_name.text().strip().replace(' ', '-') or 'cetus-share'
        path       = self._smb_srv_dir.text().strip()
        comment    = self._smb_comment.text().strip()
        wg         = self._smb_workgroup.text().strip() or 'WORKGROUP'
        users      = self._smb_valid_users.text().strip()
        guest      = 'yes' if self._smb_guest_ok.isChecked() else 'no'
        ro         = 'yes' if self._smb_read_only.isChecked() else 'no'
        force_user = getpass.getuser()   # run file access as the current user

        # Build the share block
        block_lines = [
            f'[{share}]',
            f'\tpath = {path}',
            f'\tcomment = {comment}',
            f'\tbrowseable = yes',
            f'\tread only = {ro}',
            f'\tguest ok = {guest}',
            f'\tforce user = {force_user}',
            f'\tcreate mask = 0664',
            f'\tdirectory mask = 0775',
        ]
        if users:
            block_lines.append(f'\tvalid users = {users}')
        block_text = '\n'.join(block_lines)

        # Global settings required for guest access
        guest_globals = [
            ('map to guest',   'bad user'),
            ('guest account',  'nobody'),
        ]

        script = (
            "import re\n"
            "CONF = '/etc/samba/smb.conf'\n"
            f"SHARE  = {share!r}\n"
            f"WG     = {wg!r}\n"
            f"GUEST  = {guest!r}\n"
            f"BLOCK  = {block_text!r}\n"
            f"GUEST_GLOBALS = {guest_globals!r}\n"
            "try:\n"
            "    text = open(CONF).read()\n"
            "except FileNotFoundError:\n"
            "    text = '[global]\\n'\n"
            # workgroup
            "if re.search(r'^\\s*workgroup\\s*=', text, re.MULTILINE):\n"
            "    text = re.sub(r'^(\\s*workgroup\\s*=).*', '\\\\g<1> ' + WG, text, flags=re.MULTILINE)\n"
            "else:\n"
            "    text = re.sub(r'(\\[global\\][^\\[]*?)(?=\\[|$)',\n"
            "                  lambda m: m.group(0) + '\\tworkgroup = ' + WG + '\\n',\n"
            "                  text, count=1, flags=re.DOTALL)\n"
            # guest globals
            "if GUEST == 'yes':\n"
            "    for key, val in GUEST_GLOBALS:\n"
            "        pattern = r'^(\\s*' + re.escape(key) + r'\\s*=).*'\n"
            "        if re.search(pattern, text, re.MULTILINE):\n"
            "            text = re.sub(pattern, '\\\\g<1> ' + val, text, flags=re.MULTILINE)\n"
            "        else:\n"
            "            text = re.sub(r'(\\[global\\][^\\[]*?)(?=\\[|$)',\n"
            "                          lambda m, k=key, v=val: m.group(0) + '\\t' + k + ' = ' + v + '\\n',\n"
            "                          text, count=1, flags=re.DOTALL)\n"
            # remove old share, append new
            "text = re.sub(r'\\[' + re.escape(SHARE) + r'\\][^\\[]*', '', text, flags=re.DOTALL)\n"
            "text = text.rstrip() + '\\n\\n' + BLOCK + '\\n'\n"
            "open(CONF, 'w').write(text)\n"
            "print('smb.conf updated')\n"
        )

        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
        tf.write(script); tf.close()
        try:
            res = subprocess.run(['pkexec', 'python3', tf.name],
                                 capture_output=True, text=True, timeout=15)
            os.unlink(tf.name)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or 'pkexec error').strip()
                self._ft_log_append(f"ERROR writing smb.conf: {err}")
                QMessageBox.warning(self, "SMB Config", f"Failed to write smb.conf:\n{err}")
                return False
            self._ft_log_append(f"smb.conf updated — share=[{share}] path={path} workgroup={wg} "
                                 f"guest={guest} readonly={ro} force_user={force_user}")
            if guest == 'yes':
                self._ft_log_append("Guest access enabled — connect without credentials or leave username blank.")
            else:
                self._ft_log_append(f"User auth required — add users with:  sudo smbpasswd -a <username>")
            return True
        except Exception as e:
            self._ft_log_append(f"EXCEPTION writing smb.conf: {e}")
            QMessageBox.warning(self, "SMB Config", str(e))
            return False

    def _ft_smb_srv_toggle(self):
        import subprocess, time
        # Detect service name if not yet cached
        if not getattr(self, '_smb_srv_service', None):
            self._ft_smb_srv_check_status()
        svc = getattr(self, '_smb_srv_service', None)
        if not svc:
            self._ft_log_append("ERROR: No Samba service found (tried smb, smbd, samba).")
            QMessageBox.warning(self, "SMB Server",
                "Samba service not found.\nMake sure samba is installed:\n  pacman -S samba"); return
        try:
            r = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True, timeout=5)
            current = r.stdout.strip()
            self._ft_log_append(f"Service '{svc}' current state: {current}")
            if current == 'active':
                self._ft_log_append(f"Stopping {svc} via pkexec...")
                res = subprocess.run(['pkexec', 'systemctl', 'stop', svc],
                                     capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                    err = (res.stderr or res.stdout or "pkexec returned error").strip()
                    self._ft_log_append(f"ERROR stop {svc}: {err}")
                    QMessageBox.warning(self, "SMB Server", f"Failed to stop SMB service:\n{err}"); return
                self._ft_set_action_btn(False, 'SMB')
                self._ft_log_append(f"{svc} stopped.")
            else:
                # Apply config before starting
                if not self._ft_smb_apply_config():
                    return
                self._ft_log_append(f"Starting {svc} via pkexec...")
                res = subprocess.run(['pkexec', 'systemctl', 'start', svc],
                                     capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                    err = (res.stderr or res.stdout or "pkexec returned error").strip()
                    self._ft_log_append(f"ERROR start {svc}: {err}")
                    QMessageBox.warning(self, "SMB Server", f"Failed to start SMB service:\n{err}"); return
                self._ft_set_action_btn(True, 'SMB')
                self._ft_log_append(f"{svc} started.")
            time.sleep(1.0)
            self._ft_smb_srv_check_status()
        except Exception as e:
            self._ft_log_append(f"EXCEPTION: {e}")
            QMessageBox.warning(self, "SMB Server", str(e))

    def _ft_client_connect(self):
        host = self._ft_host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Warning", "Please enter a host address.")
            return
        try:
            port = int(self._ft_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Warning", "Invalid port number.")
            return
        user = self._ft_user_input.text().strip()
        pw = self._ft_pass_input.text()
        self.tftp_btn.setEnabled(False)
        self.tftp_btn.setText("Connecting...")
        self._ft_status_label.setText("Connecting...")
        self._ft_connect_worker = FileConnectWorker(self._ft_protocol, host, port, user, pw)
        self._ft_connect_worker.connected.connect(self._ft_on_connected)
        self._ft_connect_worker.error.connect(self._ft_on_connect_error)
        self._ft_connect_worker.start()

    def _ft_on_connected(self, conn_data):
        self._ft_conn = conn_data
        import datetime
        self._ft_connect_time = datetime.datetime.now()
        host = self._ft_host_input.text().strip()
        self._ft_status_label.setText(f"● Connected to {host}")
        self._ft_status_label.setStyleSheet("color: #4CAF50; font-size: 9pt; font-weight: bold;")
        self.tftp_btn.setEnabled(True)
        self.tftp_btn.setText("DISCONNECT")
        remote_home = '/'
        try:
            if self._ft_protocol == 'SSH' and 'sftp' in conn_data:
                remote_home = conn_data['sftp'].normalize('.')
            elif self._ft_protocol == 'FTP' and 'ftp' in conn_data:
                remote_home = conn_data['ftp'].pwd()
        except Exception:
            remote_home = '/'
        self._ft_remote_path = remote_home
        self._ft_remote_path_label.setText(remote_home)
        self._ft_remote_history = [remote_home]
        self._ft_remote_history_idx = 0
        self._ft_remote_back_btn.setEnabled(False)
        self._ft_remote_fwd_btn.setEnabled(False)
        self._ft_refresh_remote(remote_home)
        self._ft_refresh_local()
        self._ft_status_timer.start(1000)

    def _ft_on_connect_error(self, msg):
        self._ft_conn = None
        self._ft_status_label.setText(f"✗ Connection failed: {msg}")
        self._ft_status_label.setStyleSheet("color: #f44336; font-size: 9pt;")
        self.tftp_btn.setEnabled(True)
        self.tftp_btn.setText(f"CONNECT {self._ft_protocol}")

    def _ft_client_disconnect(self):
        self._ft_status_timer.stop()
        if self._ft_conn:
            try:
                if 'sftp' in self._ft_conn:
                    self._ft_conn['sftp'].close()
                if 'ssh' in self._ft_conn:
                    self._ft_conn['ssh'].close()
                if 'ftp' in self._ft_conn:
                    self._ft_conn['ftp'].quit()
            except Exception:
                pass
        self._ft_conn = None
        self._ft_connect_time = None
        self._ft_remote_tree.clear()
        self._ft_status_label.setText("Not connected")
        self._ft_status_label.setStyleSheet("color: #888888; font-size: 9pt;")
        self.tftp_btn.setText(f"CONNECT {self._ft_protocol}")

    def _ft_update_duration(self):
        if self._ft_conn and self._ft_connect_time:
            import datetime
            delta = datetime.datetime.now() - self._ft_connect_time
            total_secs = int(delta.total_seconds())
            h, rem = divmod(total_secs, 3600)
            m, s = divmod(rem, 60)
            host = self._ft_host_input.text().strip()
            dur = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            self._ft_status_label.setText(f"● Connected to {host} — {dur}")

    def _ft_refresh_local(self, path=None):
        if path is None:
            path = getattr(self, '_ft_local_path', os.path.expanduser('~'))
        if not os.path.isdir(path):
            return
        self._ft_local_path = path
        self._ft_local_path_label.setText(path)
        self._ft_local_tree.clear()
        _folder_svg = self.get_icon_path('folder_yellow.svg')
        _dir_icon  = load_svg_icon(_folder_svg, 16) or self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)
        _file_icon = self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon)
        _up_icon   = self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogToParent)
        try:
            from datetime import datetime
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
            if os.path.dirname(path) != path:
                item = QTreeWidgetItem(['..', '', ''])
                item.setIcon(0, _up_icon)
                item.setData(0, Qt.ItemDataRole.UserRole, os.path.dirname(path))
                item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
                self._ft_local_tree.addTopLevelItem(item)
            for e in entries:
                try:
                    stat = e.stat()
                    if e.is_dir():
                        size_str = '<DIR>'
                    else:
                        sz = stat.st_size
                        size_str = f"{sz/1024:.1f} KB" if sz >= 1024 else f"{sz} B"
                    date_str = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    item = QTreeWidgetItem([e.name, size_str, date_str])
                    item.setIcon(0, _dir_icon if e.is_dir() else _file_icon)
                    item.setData(0, Qt.ItemDataRole.UserRole, e.path)
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, e.is_dir())
                    self._ft_local_tree.addTopLevelItem(item)
                except OSError:
                    pass
        except OSError:
            pass

    def _ft_refresh_remote(self, path=None):
        if path is None:
            path = getattr(self, '_ft_remote_path', '/')
        if not self._ft_conn:
            return
        self._ft_remote_tree.clear()
        self._ft_remote_path_label.setText(path)
        self._ft_list_worker = FileListWorker(self._ft_protocol, self._ft_conn, path)
        self._ft_list_worker.result.connect(lambda entries: self._ft_on_remote_list(entries, path))
        self._ft_list_worker.error.connect(lambda e: self._ft_status_label.setText(f"List error: {e}"))
        self._ft_list_worker.start()

    def _ft_on_remote_list(self, entries, path):
        self._ft_remote_path = path
        self._ft_remote_path_label.setText(path)
        self._ft_remote_tree.clear()
        from datetime import datetime
        _folder_svg = self.get_icon_path('folder_yellow.svg')
        _dir_icon  = load_svg_icon(_folder_svg, 16) or self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)
        _file_icon = self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon)
        _up_icon   = self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogToParent)
        if path not in ('/', ''):
            item = QTreeWidgetItem(['..', '', ''])
            item.setIcon(0, _up_icon)
            parent_path = path.rstrip('/').rsplit('/', 1)[0] or '/'
            item.setData(0, Qt.ItemDataRole.UserRole, parent_path)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
            self._ft_remote_tree.addTopLevelItem(item)
        for name, size, is_dir, mtime in entries:
            size_str = '<DIR>' if is_dir else (f"{size/1024:.1f} KB" if size >= 1024 else f"{size} B")
            date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M') if mtime else ''
            item = QTreeWidgetItem([name, size_str, date_str])
            item.setIcon(0, _dir_icon if is_dir else _file_icon)
            remote_full = path.rstrip('/') + '/' + name
            item.setData(0, Qt.ItemDataRole.UserRole, remote_full)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)
            self._ft_remote_tree.addTopLevelItem(item)

    def _ft_local_double_clicked(self, item, col):
        is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if is_dir and path:
            self._ft_navigate_local(path)
        elif path and os.path.splitext(path)[1].lower() in _TEXT_EXTENSIONS:
            try:
                with open(path, 'r', errors='replace') as f:
                    content = f.read()
            except Exception as e:
                QMessageBox.warning(self, "Open Error", str(e))
                return

            def _save_local(text):
                with open(path, 'w') as f:
                    f.write(text)

            dlg = FileTextEditor(os.path.basename(path), content, self, _save_local)
            dlg.exec()

    def _ft_remote_double_clicked(self, item, col):
        is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if is_dir and path and self._ft_conn:
            self._ft_navigate_remote(path)
        elif path and self._ft_conn and os.path.splitext(path)[1].lower() in _TEXT_EXTENSIONS:
            try:
                import io
                buf = io.BytesIO()
                if 'sftp' in self._ft_conn:
                    self._ft_conn['sftp'].getfo(path, buf)
                elif 'ftp' in self._ft_conn:
                    self._ft_conn['ftp'].retrbinary(f'RETR {path}', buf.write)
                else:
                    return
                content = buf.getvalue().decode('utf-8', errors='replace')
            except Exception as e:
                QMessageBox.warning(self, "Open Error", str(e))
                return

            def _save_remote(text):
                import io
                data = text.encode('utf-8')
                if 'sftp' in self._ft_conn:
                    self._ft_conn['sftp'].putfo(io.BytesIO(data), path)
                elif 'ftp' in self._ft_conn:
                    self._ft_conn['ftp'].storbinary(f'STOR {path}', io.BytesIO(data))

            dlg = FileTextEditor(os.path.basename(path), content, self, _save_remote)
            dlg.exec()

    def _ft_upload(self):
        if not self._ft_conn:
            return
        items = self._ft_local_tree.selectedItems()
        if not items:
            return
        transfer_list = []
        for item in items:
            name = item.text(0)
            if name == '..':
                continue
            local_path = item.data(0, Qt.ItemDataRole.UserRole)
            is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
            remote_path = self._ft_remote_path.rstrip('/') + '/' + name
            if is_dir:
                if self._ft_protocol != 'SSH':
                    QMessageBox.information(self, "Info",
                        f"Directory upload only supported via SSH/SFTP.\nSkipping '{name}'.")
                    continue
                parent_dir = os.path.dirname(local_path)
                for root, _dirs, files in os.walk(local_path):
                    for f in files:
                        lf = os.path.join(root, f)
                        rel = os.path.relpath(lf, parent_dir)
                        rf = self._ft_remote_path.rstrip('/') + '/' + rel
                        transfer_list.append((lf, rf))
            else:
                transfer_list.append((local_path, remote_path))
        if not transfer_list:
            return
        self._ft_start_transfer('upload', transfer_list)

    def _ft_download(self):
        if not self._ft_conn:
            return
        items = self._ft_remote_tree.selectedItems()
        if not items:
            return
        transfer_list = []
        for item in items:
            name = item.text(0)
            if name == '..':
                continue
            remote_path = item.data(0, Qt.ItemDataRole.UserRole)
            is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
            local_path = os.path.join(self._ft_local_path, name)
            if is_dir:
                if self._ft_protocol != 'SSH':
                    QMessageBox.information(self, "Info",
                        f"Directory download only supported via SSH/SFTP.\nSkipping '{name}'.")
                    continue
                sftp = self._ft_conn.get('sftp')
                if not sftp:
                    continue
                try:
                    remote_files = self._sftp_walk_files(sftp, remote_path)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not list remote directory: {e}")
                    continue
                parent_dir = os.path.dirname(remote_path)
                for rf in remote_files:
                    rel = os.path.relpath(rf, parent_dir)
                    lf = os.path.join(self._ft_local_path, rel)
                    transfer_list.append((lf, rf))
            else:
                transfer_list.append((local_path, remote_path))
        if not transfer_list:
            return
        self._ft_start_transfer('download', transfer_list)

    def _sftp_walk_files(self, sftp, remote_dir):
        files = []
        for entry in sftp.listdir_attr(remote_dir):
            entry_path = remote_dir.rstrip('/') + '/' + entry.filename
            if stat.S_ISDIR(entry.st_mode):
                files.extend(self._sftp_walk_files(sftp, entry_path))
            else:
                files.append(entry_path)
        return files

    def _ft_start_transfer(self, direction, item_list):
        import time
        self.tftp_btn.setEnabled(False)
        count = len(item_list)
        verb = "Uploading" if direction == 'upload' else "Downloading"
        file_word = "file" if count == 1 else "files"
        self._ft_status_label.setText(f"{verb} {count} {file_word}...")
        self._ft_status_label.setStyleSheet("color: #555555; font-size: 9pt;")
        self._ft_progress_bar.setValue(0)
        self._ft_progress_bar.setVisible(True)
        self._ft_progress_info.setText("")
        self._ft_progress_info.setVisible(True)
        self._ft_transfer_start = time.time()
        self._ft_transfer_worker = FileTransferWorker(direction, self._ft_protocol, self._ft_conn, item_list)
        self._ft_transfer_worker.progress.connect(self._ft_on_transfer_progress)
        self._ft_transfer_worker.finished.connect(self._ft_on_transfer_done)
        self._ft_transfer_worker.start()

    def _ft_on_transfer_progress(self, percent, done, total):
        import time
        self._ft_progress_bar.setValue(percent)
        elapsed = time.time() - self._ft_transfer_start
        if done > 0 and elapsed > 0.1:
            speed = done / elapsed
            if speed >= 1024 * 1024:
                speed_str = f"{speed / 1024 / 1024:.1f} MB/s"
            elif speed >= 1024:
                speed_str = f"{speed / 1024:.1f} KB/s"
            else:
                speed_str = f"{speed:.0f} B/s"
            if total > 0 and speed > 0:
                remaining = (total - done) / speed
                if remaining >= 60:
                    eta_str = f"{int(remaining // 60)}m {int(remaining % 60)}s"
                else:
                    eta_str = f"{int(remaining)}s"
                self._ft_progress_info.setText(f"{percent}%  —  {speed_str}  —  ETA {eta_str}")
            else:
                self._ft_progress_info.setText(f"{percent}%  —  {speed_str}")
        else:
            self._ft_progress_info.setText(f"{percent}%")

    def _ft_on_transfer_done(self, success, msg):
        self.tftp_btn.setEnabled(True)
        self._ft_progress_bar.setVisible(False)
        self._ft_progress_info.setVisible(False)
        if success:
            self._ft_refresh_local()
            self._ft_refresh_remote()
            host = self._ft_host_input.text().strip()
            self._ft_status_label.setText(f"● Connected to {host} — {msg}")
            self._ft_status_label.setStyleSheet("color: #388e3c; font-size: 9pt;")
        else:
            lower = msg.lower()
            if 'permission' in lower or 'denied' in lower or '[errno 13]' in lower:
                self._ft_status_label.setText(f"⛔ Permission denied — cannot write to remote directory")
                QMessageBox.warning(self, "Permission Denied",
                    "You do not have permission to write to this directory on the remote system.\n\n"
                    f"Details: {msg}")
            else:
                self._ft_status_label.setText(f"✗ Transfer failed: {msg}")
            self._ft_status_label.setStyleSheet("color: #f44336; font-size: 9pt;")

    def _ft_remote_context_menu(self, pos):
        if not self._ft_conn:
            return
        item = self._ft_remote_tree.itemAt(pos)
        menu = QMenu(self)

        if item:
            is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
            path = item.data(0, Qt.ItemDataRole.UserRole)
            dl_act = menu.addAction("Download")
            rename_act = menu.addAction("Rename")
            delete_act = menu.addAction("Delete")
            menu.addSeparator()

        new_folder_act = menu.addAction("New Folder")

        action = menu.exec(self._ft_remote_tree.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == new_folder_act:
            name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
            name = name.strip()
            if not ok or not name:
                return
            new_path = self._ft_remote_path.rstrip('/') + '/' + name
            try:
                if 'sftp' in self._ft_conn:
                    self._ft_conn['sftp'].mkdir(new_path)
                elif 'ftp' in self._ft_conn:
                    self._ft_conn['ftp'].mkd(new_path)
                self._ft_refresh_remote()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create folder: {e}")
            return

        if not item:
            return

        if action == rename_act:
            old_name = os.path.basename(path)
            new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_name)
            new_name = new_name.strip()
            if not ok or not new_name or new_name == old_name:
                return
            new_path = os.path.dirname(path).rstrip('/') + '/' + new_name
            try:
                if 'sftp' in self._ft_conn:
                    self._ft_conn['sftp'].rename(path, new_path)
                elif 'ftp' in self._ft_conn:
                    self._ft_conn['ftp'].rename(path, new_path)
                self._ft_refresh_remote()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not rename: {e}")

        elif action == delete_act:
            name = os.path.basename(path)
            reply = QMessageBox.question(self, "Confirm Delete",
                f"Delete {'folder' if is_dir else 'file'} '{name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                if 'sftp' in self._ft_conn:
                    if is_dir:
                        self._ft_conn['sftp'].rmdir(path)
                    else:
                        self._ft_conn['sftp'].remove(path)
                elif 'ftp' in self._ft_conn:
                    if is_dir:
                        self._ft_conn['ftp'].rmd(path)
                    else:
                        self._ft_conn['ftp'].delete(path)
                self._ft_refresh_remote()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete: {e}")

        elif action == dl_act:
            self._ft_remote_tree.setCurrentItem(item)
            for si in self._ft_remote_tree.selectedItems():
                si.setSelected(False)
            item.setSelected(True)
            self._ft_download()

    def _ft_local_context_menu(self, pos):
        item = self._ft_local_tree.itemAt(pos)
        menu = QMenu(self)

        upload_act = rename_act = delete_act = None
        path = name = None
        is_dir = False

        if item:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            is_dir = item.data(0, Qt.ItemDataRole.UserRole + 1)
            name = os.path.basename(path) if path else ''
            if name and name != '..':
                if self._ft_conn:
                    upload_act = menu.addAction("Upload")
                rename_act = menu.addAction("Rename")
                delete_act = menu.addAction("Delete")
                menu.addSeparator()

        new_folder_act = menu.addAction("New Folder")

        action = menu.exec(self._ft_local_tree.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == new_folder_act:
            folder_name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
            folder_name = folder_name.strip()
            if not ok or not folder_name:
                return
            new_path = os.path.join(self._ft_local_path, folder_name)
            try:
                os.makedirs(new_path, exist_ok=False)
                self._ft_refresh_local()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not create folder: {e}")
            return

        if not item or not path or name == '..':
            return

        if upload_act and action == upload_act:
            self._ft_local_tree.setCurrentItem(item)
            for si in self._ft_local_tree.selectedItems():
                si.setSelected(False)
            item.setSelected(True)
            self._ft_upload()

        elif rename_act and action == rename_act:
            new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=name)
            new_name = new_name.strip()
            if not ok or not new_name or new_name == name:
                return
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
                self._ft_refresh_local()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not rename: {e}")

        elif delete_act and action == delete_act:
            reply = QMessageBox.question(self, "Confirm Delete",
                f"Delete {'folder' if is_dir else 'file'} '{name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                if is_dir:
                    import shutil
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self._ft_refresh_local()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete: {e}")

    # ── Local navigation helpers ──────────────────────────────────────

    def _ft_navigate_local(self, path):
        """Navigate local tree to path, updating history."""
        if not os.path.isdir(path):
            return
        # Truncate forward history
        self._ft_local_history = self._ft_local_history[:self._ft_local_history_idx + 1]
        if not self._ft_local_history or self._ft_local_history[-1] != path:
            self._ft_local_history.append(path)
            self._ft_local_history_idx = len(self._ft_local_history) - 1
        self._ft_refresh_local(path)
        self._ft_local_back_btn.setEnabled(self._ft_local_history_idx > 0)
        self._ft_local_fwd_btn.setEnabled(self._ft_local_history_idx < len(self._ft_local_history) - 1)

    def _ft_local_go_back(self):
        if self._ft_local_history_idx > 0:
            self._ft_local_history_idx -= 1
            self._ft_refresh_local(self._ft_local_history[self._ft_local_history_idx])
            self._ft_local_back_btn.setEnabled(self._ft_local_history_idx > 0)
            self._ft_local_fwd_btn.setEnabled(True)

    def _ft_local_go_forward(self):
        if self._ft_local_history_idx < len(self._ft_local_history) - 1:
            self._ft_local_history_idx += 1
            self._ft_refresh_local(self._ft_local_history[self._ft_local_history_idx])
            self._ft_local_fwd_btn.setEnabled(self._ft_local_history_idx < len(self._ft_local_history) - 1)
            self._ft_local_back_btn.setEnabled(True)

    # ── Remote navigation helpers ─────────────────────────────────────

    def _ft_navigate_remote(self, path):
        """Navigate remote tree to path, updating history."""
        self._ft_remote_history = self._ft_remote_history[:self._ft_remote_history_idx + 1]
        if not self._ft_remote_history or self._ft_remote_history[-1] != path:
            self._ft_remote_history.append(path)
            self._ft_remote_history_idx = len(self._ft_remote_history) - 1
        self._ft_refresh_remote(path)
        self._ft_remote_back_btn.setEnabled(self._ft_remote_history_idx > 0)
        self._ft_remote_fwd_btn.setEnabled(self._ft_remote_history_idx < len(self._ft_remote_history) - 1)

    def _ft_remote_go_back(self):
        if self._ft_remote_history_idx > 0:
            self._ft_remote_history_idx -= 1
            self._ft_refresh_remote(self._ft_remote_history[self._ft_remote_history_idx])
            self._ft_remote_back_btn.setEnabled(self._ft_remote_history_idx > 0)
            self._ft_remote_fwd_btn.setEnabled(True)

    def _ft_remote_go_forward(self):
        if self._ft_remote_history_idx < len(self._ft_remote_history) - 1:
            self._ft_remote_history_idx += 1
            self._ft_refresh_remote(self._ft_remote_history[self._ft_remote_history_idx])
            self._ft_remote_fwd_btn.setEnabled(self._ft_remote_history_idx < len(self._ft_remote_history) - 1)
            self._ft_remote_back_btn.setEnabled(True)

    def _ft_remote_go_home(self):
        """Go to remote home directory (~)."""
        if not self._ft_conn:
            return
        home = '/'
        try:
            if 'sftp' in self._ft_conn:
                home = self._ft_conn['sftp'].normalize('.')
        except Exception:
            pass
        self._ft_navigate_remote(home)

    def build_picocom_command(self):
        """Build the picocom command with configured parameters"""
        port = self.port.currentText()

        if 'No ports found' in port or not port:
            return None

        baudrate = self.baudrate.currentText()
        databits, parity_str, stopbits = self._parse_serial_config()

        # Parity
        parity_map = {'None': 'n', 'Even': 'e', 'Odd': 'o'}
        parity = parity_map[parity_str]

        # Flow control
        flow_type = self.flow.currentText()
        if 'Hardware' in flow_type:
            flow = 'h'
        elif 'Software' in flow_type:
            flow = 's'
        else:
            flow = 'n'

        # Picocom command
        cmd = [
            'picocom',
            '-b', baudrate,
            '-d', databits,
            '-p', parity,
            '-f', flow,
            port
        ]

        # Add stop bits if 2
        if stopbits == '2':
            cmd.insert(-1, '-y')
            cmd.insert(-1, '2')

        return cmd

    # === SSH/Telnet Helper Methods ===

    def _ssh_protocol_btn_clicked(self, protocol):
        """Handle protocol button click (SSH / Telnet / VNC / RDP)"""
        for btn in self.ssh_protocol_buttons.values():
            btn.setChecked(False)
        self.ssh_protocol_buttons[protocol].setChecked(True)
        self.ssh_current_protocol = protocol

        port_map = {'SSH': '22', 'Telnet': '23', 'VNC': '5900', 'RDP': '3389'}
        self.ssh_port.setText(port_map.get(protocol, '22'))
        self.ssh_connect_btn.setText(f"CONNECT {protocol}")
        _ico = load_svg_icon_dual(self._ra_proto_icons.get(protocol), 18, '#ffffff', '#ffffff')
        if _ico:
            self.ssh_connect_btn.setIcon(_ico)
            self.ssh_connect_btn.setIconSize(QSize(18, 18))
        else:
            self.ssh_connect_btn.setIcon(QIcon())

        # SSH Key fields only make sense for SSH
        is_ssh = (protocol == 'SSH')
        self.use_ssh_key.setVisible(is_ssh)
        if not is_ssh:
            self.use_ssh_key.setChecked(False)
            self.ssh_key_widget.setVisible(False)

        # RDP resolution row only shown for RDP
        is_rdp = (protocol == 'RDP')
        self.rdp_res_widget.setVisible(is_rdp)
        if self._rdp_res_lbl:
            self._rdp_res_lbl.setVisible(is_rdp)

    def _on_rdp_resolution_changed(self, text):
        """Show custom W×H fields only when 'Custom' is selected."""
        is_custom = (text == "Custom")
        self.rdp_custom_w.setVisible(is_custom)
        self._rdp_x_lbl.setVisible(is_custom)
        self.rdp_custom_h.setVisible(is_custom)

    def _get_rdp_resolution(self):
        """Return (width, height) or None for fullscreen."""
        sel = self.rdp_resolution.currentText()
        if sel == "Fullscreen":
            return None
        if sel == "Custom":
            try:
                return int(self.rdp_custom_w.text()), int(self.rdp_custom_h.text())
            except ValueError:
                return None
        try:
            w, h = sel.split('x')
            return int(w), int(h)
        except Exception:
            return None

    def toggle_protocol(self, button):
        """Toggle between SSH and Telnet protocol"""
        if button == self.protocol_ssh_btn or self.ssh_current_protocol == "SSH":
            # SSH selected
            self.ssh_port.setText("22")
            self.ssh_connect_btn.setText("CONNECT SSH")
        else:
            # Telnet selected
            self.ssh_port.setText("23")
            self.ssh_connect_btn.setText("CONNECT TELNET")

    def toggle_ssh_key(self, checked):
        """Toggle SSH key file widget and its label visibility"""
        self.ssh_key_widget.setVisible(checked)
        layout = self.ssh_rc_content.layout()
        if isinstance(layout, QFormLayout):
            lbl = layout.labelForField(self.ssh_key_widget)
            if lbl:
                lbl.setVisible(checked)

    def _launch_vnc(self, host, port, password):
        """Launch a VNC viewer.
        Priority: vncviewer → xtigervncviewer (both run transparently via XWayland).
        """
        import shutil, subprocess
        for viewer in ('vncviewer', 'xtigervncviewer'):
            if shutil.which(viewer):
                break
        else:
            QMessageBox.critical(self, "VNC Error",
                "No VNC viewer found.\n\n"
                "Install TigerVNC:\n  sudo apt install tigervnc-viewer")
            return
        subprocess.Popen([viewer, f'{host}::{port}'])

    def _launch_rdp(self, host, port, username, password):
        """Launch an RDP client with connecting feedback and error reporting.
        Search order: sdl-freerdp3 → xfreerdp3 / wlfreerdp3 → wlfreerdp → xfreerdp.
        """
        import shutil, subprocess
        for client in ('sdl-freerdp3', 'xfreerdp3', 'wlfreerdp3', 'wlfreerdp', 'xfreerdp'):
            if shutil.which(client):
                break
        else:
            QMessageBox.critical(self, "RDP Error",
                "No RDP client found.\n\n"
                "Arch Linux:\n"
                "  sudo pacman -S freerdp\n\n"
                "Debian / Ubuntu (Wayland-native):\n"
                "  sudo apt install freerdp3-wayland\n"
                "Debian / Ubuntu (X11):\n"
                "  sudo apt install freerdp2-x11")
            return

        tls_arg = '/tls:seclevel:0' if client.endswith('3') else '/tls-seclevel:0'
        resolution = self._get_rdp_resolution()
        depth = int(self.rdp_color_depth.currentText().split()[0])  # "32 bit" → 32
        if resolution:
            w, h = resolution
            args = [client, f'/v:{host}:{port}', '/cert:ignore', tls_arg,
                    f'/w:{w}', f'/h:{h}', f'/bpp:{depth}']
        else:
            args = [client, f'/v:{host}:{port}', '/cert:ignore', tls_arg,
                    '/f', f'/bpp:{depth}']
        if username:
            args.append(f'/u:{username}')
        if password:
            args.append(f'/p:{password}')

        proc = subprocess.Popen(args, stderr=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, text=True)

        # Visual feedback: disable button and show "Connecting…"
        btn = self.ssh_connect_btn
        original_text = btn.text()
        btn.setText("Connecting RDP…")
        btn.setEnabled(False)

        # Monitor stderr in a thread; report errors back on the main thread
        class _RdpMonitor(QThread):
            connected = pyqtSignal()
            failed    = pyqtSignal(str)
            done      = pyqtSignal()

            def __init__(self, process):
                super().__init__()
                self._proc = process

            def run(self):
                import time, threading
                stderr_lines = []
                connected = False

                # Read stderr in a daemon thread — piped stderr is block-buffered
                # and would only be readable after the process exits if read inline.
                def _drain():
                    for ln in self._proc.stderr:
                        stderr_lines.append(ln.rstrip())
                threading.Thread(target=_drain, daemon=True).start()

                start = time.time()
                while self._proc.poll() is None:
                    # Detect framebuffer ready in the lines collected so far
                    if not connected:
                        for ln in list(stderr_lines):
                            if 'gdi_init_ex' in ln and 'Local framebuffer' in ln:
                                connected = True
                                self.connected.emit()
                                break
                    # Fallback: if still running after 20 s, assume connected
                    if not connected and time.time() - start > 20:
                        connected = True
                        self.connected.emit()
                    time.sleep(0.4)

                # Process has ended — only report error if it never connected
                if not connected:
                    error_msg = ''
                    for ln in stderr_lines:
                        if '[ERROR]' in ln and '[handleShow]' in ln:
                            msg = ln.split('[handleShow]:')[-1].strip()
                            if msg:
                                error_msg = msg
                    if self._proc.returncode != 0:
                        self.failed.emit(error_msg or "RDP connection failed (unknown error).")
                self.done.emit()

        monitor = _RdpMonitor(proc)

        def _on_connected():
            btn.setText(original_text)
            btn.setEnabled(True)

        def _on_failed(msg):
            btn.setText(original_text)
            btn.setEnabled(True)
            QMessageBox.critical(self, "RDP Connection Error", msg)

        def _on_done():
            btn.setText(original_text)
            btn.setEnabled(True)

        monitor.connected.connect(_on_connected)
        monitor.failed.connect(_on_failed)
        monitor.done.connect(_on_done)
        monitor.start()
        # Keep reference so thread isn't GC'd
        self._rdp_monitor = monitor

    def _native_terminal_emulators(self):
        """Return ordered list of supported native terminal emulators."""
        return [
            'konsole',
            'gnome-terminal',
            'xfce4-terminal',
            'terminator',
            'alacritty',
            'kitty',
            'xterm',
        ]

    def _find_native_terminal(self):
        """Find the first available native terminal emulator in PATH."""
        for emulator in self._native_terminal_emulators():
            if shutil.which(emulator):
                return emulator
        return None

    def _build_native_terminal_command(self, emulator, command_list):
        """Build the argument list for launching a command in a native terminal."""
        if emulator == 'gnome-terminal':
            return [emulator, '--'] + list(command_list)
        if emulator in ('konsole', 'xfce4-terminal', 'terminator', 'alacritty', 'kitty', 'xterm'):
            return [emulator, '-e'] + list(command_list)
        # Unknown emulator: try the common -e flag as a reasonable default
        return [emulator, '-e'] + list(command_list)

    def _launch_native_terminal(self, command_list):
        """Launch command_list in the system's native terminal emulator.

        Returns True on success, False otherwise. Falls back to a warning
        message when no supported emulator is installed.
        """
        emulator = self._find_native_terminal()
        if not emulator:
            QMessageBox.warning(
                self, "Native Terminal Not Found",
                "No supported native terminal emulator was found on PATH.\n\n"
                "Supported: konsole, gnome-terminal, xfce4-terminal, "
                "terminator, alacritty, kitty, xterm.\n\n"
                "Falling back to the Cetus custom terminal."
            )
            return False

        args = self._build_native_terminal_command(emulator, command_list)
        # startDetached returns immediately and lets the terminal outlive Cetus.
        if not QProcess.startDetached(args[0], args[1:]):
            QMessageBox.warning(
                self, "Native Terminal Error",
                f"Could not start native terminal '{emulator}'.\n\n"
                "Falling back to the Cetus custom terminal."
            )
            return False
        return True

    def _should_use_native_terminal(self, vendor, terminal_mode):
        """Return True when the session should be opened in a native terminal."""
        if terminal_mode == 'native':
            return True
        if terminal_mode == 'custom':
            return False
        # auto: use native only for Linux vendor
        return vendor and vendor.lower() == 'linux'

    def browse_ssh_key(self):
        """Open file dialog to select SSH private key"""
        key_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH Private Key",
            os.path.expanduser("~/.ssh"),
            "All Files (*)"
        )
        if key_file:
            self.ssh_key_path.setText(key_file)

    VENDOR_LIST = ['Default', 'Linux', 'Windows', 'FreeBSD', 'Cisco', 'Huawei', 'H3C', 'Juniper', 'D-Link', 'Brocade', 'Datacom', 'Fortinet', 'Aruba', 'MikroTik', 'TP-Link']

    def _create_vendor_icon_widget(self, vendor, row, table='ssh'):
        """Create a clickable vendor icon widget for a profiles table"""
        btn = QPushButton()
        btn.setFlat(True)
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(vendor)
        icon_path = self.get_vendor_icon_path(vendor)
        pixmap = load_svg_pixmap(icon_path, 32)
        if pixmap and not pixmap.isNull():
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(28, 28))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #37474f;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: #546e7a;
            }
        """)
        btn.setProperty('vendor', vendor)
        btn.setProperty('row', row)
        btn.setProperty('table', table)
        btn.clicked.connect(lambda: self._show_vendor_menu(btn))
        # Center the button in the cell
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(btn)
        return container

    def _show_vendor_menu(self, btn):
        """Show popup menu to select vendor"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #5a5a5a;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #2196F3;
                color: white;
            }
        """)
        current_vendor = btn.property('vendor')
        for vendor in self.VENDOR_LIST:
            icon_path = self.get_vendor_icon_path(vendor)
            pixmap = load_svg_pixmap(icon_path, 20)
            action = menu.addAction(vendor)
            if pixmap and not pixmap.isNull():
                action.setIcon(QIcon(pixmap))
            if vendor == current_vendor:
                font = action.font()
                font.setBold(True)
                action.setFont(font)
        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if chosen:
            new_vendor = chosen.text()
            row = btn.property('row')
            table_type = btn.property('table')
            # Update icon and tooltip
            icon_path = self.get_vendor_icon_path(new_vendor)
            pixmap = load_svg_pixmap(icon_path, 24)
            if pixmap and not pixmap.isNull():
                btn.setIcon(QIcon(pixmap))
            btn.setToolTip(new_vendor)
            btn.setProperty('vendor', new_vendor)
            # Save to config
            if table_type == 'serial':
                tree_item = row  # row is a QTreeWidgetItem for the serial tree
                profile = tree_item.data(0, Qt.ItemDataRole.UserRole)
                if profile:
                    profile['vendor'] = new_vendor
                    self.config.save_serial_profile(
                        profile['name'], profile.get('port', ''),
                        profile.get('baudrate', '9600'), profile.get('databits', '8'),
                        profile.get('parity', 'None'), profile.get('stopbits', '1'),
                        profile.get('flow', 'None'), new_vendor,
                        profile.get('group', 'Default'),
                        profile.get('terminal_mode', 'auto')
                    )
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, profile)
            else:
                # row is a QTreeWidgetItem for the ssh tree
                tree_item = row
                profile = tree_item.data(0, Qt.ItemDataRole.UserRole)
                if profile:
                    profile['vendor'] = new_vendor
                    self.config.save_ssh_profile(
                        profile['name'], profile['host'], profile.get('port', '22'),
                        profile.get('username', ''), profile.get('auth_method', 'password'),
                        profile.get('key_path', ''), profile.get('protocol', 'SSH'),
                        new_vendor, profile.get('group', 'Default'),
                        profile.get('password', ''),
                        profile.get('terminal_mode', 'auto')
                    )
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, profile)

    def refresh_ssh_profiles(self):
        """Refresh the SSH profiles tree, grouped by profile group"""
        self.ssh_profiles_tree.clear()
        profiles = self.config.get_ssh_profiles()

        # Group profiles preserving insertion order
        groups = {}
        for profile in profiles:
            group = profile.get('group', 'Default') or 'Default'
            groups.setdefault(group, []).append(profile)

        group_header_bg = QColor('#546e7a')
        group_header_fg = QColor('#ffffff')

        for group_name, group_profiles in groups.items():
            # Group header item (non-selectable, spans visually)
            group_item = QTreeWidgetItem(self.ssh_profiles_tree)
            count = len(group_profiles)
            group_item.setText(0, f"  ▼   {group_name.upper()}  ({count})")
            group_item.setData(0, Qt.ItemDataRole.UserRole, None)
            group_item.setData(0, Qt.ItemDataRole.UserRole + 1, group_name)  # original name for drag-drop
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            font = group_item.font(0)
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            group_item.setFont(0, font)
            group_item.setSizeHint(0, QSize(0, 34))
            for col in range(5):
                group_item.setBackground(col, group_header_bg)
                group_item.setForeground(col, group_header_fg)
            # Span name column visually across all columns
            group_item_row = self.ssh_profiles_tree.indexOfTopLevelItem(group_item)
            self.ssh_profiles_tree.setFirstColumnSpanned(
                group_item_row, self.ssh_profiles_tree.rootIndex(), True)

            _key_icon_path = self.get_tab_icon_path('key.svg')
            _key_icon = QIcon(load_svg_pixmap(_key_icon_path, 14)) if _key_icon_path else None

            for profile in group_profiles:
                child = QTreeWidgetItem(group_item)
                child.setText(0, profile.get('name', ''))
                # Key icon left of name if password is saved
                if profile.get('password') and _key_icon:
                    child.setIcon(0, _key_icon)
                    child.setToolTip(0, "Password saved")
                child.setText(1, profile.get('host', ''))
                child.setText(2, profile.get('port', '22'))
                port = profile.get('port', '22')
                protocol = profile.get('protocol', 'SSH' if port == '22' else 'Telnet' if port == '23' else 'SSH')
                child.setText(3, protocol)
                child.setData(0, Qt.ItemDataRole.UserRole, profile)
                child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsDragEnabled)

                # Vendor icon widget (col 4)
                vendor = profile.get('vendor', 'Default')
                vendor_widget = self._create_vendor_icon_widget(vendor, child, table='ssh')
                self.ssh_profiles_tree.setItemWidget(child, 4, vendor_widget)

            group_item.setExpanded(True)



    def load_ssh_profile_from_tree(self, item, column):
        """Load selected SSH profile from tree and initiate connection"""
        if item is None:
            return
        profile = item.data(0, Qt.ItemDataRole.UserRole)
        if not profile:  # group header clicked
            return

        self._pending_profile_name = profile.get('name', '')
        self.ssh_host.setText(profile.get('host', ''))
        self.ssh_port.setText(profile.get('port', '22'))
        self.ssh_username.setText(profile.get('username', ''))

        if profile.get('auth_method') == 'key':
            self.use_ssh_key.setChecked(True)
            self.ssh_key_path.setText(profile.get('key_path', ''))
        else:
            self.use_ssh_key.setChecked(False)
            # Restore saved password if present
            import base64
            saved_pw = profile.get('password', '')
            self.ssh_save_password.blockSignals(True)
            if saved_pw:
                try:
                    self.ssh_password.setText(base64.b64decode(saved_pw.encode()).decode())
                    self.ssh_save_password.setChecked(True)
                except Exception:
                    self.ssh_password.clear()
                    self.ssh_save_password.setChecked(False)
            else:
                self.ssh_password.clear()
                self.ssh_save_password.setChecked(False)
            self.ssh_save_password.blockSignals(False)

        port = profile.get('port', '22')
        protocol = profile.get('protocol') or ('Telnet' if port == '23' else 'SSH')
        self._ssh_protocol_btn_clicked(protocol)

        self._pending_vendor = profile.get('vendor', 'Default')
        self._pending_terminal_mode = profile.get('terminal_mode', 'auto')

        QApplication.processEvents()
        QTimer.singleShot(100, self.connect_ssh)

    def _connect_all_in_group(self, group_item):
        """Connect to every device in a Quick Connect group sequentially."""
        import base64
        children = [group_item.child(i) for i in range(group_item.childCount())]
        if not children:
            return

        def _connect_one(idx):
            if idx >= len(children):
                return
            item = children[idx]
            profile = item.data(0, Qt.ItemDataRole.UserRole)
            if not profile:
                QTimer.singleShot(0, lambda: _connect_one(idx + 1))
                return

            self._pending_profile_name = profile.get('name', '')
            self.ssh_host.setText(profile.get('host', ''))
            self.ssh_port.setText(profile.get('port', '22'))
            self.ssh_username.setText(profile.get('username', ''))

            if profile.get('auth_method') == 'key':
                self.use_ssh_key.setChecked(True)
                self.ssh_key_path.setText(profile.get('key_path', ''))
                self.ssh_password.clear()
            else:
                self.use_ssh_key.setChecked(False)
                saved_pw = profile.get('password', '')
                if saved_pw:
                    try:
                        self.ssh_password.setText(base64.b64decode(saved_pw.encode()).decode())
                    except Exception:
                        self.ssh_password.clear()
                else:
                    self.ssh_password.clear()

            port = profile.get('port', '22')
            protocol = profile.get('protocol') or ('Telnet' if port == '23' else 'SSH')
            self._ssh_protocol_btn_clicked(protocol)

            self._pending_vendor = profile.get('vendor', 'Default')
            self._pending_terminal_mode = profile.get('terminal_mode', 'auto')

            QApplication.processEvents()
            self.connect_ssh()
            # Small delay between connections so the terminal window has time to open
            QTimer.singleShot(400, lambda: _connect_one(idx + 1))

        _connect_one(0)

    def _ssh_group_expanded(self, item):
        """Update group item arrow indicator when expanded"""
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            return
        text = item.text(0)
        item.setText(0, text.replace('▶', '▼', 1))

    def _ssh_group_collapsed(self, item):
        """Update group item arrow indicator when collapsed"""
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            return
        text = item.text(0)
        item.setText(0, text.replace('▼', '▶', 1))



    def _rename_ssh_group(self, group_item):
        """Rename a group and update all its profiles"""
        old_text = group_item.text(0)
        # Extract group name stripping leading arrow + spaces
        old_name = old_text.lstrip('▼▶ ').strip()

        dialog = QInputDialog(self)
        dialog.setWindowTitle("Rename Group")
        dialog.setLabelText("New group name:")
        dialog.setTextValue(old_name)
        if not dialog.exec():
            return
        new_name = dialog.textValue().strip()
        if not new_name or new_name == old_name:
            return

        # Update all child profiles
        for i in range(group_item.childCount()):
            child = group_item.child(i)
            profile = child.data(0, Qt.ItemDataRole.UserRole)
            if profile:
                profile['group'] = new_name
                self.config.save_ssh_profile(
                    profile['name'], profile['host'], profile.get('port', '22'),
                    profile.get('username', ''), profile.get('auth_method', 'password'),
                    profile.get('key_path', ''), profile.get('protocol', 'SSH'),
                    profile.get('vendor', 'Default'), new_name,
                    profile.get('password', ''),
                    profile.get('terminal_mode', 'auto')
                )

        # Update header text preserving arrow
        arrow = '▼' if group_item.isExpanded() else '▶'
        group_item.setText(0, f"  {arrow}   {new_name.upper()}")

    def _ssh_tree_save_order(self):
        """Walk the tree in current visual order and persist to config."""
        profiles = []
        root = self.ssh_profiles_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            group_name = (group_item.data(0, Qt.ItemDataRole.UserRole + 1)
                          or group_item.text(0).lstrip('▼▶ ').strip())
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                profile = child.data(0, Qt.ItemDataRole.UserRole)
                if profile:
                    profile = dict(profile)
                    profile['group'] = group_name
                    profiles.append(profile)
        self.config.set('ssh_profiles', json.dumps(profiles))
        self.refresh_ssh_profiles()

    def _toggle_ssh_remote_connection(self):
        """Collapse/expand the Remote Connection form with animation."""
        collapsing = self.ssh_rc_content.isVisible()

        if collapsing:
            start = self.ssh_rc_content.sizeHint().height()
            end = 0
            self.ssh_rc_group.setTitle("▸  Remote Connection")
        else:
            start = 0
            end = self.ssh_rc_content.sizeHint().height()
            self.ssh_rc_content.setMaximumHeight(0)
            self.ssh_rc_content.setVisible(True)
            self.ssh_rc_group.setTitle("▾  Remote Connection")

        anim = QPropertyAnimation(self.ssh_rc_content, b"maximumHeight", self)
        anim.setDuration(220)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        if collapsing:
            anim.finished.connect(lambda: self.ssh_rc_content.setVisible(False))
            anim.finished.connect(lambda: self.ssh_rc_content.setMaximumHeight(16777215))
            anim.finished.connect(lambda: self.config.set('ssh_rc_collapsed', True))
        else:
            anim.finished.connect(lambda: self.ssh_rc_content.setMaximumHeight(16777215))
            anim.finished.connect(lambda: self.config.set('ssh_rc_collapsed', False))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)




    def save_current_ssh_profile(self):
        """Save current SSH settings as a profile"""
        host = self.ssh_host.text().strip()
        if not host:
            QMessageBox.warning(self, "Warning", "Enter a host before saving")
            return

        # Collect existing groups
        existing_groups = []
        root = self.ssh_profiles_tree.invisibleRootItem()
        for i in range(root.childCount()):
            grp_item = root.child(i)
            grp_name = (grp_item.data(0, Qt.ItemDataRole.UserRole + 1)
                        or grp_item.text(0).lstrip('▼▶ ').strip())
            existing_groups.append(grp_name)
        if not existing_groups:
            existing_groups = ['Default']

        # Single dialog: name + group + vendor
        dlg = QDialog(self)
        dlg.setWindowTitle("Save Profile")
        dlg.setMinimumWidth(340)
        dlg.setStyleSheet("""
            QDialog       { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel        { color: #e0e0e0; }
            QLineEdit     { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444;
                            border-radius: 5px; padding: 4px 8px; }
            QComboBox     { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444;
                            border-radius: 5px; padding: 4px 8px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #2d2d2d; color: #e0e0e0;
                                          selection-background-color: #3a3a3a; border: 1px solid #555; }
            QDialogButtonBox QPushButton { background: #2d2d2d; color: #e0e0e0;
                                           border: 1px solid #555; border-radius: 5px;
                                           padding: 5px 16px; min-width: 70px; }
            QDialogButtonBox QPushButton:hover   { background: #3a3a3a; border-color: #888; }
            QDialogButtonBox QPushButton:pressed { background: #222; }
        """)
        form = QFormLayout(dlg)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. SW_CORE")
        # Pre-fill when editing an existing profile
        _editing_name  = getattr(self, '_editing_profile_name', '')
        _editing_group = getattr(self, '_editing_profile_group', '')
        if _editing_name:
            name_edit.setText(_editing_name)
        form.addRow("Profile name:", name_edit)

        _NEW_GROUP_ITEM = "＋ New Group…"
        group_combo = QComboBox()
        group_combo.setMinimumWidth(180)
        group_combo.addItems(existing_groups)
        group_combo.addItem(_NEW_GROUP_ITEM)
        if _editing_group and _editing_group in existing_groups:
            group_combo.setCurrentText(_editing_group)

        def _on_group_changed(idx):
            if group_combo.itemText(idx) != _NEW_GROUP_ITEM:
                return
            group_combo.blockSignals(True)
            try:
                name_input, ok = QInputDialog.getText(dlg, "New Group", "Group name:")
                name_input = name_input.strip()
                if ok and name_input:
                    insert_pos = group_combo.count() - 1
                    group_combo.insertItem(insert_pos, name_input)
                    group_combo.setCurrentIndex(insert_pos)
                else:
                    group_combo.setCurrentIndex(0)
            finally:
                group_combo.blockSignals(False)

        group_combo.currentIndexChanged.connect(_on_group_changed)
        form.addRow("Group:", group_combo)

        vendor_combo = QComboBox()
        vendor_combo.setMinimumWidth(180)
        vendor_combo.addItems(self.VENDOR_LIST)
        # Pre-select vendor currently active in the terminal (if any)
        current_vendor = getattr(self, '_pending_vendor', None) or 'Default'
        idx = vendor_combo.findText(current_vendor)
        if idx >= 0:
            vendor_combo.setCurrentIndex(idx)
        form.addRow("Vendor:", vendor_combo)

        terminal_mode_combo = QComboBox()
        terminal_mode_combo.setMinimumWidth(180)
        terminal_mode_combo.addItems(['Auto', 'Native', 'Custom'])
        # Pre-select terminal mode from the profile being edited, if any
        _terminal_mode = 'Auto'
        if _editing_name:
            for _p in self.config.get_ssh_profiles():
                if _p.get('name') == _editing_name:
                    _mode = _p.get('terminal_mode', 'auto').capitalize()
                    if terminal_mode_combo.findText(_mode) >= 0:
                        _terminal_mode = _mode
                    break
        terminal_mode_combo.setCurrentText(_terminal_mode)
        form.addRow("Terminal mode:", terminal_mode_combo)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Warning", "Profile name cannot be empty")
            return
        group  = group_combo.currentText().strip()
        if not group or group == _NEW_GROUP_ITEM:
            group = 'Default'
        vendor = vendor_combo.currentText()
        terminal_mode = terminal_mode_combo.currentText().lower()

        auth_method = 'key' if self.use_ssh_key.isChecked() else 'password'
        protocol = self.ssh_current_protocol
        saved_pw = self.ssh_password.text() if self.ssh_save_password.isChecked() else ''
        self.config.save_ssh_profile(
            name, host, self.ssh_port.text(),
            self.ssh_username.text(), auth_method,
            self.ssh_key_path.text() if auth_method == 'key' else '',
            protocol, group=group, password=saved_pw, vendor=vendor,
            terminal_mode=terminal_mode
        )
        self._editing_profile_name  = ''
        self._editing_profile_group = ''
        self.refresh_ssh_profiles()
        QMessageBox.information(self, "Saved", f"Profile '{name}' saved in group '{group}'")

    def delete_ssh_profile(self):
        """Delete selected SSH profile from tree"""
        item = self.ssh_profiles_tree.currentItem()
        if item is None:
            QMessageBox.warning(self, "Warning", "Select a profile to delete")
            return
        profile = item.data(0, Qt.ItemDataRole.UserRole)
        if not profile:
            QMessageBox.warning(self, "Warning", "Select a profile to delete")
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{profile['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.delete_ssh_profile(profile['name'])
            self.refresh_ssh_profiles()

    def _parse_serial_config(self):
        """Parse serial_config combo text into (databits, parity, stopbits) strings."""
        frame = self.serial_config.currentText().strip() or '8N1'
        databits = frame[0] if len(frame) >= 1 else '8'
        parity_char = frame[1].upper() if len(frame) >= 2 else 'N'
        stopbits = frame[2] if len(frame) >= 3 else '1'
        parity_map = {'N': 'None', 'E': 'Even', 'O': 'Odd'}
        parity = parity_map.get(parity_char, 'None')
        return databits, parity, stopbits

    def _build_serial_config_text(self, databits, parity, stopbits):
        """Build serial_config combo text from individual values."""
        parity_char_map = {'None': 'N', 'Even': 'E', 'Odd': 'O'}
        parity_char = parity_char_map.get(parity, 'N')
        return f"{databits}{parity_char}{stopbits}"

    def refresh_serial_profiles(self):
        """Refresh the serial profiles tree, grouped by profile group."""
        self.serial_profiles_tree.clear()
        profiles = self.config.get_serial_profiles()

        groups = {}
        for profile in profiles:
            group = profile.get('group', 'Default') or 'Default'
            groups.setdefault(group, []).append(profile)

        group_header_bg = QColor('#37474f')
        group_header_fg = QColor('#ffffff')

        for group_name, group_profiles in groups.items():
            group_item = QTreeWidgetItem(self.serial_profiles_tree)
            group_item.setText(0, f"  ▼   {group_name.upper()}")
            group_item.setData(0, Qt.ItemDataRole.UserRole, None)
            group_item.setData(0, Qt.ItemDataRole.UserRole + 1, group_name)
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            font = group_item.font(0)
            font.setBold(True)
            font.setPointSize(font.pointSize() + 1)
            group_item.setFont(0, font)
            group_item.setSizeHint(0, QSize(0, 34))
            for col in range(5):
                group_item.setBackground(col, group_header_bg)
                group_item.setForeground(col, group_header_fg)
            group_item_row = self.serial_profiles_tree.indexOfTopLevelItem(group_item)
            self.serial_profiles_tree.setFirstColumnSpanned(
                group_item_row, self.serial_profiles_tree.rootIndex(), True)

            for profile in group_profiles:
                child = QTreeWidgetItem(group_item)
                child.setText(0, profile.get('name', ''))
                child.setText(1, profile.get('port', ''))
                child.setText(2, profile.get('baudrate', '9600'))
                databits = profile.get('databits', '8')
                parity   = profile.get('parity', 'None')[0]
                stopbits = profile.get('stopbits', '1')
                child.setText(3, f"{databits}{parity}{stopbits}")
                child.setData(0, Qt.ItemDataRole.UserRole, profile)
                child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsDragEnabled)
                vendor = profile.get('vendor', 'Default')
                vendor_widget = self._create_vendor_icon_widget(vendor, child, table='serial')
                self.serial_profiles_tree.setItemWidget(child, 4, vendor_widget)

            group_item.setExpanded(True)

    def load_serial_profile_from_tree(self, item, column):
        """Load selected serial profile from tree and initiate connection."""
        if item is None:
            return
        profile = item.data(0, Qt.ItemDataRole.UserRole)
        if not profile:  # group header clicked
            return
        idx = self.port.findText(profile.get('port', ''))
        if idx >= 0:
            self.port.setCurrentIndex(idx)
        self.baudrate.setCurrentText(profile.get('baudrate', '9600'))
        config_text = self._build_serial_config_text(
            profile.get('databits', '8'),
            profile.get('parity', 'None'),
            profile.get('stopbits', '1'),
        )
        idx = self.serial_config.findText(config_text)
        if idx >= 0:
            self.serial_config.setCurrentIndex(idx)
        self.flow.setCurrentText(profile.get('flow', 'None'))
        vendor_widget = self.serial_profiles_tree.itemWidget(item, 4)
        if vendor_widget:
            btn = vendor_widget.findChild(QPushButton)
            self._pending_vendor = btn.property('vendor') if btn else 'Default'
        else:
            self._pending_vendor = 'Default'
        self._pending_terminal_mode = profile.get('terminal_mode', 'auto')
        QApplication.processEvents()
        QTimer.singleShot(100, self.connect)

    def save_current_serial_profile(self):
        """Save current serial settings as a profile."""
        port = self.port.currentText()
        if not port or 'No ports found' in port:
            QMessageBox.warning(self, "Warning", "Select a valid port before saving")
            return

        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if not ok or not name.strip():
            return
        name = name.strip()

        # Collect existing groups for autocomplete
        existing_groups = []
        root = self.serial_profiles_tree.invisibleRootItem()
        for i in range(root.childCount()):
            grp_item = root.child(i)
            grp_name = (grp_item.data(0, Qt.ItemDataRole.UserRole + 1)
                        or grp_item.text(0).lstrip('▼▶ ').strip())
            existing_groups.append(grp_name)
        if not existing_groups:
            existing_groups = ['Default']

        group, ok = QInputDialog.getItem(
            self, "Profile Group", "Group:", existing_groups, 0, True)
        if not ok:
            return
        group = group.strip() or 'Default'

        terminal_mode, ok = QInputDialog.getItem(
            self, "Terminal Mode", "Terminal mode:", ["Auto", "Native", "Custom"], 0, False)
        if not ok:
            return
        terminal_mode = terminal_mode.lower()

        db, par, sb = self._parse_serial_config()
        self.config.save_serial_profile(
            name, port, self.baudrate.currentText(),
            db, par, sb, self.flow.currentText(), group=group,
            terminal_mode=terminal_mode
        )
        self.refresh_serial_profiles()
        QMessageBox.information(self, "Saved", f"Profile '{name}' saved in group '{group}'")

    def delete_serial_profile(self):
        """Delete selected serial profile from tree."""
        item = self.serial_profiles_tree.currentItem()
        if item is None or item.data(0, Qt.ItemDataRole.UserRole) is None:
            QMessageBox.warning(self, "Warning", "Select a profile to delete")
            return
        profile = item.data(0, Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{profile['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.delete_serial_profile(profile['name'])
            self.refresh_serial_profiles()

    def _serial_group_expanded(self, item):
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            return
        item.setText(0, item.text(0).replace('▶', '▼', 1))

    def _serial_group_collapsed(self, item):
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            return
        item.setText(0, item.text(0).replace('▼', '▶', 1))

    def _rename_serial_group(self, group_item):
        """Rename a serial group and update all its profiles."""
        old_name = group_item.text(0).lstrip('▼▶ ').strip()
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Rename Group")
        dialog.setLabelText("New group name:")
        dialog.setTextValue(old_name)
        if not dialog.exec():
            return
        new_name = dialog.textValue().strip()
        if not new_name or new_name == old_name:
            return
        for i in range(group_item.childCount()):
            child = group_item.child(i)
            profile = child.data(0, Qt.ItemDataRole.UserRole)
            if profile:
                profile['group'] = new_name
                self.config.save_serial_profile(
                    profile['name'], profile.get('port', ''),
                    profile.get('baudrate', '9600'), profile.get('databits', '8'),
                    profile.get('parity', 'None'), profile.get('stopbits', '1'),
                    profile.get('flow', 'None'), profile.get('vendor', 'Default'), new_name,
                    profile.get('terminal_mode', 'auto')
                )
        arrow = '▼' if group_item.isExpanded() else '▶'
        group_item.setText(0, f"  {arrow}   {new_name.upper()}")
        group_item.setData(0, Qt.ItemDataRole.UserRole + 1, new_name)

    def _serial_tree_save_order(self):
        """Persist current tree order to config."""
        profiles = []
        root = self.serial_profiles_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            group_name = (group_item.data(0, Qt.ItemDataRole.UserRole + 1)
                          or group_item.text(0).lstrip('▼▶ ').strip())
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                profile = child.data(0, Qt.ItemDataRole.UserRole)
                if profile:
                    profile = dict(profile)
                    profile['group'] = group_name
                    profiles.append(profile)
        self.config.set('serial_profiles', json.dumps(profiles))
        self.refresh_serial_profiles()

    def _serial_profile_context_menu(self, pos):
        """Context menu for Serial Quick Connect tree."""
        item = self.serial_profiles_tree.itemAt(pos)
        if not item:
            return
        profile = item.data(0, Qt.ItemDataRole.UserRole)
        _menu_style = """
            QMenu { background-color: #ffffff; color: #333333;
                border: 1px solid #d0d0d0; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 3px; }
            QMenu::item:selected { background-color: #e8e8e8; }
            QMenu::separator { height: 1px; background-color: #d0d0d0; margin: 4px 8px; }
        """
        if not profile:
            menu = QMenu(self)
            menu.setStyleSheet(_menu_style)
            rename_action = menu.addAction("Rename Group")
            action = menu.exec(self.serial_profiles_tree.viewport().mapToGlobal(pos))
            if action == rename_action:
                self._rename_serial_group(item)
            return

        menu = QMenu(self)
        menu.setStyleSheet(_menu_style)
        copy_port_action = menu.addAction("Copy Port Name")
        copy_baud_action = menu.addAction("Copy Baud Rate")
        menu.addSeparator()
        action = menu.exec(self.serial_profiles_tree.viewport().mapToGlobal(pos))
        if action == copy_port_action:
            QApplication.clipboard().setText(profile.get('port', ''))
        elif action == copy_baud_action:
            QApplication.clipboard().setText(profile.get('baudrate', ''))

    def connect_ssh(self):
        """Connect via SSH, Telnet, VNC or RDP"""
        host = self.ssh_host.text().strip()
        port = self.ssh_port.text().strip()
        username = self.ssh_username.text().strip()
        password = self.ssh_password.text()

        if not host:
            QMessageBox.warning(self, "Warning", "Enter host address")
            return

        # VNC / RDP: launch external viewer and return immediately
        if self.ssh_current_protocol == "VNC":
            self._launch_vnc(host, port or "5900", password)
            return
        if self.ssh_current_protocol == "RDP":
            self._launch_rdp(host, port or "3389", username, password)
            return

        port = port or "22"

        # Username is required for SSH, optional for Telnet
        if self.ssh_current_protocol == "SSH" and not username:
            QMessageBox.warning(self, "Warning", "Enter username for SSH connection")
            return

        # Get authentication credentials
        key_path = None

        if self.use_ssh_key.isChecked():
            # SSH Key authentication
            key_path = self.ssh_key_path.text().strip()
            if not key_path:
                QMessageBox.warning(self, "Warning", "Select SSH key file")
                return
            key_path = os.path.expanduser(key_path)
            password = None

        # Native terminal path for Linux / explicit preference
        _vendor = getattr(self, '_pending_vendor', None)
        _terminal_mode = getattr(self, '_pending_terminal_mode', None) or 'auto'
        if self._should_use_native_terminal(_vendor, _terminal_mode):
            if self.ssh_current_protocol == "Telnet":
                cmd = ['telnet', host]
                if port != '23':
                    cmd.append(port)
            else:  # SSH
                ssh_cmd = ['ssh', '-p', str(port)]
                if key_path:
                    ssh_cmd.extend(['-i', key_path])
                ssh_cmd.append(f'{username}@{host}')
                cmd = ssh_cmd

            self._update_ssh_connect_btn()
            if self._launch_native_terminal(cmd):
                self._pending_profile_name = None
                self._pending_vendor = None
                self._pending_terminal_mode = None
                return
            # On failure, fall back to the custom terminal below

        # SSH connection requires paramiko for the custom terminal
        if self.ssh_current_protocol == "SSH" and not SSH_AVAILABLE:
            QMessageBox.critical(
                self, "Error",
                "paramiko library is not installed.\n\n"
                "Install with: pip install paramiko"
            )
            return

        # Password authentication for custom terminal
        if not self.use_ssh_key.isChecked() and not password:
            # Prompt for password with option to save it
            _pw_dlg = QDialog(self)
            _pw_dlg.setWindowTitle("SSH Password")
            _pw_dlg.setMinimumWidth(320)
            _pw_dlg.setStyleSheet("""
                QDialog   { background-color: #1e1e1e; color: #e0e0e0; }
                QLabel    { color: #e0e0e0; }
                QLineEdit { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444;
                            border-radius: 5px; padding: 4px 8px; }
                QDialogButtonBox QPushButton {
                    background: #2d2d2d; color: #e0e0e0;
                    border: 1px solid #555; border-radius: 5px;
                    padding: 5px 16px; min-width: 70px; }
                QDialogButtonBox QPushButton:hover   { background: #3a3a3a; }
                QDialogButtonBox QPushButton:pressed { background: #222; }
            """)
            _pw_layout = QVBoxLayout(_pw_dlg)
            _pw_layout.setContentsMargins(16, 16, 16, 12)
            _pw_layout.setSpacing(10)
            _pw_layout.addWidget(QLabel(f"Password for {username}@{host}:"))
            _pw_input = QLineEdit()
            _pw_input.setEchoMode(QLineEdit.EchoMode.Password)
            _pw_layout.addWidget(_pw_input)
            _save_cb = QCheckBox("Save password")
            _save_cb.setStyleSheet(
                "QCheckBox { background: transparent; color: #e0e0e0; }"
                "QCheckBox::indicator { background: #2d2d2d; border: 1px solid #666; border-radius: 3px; }"
                "QCheckBox::indicator:checked { background: #4CAF50; border-color: #4CAF50; }"
            )
            _pw_layout.addWidget(_save_cb)
            _btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            _btns.accepted.connect(_pw_dlg.accept)
            _btns.rejected.connect(_pw_dlg.reject)
            _pw_layout.addWidget(_btns)

            if _pw_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = _pw_input.text()
            if not password:
                return

            # Save password and username to profile if requested
            if _save_cb.isChecked() and self._pending_profile_name:
                import base64
                profiles = self.config.get_ssh_profiles()
                for p in profiles:
                    if p.get('name') == self._pending_profile_name:
                        p['password'] = base64.b64encode(password.encode()).decode()
                        p['username'] = username
                        break
                import json
                self.config.set('ssh_profiles', json.dumps(profiles))
                self.ssh_password.setText(password)
                self.ssh_save_password.blockSignals(True)
                self.ssh_save_password.setChecked(True)
                self.ssh_save_password.blockSignals(False)
                self.refresh_ssh_profiles()

        # Show connecting state in the button itself
        self.ssh_connect_btn.setText("Connecting...")
        self.ssh_connect_btn.setEnabled(False)
        self.ssh_connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
        """)
        QApplication.processEvents()

        # Determine connection type
        connection_type = 'telnet' if self.ssh_current_protocol == "Telnet" else 'ssh'

        # Create and start connection worker thread
        # Capture profile name and vendor NOW (before async callbacks fire),
        # so concurrent connections don't overwrite each other's values.
        _profile_name = self._pending_profile_name
        _vendor       = getattr(self, '_pending_vendor', None)
        self._pending_profile_name = None
        self._pending_vendor       = None
        self._pending_terminal_mode = None

        worker = ConnectionWorker(
            connection_type,
            host, port, username, password, key_path
        )
        worker.connection_ready.connect(
            lambda ct, cl, ch, hi, pn=_profile_name, v=_vendor:
                self.on_connection_ready(ct, cl, ch, hi, pn, v)
        )
        worker.connection_failed.connect(self.on_connection_failed)

        # Keep a reference so the worker isn't GC'd while the thread runs
        if not hasattr(self, '_active_workers'):
            self._active_workers = []
        self._active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._active_workers.remove(w) if w in self._active_workers else None)
        worker.start()
    
    def on_connection_ready(self, conn_type, client, channel, host_info,
                            profile_name=None, vendor=None):
        """Handle successful connection from worker thread - create terminal tab in UI thread."""
        terminal_dialog = TerminalDialog(None, self.config)

        # ── Assign banner colour (cycles through BANNER_COLORS) ──────────────
        color = TerminalDialog.BANNER_COLORS[
            TerminalDialog._banner_index % len(TerminalDialog.BANNER_COLORS)
        ]
        TerminalDialog._banner_index += 1
        terminal_dialog.banner_color = color

        # ── Inject the established connection ────────────────────────────────
        if conn_type == 'telnet':
            terminal_dialog.telnet_client = client
            terminal_dialog.telnet_running = True
            terminal_dialog.connection_type = 'telnet'
            tab_label = profile_name or f"Telnet: {host_info[0]}"
            terminal_dialog.setWindowTitle(f"Cetus Terminal - {tab_label}")
            terminal_dialog.set_connection_status(host=host_info[0], color=color, name=tab_label)
        else:  # SSH
            terminal_dialog.ssh_client = client
            terminal_dialog.ssh_channel = channel
            terminal_dialog.ssh_running = True
            terminal_dialog.connection_type = 'ssh'
            tab_label = profile_name or f"SSH: {host_info[2]}@{host_info[0]}"
            terminal_dialog.setWindowTitle(f"Cetus Terminal - {tab_label}")
            terminal_dialog.set_connection_status(
                user=host_info[2], host=host_info[0], color=color, name=tab_label
            )

        # ── Profile banner (coloured label inside the terminal widget) ───────
        if profile_name:
            terminal_dialog.set_profile_name(profile_name)

        # ── Vendor syntax highlighting ────────────────────────────────────────
        if vendor:
            terminal_dialog.change_vendor(vendor)

        # ── Track and wire up close signal ───────────────────────────────────
        self.open_terminals.append(terminal_dialog)
        terminal_dialog.terminal_closed.connect(
            lambda: self._on_terminal_closed(terminal_dialog)
        )

        # ── Add to tabbed manager window ──────────────────────────────────────
        if self._terminal_manager is None or not self._terminal_manager.isVisible():
            self._terminal_manager = TerminalTabbedWindow()
        self._terminal_manager.add_terminal(terminal_dialog, tab_label, color)
        self._terminal_manager.show()
        self._terminal_manager.raise_()
        self._terminal_manager.activateWindow()

        # ── Start the shell after Qt has fully computed the layout ────────────
        # A brief timer gives the layout engine one full event-loop cycle to
        # settle the viewport size. Then we resize pyte + the remote PTY and
        # invoke_shell(), so the MOTD arrives already at the correct dimensions.
        if conn_type == 'telnet':
            terminal_dialog.telnet_read_thread = threading.Thread(
                target=terminal_dialog._telnet_read_loop, daemon=True
            )
            terminal_dialog.telnet_read_thread.start()
        else:
            vendor = terminal_dialog.terminal.vendor

            def _launch_ssh_session():
                terminal_dialog.terminal._recalculate_size()
                cols = terminal_dialog.terminal.screen.columns
                rows = terminal_dialog.terminal.screen.lines
                try:
                    channel.resize_pty(width=cols, height=rows)
                except Exception:
                    pass
                channel.invoke_shell()
                terminal_dialog.ssh_read_thread = threading.Thread(
                    target=terminal_dialog._ssh_read_loop, daemon=True
                )
                terminal_dialog.ssh_read_thread.start()

                # Re-assert TERM only for Default vendor (others don't need it).
                if vendor == 'Default':
                    def _inject_term_env():
                        try:
                            if terminal_dialog.ssh_channel and terminal_dialog.ssh_running:
                                terminal_dialog.ssh_channel.send(
                                    b'export TERM=xterm COLORTERM=truecolor;'
                                    b' printf \'\\033[1A\\033[2K\'\r'
                                )
                        except Exception:
                            pass
                    QTimer.singleShot(1200, _inject_term_env)

            QTimer.singleShot(80, _launch_ssh_session)

        self._update_ssh_connect_btn()

    def _on_terminal_closed(self, dialog):
        """Called when a terminal window is destroyed; keeps open_terminals clean."""
        try:
            self.open_terminals.remove(dialog)
        except ValueError:
            pass
        self._update_ssh_connect_btn()

    def _update_ssh_connect_btn(self):
        """Restore the SSH connect button showing current session count."""
        proto = getattr(self, 'ssh_current_protocol', 'SSH')
        base = "CONNECT SSH" if proto != "Telnet" else "CONNECT TELNET"
        n = len(self.open_terminals)
        label = f"{base}  (Sessions: {n})" if n else base
        self.ssh_connect_btn.setText(label)
        self.ssh_connect_btn.setEnabled(True)
        self.ssh_connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
            QPushButton:pressed {
                background-color: #388e3c;
            }
        """)

    def on_connection_failed(self, error_message):
        """Handle connection failure from worker thread"""
        self._update_ssh_connect_btn()
        if error_message:
            QMessageBox.critical(self, "Connection Error", error_message)

    def connect(self):
        """Connect to the serial port using embedded terminal"""
        # Check if debug mode is enabled
        if self.debug_checkbox.isChecked():
            self.status_label.setText("Opening debug terminal...")
            self.status_label.setStyleSheet("color: #fab387; font-size: 10pt;")
            self.status_led.setStyleSheet("color: #fab387; font-size: 14px;")
            QApplication.processEvents()

            # Create terminal dialog in debug mode (own window via manager)
            terminal_dialog = TerminalDialog(None, self.config)
            terminal_dialog.start_debug_mode()

            color = TerminalDialog.BANNER_COLORS[
                TerminalDialog._banner_index % len(TerminalDialog.BANNER_COLORS)
            ]
            TerminalDialog._banner_index += 1
            terminal_dialog.banner_color = color
            terminal_dialog.setWindowTitle("Cetus Terminal - Debug Mode")
            terminal_dialog.set_connection_status(host='Debug', color=color, name='Debug Mode')

            self.open_terminals.append(terminal_dialog)
            terminal_dialog.terminal_closed.connect(
                lambda: self._on_terminal_closed(terminal_dialog)
            )

            if self._terminal_manager is None or not self._terminal_manager.isVisible():
                self._terminal_manager = TerminalTabbedWindow()
            self._terminal_manager.add_terminal(terminal_dialog, "Debug Mode", color)
            self._terminal_manager.show()
            self._terminal_manager.raise_()
            self._terminal_manager.activateWindow()

            self.status_label.setText("Debug Mode - Terminal opened")
            self.status_label.setStyleSheet("color: #a6e3a1; font-size: 10pt;")
            self.status_led.setStyleSheet("color: #a6e3a1; font-size: 14px;")

            # Status remains in debug mode (don't reset immediately)
            # Will reset when terminal is closed
            return

        # Check if picocom is installed (Linux only)
        if sys.platform != 'win32':
            try:
                subprocess.run(['which', 'picocom'], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                QMessageBox.critical(
                    self,
                    "Error",
                    "picocom is not installed.\n\n"
                    "Install with:\nsudo pacman -S picocom"
                )
                return

        # Build command
        cmd = self.build_picocom_command()

        if not cmd:
            QMessageBox.warning(
                self,
                "Warning",
                "Select a valid serial port"
            )
            return

        # Native terminal path for Linux / explicit preference
        _vendor = getattr(self, '_pending_vendor', None)
        _terminal_mode = getattr(self, '_pending_terminal_mode', None) or 'auto'
        if self._should_use_native_terminal(_vendor, _terminal_mode):
            if self._launch_native_terminal(cmd):
                self._pending_vendor = None
                self._pending_terminal_mode = None
                self.status_label.setText("Connected - Terminal opened")
                self.status_label.setStyleSheet("color: #a6e3a1; font-size: 10pt;")
                self.status_led.setStyleSheet("color: #a6e3a1; font-size: 14px;")
                return
            # On failure, fall back to the custom terminal below

        self.status_label.setText("Opening terminal...")
        self.status_label.setStyleSheet("color: #fab387; font-size: 10pt;")
        self.status_led.setStyleSheet("color: #fab387; font-size: 14px;")
        QApplication.processEvents()

        # Create terminal dialog (no parent so it opens in its own window via
        # TerminalTabbedWindow, matching SSH/Telnet behaviour).
        terminal_dialog = TerminalDialog(None, self.config)

        # Assign banner colour (cycles through BANNER_COLORS)
        color = TerminalDialog.BANNER_COLORS[
            TerminalDialog._banner_index % len(TerminalDialog.BANNER_COLORS)
        ]
        TerminalDialog._banner_index += 1
        terminal_dialog.banner_color = color

        # Start picocom
        if terminal_dialog.start_picocom(cmd):
            # Apply vendor syntax highlighting from profile
            if hasattr(self, '_pending_vendor') and self._pending_vendor:
                terminal_dialog.change_vendor(self._pending_vendor)
                self._pending_vendor = None
            if hasattr(self, '_pending_terminal_mode'):
                self._pending_terminal_mode = None

            port_name = self.port.currentText() or 'Serial'
            tab_label = f"Serial: {port_name}"
            terminal_dialog.setWindowTitle(f"Cetus Terminal - {tab_label}")
            terminal_dialog.set_connection_status(host=port_name, color=color, name=tab_label)

            self.open_terminals.append(terminal_dialog)
            terminal_dialog.terminal_closed.connect(
                lambda: self._on_terminal_closed(terminal_dialog)
            )

            # Add to tabbed manager window (same as SSH/Telnet)
            if self._terminal_manager is None or not self._terminal_manager.isVisible():
                self._terminal_manager = TerminalTabbedWindow()
            self._terminal_manager.add_terminal(terminal_dialog, tab_label, color)
            self._terminal_manager.show()
            self._terminal_manager.raise_()
            self._terminal_manager.activateWindow()

            self.status_label.setText("Connected - Terminal opened")
            self.status_label.setStyleSheet("color: #a6e3a1; font-size: 10pt;")
            self.status_led.setStyleSheet("color: #a6e3a1; font-size: 14px;")

            # Status remains connected (don't reset immediately)
            # Will reset when terminal is closed
        else:
            self.status_label.setText("Connection error")
            self.status_label.setStyleSheet("color: #f38ba8; font-size: 10pt;")
            self.status_led.setStyleSheet("color: #f38ba8; font-size: 14px;")


    # ──────────────────────────────────────────────────────────────────
    #  IPERF3 BANDWIDTH TEST PAGE
    # ──────────────────────────────────────────────────────────────────

    def create_iperf_page(self):
        """Create the iPerf3 / Speed Test bandwidth page."""
        BROWN = '#00897B'

        page = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 8, 10, 8)

        # ── Toggle button style helper ─────────────────────────────────
        def _toggle_style(color):
            return f"""
                QPushButton {{
                    background-color: #d8d8d8;
                    border: 1px solid #b0b0b0;
                    border-radius: 6px;
                    color: #444444;
                    font-size: 9pt;
                    padding: 3px 10px;
                }}
                QPushButton:checked {{
                    background-color: {color};
                    border-color: {color};
                    color: white;
                    font-weight: bold;
                }}
                QPushButton:hover:!checked {{
                    background-color: #c8c8c8;
                }}
            """

        def _mode_toggle_style(color):
            return f"""
                QPushButton {{
                    border: none;
                    border-bottom: 3px solid transparent;
                    border-radius: 0px;
                    padding: 4px 14px 3px 14px;
                    background: transparent;
                    color: #666;
                    font-size: 9pt;
                    font-weight: bold;
                    min-height: 26px;
                }}
                QPushButton:hover {{
                    color: {color};
                    background: rgba(0, 137, 123, 0.08);
                }}
                QPushButton:checked {{
                    color: {color};
                    border-bottom: 3px solid {color};
                    background: rgba(0, 137, 123, 0.10);
                }}
            """

        # ── Shared field styles ────────────────────────────────────────
        field_style = f"""
            QLineEdit {{
                border: 1px solid #d0d0d0; border-radius: 6px;
                padding: 2px 8px; background-color: #f5f5f5;
                color: #333333; font-size: 9pt;
            }}
            QLineEdit:focus {{ border: 2px solid {BROWN}; }}
            QLineEdit:disabled {{ background-color: #eeeeee; color: #aaaaaa; }}
        """
        spin_style = f"""
            QSpinBox {{
                border: 1px solid #d0d0d0; border-radius: 6px;
                padding: 2px 4px; background-color: #f5f5f5;
                color: #333333; font-size: 9pt;
            }}
            QSpinBox:focus {{ border: 2px solid {BROWN}; }}
        """
        lbl_style = "color: #444444; font-size: 9pt;"

        # ── Configuration group ────────────────────────────────────────
        cfg_group = QGroupBox("Configuration")
        cfg_layout = QVBoxLayout()
        cfg_layout.setContentsMargins(10, 8, 10, 10)
        cfg_layout.setSpacing(8)

        # Row 0: test-mode selector (Speed Test | iPerf3)
        # Outer QFrame owns the border+radius; buttons have no border of their own
        _btn_style = f"""
            QPushButton {{
                background-color: #e8e8e8;
                border: none;
                color: #555555;
                font-size: 10pt;
                font-weight: bold;
                padding: 4px 24px;
                min-height: 32px;
                min-width: 110px;
            }}
            QPushButton:checked     {{ background-color: {BROWN}; color: white; }}
            QPushButton:hover:!checked {{ background-color: #d8d8d8; }}
        """
        self._test_mode_speedtest_btn = QPushButton("Speed Test")
        self._test_mode_speedtest_btn.setCheckable(True)
        self._test_mode_speedtest_btn.setChecked(True)
        self._test_mode_speedtest_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_mode_speedtest_btn.setStyleSheet(
            _btn_style + "QPushButton { border-radius: 5px 0px 0px 5px; }"
        )
        _speedtest_ico = load_svg_icon_dual(self.get_icon_path('globe.svg'), 16, '#555555', '#ffffff')
        if _speedtest_ico:
            self._test_mode_speedtest_btn.setIcon(_speedtest_ico)
            self._test_mode_speedtest_btn.setIconSize(QSize(16, 16))
        self._test_mode_iperf_btn = QPushButton("iPerf3")
        self._test_mode_iperf_btn.setCheckable(True)
        self._test_mode_iperf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_mode_iperf_btn.setStyleSheet(
            _btn_style + "QPushButton { border-radius: 0px 5px 5px 0px; }"
        )
        _iperf_ico = load_svg_icon_dual(self.get_icon_path('rj45.svg'), 16, '#555555', '#ffffff')
        if _iperf_ico:
            self._test_mode_iperf_btn.setIcon(_iperf_ico)
            self._test_mode_iperf_btn.setIconSize(QSize(16, 16))
        # 1-px separator line between the two buttons
        _sep = QFrame()
        _sep.setFixedWidth(1)
        _sep.setStyleSheet("background-color: #b0b0b0; border: none;")
        # Outer frame — visible border and rounded corners
        _sel_wrap = QFrame()
        _sel_wrap.setStyleSheet(
            "QFrame { border: 1px solid #b0b0b0; border-radius: 6px; background: transparent; }"
        )
        _sel_inner = QHBoxLayout(_sel_wrap)
        _sel_inner.setContentsMargins(0, 0, 0, 0)
        _sel_inner.setSpacing(0)
        _sel_inner.addWidget(self._test_mode_speedtest_btn)
        _sel_inner.addWidget(_sep)
        _sel_inner.addWidget(self._test_mode_iperf_btn)

        self._test_mode_speedtest_btn.setToolTip(
            "Tests internet download/upload speed\n"
            "using speedtest.net.\nRequires: pip install speedtest-cli"
        )
        self._test_mode_iperf_btn.setToolTip(
            "Measures bandwidth between two hosts using iperf3.\n"
            "Ideal for LAN tests or between servers.\n"
            "Requires iperf3 installed on both machines."
        )
        self._test_mode_speedtest_btn.clicked.connect(
            lambda: self._iperf_switch_test_mode('speedtest'))
        self._test_mode_iperf_btn.clicked.connect(
            lambda: self._iperf_switch_test_mode('iperf'))

        sel_row = QHBoxLayout()
        sel_row.addStretch()
        sel_row.addWidget(_sel_wrap)
        sel_row.addStretch()
        cfg_layout.addLayout(sel_row)

        # ── iPerf-specific options (hidden when Speed Test is active) ──
        self._iperf_options_widget = QWidget()
        iperf_opts = QVBoxLayout(self._iperf_options_widget)
        iperf_opts.setContentsMargins(0, 2, 0, 0)
        iperf_opts.setSpacing(8)

        # Row 1: Host / Port / Duration
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        host_lbl = QLabel("Host:")
        host_lbl.setFixedWidth(58)
        host_lbl.setStyleSheet(lbl_style)
        self.iperf_host_input = QLineEdit()
        self.iperf_host_input.setPlaceholderText("iperf3 server address")
        self.iperf_host_input.setFixedHeight(26)
        self.iperf_host_input.setStyleSheet(field_style)
        self.iperf_discover_btn = QPushButton("Scan Server")
        self.iperf_discover_btn.setFixedHeight(24)
        self.iperf_discover_btn.setFixedWidth(100)
        self.iperf_discover_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.iperf_discover_btn.setToolTip("Scan local /24 network for an iperf3 server on port 5201")
        _scan_ico_path = self.get_icon_path('ipscan.svg')
        if _scan_ico_path:
            _scan_ico = load_svg_icon_dual(_scan_ico_path, 14, '#333333', '#ffffff')
            if _scan_ico:
                self.iperf_discover_btn.setIcon(_scan_ico)
                self.iperf_discover_btn.setIconSize(QSize(14, 14))
        self.iperf_discover_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #e0e0e0;
                border: 1px solid #b0b0b0;
                border-radius: 6px;
                color: #333333;
                font-size: 9pt;
                font-weight: normal;
                padding: 2px 4px;
            }}
            QPushButton:hover {{
                background-color: {BROWN};
                color: white;
                border-color: {BROWN};
            }}
            QPushButton:disabled {{ color: #aaaaaa; background-color: #eeeeee; }}
        """)
        self.iperf_discover_btn.clicked.connect(self._iperf_discover)
        port_lbl = QLabel("Port:")
        port_lbl.setFixedWidth(30)
        port_lbl.setStyleSheet(lbl_style)
        self.iperf_port_input = QLineEdit("5201")
        self.iperf_port_input.setFixedWidth(55)
        self.iperf_port_input.setFixedHeight(26)
        self.iperf_port_input.setStyleSheet(field_style)
        dur_lbl = QLabel("Duration:")
        dur_lbl.setFixedWidth(56)
        dur_lbl.setStyleSheet(lbl_style)
        self.iperf_duration_combo = FlatComboButton()
        self.iperf_duration_combo.addItems(["5 s", "10 s", "15 s", "20 s", "30 s", "60 s", "120 s", "300 s"])
        self.iperf_duration_combo.setCurrentText("10 s")
        self.iperf_duration_combo.setFixedWidth(70)
        self.iperf_duration_combo.setFixedHeight(26)
        # Arrow button — public iPerf3 server presets
        _iperf_servers = [
            ("🇧🇷 Brasil — São Paulo",      "speedtest.claro.net.br"),
            ("🇧🇷 Brasil — Rio de Janeiro", "200.160.7.186"),
            (None, None),
            ("🇺🇸 USA — Fremont, CA",       "iperf.he.net"),
            ("🇺🇸 USA — New York",          "nyc.speedtest.clouvider.net"),
            ("🇨🇦 Canadá — Toronto",        "speedtest.eastlink.ca"),
            (None, None),
            ("🇬🇧 UK — London",             "lon.speedtest.clouvider.net"),
            ("🇫🇷 França — Paris",          "bouygues.iperf.fr"),
            ("🇩🇪 Alemanha — Frankfurt",    "fra.speedtest.clouvider.net"),
            ("🇳🇱 Holanda",                 "speedtest.serverius.net"),
            (None, None),
            ("🇸🇬 Singapura",               "sgp.speedtest.clouvider.net"),
            ("🇦🇺 Austrália — Sydney",      "syd.speedtest.clouvider.net"),
        ]
        _srv_btn = QPushButton()
        _srv_btn.setIcon(QIcon(self.get_arrow_icon_path()))
        _srv_btn.setIconSize(QSize(16, 16))
        _srv_btn.setFixedWidth(28)
        _srv_btn.setFixedHeight(self.iperf_host_input.sizeHint().height() or 26)
        _srv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _srv_btn.setToolTip("Public iPerf3 servers")
        _srv_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
            }
            QPushButton:hover  { background-color: #e8e8e8; border-color: #b0b0b0; }
            QPushButton:pressed { background-color: #d8d8d8; }
        """)

        def _show_iperf_servers():
            menu = QMenu(_srv_btn)
            for entry in _iperf_servers:
                label, host = entry
                if label is None:
                    menu.addSeparator()
                else:
                    action = menu.addAction(f"{label}  —  {host}")
                    action.setData(host)
            chosen = menu.exec(_srv_btn.mapToGlobal(_srv_btn.rect().bottomLeft()))
            if chosen and chosen.data():
                self.iperf_host_input.setText(chosen.data())

        _srv_btn.clicked.connect(_show_iperf_servers)

        row1.addWidget(host_lbl)
        row1.addWidget(self.iperf_host_input, 1)
        row1.addWidget(self.iperf_discover_btn)
        row1.addWidget(_srv_btn)
        row1.addWidget(port_lbl)
        row1.addWidget(self.iperf_port_input)
        row1.addWidget(dur_lbl)
        row1.addWidget(self.iperf_duration_combo)

        # Row 2: Protocol / Streams / Bandwidth
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        proto_lbl = QLabel("Protocol:")
        proto_lbl.setFixedWidth(58)
        proto_lbl.setStyleSheet(lbl_style)
        self._iperf_proto_btns = {}
        for proto, _icokey in (('TCP', 'proto_tcp'), ('UDP', 'proto_udp')):
            btn = QPushButton(proto)
            btn.setCheckable(True)
            btn.setFixedWidth(90)
            btn.setFixedHeight(24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_toggle_style(BROWN))
            _p = self.get_icon_path(f'{_icokey}.svg')
            _ico = load_svg_icon_dual(_p, 16, '#555555', '#ffffff') if _p else None
            if _ico:
                btn.setIcon(_ico)
                btn.setIconSize(QSize(16, 16))
            btn.clicked.connect(lambda _checked, p=proto: self._iperf_proto_clicked(p))
            self._iperf_proto_btns[proto] = btn
        self._iperf_proto_btns['TCP'].setChecked(True)
        streams_lbl = QLabel("Streams:")
        streams_lbl.setFixedWidth(54)
        streams_lbl.setStyleSheet(lbl_style)
        self.iperf_streams_spin = QSpinBox()
        self.iperf_streams_spin.setRange(1, 64)
        self.iperf_streams_spin.setValue(1)
        self.iperf_streams_spin.setFixedWidth(55)
        self.iperf_streams_spin.setFixedHeight(26)
        self.iperf_streams_spin.setStyleSheet(spin_style)
        bw_lbl = QLabel("BW limit:")
        bw_lbl.setFixedWidth(56)
        bw_lbl.setStyleSheet(lbl_style)
        self.iperf_bw_input = QLineEdit("100")
        self.iperf_bw_input.setPlaceholderText("Mbits/s")
        self.iperf_bw_input.setToolTip("UDP bandwidth limit in Mbits/s")
        self.iperf_bw_input.setFixedWidth(70)
        self.iperf_bw_input.setFixedHeight(26)
        self.iperf_bw_input.setStyleSheet(field_style)
        self.iperf_bw_input.setVisible(False)
        self._iperf_bw_lbl = bw_lbl
        bw_lbl.setVisible(False)
        row2.addWidget(proto_lbl)
        row2.addWidget(self._iperf_proto_btns['TCP'])
        row2.addWidget(self._iperf_proto_btns['UDP'])
        row2.addWidget(streams_lbl)
        row2.addWidget(self.iperf_streams_spin)
        row2.addWidget(bw_lbl)
        row2.addWidget(self.iperf_bw_input)
        row2.addStretch()

        # Row 3: Mode / Scan Server
        row3 = QHBoxLayout()
        row3.setSpacing(6)
        self._iperf_mode_btns = {}
        for mode, _icokey in (('Client', 'speed_client'), ('Server', 'speed_server'), ('Reverse', 'speed_reverse')):
            btn = QPushButton(mode)
            btn.setCheckable(True)
            btn.setFixedWidth(90)
            btn.setFixedHeight(24)
            btn.setStyleSheet(_mode_toggle_style(BROWN))
            _p = self.get_icon_path(f'{_icokey}.svg')
            _ico = load_svg_icon_dual(_p, 16, '#555555', '#ffffff') if _p else None
            if _ico:
                btn.setIcon(_ico)
                btn.setIconSize(QSize(16, 16))
            btn.clicked.connect(lambda _c, m=mode: self._iperf_mode_clicked(m))
            self._iperf_mode_btns[mode] = btn
            row3.addWidget(btn)
        self._iperf_mode_btns['Client'].setChecked(True)
        row3.insertStretch(0)
        row3.addStretch()
        iperf_opts.addLayout(row3)
        _sep_line = QFrame()
        _sep_line.setFrameShape(QFrame.Shape.HLine)
        _sep_line.setStyleSheet("background: #d8d8d8; border: none; max-height: 1px;")
        iperf_opts.addWidget(_sep_line)
        iperf_opts.addLayout(row2)
        iperf_opts.addLayout(row1)

        self._iperf_options_widget.setVisible(False)   # Speed Test is the default
        cfg_layout.addWidget(self._iperf_options_widget)

        cfg_group.setLayout(cfg_layout)
        cfg_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        cfg_group.setGraphicsEffect(_shadow)
        main_layout.addWidget(cfg_group)

        # ── Statistics group (shared by both modes) ────────────────────
        stats_group = QGroupBox("Statistics")
        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(8, 6, 8, 8)
        stats_layout.setSpacing(6)

        card_style = """
            QFrame {
                background-color: #1a2a2a;
                border: 1px solid #00695C;
                border-radius: 8px;
            }
        """

        def _stat_card(icon, label, accent=BROWN):
            card = QFrame()
            card.setStyleSheet(card_style)
            card.setMinimumHeight(62)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            card_layout.setSpacing(2)
            hdr = QLabel(f"{icon}  {label}")
            hdr.setStyleSheet("color: #78909C; font-size: 8pt; font-weight: bold; background: transparent; border: none;")
            val = QLabel("—")
            val.setStyleSheet(f"color: {accent}; font-size: 16pt; font-weight: bold; background: transparent; border: none;")
            val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            card_layout.addWidget(hdr)
            card_layout.addWidget(val)
            return card, val

        self._ping_card, self.stat_ping      = _stat_card("🏓", "PING",     "#FFB300")
        dl_card,         self.stat_download  = _stat_card("⬇",  "THROUGHPUT", BROWN)
        self._ul_card,   self.stat_upload    = _stat_card("⬆",  "UPLOAD",   "#78909C")
        stats_layout.addWidget(self._ping_card,  1)
        stats_layout.addWidget(dl_card,          2)
        stats_layout.addWidget(self._ul_card,    2)
        self._ul_card.setVisible(False)   # hidden by default (Speed Test mode)

        stats_group.setLayout(stats_layout)
        stats_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        stats_group.setGraphicsEffect(_shadow)
        main_layout.addWidget(stats_group)

        # ── Graph group ────────────────────────────────────────────────
        graph_group = QGroupBox("Graph")
        graph_layout = QVBoxLayout()
        graph_layout.setContentsMargins(6, 4, 6, 6)
        self.iperf_graph = IperfGraphWidget()
        graph_layout.addWidget(self.iperf_graph)
        graph_group.setLayout(graph_layout)
        _shadow = QGraphicsDropShadowEffect()
        _shadow.setBlurRadius(15); _shadow.setXOffset(0); _shadow.setYOffset(2)
        _shadow.setColor(QColor(0, 0, 0, 30))
        graph_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        graph_group.setGraphicsEffect(_shadow)
        main_layout.addWidget(graph_group, 2)

        # ── Speed Test info bar (below graph, speedtest mode only) ────
        self._speedtest_info_bar = QFrame()
        self._speedtest_info_bar.setStyleSheet("""
            QFrame {
                background-color: #1a2a2a;
                border: 1px solid #00695C;
                border-radius: 8px;
            }
        """)
        info_row = QHBoxLayout(self._speedtest_info_bar)
        info_row.setContentsMargins(12, 8, 12, 8)
        info_row.setSpacing(0)

        def _info_col(title, stretch):
            col = QVBoxLayout()
            col.setSpacing(1)
            t = QLabel(title)
            t.setStyleSheet("color: #546e7a; font-size: 9pt; font-weight: bold; background: transparent; border: none;")
            v = QLabel("—")
            v.setStyleSheet("color: #cfd8dc; font-size: 11pt; background: transparent; border: none;")
            col.addWidget(t)
            col.addWidget(v)
            info_row.addLayout(col, stretch)
            return v

        def _vsep():
            s = QFrame()
            s.setFrameShape(QFrame.Shape.VLine)
            s.setStyleSheet("color: #1e3a3a; background: #1e3a3a; border: none; min-width: 1px; max-width: 1px;")
            info_row.addSpacing(12)
            info_row.addWidget(s)
            info_row.addSpacing(12)

        self._st_info_isp     = _info_col("ISP", 3)
        _vsep()
        self._st_info_country = _info_col("COUNTRY", 1)
        _vsep()
        self._st_info_server  = _info_col("SERVER", 2)

        self._speedtest_info_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        main_layout.addWidget(self._speedtest_info_bar)

        # ── Collapsible log ────────────────────────────────────────────
        self._log_toggle_btn = QPushButton("▶  Log")
        self._log_toggle_btn.setCheckable(True)
        self._log_toggle_btn.setChecked(False)
        self._log_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_toggle_btn.setToolTip("Click to expand / collapse the log")
        self._log_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #252535;
                border: 1px solid #333345;
                border-radius: 6px;
                color: #78909C;
                font-size: 8pt;
                font-weight: bold;
                padding: 4px 10px;
                text-align: left;
            }
            QPushButton:checked {
                background-color: #1a2030;
                border-color: #00695C;
                color: #b2dfdb;
                border-radius: 4px 4px 0px 0px;
            }
            QPushButton:hover { border-color: #00897B; color: #b2dfdb; }
        """)
        self.iperf_log = QPlainTextEdit()
        self.iperf_log.setReadOnly(True)
        self.iperf_log.setMaximumBlockCount(2000)
        self.iperf_log.setFixedHeight(110)
        self.iperf_log.setFont(QFont("Monospace", 8))
        self.iperf_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1a1a2e;
                color: #c8c8c8;
                border: 1px solid #00695C;
                border-top: none;
                border-radius: 0px 0px 4px 4px;
            }
        """)
        self.iperf_log.setVisible(False)

        def _toggle_log():
            open_ = self._log_toggle_btn.isChecked()
            self.iperf_log.setVisible(open_)
            self._log_toggle_btn.setText("▼  Log" if open_ else "▶  Log")

        self._log_toggle_btn.clicked.connect(_toggle_log)
        main_layout.addWidget(self._log_toggle_btn)
        main_layout.addWidget(self.iperf_log)

        # ── Action button (label/handler change with test mode) ────────
        self.iperf_run_btn = QPushButton("SPEED TEST")
        self.iperf_run_btn.setMinimumHeight(45)
        self.iperf_run_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.iperf_run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.iperf_run_btn.setStyleSheet("""
            QPushButton {
                background-color: #00897B;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #00796B; }
            QPushButton:pressed { background-color: #E65100; }
            QPushButton:disabled { background-color: #4DB6AC; color: #ffffffaa; }
        """)
        self.iperf_run_btn.clicked.connect(self._speedtest_run)   # default = Speed Test
        self.iperf_run_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _btn_shadow = QGraphicsDropShadowEffect()
        _btn_shadow.setBlurRadius(12); _btn_shadow.setXOffset(0); _btn_shadow.setYOffset(3)
        _btn_shadow.setColor(QColor(0, 0, 0, 60))
        self.iperf_run_btn.setGraphicsEffect(_btn_shadow)
        _iperf_run_ico = load_svg_icon_dual(self.get_icon_path('globe.svg'), 18, '#ffffff', '#ffffff')
        if _iperf_run_ico:
            self.iperf_run_btn.setIcon(_iperf_run_ico)
            self.iperf_run_btn.setIconSize(QSize(18, 18))
            self.iperf_run_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        main_layout.addWidget(self.iperf_run_btn)

        page.setLayout(main_layout)
        return page

    # ── iPerf3 handlers ───────────────────────────────────────────────────

    def _iperf_proto_clicked(self, proto):
        for p, btn in self._iperf_proto_btns.items():
            btn.setChecked(p == proto)
        is_udp = (proto == 'UDP')
        self.iperf_bw_input.setVisible(is_udp)
        self._iperf_bw_lbl.setVisible(is_udp)
        if self._test_mode_iperf_btn.isChecked():
            _ico = load_svg_icon_dual(self.get_icon_path(f'proto_{proto.lower()}.svg'), 18, '#ffffff', '#ffffff')
            if _ico:
                self.iperf_run_btn.setIcon(_ico)
                self.iperf_run_btn.setIconSize(QSize(18, 18))

    def _iperf_mode_clicked(self, mode):
        for m, btn in self._iperf_mode_btns.items():
            btn.setChecked(m == mode)
        is_server = (mode == 'Server')
        is_client = (mode == 'Client')
        self.iperf_host_input.setEnabled(not is_server)
        self.iperf_discover_btn.setVisible(is_client)
        if is_server:
            self.iperf_run_btn.setText("START SERVER")
        else:
            self.iperf_run_btn.setText("RUN IPERF3")

    def _iperf_discover(self):
        """Scan local /24 subnet for an iperf3 server and auto-fill host field."""
        try:
            port = int(self.iperf_port_input.text().strip() or '5201')
        except ValueError:
            port = 5201

        self.iperf_discover_btn.setEnabled(False)
        self.iperf_discover_btn.setText("Scanning…")
        self.iperf_log.appendPlainText(f"[SCAN] Searching local network for iperf3 server on port {port}…")

        self._iperf_discover_worker = Iperf3DiscoverWorker(port=port)
        self._iperf_discover_worker.host_found.connect(self._on_iperf_host_found)
        self._iperf_discover_worker.scan_status.connect(
            lambda msg: self.iperf_log.appendPlainText(f"[SCAN] {msg}")
        )
        self._iperf_discover_worker.not_found.connect(self._on_iperf_host_not_found)
        self._iperf_discover_worker.finished.connect(
            lambda: (self.iperf_discover_btn.setEnabled(True),
                     self.iperf_discover_btn.setText("Scan Server"))
        )
        self._iperf_discover_worker.start()

    def _on_iperf_host_found(self, ip):
        self.iperf_host_input.setText(ip)
        self.iperf_log.appendPlainText(f"[SCAN] Found iperf3 server at {ip} — host field updated.")

    def _on_iperf_host_not_found(self):
        self.iperf_log.appendPlainText("[SCAN] No iperf3 server found on local network.")

    def _iperf_run(self):
        # Toggle stop if already running
        if hasattr(self, '_iperf_worker') and self._iperf_worker and self._iperf_worker.isRunning():
            self._iperf_worker.stop()
            return

        mode = next((m for m, b in self._iperf_mode_btns.items() if b.isChecked()), 'Client')
        proto = next((p for p, b in self._iperf_proto_btns.items() if b.isChecked()), 'TCP')
        host = self.iperf_host_input.text().strip()

        if mode != 'Server' and not host:
            self.iperf_log.appendPlainText("Error: host is required in Client/Reverse mode.")
            return

        try:
            port = int(self.iperf_port_input.text().strip() or '5201')
        except ValueError:
            port = 5201

        duration = int(self.iperf_duration_combo.currentText().split()[0])
        streams  = self.iperf_streams_spin.value()
        reverse  = (mode == 'Reverse')
        iperf_mode = 'server' if mode == 'Server' else 'client'

        try:
            bw = float(self.iperf_bw_input.text().strip() or '100')
        except ValueError:
            bw = 100.0

        # Reset UI
        self.iperf_graph.clear()
        self.iperf_log.clear()
        for lbl in (self.stat_download, self.stat_upload):
            lbl.setText("—")

        self.iperf_run_btn.setText("STOP ■")
        self.iperf_run_btn.setStyleSheet("""
            QPushButton {
                background-color: #c62828;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #e53935; }
            QPushButton:pressed { background-color: #b71c1c; }
        """)

        self._iperf_worker = Iperf3Worker(
            host, port, duration, proto, streams, bw, reverse, iperf_mode
        )
        self._iperf_worker.interval_result.connect(self._on_iperf_interval)
        self._iperf_worker.finished.connect(self._on_iperf_finished)
        self._iperf_worker.error.connect(self._on_iperf_error)
        self._iperf_worker.log_line.connect(self._on_iperf_log)
        self._iperf_worker.finished.connect(self._iperf_reset_btn)
        self._iperf_worker.error.connect(self._iperf_reset_btn)
        if iperf_mode == 'client':
            self._iperf_worker.finished.connect(self._iperf_run_ping)
        self._iperf_worker.start()

    def _iperf_reset_btn(self):
        is_server = next((m for m, b in self._iperf_mode_btns.items() if b.isChecked()), 'Client') == 'Server'
        self.iperf_run_btn.setText("START SERVER" if is_server else "RUN IPERF3")
        self.iperf_run_btn.setEnabled(True)
        self.iperf_run_btn.setStyleSheet("""
            QPushButton {
                background-color: #00897B;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #00796B; }
            QPushButton:pressed { background-color: #E65100; }
            QPushButton:disabled { background-color: #4DB6AC; color: #ffffffaa; }
        """)

    def _on_iperf_interval(self, t_end, bitrate_mbps, transfer_mb):
        self.iperf_graph.add_interval(t_end, bitrate_mbps, transfer_mb)
        unit = "Gbps" if bitrate_mbps >= 1000 else "Mbps"
        disp = f"{bitrate_mbps/1000:.2f}" if bitrate_mbps >= 1000 else f"{bitrate_mbps:.1f}"
        self.stat_download.setText(f"{disp} {unit}")
        xfer_unit = "GB" if transfer_mb >= 1024 else "MB"
        xfer_disp = f"{transfer_mb/1024:.2f}" if transfer_mb >= 1024 else f"{transfer_mb:.1f}"
        self.stat_upload.setText(f"{xfer_disp} {xfer_unit}")

    def _on_iperf_finished(self, avg_bps, total_mb):
        unit = "Gbps" if avg_bps >= 1000 else "Mbps"
        disp = f"{avg_bps/1000:.2f}" if avg_bps >= 1000 else f"{avg_bps:.1f}"
        self.stat_download.setText(f"{disp} {unit} avg")
        xfer_unit = "GB" if total_mb >= 1024 else "MB"
        xfer_disp = f"{total_mb/1024:.2f}" if total_mb >= 1024 else f"{total_mb:.1f}"
        self.stat_upload.setText(f"{xfer_disp} {xfer_unit}")

    def _on_iperf_error(self, msg):
        self.iperf_log.appendPlainText(f"[ERROR] {msg}")

    def _on_iperf_log(self, line):
        self.iperf_log.appendPlainText(line)
        self.iperf_log.verticalScrollBar().setValue(
            self.iperf_log.verticalScrollBar().maximum()
        )

    def _iperf_run_ping(self):
        """After a successful iPerf3 client run, ping the host to fill the PING card."""
        host = self.iperf_host_input.text().strip()
        if not host:
            return
        self.stat_ping.setText("…")
        self._ping_worker = _SimplePingWorker(host)
        self._ping_worker.result.connect(lambda ms: self.stat_ping.setText(f"{ms:.1f} ms"))
        self._ping_worker.error.connect(lambda _e: self.stat_ping.setText("—"))
        self._ping_worker.start()

    # ── Test-mode switcher ────────────────────────────────────────────────

    def _iperf_switch_test_mode(self, mode):
        """Switch between 'speedtest' and 'iperf' modes."""
        is_iperf = (mode == 'iperf')
        self._test_mode_speedtest_btn.setChecked(not is_iperf)
        self._test_mode_iperf_btn.setChecked(is_iperf)
        self._iperf_options_widget.setVisible(is_iperf)
        self._speedtest_info_bar.setVisible(not is_iperf)
        self._ul_card.setVisible(False)   # always hidden — unified single-speed view
        # Reset stats
        for lbl in (self.stat_ping, self.stat_download, self.stat_upload,
                    self._st_info_isp, self._st_info_country, self._st_info_server):
            lbl.setText("—")
        self.iperf_graph.clear()
        # Reconnect action button
        try:
            self.iperf_run_btn.clicked.disconnect()
        except Exception:
            pass
        if is_iperf:
            is_server = next(
                (m for m, b in self._iperf_mode_btns.items() if b.isChecked()), 'Client'
            ) == 'Server'
            self.iperf_run_btn.setText("START SERVER" if is_server else "RUN IPERF3")
            self.iperf_run_btn.clicked.connect(self._iperf_run)
            _cur_proto = next((p for p, b in self._iperf_proto_btns.items() if b.isChecked()), 'TCP')
            _iperf_ico = load_svg_icon_dual(self.get_icon_path(f'proto_{_cur_proto.lower()}.svg'), 18, '#ffffff', '#ffffff')
            if _iperf_ico:
                self.iperf_run_btn.setIcon(_iperf_ico)
                self.iperf_run_btn.setIconSize(QSize(18, 18))
        else:
            self.iperf_run_btn.setText("SPEED TEST")
            self.iperf_run_btn.clicked.connect(self._speedtest_run)
            _globe_ico = load_svg_icon_dual(self.get_icon_path('globe.svg'), 18, '#ffffff', '#ffffff')
            if _globe_ico:
                self.iperf_run_btn.setIcon(_globe_ico)
                self.iperf_run_btn.setIconSize(QSize(18, 18))
        self.iperf_run_btn.setEnabled(True)
        self.iperf_run_btn.setStyleSheet("""
            QPushButton {
                background-color: #00897B;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover { background-color: #00796B; }
            QPushButton:pressed { background-color: #E65100; }
            QPushButton:disabled { background-color: #4DB6AC; color: #ffffffaa; }
        """)

    # ── Speed Test handlers ───────────────────────────────────────────────

    def _speedtest_run(self):
        self.iperf_run_btn.setEnabled(False)
        self.iperf_run_btn.setText("TESTING…")
        self.stat_ping.setText("—")
        self.stat_download.setText("—")
        self.stat_upload.setText("—")
        self.iperf_graph.clear()
        self.iperf_log.appendPlainText("\n── Speed Test ──")
        for lbl in (self._st_info_isp, self._st_info_country, self._st_info_server):
            lbl.setText("—")
        self._speedtest_worker = SpeedTestWorker()
        self._speedtest_worker.result.connect(self._on_speedtest_result)
        self._speedtest_worker.info.connect(self._on_speedtest_info)
        self._speedtest_worker.progress.connect(self._on_speedtest_progress)
        self._speedtest_worker.phase_done.connect(self._on_speedtest_phase_done)
        self._speedtest_worker.log_line.connect(self._on_speedtest_log)
        self._speedtest_worker.error.connect(self._on_speedtest_error)
        self._speedtest_worker.finished.connect(self._on_speedtest_done)
        self._speedtest_worker.start()

    def _on_speedtest_info(self, isp, _isp_rating, country, server_name):
        self._st_info_isp.setText(isp)
        self._st_info_country.setText(country)
        self._st_info_server.setText(server_name)

    def _on_speedtest_progress(self, elapsed_s, speed_mbps, total_mb):
        """Real-time sample from the download worker — add directly to graph."""
        self.iperf_graph.add_interval(elapsed_s, speed_mbps, total_mb, 0)
        self.stat_download.setText(f"{speed_mbps:.2f} Mbps")

    def _on_speedtest_phase_done(self, phase, mbps):
        pass   # graph already populated by real-time progress samples

    def _on_speedtest_result(self, ping_ms, dl_mbps, ul_mbps):
        self.stat_ping.setText(f"{ping_ms:.0f} ms")
        self.stat_download.setText(f"{dl_mbps:.2f} Mbps")
        if ul_mbps > 0:
            self.stat_upload.setText(f"{ul_mbps:.2f} Mbps")

    def _on_speedtest_log(self, line):
        self.iperf_log.appendPlainText(line)
        self.iperf_log.verticalScrollBar().setValue(
            self.iperf_log.verticalScrollBar().maximum()
        )

    def _on_speedtest_error(self, msg):
        self.iperf_log.appendPlainText(f"[ERROR] {msg}")

    def _on_speedtest_done(self):
        self.iperf_run_btn.setEnabled(True)
        self.iperf_run_btn.setText("SPEED TEST")
        # Ping fast.com to fill the latency card
        self.stat_ping.setText("…")
        self._st_ping_worker = _SimplePingWorker('speedtest.net')
        self._st_ping_worker.result.connect(lambda ms: self.stat_ping.setText(f"{ms:.1f} ms"))
        self._st_ping_worker.error.connect(lambda _: self.stat_ping.setText("—"))
        self._st_ping_worker.start()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("cetus")
    app.setDesktopFileName("cetus")

    # Set default font
    font = QFont("Sans Serif", 9)
    app.setFont(font)

    window = SerialTerminalGUI()

    # Set application window icon
    icon_path = window.get_icon_path('cetus-256.png')
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
