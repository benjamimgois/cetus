"""Background workers for Cetus."""

import csv
import ipaddress
import json
import math
import os
import platform
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    paramiko = None
    SSH_AVAILABLE = False

try:
    import telnetlib
    TELNET_AVAILABLE = True
except ImportError:
    telnetlib = None
    TELNET_AVAILABLE = False

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, QSize, QPointF, QRectF
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from cetuslib.utils import (
    TFTPHandler, TFTPServer, get_network_interfaces, _get_mac_vendor
)


__all__ = [
    'ScanWorker',
    'ConnectionWorker',
    'TracerouteWorker',
    'GeoFlagWorker',
    'NmapDiscoverWorker',
    'MtrWorker',
    'PingWorker',
    'PingTCPWorker',
    'Iperf3DiscoverWorker',
    'Iperf3Worker',
    'SpeedTestWorker',
    '_SimplePingWorker',
    'DeviceImageWorker',
    'FileConnectWorker',
    'FileListWorker',
    'FileTransferWorker',
    'TcpdumpWorker',
    'DnsResolverWorker',
    'WiFiScanWorker',
]


class ScanWorker(QThread):
    """Worker thread for network host discovery via ICMP, TCP, UDP or ARP"""

    host_found = pyqtSignal(str, str, float, str, str, str, str)  # ip, status, latency_ms, method, mac, vendor, hostname
    scan_progress = pyqtSignal(int)  # percentage
    scan_finished = pyqtSignal(int)  # total hosts found
    scan_error = pyqtSignal(str)

    def __init__(self, targets, method, ports=None, timeout=1, max_threads=50, sudo_password=None, dns_lookup=False):
        super().__init__()
        self.targets = targets  # list of IP strings
        self.method = method    # 'ICMP', 'TCP', 'UDP', 'ARP'
        self.ports = ports or []
        self.timeout = timeout
        self.max_threads = max_threads
        self.sudo_password = sudo_password
        self.dns_lookup = dns_lookup
        self._stop_flag = False
        self._found_count = 0

    def stop(self):
        self._stop_flag = True

    def run(self):
        total = len(self.targets)
        if total == 0:
            self.scan_error.emit("No targets to scan")
            return
        completed = 0
        try:
            with ThreadPoolExecutor(max_workers=self.max_threads) as pool:
                futures = {}
                for ip in self.targets:
                    if self._stop_flag:
                        break
                    futures[pool.submit(self._scan_host, ip)] = ip
                for future in as_completed(futures):
                    if self._stop_flag:
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    completed += 1
                    self.scan_progress.emit(int(completed * 100 / total))
                    result = future.result()
                    if result:
                        ip, status, latency, method = result[:4]
                        self._found_count += 1
                        # For ARP scan, MAC comes from arping output
                        if method == 'ARP' and len(result) > 4:
                            mac = result[4]
                            vendor = self._get_mac_vendor(mac) if mac else "Unknown"
                        else:
                            mac, vendor = self._get_mac_and_vendor(ip)
                        hostname = self._resolve_hostname(ip) if self.dns_lookup else ""
                        self.host_found.emit(ip, status, latency, method, mac, vendor, hostname)
        except Exception as e:
            self.scan_error.emit(str(e))
        self.scan_finished.emit(self._found_count)

    def _scan_host(self, ip):
        if self._stop_flag:
            return None
        if self.method == 'ICMP':
            return self._ping(ip)
        elif self.method == 'TCP':
            return self._tcp_scan(ip)
        elif self.method == 'UDP':
            return self._udp_scan(ip)
        elif self.method == 'ARP':
            return self._arp_scan(ip)
        return None

    def _ping(self, ip):
        """Ping a host with retry to reduce false negatives from packet loss.

        Sends up to 2 ICMP echo requests per host.  Many switches and hosts
        silently drop a small percentage of ICMP traffic under load, so a
        single lost packet should not be reported as "down".
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
        return None

    def _tcp_scan(self, ip):
        open_ports = []
        best_latency = None
        for port in self.ports:
            if self._stop_flag:
                return None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                start = time.time()
                err = sock.connect_ex((ip, port))
                latency = (time.time() - start) * 1000
                sock.close()
                if err == 0:
                    open_ports.append(str(port))
                    if best_latency is None or latency < best_latency:
                        best_latency = latency
            except (socket.error, OSError):
                pass
        if open_ports:
            status = f"TCP: {','.join(open_ports)}"
            return (ip, status, round(best_latency, 1), "TCP")
        return None

    def _udp_scan(self, ip):
        responded_ports = []
        best_latency = None
        for port in self.ports:
            if self._stop_flag:
                return None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(self.timeout)
                start = time.time()
                sock.sendto(b'\x00', (ip, port))
                try:
                    sock.recvfrom(1024)
                    latency = (time.time() - start) * 1000
                    responded_ports.append(str(port))
                    if best_latency is None or latency < best_latency:
                        best_latency = latency
                except socket.timeout:
                    # No ICMP unreachable = port might be open (filtered)
                    latency = (time.time() - start) * 1000
                    responded_ports.append(f"{port}?")
                    if best_latency is None or latency < best_latency:
                        best_latency = latency
                sock.close()
            except (socket.error, OSError):
                pass
        if responded_ports:
            status = f"UDP: {','.join(responded_ports)}"
            return (ip, status, round(best_latency or 0, 1), "UDP")
        return None

    def _arp_scan(self, ip):
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
            if result.returncode == 0:
                # Parse: "Unicast reply from 192.168.1.1 [AA:BB:CC:DD:EE:FF]  1.234ms"
                for line in result.stdout.splitlines():
                    if 'reply from' in line.lower() or 'unicast' in line.lower():
                        mac = ""
                        latency = 0.0
                        # Extract MAC from [XX:XX:XX:XX:XX:XX]
                        bracket_start = line.find('[')
                        bracket_end = line.find(']')
                        if bracket_start != -1 and bracket_end != -1:
                            mac = line[bracket_start + 1:bracket_end].upper()
                        # Extract latency (e.g. "1.234ms")
                        parts = line.split()
                        for part in parts:
                            if part.lower().endswith('ms'):
                                try:
                                    latency = float(part[:-2])
                                except ValueError:
                                    pass
                        return (ip, "Active", round(latency, 1), "ARP", mac)
        except FileNotFoundError:
            # arping not installed
            return None
        except (subprocess.TimeoutExpired, Exception):
            pass
        return None

    def _resolve_hostname(self, ip):
        """Resolve IP address to hostname via reverse DNS lookup"""
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except (socket.herror, socket.gaierror, OSError):
            return ""

    def _get_mac_address(self, ip):
        """Get MAC address for an IP using ARP"""
        # Small delay to let ARP cache update after the scan
        import time
        time.sleep(0.05)
        
        try:
            # Use 'ip neigh' command
            result = subprocess.run(
                ['ip', 'neigh', 'show', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2,
                text=True
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                # Parse output like: "192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
                parts = output.split()
                if 'lladdr' in parts:
                    idx = parts.index('lladdr')
                    if idx + 1 < len(parts):
                        mac = parts[idx + 1]
                        # Validate MAC format (should be 17 chars with colons)
                        if ':' in mac and len(mac) == 17:
                            # Additional validation: check if it's a valid MAC
                            try:
                                octets = mac.split(':')
                                if len(octets) == 6 and all(len(o) == 2 for o in octets):
                                    return mac.upper()
                            except:
                                pass
        except (subprocess.TimeoutExpired, Exception):
            pass
        
        return ""

    def _get_mac_vendor(self, mac):
        return _get_mac_vendor(mac)

    def _get_mac_and_vendor(self, ip):
        """Get MAC address and vendor for an IP"""
        mac = self._get_mac_address(ip)
        if mac:
            vendor = self._get_mac_vendor(mac)
            return mac, vendor
        return "", "Unknown"



class ConnectionWorker(QThread):
    """Worker thread for establishing SSH/Telnet connections without blocking UI"""
    
    connection_ready = pyqtSignal(str, object, object, object)  # type, client, channel/None, host_info
    connection_failed = pyqtSignal(str)  # Emits error message on failure
    
    def __init__(self, connection_type, host, port, username, password=None, key_path=None):
        super().__init__()
        self.connection_type = connection_type  # 'ssh' or 'telnet'
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
    
    def run(self):
        """Execute connection in background thread"""
        try:
            if self.connection_type == 'telnet':
                # Establish Telnet connection
                if not TELNET_AVAILABLE:
                    self.connection_failed.emit("telnetlib is not available.\nInstall with: pip install standard-telnetlib")
                    return
                telnet_client = telnetlib.Telnet(self.host, int(self.port), timeout=10)
                self.connection_ready.emit('telnet', telnet_client, None, 
                                          (self.host, self.port, self.username))
            else:  # SSH
                # Establish SSH connection
                if not SSH_AVAILABLE:
                    self.connection_failed.emit("paramiko library is not installed")
                    return
                
                import paramiko
                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Connect with password or key
                if self.key_path:
                    ssh_client.connect(
                        self.host, int(self.port), self.username,
                        key_filename=self.key_path,
                        timeout=10, banner_timeout=15, auth_timeout=15,
                        allow_agent=False, look_for_keys=False
                    )
                else:
                    ssh_client.connect(
                        self.host, int(self.port), self.username,
                        password=self.password,
                        timeout=10, banner_timeout=15, auth_timeout=15,
                        allow_agent=False, look_for_keys=False
                    )
                
                # Open interactive shell with proper terminal type.
                # Use low-level API so we can inject COLORTERM between the
                # PTY request and the shell request.  Many servers override
                # TERM in /etc/profile; sending TERM via AcceptEnv env request
                # (which fires AFTER profile scripts on some sshd configs) is
                # more reliable than the PTY term type alone.
                transport = ssh_client.get_transport()
                channel = transport.open_session()
                # Use a placeholder size — the main thread will resize_pty to
                # the real terminal dimensions and invoke_shell() BEFORE the
                # read loop starts, so the MOTD arrives at the correct size.
                channel.get_pty(term='xterm', width=220, height=50)
                try:
                    channel.set_environment_variable('TERM', 'xterm')
                    channel.set_environment_variable('COLORTERM', 'truecolor')
                except Exception:
                    pass
                # Do NOT invoke_shell() here — deferred to on_connection_ready
                # so the shell starts after the PTY is resized correctly.
                channel.settimeout(0.1)

                self.connection_ready.emit('ssh', ssh_client, channel,
                                          (self.host, self.port, self.username))
        except Exception as e:
            self.connection_failed.emit(str(e))



class TracerouteWorker(QThread):
    """Worker thread for traceroute operations"""

    hop_found = pyqtSignal(int, str, str, float, float)  # hop_num, ip, hostname, latency_ms, stdev_ms
    route_progress = pyqtSignal(int)               # percentage (0-100)
    route_finished = pyqtSignal(int, str)          # total_hops, target_ip
    route_error = pyqtSignal(str)                  # error_message

    def __init__(self, target_host, max_hops=30, timeout=5, dns_lookup=True, method='ICMP', port=None):
        super().__init__()
        self.target_host = target_host
        self.max_hops = max_hops
        self.timeout = timeout
        self.dns_lookup = dns_lookup
        self.method = method  # 'ICMP', 'TCP', or 'UDP'
        self.port = port      # Target port for TCP/UDP
        self._stop_flag = False
        self._hops_count = 0

    def stop(self):
        """Signal graceful shutdown"""
        self._stop_flag = True

    def run(self):
        """Execute traceroute in background thread"""
        if not self.target_host:
            self.route_error.emit("No target host specified")
            return

        # Detect OS and set appropriate command
        system = platform.system()
        if system == "Windows":
            # Windows doesn't have built-in TCP/UDP traceroute
            if self.method in ('TCP', 'UDP'):
                self.route_error.emit(f"{self.method} traceroute not natively supported on Windows.\n\n"
                                     f"Please install tcptraceroute or use ICMP method.")
                return
            cmd = ['tracert']
            if not self.dns_lookup:
                cmd.append('-d')
            cmd.extend(['-h', str(self.max_hops), '-w', str(self.timeout * 1000), self.target_host])
        else:  # Linux/Unix
            cmd = ['traceroute']

            # Add method-specific flags
            if self.method == 'TCP':
                cmd.append('-T')  # TCP SYN for probes
                if self.port:
                    cmd.extend(['-p', str(self.port)])
            elif self.method == 'UDP':
                cmd.append('-U')  # UDP for probes (some systems use this, others default to UDP)
                if self.port:
                    cmd.extend(['-p', str(self.port)])
            elif self.method == 'ICMP':
                cmd.append('-I')  # ICMP ECHO for probes (explicit)

            # Common flags
            if not self.dns_lookup:
                cmd.append('-n')
            cmd.extend(['-m', str(self.max_hops), '-w', str(self.timeout), '-q', '3', self.target_host])

        try:
            # Start traceroute process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )

            # Read output line by line in real-time
            for line in process.stdout:
                if self._stop_flag:
                    process.terminate()
                    break

                # Parse the line
                hop_data = self._parse_traceroute_line(line, system)
                if hop_data:
                    hop_num, ip, hostname, latency, stdev = hop_data
                    self._hops_count += 1

                    # Emit hop found signal
                    self.hop_found.emit(hop_num, ip, hostname, latency, stdev)

                    # Emit progress
                    progress = min(int((hop_num / self.max_hops) * 100), 99)
                    self.route_progress.emit(progress)

            # Wait for process to complete
            process.wait()

            # Check for errors
            stderr_output = process.stderr.read()
            if process.returncode != 0 and stderr_output:
                # Check for common permission errors
                if any(msg in stderr_output for msg in (
                        'Permission denied', 'Operation not permitted',
                        'not permitted', 'privileges',
                        'Operação não permitida', 'Permissão negada')):
                    if self.method in ('TCP', 'UDP'):
                        self.route_error.emit(f"{self.method} traceroute requires root privileges.\n\n"
                                             f"Run Cetus with: sudo python3 cetus\n"
                                             f"Or use ICMP method instead.")
                    else:
                        self.route_error.emit(f"Traceroute requires root privileges.\n\n"
                                             f"Run Cetus with: sudo python3 cetus")
                else:
                    self.route_error.emit(f"Traceroute error: {stderr_output}")
            else:
                self.route_finished.emit(self._hops_count, self.target_host)

        except FileNotFoundError:
            if system == "Windows":
                self.route_error.emit("tracert command not found. Please ensure Windows is properly configured.")
            else:
                self.route_error.emit("traceroute command not found.\n\nInstall with: sudo apt install traceroute")
        except PermissionError:
            if self.method in ('TCP', 'UDP'):
                self.route_error.emit(f"{self.method} traceroute requires root privileges.\n\n"
                                     f"Run Cetus with: sudo python3 cetus\n"
                                     f"Or use ICMP method instead.")
            else:
                self.route_error.emit("Traceroute requires root privileges.\n\nRun Cetus with: sudo python3 cetus")
        except Exception as e:
            self.route_error.emit(f"Error: {str(e)}")

    def _parse_traceroute_line(self, line, system):
        """Parse a single line of traceroute output"""
        if self._stop_flag:
            return None

        line = line.strip()
        if not line:
            return None

        try:
            if system == "Windows":
                # Windows tracert format: " 1    <1 ms    <1 ms    <1 ms  192.168.1.1"
                # or: " 1     *        *        *     Request timed out."
                match = re.match(r'^\s*(\d+)\s+(?:(\d+|<\d+)\s+ms\s+(?:\d+|<\d+)\s+ms\s+(?:\d+|<\d+)\s+ms\s+)?(.+)$', line)
                if match:
                    hop_num = int(match.group(1))
                    latency_str = match.group(2)
                    target = match.group(3).strip()

                    # Check for timeout
                    if '*' in line or 'Request timed out' in line:
                        return (hop_num, "*", "*", 0.0, 0.0)

                    # Parse latency
                    if latency_str:
                        if '<' in latency_str:
                            latency = 1.0
                        else:
                            latency = float(latency_str)
                    else:
                        latency = 0.0

                    # Parse IP/hostname
                    # Format can be: "hostname [ip]" or just "ip"
                    ip_match = re.search(r'\[?([\d.]+)\]?', target)
                    if ip_match:
                        ip = ip_match.group(1)
                        hostname = target.split('[')[0].strip() if '[' in target else ip
                    else:
                        ip = target
                        hostname = target

                    return (hop_num, ip, hostname, latency, 0.0)
            else:
                # Linux traceroute format:
                # " 1  192.168.1.1 (192.168.1.1)  1.234 ms  1.456 ms  1.789 ms"
                # or: " 1  gateway.local (192.168.1.1)  1.234 ms  1.456 ms  1.789 ms"
                # or: " 1  * * *"

                # Check for timeout line
                if re.match(r'^\s*\d+\s+\*\s+\*\s+\*', line):
                    match = re.match(r'^\s*(\d+)', line)
                    if match:
                        hop_num = int(match.group(1))
                        return (hop_num, "*", "*", 0.0)
                    return None

                # Normal hop with response
                match = re.match(r'^\s*(\d+)\s+([^\s(]+)?\s*(?:\(([^)]+)\))?\s+([\d.]+)\s+ms', line)
                if match:
                    hop_num = int(match.group(1))
                    hostname = match.group(2) if match.group(2) else ""
                    ip = match.group(3) if match.group(3) else match.group(2)
                    latency_str = match.group(4)

                    # Calculate average and stdev from all probe values in line
                    latencies = [float(l) for l in re.findall(r'([\d.]+)\s+ms', line)]
                    if latencies:
                        latency = sum(latencies) / len(latencies)
                        if len(latencies) >= 2:
                            avg = latency
                            stdev = math.sqrt(sum((v - avg) ** 2 for v in latencies) / len(latencies))
                        else:
                            stdev = 0.0
                    else:
                        latency = float(latency_str)
                        stdev = 0.0

                    # If no hostname, use IP
                    if not hostname or hostname == ip:
                        hostname = ip

                    return (hop_num, ip, hostname, latency, stdev)

        except Exception as e:
            # Silently ignore parsing errors for individual lines
            pass

        return None


import queue


class GeoFlagWorker(QThread):
    """
    Background worker that fetches country codes for IPs sequentially
    using a queue, resolving them into Emoji flags for the UI.
    ip-api.com allows 45 requests per minute, so we pace requests.
    """
    flag_resolved = pyqtSignal(str, str, str, object, object, bool) # ip, cc, flag, hop_num, row_idx, is_mtr

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = queue.Queue()
        self.cache = {}
        self._running = True

    def run(self):
        import urllib.request
        import json
        import time

        while self._running:
            try:
                task = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            ip, is_mtr, hop_num, row_idx = task
            if ip in self.cache:
                cc, flag = self.cache[ip]
                self.flag_resolved.emit(ip, cc, flag, hop_num, row_idx, is_mtr)
                self.queue.task_done()
                continue
            
            if ip == "*" or ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("127.") or ip.startswith("100.") or ip.startswith("172."):
                cc, flag = "LAN", "🏠"
                self.cache[ip] = (cc, flag)
                self.flag_resolved.emit(ip, cc, flag, hop_num, row_idx, is_mtr)
                self.queue.task_done()
                continue

            try:
                url = f"http://ip-api.com/json/{ip}?fields=status,countryCode"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 Cetus'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode('utf-8'))
                
                if data.get("status") == "success" and data.get("countryCode"):
                    cc = data.get("countryCode")
                    # Convert 2-letter Country Code to Emoji Flag
                    flag = chr(ord(cc[0]) + 127397) + chr(ord(cc[1]) + 127397)
                else:
                    cc, flag = "?", "❓"
            except Exception:
                cc, flag = "?", "❓"

            self.cache[ip] = (cc, flag)
            self.flag_resolved.emit(ip, cc, flag, hop_num, row_idx, is_mtr)
            self.queue.task_done()
            
            # Rate limit respect (45 req/min ≈ 1.33s per req)
            time.sleep(1.4)

    def stop(self):
        self._running = False
        self.wait()
        
    def enqueue(self, ip, is_mtr, hop_num, row_idx):
        self.queue.put((ip, is_mtr, hop_num, row_idx))



class NmapDiscoverWorker(QThread):
    """
    Nmap-based device fingerprinting for CVE lookup.

    Phase 1 — nmap -sV (no root needed): detects open services with versions.
    Phase 2 — nmap -O  (root needed): OS fingerprinting.
      • Tries passwordless sudo first (sudo -n).
      • If a password is required, emits sudo_required and waits for provide_password()
        or cancel_sudo() to be called from the main thread.

    Signals:
      device_info(vendor, model, version, raw)  — primary result (OS or top service)
      services_found(list)                       — all open services
      discover_error(msg)                        — unrecoverable failure
      discover_status(msg)                       — progress text
      sudo_required()                            — OS detection needs a root password
    """
    device_info     = pyqtSignal(str, str, str, str)
    services_found  = pyqtSignal(list)
    discover_error  = pyqtSignal(str)
    discover_status = pyqtSignal(str)
    sudo_required   = pyqtSignal()

    def __init__(self, host, snmp_community='', parent=None):
        import threading
        super().__init__(parent)
        self.host            = host.strip()
        self.snmp_community  = snmp_community.strip()
        self._password       = None
        self._password_event = threading.Event()

    def provide_password(self, password):
        """Called from main thread with the sudo password."""
        self._password = password
        self._password_event.set()

    def cancel_sudo(self):
        """Called from main thread to skip OS detection."""
        self._password = None
        self._password_event.set()

    # ════════════════════════════════════════════════════════════════════
    # MAIN RUN — two phases
    # ════════════════════════════════════════════════════════════════════

    def run(self):
        import concurrent.futures

        # ── Phase 1: fast parallel probes (~5-8 s, no root) ─────────────
        self.discover_status.emit(
            f"[1/2] Probing {self.host} — SSH, Telnet, HTTP, UPnP"
            + (", SNMP" if self.snmp_community else "") + "…")

        probes = [
            self._probe_ssh,
            self._probe_telnet,
            lambda: self._probe_http(80,   False),
            lambda: self._probe_http(443,  True),
            lambda: self._probe_http(8080, False),
            lambda: self._probe_http(8443, True),
            self._probe_upnp,
        ]
        if self.snmp_community:
            probes.append(self._probe_snmp)

        probe_services = []
        open_ports     = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(probes)) as ex:
            futures = {ex.submit(fn): fn for fn in probes}
            for fut in concurrent.futures.as_completed(futures, timeout=10):
                try:
                    result = fut.result()
                    if result:
                        probe_services.append(result)
                        if 'port' in result:
                            open_ports.append(str(result['port']))
                except Exception:
                    pass

        if probe_services:
            self.services_found.emit(list(probe_services))

        # ── Phase 2: targeted nmap -sV ───────────────────────────────────
        if open_ports:
            port_list = ','.join(dict.fromkeys(open_ports))  # deduplicate, preserve order
            self.discover_status.emit(
                f"[2/2] nmap -sV on {self.host} (open ports: {port_list})…")
        else:
            port_list = '21,22,23,25,53,80,110,143,161,443,445,8080,8443'
            self.discover_status.emit(
                f"[2/2] nmap -sV on {self.host} (common ports)…")

        nmap_services = self._run_nmap_targeted(port_list)
        all_services  = list(probe_services)
        if nmap_services:
            existing = {s['port'] for s in probe_services}
            for ns in nmap_services:
                if ns['port'] not in existing:
                    all_services.append(ns)
                elif ns.get('version'):
                    # Nmap gives more precise version — update in place
                    for s in all_services:
                        if s['port'] == ns['port']:
                            s['version'] = ns['version']
                            break
            self.services_found.emit(all_services)

        # ── OS detection (nmap -O, needs root) ───────────────────────────
        os_vendor = os_model = os_version = os_raw = ''
        os_output = self._try_os_detection()
        if os_output:
            os_vendor, os_model, os_version = self._parse_os(os_output)
            os_raw = os_output

        if not all_services and not os_vendor:
            self.discover_error.emit(
                f"No response from {self.host}. "
                "Host may be down or all ports are blocked by a firewall.")
            return

        vendor, model, version = self._best_device_info(
            all_services, os_vendor, os_model, os_version)
        self.device_info.emit(vendor, model, version, os_raw)

    # ════════════════════════════════════════════════════════════════════
    # FAST PROBES
    # ════════════════════════════════════════════════════════════════════

    def _probe_ssh(self):
        import socket
        try:
            with socket.create_connection((self.host, 22), timeout=3) as s:
                banner = s.recv(256).decode('utf-8', errors='replace').strip()
            if not banner.startswith('SSH-'):
                return None
            vendor, model, version = self._parse_ssh_banner(banner)
            return {'port': '22', 'proto': 'tcp', 'service': 'ssh',
                    'product': banner[:80], 'vendor': vendor,
                    'model': model, 'version': version}
        except Exception:
            return None

    def _parse_ssh_banner(self, banner):
        import re
        bl = banner.lower()
        m = re.search(r'routeros[_\s]+([\d.]+)', bl)
        if m:                              return 'MikroTik',  'RouterOS', m.group(1)
        if 'routeros' in bl:              return 'MikroTik',  'RouterOS', ''
        if 'huawei' in bl:
            m = re.search(r'vrp\s+(v[\d.r]+)', bl, re.I)
            return 'Huawei', 'VRP', m.group(1) if m else ''
        if 'cisco' in bl:                 return 'Cisco',     'IOS',      ''
        if 'juniper' in bl:               return 'Juniper',   'Junos OS', ''
        if 'forti' in bl:                 return 'Fortinet',  'FortiOS',  ''
        if 'aruba' in bl:                 return 'Aruba',     'ArubaOS',  ''
        m = re.search(r'openssh[_\s]+([\d.]+\w*)', bl)
        if m:                             return 'OpenSSH',   '',         m.group(1)
        m = re.search(r'dropbear[_\s]+([\d.]+)', bl)
        if m:                             return 'Dropbear',  'sshd',     m.group(1)
        return '', '', ''

    def _probe_telnet(self):
        import socket
        try:
            with socket.create_connection((self.host, 23), timeout=3) as s:
                s.settimeout(2)
                try:    banner = s.recv(512).decode('utf-8', errors='replace')
                except socket.timeout: banner = ''
            if not banner.strip():
                return None
            vendor, model, version = self._parse_telnet_banner(banner)
            return {'port': '23', 'proto': 'tcp', 'service': 'telnet',
                    'product': banner.strip()[:80], 'vendor': vendor,
                    'model': model, 'version': version}
        except Exception:
            return None

    def _parse_telnet_banner(self, banner):
        import re
        bl = banner.lower()
        m = re.search(r'routeros\s+([\d.]+)', bl)
        if m:                  return 'MikroTik', 'RouterOS', m.group(1)
        if 'huawei' in bl or 'vrp' in bl: return 'Huawei', 'VRP', ''
        m = re.search(r'cisco ios.*?version\s+([\d.()A-Za-z]+)', bl, re.DOTALL)
        if m:                  return 'Cisco',    'IOS',      m.group(1)
        if 'cisco' in bl:      return 'Cisco',    'IOS',      ''
        if 'juniper' in bl:    return 'Juniper',  'Junos OS', ''
        if 'forti' in bl:      return 'Fortinet', 'FortiOS',  ''
        if 'mikrotik' in bl:   return 'MikroTik', 'RouterOS', ''
        return '', '', ''

    def _probe_http(self, port=80, use_ssl=False):
        import socket, ssl, re
        try:
            s = socket.create_connection((self.host, port), timeout=4)
            if use_ssl:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode    = ssl.CERT_NONE
                s = ctx.wrap_socket(s, server_hostname=self.host)
            s.sendall((f'GET / HTTP/1.1\r\nHost: {self.host}\r\n'
                        'User-Agent: Cetus/1.7\r\nConnection: close\r\n\r\n').encode())
            s.settimeout(4)
            resp = b''
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk: break
                    resp += chunk
                    if len(resp) > 8192: break
            except socket.timeout: pass
            s.close()
            text    = resp.decode('utf-8', errors='replace')
            vendor, model, version = self._parse_http_response(text)
            sm      = re.search(r'^Server:\s*(.+)$', text, re.MULTILINE | re.IGNORECASE)
            product = sm.group(1).strip()[:80] if sm else ('HTTPS' if use_ssl else 'HTTP')
            return {'port': str(port), 'proto': 'tcp',
                    'service': 'https' if use_ssl else 'http',
                    'product': product, 'vendor': vendor,
                    'model': model, 'version': version}
        except Exception:
            return None

    def _parse_http_response(self, text):
        import re
        sm     = re.search(r'^Server:\s*(.+)$', text, re.MULTILINE | re.IGNORECASE)
        server = sm.group(1).strip().lower() if sm else ''
        tm     = re.search(r'<title[^>]*>([^<]+)</title>', text, re.IGNORECASE)
        title  = tm.group(1).strip().lower() if tm else ''
        if 'huawei' in server or 'huawei' in title:
            m = re.search(r'V(\d+R\d+\w*)', text)
            return 'Huawei', 'VRP', m.group(1) if m else ''
        if 'mikrotik' in title or 'routeros' in title or 'mikrotik' in server:
            m = re.search(r'RouterOS\s+([\d.]+)', text, re.I)
            return 'MikroTik', 'RouterOS', m.group(1) if m else ''
        if 'cisco' in server or 'cisco' in title:    return 'Cisco',     '',      ''
        if 'forti' in server or 'forti' in title:     return 'Fortinet',  'FortiOS', ''
        if 'ubiquiti' in title or 'unifi' in title:   return 'Ubiquiti',  '',      ''
        if 'tp-link' in title or 'tplink' in title:   return 'TP-Link',   '',      ''
        if 'd-link' in title:                         return 'D-Link',    '',      ''
        m = re.match(r'nginx/([\d.]+)',            server);
        if m: return 'nginx',       '',       m.group(1)
        m = re.match(r'apache/([\d.]+)',           server)
        if m: return 'Apache',      'httpd',  m.group(1)
        m = re.search(r'microsoft-iis/([\d.]+)',   server)
        if m: return 'Microsoft',   'IIS',    m.group(1)
        m = re.match(r'lighttpd/([\d.]+)',         server)
        if m: return 'lighttpd',    '',       m.group(1)
        if server:
            v, md, ver = NmapDiscoverWorker._split_service_product(server)
            if v: return v, md, ver
        return '', '', ''

    def _probe_upnp(self):
        import socket, re
        msearch = ('M-SEARCH * HTTP/1.1\r\n'
                   f'HOST: {self.host}:1900\r\n'
                   'MAN: "ssdp:discover"\r\nMX: 2\r\nST: upnp:rootdevice\r\n\r\n')
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)
            s.sendto(msearch.encode(), (self.host, 1900))
            resp, _ = s.recvfrom(4096)
            s.close()
            text   = resp.decode('utf-8', errors='replace')
            vendor, model, version = self._parse_upnp_text(text)
            return {'port': '1900', 'proto': 'udp', 'service': 'upnp',
                    'product': text[:80].replace('\r\n', ' '),
                    'vendor': vendor, 'model': model, 'version': version}
        except Exception:
            return None

    def _parse_upnp_text(self, text):
        import re
        tl = text.lower()
        sm = re.search(r'^SERVER:\s*(.+)$', text, re.MULTILINE | re.IGNORECASE)
        server = sm.group(1).strip().lower() if sm else ''
        if 'huawei'   in tl: return 'Huawei',   'VRP',      ''
        if 'mikrotik' in tl or 'routeros' in tl: return 'MikroTik', 'RouterOS', ''
        if 'cisco'    in tl: return 'Cisco',     '',         ''
        if 'ubiquiti' in tl: return 'Ubiquiti',  '',         ''
        if 'tp-link'  in tl: return 'TP-Link',   '',         ''
        if 'd-link'   in tl: return 'D-Link',    '',         ''
        if server:
            v, m, ver = NmapDiscoverWorker._split_service_product(server)
            if v: return v, m, ver
        return '', '', ''

    def _probe_snmp(self):
        """SNMP v2c sysDescr via snmpget subprocess (net-snmp tools)."""
        import subprocess, re
        if not self.snmp_community:
            return None
        try:
            r = subprocess.run(
                ['snmpget', '-v2c', '-c', self.snmp_community,
                 '-t', '3', '-r', '0', self.host, '1.3.6.1.2.1.1.1.0'],
                capture_output=True, text=True, timeout=5)
            if r.returncode != 0 or not r.stdout:
                return None
            m = re.search(r'STRING:\s*["\']?(.+?)["\']?\s*$',
                          r.stdout, re.IGNORECASE | re.MULTILINE)
            if not m:
                return None
            sys_descr         = m.group(1).strip()
            vendor, model, version = self._parse_sysdescr(sys_descr)
            return {'port': '161', 'proto': 'udp', 'service': 'snmp',
                    'product': sys_descr[:80], 'vendor': vendor,
                    'model': model, 'version': version}
        except (FileNotFoundError, Exception):
            return None

    def _parse_sysdescr(self, d):
        """Parse SNMP sysDescr string into (vendor, model, version)."""
        import re
        dl = d.lower()
        if 'routeros' in dl or 'mikrotik' in dl:
            m = re.search(r'RouterOS\s+([\d.]+)', d, re.I)
            return 'MikroTik', 'RouterOS', m.group(1) if m else ''
        if 'huawei' in dl or 'vrp' in dl:
            m = re.search(r'VRP\s+V([\w.]+)', d) or re.search(r'V(\d+R\d+\w*)', d)
            return 'Huawei', 'VRP', m.group(1) if m else ''
        if 'cisco ios' in dl:
            m = re.search(r'Version\s+([\d.()A-Za-z]+)', d)
            return 'Cisco', 'IOS', m.group(1) if m else ''
        if 'cisco' in dl:  return 'Cisco',    '',            ''
        if 'juniper' in dl:
            m = re.search(r'JUNOS\s+([\d.R]+)', d, re.I)
            return 'Juniper', 'Junos OS', m.group(1) if m else ''
        if 'fortinet' in dl or 'fortigate' in dl:
            m = re.search(r'v([\d.]+),', d)
            return 'Fortinet', 'FortiOS', m.group(1) if m else ''
        if 'aruba'    in dl: return 'Aruba',    'ArubaOS',    ''
        if 'ubiquiti' in dl: return 'Ubiquiti', '',            ''
        if 'tp-link'  in dl: return 'TP-Link',  '',            ''
        if 'linux'    in dl:
            m = re.search(r'Linux\s+\S+\s+([\d.]+)', d)
            return 'Linux', 'Linux Kernel', m.group(1) if m else ''
        if 'windows'  in dl:
            m = re.search(r'Windows\s+(.+)', d, re.I)
            return 'Microsoft', 'Windows', m.group(1).strip() if m else ''
        words = d.split()
        ver_m = re.search(r'([\d]+\.[\d]+[.\d]*)', d)
        return (words[0] if words else ''), d[:60], ver_m.group(1) if ver_m else ''

    # ════════════════════════════════════════════════════════════════════
    # NMAP TARGETED SCAN
    # ════════════════════════════════════════════════════════════════════

    def _run_nmap_targeted(self, port_list):
        """Run nmap -sV against specific ports with strict time limits."""
        import subprocess
        try:
            cmd = ['nmap', '-sV', '--open', '-T4',
                   '--host-timeout', '30s',
                   '--max-rtt-timeout', '500ms',
                   '--max-retries', '1',
                   '-p', port_list, self.host]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            output = proc.stdout + (proc.stderr or '')
            if any(x in output for x in ('Host seems down', '0 hosts up', 'Failed to resolve')):
                return []
            return self._parse_services(output)
        except FileNotFoundError:
            self.discover_status.emit("nmap not found — skipping version scan.")
            return []
        except (subprocess.TimeoutExpired, Exception):
            return []

    # ════════════════════════════════════════════════════════════════════
    # OS DETECTION (sudo required)
    # ════════════════════════════════════════════════════════════════════

    def _try_os_detection(self):
        """Run nmap -O with sudo. Returns raw output string or None."""
        import subprocess
        cmd_os = ['nmap', '-O', '--open', '-T4',
                  '--host-timeout', '30s', self.host]
        try:
            r = subprocess.run(['sudo', '-n'] + cmd_os,
                               capture_output=True, text=True, timeout=45)
            if r.returncode == 0:
                return r.stdout + (r.stderr or '')
        except Exception:
            pass
        self._password_event.clear()
        self.sudo_required.emit()
        if not self._password_event.wait(timeout=60) or not self._password:
            return None
        try:
            r = subprocess.run(
                ['sudo', '-S'] + cmd_os,
                input=self._password + '\n',
                capture_output=True, text=True, timeout=45)
            if r.returncode == 0:
                return r.stdout + (r.stderr or '')
        except Exception:
            pass
        return None

    # ════════════════════════════════════════════════════════════════════
    # HELPERS
    # ════════════════════════════════════════════════════════════════════

    def _best_device_info(self, services, os_vendor, os_model, os_version):
        """Pick the best (vendor, model, version) from available data."""
        if os_vendor:
            return os_vendor, os_model, os_version
        # Priority order: SNMP gives richest info, then SSH/Telnet, then HTTP/UPnP
        for svc_type in ('snmp', 'ssh', 'telnet', 'http', 'https', 'upnp'):
            for s in services:
                if s.get('service') == svc_type and s.get('vendor'):
                    return s['vendor'], s.get('model', ''), s.get('version', '')
        for s in services:
            if s.get('vendor'):
                return s['vendor'], s.get('model', ''), s.get('version', '')
        if services:
            s = services[0]
            return (s.get('vendor', s.get('product', '')),
                    s.get('model', s.get('service', '')),
                    s.get('version', ''))
        return '', '', ''

    def _parse_services(self, output):
        import re
        services = []
        pattern = re.compile(
            r'^(\d+)/(tcp|udp)\s+open\s+(\S+)\s*(.*)?$', re.MULTILINE)
        for m in pattern.finditer(output):
            port, proto, service, rest = m.groups()
            rest = (rest or '').strip()
            vendor, model, version = self._split_service_product(rest)
            services.append({
                'port':    port,
                'proto':   proto,
                'service': service,
                'product': rest,        # full raw string for display
                'vendor':  vendor,
                'model':   model,
                'version': version,
            })
        return services

    @staticmethod
    def _split_service_product(product_str):
        """Parse nmap service description into (vendor, model, version).

        Examples:
          'Huawei VRP sshd (protocol 2.0)'      → ('Huawei', 'VRP', '')
          'OpenSSH 8.4p1 Ubuntu 5+deb11u1 ...'  → ('OpenSSH', '', '8.4')
          'Apache httpd 2.4.49 (Unix)'           → ('Apache httpd', '', '2.4.49')
          'nginx 1.18.0'                         → ('nginx', '', '1.18.0')
        """
        import re
        # Strip parenthetical OS hints: "(protocol 2.0)", "(Ubuntu Linux; ...)", etc.
        clean = re.sub(r'\s*\([^)]*\)', '', product_str).strip()

        # Known multi-word vendor+product prefixes (longest match first)
        known = [
            ('Huawei VRP',       'Huawei',    'VRP'),
            ('Huawei',           'Huawei',    'VRP'),
            ('Cisco IOS',        'Cisco',     'IOS'),
            ('Apache httpd',     'Apache',    'httpd'),
            ('Microsoft IIS',    'Microsoft', 'IIS'),
            ('Microsoft HTTPAPI','Microsoft', 'HTTPAPI'),
            ('OpenSSH',          'OpenSSH',   ''),
            ('Dropbear sshd',    'Dropbear',  'sshd'),
            ('MikroTik',         'MikroTik',  'RouterOS'),
            ('Postfix smtpd',    'Postfix',   'smtpd'),
            ('Dovecot',          'Dovecot',   ''),
            ('nginx',            'nginx',     ''),
            ('vsftpd',           'vsftpd',    ''),
            ('ProFTPD',          'ProFTPD',   ''),
            ('Pure-FTPd',        'Pure-FTPd', ''),
            ('Exim smtpd',       'Exim',      'smtpd'),
            ('Sendmail',         'Sendmail',  ''),
        ]
        for prefix, vendor, model in known:
            if clean.lower().startswith(prefix.lower()):
                rest = clean[len(prefix):].strip()
                ver_m = re.match(r'^([\d][.\d\w+-]*)', rest)
                return vendor, model, ver_m.group(1) if ver_m else ''

        # Generic: first word = vendor; second word = version if it starts with digit
        words = clean.split()
        if not words:
            return product_str, '', ''
        vendor = words[0]
        if len(words) >= 2:
            ver_m = re.match(r'^([\d][.\d\w+-]*)$', words[1])
            if ver_m:
                return vendor, '', ver_m.group(1)
            # Try third word too (e.g. "vendor product 1.2.3")
            if len(words) >= 3:
                ver_m = re.match(r'^([\d][.\d\w+-]*)$', words[2])
                if ver_m:
                    return vendor, words[1], ver_m.group(1)
        return vendor, '', ''

    def _parse_os(self, output):
        import re
        for pat in (r'OS details:\s*(.+)', r'Aggressive OS guesses:\s*(.+?)(?:\s+\(|,|$)'):
            m = re.search(pat, output)
            if m:
                return self._split_os_string(m.group(1).strip())
        return '', '', ''

    def _split_os_string(self, s):
        import re
        known = [
            (r'MikroTik RouterOS\s*([\d.x]+)?',   'MikroTik',  'RouterOS'),
            (r'Cisco IOS\s*([\d.()A-Za-z]+)?',     'Cisco',     'IOS'),
            (r'Cisco NX-OS\s*([\d.()A-Za-z]+)?',   'Cisco',     'NX-OS'),
            (r'Juniper\s+Junos\s*([\d.R]+)?',       'Juniper',   'Junos OS'),
            (r'Fortinet\s+FortiOS\s*([\d.]+)?',     'Fortinet',  'FortiOS'),
            (r'Palo Alto\s+PAN-OS\s*([\d.]+)?',     'Palo Alto', 'PAN-OS'),
            (r'pfSense\s*([\d.]+)?',                'Netgate',   'pfSense'),
            (r'FreeBSD\s*([\d.]+)?',                'FreeBSD',   'FreeBSD'),
            (r'Linux\s+([\d.-]+)',                  'Linux',     'Linux Kernel'),
            (r'Windows Server\s*([\d\w ]+)',        'Microsoft', 'Windows Server'),
            (r'Windows\s+([\d\w .]+)',              'Microsoft', 'Windows'),
        ]
        for pattern, vendor, model in known:
            m = re.search(pattern, s, re.IGNORECASE)
            if m:
                version = m.group(m.lastindex) if m.lastindex and m.group(m.lastindex) else ''
                return vendor, model, version.strip()
        # Generic fallback
        words = s.split()
        vendor = words[0] if words else s
        model  = ' '.join(words[1:]) if len(words) > 1 else ''
        ver_m  = re.search(r'([\d]+\.[\d]+[.\d]*)', s)
        return vendor, model, ver_m.group(1) if ver_m else ''






class MtrWorker(QThread):
    """Worker thread for MTR (My Traceroute) — continuous per-hop latency monitoring"""

    hop_discovered = pyqtSignal(int, str, str)                      # hop_num, ip, hostname
    hop_updated    = pyqtSignal(int, float, float, float, float, float, int)
                                                                     # hop_num, loss%, avg, best, worst, stdev, sent
    cycle_complete = pyqtSignal(int)                                 # cycle_num
    mtr_error      = pyqtSignal(str)
    mtr_finished   = pyqtSignal()

    def __init__(self, target, max_hops=30, interval=1, dns_lookup=True, packets=10):
        super().__init__()
        self.target     = target
        self.max_hops   = max_hops
        self.interval   = interval
        self.dns_lookup = dns_lookup
        self.packets    = packets      # number of packets to send
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        import statistics as _stats

        cmd = ['mtr', '--raw']
        if not self.dns_lookup:
            cmd.append('-n')
        if self.packets > 0:
            cmd.extend(['-c', str(self.packets)])
        cmd.extend(['-m', str(self.max_hops), '--interval', str(self.interval), self.target])

        # Per-hop state
        sent      = {}   # hop_num → int
        recv      = {}   # hop_num → int
        latencies = {}   # hop_num → [float ms]
        ip_map    = {}   # hop_num → str
        host_map  = {}   # hop_num → str
        discovered = set()
        cycle_num = 0

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )

            for line in process.stdout:
                if self._stop_flag:
                    process.terminate()
                    break

                parts = line.strip().split()
                if len(parts) < 3:
                    continue

                kind    = parts[0]
                hop_num = int(parts[1])
                value   = parts[2]

                if kind == 'x':
                    # Probe sent to hop_num
                    sent[hop_num] = sent.get(hop_num, 0) + 1
                    if hop_num == 0:
                        cycle_num += 1
                        self.cycle_complete.emit(cycle_num)

                elif kind == 'h':
                    # Hop IP discovered
                    ip_map[hop_num] = value
                    if hop_num not in host_map:
                        host_map[hop_num] = value
                    if hop_num not in discovered:
                        discovered.add(hop_num)
                        recv[hop_num] = 0
                        latencies[hop_num] = []
                        self.hop_discovered.emit(hop_num, value, host_map[hop_num])

                elif kind == 'd':
                    # DNS hostname resolved
                    host_map[hop_num] = value
                    # Re-emit hop_discovered to update hostname in table
                    self.hop_discovered.emit(hop_num, ip_map.get(hop_num, value), value)

                elif kind == 'p':
                    # Probe response: latency in microseconds
                    lat_ms = int(value) / 1000.0
                    recv[hop_num] = recv.get(hop_num, 0) + 1
                    if hop_num not in latencies:
                        latencies[hop_num] = []
                    latencies[hop_num].append(lat_ms)

                    lats = latencies[hop_num]
                    s    = sent.get(hop_num, 1)
                    r    = recv[hop_num]
                    loss = (s - r) / s * 100.0
                    avg  = sum(lats) / len(lats)
                    best = min(lats)
                    worst = max(lats)
                    stdev = _stats.stdev(lats) if len(lats) > 1 else 0.0
                    self.hop_updated.emit(hop_num, loss, avg, best, worst, stdev, s)

            process.wait()
            stderr_out = process.stderr.read()
            if process.returncode != 0 and stderr_out and not self._stop_flag:
                low = stderr_out.lower()
                if 'permission' in low or 'not permitted' in low:
                    if sys.platform == 'win32':
                        self.mtr_error.emit(
                            "MTR requires elevated privileges for ICMP on Windows.\n\n"
                            "Run Cetus as Administrator."
                        )
                    else:
                        self.mtr_error.emit(
                            "MTR requires elevated privileges for ICMP.\n\n"
                            "Run Cetus with: sudo python3 cetus\n"
                            "Or install mtr with setuid bit: sudo chmod u+s /usr/bin/mtr"
                        )
                    return
                elif stderr_out.strip():
                    self.mtr_error.emit(f"MTR error: {stderr_out.strip()}")
                    return

        except FileNotFoundError:
            self.mtr_error.emit(
                "mtr command not found.\n\n"
                "Install with:\n"
                "  Arch/CachyOS: sudo pacman -S mtr\n"
                "  Debian/Ubuntu: sudo apt install mtr"
            )
            return
        except PermissionError:
            self.mtr_error.emit(
                "MTR requires elevated privileges.\n\n"
                "Run Cetus with: sudo python3 cetus"
            )
            return
        except Exception as e:
            self.mtr_error.emit(f"MTR error: {e}")
            return

        self.mtr_finished.emit()



class PingWorker(QThread):
    """ICMP ping worker — sends N echo requests, emits per-result signal."""
    ping_result   = pyqtSignal(int, bool, float, str)   # seq, success, rtt_ms, info
    ping_finished = pyqtSignal(int, int, float)          # sent, received, avg_ms
    ping_error    = pyqtSignal(str)

    def __init__(self, target, count=10, interval=1, timeout=5):
        super().__init__()
        self.target    = target
        self.count     = count
        self.interval  = interval
        self.timeout   = timeout
        self._stop_flag = False

    def stop(self): self._stop_flag = True

    def run(self):
        import re as _re, time as _t
        sent = received = 0
        total_rtt = 0.0
        for seq in range(1, self.count + 1):
            if self._stop_flag:
                break
            try:
                import os as _os
                _env = dict(_os.environ)
                _env['LC_ALL'] = 'C'
                if sys.platform == 'win32':
                    timeout_ms = max(1, int(self.timeout * 1000))
                    cmd = ['ping', '-n', '1', '-w', str(timeout_ms), self.target]
                else:
                    cmd = ['ping', '-c', '1', '-W', str(self.timeout), self.target]
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=self.timeout + 2, env=_env)
                sent += 1
                out = result.stdout + result.stderr
                if result.returncode == 0:
                    # Match "time=9.34 ms" or "time=9,34 ms" (locale-aware)
                    m = _re.search(r'time[=<]([\d.,]+)\s*ms', out)
                    rtt = float(m.group(1).replace(',', '.')) if m else 0.0
                    ttl = _re.search(r'ttl=(\d+)', out, _re.IGNORECASE)
                    info = f"ttl={ttl.group(1)}" if ttl else ""
                    received += 1
                    total_rtt += rtt
                    self.ping_result.emit(seq, True, rtt, info)
                else:
                    self.ping_result.emit(seq, False, 0.0, "timeout")
            except subprocess.TimeoutExpired:
                sent += 1
                self.ping_result.emit(seq, False, 0.0, "timeout")
            except Exception as e:
                self.ping_error.emit(str(e))
                return
            if seq < self.count and not self._stop_flag:
                deadline = _t.monotonic() + self.interval
                while _t.monotonic() < deadline and not self._stop_flag:
                    _t.sleep(0.05)
        avg = total_rtt / received if received else 0.0
        self.ping_finished.emit(sent, received, avg)



class PingTCPWorker(QThread):
    """TCP ping worker — connects to host:port N times, measures RTT."""
    ping_result   = pyqtSignal(int, bool, float, str)
    ping_finished = pyqtSignal(int, int, float)
    ping_error    = pyqtSignal(str)

    def __init__(self, target, port, count=10, interval=1, timeout=5):
        super().__init__()
        self.target    = target
        self.port      = port
        self.count     = count
        self.interval  = interval
        self.timeout   = timeout
        self._stop_flag = False

    def stop(self): self._stop_flag = True

    def run(self):
        import socket as _sock, time as _t
        sent = received = 0
        total_rtt = 0.0
        try:
            resolved = _sock.gethostbyname(self.target)
        except Exception as e:
            self.ping_error.emit(f"Cannot resolve '{self.target}': {e}")
            return
        for seq in range(1, self.count + 1):
            if self._stop_flag:
                break
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(self.timeout)
            import time as _t2
            t0 = _t2.monotonic()
            err = s.connect_ex((resolved, self.port))
            rtt = (_t2.monotonic() - t0) * 1000
            s.close()
            sent += 1
            if err == 0:
                received += 1
                total_rtt += rtt
                self.ping_result.emit(seq, True, rtt, f"port {self.port} open")
            else:
                info = "timeout" if rtt >= self.timeout * 950 else f"refused (err {err})"
                self.ping_result.emit(seq, False, rtt, info)
            if seq < self.count and not self._stop_flag:
                deadline = _t.monotonic() + self.interval
                while _t.monotonic() < deadline and not self._stop_flag:
                    _t.sleep(0.05)
        avg = total_rtt / received if received else 0.0
        self.ping_finished.emit(sent, received, avg)



class Iperf3DiscoverWorker(QThread):
    """Scan the local /24 subnet for hosts with iperf3 port open."""
    host_found  = pyqtSignal(str)   # first IP found
    scan_status = pyqtSignal(str)   # progress text
    not_found   = pyqtSignal()

    def __init__(self, port=5201, timeout=0.3, parent=None):
        super().__init__(parent)
        self.port       = port
        self.timeout    = timeout
        self._stop_flag = False

    def stop(self): self._stop_flag = True

    def run(self):
        import socket as _s, ipaddress as _ip
        from concurrent.futures import ThreadPoolExecutor, as_completed as _ac

        # Detect local IP via UDP trick (no packet sent)
        try:
            sock = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
            sock.connect(('8.8.8.8', 80))
            local_ip = sock.getsockname()[0]
            sock.close()
        except Exception:
            self.scan_status.emit("Cannot detect local IP")
            self.not_found.emit()
            return

        # Build /24 target list (skip network/broadcast and self)
        try:
            network = _ip.IPv4Network(f"{local_ip}/24", strict=False)
        except Exception:
            self.not_found.emit()
            return

        targets = [str(h) for h in network.hosts() if str(h) != local_ip]
        self.scan_status.emit(f"Scanning {network} for iperf3 port {self.port}…")

        found = None

        def probe(ip):
            if self._stop_flag:
                return None
            try:
                s = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
                s.settimeout(self.timeout)
                err = s.connect_ex((ip, self.port))
                s.close()
                return ip if err == 0 else None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=64) as pool:
            futures = {pool.submit(probe, ip): ip for ip in targets}
            for future in _ac(futures):
                if self._stop_flag or found:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                result = future.result()
                if result:
                    found = result
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

        if found:
            self.host_found.emit(found)
        else:
            self.not_found.emit()



class Iperf3Worker(QThread):
    """Run iperf3 as client or server and emit real-time interval data."""
    interval_result = pyqtSignal(float, float, float, float)
    # (interval_end_s, bitrate_mbps, transfer_mb, jitter_ms)
    finished        = pyqtSignal(float, float, float, float)
    # (avg_bitrate_mbps, total_transfer_mb, avg_jitter_ms, loss_pct)
    error           = pyqtSignal(str)
    log_line        = pyqtSignal(str)

    def __init__(self, host, port, duration, protocol, streams,
                 bandwidth_mbps, reverse, mode, parent=None):
        super().__init__(parent)
        self.host           = host
        self.port           = port
        self.duration       = duration
        self.protocol       = protocol   # 'TCP' or 'UDP'
        self.streams        = streams
        self.bandwidth_mbps = bandwidth_mbps
        self.reverse        = reverse
        self.mode           = mode       # 'client' or 'server'
        self._stop_flag     = False
        self._process       = None

    def stop(self):
        self._stop_flag = True
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    @staticmethod
    def _to_mbps(value, unit):
        """Normalize a bitrate value+unit string to Mbits/s float."""
        u = unit.lower()
        if 'g' in u:
            return value * 1000.0
        if 'k' in u:
            return value / 1000.0
        return float(value)   # already Mbits/s

    @staticmethod
    def _to_mb(value, unit):
        """Normalize a transfer value+unit string to MBytes float."""
        u = unit.lower()
        if 'g' in u:
            return value * 1024.0
        if 'k' in u:
            return value / 1024.0
        return float(value)

    def run(self):
        import subprocess as _sp, re as _re

        # Build command
        if self.mode == 'server':
            cmd = ['iperf3', '-s', '-p', str(self.port), '-1', '--forceflush']
        else:
            cmd = ['iperf3', '-c', self.host, '-p', str(self.port),
                   '-t', str(self.duration), '-P', str(self.streams),
                   '--forceflush']
            if self.protocol == 'UDP':
                cmd += ['-u', '-b', f'{self.bandwidth_mbps}M']
            if self.reverse:
                cmd += ['-R']

        try:
            self._process = _sp.Popen(
                cmd,
                stdout=_sp.PIPE, stderr=_sp.STDOUT,
                text=True, bufsize=1
            )
        except FileNotFoundError:
            self.error.emit("iperf3 not found. Install it with: sudo apt install iperf3")
            return
        except Exception as e:
            self.error.emit(f"Failed to start iperf3: {e}")
            return

        # Regex for interval lines:
        # [  5]   0.00-1.00   sec  54.2 MBytes  455 Mbits/sec  [0.027 ms  0/897 (0%)]
        interval_re = _re.compile(
            r'\[\s*\d+\]\s+([\d.]+)-([\d.]+)\s+sec'
            r'\s+([\d.]+)\s+(\w+Bytes)'
            r'\s+([\d.]+)\s+(\w+bits/sec)'
            r'(?:\s+([\d.]+)\s+ms\s+(\d+)/(\d+)\s+\(([\d.]+)%\))?'
        )
        intervals = []
        last_jitter = -1.0   # -1 = no data (TCP has no jitter/loss)
        last_loss   = -1.0

        for line in self._process.stdout:
            if self._stop_flag:
                break
            line = line.rstrip('\n')
            self.log_line.emit(line)

            m = interval_re.search(line)
            if not m:
                continue

            t_end      = float(m.group(2))
            transfer   = self._to_mb(float(m.group(3)), m.group(4))
            bitrate    = self._to_mbps(float(m.group(5)), m.group(6))
            jitter_raw = m.group(7)
            loss_raw   = m.group(10)
            jitter     = float(jitter_raw) if jitter_raw else 0.0
            loss_pct   = float(loss_raw)   if loss_raw   else 0.0

            # Capture jitter/loss from any matched line, including sender/receiver summaries
            if jitter_raw:
                last_jitter = jitter
            if loss_raw is not None:
                last_loss = loss_pct

            # Skip multi-stream "[SUM]" duplicates and summary lines (same t_end)
            if intervals and abs(t_end - intervals[-1][0]) < 0.01:
                continue

            intervals.append((t_end, bitrate, transfer))
            self.interval_result.emit(t_end, bitrate, transfer, jitter)

        self._process.wait()

        if intervals:
            avg_bps  = sum(b for _, b, _ in intervals) / len(intervals)
            total_mb = intervals[-1][2] if intervals else 0.0
            self.finished.emit(avg_bps, total_mb, last_jitter, last_loss)
        else:
            if not self._stop_flag:
                self.error.emit("No interval data received — check host/port and iperf3 server.")





class SpeedTestWorker(QThread):
    """Measure download/upload speed using the speedtest-cli Python library."""

    result      = pyqtSignal(float, float, float)  # ping_ms, dl_mbps, ul_mbps
    info        = pyqtSignal(str, str, str, str)   # isp, rating, country, server
    phase_start = pyqtSignal(str)                  # 'download' | 'upload'
    phase_done  = pyqtSignal(str, float)           # phase, avg_mbps
    progress    = pyqtSignal(float, float, float)  # elapsed_s, speed_mbps, 0.0
    log_line    = pyqtSignal(str)
    error       = pyqtSignal(str)

    def run(self):
        import time as _time
        try:
            import speedtest as _speedtest
        except ImportError:
            self.error.emit(
                "'speedtest-cli' not found.\n"
                "Install with: pip install speedtest-cli"
            )
            return

        try:
            t0 = _time.monotonic()

            self.log_line.emit("Connecting to speedtest.net…")
            st = _speedtest.Speedtest()

            self.log_line.emit("Getting best server…")
            best = st.get_best_server()
            server_name = (
                f"{best.get('sponsor', '')} — {best.get('name', '')} "
                f"({best.get('country', '')})"
            )
            self.log_line.emit(f"Server: {server_name}")

            # ── Download ──────────────────────────────────────────────────
            self.phase_start.emit('download')
            self.log_line.emit("Testing download…")
            st.download()
            dl_mbps = st.results.download / 1e6
            self.progress.emit(_time.monotonic() - t0, dl_mbps, 0.0)
            self.phase_done.emit('download', dl_mbps)
            self.log_line.emit(f"Download: {dl_mbps:.2f} Mbps")

            # ── Upload ────────────────────────────────────────────────────
            self.phase_start.emit('upload')
            self.log_line.emit("Testing upload…")
            st.upload()
            ul_mbps = st.results.upload / 1e6
            self.progress.emit(_time.monotonic() - t0, ul_mbps, 0.0)
            self.phase_done.emit('upload', ul_mbps)
            self.log_line.emit(f"Upload: {ul_mbps:.2f} Mbps")

            ping_ms = st.results.ping

            # ── ISP / country via IP geolocation ──────────────────────────
            isp = '—'
            country = '—'
            try:
                import urllib.request as _ur, json as _json
                with _ur.urlopen('http://ip-api.com/json/?fields=isp,country', timeout=4) as _r:
                    _d = _json.loads(_r.read().decode())
                    isp     = _d.get('isp', '—') or '—'
                    country = _d.get('country', '—') or '—'
            except Exception:
                pass

            self.info.emit(isp, '—', country, server_name)
            self.result.emit(ping_ms, dl_mbps, ul_mbps)
            self.log_line.emit(
                f"Download: {dl_mbps:.2f} Mbps  |  Upload: {ul_mbps:.2f} Mbps"
                f"  |  Ping: {ping_ms:.1f} ms"
            )

        except Exception as e:
            self.error.emit(f"Speed test error: {e}")



class _SimplePingWorker(QThread):
    """Run `ping -c 4 <host>` and return the average RTT in ms."""
    result = pyqtSignal(float)   # avg_ms
    error  = pyqtSignal(str)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host

    def run(self):
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
            for line in proc.stdout.splitlines():
                # Linux: rtt min/avg/max/mdev = 1.2/5.6/9.0/0.3 ms
                if ('rtt' in line or 'round-trip' in line) and '/' in line:
                    try:
                        avg = float(line.split('=')[-1].strip().split('/')[1])
                        self.result.emit(avg)
                        return
                    except Exception:
                        pass
            self.error.emit("no reply")
        except Exception as e:
            self.error.emit(str(e))




class DeviceImageWorker(QThread):
    """Fetch a product image for a hardware model using DuckDuckGo image search."""
    image_ready = pyqtSignal(bytes)   # raw JPEG/PNG bytes
    image_error = pyqtSignal()

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        import urllib.request, urllib.parse, re, json
        try:
            q   = urllib.parse.quote(self.query)
            ua  = ('Mozilla/5.0 (X11; Linux x86_64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0 Safari/537.36')
            # ── Step 1: obtain VQD token ──────────────────────────────
            req1 = urllib.request.Request(
                f'https://duckduckgo.com/?q={q}&iax=images&ia=images',
                headers={'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'})
            with urllib.request.urlopen(req1, timeout=10) as r:
                html = r.read().decode('utf-8', errors='replace')
            vqd_m = re.search(r'vqd=(["\'])([^"\']+)\1', html)
            if not vqd_m:
                self.image_error.emit(); return
            vqd = vqd_m.group(2)
            # ── Step 2: image search ──────────────────────────────────
            req2 = urllib.request.Request(
                f'https://duckduckgo.com/i.js?q={q}&o=json&vqd={vqd}&f=,,,&p=1&v7exp=a',
                headers={'User-Agent': ua, 'Accept': 'application/json',
                         'Referer': 'https://duckduckgo.com/'})
            with urllib.request.urlopen(req2, timeout=10) as r:
                data = json.loads(r.read().decode())
            results = data.get('results', [])
            if not results:
                self.image_error.emit(); return
            thumb_url = results[0].get('thumbnail') or results[0].get('image', '')
            if not thumb_url:
                self.image_error.emit(); return
            # ── Step 3: download thumbnail ────────────────────────────
            req3 = urllib.request.Request(thumb_url, headers={'User-Agent': ua})
            with urllib.request.urlopen(req3, timeout=10) as r:
                self.image_ready.emit(r.read())
        except Exception:
            self.image_error.emit()






class FileConnectWorker(QThread):
    connected = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, protocol, host, port, username, password, parent=None):
        super().__init__(parent)
        self._protocol = protocol
        self._host = host
        self._port = port
        self._user = username
        self._pass = password

    def run(self):
        try:
            if self._protocol == 'SSH':
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(self._host, port=self._port, username=self._user,
                            password=self._pass, timeout=10)
                sftp = ssh.open_sftp()
                self.connected.emit({'ssh': ssh, 'sftp': sftp})
            elif self._protocol == 'FTP':
                import ftplib
                ftp = ftplib.FTP()
                ftp.connect(self._host, self._port, timeout=10)
                ftp.login(self._user, self._pass)
                self.connected.emit({'ftp': ftp})
            else:
                self.error.emit(f"Client mode for {self._protocol} not yet implemented")
        except Exception as e:
            self.error.emit(str(e))



class FileListWorker(QThread):
    result = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, protocol, conn_data, path, parent=None):
        super().__init__(parent)
        self._protocol = protocol
        self._conn = conn_data
        self._path = path

    def run(self):
        try:
            entries = []
            if self._protocol == 'SSH':
                import stat as _stat
                sftp = self._conn['sftp']
                for attr in sftp.listdir_attr(self._path):
                    is_dir = bool(attr.st_mode and _stat.S_ISDIR(attr.st_mode))
                    entries.append((attr.filename, attr.st_size or 0, is_dir, attr.st_mtime or 0))
            elif self._protocol == 'FTP':
                ftp = self._conn['ftp']
                ftp.cwd(self._path)
                for name, facts in ftp.mlsd(facts=['size', 'type', 'modify']):
                    if name in ('.', '..'):
                        continue
                    is_dir = facts.get('type', '') == 'dir'
                    size = int(facts.get('size', 0))
                    entries.append((name, size, is_dir, 0))
            entries.sort(key=lambda x: (not x[2], x[0].lower()))
            self.result.emit(entries)
        except Exception as e:
            self.error.emit(str(e))



class FileTransferWorker(QThread):
    progress = pyqtSignal(int, int, int)   # percent, bytes_done, bytes_total
    finished = pyqtSignal(bool, str)

    def __init__(self, direction, protocol, conn_data, item_list, parent=None):
        super().__init__(parent)
        self._dir = direction   # 'upload' or 'download'
        self._protocol = protocol
        self._conn = conn_data
        self._items = item_list   # list of (local_path, remote_path)
        self._total = 0

    def run(self):
        try:
            total_bytes = 0
            file_sizes = []
            for local, remote in self._items:
                size = 0
                if self._dir == 'upload':
                    try:
                        size = os.path.getsize(local) if os.path.exists(local) else 0
                    except OSError:
                        size = 0
                else:
                    try:
                        if self._protocol == 'SSH':
                            size = self._conn['sftp'].stat(remote).st_size
                    except Exception:
                        size = 0
                file_sizes.append(size)
                total_bytes += size
            self._total = total_bytes
            cumulative_done = 0

            for i, (local, remote) in enumerate(self._items):
                local_dir = os.path.dirname(local)
                if self._protocol == 'SSH':
                    sftp = self._conn['sftp']
                    if self._dir == 'upload':
                        remote_dir = os.path.dirname(remote)
                        self._sftp_mkdir_p(sftp, remote_dir)
                        off = cumulative_done
                        sftp.put(local, remote, callback=lambda d, t, _off=off: (
                            self.progress.emit(int((_off + d) * 100 / self._total) if self._total else 0, int(_off + d), int(self._total))
                        ))
                    else:
                        os.makedirs(local_dir, exist_ok=True)
                        off = cumulative_done
                        sftp.get(remote, local, callback=lambda d, t, _off=off: (
                            self.progress.emit(int((_off + d) * 100 / self._total) if self._total else 0, int(_off + d), int(self._total))
                        ))
                elif self._protocol == 'FTP':
                    os.makedirs(local_dir, exist_ok=True)
                    ftp = self._conn['ftp']
                    if self._dir == 'upload':
                        with open(local, 'rb') as f:
                            ftp.storbinary(f'STOR {os.path.basename(remote)}', f)
                    else:
                        with open(local, 'wb') as f:
                            ftp.retrbinary(f'RETR {remote}', f.write)
                cumulative_done += file_sizes[i]

            count = len(self._items)
            msg = f"{count} file{'s' if count != 1 else ''} transferred"
            self.progress.emit(100, self._total, self._total)
            self.finished.emit(True, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

    def _sftp_mkdir_p(self, sftp, remote_dir):
        if not remote_dir or remote_dir == '/':
            return
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            self._sftp_mkdir_p(sftp, os.path.dirname(remote_dir))
            sftp.mkdir(remote_dir)



class TcpdumpWorker(QThread):
    """Run tcpdump and stream output line by line."""
    line_received       = pyqtSignal(str)
    error_occurred      = pyqtSignal(str)
    packet_count_updated = pyqtSignal(int)

    def __init__(self, interface, filter_expr, snap_len=128, sudo_password=None):
        super().__init__()
        self._interface = interface
        self._filter    = filter_expr.strip()
        self._snap_len  = snap_len
        self._sudo_pw   = sudo_password
        self._proc      = None
        self._running   = False
        self._count     = 0

    def run(self):
        cmd = ['tcpdump', '-l', '-n', '-e', '-i', self._interface, '-s', str(self._snap_len)]
        if self._filter:
            import shlex
            cmd += shlex.split(self._filter)
        if self._sudo_pw is not None:
            cmd = ['sudo', '-S'] + cmd
        try:
            stdin_pipe = subprocess.PIPE if self._sudo_pw is not None else None
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=stdin_pipe,
                text=True,
                bufsize=1,
            )
            if self._sudo_pw is not None:
                try:
                    self._proc.stdin.write(self._sudo_pw + '\n')
                    self._proc.stdin.flush()
                    self._proc.stdin.close()
                except Exception:
                    pass
            self._running = True
            for line in self._proc.stdout:
                if not self._running:
                    break
                line = line.rstrip('\n')
                if line:
                    if 'password' in line.lower() and self._sudo_pw is not None:
                        continue
                    self._count += 1
                    self.line_received.emit(line)
                    self.packet_count_updated.emit(self._count)
        except FileNotFoundError:
            self.error_occurred.emit("tcpdump not found — install it with: sudo apt install tcpdump")
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None



class DnsResolverWorker(QThread):
    """Resolve an IP address to a hostname in a background thread."""
    resolved = pyqtSignal(str, str)   # (ip, hostname)

    def __init__(self, ip):
        super().__init__()
        self._ip = ip

    def run(self):
        import socket
        try:
            hostname = socket.gethostbyaddr(self._ip)[0]
        except Exception:
            hostname = self._ip
        self.resolved.emit(self._ip, hostname)



class WiFiScanWorker(QThread):
    """Worker thread that scans for WiFi networks using nmcli."""

    network_found      = pyqtSignal(dict)        # one network per emission
    scan_finished      = pyqtSignal(int)         # total count
    scan_error         = pyqtSignal(str)
    noise_floors_ready = pyqtSignal(object, object)  # (noise_24_or_None, noise_5_or_None)

    def __init__(self, interface=''):
        super().__init__()
        self.interface = interface
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            networks = self._scan()
            for net in networks:
                if self._stop_flag:
                    break
                self.network_found.emit(net)
            self.scan_finished.emit(len(networks))
        except Exception as e:
            self.scan_error.emit(str(e))

    @staticmethod
    def _resolve_interface(interface):
        """Return the given interface or auto-detect the first wireless interface."""
        import subprocess, re
        if interface:
            return interface
        if sys.platform == 'win32':
            try:
                r = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'],
                                   capture_output=True, text=True, timeout=3)
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line.lower().startswith('name'):
                        parts = line.split(':', 1)
                        if len(parts) >= 2:
                            return parts[1].strip()
            except Exception:
                pass
            return ''
        try:
            r = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=3)
            ifaces = re.findall(r'Interface\s+(\S+)', r.stdout)
            return next((i for i in ifaces
                         if re.match(r'wl', i) and 'p2p' not in i and 'mon' not in i),
                        ifaces[0] if ifaces else '')
        except Exception:
            return ''

    @staticmethod
    def _get_driver_name(interface):
        """Return the kernel driver name for the given interface, or empty string."""
        import os
        if not interface or sys.platform == 'win32':
            return ''
        try:
            driver_link = f'/sys/class/net/{interface}/device/driver'
            return os.path.basename(os.readlink(driver_link))
        except Exception:
            pass
        try:
            import subprocess
            r = subprocess.run(['ethtool', '-i', interface],
                               capture_output=True, text=True, timeout=3)
            for line in r.stdout.splitlines():
                if line.startswith('driver:'):
                    return line.split(':', 1)[1].strip()
        except Exception:
            pass
        return ''

    @staticmethod
    def _vht_op_bandwidth(ch_width, seg2):
        """Decode VHT Operation channel width field + segment-2 into MHz.
        Per 802.11ac: width=1 + seg2 != 0 → 160 MHz (or 80+80, treat as 160)."""
        if ch_width == 0:
            return None          # 20 or 40 MHz — defer to HT flags
        if ch_width == 1:
            return 160 if seg2 else 80
        if ch_width in (2, 3):
            return 160
        return None

    def _get_bandwidth_from_iw(self, interface):
        """Parse channel bandwidth and max rate from iw scan dump."""
        import subprocess, re
        bandwidth_map = {}   # bssid -> bandwidth in MHz
        rate_map      = {}   # bssid -> rate string (max PHY rate)
        wifi_gen_map  = {}   # bssid -> "WiFi 4/5/6/7"
        # Auto-detect wireless interface when not specified
        if not interface:
            try:
                r = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=3)
                ifaces = re.findall(r'Interface\s+(\S+)', r.stdout)
                # Prefer standard wlanX / wlpXsY interfaces over p2p/monitor
                interface = next((i for i in ifaces
                                  if re.match(r'wl', i) and 'p2p' not in i and 'mon' not in i),
                                 ifaces[0] if ifaces else '')
            except Exception:
                pass
        if not interface:
            return bandwidth_map, rate_map, wifi_gen_map
        try:
            # 'scan dump' reads kernel cache — no new scan triggered, no root needed
            result = subprocess.run(
                ['iw', 'dev', interface, 'scan', 'dump'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return bandwidth_map, rate_map, wifi_gen_map

            current_bssid  = None
            in_vht_op      = False   # inside "VHT operation:" block
            vht_ch_width   = None
            vht_seg2       = 0
            # WiFi generation priority per BSSID: 1=HT 2=VHT 3=HE 4=EHT
            _gen_prio      = {}

            for line in result.stdout.splitlines():
                stripped = line.strip()

                # ── New BSS entry ──────────────────────────────────────────
                m = re.match(r'BSS\s+([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})', line)
                if m:
                    if current_bssid and vht_ch_width is not None:
                        bw = WiFiScanWorker._vht_op_bandwidth(vht_ch_width, vht_seg2)
                        if bw:
                            bandwidth_map[current_bssid] = max(
                                bandwidth_map.get(current_bssid, 0), bw)
                    current_bssid = m.group(1).upper()
                    in_vht_op = False
                    vht_ch_width = None
                    vht_seg2 = 0
                    continue

                if not current_bssid:
                    continue

                # ── WiFi generation detection ──────────────────────────────
                if re.match(r'\s*EHT capabilities:', line):
                    _gen_prio[current_bssid] = max(_gen_prio.get(current_bssid, 0), 4)
                elif re.match(r'\s*HE capabilities:', line):
                    _gen_prio[current_bssid] = max(_gen_prio.get(current_bssid, 0), 3)
                elif re.match(r'\s*VHT capabilities:', line):
                    _gen_prio[current_bssid] = max(_gen_prio.get(current_bssid, 0), 2)
                elif re.match(r'\s*HT capabilities:', line):
                    _gen_prio[current_bssid] = max(_gen_prio.get(current_bssid, 0), 1)

                # ── VHT operation block ────────────────────────────────────
                if re.match(r'\s*VHT operation:', line):
                    in_vht_op = True
                    vht_ch_width = None
                    vht_seg2 = 0
                    continue
                if in_vht_op:
                    m = re.search(r'\*\s+channel width:\s*(\d+)', stripped)
                    if m:
                        vht_ch_width = int(m.group(1))
                    m = re.search(r'\*\s+center freq segment [12]:\s*(\d+)', stripped)
                    if m:
                        vht_seg2 = int(m.group(1))
                    if stripped and not stripped.startswith('*') and 'VHT operation' not in stripped:
                        bw = WiFiScanWorker._vht_op_bandwidth(vht_ch_width, vht_seg2)
                        if bw:
                            bandwidth_map[current_bssid] = max(
                                bandwidth_map.get(current_bssid, 0), bw)
                        in_vht_op = False

                # ── HT operation (802.11n) ─────────────────────────────────
                if 'HT40+' in stripped or 'HT40-' in stripped:
                    bandwidth_map[current_bssid] = max(
                        bandwidth_map.get(current_bssid, 0), 40)
                elif re.search(r'\bHT20\b', stripped):
                    bandwidth_map.setdefault(current_bssid, 20)

                # ── Explicit 160/80+80 (HE op re-uses VHT op IE) ──────────
                if re.search(r'channel width:\s*2\b', stripped, re.I):
                    bandwidth_map[current_bssid] = 160
                elif re.search(r'channel width:\s*3\b', stripped, re.I):
                    bandwidth_map[current_bssid] = 160

                # ── Max PHY rate from VHT/HE capabilities ─────────────────
                m = re.search(r'(?:VHT|HE)\s+(?:RX|TX)\s+highest supported:\s*([\d.]+)\s*Mbps',
                              stripped, re.I)
                if m:
                    mbps = int(float(m.group(1)))
                    prev = int(re.search(r'\d+', rate_map.get(current_bssid, '0')).group())
                    if mbps > prev:
                        rate_map[current_bssid] = f"{mbps} Mbit/s"

            # Flush last BSSID
            if current_bssid and vht_ch_width is not None:
                bw = WiFiScanWorker._vht_op_bandwidth(vht_ch_width, vht_seg2)
                if bw:
                    bandwidth_map[current_bssid] = max(
                        bandwidth_map.get(current_bssid, 0), bw)

            # Build wifi_gen_map from priority scores
            _prio_to_gen = {4: 'WiFi 7', 3: 'WiFi 6', 2: 'WiFi 5', 1: 'WiFi 4'}
            for bssid, prio in _gen_prio.items():
                wifi_gen_map[bssid] = _prio_to_gen.get(prio, '—')

        except Exception:
            pass
        return bandwidth_map, rate_map, wifi_gen_map

    def _get_noise_floors_from_survey(self, interface):
        """Measure per-band and per-frequency noise floor using 'iw dev <iface> survey dump'.
        Returns (noise_24, noise_5, noise_by_freq) where noise_by_freq maps freq_mhz→dBm.
        Band averages and per-freq values are None/empty if unavailable."""
        import subprocess, re
        if not interface:
            return None, None, {}
        try:
            result = subprocess.run(
                ['iw', 'dev', interface, 'survey', 'dump'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None, None, {}
            noise_24, noise_5 = [], []
            noise_by_freq = {}
            current_freq = None
            for line in result.stdout.splitlines():
                m = re.search(r'frequency:\s+(\d+)\s+MHz', line)
                if m:
                    current_freq = int(m.group(1))
                    continue
                m = re.search(r'noise:\s+(-\d+)\s+dBm', line)
                if m and current_freq is not None:
                    dbm = int(m.group(1))
                    noise_by_freq[current_freq] = dbm
                    if 2400 <= current_freq <= 2500:
                        noise_24.append(dbm)
                    elif 5150 <= current_freq <= 5850:
                        noise_5.append(dbm)
            avg_24 = round(sum(noise_24) / len(noise_24)) if noise_24 else None
            avg_5  = round(sum(noise_5)  / len(noise_5))  if noise_5  else None
            return avg_24, avg_5, noise_by_freq
        except Exception:
            return None, None, {}

    def _scan(self):
        import subprocess, re

        # Resolve the actual interface once (auto-detect if not specified)
        iface = self._resolve_interface(self.interface)

        # Force a fresh scan first (best-effort, may fail without privileges)
        try:
            iface_arg = ['iface', iface] if iface else []
            subprocess.run(
                ['nmcli', 'device', 'wifi', 'rescan'] + iface_arg,
                capture_output=True, timeout=6
            )
        except Exception:
            pass

        # Try to get bandwidth, max PHY rate and WiFi generation from iw scan dump
        bandwidth_map, rate_map, wifi_gen_map = self._get_bandwidth_from_iw(iface)

        # Measure real-time noise floor per band and per frequency via iw survey dump
        noise_24, noise_5, noise_by_freq = self._get_noise_floors_from_survey(iface)
        self.noise_floors_ready.emit(noise_24, noise_5)

        # Driver name for fallback tooltip
        driver_name = self._get_driver_name(iface)

        # Query results
        cmd = [
            'nmcli', '-t',
            '-f', 'IN-USE,BSSID,SSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY',
            'device', 'wifi', 'list'
        ]
        if iface:
            cmd += ['ifname', iface]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'nmcli failed')

        networks = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            # nmcli -t uses ':' as separator; BSSIDs contain ':' so we split carefully
            # Format: IN-USE:BSSID:SSID:MODE:CHAN:FREQ:RATE:SIGNAL:SECURITY
            # BSSID is AA\:BB\:CC\:DD\:EE\:FF (escaped colons)
            line = line.replace('\\:', '\x00')  # temporarily replace escaped colons
            parts = line.split(':')
            if len(parts) < 9:
                continue
            parts = [p.replace('\x00', ':') for p in parts]

            in_use   = parts[0].strip() == '*'
            bssid    = parts[1].strip()
            ssid     = parts[2].strip() or '<hidden>'
            chan_str = parts[4].strip()
            freq_str = parts[5].strip()   # e.g. "2437 MHz"
            rate_str = parts[6].strip()   # e.g. "54 Mbit/s"
            sig_str  = parts[7].strip()
            security = ':'.join(parts[8:]).strip() or 'Open'

            try:
                channel = int(chan_str)
            except ValueError:
                channel = 0

            try:
                signal_pct = int(sig_str)
            except ValueError:
                signal_pct = 0

            # Convert 0-100 signal to approximate dBm
            dbm = (signal_pct // 2) - 100

            # Determine band from frequency
            freq_mhz = 0
            m = re.search(r'(\d+)', freq_str)
            if m:
                freq_mhz = int(m.group(1))
            band = '5GHz' if freq_mhz >= 5000 else '2.4GHz'

            # Use measured noise floor for this channel if available, else fall back to defaults
            measured_noise = noise_by_freq.get(freq_mhz)
            noise_measured = measured_noise is not None
            noise_floor = measured_noise if noise_measured else (-92 if band == '5GHz' else -95)
            snr = dbm - noise_floor if dbm > noise_floor else 0

            # Determine bandwidth
            bandwidth = bandwidth_map.get(bssid.upper())
            if bandwidth is None:
                # Infer from rate if not available from iw
                try:
                    rate_mbps = int(re.search(r'(\d+)', rate_str).group(1)) if rate_str else 0
                    if band == '5GHz':
                        # 802.11ac/ax can use 20/40/80/160 MHz
                        if rate_mbps >= 866:  # Typical for 80MHz 2-stream
                            bandwidth = 80
                        elif rate_mbps >= 300:  # Typical for 40MHz
                            bandwidth = 40
                        else:
                            bandwidth = 20
                    else:
                        # 2.4GHz typically uses 20 or 40 MHz
                        if rate_mbps >= 150:  # Typical for 40MHz
                            bandwidth = 40
                        else:
                            bandwidth = 20
                except (AttributeError, ValueError):
                    bandwidth = 20  # Default fallback

            networks.append({
                'in_use':     in_use,
                'bssid':      bssid,
                'ssid':       ssid,
                'vendor':     _get_mac_vendor(bssid),
                'channel':    channel,
                'freq_mhz':   freq_mhz,
                'band':       band,
                'rate':       rate_map.get(bssid.upper(), rate_str),
                'wifi_gen':   wifi_gen_map.get(bssid.upper(),
                                  'WiFi 6E' if freq_mhz >= 5945 else '—'),
                'signal_pct': signal_pct,
                'dbm':        dbm,
                'snr':        snr,
                'noise_floor':    noise_floor,
                'noise_measured': noise_measured,
                'noise_driver':   driver_name,
                'bandwidth':  bandwidth,
                'security':   security,
            })

        # Sort by signal descending
        networks.sort(key=lambda x: x['signal_pct'], reverse=True)
        return networks




