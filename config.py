import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
VIDEOS_DIR = DATA_DIR / "videos"
CLIPS_DIR = DATA_DIR / "clips"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
QUEUE_DIR = DATA_DIR / "queue"
POSTED_DIR = DATA_DIR / "posted"
LOG_DIR = PROJECT_DIR / "logs"

for d in [DATA_DIR, VIDEOS_DIR, CLIPS_DIR, TRANSCRIPTS_DIR, QUEUE_DIR, POSTED_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Track which videos have already been processed
PROCESSED_VIDEOS_FILE = DATA_DIR / "processed_videos.txt"

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Dashboard
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "change-me-in-production")

# Require approval before posting (managed via dashboard)
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() == "true"

# Settings file (runtime-editable from dashboard)
SETTINGS_FILE = DATA_DIR / "settings.json"

# YouTube Upload OAuth
YOUTUBE_CLIENT_SECRET_FILE = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
YOUTUBE_TOKEN_FILE = PROJECT_DIR / "youtube_token.json"

# Source channels
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
