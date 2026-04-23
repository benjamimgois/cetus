# OpenGrid — Agent Context File

> This file is intended for AI agents and automated tooling. It describes the project architecture, conventions, and workflows so agents can make safe, useful changes.

---

## 1. What is OpenGrid?

OpenGrid is a **desktop GUI application for Linux** that provides an easy, modern interface to manage network devices. It targets network engineers and system administrators who need serial, SSH, Telnet, VNC, RDP, SNMP, file transfer, speed tests, Wi-Fi surveys, and network discovery tools in a single PyQt6 application.

- **Language**: Python 3.8+
- **GUI Framework**: PyQt6 (Qt6)
- **License**: GPL-3.0
- **Repository**: https://github.com/benjamimgois/opengrid
- **Current Version**: 1.7

---

## 2. Architecture Overview

### 2.1 Single-File Monolith

The entire application logic lives in a single executable Python file:

- **`opengrid`** (≈27k lines) — Main application entrypoint and all modules.

This is by design for easy distribution (AppImage, .deb, AUR). All classes, workers, widgets, and protocol handlers are defined in this file.

### 2.2 Key Classes

| Class | Line (approx) | Responsibility |
|-------|--------------|----------------|
| `SerialTerminalGUI` | ~13472 | Main window (QMainWindow). Hosts tabs, menu bar, and global state. |
| `TerminalWidget` | ~931 | VT100/ANSI terminal emulator using `pyte`. Supports scrollback, search, syntax highlighting, autocomplete, and cursor overlay. |
| `TerminalDialog` | ~9862 | Dialog window embedding a `TerminalWidget` for serial/SSH/Telnet sessions. |
| `TerminalTabbedWindow` | ~13026 | Detachable tabbed terminal window for multi-session management. |
| `ConfigManager` | ~584 | JSON-based settings persistence (XDG Base Directory). Handles serial/SSH profiles, SNMP community history, and quick notes. |
| `ScanWorker` | ~2501 | IP scanner worker (ICMP/TCP/UDP/ARP). |
| `ConnectionWorker` | ~3097 | SSH/Telnet connection worker using `paramiko` / `telnetlib`. |
| `TracerouteWorker` | ~3176 | Traceroute execution worker. |
| `MtrWorker` | ~4004 | MTR continuous traceroute worker. |
| `Iperf3Worker` | ~4325 | iPerf3 throughput test worker. |
| `SpeedTestWorker` | ~4580 | Internet speed test worker (fast.com / iPerf3). |
| `WifiChannelChart` | ~5522 | Custom QWidget rendering channel usage with Gaussian curves. |
| `WifiHeatmapWidget` | ~6418 | Wi-Fi signal strength heatmap visualization. |
| `FileConnectWorker` | ~6624 | SFTP connection worker. |
| `FileListWorker` | ~6658 | SFTP file listing worker. |
| `FileTransferWorker` | ~6692 | SFTP upload/download worker. |
| `NmapDiscoverWorker` | ~3466 | Nmap OS/service discovery worker. |
| `VendorConfigTemplateDialog` | ~8651 | Dialog with vendor-specific command reference and config templates. |

### 2.3 Threading Model

- **Main Thread**: Qt GUI event loop, all QWidget updates.
- **Worker Threads**: `QThread` subclasses perform I/O (SSH, serial, scans, file transfers).
- Workers communicate with UI via Qt signals (`pyqtSignal`).
- `TerminalWidget` uses a `threading.Lock` (`_pyte_lock`) to protect `pyte` screen/stream state when the worker thread writes bytes and the main thread renders.

**⚠️ Important**: Never update QWidget state directly from a worker thread. Always use signals/slots or `QMetaObject.invokeMethod`.

### 2.4 Configuration & State

- **Config path**: `~/.config/opengrid/settings.json` (XDG compliant).
- **ConfigManager** merges defaults with loaded JSON on startup.
- Profiles (SSH, serial) are stored as JSON strings inside the settings dict (legacy reason: flat JSON structure).
- Passwords in profiles are **base64-encoded only** — not encrypted. This is a known limitation.

---

## 3. Technology Stack

### 3.1 Core Dependencies

