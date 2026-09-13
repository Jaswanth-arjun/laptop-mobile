"""Windows firewall helpers: detect and (optionally) create an inbound rule.

Creating a firewall rule requires administrator rights. The app never fails
because of this - it reports the problem and prints the exact command the
user can run manually.
"""
import subprocess

RULE_NAME = "RemoteView Server"


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def rule_exists(port: int) -> bool:
    ok, out = _run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"])
    if not ok:
        return False
    return f"LocalPort:          {port}" in out or str(port) in out


def add_rule(port: int) -> tuple[bool, str]:
    ok, out = _run(
        [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_NAME}",
            "dir=in", "action=allow",
            "protocol=TCP", f"localport={port}",
            "profile=private,domain",
            "program=C:\\Windows\\System32\\python.exe",
        ]
    )
    # re-run without the program restriction in case python lives elsewhere
    if not ok:
        ok, out = _run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={RULE_NAME} {port}",
                "dir=in", "action=allow",
                "protocol=TCP", f"localport={port}",
                "profile=private,domain",
            ]
        )
    return ok, out


def ensure_rule(port: int, auto: bool = False) -> str | None:
    """Return a human readable message if the user should act, else None."""
    if rule_exists(port):
        return None
    if auto:
        ok, out = add_rule(port)
        if ok:
            return None
        return (
            "Could not add a Windows Firewall rule automatically. "
            f"Run this in an Administrator terminal:\n"
            f'  netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in '
            f"action=allow protocol=TCP localport={port} profile=private,domain\n"
            f"Details: {out}"
        )
    return (
        "If your phone cannot connect, allow Python through the Windows "
        f"Firewall for TCP port {port} (Private networks), or run:\n"
        f'  netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in '
        f"action=allow protocol=TCP localport={port} profile=private,domain"
    )
