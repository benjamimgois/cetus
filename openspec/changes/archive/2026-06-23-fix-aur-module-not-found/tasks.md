## 1. PKGBUILD — Add cetuslib installation

- [x] 1.1 Add `cp -r cetuslib "$pkgdir/usr/share/cetus/cetuslib"` to `package()` in `packaging/arch/PKGBUILD`
- [x] 1.2 Add `install -dm755 "$pkgdir/usr/share/cetus"` before the copy to ensure parent directory exists
- [x] 1.3 Verify the final tree includes `/usr/share/cetus/cetuslib/` with all `.py` files — 15 `.py` files confirm

## 2. Verify

- [x] 2.1 Run `python3 -m py_compile` on all `cetuslib/` files to ensure syntax validity for AUR install
- [x] 2.2 Confirm launcher fallback path `/usr/share/cetus` resolves `cetuslib` with a dry check
