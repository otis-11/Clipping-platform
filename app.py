"""
Multi-account Flask dashboard for YouTube Clipper pipeline.
Provides admin UI to manage queues, approve posts, change settings,
view history, trigger processing, and monitor logs — per account.
"""
import json
import logging
import re as _re
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, Response
from apscheduler.schedulers.background import BackgroundScheduler

import config
from config import load_accounts, save_accounts, get_account, get_account_dirs, get_account_files
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
# Per-account helpers
# ---------------------------------------------------------------------------

def _acct_settings_file(account_id: str) -> Path:
    return get_account_files(account_id)["settings"]


def load_settings(account_id: str = "kiriakou") -> dict:
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
    # Override source_channels from account definition
    acct = get_account(account_id)
    if acct:
        defaults["source_channels"] = acct.get("source_channels", defaults["source_channels"])

    sf = _acct_settings_file(account_id)
    if sf.exists():
        try:
            with open(sf, "r") as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_settings(settings: dict, account_id: str = "kiriakou"):
    sf = _acct_settings_file(account_id)
    with open(sf, "w") as f:
        json.dump(settings, f, indent=2)


def _save_to_history(clip: dict, youtube_video_id: str, account_id: str = "kiriakou"):
    history_file = get_account_files(account_id)["history"]
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


def _get_history(account_id: str = "kiriakou") -> list[dict]:
    history_file = get_account_files(account_id)["history"]
    if history_file.exists():
        try:
            return json.loads(history_file.read_text())
        except Exception:
            return []
    return []


def _yt_creds(account_id: str) -> tuple[Path, Path]:
    """Return (client_secret_path, token_path) for an account."""
    acct = get_account(account_id) or {}
    secret = config.PROJECT_DIR / acct.get("youtube_client_secret", "client_secret.json")
    token = config.PROJECT_DIR / acct.get("youtube_token", "youtube_token.json")
    return secret, token


# ---------------------------------------------------------------------------
# Per-account job status
# ---------------------------------------------------------------------------
_job_status = {}  # account_id -> status dict


def _get_job_status(account_id: str) -> dict:
    if account_id not in _job_status:
        _job_status[account_id] = {
            "processing": False,
            "posting": False,
            "last_process_time": None,
            "last_post_time": None,
            "last_process_result": "",
            "last_post_result": "",
        }
    return _job_status[account_id]


# ---------------------------------------------------------------------------
# Scheduler jobs (per-account)
# ---------------------------------------------------------------------------

def _make_process_job(account_id: str):
    """Return a processing function bound to one account."""
    def job_fn():
        status = _get_job_status(account_id)
        if status["processing"]:
            return
        status["processing"] = True
        status["last_process_time"] = datetime.now().isoformat()
        acct = get_account(account_id) or {}
        dirs = get_account_dirs(account_id)
        files = get_account_files(account_id)
        try:
            new_videos = fetch_new_videos(
                max_per_channel=3,
                source_channels=acct.get("source_channels"),
                processed_file=files["processed_videos"],
            )
            total = 0
            for video in new_videos[:2]:
                total += process_video(
                    video,
                    account_dirs=dirs,
                    account_files=files,
                    prompt_context=acct.get("clip_prompt_context",
                                           "John Kiriakou (former CIA officer and whistleblower)"),
                )
            status["last_process_result"] = f"Queued {total} clips"
            logger.info(f"[{account_id}] Processing complete. {total} new clips queued.")
        except Exception as e:
            status["last_process_result"] = f"Error: {e}"
            logger.error(f"[{account_id}] Processing job failed: {e}", exc_info=True)
        finally:
            status["processing"] = False
    job_fn.__name__ = f"process_{account_id}"
    return job_fn


