## ADDED Requirements

### Requirement: AUR package installs cetuslib module
The AUR `cetus-git` package SHALL install the `cetuslib/` Python package directory so the launcher script can import it.

#### Scenario: AUR-installed cetus runs without ImportError
- **WHEN** the `cetus-git` AUR package is installed and the `cetus` command is executed
- **THEN** the application starts without raising `ModuleNotFoundError: No module named 'cetuslib'`

### Requirement: cetuslib installed to launcher-expected path
The AUR package SHALL place `cetuslib/` at a path the launcher script searches during its fallback import resolution.

#### Scenario: cetuslib resolves from /usr/share/cetus
- **WHEN** the launcher's fallback import logic checks `Path('/usr/share/cetus')`
- **THEN** `cetuslib/` exists as a subdirectory of `/usr/share/cetus/` and imports successfully
