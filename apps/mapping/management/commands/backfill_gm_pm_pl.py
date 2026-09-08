"""
One-time backfill: adds the pm_name/gm_name/pl_name (and, where safe,
branch_manpower_count/inhouse_manpower_count) mapping rules to every
EXISTING ProjectTemplate that matches the standard PM02 layout (Version
Control + Project Summary sheets) and doesn't already have them - these
templates were created and saved to the DB *before* those rules existed in
apps/mapping/autodetect.py, so newly-added code alone never touches their
already-stored config JSON. New projects imported from now on already get
these rules automatically (autodetect.py); this command is only needed once,
to catch up every project template that already existed.

pm_name/gm_name/pl_name are added unconditionally (every PM02-standard
workbook has a Version Control sheet by definition of matching that
signature). branch_manpower_count/inhouse_manpower_count and
weekly_delivery_rows are only added after actually downloading that
project's linked Google Sheet and confirming the sheet they depend on
("Project Insights" / "Weekly Delivery Plan") is present - avoids adding a
rule for a sheet a particular project doesn't actually have. A project
without a linked Google Sheet (manual-upload-only) is skipped for these
checks - re-uploading its file manually re-runs autodetect.py fresh, which
does this check safely on the fly instead.

After patching a template's config, this also re-syncs every Project using
it that has a linked Google Sheet, so the new columns populate right away
instead of waiting for the next scheduled/manual sync.

Usage:
    python manage.py backfill_gm_pm_pl            # patches + re-syncs
    python manage.py backfill_gm_pm_pl --dry-run   # shows what WOULD change, touches nothing
"""
from django.core.management.base import BaseCommand

from apps.mapping.models import ProjectTemplate
from apps.projects.gsheet import GoogleSheetError, download_as_xlsx
from apps.projects.models import Project

TEAM_RULES = {
    "pm_name": {"mode": "header", "sheet": "Version Control", "column": "Prepapred by", "header_row": 2, "row": -1},
    "gm_name": {"mode": "header", "sheet": "Version Control", "column": "Approved by", "header_row": 2, "row": -1},
    "pl_name": {"mode": "header", "sheet": "Version Control", "column": "PL Name", "header_row": 2, "row": -1},
}
MANPOWER_RULES = {
    "branch_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Branch.1", "header_row": 18, "row": -1},
    "inhouse_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Inhouse.1", "header_row": 18, "row": -1},
}


def _find_weekly_plan_sheet(sheet_names):
    """Same loose match as autodetect.py: 'weekly' + ('delivery' or 'plan')
    anywhere in the tab name, not an exact string - so a project whose tab
    is worded differently ("Weekly Plan", "Weekly Delivery Tracker") is
    still found."""
    if not sheet_names:
        return None
    return next(
        (s for s in sheet_names if "weekly" in s.lower() and ("delivery" in s.lower() or "plan" in s.lower())),
        None,
    )


def _is_pm02_standard_config(config: dict) -> bool:
    pn = config.get("project_name") or {}
    return pn.get("mode") == "cell" and pn.get("sheet") == "Version Control" and pn.get("cell") == "B1"


def _downloaded_sheet_names(project):
    """Downloads this project's linked Google Sheet (if any) purely to see
    which tabs it has - returns None (never raises) on any problem, since
    this is only a safety gate deciding which optional rules are safe to
    add, not the actual sync."""
    if not project or not project.google_sheet_url:
        return None
    try:
        import openpyxl

        path = download_as_xlsx(project.google_sheet_url)
        wb = openpyxl.load_workbook(path, read_only=True)
        try:
            return set(wb.sheetnames)
        finally:
            wb.close()
    except Exception:
        return None


class Command(BaseCommand):
    help = "Backfills pm_name/gm_name/pl_name (and manpower, where safe) mapping rules onto existing PM02-standard ProjectTemplates and re-syncs their projects."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving or syncing anything.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        patched = []

        for template in ProjectTemplate.objects.all():
            config = template.config or {}
            if not _is_pm02_standard_config(config):
                continue

            missing = {k: v for k, v in TEAM_RULES.items() if k not in config}

            missing_manpower_keys = [k for k in MANPOWER_RULES if k not in config]
            missing_weekly = "weekly_delivery_rows" not in config
            if missing_manpower_keys or missing_weekly:
                sample_project = Project.objects.filter(project_key=template.project_key).exclude(google_sheet_url="").first()
                sheet_names = _downloaded_sheet_names(sample_project)

                if missing_manpower_keys:
                    if sheet_names and "Project Insights" in sheet_names:
                        missing.update({k: MANPOWER_RULES[k] for k in missing_manpower_keys})
                        self.stdout.write(f"[{template.project_key}] 'Project Insights' sheet confirmed - including manpower rules.")
                    else:
                        self.stdout.write(f"[{template.project_key}] no 'Project Insights' sheet found (or no linked Google Sheet to check) - skipping manpower rules.")

                if missing_weekly:
                    weekly_sheet = _find_weekly_plan_sheet(sheet_names)
                    if weekly_sheet:
                        missing["weekly_delivery_rows"] = {"sheet": weekly_sheet}
                        self.stdout.write(f"[{template.project_key}] '{weekly_sheet}' sheet confirmed - including weekly_delivery_rows.")
                    else:
                        self.stdout.write(f"[{template.project_key}] no weekly-plan-looking sheet found (or no linked Google Sheet to check) - skipping.")

            if not missing:
                continue

            self.stdout.write(f"[{template.project_key}] adding: {', '.join(missing.keys())}")
            if not dry_run:
                config.update(missing)
                template.config = config
                template.save(update_fields=["config", "updated_at"])
            patched.append(template)

        if not patched:
            self.stdout.write(self.style.SUCCESS("No templates needed patching - all already up to date."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run - {len(patched)} template(s) would be patched. Re-run without --dry-run to apply."))
            return

        self.stdout.write(self.style.SUCCESS(f"Patched {len(patched)} template(s). Re-syncing their linked projects..."))

        from apps.projects.import_engine import resync_project

        synced, skipped, failed = 0, 0, 0
        for template in patched:
            projects = Project.objects.filter(project_key=template.project_key).exclude(google_sheet_url="")
            for project in projects:
                try:
                    _updated, errors = resync_project(project)
                except GoogleSheetError as exc:
                    errors = [str(exc)]
                if errors:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f"  [{project.project_name}] sync failed: {errors}"))
                else:
                    synced += 1
                    self.stdout.write(f"  [{project.project_name}] re-synced.")
            if not projects.exists():
                skipped += 1
                self.stdout.write(f"  [{template.project_key}] no Google-Sheet-linked project to auto-sync - use 'Sync Now' or re-upload manually.")

        self.stdout.write(self.style.SUCCESS(f"Done. {synced} project(s) re-synced, {failed} failed, {skipped} template(s) had nothing to auto-sync."))
