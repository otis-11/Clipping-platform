"""
Generate 5 viral-style clips from JRE #2392 - John Kiriakou and queue them for approval.
Uses the approved two-segment concat technique with aggressive editing.
"""
import json
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Config ---
VIDEO_ID = "TZqADzuu73g"
ACCOUNT_ID = "kiriakou"
DATA_DIR = Path("data") / ACCOUNT_ID
VIDEO_PATH = DATA_DIR / "videos" / f"{VIDEO_ID}.mp4"
TRANSCRIPT_PATH = DATA_DIR / "transcripts" / f"{VIDEO_ID}.json"
OUTPUT_DIR = DATA_DIR / "clips"
QUEUE_DIR = DATA_DIR / "queue"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

TARGET_W, TARGET_H = 1080, 1920
SPEED = 1.1

# --- 5 Clips: each has two segments (A=hook, B=escalation/cliffhanger) ---
CLIPS = [
    {
        "id": "viral01",
        "seg_a": (2554.0, 2572.0),   # "Obama became president, Brennan decided to have my head"
        "seg_b": (2602.0, 2620.0),   # "2000 Taliban suffocated in container trucks"
        "headline": "Obama's CIA Director Wanted My HEAD",
        "title": "Obama's CIA Director Wanted to Destroy Me - John Kiriakou",
        "hook": "John Brennan decided he was going to have my head...",
        "description": "John Kiriakou reveals how CIA Director John Brennan targeted him for prosecution after he blew the whistle. The secrets they tried to keep buried are shocking. #CIA #Whistleblower #JohnKiriakou #JoeRogan #Shorts",
        "virality_score": 10,
    },
    {
        "id": "viral02",
        "seg_a": (3554.0, 3584.0),   # "Espionage court, jury is CIA/FBI/DOD... you don't have a prayer"
        "seg_b": (3649.0, 3678.0),   # "Walking to back of prison... Brennan said make it difficult"
        "headline": "Your Entire Jury Works for the CIA",
        "title": "They Rigged My Trial - CIA Whistleblower Reveals the Truth",
        "hook": "Your entire jury is going to be people from the CIA...",
        "description": "John Kiriakou exposes how the espionage court is stacked against whistleblowers. Even after sentencing, the CIA wanted revenge. #CIA #Espionage #Whistleblower #JoeRogan #Shorts",
        "virality_score": 9,
    },
    {
        "id": "viral03",
        "seg_a": (5063.0, 5093.0),   # "CIA torture program wasn't even effective"
        "seg_b": (5125.0, 5158.0),   # "Mitchell and Jessen took $108 million, retired to Florida"
        "headline": "The CIA's Torture Program Was a $108M LIE",
        "title": "CIA Torture Was USELESS - They Took $108 Million Anyway",
        "hook": "The CIA torture program wasn't even effective...",
        "description": "The architects of the CIA's torture program walked away with $108 million and retired to Florida. The program didn't even work. #CIA #Torture #Whistleblower #JoeRogan #Shorts",
        "virality_score": 10,
    },
    {
        "id": "viral04",
        "seg_a": (7856.0, 7878.0),   # "Machine turned on you... felt really alone... email from deputy director"
        "seg_b": (7884.0, 7908.0),   # "You've chosen a difficult path, I wish I had the guts"
        "headline": "A CIA Deputy Director Sent Me THIS",
        "title": "What a CIA Deputy Director Secretly Told Me Changed Everything",
        "hook": "I felt really alone in the world...",
        "description": "After being arrested, a retired CIA deputy director sent John Kiriakou an email that changed everything. 'I wish I had the guts to do it myself.' #CIA #Whistleblower #JoeRogan #Shorts",
        "virality_score": 9,
    },
    {
        "id": "viral05",
        "seg_a": (167.0, 195.0),     # "bin Laden's wadi, killed Muhammad Atef, Abu Zubayda"
        "seg_b": (204.0, 235.0),     # "Six weeks to track him, busted down doors, half-eaten sandwich"
        "headline": "I Was Hunting Bin Laden's Inner Circle",
        "title": "Inside the Hunt for Al-Qaeda's Leadership - CIA Officer Reveals",
        "hook": "I'm in bin Laden's wadi. We had killed Muhammad Atef...",
        "description": "Former CIA officer John Kiriakou takes you inside the hunt for Al-Qaeda's top leadership. Bin Laden, Abu Zubayda, Khalid Sheikh Muhammad. #CIA #AlQaeda #BinLaden #JoeRogan #Shorts",
        "virality_score": 8,
    },
]

