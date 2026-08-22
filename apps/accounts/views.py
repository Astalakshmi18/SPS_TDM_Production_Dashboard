from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render

from apps.branches.models import Branch
from apps.projects.models import Project
from .decorators import role_required
from .models import UserProfile


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard:home")
        messages.error(request, "Invalid username or password.")

    return render(request, "accounts/login.html")


@login_required
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@role_required(UserProfile.ROLE_ADMIN)
def user_list(request):
    users = User.objects.select_related("profile").prefetch_related("profile__branches").all()
    return render(request, "accounts/user_list.html", {"users": users})


@role_required(UserProfile.ROLE_ADMIN)
def user_create(request):
    branches = Branch.objects.all()
    projects = Project.objects.select_related("branch").order_by("branch__code", "project_name")
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        role = request.POST.get("role")
        branch_ids = request.POST.getlist("branches")
        project_ids = request.POST.getlist("projects")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        else:
            user = User.objects.create_user(username=username, password=password)
            user.profile.role = role
            user.profile.save()
            user.profile.branches.set(branch_ids)
            user.profile.projects.set(project_ids)
            messages.success(request, f"User '{username}' created.")
            return redirect("accounts:user_list")

    return render(request, "accounts/user_form.html", {
        "branches": branches,
        "projects": projects,
        "role_choices": UserProfile.ROLE_CHOICES,
        "mode": "create",
    })


@role_required(UserProfile.ROLE_ADMIN)
def user_edit(request, pk):
    target = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    branches = Branch.objects.all()
    projects = Project.objects.select_related("branch").order_by("branch__code", "project_name")

    if request.method == "POST":
        role = request.POST.get("role")
        branch_ids = request.POST.getlist("branches")
        project_ids = request.POST.getlist("projects")
        new_password = request.POST.get("password", "").strip()

        target.profile.role = role
        target.profile.save()
        target.profile.branches.set(branch_ids)
        target.profile.projects.set(project_ids)

        if new_password:
            target.set_password(new_password)
            target.save()

        messages.success(request, f"User '{target.username}' updated.")
        return redirect("accounts:user_list")

    return render(request, "accounts/user_form.html", {
        "target": target,
        "branches": branches,
        "projects": projects,
        "assigned_branch_ids": set(target.profile.branches.values_list("id", flat=True)),
        "assigned_project_ids": set(target.profile.projects.values_list("id", flat=True)),
        "role_choices": UserProfile.ROLE_CHOICES,
        "mode": "edit",
    })


@role_required(UserProfile.ROLE_ADMIN)
def user_delete(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        if target == request.user:
            messages.error(request, "You can't delete your own account while logged in as it.")
            return redirect("accounts:user_list")
        username = target.username
        target.delete()
        messages.success(request, f"User '{username}' deleted.")
        return redirect("accounts:user_list")
    return render(request, "accounts/confirm_delete.html", {"target": target})
