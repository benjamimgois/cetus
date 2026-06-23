"""Utility classes and helpers for Cetus."""

import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

try:
    from PyQt6.QtSvg import QSvgRenderer
    SVG_AVAILABLE = True
except ImportError:
    QSvgRenderer = None
    SVG_AVAILABLE = False

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap


__all__ = ['TFTPHandler', 'TFTPServer', 'SVG_AVAILABLE', 'load_svg_pixmap', 'load_svg_icon', 'load_svg_icon_dual']


class TFTPHandler(socketserver.BaseRequestHandler):
    """Simple TFTP request handler supporting RRQ (read) operations"""

    TFTP_OPCODES: dict[int, str] = {
        1: 'RRQ',   # Read request
        2: 'WRQ',   # Write request
        3: 'DATA',  # Data
        4: 'ACK',   # Acknowledgment
        5: 'ERROR'  # Error
    }

    def handle(self) -> None:
        data, sock = self.request
        opcode = int.from_bytes(data[0:2], 'big')

        if opcode == 1:  # RRQ - Read Request
            self.handle_rrq(data, sock)
        elif opcode == 2:  # WRQ - Write Request
            self.handle_wrq(data, sock)

    def handle_rrq(self, data, sock):
        """Handle read request - send file to client"""
        # Parse filename from request
        parts = data[2:].split(b'\x00')
        filename = parts[0].decode('utf-8')

        # Get the file path from server's root directory
        filepath = os.path.join(self.server.tftp_root, filename)

        if not os.path.exists(filepath):
            # Send error: File not found
            error_packet = b'\x00\x05\x00\x01File not found\x00'
            sock.sendto(error_packet, self.client_address)
            print(f"[TFTP] File not found: {filename}")
            return

        try:
            with open(filepath, 'rb') as f:
                block_num = 1
                while True:
                    file_data = f.read(512)
                    # Build DATA packet: opcode (2 bytes) + block# (2 bytes) + data
                    data_packet = b'\x00\x03' + block_num.to_bytes(2, 'big') + file_data
                    sock.sendto(data_packet, self.client_address)

                    # Wait for ACK
                    sock.settimeout(5.0)
                    try:
                        ack_data, _ = sock.recvfrom(516)
                        ack_opcode = int.from_bytes(ack_data[0:2], 'big')
                        ack_block = int.from_bytes(ack_data[2:4], 'big')

                        if ack_opcode != 4 or ack_block != block_num:
                            print(f"[TFTP] Unexpected ACK: opcode={ack_opcode}, block={ack_block}")
                            break
                    except socket.timeout:
                        print(f"[TFTP] Timeout waiting for ACK block {block_num}")
                        break

                    if len(file_data) < 512:
                        # Last block sent
                        print(f"[TFTP] Transfer complete: {filename}")
                        break

                    block_num += 1

        except Exception as e:
            error_packet = b'\x00\x05\x00\x00' + str(e).encode() + b'\x00'
            sock.sendto(error_packet, self.client_address)
            print(f"[TFTP] Error reading file: {e}")

    def handle_wrq(self, data, sock):
        """Handle write request - receive file from client"""
        # Parse filename from request
        parts = data[2:].split(b'\x00')
        filename = parts[0].decode('utf-8')

        # Get the file path in server's root directory
        filepath = os.path.join(self.server.tftp_root, filename)

        try:
            # Send ACK for block 0 to start transfer
            ack_packet = b'\x00\x04\x00\x00'
            sock.sendto(ack_packet, self.client_address)

            with open(filepath, 'wb') as f:
                block_num = 1
                while True:
                    sock.settimeout(5.0)
                    try:
                        data_packet, _ = sock.recvfrom(516)
                        opcode = int.from_bytes(data_packet[0:2], 'big')
                        recv_block = int.from_bytes(data_packet[2:4], 'big')

                        if opcode != 3 or recv_block != block_num:
                            print(f"[TFTP] Unexpected DATA: opcode={opcode}, block={recv_block}")
                            break

                        file_data = data_packet[4:]
                        f.write(file_data)

                        # Send ACK
                        ack_packet = b'\x00\x04' + block_num.to_bytes(2, 'big')
                        sock.sendto(ack_packet, self.client_address)

                        if len(file_data) < 512:
                            print(f"[TFTP] Receive complete: {filename}")
                            break

                        block_num += 1

                    except socket.timeout:
                        print(f"[TFTP] Timeout waiting for DATA block {block_num}")
                        break

        except Exception as e:
            error_packet = b'\x00\x05\x00\x00' + str(e).encode() + b'\x00'
            sock.sendto(error_packet, self.client_address)
            print(f"[TFTP] Error writing file: {e}")