# Trigger words for colored captions
RED_WORDS = {"prison", "killed", "head", "destroy", "torture", "death", "suffocated", "espionage",
             "revenge", "arrested", "alone", "afraid", "terrified", "$108", "million", "murdered",
             "betrayed", "illegal", "bombs", "bombing"}
GREEN_WORDS = {"guts", "prayer", "effective", "retired", "florida", "friends", "secretary",
               "honorable", "peace", "survived", "pillow", "deal"}
YELLOW_WORDS = {"why", "really", "truth", "secret", "classified", "revealed", "whistleblower",
                "difficult", "chosen", "investigate", "program", "operations"}


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
    clean = word.strip(".,!?;:'\"$").lower()
    if clean in RED_WORDS or any(r in clean for r in RED_WORDS):
        return r"{\c&H0000FF&}"
    if clean in GREEN_WORDS or any(g in clean for g in GREEN_WORDS):
        return r"{\c&H00FF00&}"
    if clean in YELLOW_WORDS or any(y in clean for y in YELLOW_WORDS):
        return r"{\c&H00FFFF&}"
    return r"{\c&HFFFFFF&}"


def generate_viral_ass(word_segments, seg_a, seg_b, headline, output_path):
    words_a = [w for w in word_segments if seg_a[0] <= w["start"] <= seg_a[1]]
    words_b = [w for w in word_segments if seg_b[0] <= w["start"] <= seg_b[1]]

    offset_a = seg_a[0]
    duration_a = seg_a[1] - seg_a[0]
    glitch_gap = 0.3

    adjusted = []
    for w in words_a:
        adjusted.append({"word": w["word"], "start": w["start"] - offset_a, "end": w["end"] - offset_a})
    for w in words_b:
        adjusted.append({
            "word": w["word"],
            "start": (w["start"] - seg_b[0]) + duration_a + glitch_gap,
            "end": (w["end"] - seg_b[0]) + duration_a + glitch_gap,
        })

    total_duration = duration_a + glitch_gap + (seg_b[1] - seg_b[0])

    ass = f"""[Script Info]
Title: Viral Clip
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
    headline_escaped = headline.replace(",", "\\,")
    ass += f"Dialogue: 1,{seconds_to_ass(0)},{seconds_to_ass(total_duration)},Headline,,0,0,0,,{{\\b1}}{headline_escaped}\n"

    group_size = 3
    for g_start in range(0, len(adjusted), group_size):
        group = adjusted[g_start:g_start + group_size]
        if not group:
            continue
        for hi, highlighted_word in enumerate(group):
            w_start = highlighted_word["start"]
            w_end = highlighted_word["end"]
            parts = []
            for gi, gw in enumerate(group):
                color = word_color(gw["word"])
                if gi == hi:
                    parts.append(f"{color}{{\\fscx120\\fscy120\\b1}}{gw['word']}{{\\fscx100\\fscy100\\b0}}{{\\c&HFFFFFF&}}")
                else:
                    parts.append(f"{{\\c&HAAAAAA&}}{gw['word']}{{\\c&HFFFFFF&}}")
            text = " ".join(parts)
            ass += f"Dialogue: 0,{seconds_to_ass(w_start)},{seconds_to_ass(w_end)},Words,,0,0,0,,{text}\n"

    output_path.write_text(ass, encoding="utf-8")
    return total_duration


def extract_segment(video_path, start, end, output_path, vid_dims):
    ffmpeg = get_ffmpeg()
    width, height = vid_dims
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
        ffmpeg, "-y", "-ss", str(start), "-i", str(video_path), "-t", str(duration),
        "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"Extract failed: {result.stderr[-300:]}")
        return None
    return output_path


def build_clip(video_path, clip_def, word_segments, vid_dims):
    clip_id = clip_def["id"]
    seg_a = clip_def["seg_a"]
    seg_b = clip_def["seg_b"]
    headline = clip_def["headline"]

    subs_path = OUTPUT_DIR / f"{VIDEO_ID}_{clip_id}.ass"
    total_dur = generate_viral_ass(word_segments, seg_a, seg_b, headline, subs_path)

    tmp_a = OUTPUT_DIR / f"_tmp_{clip_id}_a.mp4"
    tmp_b = OUTPUT_DIR / f"_tmp_{clip_id}_b.mp4"
    output_path = OUTPUT_DIR / f"{VIDEO_ID}_{clip_id}.mp4"

    if not extract_segment(video_path, seg_a[0], seg_a[1], tmp_a, vid_dims):
        return None
    if not extract_segment(video_path, seg_b[0], seg_b[1], tmp_b, vid_dims):
        return None

    ffmpeg = get_ffmpeg()
    subs_escaped = str(subs_path).replace("\\", "/").replace(":", r"\:")
    glitch_gap = 0.3

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
        ffmpeg, "-y", "-i", str(tmp_a), "-i", str(tmp_b),
        "-filter_complex", filtergraph,
        "-map", "[vfinal]", "-map", "[afinal]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    tmp_a.unlink(missing_ok=True)
    tmp_b.unlink(missing_ok=True)

    if result.returncode != 0:
        logger.error(f"Concat failed for {clip_id}: {result.stderr[-500:]}")
        return None

    # Clean up subs
    subs_path.unlink(missing_ok=True)
    logger.info(f"Created: {output_path.name} (~{total_dur/SPEED:.0f}s)")
    return output_path


def queue_clip(clip_def, clip_path):
    """Add clip to the dashboard queue for approval."""
    queue_item = {
        "clip_path": str(clip_path.resolve()),
        "title": clip_def["title"],
        "hook": clip_def["hook"],
        "description": clip_def["description"],
        "virality_score": clip_def["virality_score"],
        "source_video_title": "Joe Rogan Experience #2392 - John Kiriakou",
        "start_time": clip_def["seg_a"][0],
        "end_time": clip_def["seg_b"][1],
        "approved": False,
        "created_at": datetime.now().isoformat(),
    }
    queue_file = QUEUE_DIR / f"{VIDEO_ID}_{clip_def['id']}.json"
    queue_file.write_text(json.dumps(queue_item, indent=2))
    logger.info(f"Queued for approval: {clip_def['title'][:50]}")


def main():
    if not VIDEO_PATH.exists():
        logger.error(f"Source video not found: {VIDEO_PATH}")
        return

    transcript = json.loads(TRANSCRIPT_PATH.read_text())
    word_segments = transcript.get("word_segments", [])
    if not word_segments:
        logger.error("No word segments in transcript")
        return

    vid_dims = get_video_dimensions(VIDEO_PATH)
    logger.info(f"Video dimensions: {vid_dims[0]}x{vid_dims[1]}")

    success = 0
    for i, clip_def in enumerate(CLIPS):
        logger.info(f"\n{'='*60}")
        logger.info(f"Generating clip {i+1}/5: {clip_def['title'][:50]}")
        logger.info(f"{'='*60}")

        clip_path = build_clip(VIDEO_PATH, clip_def, word_segments, vid_dims)
        if clip_path:
            queue_clip(clip_def, clip_path)
            success += 1
        else:
            logger.error(f"Failed to generate clip {clip_def['id']}")

    print(f"\n{'='*60}")
    print(f"DONE! Generated {success}/5 clips and queued for approval.")
    print(f"Open the dashboard to review and approve them.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
