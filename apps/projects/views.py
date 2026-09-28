import csv
import datetime
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.decorators import accessible_branches, accessible_projects, branch_queryset, role_required
from apps.accounts.models import UserProfile
from apps.branches.models import Branch
from apps.mapping.models import ProjectTemplate
from .gsheet import GoogleSheetError, download_as_xlsx
from .import_engine import _safe_int, resync_project, run_import
from .models import ImportBatch, Project


@login_required
def project_list(request):
    projects_qs = accessible_projects(request).select_related("branch")

    q = request.GET.get("q", "").strip()
    branch_code = request.GET.get("branch", "")
    status_filter = request.GET.get("status", "")

    if q:
        projects_qs = projects_qs.filter(
            Q(project_name__icontains=q) |
            Q(customer_name__icontains=q) |
            Q(gm_name__icontains=q) |
            Q(pm_name__icontains=q) |
            Q(pl_name__icontains=q)
        )
    if branch_code:
        projects_qs = projects_qs.filter(branch__code=branch_code)

    if status_filter:
        projects = [p for p in projects_qs if p.status == status_filter]
    else:
        projects = list(projects_qs)

    branches = accessible_branches(request)

    return render(request, "projects/list.html", {
        "projects": projects,
        "q": q,
        "branch_code": branch_code,
        "status_filter": status_filter,
        "branch_choices": [(b.code, b.name) for b in branches],
        "show_branch_filter": branches.count() > 1,
    })


AUTO_SYNC_THROTTLE_SECONDS = 300


def _get_daily_metrics_context(project):
    daily_metrics_qs = project.daily_operational_metrics.values("date", "metric_key", "value")
    daily_metrics_map = {}
    for row in daily_metrics_qs:
        d = row["date"].isoformat()
        if d not in daily_metrics_map:
            daily_metrics_map[d] = {"branch_receipt": 0.0, "rqc_completed": 0.0}
        if row["metric_key"] == "branch_receipt":
            daily_metrics_map[d]["branch_receipt"] = row["value"]
        elif row["metric_key"] == "rqc_completed":
            daily_metrics_map[d]["rqc_completed"] = row["value"]

    latest_metric = project.daily_operational_metrics.order_by("-date").first()
    latest_metric_date = latest_metric.date.isoformat() if latest_metric else ""

    return {
        "daily_metrics_json": json.dumps(daily_metrics_map),
        "latest_metric_date": latest_metric_date,
        "project_start_iso": project.start_date.isoformat() if project.start_date else "",
        "project_end_iso": project.end_date.isoformat() if project.end_date else "",
    }


