"""
Core pipeline: processes a single video end-to-end.
Downloads -> Transcribes -> Detects clips -> Processes video -> Queues for upload.
"""
import json
import logging
import shutil
from pathlib import Path

import config
from downloader import download_video, mark_processed
from transcriber import transcribe_video, load_transcript
from clip_detector import detect_clips
from video_processor import process_clip, add_hook_overlay

logger = logging.getLogger(__name__)


def save_to_queue(clip_info: dict, clip_path: Path):
    """Save a processed clip to the upload queue."""
    queue_item = {
        "clip_path": str(clip_path),
        "title": clip_info.get("title", ""),
        "hook": clip_info.get("hook", ""),
        "description": clip_info.get("description", ""),
        "virality_score": clip_info.get("virality_score", 0),
        "source_video_title": clip_info.get("source_video_title", ""),
        "start_time": clip_info.get("start_time", 0),
        "end_time": clip_info.get("end_time", 0),
        "approved": not config.REQUIRE_APPROVAL,
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    queue_file = config.QUEUE_DIR / f"{clip_path.stem}.json"
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue_item, f, indent=2)
    logger.info(f"Queued clip: {clip_info.get('title', clip_path.stem)}")


def get_queue() -> list[dict]:
    """Get all clips waiting in the upload queue, sorted by virality score."""
    queue = []
    for f in config.QUEUE_DIR.glob("*.json"):
        with open(f, "r", encoding="utf-8") as fh:
            item = json.load(fh)
            item["_queue_file"] = str(f)
            queue.append(item)
    queue.sort(key=lambda x: x.get("virality_score", 0), reverse=True)
    return queue


def remove_from_queue(queue_item: dict):
    """Remove a clip from the queue after posting."""
    queue_file = Path(queue_item.get("_queue_file", ""))
    if queue_file.exists():
        queue_file.unlink()
    # Move clip to posted directory
    clip_path = Path(queue_item.get("clip_path", ""))
    if clip_path.exists():
        dest = config.POSTED_DIR / clip_path.name
        shutil.move(str(clip_path), str(dest))


def process_video(video_info: dict) -> int:
    """
    Full pipeline for one video. Returns number of clips queued.
    """
    video_id = video_info["id"]
    video_url = video_info.get("url", f"https://www.youtube.com/watch?v={video_id}")
    video_title = video_info.get("title", video_id)

    logger.info(f"=== Processing: {video_title} ===")

    # Step 1: Download
    video_path = download_video(video_url, video_id)
    if not video_path:
        logger.error(f"Download failed for {video_id}")
        return 0

    # Step 2: Transcribe
    transcript = load_transcript(video_id)
    if not transcript:
        transcript = transcribe_video(video_path)

    if not transcript or not transcript.get("segments"):
        logger.error(f"Transcription failed for {video_id}")
        mark_processed(video_id)
        return 0

    # Step 3: Detect clips
    clips = detect_clips(transcript, video_title, num_clips=8)
    if not clips:
        logger.warning(f"No clips detected for {video_id}")
        mark_processed(video_id)
        return 0

    # Step 4: Process each clip
    queued = 0
    for i, clip_info in enumerate(clips):
        clip_filename = f"{video_id}_clip{i:02d}.mp4"
        raw_clip_path = config.CLIPS_DIR / f"raw_{clip_filename}"
        final_clip_path = config.CLIPS_DIR / clip_filename

        # Cut and reformat the clip
        result = process_clip(
            video_path=video_path,
            clip_info=clip_info,
            word_segments=transcript.get("word_segments", []),
            output_path=raw_clip_path,
        )
        if not result:
            continue

        # Add hook text overlay
        hook_text = clip_info.get("hook", "")
        if hook_text:
            add_hook_overlay(raw_clip_path, hook_text, final_clip_path)
            if raw_clip_path.exists() and final_clip_path.exists():
                raw_clip_path.unlink()
        else:
            shutil.move(str(raw_clip_path), str(final_clip_path))

        # Queue for upload
        save_to_queue(clip_info, final_clip_path)
        queued += 1

    # Mark video as processed
    mark_processed(video_id)

    # Clean up downloaded video to save disk space
    if video_path.exists():
        video_path.unlink()
        logger.info(f"Cleaned up source video: {video_path.name}")

    logger.info(f"=== Queued {queued} clips from: {video_title} ===")
    return queued
