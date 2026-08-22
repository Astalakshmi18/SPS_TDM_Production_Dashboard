from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import accessible_branches, role_required
from apps.accounts.models import UserProfile
from .models import Branch


@login_required
def branch_list(request):
    # Was Branch.objects.all() for every logged-in user regardless of role -
    # a Viewer/Manager/PL/PM scoped to one branch could still see every
    # other branch in this list (just not act on them). accessible_branches()
    # gives ADMIN everything and everyone else only what's been granted.
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
    if request.method == "POST":
        if branch.projects.exists():
            messages.error(request, f"Can't delete '{branch.code}' - it still has projects assigned to it.")
        else:
            code = branch.code
            branch.delete()
            messages.success(request, f"Branch '{code}' deleted.")
        return redirect("branches:list")
    return render(request, "branches/confirm_delete.html", {"branch": branch})


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
