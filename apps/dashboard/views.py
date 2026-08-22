import json
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.decorators import accessible_branches, accessible_projects
from apps.projects.models import Project

MILESTONE_STATUS_LABELS = {
    "green": "On Track / Met",
    "yellow": "At Risk",
    "red": "Missed / Behind",
}
MILESTONE_STATUS_COLORS = {
    "green": "#22c55e",
    "yellow": "#eab308",
    "red": "#ef4444",
}


def _distinct_ci(queryset, field):
    """Case/whitespace-insensitive distinct values for a free-text field
    (e.g. vendor) - "Acme", "acme", " Acme " previously showed as three
    separate dropdown entries since .distinct() only dedupes exact strings."""
    seen = {}
    for raw in queryset.exclude(**{field: ""}).values_list(field, flat=True):
        key = raw.strip().lower()
        if key and key not in seen:
            seen[key] = raw.strip()
    return sorted(seen.values(), key=str.lower)


@login_required
def home(request):
    all_projects = accessible_projects(request).select_related("branch")
    branches = accessible_branches(request)

    branch_filter = request.GET.get("branch")
    vendor_filter = request.GET.get("vendor")
    project_filter = request.GET.get("project")

    # `projects` gets progressively narrowed by the filters below for the
    # KPIs/table - `all_projects` (above) stays unfiltered so the "All
    # Branches"/"All Projects" dropdowns always show every option the user
    # can pick, not just whatever the CURRENT selection already narrowed it
    # down to (previously reused the same narrowing queryset for both,
    # so picking one project would also collapse the project dropdown to
    # just that one project on the next request).
    projects = all_projects
    if branch_filter:
        projects = projects.filter(branch__code=branch_filter)
    if vendor_filter:
        projects = projects.filter(vendor=vendor_filter)
    if project_filter:
        projects = projects.filter(pk=project_filter)

    totals = projects.aggregate(target=Sum("target_records"), delivered=Sum("delivered_records"),
                                 images=Sum("total_images"))
    target = totals["target"] or 0
    delivered = totals["delivered"] or 0
    images = totals["images"] or 0
    remaining = max(target - delivered, 0)
    delivery_pct = round((delivered / target) * 100, 2) if target else 0.0

    # Total Batches / Batches Being Processed / Promoted: summed per-project via
    # batches_keying_panel() (No. of Batches - No. of Batches Shipped = No.
    # of Batches Being Processed), NOT a plain DB Sum() of the stored fields -
    # those stored fields only reflect the raw import-time derivation, so a
    # project with the WIP/blank-excluding refinement configured on Project
    # Insights would show one number there and a different, stale one here.
    total_batches = 0
    batches_being_keyed = 0
    promoted = 0
    for p in projects:
        panel = p.batches_keying_panel()
        total_batches += panel["total_batches"]
        batches_being_keyed += panel["batches_being_keyed"]
        promoted += p.promoted
    promoted_pct = round((promoted / total_batches) * 100, 2) if total_batches else 0.0

    kpis = {
        "total_projects": projects.count(),
        "target": target,
        "delivered": delivered,
        "remaining": remaining,
        "delivery_pct": delivery_pct,
        "total_images": images,
        "total_batches": total_batches,
        "batches_being_keyed": batches_being_keyed,
        "promoted": promoted,
        "promoted_pct": promoted_pct,
        "last_updated": projects.order_by("-last_updated").values_list("last_updated", flat=True).first(),
    }

    # Branch-wise bar chart
    branch_data = (
        projects.values("branch__code")
        .annotate(target=Sum("target_records"), delivered=Sum("delivered_records"))
        .order_by("branch__code")
    )
    branch_chart = {
        "labels": [b["branch__code"] for b in branch_data],
        "target": [b["target"] for b in branch_data],
        "delivered": [b["delivered"] for b in branch_data],
    }

    # Completion doughnut
    completion_chart = {"delivered": delivered, "remaining": remaining}

    # Status legend counts (overall project status: green/yellow/orange/red)
    status_counts = Counter(p.status for p in projects)
    status_chart = {
        "labels": [s.capitalize() for s in status_counts.keys()],
        "values": list(status_counts.values()),
        "colors": [{"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}[s] for s in status_counts.keys()],
    }

    # PHX-style Milestone Summary: bucket every project by its 100% checkpoint
    # status, plus a full per-project milestone table (IDX Start/10%/50%/100%).
    milestone_100_counts = Counter(p.milestone_100_status for p in projects)
    milestone_summary = [
        {"key": key, "label": label, "count": milestone_100_counts.get(key, 0), "color": MILESTONE_STATUS_COLORS[key]}
        for key, label in MILESTONE_STATUS_LABELS.items()
        if milestone_100_counts.get(key, 0) > 0
    ]
    milestone_table_rows = []
    for p in projects:
        idx_start = {m["label"]: m for m in p.milestones()}.get("IDX Start")
        # m10/m50/m100 now come from milestone_shipment_checkpoints() - the
        # REAL, actually-shipped-by-that-date % (Inventory page Shipment
        # Date column) and its own Green/Yellow/Red, rather than the
        # straight-line pace estimate milestones() uses on its own. IDX
        # Start (= Project Start, always day zero) still comes from
        # milestones() since there's no "shipped by project start" figure
        # to compute.
        shipment_checkpoints = {c["label"]: c for c in p.milestone_shipment_checkpoints()}
        milestone_table_rows.append({
            "project": p,
            "idx_start": idx_start,
            "m10": shipment_checkpoints.get("10%"),
            "m50": shipment_checkpoints.get("50%"),
            "m100": shipment_checkpoints.get("100%"),
            "batches": p.batches_keying_panel(),
        })

    # Project Detail Table (bottom of page): Total Volume/Delivered/Remaining
    # + week-based Expected % + the 10%/50%/100% checkpoint dates paired
    # with "PctBy X%" (actual shipped-by-that-date % from the Inventory
    # page's own shipment_date column - see Project.milestone_shipment_
    # checkpoints). Precomputed here rather than called per-cell in the
    # template so each project's Inventory rows are only queried once.
    project_table_rows = []
    for p in projects:
        cps = {c["label"]: c for c in p.milestone_shipment_checkpoints()}
        project_table_rows.append({
            "project": p,
            "cp10": cps.get("10%"),
            "cp50": cps.get("50%"),
            "cp100": cps.get("100%"),
        })

    context = {
        "kpis": kpis,
        "projects": projects,
        "branches": branches,
        "show_branch_filter": branches.count() > 1,
        "show_project_filter": all_projects.count() > 1,
        "vendors": _distinct_ci(all_projects, "vendor"),
        "branch_chart_json": json.dumps(branch_chart),
        "completion_chart_json": json.dumps(completion_chart),
        "status_chart_json": json.dumps(status_chart),
        "milestone_summary": milestone_summary,
        "milestone_total": sum(m["count"] for m in milestone_summary),
        "milestone_table_rows": milestone_table_rows,
        "project_table_rows": project_table_rows,
        "selected_branch": branch_filter or "",
        "selected_vendor": vendor_filter or "",
        "selected_project": project_filter or "",
        "all_projects": all_projects,
        # Presentation-only: lets the Project Detail Table derive a richer
        # 5-state milestone indicator (Met / Future-On Track / Future-At Risk /
        # Missed-Now Complete / Missed-Incomplete) purely in the template by
        # comparing each checkpoint's existing date/status/pct_by values
        # against "today" - no milestone calculation logic is changed.
        "today": timezone.localdate(),
    }

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("format") == "json":
        last_updated_str = kpis["last_updated"].strftime("%d %b %Y, %H:%M") if kpis["last_updated"] else "—"
        return JsonResponse({
            "kpis": {
                "total_projects": kpis["total_projects"],
                "target": kpis["target"],
                "delivered": kpis["delivered"],
                "remaining": kpis["remaining"],
                "delivery_pct": kpis["delivery_pct"],
                "total_images": kpis["total_images"],
                "total_batches": kpis["total_batches"],
                "batches_being_keyed": kpis["batches_being_keyed"],
                "promoted": kpis["promoted"],
                "promoted_pct": kpis["promoted_pct"],
                "last_updated": last_updated_str,
            },
            "branch_chart": branch_chart,
            "completion_chart": completion_chart,
            "status_chart": status_chart,
        })

    return render(request, "dashboard/home.html", context)
