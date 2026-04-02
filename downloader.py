"""
Downloads new videos from monitored YouTube channels using yt-dlp.
Tracks which videos have already been processed to avoid duplicates.
"""
import json
import logging
from pathlib import Path

import shutil

import yt_dlp

import config

logger = logging.getLogger(__name__)


def _get_ffmpeg_location() -> str | None:
    """Find ffmpeg for yt-dlp. Returns path to ffmpeg executable or its parent dir."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return str(Path(ffmpeg).parent)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        # yt-dlp expects either a dir with 'ffmpeg.exe' or the exe path itself
        return exe
    except ImportError:
        return None


def get_processed_videos(processed_file: Path | None = None) -> set:
    """Load the set of already-processed video IDs."""
    pf = processed_file or config.PROCESSED_VIDEOS_FILE
    if pf.exists():
        return set(pf.read_text().strip().splitlines())
    return set()


def mark_processed(video_id: str, processed_file: Path | None = None):
    """Mark a video ID as processed."""
    pf = processed_file or config.PROCESSED_VIDEOS_FILE
    with open(pf, "a") as f:
        f.write(video_id + "\n")


def get_channel_videos(channel_url: str, max_videos: int = 10) -> list[dict]:
    """Fetch recent video metadata from a YouTube channel."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": max_videos,
        "ignoreerrors": True,
    }

    # Normalize channel URL
    if not channel_url.startswith("http"):
        channel_url = f"https://www.youtube.com/{channel_url}/videos"
    elif "/videos" not in channel_url:
        channel_url = channel_url.rstrip("/") + "/videos"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if not info or "entries" not in info:
                return []
            videos = []
            for entry in info["entries"]:
                if entry:
                    videos.append({
                        "id": entry.get("id", ""),
                        "title": entry.get("title", ""),
                        "url": entry.get("url", f"https://www.youtube.com/watch?v={entry.get('id', '')}"),
                        "duration": entry.get("duration", 0),
                    })
            return videos
    except Exception as e:
        logger.error(f"Error fetching channel videos: {e}")
        return []


def download_video(video_url: str, video_id: str, videos_dir: Path | None = None) -> Path | None:
    """Download a video and return the path to the downloaded file."""
    vdir = videos_dir or config.VIDEOS_DIR
    output_path = vdir / f"{video_id}.%(ext)s"

    ffmpeg_loc = _get_ffmpeg_location()
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "outtmpl": str(output_path),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    if ffmpeg_loc:
        ydl_opts["ffmpeg_location"] = ffmpeg_loc

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        # Find the downloaded file
        for f in vdir.glob(f"{video_id}.*"):
            if f.suffix in (".mp4", ".mkv", ".webm"):
                logger.info(f"Downloaded: {f}")
                return f
        return None
    except Exception as e:
        logger.error(f"Error downloading {video_url}: {e}")
        return None


def fetch_new_videos(max_per_channel: int = 5,
                     source_channels: list[str] | None = None,
                     processed_file: Path | None = None) -> list[dict]:
    """
    Check all source channels for new (unprocessed) videos.
    Returns list of dicts with video info.
    """
    processed = get_processed_videos(processed_file)
    new_videos = []
    channels = source_channels or config.SOURCE_CHANNELS

    for channel in channels:
        logger.info(f"Checking channel: {channel}")
        videos = get_channel_videos(channel, max_videos=max_per_channel)
        for v in videos:
            if v["id"] and v["id"] not in processed:
                # Skip very short videos (likely already shorts)
                if v.get("duration", 0) and v["duration"] < 120:
                    continue
                new_videos.append(v)

    logger.info(f"Found {len(new_videos)} new videos to process")
    return new_videos
