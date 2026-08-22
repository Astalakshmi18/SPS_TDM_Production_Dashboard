from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Extends Django's built-in User with the RBAC role and branch access.

    Roles:
      ADMIN    - full access everywhere: branches, mapping templates, users,
                 all projects/inventory across every branch, no restriction.
      MANAGER  - Branch Manager. Scoped to their assigned branch(es), but
                 sees and can Add/Edit/Delete EVERY project within those
                 branches (not scoped down to individual projects) - also
                 the only non-ADMIN role that manages mapping templates.
      PM       - Project Manager. Scoped BELOW branch level to only the
                 specific project(s) assigned via `projects` (still also
                 needs branch access to that project's branch). Can Edit
                 AND Delete their assigned projects, but can NOT create new
                 ones - those stay with MANAGER/ADMIN.
      PL       - Project Lead. Same project-level scoping as PM (assigned
                 branch + assigned project only), but Edit ONLY - no
                 delete, no create.
      VIEWER   - Same project-level scoping as PM/PL (assigned branch +
                 assigned project only), but read-only - no edit, no
                 delete, no create.

    `branches` is many-to-many so one person can be scoped to more than one
    branch (e.g. a regional manager covering TDM + CHN). ADMIN ignores this
    field entirely (always sees/can-edit everything). For everyone else, no
    assigned branches means no access to any branch data - deny by default,
    not "everything" - an admin must explicitly grant branch access.

    `projects` is a SECOND, narrower layer of scoping on top of `branches`,
    enforced for PM, PL, and VIEWER (see `is_project_scoped`) - MANAGER is
    branch-scoped only and ignores this field, seeing every project in
    their assigned branches. A branch still has to be granted for the
    project's branch to show through at all - `projects` never widens
    access beyond `branches`, only narrows it further down to individual
    projects. Same deny-by-default rule: a PM/PL/Viewer with no projects
    assigned sees none yet, not "every project in their branch".
    """

    ROLE_ADMIN = "ADMIN"
    ROLE_MANAGER = "MANAGER"
    ROLE_PL = "PL"
    ROLE_PM = "PM"
    ROLE_VIEWER = "VIEWER"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_MANAGER, "Branch Manager"),
        (ROLE_PL, "Project Lead"),
        (ROLE_PM, "Project Manager"),
        (ROLE_VIEWER, "Viewer"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    branches = models.ManyToManyField(
        "branches.Branch", blank=True, related_name="user_profiles",
        help_text="Which branches this user can see/manage. Ignored for ADMIN (always full access). "
                   "Leave empty for MANAGER/PL/PM/VIEWER to grant no branch access yet.",
    )
    projects = models.ManyToManyField(
        "projects.Project", blank=True, related_name="assigned_profiles",
        help_text="Which SPECIFIC projects this user can see/manage, on top of branch access. Only "
                   "enforced for Project Manager, Project Lead, and Viewer roles - Admin/Branch Manager "
                   "are governed by branch access alone and ignore this field. Leave empty for PM/PL/"
                   "Viewer to grant no project access yet.",
    )

    def __str__(self):
        return f"{self.user.username} ({self.role})"

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def is_manager(self):
        return self.role in (self.ROLE_ADMIN, self.ROLE_MANAGER)

    @property
    def is_pl(self):
        return self.role == self.ROLE_PL

    @property
    def is_pm(self):
        return self.role == self.ROLE_PM

    @property
    def can_edit_projects(self):
        """Can edit projects and upload/import data (within their accessible
        branches/projects): everyone except VIEWER."""
        return self.role in (self.ROLE_ADMIN, self.ROLE_MANAGER, self.ROLE_PL, self.ROLE_PM)

    @property
    def can_create_projects(self):
        """Can create brand-new projects: ADMIN, MANAGER only. PM/PL are
        scoped to working within projects that were already assigned to
        them, not standing up new ones."""
        return self.role in (self.ROLE_ADMIN, self.ROLE_MANAGER)

    @property
    def can_delete_projects(self):
        """Can delete projects: ADMIN, MANAGER, PM. PL explicitly cannot -
        edit-only."""
        return self.role in (self.ROLE_ADMIN, self.ROLE_MANAGER, self.ROLE_PM)

    @property
    def can_manage_templates(self):
        """Can create/edit/delete mapping templates: ADMIN, MANAGER only."""
        return self.is_manager

    @property
    def is_project_scoped(self):
        """True for roles that are restricted below branch level to
        individually-assigned projects: PM, PL, and VIEWER. MANAGER is
        branch-scoped only and sees every project in their branches."""
        return self.role in (self.ROLE_PM, self.ROLE_PL, self.ROLE_VIEWER)

    def accessible_branch_ids(self):
        """None means "all branches" (ADMIN); otherwise a set of allowed branch IDs."""
        if self.is_admin:
            return None
        return set(self.branches.values_list("id", flat=True))

    def can_access_branch(self, branch):
        if self.is_admin:
            return True
        if branch is None:
            return False
        branch_id = branch.pk if hasattr(branch, "pk") else branch
        return branch_id in self.accessible_branch_ids()

    def accessible_project_ids(self):
        """None means "no extra restriction beyond branch access" (every
        role except PM/VIEWER); otherwise a set of the specific project IDs
        a PM/VIEWER may see, deny-by-default if none have been assigned."""
        if not self.is_project_scoped:
            return None
        return set(self.projects.values_list("id", flat=True))

    def can_access_project(self, project):
        if project is None:
            return False
        if not self.can_access_branch(getattr(project, "branch", None)):
            return False
        if self.is_project_scoped:
            return project.pk in self.accessible_project_ids()
        return True
