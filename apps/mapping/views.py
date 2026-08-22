import json
import re
import tempfile

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import accessible_branches, branch_queryset, role_required
from apps.accounts.models import UserProfile
from apps.branches.models import Branch
from .autodetect import detect_mapping
from .engine import apply_mapping
from .models import ProjectTemplate


def _save_template_to_disk(project_key, display_name, branch_code, config):
    """Every save-and-reuse also writes the mapping out as a JSON file in
    /mappings, not just the DB row - so it survives a fresh `seed_data` /
    `sync_from_disk` run and can be committed to version control like the
    hand-built templates."""
    data = {
        "project_key": project_key,
        "display_name": display_name,
        "branch": branch_code,
        "config": config,
    }
    file_name = re.sub(r"[^a-z0-9_]", "", project_key.lower()) + "_mapping.json"
    (settings.MAPPINGS_DIR / file_name).write_text(json.dumps(data, indent=2))


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def template_list(request):
    templates = branch_queryset(request, ProjectTemplate.objects.select_related("branch"))
    return render(request, "mapping/list.html", {"templates": templates})


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def template_detail(request, pk):
    template = get_object_or_404(branch_queryset(request, ProjectTemplate.objects.all()), pk=pk)
    return render(request, "mapping/detail.html", {
        "template": template,
        "config_pretty": json.dumps(template.config, indent=2),
    })


