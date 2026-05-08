#!/usr/bin/env python3
"""
Aplica modificações de compatibilidade Windows no arquivo cetus.
"""

import re

FILE = '/home/benjamim/Documentos/opengrid/cetus'

with open(FILE, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. ConfigManager - APPDATA no Windows
old = '''class ConfigManager:
    """Manage application settings using XDG Base Directory specification"""

    def __init__(self) -> None:
        # Get XDG config directory (defaults to ~/.config)
        xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
        if not xdg_config_home:
            xdg_config_home = os.path.join(Path.home(), '.config')

        # Create cetus config directory
        self.config_dir = os.path.join(xdg_config_home, 'cetus')
        os.makedirs(self.config_dir, exist_ok=True)

        # Config file path
        self.config_file = os.path.join(self.config_dir, 'settings.json')'''

new = '''class ConfigManager:
    """Manage application settings using XDG Base Directory on Linux and APPDATA on Windows"""

    def __init__(self) -> None:
        if sys.platform == 'win32':
            appdata = os.environ.get('APPDATA')
            if not appdata:
                appdata = os.path.join(Path.home(), 'AppData', 'Roaming')
            self.config_dir = os.path.join(appdata, 'Cetus')
        else:
            # Get XDG config directory (defaults to ~/.config)
            xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
            if not xdg_config_home:
                xdg_config_home = os.path.join(Path.home(), '.config')
            self.config_dir = os.path.join(xdg_config_home, 'cetus')

        # Create cetus config directory
        os.makedirs(self.config_dir, exist_ok=True)

        # Config file path
        self.config_file = os.path.join(self.config_dir, 'settings.json')'''

text = text.replace(old, new)

# 2. get_network_interfaces - cross-platform
old = '''def get_network_interfaces():
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

    return interfaces'''

new = '''def get_network_interfaces():
    """Get list of network interfaces with their IP addresses (cross-platform)"""
    interfaces = []

    # On Windows, try psutil first (most reliable)
    if sys.platform == 'win32':
        try:
            import psutil
            for iface_name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        if ip == '127.0.0.1':
                            continue
                        netmask = addr.netmask
                        if netmask:
                            prefix_len = bin(int.from_bytes(socket.inet_aton(netmask), 'big')).count('1')
                        else:
                            prefix_len = 24
                        interfaces.append((iface_name, ip, prefix_len))
                        break  # Only take first IPv4 per interface
            if interfaces:
                return interfaces
        except Exception as e:
            print(f"psutil interface detection failed: {e}")
        # Fallback to ipconfig
        try:
            result = subprocess.run(['ipconfig'], capture_output=True, text=True)
            current_iface = None
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line and not line.startswith(' '):
                    current_iface = line.rstrip(':')
                elif 'IPv4 Address' in line and current_iface:
                    ip = line.split(':')[-1].strip()
                    if ip and ip != '127.0.0.1':
                        interfaces.append((current_iface, ip, 24))
        except Exception as e:
            print(f"ipconfig fallback failed: {e}")
        return interfaces

    # Linux path
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

    return interfaces'''

text = text.replace(old, new)

# 3. update_port_list - COM ports no Windows
old = '''    def update_port_list(self):
        """Update the list of available ports"""
        self.port.clear()

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
            self.status_led.setStyleSheet("color: #ff9800; font-size: 14px;")'''

new = '''    def update_port_list(self):
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
            self.status_led.setStyleSheet("color: #ff9800; font-size: 14px;")'''

text = text.replace(old, new)

# 4. _ping - argumentos Windows (ScanWorker)
old = '''    def _ping(self, ip):
        """
        for _ in range(2):
            if self._stop_flag:
                return None
            try:
                start = time.time()
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', str(self.timeout), ip],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=self.timeout + 2
                )
                latency = (time.time() - start) * 1000
                if result.returncode == 0:
                    return (ip, "Active", round(latency, 1), "ICMP")
                # If ping returned non-zero but quickly, wait a short
                # random backoff before retry to avoid colliding with
                # other threads pinging the same switch/broadcast domain.
                time.sleep(0.05)
            except (subprocess.TimeoutExpired, Exception):
                pass
        return None'''

new = '''    def _ping(self, ip):
        """
        for _ in range(2):
            if self._stop_flag:
                return None
            try:
                start = time.time()
                if sys.platform == 'win32':
                    # Windows: -n count, -w timeout_ms
                    timeout_ms = max(1, int(self.timeout * 1000))
                    result = subprocess.run(
                        ['ping', '-n', '1', '-w', str(timeout_ms), ip],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=self.timeout + 2
                    )
                else:
                    result = subprocess.run(
                        ['ping', '-c', '1', '-W', str(self.timeout), ip],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=self.timeout + 2
                    )
                latency = (time.time() - start) * 1000
                if result.returncode == 0:
                    return (ip, "Active", round(latency, 1), "ICMP")
                # If ping returned non-zero but quickly, wait a short
                # random backoff before retry to avoid colliding with
                # other threads pinging the same switch/broadcast domain.
                time.sleep(0.05)
            except (subprocess.TimeoutExpired, Exception):
                pass
        return None'''

text = text.replace(old, new)

# 5. PingWorker - argumentos Windows
old = '''                cmd = ['ping', '-c', '1', '-W', str(self.timeout), self.target]
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=self.timeout + 2, env=_env)'''

new = '''                if sys.platform == 'win32':
                    timeout_ms = max(1, int(self.timeout * 1000))
                    cmd = ['ping', '-n', '1', '-w', str(timeout_ms), self.target]
                else:
                    cmd = ['ping', '-c', '1', '-W', str(self.timeout), self.target]
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=self.timeout + 2, env=_env)'''

text = text.replace(old, new)

# 6. _SimplePingWorker - argumentos Windows
old = '''    def run(self):
        import subprocess as _sp
        try:
            proc = _sp.run(
                ['ping', '-c', '4', '-W', '2', self._host],
                capture_output=True, text=True, timeout=20
            )
            for line in proc.stdout.splitlines():'''

new = '''    def run(self):
        import subprocess as _sp
        try:
            if sys.platform == 'win32':
                proc = _sp.run(
                    ['ping', '-n', '4', '-w', '2000', self._host],
                    capture_output=True, text=True, timeout=20
                )
            else:
                proc = _sp.run(
                    ['ping', '-c', '4', '-W', '2', self._host],
                    capture_output=True, text=True, timeout=20
                )
            for line in proc.stdout.splitlines():'''

text = text.replace(old, new)

# 7. Áudio - QSoundEffect no Windows
old = '''    @staticmethod
    def _audio_worker_loop(q):
        """Single consumer: writes WAV to a temp file and plays it in full."""
        import subprocess, shutil, tempfile, os
        player = ('paplay' if shutil.which('paplay')
                  else 'aplay' if shutil.which('aplay')
                  else None)
        while True:
            wav = q.get()
            if wav is None:
                break
            if player is None:
                continue
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(
                        suffix='.wav', delete=False) as f:
                    f.write(wav)
                    tmp = f.name
                cmd = ([player, '--volume=65536', tmp]
                       if player == 'paplay' else [player, tmp])
                subprocess.run(cmd, stderr=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL)
            except Exception:
                pass
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)'''

new = '''    @staticmethod
    def _audio_worker_loop(q):
        """Single consumer: writes WAV to a temp file and plays it in full."""
        import shutil, tempfile, os
        if sys.platform == 'win32':
            from PyQt6.QtMultimedia import QSoundEffect
            from PyQt6.QtCore import QUrl
            player = 'qt'
        else:
            player = ('paplay' if shutil.which('paplay')
                      else 'aplay' if shutil.which('aplay')
                      else None)
        while True:
            wav = q.get()
            if wav is None:
                break
            if player is None:
                continue
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(
                        suffix='.wav', delete=False) as f:
                    f.write(wav)
                    tmp = f.name
                if player == 'qt':
                    se = QSoundEffect()
                    se.setSource(QUrl.fromLocalFile(tmp))
                    se.setVolume(1.0)
                    se.play()
                    # Wait for playback to finish (approximate)
                    import time as _time
                    _time.sleep(0.5)
                else:
                    cmd = ([player, '--volume=65536', tmp]
                           if player == 'paplay' else [player, tmp])
                    subprocess.run(cmd, stderr=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL)
            except Exception:
                pass
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)'''

text = text.replace(old, new)

# 8. MTR error message - Windows
old = '''                if 'permission' in low or 'not permitted' in low:
                    self.mtr_error.emit(
                        "MTR requires elevated privileges for ICMP.\\n\\n"
                        "Run Cetus with: sudo python3 cetus\\n"
                        "Or install mtr with setuid bit: sudo chmod u+s /usr/bin/mtr"
                    )'''

new = '''                if 'permission' in low or 'not permitted' in low:
                    if sys.platform == 'win32':
                        self.mtr_error.emit(
                            "MTR requires elevated privileges for ICMP on Windows.\\n\\n"
                            "Run Cetus as Administrator."
                        )
                    else:
                        self.mtr_error.emit(
                            "MTR requires elevated privileges for ICMP.\\n\\n"
                            "Run Cetus with: sudo python3 cetus\\n"
                            "Or install mtr with setuid bit: sudo chmod u+s /usr/bin/mtr"
                        )'''

text = text.replace(old, new)

# 9. ARP scan - desabilitar no Windows
old = '''    def _arp_scan(self, ip):
        """Discover host using ARP (Layer 2) via arping"""
        try:
            cmd = ['arping', '-c', '1', '-w', str(self.timeout), ip]
            stdin_data = None
            if self.sudo_password:
                cmd = ['sudo', '-S'] + cmd
                stdin_data = self.sudo_password + '\n'
            result = subprocess.run(
                cmd,
                input=stdin_data,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=self.timeout + 2, text=True
            )
            if result.returncode == 0:'''

new = '''    def _arp_scan(self, ip):
        """Discover host using ARP (Layer 2) via arping"""
        if sys.platform == 'win32':
            # ARP ping is not natively supported on Windows via arping
            return None
        try:
            cmd = ['arping', '-c', '1', '-w', str(self.timeout), ip]
            stdin_data = None
            if self.sudo_password:
                cmd = ['sudo', '-S'] + cmd
                stdin_data = self.sudo_password + '\n'
            result = subprocess.run(
                cmd,
                input=stdin_data,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=self.timeout + 2, text=True
            )
            if result.returncode == 0:'''

text = text.replace(old, new)

# 10. get_icon_path - PyInstaller bundle (primeira ocorrência)
old = '''        # Check for Flatpak
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
        return None'''

new = '''        # Check for PyInstaller / PyOxidizer / cx_Freeze bundle
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
        return None'''

text = text.replace(old, new)

# 11. get_icon_path segunda ocorrência (ícones)
old2 = '''        # Check for Flatpak
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
        return None'''

new2 = '''        # Check for PyInstaller / PyOxidizer / cx_Freeze bundle
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
        return None'''

text = text.replace(old2, new2)

# 12. _launch_vnc - Windows
old = '''    def _launch_vnc(self, host, port, password):
        """Launch a VNC viewer.
        Priority: vncviewer -> xtigervncviewer (both run transparently via XWayland).
        """
        import shutil, subprocess
        for viewer in ('vncviewer', 'xtigervncviewer'):
            if shutil.which(viewer):
                break
        else:
            QMessageBox.critical(self, "VNC Error",
                "No VNC viewer found.\\n\\n"
                "Install TigerVNC:\\n  sudo apt install tigervnc-viewer")
            return
        subprocess.Popen([viewer, f'{host}::{port}'])'''

new = '''    def _launch_vnc(self, host, port, password):
        """Launch a VNC viewer (cross-platform)."""
        import shutil, subprocess
        if sys.platform == 'win32':
            viewers = ('vncviewer.exe', 'tvnviewer.exe', 'VNC-Viewer.exe')
            for viewer in viewers:
                if shutil.which(viewer):
                    subprocess.Popen([viewer, f'{host}::{port}'])
                    return
            QMessageBox.critical(self, "VNC Error",
                "No VNC viewer found on Windows.\\n\\n"
                "Install RealVNC, TightVNC, or TigerVNC for Windows.")
            return
        # Linux
        for viewer in ('vncviewer', 'xtigervncviewer'):
            if shutil.which(viewer):
                break
        else:
            QMessageBox.critical(self, "VNC Error",
                "No VNC viewer found.\\n\\n"
                "Install TigerVNC:\\n  sudo apt install tigervnc-viewer")
            return
        subprocess.Popen([viewer, f'{host}::{port}'])'''

text = text.replace(old, new)

# 13. _launch_rdp - Windows
old = '''    def _launch_rdp(self, host, port, username, password):
        """Launch an RDP client with connecting feedback and error reporting.
        Search order: sdl-freerdp3 -> xfreerdp3 / wlfreerdp3 -> wlfreerdp -> xfreerdp.
        """
        import shutil, subprocess
        for client in ('sdl-freerdp3', 'xfreerdp3', 'wlfreerdp3', 'wlfreerdp', 'xfreerdp'):
            if shutil.which(client):
                break
        else:
            QMessageBox.critical(self, "RDP Error",
                "No RDP client found.\\n\\n"
                "Arch Linux:\\n"
                "  sudo pacman -S freerdp\\n\\n"
                "Debian / Ubuntu (Wayland-native):\\n"
                "  sudo apt install freerdp3-wayland\\n"
                "Debian / Ubuntu (X11):\\n"
                "  sudo apt install freerdp2-x11")
            return

        tls_arg = '/tls:seclevel:0' if client.endswith('3') else '/tls-seclevel:0'
        resolution = self._get_rdp_resolution()
        depth = int(self.rdp_color_depth.currentText().split()[0])  # "32 bit" -> 32
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
            args.append(f'/p:{password}')'''

new = '''    def _launch_rdp(self, host, port, username, password):
        """Launch an RDP client with connecting feedback and error reporting (cross-platform)."""
        import shutil, subprocess
        if sys.platform == 'win32':
            # Windows native RDP client
            if shutil.which('mstsc.exe'):
                # Build .rdp file for mstsc
                import tempfile
                rdp_content = f"full address:s:{host}:{port}\\n"
                if username:
                    rdp_content += f"username:s:{username}\\n"
                rdp_content += "prompt for credentials:i:0\\n"
                with tempfile.NamedTemporaryFile(suffix='.rdp', delete=False, mode='w') as f:
                    f.write(rdp_content)
                    rdp_file = f.name
                subprocess.Popen(['mstsc.exe', rdp_file])
                return
            QMessageBox.critical(self, "RDP Error",
                "mstsc.exe not found. Windows RDP client should be available by default.")
            return
        # Linux
        for client in ('sdl-freerdp3', 'xfreerdp3', 'wlfreerdp3', 'wlfreerdp', 'xfreerdp'):
            if shutil.which(client):
                break
        else:
            QMessageBox.critical(self, "RDP Error",
                "No RDP client found.\\n\\n"
                "Arch Linux:\\n"
                "  sudo pacman -S freerdp\\n\\n"
                "Debian / Ubuntu (Wayland-native):\\n"
                "  sudo apt install freerdp3-wayland\\n"
                "Debian / Ubuntu (X11):\\n"
                "  sudo apt install freerdp2-x11")
            return

        tls_arg = '/tls:seclevel:0' if client.endswith('3') else '/tls-seclevel:0'
        resolution = self._get_rdp_resolution()
        depth = int(self.rdp_color_depth.currentText().split()[0])  # "32 bit" -> 32
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
            args.append(f'/p:{password}')'''

text = text.replace(old, new)

# 14. _ft_ssh_srv_check_status/toggle - Windows
old = '''    def _ft_ssh_srv_check_status(self):
        import subprocess
        try:
            r = subprocess.run(['systemctl', 'is-active', 'sshd'], capture_output=True, text=True, timeout=5)
            status = r.stdout.strip()
            color = '#4CAF50' if status == 'active' else '#f44336'
            self._ssh_srv_status_lbl.setText(f"Status: <span style='color:{color};font-weight:bold'>{status}</span>")
            if self._ft_mode == 'Server' and self._ft_protocol == 'SSH':
                self._ft_set_action_btn(status == 'active', 'SSH')
        except Exception as e:
            self._ssh_srv_status_lbl.setText(f"Status: error - {e}")

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
            QMessageBox.warning(self, "SSH Server", str(e))'''

new = '''    def _ft_ssh_srv_check_status(self):
        import subprocess
        try:
            if sys.platform == 'win32':
                r = subprocess.run(['sc', 'query', 'sshd'], capture_output=True, text=True, timeout=5)
                running = 'RUNNING' in r.stdout
                status = 'active' if running else 'inactive'
            else:
                r = subprocess.run(['systemctl', 'is-active', 'sshd'], capture_output=True, text=True, timeout=5)
                status = r.stdout.strip()
            color = '#4CAF50' if status == 'active' else '#f44336'
            self._ssh_srv_status_lbl.setText(f"Status: <span style='color:{color};font-weight:bold'>{status}</span>")
            if self._ft_mode == 'Server' and self._ft_protocol == 'SSH':
                self._ft_set_action_btn(status == 'active', 'SSH')
        except Exception as e:
            self._ssh_srv_status_lbl.setText(f"Status: error - {e}")

    def _ft_ssh_srv_toggle(self):
        import subprocess, time
        try:
            if sys.platform == 'win32':
                r = subprocess.run(['sc', 'query', 'sshd'], capture_output=True, text=True, timeout=5)
                running = 'RUNNING' in r.stdout
                action = 'stop' if running else 'start'
                self._ft_log_append(f"{action.capitalize()}ing sshd service...")
                res = subprocess.run(['sc', action, 'sshd'], capture_output=True, text=True, timeout=15)
                if res.returncode != 0:
                    err = (res.stderr or res.stdout or "sc returned error").strip()
                    self._ft_log_append(f"ERROR {action} sshd: {err}")
                    QMessageBox.warning(self, "SSH Server", f"Failed to {action} SSH service:\n{err}"); return
                self._ft_set_action_btn(not running, 'SSH')
                self._ft_log_append(f"sshd {action}ped.")
            else:
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
            QMessageBox.warning(self, "SSH Server", str(e))'''

text = text.replace(old, new)

# 15. SMB check status - Windows
old = '''    # -- SMB Server (systemctl) -----------------------------------------------
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
        self._ft_log_append("SMB: service not found (tried smb, smbd, samba, nmb)")'''

new = '''    # -- SMB Server (systemctl) -----------------------------------------------
    def _ft_smb_srv_check_status(self):
        import subprocess
        if sys.platform == 'win32':
            self._smb_srv_status_lbl.setText("Status: SMB sharing is managed natively by Windows")
            return
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
        self._ft_log_append("SMB: service not found (tried smb, smbd, samba, nmb)")'''

text = text.replace(old, new)

# 16. TFTP toggle - sem sudo no Windows
old = '''            directory = self.tftp_directory.text()
            if not os.path.isdir(directory):
                QMessageBox.warning(self, "Warning", "Invalid TFTP directory")
                return

            password, ok = QInputDialog.getText(
                self, "Sudo Password Required",
                "TFTP port 69 requires root privileges.\\nPlease enter your sudo password:",
                QLineEdit.EchoMode.Password
            )
            if not ok or not password:
                return

            # Build command to run TFTP server with sudo
            script_path = os.path.abspath(__file__)
            cmd = ['sudo', '-S', sys.executable, script_path, '--tftp-server', ip, '69', directory]'''

new = '''            directory = self.tftp_directory.text()
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
                    "TFTP port 69 requires root privileges.\\nPlease enter your sudo password:",
                    QLineEdit.EchoMode.Password
                )
                if not ok or not password:
                    return
                cmd = ['sudo', '-S', sys.executable, script_path, '--tftp-server', ip, '69', directory]'''

text = text.replace(old, new)

# 17. TFTP envio de senha
old = '''                self.tftp_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=None,  # Inherit parent's stdout (terminal)
                    stderr=None,  # Inherit parent's stderr (terminal)
                    text=False
                )
                # Send password
                self.tftp_process.stdin.write((password + '\\n').encode())
                self.tftp_process.stdin.flush()
                self.tftp_process.stdin.close()  # Close stdin after sending password
                password = None  # Clear from memory'''

new = '''                self.tftp_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=None,  # Inherit parent's stdout (terminal)
                    stderr=None,  # Inherit parent's stderr (terminal)
                    text=False
                )
                # Send password (Linux only)
                if sys.platform != 'win32' and 'password' in locals() and password:
                    self.tftp_process.stdin.write((password + '\\n').encode())
                    self.tftp_process.stdin.flush()
                    self.tftp_process.stdin.close()  # Close stdin after sending password
                    password = None  # Clear from memory'''

text = text.replace(old, new)

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(text)

print("Modificacoes aplicadas com sucesso!")