| Dependency | Purpose |
|------------|---------|
| `PyQt6` | GUI framework (widgets, timers, threads, serial port info) |
| `pyte` | VT100/ANSI terminal emulation in `TerminalWidget` |
| `paramiko` | SSH/SFTP client protocol |
| `pysnmp` | SNMP GET/GETNEXT/WALK queries |
| `standard-telnetlib` | Telnet protocol (Python 3.13+) |

### 3.2 System / External Tools

Many features spawn external processes. The app expects these binaries in `$PATH`:

| Tool | Feature | Required? |
|------|---------|-----------|
| `picocom` | Serial terminal backend | Yes |
| `ssh` | SSH proxy / external sessions | Yes |
| `smbd` / `samba` | SMB file server | Yes |
| `iperf3` | LAN/WAN speed test | Yes |
| `traceroute` | Route discovery | Yes |
| `mtr` / `mtr-tiny` | Continuous traceroute | Yes |
| `nmcli` / `NetworkManager` | Wi-Fi scanning | Yes |
| `nmap` | Vulnerability scanner | Yes |
| `iw` | Wi-Fi interface info | Yes |
| `xtigervncviewer` | VNC viewer (Wayland) | Optional |
| `wlfreerdp` / `xfreerdp` | RDP client (Wayland) | Optional |
| `fast-cli` | fast.com speed test | Optional |
| `python3-pyftpdlib` | Built-in FTP server | Optional |

### 3.3 Build / Packaging

| Script | Purpose |
|--------|---------|
| `scripts/make-deb.sh` | Build Debian `.deb` package |
| `scripts/build-deb-manual.sh` | Manual deb build |
| `scripts/make-release.sh` | Generate release tarball |
| `scripts/make-anylinux-appimage.sh` | Build AppImage |
| `scripts/make-anylinux-docker.sh` | Docker-based AppImage build |
| `scripts/install.sh` | System-wide installation script |

Additional packaging:
- `debian/` — Debian packaging metadata.
- `packaging/flatpak/` — Flatpak manifest.
- `PKGBUILD` — Arch Linux AUR package.

---

## 4. Project Structure

```
opengrid/
├── opengrid                  ← Main application (Python executable, ~27k lines)
├── opengrid.desktop          ← Linux .desktop launcher
├── appinfo                   ← AppStream / app metadata
├── README.md                 ← Human-facing documentation
├── LICENSE                   ← GPL-3.0
│
├── assets/
│   ├── icons/                ← SVG icons (opengrid_icon.svg, etc.)
│   └── remmina/              ← Remmina integration assets
│
├── scripts/                  ← Build and packaging scripts
│   ├── make-deb.sh
│   ├── make-release.sh
│   ├── make-anylinux-appimage.sh
│   └── install.sh
│
├── packaging/
│   └── flatpak/
│       └── io.github.benjamimgois.opengrid.yml
│
├── debian/                   ← Debian package metadata
├── build-anylinux/           ← AppImage build artifacts
├── docs/
│   ├── INTERFACE.md          ← UI layout guide
│   ├── NEXT-STEPS.md         ← Release checklist
│   ├── AUR-INSTRUCTIONS.md   ← AUR packaging guide
│   └── README-AUR.md
│
└── .github/                  ← GitHub workflows/templates
```

---

## 5. How to Run / Develop

### 5.1 Quick Run (from source)

```bash
# Install system dependencies (Debian/Ubuntu example)
sudo apt install python3-pyqt6 python3-pyqt6.qtserialport picocom \
  openssh-client samba iperf3 traceroute mtr iw network-manager nmap

# Install Python dependencies
pip3 install pyte paramiko pysnmp

# Run directly
chmod +x opengrid
./opengrid
# or
python3 opengrid
```

### 5.2 Development Mode

Because it's a single file, no build step is required. Just edit `opengrid` and rerun.

```bash
# Syntax check after editing
python3 -m py_compile opengrid
```

### 5.3 Build Debian Package

```bash
cd scripts
chmod +x make-deb.sh
./make-deb.sh
sudo dpkg -i ../opengrid_1.6-1_all.deb
```

### 5.4 Build AppImage

```bash
cd scripts
chmod +x make-anylinux-appimage.sh
./make-anylinux-appimage.sh
```

---

## 6. Coding Conventions

### 6.1 Style

