"""Screen capture + JPEG frame encoding using DXCam (with MSS fallback) and Pillow.

DXCam uses DXGI Desktop Duplication API on Windows, eliminating mouse cursor flickering
and offering ultra-low CPU GPU-accelerated capture.
"""
import io
import logging
import threading
import time

from PIL import Image

log = logging.getLogger("remoteview.capture")

try:
    import dxcam
    HAS_DXCAM = True
except Exception:
    HAS_DXCAM = False

import mss


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
        self._camera = None

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
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            self._camera = None

    @property
    def running(self) -> bool:
        return self._running

    def set_monitor(self, index: int) -> None:
        self._monitor_index = max(0, int(index))

    # ------------------------------------------------------------ internals
    def _loop(self) -> None:
        sct = None
        use_dxcam = HAS_DXCAM

        if use_dxcam:
            try:
                self._camera = dxcam.create(output_idx=self._monitor_index, output_color="RGB")
                log.info("DXCam initialized (No mouse flickering, DXGI GPU capture)")
            except Exception as e:
                log.warning("Failed to initialize DXCam: %s. Falling back to MSS.", e)
                use_dxcam = False
                self._camera = None

        while self._running:
            started = time.time()
            try:
                img = None
                if use_dxcam and self._camera is not None:
                    frame = self._camera.grab()
                    if frame is not None:
                        img = Image.fromarray(frame)
                
                if img is None:
                    if sct is None:
                        sct = mss.mss()
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
                self._error = None

            except Exception as exc:  # capture failures must never kill the thread
                self._error = str(exc) or exc.__class__.__name__
                if sct is not None:
                    try:
                        sct.close()
                    except Exception:
                        pass
                    sct = None

            elapsed = time.time() - started
            delay = max(0.01, 0.033 - elapsed)
            self._event.wait(delay)
            self._event.clear()

        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass

    # ------------------------------------------------------------ public API
    def get_frame(self, quality: int, scale: float) -> tuple[bytes | None, bytes | None, float]:
        """Return (encoded_jpeg, thumb, timestamp)."""
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
            if HAS_DXCAM and self._camera is not None:
                frame = self._camera.grab()
                if frame is not None:
                    img = Image.fromarray(frame)
            if img is None:
                with mss.mss() as sct:
                    monitors = sct.monitors
                    idx = self._monitor_index if 0 <= self._monitor_index < len(monitors) else 1
                    raw = sct.grab(monitors[idx])
                img = Image.frombytes("RGB", raw.size, raw.rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
