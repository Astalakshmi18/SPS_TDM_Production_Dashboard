"""
In-process auto-sync scheduler.

Runs entirely inside this server's own process (inside the single gunicorn
worker) - no external service ever sees the sync logic, the OAuth token, or
any project data. It simply calls resync_project() for every project with a
linked Google Sheet, every AUTO_SYNC_INTERVAL_MINUTES.

Why this instead of an external cron-ping service: an external pinger would
need a URL (with a secret token) to trigger the sync, and would receive a
JSON response back - a small but real exposure. Running the timer in-process
means nothing about syncing ever leaves the server. The trade-off: Render's
free plan spins a web service down after ~15 minutes with no incoming HTTP
traffic, which would also pause this in-process timer. See
AUTO_SYNC_SETUP.md for the (privacy-neutral) fix - a plain uptime pinger
that only ever touches the homepage, never this app's sync logic.
"""
import logging
import threading

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _run_sync_all():
    from django.conf import settings
    from .gsheet import GoogleSheetError
    from .import_engine import resync_project
    from .models import Project

    interval = getattr(settings, "AUTO_SYNC_INTERVAL_MINUTES", 30)
    projects = list(Project.objects.exclude(google_sheet_url=""))
    synced, failed = 0, 0
    for project in projects:
        try:
            _updated, errors = resync_project(project)
        except GoogleSheetError as exc:
            failed += 1
            logger.warning("Auto-sync failed for project %s: %s", project.pk, exc)
            continue
        if errors:
            failed += 1
        else:
            synced += 1
    logger.info(
        "Auto-sync run complete: %s synced, %s failed, %s linked project(s) (next run in %s min)",
        synced, failed, len(projects), interval,
    )


def start():
    """Starts the background scheduler exactly once per process."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    from django.conf import settings

    if not getattr(settings, "ENABLE_AUTO_SYNC_SCHEDULER", False):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning(
            "ENABLE_AUTO_SYNC_SCHEDULER is on but APScheduler isn't installed - "
            "add 'APScheduler' to requirements.txt."
        )
        return

    interval = getattr(settings, "AUTO_SYNC_INTERVAL_MINUTES", 30)
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_sync_all,
        "interval",
        minutes=interval,
        id="gsheet_auto_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Auto-sync scheduler started (every %s minutes).", interval)
