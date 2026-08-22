"""
Google Sheet import support.

A project's tracker can now live as a Google Sheet instead of an uploaded
.xlsx - same mapping engine, same standard schema, the only difference is
where the bytes come from. This module resolves any of the common Google
Sheets share-link shapes to the sheet's ID, downloads it as .xlsx (Google
Sheets supports this via the /export endpoint), and saves it to disk so the
existing mapping engine (which needs a real file path for pandas/openpyxl)
can read it exactly like an upload.

Requirements on the sheet: "Anyone with the link can view" sharing must be
enabled - this uses the anonymous export endpoint, no OAuth/service account
needed. If the sheet is private, the download will come back as an HTML
login page instead of a workbook, and we raise a clear error for that.
"""
import re
import uuid

import requests
from django.conf import settings

SHEET_ID_PATTERNS = [
    r"/spreadsheets/d/([a-zA-Z0-9-_]+)",  # standard share link
    r"^([a-zA-Z0-9-_]{20,})$",             # bare sheet ID pasted directly
]


class GoogleSheetError(Exception):
    pass


def extract_sheet_id(url_or_id: str) -> str:
    url_or_id = url_or_id.strip()
    for pattern in SHEET_ID_PATTERNS:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    raise GoogleSheetError("Could not find a Google Sheet ID in that link.")


def download_as_xlsx(url_or_id: str) -> str:
    """Downloads the sheet and returns the local file path it was saved to."""
    sheet_id = extract_sheet_id(url_or_id)
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"

    try:
        response = requests.get(export_url, timeout=30)
    except requests.RequestException as exc:
        raise GoogleSheetError(f"Could not reach Google Sheets: {exc}") from exc

    if response.status_code != 200:
        raise GoogleSheetError(
            f"Google Sheets returned HTTP {response.status_code}. "
            "Make sure link sharing is set to 'Anyone with the link can view'."
        )

    content_type = response.headers.get("Content-Type", "")
    if "spreadsheet" not in content_type and "octet-stream" not in content_type:
        raise GoogleSheetError(
            "That didn't come back as a spreadsheet - the sheet is probably "
            "private. Set sharing to 'Anyone with the link can view' and try again."
        )

    uploads_dir = settings.MEDIA_ROOT / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"gsheet_{sheet_id[:8]}_{uuid.uuid4().hex[:6]}.xlsx"
    file_path = uploads_dir / file_name
    file_path.write_bytes(response.content)

    return str(file_path)
