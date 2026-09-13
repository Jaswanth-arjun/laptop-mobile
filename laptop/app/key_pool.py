"""Smart Gemini API key rotation pool.

Holds multiple API keys (from different Google accounts) and rotates them
round-robin.  When a key is rate-limited (HTTP 429), it enters a cooldown
period and the next available key is tried instantly.

Usage:
    pool = GeminiKeyPool(["key1", "key2", "key3"])
    key  = await pool.next_key()        # get the next available key
    pool.report_rate_limit(key)          # mark it as rate-limited
    pool.report_success(key)            # mark a successful call
    info = pool.status()                # get pool health info
"""

import asyncio
import time
import logging

log = logging.getLogger("remoteview.keypool")

# How long (seconds) a key stays on cooldown after a 429
DEFAULT_COOLDOWN = 60


class KeyState:
    """Tracks per-key health."""

    __slots__ = ("key", "masked", "request_count", "success_count",
                 "rate_limit_count", "last_used", "cooldown_until", "label")

    def __init__(self, key: str, label: str = ""):
        self.key = key
        # Show only first 8 and last 4 chars for safety
        self.masked = key[:8] + "..." + key[-4:] if len(key) > 14 else "***"
        self.label = label
        self.request_count = 0
        self.success_count = 0
        self.rate_limit_count = 0
        self.last_used = 0.0
        self.cooldown_until = 0.0

    @property
    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until - time.time())

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "masked_key": self.masked,
            "requests": self.request_count,
            "successes": self.success_count,
            "rate_limits": self.rate_limit_count,
            "available": self.is_available,
            "cooldown_remaining_s": round(self.cooldown_remaining, 1),
            "last_used": self.last_used,
        }


class GeminiKeyPool:
    """Round-robin key pool with automatic cooldown on rate-limit."""

    def __init__(self, keys: list[str], cooldown: int = DEFAULT_COOLDOWN):
        if not keys:
            raise ValueError("At least one Gemini API key is required")
        labels = []
        for i, k in enumerate(keys):
            if i == 0:
                labels.append(f"Key {i+1} (PRIMARY)")
            else:
                labels.append(f"Key {i+1}")
        self._states = [KeyState(k, lbl) for k, lbl in zip(keys, labels)]
        self._index = 0
        self._cooldown = cooldown
        self._lock = asyncio.Lock()
        log.info("Gemini key pool initialized with %d key(s)", len(keys))

    @property
    def size(self) -> int:
        return len(self._states)

    @property
    def available_count(self) -> int:
        return sum(1 for s in self._states if s.is_available)

    async def next_key(self) -> str | None:
        """Get the next available key via round-robin.

        Returns None if all keys are on cooldown.
        """
        async with self._lock:
            n = len(self._states)
            # Try each key starting from current index
            for _ in range(n):
                state = self._states[self._index]
                self._index = (self._index + 1) % n
                if state.is_available:
                    state.request_count += 1
                    state.last_used = time.time()
                    return state.key
            # All keys on cooldown — return the one with shortest remaining
            best = min(self._states, key=lambda s: s.cooldown_until)
            remaining = best.cooldown_remaining
            log.warning(
                "All %d keys on cooldown! Shortest wait: %.1fs (%s)",
                n, remaining, best.label,
            )
            return None

    async def next_key_wait(self, timeout: float = 120) -> str | None:
        """Get the next available key, waiting for cooldown if needed."""
        key = await self.next_key()
        if key is not None:
            return key

        # Wait for the shortest cooldown
        best = min(self._states, key=lambda s: s.cooldown_until)
        wait_time = min(best.cooldown_remaining, timeout)
        if wait_time > 0:
            log.info("Waiting %.1fs for key cooldown (%s)...", wait_time, best.label)
            await asyncio.sleep(wait_time)
        return await self.next_key()

    def report_rate_limit(self, key: str) -> None:
        """Mark a key as rate-limited (429). It enters cooldown."""
        for state in self._states:
            if state.key == key:
                state.rate_limit_count += 1
                state.cooldown_until = time.time() + self._cooldown
                log.warning(
                    "Key %s rate-limited! Cooldown %ds. (total 429s: %d)",
                    state.label, self._cooldown, state.rate_limit_count,
                )
                break

    def report_success(self, key: str) -> None:
        """Record a successful API call."""
        for state in self._states:
            if state.key == key:
                state.success_count += 1
                break

    def report_error(self, key: str, status: int) -> None:
        """Record a non-429 error.  Only 429 triggers cooldown."""
        if status == 429:
            self.report_rate_limit(key)

    def status(self) -> dict:
        """Return pool health for the admin dashboard / status endpoint."""
        total_reqs = sum(s.request_count for s in self._states)
        total_success = sum(s.success_count for s in self._states)
        total_429s = sum(s.rate_limit_count for s in self._states)
        return {
            "total_keys": len(self._states),
            "available_keys": self.available_count,
            "total_requests": total_reqs,
            "total_successes": total_success,
            "total_rate_limits": total_429s,
            "keys": [s.to_dict() for s in self._states],
        }