def _make_post_job(account_id: str):
    """Return a posting function bound to one account."""
    def job_fn():
        status = _get_job_status(account_id)
        if status["posting"]:
            return
        status["posting"] = True
        now = datetime.now()
        now_hhmm = now.strftime("%H:%M")
        dirs = get_account_dirs(account_id)
        secret, token = _yt_creds(account_id)
        acct = get_account(account_id) or {}
        logger.info(f"[{account_id}] Post-check at {now_hhmm}")
        try:
            queue = get_queue(queue_dir=dirs["queue"])
            approved = [c for c in queue if c.get("approved", False)]
            if not approved:
                status["last_post_result"] = "No approved clips"
                return

            due = [c for c in approved if c.get("scheduled_time", "99:99") <= now_hhmm]
            if not due:
                status["last_post_result"] = f"Next due at {approved[0].get('scheduled_time','?')}"
                return

            clip = sorted(due, key=lambda c: c.get("scheduled_time", "00:00"))[0]
            clip_path = Path(clip["clip_path"])
            if not clip_path.exists():
                remove_from_queue(clip, posted_dir=dirs["posted"])
                status["last_post_result"] = "Clip file missing, removed"
                return

            logger.info(f"[{account_id}] Uploading: {clip['title'][:60]}")
            status["last_post_time"] = now.isoformat()
            video_id = upload_short(
                video_path=clip_path,
                title=clip["title"],
                description=clip.get("description", ""),
                category_id=acct.get("category_id", "25"),
                client_secret_path=secret,
                token_path=token,
            )
            if video_id:
                _save_to_history(clip, video_id, account_id=account_id)
                remove_from_queue(clip, posted_dir=dirs["posted"])
                status["last_post_result"] = f"Posted: {clip['title'][:40]}"
                logger.info(f"[{account_id}] Posted: {video_id}")
            else:
                status["last_post_result"] = "Upload returned no video ID"
        except Exception as e:
            status["last_post_result"] = f"Error: {e}"
            logger.error(f"[{account_id}] Post job failed: {e}", exc_info=True)
        finally:
            status["posting"] = False
    job_fn.__name__ = f"post_{account_id}"
    return job_fn


def _make_post_now(account_id: str):
    """Manual trigger — post the next approved clip immediately for this account."""
    def job_fn():
        status = _get_job_status(account_id)
        if status["posting"]:
            return "Already posting"
        status["posting"] = True
        status["last_post_time"] = datetime.now().isoformat()
        dirs = get_account_dirs(account_id)
        secret, token = _yt_creds(account_id)
        acct = get_account(account_id) or {}
        try:
            queue = get_queue(queue_dir=dirs["queue"])
            approved = [c for c in queue if c.get("approved", False)]
            if not approved:
                status["last_post_result"] = "No approved clips"
                return "No approved clips"

            clip = approved[0]
            clip_path = Path(clip["clip_path"])
            if not clip_path.exists():
                remove_from_queue(clip, posted_dir=dirs["posted"])
                return "Clip file missing"

            logger.info(f"[{account_id}] Manual upload: {clip['title'][:60]}")
            video_id = upload_short(
                video_path=clip_path,
                title=clip["title"],
                description=clip.get("description", ""),
                category_id=acct.get("category_id", "25"),
                client_secret_path=secret,
                token_path=token,
            )
            if video_id:
                _save_to_history(clip, video_id, account_id=account_id)
                remove_from_queue(clip, posted_dir=dirs["posted"])
                status["last_post_result"] = f"Posted: {clip['title'][:40]}"
                return f"Posted! Video ID: {video_id}"
            else:
                status["last_post_result"] = "Upload failed"
                return "Upload failed"
        except Exception as e:
            status["last_post_result"] = f"Error: {e}"
            logger.error(f"[{account_id}] Manual post failed: {e}", exc_info=True)
            return f"Error: {e}"
        finally:
            status["posting"] = False
    return job_fn


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------
scheduler = BackgroundScheduler()


def _rebuild_scheduler():
    """Rebuild scheduled jobs for ALL accounts."""
    for job in scheduler.get_jobs():
        job.remove()

    for acct in load_accounts():
        aid = acct["id"]
        # Daily processing at 6 AM
        scheduler.add_job(
            _make_process_job(aid), "cron", hour=6, minute=0,
            id=f"process_{aid}", name=f"Process [{acct['name']}]", replace_existing=True,
        )
        # Check for due clips every 5 minutes
        scheduler.add_job(
            _make_post_job(aid), "interval", minutes=5,
            id=f"post_{aid}", name=f"Post [{acct['name']}] (5 min)", replace_existing=True,
        )


# ---------------------------------------------------------------------------
# Routes — Root redirect
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    accounts = load_accounts()
    if accounts:
        return redirect(url_for("dashboard", account_id=accounts[0]["id"]))
    return "No accounts configured", 500


