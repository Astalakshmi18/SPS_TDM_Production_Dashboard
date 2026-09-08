import calendar
import datetime
import json
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
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
    "yellow": "#d97706",
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


def _get_home_operational_summary(projects, selected_cycle=None):
    """Aggregate operational overview metrics (Daily Receipts, Daily RQC, Throughput,
    Run Rate, Monthly Plan) across all filtered projects for the executive overview."""
    panels = [p.operational_panel() for p in projects]
    if not panels:
        return {
            "available_cycles": [],
            "available_cycles_json": "[]",
            "selected_cycle": "",
            "active_cycle_label": "No Projects",
            "active_cycle_range": "—",
            "active_cycle_is_current": True,
            "operational": {},
        }

    # 1. Collect and aggregate available_cycles across all filtered projects
    cycle_map = {}
    for panel in panels:
        for c in panel.get("available_cycles", []):
            k = c["month_key"]
            if k not in cycle_map:
                cycle_map[k] = {
                    "month_key": k,
                    "month_label": c["month_label"],
                    "short_label": c["short_label"],
                    "is_current": c["is_current"],
                    "date_range_label": c.get("date_range_label", ""),
                    "monthly_plan": 0.0,
                    "monthly_actual": 0.0,
                    "weekly_plan": 0.0,
                    "weekly_actual": 0.0,
                    "expected_throughput": 0.0,
                    "current_throughput": 0.0,
                    "month_receipts_total": 0.0,
                    "month_rqc_total": 0.0,
                }
            cycle_map[k]["monthly_plan"] += (c.get("monthly_plan") or 0.0)
            cycle_map[k]["monthly_actual"] += (c.get("monthly_actual") or 0.0)
            cycle_map[k]["weekly_plan"] += (c.get("weekly_plan") or 0.0)
            cycle_map[k]["weekly_actual"] += (c.get("weekly_actual") or 0.0)
            cycle_map[k]["expected_throughput"] += (c.get("expected_throughput") or 0.0)
            cycle_map[k]["current_throughput"] += (c.get("current_throughput") or 0.0)
            cycle_map[k]["month_receipts_total"] += (c.get("month_receipts_total") or 0.0)
            cycle_map[k]["month_rqc_total"] += (c.get("month_rqc_total") or 0.0)

    overall_cycles = []
    for k, data in cycle_map.items():
        m_gap = round(data["monthly_actual"] - data["monthly_plan"], 2)
        m_achieved = data["monthly_actual"] >= data["monthly_plan"] if data["monthly_plan"] > 0 else None
        tp_gap = round(data["current_throughput"] - data["expected_throughput"], 2)
        tp_achieved = data["current_throughput"] >= data["expected_throughput"] if data["expected_throughput"] > 0 else None
        w_achieved = data["weekly_actual"] >= data["weekly_plan"] if data["weekly_plan"] > 0 else None

        data["monthly_gap"] = m_gap
        data["monthly_achieved"] = m_achieved
        data["monthly_status_label"] = "Achieved" if m_achieved else ("Not Achieved" if m_achieved is False else "—")
        data["throughput_gap"] = tp_gap
        data["target_achieved_status"] = tp_achieved
        data["target_achieved_label"] = "Achieved" if tp_achieved else ("Not Achieved" if tp_achieved is False else "—")
        data["weekly_achieved"] = w_achieved
        overall_cycles.append(data)

    # Sort cycles: current cycle first, then reverse chronological
    overall_cycles.sort(key=lambda x: (not x["is_current"], x["month_key"]), reverse=False)

    # Determine active cycle (selected_cycle if valid, else the current one or first one)
    active_cycle = None
    if selected_cycle:
        active_cycle = next((c for c in overall_cycles if c["month_key"] == selected_cycle), None)
    if not active_cycle:
        active_cycle = next((c for c in overall_cycles if c["is_current"]), None) or (overall_cycles[0] if overall_cycles else None)

    # 2. Overall Daily / Active Metrics
    # Receipts
    total_branch_receipt = sum(p["branch_receipt"] or 0 for p in panels if p.get("branch_receipt") is not None)
    total_branch_target = sum(p["branch_receipt_target"] or 0 for p in panels if p.get("branch_receipt_target") is not None)
    branch_gap = round(total_branch_receipt - total_branch_target, 2)
    branch_achieved = total_branch_receipt >= total_branch_target if total_branch_target > 0 else None
    branch_status_label = "Achieved" if branch_achieved else ("Not Achieved" if branch_achieved is False else "—")

    # RQC
    total_rqc = sum(p["rqc_completed"] or 0 for p in panels if p.get("rqc_completed") is not None)
    total_rqc_target = sum(p["rqc_target"] or 0 for p in panels if p.get("rqc_target") is not None)
    rqc_gap = round(total_rqc - total_rqc_target, 2)
    rqc_achieved = total_rqc >= total_rqc_target if total_rqc_target > 0 else None
    rqc_status_label = "Achieved" if rqc_achieved else ("Not Achieved" if rqc_achieved is False else "—")

    rqc_scores = [p["rqc_quality_score"] for p in panels if p.get("rqc_quality_score") is not None]
    avg_rqc_score = round(sum(rqc_scores) / len(rqc_scores), 2) if rqc_scores else None

    # Run Rate
    total_curr_rr = sum(p["current_run_rate"] or 0 for p in panels if p.get("current_run_rate") is not None)
    total_plan_rr = sum(p["planned_run_rate"] or 0 for p in panels if p.get("planned_run_rate") is not None)
    rr_gap = round(total_curr_rr - total_plan_rr, 2)
    rr_achieved = total_curr_rr >= total_plan_rr if total_plan_rr > 0 else None
    rr_status_label = "Achieved" if rr_achieved else ("Not Achieved" if rr_achieved is False else "—")
    req_hcs = [p["required_headcount"] for p in panels if p.get("required_headcount") is not None]
    total_req_hc = round(sum(req_hcs), 1) if req_hcs else None

    # Active cycle dependent values (Throughput, Monthly Plan, Weekly)
    if active_cycle:
        curr_tp = active_cycle.get("current_throughput", 0.0)
        exp_tp = active_cycle.get("expected_throughput", 0.0)
        tp_gap = active_cycle.get("throughput_gap")
        tp_achieved = active_cycle.get("target_achieved_status")
        tp_label = active_cycle.get("target_achieved_label", "—")

        m_actual = active_cycle.get("monthly_actual", 0.0)
        m_plan = active_cycle.get("monthly_plan", 0.0)
        m_gap = active_cycle.get("monthly_gap")
        m_achieved = active_cycle.get("monthly_achieved")
        m_status_label = active_cycle.get("monthly_status_label", "—")

        w_actual = active_cycle.get("weekly_actual", 0.0)
        w_plan = active_cycle.get("weekly_plan", 0.0)
        w_achieved = active_cycle.get("weekly_achieved")

        active_cycle_label = active_cycle.get("month_label", "")
        active_cycle_range = "Live / Current" if active_cycle.get("is_current") else active_cycle.get("date_range_label", "Closed Month")
        active_cycle_is_current = bool(active_cycle.get("is_current"))
    else:
        curr_tp = sum(p["current_throughput"] or 0 for p in panels if p.get("current_throughput") is not None)
        exp_tp = sum(p["expected_throughput"] or 0 for p in panels if p.get("expected_throughput") is not None)
        tp_gap = curr_tp - exp_tp
        tp_achieved = curr_tp >= exp_tp if exp_tp > 0 else None
        tp_label = "Achieved" if tp_achieved else ("Not Achieved" if tp_achieved is False else "—")

        m_actual = sum(p["monthly_actual"] or 0 for p in panels if p.get("monthly_actual") is not None)
        m_plan = sum(p["monthly_plan"] or 0 for p in panels if p.get("monthly_plan") is not None)
        m_gap = m_actual - m_plan
        m_achieved = m_actual >= m_plan if m_plan > 0 else None
        m_status_label = "Achieved" if m_achieved else ("Not Achieved" if m_achieved is False else "—")

        w_actual = sum(p["weekly_actual"] or 0 for p in panels if p.get("weekly_actual") is not None)
        w_plan = sum(p["weekly_plan"] or 0 for p in panels if p.get("weekly_plan") is not None)
        w_achieved = w_actual >= w_plan if w_plan > 0 else None

        active_cycle_label = "Current Month"
        active_cycle_range = "Live / Current"
        active_cycle_is_current = True

    operational = {
        "branch_receipt": total_branch_receipt,
        "branch_receipt_target": total_branch_target,
        "branch_receipt_gap": branch_gap,
        "branch_receipt_achieved": branch_achieved,
        "branch_receipt_status_label": branch_status_label,
        "rqc_completed": total_rqc,
        "rqc_target": total_rqc_target,
        "rqc_gap": rqc_gap,
        "rqc_achieved": rqc_achieved,
        "rqc_status_label": rqc_status_label,
        "rqc_quality_score": avg_rqc_score,
        "current_throughput": curr_tp,
        "expected_throughput": exp_tp,
        "throughput_gap": tp_gap,
        "target_achieved_status": tp_achieved,
        "target_achieved_label": tp_label,
        "current_run_rate": total_curr_rr,
        "planned_run_rate": total_plan_rr,
        "run_rate_gap": rr_gap,
        "run_rate_achieved": rr_achieved,
        "run_rate_status_label": rr_status_label,
        "required_headcount": total_req_hc,
        "monthly_actual": m_actual,
        "monthly_plan": m_plan,
        "monthly_gap": m_gap,
        "monthly_achieved": m_achieved,
        "monthly_status_label": m_status_label,
        "weekly_actual": w_actual,
        "weekly_plan": w_plan,
        "weekly_achieved": w_achieved,
        "available_cycles": overall_cycles,
        "available_cycles_json": json.dumps(overall_cycles),
        "active_cycle_key": active_cycle.get("month_key") if active_cycle else None,
        "monthly_label": active_cycle_label,
    }

    return {
        "available_cycles": overall_cycles,
        "available_cycles_json": json.dumps(overall_cycles),
        "selected_cycle": active_cycle.get("month_key") if active_cycle else None,
        "active_cycle_label": active_cycle_label,
        "active_cycle_range": active_cycle_range,
        "active_cycle_is_current": active_cycle_is_current,
        "operational": operational,
    }


