"""
Checks which Google account the saved OAuth refresh token actually belongs
to. Run this if sheet imports fail with "access denied" / "not found" even
though the sheet IS shared with the account you think is connected.

Usage:
    python whoami.py
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import requests  # noqa: E402
from apps.projects.gsheet import _get_access_token, GoogleSheetError  # noqa: E402

if __name__ == "__main__":
    try:
        token = _get_access_token()
    except GoogleSheetError as exc:
        print("FAILED to get access token:", exc)
        raise SystemExit(1)

    resp = requests.get(
        "https://www.googleapis.com/drive/v3/about",
        params={"fields": "user"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    print("Status:", resp.status_code)
    print(resp.json())
