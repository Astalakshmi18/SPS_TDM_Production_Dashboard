"""
Google Sheet import support.

A project's tracker can live as a Google Sheet instead of an uploaded .xlsx -
same mapping engine, same standard schema, only the source of the bytes
differs. This module resolves any of the common Google Sheets share-link
shapes to the sheet's ID, downloads it as .xlsx, and saves it to disk so the
existing mapping engine (which needs a real file path for pandas/openpyxl)
can read it exactly like an upload.

Auth model: OAuth2 as a specific Google account - NOT "Anyone with the link
can view". The sheet only needs to be shared with one Google account (role:
Viewer is enough), exactly like sharing it with a person. The server signs
in as that account using a long-lived refresh token and calls the Drive API
export endpoint, so it can read anything that account has been given access
to without the sheet ever being publicly link-accessible.

One-time setup to connect an account (see SETUP_GSHEET_OAUTH.md in the repo
root for the full click-by-click steps):
    1. Create an OAuth Client ID (type: Desktop app) in Google Cloud Console.
    2. Using the OAuth Playground (or equivalent), sign in as the Google
       account that was given Viewer access to the sheet(s), and generate a
       refresh token for the scope https://www.googleapis.com/auth/drive.readonly
    3. Set these env vars on the server (Render dashboard -> Environment):
         GOOGLE_OAUTH_CLIENT_ID
         GOOGLE_OAUTH_CLIENT_SECRET
         GOOGLE_OAUTH_REFRESH_TOKEN
"""
import re
import uuid

import requests
from django.conf import settings

SHEET_ID_PATTERNS = [
    r"/spreadsheets/d/([a-zA-Z0-9-_]+)",  # standard share link
    r"^([a-zA-Z0-9-_]{20,})$",             # bare sheet ID pasted directly
]

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{file_id}/export"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class GoogleSheetError(Exception):
    pass


def extract_sheet_id(url_or_id: str) -> str:
    url_or_id = url_or_id.strip()
    for pattern in SHEET_ID_PATTERNS:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    raise GoogleSheetError("Could not find a Google Sheet ID in that link.")


def _get_access_token() -> str:
    """Exchanges the long-lived refresh token for a short-lived access
    token. This authenticates as whichever Google account the refresh
    token belongs to - i.e. the account that was given Viewer access to
    the sheet(s) - so no sheet needs to be publicly link-shared."""
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    refresh_token = getattr(settings, "GOOGLE_OAUTH_REFRESH_TOKEN", "")

    if not (client_id and client_secret and refresh_token):
        raise GoogleSheetError(
            "No Google account is connected yet. Set GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REFRESH_TOKEN as env "
            "vars - see SETUP_GSHEET_OAUTH.md for the one-time steps."
        )

    try:
        response = requests.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=15)
    except requests.RequestException as exc:
        raise GoogleSheetError(f"Could not reach Google to refresh the access token: {exc}") from exc

    if response.status_code != 200:
        raise GoogleSheetError(
            f"Google rejected the stored credentials (HTTP {response.status_code}). "
            "The refresh token may have been revoked or the connected account's "
            "password/security settings changed - redo the one-time setup in "
            "SETUP_GSHEET_OAUTH.md."
        )

    token = response.json().get("access_token")
    if not token:
        raise GoogleSheetError("Google did not return an access token.")
    return token


def download_as_xlsx(url_or_id: str) -> str:
    """Downloads the sheet (as the connected Google account) and returns
    the local file path it was saved to."""
    sheet_id = extract_sheet_id(url_or_id)
    access_token = _get_access_token()

    try:
        response = requests.get(
            DRIVE_EXPORT_URL.format(file_id=sheet_id),
            params={"mimeType": XLSX_MIME},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GoogleSheetError(f"Could not reach Google Sheets: {exc}") from exc

    if response.status_code == 404:
        raise GoogleSheetError(
            "Sheet not found, or the connected Google account doesn't have "
            "access to it. Share the sheet with that account (Viewer is "
            "enough) and try again."
        )
    if response.status_code == 403:
        raise GoogleSheetError(
            "The connected Google account was denied access to this sheet. "
            "Make sure it has at least Viewer permission on it."
        )
    if response.status_code != 200:
        raise GoogleSheetError(f"Google Sheets returned HTTP {response.status_code}.")

    uploads_dir = settings.MEDIA_ROOT / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"gsheet_{sheet_id[:8]}_{uuid.uuid4().hex[:6]}.xlsx"
    file_path = uploads_dir / file_name
    file_path.write_bytes(response.content)

    return str(file_path)