@login_required
def project_detail(request, pk):
    project = get_object_or_404(accessible_projects(request), pk=pk)

    # Auto-sync: pulls the latest Google Sheet data automatically whenever
    # the page is opened, so nobody has to click "Sync Now" first to see
    # today's numbers. Throttled per project and silent on failure - the
    # "Sync Now" button is still right there and will surface any error.
    # Auto-sync: pulls latest Google Sheet data in the background so page load
    # never hangs on external Google Sheets API network calls.
    if project.google_sheet_url and project.sync_token:
        throttle_key = f"project_autosync_{project.pk}"
        if not cache.get(throttle_key):
            cache.set(throttle_key, True, AUTO_SYNC_THROTTLE_SECONDS)
            import threading
            def _bg_autosync(proj_id, user_obj):
                try:
                    from apps.projects.models import Project as PModel
                    p = PModel.objects.filter(pk=proj_id).first()
                    if p:
                        resync_project(p, user=user_obj)
                except Exception:
                    pass
            threading.Thread(target=_bg_autosync, args=(project.pk, request.user), daemon=True).start()

    webhook_url = None
    if project.google_sheet_url and project.sync_token:
        webhook_url = request.build_absolute_uri(
            f"/projects/webhook/{project.pk}/{project.sync_token}/"
        )

    months = project.weekly_delivery_plan()
    weekly_rows = []
    total_monthly_plan = 0
    total_monthly_actual = 0
    total_monthly_variance = 0

    for m in months:
        p = m["monthly_plan"] or 0
        a = m["monthly_actual"] or 0
        v = m["monthly_variance"] or 0
        total_monthly_plan += p
        total_monthly_actual += a
        total_monthly_variance += v
        if p > 0:
            m["display_variance_pct"] = round((v / p) * 100, 1)
        else:
            m["display_variance_pct"] = 0.0

        for w in m["weeks"]:
            wp = w.plan_records or 0
            wa = w.actual_records or 0
            wv = w.variance or 0
            if wp > 0:
                w.display_variance_pct = round((wv / wp) * 100, 1)
            else:
                w.display_variance_pct = 0.0
            global_week_num = len(weekly_rows) + 1
            weekly_rows.append({"month_label": m["month_label"], "week": w, "global_week_num": global_week_num})

    monthly_totals = {
        "plan": total_monthly_plan,
        "actual": total_monthly_actual,
        "variance": total_monthly_variance,
        "variance_pct": round((total_monthly_variance / total_monthly_plan * 100), 1) if total_monthly_plan > 0 else 0.0,
    }

    monthly_chart = {
        "labels": [m["month_label"] for m in months],
        "plan": [m["monthly_plan"] for m in months],
        "actual": [m["monthly_actual"] for m in months],
    }
    weekly_chart = {
        "labels": [f'{r["month_label"]} Week-{r["global_week_num"]}' for r in weekly_rows],
        "plan": [r["week"].plan_records for r in weekly_rows],
        "actual": [r["week"].actual_records for r in weekly_rows],
    }

    if request.method == "POST" and hasattr(request.user, "profile") and request.user.profile.can_edit_projects:
        if "update_milestones" in request.POST:
            if not request.user.profile.is_admin:
                messages.error(request, "Only administrators are allowed to edit milestone target dates.")
                return redirect("projects:detail", pk=pk)
            if project.is_ancestry_client:
                project.milestone_10_date = _safe_date(request.POST.get("milestone_10_date"))
                project.milestone_50_date = _safe_date(request.POST.get("milestone_50_date"))
                project.milestone_100_date = _safe_date(request.POST.get("milestone_100_date"))
            else:
                project.milestone_10_date = None
                project.milestone_50_date = None
                project.milestone_100_date = None
            project.save(update_fields=["milestone_10_date", "milestone_50_date", "milestone_100_date"])
            messages.success(request, "Milestone checkpoint dates updated.")
            return redirect("projects:detail", pk=pk)

        delivered_col = request.POST.get("delivered_column_key", "").strip()
        received_col = request.POST.get("received_column_key", "").strip()
        project.delivered_column_key = delivered_col
        project.received_column_key = received_col

        if "batches_status_column_key" in request.POST:
            project.batches_status_column_key = request.POST.get("batches_status_column_key", "").strip()
            project.batches_keyed_value = request.POST.get("batches_keyed_value", "").strip()
            project.batches_end_date_column_key = request.POST.get("batches_end_date_column_key", "").strip()

        if "branch_receipt_column_key" in request.POST or "rqc_completed_column_key" in request.POST or "rqc_quality_column_key" in request.POST:
            project.branch_receipt_column_key = request.POST.get("branch_receipt_column_key", "").strip()
            project.rqc_completed_column_key = request.POST.get("rqc_completed_column_key", "").strip()
            project.rqc_quality_column_key = request.POST.get("rqc_quality_column_key", "").strip()

        project.save(update_fields=[
            "delivered_column_key", "received_column_key",
            "batches_status_column_key", "batches_keyed_value", "batches_end_date_column_key",
            "branch_receipt_column_key", "rqc_completed_column_key", "rqc_quality_column_key",
        ])
        messages.success(request, "Selected columns saved.")
        return redirect("projects:detail", pk=pk)

    weekly_totals = {
        "plan": sum((r["week"].plan_records or 0) for r in weekly_rows),
        "actual": sum((r["week"].actual_records or 0) for r in weekly_rows),
        "variance": sum((r["week"].variance or 0) for r in weekly_rows),
    }
    weekly_totals["variance_pct"] = (
        round((weekly_totals["variance"] / weekly_totals["plan"]) * 100, 1) if weekly_totals["plan"] > 0 else 0.0
    )

    cps = {c["label"]: c for c in project.milestone_shipment_checkpoints()}
    detailed_milestones = []
    today = timezone.localdate()
    for m in project.milestones():
        lbl = m["label"]
        target_pct = m["expected_pct"]
        m_date = m["date"]
        cp = cps.get(lbl)
        if cp:
            pct_by = cp["pct_by"]
        elif lbl == "IDX Start":
            shipped_start = project.shipped_records_by(m_date)
            pct_by = round(min(shipped_start / project.target_records, 1) * 100, 2) if project.target_records else 0.0
        else:
            pct_by = 0.0
        cp_status = cp["status"] if cp else m["status"]

        if lbl == "IDX Start" or pct_by >= target_pct:
            cat_key = "met"
            cat_badge = "Met"
            cat_label = "Milestone Met"
        elif today <= m_date:
            if cp_status == "green":
                cat_key = "ontrack"
                cat_badge = "On Track"
                cat_label = "Future Milestone – On Track"
            else:
                cat_key = "atrisk"
                cat_badge = "At Risk"
                cat_label = "Future Milestone – At Risk"
        else:
            if project.delivery_percent >= target_pct:
                cat_key = "latecomplete"
                cat_badge = "Complete"
                cat_label = "Milestone Missed – Now Complete"
            else:
                cat_key = "missed"
                cat_badge = "Missed"
                cat_label = "Milestone Missed – Incomplete"

        detailed_milestones.append({
            "label": lbl,
            "date": m_date,
            "expected_pct": target_pct,
            "pct_by": pct_by,
            "actual_pct": project.delivery_percent,
            "category": cat_key,
            "cat_badge": cat_badge,
            "cat_label": cat_label,
            "reached": today >= m_date,
            "status": cp_status,
            "is_manual": m.get("is_manual", False),
        })

    ctx = {
        "project": project,
        "milestones": detailed_milestones,
        "milestones_completed_count": sum(1 for m in detailed_milestones if m["category"] in ("met", "latecomplete")),
        "webhook_url": webhook_url,
        "batches_keying": project.batches_keying_panel(),
        "weekly_delivery_plan": months,
        "months": months,
        "weekly_rows": weekly_rows,
        "monthly_chart_json": json.dumps(monthly_chart),
        "weekly_chart_json": json.dumps(weekly_chart),
        "column_choices": project.inventory_column_choices(),
        "project_status": project.project_status_panel(),
        "branch_status": project.branch_status_panel(),
        "batches_status_values": project.batch_status_values(),
        "operational": project.operational_panel(),
        "operational_alerts": project.operational_alerts(),
        "monthly_totals": monthly_totals,
        "weekly_totals": weekly_totals,
    }
    ctx.update(_get_daily_metrics_context(project))
    return render(request, "projects/detail.html", ctx)


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER, UserProfile.ROLE_PL, UserProfile.ROLE_PM)
def project_sync_now(request, pk):
    """Manual pull-to-refresh for a project that came from a Google Sheet -
    re-downloads the current sheet contents and re-runs the import instantly,
    no re-upload needed."""
    project = get_object_or_404(accessible_projects(request), pk=pk)
    if request.method == "POST":
        try:
            updated, errors = resync_project(project, user=request.user)
        except GoogleSheetError as exc:
            errors = [str(exc)]
            updated = None
        if errors:
            messages.error(request, "Sync failed: " + "; ".join(errors))
        else:
            messages.success(request, f"'{updated.project_name}' synced from Google Sheet just now.")
    return redirect("projects:detail", pk=pk)


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER, UserProfile.ROLE_PL, UserProfile.ROLE_PM)
def project_sync_all(request):
    """Bulk version of "Sync Now" - re-pulls every project (that this user
    can access) which is linked to a Google Sheet, in one click, instead of
    opening each project's detail page one at a time.

    Each sync is dominated by network latency (downloading the sheet from
    Google) rather than CPU, so syncing projects one-after-another in a
    Python for-loop meant total time scaled linearly with project count -
    20 projects at ~2-3s each was a genuine 40-60s page hang. Running them
    on a small thread pool overlaps that network wait time across projects
    instead of paying it serially; each thread still does its own DB writes
    inside resync_project()'s own transaction, so results stay consistent
    (SQLite's WAL mode + busy-timeout, set in settings.py, is what lets
    those concurrent writers succeed instead of hitting "database is
    locked")."""
    import concurrent.futures

    if request.method == "POST":
        projects = list(accessible_projects(request).exclude(google_sheet_url=""))
        synced, failed = [], []

        def _sync_one(project):
            try:
                updated, errors = resync_project(project, user=request.user)
            except GoogleSheetError as exc:
                return project.project_name, None, [str(exc)]
            return project.project_name, updated, errors

        if projects:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(projects))) as pool:
                for name, updated, errors in pool.map(_sync_one, projects):
                    if errors or not updated:
                        failed.append(name)
                    else:
                        synced.append(name)

        if synced:
            messages.success(request, f"Synced {len(synced)} project(s): " + ", ".join(synced))
        if failed:
            messages.error(request, f"Failed to sync {len(failed)} project(s): " + ", ".join(failed))
        if not synced and not failed:
            messages.info(request, "No projects are linked to a Google Sheet yet.")
    return redirect("projects:list")


