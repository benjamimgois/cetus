<p align="center">
  <img width="128" height="128" alt="Cetus" src="assets/icons/cetus_icon.svg" />
</p>

<p align="center">
  <a href="https://github.com/benjamimgois/opengrid/releases">
    <img
      src="https://img.shields.io/github/v/release/benjamimgois/opengrid?color=4CAF50&label=Latest%20release&style=for-the-badge"
      alt="Latest release">
  </a>

  <a href="https://github.com/benjamimgois/opengrid/releases">
    <img src="https://img.shields.io/badge/Flatpak-Stable-blue?style=for-the-badge&logo=flatpak" alt="Flatpak">
  </a>

  <a href="https://aur.archlinux.org/packages/cetus-git">
    <img
      src="https://img.shields.io/aur/version/cetus-git?color=1793d1&label=AUR&style=for-the-badge"
      alt="AUR version">
  </a>

  <a href="https://github.com/benjamimgois/opengrid/releases">
    <img
      src="https://img.shields.io/badge/Debian-Stable-A81D33?style=for-the-badge&logo=debian"
      alt="Debian package">
  </a>

  <a href="https://github.com/benjamimgois/opengrid/blob/main/LICENSE">
    <img
      src="https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge"
      alt="License: GPL-3.0">
  </a>
</p>

Easy and modern interface to manage network devices — Serial, SSH, Telnet, VNC, RDP, Traceroute/MTR, IP Scanner, SNMP, File Transfer, Speed Test and Wi-Fi Survey.

<img width="716" height="896" alt="image" src="https://github.com/user-attachments/assets/fe1d4bc5-b92d-4094-bd90-189f70b06466" />


## Features

### Serial Communication
- Modern graphical interface with PyQt6
- **Embedded terminal** — no external terminal required
- Automatic serial port detection with QSerialPortInfo
- Support for serial ports (`/dev/ttyS*`) and USB adapters (`/dev/ttyUSB*`)
- **Port type toggle** (USB / Serial) for quick switching
- Complete parameter configuration: baud rate (300–921600), data bits, parity, stop bits, flow control
- Quick connect profiles with per-device vendor selection
- Root password request via sudo

### Remote Access
- **SSH** — secure shell with password or private key authentication
- **Telnet** — connect to legacy devices over port 23
- **VNC** — graphical desktop access via xtigervncviewer (Wayland-compatible)
- **RDP** — Windows Remote Desktop via wlfreerdp/xfreerdp (Wayland-compatible)
- Saved connection profiles with Quick Connect list and vendor selection
- Save password per host (encrypted in profile)
- Right-click Quick Connect entries to remove them
- Key icon indicator for hosts with saved credentials

### Terminal Emulator
- VT100/ANSI terminal emulation via pyte
- **Syntax highlighting** for network equipment commands
- Support for multiple vendors: Cisco, Huawei, H3C, Juniper, D-Link, Brocade, Datacom, Fortinet
- **Vendor selection per profile** — applies syntax highlighting automatically on connect
- **Search with scroll-to-match** (Ctrl+F)
- Scrollback mode — scroll freely without losing the live view
- Adjustable font size, multiple simultaneous terminal tabs
- Right-click context menu: copy, paste, export, close tab

### IP Scanner
- Network host discovery with ICMP, TCP and UDP scan methods
- **ARP scanning** with hostname resolution and MAC vendor detection
- Configurable subnet mask (CIDR /8–/30), ports, timeout and threads
- Real-time results with IP, status, latency and MAC vendor
- Sortable results table with CSV export
- Progress indicator on the scan button

### Traceroute / MTR
- Graphical route visualization with glowing neon bars and hop details
- **MTR (My Traceroute)** for continuous real-time path monitoring
- **ICMP and TCP ping** with results visualization
- Latency graph with dark/neon aesthetic
- Automatic `cap_net_raw` capability configuration for TCP/UDP probes
- Packet loss and latency statistics per hop
- Configurable packet count and proxy (SOCKS/HTTP)

