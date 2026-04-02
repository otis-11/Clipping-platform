import json
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Multi-account registry
# ---------------------------------------------------------------------------
ACCOUNTS_FILE = DATA_DIR / "accounts.json"


def load_accounts() -> list[dict]:
    """Load all account definitions from accounts.json."""
    if ACCOUNTS_FILE.exists():
        try:
            return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_accounts(accounts: list[dict]):
    """Persist account definitions to accounts.json."""
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")


def get_account(account_id: str) -> dict | None:
    """Return a single account dict by ID, or None."""
    for acct in load_accounts():
        if acct["id"] == account_id:
            return acct
    return None


def get_account_dirs(account_id: str) -> dict[str, Path]:
    """Return all data-directory paths scoped to one account."""
    base = DATA_DIR / account_id
    dirs = {
        "base": base,
        "videos": base / "videos",
        "clips": base / "clips",
        "transcripts": base / "transcripts",
        "queue": base / "queue",
        "posted": base / "posted",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def get_account_files(account_id: str) -> dict[str, Path]:
    """Return auxiliary file paths scoped to one account."""
    base = DATA_DIR / account_id
    base.mkdir(parents=True, exist_ok=True)
    return {
        "settings": base / "settings.json",
        "history": base / "post_history.json",
        "processed_videos": base / "processed_videos.txt",
    }


# ---------------------------------------------------------------------------
# One-time migration: move legacy flat data/ into data/kiriakou/
# ---------------------------------------------------------------------------
def _migrate_legacy_data():
    """If accounts.json doesn't exist yet, create the default Kiriakou account
    and move existing flat data/ contents into data/kiriakou/."""
    if ACCOUNTS_FILE.exists():
        return  # already migrated

    default_account = {
        "id": "kiriakou",
        "name": "Kiriakou Clipper",
        "source_channels": [
            ch.strip()
            for ch in os.getenv("SOURCE_CHANNELS", "@DeepFocuswithJohnKiriakou").split(",")
        ],
        "youtube_client_secret": "client_secret_kiriakou.json",
        "youtube_token": "youtube_token_kiriakou.json",
        "default_tags": "#JohnKiriakou #CIA #whistleblower #podcast #shorts #intelligence #politics",
        "clip_prompt_context": "John Kiriakou (former CIA officer and whistleblower)",
        "category_id": "25",
    }
    save_accounts([default_account])

    # Create account directories
    dirs = get_account_dirs("kiriakou")
    files = get_account_files("kiriakou")

    # Move legacy sub-directories into account folder
    for legacy_name, target in [
        ("queue", dirs["queue"]),
        ("clips", dirs["clips"]),
        ("posted", dirs["posted"]),
        ("transcripts", dirs["transcripts"]),
        ("videos", dirs["videos"]),
    ]:
        legacy = DATA_DIR / legacy_name
        if legacy.exists() and legacy != target and any(legacy.iterdir()):
            for item in legacy.iterdir():
                dest = target / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))

    # Move legacy files
    legacy_settings = DATA_DIR / "settings.json"
    if legacy_settings.exists():
        shutil.copy2(str(legacy_settings), str(files["settings"]))

    legacy_history = DATA_DIR / "post_history.json"
    if legacy_history.exists():
        shutil.copy2(str(legacy_history), str(files["history"]))

    legacy_processed = DATA_DIR / "processed_videos.txt"
    if legacy_processed.exists():
        shutil.copy2(str(legacy_processed), str(files["processed_videos"]))

    # Rename YouTube credential files
    old_secret = PROJECT_DIR / os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
    new_secret = PROJECT_DIR / "client_secret_kiriakou.json"
    if old_secret.exists() and not new_secret.exists() and old_secret.name != new_secret.name:
        shutil.copy2(str(old_secret), str(new_secret))

    old_token = PROJECT_DIR / "youtube_token.json"
    new_token = PROJECT_DIR / "youtube_token_kiriakou.json"
    if old_token.exists() and not new_token.exists() and old_token.name != new_token.name:
        shutil.copy2(str(old_token), str(new_token))


_migrate_legacy_data()

# ---------------------------------------------------------------------------
# Legacy globals (kept for backward compat during transition, but prefer
# per-account dirs/files in new code)
# ---------------------------------------------------------------------------
VIDEOS_DIR = DATA_DIR / "kiriakou" / "videos"
CLIPS_DIR = DATA_DIR / "kiriakou" / "clips"
TRANSCRIPTS_DIR = DATA_DIR / "kiriakou" / "transcripts"
QUEUE_DIR = DATA_DIR / "kiriakou" / "queue"
POSTED_DIR = DATA_DIR / "kiriakou" / "posted"
PROCESSED_VIDEOS_FILE = DATA_DIR / "kiriakou" / "processed_videos.txt"
SETTINGS_FILE = DATA_DIR / "kiriakou" / "settings.json"

for d in [VIDEOS_DIR, CLIPS_DIR, TRANSCRIPTS_DIR, QUEUE_DIR, POSTED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# OpenAI (shared across all accounts)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Dashboard
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "change-me-in-production")

# Require approval before posting (managed via dashboard)
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() == "true"

# YouTube Upload OAuth (legacy — new code uses per-account paths)
YOUTUBE_CLIENT_SECRET_FILE = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
YOUTUBE_TOKEN_FILE = PROJECT_DIR / "youtube_token.json"

# Source channels (legacy default)
SOURCE_CHANNELS = [
    ch.strip() for ch in os.getenv("SOURCE_CHANNELS", "@DeepFocuswithJohnKiriakou").split(",")
]

# Scheduling
CLIPS_PER_DAY = int(os.getenv("CLIPS_PER_DAY", "5"))
POST_TIMES = [t.strip() for t in os.getenv("POST_TIMES", "08:00,10:30,13:00,16:00,19:00").split(",")]

# Clip settings
MIN_CLIP_DURATION = int(os.getenv("MIN_CLIP_DURATION", "30"))
MAX_CLIP_DURATION = int(os.getenv("MAX_CLIP_DURATION", "90"))

# Whisper
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
