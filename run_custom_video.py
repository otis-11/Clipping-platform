"""
One-off script: process a specific YouTube video into clips for the kiriakou account.
Usage: python run_custom_video.py
"""
import logging
import yt_dlp
import config
from pipeline import process_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

VIDEO_URL = "https://www.youtube.com/watch?v=TZqADzuu73g"
VIDEO_ID = "TZqADzuu73g"
ACCOUNT_ID = "kiriakou"
NUM_CLIPS = 10

# Fetch video title
print("Fetching video title...")
with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
    info = ydl.extract_info(VIDEO_URL, download=False)
    video_title = info.get("title", VIDEO_ID)
print(f"Video: {video_title}")

acct = config.get_account(ACCOUNT_ID)
dirs = config.get_account_dirs(ACCOUNT_ID)
files = config.get_account_files(ACCOUNT_ID)

video_info = {
    "id": VIDEO_ID,
    "url": VIDEO_URL,
    "title": video_title,
}

count = process_video(
    video_info,
    account_dirs=dirs,
    account_files=files,
    prompt_context=acct.get("clip_prompt_context", "John Kiriakou (former CIA officer and whistleblower)"),
    num_clips=NUM_CLIPS,
)
print(f"\nDone! Queued {count} clips.")