@csrf_exempt
def cron_sync_all(request, token):
    """Token-protected bulk sync, meant to be hit by an external scheduler
    (e.g. a free cron-ping service or Render Cron Job) every N minutes -
    NOT by a logged-in user, so it doesn't use @login_required. The token
    in the URL (CRON_SYNC_TOKEN setting) is the only thing keeping this from
    being a public "resync everything" endpoint anyone could spam.

    Syncs every project that has a google_sheet_url set, regardless of who
    normally has view access to it in the app - a cron job has no "user".
    """
    import concurrent.futures

    expected_token = getattr(settings, "CRON_SYNC_TOKEN", "")
    if not expected_token or token != expected_token:
        return JsonResponse({"error": "invalid token"}, status=403)

    projects = list(Project.objects.exclude(google_sheet_url=""))
    synced, failed = [], []

    def _sync_one(project):
        try:
            updated, errors = resync_project(project)
        except GoogleSheetError as exc:
            return project.project_name, None, [str(exc)]
        return project.project_name, updated, errors

    if projects:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(projects))) as pool:
            for name, updated, errors in pool.map(_sync_one, projects):
                if errors or not updated:
                    failed.append(name)
                else:
                    synced.append(name)

    return JsonResponse({
        "status": "ok",
        "synced": synced,
        "failed": failed,
        "total_linked_projects": len(projects),
    })


