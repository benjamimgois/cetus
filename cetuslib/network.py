"""Network scanning, discovery, testing and visualization widgets for Cetus."""

import math
import time
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *


__all__ = [
    'IperfGraphWidget',
    'SignalHistoryWidget',
    'WifiChannelChart',
    'WifiHeatmapWidget',
    'RouteVisualizationWidget',
    'LatencyGraphWidget',
    'PingGraphWidget',
]


class IperfGraphWidget(QWidget):
    """Real-time iperf3 throughput chart — bitrate (left Y) and cumulative transfer (right Y)."""

    _COLOR_BITRATE  = QColor('#00897B')   # teal accent
    _COLOR_TRANSFER = QColor('#78909C')   # blue-grey for cumulative

    _COLOR_UPLOAD    = QColor('#E65100')
    _COLOR_UPLOAD_LT = QColor('#FFAB40')

    def __init__(self, parent=None):
        super().__init__(parent)
        self._intervals: list = []   # [(t_end_s, bitrate_mbps, transfer_mb, series)]
        self.setMinimumSize(300, 140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: transparent;")

    def add_interval(self, t_end: float, bitrate_mbps: float, transfer_mb: float,
                     series: int = 0):
        self._intervals.append((t_end, bitrate_mbps, transfer_mb, series))
        self.update()

    def clear(self):
        self._intervals = []
        self.update()

    def clear_series(self, series: int):
        """Remove all intervals belonging to *series*, keep others."""
        self._intervals = [item for item in self._intervals if item[3] != series]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W, H = self.width(), self.height()
        L, R, T, B = 62, 58, 22, 38

        plot_w = W - L - R
        plot_h = H - T - B

        TEAL      = QColor('#00897B')
        TEAL_LT   = QColor('#4DB6AC')
        TRANSFER  = QColor('#546E7A')

        # ── Background with subtle vignette ──────────────────────────────
        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0.0, QColor("#141B2D"))
        bg.setColorAt(0.6, QColor("#0D1117"))
        bg.setColorAt(1.0, QColor("#080D14"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, W, H, 12, 12)

        # border glow
        border_c = QColor(TEAL); border_c.setAlpha(60)
        painter.setPen(QPen(border_c, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, W - 1, H - 1, 12, 12)

        # ── Empty state ───────────────────────────────────────────────────
        if not self._intervals:
            painter.setPen(QColor("#2A3A4A"))
            painter.setFont(QFont("Sans Serif", 9))
            painter.drawText(0, 0, W, H, Qt.AlignmentFlag.AlignCenter,
                             "Run a test to see the graph")
            return

        # ── Data ranges ───────────────────────────────────────────────────
        max_t    = max(item[0] for item in self._intervals)
        max_bps  = max(item[1] for item in self._intervals)
        max_bps  = max(max_bps * 1.25, 1.0)
        max_xfer = max(item[2] for item in self._intervals)
        max_xfer = max(max_xfer * 1.25, 1.0)
        peak_bps = max(item[1] for item in self._intervals)

        def px(t): return L + (t / max(max_t, 1)) * plot_w
        def py(b): return T + plot_h - (b / max_bps) * plot_h
        def py2(x): return T + plot_h - (x / max_xfer) * plot_h

        def fmt_bps(v):
            if v >= 1000: return f"{v/1000:.2f} Gbps"
            return f"{v:.1f} Mbps"
        def fmt_mb(v):
            if v >= 1024: return f"{v/1024:.2f} GB"
            return f"{v:.1f} MB"

        # ── Horizontal grid lines (dotted) ────────────────────────────────
        painter.setFont(QFont("Monospace", 7))
        for i in range(5):
            frac = i / 4
            y_g  = T + plot_h - frac * plot_h
            val  = frac * max_bps
            # grid
            dot_pen = QPen(QColor("#1A2A3A"))
            dot_pen.setWidth(1)
            dot_pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(dot_pen)
            painter.drawLine(L, int(y_g), L + plot_w, int(y_g))
            # left label
            lbl_c = QColor(TEAL_LT); lbl_c.setAlpha(160)
            painter.setPen(lbl_c)
            unit = "Gbps" if val >= 1000 else "Mbps"
            disp = f"{val/1000:.1f}" if val >= 1000 else f"{val:.0f}"
            painter.drawText(0, int(y_g) - 8, L - 5, 16,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{disp}{unit}")
            # right label (transfer)
            val2 = frac * max_xfer
            painter.setPen(QColor("#546E7A"))
            u2 = "GB" if val2 >= 1024 else "MB"
            d2 = f"{val2/1024:.1f}" if val2 >= 1024 else f"{val2:.0f}"
            painter.drawText(L + plot_w + 5, int(y_g) - 8, R - 5, 16,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{d2}{u2}")

        # ── Peak bitrate horizontal marker ────────────────────────────────
        y_peak = py(peak_bps)
        peak_pen = QPen(QColor(TEAL_LT))
        peak_pen.setWidth(1)
        peak_pen.setStyle(Qt.PenStyle.DashDotLine)
        peak_pen.setColor(QColor(76, 182, 172, 80))
        painter.setPen(peak_pen)
        painter.drawLine(L, int(y_peak), L + plot_w, int(y_peak))

        # ── Axes ──────────────────────────────────────────────────────────
        axis_c = QColor(TEAL); axis_c.setAlpha(90)
        painter.setPen(QPen(axis_c, 1))
        painter.drawLine(L, T, L, T + plot_h)
        painter.drawLine(L, T + plot_h, L + plot_w, T + plot_h)
        axis_r = QColor(TRANSFER); axis_r.setAlpha(70)
        painter.setPen(QPen(axis_r, 1))
        painter.drawLine(L + plot_w, T, L + plot_w, T + plot_h)

        # ── X axis ticks & "Time (s)" label ──────────────────────────────
        painter.setPen(QColor("#3A5060"))
        painter.setFont(QFont("Sans Serif", 7))
        painter.drawText(L, T + plot_h + 24, plot_w, 12,
                         Qt.AlignmentFlag.AlignCenter, "Time (s)")
        painter.setFont(QFont("Monospace", 7))
        n_ticks = min(len(self._intervals), 10)
        step = max(1, int(max_t / max(n_ticks, 1)))
        for t_tick in range(step, int(max_t) + 1, step):
            x_g = px(t_tick)
            tick_c = QColor(TEAL); tick_c.setAlpha(100)
            painter.setPen(tick_c)
            painter.drawLine(int(x_g), T + plot_h, int(x_g), T + plot_h + 4)
            painter.setPen(QColor("#4A7070"))
            painter.drawText(int(x_g) - 15, T + plot_h + 5, 30, 14,
                             Qt.AlignmentFlag.AlignCenter, str(t_tick))

        # ── Rotated axis labels ───────────────────────────────────────────
        painter.save()
        lbl_teal = QColor(TEAL_LT); lbl_teal.setAlpha(200)
        painter.setPen(lbl_teal)
        painter.setFont(QFont("Sans Serif", 8, QFont.Weight.Bold))
        painter.translate(10, T + plot_h // 2)
        painter.rotate(-90)
        painter.drawText(-40, -8, 80, 16, Qt.AlignmentFlag.AlignCenter, "Bitrate")
        painter.restore()

        painter.save()
        painter.setPen(QColor("#546E7A"))
        painter.setFont(QFont("Sans Serif", 8))
        painter.translate(W - 10, T + plot_h // 2)
        painter.rotate(90)
        painter.drawText(-40, -8, 80, 16, Qt.AlignmentFlag.AlignCenter, "Transfer")
        painter.restore()

        # ── Transfer: smooth filled area (behind bitrate) ─────────────────
        if len(self._intervals) >= 2:
            pts_x = [(px(item[0]), py2(item[2])) for item in self._intervals]
            xp = QPainterPath()
            xp.moveTo(pts_x[0][0], T + plot_h)
            xp.lineTo(pts_x[0][0], pts_x[0][1])
            for i in range(1, len(pts_x)):
                xp.lineTo(pts_x[i][0], pts_x[i][1])
            xp.lineTo(pts_x[-1][0], T + plot_h)
            xp.closeSubpath()
            xfr_grad = QLinearGradient(0, T, 0, T + plot_h)
            xfr_top = QColor(TRANSFER); xfr_top.setAlpha(35)
            xfr_bot = QColor(TRANSFER); xfr_bot.setAlpha(0)
            xfr_grad.setColorAt(0.0, xfr_top)
            xfr_grad.setColorAt(1.0, xfr_bot)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(xp, xfr_grad)
            # line
            xfr_line = QPainterPath()
            xfr_line.moveTo(pts_x[0][0], pts_x[0][1])
            for i in range(1, len(pts_x)):
                xfr_line.lineTo(pts_x[i][0], pts_x[i][1])
            xfr_lc = QColor(TRANSFER); xfr_lc.setAlpha(140)
            painter.setPen(QPen(xfr_lc, 1, Qt.PenStyle.DashLine))
            painter.drawPath(xfr_line)

        # ── Bitrate: series-aware filled area + neon glow ────────────────
        def _smooth_path(pts, close_bottom=False):
            p = QPainterPath()
            if close_bottom:
                p.moveTo(pts[0][0], T + plot_h)
                p.lineTo(pts[0][0], pts[0][1])
            else:
                p.moveTo(pts[0][0], pts[0][1])
            for i in range(1, len(pts)):
                cx = (pts[i-1][0] + pts[i][0]) / 2
                p.cubicTo(cx, pts[i-1][1], cx, pts[i][1], pts[i][0], pts[i][1])
            if close_bottom:
                p.lineTo(pts[-1][0], T + plot_h)
                p.closeSubpath()
            return p

        _SERIES_COLORS = {
            0: (TEAL,                  TEAL_LT),                  # download
            1: (self._COLOR_UPLOAD,    self._COLOR_UPLOAD_LT),    # upload
        }

        # Group intervals by series (preserving time order within each group)
        _series_pts: dict = {}
        for item in self._intervals:
            s = item[3]
            _series_pts.setdefault(s, []).append((px(item[0]), py(item[1])))

        for s_idx, pts_b in sorted(_series_pts.items()):
            c_main, c_lt = _SERIES_COLORS.get(s_idx, _SERIES_COLORS[0])
            if len(pts_b) >= 2:
                fill_path = _smooth_path(pts_b, close_bottom=True)
                grad1 = QLinearGradient(0, T, 0, T + plot_h)
                c1 = QColor(c_main); c1.setAlpha(110)
                c2 = QColor(c_main); c2.setAlpha(30)
                c3 = QColor(c_main); c3.setAlpha(5)
                grad1.setColorAt(0.0, c1); grad1.setColorAt(0.5, c2); grad1.setColorAt(1.0, c3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.fillPath(fill_path, grad1)

                line_path = _smooth_path(pts_b)
                for pw, pa in [(8, 15), (5, 35), (3, 70), (2, 150), (1, 255)]:
                    _c = QColor(c_lt if pw <= 2 else c_main); _c.setAlpha(pa)
                    pen = QPen(_c, pw)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.drawPath(line_path)
            elif len(pts_b) == 1:
                _, y0 = pts_b[0]
                for pw, pa in [(6, 30), (3, 100), (2, 220)]:
                    _c = QColor(c_main); _c.setAlpha(pa)
                    painter.setPen(QPen(_c, pw))
                    painter.drawLine(L, int(y0), L + plot_w, int(y0))

        # ── Glowing data point dots ───────────────────────────────────────
        painter.setPen(Qt.PenStyle.NoPen)
        for i, item in enumerate(self._intervals):
            t, b, _, s = item
            xp_d, yp_d = int(px(t)), int(py(b))
            c_main, c_lt = _SERIES_COLORS.get(s, _SERIES_COLORS[0])
            is_last = (i == len(self._intervals) - 1)
            if is_last:
                for r, a in [(7, 20), (5, 50), (3, 130), (2, 255)]:
                    gc = QColor(c_lt); gc.setAlpha(a)
                    painter.setBrush(gc)
                    painter.drawEllipse(xp_d - r, yp_d - r, r * 2, r * 2)
            else:
                gc = QColor(c_main); gc.setAlpha(180)
                painter.setBrush(gc)
                painter.drawEllipse(xp_d - 2, yp_d - 2, 4, 4)

        # ── Live value badge (last point) ─────────────────────────────────
        if self._intervals:
            t_last, b_last, _, s_last = self._intervals[-1]
            c_badge, _ = _SERIES_COLORS.get(s_last, _SERIES_COLORS[0])
            x_lp = int(px(t_last))
            y_lp = int(py(b_last))

            cur_c = QColor(c_badge); cur_c.setAlpha(50)
            painter.setPen(QPen(cur_c, 1, Qt.PenStyle.DashLine))
            painter.drawLine(x_lp, T, x_lp, T + plot_h)

            badge_txt = fmt_bps(b_last)
            fm = painter.fontMetrics()
            bw = fm.horizontalAdvance(badge_txt) + 12
            bh = 16
            bx = min(x_lp + 6, L + plot_w - bw - 2)
            by = max(T + 2, y_lp - bh - 4)
            badge_bg = QColor(c_badge); badge_bg.setAlpha(200)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(badge_bg)
            painter.drawRoundedRect(bx, by, bw, bh, 4, 4)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Monospace", 7, QFont.Weight.Bold))
            painter.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, badge_txt)



class SignalHistoryWidget(QWidget):
    """Time-series signal-strength graph for a selected WiFi network."""

    def __init__(self, parent=None):
        import time as _time
        super().__init__(parent)
        self._bssid  = None
        self._ssid   = ''
        self._points = []          # [(elapsed_s, dbm), ...]
        self._color  = QColor('#E91E63')
        self._t_ref  = _time.monotonic()  # monotonic epoch matching the scan timestamps
        self.setMinimumWidth(180)
        self.setStyleSheet("background: transparent;")

        self._window_s = 120        # visible time window in seconds
        self._loss_threshold_s = 15.0  # seconds without a point → "signal lost"

        self._audio_enabled       = True
        self._audio_last_ts       = None   # timestamp of last point when a tone was emitted
        self._audio_loss_last_played = None  # monotonic time of last loss tone (None = no outage yet)

        # Single worker thread + queue: only one aplay process at a time
        import queue as _q, threading as _th
        self._audio_queue = _q.Queue(maxsize=1)
        _worker = _th.Thread(target=self._audio_worker_loop,
                             args=(self._audio_queue,), daemon=True)
        _worker.start()

        # Continuous scroll: repaint at ~30 fps
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(33)
        self._scroll_timer.timeout.connect(self.update)

        # CRT Scanlines — enabled by default
        self._scanlines_enabled = True
        self._scanlines_offset  = 0.0
        self._scanlines_timer   = QTimer(self)
        self._scanlines_timer.setInterval(33)
        self._scanlines_timer.timeout.connect(self._update_scanlines)
        self._scanlines_timer.start()

    def set_window_s(self, seconds: int):
        """Change the X-axis time window and trigger a repaint."""
        self._window_s = max(30, int(seconds))
        self.update()

    def set_audio(self, enabled: bool):
        self._audio_enabled = enabled

    def set_scanlines(self, enabled: bool):
        """Enable or disable the CRT scanlines overlay."""
        self._scanlines_enabled = enabled
        if enabled:
            self._scanlines_timer.start()
        else:
            self._scanlines_timer.stop()
        self.update()

    def _update_scanlines(self):
        self._scanlines_offset = (self._scanlines_offset + 0.6) % 8.0
        self.update()

    # ── Audio helpers ─────────────────────────────────────────────────────────

    _AUDIO_RATE = 48000   # native PipeWire/PulseAudio rate — no resampling

    @staticmethod
    def _build_pcm(freq_hz: float, duration_ms: int,
                   volume: float = 0.45, sweep_to: float = None,
                   clip: float = 1.0) -> bytes:
        """Build S16LE mono PCM.  clip in (0, 1] controls waveform distortion:
        1.0 = clean sine, <1.0 clips the sine towards a square wave."""
        import math, struct
        rate = SignalHistoryWidget._AUDIO_RATE
        n    = int(rate * duration_ms / 1000)
        fade = max(1, min(int(rate * 0.010), n // 4))   # 10 ms fade
        clip = max(0.01, min(1.0, clip))
        pcm  = []
        for i in range(n):
            f = freq_hz if sweep_to is None else freq_hz + (sweep_to - freq_hz) * i / n
            s = math.sin(2.0 * math.pi * f * i / rate)
            s = max(-clip, min(clip, s)) / clip   # clip then re-normalise to ±1
            s *= volume
            s *= min(i / fade, 1.0, (n - i) / fade)
            pcm.append(max(-32767, min(32767, int(s * 32767))))
        return struct.pack(f'<{n}h', *pcm)

    @staticmethod
    def _make_wav(pcm_bytes: bytes) -> bytes:
        """Wrap S16LE mono PCM in a minimal WAV container."""
        import struct
        rate = SignalHistoryWidget._AUDIO_RATE
        dlen = len(pcm_bytes)
        hdr  = struct.pack('<4sI4s4sIHHIIHH4sI',
                           b'RIFF', 36 + dlen, b'WAVE',
                           b'fmt ', 16, 1, 1, rate, rate * 2, 2, 16,
                           b'data', dlen)
        return hdr + pcm_bytes

    @staticmethod
    def _audio_worker_loop(q):
        """Single consumer: writes WAV to a temp file and plays it in full."""
        import subprocess, shutil, tempfile, os
        player = ('paplay' if shutil.which('paplay')
                  else 'aplay' if shutil.which('aplay')
                  else None)
        while True:
            wav = q.get()
            if wav is None:
                break
            if player is None:
                continue
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(
                        suffix='.wav', delete=False) as f:
                    f.write(wav)
                    tmp = f.name
                cmd = ([player, '--volume=65536', tmp]
                       if player == 'paplay' else [player, tmp])
                subprocess.run(cmd, stderr=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL)
            except Exception:
                pass
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    def _enqueue(self, wav: bytes):
        """Put WAV into the queue; replace stale item if full."""
        try:
            self._audio_queue.put_nowait(wav)
        except Exception:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(wav)
            except Exception:
                pass

    @staticmethod
    def _preroll(ms: int = 250) -> bytes:
        """Silent pre-roll: gives a suspended audio device time to wake up
        before the first audible sample arrives."""
        return bytes(int(SignalHistoryWidget._AUDIO_RATE * ms / 1000) * 2)

    def _trigger_signal_tone(self, dbm: float):
        """Double beep pitched to signal strength."""
        freq = 250 + (dbm - (-100)) / 80.0 * 1550
        freq = max(250.0, min(1800.0, freq))
        rate = self._AUDIO_RATE
        beep = self._build_pcm(freq, 150)
        gap  = bytes(int(rate * 0.130) * 2)
        self._enqueue(self._make_wav(self._preroll() + beep + gap + beep))

    def _trigger_loss_tone(self):
        """Harsh repeating alarm on signal loss: three sharp blips + falling sweep."""
        rate    = self._AUDIO_RATE
        silence = bytes(int(rate * 0.055) * 2)          # 55 ms gap between blips
        # Sharp clipped blips (square-wave-like, high-freq → uncomfortable)
        blip    = self._build_pcm(1900, 90, volume=0.80, clip=0.25)
        # Falling glide (ominous "signal dying" sweep)
        fall    = self._build_pcm(1600, 400, volume=0.70, clip=0.40, sweep_to=220)
        self._enqueue(self._make_wav(
            self._preroll(100)
            + blip + silence + blip + silence + blip
            + silence + fall
        ))

    def set_network(self, bssid, ssid, points, color=None, t_ref=None):
        _prev_last_ts = self._points[-1][0] if self._points else None

        self._bssid  = bssid
        self._ssid   = ssid
        self._points = list(points)
        if color is not None:
            self._color = QColor(color) if isinstance(color, str) else color
        if t_ref is not None:
            self._t_ref = t_ref

        # ── Audio feedback ────────────────────────────────────────────────────
        if self._audio_enabled and self._points:
            _new_last_ts  = self._points[-1][0]
            _new_last_dbm = self._points[-1][1]
            if _new_last_ts != _prev_last_ts:
                # Fresh measurement arrived — play signal tone and clear loss state
                self._trigger_signal_tone(_new_last_dbm)
                self._audio_last_ts       = _new_last_ts
                self._audio_loss_last_played = None
            else:
                # No new point — check if signal is lost and repeat alarm every 4 s
                import time as _t
                _now_mono = _t.monotonic()
                _age = _now_mono - self._t_ref - _new_last_ts
                if _age >= self._loss_threshold_s:
                    _repeat_s = 4.0
                    if (self._audio_loss_last_played is None or
                            _now_mono - self._audio_loss_last_played >= _repeat_s):
                        self._trigger_loss_tone()
                        self._audio_loss_last_played = _now_mono

        if not self._scroll_timer.isActive():
            self._scroll_timer.start()
        self.update()

    def hideEvent(self, event):
        self._scroll_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if self._bssid:
            self._scroll_timer.start()
        super().showEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        PL, PR, PT, PB = 46, 40, 22, 28
        cw, ch = W - PL - PR, H - PT - PB

        # Clip all painting to the rounded rectangle so corners stay clean
        _clip = QPainterPath()
        _clip.addRoundedRect(0.0, 0.0, float(W), float(H), 10.0, 10.0)
        painter.setClipPath(_clip)

        # Background
        painter.fillRect(0, 0, W, H, QColor('#0D1117'))

        if not self._bssid:
            painter.setPen(QColor('#8b949e'))
            painter.setFont(QFont('Sans Serif', 8))
            painter.drawText(0, 0, W, H, Qt.AlignmentFlag.AlignCenter,
                             'Select a network\nto see signal history')
            return

        # dBm axis range (Left Y)
        DBM_MIN, DBM_MAX = -100, -20
        # Score axis range (Right Y)
        SCORE_MIN, SCORE_MAX = 0, 100

        # "Now" on the right side: each point is positioned by its AGE
        # as time passes the age increases and the point slides to the left
        import time as _time
        now = _time.monotonic() - self._t_ref  # current time in seconds since scan start
        W_S = float(self._window_s)

        def _x(pt):
            """Posição X de um ponto: direita = agora, esquerda = agora - _window_s."""
            age = now - pt
            return PL + (1.0 - age / W_S) * cw

        def _y_dbm(dbm):
            clamped = max(DBM_MIN, min(DBM_MAX, dbm))
            return PT + ch - (clamped - DBM_MIN) / (DBM_MAX - DBM_MIN) * ch

        def _y_score(score):
            clamped = max(SCORE_MIN, min(SCORE_MAX, score))
            return PT + ch - (clamped - SCORE_MIN) / (SCORE_MAX - SCORE_MIN) * ch

        # Grid horizontal (dBm) - aligns with left Y
        grid_pen = QPen(QColor('#21262d'))
        grid_pen.setWidthF(0.8)
        painter.setPen(grid_pen)
        for dbm in range(DBM_MIN, DBM_MAX + 1, 10):
            y = int(_y_dbm(dbm))
            painter.drawLine(PL, y, PL + cw, y)

        # Grid step: adapts to the visible window
        if W_S <= 60:
            step_s = 10
        elif W_S <= 180:
            step_s = 30
        elif W_S <= 360:
            step_s = 60
        else:
            step_s = 120

        # Grid vertical
        for age_mark in range(step_s, int(W_S) + 1, step_s):
            x = int(PL + (1.0 - age_mark / W_S) * cw)
            if PL <= x <= PL + cw:
                painter.drawLine(x, PT, x, PT + ch)

        # Axes borders
        ax_pen = QPen(QColor('#30363d'))
        painter.setPen(ax_pen)
        painter.drawLine(PL, PT, PL, PT + ch)            # Left Y
        painter.drawLine(PL + cw, PT, PL + cw, PT + ch)  # Right Y
        painter.drawLine(PL, PT + ch, PL + cw, PT + ch)  # Bottom X

        # Left Y-axis labels (dBm)
        painter.setFont(QFont('Sans Serif', 7))
        painter.setPen(QColor('#8b949e'))
        for dbm in range(DBM_MIN, DBM_MAX + 1, 10):
            y = int(_y_dbm(dbm))
            painter.drawText(0, y - 7, PL - 4, 14,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             str(dbm))

        # Right Y-axis labels (Score)
        painter.setPen(QColor('#f57f17'))  # Amber color for score labels
        for score in range(SCORE_MIN, SCORE_MAX + 1, 25):
            y = int(_y_score(score))
            painter.drawText(PL + cw + 4, y - 7, PR - 4, 14,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             str(score))
        
        # Right Y-axis Title
        painter.save()
        painter.translate(PL + cw + PR - 8, PT + ch // 2)
        painter.rotate(-90)
        painter.drawText(-60, -8, 120, 16, Qt.AlignmentFlag.AlignCenter, "Ch. Score")
        painter.restore()

        # X-axis labels
        painter.setFont(QFont('Sans Serif', 7))
        painter.setPen(QColor('#8b949e'))
        for age_mark in range(0, int(W_S) + 1, step_s):
            x = int(PL + (1.0 - age_mark / W_S) * cw)
            label = 'now' if age_mark == 0 else f'-{age_mark}s'
            painter.drawText(x - 22, PT + ch + 3, 44, 14,
                             Qt.AlignmentFlag.AlignCenter, label)

        # Signal curve: filter points within the time window
        # Element format: (pt_ts, dbm, [score_optional])
        visible = [p for p in self._points if 0.0 <= (now - p[0]) <= W_S]

        # Split into continuous segments — breaks at any gap >= threshold so
        # the curve is never drawn through a signal-loss region.
        _segs = []
        if visible:
            _seg = [visible[0]]
            for _i in range(1, len(visible)):
                if visible[_i][0] - visible[_i - 1][0] >= self._loss_threshold_s:
                    _segs.append(_seg)
                    _seg = [visible[_i]]
                else:
                    _seg.append(visible[_i])
            _segs.append(_seg)

        color = self._color

        for _seg in _segs:
            if len(_seg) >= 2:
                # Filled area (signal)
                area = QPainterPath()
                area.moveTo(_x(_seg[0][0]), _y_dbm(DBM_MIN))
                area.lineTo(_x(_seg[0][0]), _y_dbm(_seg[0][1]))
                for p in _seg[1:]:
                    area.lineTo(_x(p[0]), _y_dbm(p[1]))
                area.lineTo(_x(_seg[-1][0]), _y_dbm(DBM_MIN))
                area.closeSubpath()
                fill = QColor(color)
                fill.setAlpha(35)
                painter.setBrush(fill)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(area)

                # Line (signal)
                line = QPainterPath()
                line.moveTo(_x(_seg[0][0]), _y_dbm(_seg[0][1]))
                for p in _seg[1:]:
                    line.lineTo(_x(p[0]), _y_dbm(p[1]))
                lp = QPen(color)
                lp.setWidthF(1.8)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(lp)
                painter.drawPath(line)
                
                # Line (score) - if available
                if len(_seg[0]) > 2:
                    score_line = QPainterPath()
                    score_line.moveTo(_x(_seg[0][0]), _y_score(_seg[0][2]))
                    for p in _seg[1:]:
                        if len(p) > 2:
                            score_line.lineTo(_x(p[0]), _y_score(p[2]))
                    sp = QPen(QColor(245, 127, 23, 160))  # Semi-transparent amber + dashed
                    sp.setWidthF(1.5)
                    sp.setStyle(Qt.PenStyle.DashLine)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(sp)
                    painter.drawPath(score_line)

            elif len(_seg) == 1:
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(_x(_seg[0][0]), _y_dbm(_seg[0][1])), 3.5, 3.5)
                if len(_seg[0]) > 2:
                    painter.setBrush(QColor(245, 127, 23, 160))
                    painter.drawEllipse(QPointF(_x(_seg[0][0]), _y_score(_seg[0][2])), 2.5, 2.5)

        # Dot + label on the most recent point of the last segment
        if _segs and _segs[-1]:
            _last = _segs[-1][-1]
            lx = _x(_last[0])
            ly_dbm = _y_dbm(_last[1])
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(lx, ly_dbm), 3.5, 3.5)
            painter.setFont(QFont('Sans Serif', 7, QFont.Weight.Bold))
            painter.setPen(color)
            painter.drawText(int(lx) + 5, int(ly_dbm) + 4, f'{int(_last[1])} dBm')
            
            # Score label
            if len(_last) > 2:
                ly_score = _y_score(_last[2])
                painter.setBrush(QColor(245, 127, 23))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(lx, ly_score), 2.5, 2.5)
                painter.setPen(QColor(245, 127, 23))
                painter.drawText(int(lx) + 5, int(ly_score) - 4, f'Score: {int(_last[2])}')

        # ── Signal-loss markers ───────────────────────────────────────────────
        # Collect every dropout event from the full point history:
        #   • gaps between consecutive points >= threshold  (historical)
        #   • trailing gap from last point to "now" >= threshold  (ongoing)
        # Each event is (t_loss, t_recovery_or_None).
        # Markers are drawn even after the signal recovers so the history
        # of outages stays visible as the time axis scrolls.
        _pts = self._points
        _loss_events = []
        for _i in range(len(_pts) - 1):
            _t1 = _pts[_i][0]
            _t2 = _pts[_i + 1][0]
            if _t2 - _t1 >= self._loss_threshold_s:
                _loss_events.append((_t1, _t2))
        if _pts and (now - _pts[-1][0]) >= self._loss_threshold_s:
            _loss_events.append((_pts[-1][0], None))  # still lost

        _loss_pen = QPen(QColor(220, 40, 40, 230))
        _loss_pen.setWidthF(3.0)
        for _t_loss, _t_rec in _loss_events:
            _lx = _x(_t_loss)
            if not (PL <= _lx <= PL + cw):
                continue
            _lxi = int(_lx)
            # Red wash from loss point to recovery (or right edge if still lost)
            _rx = min(int(_x(_t_rec)), PL + cw) if _t_rec is not None else PL + cw
            if _rx > _lxi:
                painter.fillRect(_lxi, PT, _rx - _lxi, ch, QColor(220, 40, 40, 30))
            # Vertical bar
            painter.setPen(_loss_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(_lxi, PT, _lxi, PT + ch)
            # Label
            painter.setFont(QFont('Sans Serif', 7, QFont.Weight.Bold))
            painter.setPen(QColor(220, 70, 70))
            painter.drawText(_lxi + 5, PT + 14, 'Signal lost')

        # Title — "Power Analysis" + SSID · BSSID subtitle
        painter.setFont(QFont('Sans Serif', 8, QFont.Weight.Bold))
        painter.setPen(QColor('#c9d1d9'))
        painter.drawText(PL, 1, cw, 12, Qt.AlignmentFlag.AlignCenter, 'Power Analysis')

        ssid_label = self._ssid if self._ssid and self._ssid != '<hidden>' else '<hidden>'
        subtitle = f'{ssid_label}  ·  {self._bssid}'
        painter.setFont(QFont('Sans Serif', 7))
        painter.setPen(QColor('#8b949e'))
        painter.drawText(PL, 12, cw, 10, Qt.AlignmentFlag.AlignCenter, subtitle)

        # Y-axis title (rotated)
        painter.save()
        painter.translate(9, PT + ch // 2)
        painter.rotate(-90)
        painter.setFont(QFont('Sans Serif', 7))
        painter.setPen(QColor('#8b949e'))
        painter.drawText(-20, -8, 40, 16, Qt.AlignmentFlag.AlignCenter, 'dBm')
        painter.restore()

        # X-axis title
        painter.setFont(QFont('Sans Serif', 7))
        painter.setPen(QColor('#8b949e'))
        painter.drawText(PL, PT + ch + 16, cw, 12, Qt.AlignmentFlag.AlignCenter, 'Time (s)')

        # ── CRT Scanlines overlay ───────────────────────────────────────────
        if getattr(self, '_scanlines_enabled', False):
            from PyQt6.QtCore import QRectF as _QRF
            _sl_spacing  = 8
            _sl_thickness = 2
            painter.setClipRect(_QRF(PL, PT, cw, ch))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 55))
            _offset = int(getattr(self, '_scanlines_offset', 0.0)) % _sl_spacing
            _y2 = PT - _sl_spacing + _offset
            while _y2 < PT + ch + _sl_spacing:
                painter.drawRect(_QRF(PL, _y2, cw, _sl_thickness))
                _y2 += _sl_spacing
            painter.setClipping(False)



class WifiChannelChart(QWidget):
    """Custom widget that draws a bar chart of WiFi channel usage."""

    carrier_clicked = pyqtSignal(str, str)  # bssid, ssid

    def __init__(self, parent=None):
        from PyQt6.QtCore import QTimer
        super().__init__(parent)
        self.networks = []   # list of dicts: {channel, signal_pct, ssid, band, bandwidth}
        self.band = '2.4GHz'
        self.setMinimumHeight(240)
        self.setStyleSheet("background: transparent;")
        self._animated_sig = {}   # channel → current animated signal value (float)
        self._target_sig = {}     # channel → target signal value
        self._ch_bandwidth = {}   # channel → max bandwidth in MHz
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)  # ~30 fps
        self._anim_timer.timeout.connect(self._anim_step)

        # Mouse tracking for tooltips
        self.setMouseTracking(True)
        self._hovered_ssid = None
        self._selected_bssid = None  # BSSID highlighted from table selection
        self._ssid_curves = {}  # ssid_bssid → curve info for hit detection
        self._hidden_ssids = set()  # Set of hidden SSIDs

        # Best-channel tooltip state (populated during paintEvent)
        self._best_ch_info       = None   # (channel, reason_str, ch_load_dict)
        self._best_ch_badge_rect = None   # QRectF of the badge for hit testing
        self._frozen_best_ch_info = None  # set after survey finishes; overrides live computation
        self._avoid_dfs = True            # when True, DFS channels are excluded from best-ch selection

        # Measured noise floors (updated after each scan via iw survey dump)
        self._noise_floor_24 = -95   # 2.4 GHz default dBm
        self._noise_floor_5  = -92   # 5 GHz default dBm

        # White noise generator — enabled by default
        self._noise_enabled = True
        self._noise_cache   = None  # invalidated when band changes or noise toggled
        self._noise_timer   = QTimer(self)
        self._noise_timer.setInterval(33)   # 30 fps
        self._noise_timer.timeout.connect(self._update_noise)
        self._noise_timer.start()

        # Glow effect — disabled by default
        self._glow_enabled = False

        # Scanlines (CRT) effect — enabled by default
        self._scanlines_enabled = True
        self._scanlines_offset  = 0.0   # scroll position (pixels, wraps)
        self._scanlines_timer   = QTimer(self)
        self._scanlines_timer.setInterval(33)   # 30 fps
        self._scanlines_timer.timeout.connect(self._update_scanlines)
        self._scanlines_timer.start()   # start immediately (enabled by default)

        # Tooltip styling
        self.setStyleSheet("""
            QToolTip {
                background-color: #1A1F2E;
                color: #AABBCC;
                border: 1px solid #3A4460;
                border-radius: 6px;
                padding: 6px;
                font-size: 9pt;
            }
        """)

    def set_networks(self, networks, band='2.4GHz'):
        self.networks = networks
        self.band = band
        # Build signal targets per channel for animation
        # We'll animate based on the strongest signal per channel
        new_targets = {}
        new_bandwidths = {}
        # Compute channel-load for score annotation
        _ch_load: dict = {}
        for net in networks:
            ch = net.get('channel')
            sig = net.get('signal_pct', 0)
            bw = net.get('bandwidth', 20)
            if ch is not None:
                new_targets[ch] = max(new_targets.get(ch, 0), sig)
                new_bandwidths[ch] = max(new_bandwidths.get(ch, 20), bw)
                _ch_load[ch] = _ch_load.get(ch, 0) + sig
        _max_load = max(_ch_load.values()) if _ch_load else 1
        for net in networks:
            _c = net.get('channel')
            _raw = _ch_load.get(_c, 0) if _c is not None else 0
            if 'channel_score' not in net:  # don't overwrite if already set by UI
                net['channel_score'] = min(100, round(_raw * 100 / max(_max_load, 1)))
        # Include channels still animating down to 0
        all_channels = set(self._animated_sig.keys()) | set(new_targets.keys())
        self._target_sig = {ch: new_targets.get(ch, 0) for ch in all_channels}
        self._ch_bandwidth = {ch: new_bandwidths.get(ch, 20) for ch in all_channels}
        for ch in all_channels:
            if ch not in self._animated_sig:
                self._animated_sig[ch] = 0.0
        self._anim_timer.start()

    def _anim_step(self):
        done = True
        for ch in list(self._animated_sig.keys()):
            target = self._target_sig.get(ch, 0)
            current = self._animated_sig[ch]
            diff = target - current
            if abs(diff) < 0.4:
                self._animated_sig[ch] = float(target)
            else:
                self._animated_sig[ch] = current + diff * 0.14
                done = False
        # Remove channels that settled at 0 and are no longer needed
        self._animated_sig = {
            ch: v for ch, v in self._animated_sig.items()
            if v > 0.1 or self._target_sig.get(ch, 0) > 0
        }
        if done:
            self._anim_timer.stop()
        self.update()

    def _channel_to_freq(self, channel):
        """Convert WiFi channel number to frequency in MHz"""
        if channel >= 1 and channel <= 13:
            # 2.4 GHz band
            return 2412 + (channel - 1) * 5
        elif channel == 14:
            return 2484
        elif channel >= 36 and channel <= 177:
            # 5 GHz band
            return 5000 + channel * 5
        return 2412  # fallback

    def _freq_to_x(self, freq_mhz, freq_min, freq_max, chart_w, pad_l):
        """Convert frequency in MHz to X coordinate"""
        if freq_max <= freq_min:
            return pad_l
        pct = (freq_mhz - freq_min) / (freq_max - freq_min)
        pct = max(0, min(1, pct))
        return pad_l + int(chart_w * pct)

    def _dbm_to_y(self, dbm, chart_h, pad_t, dbm_min=-100, dbm_max=-50):
        """Convert dBm value to Y coordinate"""
        pct = (dbm - dbm_min) / (dbm_max - dbm_min)
        pct = max(0, min(1, pct))
        return pad_t + chart_h - int(chart_h * pct)

    def _gaussian(self, x, center, sigma):
        """Calculate gaussian curve value at position x"""
        import math
        return math.exp(-0.5 * ((x - center) / sigma) ** 2)

    # ── White noise ───────────────────────────────────────────────────────────

    def set_noise_floors(self, noise_24, noise_5):
        """Update measured noise floors and redraw. None values keep current defaults."""
        if noise_24 is not None:
            self._noise_floor_24 = noise_24
        if noise_5 is not None:
            self._noise_floor_5 = noise_5
        self.update()

    def set_noise(self, enabled: bool):
        """Enable or disable the animated white-noise overlay."""
        self._noise_enabled = enabled
        self._noise_cache   = None   # invalidate so next frame is fresh
        if enabled:
            self._noise_timer.start()
        else:
            self._noise_timer.stop()
        self.update()

    def _update_noise(self):
        """Request a repaint; noise is computed fresh inside paintEvent."""
        self.update()

    def set_glow(self, enabled: bool):
        """Enable or disable the peak radial glow burst."""
        self._glow_enabled = enabled
        self.update()

    def set_interference(self, enabled: bool):
        """Enable or disable the interference heat pulse overlay."""
        self._interference_enabled = enabled
        self.update()

    def set_score(self, enabled: bool):
        """Enable or disable the per-channel congestion score bar."""
        self._score_enabled = enabled
        self.update()

    def set_scanlines(self, enabled: bool):
        """Enable or disable the CRT scanlines overlay."""
        self._scanlines_enabled = enabled
        if enabled:
            self._scanlines_timer.start()
        else:
            self._scanlines_timer.stop()
        self.update()

    def _update_scanlines(self):
        """Advance scanlines scroll and request repaint."""
        self._scanlines_offset = (self._scanlines_offset + 0.6) % 8.0
        self.update()

    # ── BSSID selection ───────────────────────────────────────────────────────

    def select_bssid(self, bssid):
        """Highlight a specific BSSID from table selection."""
        self._selected_bssid = bssid
        self.update()

    def _bssid_color(self, bssid, ssid=''):
        """Generate a stable, well-distributed HSL color from BSSID/SSID hash."""
        import hashlib
        from PyQt6.QtGui import QColor
        key = (bssid or ssid or 'unknown').encode()
        h = int(hashlib.md5(key).hexdigest()[:6], 16)
        # Golden-angle distribution across hue wheel for maximum separation
        hue = (h * 137.508) % 360
        color = QColor.fromHsvF(hue / 360.0, 0.88, 1.0)
        return color.name()

    def paintEvent(self, event):
        from PyQt6.QtGui import (QPainter, QColor, QFont, QPen,
                                  QLinearGradient, QPainterPath)
        from PyQt6.QtCore import Qt, QRectF, QPointF
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W = self.width()
        H = self.height()
        pad_l, pad_r, pad_b, pad_t = 44, 16, 25, 22
        chart_w = W - pad_l - pad_r
        chart_h = H - pad_b - pad_t

        # dBm range for display (dbm_max is set dynamically after collecting networks)
        dbm_min = -100

        # Frequency ranges for selected band
        if self.band == '2.4GHz':
            freq_min, freq_max = 2400, 2500  # MHz
            noise_floor = self._noise_floor_24
            # Channels for reference
            channels = list(range(1, 14))
            show_both_bands = False
        elif self.band == '5GHz':
            freq_min, freq_max = 5150, 5850  # MHz
            noise_floor = self._noise_floor_5
            # Channels for reference
            channels = [36, 40, 44, 48, 52, 56, 60, 64,
                        100, 104, 108, 112, 116, 120, 124, 128,
                        132, 136, 140, 149, 153, 157, 161, 165]
            show_both_bands = False
        else:  # Both bands
            freq_min, freq_max = 2400, 5900  # MHz - full range
            noise_floor = self._noise_floor_24  # reference for single-floor fallback
            channels = []  # Will be handled differently
            show_both_bands = True

        # Collect individual networks (by SSID)
        # Check for hidden SSIDs filter
        hidden_ssids = getattr(self, '_hidden_ssids', set())

        all_networks = []
        for net in self.networks:
            ch = net.get('channel')
            net_band = net.get('band', '')
            ssid = net.get('ssid', '') or '<hidden>'

            # Skip hidden SSIDs
            if ssid in hidden_ssids:
                continue

            # Filter by band (skip filter if showing both bands)
            if not show_both_bands and net_band != self.band:
                continue
            # Get frequency
            net_freq = net.get('freq_mhz', self._channel_to_freq(ch))
            # Check if frequency is in range
            if net_freq < freq_min or net_freq > freq_max:
                continue

            sig_pct = net.get('signal_pct', 0)
            # Apply animation factor based on channel
            ch_anim = self._animated_sig.get(ch, 0.0)
            ch_target = self._target_sig.get(ch, 0.0)
            if ch_target > 0:
                anim_factor = ch_anim / ch_target
            else:
                anim_factor = 0.0
            # Animated signal for this network
            display_sig = sig_pct * anim_factor
            if display_sig > 0.5:  # Only show if visible
                # Convert signal percentage to dBm
                dbm = (display_sig / 2) - 100
                net_copy = net.copy()
                net_copy['display_dbm'] = dbm
                all_networks.append(net_copy)

        # ── Dynamic Y-axis range ──────────────────────────────────────────
        # Find the strongest signal and add 15 dBm headroom so curves never
        # hit the ceiling. Clamp between -45 (min headroom) and -20 (max).
        if all_networks:
            max_dbm = max(n.get('display_dbm', -100) for n in all_networks)
            dbm_max = max(-45, min(-20, int(max_dbm) + 15))
        else:
            dbm_max = -45

        # ── Grid lines + Y-axis labels (dBm) ─────────────────────────────
        font_mono = QFont('Monospace', 7)
        painter.setFont(font_mono)
        # Generate grid ticks every 10 dBm within the dynamic range
        grid_top = (dbm_max // 10) * 10  # round down to nearest 10
        for dbm_val in range(grid_top, dbm_min - 1, -10):
            y = self._dbm_to_y(dbm_val, chart_h, pad_t, dbm_min, dbm_max)
            grid_pen = QPen(QColor('#1E2A3A'))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            painter.drawLine(pad_l, y, W - pad_r, y)
            painter.setPen(QColor('#3A4460'))
            painter.drawText(0, y - 7, pad_l - 6, 14,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             str(dbm_val))

        # ── Axes ─────────────────────────────────────────────────────────
        axis_pen = QPen(QColor('#2A3A50'))
        axis_pen.setWidth(1)
        painter.setPen(axis_pen)
        painter.drawLine(pad_l, pad_t, pad_l, pad_t + chart_h)
        painter.drawLine(pad_l, pad_t + chart_h, W - pad_r, pad_t + chart_h)

        # ── Noise Floor ──────────────────────────────────────────────────
        if show_both_bands:
            # Draw two noise floors for both bands
            # 2.4GHz noise floor in left region
            noise_24_y = self._dbm_to_y(self._noise_floor_24, chart_h, pad_t, dbm_min, dbm_max)
            freq_24_end = self._freq_to_x(2500, freq_min, freq_max, chart_w, pad_l)
            noise_pen = QPen(QColor('#FF6B6B'))
            noise_pen.setWidth(2)
            noise_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(noise_pen)
            painter.drawLine(pad_l, noise_24_y, freq_24_end, noise_24_y)

            # 5GHz noise floor in right region
            noise_5_y = self._dbm_to_y(self._noise_floor_5, chart_h, pad_t, dbm_min, dbm_max)
            freq_5_start = self._freq_to_x(5150, freq_min, freq_max, chart_w, pad_l)
            painter.drawLine(freq_5_start, noise_5_y, W - pad_r, noise_5_y)

            # Labels
            painter.setPen(QColor('#FF6B6B'))
            painter.setFont(QFont('Sans Serif', 7))
            painter.drawText(pad_l + 5, noise_24_y - 12, 80, 10,
                            Qt.AlignmentFlag.AlignLeft, f'2.4G Floor ({self._noise_floor_24})')
            painter.drawText(W - pad_r - 80, noise_5_y - 12, 75, 10,
                            Qt.AlignmentFlag.AlignRight, f'5G Floor ({self._noise_floor_5})')
            painter.setFont(font_mono)
        else:
            # Single noise floor
            noise_y = self._dbm_to_y(noise_floor, chart_h, pad_t, dbm_min, dbm_max)
            noise_pen = QPen(QColor('#FF6B6B'))
            noise_pen.setWidth(2)
            noise_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(noise_pen)
            painter.drawLine(pad_l, noise_y, W - pad_r, noise_y)
            # Noise floor label
            painter.setPen(QColor('#FF6B6B'))
            painter.setFont(QFont('Sans Serif', 7))
            painter.drawText(W - pad_r - 80, noise_y - 12, 75, 10,
                             Qt.AlignmentFlag.AlignRight, f'Noise Floor ({noise_floor} dBm)')
            painter.setFont(font_mono)

        # ── DFS Channel Shading (5GHz only) ──────────────────────────────
        # Two contiguous DFS ranges: ch52-64 (5250–5330 MHz) and ch100-140 (5490–5710 MHz)
        if self.band in ('5GHz',) and not show_both_bands:
            _dfs_ranges = [(5250, 5330), (5490, 5710)]
            for _df_lo, _df_hi in _dfs_ranges:
                _dx1 = self._freq_to_x(_df_lo, freq_min, freq_max, chart_w, pad_l)
                _dx2 = self._freq_to_x(_df_hi, freq_min, freq_max, chart_w, pad_l)
                # Translucent amber fill
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 160, 0, 22))
                painter.drawRect(int(_dx1), pad_t, int(_dx2 - _dx1), chart_h)
                # Top border line
                _dfs_pen = QPen(QColor(255, 160, 0, 80))
                _dfs_pen.setWidth(1)
                _dfs_pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(_dfs_pen)
                painter.drawLine(int(_dx1), pad_t, int(_dx1), pad_t + chart_h)
                painter.drawLine(int(_dx2), pad_t, int(_dx2), pad_t + chart_h)
                # "DFS" label at top-centre of the region
                painter.setPen(QColor(255, 160, 0, 140))
                painter.setFont(QFont('Sans Serif', 7, QFont.Weight.Bold))
                painter.drawText(int(_dx1), pad_t + 2, int(_dx2 - _dx1), 12,
                                 Qt.AlignmentFlag.AlignCenter, 'DFS')
            painter.setFont(font_mono)

        # ── Gaussian Curves for each network (grouped by BSSID) ──────────

        # Sort weakest first so strongest signals render on top
        all_networks.sort(key=lambda n: n.get('display_dbm', -100))

        # Clear curve tracking for hover detection
        self._ssid_curves = {}

        # Track label placements for collision avoidance: list of (x1, y1, x2, y2)
        placed_labels = []

        # ── Best Channel: compute least-congested channel ─────────────────
        # Only when not showing both bands simultaneously
        _best_ch = None
        _best_ch_x = None
        _ch_load = {}
        if not show_both_bands and all_networks:
            _ch_load = {}
            for _n in all_networks:
                _c = _n.get('channel')
                if _c is not None:
                    _ch_load[_c] = _ch_load.get(_c, 0) + _n.get('signal_pct', 0)
            # If a frozen survey result exists, use it instead of live computation
            if self._frozen_best_ch_info:
                _best_ch, _best_reason, _frozen_load = self._frozen_best_ch_info
                self._best_ch_info = (_best_ch, _best_reason, _frozen_load)
                _best_freq = self._channel_to_freq(_best_ch)
                _best_ch_x = self._freq_to_x(_best_freq, freq_min, freq_max, chart_w, pad_l)
            else:
                # Find candidate channels for this band (non-overlapping preferred)
                _best_reason = ''
                if self.band == '2.4GHz':
                    _preferred = [1, 6, 11, 13]
                    _candidates = [c for c in _preferred if c not in _ch_load]
                    if _candidates:
                        _best_ch = min(_candidates, key=lambda c: abs(c - 7))
                        _best_reason = (
                            f"Non-overlapping channel with no detected networks.\n"
                            f"Preferred non-overlapping channels: 1, 6, 11, 13.\n"
                            f"Ch {_best_ch} is the quietest among them."
                        )
                    else:
                        _best_ch = min(channels, key=lambda c: _ch_load.get(c, 0))
                        _best_reason = (
                            f"All non-overlapping channels are occupied.\n"
                            f"Ch {_best_ch} has the lowest cumulative interference "
                            f"({int(_ch_load.get(_best_ch, 0))}%)."
                        )
                else:
                    _non_dfs = [36, 40, 44, 48, 149, 153, 157, 161, 165]
                    _dfs     = [52, 56, 60, 64, 100, 104, 108, 112, 116,
                                120, 124, 128, 132, 136, 140]
                    _avoid   = getattr(self, '_avoid_dfs', True)
                    if _avoid:
                        # Tier 1: empty non-DFS; Tier 2: empty DFS; Tier 3: lowest load non-DFS
                        _empty_nondfs = [c for c in _non_dfs if c not in _ch_load]
                        _empty_dfs    = [c for c in _dfs    if c not in _ch_load]
                        if _empty_nondfs:
                            _best_ch = min(_empty_nondfs,
                                           key=lambda c: sum(_ch_load.get(n, 0)
                                                             for n in _non_dfs
                                                             if abs(n - c) <= 8))
                            _nb_load = sum(_ch_load.get(n, 0) for n in _non_dfs
                                           if abs(n - _best_ch) <= 8 and n != _best_ch)
                            _best_reason = (
                                f"No networks detected on ch {_best_ch}.\n"
                                f"Non-DFS channel — no radar avoidance required.\n"
                                f"Neighbour interference score: {int(_nb_load)}%."
                            )
                        elif _empty_dfs:
                            _best_ch = min(_empty_dfs,
                                           key=lambda c: sum(_ch_load.get(n, 0)
                                                             for n in channels
                                                             if abs(n - c) <= 8))
                            _nb_load = sum(_ch_load.get(n, 0) for n in channels
                                           if abs(n - _best_ch) <= 8 and n != _best_ch)
                            _best_reason = (
                                f"No networks detected on ch {_best_ch}.\n"
                                f"DFS channel — radar avoidance may be required.\n"
                                f"All non-DFS channels are occupied.\n"
                                f"Neighbour interference score: {int(_nb_load)}%."
                            )
                        else:
                            _best_ch = min(_non_dfs, key=lambda c: _ch_load.get(c, 0))
                            _best_reason = (
                                f"All channels are occupied.\n"
                                f"Ch {_best_ch} has the lowest cumulative load "
                                f"({int(_ch_load.get(_best_ch, 0))}%) among non-DFS channels."
                            )
                    else:
                        # DFS allowed — treat all channels equally
                        _all_5g   = _non_dfs + _dfs
                        _empty_all = [c for c in _all_5g if c not in _ch_load]
                        if _empty_all:
                            _best_ch = min(_empty_all,
                                           key=lambda c: sum(_ch_load.get(n, 0)
                                                             for n in _all_5g
                                                             if abs(n - c) <= 8))
                            _nb_load = sum(_ch_load.get(n, 0) for n in _all_5g
                                           if abs(n - _best_ch) <= 8 and n != _best_ch)
                            _dfs_note = " (DFS)" if _best_ch in _dfs else ""
                            _best_reason = (
                                f"No networks detected on ch {_best_ch}{_dfs_note}.\n"
                                f"DFS avoidance disabled — all channels considered.\n"
                                f"Neighbour interference score: {int(_nb_load)}%."
                            )
                        else:
                            _best_ch = min(_all_5g, key=lambda c: _ch_load.get(c, 0))
                            _dfs_note = " (DFS)" if _best_ch in _dfs else ""
                            _best_reason = (
                                f"All channels occupied.\n"
                                f"Ch {_best_ch}{_dfs_note} has the lowest cumulative load "
                                f"({int(_ch_load.get(_best_ch, 0))}).\n"
                                f"DFS avoidance disabled."
                            )
                # Store for tooltip (mouseMoveEvent reads these)
                self._best_ch_info = (_best_ch, _best_reason, dict(_ch_load))
                _best_freq = self._channel_to_freq(_best_ch)
                _best_ch_x = self._freq_to_x(_best_freq, freq_min, freq_max, chart_w, pad_l)

        # ── Draw Best Channel background highlight ────────────────────────
        if _best_ch_x is not None:
            from PyQt6.QtGui import QRadialGradient
            _bw_px = max(20, int(20 * chart_w / (freq_max - freq_min)))
            _best_rect = QRectF(_best_ch_x - _bw_px, pad_t,
                                _bw_px * 2, chart_h)
            _bg_grad = QLinearGradient(
                QPointF(_best_ch_x - _bw_px, 0), QPointF(_best_ch_x + _bw_px, 0))
            _bg_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            _bg_grad.setColorAt(0.5, QColor(0, 230, 120, 28))
            _bg_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_bg_grad)
            painter.drawRect(_best_rect)
            # Thin green border lines on each side
            _edge_pen = QPen(QColor(0, 230, 120, 100))
            _edge_pen.setWidthF(1.0)
            _edge_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(_edge_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(int(_best_ch_x - _bw_px), pad_t,
                             int(_best_ch_x - _bw_px), pad_t + chart_h)
            painter.drawLine(int(_best_ch_x + _bw_px), pad_t,
                             int(_best_ch_x + _bw_px), pad_t + chart_h)

        # ── Pre-compute noise frame (always fresh — no timer dependency) ──
        # Two adjacent "slots" at 30 fps are blended so the animation is
        # perfectly smooth regardless of what triggered this repaint.
        if self._noise_enabled:
            import random as _rnd, time as _time
            _N    = 320
            _t    = _time.monotonic() * 30.0   # units: 1/30 s slots
            _fa   = int(_t)
            _bl   = _t - _fa                    # blend factor 0→1

            cache = getattr(self, '_noise_cache', None)
            if cache is None or cache[0] != _fa:
                def _mk(seed):
                    r = _rnd.Random(seed)
                    return [r.gauss(0, 2.2) +
                            (r.uniform(4, 18) if r.random() < 0.025 else 0.0)
                            for _ in range(_N)]
                _a, _b = _mk(_fa), _mk(_fa + 1)
                self._noise_cache = (_fa, _a, _b)
            _, _a, _b = self._noise_cache
            _noise_frame = [_a[j] * (1.0 - _bl) + _b[j] * _bl for j in range(_N)]
        else:
            _noise_frame = []

        # Draw each network as a gaussian curve
        num_points = 100
        for net in all_networks:
            ch = net.get('channel')
            bandwidth = net.get('bandwidth', 20)
            dbm = net.get('display_dbm', -90)
            bssid = net.get('bssid', '')
            ssid = net.get('ssid', '') or '<hidden>'

            # Stable HSL color derived from BSSID hash
            color = self._bssid_color(bssid, ssid)

            # Active state: hovered or selected from table
            is_hovered = (ssid == self._hovered_ssid)
            is_selected = (bssid == self._selected_bssid) if self._selected_bssid else False
            is_active = is_hovered or is_selected

            # Get center frequency
            center_freq = net.get('freq_mhz', self._channel_to_freq(ch))

            # sigma for gaussian shape; cutoff_px limits horizontal spread to
            # the actual WiFi channel footprint (±half_bandwidth × 1.3)
            sigma_mhz = bandwidth / 2.5
            mhz_to_px = chart_w / (freq_max - freq_min)
            sigma_px = sigma_mhz * mhz_to_px
            # Hard cutoff: ±65% of channel bandwidth (e.g. 40MHz → ±26MHz each side)
            cutoff_px = (bandwidth / 2) * 1.3 * mhz_to_px

            center_x = self._freq_to_x(center_freq, freq_min, freq_max, chart_w, pad_l)
            peak_y = self._dbm_to_y(dbm, chart_h, pad_t, dbm_min, dbm_max)
            base_y = self._dbm_to_y(dbm_min, chart_h, pad_t, dbm_min, dbm_max)

            # Helper: compute y for a given x_offset, with soft fade-to-floor
            # in the outer 30% of each tail to avoid hard vertical edges.
            # When noise is enabled, a per-frequency noise offset is added to
            # the dBm value — scaled by sqrt(amplitude) so the noise is
            # strongest at the peak and fades naturally toward the tails.
            _nd = _noise_frame
            _nd_len = len(_nd)
            def _curve_y(x_offset):
                amplitude = self._gaussian(x_offset, 0, sigma_px)
                y_dbm_raw = dbm + 10 * math.log10(amplitude) if amplitude > 0.001 else dbm_min
                t = abs(x_offset) / cutoff_px  # 0 at center, 1 at edge
                if t > 0.70:
                    fade = (t - 0.70) / 0.30  # 0→1 in last 30% of tail
                    y_dbm_raw = y_dbm_raw + (dbm_min - y_dbm_raw) * fade
                if _nd_len:
                    # Map absolute x to noise sample index
                    freq_frac = (center_x + x_offset - pad_l) / max(chart_w, 1)
                    n_idx = max(0, min(_nd_len - 1, int(freq_frac * _nd_len)))
                    # Weight by sqrt(amplitude): full noise at peak, fades on tails
                    y_dbm_raw += _nd[n_idx] * (amplitude ** 0.5)
                return self._dbm_to_y(y_dbm_raw, chart_h, pad_t, dbm_min, dbm_max)

            # Build filled curve path — last point naturally lands at base_y
            curve_path = QPainterPath()
            curve_path.moveTo(center_x - cutoff_px, base_y)
            for i in range(num_points + 1):
                x_offset = -cutoff_px + (2 * cutoff_px * i / num_points)
                curve_path.lineTo(center_x + x_offset, _curve_y(x_offset))
            curve_path.lineTo(center_x + cutoff_px, base_y)
            curve_path.closeSubpath()

            # Store for hover detection
            curve_key = f"{ssid}_{bssid}"
            self._ssid_curves[curve_key] = {
                'path':          curve_path,
                'center_x':      center_x,
                'center_y':      peak_y,
                'sigma_px':      sigma_px,
                'ssid':          ssid,
                'bssid':         bssid,
                'channel':       net.get('channel', '?'),
                'dbm':           net.get('dbm', '?'),
                'bandwidth':     net.get('bandwidth', '?'),
                'channel_score': net.get('channel_score', '?'),
            }

            # Gradient fill: opaque at peak, transparent at base
            grad = QLinearGradient(QPointF(center_x, peak_y), QPointF(center_x, base_y))
            fill_color_top = QColor(color)
            fill_color_bot = QColor(color)
            fill_color_top.setAlpha(90 if is_active else 45)
            fill_color_bot.setAlpha(0)
            grad.setColorAt(0.0, fill_color_top)
            grad.setColorAt(1.0, fill_color_bot)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawPath(curve_path)

            # Outline glow (brighter when active)
            glow_levels = [(6, 80), (3, 160), (1.5, 255)] if is_active else [(4, 30), (2, 90), (1, 200)]
            top_curve = QPainterPath()
            top_curve.moveTo(center_x - cutoff_px, base_y)
            for i in range(num_points + 1):
                x_offset = -cutoff_px + (2 * cutoff_px * i / num_points)
                top_curve.lineTo(center_x + x_offset, _curve_y(x_offset))
            for width, alpha in glow_levels:
                glow_color = QColor(color)
                glow_color.setAlpha(alpha)
                glow_pen = QPen(glow_color)
                glow_pen.setWidthF(width)
                painter.setPen(glow_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(top_curve)

            # ── SSID label with collision avoidance ──────────────────────
            font_size = 8 if not is_active else 9
            painter.setFont(QFont('Sans Serif', font_size, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            label_h = fm.height()
            label_w = fm.horizontalAdvance(ssid)
            label_x = int(center_x - label_w / 2)
            label_y = peak_y - 6  # start just above peak

            # Push label up until it doesn't overlap any placed label
            max_attempts = 12
            for _ in range(max_attempts):
                ly1, ly2 = label_y - label_h, label_y
                lx1, lx2 = label_x, label_x + label_w
                overlap = any(
                    lx1 < px2 and lx2 > px1 and ly1 < py2 and ly2 > py1
                    for (px1, py1, px2, py2) in placed_labels
                )
                if not overlap:
                    break
                label_y -= label_h + 2

            placed_labels.append((label_x, label_y - label_h, label_x + label_w, label_y))

            # Shadow then main text
            painter.setPen(QColor(0, 0, 0, 180))
            painter.drawText(label_x + 1, label_y + 1, ssid)
            painter.setPen(QColor(color))
            painter.drawText(label_x, label_y, ssid)
            painter.setFont(font_mono)

            # ── Peak radial glow burst ────────────────────────────────────
            if self._glow_enabled:
                from PyQt6.QtGui import QRadialGradient
                _glow_r = max(18, sigma_px * 0.55)
                _glow_color = QColor(color)
                _glow_grad = QRadialGradient(QPointF(center_x, peak_y), _glow_r)
                _alpha_center = 130 if is_active else 70
                _glow_color.setAlpha(_alpha_center)
                _glow_grad.setColorAt(0.0, _glow_color)
                _glow_color2 = QColor(color)
                _glow_color2.setAlpha(30 if is_active else 15)
                _glow_grad.setColorAt(0.45, _glow_color2)
                _glow_color3 = QColor(color)
                _glow_color3.setAlpha(0)
                _glow_grad.setColorAt(1.0, _glow_color3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_glow_grad)
                painter.drawEllipse(QPointF(center_x, peak_y), _glow_r, _glow_r * 0.6)
                painter.setFont(font_mono)

        # ── Frequency labels (X-axis) ─────────────────────────────────────
        painter.setPen(QColor('#4A6080'))
        painter.setFont(QFont('Monospace', 7))

        # Determine frequency tick interval
        if show_both_bands:
            # Show both 2.4GHz and 5GHz frequency ranges
            freq_ticks_24 = range(2400, 2500, 20)
            freq_ticks_5 = range(5150, 5900, 100)  # Less dense for 5GHz
            freq_ticks = list(freq_ticks_24) + list(freq_ticks_5)
        elif self.band == '2.4GHz':
            # Show every 20 MHz
            freq_ticks = range(2400, 2500, 20)
        else:
            # Show every 50 MHz for 5GHz
            freq_ticks = range(5150, 5900, 50)

        for freq in freq_ticks:
            if freq >= freq_min and freq <= freq_max:
                fx = self._freq_to_x(freq, freq_min, freq_max, chart_w, pad_l)
                # Draw tick mark
                painter.drawLine(fx, pad_t + chart_h, fx, pad_t + chart_h + 4)
                # Draw frequency label
                painter.drawText(fx - 20, H - pad_b + 2, 40, 14,
                                Qt.AlignmentFlag.AlignCenter, str(freq))

        # X-axis label
        painter.setPen(QColor('#4A6080'))
        painter.setFont(QFont('Sans Serif', 8))
        painter.drawText(pad_l, H - 8, chart_w, 10,
                        Qt.AlignmentFlag.AlignCenter, 'Frequency (MHz)')

        # ── Y-axis title ──────────────────────────────────────────────────
        painter.save()
        painter.translate(12, pad_t + chart_h // 2)
        painter.rotate(-90)
        painter.setPen(QColor('#4A6080'))
        painter.setFont(QFont('Sans Serif', 8))
        painter.drawText(-22, -6, 44, 14, Qt.AlignmentFlag.AlignCenter, 'dBm')
        painter.restore()

        # ── Chart title — centered at top ─────────────────────────────────
        band_label = {'2.4GHz': '2.4 GHz', '5GHz': '5 GHz'}.get(self.band, '2.4 & 5 GHz')
        chart_title = f'Spectrum Analysis  —  {band_label}'
        painter.setFont(QFont('Sans Serif', 9, QFont.Weight.Bold))
        painter.setPen(QColor('#c9d1d9'))
        painter.drawText(pad_l, 2, chart_w, 18,
                         Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                         chart_title)

        # ── Best Channel badge (drawn on top of everything) ───────────────
        if _best_ch_x is not None:
            _badge_text = (f'★ Survey: Ch {_best_ch}' if self._frozen_best_ch_info
                           else f'★ Best Ch: {_best_ch}')
            painter.setFont(QFont('Sans Serif', 8, QFont.Weight.Bold))
            _bfm = painter.fontMetrics()
            _bw = _bfm.horizontalAdvance(_badge_text) + 10
            _bh = _bfm.height() + 4
            _bx = int(_best_ch_x - _bw / 2)
            _by = pad_t + 2
            # Store badge rect for hover hit-testing
            self._best_ch_badge_rect = QRectF(_bx, _by, _bw, _bh)
            # Badge background
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 180, 90, 200))
            painter.drawRoundedRect(self._best_ch_badge_rect, 4, 4)
            # Badge text
            painter.setPen(QColor(255, 255, 255, 230))
            painter.setFont(QFont('Sans Serif', 8, QFont.Weight.Bold))
            painter.drawText(int(_bx), int(_by), int(_bw), int(_bh),
                             Qt.AlignmentFlag.AlignCenter, _badge_text)
        else:
            self._best_ch_badge_rect = None

        # ── CRT Scanlines overlay (drawn last, on top of everything) ────────
        if self._scanlines_enabled:
            _sl_spacing  = 8     # px between scanline centers
            _sl_thickness = 2    # dark stripe height in pixels
            painter.setClipRect(QRectF(pad_l, pad_t, chart_w, chart_h))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 55))
            _offset = int(self._scanlines_offset) % _sl_spacing
            _y = pad_t - _sl_spacing + _offset
            while _y < pad_t + chart_h + _sl_spacing:
                painter.drawRect(QRectF(pad_l, _y, chart_w, _sl_thickness))
                _y += _sl_spacing
            painter.setClipping(False)

        painter.end()

    def mouseMoveEvent(self, event):
        """Handle mouse movement for tooltip display"""
        from PyQt6.QtCore import QPointF
        mouse_pos = event.position()
        mx, my = mouse_pos.x(), mouse_pos.y()
        mp = QPointF(mx, my)

        # ── Best-channel badge hover ───────────────────────────────────────
        _badge = getattr(self, '_best_ch_badge_rect', None)
        if _badge and _badge.contains(mp):
            info = getattr(self, '_best_ch_info', None)
            if info:
                _ch, _reason, _load = info
                _top = sorted(_load.items(), key=lambda x: -x[1])[:5]
                _top_str = '  '.join(f'ch{c}: {int(v)}%' for c, v in _top)
                tip = (
                    f"Best Channel: {_ch}\n"
                    f"─────────────────────────\n"
                    f"{_reason}\n"
                    f"─────────────────────────\n"
                    f"Top loaded channels:\n  {_top_str}"
                )
                self.setToolTip(tip)
            return

        # ── Network curve hover ───────────────────────────────────────────
        old_hovered = self._hovered_ssid
        self._hovered_ssid = None

        for curve_info in self._ssid_curves.values():
            path = curve_info['path']
            if path.contains(mp):
                ssid   = curve_info['ssid']
                bssid  = curve_info['bssid']
                ch     = curve_info.get('channel', '?')
                dbm    = curve_info.get('dbm', '?')
                bw     = curve_info.get('bandwidth', '?')
                score  = curve_info.get('channel_score', '?')
                self._hovered_ssid = ssid
                tooltip_text = (
                    f"SSID: {ssid}\n"
                    f"BSSID: {bssid}\n"
                    f"Channel: {ch}  \u2022  {dbm} dBm  \u2022  {bw} MHz\n"
                    f"Congestion score: {score}/100"
                )
                self.setToolTip(tooltip_text)
                break

        if self._hovered_ssid is None:
            self.setToolTip("")

        if old_hovered != self._hovered_ssid:
            self.update()

    def mousePressEvent(self, event):
        """Emit carrier_clicked when user clicks on a curve."""
        from PyQt6.QtCore import QPointF
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for curve_info in self._ssid_curves.values():
                if curve_info['path'].contains(QPointF(pos.x(), pos.y())):
                    self.carrier_clicked.emit(curve_info['bssid'], curve_info['ssid'])
                    break

    def leaveEvent(self, event):
        """Handle mouse leaving the widget"""
        if self._hovered_ssid is not None:
            self._hovered_ssid = None
            self.setToolTip("")
            self.update()

    def hide_ssid(self, ssid):
        """Hide an SSID from the chart"""
        self._hidden_ssids.add(ssid)
        self.update()

    def show_ssid(self, ssid):
        """Show a hidden SSID in the chart"""
        self._hidden_ssids.discard(ssid)
        self.update()



class WifiHeatmapWidget(QWidget):
    """Scrolling waterfall heatmap — frequency (X) vs time (Y), colour = signal intensity."""

    # 256-entry RGB colormap built once at class level
    _CMAP: list = []

    @classmethod
    def _build_cmap(cls):
        if cls._CMAP:
            return
        stops = [  # (index 0-255, r, g, b)  — spectrum-analyser palette
            (0,    0,   0,  18),   # near-black navy (absolute silence)
            (25,   0,  15, 110),   # dark blue       (deep noise floor)
            (55,   0,  70, 220),   # blue            (noise floor)
            (90,   0, 180, 235),   # blue-cyan
            (125,  0, 215,  90),   # cyan-green
            (160, 140, 220,   0),  # yellow-green
            (195, 255, 130,   0),  # orange
            (228, 255,  20,   0),  # red-orange
            (255, 255, 220, 160),  # hot white-pink  (peak)
        ]

        def _lerp(a, b, t):
            return int(a + (b - a) * t)

        for i in range(256):
            lo = hi = stops[0]
            for j in range(len(stops) - 1):
                if stops[j][0] <= i <= stops[j + 1][0]:
                    lo, hi = stops[j], stops[j + 1]
                    break
            span = hi[0] - lo[0]
            t = (i - lo[0]) / span if span > 0 else 0.0
            cls._CMAP.append((_lerp(lo[1], hi[1], t),
                               _lerp(lo[2], hi[2], t),
                               _lerp(lo[3], hi[3], t)))

    # Pixel dimensions of the internal buffer
    COLS = 300
    ROWS = 90

    # Column layout for "Both" mode  (must sum to COLS)
    _B24  = 90    # 2.4 GHz slice
    _BGAP = 20    # visual gap
    _B5   = 190   # 5 GHz slice

    def __init__(self, parent=None):
        super().__init__(parent)
        import random as _rnd
        self.__class__._build_cmap()
        self._buf = [[_rnd.randint(18, 38) for _ in range(self.COLS)]
                     for _ in range(self.ROWS)]
        self._band_key = '2.4GHz'
        self.setFixedHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("Waterfall heatmap — frequência (X) × tempo (Y) — cores mais quentes = sinal mais forte")

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _ch_to_mhz(channel, band):
        """Return centre frequency in MHz for a (channel, band) pair."""
        try:
            ch = int(channel)
        except (TypeError, ValueError):
            return None
        if '2.4' in str(band):
            return 2484 if ch == 14 else 2407 + 5 * ch
        return 5000 + 5 * ch  # 5 GHz

    def _mhz_to_col(self, freq):
        """Map a frequency (MHz) to a pixel column 0‥COLS-1.
        Frequency ranges match WifiChannelChart exactly for axis alignment."""
        bk = self._band_key
        if bk == '2.4GHz':
            # Chart uses 2400–2500 MHz
            return max(0, min(self.COLS - 1,
                              int((freq - 2400) / 100 * self.COLS)))
        if bk == '5GHz':
            # Chart uses 5150–5850 MHz
            return max(0, min(self.COLS - 1,
                              int((freq - 5150) / 700 * self.COLS)))
        # Both: chart uses continuous 2400–5900 MHz range
        return max(0, min(self.COLS - 1,
                          int((freq - 2400) / 3500 * self.COLS)))

    def _band_ok(self, net_band):
        bk = self._band_key
        nb = str(net_band)
        if bk == 'Both':
            return True
        return (bk == '2.4GHz' and '2.4' in nb) or (bk == '5GHz' and '5' in nb and '2.4' not in nb)

    # ── Public API ────────────────────────────────────────────────────

    def set_band(self, band_key):
        """Update the active band; clear buffer only when the band actually changes."""
        if band_key == self._band_key:
            return
        import random as _rnd
        self._band_key = band_key
        self._buf = [[_rnd.randint(18, 38) for _ in range(self.COLS)]
                     for _ in range(self.ROWS)]
        self.update()

    def push_networks(self, networks, band_key):
        """Ingest one scan snapshot and scroll the waterfall down by one row."""
        import random as _rnd
        self._band_key = band_key
        # Initialise each column at noise-floor level; signals are painted on top
        new_row = [_rnd.randint(18, 38) for _ in range(self.COLS)]

        for net in networks:
            if not self._band_ok(net.get('band', '2.4GHz')):
                continue
            center = self._ch_to_mhz(net.get('channel'), net.get('band', '2.4GHz'))
            if center is None:
                continue
            try:
                bw_half = int(str(net.get('bandwidth', '20')).replace('MHz', '')) / 2
            except (ValueError, TypeError):
                bw_half = 10
            intensity = min(255, int(net.get('signal_pct', 0) * 2.55))
            c0 = self._mhz_to_col(center - bw_half)
            c1 = self._mhz_to_col(center + bw_half)
            for c in range(max(0, c0), min(self.COLS, c1 + 1)):
                new_row[c] = max(new_row[c], intensity)

        # Scroll: drop oldest (last) row, prepend newest at index 0 (top)
        self._buf.pop()
        self._buf.insert(0, new_row)
        self.update()

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        W, H = self.width(), self.height()
        ML = 44   # left margin — matches WifiChannelChart pad_l for aligned frequency axis
        MR = 16   # right margin — matches WifiChannelChart pad_r
        MB = 16   # bottom margin for frequency labels
        cw = max(1, W - ML - MR)
        ch = max(1, H - MB - 2)

        # Fill entire widget with dark background (same as chart container #0D1117)
        painter.fillRect(self.rect(), QColor(13, 17, 23))

        # ── Build QImage from buffer ───────────────────────────────────
        stride = self.COLS * 3
        raw = bytearray(self.ROWS * stride)
        cmap = self._CMAP
        buf  = self._buf
        for r in range(self.ROWS):
            base = r * stride
            row  = buf[r]
            for c in range(self.COLS):
                rv, gv, bv = cmap[row[c]]
                off = base + c * 3
                raw[off]     = rv
                raw[off + 1] = gv
                raw[off + 2] = bv

        img = QImage(bytes(raw), self.COLS, self.ROWS, stride, QImage.Format.Format_RGB888)
        painter.drawImage(QRect(ML, 2, cw, ch), img)

        # ── Dashed frequency grid + labels ────────────────────────────
        bk = self._band_key
        if bk == '2.4GHz':
            ticks = [(2412,'1'),(2422,'2'),(2432,'5'),(2437,'6'),
                     (2452,'9'),(2462,'11'),(2472,'13')]
        elif bk == '5GHz':
            ticks = [(5180,'36'),(5220,'44'),(5260,'52'),(5300,'60'),
                     (5500,'100'),(5580,'116'),(5660,'132'),(5745,'149'),(5825,'165')]
        else:
            ticks = [(2412,'1'),(2437,'6'),(2462,'11'),
                     (5180,'36'),(5500,'100'),(5745,'149')]

        painter.setFont(QFont('Monospace', 6))
        for freq, lbl in ticks:
            col = self._mhz_to_col(freq)
            x   = ML + int(col * cw / self.COLS)
            painter.setPen(QPen(QColor('#334466'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(x, 2, x, 2 + ch)
            painter.setPen(QColor('#6688aa'))
            painter.drawText(x - 10, 2 + ch + 1, 24, 13,
                             Qt.AlignmentFlag.AlignHCenter, f'ch{lbl}')

        # ── "Both" band labels ─────────────────────────────────────────
        if bk == 'Both':
            # 2500 MHz marks the boundary between 2.4 GHz and 5 GHz regions
            split_col = self._mhz_to_col(2500)
            split_x = ML + int(split_col * cw / self.COLS)
            painter.setPen(QPen(QColor('#334466'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(split_x, 2, split_x, 2 + ch)
            painter.setFont(QFont('Sans Serif', 6, QFont.Weight.Bold))
            painter.setPen(QColor('#556688'))
            painter.drawText(ML + 3, 4, 50, 11, Qt.AlignmentFlag.AlignLeft, '2.4 GHz')
            painter.drawText(split_x + 3, 4, 50, 11, Qt.AlignmentFlag.AlignLeft, '5 GHz')

        # ── Border ─────────────────────────────────────────────────────
        painter.setPen(QPen(QColor('#2A3040'), 1))
        painter.drawRect(QRect(ML, 2, cw, ch))

        painter.end()



class RouteVisualizationWidget(QWidget):
    """Custom widget for visualizing traceroute hops as glowing neon bars on a dark background."""

    # Latency → (bar color, glow color)
    _PALETTE = [
        (20,  "#00E676", "#00FF88"),   # fast   – neon green
        (50,  "#FFEA00", "#FFD740"),   # ok     – neon yellow
        (100, "#FF6D00", "#FF9100"),   # slow   – neon orange
        (float("inf"), "#FF1744", "#FF6E40"),  # bad – neon red
    ]
    _TIMEOUT_COLOR = ("#546E7A", "#607D8B")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hops = []
        self._hovered_row = None
        self.setMinimumHeight(220)
        self.setMaximumHeight(320)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

    # ── helpers ─────────────────────────────────────────────────────────────
    def _colors(self, latency, ip):
        if latency == 0 or ip == "*":
            return self._TIMEOUT_COLOR
        for threshold, bar, glow in [(t, b, g) for t, b, g in self._PALETTE]:
            if latency < threshold:
                return bar, glow
        return self._PALETTE[-1][1], self._PALETTE[-1][2]

    def add_hop(self, hop_num, ip, hostname, latency):
        self.hops.append((hop_num, ip, hostname, latency))
        self.update()

    def clear(self):
        self.hops = []
        self._hovered_row = None
        self.update()

    # ── mouse ────────────────────────────────────────────────────────────────
    def _row_rect(self, index, bar_h, spacing, y0):
        y = y0 + index * (bar_h + spacing)
        return y, y + bar_h

    def mouseMoveEvent(self, event):
        if not self.hops:
            return
        PAD_L, PAD_T = 14, 14
        num_hops = len(self.hops)
        avail_h = self.height() - PAD_T * 2
        bar_h = max(18, min(32, (avail_h - (num_hops - 1) * 6) // max(num_hops, 1)))
        spacing = 6
        my = event.position().y()
        old = self._hovered_row
        self._hovered_row = None
        for i in range(num_hops):
            y_top, y_bot = self._row_rect(i, bar_h, spacing, PAD_T)
            if y_top <= my <= y_bot:
                self._hovered_row = i
                break
        if self._hovered_row != old:
            self.update()

    def leaveEvent(self, _event):
        if self._hovered_row is not None:
            self._hovered_row = None
            self.update()

    # ── paint ────────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W, H = self.width(), self.height()

        # ── background: dark gradient ────────────────────────────────────────
        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0.0, QColor("#1A1F2E"))
        bg.setColorAt(1.0, QColor("#0D1117"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, W, H, 12, 12)

        # subtle border
        border_pen = QPen(QColor("#2A3040"))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, W - 1, H - 1, 12, 12)

        if not self.hops:
            # Placeholder
            painter.setPen(QColor("#3A4460"))
            painter.setFont(QFont("Sans Serif", 10))
            painter.drawText(0, 0, W, H, Qt.AlignmentFlag.AlignCenter,
                             "Run traceroute to see the route visualization")
            painter.end()
            return

        PAD_L   = 14
        PAD_R   = 14
        PAD_T   = 14
        num_hops = len(self.hops)
        avail_h = H - PAD_T * 2
        bar_h   = max(18, min(32, (avail_h - (num_hops - 1) * 6) // max(num_hops, 1)))
        spacing = 6

        # label column widths
        HOP_COL  = 32   # circle badge
        BAR_L    = PAD_L + HOP_COL + 8
        BAR_AVAIL = W - BAR_L - PAD_R - 180  # reserve right side for text

        # max latency for scaling
        max_lat = max((h[3] for h in self.hops if h[3] > 0 and h[1] != "*"), default=100)
        max_lat = max(max_lat, 1)

        for i, (hop_num, ip, hostname, latency) in enumerate(self.hops):
            y = PAD_T + i * (bar_h + spacing)
            is_hovered = (self._hovered_row == i)
            bar_col, glow_col = self._colors(latency, ip)
            is_timeout = (latency == 0 or ip == "*")

            # ── hop circle ───────────────────────────────────────────────────
            cx = PAD_L + HOP_COL // 2
            cy = int(y + bar_h / 2)
            r  = bar_h // 2 - 1
            circle_grad = QRadialGradient(cx - r//3, cy - r//3, r * 2)
            circle_grad.setColorAt(0.0, QColor(bar_col).lighter(130))
            circle_grad.setColorAt(1.0, QColor(bar_col).darker(160))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(circle_grad)
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            # hop number text
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Sans Serif", 7, QFont.Weight.Bold))
            painter.drawText(cx - r, cy - r, r * 2, r * 2,
                             Qt.AlignmentFlag.AlignCenter, str(hop_num))

            # ── bar ──────────────────────────────────────────────────────────
            if is_timeout:
                bar_w = max(40, BAR_AVAIL // 8)
            else:
                bar_w = max(40, int((latency / max_lat) * BAR_AVAIL))

            bar_x = BAR_L
            bar_y = int(y + (bar_h - max(bar_h - 6, 8)) / 2)
            bar_rh = max(bar_h - 6, 8)
            bar_radius = bar_rh // 2

            # glow shadow layers (only when not timeout)
            if not is_timeout:
                for glow_r, alpha in [(6, 18), (4, 30), (2, 55)]:
                    glow_c = QColor(glow_col)
                    glow_c.setAlpha(alpha)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(glow_c)
                    painter.drawRoundedRect(
                        bar_x - glow_r, bar_y - glow_r,
                        bar_w + glow_r * 2, bar_rh + glow_r * 2,
                        bar_radius + glow_r, bar_radius + glow_r
                    )

            # bar gradient fill
            bar_grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
            if is_timeout:
                bar_grad.setColorAt(0.0, QColor("#374151"))
                bar_grad.setColorAt(1.0, QColor("#1F2937"))
            else:
                c1 = QColor(glow_col)
                c1.setAlpha(230)
                c2 = QColor(bar_col)
                c2.setAlpha(180)
                bar_grad.setColorAt(0.0, c1)
                bar_grad.setColorAt(1.0, c2)

            # hovered: brighten slightly
            if is_hovered and not is_timeout:
                bar_grad.setColorAt(0.0, QColor(glow_col).lighter(115))
                bar_grad.setColorAt(1.0, QColor(bar_col).lighter(115))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bar_grad)
            painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_rh, bar_radius, bar_radius)

            # highlight stripe (top edge)
            if not is_timeout:
                hi = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
                hi.setColorAt(0.0, QColor(255, 255, 255, 55))
                hi.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.setBrush(hi)
                painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_rh // 2, bar_radius, bar_radius)

            # ── text label ───────────────────────────────────────────────────
            text_x = bar_x + bar_w + 10
            text_w = W - text_x - PAD_R

            if is_timeout:
                label_main = "* * *  (no response)"
                painter.setPen(QColor("#546E7A"))
                painter.setFont(QFont("Sans Serif", 8))
            else:
                display = hostname if hostname and hostname != ip else ip
                if len(display) > 28:
                    display = display[:25] + "…"
                lat_str = f"{latency:.1f} ms"
                label_main = f"{display}"
                # draw latency badge
                badge_col = QColor(bar_col)
                badge_col.setAlpha(30)
                lat_font = QFont("Monospace", 8, QFont.Weight.Bold)
                painter.setFont(lat_font)
                lat_w = painter.fontMetrics().horizontalAdvance(lat_str) + 14
                lat_x = W - PAD_R - lat_w
                lat_y = int(y + (bar_h - 18) / 2)
                # badge background
                badge_bg = QColor(bar_col)
                badge_bg.setAlpha(35)
                painter.setBrush(badge_bg)
                _border_c = QColor(bar_col)
                _border_c.setAlpha(120)
                badge_border = QPen(_border_c)
                painter.setPen(badge_border)
                painter.drawRoundedRect(lat_x, lat_y, lat_w, 18, 9, 9)
                painter.setPen(QColor(glow_col))
                painter.drawText(lat_x, lat_y, lat_w, 18,
                                 Qt.AlignmentFlag.AlignCenter, lat_str)

                painter.setPen(QColor("#C9D1E0") if not is_hovered else QColor("#FFFFFF"))
                painter.setFont(QFont("Sans Serif", 8, QFont.Weight.Bold if is_hovered else QFont.Weight.Normal))

            painter.drawText(text_x, int(y), min(text_w, W - text_x - 80), bar_h,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             label_main)

        painter.end()



class LatencyGraphWidget(QWidget):
    """Widget that draws traceroute hop latencies as a smooth neon line chart on dark background."""

    _THRESHOLDS = [(20, "#00E676", "#00FF88"),
                   (50, "#FFEA00", "#FFD740"),
                   (100, "#FF6D00", "#FF9100"),
                   (float("inf"), "#FF1744", "#FF6E40")]

    def __init__(self, hops, local_info=None, hop_stats=None, parent=None):
        super().__init__(parent)
        self.hops = hops
        self.local_info = local_info  # (hostname, ip) tuple or None
        self.hop_stats = hop_stats or {}  # {hop_num: (loss_pct, stdev)}
        self.setMinimumSize(420, 300)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        self._hovered = None
        self._zoom_stdev = False
        self._zoom_btn = QPushButton(self)
        self._zoom_btn.setFixedSize(30, 30)
        self._zoom_btn.setCheckable(True)
        self._zoom_btn.setToolTip("Expandir eixo Y para incluir desvio padrão")
        self._zoom_btn.setStyleSheet(
            "QPushButton{background:rgba(26,31,46,180);border:1px solid #2A3A50;"
            "border-radius:6px;}"
            "QPushButton:hover{background:rgba(38,50,80,200);border-color:#546E7A;}"
            "QPushButton:checked{background:rgba(38,80,80,200);border-color:#80CBC4;}"
        )
        _sd_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "assets", "icons", "stdev_zoom.svg")
        _sd_icon = load_svg_icon(_sd_icon_path, 18)
        if _sd_icon:
            self._zoom_btn.setIcon(_sd_icon)
            self._zoom_btn.setIconSize(QSize(18, 18))
        else:
            self._zoom_btn.setText("±σ")
        self._zoom_btn.clicked.connect(
            lambda checked: (setattr(self, "_zoom_stdev", checked), self.update())
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._zoom_btn.move(self.width() - 20 - self._zoom_btn.width() - 4, 8)

    def _color(self, lat):
        for threshold, bar, glow in self._THRESHOLDS:
            if lat < threshold:
                return QColor(bar), QColor(glow)
        return QColor(self._THRESHOLDS[-1][1]), QColor(self._THRESHOLDS[-1][2])

    def mouseMoveEvent(self, event):
        L, R, T, B = 72, 20, 32, 58
        W = self.width() - L - R
        H = self.height() - T - B
        valid = [(hn, lat) for hn, ip, _, lat in self.hops if lat > 0 and ip != "*"]
        max_hop = max((hn for hn, _, _, _ in self.hops), default=1)
        all_lats = [lat for _, lat in valid]
        max_lat = max(all_lats, default=100) * 1.18
        max_lat = max(max_lat, 10)
        px = lambda hn: L + hn / max(max_hop, 1) * W
        py = lambda lat: T + H - (lat / max_lat) * H
        pos = event.position()
        closest, closest_dist = None, float("inf")
        for i, (hn, lat) in enumerate(valid):
            dx = pos.x() - px(hn)
            dy = pos.y() - py(lat)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < closest_dist:
                closest_dist, closest = dist, i
        new_hovered = closest if closest_dist < 30 else None
        if new_hovered != self._hovered:
            self._hovered = new_hovered
            self.update()

    def leaveEvent(self, _event):
        if self._hovered is not None:
            self._hovered = None
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W_total, H_total = self.width(), self.height()

        # ── dark background ──────────────────────────────────────────────────
        bg = QLinearGradient(0, 0, 0, H_total)
        bg.setColorAt(0.0, QColor("#1A1F2E"))
        bg.setColorAt(1.0, QColor("#0D1117"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, W_total, H_total, 12, 12)

        border_pen = QPen(QColor("#2A3040"))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, W_total - 1, H_total - 1, 12, 12)

        L, R, T, B = 72, 20, 32, 58
        W = W_total - L - R
        H = H_total - T - B

        valid = [(hn, ip, hostname, lat) for hn, ip, hostname, lat in self.hops
                 if lat > 0 and ip != "*"]
        all_lats = [lat for _, _, _, lat in valid]
        total_lat = sum(all_lats)
        max_hop = max((hn for hn, _, _, _ in self.hops), default=1)
        max_lat = max(all_lats, default=100) * 1.18
        if self._zoom_stdev and self.hop_stats:
            for hn, _, _, lat in valid:
                if hn in self.hop_stats:
                    _, sd = self.hop_stats[hn]
                    if sd > 0:
                        max_lat = max(max_lat, (lat + sd) * 1.18)
        max_lat = max(max_lat, 10)

        def px(hn):
            return L + hn / max(max_hop, 1) * W

        def py(lat):
            return T + H - (lat / max_lat) * H

        # ── grid lines ───────────────────────────────────────────────────────
        grid_steps = 5
        for i in range(grid_steps + 1):
            frac = i / grid_steps
            y_g = T + H - frac * H
            val = frac * max_lat
            grid_pen = QPen(QColor("#1E2A3A"))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            painter.drawLine(L, int(y_g), L + W, int(y_g))
            painter.setPen(QColor("#3A4460"))
            painter.setFont(QFont("Monospace", 7))
            painter.drawText(0, int(y_g) - 8, L - 8, 16,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{val:.0f}")

        # ── axes ─────────────────────────────────────────────────────────────
        axis_pen = QPen(QColor("#2A3A50"))
        axis_pen.setWidth(1)
        painter.setPen(axis_pen)
        painter.drawLine(L, T, L, T + H)
        painter.drawLine(L, T + H, L + W, T + H)

        # ── Y label ──────────────────────────────────────────────────────────
        painter.save()
        painter.setPen(QColor("#4A6080"))
        painter.setFont(QFont("Sans Serif", 8))
        painter.translate(12, T + H // 2)
        painter.rotate(-90)
        painter.drawText(-50, -8, 100, 16, Qt.AlignmentFlag.AlignCenter, "Latency (ms)")
        painter.restore()

        # ── X axis labels ────────────────────────────────────────────────────
        painter.setPen(QColor("#4A6080"))
        painter.setFont(QFont("Monospace", 7))
        # Origin "0"
        painter.drawText(L - 8, T + H + 4, 16, 14, Qt.AlignmentFlag.AlignCenter, "0")
        for hop_num, ip, _, _ in self.hops:
            x_g = px(hop_num)
            painter.drawText(int(x_g) - 15, T + H + 4, 30, 14,
                             Qt.AlignmentFlag.AlignCenter, str(hop_num))
        painter.setPen(QColor("#3A4460"))
        painter.setFont(QFont("Sans Serif", 8))
        painter.drawText(L, T + H + 20, W, 14, Qt.AlignmentFlag.AlignCenter, "Hop")

        # ── Local Network Latency region (between 0 and hop 1) ────────────────
        if self.hops:
            x_hop1 = px(1)
            region_w = int(x_hop1 - L)
            if region_w > 8:
                # subtle shaded band
                region_fill = QLinearGradient(L, T, L + region_w, T)
                local_c = QColor("#00BCD4")
                local_c.setAlpha(14)
                region_fill.setColorAt(0.0, local_c)
                local_c2 = QColor("#00BCD4")
                local_c2.setAlpha(0)
                region_fill.setColorAt(1.0, local_c2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(region_fill)
                painter.drawRect(L, T, region_w, H)

                # ── growing latency curve from (0, 0ms) to hop 1 ──────────────
                # painter.save() here ensures the cyan pen does NOT leak into the rest
                painter.save()
                first_hop = next(
                    ((hn, ip, hostname, lat) for hn, ip, hostname, lat in self.hops
                     if lat > 0 and ip != "*"), None
                )
                if first_hop:
                    _, _, _, lat1 = first_hop
                    x0_curve, y0_curve = L, T + H
                    x1_curve, y1_curve = x_hop1, py(lat1)
                    ctrl_x = (x0_curve + x1_curve) / 2
                    curve_path = QPainterPath()
                    curve_path.moveTo(x0_curve, y0_curve)
                    curve_path.cubicTo(ctrl_x, y0_curve, ctrl_x, y1_curve, x1_curve, y1_curve)
                    fill_path = QPainterPath(curve_path)
                    fill_path.lineTo(x1_curve, T + H)
                    fill_path.lineTo(x0_curve, T + H)
                    fill_path.closeSubpath()
                    fill_grad = QLinearGradient(0, min(y0_curve, y1_curve), 0, T + H)
                    fill_top = QColor("#00BCD4"); fill_top.setAlpha(55)
                    fill_bot = QColor("#00BCD4"); fill_bot.setAlpha(0)
                    fill_grad.setColorAt(0.0, fill_top)
                    fill_grad.setColorAt(1.0, fill_bot)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.fillPath(fill_path, fill_grad)
                    for pass_w, pass_alpha in [(5, 30), (3, 70), (2, 180)]:
                        glow_c = QColor("#00E5FF"); glow_c.setAlpha(pass_alpha)
                        gp = QPen(glow_c); gp.setWidth(pass_w)
                        gp.setCapStyle(Qt.PenCapStyle.RoundCap)
                        gp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                        painter.setPen(gp)
                        painter.drawPath(curve_path)
                painter.restore()  # reset pen/brush before the rest of the graph

                # dashed vertical at hop 1 position
                dash_pen = QPen(QColor("#00BCD4"))
                dash_pen.setStyle(Qt.PenStyle.DashLine)
                dash_pen.setWidth(1)
                dash_pen.setDashPattern([3, 4])
                painter.setPen(dash_pen)
                painter.drawLine(int(x_hop1), T, int(x_hop1), T + H)

                # label rotated vertically in the band
                mid_x = L + region_w // 2
                painter.save()
                painter.translate(mid_x, T + H // 2)
                painter.rotate(-90)
                label_color = QColor("#00E5FF")
                label_color.setAlpha(200)
                painter.setPen(label_color)
                painter.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
                band_text_w = min(H - 4, 160)
                painter.drawText(-band_text_w // 2, -9, band_text_w, 18,
                                 Qt.AlignmentFlag.AlignCenter, "Local Network Latency")
                painter.restore()

        # ── Origin point: local machine (hop 0) ─────────────────────────────
        painter.save()  # isolate brush/pen — prevents leaking into the green curve
        origin_x, origin_y = L, T + H
        origin_color = QColor("#00E5FF")
        # glow rings
        for gr, ga in [(14, 15), (9, 35), (6, 80)]:
            gc = QColor(origin_color); gc.setAlpha(ga)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gc)
            painter.drawEllipse(origin_x - gr, origin_y - gr, gr * 2, gr * 2)
        # solid point
        pt_g = QRadialGradient(origin_x - 1, origin_y - 1, 10)
        pt_g.setColorAt(0.0, QColor("#80FFFF"))
        pt_g.setColorAt(1.0, QColor("#00BCD4"))
        painter.setBrush(pt_g)
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawEllipse(origin_x - 5, origin_y - 5, 10, 10)
        # local hostname + IP labels above the origin point
        if self.local_info:
            local_host, local_ip = self.local_info
            if len(local_host) > 20:
                local_host = local_host[:18] + "\u2026"
            painter.setPen(QColor("#E8F0FF"))
            painter.setFont(QFont("Sans Serif", 8, QFont.Weight.Bold))
            painter.drawText(origin_x - 60, origin_y - 50, 120, 14,
                             Qt.AlignmentFlag.AlignCenter, local_host)
            painter.setPen(QColor("#00E5FF"))
            painter.setFont(QFont("Monospace", 7))
            painter.drawText(origin_x - 60, origin_y - 36, 120, 13,
                             Qt.AlignmentFlag.AlignCenter, local_ip)
        painter.restore()  # restore brush/pen state so the green curve is unaffected

        # ── timeout markers ──────────────────────────────────────────────────
        for hop_num, ip, _, lat in self.hops:
            if lat <= 0 or ip == "*":
                x_g = px(hop_num)
                dash_pen = QPen(QColor("#2A3A50"))
                dash_pen.setStyle(Qt.PenStyle.DashLine)
                dash_pen.setWidth(1)
                painter.setPen(dash_pen)
                painter.drawLine(int(x_g), T, int(x_g), T + H)
                painter.setPen(QColor("#3A4460"))
                painter.setFont(QFont("Sans Serif", 8))
                painter.drawText(int(x_g) - 10, T + H + 4, 20, 14,
                                 Qt.AlignmentFlag.AlignCenter, "✕")

        # ── gradient fill + neon curve ───────────────────────────────────────
        if len(valid) >= 2:
            points = [(px(hn), py(lat), lat) for hn, ip, hostname, lat in valid]

            # glow fill under each segment
            for i in range(1, len(points)):
                x0, y0, lat0 = points[i - 1]
                x1, y1, lat1 = points[i]
                cx_m = (x0 + x1) / 2
                seg_fill = QPainterPath()
                seg_fill.moveTo(x0, T + H)
                seg_fill.lineTo(x0, y0)
                seg_fill.cubicTo(cx_m, y0, cx_m, y1, x1, y1)
                seg_fill.lineTo(x1, T + H)
                seg_fill.closeSubpath()
                _, glow_c = self._color(lat1)
                gradient = QLinearGradient(0, min(y0, y1), 0, T + H)
                top_c = QColor(glow_c)
                top_c.setAlpha(70)
                bot_c = QColor(glow_c)
                bot_c.setAlpha(0)
                gradient.setColorAt(0.0, top_c)
                gradient.setColorAt(1.0, bot_c)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.fillPath(seg_fill, gradient)

            # neon glow curve (multiple passes for glow)
            for pass_w, pass_alpha in [(5, 40), (3, 80), (2, 200)]:
                for i in range(1, len(points)):
                    x0, y0, lat0 = points[i - 1]
                    x1, y1, lat1 = points[i]
                    cx_m = (x0 + x1) / 2
                    seg_curve = QPainterPath()
                    seg_curve.moveTo(x0, y0)
                    seg_curve.cubicTo(cx_m, y0, cx_m, y1, x1, y1)
                    _, glow_c = self._color(lat1)
                    _gc = QColor(glow_c)
                    _gc.setAlpha(pass_alpha)
                    pen = QPen(_gc)
                    pen.setWidth(pass_w)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.drawPath(seg_curve)

        elif len(valid) == 1:
            hn0, ip0, _name0, lat0 = valid[0]
            x_g, y_g = px(hn0), py(lat0)
            bar_c, glow_c = self._color(lat0)
            for pass_w, pass_alpha in [(4, 50), (2, 180)]:
                _pc = QColor(glow_c)
                _pc.setAlpha(pass_alpha)
                p_pen = QPen(_pc)
                p_pen.setWidth(pass_w)
                painter.setPen(p_pen)
                painter.drawLine(L, int(y_g), L + W, int(y_g))

        # ── points + labels ──────────────────────────────────────────────────
        for i, (hop_num, ip, hostname, lat) in enumerate(valid):
            x_g, y_g = px(hop_num), py(lat)
            is_hovered = (self._hovered == i)
            bar_c, glow_c = self._color(lat)

            # point glow — stronger on hover
            if is_hovered:
                glow_passes = [(22, 18), (16, 35), (11, 70), (7, 130)]
            else:
                glow_passes = [(10, 20), (6, 50)]
            for glow_r, glow_a in glow_passes:
                g_c = QColor(glow_c)
                g_c.setAlpha(glow_a)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(g_c)
                painter.drawEllipse(int(x_g) - glow_r, int(y_g) - glow_r,
                                    glow_r * 2, glow_r * 2)

            # point circle — bigger on hover
            r = 10 if is_hovered else 5
            pt_grad = QRadialGradient(x_g - r // 3, y_g - r // 3, r * 2)
            pt_grad.setColorAt(0.0, QColor(glow_c).lighter(150 if is_hovered else 120))
            pt_grad.setColorAt(1.0, QColor(bar_c))
            painter.setBrush(pt_grad)
            painter.setPen(QPen(QColor("#FFFFFF"), 2 if is_hovered else 0))
            painter.drawEllipse(int(x_g) - r, int(y_g) - r, r * 2, r * 2)

            # ── stdev range markers (subtle dots above/below mean) ───────────
            if hop_num in self.hop_stats:
                _, sd = self.hop_stats[hop_num]
                if sd > 0:
                    y_up = py(lat + sd)
                    y_dn = py(max(lat - sd, 0.1))
                    painter.save()
                    sd_col = QColor("#80CBC4")
                    sd_col.setAlpha(120)
                    sd_pen = QPen(sd_col)
                    sd_pen.setWidth(1)
                    painter.setPen(sd_pen)
                    painter.drawLine(int(x_g), int(y_up), int(x_g), int(y_dn))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(sd_col)
                    r_sd = 3
                    painter.drawEllipse(int(x_g) - r_sd, int(y_up) - r_sd, r_sd * 2, r_sd * 2)
                    painter.drawEllipse(int(x_g) - r_sd, int(y_dn) - r_sd, r_sd * 2, r_sd * 2)
                    painter.restore()

            # hostname (above point) — larger and brighter on hover
            display = hostname if hostname and hostname != ip else ip
            if is_hovered:
                max_chars = 28
                font_size = 9
            else:
                max_chars = 18
                font_size = 6
            if len(display) > max_chars:
                display = display[:max_chars - 2] + "…"
            text_color = QColor("#E8F0FF") if is_hovered else QColor("#8899BB")
            painter.setPen(text_color)
            painter.setFont(QFont("Sans Serif", font_size,
                                  QFont.Weight.Bold if is_hovered else QFont.Weight.Normal))
            label_w = 120 if is_hovered else 84
            label_offset_y = 58 if is_hovered else 46
            painter.drawText(int(x_g) - label_w // 2, int(y_g) - label_offset_y,
                             label_w, 14, Qt.AlignmentFlag.AlignCenter, display)

            # latency badge — larger on hover
            lat_str = f"{lat:.1f}ms"
            badge_font_size = 10 if is_hovered else 7
            badge_font = QFont("Monospace", badge_font_size, QFont.Weight.Bold)
            painter.setFont(badge_font)
            bw = painter.fontMetrics().horizontalAdvance(lat_str) + (16 if is_hovered else 10)
            bh = 20 if is_hovered else 16
            bx = int(x_g) - bw // 2
            by = int(y_g) - (28 if is_hovered else 22)
            badge_bg = QColor(bar_c)
            badge_bg.setAlpha(80 if is_hovered else 45)
            painter.setBrush(badge_bg)
            _bb_c = QColor(bar_c)
            _bb_c.setAlpha(200 if is_hovered else 140)
            badge_border_pen = QPen(_bb_c, 2 if is_hovered else 1)
            painter.setPen(badge_border_pen)
            painter.drawRoundedRect(bx, by, bw, bh, bh // 2, bh // 2)
            painter.setPen(QColor(glow_c))
            painter.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, lat_str)

            # stdev / loss badges when hovered
            if is_hovered and hop_num in self.hop_stats:
                loss_pct, sd = self.hop_stats[hop_num]
                painter.setFont(QFont("Monospace", 8))
                # stdev badge (below latency badge)
                if sd > 0:
                    sd_str = f"σ {sd:.1f}ms"
                    sd_w = painter.fontMetrics().horizontalAdvance(sd_str) + 12
                    sd_x = int(x_g) - sd_w // 2
                    sd_y = by + bh + 3
                    sd_bg = QColor("#263238"); sd_bg.setAlpha(180)
                    painter.setBrush(sd_bg)
                    painter.setPen(QPen(QColor("#546E7A"), 1))
                    painter.drawRoundedRect(sd_x, sd_y, sd_w, 16, 8, 8)
                    painter.setPen(QColor("#80CBC4"))
                    painter.drawText(sd_x, sd_y, sd_w, 16, Qt.AlignmentFlag.AlignCenter, sd_str)
                # loss badge
                if loss_pct > 0:
                    loss_str = f"⚠ {loss_pct:.1f}%"
                    lw = painter.fontMetrics().horizontalAdvance(loss_str) + 12
                    lx = int(x_g) - lw // 2
                    ly = by + bh + (22 if sd > 0 else 3)
                    loss_bg = QColor("#B71C1C"); loss_bg.setAlpha(160)
                    painter.setBrush(loss_bg)
                    painter.setPen(QPen(QColor("#EF9A9A"), 1))
                    painter.drawRoundedRect(lx, ly, lw, 16, 8, 8)
                    painter.setPen(QColor("#FFCDD2"))
                    painter.drawText(lx, ly, lw, 16, Qt.AlignmentFlag.AlignCenter, loss_str)

        # ── footer ───────────────────────────────────────────────────────────
        painter.setPen(QColor("#4A6080"))
        painter.setFont(QFont("Sans Serif", 8))
        reached = len(valid)
        total_hops = len(self.hops)
        last_lat = valid[-1][3] if valid else 0.0
        footer_parts = [
            f"Avg to destination: {last_lat:.1f} ms",
            f"{reached}/{total_hops} hops reached",
        ]
        if self.hop_stats:
            sd_vals = [sd for (_, sd) in self.hop_stats.values() if sd > 0]
            loss_vals = [lp for (lp, _) in self.hop_stats.values() if lp > 0]
            if sd_vals:
                footer_parts.append(f"σ avg: {sum(sd_vals)/len(sd_vals):.1f} ms")
            if loss_vals:
                footer_parts.append(f"loss: {max(loss_vals):.1f}% (max)")
        footer = "  ·  ".join(footer_parts)
        painter.drawText(L, T + H + 38, W, 14,
                         Qt.AlignmentFlag.AlignRight, footer)

        painter.end()



class PingGraphWidget(QWidget):
    """Neon line chart showing ping RTT (Y) vs packet number (X) on dark background."""

    _THRESHOLDS = [(20, "#00E676", "#00FF88"),
                   (50, "#FFEA00", "#FFD740"),
                   (100, "#FF6D00", "#FF9100"),
                   (float("inf"), "#FF1744", "#FF6E40")]

    def __init__(self, results, parent=None):
        super().__init__(parent)
        # results: [(seq, success, rtt_ms), ...]
        self.results = results
        self.setMinimumSize(420, 280)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        self._hovered = None

    def _color(self, lat):
        for threshold, bar, glow in self._THRESHOLDS:
            if lat < threshold:
                return QColor(bar), QColor(glow)
        return QColor(self._THRESHOLDS[-1][1]), QColor(self._THRESHOLDS[-1][2])

    def _valid(self):
        return [(seq, rtt) for seq, success, rtt in self.results if success]

    def mouseMoveEvent(self, event):
        L, T, B = 72, 32, 58
        W = self.width() - L - 20
        H = self.height() - T - B
        valid = self._valid()
        if not valid:
            return
        max_seq = max(seq for seq, success, _ in self.results)
        max_rtt = max(rtt for _, rtt in valid) * 1.18
        max_rtt = max(max_rtt, 10)
        px = lambda s: L + (s / max(max_seq, 1)) * W
        py = lambda r: T + H - (r / max_rtt) * H
        pos = event.position()
        closest, closest_dist = None, float("inf")
        for i, (seq, rtt) in enumerate(valid):
            dx = pos.x() - px(seq)
            dy = pos.y() - py(rtt)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < closest_dist:
                closest_dist, closest = dist, i
        new_hovered = closest if closest_dist < 30 else None
        if new_hovered != self._hovered:
            self._hovered = new_hovered
            self.update()

    def leaveEvent(self, _):
        if self._hovered is not None:
            self._hovered = None
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W_total, H_total = self.width(), self.height()
        L, R, T, B = 72, 20, 32, 58
        W = W_total - L - R
        H = H_total - T - B

        # dark background
        bg = QLinearGradient(0, 0, 0, H_total)
        bg.setColorAt(0.0, QColor("#1A1F2E"))
        bg.setColorAt(1.0, QColor("#0D1117"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, W_total, H_total, 12, 12)
        border_pen = QPen(QColor("#2A3040"))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, W_total - 1, H_total - 1, 12, 12)

        valid = self._valid()
        all_rtts = [rtt for _, rtt in valid]
        sent = len(self.results)
        recv = len(valid)
        max_seq = max((seq for seq, _, _ in self.results), default=1)
        max_rtt = max(all_rtts, default=100) * 1.18
        max_rtt = max(max_rtt, 10)

        def px(s): return L + (s / max(max_seq, 1)) * W
        def py(r): return T + H - (r / max_rtt) * H

        # grid + Y labels
        for i in range(6):
            frac = i / 5
            y_g = T + H - frac * H
            val = frac * max_rtt
            grid_pen = QPen(QColor("#1E2A3A"))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            painter.drawLine(L, int(y_g), L + W, int(y_g))
            painter.setPen(QColor("#3A4460"))
            painter.setFont(QFont("Monospace", 7))
            painter.drawText(0, int(y_g) - 8, L - 8, 16,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{val:.0f}")

        # axes
        axis_pen = QPen(QColor("#2A3A50"))
        axis_pen.setWidth(1)
        painter.setPen(axis_pen)
        painter.drawLine(L, T, L, T + H)
        painter.drawLine(L, T + H, L + W, T + H)

        # Y axis label
        painter.save()
        painter.setPen(QColor("#4A6080"))
        painter.setFont(QFont("Sans Serif", 8))
        painter.translate(12, T + H // 2)
        painter.rotate(-90)
        painter.drawText(-50, -8, 100, 16, Qt.AlignmentFlag.AlignCenter, "Latency (ms)")
        painter.restore()

        # X axis label + ticks
        painter.setPen(QColor("#3A4460"))
        painter.setFont(QFont("Sans Serif", 8))
        painter.drawText(L, T + H + 20, W, 14, Qt.AlignmentFlag.AlignCenter, "Packet #")
        painter.setPen(QColor("#4A6080"))
        painter.setFont(QFont("Monospace", 7))
        step = max(1, max_seq // 10)
        for seq in range(step, max_seq + 1, step):
            x_g = px(seq)
            painter.drawText(int(x_g) - 15, T + H + 4, 30, 14,
                             Qt.AlignmentFlag.AlignCenter, str(seq))

        # timeout markers
        for seq, success, _ in self.results:
            if not success:
                x_g = px(seq)
                dash_pen = QPen(QColor("#3A4460"))
                dash_pen.setStyle(Qt.PenStyle.DashLine)
                dash_pen.setWidth(1)
                painter.setPen(dash_pen)
                painter.drawLine(int(x_g), T, int(x_g), T + H)
                painter.setPen(QColor("#5A3055"))
                painter.setFont(QFont("Sans Serif", 8))
                painter.drawText(int(x_g) - 8, T + H - 14, 16, 14,
                                 Qt.AlignmentFlag.AlignCenter, "✗")

        # gradient fill + neon curve
        if len(valid) >= 2:
            points = [(px(seq), py(rtt), rtt) for seq, rtt in valid]
            for i in range(1, len(points)):
                x0, y0, lat0 = points[i - 1]
                x1, y1, lat1 = points[i]
                cx_m = (x0 + x1) / 2
                seg_fill = QPainterPath()
                seg_fill.moveTo(x0, T + H)
                seg_fill.lineTo(x0, y0)
                seg_fill.cubicTo(cx_m, y0, cx_m, y1, x1, y1)
                seg_fill.lineTo(x1, T + H)
                seg_fill.closeSubpath()
                _, glow_c = self._color(lat1)
                gradient = QLinearGradient(0, min(y0, y1), 0, T + H)
                top_c = QColor(glow_c); top_c.setAlpha(60)
                bot_c = QColor(glow_c); bot_c.setAlpha(0)
                gradient.setColorAt(0.0, top_c)
                gradient.setColorAt(1.0, bot_c)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.fillPath(seg_fill, gradient)

            for pass_w, pass_alpha in [(5, 40), (3, 80), (2, 200)]:
                for i in range(1, len(points)):
                    x0, y0, _ = points[i - 1]
                    x1, y1, lat1 = points[i]
                    cx_m = (x0 + x1) / 2
                    seg_curve = QPainterPath()
                    seg_curve.moveTo(x0, y0)
                    seg_curve.cubicTo(cx_m, y0, cx_m, y1, x1, y1)
                    _, glow_c = self._color(lat1)
                    _gc = QColor(glow_c); _gc.setAlpha(pass_alpha)
                    pen = QPen(_gc)
                    pen.setWidth(pass_w)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.drawPath(seg_curve)

        elif len(valid) == 1:
            seq0, rtt0 = valid[0]
            x_g, y_g = px(seq0), py(rtt0)
            bar_c, glow_c = self._color(rtt0)
            for pass_w, pass_alpha in [(4, 50), (2, 180)]:
                _pc = QColor(glow_c); _pc.setAlpha(pass_alpha)
                painter.setPen(QPen(_pc, pass_w))
                painter.drawLine(L, int(y_g), L + W, int(y_g))

        # data points + hover badge
        for i, (seq, rtt) in enumerate(valid):
            x_g, y_g = px(seq), py(rtt)
            is_hovered = (self._hovered == i)
            bar_c, glow_c = self._color(rtt)

            glow_passes = [(22, 18), (16, 35), (11, 70), (7, 130)] if is_hovered else [(10, 20), (6, 50)]
            for glow_r, glow_a in glow_passes:
                g_c = QColor(glow_c); g_c.setAlpha(glow_a)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(g_c)
                painter.drawEllipse(int(x_g) - glow_r, int(y_g) - glow_r, glow_r * 2, glow_r * 2)

            r = 8 if is_hovered else 4
            pt_grad = QRadialGradient(x_g - r // 3, y_g - r // 3, r * 2)
            pt_grad.setColorAt(0.0, QColor(glow_c).lighter(150 if is_hovered else 120))
            pt_grad.setColorAt(1.0, QColor(bar_c))
            painter.setBrush(pt_grad)
            painter.setPen(QPen(QColor("#FFFFFF"), 2 if is_hovered else 0))
            painter.drawEllipse(int(x_g) - r, int(y_g) - r, r * 2, r * 2)

            if is_hovered:
                lat_str = f"#{seq}  {rtt:.2f} ms"
                badge_font = QFont("Monospace", 9, QFont.Weight.Bold)
                painter.setFont(badge_font)
                bw = painter.fontMetrics().horizontalAdvance(lat_str) + 18
                bh = 22
                bx = max(L, min(int(x_g) - bw // 2, L + W - bw))
                by = max(T, int(y_g) - 38)
                badge_bg = QColor(bar_c); badge_bg.setAlpha(90)
                painter.setBrush(badge_bg)
                _bb_c = QColor(bar_c); _bb_c.setAlpha(220)
                painter.setPen(QPen(_bb_c, 2))
                painter.drawRoundedRect(bx, by, bw, bh, bh // 2, bh // 2)
                painter.setPen(QColor(glow_c))
                painter.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, lat_str)
            else:
                # Small always-visible RTT label above point
                lat_str = f"{rtt:.1f}"
                painter.setFont(QFont("Monospace", 7))
                lw = painter.fontMetrics().horizontalAdvance(lat_str) + 4
                lx = max(L, min(int(x_g) - lw // 2, L + W - lw))
                ly = max(T, int(y_g) - 18)
                _tc = QColor(glow_c); _tc.setAlpha(200)
                painter.setPen(_tc)
                painter.drawText(lx, ly, lw, 13, Qt.AlignmentFlag.AlignCenter, lat_str)

        # footer stats
        if recv > 0 and all_rtts:
            min_r = min(all_rtts)
            avg_r = sum(all_rtts) / recv
            max_r = max(all_rtts)
            loss  = (sent - recv) / sent * 100
            footer = (f"{recv}/{sent} recv  ·  loss {loss:.0f}%  ·  "
                      f"min {min_r:.1f}  avg {avg_r:.1f}  max {max_r:.1f} ms")
        else:
            footer = f"0/{sent} recv  ·  100% loss"
        painter.setPen(QColor("#4A6080"))
        painter.setFont(QFont("Sans Serif", 8))
        painter.drawText(L, T + H + 38, W, 14, Qt.AlignmentFlag.AlignRight, footer)

        painter.end()

