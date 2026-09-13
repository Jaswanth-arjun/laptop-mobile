"""Random token helpers."""
import secrets


def new_pairing_code(length: int = 6) -> str:
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(length))
