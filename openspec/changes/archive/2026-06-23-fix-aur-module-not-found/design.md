## Context

The `cetus` launcher script (`/usr/bin/cetus` post-install) attempts to import `cetuslib` with a multi-path fallback:

1. Direct `import cetuslib`
2. `cetuslib/` next to script
3. Script's own directory
4. `script_dir.parent / 'share' / 'cetus'`
5. `/usr/share/cetus`

The AUR `cetus-git` PKGBUILD (`packaging/arch/PKGBUILD`) only installs the launcher script and assets — never `cetuslib/`. In contrast, `scripts/install.sh` correctly copies `cetuslib/` to `$PREFIX/share/cetus/`.

The launcher's last fallback `Path('/usr/share/cetus')` would resolve `cetuslib` if `/usr/share/cetus/cetuslib` existed — but it doesn't because the PKGBUILD never creates it.

The fix is minimal: add a `cetuslib/` copy step to the PKGBUILD's `package()` function.

## Goals / Non-Goals

**Goals:**
- AUR-installed Cetus runs without `ModuleNotFoundError`
- `cetuslib/` is installed to `/usr/share/cetus/cetuslib` matching the launcher's fallback path
- Minimal diff — only PKGBUILD changes

**Non-Goals:**
- No changes to the launcher script logic
- No wheel-based build for the AUR (this PKGBUILD is a simple file-copy approach)
- No changes to the release PKGBUILD (`PKGBUILD` at repo root)

## Decisions

- **Decision**: Add `cetuslib/` install via `cp -r` in the `package()` function
  - **Rationale**: Matches what `scripts/install.sh` does. The existing launcher already looks for `/usr/share/cetus/cetuslib` — simplest fix.
  - **Alternatives considered**:
    - Switch to wheel-based build (like root `PKGBUILD`): larger diff, changes package architecture, riskier
    - Modify launcher to search additional paths: unnecessary — existing fallback covers `/usr/share/cetus/`
    - Install via `pip` / `python -m installer`: requires `pyproject.toml` build which may pull unnecessary deps

- **Decision**: Use `/usr/share/cetus/cetuslib` as target directory
  - **Rationale**: Already the last fallback path in the launcher. No other launcher changes needed.

- **Decision**: Exclude `__pycache__` and `.pyc` from installed files
  - **Rationale**: Standard packaging practice. Fresh compile on target machine.

## Risks / Trade-offs

- **[Low] Stale `.pyc` files** → PKGBUILD uses `cp -r` without exclusion, but fresh install on user machine has no cache. Minimal risk.
- **[Low] Permission mismatch** → `cetuslib/` files inherit directory permissions. Using `install -d` for parent dir + `cp -r` is safe.
