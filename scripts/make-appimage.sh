#!/bin/bash
# Script to build AppImage for Omnicom

set -e

VERSION="1.0"
PKGNAME="omnicom"
ARCH="x86_64"
APPIMAGE_NAME="Omnicom-${ARCH}.AppImage"

echo "=== Omnicom AppImage Builder ==="
echo "Version: ${VERSION}"
echo ""

# Check if AppDir exists
if [ ! -d "AppDir" ]; then
    echo "Error: AppDir directory not found"
    echo "Please run this script from the omnicom directory"
    exit 1
fi

# Download appimagetool if not present
APPIMAGETOOL="appimagetool-${ARCH}.AppImage"
if [ ! -f "${APPIMAGETOOL}" ]; then
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/${APPIMAGETOOL}"
    chmod +x "${APPIMAGETOOL}"
fi

# Verify AppDir structure
echo "Verifying AppDir structure..."
if [ ! -f "AppDir/AppRun" ]; then
    echo "Error: AppDir/AppRun not found"
    exit 1
fi

if [ ! -f "AppDir/omnicom.desktop" ]; then
    echo "Error: AppDir/omnicom.desktop not found"
    exit 1
fi

if [ ! -f "AppDir/omnicom.png" ]; then
    echo "Error: AppDir/omnicom.png not found"
    exit 1
fi

# Update desktop file paths for AppImage
echo "Updating desktop file..."
sed -i 's|Exec=.*|Exec=omnicom|' AppDir/omnicom.desktop
sed -i 's|Icon=.*|Icon=omnicom|' AppDir/omnicom.desktop

# Build AppImage
echo ""
echo "Building AppImage..."
ARCH=${ARCH} ./${APPIMAGETOOL} AppDir ${APPIMAGE_NAME}

# Check if build was successful
if [ $? -eq 0 ]; then
    echo ""
    echo "=== AppImage built successfully! ==="
    echo ""
    echo "AppImage location: ./${APPIMAGE_NAME}"
    echo "Size: $(du -h ${APPIMAGE_NAME} | cut -f1)"
    echo ""
    echo "To run:"
    echo "  chmod +x ${APPIMAGE_NAME}"
    echo "  ./${APPIMAGE_NAME}"
    echo ""
    echo "To integrate with desktop:"
    echo "  ./${APPIMAGE_NAME} --appimage-integrate"
    echo ""
    echo "To extract contents:"
    echo "  ./${APPIMAGE_NAME} --appimage-extract"
else
    echo ""
    echo "Error: AppImage build failed"
    exit 1
fi
