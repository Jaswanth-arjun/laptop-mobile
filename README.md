# RemoteView

View and capture your **own** laptop's screen from your phone over the same
Wi-Fi network. The laptop runs a small Python server; the phone uses a web app
(PWA) served by that server — no cloud, no accounts, nothing leaves your
network.

```
┌────────────── Laptop ──────────────┐        ┌───────── Phone ─────────┐
│ Screen capture (MSS)               │        │ PWA (React)             │
│   → JPEG frames (quality/scale     │  LAN   │   WebSocket client      │
│      adaptive, change detection)   │ ◄────► │   decode → canvas       │
│ FastAPI + WebSocket (Uvicorn)      │  HTTP  │   screenshot gallery    │
│ Pairing: QR + one-time code        │        │   (IndexedDB, local)    │
│ SQLite sessions + tokens           │        │                         │
│ On-screen sharing indicator        │        │                         │
└────────────────────────────────────┘        └─────────────────────────┘
```

## Features

**Laptop (Windows)**
- Dashboard at `http://127.0.0.1:<port>/admin`: device name, local IP, QR
  code + one-time pairing code, connected devices, paired devices, start/stop
  screen sharing, disconnect one/all, streaming settings (FPS, quality,
  scale, monitor).
- Always-on-top indicator while sharing: *"SCREEN SHARING ACTIVE — Mobile
  connected: \<name\>"* with an instant **Disconnect mobile** button.
- Efficient streaming: background capture thread, JPEG encoding at the
  resolution/quality each client requested, unchanged-screen detection, and
  client-driven adaptive quality.

**Mobile (PWA, served by the laptop)**
- **Home** — connect by scanning the dashboard QR (opens the app with the
  code pre-filled) or typing the pairing code.
- **Live** — low-latency live screen, full-screen mode, pinch/button zoom,
  fit-to-screen, pause/resume, reconnect, connection status, resolution,
  and a **Take Laptop Screenshot** button.
- **Screenshots** — history stored locally on the phone (IndexedDB) with
  timestamp and laptop name; open, save, share (native share sheet with
  download fallback), delete.
- **Settings** — laptop info, reconnect, streaming preferences
  (auto-quality + JPEG quality), phone name, and *Remove this device* which
  revokes the phone's token on the laptop.

**Security**
- Pairing codes are one-time, 6 digits, and expire (default 5 minutes).
- After pairing, the phone gets a random session token; **every** request
  (REST and WebSocket) requires it. No token = no screen data.
- Tokens can be revoked per device or globally ("Disconnect all").
- The admin dashboard only accepts loopback connections.
- Sharing can be stopped at any time from the dashboard or the on-screen
  indicator; stopping sharing immediately disconnects every viewer.
- Screenshots are only captured after an explicit tap on the phone.

**Optional AI (OpenRouter)**
- The live screen has an **AI chat bar**: tap **+** to capture the current
  laptop screen into the chat (tap again to attach more screens), type a
  question, press **➤** — the backend sends all captures + the question (and
  recent chat context) to OpenRouter and returns the answer. Follow-up
  questions keep context.
- The screenshot viewer also has an "AI" describe button.
- All AI requests go **phone → laptop → OpenRouter**; the API key stays on
  the laptop. Without `OPENROUTER_API_KEY` set, everything else works
  normally and the chat explains how to enable it.

## Requirements

- Windows 10/11
- Python 3.10+ (`python --version`)
- Node.js 18+ and npm (only needed to build the mobile app; a prebuilt
  `mobile/dist` can be reused)
- Laptop and phone on the same Wi-Fi/LAN

## Installation

### 1. Laptop

```powershell
cd laptop
python -m pip install -r requirements.txt
```

Optional configuration — copy `.env.example` to `.env` and edit:

```
RV_PORT=8756          # server port
RV_PAIRING_TTL=300    # pairing code lifetime (seconds)
RV_FPS=12             # default FPS cap
RV_QUALITY=60         # default JPEG quality
RV_SCALE=1.0          # default stream scale
# OPENROUTER_API_KEY=your_key_here   # optional, enables the AI describe button
# OPENROUTER_MODEL=openai/gpt-4o-mini
```

Never hardcode keys in source and never commit `.env`.

### 2. Mobile app build

```powershell
cd mobile
npm install
npm run build      # outputs mobile/dist — served automatically by the laptop
```

If `mobile/dist` does not exist when the server starts, the API and dashboard
still work; only the phone UI needs the build.

### 3. Run

```powershell
cd laptop
python main.py
```

- The **dashboard** opens automatically at `http://127.0.0.1:8756/admin`.
- The **mobile URL** is printed, e.g. `http://192.168.0.109:8756`.

Useful flags:

```
python main.py --setup-firewall   # try to add the Windows Firewall rule (run as admin)
python main.py --no-overlay       # disable the on-screen sharing indicator
python main.py --port 9000        # use a different port
```

## Pairing (phone ↔ laptop)

1. Start the server on the laptop (dashboard opens).
2. On the phone, scan the **QR code** with the phone's camera app — it opens
   the mobile app with the pairing code pre-filled. Or open
   `http://<laptop-ip>:8756` and type the **6-digit code**.
