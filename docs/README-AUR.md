# SerialCom

Modern graphical interface for serial communication via picocom.

## Features

- **Modern PyQt6 Interface** with elegant design
- **Automatic Port Detection** for serial and USB devices
- **Complete Configuration** of communication parameters
- **Baud Rates** from 300 to 921600 bps
- **Full Serial Control** (data bits, parity, stop bits, flow control)
- **picocom Integration** via system terminal

## Installation

### From AUR

```bash
yay -S serialcom
# or
paru -S serialcom
```

### Manual Installation

```bash
git clone https://aur.archlinux.org/serialcom.git
cd serialcom
makepkg -si
```

## Usage

Simply run:

```bash
serialcom
```

Or launch from your application menu.

## Configuration

1. Select port type (Serial/USB/All Ports)
2. Choose specific port from the list
3. Set baud rate (highlighted field)
4. Adjust other parameters as needed
5. Click CONNECT
6. Enter root password when prompted
7. picocom terminal opens in a new window

## Permissions

To avoid entering password every time, add your user to the `dialout` group:

```bash
sudo usermod -a -G dialout $USER
```

Then logout and login again.

## Dependencies

- python
- python-pyqt6
- qt6-serialport
- picocom
- sudo

## Optional Dependencies

- gnome-terminal (or any other terminal emulator)

## License

MIT

## Links

- GitHub: https://github.com/benjamimgois/serialcom
- AUR: https://aur.archlinux.org/packages/serialcom
