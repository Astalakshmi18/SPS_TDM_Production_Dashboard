"""
Quick standalone test for the Google Sheet OAuth connection.

Run this BEFORE running the full dashboard, to check the
GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN
values actually work, without needing the server, database, or login.

Usage:
    python test_gsheet.py "PASTE_YOUR_GOOGLE_SHEET_LINK_HERE"
"""
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.projects.gsheet import GoogleSheetError, download_as_xlsx  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_gsheet.py \"<google sheet link>\"")
        sys.exit(1)

    link = sys.argv[1]
    print(f"Trying to download: {link}")
    try:
        path = download_as_xlsx(link)
    except GoogleSheetError as exc:
        print("FAILED:", exc)
        sys.exit(1)

    size_kb = os.path.getsize(path) / 1024
    print(f"SUCCESS - saved to {path} ({size_kb:.1f} KB)")
    print("The OAuth connection works. You can now run the full server.")