@role_required(UserProfile.ROLE_ADMIN)
def sync_from_disk(request):
    """Load every *.json file in /mappings into the ProjectTemplate table.
    This is how new project formats get onboarded: drop a mapping JSON in
    the folder (or edit an existing one) and click Sync - no code change,
    no redeploy."""
    created, updated = 0, 0
    for path in sorted(settings.MAPPINGS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        branch = Branch.objects.filter(code=data.get("branch", "TDM")).first()
        if not branch:
            branch = Branch.objects.first()
        obj, was_created = ProjectTemplate.objects.update_or_create(
            project_key=data["project_key"],
            defaults={
                "display_name": data.get("display_name", data["project_key"]),
                "branch": branch,
                "config": data["config"],
            },
        )
        created += int(was_created)
        updated += int(not was_created)

    messages.success(request, f"Synced mapping templates: {created} created, {updated} updated.")
    return redirect("mapping:list")


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def template_create(request):
    """Manual CRUD entry - hand-write (or paste) a mapping config directly.
    A Manager can only create templates for branches they have access to."""
    branches = accessible_branches(request)

    if request.method == "POST":
        project_key = request.POST.get("project_key", "").strip().upper()
        display_name = request.POST.get("display_name", "").strip()
        branch_code = request.POST.get("branch", "")
        config_text = request.POST.get("config", "{}")
        branch = Branch.objects.filter(code=branch_code).first()

        if not request.user.profile.can_access_branch(branch):
            messages.error(request, "You don't have access to create templates for that branch.")
            return render(request, "mapping/form.html", {
                "mode": "create", "branches": branches,
                "project_key": project_key, "display_name": display_name, "config_text": config_text,
            })

        try:
            config = json.loads(config_text)
        except json.JSONDecodeError as exc:
            messages.error(request, f"Config isn't valid JSON: {exc}")
            return render(request, "mapping/form.html", {
                "mode": "create", "branches": branches,
                "project_key": project_key, "display_name": display_name, "config_text": config_text,
            })

        ProjectTemplate.objects.update_or_create(
            project_key=project_key,
            defaults={"display_name": display_name, "branch": branch, "config": config},
        )
        _save_template_to_disk(project_key, display_name, branch.code, config)
        messages.success(request, f"Template '{project_key}' created.")
        return redirect("mapping:list")

    return render(request, "mapping/form.html", {"mode": "create", "branches": branches})


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def template_edit(request, pk):
    template = get_object_or_404(branch_queryset(request, ProjectTemplate.objects.all()), pk=pk)
    branches = accessible_branches(request)

    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        branch_code = request.POST.get("branch", "")
        config_text = request.POST.get("config", "{}")
        is_active = bool(request.POST.get("is_active"))
        new_branch = Branch.objects.filter(code=branch_code).first()

        if not request.user.profile.can_access_branch(new_branch):
            messages.error(request, "You don't have access to move this template to that branch.")
            return render(request, "mapping/form.html", {
                "mode": "edit", "template": template, "branches": branches,
                "display_name": display_name, "config_text": config_text,
            })

        try:
            config = json.loads(config_text)
        except json.JSONDecodeError as exc:
            messages.error(request, f"Config isn't valid JSON: {exc}")
            return render(request, "mapping/form.html", {
                "mode": "edit", "template": template, "branches": branches,
                "display_name": display_name, "config_text": config_text,
            })

        template.display_name = display_name
        template.branch = new_branch
        template.config = config
        template.is_active = is_active
        template.save()
        _save_template_to_disk(template.project_key, display_name, new_branch.code, config)
        messages.success(request, f"Template '{template.project_key}' updated.")
        return redirect("mapping:detail", pk=template.pk)

    return render(request, "mapping/form.html", {
        "mode": "edit", "template": template, "branches": branches,
        "config_text": json.dumps(template.config, indent=2),
    })


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def template_delete(request, pk):
    """ADMIN can delete any template; a MANAGER can only delete templates for
    branches they have access to."""
    template = get_object_or_404(ProjectTemplate, pk=pk)
    if not request.user.profile.can_access_branch(template.branch):
        messages.error(request, f"You don't have access to the '{template.branch}' branch.")
        return redirect("mapping:list")
    if request.method == "POST":
        key = template.project_key
        template.delete()
        messages.success(request, f"Template '{key}' deleted. (The mappings/*.json file on disk was left as-is - delete it manually if you don't want it re-synced later.)")
        return redirect("mapping:list")
    return render(request, "mapping/confirm_delete.html", {"template": template})


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def auto_detect(request):
    """Step 1: upload a sample Excel file for a project format we don't have
    a template for yet. Runs detection and shows the guessed config for
    review before anything is saved."""
    if request.method == "POST" and request.FILES.get("sample_file"):
        sample = request.FILES["sample_file"]
        saved_path = default_storage.save(f"uploads/_detect_{sample.name}", sample)
        full_path = default_storage.path(saved_path)

        result = detect_mapping(full_path)

        # Immediately validate the guessed config against the same file, so
        # the review screen shows real extracted values, not just guesses.
        preview = apply_mapping(full_path, result["config"])

        return render(request, "mapping/detect_review.html", {
            "notes": result["notes"],
            "confidence": result["confidence"],
            "config_text": json.dumps(result["config"], indent=2),
            "preview_valid": preview.is_valid,
            "preview_values": preview.values,
            "preview_errors": preview.errors,
            "branches": accessible_branches(request),
            "sample_path": saved_path,
        })

    return render(request, "mapping/detect_upload.html")


@role_required(UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER)
def auto_detect_save(request):
    """Step 2: save the (possibly hand-edited) detected config as a reusable
    ProjectTemplate - both in the DB and as a mappings/*.json file, so future
    uploads of the same format are picked from a dropdown, no re-detection
    needed."""
    if request.method != "POST":
        return redirect("mapping:auto_detect")

    project_key = request.POST.get("project_key", "").strip().upper()
    display_name = request.POST.get("display_name", "").strip() or project_key
    branch_code = request.POST.get("branch", "")
    config_text = request.POST.get("config", "{}")

    if not project_key:
        messages.error(request, "Please give this template a project key (e.g. SSH, HOR).")
        return redirect("mapping:auto_detect")

    try:
        config = json.loads(config_text)
    except json.JSONDecodeError as exc:
        messages.error(request, f"Config isn't valid JSON: {exc}")
        return redirect("mapping:auto_detect")

    branch = Branch.objects.filter(code=branch_code).first()
    if not request.user.profile.can_access_branch(branch):
        messages.error(request, "You don't have access to save a template for that branch.")
        return redirect("mapping:auto_detect")

    template, created = ProjectTemplate.objects.update_or_create(
        project_key=project_key,
        defaults={"display_name": display_name, "branch": branch, "config": config},
    )
    _save_template_to_disk(project_key, display_name, branch.code, config)

    messages.success(
        request,
        f"Template '{project_key}' {'created' if created else 'updated'} and saved for reuse — "
        f"it'll now appear in the Upload Excel dropdown for every future import of this format."
    )
    return redirect("mapping:detail", pk=template.pk)
