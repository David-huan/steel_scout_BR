import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(ROOT_DIR / ".env")

def _path(value: str, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


DATA_DIR = _path(os.getenv("DATA_DIR", ""), ROOT_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = _path(os.getenv("DATABASE_PATH", ""), DATA_DIR / "steel.db")
SEED_PATH = _path(
    os.getenv("SEED_PATH", ""),
    BACKEND_DIR / "app" / "data" / "seed_candidates.csv",
)
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

CRAWL_LIVE = os.getenv("CRAWL_LIVE", "true").lower() in {"1", "true", "yes", "on"}
CRAWL_MAX_PAGES = int(os.getenv("CRAWL_MAX_PAGES", "2"))
CRAWL_THREADS = int(os.getenv("CRAWL_THREADS", "6"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8"))
MAX_QUERIES = int(os.getenv("MAX_QUERIES", "40"))
MAX_SITES = int(os.getenv("MAX_SITES", "120"))
SERPER_MAX_QUERIES = int(os.getenv("SERPER_MAX_QUERIES", "6" if SERPER_API_KEY else "0"))

USER_AGENT = os.getenv(
    "USER_AGENT",
    "YIEH-CustomerResearchBot/1.0 (+https://www.yieh.com; research-only)",
)


def flags() -> dict:
    return {
        "serper": bool(SERPER_API_KEY),
        "places": bool(GOOGLE_MAPS_API_KEY),
        "llm": bool(OPENAI_API_KEY),
        "crawl_live": CRAWL_LIVE,
    }