class TFTPServer:
    """Simple TFTP Server"""

    def __init__(self, host='0.0.0.0', port=69, root_dir=None):
        self.host = host
        self.port = port
        # Use XDG HOME for Flatpak compatibility
        self.root_dir = root_dir or os.environ.get('HOME', str(Path.home()))
        self.server = None
        self.thread = None
        self.running = False

    def start(self):
        """Start the TFTP server in a background thread"""
        if self.running:
            return False

        try:
            self.server = socketserver.UDPServer((self.host, self.port), TFTPHandler)
            self.server.tftp_root = self.root_dir
            self.thread = threading.Thread(target=self._serve, daemon=True)
            self.thread.start()
            self.running = True
            print(f"[TFTP] Server started on {self.host}:{self.port}, root: {self.root_dir}")
            return True
        except PermissionError:
            print(f"[TFTP] Permission denied for port {self.port}. Try running with sudo or use port > 1024")
            return False
        except Exception as e:
            print(f"[TFTP] Failed to start server: {e}")
            return False

    def _serve(self):
        """Serve requests until stopped"""
        try:
            self.server.serve_forever()
        except Exception as e:
            print(f"[TFTP] Server error: {e}")
            self.running = False

    def stop(self):
        """Stop the TFTP server"""
        if not self.running:
            return

        self.running = False
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                print(f"[TFTP] Error stopping server: {e}")
            finally:
                self.server = None
        print("[TFTP] Server stopped")

    def is_running(self):
        return self.running


def load_svg_pixmap(path, size=40):
    """Load an SVG file as QPixmap using QSvgRenderer for reliable rendering"""
    if not path or not os.path.exists(path):
        return None
    if SVG_AVAILABLE:
        renderer = QSvgRenderer(path)
        if renderer.isValid():
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return pixmap
    # Fallback to QPixmap direct loading
    return QPixmap(path)


def load_svg_icon(path, size=40):
    """Load an SVG file as QIcon using QSvgRenderer for reliable rendering"""
    pixmap = load_svg_pixmap(path, size)
    if pixmap and not pixmap.isNull():
        return QIcon(pixmap)
    return None


def load_svg_icon_dual(path, size=16, color_off='#555555', color_on='#ffffff'):
    """Load SVG as dual-state QIcon: dark when unchecked (Off), white when checked (On).
    Designed for toggle buttons with light unchecked / colored checked backgrounds."""
    if not path or not os.path.exists(path):
        return None
    if not SVG_AVAILABLE:
        return load_svg_icon(path, size)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            svg_src = f.read()
    except OSError:
        return None
    icon = QIcon()
    for qt_state, color in ((QIcon.State.Off, color_off), (QIcon.State.On, color_on)):
        svg = re.sub(r'fill="(?!none\b|transparent\b)[^"]*"', f'fill="{color}"', svg_src)
        svg = re.sub(r'stroke="(?!none\b|transparent\b)[^"]*"', f'stroke="{color}"', svg)
        renderer = QSvgRenderer(svg.encode())
        if not renderer.isValid():
            continue
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, qt_state)
    return icon if not icon.isNull() else None

