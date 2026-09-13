"""Local network address detection."""
import socket


def get_local_ip() -> str:
    """Best-effort detection of the LAN IP (never opens a real connection)."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    for ip in ips:
        if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
            return ip
    return ips[0] if ips else "127.0.0.1"


def get_device_name() -> str:
    try:
        return socket.gethostname() or "Laptop"
    except Exception:
        return "Laptop"
