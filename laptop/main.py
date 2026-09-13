"""RemoteView laptop application entry point.

Usage:
    python main.py                 # local mode (same Wi-Fi)
    python main.py --relay         # cloud relay mode (any network)
    python main.py --setup-firewall
    python main.py --no-overlay
"""
import argparse
import asyncio
import logging
import os
import socket
import sys
import threading
import webbrowser

# Fix PyInstaller --windowed mode where sys.stdout / sys.stderr are None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import uvicorn

from app import config
from app.overlay import ShareOverlay
from app.server import RemoteViewServer
from networking.address import get_device_name, get_local_ip
from networking.firewall import ensure_rule
from security import db


def find_free_port(start: int, span: int = 500) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((config.HOST, port))
                return port
            except OSError:
                continue
    # Fallback: let OS assign an available free port automatically
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((config.HOST, 0))
        return s.getsockname()[1]


def open_app_window(url: str):
    """Launch dashboard as a standalone desktop app window (frameless app mode)."""
    import shutil
    import subprocess

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"),
    ]
    for ep in edge_paths:
        if ep and os.path.exists(ep):
            try:
                subprocess.Popen([ep, f"--app={url}", "--window-size=1220,820"])
                return
            except Exception:
                pass

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome"),
    ]
    for cp in chrome_paths:
        if cp and os.path.exists(cp):
            try:
                subprocess.Popen([cp, f"--app={url}", "--window-size=1220,820"])
                return
            except Exception:
                pass

    webbrowser.open(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="RemoteView laptop server")
    parser.add_argument("--setup-firewall", action="store_true", help="Add Windows Firewall rule (requires admin)")
    parser.add_argument("--no-overlay", action="store_true", help="Disable the on-screen sharing indicator")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-relay", action="store_true", help="Disable cloud relay mode")
    parser.add_argument("--relay-url", type=str, default=None, help="Custom relay server URL")
    args = parser.parse_args()
    args.relay = not args.no_relay

    # load .env from the laptop directory if present
    try:
        from dotenv import load_dotenv

        load_dotenv(config.PROJECT_DIR / ".env")
    except ImportError:
        pass

    import importlib
    importlib.reload(config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    log = logging.getLogger("remoteview")

    db.init()
    port = find_free_port(args.port, 500)

    firewall_msg = ensure_rule(port, auto=args.setup_firewall)

    server = RemoteViewServer()
    server.port = port
    server.local_ip = get_local_ip()

    # restore sharing preference
    if bool(db.get_setting("sharing", False)):
        server.apply_sharing(True)

    # on-screen indicator
    overlay = None
    if not args.no_overlay:
        overlay = ShareOverlay(on_disconnect=server.disconnect_all_sync)
        server.overlay = overlay

    if server.state.sharing and overlay is not None:
        overlay.start()
        overlay.update("No device connected")

    url = f"http://{server.local_ip}:{port}"
    admin_url = f"http://127.0.0.1:{port}/admin"
    relay_url = args.relay_url or config.RELAY_URL

    print("", flush=True)
    print("=" * 62, flush=True)
    print("  RemoteView is running", flush=True)
    print("=" * 62, flush=True)
    print(f"  Dashboard (this laptop) : {admin_url}", flush=True)
    print(f"  Mobile URL (same Wi-Fi) : {url}", flush=True)
    print(f"  Device name             : {get_device_name()}", flush=True)
    print(f"  Local IP                : {server.local_ip}", flush=True)
    print(f"  Port                    : {port}", flush=True)
    if firewall_msg:
        print("", flush=True)
        print("  Firewall notice:", flush=True)
        for line in firewall_msg.splitlines():
            print(f"    {line}", flush=True)
    print("=" * 62, flush=True)

    server.loop = None
    app = server.app

    relay_client = None
    if args.relay:
        from app.relay_client import RelayClient
        relay_client = RelayClient(
            relay_url=relay_url,
            capture=server.capture,
            key_pool=server.key_pool,
            laptop_name=get_device_name(),
        )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        server.loop = asyncio.get_running_loop()
        server.capture.start()

        relay_task = None
        if relay_client:
            try:
                code = await relay_client.connect()
                print("", flush=True)
                print("  " + "★" * 58, flush=True)
                print("  ★ CLOUD RELAY ACTIVE — WORKS ACROSS ANY NETWORK!", flush=True)
                print(f"  ★ ROOM CODE: {code}", flush=True)
                print(f"  ★ Relay URL: {relay_url}", flush=True)
                print("  " + "★" * 58, flush=True)
                print("", flush=True)
                relay_task = asyncio.create_task(relay_client.run())
            except Exception as e:
                log.error("Failed to connect to relay: %s", e)

        yield

        if relay_client:
            await relay_client.close()
        if relay_task:
            relay_task.cancel()
        server.capture.stop()

    app.router.lifespan_context = lifespan
    config.PORT = port

    # open dashboard in dedicated app window mode
    threading.Timer(1.2, lambda: open_app_window(admin_url)).start()

    print("  Keep this window open. Press Ctrl+C to stop.", flush=True)
    print("", flush=True)

    uvicorn.run(app, host=config.HOST, port=port, log_config=None, ws_ping_interval=20, ws_ping_timeout=20)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nRemoteView stopped.")
        sys.exit(0)
