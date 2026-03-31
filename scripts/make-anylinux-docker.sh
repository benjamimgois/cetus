#!/bin/bash
# Build a portable Anylinux AppImage for OpenGrid inside an Ubuntu 22.04
# Docker/Podman container.
#
# WHY DOCKER?
#   Building on Arch/CachyOS bundles glibc 2.43 components (ld-linux, libc.so.6)
#   that internally use AVX-512 IFUNC resolvers.  CPUs without AVX-512 receive a
#   SIGILL ("invalid opcode") before any user code runs.  Furthermore, ld-linux
#   and libc.so.6 are tightly coupled — you cannot replace one without the other.
#
#   Building inside Ubuntu 22.04 (glibc 2.35) produces a coherent, baseline-safe
#   glibc pair that runs on any x86-64 CPU (including those without SSE4/AVX).
#
# USAGE:
#   bash scripts/make-anylinux-docker.sh            # auto-detect docker/podman
#   bash scripts/make-anylinux-docker.sh --podman   # force podman
#   bash scripts/make-anylinux-docker.sh --docker   # force docker
#   bash scripts/make-anylinux-docker.sh --no-cache # rebuild image from scratch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # repo root
DOCKERFILE="$SCRIPT_DIR/scripts/Dockerfile.appimage-builder"
IMAGE_TAG="opengrid-appimage-builder:latest"
NO_CACHE=""

# ── Parse arguments ────────────────────────────────────────────────────────────
FORCE_ENGINE=""
for arg in "$@"; do
    case "$arg" in
        --podman)    FORCE_ENGINE="podman" ;;
        --docker)    FORCE_ENGINE="docker" ;;
        --no-cache)  NO_CACHE="--no-cache" ;;
        --help|-h)
            echo "Usage: $0 [--docker|--podman] [--no-cache]"
            exit 0 ;;
    esac
done

# ── Detect container engine ────────────────────────────────────────────────────
_detect_engine() {
    if [ -n "$FORCE_ENGINE" ]; then
        if ! command -v "$FORCE_ENGINE" &>/dev/null; then
            echo "ERROR: $FORCE_ENGINE not found in PATH." >&2; exit 1
        fi
        echo "$FORCE_ENGINE"; return
    fi
    for _e in docker podman; do
        command -v "$_e" &>/dev/null && echo "$_e" && return
    done
    echo "ERROR: Neither docker nor podman found. Install one and try again." >&2
    echo "  Arch: sudo pacman -S docker && sudo systemctl enable --now docker" >&2
    echo "  or:   sudo pacman -S podman" >&2
    exit 1
}

ENGINE="$(_detect_engine)"
echo "=== OpenGrid Docker AppImage Builder ==="
echo "Engine  : $ENGINE"
echo "Image   : $IMAGE_TAG"
echo "Repo    : $SCRIPT_DIR"
echo ""

# ── Build the builder image ────────────────────────────────────────────────────
echo "[1/2] Building Ubuntu 22.04 builder image..."
echo "      (first run downloads ~500 MB; subsequent runs use cache)"
"$ENGINE" build $NO_CACHE \
    -t "$IMAGE_TAG" \
    -f "$DOCKERFILE" \
    "$SCRIPT_DIR/scripts"

echo ""
echo "[2/2] Running build inside container..."
echo "      Output AppImage → $SCRIPT_DIR/OpenGrid-x86_64.AppImage"
echo ""

# ── Run the build ──────────────────────────────────────────────────────────────
# --cap-add SYS_PTRACE   : required for strace (quick-sharun dep capture phase)
# --security-opt …       : allows strace to work in newer Docker/podman with seccomp
# Xvfb :99              : virtual display so Qt can initialise during strace run
# DEPLOY_PYTHON=1        : tells quick-sharun to bundle Python + site-packages
#
# The repo is bind-mounted read-only so the build script can copy source files,
# and a build output volume is mounted read-write for the generated AppImage.

"$ENGINE" run --rm \
    --cap-add SYS_PTRACE \
    --security-opt seccomp=unconfined \
    -v "$SCRIPT_DIR:/workspace:ro" \
    -v "$SCRIPT_DIR:/output:rw" \
    --tmpfs /tmp:exec,size=4G \
    -e DISPLAY=:99 \
    -e OUTPATH=/output \
    -e OUTNAME="OpenGrid-x86_64.AppImage" \
    "$IMAGE_TAG" \
    bash -c '
        set -euo pipefail

        # Start virtual display for Qt initialisation during strace
        Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
        XVFB_PID=$!
        sleep 1

        # Copy workspace to a writable area (source is mounted :ro)
        cp -a /workspace /build
        cd /build

        # Run the main build script (it auto-detects non-root, skips pacman)
        bash scripts/make-anylinux-appimage.sh

        # Copy the result to the output mount
        if ls /build/OpenGrid-*.AppImage 1>/dev/null 2>&1; then
            cp /build/OpenGrid-*.AppImage /output/
            echo ""
            echo "✓ AppImage copied to host: /output/OpenGrid-x86_64.AppImage"
        else
            echo "ERROR: No AppImage generated." >&2
            kill $XVFB_PID 2>/dev/null || true
            exit 1
        fi

        kill $XVFB_PID 2>/dev/null || true
    '

echo ""
echo "=== Build complete! ==="
if [ -f "$SCRIPT_DIR/OpenGrid-x86_64.AppImage" ]; then
    echo "AppImage : $SCRIPT_DIR/OpenGrid-x86_64.AppImage"
    echo "Size     : $(du -sh "$SCRIPT_DIR/OpenGrid-x86_64.AppImage" | cut -f1)"
    echo ""
    echo "The AppImage is built against Ubuntu 22.04 (glibc 2.35) and runs on"
    echo "any x86-64 Linux system — including CPUs without AVX2 / AVX-512."
fi
echo ""
echo "Run:  chmod +x OpenGrid-x86_64.AppImage && ./OpenGrid-x86_64.AppImage"
