"""
Uses FFmpeg to cut clips, convert to 9:16 vertical format,
and burn in animated captions. No external paid services needed.
"""
import json
import logging
import subprocess
import shutil
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _get_ffmpeg() -> str:
    """Find ffmpeg binary. Falls back to imageio-ffmpeg bundled binary."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError("ffmpeg not found. Install it or run: pip install imageio-ffmpeg")


def _get_ffprobe() -> str:
    """Find ffprobe binary. Falls back to using ffmpeg -i for probing."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    # imageio-ffmpeg doesn't bundle ffprobe, so we use ffmpeg -i as a fallback
    return None


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Get video width and height. Works with ffprobe or falls back to ffmpeg -i."""
    import re as _re

    ffprobe = _get_ffprobe()
    if ffprobe:
        cmd = [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        stream = info["streams"][0]
        return int(stream["width"]), int(stream["height"])

    # Fallback: parse ffmpeg -i stderr for resolution
    ffmpeg = _get_ffmpeg()
    cmd = [ffmpeg, "-i", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Look for pattern like "1920x1080" or "1280x720" in stderr
    match = _re.search(r'(\d{3,5})x(\d{3,5})', result.stderr)
    if match:
        return int(match.group(1)), int(match.group(2))
    # Default to 1920x1080 if detection fails
    logger.warning("Could not detect video dimensions, defaulting to 1920x1080")
    return 1920, 1080


def generate_ass_subtitles(word_segments: list[dict], clip_start: float, clip_end: float, output_path: Path):
    """
    Generate ASS subtitle file with word-by-word highlighting.
    Uses a CapCut-style look: big white text with current word highlighted in yellow.
    """
    # Filter words that fall within our clip
    clip_words = [
        w for w in word_segments
        if w["start"] >= clip_start and w["end"] <= clip_end
    ]

    if not clip_words:
        return None

    # ASS header with styling
    ass_content = """[Script Info]
