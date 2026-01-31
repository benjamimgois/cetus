#!/bin/bash
# SerialCom installation script

echo "=== SerialCom - Installation ==="
echo ""

# Detect package manager
if command -v pacman &> /dev/null; then
    PKG_MANAGER="pacman"
    echo "Detected: Arch Linux / Manjaro"
elif command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    echo "Detected: Fedora / RHEL"
elif command -v apt &> /dev/null; then
    PKG_MANAGER="apt"
    echo "Detected: Debian / Ubuntu"
else
    echo "ERROR: Unsupported package manager."
    echo "Install manually: python3, PyQt6 and picocom"
    exit 1
fi
echo ""

# Check Python3
echo "1. Checking Python3..."
if ! command -v python3 &> /dev/null; then
    echo "   ERROR: Python3 not found."
    case $PKG_MANAGER in
        pacman) echo "   Install with: sudo pacman -S python" ;;
        dnf) echo "   Install with: sudo dnf install python3" ;;
        apt) echo "   Install with: sudo apt install python3" ;;
    esac
    exit 1
fi
echo "   ✓ Python3 found: $(python3 --version)"

# Check PyQt6
echo "2. Checking PyQt6..."
if ! python3 -c "from PyQt6.QtWidgets import QApplication" 2>/dev/null; then
    echo "   PyQt6 not found. Installing..."
    case $PKG_MANAGER in
        pacman)
            sudo pacman -S --noconfirm python-pyqt6 qt6-serialport
            ;;
        dnf)
            sudo dnf install -y python3-pyqt6 python3-pyqt6-sip
            ;;
        apt)
            sudo apt install -y python3-pyqt6 python3-pyqt6.qtserialport
            ;;
    esac
else
    echo "   ✓ PyQt6 already installed"
fi

# Install picocom
echo "3. Checking picocom..."
if ! command -v picocom &> /dev/null; then
    echo "   picocom not found. Installing..."
    case $PKG_MANAGER in
        pacman) sudo pacman -S --noconfirm picocom ;;
        dnf) sudo dnf install -y picocom ;;
        apt) sudo apt install -y picocom ;;
    esac
else
    echo "   ✓ picocom already installed: $(picocom --help | head -n1)"
fi

# Add user to dialout group
echo "4. Configuring permissions..."
if groups $USER | grep -q dialout; then
    echo "   ✓ User is already in dialout group"
else
    echo "   Adding user to dialout group..."
    sudo usermod -a -G dialout $USER
    echo "   ✓ User added to dialout group"
    echo "   IMPORTANT: Logout and login again to apply changes"
fi

# Install .desktop file
echo "5. Installing menu shortcut..."
mkdir -p ~/.local/share/applications
cp serialcom.desktop ~/.local/share/applications/
echo "   ✓ Shortcut installed at ~/.local/share/applications/"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To run the application:"
echo "  - From terminal: ./serialcom"
echo "  - From menu: Look for 'SerialCom'"
echo ""
echo "IMPORTANT: If added to dialout group now,"
echo "logout and login again to avoid password prompts."
