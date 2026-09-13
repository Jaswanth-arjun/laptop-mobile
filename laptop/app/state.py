"""Global application state shared between server, overlay and capture."""
import threading
import time


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.sharing: bool = False
        self.clients: dict[str, dict] = {}  # token -> {device_name, connected_at, paused}

    def set_sharing(self, enabled: bool) -> None:
        with self._lock:
            self.sharing = bool(enabled)
            if not enabled:
                self.clients.clear()

    def add_client(self, token: str, device_name: str) -> None:
        with self._lock:
            self.clients[token] = {
                "device_name": device_name,
                "connected_at": time.time(),
                "paused": False,
            }

    def remove_client(self, token: str) -> None:
        with self._lock:
            self.clients.pop(token, None)

    def set_paused(self, token: str, paused: bool) -> None:
        with self._lock:
            if token in self.clients:
                self.clients[token]["paused"] = bool(paused)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "sharing": self.sharing,
                "clients": [
                    {
                        "device_name": c["device_name"],
                        "connected_at": c["connected_at"],
                        "paused": c["paused"],
                    }
                    for c in self.clients.values()
                ],
            }

    def client_count(self) -> int:
        with self._lock:
            return len(self.clients)

    def client_for_token(self, token: str) -> dict | None:
        with self._lock:
            return self.clients.get(token)

    def is_paused(self, token: str) -> bool:
        with self._lock:
            client = self.clients.get(token)
            return bool(client and client["paused"])
