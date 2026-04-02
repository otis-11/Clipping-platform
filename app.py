"""
Flask dashboard for the Kiriakou Clipper pipeline.
Provides admin UI to manage queue, approve posts, change settings,
view history, trigger processing, and monitor logs.
"""
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, Response
from apscheduler.schedulers.background import BackgroundScheduler

import config
from downloader import fetch_new_videos
from pipeline import process_video, get_queue, remove_from_queue
from uploader import upload_short

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "clipper.log"),
    ],
)
logger = logging.getLogger("dashboard")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="data")
app.secret_key = config.DASHBOARD_SECRET
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# ---------------------------------------------------------------------------
# Runtime settings (editable from dashboard, persisted to JSON)
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    defaults = {
        "source_channels": config.SOURCE_CHANNELS,
        "clips_per_day": config.CLIPS_PER_DAY,
        "post_times": config.POST_TIMES,
        "min_clip_duration": config.MIN_CLIP_DURATION,
        "max_clip_duration": config.MAX_CLIP_DURATION,
        "whisper_model": config.WHISPER_MODEL,
        "openai_model": config.OPENAI_MODEL,
        "require_approval": config.REQUIRE_APPROVAL,
    }
    if config.SETTINGS_FILE.exists():
        try:
            with open(config.SETTINGS_FILE, "r") as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_settings(settings: dict):
    with open(config.SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ---------------------------------------------------------------------------
# Background job state (so we can show status in the UI)
# ---------------------------------------------------------------------------
job_status = {
    "processing": False,
    "posting": False,
    "last_process_time": None,
    "last_post_time": None,
    "last_process_result": "",
    "last_post_result": "",
}

# ---------------------------------------------------------------------------
# Scheduler jobs
# ---------------------------------------------------------------------------

def job_process_new_videos():
    if job_status["processing"]:
        return
    job_status["processing"] = True
    job_status["last_process_time"] = datetime.now().isoformat()
    try:
        new_videos = fetch_new_videos(max_per_channel=3)
        total = 0
        for video in new_videos[:2]:
            total += process_video(video)
        job_status["last_process_result"] = f"Queued {total} clips"
        logger.info(f"Processing complete. {total} new clips queued.")
    except Exception as e:
        job_status["last_process_result"] = f"Error: {e}"
        logger.error(f"Processing job failed: {e}", exc_info=True)
    finally:
        job_status["processing"] = False


def job_post_due_clips():
    """Check every few minutes for approved clips whose scheduled_time has passed."""
    if job_status["posting"]:
        return
    job_status["posting"] = True
    now = datetime.now()
    now_hhmm = now.strftime("%H:%M")
    logger.info(f"Post-check running at {now_hhmm}")
    try:
        queue = get_queue()
        approved = [c for c in queue if c.get("approved", False)]
        if not approved:
            job_status["last_post_result"] = "No approved clips"
            logger.info("No approved clips to post.")
            return

        # Find clips whose scheduled_time <= current time
        due = [c for c in approved if c.get("scheduled_time", "99:99") <= now_hhmm]
        if not due:
            logger.info(f"No clips due yet (next: {approved[0].get('scheduled_time','?')})")
            job_status["last_post_result"] = f"Next due at {approved[0].get('scheduled_time','?')}"
            return

        # Post the earliest-due clip
        clip = sorted(due, key=lambda c: c.get("scheduled_time", "00:00"))[0]
        clip_path = Path(clip["clip_path"])
        if not clip_path.exists():
            remove_from_queue(clip)
            job_status["last_post_result"] = "Clip file missing, removed"
            logger.warning(f"Clip file missing: {clip_path}")
            return

        logger.info(f"Uploading: {clip['title'][:60]}")
        job_status["last_post_time"] = now.isoformat()
        video_id = upload_short(
            video_path=clip_path,
            title=clip["title"],
            description=clip.get("description", ""),
        )
        if video_id:
            _save_to_history(clip, video_id)
            remove_from_queue(clip)
            job_status["last_post_result"] = f"Posted: {clip['title'][:40]}"
            logger.info(f"Posted successfully: {video_id}")
        else:
            job_status["last_post_result"] = "Upload returned no video ID"
            logger.error("upload_short returned falsy value")
    except Exception as e:
        job_status["last_post_result"] = f"Error: {e}"
        logger.error(f"Post job failed: {e}", exc_info=True)
    finally:
        job_status["posting"] = False


def job_post_now():
    """Manual trigger — post the next approved clip immediately."""
    if job_status["posting"]:
        return "Already posting"
    job_status["posting"] = True
    job_status["last_post_time"] = datetime.now().isoformat()
    try:
        queue = get_queue()
        approved = [c for c in queue if c.get("approved", False)]
        if not approved:
            job_status["last_post_result"] = "No approved clips"
            return "No approved clips"

        clip = approved[0]
        clip_path = Path(clip["clip_path"])
        if not clip_path.exists():
            remove_from_queue(clip)
            return "Clip file missing"

        logger.info(f"Manual upload: {clip['title'][:60]}")
        video_id = upload_short(
            video_path=clip_path,
            title=clip["title"],
            description=clip.get("description", ""),
        )
        if video_id:
            _save_to_history(clip, video_id)
            remove_from_queue(clip)
            job_status["last_post_result"] = f"Posted: {clip['title'][:40]}"
            return f"Posted! Video ID: {video_id}"
        else:
            job_status["last_post_result"] = "Upload failed"
            return "Upload failed — no video ID returned"
    except Exception as e:
        job_status["last_post_result"] = f"Error: {e}"
        logger.error(f"Manual post failed: {e}", exc_info=True)
        return f"Error: {e}"
    finally:
        job_status["posting"] = False


def _save_to_history(clip: dict, youtube_video_id: str):
    history_file = config.DATA_DIR / "post_history.json"
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
        except Exception:
            pass
    history.append({
        "title": clip.get("title", ""),
        "description": clip.get("description", ""),
        "source_video_title": clip.get("source_video_title", ""),
        "youtube_video_id": youtube_video_id,
        "youtube_url": f"https://youtube.com/shorts/{youtube_video_id}",
        "posted_at": datetime.now().isoformat(),
        "virality_score": clip.get("virality_score", 0),
    })
    history_file.write_text(json.dumps(history, indent=2))


def _get_history() -> list[dict]:
    history_file = config.DATA_DIR / "post_history.json"
    if history_file.exists():
        try:
            return json.loads(history_file.read_text())
        except Exception:
            return []
    return []


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------
scheduler = BackgroundScheduler()


def _rebuild_scheduler():
    """Rebuild scheduled jobs from current settings."""
    # Remove existing jobs
    for job in scheduler.get_jobs():
        job.remove()

    # Daily processing at 6 AM
    scheduler.add_job(
        job_process_new_videos, "cron", hour=6, minute=0,
        id="process_videos", name="Process new videos", replace_existing=True,
    )

    # Check for due clips every 5 minutes
    scheduler.add_job(
        job_post_due_clips, "interval", minutes=5,
        id="post_due_clips", name="Post due clips (every 5 min)", replace_existing=True,
    )


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    queue = get_queue()
    settings = load_settings()
    history = _get_history()
    pending = [c for c in queue if not c.get("approved", False)]
    approved = [c for c in queue if c.get("approved", False)]
    posted_clips = list(config.POSTED_DIR.glob("*.mp4"))

    scheduled_jobs = []
    for job in scheduler.get_jobs():
        scheduled_jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.strftime("%Y-%m-%d %H:%M") if job.next_run_time else "—",
        })

    return render_template("dashboard.html",
        queue=queue,
        pending=pending,
        approved=approved,
        history=history[-20:][::-1],
        settings=settings,
        job_status=job_status,
        scheduled_jobs=scheduled_jobs,
        posted_count=len(posted_clips),
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.route("/edit/<path:filename>")
def edit_page(filename):
    """Full-page editor for a single clip."""
    queue_file = config.QUEUE_DIR / filename
    if not queue_file.exists():
        return redirect(url_for("dashboard"))
    clip = json.loads(queue_file.read_text())
    clip["_queue_file"] = filename
    # Derive video filename
    vname = Path(clip.get("clip_path", "")).name
    clip["video_filename"] = vname
    # Defaults for new fields
    if "tags" not in clip:
        clip["tags"] = "#JohnKiriakou #CIA #whistleblower #podcast #shorts #intelligence #politics"
    if "scheduled_time" not in clip:
        settings = load_settings()
        times = settings.get("post_times", ["08:00"])
        clip["scheduled_time"] = times[0] if times else "08:00"

    settings = load_settings()
    return render_template("edit_clip.html", clip=clip, filename=filename, settings=settings)


# ---------------------------------------------------------------------------
# Routes — Queue actions
# ---------------------------------------------------------------------------

@app.route("/api/queue/approve/<path:filename>", methods=["POST"])
def approve_clip(filename):
    """Approve a clip for posting."""
    queue_file = config.QUEUE_DIR / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        data["approved"] = True
        queue_file.write_text(json.dumps(data, indent=2))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/api/queue/reject/<path:filename>", methods=["POST"])
def reject_clip(filename):
    """Remove a clip from the queue permanently."""
    queue_file = config.QUEUE_DIR / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        clip_path = Path(data.get("clip_path", ""))
        if clip_path.exists():
            clip_path.unlink()
        queue_file.unlink()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/api/queue/approve-all", methods=["POST"])
def approve_all():
    for f in config.QUEUE_DIR.glob("*.json"):
        data = json.loads(f.read_text())
        data["approved"] = True
        f.write_text(json.dumps(data, indent=2))
    return jsonify({"ok": True})


@app.route("/api/queue/edit/<path:filename>", methods=["POST"])
def edit_clip(filename):
    """Edit all metadata of a queued clip."""
    queue_file = config.QUEUE_DIR / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        body = request.get_json() or request.form
        for field in ["title", "description", "hook", "tags", "scheduled_time", "timezone"]:
            if field in body:
                data[field] = body[field]
        queue_file.write_text(json.dumps(data, indent=2))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/api/queue/<path:filename>")
def get_clip_data(filename):
    """Get full clip data as JSON."""
    queue_file = config.QUEUE_DIR / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        # Add defaults for new fields
        if "tags" not in data:
            data["tags"] = "#JohnKiriakou #CIA #whistleblower #podcast #shorts #intelligence #politics"
        if "scheduled_time" not in data:
            settings = load_settings()
            # Assign next available post time
            times = settings.get("post_times", ["08:00"])
            data["scheduled_time"] = times[0] if times else "08:00"
        vname = Path(data.get("clip_path", "")).name
        data["video_filename"] = vname
        data["queue_filename"] = filename
        return jsonify(data)
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# Routes — Video preview
# ---------------------------------------------------------------------------

@app.route("/preview/<path:filename>")
def preview_clip(filename):
    """Serve a clip video file with full range request support for audio."""
    clip_path = config.CLIPS_DIR / filename
    if not clip_path.exists():
        for f in config.QUEUE_DIR.glob("*.json"):
            data = json.loads(f.read_text())
            p = Path(data.get("clip_path", ""))
            if p.name == filename and p.exists():
                clip_path = p
                break
        else:
            return "Not found", 404

    file_size = clip_path.stat().st_size
    range_header = request.headers.get("Range")

    if range_header:
        # Parse range header: "bytes=start-end"
        byte_start = 0
        byte_end = file_size - 1
        range_match = range_header.replace("bytes=", "").split("-")
        if range_match[0]:
            byte_start = int(range_match[0])
        if range_match[1]:
            byte_end = int(range_match[1])
        content_length = byte_end - byte_start + 1

        def generate():
            with open(clip_path, "rb") as f:
                f.seek(byte_start)
                remaining = content_length
                while remaining > 0:
                    chunk_size = min(8192, remaining)
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return Response(
            generate(),
            status=206,
            mimetype="video/mp4",
            headers={
                "Content-Range": f"bytes {byte_start}-{byte_end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
            },
        )

    return send_file(clip_path, mimetype="video/mp4")


# ---------------------------------------------------------------------------
# Routes — Manual triggers
# ---------------------------------------------------------------------------

@app.route("/api/process-now", methods=["POST"])
def trigger_process():
    if job_status["processing"]:
        return jsonify({"ok": False, "error": "Already processing"})
    thread = threading.Thread(target=job_process_new_videos, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Processing started"})


@app.route("/api/post-now", methods=["POST"])
def trigger_post():
    if job_status["posting"]:
        return jsonify({"ok": False, "error": "Already posting"})
    thread = threading.Thread(target=job_post_now, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Posting started"})


# ---------------------------------------------------------------------------
# Routes — Settings
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["POST"])
def update_settings():
    body = request.get_json() or request.form.to_dict()
    settings = load_settings()

    if "source_channels" in body:
        val = body["source_channels"]
        settings["source_channels"] = [c.strip() for c in val.split(",")] if isinstance(val, str) else val
    if "clips_per_day" in body:
        settings["clips_per_day"] = int(body["clips_per_day"])
    if "post_times" in body:
        val = body["post_times"]
        settings["post_times"] = [t.strip() for t in val.split(",")] if isinstance(val, str) else val
    if "min_clip_duration" in body:
        settings["min_clip_duration"] = int(body["min_clip_duration"])
    if "max_clip_duration" in body:
        settings["max_clip_duration"] = int(body["max_clip_duration"])
    if "whisper_model" in body:
        settings["whisper_model"] = body["whisper_model"]
    if "openai_model" in body:
        settings["openai_model"] = body["openai_model"]
    if "require_approval" in body:
        settings["require_approval"] = body["require_approval"] in ("true", True, "on", "1")

    save_settings(settings)

    # Also update the runtime config values
    config.SOURCE_CHANNELS = settings["source_channels"]
    config.CLIPS_PER_DAY = settings["clips_per_day"]
    config.POST_TIMES = settings["post_times"]
    config.MIN_CLIP_DURATION = settings["min_clip_duration"]
    config.MAX_CLIP_DURATION = settings["max_clip_duration"]
    config.WHISPER_MODEL = settings["whisper_model"]
    config.OPENAI_MODEL = settings["openai_model"]
    config.REQUIRE_APPROVAL = settings["require_approval"]

    _rebuild_scheduler()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — Logs
# ---------------------------------------------------------------------------

@app.route("/api/logs")
def get_logs():
    log_path = config.LOG_DIR / "clipper.log"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": lines[-200:]})
    return jsonify({"lines": []})


# ---------------------------------------------------------------------------
# Routes — Status API (for AJAX refresh)
# ---------------------------------------------------------------------------

@app.route("/api/status")
def get_status():
    queue = get_queue()
    pending = [c for c in queue if not c.get("approved", False)]
    approved = [c for c in queue if c.get("approved", False)]
    return jsonify({
        "queue_total": len(queue),
        "pending": len(pending),
        "approved": len(approved),
        "posted_total": len(list(config.POSTED_DIR.glob("*.mp4"))),
        "job_status": job_status,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _rebuild_scheduler()
    scheduler.start()
    logger.info(f"Dashboard starting on http://localhost:{config.DASHBOARD_PORT}")
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT, debug=False)
