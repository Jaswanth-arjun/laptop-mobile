"""Relay client — connects the laptop to the cloud relay server.

When running in relay mode, the laptop:
1. Connects to the relay via WebSocket
2. Creates a room (gets a 6-digit code)
3. Streams screen frames through the relay
4. Handles AI requests arriving from viewers via the relay
"""

import asyncio
import base64
import json
import logging
import time

log = logging.getLogger("remoteview.relay")


class RelayClient:
    """Manages the WebSocket connection to the cloud relay."""

    def __init__(self, relay_url: str, capture, key_pool, laptop_name: str = "Laptop"):
        self.relay_url = relay_url.rstrip("/")
        self.capture = capture
        self.key_pool = key_pool
        self.laptop_name = laptop_name
        self.ws = None
        self.room_code = None
        self.viewers = {}  # viewer_id → {device_name, quality, fps, scale, paused}
        self._running = False
        self._stream_task = None

    async def connect(self):
        """Connect to relay and register as host."""
        import websockets

        url = f"{self.relay_url}/host"
        log.info("Connecting to relay: %s", url)

        try:
            self.ws = await websockets.connect(url, max_size=50_000_000, ping_interval=20, ping_timeout=20)
        except Exception as e:
            log.error("Failed to connect to relay: %s", e)
            raise

        # Register
        await self.ws.send(json.dumps({
            "type": "register",
            "name": self.laptop_name,
        }))

        # Wait for room_created
        raw = await self.ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == "room_created":
            self.room_code = msg["code"]
            log.info("Room created! Code: %s", self.room_code)
        else:
            raise RuntimeError(f"Unexpected relay response: {msg}")

        self._running = True
        return self.room_code

    async def run(self):
        """Main loop: listen for relay messages + stream frames."""
        self._stream_task = asyncio.create_task(self._stream_loop())

        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue  # Host doesn't receive binary from relay

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                await self._handle_message(msg)
        except Exception as e:
            if self._running:
                log.error("Relay connection lost: %s", e)
        finally:
            self._running = False
            if self._stream_task:
                self._stream_task.cancel()

    async def _handle_message(self, msg):
        """Handle messages from the relay."""
        mtype = msg.get("type")

        if mtype == "viewer_joined":
            vid = msg["viewer_id"]
            name = msg.get("device_name", "Mobile")
            self.viewers[vid] = {
                "device_name": name,
                "quality": 60,
                "fps": 12,
                "scale": 1.0,
                "paused": False,
            }
            log.info("Viewer joined: %s (%s)", name, vid[:8])

        elif mtype == "viewer_left":
            vid = msg["viewer_id"]
            name = self.viewers.pop(vid, {}).get("device_name", "?")
            log.info("Viewer left: %s", name)

        elif mtype == "config":
            vid = msg.get("viewer_id")
            if vid and vid in self.viewers:
                v = self.viewers[vid]
                if "quality" in msg:
                    v["quality"] = max(20, min(int(msg["quality"]), 95))
                if "fps" in msg:
                    v["fps"] = max(1, min(int(msg["fps"]), 30))
                if "scale" in msg:
                    v["scale"] = max(0.15, min(float(msg["scale"]), 1.0))

        elif mtype == "pause":
            vid = msg.get("viewer_id")
            if vid and vid in self.viewers:
                self.viewers[vid]["paused"] = True

        elif mtype == "resume":
            vid = msg.get("viewer_id")
            if vid and vid in self.viewers:
                self.viewers[vid]["paused"] = False

        elif mtype == "ai_chat":
            asyncio.create_task(self._handle_ai_chat(msg))

        elif mtype == "screenshot_request":
            asyncio.create_task(self._handle_screenshot(msg))

    async def _handle_ai_chat(self, msg):
        """Process an AI chat request from a viewer."""
        rid = msg.get("rid", "")
        viewer_id = msg.get("viewer_id", "")
        prompt = str(msg.get("prompt") or "").strip()[:4000]
        images = msg.get("images") or []
        history = msg.get("history") or []

        try:
            text = await self._call_gemini(prompt, images, history)
            await self.ws.send(json.dumps({
                "type": "ai_response",
                "rid": rid,
                "viewer_id": viewer_id,
                "text": text,
                "error": False,
            }))
        except Exception as e:
            await self.ws.send(json.dumps({
                "type": "ai_response",
                "rid": rid,
                "viewer_id": viewer_id,
                "text": str(e),
                "error": True,
            }))

    async def _call_gemini(self, prompt: str, images: list, history: list) -> str:
        """Call Gemini API with key rotation (same logic as server.py)."""
        from app import config

        if not self.key_pool:
            raise RuntimeError("AI not configured. Add GEMINI_API_KEY_1 to .env")

        import base64 as b64mod

        # Build Gemini content parts
        user_parts = []
        if prompt:
            user_parts.append({"text": prompt})

        used = 0
        for img in images:
            if used >= config.AI_CHAT_MAX_IMAGES:
                break
            if not isinstance(img, str) or not img.startswith("data:image/"):
                continue
            if len(img) > 8_000_000:
                continue
            header, b64data = img.split(",", 1) if "," in img else ("", "")
            mime = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
            user_parts.append({"inline_data": {"mime_type": mime, "data": b64data}})
            used += 1

        if not user_parts:
            raise RuntimeError("No question or images provided")

        if used > 0:
            system_text = (
                "You are RemoteView, an assistant helping the user solve questions on their screen. "
                "CRITICAL REQUIREMENT: Give ONLY the direct answer. Do NOT provide any explanations, reasons, "
                "or background information. For multiple-choice questions or quiz screens, reply ONLY with the "
                "correct option letter and option name (e.g. 'B. Bharti AXA Life Insurance'). "
                "DO NOT wrap text in double asterisks (**) or markdown formatting. Keep the output strictly to "
                "the direct answer alone."
            )
        else:
            system_text = (
                "You are RemoteView, a direct-answer assistant. "
                "CRITICAL REQUIREMENT: Give ONLY the direct answer without any extra explanations, reasons, "
                "or intro/outro text. For multiple-choice questions, state ONLY the correct option letter and answer. "
                "DO NOT use double asterisks (**) or markdown formatting."
            )

        contents = []
        for h in history[-12:]:
            if not isinstance(h, dict):
                continue
            role = h.get("role")
            text = str(h.get("content") or "").strip()[:4000]
            if text:
                if role == "user":
                    contents.append({"role": "user", "parts": [{"text": text}]})
                elif role == "assistant":
                    contents.append({"role": "model", "parts": [{"text": text}]})
        contents.append({"role": "user", "parts": user_parts})

        payload = {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 4000},
        }

        # Call Gemini with key rotation
        import httpx

        last_error = "No AI keys available"
        for attempt in range(self.key_pool.size + 1):
            if attempt < self.key_pool.size:
                key = await self.key_pool.next_key()
            else:
                key = await self.key_pool.next_key_wait(timeout=65)
            if key is None:
                last_error = "All AI keys are rate-limited. Wait a moment."
                continue

            url = config.GEMINI_URL_TEMPLATE.format(model=config.GEMINI_MODEL, key=key)
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(url, json=payload)
            except httpx.HTTPError:
                last_error = "Could not reach Gemini API. Check internet."
                continue

            if resp.status_code == 429:
                self.key_pool.report_rate_limit(key)
                continue
            if resp.status_code >= 400:
                last_error = f"Gemini error ({resp.status_code})"
                continue

            self.key_pool.report_success(key)
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts) or "(empty)"

        raise RuntimeError(last_error)

    async def _handle_screenshot(self, msg):
        """Take a screenshot and send it back through relay."""
        rid = msg.get("rid", "")
        viewer_id = msg.get("viewer_id", "")

        try:
            jpeg = self.capture.capture_full(quality=60)
            b64 = base64.b64encode(jpeg).decode("ascii")
            res = self.capture.resolution()
            await self.ws.send(json.dumps({
                "type": "screenshot_response",
                "rid": rid,
                "viewer_id": viewer_id,
                "data": "data:image/jpeg;base64," + b64,
                "timestamp": time.time(),
                "laptop": self.laptop_name,
                "width": res.get("width", 0),
                "height": res.get("height", 0),
            }))
        except Exception as e:
            log.error("Screenshot failed: %s", e)

    async def _stream_loop(self):
        """Continuously capture screen and send frames through relay."""
        loop = asyncio.get_event_loop()
        last_thumb = None

        while self._running:
            if not self.viewers:
                await asyncio.sleep(0.5)
                continue

            # Use best quality/fps from active viewers
            active = [v for v in self.viewers.values() if not v["paused"]]
            if not active:
                await asyncio.sleep(0.1)
                continue

            quality = max(v["quality"] for v in active)
            scale = max(v["scale"] for v in active)
            fps = max(v["fps"] for v in active)

            started = time.perf_counter()
            try:
                jpeg, thumb, ts = await loop.run_in_executor(
                    None, self.capture.get_frame, quality, scale
                )
            except Exception as e:
                log.error("Capture error: %s", e)
                await asyncio.sleep(1)
                continue

            if jpeg is not None and thumb != last_thumb:
                last_thumb = thumb
                try:
                    await self.ws.send(jpeg)
                except Exception:
                    break
            elif thumb == last_thumb:
                try:
                    await self.ws.send(json.dumps({"type": "idle"}))
                except Exception:
                    break

            target = 1.0 / max(1, fps)
            spent = time.perf_counter() - started
            await asyncio.sleep(max(0.005, target - spent))

    async def close(self):
        """Disconnect from relay."""
        self._running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
