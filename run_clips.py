"""
Re-process approved clips at 1.25x speed, then generate 4 new replacement clips.
Video: https://www.youtube.com/watch?v=TZqADzuu73g
"""
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

import config

# Source clips should be 24-31s so after 1.25x speedup they become ~19-25s
config.MIN_CLIP_DURATION = 24
config.MAX_CLIP_DURATION = 35
config.OPENAI_MODEL = "gpt-4o"

from config import get_account_dirs, get_account_files, get_account
from downloader import download_video
from transcriber import load_transcript
from clip_detector import detect_clips
from video_processor import process_clip
from pipeline import save_to_queue
from pathlib import Path

logger = logging.getLogger("run_clips")

VIDEO_ID = "TZqADzuu73g"
ACCOUNT_ID = "kiriakou"

acct = get_account(ACCOUNT_ID)
dirs = get_account_dirs(ACCOUNT_ID)
files = get_account_files(ACCOUNT_ID)

# Ensure video is available
video_path = download_video(
    f"https://www.youtube.com/watch?v={VIDEO_ID}", VIDEO_ID, videos_dir=dirs["videos"]
)
if not video_path:
    logger.error("Download failed!")
    sys.exit(1)

transcript = load_transcript(VIDEO_ID, transcripts_dir=dirs["transcripts"])
if not transcript:
    logger.error("No transcript found!")
    sys.exit(1)

# ── PHASE 1: Re-process approved clips at 1.25x speed ──────────────────────
logger.info("=== PHASE 1: Re-processing approved clips at 1.25x speed ===")
approved_clips = ["TZqADzuu73g_clip03", "TZqADzuu73g_clip05", "TZqADzuu73g_clip07"]

for stem in approved_clips:
    queue_file = dirs["queue"] / f"{stem}.json"
    clip_file = dirs["clips"] / f"{stem}.mp4"
    if not queue_file.exists():
        logger.warning(f"  Queue file missing: {queue_file.name}, skipping")
        continue

    meta = json.loads(queue_file.read_text(encoding="utf-8"))
    clip_info = {
        "start_time": meta["start_time"],
        "end_time": meta["end_time"],
        "title": meta["title"],
        "hook": meta.get("hook", ""),
    }

    logger.info(f"  Re-processing {stem} ({meta['title'][:50]})")
    result = process_clip(
        video_path=video_path,
        clip_info=clip_info,
        word_segments=transcript.get("word_segments", []),
        output_path=clip_file,
    )
    if result:
        logger.info(f"  ✓ {stem} re-processed at 1.25x")
    else:
        logger.error(f"  ✗ {stem} re-processing failed!")

# ── PHASE 2: Detect and process 4 new interesting clips ─────────────────────
logger.info("\n=== PHASE 2: Detecting 4 new interesting clips ===")

# Get timestamps of ALL existing clips to avoid overlapping
approved_ranges = []
for qf in sorted(dirs["queue"].glob("TZqADzuu73g*.json")):
    m = json.loads(qf.read_text(encoding="utf-8"))
    approved_ranges.append((m["start_time"], m["end_time"]))
logger.info(f"  Avoiding {len(approved_ranges)} existing clip ranges")

video_title = transcript.get("video_title", VIDEO_ID)
clips = detect_clips(
    transcript,
    video_title,
    num_clips=12,  # ask for more since some get rejected or overlap
    prompt_context=acct.get("clip_prompt_context",
                            "John Kiriakou (former CIA officer and whistleblower)"),
)
if not clips:
    logger.error("No clips detected!")
    sys.exit(1)

# Filter out clips that overlap with approved ones
def overlaps(c, ranges):
    for rs, re_ in ranges:
        if c["start_time"] < re_ and c["end_time"] > rs:
            return True
    return False

new_clips = [c for c in clips if not overlaps(c, approved_ranges)]
logger.info(f"Detected {len(clips)} total, {len(new_clips)} non-overlapping candidates")

queued = 0
clip_idx = 11  # continue numbering after clip10
for i, clip_info in enumerate(new_clips):
    if queued >= 1:
        break
    duration = clip_info["end_time"] - clip_info["start_time"]
    logger.info(f"\n--- New clip {clip_idx:02d} (candidate {i+1}/{len(new_clips)}) ---")
    logger.info(f"  Title: {clip_info['title']}")
    logger.info(f"  Time: {clip_info['start_time']:.1f}s - {clip_info['end_time']:.1f}s ({duration:.0f}s → {duration/1.25:.0f}s at 1.25x)")
    logger.info(f"  Hook: {clip_info.get('hook', '')}")
    logger.info(f"  Score: {clip_info.get('virality_score', '?')}/10")

    final_path = dirs["clips"] / f"{VIDEO_ID}_clip{clip_idx:02d}.mp4"
    result = process_clip(
        video_path=video_path,
        clip_info=clip_info,
        word_segments=transcript.get("word_segments", []),
        output_path=final_path,
    )
    if not result:
        logger.warning(f"  FAILED to process")
        continue

    save_to_queue(clip_info, final_path, queue_dir=dirs["queue"])
    queued += 1
    clip_idx += 1
    logger.info(f"  ✓ Queued: {final_path.name}")

logger.info(f"\n=== Done! Re-processed 3 approved + {queued} new clips ===")
logger.info(f"View at: http://localhost:5000/kiriakou/")