@login_required
def home(request):
    all_projects = accessible_projects(request).select_related("branch")
    branches = accessible_branches(request)

    branch_filter = request.GET.get("branch")
    customer_filter = request.GET.get("customer")
    vendor_filter = request.GET.get("vendor")
    project_filter = request.GET.get("project")
    gm_filter = request.GET.get("gm")
    cycle_filter = request.GET.get("cycle")

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
    if customer_filter:
        projects = projects.filter(customer_name=customer_filter)
    if vendor_filter:
        projects = projects.filter(vendor=vendor_filter)
    if project_filter:
        projects = projects.filter(pk=project_filter)
    if gm_filter:
        projects = projects.filter(gm_name=gm_filter)

    ops_summary = _get_home_operational_summary(projects, selected_cycle=cycle_filter)

    totals = projects.aggregate(target=Sum("target_records"), delivered=Sum("delivered_records"),
                                 images=Sum("total_images"))
    target = totals["target"] or 0
    delivered = totals["delivered"] or 0
    images = totals["images"] or 0
    remaining = max(target - delivered, 0)
    delivery_pct = round((delivered / target) * 100, 2) if target else 0.0

    # Total Batches / Batches Being Processed / Promoted: summed per-project via
    # Single pass over `projects`, computing everything every section below
    # needs ONCE per project - batches_keying_panel() and
    # milestone_shipment_checkpoints() were each being called TWICE per
    # project before (once here for the KPI/milestone-summary totals, again
    # further down for the detail tables), doubling their underlying
    # InventoryItem queries for no reason; this computes each once and
    # reuses it everywhere below. Output is unchanged - same values land in
    # the same places, just without the repeat work.
    per_project = []
    total_batches = 0
    batches_being_keyed = 0
    promoted = 0
    for p in projects:
        panel = p.batches_keying_panel()
        checkpoints = {c["label"]: c for c in p.milestone_shipment_checkpoints()}
        idx_start = {m["label"]: m for m in p.milestones()}.get("IDX Start")

        total_batches += panel["total_batches"]
        batches_being_keyed += panel["batches_being_keyed"]
        promoted += p.promoted

        per_project.append({"project": p, "batches": panel, "checkpoints": checkpoints, "idx_start": idx_start})
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
    status_labels_map = {"green": "On Track", "yellow": "At Risk", "red": "Behind"}
    status_colors_map = {"green": "#22c55e", "yellow": "#d97706", "red": "#ef4444"}
    status_chart = {
        "labels": [status_labels_map.get(s, s.capitalize()) for s in status_counts.keys()],
        "values": list(status_counts.values()),
        "colors": [status_colors_map.get(s, "#94a3b8") for s in status_counts.keys()],
    }

    # PHX-style Milestone Summary: bucket every project by its 100% checkpoint
    # status, plus a full per-project milestone table (IDX Start/10%/50%/100%).
    # milestone_100_status (a Project property) internally calls
    # milestone_shipment_checkpoints() itself too - reading the 100% entry
    # straight out of the already-computed `checkpoints` above avoids
    # triggering that a THIRD time per project.
    milestone_100_counts = Counter(pp["checkpoints"].get("100%", {}).get("status") for pp in per_project)
    milestone_summary = [
        {"key": key, "label": label, "count": milestone_100_counts.get(key, 0), "color": MILESTONE_STATUS_COLORS[key]}
        for key, label in MILESTONE_STATUS_LABELS.items()
        if milestone_100_counts.get(key, 0) > 0
    ]
    # m10/m50/m100 come from milestone_shipment_checkpoints() - the REAL,
    # actually-shipped-by-that-date % (Inventory page Shipment Date column)
    # and its own Green/Yellow/Red, rather than the straight-line pace
    # estimate milestones() uses on its own. IDX Start (= Project Start,
    # always day zero) still comes from milestones() since there's no
    # "shipped by project start" figure to compute.
    milestone_table_rows = [
        {
            "project": pp["project"],
            "idx_start": pp["idx_start"],
            "m10": pp["checkpoints"].get("10%"),
            "m50": pp["checkpoints"].get("50%"),
            "m100": pp["checkpoints"].get("100%"),
            "batches": pp["batches"],
        }
        for pp in per_project
    ]

    # Project Detail Table (bottom of page): Total Volume/Delivered/Remaining
    # + week-based Expected % + the 10%/50%/100% checkpoint dates paired
    # with "PctBy X%" (actual shipped-by-that-date % from the Inventory
    # page's own shipment_date column - see Project.milestone_shipment_
    # checkpoints).
    project_table_rows = [
        {
            "project": pp["project"],
            "cp10": pp["checkpoints"].get("10%"),
            "cp50": pp["checkpoints"].get("50%"),
            "cp100": pp["checkpoints"].get("100%"),
            "weekly_delivery_plan": pp["project"].weekly_delivery_plan(),
        }
        for pp in per_project
    ]

    context = {
        "kpis": kpis,
        "projects": projects,
        "branches": branches,
        "show_branch_filter": branches.count() > 1,
        "show_project_filter": all_projects.count() > 1,
        "vendors": _distinct_ci(all_projects, "vendor"),
        "customers": _distinct_ci(all_projects, "customer_name"),
        "gms": _distinct_ci(all_projects, "gm_name"),
        "branch_chart_json": json.dumps(branch_chart),
        "completion_chart_json": json.dumps(completion_chart),
        "status_chart_json": json.dumps(status_chart),
        "milestone_summary": milestone_summary,
        "milestone_total": sum(m["count"] for m in milestone_summary),
        "milestone_table_rows": milestone_table_rows,
        "project_table_rows": project_table_rows,
        "selected_branch": branch_filter or "",
        "selected_customer": customer_filter or "",
        "selected_vendor": vendor_filter or "",
        "selected_project": project_filter or "",
        "selected_gm": gm_filter or "",
        "all_projects": all_projects,
        # Presentation-only: lets the Project Detail Table derive a richer
        # 5-state milestone indicator (Met / Future-On Track / Future-At Risk /
        # Missed-Now Complete / Missed-Incomplete) purely in the template by
        # comparing each checkpoint's existing date/status/pct_by values
        # against "today" - no milestone calculation logic is changed.
        "today": timezone.localdate(),
    }
    context.update(ops_summary)

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


