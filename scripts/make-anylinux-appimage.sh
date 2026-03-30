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
        freerdp tigervnc iperf3 \
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

# ── 6b. Post-deploy: copy app data, extra binaries & custom AppRun ───────────

# Helper: copy a binary + ALL its transitive shared-library deps into AppDir.
# ldd resolves the full dependency closure in one call.
# Skips glibc/ld-linux (too system-critical to bundle safely).
_bundle_exe() {
    local _exe="$1"
    local _dest_bin="$APPDIR/usr/bin/$(basename "$_exe")"
    cp "$_exe" "$_dest_bin"
    chmod +x "$_dest_bin"
    # Make it findable on PATH inside the AppImage (shared/bin → usr/bin)
    local _bindir="$APPDIR/bin"
    [ -d "$_bindir" ] && \
        ln -sf "../usr/bin/$(basename "$_exe")" "$_bindir/$(basename "$_exe")" 2>/dev/null || true

    ldd "$_exe" 2>/dev/null | awk '/=> \//{print $3}' | \
    grep -v 'ld-linux\|/lib/libc\.\|/lib/libm\.\|/lib/libdl\.\|/lib/libpthread\.\|/lib/librt\.' | \
    while read _dep; do
        [ -f "$_dep" ] || continue
        local _bn
        _bn="$(basename "$_dep")"
        [ -f "$APPDIR/usr/lib/$_bn" ] || [ -f "$APPDIR/lib/$_bn" ] || \
            cp "$_dep" "$APPDIR/usr/lib/$_bn" 2>/dev/null || true
    done
}

echo "  Copying app data into AppDir..."
install -dm755 "$APPDIR/usr/share/omnicom/assets/icons"
install -dm755 "$APPDIR/usr/share/omnicom/assets/vendors"
cp "$SCRIPT_DIR/omnicom"                "$APPDIR/usr/share/omnicom/omnicom"
cp "$SCRIPT_DIR/assets/icons/"*.svg     "$APPDIR/usr/share/omnicom/assets/icons/"
cp "$SCRIPT_DIR/assets/vendors/"*.svg   "$APPDIR/usr/share/omnicom/assets/vendors/"

# ── Bundle Qt platform plugins (XCB + Wayland + themes) ──────────────────────
# The strace phase captures Qt plugin loads for the running session's display,
# but the AppImage must also run on the OTHER platform (e.g., built on Wayland
# → must still work on X11/XWayland).  Force-bundle both platforms here.
echo "  Bundling Qt platform/decoration plugins..."
for _plugin_dir in platforms platformthemes wayland-decoration-client; do
    _src="/usr/lib/qt6/plugins/$_plugin_dir"
    _dst="$APPDIR/usr/lib/qt6/plugins/$_plugin_dir"
    [ -d "$_src" ] || continue
    install -dm755 "$_dst"
    for _so in "$_src"/*.so; do
        [ -f "$_so" ] || continue
        cp "$_so" "$_dst/"
        # Bundle the plugin's own deps (skip GTK3 — always on target distro).
        ldd "$_so" 2>/dev/null | awk '/=> \//{print $3}' | \
        grep -v 'libgtk\|libgdk\|libgio\|libgobject\|libpango\|libcairo\|libgmodule\|libatk\|libepoxy' | \
        grep -v 'ld-linux\|/lib/libc\.\|/lib/libm\.' | \
        while read _dep; do
            [ -f "$_dep" ] || continue
            _bn="$(basename "$_dep")"
            [ -f "$APPDIR/usr/lib/$_bn" ] || [ -f "$APPDIR/lib/$_bn" ] || \
                cp "$_dep" "$APPDIR/usr/lib/$_bn" 2>/dev/null || true
        done
    done
done

# ── Bundle external tools via pkgforge static binaries ───────────────────────
# Using https://bin.pkgforge.dev portable static builds avoids glibc version
# mismatches when the AppImage (built on Arch) runs on older distros.
mkdir -p "$APPDIR/usr/bin"

# Map uname -m to pkgforge arch directory name
case "$ARCH" in
    x86_64)  _pkgforge_arch="x86_64-Linux" ;;
    aarch64) _pkgforge_arch="aarch64-Linux" ;;
    *)       _pkgforge_arch="${ARCH}-Linux" ;;
esac
_PKGFORGE="https://bin.pkgforge.dev/${_pkgforge_arch}"

# Download a single static binary from pkgforge; fall back to system binary.
_get_static() {
    local _name="$1"
    local _dest="$APPDIR/usr/bin/$_name"
    if wget -q "$_PKGFORGE/$_name" -O "$_dest" 2>/dev/null && \
       file "$_dest" 2>/dev/null | grep -q ELF; then
        chmod +x "$_dest"
        ln -sf "../usr/bin/$_name" "$APPDIR/bin/$_name" 2>/dev/null || true
        echo "    $_name (static/pkgforge) → AppDir/usr/bin/"
        return 0
    else
        rm -f "$_dest"
        return 1
    fi
}

echo "  Downloading static iPerf3..."
_get_static iperf3 || {
    echo "    WARNING: pkgforge download failed, falling back to system iperf3"
    _p="$(command -v iperf3 2>/dev/null)" && _bundle_exe "$_p" || \
        echo "    WARNING: iperf3 not found"
}

echo "  Downloading static FreeRDP..."
_rdp_ok=0
for _rdp_name in xfreerdp3 xfreerdp sdl-freerdp3; do
    _get_static "$_rdp_name" && { _rdp_ok=1; break; }
done
if [ "$_rdp_ok" = "0" ]; then
    echo "    pkgforge download failed, falling back to system freerdp"
    for _rdp_bin in sdl-freerdp3 xfreerdp3 wlfreerdp3 wlfreerdp xfreerdp; do
        _rdp_path="$(command -v "$_rdp_bin" 2>/dev/null)" || continue
        _bundle_exe "$_rdp_path" && _rdp_ok=1 && break
    done
    [ "$_rdp_ok" = "0" ] && echo "    WARNING: no freerdp binary found"
fi

echo "  Downloading static TigerVNC viewer..."
_vnc_ok=0
for _vnc_name in vncviewer xtigervncviewer; do
    _get_static "$_vnc_name" && { _vnc_ok=1; break; }
done
if [ "$_vnc_ok" = "0" ]; then
    echo "    pkgforge download failed, falling back to system vncviewer"
    for _vnc_bin in vncviewer xtigervncviewer; do
        _vnc_path="$(command -v "$_vnc_bin" 2>/dev/null)" || continue
        _bundle_exe "$_vnc_path" && _vnc_ok=1 && break
    done
    [ "$_vnc_ok" = "0" ] && echo "    WARNING: no VNC viewer found"
fi

# Custom AppRun — calls bundled python3 (sharun hardlink) with the omnicom script
cat > "$APPDIR/AppRun" << 'APPRUN_EOF'
#!/bin/sh
APPDIR="$(cd "${0%/*}" && echo "$PWD")"

export APPDIR
export PATH="$APPDIR/bin:$APPDIR/usr/bin:$PATH"

# Qt plugin path — needed for XCB, Wayland, platform themes
export QT_PLUGIN_PATH="$APPDIR/usr/lib/qt6/plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"

# Force X11/XWayland platform: reliable window decorations on every distro.
# Users who want native Wayland: QT_QPA_PLATFORM=wayland ./Omnicom.AppImage
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

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

# Expose bundled libs to subprocesses (iperf3, freerdp, vncviewer …).
# Prepend AFTER hooks so sharun's own lib path is already included.
export LD_LIBRARY_PATH="$APPDIR/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

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
