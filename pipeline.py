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


def save_to_queue(clip_info: dict, clip_path: Path, queue_dir: Path | None = None):
    """Save a processed clip to the upload queue."""
    qdir = queue_dir or config.QUEUE_DIR
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
    queue_file = qdir / f"{clip_path.stem}.json"
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue_item, f, indent=2)
    logger.info(f"Queued clip: {clip_info.get('title', clip_path.stem)}")


def get_queue(queue_dir: Path | None = None) -> list[dict]:
    """Get all clips waiting in the upload queue, sorted by virality score."""
    qdir = queue_dir or config.QUEUE_DIR
    queue = []
    for f in qdir.glob("*.json"):
        with open(f, "r", encoding="utf-8") as fh:
            item = json.load(fh)
            item["_queue_file"] = str(f)
            queue.append(item)
    queue.sort(key=lambda x: x.get("virality_score", 0), reverse=True)
    return queue


def remove_from_queue(queue_item: dict, posted_dir: Path | None = None):
    """Remove a clip from the queue after posting."""
    pdir = posted_dir or config.POSTED_DIR
    queue_file = Path(queue_item.get("_queue_file", ""))
    if queue_file.exists():
        queue_file.unlink()
    # Move clip to posted directory
    clip_path = Path(queue_item.get("clip_path", ""))
    if clip_path.exists():
        dest = pdir / clip_path.name
        shutil.move(str(clip_path), str(dest))


def process_video(video_info: dict, account_dirs: dict | None = None,
                  account_files: dict | None = None,
                  prompt_context: str = "John Kiriakou (former CIA officer and whistleblower)",
                  num_clips: int = 8) -> int:
    """
    Full pipeline for one video. Returns number of clips queued.

    account_dirs: dict with keys videos, clips, transcripts, queue, posted
    account_files: dict with key processed_videos
    """
    video_id = video_info["id"]
    video_url = video_info.get("url", f"https://www.youtube.com/watch?v={video_id}")
    video_title = video_info.get("title", video_id)

    # Resolve account-scoped directories
    videos_dir = account_dirs["videos"] if account_dirs else config.VIDEOS_DIR
    clips_dir = account_dirs["clips"] if account_dirs else config.CLIPS_DIR
    transcripts_dir = account_dirs["transcripts"] if account_dirs else config.TRANSCRIPTS_DIR
    queue_dir = account_dirs["queue"] if account_dirs else config.QUEUE_DIR
    processed_file = account_files["processed_videos"] if account_files else config.PROCESSED_VIDEOS_FILE

    logger.info(f"=== Processing: {video_title} ===")

    # Step 1: Download
    video_path = download_video(video_url, video_id, videos_dir=videos_dir)
    if not video_path:
        logger.error(f"Download failed for {video_id}")
        return 0

    # Step 2: Transcribe
    transcript = load_transcript(video_id, transcripts_dir=transcripts_dir)
    if not transcript:
        transcript = transcribe_video(video_path, transcripts_dir=transcripts_dir)

    if not transcript or not transcript.get("segments"):
        logger.error(f"Transcription failed for {video_id}")
        mark_processed(video_id, processed_file=processed_file)
        return 0

    # Step 3: Detect clips
    clips = detect_clips(transcript, video_title, num_clips=num_clips, prompt_context=prompt_context)
    if not clips:
        logger.warning(f"No clips detected for {video_id}")
        mark_processed(video_id, processed_file=processed_file)
        return 0

    # Step 4: Process each clip
    queued = 0
    for i, clip_info in enumerate(clips):
        clip_filename = f"{video_id}_clip{i:02d}.mp4"
        final_clip_path = clips_dir / clip_filename

        # Cut and reformat the clip (no hook overlay)
        result = process_clip(
            video_path=video_path,
            clip_info=clip_info,
            word_segments=transcript.get("word_segments", []),
            output_path=final_clip_path,
        )
        if not result:
            continue

        # Queue for upload
        save_to_queue(clip_info, final_clip_path, queue_dir=queue_dir)
        queued += 1

    # Mark video as processed
    mark_processed(video_id, processed_file=processed_file)

    # Clean up downloaded video to save disk space
    if video_path.exists():
        video_path.unlink()
        logger.info(f"Cleaned up source video: {video_path.name}")

    logger.info(f"=== Queued {queued} clips from: {video_title} ===")
    return queued