@csrf_exempt
@require_POST
def gsheet_webhook(request, pk, token):
    """Push endpoint for a Google Apps Script trigger bound to the sheet
    (onEdit / onChange). No login required (external caller) - instead the
    per-project sync_token in the URL acts as the shared secret. Point an
    Apps Script trigger at this URL and edits sync automatically, with no one
    ever re-uploading a file. See Project Detail page for the exact URL and
    a ready-to-paste Apps Script snippet."""
    project = get_object_or_404(Project.objects.all(), pk=pk)
    if not project.sync_token or token != project.sync_token:
        return JsonResponse({"error": "invalid token"}, status=403)

    try:
        updated, errors = resync_project(project)
    except GoogleSheetError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    if errors:
        return JsonResponse({"status": "failed", "errors": errors}, status=422)
    return JsonResponse({"status": "synced", "project": updated.project_name,
                          "delivered": updated.delivered_records, "target": updated.target_records})


@login_required
def project_insights(request, pk):
    """Merged into project_detail - redirects to the unified dashboard."""
    project = get_object_or_404(accessible_projects(request), pk=pk)

    if request.method == "POST" and hasattr(request.user, "profile") and request.user.profile.can_edit_projects:
        delivered_col = request.POST.get("delivered_column_key", "").strip()
        received_col = request.POST.get("received_column_key", "").strip()
        project.delivered_column_key = delivered_col
        project.received_column_key = received_col

        if "batches_status_column_key" in request.POST:
            project.batches_status_column_key = request.POST.get("batches_status_column_key", "").strip()
            project.batches_keyed_value = request.POST.get("batches_keyed_value", "").strip()
            project.batches_end_date_column_key = request.POST.get("batches_end_date_column_key", "").strip()

        if "branch_receipt_column_key" in request.POST or "rqc_completed_column_key" in request.POST or "rqc_quality_column_key" in request.POST:
            project.branch_receipt_column_key = request.POST.get("branch_receipt_column_key", "").strip()
            project.rqc_completed_column_key = request.POST.get("rqc_completed_column_key", "").strip()
            project.rqc_quality_column_key = request.POST.get("rqc_quality_column_key", "").strip()

        project.save(update_fields=[
            "delivered_column_key", "received_column_key",
            "batches_status_column_key", "batches_keyed_value", "batches_end_date_column_key",
            "branch_receipt_column_key", "rqc_completed_column_key", "rqc_quality_column_key",
        ])
        messages.success(request, "Selected columns saved.")

    return redirect("projects:detail", pk=pk)


