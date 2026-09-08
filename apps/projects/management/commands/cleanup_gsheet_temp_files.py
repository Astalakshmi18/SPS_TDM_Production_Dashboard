"""
One-time cleanup: deletes leftover gsheet_*.xlsx temp files sitting in
media/uploads/ from BEFORE the fix in import_engine.py/views.py that now
deletes each one right after it's imported. Safe to run any time - these
files are disposable Google Sheet downloads (a text label of the filename
is kept on the ImportBatch audit record, not a live reference to the file
itself - see apps/projects/models.py), never re-read after their import
completes, so nothing currently uses them.

Only touches files matching the gsheet_*.xlsx naming pattern - a manually
uploaded file (any other name) is left alone.

Usage:
    python manage.py cleanup_gsheet_temp_files            # deletes them
    python manage.py cleanup_gsheet_temp_files --dry-run   # lists what WOULD be deleted, touches nothing
"""
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deletes leftover gsheet_*.xlsx temp files in media/uploads/ (safe - these are never re-read after import)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List what would be deleted without deleting anything.")

    def handle(self, *args, **options):
        uploads_dir = settings.MEDIA_ROOT / "uploads"
        if not uploads_dir.exists():
            self.stdout.write("No media/uploads/ directory found - nothing to clean up.")
            return

        matches = sorted(uploads_dir.glob("gsheet_*.xlsx"))
        if not matches:
            self.stdout.write(self.style.SUCCESS("No leftover gsheet_*.xlsx files found - already clean."))
            return

        total_bytes = sum(f.stat().st_size for f in matches)
        total_mb = total_bytes / (1024 * 1024)

        if options["dry_run"]:
            self.stdout.write(f"Would delete {len(matches)} file(s), freeing {total_mb:.1f} MB:")
            for f in matches:
                self.stdout.write(f"  {f.name}")
            self.stdout.write(self.style.WARNING("Dry run - nothing deleted. Re-run without --dry-run to actually delete."))
            return

        deleted, failed = 0, 0
        for f in matches:
            try:
                f.unlink()
                deleted += 1
            except OSError as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  Could not delete {f.name}: {exc}"))

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} file(s), freed ~{total_mb:.1f} MB. {failed} failed."))
