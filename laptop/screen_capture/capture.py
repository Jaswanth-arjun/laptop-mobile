"""Screen capture + JPEG frame encoding using MSS and Pillow.

A single background thread captures frames into a shared slot; WebSocket
handlers just read the latest frame and encode it at the quality/scale the
client requested. This keeps CPU usage low even with multiple viewers.
"""
import io
import threading
import time

import mss
from PIL import Image


class CaptureError(Exception):
    pass


class ScreenCapture:
    def __init__(self, monitor_index: int = 0):
        self._lock = threading.Lock()
        self._img: Image.Image | None = None
        self._thumb: bytes | None = None  # tiny JPEG used for change detection
        self._ts: float = 0.0
        self._monitor_index = max(0, monitor_index)
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._event = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="rv-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._running

    def set_monitor(self, index: int) -> None:
        self._monitor_index = max(0, int(index))

    # ------------------------------------------------------------ internals
    def _loop(self) -> None:
        while self._running:
            started = time.time()
            try:
                self._capture_once()
                self._error = None
            except Exception as exc:  # capture failures must never kill the thread
                self._error = str(exc) or exc.__class__.__name__
            elapsed = time.time() - started
            # run at ~2x the default fps so slower clients still get fresh frames
            delay = max(0.01, 0.5 / max(1, 12) - elapsed)
            self._event.wait(delay)
            self._event.clear()

    def _capture_once(self) -> None:
        with mss.mss() as sct:
            monitors = sct.monitors
            idx = self._monitor_index if 0 <= self._monitor_index < len(monitors) else 1
            monitor = monitors[idx]
            if monitor["width"] <= 0 or monitor["height"] <= 0:
                raise CaptureError("No usable monitor found")
            raw = sct.grab(monitor)

        img = Image.frombytes("RGB", raw.size, raw.rgb)

        # tiny thumbnail used by clients for cheap change detection
        thumb_w = 64
        thumb = img.resize((thumb_w, max(1, int(thumb_w * img.height / img.width))))
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=40)

        with self._lock:
            self._img = img
            self._thumb = buf.getvalue()
            self._ts = time.time()

    # ------------------------------------------------------------ public API
    def get_frame(self, quality: int, scale: float) -> tuple[bytes | None, bytes | None, float]:
        """Return (encoded_jpeg, thumb, timestamp).

        Encoding happens outside the lock on a private reference, so the
        capture thread keeps running while we encode.
        """
        with self._lock:
            img = self._img
            thumb = self._thumb
            ts = self._ts
        if img is None:
            return None, thumb, ts
        try:
            out = img
            if scale < 1.0:
                w = max(1, int(img.width * scale))
                h = max(1, int(img.height * scale))
                out = img.resize((w, h))
            buf = io.BytesIO()
            out.save(buf, format="JPEG", quality=int(quality))
            return buf.getvalue(), thumb, ts
        except Exception:
            return None, thumb, ts

    @property
    def last_error(self) -> str | None:
        return self._error

    def resolution(self) -> dict:
        with self._lock:
            img = self._img
        if img is not None:
            return {"width": img.width, "height": img.height}
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                idx = self._monitor_index if 0 <= self._monitor_index < len(monitors) else 1
                mon = monitors[idx]
                return {"width": mon["width"], "height": mon["height"]}
        except Exception:
            return {"width": 0, "height": 0}

    def capture_full(self, quality: int = 92) -> bytes:
        """High quality one-shot capture used for the screenshot feature."""
        with self._lock:
            img = self._img
            ts = self._ts
        if img is None or time.time() - ts > 2.0:
            with mss.mss() as sct:
                monitors = sct.monitors
                idx = self._monitor_index if 0 <= self._monitor_index < len(monitors) else 1
                raw = sct.grab(monitors[idx])
            img = Image.frombytes("RGB", raw.size, raw.rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
