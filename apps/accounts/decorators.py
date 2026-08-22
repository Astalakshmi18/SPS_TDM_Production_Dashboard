from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def role_required(*allowed_roles):
    """Restrict a view to users whose profile.role is in allowed_roles.
    Usage: @role_required("ADMIN", "MANAGER")
    This only checks role - it does NOT check branch access. Views that
    create/edit/delete branch-scoped objects (Project, InventoryItem,
    ProjectTemplate, ...) must also call require_branch_access() for the
    specific branch involved.
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            profile = getattr(request.user, "profile", None)
            if not profile or profile.role not in allowed_roles:
                messages.error(request, "You do not have permission to access that page.")
                return redirect("dashboard:home")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def branch_queryset(request, queryset, branch_field="branch"):
    """Scope a queryset to the logged-in user's accessible branches.
    ADMIN always sees everything. MANAGER and VIEWER are both scoped to
    UserProfile.branches - a Manager with no branches assigned sees nothing,
    not everything (deny by default)."""
    profile = getattr(request.user, "profile", None)
    if not profile:
        return queryset.none()
    if profile.is_admin:
        return queryset
    branch_ids = profile.accessible_branch_ids()
    if not branch_ids:
        return queryset.none()
    return queryset.filter(**{f"{branch_field}__in": branch_ids})


def project_queryset(request, queryset, project_field="pk"):
    """Second, narrower filter applied ON TOP OF branch_queryset(): scopes a
    Project (or Project-related) queryset down to the logged-in user's
    individually-assigned projects, for roles that are project-scoped (PM,
    VIEWER - see UserProfile.is_project_scoped). ADMIN/MANAGER/PL are
    unaffected by this and pass through untouched - branch access alone is
    enough for them. `project_field` is the lookup path to a Project (or
    Project pk) from `queryset`'s model - "pk" when the queryset already IS
    Project, "project" when filtering e.g. InventoryItem rows.
    Deny-by-default: a PM/Viewer with no projects assigned yet sees none,
    same rule as branch_queryset."""
    profile = getattr(request.user, "profile", None)
    if not profile or not profile.is_project_scoped:
        return queryset
    project_ids = profile.accessible_project_ids()
    if not project_ids:
        return queryset.none()
    return queryset.filter(**{f"{project_field}__in": project_ids})


def accessible_projects(request):
    """The queryset of Project objects this user may act on, after BOTH the
    branch filter and (for PM/Viewer) the individual-project filter - use
    this for a project <select> and for get_object_or_404 lookups so a PM/
    Viewer can never open a project they weren't assigned, even by guessing
    its URL."""
    from apps.projects.models import Project

    return project_queryset(request, branch_queryset(request, Project.objects.all()))


def require_branch_access(request, branch):
    """Object-level check for a single write (create/edit/delete a project,
    inventory item, or mapping template tied to `branch`). Raises
    PermissionDenied (-> Django's 403 page) if the logged-in user isn't
    ADMIN and doesn't have this specific branch in their access list.
    Call this from inside a view BEFORE saving/deleting, after role_required
    has already confirmed the user's role is allowed to attempt the action
    at all."""
    profile = getattr(request.user, "profile", None)
    if not profile or not profile.can_access_branch(branch):
        raise PermissionDenied(
            f"You don't have access to the '{branch}' branch. Ask an administrator to grant it "
            f"under Users \u2192 Branch Access."
        )


def accessible_branches(request):
    """The queryset of Branch objects this user may act on - use this to
    populate branch <select> dropdowns so a Manager/Viewer is never even
    shown a branch they can't touch."""
    from apps.branches.models import Branch

    profile = getattr(request.user, "profile", None)
    if not profile:
        return Branch.objects.none()
    if profile.is_admin:
        return Branch.objects.all()
    return profile.branches.all()
