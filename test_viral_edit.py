"""
One-off test: Generate a single YouTube Short with aggressive viral editing style.
Source: JRE #2392 - John Kiriakou (TZqADzuu73g)
Segment: "$6 million to put me in prison" → "45 years for blowing the whistle"

Two segments concatenated with glitch transition:
  A) 3268.7s–3285.3s  "$6M to prison for 23 months" (HOOK + CONFLICT)
  B) 3322.0s–3342.1s  "pillow talk → executed → 45 years" (ESCALATION + CLIFFHANGER)
"""
import json
import logging
import subprocess
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Config ---
VIDEO_ID = "TZqADzuu73g"
ACCOUNT_ID = "kiriakou"
DATA_DIR = Path("data") / ACCOUNT_ID
VIDEO_PATH = DATA_DIR / "videos" / f"{VIDEO_ID}.mp4"
TRANSCRIPT_PATH = DATA_DIR / "transcripts" / f"{VIDEO_ID}.json"
OUTPUT_DIR = DATA_DIR / "clips"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Two segments to concatenate
SEG_A = (3268.7, 3285.3)   # ~16.6s → hook + conflict
SEG_B = (3322.0, 3342.1)   # ~20.1s → escalation + cliffhanger
# Total raw: ~36.7s. At 1.1x speed → ~33s. Perfect for 30-45s Short.

SPEED = 1.1  # slight speed-up for energy without sounding chipmunk
TARGET_W, TARGET_H = 1080, 1920

# Hook headline that persists at top of frame
HOOK_HEADLINE = "They Spent $6 MILLION to Silence Me"

# Emotional trigger words for colored captions
RED_WORDS = {"prison", "$6", "million", "executed", "45", "years", "torture", "killed", "crime"}
GREEN_WORDS = {"nine", "months", "pillow", "talk", "affair", "secretary"}
YELLOW_WORDS = {"why", "really", "society", "whistle", "program", "charged"}


def get_ffmpeg():
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    import re
    ffmpeg = get_ffmpeg()
    result = subprocess.run([ffmpeg, "-i", str(video_path)], capture_output=True, text=True)
    match = re.search(r'(\d{3,5})x(\d{3,5})', result.stderr)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1920, 1080


