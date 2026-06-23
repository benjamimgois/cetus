# Maintainer: Benjamim Gois <benjamimgois@example.com>
pkgname=cetus
pkgver=1.8
pkgrel=1
pkgdesc="Modern graphical interface for network device management"
arch=('any')
url="https://github.com/benjamimgois/opengrid"
license=('GPL3')
makedepends=('python-build' 'python-installer')
depends=(
    'python'
    'python-pyqt6'
    'python-pyqt6-serialport'
    'python-pyte'
    'python-paramiko'
    'python-pysnmp'
    'picocom'
    'openssh'
    'samba'
    'iperf3'
    'traceroute'
    'mtr'
    'networkmanager'
    'nmap'
    'iw'
)
optdepends=(
    'tigervnc: VNC viewer'
    'freerdp: RDP client'
    'python-pyftpdlib: built-in FTP server'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/benjamimgois/opengrid/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "opengrid-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "opengrid-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl

    install -Dm644 cetus.desktop "$pkgdir/usr/share/applications/cetus.desktop"
    install -Dm644 assets/icons/cetus_icon.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/cetus.svg"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
