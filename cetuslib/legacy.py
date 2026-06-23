"""Legacy entrypoint stub.

Only the standalone TFTP server early-exit remains here so that the bundled
monolith can still be invoked as `cetus --tftp-server <host> <port> <dir>`
without importing PyQt6.
"""

import sys

from cetuslib.utils import run_tftp_server_standalone


if __name__ == '__main__' and len(sys.argv) >= 5 and sys.argv[1] == '--tftp-server':
    host = sys.argv[2]
    port = int(sys.argv[3])
    directory = sys.argv[4]
    run_tftp_server_standalone(host, port, directory)
    sys.exit(0)
