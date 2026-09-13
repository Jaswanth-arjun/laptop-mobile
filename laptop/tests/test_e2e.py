"""End-to-end tests for RemoteView laptop server.

Start the server first (python main.py --no-overlay), then run:
    python tests/test_e2e.py
"""
import asyncio
import io
import json
import os
import urllib.request
import urllib.error

PORT = int(os.environ.get("RV_TEST_PORT", "8756"))
BASE = os.environ.get("RV_TEST_BASE", f"http://127.0.0.1:{PORT}")
PASSED = []
FAILED = []


def check(name, cond, extra=""):
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {extra}")


def req(method, path, body=None, token=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        resp = urllib.request.urlopen(r, timeout=15)
        payload = resp.read()
        if raw:
            return resp.status, payload, dict(resp.headers)
        return resp.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, payload, {}
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, {}


async def ws_test(token, expect_frames=3, timeout=15):
    import websockets

    uri = f"ws://127.0.0.1:{PORT}/ws/stream?token={token}"
    frames = 0
    json_msgs = []
    async with websockets.connect(uri, open_timeout=10) as ws:
        async def reader():
            nonlocal frames
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    if isinstance(msg, bytes):
                        frames += 1
                        if frames >= expect_frames:
                            return
                    else:
                        json_msgs.append(json.loads(msg))
                        if json_msgs[-1].get("type") in ("sharing_disabled", "unauthorized"):
                            return
            except Exception:
                return
        await reader()
    return frames, json_msgs


async def main():
    print("== admin ==")
    st, s = req("GET", "/api/admin/status")
    check("admin status 200", st == 200)
    check("admin has laptop name", bool(s.get("laptop_name")))
    check("admin local ip", s.get("local_ip") not in (None, "", "127.0.0.1"))

    # admin from non-loopback should be denied - simulate by checking endpoint requires local
    # (can't easily fake source IP here; the guard checks request.client.host)

    print("== pairing ==")
    st, s = req("GET", "/api/client/status")
    check("status without token 401", st == 401)

    st, p = req("POST", "/api/admin/pairing/start", {})
    check("pairing start 200", st == 200 and p.get("code"))
    code = p["code"]

    st, e = req("POST", "/api/pair", {"code": "000000", "device_name": "Bad Phone"})
    check("invalid code rejected", st == 401, str(st))

    st, e = req("POST", "/api/pair", {"code": "999999", "device_name": "Bad Phone"})
    check("second invalid code rejected", st == 401)

    st, ok = req("POST", "/api/pair", {"code": code, "device_name": "Test Phone"})
    check("valid code pairs", st == 200 and ok.get("token"), str(ok))
    token = ok["token"]

    st, e = req("POST", "/api/pair", {"code": code, "device_name": "Reuse Phone"})
    check("code is one-time use", st in (400, 401, 410), str(st))

    print("== client session ==")
    st, s = req("GET", "/api/client/status", token=token)
    check("client status 200", st == 200)
    check("status has resolution", s.get("resolution", {}).get("width", 0) > 0)
    check("sharing auto-enabled after pair", s.get("sharing") is True)

    print("== websocket stream ==")
    frames, msgs = await ws_test(token)
    check("stream delivers >=3 JPEG frames", frames >= 3, f"frames={frames}")
    check("no stream errors", not any(m.get("type") == "capture_error" for m in msgs), str(msgs))
    st, payload, headers = req("GET", "/api/screenshot", token=token, raw=True)
    check("screenshot 200", st == 200)
    check("screenshot is JPEG", payload[:2] == b"\xff\xd8", payload[:8].hex())
    check("screenshot size sane", len(payload) > 20000, str(len(payload)))
    check("screenshot laptop header", any(k.lower() == "x-rv-laptop" and v for k, v in headers.items()), str(list(headers.keys())))

    print("== unauthorized screenshot ==")
    st, _ = req("GET", "/api/screenshot")
    check("screenshot without token 401", st == 401)
    st, _ = req("GET", "/api/screenshot", token="forged-token-123")
    check("screenshot bad token 401", st == 401)

    print("== pause via websocket ==")
    import websockets
    uri = f"ws://127.0.0.1:{PORT}/ws/stream?token={token}"
    async with websockets.connect(uri, open_timeout=10) as ws:
        await ws.send(json.dumps({"type": "pause"}))
        # allow at most one in-flight frame, then require 2s of silence
        frames_after_pause = 0
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                if isinstance(msg, bytes):
                    frames_after_pause += 1
                    if frames_after_pause > 1:
                        break
        except asyncio.TimeoutError:
            pass
        check("paused stream sends no frames (max 1 in-flight)", frames_after_pause <= 1, str(frames_after_pause))
        await ws.send(json.dumps({"type": "resume"}))
        got = False
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                if isinstance(msg, bytes):
                    got = True
                    break
        except asyncio.TimeoutError:
            pass
        check("resumed stream sends frames", got)

    print("== expired pairing code ==")
    st, p = req("POST", "/api/admin/pairing/start", {"ttl": 5})
    exp_code = p["code"]
    await asyncio.sleep(6)
    st, e = req("POST", "/api/pair", {"code": exp_code, "device_name": "Late Phone"})
    check("expired code rejected", st in (400, 410), str(st))

    print("== unauthorized ws ==")
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/stream?token=badtoken", open_timeout=10) as ws:
            pass
        check("bad token ws rejected", False, "connection was accepted")
    except Exception as ex:
        text = str(ex)
        code_num = getattr(ex, "code", None) or (ex.rcvd.code if getattr(ex, "rcvd", None) else None)
        status_code = getattr(getattr(ex, "rsp", None), "status_code", None) or getattr(ex, "status_code", None)
        rejected = (
            code_num in (4401, 1008, 1006, 1011)
            or status_code in (401, 403)
            or "403" in text or "401" in text or "rejected" in text
        )
        check("bad token ws rejected", rejected, text)

    print("== revoke device ==")
    st, s = req("GET", "/api/admin/status")
    dev = next((d for d in s["sessions"] if d["device_name"] == "Test Phone"), None)
    check("device in session list", dev is not None)

    async def revoked_ws():
        import websockets
        uri = f"ws://127.0.0.1:{PORT}/ws/stream?token={token}"
        ws = await websockets.connect(uri, open_timeout=10)
        code_seen = None
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=10)
        except Exception as ex:
            code_seen = getattr(ex, "code", None) or getattr(getattr(ex, "rcvd", None), "code", None)
        return code_seen

    task = asyncio.create_task(revoked_ws())
    await asyncio.sleep(1.5)
    st, _ = req("POST", f"/api/admin/revoke/{dev['device_id']}", {})
    check("revoke 200", st == 200)
    code_seen = await task
    check("revoked ws closed 4403", code_seen == 4403, str(code_seen))

    st, s = req("GET", "/api/client/status", token=token)
    check("revoked token rejected", st == 401)

    print("== sharing off ==")
    st, p = req("POST", "/api/admin/pairing/start", {})
    st, ok = req("POST", "/api/pair", {"code": p["code"], "device_name": "Share Test"})
    token2 = ok["token"]
    st, _ = req("POST", "/api/admin/sharing", {"enabled": False})
    check("sharing off 200", st == 200)
    frames, msgs = await ws_test(token2, expect_frames=1, timeout=5)
    check("sharing off closes stream with message", any(m.get("type") == "sharing_disabled" for m in msgs), str(msgs))
    st, _ = req("POST", "/api/admin/sharing", {"enabled": True})
    check("sharing back on", st == 200)

    print("== revoke all ==")
    st, r = req("POST", "/api/admin/revoke-all", {})
    check("revoke-all 200", st == 200 and r.get("revoked", 0) >= 1, str(r))
    st, _ = req("GET", "/api/client/status", token=token2)
    check("all tokens invalidated", st == 401)

    print("== spa / static ==")
    st, payload, headers = req("GET", "/", raw=True)
    check("mobile index served", st == 200 and b"<div id=\"root\">" in payload)
    st, payload, _ = req("GET", "/pair?code=123456", raw=True)
    check("pair route serves SPA", st == 200)
    st, payload, _ = req("GET", "/manifest.webmanifest", raw=True)
    check("manifest served", st == 200 and b"RemoteView" in payload)
    st, payload, _ = req("GET", "/api/nonexistent", raw=True)
    check("unknown api 404", st == 404)

    print()
    print(f"RESULT: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failed:", FAILED)


asyncio.run(main())
