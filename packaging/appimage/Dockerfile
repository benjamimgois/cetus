# Builds the Anylinux AppImage for OpenGrid inside an Ubuntu 22.04 container.
#
# WHY Ubuntu 22.04 (NOT Arch/CachyOS)?
#   Arch/CachyOS ships glibc with AVX-512 IFUNC resolvers baked into ld-linux.
#   quick-sharun bundles the host ld-linux, so AppImages built on Arch cause a
#   "trap invalid opcode" SIGILL on any CPU without AVX-512/AVX2 support.
#   Ubuntu 22.04 (glibc 2.35) compiles ld-linux for baseline x86-64, producing
#   AppImages that run on virtually any x86-64 machine.
#
# Usage (from repo root):
#   docker build -f packaging/appimage/Dockerfile -t opengrid-appimage-builder .
#   docker run --rm --cap-add SYS_PTRACE --security-opt seccomp=unconfined \
#     -v "$(pwd)/dist:/out" \
#     opengrid-appimage-builder
#
# The finished AppImage will appear in ./dist/

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget curl git strace file binutils patchelf \
    xz-utils zstd \
    python3 python3-pip python3-dev \
    libgl1 libglib2.0-0 libdbus-1-3 libegl1 \
    libfontconfig1 libfreetype6 libxcb1 libx11-6 libxext6 \
    libxrender1 libxi6 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-xinerama0 libxcb-cursor0 \
    iperf3 freerdp2-x11 \
    xvfb xauth \
    squashfs-tools \
    libfuse2 \
 && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    PyQt6 \
    paramiko \
    pyte \
    speedtest-cli \
    standard-telnetlib

# zsyncmake stub — quick-sharun calls it but we don't need delta updates
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/zsyncmake \
 && chmod +x /usr/local/bin/zsyncmake

WORKDIR /src
COPY . .

RUN bash scripts/make-anylinux-appimage.sh

CMD cp /src/OpenGrid-*.AppImage /out/ \
    && echo "AppImage copied to /out/"