Title: Clip Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,40,40,200,1
Style: Highlight,Arial Black,72,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,40,40,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Group words into lines of ~4-6 words
    lines = []
    current_line = []
    for word in clip_words:
        current_line.append(word)
        if len(current_line) >= 5 or word["word"].endswith((".", "!", "?", ",")):
            lines.append(current_line)
            current_line = []
    if current_line:
        lines.append(current_line)

    for line_words in lines:
        if not line_words:
            continue
        line_start = line_words[0]["start"] - clip_start
        line_end = line_words[-1]["end"] - clip_start

        # Build the line text with override tags for word-by-word highlight
        for i, word in enumerate(line_words):
            word_start = word["start"] - clip_start
            word_end = word["end"] - clip_start

            # Build text: all words, with current word highlighted
            parts = []
            for j, w in enumerate(line_words):
                if j == i:
                    parts.append(r"{\c&H00FFFF&}" + w["word"] + r"{\c&HFFFFFF&}")
                else:
                    parts.append(w["word"])
            text = " ".join(parts)

            start_ts = _seconds_to_ass_time(word_start)
            end_ts = _seconds_to_ass_time(word_end)
            ass_content += f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}\n"

    output_path.write_text(ass_content, encoding="utf-8")
    logger.info(f"Generated subtitles: {output_path}")
    return output_path


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.CC"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def process_clip(
    video_path: Path,
    clip_info: dict,
    word_segments: list[dict],
    output_path: Path,
) -> Path | None:
    """
    Full clip processing pipeline:
    1. Cut the clip from the source video
    2. Convert to 9:16 vertical (center-crop for talking head content)
    3. Burn in captions
    """
    ffmpeg = _get_ffmpeg()
    start = clip_info["start_time"]
    end = clip_info["end_time"]
    duration = end - start

    # Step 1: Generate subtitle file
    subs_path = output_path.with_suffix(".ass")
    generate_ass_subtitles(word_segments, start, end, subs_path)

    # Step 2: Build FFmpeg command
    # For podcast content (usually 16:9 talking heads), center-crop to 9:16
    # This focuses on the center of frame where speakers typically are
    width, height = get_video_dimensions(video_path)

    # Calculate crop dimensions for 9:16 from 16:9
    target_w = 1080
    target_h = 1920
    # Scale to match height first, then crop width
    scale_factor = target_h / height
    scaled_w = int(width * scale_factor)

    filter_parts = []
    # Horizontal flip so the clip looks different from the original
    filter_parts.append("hflip")
    # Scale up to target height
    filter_parts.append(f"scale={scaled_w}:{target_h}")
    # Center crop to target width
    if scaled_w > target_w:
        crop_x = (scaled_w - target_w) // 2
        filter_parts.append(f"crop={target_w}:{target_h}:{crop_x}:0")

    # Add subtitles if they were generated
    if subs_path.exists():
        # Need to escape path for FFmpeg on Windows
        subs_escaped = str(subs_path).replace("\\", "/").replace(":", r"\:")
        filter_parts.append(f"ass='{subs_escaped}'")

    filter_chain = ",".join(filter_parts)

    cmd = [
        ffmpeg, "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", filter_chain,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        logger.info(f"Processing clip: {start:.1f}s - {end:.1f}s -> {output_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr[-500:]}")
            return None
        # Clean up subtitle file
        if subs_path.exists():
            subs_path.unlink()
        logger.info(f"Clip processed: {output_path}")
        return output_path
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timed out")
        return None
    except Exception as e:
        logger.error(f"Processing error: {e}")
        return None


def add_hook_overlay(clip_path: Path, hook_text: str, output_path: Path) -> Path | None:
    """
    Add a BIG, BOLD hook text overlay to the first 3 seconds of the clip.
    This is the attention-grabbing text that makes viewers stop scrolling.
    Large white text with heavy black outline, dark semi-transparent background bar.
    """
    ffmpeg = _get_ffmpeg()

    # Escape special chars for FFmpeg drawtext
    hook_escaped = (hook_text
        .replace("\\", "\\\\")
        .replace("'", "\u2019")  # smart quote
        .replace(":", "\\:")
        .replace("%", "%%"))

    # Break into 2 lines if longer than 30 chars
    if len(hook_text) > 30:
        mid = len(hook_text) // 2
        space_pos = hook_text.rfind(" ", 0, mid + 10)
        if space_pos > 5:
            line1 = hook_text[:space_pos].strip()
            line2 = hook_text[space_pos:].strip()
            hook_escaped = (line1
                .replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:").replace("%", "%%"))
            hook_escaped += "\\n" + (line2
                .replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:").replace("%", "%%"))

    # Dark background bar behind the text
    bg_bar = (
        "drawbox=x=0:y=(h/2-120):w=iw:h=240"
        ":color=black@0.6:t=fill"
        ":enable='between(t,0,3)'"
    )

    # Big bold white text with thick black outline — centered
    drawtext = (
        f"drawtext=text='{hook_escaped}'"
        f":fontsize=82:fontcolor=white:borderw=5:bordercolor=black"
        f":shadowcolor=black@0.8:shadowx=3:shadowy=3"
        f":x=(w-text_w)/2:y=(h/2-text_h/2)"
        f":line_spacing=12"
        f":enable='between(t,0,3)'"
        f":alpha='if(lt(t,0.2),t/0.2,if(gt(t,2.5),1-(t-2.5)/0.5,1))'"
    )

    cmd = [
        ffmpeg, "-y",
        "-i", str(clip_path),
        "-vf", f"{bg_bar},{drawtext}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Hook overlay failed, using clip without hook: {result.stderr[-300:]}")
            shutil.copy2(clip_path, output_path)
        return output_path
    except Exception as e:
        logger.warning(f"Hook overlay error: {e}, using clip without hook")
        shutil.copy2(clip_path, output_path)
        return output_path
