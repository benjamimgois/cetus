#!/bin/bash
# Script to build Debian package for Omnicom

set -e

VERSION="1.3"
PKGNAME="omnicom"

echo "=== Omnicom Debian Package Builder ==="
echo "Version: ${VERSION}"
echo ""

# Check for required tools
echo "Checking for required build tools..."
if ! command -v dpkg-buildpackage &> /dev/null; then
    echo "Error: dpkg-buildpackage not found"
    echo "Install with: sudo apt install dpkg-dev"
    exit 1
fi

if ! command -v debhelper &> /dev/null; then
    echo "Warning: debhelper not found"
    echo "Install with: sudo apt install debhelper"
    echo "Continuing anyway..."
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -f ../${PKGNAME}_${VERSION}*.deb
rm -f ../${PKGNAME}_${VERSION}*.build
rm -f ../${PKGNAME}_${VERSION}*.buildinfo
rm -f ../${PKGNAME}_${VERSION}*.changes
rm -rf debian/.debhelper
rm -rf debian/${PKGNAME}
rm -f debian/debhelper-build-stamp
rm -f debian/files

# Build package
echo ""
echo "Building Debian package..."
dpkg-buildpackage -us -uc -b

# Check if build was successful
if [ $? -eq 0 ]; then
    echo ""
    echo "=== Package built successfully! ==="
    echo ""
    echo "Package location: ../${PKGNAME}_${VERSION}-1_all.deb"
    echo ""
    echo "To install:"
    echo "  sudo dpkg -i ../${PKGNAME}_${VERSION}-1_all.deb"
    echo "  sudo apt-get install -f  # Fix any missing dependencies"
    echo ""
    echo "To inspect package:"
    echo "  dpkg-deb -c ../${PKGNAME}_${VERSION}-1_all.deb  # List contents"
    echo "  dpkg-deb -I ../${PKGNAME}_${VERSION}-1_all.deb  # Show info"
else
    echo ""
    echo "Error: Package build failed"
    exit 1
fi