3. Tap **Connect to laptop**. The code is burned (one-time use) and the phone
   is saved in the laptop's paired devices.
4. The live screen appears immediately.

Codes expire after 5 minutes; generate a new one from the dashboard with
**New pairing code**.

## LAN / firewall notes

- The server binds to `0.0.0.0` on port 8756 (configurable). If the phone
  cannot connect:
  - Make sure both devices are on the same Wi-Fi and the network is not a
    "Public" profile (rule is created for Private/Domain).
  - Allow Python or TCP port 8756 in Windows Firewall, or run as admin:
    `python main.py --setup-firewall`.
- If the port is busy, the server automatically tries the next 10 ports and
  prints the chosen one.
- The app never opens the internet; the phone must be able to reach the
  laptop's LAN IP.

## How streaming works

- A capture thread grabs the screen ~2× per second at full quality using
  [MSS](https://github.com/BoboTiG/python-mss).
- Each WebSocket viewer requests its own quality/scale/FPS; frames are
  encoded per-viewer and skipped entirely when the tiny change-detection
  thumbnail shows the screen hasn't changed (a lightweight `idle` message is
  sent instead).
- The phone auto-lowers the stream scale if it can't keep up (configurable in
  Settings → "Auto-adjust quality"), and raises it back when possible.

## Testing

The repository's server logic was verified end-to-end (37 automated checks):
valid/invalid/expired pairing codes, one-time code burn, streaming frames,
pause/resume, screenshot capture + auth, revocation (WebSocket close 4403),
session persistence across restarts, port fallback, sharing on/off, and
static/PWA serving. To re-run against a running server:

```powershell
python <path-to>\test_remoteview.py
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Phone can't open the URL | Same Wi-Fi? Windows Firewall rule for the port? Network profile set to Private? |
| "Pairing code has expired" | Press **New pairing code** on the dashboard and re-scan. |
| "Invalid pairing code" | Codes are one-time and 6 digits; type the current code from the dashboard. |
| Live view stuck on "Connecting…" | Laptop server stopped, or the phone lost Wi-Fi. The app reconnects automatically; use **Reconnect** to force it. |
| "Screen sharing was stopped on the laptop" | Someone pressed Stop sharing / Disconnect on the laptop. Re-enable sharing there, then Reconnect. |
| Low FPS on the phone | Lower JPEG quality in Settings, or close other viewers; each viewer adds encode cost on the laptop. |
| Port already in use | The app auto-falls back to the next port — check the printed banner, or set `RV_PORT`. |
| Capture errors on multi-monitor | Change **Monitor** in dashboard settings (0 = full virtual screen, 1 = first monitor). |
| Screenshot button does nothing | Sharing is disabled on the laptop, or the session was revoked — check the dashboard. |

## Security considerations

- Intended for viewing **your own** laptop from **your own** phone.
- HTTP (not HTTPS) on the LAN: the pairing token is the security boundary —
  anyone on the network without the token sees no data. For use on untrusted
  networks, put the server behind a reverse proxy with TLS or a VPN such as
  Tailscale/WireGuard.
- Pairing codes are single-use and short-lived; sessions expire after
  `RV_SESSION_TTL_DAYS` (30) days of inactivity.
- The on-screen indicator and instant disconnect exist so the laptop user is
  always in control. Do not remove or hide them.
- No stealth features, no keylogging, no background collection — screenshots
  only happen when the phone user taps the button.

## Production build

- Mobile: `cd mobile && npm run build` → static assets in `mobile/dist`
  (served by the laptop). Install as an app from Chrome/Android
  ("Add to Home screen") for the standalone PWA experience.
- Laptop: create a venv, install `requirements.txt`, and run
  `python main.py`. For auto-start, create a Task Scheduler task or a
  shortcut in `shell:startup` running:
  `pythonw.exe D:\path\to\laptop\main.py --setup-firewall`.

## Project structure

```
remoteview/
├── laptop/
│   ├── app/               # FastAPI server, state, overlay, admin dashboard
│   │   ├── static/        # admin.html (localhost-only dashboard)
│   │   ├── server.py      # routes + WebSocket streaming
│   │   ├── state.py       # sharing/clients state
│   │   ├── overlay.py     # always-on-top sharing indicator
│   │   └── config.py      # env-based configuration
│   ├── screen_capture/    # MSS capture + JPEG encoding
│   ├── networking/        # local IP detection, firewall helpers
│   ├── security/          # tokens, SQLite sessions/settings
│   ├── pairing/           # one-time expiring pairing codes
│   ├── screenshots/       # on-demand capture service
│   ├── main.py            # entry point
│   └── requirements.txt
├── mobile/
│   ├── src/
│   │   ├── pages/         # Home, Live, Screenshots, Settings
│   │   ├── components/    # ScreenCanvas, BottomNav, Toast, StatusPill
│   │   ├── services/      # api.js, stream.js (WS), db.js (IndexedDB)
│   │   ├── hooks/         # useZoom (pinch/pan)
│   │   └── utils/         # formatting, save/share helpers
│   ├── public/            # manifest, service worker, icons
│   └── package.json
├── README.md
└── .gitignore
```
