"""
Uploads clips to YouTube as Shorts using the YouTube Data API v3.
Handles OAuth2 authentication and scheduled uploads.
"""
import json
import logging
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def get_youtube_service(client_secret_path: Path | str | None = None,
                        token_path: Path | str | None = None):
    """Authenticate and return a YouTube API service instance.

    Args:
        client_secret_path: Path to the OAuth client secret JSON.
            Defaults to the legacy global config value.
        token_path: Path to the saved OAuth token JSON.
            Defaults to the legacy global config value.
    """
    if client_secret_path is None:
        client_secret_path = config.PROJECT_DIR / config.YOUTUBE_CLIENT_SECRET_FILE
    else:
        client_secret_path = Path(client_secret_path)

    if token_path is None:
        token_path = config.YOUTUBE_TOKEN_FILE
    else:
        token_path = Path(token_path)

    creds = None

    # Load saved credentials
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            if not client_secret_path.exists():
                raise FileNotFoundError(
                    f"YouTube client secret file not found: {client_secret_path}\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_short(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str] | None = None,
    category_id: str = "25",
    client_secret_path: Path | str | None = None,
    token_path: Path | str | None = None,
) -> str | None:
    """
    Upload a video as a YouTube Short.

    Returns the video ID if successful, None otherwise.
    """
    if tags is None:
        tags = [
            "JohnKiriakou", "CIA", "whistleblower", "podcast",
            "shorts", "clips", "intelligence", "politics",
        ]

    # YouTube Shorts must have #Shorts in title or description
    if "#Shorts" not in title and "#Shorts" not in description:
        description += "\n\n#Shorts"

    # Ensure title is within YouTube's 100 char limit
    title = title[:100]

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        youtube = get_youtube_service(client_secret_path, token_path)
        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=256 * 1024,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        logger.info(f"Uploading: {title}")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response["id"]
        logger.info(f"Upload complete! Video ID: {video_id}")
        logger.info(f"URL: https://youtube.com/shorts/{video_id}")
        return video_id

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return None