### SNMP Queries
- SNMP GET, GETNEXT and WALK operations (v1 and v2c)
- GETNEXT remembers the last OID per host and advances on each click
- Real-time streaming results in a sortable table (OID, Value, Type)
- Automatic value type classification (Integer, String, Counter, TimeTicks, etc.)
- Walk progress indicator; limit of 1000 entries per walk to prevent UI overload

### File Transfer
- **SSH/SFTP** — client and server mode with file browser
- **SMB** — server with Share Name, Comment, Workgroup, Valid Users, Guest access, Read-only
- **FTP** — server via pyftpdlib with automatic `pkexec` elevation for port 21
- **TFTP** — server for firmware transfers with network interface auto-detection
- Client mode defaults to SSH; collapsible log panel with timestamps

### Vulnerability Scanner
- **Nmap** integration for OS and service version detection
- **CVE search via NVD API** with CVSS severity badges
- Supports Cisco, Huawei, MikroTik, Juniper and other vendors
- MikroTik version discovery via SNMP OID
- Export results to CSV

### Speed Test
- **iPerf3** — LAN/WAN throughput testing (client / server / reverse modes)
- **fast.com** — internet speed test via Netflix CDN
- Real-time throughput graph (bitrate + cumulative transfer)
- Post-test latency measurement via ping
- ISP and country detection via ip-api.com
- iPerf3 public server list with country flags

### Wi-Fi Survey
- Network scanning with SSID, BSSID, channel, signal strength and security
- **Channel usage chart** with Gaussian curves, BSSID grouping and animation
- **Best channel recommendation** avoiding DFS channels
- **Power Analysis graph** — scrolling signal history with loss detection
- **Wi-Fi heatmap** for signal strength visualization
- Audio feedback (beep alarm) for signal loss events


## Requirements

### System Dependencies
- Python 3.8+
- PyQt6
- Qt6 SerialPort (optional, for advanced port detection)
- picocom (for serial connections)
- sudo / pkexec configured

### External Tools
| Tool | Feature | Required |
|------|---------|----------|
| **openssh** / `ssh` | SSH connections and SFTP file transfer | Yes |
| **samba** / `smbd` | SMB file server | Yes |
| **iperf3** | Speed Test LAN/WAN | Yes |
| **traceroute** | Traceroute hop discovery | Yes |
| **mtr** / **mtr-tiny** | MTR continuous traceroute | Yes |
| **nmcli** / **network-manager** | Wi-Fi scanning | Yes |
| **nmap** | Vulnerability Scanner | Yes |
| **iw** | Wi-Fi interface info | Yes |
| **tigervnc** / `xtigervncviewer` | VNC remote desktop (Wayland) | Optional |
| **freerdp** / `wlfreerdp` | RDP remote desktop (Wayland) | Optional |
| **fast** / **fast-cli** | Speed Test via fast.com | Optional |
| **python3-pyftpdlib** | Built-in FTP server | Optional |

Install fast-cli via npm:
```bash
npm install -g fast-cli
```

### Python Dependencies
- **pyte** — Terminal emulator (VT100/ANSI)
- **paramiko** — SSH/SFTP protocol support
- **pysnmp** — SNMP protocol support
- **standard-telnetlib** — Telnet protocol support (Python 3.13+)

> **Security Note**: Telnet transmits data without encryption, including passwords and sensitive information.
> Use SSH whenever possible. Telnet should only be used in trusted, isolated networks
> or when connecting to devices that don't support SSH.


## Installation

### Debian / Ubuntu (from .deb package)

