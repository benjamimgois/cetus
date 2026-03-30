#!/bin/bash
# Build a truly portable Anylinux AppImage for Omnicom using quick-sharun.
#
# Uses: https://pkgforge-dev.github.io/Anylinux-AppImages/
#
# Can be run as normal user on Arch/CachyOS if all Python deps are already
# installed system-wide. Pass --root to also install packages via sudo.
#
# Usage:
#   bash scripts/make-anylinux-appimage.sh          # non-root (deps pre-installed)
#   sudo bash scripts/make-anylinux-appimage.sh     # root (installs deps)

set -eux

ARCH="$(uname -m)"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # repo root

VERSION="$(grep -oP '(?<=^VERSION = \")[^\"]+' "$SCRIPT_DIR/omnicom" || echo "1.0")"
OUTNAME="Omnicom-${ARCH}.AppImage"

QUICK_SHARUN_URL="https://raw.githubusercontent.com/pkgforge-dev/Anylinux-AppImages/refs/heads/main/useful-tools/quick-sharun.sh"
GET_DEBLOATED_URL="https://raw.githubusercontent.com/pkgforge-dev/Anylinux-AppImages/refs/heads/main/useful-tools/get-debloated-pkgs.sh"

BUILD_DIR="$SCRIPT_DIR/build-anylinux"
APPDIR="$BUILD_DIR/AppDir"

echo "=== Omnicom Anylinux AppImage Builder ==="
echo "Version : $VERSION"
echo "Arch    : $ARCH"
echo "Build   : $BUILD_DIR"
echo ""

# ── 1. Optional: install system dependencies (requires root) ─────────────────
if [ "$(id -u)" = "0" ] && command -v pacman &>/dev/null; then
    echo "[1/7] Installing system dependencies via pacman..."
    pacman -Syu --noconfirm --needed \
        base-devel wget curl git strace \
        python python-pip \
        python-pyqt6 python-pyqt6-qt6 \
        python-paramiko python-pyte \
        qt6-base qt6-svg qt6-wayland \
        picocom xorg-server-xvfb
    pip install --break-system-packages standard-telnetlib speedtest-cli 2>/dev/null || true
else
    echo "[1/7] Skipping pacman install (not root) — verifying installed deps..."
    for dep in PyQt6 paramiko pyte; do
        python3 -c "import $dep" 2>/dev/null || { echo "ERROR: python3 $dep not found. Install it first."; exit 1; }
    done
    python3 -c "import speedtest" 2>/dev/null || pip install --break-system-packages speedtest-cli 2>/dev/null || true
    echo "  All Python deps OK"
fi

# ── 2. Prepare build directory ────────────────────────────────────────────────
echo "[2/7] Preparing build directory..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# zsyncmake is required by quick-sharun but only needed for delta updates.
# If not installed, create a no-op stub so the build still works locally.
if ! command -v zsyncmake &>/dev/null; then
    mkdir -p "$BUILD_DIR/tools"
    printf '#!/bin/sh\nexit 0\n' > "$BUILD_DIR/tools/zsyncmake"
    chmod +x "$BUILD_DIR/tools/zsyncmake"
    export PATH="$BUILD_DIR/tools:$PATH"
fi

# ── 3. Compile the native C launcher ─────────────────────────────────────────
# quick-sharun needs a real ELF binary as the entry point (not a Python script).
# The launcher resolves paths relative to its own location:
#
#   During strace (system paths):
#     /tmp/.../launcher → bin at /tmp/.../bin → appdir = /tmp/...
#     python3 = /tmp/.../bin/python3  (or falls back to PATH /usr/bin/python3)
#     script  = /tmp/.../usr/share/omnicom/omnicom
#
#   Inside AppDir (mounted AppImage):
#     AppDir/shared/bin/omnicom → dirname x2 → AppDir
#     python3 = AppDir/bin/python3   (sharun hardlink → bundled Python)
#     script  = AppDir/usr/share/omnicom/omnicom
echo "[3/7] Compiling native launcher..."

cat > "$BUILD_DIR/omnicom-launcher.c" << 'LAUNCHER_EOF'
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <libgen.h>

