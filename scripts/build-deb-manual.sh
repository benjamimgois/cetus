#!/bin/bash
# Manual Debian Package Builder for Arch Linux
# This script assembles the package structure manually and uses dpkg-deb to build it.

set -e

VERSION="1.4"
PKGNAME="omnicom"
ARCH="all"
BUILD_DIR="build-deb/${PKGNAME}_${VERSION}-1_${ARCH}"

echo "=== Omnicom Manual Debian Package Builder ==="
echo "Version: ${VERSION}"
echo "Build Directory: ${BUILD_DIR}"
echo ""

# Check if running from project root
if [ ! -f "omnicom" ] || [ ! -d "assets" ]; then
    echo "Error: Please run this script from the project root directory."
    exit 1
fi

# Check for dpkg-deb
if ! command -v dpkg-deb &> /dev/null; then
    echo "Error: dpkg-deb not found."
    echo "Please install dpkg: sudo pacman -S dpkg"
    exit 1
fi

# Clean previous build
echo "Cleaning build directory..."
rm -rf build-deb

# Create directory structure
echo "Creating directory structure..."
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/512x512/apps"
mkdir -p "${BUILD_DIR}/usr/share/omnicom/icons"
mkdir -p "${BUILD_DIR}/usr/share/omnicom/vendors"
mkdir -p "${BUILD_DIR}/usr/share/doc/omnicom"

# Copy files
echo "Copying application files..."

# Main executable
cp omnicom "${BUILD_DIR}/usr/bin/"
chmod 755 "${BUILD_DIR}/usr/bin/omnicom"

# Desktop file
cp omnicom.desktop "${BUILD_DIR}/usr/share/applications/"

# App Icon
cp assets/omnicom.png "${BUILD_DIR}/usr/share/icons/hicolor/512x512/apps/"

# UI Icons
echo "Copying UI icons..."
cp assets/icons/*.svg "${BUILD_DIR}/usr/share/omnicom/icons/"

# Vendor Icons
echo "Copying vendor icons..."
cp assets/vendors/*.svg "${BUILD_DIR}/usr/share/omnicom/vendors/"

# Documentation
echo "Copying documentation..."
cp README.md "${BUILD_DIR}/usr/share/doc/omnicom/"
[ -f LICENSE ] && cp LICENSE "${BUILD_DIR}/usr/share/doc/omnicom/copyright"
[ -f docs/INTERFACE.md ] && cp docs/INTERFACE.md "${BUILD_DIR}/usr/share/doc/omnicom/"

# Control file
echo "Generating control file..."
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKGNAME}
Version: ${VERSION}-1
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Benjamim Gois <benjamimgois@example.com>
Depends: python3 (>= 3.10), python3-pyqt6, python3-pyte, python3-paramiko, picocom
Description: Modern graphical interface for serial communication
 Omnicom is a modern and elegant graphical interface for serial
 communication via picocom, with support for SSH and Telnet connections.
 It provides an easy-to-use interface for configuring serial port
 parameters and establishing remote connections.
EOF

# Calculate installed size (in KB)
INSTALLED_SIZE=$(du -s "${BUILD_DIR}/usr" | awk '{print $1}')
echo "Installed-Size: ${INSTALLED_SIZE}" >> "${BUILD_DIR}/DEBIAN/control"

# Post-installation script (if exists)
if [ -f "packaging/debian/postinst" ]; then
    cp "packaging/debian/postinst" "${BUILD_DIR}/DEBIAN/postinst"
    chmod 755 "${BUILD_DIR}/DEBIAN/postinst"
fi

# Build package
echo "Building package..."
dpkg-deb --build "${BUILD_DIR}"

echo ""
echo "=== Package build complete! ==="
echo "Output: build-deb/${PKGNAME}_${VERSION}-1_${ARCH}.deb"
