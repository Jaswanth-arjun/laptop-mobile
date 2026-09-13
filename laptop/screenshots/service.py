"""Screenshot service: explicit, on-demand captures for authorized clients."""
import time

from screen_capture.capture import ScreenCapture


def take_screenshot(capture: ScreenCapture) -> tuple[bytes, dict]:
    data = capture.capture_full(quality=92)
    meta = {
        "timestamp": time.time(),
        "width": capture.resolution().get("width", 0),
        "height": capture.resolution().get("height", 0),
    }
    return data, meta
