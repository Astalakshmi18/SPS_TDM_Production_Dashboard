"""
Shows Google's RAW error response for a sheet download, instead of our
code's simplified message - for debugging a 403/404 that doesn't make
sense given the sharing looks correct.

Usage:
    python debug_gsheet.py "<google sheet link>"
"""
import os
import re
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import requests  # noqa: E402
from apps.projects.gsheet import _get_access_token, extract_sheet_id, GoogleSheetError  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_gsheet.py \"<google sheet link>\"")
        sys.exit(1)

    link = sys.argv[1]
    sheet_id = extract_sheet_id(link)
    print("Sheet ID:", sheet_id)

    try:
        token = _get_access_token()
    except GoogleSheetError as exc:
        print("FAILED to get access token:", exc)
        sys.exit(1)

    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{sheet_id}/export",
        params={"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print("Status:", resp.status_code)
    print("Raw response body:")
    print(resp.text[:3000])

    # Bonus: also check file metadata (a lighter call) to see what Drive
    # itself thinks about this file/access, independent of the export step.
    meta = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{sheet_id}",
        params={"fields": "id,name,owners,capabilities,mimeType"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print("\nMetadata check status:", meta.status_code)
    print(meta.text[:2000])