@login_required
def weekly_delivery_report(request, pk):
    """Monthly Plan vs Shipped / Weekly Plan vs Shipped report for one
    project (table + chart) - built entirely from Project.
    weekly_delivery_plan() (already grouped by month, with each month's own
    week rows), same data that already backs the Weekly Delivery Plan
    accordion on the project detail page and the homepage's monthly
    summary - this just re-presents it as a dedicated report with charts."""
    project = get_object_or_404(accessible_projects(request), pk=pk)
    months = project.weekly_delivery_plan()

    weekly_rows = []
    for m in months:
        for w in m["weeks"]:
            global_week_num = len(weekly_rows) + 1
            weekly_rows.append({"month_label": m["month_label"], "week": w, "global_week_num": global_week_num})

    monthly_chart = {
        "labels": [m["month_label"] for m in months],
        "plan": [m["monthly_plan"] for m in months],
        "actual": [m["monthly_actual"] for m in months],
    }
    weekly_chart = {
        "labels": [f'{r["month_label"]} Week-{r["global_week_num"]}' for r in weekly_rows],
        "plan": [r["week"].plan_records for r in weekly_rows],
        "actual": [r["week"].actual_records for r in weekly_rows],
    }

    return render(request, "projects/weekly_report.html", {
        "project": project,
        "all_projects": accessible_projects(request),
        "months": months,
        "weekly_rows": weekly_rows,
        "monthly_chart_json": json.dumps(monthly_chart),
        "weekly_chart_json": json.dumps(weekly_chart),
    })


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def project_upload(request):
    # PL/PM/VIEWER are intentionally excluded here (not in the decorator
    # above): this view can create a brand-new Project via
    # update_or_create when the project_key/branch combo doesn't already
    # exist yet, and PL/PM are scoped to editing projects that were already
    # assigned to them, not standing up new ones - see
    # UserProfile.can_create_projects.
    """Two import sources feed the same mapping engine:
      - "file": a directly uploaded .xlsx/.xls
      - "gsheet": a Google Sheet link (must be shared - Viewer is enough -
        with the Google account connected via GOOGLE_OAUTH_* env vars, see
        SETUP_GSHEET_OAUTH.md) - it's downloaded once as .xlsx and imported
        exactly like a file upload, so the mapping config never has to know
        the difference.
    Only templates whose branch this user can access are offered - a
    Manager scoped to TDM never even sees a CHN template in the dropdown,
    and the branch is re-checked server-side on submit too.
    """
    templates = ProjectTemplate.objects.filter(is_active=True, branch__in=accessible_branches(request))
    recent_batches = ImportBatch.objects.select_related("project").filter(
        Q(project__isnull=True) | Q(project__branch__in=accessible_branches(request))
    )[:10]

    if request.method == "POST":
        source = request.POST.get("source", "file")
        template_id = request.POST.get("template")
        template = get_object_or_404(ProjectTemplate, pk=template_id)

        if template.branch and not request.user.profile.can_access_branch(template.branch):
            messages.error(request, f"You don't have access to the '{template.branch}' branch.")
            return redirect("projects:upload")

        # Ensure uploads media directory exists
        (settings.MEDIA_ROOT / "uploads").mkdir(parents=True, exist_ok=True)

        try:
            if source == "gsheet":
                sheet_url = request.POST.get("sheet_url", "").strip()
                if not sheet_url:
                    messages.error(request, "Please paste a Google Sheet link.")
                    return redirect("projects:upload")
                try:
                    full_path = download_as_xlsx(sheet_url)
                except GoogleSheetError as exc:
                    messages.error(request, f"Google Sheet import failed: {exc}")
                    return redirect("projects:upload")

                try:
                    project, errors = run_import(
                        template, full_path, sheet_url, request.user,
                        source_type=ImportBatch.SOURCE_GOOGLE_SHEET, source_url=sheet_url,
                    )
                finally:
                    # Same cleanup as resync_project() in import_engine.py -
                    # this is a disposable temp download, not a file any
                    # model keeps a live reference to.
                    import os
                    try:
                        os.remove(full_path)
                    except OSError:
                        pass
            else:
                excel_file = request.FILES.get("excel_file")
                if not excel_file:
                    messages.error(request, "Please choose an Excel file.")
                    return redirect("projects:upload")
                saved_path = default_storage.save(f"uploads/{excel_file.name}", excel_file)
                try:
                    full_path = default_storage.path(saved_path)
                except (NotImplementedError, AttributeError):
                    full_path = str(settings.MEDIA_ROOT / saved_path)

                project, errors = run_import(
                    template, full_path, excel_file.name, request.user,
                    source_type=ImportBatch.SOURCE_FILE,
                )

            if errors:
                messages.error(request, "Import failed: " + "; ".join(errors))
            elif project:
                messages.success(request, f"'{project.project_name}' imported and dashboard refreshed.")
                return redirect("projects:detail", pk=project.pk)
        except Exception as exc:
            messages.error(request, f"File processing error: {exc}")
            return redirect("projects:upload")

    return render(request, "projects/upload.html", {
        "templates": templates,
        "recent_batches": recent_batches,
    })


