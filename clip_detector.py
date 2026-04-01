"""
Uses OpenAI GPT to analyze transcripts and
identify the most viral-worthy clip moments.
"""
import json
import logging
import re

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


CLIP_DETECTION_PROMPT = """You are a viral content expert who identifies the best short-form clip moments from podcast transcripts.

Analyze this transcript from a podcast featuring John Kiriakou (former CIA officer and whistleblower) and find the {num_clips} BEST moments to turn into YouTube Shorts / TikTok clips.

WHAT MAKES A VIRAL CLIP:
- Shocking revelations or insider secrets from the CIA
- Strong emotional moments (anger, surprise, humor)
- Controversial or provocative statements
- Self-contained stories that make sense without context
- Punchy quotes that stand alone
- Moments that make viewers say "wait, WHAT?"
- Cliffhangers or dramatic pauses

CRITICAL DURATION RULES:
- EVERY clip MUST be between {min_dur} and {max_dur} seconds long. This is NON-NEGOTIABLE.
- The difference between end_time and start_time MUST be at least {min_dur} seconds.
- For example, if min is 30s: start_time=100.0, end_time=160.0 is a 60s clip (GOOD).
- A clip of 8 seconds is TOO SHORT and INVALID. Expand it to include surrounding context.
- Look for continuous stretches of {min_dur}-{max_dur} seconds of compelling content.
- Clips must start and end at natural sentence boundaries
- Each clip must be self-contained and understandable on its own
- Clips must NOT overlap with each other
- Prioritize moments where John is speaking directly

Return ONLY a valid JSON array with exactly {num_clips} objects, each with:
- "start_time": start time in seconds (float)
- "end_time": end time in seconds (float) — MUST be at least {min_dur} seconds after start_time
- "title": catchy YouTube Shorts title (max 70 chars, attention-grabbing)
- "hook": 1-sentence hook text to display in first 2 seconds (max 80 chars)
- "description": short description for YouTube (2-3 sentences with hashtags)
- "virality_score": 1-10 rating of viral potential

TRANSCRIPT (with timestamps in seconds):
{transcript}

Return ONLY the JSON array, no markdown, no code fences, no other text."""


def detect_clips(transcript: dict, video_title: str, num_clips: int = 8) -> list[dict]:
    """
    Analyze transcript and return the best clip candidates.
    Returns more than needed so we can queue them up over multiple days.
    """
    # Format transcript with timestamps for the LLM
    formatted_segments = []
    for seg in transcript["segments"]:
        formatted_segments.append(f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")

    transcript_text = "\n".join(formatted_segments)

    # Truncate if too long (Gemini Flash has 1M context but let's be efficient)
    if len(transcript_text) > 80000:
        transcript_text = transcript_text[:80000] + "\n[TRANSCRIPT TRUNCATED]"

    prompt = CLIP_DETECTION_PROMPT.format(
        num_clips=num_clips,
        min_dur=config.MIN_CLIP_DURATION,
        max_dur=config.MAX_CLIP_DURATION,
        transcript=transcript_text,
    )

    try:
        response = _get_client().chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )

        # Parse JSON from response (strip markdown code fences if present)
        text = response.choices[0].message.content.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        # Try to extract JSON array from response
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            clips = json.loads(json_match.group())
        else:
            clips = json.loads(text)

        logger.info(f"AI returned {len(clips)} clips, validating durations...")

        # Validate and clean clips
        valid_clips = []
        for clip in clips:
            if all(k in clip for k in ["start_time", "end_time", "title", "hook"]):
                duration = clip["end_time"] - clip["start_time"]
                if config.MIN_CLIP_DURATION <= duration <= config.MAX_CLIP_DURATION + 10:
                    clip["source_video_title"] = video_title
                    valid_clips.append(clip)
                else:
                    logger.warning(f"Clip rejected (duration {duration:.0f}s): {clip.get('title', '?')}")

        # Sort by virality score
        valid_clips.sort(key=lambda x: x.get("virality_score", 0), reverse=True)

        logger.info(f"Detected {len(valid_clips)} valid clips from '{video_title}'")
        return valid_clips

    except Exception as e:
        logger.error(f"Clip detection failed: {e}")
        return []