_OUI_VENDORS = None   # built once, re-used on every subsequent call

# Candidate system OUI database paths (tried in order)
_OUI_DB_PATHS = [
    '/usr/share/hwdata/oui.txt',
    '/usr/share/ieee-data/oui.txt',
    '/usr/share/arp-scan/ieee-oui.txt',
    '/usr/share/wireshark/manuf',
]

def _load_system_oui_db():
    """Parse the system OUI database into a {OUI6HEX: vendor} dict.
    Returns an empty dict if no file is found or parsing fails."""
    import re
    result = {}
    for path in _OUI_DB_PATHS:
        try:
            with open(path, 'r', errors='replace') as fh:
                for line in fh:
                    # hwdata/ieee format: "286FB9     (base 16)  Nokia..."
                    m = re.match(r'^([0-9A-Fa-f]{6})\s+\(base 16\)\s+(.+)', line)
                    if m:
                        result[m.group(1).upper()] = m.group(2).strip()
                        continue
                    # wireshark/manuf format: "28:6F:B9  Nokia..."
                    m = re.match(r'^([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})\s+\S+\s+(.*)', line)
                    if m:
                        result[m.group(1).replace(':', '').upper()] = m.group(2).strip()
            if result:
                return result
        except OSError:
            continue
    return result

def _get_mac_vendor(mac):
    """Lookup MAC vendor from OUI (first 3 octets). Dict is built once and cached."""
    global _OUI_VENDORS
    if not mac or len(mac) < 8:
        return "Unknown"

    oui = mac.replace(':', '').upper()[:6]

    # Randomised / locally-administered MAC — cannot resolve to a vendor
    if len(mac) >= 2 and mac[1].upper() in ('2', '6', 'A', 'E'):
        return 'Private/Local'

    # Fast path: dict already built
    if _OUI_VENDORS is not None:
        return _OUI_VENDORS.get(oui, 'Unknown')

    # First call only: try system OUI database, fall back to built-in table
    vendors = _load_system_oui_db()
    if not vendors:
        # Fallback minimal built-in table
        vendors = {
        # IANA and Standards
        '00005E': 'IANA',
        '70B3D5': 'IEEE',
        
        # Apple
        '001B63': 'Apple',
        '10FEED': 'Apple',
        '3C0754': 'Apple',
        '54EE75': 'Apple',
        '6C4008': 'Apple',
        '8C8590': 'Apple',
        '9C5C8E': 'Apple',
        'A0999B': 'Apple',
        'A483E7': 'Apple',
        'AC87A3': 'Apple',
        'B8E856': 'Apple',
        'BC3BAF': 'Apple',
        'C82A14': 'Apple',
        'D023DB': 'Apple',
        'D49A20': 'Apple',
        'E0ACCB': 'Apple',
        'E4CE8F': 'Apple',
        'F437B7': 'Apple',
        'FC253F': 'Apple',
        '0C7451': 'Apple',
        '14109F': 'Apple',
        '1C91E8': 'Apple',
        '24A074': 'Apple',
        '2C1F23': 'Apple',
        '34159E': 'Apple',
        '3C2EFF': 'Apple',
        '40A6D9': 'Apple',
        '44D884': 'Apple',
        '4C7C5F': 'Apple',
        '509EA7': 'Apple',
        '5C5948': 'Apple',
        '609217': 'Apple',
        '64200C': 'Apple',
        '68967B': 'Apple',
        '6C4D73': 'Apple',
        '6C709F': 'Apple',
        '6C96CF': 'Apple',
        '7014A6': 'Apple',
        '7073CB': 'Apple',
        '78A3E4': 'Apple',
        '7CC537': 'Apple',
        '80E650': 'Apple',
        '8489AD': 'Apple',
        '88E87F': 'Apple',
        '8C006D': 'Apple',
        '8C2DAA': 'Apple',
        '8CF8C5': 'Apple',
        '90840D': 'Apple',
        '98FE94': 'Apple',
        'A85C2C': 'Apple',
        'AC3C0B': 'Apple',
        'B065BD': 'Apple',
        'B8782E': 'Apple',
        'C0847A': 'Apple',
        'C42C03': 'Apple',
        'C8B5B7': 'Apple',
        'D0E140': 'Apple',
        'D4909C': 'Apple',
        'D8004D': 'Apple',
        'DC2B61': 'Apple',
        'E0B52D': 'Apple',
        'E80688': 'Apple',
        'E88D28': 'Apple',
        'F0DBE2': 'Apple',
        'F0DCE2': 'Apple',
        'F8D0BD': 'Apple',
        
        # Cisco
        '002241': 'Cisco',
        '485073': 'Cisco',
        '7C2EBD': 'Cisco',
        'DC2B2A': 'Cisco',
        '001120': 'Cisco',
        '0016C7': 'Cisco',
        '001D45': 'Cisco',
        '001E14': 'Cisco',
        '0021A0': 'Cisco',
        '0023EB': 'Cisco',
        '002618': 'Cisco',
        '0026CA': 'Cisco',
        '00D0BA': 'Cisco',
        '00D0BC': 'Cisco',
        '00D0FF': 'Cisco',
        '3C5EC4': 'Cisco',
        '5C5015': 'Cisco',
        '6C9C54': 'Cisco',
        '7081EB': 'Cisco',
        '88F031': 'Cisco',
        'A0F84C': 'Cisco',
        'B8BE76': 'Cisco',
        'C471FE': 'Cisco',
        'E4C7A2': 'Cisco',
        
        # Microsoft
        '000D3A': 'Microsoft',
        '0050F2': 'Microsoft',
        '001DD8': 'Microsoft',
        '7C1E52': 'Microsoft',
        '00155D': 'Microsoft',
        '0017FA': 'Microsoft',
        
        # Intel
        '8086F2': 'Intel',
        'F0189C': 'Intel',
        '001E67': 'Intel',
        '0024D7': 'Intel',
        '00D0B7': 'Intel',
        '3497F6': 'Intel',
        '7085C2': 'Intel',
        '94659C': 'Intel',
        'A0A8CD': 'Intel',
        'B4B686': 'Intel',
        'D0509': 'Intel',
        'E4028': 'Intel',
        
        # Samsung
        '001599': 'Samsung',  # Found in user's network
        '001632': 'Samsung',
        '0018AF': 'Samsung',
        '001D25': 'Samsung',
        '002566': 'Samsung',
        '0026FC': 'Samsung',
        '34BE00': 'Samsung',
        '38AA3C': 'Samsung',
        '3C5A37': 'Samsung',
        '40F520': 'Samsung',
        '44D6E1': 'Samsung',
        '5C0A5B': 'Samsung',
        '68A86D': 'Samsung',
        '78521A': 'Samsung',
        '7C6193': 'Samsung',
        '8C7712': 'Samsung',
        '9C02A0': 'Samsung',
        'A0821F': 'Samsung',
        'B4F0AB': 'Samsung',
        'C8F230': 'Samsung',
        'D0176A': 'Samsung',
        'D4E8B2': 'Samsung',
        'E0036B': 'Samsung',  # Found in user's network
        'E8508B': 'Samsung',
        'EC1F72': 'Samsung',
        
        # Google
        '2C3AE8': 'Google',
        '3C5A37': 'Google',
        '54605D': 'Google',
        '6C198F': 'Google',
        '74E5F9': 'Google',
        'A4F1E8': 'Google',
        'B4F0AB': 'Google',
        'D8C46A': 'Google',
        'F4F5E8': 'Google',
        
        # Amazon
        '1C697A': 'Amazon',
        '4C3275': 'Amazon',
        '00FC8B': 'Amazon',
        '44650D': 'Amazon',
        '747548': 'Amazon',
        '84D6D0': 'Amazon',
        'A002DC': 'Amazon',
        'F0D2F1': 'Amazon',
        
        # Xiaomi
        '0C5477': 'Xiaomi',
        '90324B': 'Xiaomi',
        '34CE00': 'Xiaomi',
        '3CBD3E': 'Xiaomi',  # Found in user's network
        '50EC50': 'Xiaomi',
        '64B473': 'Xiaomi',
        '78022': 'Xiaomi',
        '8CFABA': 'Xiaomi',
        'A0E45E': 'Xiaomi',
        'F8A45F': 'Xiaomi',
        
        # TP-Link
        '001FE2': 'TP-Link',
        '0025BC': 'TP-Link',
        '0C8268': 'TP-Link',
        '1C3BF3': 'TP-Link',
        '2C3033': 'TP-Link',
        '3C6AD2': 'TP-Link',  # Found in user's network
        '5065F3': 'TP-Link',
        '5C628B': 'TP-Link',
        '6C5AB0': 'TP-Link',
        '7C8BCA': 'TP-Link',
        '98DAC4': 'TP-Link',
        'A42BB0': 'TP-Link',
        'B0487A': 'TP-Link',
        'C06885': 'TP-Link',
        'D84489': 'TP-Link',  # Found in user's network
        'D8EB97': 'TP-Link',
        'E0D362': 'TP-Link',  # Found in user's network
        'E8DE27': 'TP-Link',
        'F4F26D': 'TP-Link',
        '1C61B4': 'TP-Link',
        '2C30AA': 'TP-Link',
        '30B49E': 'TP-Link',
        '4C5E0C': 'TP-Link',
        '5C8FE0': 'TP-Link',
        '6C5AB0': 'TP-Link',
        '7C8BCA': 'TP-Link',
        '8C21A1': 'TP-Link',
        '9C53CD': 'TP-Link',
        'A0F3C1': 'TP-Link',
        'B0BE76': 'TP-Link',
        'C46E1F': 'TP-Link',
        'D46E0E': 'TP-Link',
        'E4C346': 'TP-Link',
        'F4EC38': 'TP-Link',
        
        # D-Link
        '001195': 'D-Link',
        '0015E9': 'D-Link',
        '001CF0': 'D-Link',
        '001E58': 'D-Link',
        '0022B0': 'D-Link',
        '1C7EE5': 'D-Link',
        '28107B': 'D-Link',
        '3C1E04': 'D-Link',
        '5CD998': 'D-Link',
        '84C9B2': 'D-Link',
        'C0A0BB': 'D-Link',
        'CCB255': 'D-Link',
        
        # Hewlett Packard
        '3CD92B': 'HP',
        '001438': 'HP',
        '001CC4': 'HP',
        '001E0B': 'HP',
        '002264': 'HP',
        '00306E': 'HP',
        '1C98EC': 'HP',
        '2C27D7': 'HP',
        '3860F9': 'HP',
        '6C3BE5': 'HP',
        '9C8CDC': 'HP',
        'A0B3CC': 'HP',
        'B499BA': 'HP',
        'D48564': 'HP',
        
        # Dell
        '001C23': 'Dell',
        '0024E8': 'Dell',
        '00B0D0': 'Dell',
        '10BF48': 'Dell',
        '14FEB5': 'Dell',
        '18A996': 'Dell',
        '18FB7B': 'Dell',
        '2016B9': 'Dell',
        '34E6AD': 'Dell',
        '44A842': 'Dell',
        '5C260A': 'Dell',
        '84B153': 'Dell',
        '90B11C': 'Dell',
        'B8CA3A': 'Dell',
        'D4AE52': 'Dell',
        'F04DA2': 'Dell',
        
        # Huawei
        '001E10': 'Huawei',
        '002EC7': 'Huawei',
        '0C37DC': 'Huawei',
        '10C61F': 'Huawei',
        '1C1D67': 'Huawei',
        '28C63F': 'Huawei',
        '34CD12': 'Huawei',
        '3C1E04': 'Huawei',
        '4C549': 'Huawei',
        '5C:F9:6A': 'Huawei',
        '6C4A85': 'Huawei',
        '7C60AF': 'Huawei',
        '8C34FD': 'Huawei',
        'A4C168': 'Huawei',
        'C81479': 'Huawei',
        'D0C857': 'Huawei',
        'E0979': 'Huawei',
        
        # VMware / Virtualization
        '000C29': 'VMware',
        '005056': 'VMware',
        '001C42': 'Parallels',
        '080027': 'VirtualBox',
        '525400': 'QEMU/KVM',
        
        # Other Common
        '0001C8': 'Thomas-Krenn',
        '08002B': 'DEC',
        '100000': 'Private',
        '74C63B': 'AzureWave',
            'F43C3B': 'FN-LINK',
        }

    _OUI_VENDORS = vendors
    return vendors.get(oui, 'Unknown')


