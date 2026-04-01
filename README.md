# Kiriakou Clipper — Automated YouTube Shorts Pipeline

Fully automated pipeline that monitors John Kiriakou's podcast channels, extracts the most viral-worthy moments, converts them to vertical Shorts with captions, and posts 5x/day to YouTube.

**Total cost: $0/month** (uses Gemini Flash free tier + local Whisper + FFmpeg)

## How It Works

```
New Video Detected → Download → Transcribe → AI Finds Best Moments → 
Cut & Reformat to 9:16 → Burn Captions → Queue → Auto-Post 5x/Day
```

## Prerequisites

1. **Python 3.10+** — [python.org](https://www.python.org/downloads/)
2. **FFmpeg** — [ffmpeg.org/download](https://ffmpeg.org/download.html)
   - Windows: `winget install ffmpeg` or download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
   - Make sure `ffmpeg` and `ffprobe` are on your PATH
3. **Google Gemini API Key** (free) — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
4. **YouTube Data API OAuth credentials** — see setup below

## Setup (5 minutes)

### Step 1: Install dependencies
```bash
cd windsurf-project-9
pip install -r requirements.txt
```

### Step 2: Configure environment
```bash
copy .env.example .env
```
Edit `.env` and add your Gemini API key.

### Step 3: Set up YouTube upload credentials
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable **YouTube Data API v3**
4. Go to **APIs & Services → Credentials**
5. Create **OAuth 2.0 Client ID** (type: Desktop App)
6. Download the JSON file and save it as `client_secret.json` in the project root

### Step 4: Authenticate with YouTube
```bash
python main.py --auth
```
This opens a browser window to authorize the app. You only need to do this once.

### Step 5: Test the pipeline
```bash
# Process new videos and generate clips
python main.py --process-now

# Check what's in the queue
python main.py --status

# Post a clip immediately
python main.py --post-now
```

### Step 6: Start the automation
```bash
python main.py
```
This starts the scheduler that:
- Checks for new videos daily at 6:00 AM
- Posts clips at: 8:00, 10:30, 13:00, 16:00, 19:00

## Configuration

Edit `.env` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `SOURCE_CHANNELS` | `@DeepFocuswithJohnKiriakou` | YouTube channels to monitor (comma-separated) |
| `CLIPS_PER_DAY` | `5` | Number of clips to post daily |
| `POST_TIMES` | `08:00,10:30,13:00,16:00,19:00` | When to post each clip |
| `MIN_CLIP_DURATION` | `30` | Minimum clip length (seconds) |
| `MAX_CLIP_DURATION` | `90` | Maximum clip length (seconds) |
| `WHISPER_MODEL` | `base` | Whisper model size (tiny/base/small/medium/large-v3) |

## Adding More Source Channels

To also clip John Kiriakou's guest appearances on other channels:
```
SOURCE_CHANNELS=@DeepFocuswithJohnKiriakou,@SomeOtherChannel,@AnotherPodcast
```

## Commands

| Command | Description |
|---------|-------------|
| `python main.py` | Start the scheduler (runs continuously) |
| `python main.py --process-now` | Process new videos immediately |
| `python main.py --post-now` | Post the next queued clip immediately |
| `python main.py --status` | Show queue and pipeline status |
| `python main.py --auth` | YouTube OAuth setup (first time only) |

## File Structure

```
├── main.py              # Entry point & scheduler
├── pipeline.py          # Orchestrates the full pipeline
├── downloader.py        # YouTube channel monitoring & video download
├── transcriber.py       # Local speech-to-text (faster-whisper)
├── clip_detector.py     # AI viral moment detection (Gemini Flash)
├── video_processor.py   # FFmpeg: cut, reformat 9:16, burn captions
├── uploader.py          # YouTube Data API upload
├── config.py            # Configuration loader
├── .env                 # Your API keys (not committed)
├── client_secret.json   # YouTube OAuth file (not committed)
├── data/
│   ├── videos/          # Downloaded source videos (auto-cleaned)
│   ├── transcripts/     # Saved transcripts
│   ├── clips/           # Processed clips
│   ├── queue/           # Clips waiting to be posted
│   └── posted/          # Successfully posted clips
└── logs/
    └── clipper.log      # Pipeline logs
```

## Running as a Background Service (Windows)

To keep the clipper running 24/7, use Windows Task Scheduler:

1. Open Task Scheduler
2. Create Basic Task → Name: "Kiriakou Clipper"
3. Trigger: "When the computer starts"
4. Action: Start a program
   - Program: `python`
   - Arguments: `main.py`
   - Start in: `C:\Users\czami\CascadeProjects\windsurf-project-9`
5. Check "Run whether user is logged on or not"

## Important Notes

- **Copyright**: Get explicit permission from John Kiriakou before launching. Many creators welcome clipping channels as free promotion. Reach out via his channel's contact info.
- **YouTube API Quota**: Default is 10,000 units/day. Each upload costs 1,600 units = max ~6 uploads/day. Request a quota increase if needed.
- **Account Warm-up**: New YouTube channels should start slow (1-2 posts/day) for the first 1-2 weeks before ramping to 5/day.
