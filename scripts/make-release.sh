#!/bin/bash
# Script to prepare Omnicom for AUR submission

set -e

VERSION="1.0"
PKGNAME="omnicom"
BUILD_DIR="/tmp/${PKGNAME}-build"

echo "=== Omnicom Release Builder ==="
echo "Version: ${VERSION}"
echo ""

# Clean previous build
if [ -d "${BUILD_DIR}" ]; then
    echo "Cleaning previous build..."
    rm -rf "${BUILD_DIR}"
fi

# Create build directory
echo "Creating build directory..."
mkdir -p "${BUILD_DIR}/${PKGNAME}-${VERSION}"

# Copy necessary files
echo "Copying files..."
cp omnicom "${BUILD_DIR}/${PKGNAME}-${VERSION}/"
cp omnicom "${BUILD_DIR}/${PKGNAME}-${VERSION}/"
cp omnicom.png "${BUILD_DIR}/${PKGNAME}-${VERSION}/"
cp omnicom.desktop "${BUILD_DIR}/${PKGNAME}-${VERSION}/"
cp README.md "${BUILD_DIR}/${PKGNAME}-${VERSION}/"
cp INTERFACE.md "${BUILD_DIR}/${PKGNAME}-${VERSION}/"
cp LICENSE "${BUILD_DIR}/${PKGNAME}-${VERSION}/"

# Create tarball
echo "Creating tarball..."
cd "${BUILD_DIR}"
tar -czf "${PKGNAME}-${VERSION}.tar.gz" "${PKGNAME}-${VERSION}/"

# Calculate checksum
echo ""
echo "=== Package created ==="
echo "Location: ${BUILD_DIR}/${PKGNAME}-${VERSION}.tar.gz"
echo ""
echo "SHA256 checksum:"
sha256sum "${PKGNAME}-${VERSION}.tar.gz"
echo ""

# Copy to current directory
cp "${PKGNAME}-${VERSION}.tar.gz" "${OLDPWD}/"
echo "Tarball copied to: ${OLDPWD}/${PKGNAME}-${VERSION}.tar.gz"

# Generate .SRCINFO if makepkg is available
if command -v makepkg &> /dev/null; then
    echo ""
    echo "Generating .SRCINFO..."
    cd "${OLDPWD}"
    makepkg --printsrcinfo > .SRCINFO
    echo ".SRCINFO generated successfully"
else
    echo ""
    echo "Warning: makepkg not found. Please generate .SRCINFO manually with:"
    echo "  makepkg --printsrcinfo > .SRCINFO"
fi

# Clean up
rm -rf "${BUILD_DIR}"

echo ""
echo "=== Release ready! ==="
echo ""
echo "Next steps:"
echo "1. Upload ${PKGNAME}-${VERSION}.tar.gz to GitHub releases"
echo "2. Update PKGBUILD with the download URL"
echo "3. Update PKGBUILD sha256sums with the checksum above"
echo "4. Test with: makepkg -si"
echo "5. Submit to AUR following AUR-INSTRUCTIONS.md"
