#!/bin/bash
# Script to build self-contained AppImage for SerialCom with all dependencies

set -e

VERSION="1.0"
PKGNAME="serialcom"
ARCH="x86_64"
APPIMAGE_NAME="SerialCom-full-${ARCH}.AppImage"

echo "=== SerialCom Self-Contained AppImage Builder ==="
echo "Version: ${VERSION}"
echo ""

# Check for required tools
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required to build"
    exit 1
fi

# Clean previous build
echo "Cleaning previous build..."
rm -rf AppDir-full

# Create AppDir-full structure
echo "Creating AppDir-full structure..."
mkdir -p AppDir-full/usr/bin
mkdir -p AppDir-full/usr/share/serialcom
mkdir -p AppDir-full/usr/lib

# Install PyQt6 using pip --target (no venv needed)
echo "Installing PyQt6 to AppDir..."
# Use pip3 command if available, otherwise try python3 -m pip
if command -v pip3 &> /dev/null; then
    pip3 install --target=AppDir-full/usr/lib/python-packages PyQt6
else
    python3 -m pip install --target=AppDir-full/usr/lib/python-packages PyQt6
fi

# Copy system Python to AppDir
echo "Copying Python interpreter..."
PYTHON_BIN=$(which python3)
cp "$PYTHON_BIN" AppDir-full/usr/bin/

# Bundle Python shared libraries
echo "Bundling Python shared libraries..."
PYTHON_LIB_PATH=$(ldd "$PYTHON_BIN" | grep libpython | awk '{print $3}')
if [ -n "$PYTHON_LIB_PATH" ]; then
    cp -L "$PYTHON_LIB_PATH" AppDir-full/usr/lib/
    # Also copy any related symlinks
    PYTHON_LIB_DIR=$(dirname "$PYTHON_LIB_PATH")
    PYTHON_LIB_NAME=$(basename "$PYTHON_LIB_PATH" | sed 's/\.so.*//')
    cp -L "$PYTHON_LIB_DIR/${PYTHON_LIB_NAME}".so* AppDir-full/usr/lib/ 2>/dev/null || true
fi

# Copy picocom binary and dependencies
echo "Bundling picocom..."
if command -v picocom &> /dev/null; then
    PICOCOM_PATH=$(which picocom)
    cp "${PICOCOM_PATH}" AppDir-full/usr/bin/
    
    # Copy picocom library dependencies
    echo "Copying picocom dependencies..."
    ldd "${PICOCOM_PATH}" 2>/dev/null | grep "=> /" | awk '{print $3}' | while read lib; do
        if [ -f "$lib" ]; then
            libname=$(basename "$lib")
            # Skip system libraries that should be present everywhere
            if [[ ! $libname =~ ^(libc\.|libm\.|libdl\.|libpthread\.|librt\.) ]]; then
                cp -L "$lib" AppDir-full/usr/lib/ 2>/dev/null || true
            fi
        fi
    done
else
    echo "Warning: picocom not found, will not be bundled"
fi

# Copy application files
echo "Copying application files..."
cp serialcom AppDir-full/usr/bin/
cp arrow_down.svg AppDir-full/usr/share/serialcom/
cp serialcom.png AppDir-full/
cp serialcom.desktop AppDir-full/

# Create AppRun script
echo "Creating AppRun script..."
cat > AppDir-full/AppRun << 'APPRUN_EOF'
#!/bin/bash
# AppRun script for self-contained SerialCom AppImage

HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="${HERE}"

# Set PYTHONPATH to our pip --target installation
export PYTHONPATH="${HERE}/usr/lib/python-packages"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH}"

# Use bundled Python
exec "${HERE}/usr/bin/python3" "${HERE}/usr/bin/serialcom" "$@"
APPRUN_EOF

chmod +x AppDir-full/AppRun

# Update desktop file
echo "Updating desktop file..."
sed -i 's|Exec=.*|Exec=serialcom|' AppDir-full/serialcom.desktop
sed -i 's|Icon=.*|Icon=serialcom|' AppDir-full/serialcom.desktop

# Download appimagetool if not present
APPIMAGETOOL="appimagetool-${ARCH}.AppImage"
if [ ! -f "${APPIMAGETOOL}" ]; then
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/${APPIMAGETOOL}"
    chmod +x "${APPIMAGETOOL}"
fi

# Build AppImage
echo ""
echo "Building self-contained AppImage..."
ARCH=${ARCH} ./${APPIMAGETOOL} AppDir-full ${APPIMAGE_NAME}

# Check if build was successful
if [ $? -eq 0 ]; then
    echo ""
    echo "=== Self-Contained AppImage built successfully! ==="
    echo ""
    echo "AppImage location: ./${APPIMAGE_NAME}"
    echo "Size: $(du -h ${APPIMAGE_NAME} | cut -f1)"
    echo ""
    echo "This AppImage includes:"
    echo "  - Python 3 (from venv)"
    echo "  - PyQt6"
    echo "  - picocom (if available on build system)"
    echo "  - SerialCom application"
    echo ""
    echo "To run (minimal dependencies required):"
    echo "  chmod +x ${APPIMAGE_NAME}"
    echo "  ./${APPIMAGE_NAME}"
    echo ""
    echo "To integrate with desktop:"
    echo "  ./${APPIMAGE_NAME} --appimage-integrate"
else
    echo ""
    echo "Error: AppImage build failed"
    exit 1
fi