@login_required
def operational(request):
    """Project-Level Operational Dashboard (ops-review request): one row per
    project with Monthly/Weekly Plan, GM/PM/PL, Daily Branch Receipt/RQC
    Completed, Expected/Current Throughput, Headcount split, Variance vs
    Plan, Planned/Current Run Rate, RQC Quality Score, Required Headcount -
    plus the 4 alert types, and an Executive Summary strip (CEO/MD view)
    condensing the whole portfolio to counts + the top at-risk projects."""
    all_projects = accessible_projects(request).select_related("branch")
    branches = accessible_branches(request)

    branch_filter = request.GET.get("branch")
    project_filter = request.GET.get("project")
    projects = all_projects
    if branch_filter:
        projects = projects.filter(branch__code=branch_filter)
    if project_filter:
        projects = projects.filter(pk=project_filter)

    rows = []
    all_alerts = []
    for p in projects:
        alerts = p.operational_alerts()
        rows.append({"panel": p.operational_panel(), "alerts": alerts})
        all_alerts.extend(alerts)

    alert_counts = Counter(a["level"] for a in all_alerts)
    alerts_by_project = Counter(a["project"].pk for a in all_alerts)
    # CEO/MD executive summary: rank projects by how many red/yellow alerts
    # they're carrying (red weighted heavier) so leadership sees the
    # projects needing a call TODAY at the top, not just an alphabetical list.
    risk_weight = Counter()
    for a in all_alerts:
        risk_weight[a["project"].pk] += 3 if a["level"] == "red" else 1
    top_at_risk = sorted(
        ({"project": p, "alert_count": alerts_by_project.get(p.pk, 0)} for p in projects if alerts_by_project.get(p.pk)),
        key=lambda r: risk_weight[r["project"].pk], reverse=True,
    )[:5]

    context = {
        "rows": rows,
        "branches": branches,
        "show_branch_filter": branches.count() > 1,
        "show_project_filter": all_projects.count() > 1,
        "all_projects": all_projects,
        "selected_branch": branch_filter or "",
        "selected_project": project_filter or "",
        "exec_summary": {
            "total_projects": projects.count(),
            "red_count": alert_counts.get("red", 0),
            "yellow_count": alert_counts.get("yellow", 0),
            "clean_count": projects.count() - len(alerts_by_project),
            "top_at_risk": top_at_risk,
        },
    }
    return render(request, "dashboard/operational.html", context)