def get_network_interfaces():
    """Get list of network interfaces with their IP addresses"""
    interfaces = []

    # Try Python-native approach first (works in Flatpak without ip command)
    try:
        import fcntl
        import struct
        # Read interfaces from /proc/net/dev
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()[2:]  # Skip header lines
        for line in lines:
            iface = line.split(':')[0].strip()
            if iface == 'lo':
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ip = socket.inet_ntoa(fcntl.ioctl(
                    s.fileno(),
                    0x8915,  # SIOCGIFADDR
                    struct.pack('256s', iface.encode('utf-8')[:15])
                )[20:24])
                # Get subnet mask
                try:
                    netmask = socket.inet_ntoa(fcntl.ioctl(
                        s.fileno(),
                        0x891b,  # SIOCGIFNETMASK
                        struct.pack('256s', iface.encode('utf-8')[:15])
                    )[20:24])
                    prefix_len = bin(int.from_bytes(socket.inet_aton(netmask), 'big')).count('1')
                except OSError:
                    prefix_len = 24
                interfaces.append((iface, ip, prefix_len))
                s.close()
            except OSError:
                pass  # Interface might not have an IP
        if interfaces:
            return interfaces
    except Exception as e:
        print(f"Python-native interface detection failed: {e}")

    # Fallback to ip command
    try:
        result = subprocess.run(['ip', '-4', 'addr', 'show'], capture_output=True, text=True)

        current_iface = None
        for line in result.stdout.split('\n'):
            # Match interface line (e.g., "2: eth0: <BROADCAST...")
            if ': ' in line and not line.startswith(' '):
                parts = line.split(': ')
                if len(parts) >= 2:
                    current_iface = parts[1].split('@')[0]

            # Match inet line (e.g., "    inet 192.168.1.100/24...")
            elif 'inet ' in line and current_iface:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ip_with_mask = parts[1]
                    if '/' in ip_with_mask:
                        ip, prefix_len = ip_with_mask.split('/', 1)
                        prefix_len = int(prefix_len)
                    else:
                        ip = ip_with_mask
                        prefix_len = 24
                    if ip != '127.0.0.1':  # Skip loopback
                        interfaces.append((current_iface, ip, prefix_len))
    except Exception as e:
        print(f"Error getting interfaces: {e}")

    return interfaces
def run_tftp_server_standalone(host, port, directory):
    """Run TFTP server in standalone mode (for sudo execution)"""
    import signal

    server = TFTPServer(host=host, port=port, root_dir=directory)

    def signal_handler(signum, frame):
        print("\n[TFTP] Stopping server...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    if server.start():
        print(f"[TFTP] Server running on {host}:{port}")
        print(f"[TFTP] Directory: {directory}")
        print("[TFTP] Press Ctrl+C to stop")
        # Keep running until signal
        while server.is_running():
            import time
            time.sleep(1)
    else:
        print("[TFTP] Failed to start server")
        sys.exit(1)
