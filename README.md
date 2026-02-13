# Omnicom

[![GitHub](https://img.shields.io/badge/GitHub-benjamimgois%2Fomnicom-blue?logo=github)](https://github.com/benjamimgois/omnicom)
[![Version](https://img.shields.io/badge/version-1.3-green)](https://github.com/benjamimgois/omnicom/releases)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Easy and modern interface to manage network devices — Serial, SSH, Telnet, IP Scanner and SNMP.

<img width="3609" height="1625" alt="image" src="https://github.com/user-attachments/assets/a0cc6cd0-1954-49ba-a481-6b4779b64ff7" />

## Features

### Serial Communication
- Modern graphical interface with PyQt6
- **Embedded terminal** - No external terminal required
- Elegant and responsive design
- Automatic serial port detection with QSerialPortInfo
- Support for serial ports (/dev/ttyS*) and USB adapters (/dev/ttyUSB*)
- Complete serial parameter configuration:
  - Baud rate - 300 to 921600 bps
  - Data bits (5-8)
  - Parity (None, Even, Odd)
  - Stop bits (1-2)
  - Flow control (None, Hardware, Software)
- Quick connect profiles with per-device vendor selection
- Root password request via sudo
- Real-time bidirectional communication
- Support for picocom control sequences (Ctrl+A, Ctrl+X, etc.)

### Remote Connections
- **SSH Support** - Secure remote connections with password or key authentication
- **Telnet Support** - Connect to network devices via Telnet protocol
- Connection profile management with per-device vendor selection
- Automatic protocol detection (SSH port 22, Telnet port 23)

### Terminal Features
- VT100/ANSI terminal emulation with pyte
- **Syntax highlighting** for network equipment commands
- Support for multiple vendors: Cisco, Huawei, H3C, Juniper, D-Link, Brocade, Datacom, Fortinet
- **Vendor selection per profile** - Automatically applies syntax highlighting on connect
- **Search with scroll-to-match** - Find text in terminal output (Ctrl+F)
- **Context menu** - Right-click for copy, paste, and export options
- Adjustable font size
- Full keyboard support including special keys and control sequences

### IP Scanner
- Network host discovery with ICMP, TCP and UDP scan methods
- Configurable subnet mask, ports, timeout and threads
- Real-time results with IP, status, latency and MAC vendor detection
- Sortable results table with export to CSV
- Progress indicator on the scan button

### SNMP Queries
- SNMP GET and WALK operations (v1 and v2c)
- Real-time streaming results displayed in a sortable table (OID, Value, Type)
- Automatic SNMP value type classification (Integer, String, Counter, TimeTicks, etc.)
- Walk progress indicator on the execute button
- Limit of 1000 entries per walk to prevent UI overload

### TFTP Server
- Built-in TFTP server for firmware transfers
- Network interface auto-detection
- Configurable root directory
- Profile name banner with copy button for TFTP file names

## Requirements

### System Dependencies
- Python 3.8+
- PyQt6
- Qt6 SerialPort (optional, for advanced port detection)
- picocom (for serial connections)
- sudo configured

### Python Dependencies
- **pyte** - Terminal emulator (VT100/ANSI)
- **paramiko** - SSH protocol support (optional, for SSH connections)
- **pysnmp** - SNMP protocol support (optional, for SNMP queries)
- **standard-telnetlib** - Telnet protocol support (Python 3.13+)

> **Security Note**: Telnet transmits data without encryption, including passwords and sensitive information. 
> Use SSH whenever possible for remote connections. Telnet should only be used in trusted, isolated networks 
> or when connecting to devices that don't support SSH.

## Installation

### Debian / Ubuntu (from .deb package)

1. Download the latest .deb package from [releases](https://github.com/benjamimgois/omnicom/releases)

2. Install the package:
```bash
sudo dpkg -i omnicom_1.3-1_all.deb
sudo apt-get install -f  # Fix any missing dependencies
```

3. Launch from application menu or terminal:
```bash
omnicom
```

### Debian / Ubuntu (build from source)

1. Install build dependencies:
```bash
sudo apt install debhelper dpkg-dev python3-pyqt6 picocom
```

2. Build the package:
```bash
chmod +x make-deb.sh
./make-deb.sh
```

3. Install the generated package:
```bash
sudo dpkg -i ../omnicom_1.3-1_all.deb
```

### Arch Linux / Manjaro (from AUR)

Install using an AUR helper:
```bash
yay -S omnicom
# or
paru -S omnicom
```

### Arch Linux / Manjaro (from package file)

1. Download the latest `.pkg.tar.zst` package from [releases](https://github.com/benjamimgois/omnicom/releases)

2. Install the package:
```bash
sudo pacman -U omnicom-1.3-1-any.pkg.tar.zst
```

### Flatpak

1. Install from Flathub (when available):
```bash
flatpak install flathub io.github.benjamimgois.omnicom
```

2. Or build from source:
```bash
cd packaging/flatpak
flatpak-builder --install --user build io.github.benjamimgois.omnicom.yml
```

3. Run:
```bash
flatpak run io.github.benjamimgois.omnicom
```

### Other Linux Distributions

1. Install dependencies (if not already installed):
```bash
# Arch Linux / Manjaro
sudo pacman -S python-pyqt6 qt6-serialport picocom
pip install pyte paramiko pysnmp

# Fedora / RHEL
sudo dnf install python3-pyqt6 python3-pyqt6-sip picocom
pip3 install pyte paramiko pysnmp

# Debian / Ubuntu (manual installation)
sudo apt install python3-pyqt6 python3-pyqt6.qtserialport picocom
pip3 install pyte paramiko pysnmp

# Python 3.13+ users also need:
pip3 install standard-telnetlib
```

2. Make scripts executable:
```bash
chmod +x omnicom
```

3. (Optional) Install system-wide:
```bash
./install.sh
```

## Usage

Run the application:
```bash
# Recommended way
./omnicom

# Directly
./omnicom

# Or via Python
python3 omnicom
```

### Serial Connection

1. Select port type (Serial or USB)
2. Choose specific port from the list
3. Configure communication speed (main field)
4. Adjust other parameters as needed
5. Click "CONNECT"
6. Enter root password when prompted in the embedded terminal
7. The integrated terminal window will open with picocom running

### SSH Connection

1. Click the SSH tab (computer icon)
2. Select "SSH" protocol
3. Enter host (IP address or hostname)
4. Enter port (default: 22)
5. Enter username
6. Choose authentication method:
   - **Password**: Enter password or leave blank to be prompted
   - **SSH Key**: Browse and select your private key file
7. (Optional) Save as profile for quick access
8. Click "CONNECT SSH"

### Telnet Connection

1. Click the SSH tab (computer icon)
2. Select "Telnet" protocol
3. Enter host (IP address or hostname)
4. Enter port (default: 23)
5. Click "CONNECT TELNET"

> **Note**: Telnet does not require authentication in the UI - credentials are typically
> requested by the remote device after connection.

### IP Scanner

1. Click the IP Scan tab
2. Enter target network (e.g. 192.168.1.0)
3. Select subnet mask (default: /24)
4. Choose scan method (ICMP, TCP or UDP)
5. Click "SCAN" — the button shows progress as "Scanning X%"
6. Results appear in real-time with IP, status, latency and MAC vendor
7. Export results to CSV or right-click for options

### SNMP Query

1. Click the SNMP tab
2. Enter host IP address
3. Select SNMP version (v1 or v2c)
4. Enter community string (default: public)
5. Select query type (snmpwalk or snmpget)
6. Enter OID (optional for walk, defaults to .1.3.6.1.2.1)
7. Click "EXECUTE QUERY" — the button shows progress as "Walking X%"
8. Results stream in real-time to the table with OID, Value and Type columns

### picocom Commands

In the embedded terminal, use:
- `Ctrl+A` `Ctrl+X` - Exit picocom
- `Ctrl+A` `Ctrl+H` - Help with all commands

You can also click the "DISCONNECT" button to close the connection.

## Permissions

To avoid password prompts every time, add your user to the dialout group:
```bash
sudo usermod -a -G dialout $USER
```

After this, logout and login again to apply changes.

## Troubleshooting

### Port doesn't appear in list
- Check if the device is connected
- Run `ls -la /dev/ttyUSB* /dev/ttyS*` to see available ports
- May need to load kernel modules

### Permission denied
- Make sure you're using sudo
- Check if your user has sudo permissions
- Or add your user to dialout group (see above)

## Links

- **GitHub Repository**: https://github.com/benjamimgois/omnicom
- **AUR Package**: https://aur.archlinux.org/packages/omnicom
- **Flathub**: https://flathub.org/apps/io.github.benjamimgois.omnicom
- **Releases**: https://github.com/benjamimgois/omnicom/releases
- **Issues**: https://github.com/benjamimgois/omnicom/issues

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

Benjamim Gois