# ---------------------------------------------------------------------------
# Routes — Accounts API
# ---------------------------------------------------------------------------

@app.route("/api/accounts")
def list_accounts():
    return jsonify(load_accounts())


@app.route("/api/accounts/add", methods=["POST"])
def add_account():
    body = request.get_json() or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    # Generate slug id
    aid = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not aid:
        return jsonify({"ok": False, "error": "Invalid name"}), 400

    accounts = load_accounts()
    if any(a["id"] == aid for a in accounts):
        return jsonify({"ok": False, "error": "Account already exists"}), 409

    new_acct = {
        "id": aid,
        "name": name,
        "source_channels": [ch.strip() for ch in body.get("source_channels", "").split(",") if ch.strip()],
        "youtube_client_secret": f"client_secret_{aid}.json",
        "youtube_token": f"youtube_token_{aid}.json",
        "default_tags": body.get("default_tags", "#shorts"),
        "clip_prompt_context": body.get("clip_prompt_context", name),
        "category_id": body.get("category_id", "22"),
    }
    accounts.append(new_acct)
    save_accounts(accounts)

    # Create directories
    get_account_dirs(aid)
    get_account_files(aid)

    # Add scheduler jobs for new account
    scheduler.add_job(
        _make_process_job(aid), "cron", hour=6, minute=0,
        id=f"process_{aid}", name=f"Process [{name}]", replace_existing=True,
    )
    scheduler.add_job(
        _make_post_job(aid), "interval", minutes=5,
        id=f"post_{aid}", name=f"Post [{name}] (5 min)", replace_existing=True,
    )

    return jsonify({"ok": True, "account": new_acct})


