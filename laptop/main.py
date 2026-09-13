"""RemoteView laptop application entry point.

Usage:
    python main.py                 # start server + dashboard + overlay
    python main.py --setup-firewall
    python main.py --no-overlay
"""
import argparse
import logging
import socket
import sys
import threading
import webbrowser

import uvicorn

from app import config
from app.overlay import ShareOverlay
from app.server import RemoteViewServer
from networking.address import get_device_name, get_local_ip
from networking.firewall import ensure_rule
from security import db


def find_free_port(start: int, span: int) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((config.HOST, port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port found in range {start}-{start + span - 1}. Close the program using port {start} or set RV_PORT.")


def main() -> int:
    parser = argparse.ArgumentParser(description="RemoteView laptop server")
    parser.add_argument("--setup-firewall", action="store_true", help="Add Windows Firewall rule (requires admin)")
    parser.add_argument("--no-overlay", action="store_true", help="Disable the on-screen sharing indicator")
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()

    # load .env from the laptop directory if present (never overrides real env vars)
    try:
        from dotenv import load_dotenv

        load_dotenv(config.PROJECT_DIR / ".env")
    except ImportError:
        pass

    # re-read config values that may come from .env
    import importlib

    importlib.reload(config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    log = logging.getLogger("remoteview")

    db.init()
    port = find_free_port(args.port, config.PORT_RANGE)

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
    print("  Keep this window open. Press Ctrl+C to stop.", flush=True)
    print("", flush=True)

    server.loop = None  # set once the event loop is running (see lifespan)

    app = server.app

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        import asyncio

        server.loop = asyncio.get_running_loop()
        server.capture.start()
        yield
        server.capture.stop()

    app.router.lifespan_context = lifespan

    config.PORT = port

    # open dashboard in the default browser
    threading.Timer(1.0, lambda: webbrowser.open(admin_url)).start()

    uvicorn.run(app, host=config.HOST, port=port, log_level="warning", ws_ping_interval=20, ws_ping_timeout=20)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nRemoteView stopped.")
        sys.exit(0)