- **Indentation**: 4 spaces (no tabs).
- **Line length**: No strict limit, but keep readable (≈100).
- **Quotes**: Single quotes for strings, double for docstrings.
- **Naming**:
  - `PascalCase` for classes.
  - `snake_case` for functions, methods, variables.
  - `UPPER_CASE` for module-level constants.
  - Private methods/attrs prefix with `_`.

### 6.2 Qt / PyQt6 Patterns

- Use `pyqtSignal` for worker → UI communication.
- Use `QTimer` for periodic UI updates, never `time.sleep` in main thread.
- Set object names for widgets that need style targeting: `widget.setObjectName("name")`.
- Stylesheets are applied inline or via `setStyleSheet`. No external .qss file.

### 6.3 Terminal Widget Conventions

- The terminal screen state (`pyte.Screen`) is protected by `self._pyte_lock`.
- The `render_screen` method runs on the main thread via `QTimer`.
- Cursor blink is handled by `_CursorOverlay` to avoid full `setHtml` refresh.
- Scrollback history is pre-rendered HTML stored in `self._scrollback_lines`.

### 6.4 Adding a New Worker

1. Subclass `QThread`.
2. Define result signals (e.g., `result_ready = pyqtSignal(list)`).
3. Implement `run()` with the blocking operation.
4. Emit signals for progress and results.
5. In the main window, connect signals before calling `worker.start()`.
6. Call `worker.wait()` or handle cleanup in a finished signal to avoid leaks.

---

## 7. Known Issues & Limitations

- **Monolithic file**: `opengrid` is very large (27k lines). Refactoring into modules is desirable but must preserve single-file distribution compatibility.
- **Password storage**: SSH profile passwords are base64-encoded, not encrypted.
- **Thread safety**: Some workers may still emit signals under high load that race with UI updates. Always use `QMetaObject.invokeMethod` for direct widget mutations from threads.
- **Telnet deprecation**: `telnetlib` is deprecated in Python 3.13+; the app uses `standard-telnetlib` as a fallback.
- **Type hints**: Only ~3% of functions currently have type hints. Adding `typing` annotations is an active improvement area.

---

## 8. Common Tasks for Agents

### 8.1 Adding a New UI Tab

1. In `SerialTerminalGUI.__init__`, add the tab to the `QTabWidget`.
2. Create a container `QWidget` and layout.
3. Add the widget class to the main file (or a new import if modularized).
4. Connect buttons to methods on the main window.

### 8.2 Adding a New External Tool Integration

1. Check for binary availability with `shutil.which("tool")`.
2. Use `QProcess` or `subprocess.run` with `shell=False`.
3. Wrap in a `QThread` if the operation is blocking.
4. Parse stdout and emit results via signals.

### 8.3 Modifying Settings

1. Add the default to `ConfigManager.defaults`.
2. Use `config_manager.set(key, value)` and `config_manager.get(key)`.
3. The file auto-saves on every `set()` call.

### 8.4 Adding Type Hints

1. Add `from typing import Any, Optional, Callable` near the top imports.
2. Annotate method signatures: `def method(self, arg: str) -> dict[str, Any]:`.
3. Run `python3 -m py_compile opengrid` to verify syntax.

---

## 9. Release Checklist (for maintainers)

When cutting a new release:

1. Update `VERSION` and `VERSION_LABEL` constants at the top of `opengrid`.
2. Update version in `PKGBUILD`, `debian/changelog`, and `appinfo`.
3. Run `python3 -m py_compile opengrid`.
4. Build packages: `.deb`, AppImage, Flatpak.
5. Test on clean VMs (Debian, Arch, Fedora).
6. Tag release on GitHub and upload artifacts.
7. Update AUR package (`PKGBUILD` + `.SRCINFO`).

---

## 10. Useful Resources

- **README.md** — End-user documentation, installation, features.
- **docs/INTERFACE.md** — Visual UI layout guide.
- **docs/NEXT-STEPS.md** — Release & AUR checklist.
- **PyQt6 Docs**: https://www.riverbankcomputing.com/static/Docs/PyQt6/
- **pyte Docs**: https://pyte.readthedocs.io/
- **paramiko Docs**: https://docs.paramiko.org/

---

*Last updated: 2026-04-23*
