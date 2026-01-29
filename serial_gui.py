#!/usr/bin/env python3
"""
SerialCom - Graphical interface for serial communication via picocom
Version: 1.0
"""

import sys
import subprocess
import glob
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QFormLayout, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPalette, QColor

# Application version
VERSION = "1.0"

try:
    from PyQt6.QtSerialPort import QSerialPortInfo
    SERIAL_PORT_AVAILABLE = True
except ImportError:
    SERIAL_PORT_AVAILABLE = False


class SerialTerminalGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SerialCom v{VERSION}")
        self.setFixedSize(550, 500)
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        """Initialize the user interface"""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel(f"SerialCom v{VERSION}")
        title_font = QFont("Sans Serif", 16, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Port configuration group
        port_group = QGroupBox("Port Configuration")
        port_layout = QFormLayout()
        port_layout.setSpacing(10)

        # Port type
        self.port_type = QComboBox()
        self.port_type.addItems(['Serial (/dev/ttyS*)', 'USB (/dev/ttyUSB*)', 'All Ports'])
        self.port_type.setCurrentIndex(1)
        self.port_type.currentIndexChanged.connect(self.update_port_list)
        port_layout.addRow("Port Type:", self.port_type)

        # Specific port
        self.port = QComboBox()
        self.port.setMinimumHeight(30)
        port_layout.addRow("Port:", self.port)

        port_group.setLayout(port_layout)
        main_layout.addWidget(port_group)

        # Communication parameters group
        comm_group = QGroupBox("Communication Parameters")
        comm_layout = QFormLayout()
        comm_layout.setSpacing(10)

        # Baud Rate - MAIN FIELD
        velocity_label = QLabel("Baud Rate:")
        velocity_font = QFont("Sans Serif", 10, QFont.Weight.Bold)
        velocity_label.setFont(velocity_font)

        self.baudrate = QComboBox()
        self.baudrate.addItems([
            '300', '1200', '2400', '4800', '9600', '19200',
            '38400', '57600', '115200', '230400', '460800', '921600'
        ])
        self.baudrate.setCurrentText('9600')
        self.baudrate.setMinimumHeight(35)
        self.baudrate.setStyleSheet("""
            QComboBox {
                background-color: #e3f2fd;
                border: 2px solid #2196f3;
                border-radius: 5px;
                padding: 5px;
                font-weight: bold;
            }
        """)
        comm_layout.addRow(velocity_label, self.baudrate)

        # Data bits
        self.databits = QComboBox()
        self.databits.addItems(['5', '6', '7', '8'])
        self.databits.setCurrentText('8')
        comm_layout.addRow("Data Bits:", self.databits)

        # Parity
        self.parity = QComboBox()
        self.parity.addItems(['None', 'Even', 'Odd'])
        self.parity.setCurrentText('None')
        comm_layout.addRow("Parity:", self.parity)

        # Stop bits
        self.stopbits = QComboBox()
        self.stopbits.addItems(['1', '2'])
        self.stopbits.setCurrentText('1')
        comm_layout.addRow("Stop Bits:", self.stopbits)

        # Flow control
        self.flow = QComboBox()
        self.flow.addItems(['None', 'Hardware (RTS/CTS)', 'Software (XON/XOFF)'])
        self.flow.setCurrentText('None')
        comm_layout.addRow("Flow Control:", self.flow)

        comm_group.setLayout(comm_layout)
        main_layout.addWidget(comm_group)

        # Connect button
        self.connect_btn = QPushButton("CONNECT")
        self.connect_btn.setMinimumHeight(45)
        self.connect_btn.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
        self.connect_btn.clicked.connect(self.connect)
        main_layout.addWidget(self.connect_btn)

        # Status
        self.status_label = QLabel("Ready to connect")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: green; font-size: 10pt; padding: 5px;")
        main_layout.addWidget(self.status_label)

        central_widget.setLayout(main_layout)

        # Update port list
        self.update_port_list()

    def apply_styles(self):
        """Apply modern styles to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QComboBox {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 5px;
                background-color: white;
                min-height: 25px;
            }
            QComboBox:hover {
                border: 1px solid #2196f3;
            }
            QComboBox:focus {
                border: 2px solid #2196f3;
            }
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QLabel {
                color: #333333;
            }
        """)

    def update_port_list(self):
        """Update the list of available ports"""
        self.port.clear()

        port_type = self.port_type.currentText()
        ports = []

        if SERIAL_PORT_AVAILABLE and 'All' in port_type:
            # Use QSerialPortInfo to detect all ports
            available_ports = QSerialPortInfo.availablePorts()
            ports = [port.portName() for port in available_ports]
            ports = [f"/dev/{p}" for p in ports]
        else:
            # Use glob to search for ports
            if 'Serial' in port_type:
                pattern = '/dev/ttyS*'
            elif 'USB' in port_type:
                pattern = '/dev/ttyUSB*'
            else:  # All
                ports_s = sorted(glob.glob('/dev/ttyS*'))
                ports_usb = sorted(glob.glob('/dev/ttyUSB*'))
                ports = ports_s + ports_usb

            if not ports:
                ports = sorted(glob.glob(pattern))

        if ports:
            self.port.addItems(ports)
            self.status_label.setText(f"{len(ports)} port(s) found")
            self.status_label.setStyleSheet("color: green; font-size: 10pt; padding: 5px;")
        else:
            self.port.addItem("No ports found")
            self.status_label.setText("No serial ports available")
            self.status_label.setStyleSheet("color: orange; font-size: 10pt; padding: 5px;")

    def build_picocom_command(self):
        """Build the picocom command with configured parameters"""
        port = self.port.currentText()

        if 'No ports found' in port or not port:
            return None

        baudrate = self.baudrate.currentText()
        databits = self.databits.currentText()

        # Parity
        parity_map = {'None': 'n', 'Even': 'e', 'Odd': 'o'}
        parity = parity_map[self.parity.currentText()]

        stopbits = self.stopbits.currentText()

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

    def connect(self):
        """Connect to the serial port using picocom"""
        # Check if picocom is installed
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

        self.status_label.setText("Connecting...")
        self.status_label.setStyleSheet("color: orange; font-size: 10pt; padding: 5px;")
        QApplication.processEvents()

        # Determine default terminal
        terminals = [
            'gnome-terminal',
            'konsole',
            'xfce4-terminal',
            'kitty',
            'alacritty',
            'xterm'
        ]

        terminal_cmd = None
        for term in terminals:
            try:
                subprocess.run(['which', term], check=True, capture_output=True)
                terminal_cmd = term
                break
            except subprocess.CalledProcessError:
                continue

        if not terminal_cmd:
            QMessageBox.critical(
                self,
                "Error",
                "No terminal found on the system.\n\n"
                "Install a terminal like:\n"
                "sudo pacman -S gnome-terminal"
            )
            self.status_label.setText("Error: terminal not found")
            self.status_label.setStyleSheet("color: red; font-size: 10pt; padding: 5px;")
            return

        # Build full command with sudo
        picocom_cmd_str = ' '.join(cmd)

        # Terminal-specific commands
        if terminal_cmd == 'gnome-terminal':
            full_cmd = [terminal_cmd, '--', 'bash', '-c',
                       f'sudo {picocom_cmd_str}; echo "\nPress Enter to close..."; read']
        elif terminal_cmd == 'konsole':
            full_cmd = [terminal_cmd, '-e', 'bash', '-c',
                       f'sudo {picocom_cmd_str}; echo "\nPress Enter to close..."; read']
        elif terminal_cmd in ['xfce4-terminal', 'xterm']:
            full_cmd = [terminal_cmd, '-e', 'bash', '-c',
                       f'sudo {picocom_cmd_str}; echo "\nPress Enter to close..."; read']
        else:  # kitty, alacritty
            full_cmd = [terminal_cmd, 'bash', '-c',
                       f'sudo {picocom_cmd_str}; echo "\nPress Enter to close..."; read']

        try:
            subprocess.Popen(full_cmd)
            self.status_label.setText("Terminal opened - enter root password")
            self.status_label.setStyleSheet("color: blue; font-size: 10pt; padding: 5px;")

            # Show connection information
            QMessageBox.information(
                self,
                "Connection Started",
                f"Picocom terminal opened.\n\n"
                f"Port: {self.port.currentText()}\n"
                f"Baud Rate: {self.baudrate.currentText()} baud\n"
                f"Configuration: {self.databits.currentText()}{self.parity.currentText()[0]}{self.stopbits.currentText()}\n\n"
                f"Use Ctrl+A Ctrl+X to exit picocom"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error opening terminal:\n{str(e)}"
            )
            self.status_label.setText("Connection error")
            self.status_label.setStyleSheet("color: red; font-size: 10pt; padding: 5px;")


def main():
    app = QApplication(sys.argv)

    # Set default font
    font = QFont("Sans Serif", 9)
    app.setFont(font)

    window = SerialTerminalGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