PROJECT_FORM_FIELDS = [
    "project_name", "project_key", "branch", "start_date", "end_date",
    "target_records", "delivered_records", "total_images",
    "total_batches", "batches_being_keyed", "promoted",
    "language", "vendor", "event_type", "ocr_status",
    "gm_name", "pm_name", "pl_name",
    "milestone_10_date", "milestone_50_date", "milestone_100_date",
]


def _safe_date(val):
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def project_create(request):
    """Manual CRUD entry point - for projects that don't come from a file/sheet at all.
    The branch dropdown only offers branches this user can access; the
    submitted branch is re-validated server-side too (never trust the form)."""
    branches = accessible_branches(request)

    if request.method == "POST":
        data = request.POST
        branch = Branch.objects.filter(pk=data.get("branch")).first()
        if not request.user.profile.can_access_branch(branch):
            messages.error(request, "You don't have access to create projects in that branch.")
            return render(request, "projects/form.html", {"branches": branches, "mode": "create"})
        m10 = _safe_date(data.get("milestone_10_date")) if request.user.profile.is_admin else None
        m50 = _safe_date(data.get("milestone_50_date")) if request.user.profile.is_admin else None
        m100 = _safe_date(data.get("milestone_100_date")) if request.user.profile.is_admin else None
        try:
            project = Project.objects.create(
                project_name=data["project_name"],
                project_key=data["project_key"],
                branch=branch,
                start_date=data["start_date"],
                end_date=data["end_date"],
                target_records=_safe_int(data.get("target_records")),
                delivered_records=_safe_int(data.get("delivered_records")),
                total_images=_safe_int(data.get("total_images")),
                total_batches=_safe_int(data.get("total_batches")),
                batches_being_keyed=_safe_int(data.get("batches_being_keyed")),
                promoted=_safe_int(data.get("promoted")),
                language=data.get("language", ""),
                customer_name=data.get("customer_name", "").strip(),
                vendor=data.get("vendor", ""),
                event_type=data.get("event_type", ""),
                ocr_status=data.get("ocr_status", ""),
                gm_name=data.get("gm_name", "").strip(),
                pm_name=data.get("pm_name", "").strip(),
                pl_name=data.get("pl_name", "").strip(),
                google_sheet_url=data.get("google_sheet_url", "").strip(),
                milestone_10_date=m10,
                milestone_50_date=m50,
                milestone_100_date=m100,
            )
            if not project.is_ancestry_client:
                project.milestone_10_date = None
                project.milestone_50_date = None
                project.milestone_100_date = None
                project.save(update_fields=["milestone_10_date", "milestone_50_date", "milestone_100_date"])
            messages.success(request, f"Project '{project.project_name}' created.")
            return redirect("projects:detail", pk=project.pk)
        except Exception as exc:
            messages.error(request, f"Could not create project: {exc}")

    return render(request, "projects/form.html", {
        "branches": branches,
        "mode": "create",
    })


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER, UserProfile.ROLE_PL, UserProfile.ROLE_PM)
def project_edit(request, pk):
    project = get_object_or_404(accessible_projects(request), pk=pk)
    branches = accessible_branches(request)

    if request.method == "POST":
        data = request.POST
        new_branch = Branch.objects.filter(pk=data.get("branch")).first()
        if not request.user.profile.can_access_branch(new_branch):
            messages.error(request, "You don't have access to move this project to that branch.")
            return render(request, "projects/form.html", {"project": project, "branches": branches, "mode": "edit"})
        try:
            project.project_name = data["project_name"]
            project.project_key = data["project_key"]
            project.branch = new_branch
            project.start_date = data["start_date"]
            project.end_date = data["end_date"]
            project.target_records = _safe_int(data.get("target_records"))
            project.delivered_records = _safe_int(data.get("delivered_records"))
            project.total_images = _safe_int(data.get("total_images"))
            project.total_batches = _safe_int(data.get("total_batches"))
            project.batches_being_keyed = _safe_int(data.get("batches_being_keyed"))
            project.promoted = _safe_int(data.get("promoted"))
            project.language = data.get("language", "")
            project.customer_name = data.get("customer_name", "").strip()
            project.vendor = data.get("vendor", "")
            project.event_type = data.get("event_type", "")
            project.ocr_status = data.get("ocr_status", "")
            project.gm_name = data.get("gm_name", "").strip()
            project.pm_name = data.get("pm_name", "").strip()
            project.pl_name = data.get("pl_name", "").strip()
            project.google_sheet_url = data.get("google_sheet_url", "").strip()
            if request.user.profile.is_admin:
                if project.is_ancestry_client:
                    project.milestone_10_date = _safe_date(data.get("milestone_10_date"))
                    project.milestone_50_date = _safe_date(data.get("milestone_50_date"))
                    project.milestone_100_date = _safe_date(data.get("milestone_100_date"))
                else:
                    project.milestone_10_date = None
                    project.milestone_50_date = None
                    project.milestone_100_date = None
            elif not project.is_ancestry_client:
                project.milestone_10_date = None
                project.milestone_50_date = None
                project.milestone_100_date = None
            project.save()
            messages.success(request, f"Project '{project.project_name}' updated.")
            return redirect("projects:detail", pk=project.pk)
        except Exception as exc:
            messages.error(request, f"Could not update project: {exc}")

    return render(request, "projects/form.html", {
        "project": project,
        "branches": branches,
        "mode": "edit",
    })


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER, UserProfile.ROLE_PM)
def project_delete(request, pk):
    """Delete requires ADMIN role globally OR a MANAGER/PM who has access to
    this specific project's branch - checked here rather than in the role
    decorator since it depends on which project is being deleted. PL/VIEWER
    are excluded at the decorator level above (see UserProfile.can_delete_projects)."""
    project = get_object_or_404(Project.objects.all(), pk=pk)
    if not request.user.profile.can_access_branch(project.branch):
        messages.error(request, f"You don't have access to the '{project.branch}' branch.")
        return redirect("projects:list")
    if request.method == "POST":
        name = project.project_name
        project.delete()
        messages.success(request, f"Project '{name}' deleted.")
        return redirect("projects:list")
    return render(request, "projects/confirm_delete.html", {"project": project})


@login_required
def project_export(request):
    projects = accessible_projects(request).select_related("branch")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="projects_export.csv"'
    writer = csv.writer(response)
    writer.writerow(["Project", "Branch", "Target", "Delivered", "Remaining",
                      "Delivery %", "Total Batches", "Batches Being Processed", "Promoted", "Promoted %",
                      "Start Date", "End Date", "Status"])
    for p in projects:
        writer.writerow([p.project_name, p.branch.code, p.target_records, p.delivered_records,
                          p.remaining_records, p.delivery_percent, p.total_batches, p.batches_being_keyed,
                          p.promoted, p.promoted_percent, p.start_date, p.end_date, p.status])
    return response