int main(int argc, char *argv[])
{
    char self[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", self, PATH_MAX - 1);
    if (len < 0) { perror("readlink /proc/self/exe"); return 1; }
    self[len] = '\0';

    /* shared/bin/omnicom  →  dirname x2  →  AppDir root  */
    char *p1 = strdup(self);
    char *bin_dir    = strdup(dirname(p1));      /* …/shared/bin   */
    char *shared_dir = strdup(dirname(bin_dir)); /* …/shared       */
    char *app_dir    = strdup(dirname(shared_dir)); /* AppDir root */
    free(p1);

    char python[PATH_MAX], script[PATH_MAX];
    snprintf(python, PATH_MAX, "%s/bin/python3",               app_dir);
    snprintf(script, PATH_MAX, "%s/usr/share/omnicom/omnicom", app_dir);
    free(bin_dir); free(shared_dir); free(app_dir);

    char **new_argv = malloc((argc + 2) * sizeof(char *));
    if (!new_argv) return 1;
    new_argv[0] = python;
    new_argv[1] = script;
    for (int i = 1; i < argc; i++) new_argv[i + 1] = argv[i];
    new_argv[argc + 1] = NULL;

    /* Try bundled python3; fall back to PATH if not accessible. */
    if (access(python, X_OK) == 0) {
        execv(python, new_argv);
    }
    /* Fallback: shift new_argv to skip python path, use execvp */
    new_argv[0] = "python3";
    execvp("python3", new_argv);
    perror("execvp python3");
    return 1;
}
LAUNCHER_EOF

gcc -O2 -o "$BUILD_DIR/omnicom-bin" "$BUILD_DIR/omnicom-launcher.c"
echo "  Compiled: $BUILD_DIR/omnicom-bin ($(file "$BUILD_DIR/omnicom-bin" | cut -d: -f2 | xargs))"

# ── 4. Stage app files in a local prefix (replaces system install) ────────────
# quick-sharun traces the binary from its real location, so we set up a local
# staging tree under BUILD_DIR/prefix and tell the launcher where to find things.
echo "[4/7] Staging app files..."

PREFIX="$BUILD_DIR/prefix"
mkdir -p "$PREFIX/usr/bin"
mkdir -p "$PREFIX/usr/share/omnicom/assets/icons"
mkdir -p "$PREFIX/usr/share/omnicom/assets/vendors"
mkdir -p "$PREFIX/usr/share/applications"
mkdir -p "$PREFIX/usr/share/icons/hicolor/256x256/apps"

cp "$BUILD_DIR/omnicom-bin"              "$PREFIX/usr/bin/omnicom"
cp "$SCRIPT_DIR/omnicom"                 "$PREFIX/usr/share/omnicom/omnicom"
cp "$SCRIPT_DIR/assets/icons/"*.svg      "$PREFIX/usr/share/omnicom/assets/icons/"
cp "$SCRIPT_DIR/assets/vendors/"*.svg    "$PREFIX/usr/share/omnicom/assets/vendors/"
cp "$SCRIPT_DIR/omnicom.desktop"         "$PREFIX/usr/share/applications/omnicom.desktop"

# Icon: use PNG from assets if available
if [ -f "$SCRIPT_DIR/assets/omnicom.png" ]; then
    cp "$SCRIPT_DIR/assets/omnicom.png" \
       "$PREFIX/usr/share/icons/hicolor/256x256/apps/omnicom.png"
else
    # Convert SVG to PNG as fallback
    _svg=$(ls "$SCRIPT_DIR/assets/icons/omnicom"*.svg 2>/dev/null | head -1)
    if [ -n "$_svg" ]; then
        rsvg-convert -w 256 -h 256 "$_svg" \
            -o "$PREFIX/usr/share/icons/hicolor/256x256/apps/omnicom.png" 2>/dev/null || \
        cp "$_svg" "$PREFIX/usr/share/icons/hicolor/256x256/apps/omnicom.png"
    fi
fi

# ── 5. Download quick-sharun ──────────────────────────────────────────────────
echo "[5/7] Downloading quick-sharun tools..."
wget -q "$QUICK_SHARUN_URL"  -O "$BUILD_DIR/quick-sharun"
wget -q "$GET_DEBLOATED_URL" -O "$BUILD_DIR/get-debloated-pkgs.sh"
chmod +x "$BUILD_DIR/quick-sharun" "$BUILD_DIR/get-debloated-pkgs.sh"

# ── 6. Deploy with quick-sharun ───────────────────────────────────────────────
# Pass the C launcher binary. quick-sharun uses strace to trace its execution
# (which forks python3 → loads PyQt6 / Qt6 / etc.) and bundles all libraries.
# DEPLOY_PYTHON=1 copies the full system Python + all installed packages.
echo "[6/7] Deploying with quick-sharun (strace phase — may take a few minutes)..."

export APPDIR
export ICON="$PREFIX/usr/share/icons/hicolor/256x256/apps/omnicom.png"
export DESKTOP="$PREFIX/usr/share/applications/omnicom.desktop"
export OUTPATH="$SCRIPT_DIR"
export OUTNAME
export DEPLOY_PYTHON=1
export DEPLOY_QT=1
export DEPLOY_OPENGL=1
export MAIN_BIN="omnicom"
# Tell lib4bin where to find libraries
export LIB_DIR=/usr/lib

# Use existing display (we're in a graphical session)
# The C launcher will exec python3 → omnicom --help, giving strace all Qt libs
_DISPLAY="${DISPLAY:-:0}"
_WAYLAND="${WAYLAND_DISPLAY:-}"

# If we have a display, strace will see Qt initialise and load all .so files
if [ -n "$_DISPLAY" ] || [ -n "$_WAYLAND" ]; then
    export DISPLAY="$_DISPLAY"
    export WAYLAND_DISPLAY="$_WAYLAND"
fi

cd "$BUILD_DIR"

# quick-sharun syntax: binary [-- strace-args]
# We trace the launcher which calls: python3 <script> --help
"$BUILD_DIR/quick-sharun" "$PREFIX/usr/bin/omnicom" -- \
    "$PREFIX/usr/bin/omnicom" --help 2>/dev/null || \
"$BUILD_DIR/quick-sharun" "$PREFIX/usr/bin/omnicom"

# ── 6b. Post-deploy: copy app data, Qt plugins & custom AppRun ───────────────
echo "  Copying app data into AppDir..."

install -dm755 "$APPDIR/usr/share/omnicom/assets/icons"
install -dm755 "$APPDIR/usr/share/omnicom/assets/vendors"
cp "$SCRIPT_DIR/omnicom"                "$APPDIR/usr/share/omnicom/omnicom"
cp "$SCRIPT_DIR/assets/icons/"*.svg     "$APPDIR/usr/share/omnicom/assets/icons/"
cp "$SCRIPT_DIR/assets/vendors/"*.svg   "$APPDIR/usr/share/omnicom/assets/vendors/"

# Bundle Qt platform-theme and Wayland decoration plugins that strace may miss
# (they are dlopen-ed at runtime by Qt and need to be in the AppDir).
echo "  Bundling Qt platform/decoration plugins..."
for _plugin_dir in platformthemes wayland-decoration-client; do
    _src="/usr/lib/qt6/plugins/$_plugin_dir"
    _dst="$APPDIR/usr/lib/qt6/plugins/$_plugin_dir"
    [ -d "$_src" ] || continue
    install -dm755 "$_dst"
    for _so in "$_src"/*.so; do
        cp "$_so" "$_dst/"
        # Copy direct shared-library deps that are NOT already bundled.
        # GTK3 libs are intentionally skipped — they are always present on
        # the target system and bundling them causes version conflicts.
        ldd "$_so" 2>/dev/null | awk '/=> \/(usr|lib)/{print $3}' | \
        grep -v 'libgtk\|libgdk\|libgio\|libgobject\|libglib\|libpango\|libcairo\|libgmodule\|libatk\|libepoxy' | \
        while read _dep; do
            [ -f "$_dep" ] || continue
            _bn="$(basename "$_dep")"
            [ -f "$APPDIR/usr/lib/$_bn" ] || \
            [ -f "$APPDIR/lib/$_bn" ]     || \
            cp "$_dep" "$APPDIR/usr/lib/$_bn" 2>/dev/null || true
        done
    done
done

# Custom AppRun — calls bundled python3 (sharun hardlink) with the omnicom script
cat > "$APPDIR/AppRun" << 'APPRUN_EOF'
#!/bin/sh
APPDIR="$(cd "${0%/*}" && echo "$PWD")"

export APPDIR
export PATH="$APPDIR/bin:$PATH"

# Qt plugin path — needed for platform theme and decoration plugins
export QT_PLUGIN_PATH="$APPDIR/usr/lib/qt6/plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"

# Window decoration: prefer adwaita CSD on Wayland; gtk3 theme on X11
export QT_WAYLAND_DECORATION="${QT_WAYLAND_DECORATION:-adwaita}"
export QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-gtk3}"

# Run any deployed hooks
for _hook in "$APPDIR"/bin/*.hook; do
    [ -x "$_hook" ] || continue
    case "$_hook" in
        *.src.hook) continue ;;
        *.bg.hook)  "$_hook" & ;;
        *.hook)     "$_hook"   ;;
    esac
done
for _hook in "$APPDIR"/bin/*.src.hook; do
    [ -e "$_hook" ] || continue
    . "$_hook"
done

exec "$APPDIR/bin/python3" \
     "$APPDIR/usr/share/omnicom/omnicom" "$@"
APPRUN_EOF
chmod +x "$APPDIR/AppRun"

# ── 7. Build the AppImage ─────────────────────────────────────────────────────
echo "[7/7] Building AppImage..."
"$BUILD_DIR/quick-sharun" --make-appimage

echo ""
echo "=== Done! ==="
echo ""
echo "AppImage : $SCRIPT_DIR/$OUTNAME"
if [ -f "$SCRIPT_DIR/$OUTNAME" ]; then
    echo "Size     : $(du -sh "$SCRIPT_DIR/$OUTNAME" | cut -f1)"
fi
echo ""
echo "Run:"
echo "  chmod +x $OUTNAME && ./$OUTNAME"
