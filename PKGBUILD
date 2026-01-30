# Maintainer: Benjamim Gois <your.email@example.com>
pkgname=serialcom
pkgver=1.0
pkgrel=1
pkgdesc="Modern graphical interface for serial communication via picocom"
arch=('any')
url="https://github.com/benjamimgois/serialcom"
license=('MIT')
depends=('python' 'python-pyqt6' 'qt6-serialport' 'picocom' 'sudo')
makedepends=()
optdepends=(
    'gnome-terminal: default terminal emulator'
    'konsole: KDE terminal emulator'
    'xfce4-terminal: XFCE terminal emulator'
    'kitty: fast GPU-based terminal emulator'
    'alacritty: cross-platform GPU-accelerated terminal emulator'
)
source=("https://github.com/benjamimgois/serialcom/releases/download/v${pkgver}/${pkgname}-${pkgver}.tar.gz")
sha256sums=('7481ee224a0a1a7e2838098444011879990b2da1914220dc6164280904fe7042')

package() {
    cd "${srcdir}/${pkgname}-${pkgver}"

    # Install main script
    install -Dm755 serialcom "${pkgdir}/usr/lib/${pkgname}/serialcom"

    # Install executable wrapper
    install -Dm755 serialcom "${pkgdir}/usr/bin/serialcom"
    
    # Install icon
    install -Dm644 serialcom.png "${pkgdir}/usr/share/pixmaps/serialcom.png"

    # Fix path in wrapper
    sed -i "s|SCRIPT_DIR=.*|SCRIPT_DIR=\"/usr/lib/${pkgname}\"|" "${pkgdir}/usr/bin/serialcom"

    # Install desktop file
    install -Dm644 serialcom.desktop "${pkgdir}/usr/share/applications/serialcom.desktop"

    # Fix Exec path in desktop file
    sed -i "s|Exec=.*|Exec=/usr/bin/serialcom|" "${pkgdir}/usr/share/applications/serialcom.desktop"
    
    # Fix Icon path in desktop file
    sed -i "s|Icon=.*|Icon=/usr/share/pixmaps/serialcom.png|" "${pkgdir}/usr/share/applications/serialcom.desktop"

    # Install documentation
    install -Dm644 README.md "${pkgdir}/usr/share/doc/${pkgname}/README.md"
    install -Dm644 INTERFACE.md "${pkgdir}/usr/share/doc/${pkgname}/INTERFACE.md"

    # Install license
    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