@login_required
def operational_calendar(request, pk):
    """Per-project Calendar view for the Operational Dashboard (an
    alternative to the Project-Level Operational Review table, not a
    replacement for it - see operational.html's Table/Calendar toggle).
    Renders a month grid; clicking a date fetches that day's + its week's +
    its month's Branch Receipt/RQC Completed/RQC Quality Score via
    operational_day_detail_json below, without a full page reload."""
    project = get_object_or_404(accessible_projects(request), pk=pk)

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    cal = calendar.Calendar(firstweekday=0)  # Monday-first, matches WeeklyDeliveryPlanRow's own week convention
    month_days = cal.monthdayscalendar(year, month)  # list of weeks, each a list of 7 ints (0 = day outside this month)
    data_days = set(project.daily_metric_dates(year, month))

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    context = {
        "project": project,
        "all_projects": accessible_projects(request),
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "month_days": month_days,
        "data_days": data_days,
        "today": today,
        "prev_year": prev_year, "prev_month": prev_month,
        "next_year": next_year, "next_month": next_month,
    }
    return render(request, "dashboard/operational_calendar.html", context)


@login_required
def operational_day_detail_json(request, pk, date):
    """JSON backing operational_calendar's date-click panel - day/week/
    month rollup for Branch Receipt and RQC Completed, plus the (dateless,
    running-average) RQC Quality Score figure."""
    project = get_object_or_404(accessible_projects(request), pk=pk)
    try:
        target_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse({"error": "invalid date"}, status=400)

    detail = project.operational_day_detail(target_date)
    return JsonResponse({
        "date": detail["date"].isoformat(),
        "week_start": detail["week_start"].isoformat(),
        "week_end": detail["week_end"].isoformat(),
        "month_start": detail["month_start"].isoformat(),
        "month_end": detail["month_end"].isoformat(),
        "branch_receipt": detail["branch_receipt"],
        "rqc_completed": detail["rqc_completed"],
        "rqc_quality_score": detail["rqc_quality_score"],
    })

