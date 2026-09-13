"""One-time pairing codes with expiry."""
import threading
import time

from security import db, tokens


class PairingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class PairingManager:
    def __init__(self, ttl: int):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._code: str | None = None
        self._expires: float = 0.0

    def new_code(self, ttl: int | None = None) -> dict:
        with self._lock:
            self._code = tokens.new_pairing_code()
            self._expires = time.time() + (ttl or self.ttl)
            return {
                "code": self._code,
                "expires_at": self._expires,
                "ttl": ttl or self.ttl,
            }

    def status(self) -> dict:
        with self._lock:
            if not self._code:
                return {"active": False, "expires_in": 0}
            remaining = round(self._expires - time.time())
            if remaining <= 0:
                self._code = None
                return {"active": False, "expires_in": 0}
            return {"active": True, "code": self._code, "expires_in": remaining}

    def redeem(self, code: str, device_name: str) -> dict:
        clean = (code or "").strip()
        with self._lock:
            if not self._code:
                raise PairingError("No pairing code is active. Generate a new one on the laptop.")
            if clean != self._code:
                raise PairingError("Invalid pairing code", status=401)
            remaining = self._expires - time.time()
            if remaining <= 0:
                self._code = None
                raise PairingError("Pairing code has expired. Generate a new one on the laptop.", status=410)
            # one-time use: burn the code immediately
            self._code = None
        name = (device_name or "").strip() or "Mobile device"
        session = db.create_session(name)
        return session
