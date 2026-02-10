# Omnicom

[![GitHub](https://img.shields.io/badge/GitHub-benjamimgois%2Fomnicom-blue?logo=github)](https://github.com/benjamimgois/omnicom)
[![Version](https://img.shields.io/badge/version-1.1-green)](https://github.com/benjamimgois/omnicom/releases)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Modern and elegant graphical interface for serial communication via picocom.

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
- Automatic detection of available ports
- Root password request via sudo
- Real-time bidirectional communication
- Support for picocom control sequences (Ctrl+A, Ctrl+X, etc.)

### Remote Connections
- **SSH Support** - Secure remote connections with password or key authentication
- **Telnet Support** - Connect to network devices via Telnet protocol
- Connection profile management for quick access
- Automatic protocol detection (SSH port 22, Telnet port 23)

### Terminal Features
- VT100/ANSI terminal emulation with pyte
- Syntax highlighting for network equipment commands
- Support for multiple vendors: Cisco, Huawei, H3C, Juniper, D-Link, Brocade, Datacom, Fortinet
- Adjustable font size
- Full keyboard support including special keys and control sequences

### TFTP Server
- Built-in TFTP server for firmware transfers
- Network interface selection
- Configurable root directory

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
- **standard-telnetlib** - Telnet protocol support (Python 3.13+)

> **Security Note**: Telnet transmits data without encryption, including passwords and sensitive information. 
> Use SSH whenever possible for remote connections. Telnet should only be used in trusted, isolated networks 
> or when connecting to devices that don't support SSH.

## Installation

### Debian / Ubuntu (from .deb package)

1. Download the latest .deb package from [releases](https://github.com/benjamimgois/omnicom/releases)

2. Install the package:
```bash
sudo dpkg -i omnicom_1.1-1_all.deb
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
sudo dpkg -i ../omnicom_1.1-1_all.deb
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
sudo pacman -U omnicom-1.1-1-any.pkg.tar.zst
```

### Other Linux Distributions

1. Install dependencies (if not already installed):
```bash
# Arch Linux / Manjaro
sudo pacman -S python-pyqt6 qt6-serialport picocom
pip install pyte paramiko

# Fedora / RHEL
sudo dnf install python3-pyqt6 python3-pyqt6-sip picocom
pip3 install pyte paramiko

# Debian / Ubuntu (manual installation)
sudo apt install python3-pyqt6 python3-pyqt6.qtserialport picocom
pip3 install pyte paramiko

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
- **Releases**: https://github.com/benjamimgois/omnicom/releases
- **Issues**: https://github.com/benjamimgois/omnicom/issues

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

Benjamim Gois
