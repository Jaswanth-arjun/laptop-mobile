"""RemoteView FastAPI application: pairing, streaming, screenshots, admin."""
import asyncio
import json
import logging
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .state import AppState
from networking.address import get_device_name
from pairing.manager import PairingError, PairingManager
from security import db
from screen_capture.capture import ScreenCapture
from screenshots.service import take_screenshot

log = logging.getLogger("remoteview")

MOBILE_DIST = Path(os.environ.get("RV_MOBILE_DIST", str(config.PROJECT_DIR.parent / "mobile" / "dist")))
ADMIN_PAGE = config.APP_DIR / "static" / "admin.html"

STATIC_FILENAMES = {"manifest.webmanifest", "favicon.ico", "icon-192.png", "icon-512.png", "sw.js"}


class RemoteViewServer:
    def __init__(self):
        self.state = AppState()
        self.capture = ScreenCapture(monitor_index=int(db.get_setting("monitor", 0) or 0))
        self.pairing = PairingManager(config.PAIRING_CODE_TTL)
        self.websockets: dict[str, set[WebSocket]] = {}
        self.kicked: set[str] = set()
        self.overlay = None
        self.local_ip = "127.0.0.1"
        self.port = config.PORT
        # Gemini multi-key pool (PRO key first, then normal keys)
    def get_key_pool(self):
        """Return dynamic key pool with user custom DB keys if present, else config default keys."""
        from .key_pool import GeminiKeyPool
        k1 = str(db.get_setting("gemini_key_1", "") or "").strip()
        k2 = str(db.get_setting("gemini_key_2", "") or "").strip()
        k3 = str(db.get_setting("gemini_key_3", "") or "").strip()
        custom_keys = [k for k in [k1, k2, k3] if k]
        if custom_keys:
            return GeminiKeyPool(custom_keys, cooldown=config.GEMINI_COOLDOWN)
        if config.GEMINI_API_KEYS:
            return GeminiKeyPool(config.GEMINI_API_KEYS, cooldown=config.GEMINI_COOLDOWN)
        return None

    async def _gemini_call(self, payload: dict) -> str:
        """Call Gemini API with automatic key rotation and retry on rate-limit."""
        import httpx

        pool = self.get_key_pool()
        if pool is None:
            raise HTTPException(
                status_code=503,
                detail="AI is not configured. Go to Dashboard > Settings to enter your Gemini API Key.",
            )

        last_error = "No AI keys available"
        for attempt in range(pool.size + 1):
            if attempt < pool.size:
                key = await pool.next_key()
            else:
                key = await pool.next_key_wait(timeout=65)
            if key is None:
                last_error = "All AI keys are rate-limited. Please wait a moment and try again."
                continue

            url = config.GEMINI_URL_TEMPLATE.format(model=config.GEMINI_MODEL, key=key)
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(url, json=payload)
            except httpx.HTTPError:
                last_error = "Could not reach Gemini API. Check the laptop's internet connection."
                continue

            if resp.status_code == 429:
                pool.report_rate_limit(key)
                last_error = "Key rate-limited, rotating..."
                log.info("Gemini 429 on attempt %d, rotating to next key", attempt + 1)
                continue
            if resp.status_code == 400:
                data = resp.json()
                err_msg = ""
                for e in data.get("error", {}).get("details", []):
                    err_msg += str(e.get("reason", ""))
                if "API_KEY_INVALID" in err_msg or "API key" in str(data.get("error", {}).get("message", "")):
                    raise HTTPException(status_code=502, detail="Invalid Gemini API key. Please check your keys in Settings.")
                last_error = data.get("error", {}).get("message", f"Gemini error ({resp.status_code})")
                continue
            if resp.status_code >= 400:
                last_error = f"Gemini API error ({resp.status_code})"
                continue

            pool.report_success(key)
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                last_error = "Gemini returned no candidates. Try again."
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            if not text:
                last_error = "Gemini returned an empty answer. Try again."
                continue
            return text

        raise HTTPException(status_code=502, detail=last_error)



    # ================================================================ auth
    def _auth_token(self, request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token:
            token = request.headers.get("X-RemoteView-Token", "")
        if not token:
            token = request.query_params.get("token", "")
        if not db.get_session(token):
            raise HTTPException(status_code=401, detail="Unauthorized. Pair the device again.")
        db.touch_session(token)
        return token

    def _session_name(self, token: str) -> str:
        row = db.get_session(token)
        return row["device_name"] if row else "Mobile device"

    def _require_local(self, request: Request) -> None:
        host = request.client.host if request.client else ""
        if host not in ("127.0.0.1", "::1"):
            raise HTTPException(status_code=403, detail="Local access only")

    # ================================================================ app
    def _build_app(self) -> FastAPI:
        app = FastAPI(title="RemoteView", docs_url=None, redoc_url=None, openapi_url=None)
        rt = self

        # -------------------------------------------------- public (pairing)
        @app.post("/api/pair")
        async def pair(body: dict):
            try:
                session = rt.pairing.redeem(body.get("code", ""), body.get("device_name", ""))
            except PairingError as exc:
                raise HTTPException(status_code=exc.status, detail=str(exc))
            # Pairing is the explicit authorization act: sharing starts enabled.
            rt.apply_sharing(True)
            return {
                "ok": True,
                "token": session["token"],
                "device_id": session["device_id"],
                "laptop_name": get_device_name(),
            }

        # -------------------------------------------------- mobile (token)
        @app.get("/api/client/status")
        async def client_status(token: str = Depends(rt._auth_token)):
            mine = rt.state.client_for_token(token)
            return {
                "ok": True,
                "laptop_name": get_device_name(),
                "sharing": rt.state.sharing,
                "resolution": rt.capture.resolution(),
                "connected_devices": rt.state.client_count(),
                "paused": bool(mine and mine["paused"]),
                "capture_error": rt.capture.last_error,
            }

        @app.post("/api/client/revoke")
        async def client_revoke(token: str = Depends(rt._auth_token)):
            db.delete_session(token)
            await rt.close_token_websockets(token)
            return {"ok": True}

        @app.get("/api/screenshot")
        async def screenshot(token: str = Depends(rt._auth_token)):
            if not rt.state.sharing:
                raise HTTPException(status_code=403, detail="Screen sharing is currently disabled on the laptop")
            data, meta = take_screenshot(rt.capture)
            return Response(
                content=data,
                media_type="image/jpeg",
                headers={
                    "Content-Disposition": "attachment; filename=remoteview-screenshot.jpg",
                    "X-RV-Timestamp": str(meta["timestamp"]),
                    "X-RV-Laptop": get_device_name(),
                    "X-RV-Width": str(meta["width"]),
                    "X-RV-Height": str(meta["height"]),
                },
            )

        @app.post("/api/ai/describe")
        async def ai_describe(request: Request, token: str = Depends(rt._auth_token)):
            if not config.GEMINI_API_KEYS:
                raise HTTPException(
                    status_code=503,
                    detail="AI is not configured. Set GEMINI_API_KEY_1 (and optionally _2, _3) in laptop/.env and restart.",
                )
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid request body")
            prompt = (body.get("prompt") or "Briefly describe what is visible on this screen.").strip()[:2000]
            jpeg = rt.capture.capture_full(quality=60)
            import base64
            b64data = base64.b64encode(jpeg).decode("ascii")

            # Gemini API format
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64data}},
                        ]
                    }
                ],
                "generationConfig": {"maxOutputTokens": 400},
            }
            text = await rt._gemini_call(payload)
            return {"ok": True, "text": text}

        @app.post("/api/ai/chat")
        async def ai_chat(request: Request, token: str = Depends(rt._auth_token)):
            """AI agent chat: user question + N captured screen images -> answer.

            Images arrive as data:image/...;base64 URLs captured on the phone
            (compressed there). The Gemini API keys never leave the laptop.
            """
            if not config.GEMINI_API_KEYS:
                raise HTTPException(
                    status_code=503,
                    detail="AI is not configured. Set GEMINI_API_KEY_1 (and optionally _2, _3) in laptop/.env and restart.",
                )
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid request body")

            prompt = str(body.get("prompt") or "").strip()[:4000]
            images = body.get("images") or []
            history = body.get("history") or []
            if not isinstance(images, list) or not isinstance(history, list):
                raise HTTPException(status_code=400, detail="Invalid request body")
            if not prompt and not images:
                raise HTTPException(status_code=400, detail="Type a question or tap + to capture the screen first")

            # Build Gemini-format parts for the user message
            import base64 as b64mod
            user_parts = []
            if prompt:
                user_parts.append({"text": prompt})
            total = 0
            used = 0
            for img in images:
                if used >= config.AI_CHAT_MAX_IMAGES:
                    break
                if not isinstance(img, str) or not img.startswith("data:image/"):
                    continue
                if len(img) > 8_000_000:
                    continue
                total += len(img)
                # Extract mime and base64 data from data URL
                header, b64data = img.split(",", 1) if "," in img else ("", "")
                mime = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
                user_parts.append({"inline_data": {"mime_type": mime, "data": b64data}})
                used += 1
            if total > 30_000_000:
                raise HTTPException(status_code=413, detail="Too many/too large captures in one message. Send a few at a time.")
            if not user_parts:
                raise HTTPException(status_code=400, detail="No usable captures or question found")

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

            # Build Gemini contents array with history
            contents = []
            # System instruction goes in systemInstruction field (Gemini format)
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

            text = await rt._gemini_call(payload)
            return {"ok": True, "text": text}

        @app.get("/api/ai/status")
        async def ai_status(token: str = Depends(rt._auth_token)):
            """Return key pool health so the mobile app can show rotation status."""
            if rt.key_pool is None:
                return {"ok": True, "configured": False, "pool": None}
            return {"ok": True, "configured": True, "pool": rt.key_pool.status()}

        @app.get("/api/admin/qr")
        async def admin_qr(request: Request, u: str = ""):
            rt._require_local(request)
            if not u:
                raise HTTPException(status_code=400, detail="Missing URL")
            import io

            import qrcode

            img = qrcode.make(u)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return Response(content=buf.getvalue(), media_type="image/png")

        # -------------------------------------------------- admin (loopback)
        @app.get("/api/admin/status")
        async def admin_status(request: Request):
            rt._require_local(request)
            return {
                "ok": True,
                "laptop_name": get_device_name(),
                "sharing": rt.state.sharing,
                "local_ip": rt.local_ip,
                "port": rt.port,
                "resolution": rt.capture.resolution(),
                "capture_error": rt.capture.last_error,
                "connected": rt.state.snapshot()["clients"],
                "sessions": db.list_sessions(),
                "pairing": rt.pairing.status(),
            }

        @app.post("/api/admin/pairing/start")
        async def admin_pairing_start(request: Request):
            rt._require_local(request)
            ttl = None
            try:
                body = await request.json()
                ttl = body.get("ttl")
                if ttl is not None:
                    ttl = max(5, min(int(ttl), 3600))
            except Exception:
                pass
            return {"ok": True, **rt.pairing.new_code(ttl)}

        @app.post("/api/admin/sharing")
        async def admin_sharing(request: Request, body: dict):
            rt._require_local(request)
            enabled = bool(body.get("enabled"))
            rt.apply_sharing(enabled)
            return {"ok": True, "sharing": rt.state.sharing}

        @app.get("/api/admin/settings")
        async def admin_settings(request: Request):
            rt._require_local(request)
            k1 = str(db.get_setting("gemini_key_1", "") or "")
            k2 = str(db.get_setting("gemini_key_2", "") or "")
            k3 = str(db.get_setting("gemini_key_3", "") or "")
            def mask(k):
                return (k[:6] + "..." + k[-4:]) if len(k) > 10 else ("********" if k else "")
            return {
                "ok": True,
                "fps": db.get_setting("fps", config.DEFAULT_FPS),
                "quality": db.get_setting("quality", config.DEFAULT_QUALITY),
                "scale": db.get_setting("scale", config.DEFAULT_SCALE),
                "monitor": db.get_setting("monitor", 0),
                "gemini_key_1": k1,
                "gemini_key_2": k2,
                "gemini_key_3": k3,
                "gemini_key_1_masked": mask(k1),
                "gemini_key_2_masked": mask(k2),
                "gemini_key_3_masked": mask(k3),
                "has_custom_keys": bool(k1 or k2 or k3),
            }

        @app.post("/api/admin/settings")
        async def admin_settings_post(request: Request, body: dict):
            rt._require_local(request)
            fps = db.get_setting("fps", config.DEFAULT_FPS)
            quality = db.get_setting("quality", config.DEFAULT_QUALITY)
            scale = db.get_setting("scale", config.DEFAULT_SCALE)
            monitor = db.get_setting("monitor", 0)
            if "fps" in body:
                fps = max(1, min(int(body["fps"]), config.MAX_FPS))
                db.set_setting("fps", fps)
            if "quality" in body:
                quality = max(10, min(int(body["quality"]), config.MAX_QUALITY))
                db.set_setting("quality", quality)
            if "scale" in body:
                scale = max(0.15, min(float(body["scale"]), 1.0))
                db.set_setting("scale", scale)
            if "monitor" in body:
                monitor = max(0, int(body["monitor"]))
                rt.capture.set_monitor(monitor)
                db.set_setting("monitor", monitor)
            if "gemini_key_1" in body:
                db.set_setting("gemini_key_1", str(body["gemini_key_1"]).strip())
            if "gemini_key_2" in body:
                db.set_setting("gemini_key_2", str(body["gemini_key_2"]).strip())
            if "gemini_key_3" in body:
                db.set_setting("gemini_key_3", str(body["gemini_key_3"]).strip())
            return {"ok": True, "fps": fps, "quality": quality, "scale": scale, "monitor": monitor}


        @app.post("/api/admin/revoke/{device_id}")
        async def admin_revoke(device_id: str, request: Request):
            rt._require_local(request)
            token = db.delete_session_by_device(device_id)
            if not token:
                raise HTTPException(status_code=404, detail="Device not found")
            await rt.close_token_websockets(token)
            return {"ok": True}

        @app.post("/api/admin/revoke-all")
        async def admin_revoke_all(request: Request):
            rt._require_local(request)
            tokens = db.delete_all_sessions()
            await rt.disconnect_all_ws()
            return {"ok": True, "revoked": len(tokens)}

        # -------------------------------------------------- websocket stream
        @app.websocket("/ws/stream")
        async def stream(ws: WebSocket):
            token = ws.query_params.get("token", "")
            if not db.get_session(token):
                try:
                    await ws.close(code=4401)
                except Exception:
                    pass
                return
            await ws.accept()
            await rt._run_stream(ws, token)

        # -------------------------------------------------- static frontend
        @app.get("/admin", include_in_schema=False)
        async def admin_ui(request: Request):
            rt._require_local(request)
            return FileResponse(ADMIN_PAGE)

        if MOBILE_DIST.exists():
            app.mount("/assets", StaticFiles(directory=MOBILE_DIST / "assets"), name="assets")

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa(full_path: str):
                if full_path.startswith(("api/", "ws/", "admin")):
                    raise HTTPException(status_code=404, detail="Not found")
                if full_path in STATIC_FILENAMES:
                    candidate = MOBILE_DIST / full_path
                    if candidate.exists():
                        return FileResponse(candidate)
                return FileResponse(MOBILE_DIST / "index.html")
        return app

    # ============================================================ streaming
    async def _run_stream(self, ws: WebSocket, token: str) -> None:
        settings = {
            "quality": max(20, min(int(db.get_setting("quality", config.DEFAULT_QUALITY)), config.MAX_QUALITY)),
            "scale": max(0.15, min(float(db.get_setting("scale", config.DEFAULT_SCALE)), 1.0)),
            "fps": max(1, min(int(db.get_setting("fps", config.DEFAULT_FPS)), config.MAX_FPS)),
        }
        device_name = self._session_name(token)
        self.state.add_client(token, device_name)
        self.websockets.setdefault(token, set()).add(ws)
        self._notify_overlay()
        last_thumb: bytes | None = None
        idle_sent = False
        error_sent = False
        loop = asyncio.get_event_loop()

        async def reader():
            try:
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    mtype = msg.get("type")
                    if mtype == "config":
                        try:
                            if "quality" in msg:
                                settings["quality"] = max(20, min(int(msg["quality"]), config.MAX_QUALITY))
                            if "scale" in msg:
                                settings["scale"] = max(0.15, min(float(msg["scale"]), 1.0))
                            if "fps" in msg:
                                settings["fps"] = max(1, min(int(msg["fps"]), config.MAX_FPS))
                        except (TypeError, ValueError):
                            pass
                    elif mtype == "pause":
                        self.state.set_paused(token, True)
                        self._notify_overlay()
                    elif mtype == "resume":
                        self.state.set_paused(token, False)
                        self._notify_overlay()
            except Exception:
                pass

        reader_task = asyncio.create_task(reader())
        kicked = False
        try:
            while True:
                if token in self.kicked:
                    kicked = True
                    try:
                        await ws.close(code=4403)
                    except Exception:
                        pass
                    break
                started = time.perf_counter()
                if not self.state.sharing:
                    await ws.send_json({"type": "sharing_disabled"})
                    await ws.close()
                    break
                # encode first, then re-check pause/kick so a pause requested
                # while encoding never lets an extra frame through
                jpeg, thumb, ts = await loop.run_in_executor(
                    None, self.capture.get_frame, settings["quality"], settings["scale"]
                )
                if token in self.kicked:
                    kicked = True
                    try:
                        await ws.close(code=4403)
                    except Exception:
                        pass
                    break
                if self.state.is_paused(token):
                    await asyncio.sleep(0.02)
                    continue
                stale = ts > 0 and (time.time() - ts) > 2.0
                if stale and not error_sent:
                    error_sent = True
                    await ws.send_json({
                        "type": "capture_error",
                        "message": self.capture.last_error or "Screen capture is not producing frames",
                    })
                elif jpeg is not None and not stale:
                    error_sent = False
                    if thumb != last_thumb:
                        last_thumb = thumb
                        idle_sent = False
                        await ws.send_bytes(jpeg)
                    elif not idle_sent:
                        idle_sent = True
                        await ws.send_json({"type": "idle"})
                target = 1.0 / max(1, settings["fps"])
                spent = time.perf_counter() - started
                await asyncio.sleep(max(0.005, target - spent))
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception as exc:
            log.warning("stream error: %s", exc)
        finally:
            reader_task.cancel()
            self.state.remove_client(token)
            self.websockets.get(token, set()).discard(ws)
            self.kicked.discard(token)
            self._notify_overlay()

    # ============================================================ sharing
    def apply_sharing(self, enabled: bool) -> None:
        """Thread-safe sharing toggle used by admin API and pairing."""
        self.state.set_sharing(enabled)
        db.set_setting("sharing", enabled)
        if not enabled:
            self._schedule(self.disconnect_all_ws())
            if self.overlay is not None:
                self.overlay.close()
        else:
            if self.overlay is not None:
                self.overlay.start()
                self.overlay.update("No device connected")
            self._notify_overlay()

    def disconnect_all_sync(self) -> None:
        """Called from the overlay button (non-asyncio thread)."""
        self._schedule(self.disconnect_all_ws())

    def _schedule(self, coro) -> None:
        loop = getattr(self, "loop", None)
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            try:
                asyncio.run(coro)
            except Exception:
                pass

    async def close_token_websockets(self, token: str) -> None:
        # Never await close() from a foreign request context: the stream
        # handler loop notices the "kicked" flag and closes cleanly itself.
        self.kicked.add(token)
        for ws in list(self.websockets.get(token, set())):
            try:
                ws_closed = ws.close(code=4403)
                asyncio.create_task(ws_closed)
            except Exception:
                pass
        self.state.remove_client(token)
        self._notify_overlay()

    async def disconnect_all_ws(self) -> None:
        for token in list(self.websockets.keys()):
            await self.close_token_websockets(token)

    def _notify_overlay(self) -> None:
        if self.overlay is None:
            return
        snap = self.state.snapshot()
        if not snap["sharing"]:
            return
        names = ", ".join(c["device_name"] for c in snap["clients"]) or "No device connected"
        self.overlay.update(f"Mobile connected: {names}")