# ---------------------------------------------------------------------------
# Routes — Dashboard (account-scoped)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/")
def dashboard(account_id):
    acct = get_account(account_id)
    if not acct:
        return redirect(url_for("index"))

    dirs = get_account_dirs(account_id)
    queue = get_queue(queue_dir=dirs["queue"])
    settings = load_settings(account_id)
    history = _get_history(account_id)
    pending = [c for c in queue if not c.get("approved", False)]
    approved = [c for c in queue if c.get("approved", False)]
    posted_clips = list(dirs["posted"].glob("*.mp4"))
    status = _get_job_status(account_id)

    scheduled_jobs = []
    for job in scheduler.get_jobs():
        if account_id in job.id:
            scheduled_jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.strftime("%Y-%m-%d %H:%M") if job.next_run_time else "—",
            })

    return render_template("dashboard.html",
        account=acct,
        accounts=load_accounts(),
        queue=queue,
        pending=pending,
        approved=approved,
        history=history[-20:][::-1],
        settings=settings,
        job_status=status,
        scheduled_jobs=scheduled_jobs,
        posted_count=len(posted_clips),
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.route("/<account_id>/edit/<path:filename>")
def edit_page(account_id, filename):
    acct = get_account(account_id)
    if not acct:
        return redirect(url_for("index"))
    dirs = get_account_dirs(account_id)
    queue_file = dirs["queue"] / filename
    if not queue_file.exists():
        return redirect(url_for("dashboard", account_id=account_id))
    clip = json.loads(queue_file.read_text())
    clip["_queue_file"] = filename
    vname = Path(clip.get("clip_path", "")).name
    clip["video_filename"] = vname
    if "tags" not in clip:
        clip["tags"] = acct.get("default_tags", "#shorts")
    if "scheduled_time" not in clip:
        settings = load_settings(account_id)
        times = settings.get("post_times", ["08:00"])
        clip["scheduled_time"] = times[0] if times else "08:00"

    settings = load_settings(account_id)
    return render_template("edit_clip.html", clip=clip, filename=filename,
                           settings=settings, account=acct, accounts=load_accounts())


# ---------------------------------------------------------------------------
# Routes — Queue actions (account-scoped)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/api/queue/approve/<path:filename>", methods=["POST"])
def approve_clip(account_id, filename):
    dirs = get_account_dirs(account_id)
    queue_file = dirs["queue"] / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        data["approved"] = True
        queue_file.write_text(json.dumps(data, indent=2))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/<account_id>/api/queue/reject/<path:filename>", methods=["POST"])
def reject_clip(account_id, filename):
    dirs = get_account_dirs(account_id)
    queue_file = dirs["queue"] / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        clip_path = Path(data.get("clip_path", ""))
        if clip_path.exists():
            clip_path.unlink()
        queue_file.unlink()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/<account_id>/api/queue/approve-all", methods=["POST"])
def approve_all(account_id):
    dirs = get_account_dirs(account_id)
    for f in dirs["queue"].glob("*.json"):
        data = json.loads(f.read_text())
        data["approved"] = True
        f.write_text(json.dumps(data, indent=2))
    return jsonify({"ok": True})


@app.route("/<account_id>/api/queue/edit/<path:filename>", methods=["POST"])
def edit_clip(account_id, filename):
    dirs = get_account_dirs(account_id)
    queue_file = dirs["queue"] / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        body = request.get_json() or request.form
        for field in ["title", "description", "hook", "tags", "scheduled_time", "timezone"]:
            if field in body:
                data[field] = body[field]
        queue_file.write_text(json.dumps(data, indent=2))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/<account_id>/api/queue/<path:filename>")
def get_clip_data(account_id, filename):
    dirs = get_account_dirs(account_id)
    queue_file = dirs["queue"] / filename
    if queue_file.exists():
        data = json.loads(queue_file.read_text())
        acct = get_account(account_id) or {}
        if "tags" not in data:
            data["tags"] = acct.get("default_tags", "#shorts")
        if "scheduled_time" not in data:
            settings = load_settings(account_id)
            times = settings.get("post_times", ["08:00"])
            data["scheduled_time"] = times[0] if times else "08:00"
        vname = Path(data.get("clip_path", "")).name
        data["video_filename"] = vname
        data["queue_filename"] = filename
        return jsonify(data)
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# Routes — Video preview (account-scoped)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/preview/<path:filename>")
def preview_clip(account_id, filename):
    dirs = get_account_dirs(account_id)
    clip_path = dirs["clips"] / filename
    if not clip_path.exists():
        for f in dirs["queue"].glob("*.json"):
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
# Routes — Manual triggers (account-scoped)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/api/process-now", methods=["POST"])
def trigger_process(account_id):
    status = _get_job_status(account_id)
    if status["processing"]:
        return jsonify({"ok": False, "error": "Already processing"})
    thread = threading.Thread(target=_make_process_job(account_id), daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Processing started"})


@app.route("/<account_id>/api/post-now", methods=["POST"])
def trigger_post(account_id):
    status = _get_job_status(account_id)
    if status["posting"]:
        return jsonify({"ok": False, "error": "Already posting"})
    thread = threading.Thread(target=_make_post_now(account_id), daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Posting started"})


# ---------------------------------------------------------------------------
# Routes — Settings (account-scoped)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/api/settings", methods=["POST"])
def update_settings(account_id):
    body = request.get_json() or request.form.to_dict()
    settings = load_settings(account_id)

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

    save_settings(settings, account_id)

    # Also update account source_channels in the registry
    if "source_channels" in body:
        accounts = load_accounts()
        for a in accounts:
            if a["id"] == account_id:
                a["source_channels"] = settings["source_channels"]
        save_accounts(accounts)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — Logs (shared)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/api/logs")
def get_logs(account_id):
    log_path = config.LOG_DIR / "clipper.log"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": lines[-200:]})
    return jsonify({"lines": []})


# ---------------------------------------------------------------------------
# Routes — Status API (account-scoped)
# ---------------------------------------------------------------------------

@app.route("/<account_id>/api/status")
def get_status(account_id):
    dirs = get_account_dirs(account_id)
    queue = get_queue(queue_dir=dirs["queue"])
    pending = [c for c in queue if not c.get("approved", False)]
    approved = [c for c in queue if c.get("approved", False)]
    return jsonify({
        "queue_total": len(queue),
        "pending": len(pending),
        "approved": len(approved),
        "posted_total": len(list(dirs["posted"].glob("*.mp4"))),
        "job_status": _get_job_status(account_id),
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _rebuild_scheduler()
    scheduler.start()
    logger.info(f"Dashboard starting on http://localhost:{config.DASHBOARD_PORT}")
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT, debug=False)
