# Cetus — Agent Context File

> This file is intended for AI agents and automated tooling. It describes the project architecture, conventions, and workflows so agents can make safe, useful changes.

---

## 1. What is Cetus?

Cetus is a **desktop GUI application for Linux** that provides an easy, modern interface to manage network devices. It targets network engineers and system administrators who need serial, SSH, Telnet, VNC, RDP, SNMP, file transfer, speed tests, Wi-Fi surveys, and network discovery tools in a single PyQt6 application.

- **Language**: Python 3.8+
- **GUI Framework**: PyQt6 (Qt6)
- **License**: GPL-3.0
- **Repository**: https://github.com/benjamimgois/opengrid
- **Current Version**: 1.7

---

## 2. Architecture Overview

### 2.1 Modular Source, Single-File Distribution

The source code is split into a Python package for maintainability, but a single-file executable is still produced for distribution:

- **`cetuslib/`** — Modular source package:
  - `config.py`, `constants.py`, `utils.py`
  - `terminal.py` — terminal widgets
  - `workers.py` — background workers
  - `network.py` — network/graph widgets
  - `ui/` — reusable UI components
  - `main.py` — `SerialTerminalGUI` and `main()`
- **`cetus`** (launcher) — Thin root entrypoint that imports `cetuslib.main.main()`.
- **`dist/cetus`** — Generated monolithic executable (via `scripts/bundle-monolith.py`) used for AppImage, `.deb`, and AUR.

### 2.2 Key Classes

| Class | Module | Responsibility |
|-------|--------|----------------|
| `SerialTerminalGUI` | `cetuslib/main.py` | Main window (QMainWindow). Hosts tabs, menu bar, and global state. |
| `TerminalWidget` | `cetuslib/terminal.py` | VT100/ANSI terminal emulator using `pyte`. Supports scrollback, search, syntax highlighting, autocomplete, and cursor overlay. |
| `TerminalDialog` | `cetuslib/terminal.py` | Dialog window embedding a `TerminalWidget` for serial/SSH/Telnet sessions. |
| `TerminalTabbedWindow` | `cetuslib/terminal.py` | Detachable tabbed terminal window for multi-session management. |
| `ConfigManager` | `cetuslib/config.py` | JSON-based settings persistence (XDG Base Directory). Handles serial/SSH profiles, SNMP community history, and quick notes. |
| `ScanWorker` | `cetuslib/workers.py` | IP scanner worker (ICMP/TCP/UDP/ARP). |
| `ConnectionWorker` | `cetuslib/workers.py` | SSH/Telnet connection worker using `paramiko` / `telnetlib`. |
| `TracerouteWorker` | `cetuslib/workers.py` | Traceroute execution worker. |
| `MtrWorker` | `cetuslib/workers.py` | MTR continuous traceroute worker. |
| `Iperf3Worker` | `cetuslib/workers.py` | iPerf3 throughput test worker. |
| `SpeedTestWorker` | `cetuslib/workers.py` | Internet speed test worker (fast.com / iPerf3). |
| `WifiChannelChart` | `cetuslib/network.py` | Custom QWidget rendering channel usage with Gaussian curves. |
| `WifiHeatmapWidget` | `cetuslib/network.py` | Wi-Fi signal strength heatmap visualization. |
| `FileConnectWorker` | `cetuslib/workers.py` | SFTP connection worker. |
| `FileListWorker` | `cetuslib/workers.py` | SFTP file listing worker. |
| `FileTransferWorker` | `cetuslib/workers.py` | SFTP upload/download worker. |
| `NmapDiscoverWorker` | `cetuslib/workers.py` | Nmap OS/service discovery worker. |
| `VendorConfigTemplateDialog` | `cetuslib/main.py` | Dialog with vendor-specific command reference and config templates. |

### 2.3 Threading Model

- **Main Thread**: Qt GUI event loop, all QWidget updates.
- **Worker Threads**: `QThread` subclasses perform I/O (SSH, serial, scans, file transfers).
- Workers communicate with UI via Qt signals (`pyqtSignal`).
- `TerminalWidget` uses a `threading.Lock` (`_pyte_lock`) to protect `pyte` screen/stream state when the worker thread writes bytes and the main thread renders.

**⚠️ Important**: Never update QWidget state directly from a worker thread. Always use signals/slots or `QMetaObject.invokeMethod`.

### 2.4 Configuration & State

- **Config path**: `~/.config/cetus/settings.json` (XDG compliant).
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
| `scripts/bundle-monolith.py` | Generate `dist/cetus` from `cetuslib/` modules |
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
cetus/
├── cetus                  ← Main application launcher (imports cetuslib)
├── cetus.desktop          ← Linux .desktop launcher
├── appinfo                ← AppStream / app metadata
├── README.md              ← Human-facing documentation
├── LICENSE                ← GPL-3.0
│
├── cetuslib/              ← Modular source package
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py
│   ├── constants.py
│   ├── utils.py
│   ├── terminal.py
│   ├── workers.py
│   ├── network.py
│   ├── main.py
│   ├── legacy.py          ← TFTP early-exit stub
│   └── ui/
│       ├── __init__.py
│       ├── dialogs.py
│       ├── profiles.py
│       └── widgets.py
│
├── dist/
│   └── cetus              ← Generated monolithic executable
│
├── assets/
│   ├── icons/             ← SVG icons (cetus_icon.svg, etc.)
│   └── remmina/           ← Remmina integration assets
│
├── scripts/               ← Build and packaging scripts
│   ├── make-deb.sh
│   ├── bundle-monolith.py
│   ├── make-release.sh
│   ├── make-anylinux-appimage.sh
│   └── install.sh
│
├── packaging/
│   └── flatpak/
│       └── io.github.benjamimgois.cetus.yml
│
├── debian/                ← Debian package metadata
├── build-anylinux/        ← AppImage build artifacts
├── docs/
│   ├── INTERFACE.md       ← UI layout guide
│   ├── NEXT-STEPS.md      ← Release checklist
│   ├── AUR-INSTRUCTIONS.md ← AUR packaging guide
│   └── README-AUR.md
│
└── .github/               ← GitHub workflows/templates
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
chmod +x cetus
./cetus
# or
python3 cetus
```

### 5.2 Development Mode

Edit modules under `cetuslib/` and run the launcher directly. No bundler step is needed during development.

```bash
# Run from source
./cetus
# or
python3 -m cetuslib

# Syntax check after editing
python3 -m py_compile cetuslib/main.py cetuslib/terminal.py cetuslib/workers.py

# Regenerate the distribution monolith
python3 scripts/bundle-monolith.py
```

### 5.3 Build Debian Package

```bash
cd scripts
chmod +x make-deb.sh
./make-deb.sh
sudo dpkg -i ../cetus_1.6-1_all.deb
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

- **Monolithic file**: `dist/cetus` is generated from `cetuslib/`. Edit `cetuslib/` and regenerate the bundle; do not edit `dist/cetus` directly.
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
3. Run `python3 -m py_compile cetuslib/main.py` to verify syntax.

---

## 9. Release Checklist (for maintainers)

When cutting a new release:

1. Update `VERSION` and `VERSION_LABEL` in `cetuslib/constants.py`.
2. Update version in `PKGBUILD`, `debian/changelog`, and `appinfo`.
3. Run `python3 -m py_compile cetuslib/main.py` and regenerate `dist/cetus` with `python3 scripts/bundle-monolith.py`.
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
