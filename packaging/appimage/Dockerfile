# Builds the Anylinux AppImage for OpenGrid inside an Arch Linux container.
#
# Usage (from repo root):
#   docker build -f packaging/appimage/Dockerfile -t opengrid-appimage-builder .
#   docker run --rm --privileged \
#     -v "$(pwd)/dist:/out" \
#     opengrid-appimage-builder
#
# The finished AppImage will appear in ./dist/

FROM archlinux:latest

# Keep the image layer cache useful for repeated builds
RUN pacman -Syu --noconfirm --needed \
        base-devel wget curl git strace \
        python python-pip \
        python-pyqt6 python-pyqt6-qt6 \
        python-paramiko python-pyte \
        qt6-base qt6-svg qt6-wayland \
        freerdp tigervnc iperf3 \
        picocom \
        xorg-server-xvfb \
    && pip install --break-system-packages standard-telnetlib speedtest-cli \
    && pacman -Scc --noconfirm

# Copy the repo into the image
WORKDIR /src
COPY . .

# Run the build
RUN bash scripts/make-anylinux-appimage.sh

# Copy result to /out (mapped from host at docker run time)
CMD cp /src/OpenGrid-*.AppImage /out/ \
    && echo "AppImage copied to /out/"
