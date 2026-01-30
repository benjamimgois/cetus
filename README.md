# SerialCom 1.0

[![GitHub](https://img.shields.io/badge/GitHub-benjamimgois%2Fserialcom-blue?logo=github)](https://github.com/benjamimgois/serialcom)
[![Version](https://img.shields.io/badge/version-1.0-green)](https://github.com/benjamimgois/serialcom/releases)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Modern and elegant graphical interface for serial communication via picocom.

<img width="549" height="626" alt="image" src="https://github.com/user-attachments/assets/d39b5111-4605-486e-8078-24ca070819bf" />


## Features

- Modern graphical interface with PyQt6
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
- Opens in system default terminal

## Requirements

- Python 3
- PyQt6
- Qt6 SerialPort (optional, for advanced port detection)
- picocom
- sudo configured

## Installation

### Debian / Ubuntu (from .deb package)

1. Download the latest .deb package from [releases](https://github.com/benjamimgois/serialcom/releases)

2. Install the package:
```bash
sudo dpkg -i serialcom_1.0-1_all.deb
sudo apt-get install -f  # Fix any missing dependencies
```

3. Launch from application menu or terminal:
```bash
serialcom
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
sudo dpkg -i ../serialcom_1.0-1_all.deb
```

### Arch Linux / Manjaro (from AUR)

Install using an AUR helper:
```bash
yay -S serialcom
# or
paru -S serialcom
```

### Arch Linux / Manjaro (from package file)

1. Download the latest `.pkg.tar.zst` package from [releases](https://github.com/benjamimgois/serialcom/releases)

2. Install the package:
```bash
sudo pacman -U serialcom-1.0-1-any.pkg.tar.zst
```

### Other Linux Distributions

1. Install dependencies (if not already installed):
```bash
# Arch Linux / Manjaro
sudo pacman -S python-pyqt6 qt6-serialport picocom

# Fedora / RHEL
sudo dnf install python3-pyqt6 python3-pyqt6-sip picocom

# Debian / Ubuntu (manual installation)
sudo apt install python3-pyqt6 python3-pyqt6.qtserialport picocom
```

2. Make scripts executable:
```bash
chmod +x serialcom
```

3. (Optional) Install system-wide:
```bash
./install.sh
```

## Usage

Run the application:
```bash
# Recommended way
./serialcom

# Directly
./serialcom

# Or via Python
python3 serialcom
```

### Configuration

1. Select port type (Serial or USB)
2. Choose specific port from the list
3. Configure communication speed (main field)
4. Adjust other parameters as needed
5. Click "CONNECT"
6. Enter root password when prompted
7. picocom terminal will open in a new window

### picocom Commands

In the picocom terminal, use:
- `Ctrl+A` `Ctrl+X` - Exit picocom
- `Ctrl+A` `Ctrl+H` - Help with all commands

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

### Terminal doesn't open
- Check if you have a terminal installed (gnome-terminal, konsole, xterm, etc.)
- Install a terminal if needed: `sudo pacman -S gnome-terminal`

## Links

- **GitHub Repository**: https://github.com/benjamimgois/serialcom
- **AUR Package**: https://aur.archlinux.org/packages/serialcom
- **Releases**: https://github.com/benjamimgois/serialcom/releases
- **Issues**: https://github.com/benjamimgois/serialcom/issues

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

Benjamim Gois
