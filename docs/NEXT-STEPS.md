# Next Steps - Omnicom v1.0

Your GitHub repository is ready! Follow these steps to complete the release and AUR submission.

## Repository Information

- **GitHub URL**: https://github.com/benjamimgois/omnicom
- **Version**: 1.0
- **Tarball**: omnicom-1.0.tar.gz
- **SHA256**: 7481ee224a0a1a7e2838098444011879990b2da1914220dc6164280904fe7042

## Step 1: Push Code to GitHub ✓

Your repository is created. Now push the code:

```bash
cd /home/benjamim/Documentos/omnicom

# Initialize git if not already done
git init

# Add all files
git add .

# Create .gitignore to exclude build artifacts
cat > .gitignore << 'EOF'
# Build artifacts
*.tar.gz
.SRCINFO
pkg/
src/

# Python
__pycache__/
*.pyc

# IDE
.vscode/
.idea/
EOF

# Commit
git commit -m "Initial commit - Omnicom v1.0"

# Add remote (if not already added)
git remote add origin https://github.com/benjamimgois/omnicom.git

# Push to main branch
git branch -M main
git push -u origin main
```

## Step 2: Create GitHub Release

1. Go to: https://github.com/benjamimgois/omnicom/releases/new

2. Fill in the release information:
   - **Tag version**: `v1.0`
   - **Release title**: `Omnicom v1.0`
   - **Description**:
   ```markdown
   # Omnicom v1.0 - Initial Release

   Modern graphical interface for serial communication via picocom.

   ## Features
   - Modern PyQt6 interface
   - Automatic port detection
   - Full serial parameter configuration
   - Baud rates from 300 to 921600 bps
   - Support for serial and USB ports

   ## Installation

   ### Arch Linux (AUR)
   ```bash
   yay -S omnicom
   ```

   ### Manual Installation
   ```bash
   wget https://github.com/benjamimgois/omnicom/releases/download/v1.0/omnicom-1.0.tar.gz
   tar -xzf omnicom-1.0.tar.gz
   cd omnicom-1.0
   chmod +x omnicom
   ./omnicom
   ```

   ## Requirements
   - Python 3
   - PyQt6
   - Qt6 SerialPort
   - picocom

   ## SHA256 Checksum
   ```
   7481ee224a0a1a7e2838098444011879990b2da1914220dc6164280904fe7042
   ```
   ```

3. **Attach the tarball**:
   - Upload `omnicom-1.0.tar.gz` as a release asset

4. Click **"Publish release"**

## Step 3: Verify Release

After publishing, verify the download URL:
```bash
wget https://github.com/benjamimgois/omnicom/releases/download/v1.0/omnicom-1.0.tar.gz
sha256sum omnicom-1.0.tar.gz
# Should output: 7481ee224a0a1a7e2838098444011879990b2da1914220dc6164280904fe7042
```

## Step 4: Test PKGBUILD

```bash
cd /home/benjamim/Documentos/omnicom

# Test build
makepkg -si

# If successful, test the application
omnicom
```

## Step 5: Submit to AUR

### 5.1: Setup AUR Account

1. Create account: https://aur.archlinux.org/register
2. Add SSH key to your AUR account

### 5.2: Clone AUR Repository

```bash
git clone ssh://aur@aur.archlinux.org/omnicom.git aur-omnicom
cd aur-omnicom
```

### 5.3: Add Files

```bash
# Copy PKGBUILD and .SRCINFO
cp ../omnicom/PKGBUILD .
cp ../omnicom/.SRCINFO .

# Verify files
cat .SRCINFO
cat PKGBUILD
```

### 5.4: Commit and Push

```bash
# Add files
git add PKGBUILD .SRCINFO

# Commit
git commit -m "Initial release of Omnicom v1.0

Modern graphical interface for serial communication via picocom.

Features:
- PyQt6 interface
- Automatic port detection
- Full serial configuration
- Support for serial and USB ports"

# Push to AUR
git push
```

### 5.5: Verify AUR Package

Visit: https://aur.archlinux.org/packages/omnicom

## Step 6: Update README Badges

After AUR submission, update README.md with AUR badge:

```markdown
[![AUR version](https://img.shields.io/aur/version/omnicom)](https://aur.archlinux.org/packages/omnicom)
```

## Summary Checklist

- [ ] Push code to GitHub
- [ ] Create release v1.0 on GitHub
- [ ] Upload omnicom-1.0.tar.gz to release
- [ ] Verify release download URL works
- [ ] Test PKGBUILD locally with makepkg
- [ ] Create AUR account and add SSH key
- [ ] Clone AUR repository
- [ ] Submit PKGBUILD and .SRCINFO to AUR
- [ ] Verify package appears on AUR
- [ ] Update README with badges

## Files Ready for Upload

All files are configured with the correct URLs:

```
✓ PKGBUILD - Points to GitHub release
✓ .SRCINFO - Generated with correct URLs
✓ README.md - Updated with repository links
✓ README-AUR.md - Updated with repository links
✓ omnicom-1.0.tar.gz - Ready to upload to GitHub release
```

**Everything is ready! Follow the steps above to complete the release.** 🚀
