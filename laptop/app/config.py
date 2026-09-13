"""Configuration loaded from environment variables with sane defaults."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = Path(os.environ.get("RV_DATA_DIR", PROJECT_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "remoteview.db"

HOST = os.environ.get("RV_HOST", "0.0.0.0")
PORT = int(os.environ.get("RV_PORT", "8756"))
PORT_RANGE = 10  # if the port is busy, try the next N ports

PAIRING_CODE_TTL = int(os.environ.get("RV_PAIRING_TTL", "300"))  # seconds
SESSION_TTL_DAYS = int(os.environ.get("RV_SESSION_TTL_DAYS", "30"))

DEFAULT_FPS = int(os.environ.get("RV_FPS", "12"))
DEFAULT_QUALITY = int(os.environ.get("RV_QUALITY", "60"))  # JPEG quality 1-95
DEFAULT_SCALE = float(os.environ.get("RV_SCALE", "1.0"))  # 0.1 - 1.0

MAX_FPS = 30
MAX_QUALITY = 95
MAX_PIXELS = 4_000_000  # safety cap for streamed frame size

# Gemini AI — up to 3 API keys from different Google accounts.
# Key 1 should be your PRO account (highest RPM), keys 2-3 normal accounts.
# The key pool rotates round-robin and auto-skips rate-limited keys.
GEMINI_API_KEY_1 = os.environ.get("GEMINI_API_KEY_1", "")
GEMINI_API_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "")
GEMINI_API_KEY_3 = os.environ.get("GEMINI_API_KEY_3", "")
GEMINI_API_KEYS = [k for k in [GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3] if k]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)
GEMINI_COOLDOWN = int(os.environ.get("GEMINI_COOLDOWN", "60"))  # seconds per-key cooldown on 429
AI_CHAT_MAX_IMAGES = int(os.environ.get("RV_AI_MAX_IMAGES", "30"))
