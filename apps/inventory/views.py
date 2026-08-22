from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404

from apps.accounts.decorators import accessible_branches, accessible_projects, branch_queryset, project_queryset
from apps.projects.models import Project
from .models import InventoryItem


from django.conf import settings

@login_required
def inventory_project_list(request):
    """Shows a list of projects so the user can select one to view its inventory."""
    projects = accessible_projects(request).select_related("branch")
    q = request.GET.get("q", "")
    branch_code = request.GET.get("branch", "")
    if q:
        projects = projects.filter(project_name__icontains=q)
    if branch_code:
        projects = projects.filter(branch__code=branch_code)

    # See apps/projects/views.py:project_list for why this comes from
    # accessible_branches() instead of the global settings.BRANCH_CHOICES,
    # and is hidden entirely when there's only one option anyway.
    branches = accessible_branches(request)

    return render(request, "inventory/project_list.html", {
        "projects": projects,
        "q": q,
        "branch_code": branch_code,
        "branch_choices": [(b.code, b.name) for b in branches],
        "show_branch_filter": branches.count() > 1,
    })


@login_required
def inventory_detail(request, pk):
    """Company-wide inventory tracker: every ingested file/folder row,
    across every project, searchable and filterable - separate from the
    rolled-up Production dashboard so this can stay row-level and fast."""
    
    project = get_object_or_404(accessible_projects(request), pk=pk)
    project_id = project.pk
    
    # Handle POST for saving column configuration
    if request.method == "POST":
        if hasattr(request.user, 'profile') and request.user.profile.can_edit_projects:
            project = Project.objects.filter(pk=project_id).first()
            if project:
                action = request.POST.get("action", "save_visibility")
                
                if action == "add_column":
                    new_col = request.POST.get("new_column_name", "").strip()
                    if new_col and new_col not in project.defined_custom_columns:
                        project.defined_custom_columns.append(new_col)
                        if new_col not in project.visible_inventory_columns:
                            project.visible_inventory_columns.append(new_col)
                        project.save()
                        
                elif action == "edit_column":
                    old_name = request.POST.get("old_column_name", "").strip()
                    new_name = request.POST.get("new_column_name", "").strip()
                    if old_name in project.defined_custom_columns and new_name and new_name not in project.defined_custom_columns:
                        idx = project.defined_custom_columns.index(old_name)
                        project.defined_custom_columns[idx] = new_name
                        if old_name in project.visible_inventory_columns:
                            v_idx = project.visible_inventory_columns.index(old_name)
                            project.visible_inventory_columns[v_idx] = new_name
                        project.save()
                        
                elif action == "delete_column":
                    col_name = request.POST.get("column_name", "").strip()
                    if col_name in project.defined_custom_columns:
                        project.defined_custom_columns.remove(col_name)
                        if col_name in project.visible_inventory_columns:
                            project.visible_inventory_columns.remove(col_name)
                        project.save()
                        
                else:
                    visible_columns = request.POST.getlist("visible_columns")
                    project.visible_inventory_columns = visible_columns
                    project.save()
        return redirect(request.get_full_path())

    items = InventoryItem.objects.select_related("project", "project__branch")
    items = branch_queryset(request, items, branch_field="project__branch")
    items = project_queryset(request, items, project_field="project")

    event_type = request.GET.get("event_type", "")
    language = request.GET.get("language", "")
    q = request.GET.get("q", "")

    # Filter DROPDOWN OPTIONS are computed from the accessible, project-scoped
    # base (below) rather than event_type/language-filtered `items` further
    # down - narrowing options by the very filter being picked would make
    # the list collapse to 1 option after a selection. Previously this also
    # scanned InventoryItem.objects across EVERY project/branch org-wide
    # (not just this project or what the user can see), which both leaked
    # other branches' values into the dropdown and produced "duplicate"-
    # looking entries from free-text values that only differ by casing/
    # whitespace ("English" vs "english" vs " English") - normalized below.
    option_source = items.filter(project_id=project_id) if project_id else items

    def _distinct_options(queryset, field):
        seen = {}
        for raw in queryset.exclude(**{field: ""}).values_list(field, flat=True):
            key = raw.strip().lower()
            if key and key not in seen:
                seen[key] = raw.strip()
        return sorted(seen.values(), key=str.lower)

    event_types = _distinct_options(option_source, "event_type")
    languages = _distinct_options(option_source, "language")

    if project_id:
        items = items.filter(project_id=project_id)
    if event_type:
        items = items.filter(event_type__iexact=event_type)
    if language:
        items = items.filter(language__iexact=language)
    if q:
        items = items.filter(file_name__icontains=q) | items.filter(folder_name__icontains=q)

    totals = items.aggregate(images=Sum("image_count"), records=Sum("record_count"))

    paginator = Paginator(items, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    projects = accessible_projects(request)

    # Calculate available and visible columns
    available_columns = {
        "event_type": "Event Type",
        "language": "Language",
        "image_count": "Images",
        "record_count": "Records",
        "shipment_date": "Shipment Date",
        "remarks": "Remarks",
    }
    
    visible_columns = ["event_type", "language", "image_count", "record_count", "shipment_date"]  # Default standard columns
    extra_columns = []
    
    if project_id:
        project = Project.objects.filter(pk=project_id).first()
        if project:
            # Add user-defined custom columns
            for col in project.defined_custom_columns:
                if col not in available_columns:
                    extra_columns.append(col)
                    available_columns[col] = col
            
            # Add any other extra columns that might exist in the data but haven't been explicitly defined.
            # Uses the same project-wide scan as the Insights page's Selected_Column
            # dropdown (up to 500 rows) - sampling only the first row here used to
            # silently miss columns that row happened to have blank/absent.
            for k, label in project.inventory_column_choices().items():
                if k not in available_columns and k not in ("image_count", "record_count"):
                    extra_columns.append(k)
                    available_columns[k] = label
            
            # If the user has explicitly saved a column configuration, use it.
            if project.visible_inventory_columns:
                visible_columns = project.visible_inventory_columns
            else:
                # By default, show standard columns PLUS any extra columns from the spreadsheet
                visible_columns.extend(extra_columns)

    return render(request, "inventory/list.html", {
        "page_obj": page_obj,
        "totals": totals,
        "projects": projects,
        "event_types": event_types,
        "languages": languages,
        "q": q, "selected_project": project, "selected_event_type": event_type, "selected_language": language,
        "available_columns": available_columns,
        "visible_columns": visible_columns,
        "extra_columns": extra_columns,
        "defined_custom_columns": project.defined_custom_columns if project_id and project else [],
    })
