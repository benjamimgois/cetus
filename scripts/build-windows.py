#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for Windows executable using PyInstaller.

Usage:
    python build-windows.py

Requirements:
    pip install pyinstaller pyqt6 pyserial psutil paramiko pysnmp pyte
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Configuration
APP_NAME = "Cetus"
APP_VERSION = "1.8"
SCRIPT_NAME = "cetus"
ICON_NAME = "assets/icons/cetus-256.png"

# Directories
BASE_DIR = Path(__file__).parent.absolute()
BUILD_DIR = BASE_DIR / "build-windows"
DIST_DIR = BASE_DIR / "dist-windows"
SPEC_DIR = BASE_DIR / "spec-windows"

# Assets to include
ASSETS = [
    ("assets", "assets"),
    ("assets/icons", "assets/icons"),
    ("assets/vendors", "assets/vendors"),
    ("assets/screenshots", "assets/screenshots"),
]

# Hidden imports (modules that PyInstaller might miss)
HIDDEN_IMPORTS = [
    "pyte",
    "pyte.screens",
    "pyte.streams",
    "pyte.charsets",
    "pyte.graphics",
    "pyte.modes",
    "paramiko",
    "paramiko.transport",
    "paramiko.channel",
    "paramiko.sftp_client",
    "paramiko.rsakey",
    "paramiko.ecdsakey",
    "paramiko.ed25519key",
    "pysnmp",
    "pysnmp.hlapi",
    "pysnmp.hlapi.v3arch",
    "pysnmp.hlapi.v3arch.asyncio",
    "pysnmp.entity.rfc3413.oneliner",
    "psutil",
    "serial",
    "serial.tools.list_ports",
    "PyQt6.QtSerialPort",
    "PyQt6.QtMultimedia",
    "PyQt6.sip",
]

# Binary hooks (exclude unnecessary Qt plugins to reduce size)
EXCLUDES = [
    "PyQt6.Qt3DAnimation",
    "PyQt6.Qt3DCore",
    "PyQt6.Qt3DExtras",
    "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic",
    "PyQt6.Qt3DRender",
    "PyQt6.QtBluetooth",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtLocation",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.QtQuick3D",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtSensors",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtTextToSpeech",
    "PyQt6.QtWebChannel",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebSockets",
    "PyQt6.QtXml",
    "PyQt6.QtXmlPatterns",
    "matplotlib",
    "numpy",
    "pandas",
    "PIL",
    "scipy",
    "sklearn",
    "tensorflow",
    "torch",
]


def clean_directories():
    """Remove previous build artifacts."""
    for d in [BUILD_DIR, DIST_DIR, SPEC_DIR]:
        if d.exists():
            print(f"Removing {d}...")
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)


def verify_script():
    """Check that the main script exists."""
    script_path = BASE_DIR / SCRIPT_NAME
    if not script_path.exists():
        print(f"ERROR: {script_path} not found!")
        sys.exit(1)
    return str(script_path)


def build_executable():
    """Run PyInstaller to build the executable."""
    script_path = verify_script()
    icon_path = BASE_DIR / ICON_NAME
    if not icon_path.exists():
        print(f"WARNING: Icon {icon_path} not found, building without icon")
        icon_arg = []
    else:
        icon_arg = ["--icon", str(icon_path)]

    # Build command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(SPEC_DIR),
        "--noconfirm",
        "--clean",
        # We use --onedir for faster startup and smaller size
        # Use --onefile if you prefer a single executable
        "--onedir",
        "--windowed",  # No console window on Windows
    ]

    # Add icon
    cmd.extend(icon_arg)

    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Add excluded modules
    for exc in EXCLUDES:
        cmd.extend(["--exclude-module", exc])

    # Add data files (assets)
    for src, dst in ASSETS:
        src_path = BASE_DIR / src
        if src_path.exists():
            # PyInstaller syntax: source;destination
            cmd.extend(["--add-data", f"{src_path}{os.pathsep}{dst}"])
        else:
            print(f"WARNING: Asset {src_path} not found, skipping")

    # Add the main script
    cmd.append(script_path)

    print("Running PyInstaller...")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print("\nERROR: PyInstaller build failed!")
        sys.exit(1)

    print("\nBuild completed successfully!")
    print(f"Output directory: {DIST_DIR / APP_NAME}")


def create_shortcut():
    """Create a Windows shortcut (.lnk) for the application."""
    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        print("Note: winshell/pywin32 not installed, skipping shortcut creation")
        print("Install with: pip install winshell pywin32")
        return

    exe_path = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    if not exe_path.exists():
        print(f"WARNING: {exe_path} not found, skipping shortcut")
        return

    desktop = Path(winshell.desktop())
    shortcut_path = desktop / f"{APP_NAME}.lnk"

    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(exe_path)
    shortcut.WorkingDirectory = str(exe_path.parent)
    shortcut.IconLocation = str(exe_path)
    shortcut.save()

    print(f"Desktop shortcut created: {shortcut_path}")


def main():
    print(f"=== {APP_NAME} v{APP_VERSION} Windows Build ===\n")

    # Verify we're on Windows or at least have PyInstaller
    if sys.platform != 'win32':
        print("WARNING: This script is intended for Windows builds.")
        print("Cross-compilation from Linux to Windows is not supported.")
        print("Please run this script on a Windows machine with Python installed.\n")
        # Continue anyway for testing

    clean_directories()
    build_executable()

    if sys.platform == 'win32':
        create_shortcut()

    print(f"\n✅ {APP_NAME} built successfully!")
    print(f"   Location: {DIST_DIR / APP_NAME}")
    print(f"   Executable: {DIST_DIR / APP_NAME / (APP_NAME + '.exe')}")
    print("\nNext steps:")
    print("  1. Test the executable on a clean Windows machine")
    print("  2. Create an installer using Inno Setup or NSIS if needed")
    print("  3. Sign the executable with a code signing certificate")


if __name__ == "__main__":
    main()
