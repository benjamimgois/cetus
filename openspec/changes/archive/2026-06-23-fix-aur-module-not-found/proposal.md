## Why

When Cetus is installed via the AUR `cetus-git` package, the `cetus` launcher script at `/usr/bin/cetus` fails with `ModuleNotFoundError: No module named 'cetuslib'` because the PKGBUILD never installs the `cetuslib/` package directory — only the launcher script and assets. Compare with `scripts/install.sh` which correctly copies `cetuslib/` to the share directory.

## What Changes

- Add `cetuslib/` directory installation to `packaging/arch/PKGBUILD` package function
- Install `cetuslib/` to `/usr/share/cetus/cetuslib` so the launcher's existing fallback path logic resolves the module
- No changes to the launcher script itself — the fallback path `Path('/usr/share/cetus')` already exists in its search order

## Capabilities

### New Capabilities

- `aur-packaging`: Ensure AUR package installs all required Python modules so the application runs correctly after installation

### Modified Capabilities

- `distribution-bundler`: PKGBUILD now includes `cetuslib/` in the package payload — this spec covers build/packaging correctness
- `module-import-compatibility`: AUR-installed launcher must resolve `cetuslib` — this spec covers the import path resolution

## Impact

- `packaging/arch/PKGBUILD`: add `cetuslib/` copy to `package()` function
- No other files affected
- No new dependencies
- No API changes
