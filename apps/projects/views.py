import csv
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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
    projects = accessible_projects(request).select_related("branch")

    q = request.GET.get("q", "")
    branch_code = request.GET.get("branch", "")
    if q:
        projects = projects.filter(project_name__icontains=q)
    if branch_code:
        projects = projects.filter(branch__code=branch_code)

    # Branch filter options come from accessible_branches(), NOT the global
    # settings.BRANCH_CHOICES list - a Manager/PL/PM/Viewer scoped to one
    # branch used to still see every branch code in the org in this
    # dropdown, even ones they have zero projects in (picking one just
    # produced an empty, confusing result since accessible_projects() would
    # already filter it all out). And per-request: if someone only has ONE
    # branch to choose from anyway, the dropdown adds nothing - hide it.
    branches = accessible_branches(request)

    return render(request, "projects/list.html", {
        "projects": projects,
        "q": q,
        "branch_code": branch_code,
        "branch_choices": [(b.code, b.name) for b in branches],
        "show_branch_filter": branches.count() > 1,
    })


# How often the detail page is allowed to auto-pull from Google Sheets for
# the same project. Keeps "just open the page and it's current" from turning
# into a fresh download on every single request/refresh.
AUTO_SYNC_THROTTLE_SECONDS = 300


@login_required
def project_detail(request, pk):
    project = get_object_or_404(accessible_projects(request), pk=pk)

    # Auto-sync: pulls the latest Google Sheet data automatically whenever
    # the page is opened, so nobody has to click "Sync Now" first to see
    # today's numbers. Throttled per project and silent on failure - the
    # "Sync Now" button is still right there and will surface any error.
    if project.google_sheet_url and project.sync_token:
        throttle_key = f"project_autosync_{project.pk}"
        if not cache.get(throttle_key):
            cache.set(throttle_key, True, AUTO_SYNC_THROTTLE_SECONDS)
            try:
                updated, errors = resync_project(project, user=request.user)
                if updated and not errors:
                    project = updated
            except GoogleSheetError:
                pass

    webhook_url = None
    if project.google_sheet_url and project.sync_token:
        webhook_url = request.build_absolute_uri(
            f"/projects/webhook/{project.pk}/{project.sync_token}/"
        )
    return render(request, "projects/detail.html", {
        "project": project,
        "milestones": project.milestones(),
        "webhook_url": webhook_url,
        "batches_keying": project.batches_keying_panel(),
    })


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
    """Everything the mapping engine found that isn't one of the core
    dashboard fields - kept off the main Dashboard on purpose so that stays
    scannable, but nothing gets silently dropped. Also hosts the Project
    Status / Branch Status panels and the Selected_Column dropdowns that
    drive them."""
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

        project.save(update_fields=[
            "delivered_column_key", "received_column_key",
            "batches_status_column_key", "batches_keyed_value", "batches_end_date_column_key",
        ])
        messages.success(request, "Selected columns saved.")
        return redirect("projects:insights", pk=pk)

    return render(request, "projects/insights.html", {
        "project": project,
        "column_choices": project.inventory_column_choices(),
        "project_status": project.project_status_panel(),
        "branch_status": project.branch_status_panel(),
        "batches_status_values": project.batch_status_values(),
        "batches_keying": project.batches_keying_panel(),
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

                project, errors = run_import(
                    template, full_path, sheet_url, request.user,
                    source_type=ImportBatch.SOURCE_GOOGLE_SHEET, source_url=sheet_url,
                )
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
]


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
                vendor=data.get("vendor", ""),
                event_type=data.get("event_type", ""),
                ocr_status=data.get("ocr_status", ""),
                google_sheet_url=data.get("google_sheet_url", "").strip(),
            )
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
            project.vendor = data.get("vendor", "")
            project.event_type = data.get("event_type", "")
            project.ocr_status = data.get("ocr_status", "")
            project.google_sheet_url = data.get("google_sheet_url", "").strip()
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