1. Download the latest .deb package from [releases](https://github.com/benjamimgois/opengrid/releases)

2. Install the package:
```bash
sudo dpkg -i cetus_1.6-1_all.deb
sudo apt-get install -f  # Fix any missing dependencies
```

3. Launch from application menu or terminal:
```bash
cetus
```

### Debian / Ubuntu (build from source)

1. Install build dependencies:
```bash
sudo apt install debhelper dpkg-dev python3-pyqt6 picocom
```

2. Build the package:
```bash
cd scripts
chmod +x make-deb.sh
./make-deb.sh
```

3. Install the generated package:
```bash
sudo dpkg -i ../cetus_1.6-1_all.deb
```

### Arch Linux / Manjaro (from AUR)

```bash
yay -S cetus
# or
paru -S cetus
```

### Arch Linux / Manjaro (from package file)

1. Download the latest `.pkg.tar.zst` from [releases](https://github.com/benjamimgois/opengrid/releases)

2. Install:
```bash
sudo pacman -U cetus-1.6-1-any.pkg.tar.zst
```

### Flatpak

1. Install from Flathub (when available):
```bash
flatpak install flathub io.github.benjamimgois.cetus
```

2. Or build from source:
```bash
cd packaging/flatpak
flatpak-builder --install --user build io.github.benjamimgois.cetus.yml
```

3. Run:
```bash
flatpak run io.github.benjamimgois.cetus
```

### Other Linux Distributions

1. Install dependencies:
```bash
# Arch Linux / Manjaro
sudo pacman -S python-pyqt6 qt6-serialport picocom openssh samba iperf3 traceroute mtr networkmanager nmap iw tigervnc freerdp

# Fedora / RHEL
sudo dnf install python3-pyqt6 python3-pyqt6-sip picocom openssh samba iperf3 traceroute mtr NetworkManager nmap iw tigervnc freerdp

# Debian / Ubuntu
sudo apt install python3-pyqt6 python3-pyqt6.qtserialport picocom openssh-client samba samba-common-bin iperf3 traceroute mtr iw network-manager nmap tigervnc-viewer freerdp3-wayland

# Python dependencies
pip3 install pyte paramiko pysnmp

# Python 3.13+ users also need:
pip3 install standard-telnetlib
```

2. Make executable:
```bash
chmod +x cetus
```

3. (Optional) Install system-wide:
```bash
./scripts/install.sh
```


## Usage

```bash
./cetus
# or
python3 -m cetuslib
```

### Serial Connection

1. Select port type (USB or Serial toggle)
2. Choose port from the list
3. Configure baud rate and parameters
4. Click **CONNECT**
5. Enter root password when prompted

### Remote Access (SSH / Telnet / VNC / RDP)

1. Click the **Remote** tab
2. Select protocol (SSH, Telnet, VNC or RDP)
3. Enter host and port (auto-filled per protocol)
4. Enter username and password (or select SSH key)
5. (Optional) Save as profile for Quick Connect
6. Click **CONNECT**

### IP Scanner

1. Click the **IP Scan** tab
2. Enter target network (e.g. `192.168.1.0`) and subnet mask
3. Choose scan method (ICMP, TCP, UDP or ARP)
4. Click **SCAN** — button shows progress percentage
5. Export results to CSV

### SNMP Query

1. Click the **SNMP** tab
2. Enter host IP, SNMP version and community string
3. Select query type (GET, GETNEXT or WALK)
4. Enter OID (optional for WALK, defaults to `.1.3.6.1.2.1`)
5. Click **EXECUTE QUERY**

### File Transfer

1. Click the **Transfer** tab
2. Select protocol (SSH/SFTP, SMB, FTP or TFTP)
3. Choose Client or Server mode
4. Configure connection/server parameters
5. Click **CONNECT** or **START**

### picocom Commands (Serial tab)

- `Ctrl+A` `Ctrl+X` — Exit picocom
- `Ctrl+A` `Ctrl+H` — Show all picocom commands


## Permissions

To avoid password prompts for serial ports, add your user to the `dialout` group:
```bash
sudo usermod -a -G dialout $USER
```

Log out and back in to apply.


## Troubleshooting

### Port doesn't appear in list
- Check device is connected: `ls -la /dev/ttyUSB* /dev/ttyS*`
- May need to load kernel modules

### Permission denied on serial port
- Add user to dialout group (see above)

### VNC / RDP not launching
- Install `tigervnc` (for VNC) and `freerdp` (for RDP)
- On Debian/Ubuntu: `sudo apt install tigervnc-viewer freerdp3-wayland`


## Links

- **GitHub**: https://github.com/benjamimgois/opengrid
- **AUR Package**: https://aur.archlinux.org/packages/cetus
- **Flathub**: https://flathub.org/apps/io.github.benjamimgois.cetus
- **Releases**: https://github.com/benjamimgois/opengrid/releases
- **Issues**: https://github.com/benjamimgois/opengrid/issues


## License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)


## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.


## Author

Benjamim Gois
