"""Workers for the Cetus Automation module (mass command execution over SSH/Telnet)."""

import ipaddress
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from cetuslib.vendors import (
    AUTODETECT, get_vendor, detect_vendor, is_prompt,
    find_interactive_answer, find_vendor_error,
)

try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    paramiko = None
    SSH_AVAILABLE = False

try:
    import telnetlib
    TELNET_AVAILABLE = True
except ImportError:
    telnetlib = None
    TELNET_AVAILABLE = False


__all__ = [
    'MAX_TARGETS',
    'STATUS_PENDING', 'STATUS_RUNNING', 'STATUS_OK',
    'STATUS_ERROR', 'STATUS_TIMEOUT', 'STATUS_CANCELLED',
    'parse_targets', 'AutomationHostWorker', 'AutomationManager',
]


MAX_TARGETS = 1024

STATUS_PENDING = 'Pending'
STATUS_RUNNING = 'Running'
STATUS_OK = 'OK'
STATUS_ERROR = 'Error'
STATUS_TIMEOUT = 'Timeout'
STATUS_CANCELLED = 'Cancelled'

_MAX_INTERACTIVE_REPLIES = 5


class AutomationError(Exception):
    """Raised by host workers to abort a session with a status/message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _is_valid_ipv4(text):
    try:
        addr = ipaddress.IPv4Address(text)
        return str(addr) == text
    except ValueError:
        return False


def parse_targets(text):
    """Parse the target list into individual IPs.

    Accepts one entry per line:
    - a single address:              192.168.15.1
    - a last-octet range:            192.168.15.1-45
    - a full address range (same /24): 10.0.0.5-10.0.0.7

    Lines starting with ``#`` are comments; blank lines are ignored.

    Returns ``(ips, invalid)`` where *ips* is a de-duplicated ordered list of
    address strings and *invalid* is a list of ``(line, reason)`` tuples.
    """
    ips = []
    seen = set()
    invalid = []

    def _push(ip):
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '-' not in line:
            if _is_valid_ipv4(line):
                _push(line)
            else:
                invalid.append((line, 'endereço IPv4 inválido'))
            continue
        parts = line.split('-', 1)
        left, right = parts[0].strip(), parts[1].strip()
        if not _is_valid_ipv4(left):
            invalid.append((line, 'endereço IPv4 inválido'))
            continue
        l_prefix, l_last = left.rsplit('.', 1)
        if right.isdigit():
            r_last = int(right)
        else:
            if not _is_valid_ipv4(right):
                invalid.append((line, 'endereço IPv4 inválido'))
                continue
            r_prefix, r_last_text = right.rsplit('.', 1)
            if r_prefix != l_prefix:
                invalid.append((line, 'range deve estar na mesma /24'))
                continue
            r_last = int(r_last_text)
        if int(l_last) > r_last:
            invalid.append((line, 'limite inferior maior que o superior'))
            continue
        for octet in range(int(l_last), r_last + 1):
            _push(f'{l_prefix}.{octet}')

    return ips, invalid


class AutomationHostWorker(QThread):
    """Executes the command list on a single host and writes its log."""

    def __init__(self, ip, port, conn_type, username, password, commands,
                 vendor_key, min_gap, cmd_timeout, log_dir):
        super().__init__()
        self.ip = ip
        self.port = port
        self.conn_type = conn_type  # 'ssh' | 'telnet'
        self.username = username
        self.password = password
        self.commands = commands
        self.vendor_key = vendor_key  # AUTODETECT or a vendor key
        self.min_gap = float(min_gap)
        self.cmd_timeout = float(cmd_timeout)
        self.log_dir = log_dir
        self._cancel = False
        self.result = {
            'ip': ip, 'status': STATUS_PENDING, 'duration': 0.0,
            'message': '', 'vendor': vendor_key, 'log': '',
        }
        self._channel = None
        self._telnet = None
        self._client = None
        self._log_fh = None
        self._buffer = ''
        self.vendor = vendor_key
        self._replies = 0
        self._last_reply_at = 0.0
        self._last_reply_pos = 0

    # ------------------------------------------------------------------ #
    def cancel(self):
        self._cancel = True

    # ------------------------------------------------------------------ #
    def run(self):
        start = time.monotonic()
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', self.ip)
        log_path = os.path.join(self.log_dir, f'{safe_name}.log')
        self.result['log'] = log_path
        status, message = STATUS_OK, ''

        try:
            os.makedirs(self.log_dir, exist_ok=True)
            self._log_fh = open(log_path, 'w', encoding='utf-8', buffering=1)
            self._log_fh.write(
                f'=== Cetus Automation ===\nHost: {self.ip}\n'
                f'Started: {datetime.now().isoformat(timespec="seconds")}\n'
                f'Connection: {self.conn_type} port {self.port}\n\n'
            )
            self._connect()
            self.vendor = self._resolve_vendor()
            self.result['vendor'] = self.vendor
            self._log_fh.write(f'Vendor: {get_vendor(self.vendor)["label"]}\n\n')

            for cmd in self.commands:
                if self._cancel:
                    raise AutomationError(STATUS_CANCELLED, 'Cancelled by user')
                self._send_command(cmd)
        except AutomationError as exc:
            status, message = exc.status, str(exc)
        except Exception as exc:  # connection failures, EOF, decode errors
            status, message = STATUS_ERROR, f'{type(exc).__name__}: {exc}'
        finally:
            self._close_session()
            if self._log_fh:
                self._log_fh.flush()
                self._log_fh.close()
                self._log_fh = None

        self.result['status'] = status
        self.result['message'] = message
        self.result['duration'] = time.monotonic() - start
        self._log_fh = None
        # Final summary line in the log
        try:
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write(f'\n=== Result: {status} in {self.result["duration"]:.1f}s ===\n')
                if message:
                    fh.write(f'=== {message} ===\n')
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    def _append_log(self, text):
        if self._log_fh and text:
            try:
                self._log_fh.write(text)
            except (OSError, ValueError):
                pass

    def _close_session(self):
        try:
            if self._channel is not None:
                self._channel.close()
        except Exception:
            pass
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        try:
            if self._telnet is not None:
                self._telnet.close()
        except Exception:
            pass
        self._channel = None
        self._client = None
        self._telnet = None

    def _read_chunk(self):
        if self._channel is not None:
            if self._channel.recv_ready():
                return self._channel.recv(65535).decode('utf-8', errors='replace')
            return ''
        if self._telnet is not None:
            try:
                return self._telnet.read_very_eager().decode('utf-8', errors='replace')
            except EOFError:
                raise AutomationError(STATUS_ERROR, 'Connection closed by host')
        return ''

    def _read_for(self, duration):
        """Accumulate output for up to *duration* seconds (polls cancel)."""
        collected = ''
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._cancel:
                raise AutomationError(STATUS_CANCELLED, 'Cancelled by user')
            chunk = self._read_chunk()
            if chunk:
                collected += chunk
                self._buffer += chunk
                self._append_log(chunk)
            else:
                time.sleep(0.05)
        return collected

    def _send(self, text):
        if self._channel is not None:
            self._channel.sendall(text.encode('utf-8'))
        elif self._telnet is not None:
            self._telnet.write(text.encode('utf-8'))

    # ------------------------------------------------------------------ #
    def _connect(self):
        if self.conn_type == 'telnet':
            self._connect_telnet()
        else:
            self._connect_ssh()

    def _connect_ssh(self):
        if not SSH_AVAILABLE:
            raise AutomationError(STATUS_ERROR, 'paramiko is not installed')
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.ip, int(self.port), self.username, password=self.password,
            timeout=10, banner_timeout=15, auth_timeout=15,
            allow_agent=False, look_for_keys=False,
        )
        self._client = client
        self._channel = client.invoke_shell(term='xterm', width=200, height=50)
        self._channel.settimeout(0.0)
        self._buffer = ''
        self._read_for(1.0)  # MOTD/banner
        self._send('\n')
        self._read_for(0.5)

    def _connect_telnet(self):
        if not TELNET_AVAILABLE:
            raise AutomationError(STATUS_ERROR, 'telnetlib is not available')
        try:
            self._telnet = telnetlib.Telnet(self.ip, int(self.port), timeout=10)
        except (OSError, EOFError) as exc:
            raise AutomationError(STATUS_ERROR, f'Connection failed: {exc}')

        vendor = get_vendor('generic')
        user_rx, pass_rx = vendor['telnet_login']
        sent_user = sent_pass = False
        deadline = time.monotonic() + 25
        buffer = ''
        while time.monotonic() < deadline:
            if self._cancel:
                raise AutomationError(STATUS_CANCELLED, 'Cancelled by user')
            try:
                chunk = self._telnet.read_very_eager().decode('utf-8', errors='replace')
            except EOFError:
                raise AutomationError(STATUS_ERROR, 'Connection closed during login')
            if chunk:
                buffer += chunk
                self._append_log(chunk)
            tail = buffer[-120:]
            if not sent_pass and pass_rx.search(tail):
                if self.password:
                    self._send(self.password + '\n')
                sent_pass = True
                buffer = ''
                time.sleep(0.3)
                continue
            if not sent_user and user_rx.search(tail):
                self._send(self.username + '\n')
                sent_user = True
                buffer = ''
                time.sleep(0.3)
                continue
            if not sent_user and is_prompt(buffer, 'generic'):
                break  # loginless shell already at a prompt
            if sent_user and sent_pass and (is_prompt(buffer, 'generic') or buffer):
                # Give slow banners a moment before concluding login
                if not self._telnet.read_very_eager():
                    break
            time.sleep(0.1)
        self._send('\n')
        self._read_for(0.5)

    # ------------------------------------------------------------------ #
    def _resolve_vendor(self):
        if self.vendor_key != AUTODETECT:
            return self.vendor_key
        last_line = ''
        for line in reversed(self._buffer.splitlines()):
            if line.strip():
                last_line = line
                break
        key = detect_vendor(last_line or self._buffer)
        return key

    # ------------------------------------------------------------------ #
    def _send_command(self, cmd):
        self._log_fh_write(f'[{datetime.now().strftime("%H:%M:%S")}] > {cmd}\n')
        self._buffer = ''
        self._replies = 0
        self._last_reply_at = 0.0
        self._last_reply_pos = 0
        self._send(cmd + '\n')
        deadline = time.monotonic() + self.cmd_timeout

        while time.monotonic() < deadline:
            if self._cancel:
                raise AutomationError(STATUS_CANCELLED, 'Cancelled by user')
            chunk = self._read_chunk()
            if chunk:
                self._buffer += chunk
                self._append_log(chunk)
            # Vendor error? (checked even when the prompt also arrived)
            error_line = find_vendor_error(
                self._buffer, self.vendor, echo_line=cmd)
            if error_line:
                raise AutomationError(
                    STATUS_ERROR, f'Error on "{cmd}": {error_line}')
            # Prompt reached?
            if is_prompt(self._buffer, self.vendor):
                self._wait_min_gap()
                return
            # Interactive question pending?
            if self._replies < _MAX_INTERACTIVE_REPLIES and \
                    len(self._buffer) > self._last_reply_pos and \
                    time.monotonic() - self._last_reply_at > 0.5:
                answer = find_interactive_answer(
                    self._buffer, self.vendor, password=self.password)
                if answer:
                    self._replies += 1
                    self._last_reply_at = time.monotonic()
                    self._last_reply_pos = len(self._buffer)
                    self._log_fh_write(f'[{datetime.now().strftime("%H:%M:%S")}] (auto) > {answer}\n')
                    self._send(answer + '\n')
            if not chunk:
                time.sleep(0.05)

        raise AutomationError(
            STATUS_TIMEOUT, f'Timeout after {self.cmd_timeout:.0f}s on "{cmd}"')

    def _log_fh_write(self, text):
        if self._log_fh:
            try:
                self._log_fh.write(text)
            except (OSError, ValueError):
                pass

    def _wait_min_gap(self):
        gap_end = time.monotonic() + self.min_gap
        while time.monotonic() < gap_end:
            if self._cancel:
                raise AutomationError(STATUS_CANCELLED, 'Cancelled by user')
            chunk = self._read_chunk()
            if chunk:
                self._append_log(chunk)
            else:
                time.sleep(0.05)


class AutomationManager(QThread):
    """Coordinates a batch run: spawns host workers (serial or pooled),
    aggregates results, writes run.json and honors stop requests."""

    row_started = pyqtSignal(str)
    row_finished = pyqtSignal(str, float, str, str, str, str)
    # ip, duration, status, message, vendor, log_path
    progress_changed = pyqtSignal(int, int)   # done, total
    run_finished = pyqtSignal(str, float)     # run_dir, total duration

    def __init__(self, targets, settings):
        super().__init__()
        # De-duplicate preserving order (defense in depth: the UI parser
        # already dedupes, but the manager must not rely on that).
        self._targets = list(dict.fromkeys(targets))
        self._settings = dict(settings)
        self._cancel = False
        self._active = []
        self._pending = []
        self._done = 0
        self._results = []
        self._start_wall = None

    def cancel(self):
        self._cancel = True
        for worker in list(self._active):
            worker.cancel()

    # ------------------------------------------------------------------ #
    def _run_dir(self):
        base = Path.home() / '.local' / 'share' / 'cetus' / 'automation'
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        path = base / ts
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            path = base
        return str(path)

    def _spawn(self, ip):
        s = self._settings
        worker = AutomationHostWorker(
            ip=ip, port=s['port'], conn_type=s['conn_type'],
            username=s['username'], password=s['password'],
            commands=s['commands'], vendor_key=s['vendor_key'],
            min_gap=s['min_gap'], cmd_timeout=s['cmd_timeout'],
            log_dir=self._dir,
        )
        self.row_started.emit(ip)
        return worker

    def _on_worker_done(self, worker):
        if worker in self._active:
            self._active.remove(worker)
        self._results.append(worker.result)
        self._done += 1
        self.row_finished.emit(
            worker.result['ip'], worker.result['duration'], worker.result['status'],
            worker.result['message'], worker.result['vendor'], worker.result['log'])
        self.progress_changed.emit(self._done, len(self._targets))
        # No deleteLater here: the worker thread has already finished
        # (isFinished() was checked), so plain garbage collection is safe.
        # deleteLater would be posted to the manager thread, which has no
        # running event loop during run().

    def _reap(self):
        """Collect finished workers. Called from the manager loop; workers
        report via isFinished() polling instead of cross-thread signal
        connections (a lambda connected from the manager thread would be
        queued on the manager thread, which has no event loop during run())."""
        for worker in [w for w in self._active if w.isFinished()]:
            self._on_worker_done(worker)

    # ------------------------------------------------------------------ #
    def run(self):
        self._dir = self._run_dir()
        self._start_wall = time.monotonic()
        total = len(self._targets)
        self.progress_changed.emit(0, total)
        self._pending = list(self._targets)
        pool = 1 if not self._settings['parallel'] else max(1, int(self._settings['pool_size']))

        while (self._pending or self._active) and not self._cancel:
            while self._pending and len(self._active) < pool:
                ip = self._pending.pop(0)
                worker = self._spawn(ip)
                self._active.append(worker)
                worker.start()
                if pool == 1:
                    break  # serial: one at a time
            self._reap()
            self.msleep(80)

        if self._cancel:
            for worker in list(self._active):
                worker.cancel()
            deadline = time.monotonic() + 5
            while self._active and time.monotonic() < deadline:
                self._reap()
                self.msleep(80)
            # Force-cancel any stragglers.  Workers blocked in connect() may
            # take up to ~10 s to fail; wait long enough so the thread is
            # always done before its last Python reference goes away.
            for worker in list(self._active):
                try:
                    worker.wait(12000)
                except Exception:
                    pass
                result = dict(worker.result)
                if result['status'] in (STATUS_PENDING, STATUS_RUNNING, STATUS_OK):
                    result['status'] = STATUS_CANCELLED
                    result['message'] = 'Cancelled by user'
                self._results.append(result)
                self.row_finished.emit(
                    result['ip'], result['duration'], result['status'],
                    result['message'], result['vendor'], result['log'])
                self._done += 1
                self.progress_changed.emit(self._done, total)
                self._active.remove(worker)
            for ip in list(self._pending):
                self._results.append({
                    'ip': ip, 'status': STATUS_CANCELLED, 'duration': 0.0,
                    'message': 'Cancelled before start',
                    'vendor': self._settings['vendor_key'], 'log': '',
                })
                self.row_finished.emit(ip, 0.0, STATUS_CANCELLED,
                                       'Cancelled before start',
                                       self._settings['vendor_key'], '')
                self._done += 1
                self.progress_changed.emit(self._done, total)
            self._pending = []

        duration = time.monotonic() - self._start_wall
        self._write_run_json(duration)
        self.run_finished.emit(self._dir, duration)

    # ------------------------------------------------------------------ #
    def _write_run_json(self, duration):
        data = {
            'started': datetime.fromtimestamp(
                time.time() - duration).isoformat(timespec='seconds'),
            'finished': datetime.now().isoformat(timespec='seconds'),
            'duration': round(duration, 2),
            'connection': self._settings['conn_type'],
            'port': self._settings['port'],
            'vendor': self._settings['vendor_key'],
            'parallel': bool(self._settings['parallel']),
            'results': self._results,
        }
        try:
            with open(os.path.join(self._dir, 'run.json'), 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            print(f'Warning: could not write run.json: {exc}')