def seconds_to_ass(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def word_color(word: str) -> str:
    """Return ASS color tag based on emotional category."""
    clean = word.strip(".,!?;:'\"").lower()
    if clean in RED_WORDS or any(r in clean for r in RED_WORDS):
        return r"{\c&H0000FF&}"  # ASS uses BGR: 0000FF = red
    if clean in GREEN_WORDS or any(g in clean for g in GREEN_WORDS):
        return r"{\c&H00FF00&}"  # green
    if clean in YELLOW_WORDS or any(y in clean for y in YELLOW_WORDS):
        return r"{\c&H00FFFF&}"  # yellow (BGR)
    return r"{\c&HFFFFFF&}"      # white


def generate_viral_ass(word_segments: list[dict], seg_a: tuple, seg_b: tuple, output_path: Path):
    """
    Generate ASS subtitles with:
    - Word-by-word sync
    - Colored emotional trigger words (red/green/yellow)
    - Large bold center-weighted typography
    - Persistent hook headline at top
    """
    # Get words for each segment, adjust timestamps for concatenation
    words_a = [w for w in word_segments if seg_a[0] <= w["start"] <= seg_a[1]]
    words_b = [w for w in word_segments if seg_b[0] <= w["start"] <= seg_b[1]]

    # Segment B starts after segment A ends + 0.3s glitch gap
    offset_a = seg_a[0]
    duration_a = seg_a[1] - seg_a[0]
    glitch_gap = 0.3
    offset_b_shift = duration_a + glitch_gap

    # Adjust timestamps: A starts at 0, B starts at duration_a + gap
    adjusted = []
    for w in words_a:
        adjusted.append({
            "word": w["word"],
            "start": w["start"] - offset_a,
            "end": w["end"] - offset_a,
        })
    for w in words_b:
        adjusted.append({
            "word": w["word"],
            "start": (w["start"] - seg_b[0]) + offset_b_shift,
            "end": (w["end"] - seg_b[0]) + offset_b_shift,
        })

    total_duration = offset_b_shift + (seg_b[1] - seg_b[0])

    # ASS header — aggressive styling
    ass = f"""[Script Info]
Title: Viral Test Clip
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Words,Impact,100,&H00FFFFFF,&H000000FF,&H00000000,&HCC000000,-1,0,0,0,100,100,2,0,1,6,3,2,40,40,680,1
Style: Headline,Impact,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&HCC000000,-1,0,0,0,100,100,1,0,3,5,0,8,30,30,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Persistent headline at top for full duration
    headline_escaped = HOOK_HEADLINE.replace(",", "\\,")
    ass += f"Dialogue: 1,{seconds_to_ass(0)},{seconds_to_ass(total_duration)},Headline,,0,0,0,,{{\\b1}}{headline_escaped}\n"

    # Word-by-word captions in groups of 3-4 words
    group_size = 3
    for g_start in range(0, len(adjusted), group_size):
        group = adjusted[g_start:g_start + group_size]
        if not group:
            continue

        line_start = group[0]["start"]
        line_end = group[-1]["end"]

        # For each word highlight in the group
        for hi, highlighted_word in enumerate(group):
            w_start = highlighted_word["start"]
            w_end = highlighted_word["end"]

            parts = []
            for gi, gw in enumerate(group):
                color = word_color(gw["word"])
                if gi == hi:
                    # Current word: bold + scale up + colored
                    parts.append(f"{color}{{\\fscx120\\fscy120\\b1}}{gw['word']}{{\\fscx100\\fscy100\\b0}}{{\\c&HFFFFFF&}}")
                else:
                    # Other words: dimmer white or their color
                    parts.append(f"{{\\c&HAAAAAA&}}{gw['word']}{{\\c&HFFFFFF&}}")

            text = " ".join(parts)
            ass += f"Dialogue: 0,{seconds_to_ass(w_start)},{seconds_to_ass(w_end)},Words,,0,0,0,,{text}\n"

    output_path.write_text(ass, encoding="utf-8")
    logger.info(f"Generated viral ASS subtitles: {output_path}")
    return total_duration


def extract_segment(video_path: Path, start: float, end: float, output_path: Path):
    """Fast-extract a segment using -ss before -i for keyframe seeking."""
    ffmpeg = get_ffmpeg()
    width, height = get_video_dimensions(video_path)
    scale_factor = TARGET_H / height
    scaled_w = int(width * scale_factor)
    crop_x = (scaled_w - TARGET_W) // 2 if scaled_w > TARGET_W else 0

    duration = end - start
    vf = (
        f"hflip,scale={scaled_w}:{TARGET_H},crop={TARGET_W}:{TARGET_H}:{crop_x}:0,"
        f"eq=contrast=1.3:brightness=-0.05:saturation=0.8,"
        f"setsar=1,fps=30"
    )

    cmd = [
        ffmpeg, "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    logger.info(f"Extracting segment {start:.1f}s-{end:.1f}s -> {output_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"Extract failed: {result.stderr[-500:]}")
        return None
    return output_path


def build_video(video_path: Path, seg_a: tuple, seg_b: tuple, subs_path: Path, output_path: Path):
    """
    Build the final video:
    1. Extract segments A and B as fast intermediate files
    2. Concatenate with glitch gap
    3. Burn captions + speed adjust
    """
    ffmpeg = get_ffmpeg()
    dur_a = seg_a[1] - seg_a[0]
    dur_b = seg_b[1] - seg_b[0]
    glitch_gap = 0.3
    total_dur = dur_a + glitch_gap + dur_b

    subs_escaped = str(subs_path).replace("\\", "/").replace(":", r"\:")

    # Step 1: Extract segments
    tmp_a = OUTPUT_DIR / "_tmp_seg_a.mp4"
    tmp_b = OUTPUT_DIR / "_tmp_seg_b.mp4"

    if not extract_segment(video_path, seg_a[0], seg_a[1], tmp_a):
        return None
    if not extract_segment(video_path, seg_b[0], seg_b[1], tmp_b):
        return None

    # Step 2: Concatenate A + black gap + B, burn subs, speed up
    filtergraph = (
        f"[0:v]setsar=1[va];"
        f"[1:v]setsar=1[vb];"
        f"color=c=black:s={TARGET_W}x{TARGET_H}:d={glitch_gap}:r=30,setsar=1[vgap];"
        f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[aa];"
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[ab];"
        f"anullsrc=r=44100:cl=stereo:d={glitch_gap}[agap];"
        f"[va][aa][vgap][agap][vb][ab]concat=n=3:v=1:a=1[vc][ac];"
        f"[vc]ass='{subs_escaped}',setpts={1/SPEED}*PTS[vfinal];"
        f"[ac]atempo={SPEED}[afinal]"
    )

    cmd = [
        ffmpeg, "-y",
        "-i", str(tmp_a),
        "-i", str(tmp_b),
        "-filter_complex", filtergraph,
        "-map", "[vfinal]",
        "-map", "[afinal]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]

    logger.info("Concatenating + burning captions + speed adjust...")
    logger.info(f"Speed: {SPEED}x, Total estimated: {total_dur/SPEED:.1f}s")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # Cleanup temp files
    tmp_a.unlink(missing_ok=True)
    tmp_b.unlink(missing_ok=True)

    if result.returncode != 0:
        logger.error(f"FFmpeg concat failed:\n{result.stderr[-1500:]}")
        return None

    logger.info(f"Video created: {output_path}")
    return output_path


def main():
    # Check video exists (may have been cleaned up by pipeline)
    if not VIDEO_PATH.exists():
        # Re-download
        logger.info("Source video not found, re-downloading...")
        from downloader import download_video
        download_video(f"https://www.youtube.com/watch?v={VIDEO_ID}", VIDEO_ID,
                       videos_dir=DATA_DIR / "videos")

    if not VIDEO_PATH.exists():
        # Check for any video file with this ID
        for f in (DATA_DIR / "videos").glob(f"{VIDEO_ID}.*"):
            if f.suffix in (".mp4", ".mkv", ".webm"):
                logger.info(f"Found video: {f}")
                break
        else:
            logger.error("Could not find or download source video")
            return

    # Load transcript
    transcript = json.loads(TRANSCRIPT_PATH.read_text())
    word_segments = transcript.get("word_segments", [])
    if not word_segments:
        logger.error("No word segments in transcript")
        return

    # Generate subtitles
    subs_path = OUTPUT_DIR / f"{VIDEO_ID}_viral_test.ass"
    total_dur = generate_viral_ass(word_segments, SEG_A, SEG_B, subs_path)
    logger.info(f"Subtitle duration: {total_dur:.1f}s")

    # Build the video
    output_path = OUTPUT_DIR / f"{VIDEO_ID}_viral_test.mp4"
    result = build_video(VIDEO_PATH, SEG_A, SEG_B, subs_path, output_path)

    if result:
        print(f"\n{'='*60}")
        print(f"VIRAL TEST VIDEO CREATED!")
        print(f"Output: {output_path}")
        print(f"Duration: ~{total_dur/SPEED:.0f}s")
        print(f"{'='*60}")
    else:
        print("\nVideo creation failed. Check logs above.")


if __name__ == "__main__":
    main()
