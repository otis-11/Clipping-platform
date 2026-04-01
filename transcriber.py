"""
Transcribes video audio using faster-whisper (local, free).
Produces timestamped segments for clip detection and caption generation.
"""
import json
import logging
from pathlib import Path

from faster_whisper import WhisperModel

import config

logger = logging.getLogger(__name__)

_model = None


def get_model() -> WhisperModel:
    """Lazy-load the Whisper model."""
    global _model
    if _model is None:
        logger.info(f"Loading Whisper model: {config.WHISPER_MODEL}")
        _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe_video(video_path: Path) -> dict:
    """
    Transcribe a video file and return structured transcript data.
    Returns:
        {
            "segments": [{"start": float, "end": float, "text": str}, ...],
            "full_text": str,
            "word_segments": [{"start": float, "end": float, "word": str}, ...]
        }
    """
    model = get_model()
    logger.info(f"Transcribing: {video_path.name}")

    segments_raw, info = model.transcribe(
        str(video_path),
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
    )

    segments = []
    word_segments = []
    full_text_parts = []

    for seg in segments_raw:
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        full_text_parts.append(seg.text.strip())

        if seg.words:
            for w in seg.words:
                word_segments.append({
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                    "word": w.word.strip(),
                })

    transcript = {
        "segments": segments,
        "full_text": " ".join(full_text_parts),
        "word_segments": word_segments,
    }

    # Save transcript to disk
    transcript_path = config.TRANSCRIPTS_DIR / f"{video_path.stem}.json"
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    logger.info(f"Transcription complete: {len(segments)} segments, {len(word_segments)} words")
    return transcript


def load_transcript(video_id: str) -> dict | None:
    """Load a previously saved transcript."""
    transcript_path = config.TRANSCRIPTS_DIR / f"{video_id}.json"
    if transcript_path.exists():
        with open(transcript_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
