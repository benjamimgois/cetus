# How to Submit Cetus to AUR

This guide explains how to prepare and submit Cetus to the Arch User Repository (AUR).

## Prerequisites

1. **AUR Account**: Create an account at https://aur.archlinux.org/register
2. **SSH Key**: Add your SSH public key to your AUR account
3. **Required Tools**:
   ```bash
   sudo pacman -S base-devel git
   ```

## Step 1: Prepare the Source Archive

Create a tarball of the project:

```bash
# Navigate to the parent directory
cd /home/benjamim/Documentos

# Create a versioned directory
mkdir cetus-1.0
cp cetus/{cetus,cetus.desktop,README.md,INTERFACE.md,LICENSE} cetus-1.0/

# Create tarball
tar -czf cetus-1.0.tar.gz cetus-1.0/

# Clean up
rm -rf cetus-1.0
```

## Step 2: Host the Source Archive

You need to host the tarball somewhere publicly accessible. Options:

1. **GitHub Release** (recommended):
   - Create a GitHub repository for Cetus
   - Create a release tagged `v1.0`
   - Upload the tarball as a release asset
   - Use the release URL in PKGBUILD

2. **Your own server**:
   - Upload to your web server
   - Use the direct download URL

Example GitHub URL:
```
https://github.com/benjamimgois/opengrid/releases/download/v1.0/cetus-1.0.tar.gz
```

## Step 3: Update PKGBUILD

1. Update the maintainer information:
   ```bash
   # Maintainer: Benjamim Gois <your.email@example.com>
   ```

2. Update the `url` field with your repository:
   ```bash
   url="https://github.com/benjamimgois/opengrid"
   ```

3. Update the `source` array with the actual download URL:
   ```bash
   source=("https://github.com/benjamimgois/opengrid/releases/download/v${pkgver}/${pkgname}-${pkgver}.tar.gz")
   ```

4. Calculate the SHA256 checksum:
   ```bash
   sha256sum cetus-1.0.tar.gz
   ```

5. Update `sha256sums` in PKGBUILD with the actual checksum:
   ```bash
   sha256sums=('actual_checksum_here')
   ```

## Step 4: Test the PKGBUILD Locally

```bash
# Navigate to the directory with PKGBUILD
cd /home/benjamim/Documentos/cetus

# Build the package
makepkg -si

# Test the installed package
cetus

# Clean up if needed
makepkg --clean
```

## Step 5: Generate .SRCINFO

The AUR requires a `.SRCINFO` file:

```bash
makepkg --printsrcinfo > .SRCINFO
```

## Step 6: Clone the AUR Repository

```bash
# Clone the AUR repo (replace 'cetus' with your package name if different)
git clone ssh://aur@aur.archlinux.org/cetus.git aur-cetus
cd aur-cetus
```

## Step 7: Add Your Files

```bash
# Copy PKGBUILD and .SRCINFO
cp ../cetus/PKGBUILD .
cp ../cetus/.SRCINFO .

# Add files to git
git add PKGBUILD .SRCINFO
```

## Step 8: Commit and Push

```bash
# Commit
git commit -m "Initial release of Cetus v1.0"

# Push to AUR
git push
```

## Step 9: Verify on AUR

Visit: https://aur.archlinux.org/packages/cetus

Your package should now be available!

## Updating the Package

When releasing a new version:

1. Update `pkgver` in PKGBUILD
2. Reset `pkgrel` to 1
3. Create new tarball with new version
4. Update `sha256sums`
5. Regenerate `.SRCINFO`:
   ```bash
   makepkg --printsrcinfo > .SRCINFO
   ```
6. Commit and push:
   ```bash
   git add PKGBUILD .SRCINFO
   git commit -m "Update to v1.1"
   git push
   ```

## Package Naming Guidelines

- Use lowercase for package names
- Avoid version numbers in package name
- Use hyphens to separate words (e.g., `python-pyqt6`)

## Additional Resources

- AUR Submission Guidelines: https://wiki.archlinux.org/title/AUR_submission_guidelines
- PKGBUILD Reference: https://wiki.archlinux.org/title/PKGBUILD
- .SRCINFO: https://wiki.archlinux.org/title/.SRCINFO

## Notes

- The AUR is for PKGBUILD files only, not for hosting source code
- Source code should be hosted on GitHub, GitLab, or similar
- Keep PKGBUILD simple and follow Arch packaging standards
- Respond to package comments and maintain your package
