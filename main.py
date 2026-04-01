"""
Main entry point. Runs the automated clipping pipeline on a schedule.

Usage:
    python main.py                  # Start the dashboard + scheduler
    python main.py --process-now    # Process new videos immediately
    python main.py --post-now       # Post the next queued clip immediately
    python main.py --status         # Show queue status
    python main.py --auth           # Authenticate with YouTube (first-time setup)
    python main.py --no-dashboard   # Run scheduler only (no web UI)
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

import config
from downloader import fetch_new_videos
from pipeline import process_video, get_queue, remove_from_queue
from uploader import upload_short, get_youtube_service

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "clipper.log"),
    ],
)
logger = logging.getLogger("main")


def job_process_new_videos():
    """Scheduled job: check for new videos and process them into clips."""
    logger.info("--- Checking for new videos ---")
    try:
        new_videos = fetch_new_videos(max_per_channel=3)
        total_queued = 0
        for video in new_videos[:2]:  # Process max 2 new videos per run
            queued = process_video(video)
            total_queued += queued
        logger.info(f"Processing complete. {total_queued} new clips queued.")
        queue = get_queue()
        logger.info(f"Total clips in queue: {len(queue)}")
    except Exception as e:
        logger.error(f"Processing job failed: {e}", exc_info=True)


def job_post_clip():
    """Scheduled job: post the next approved clip from the queue."""
    logger.info("--- Posting next clip ---")
    try:
        queue = get_queue()
        # Only post approved clips
        approved = [c for c in queue if c.get("approved", False)]
        if not approved:
            logger.info("No approved clips to post.")
            return

        clip = approved[0]
        clip_path = Path(clip["clip_path"])

        if not clip_path.exists():
            logger.warning(f"Clip file missing: {clip_path}, removing from queue")
            remove_from_queue(clip)
            return

        video_id = upload_short(
            video_path=clip_path,
            title=clip["title"],
            description=clip.get("description", ""),
        )

        if video_id:
            remove_from_queue(clip)
            remaining = len(get_queue())
            logger.info(f"Posted! Remaining in queue: {remaining}")
        else:
            logger.error("Upload failed, clip stays in queue for retry")

    except Exception as e:
        logger.error(f"Posting job failed: {e}", exc_info=True)


def show_status():
    """Print current queue status."""
    queue = get_queue()
    print(f"\n{'='*60}")
    print(f"  KIRIAKOU CLIPPER STATUS")
    print(f"{'='*60}")
    print(f"  Clips in queue: {len(queue)}")
    print(f"  Post times: {', '.join(config.POST_TIMES)}")
    print(f"  Clips per day: {config.CLIPS_PER_DAY}")
    print(f"  Source channels: {', '.join(config.SOURCE_CHANNELS)}")
    print(f"{'='*60}")

    if queue:
        print(f"\n  Upcoming clips (by virality score):")
        for i, clip in enumerate(queue[:10]):
            score = clip.get("virality_score", "?")
            title = clip.get("title", "Untitled")[:50]
            print(f"    {i+1}. [{score}/10] {title}")

    posted_count = len(list(config.POSTED_DIR.glob("*.mp4")))
    print(f"\n  Total clips posted: {posted_count}")
    print()


def authenticate_youtube():
    """Run YouTube OAuth flow for first-time setup."""
    print("Authenticating with YouTube...")
    try:
        service = get_youtube_service()
        # Test the connection
        response = service.channels().list(part="snippet", mine=True).execute()
        if response.get("items"):
            channel = response["items"][0]["snippet"]["title"]
            print(f"Authenticated as: {channel}")
        else:
            print("Authenticated but no channel found. Create a YouTube channel first.")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)


def start_scheduler():
    """Start the automated scheduler."""
    scheduler = BlockingScheduler()

    # Schedule video processing once daily at 6 AM
    scheduler.add_job(
        job_process_new_videos,
        "cron",
        hour=6,
        minute=0,
        id="process_videos",
        name="Process new videos",
    )

    # Schedule clip posting at configured times
    for i, time_str in enumerate(config.POST_TIMES[:config.CLIPS_PER_DAY]):
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_job(
            job_post_clip,
            "cron",
            hour=hour,
            minute=minute,
            id=f"post_clip_{i}",
            name=f"Post clip at {time_str}",
        )

    print(f"\n{'='*60}")
    print(f"  KIRIAKOU CLIPPER - SCHEDULER STARTED")
    print(f"{'='*60}")
    print(f"  Processing runs daily at: 06:00")
    print(f"  Posting times: {', '.join(config.POST_TIMES[:config.CLIPS_PER_DAY])}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


def main():
    parser = argparse.ArgumentParser(description="Automated YouTube Clipping Pipeline")
    parser.add_argument("--process-now", action="store_true", help="Process new videos immediately")
    parser.add_argument("--post-now", action="store_true", help="Post next queued clip immediately")
    parser.add_argument("--status", action="store_true", help="Show queue status")
    parser.add_argument("--auth", action="store_true", help="Authenticate with YouTube")
    parser.add_argument("--no-dashboard", action="store_true", help="Run scheduler only, no web UI")

    args = parser.parse_args()

    if args.auth:
        authenticate_youtube()
    elif args.process_now:
        job_process_new_videos()
    elif args.post_now:
        job_post_clip()
    elif args.status:
        show_status()
    elif args.no_dashboard:
        show_status()
        start_scheduler()
    else:
        # Default: start the dashboard (which includes the scheduler)
        from app import app, scheduler as dash_scheduler, _rebuild_scheduler
        show_status()
        _rebuild_scheduler()
        dash_scheduler.start()
        logger.info(f"Dashboard: http://localhost:{config.DASHBOARD_PORT}")
        app.run(host="0.0.0.0", port=config.DASHBOARD_PORT, debug=False)


if __name__ == "__main__":
    main()
