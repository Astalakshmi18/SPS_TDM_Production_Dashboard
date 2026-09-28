from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import accessible_branches, role_required
from apps.accounts.models import UserProfile
from .models import Branch


@role_required(UserProfile.ROLE_ADMIN)
def branch_list(request):
    branches = accessible_branches(request)
    return render(request, "branches/list.html", {"branches": branches})


@role_required(UserProfile.ROLE_ADMIN)
def branch_create(request):
    if request.method == "POST":
        code = request.POST.get("code", "").strip().upper()
        name = request.POST.get("name", "").strip()
        if Branch.objects.filter(code=code).exists():
            messages.error(request, f"Branch code '{code}' already exists.")
        else:
            Branch.objects.create(code=code, name=name)
            messages.success(request, f"Branch '{code}' created.")
            return redirect("branches:list")
    return render(request, "branches/form.html", {"mode": "create"})


@role_required(UserProfile.ROLE_ADMIN)
def branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == "POST":
        branch.code = request.POST.get("code", branch.code).strip().upper()
        branch.name = request.POST.get("name", branch.name).strip()
        branch.is_active = bool(request.POST.get("is_active"))
        branch.save()
        messages.success(request, f"Branch '{branch.code}' updated.")
        return redirect("branches:list")
    return render(request, "branches/form.html", {"branch": branch, "mode": "edit"})


@role_required(UserProfile.ROLE_ADMIN)
def branch_delete(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    projects = branch.projects.all()
    templates = branch.projecttemplate_set.all()
    has_blockers = projects.exists() or templates.exists()

    if request.method == "POST":
        if projects.exists():
            messages.error(
                request,
                f"Can't delete '{branch.code}' - it still has {projects.count()} project(s) assigned to it."
            )
            return redirect("branches:list")

        if templates.exists():
            template_keys = ", ".join(t.project_key for t in templates)
            messages.error(
                request,
                f"Can't delete '{branch.code}' - it is used by mapping template(s): {template_keys}. "
                f"Please reassign or delete the template(s) first."
            )
            return redirect("branches:list")

        try:
            code = branch.code
            branch.delete()
            messages.success(request, f"Branch '{code}' deleted.")
        except ProtectedError as exc:
            messages.error(
                request,
                f"Cannot delete '{branch.code}' because other records depend on it: {exc}"
            )
        return redirect("branches:list")

    return render(
        request,
        "branches/confirm_delete.html",
        {
            "branch": branch,
            "projects": projects,
            "templates": templates,
            "has_blockers": has_blockers,
        },
    )


@role_required(UserProfile.ROLE_ADMIN)
def branch_access(request, pk):
    """See and manage, at a glance, exactly which users can reach this one
    branch's data - the reverse view of the per-user branch checklist on the
    Users page."""
    from django.contrib.auth.models import User

    branch = get_object_or_404(Branch, pk=pk)
    all_users = User.objects.select_related("profile").exclude(profile__role=UserProfile.ROLE_ADMIN)

    if request.method == "POST":
        granted_ids = set(int(i) for i in request.POST.getlist("users"))
        for u in all_users:
            has_access = branch in u.profile.branches.all()
            should_have = u.pk in granted_ids
            if should_have and not has_access:
                u.profile.branches.add(branch)
            elif has_access and not should_have:
                u.profile.branches.remove(branch)
        messages.success(request, f"Branch access for '{branch.code}' updated.")
        return redirect("branches:list")

    return render(request, "branches/access.html", {
        "branch": branch,
        "all_users": all_users,
        "granted_ids": set(all_users.filter(profile__branches=branch).values_list("id", flat=True)),
    })
