"""
Excel Import Engine
====================
Workflow (matches the brief exactly):
  1. User uploads Excel.
  2. Select project (ProjectTemplate).
  3. Load mapping (ProjectTemplate.config).
  4. Validate headers (mapping.engine.validate_headers).
  5. Convert into common schema (mapping.engine.apply_mapping).
  6. Save into database (Project, upserted by project_key + branch).
  7. Dashboard auto refreshes (it always reads live from Project - no cache).
"""
import datetime
import re
from django.db import transaction

from apps.branches.models import Branch
from apps.mapping.engine import apply_mapping
from .models import ImportBatch, Project


def _parse_month_cell(val, default_year=None):
    """Normalize any month cell (datetime, date, or string like 'August', 'Aug 2026', 'Februay 2026')
    into (month_key 'YYYY-MM', month_label 'Month YYYY', month_date 'YYYY-MM-DD')."""
    if val is None:
        return "", "", ""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m"), val.strftime("%B %Y"), val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if not s:
        return "", "", ""

    # Fix common typos (e.g. Februay -> February)
    norm_s = re.sub(r"(?i)\bfebruay\b", "February", s)

    # If already YYYY-MM
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", norm_s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        try:
            d = datetime.date(y, mo, 1)
            return d.strftime("%Y-%m"), d.strftime("%B %Y"), d.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Try dateutil parser
    from dateutil import parser
    cur_year = default_year or datetime.date.today().year
    try:
        dt = parser.parse(norm_s, default=datetime.datetime(cur_year, 1, 1))
        d = dt.date().replace(day=1)
        return d.strftime("%Y-%m"), d.strftime("%B %Y"), d.strftime("%Y-%m-%d")
    except Exception:
        pass

    clean_key = re.sub(r"[^a-zA-Z0-9_-]", "-", s).strip("-")
    return clean_key, s, clean_key


def _num(v):
    """Reads a numeric value defensively - real sheets have stray text
    ("Exatech" typed into a Received Records cell) and Excel errors
    (#VALUE!) sitting in cells that are supposed to be numbers. Either
    just means "not available", not a crash."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or s.startswith("#"):
            return None
        try:
            return float(s.replace(",", "").replace("%", ""))
        except ValueError:
            return None
    if hasattr(v, "year"):  # a date landed in a numeric cell - not usable here
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cell_num(ws, addr):
    return _num(ws[addr].value)


def _cell_date(ws, addr):
    v = ws[addr].value
    return v.date() if hasattr(v, "date") else (v if hasattr(v, "year") else None)


def read_project_summary_snapshot(xls_path):
    """Reads the Project/Production Summary sheet's OWN pre-computed cells -
    Delivered/Received Records, %, Days Gone, Remaining Days etc. - directly,
    instead of Python re-deriving them. The tab itself may be named either
    "Project Summary" or "Production Summary" (both seen in real project
    files) - whichever is present is used. Every real project file checked
    (Latvia, Newspaper, BPW, BV_AT, ANC) uses the identical cell layout:
      B1/D1/F1/H1  = status-as-of date / start / end / total days
      B2/C2        = volume / unit label ("records" or "Pages")
      A4/B4/C4     = Delivered label / value / Days Gone
      B5           = Delivered %
      B6           = Days Gone %
      A8/B8/C8     = Remaining label / value / Remaining Days
      B9           = Remaining %
      B10          = Remaining Days %
      B13/A14/B14  = Branch Status as-of date / Received label / value
      B15          = Received %
    Sanity-checked against A1's label before trusting any of it - if a
    project's sheet doesn't follow this layout, this quietly returns {}
    and the panel falls back to the Selected_Column / imported-field path."""
    import openpyxl

    try:
        try:
            wb = openpyxl.load_workbook(xls_path, data_only=True, read_only=True)
        except Exception:
            wb = openpyxl.load_workbook(xls_path, data_only=True, read_only=False)
    except Exception:
        return {}
    # Real project files use either "Project Summary" or "Production
    # Summary" as this tab's name - same layout, just a naming difference
    # between templates. Try both rather than hardcoding one and silently
    # returning {} (and losing volume_unit/delivered_pct/days_gone/etc, not
    # just the sheet lookup itself) for every file that uses the other name.
    sheet_name = next((n for n in ("Project Summary", "Production Summary") if n in wb.sheetnames), None)
    if sheet_name is None:
        return {}
    ws = wb[sheet_name]

    a1 = str(ws["A1"].value or "").strip().lower()
    if "project status" not in a1:
        return {}  # not the layout we expect - don't guess

    delivered_pct = _cell_num(ws, "B5")
    days_gone_pct = _cell_num(ws, "B6")
    remaining_pct = _cell_num(ws, "B9")
    remaining_days_pct = _cell_num(ws, "B10")
    received_pct = _cell_num(ws, "B15")

    return {
        "status_as_of": str(_cell_date(ws, "B1") or ""),
        "start_date": str(_cell_date(ws, "D1") or ""),
        "end_date": str(_cell_date(ws, "F1") or ""),
        "total_days": _cell_num(ws, "H1"),
        "volume": _cell_num(ws, "B2"),
        "volume_unit": str(ws["C2"].value or "").strip(),
        "delivered_label": str(ws["A4"].value or "Delivered Records").strip(),
        "delivered": _cell_num(ws, "B4"),
        "days_gone": _cell_num(ws, "C4"),
        "delivered_pct": round(delivered_pct * 100, 2) if delivered_pct is not None else None,
        "days_gone_pct": round(days_gone_pct * 100, 2) if days_gone_pct is not None else None,
        "remaining_label": str(ws["A8"].value or "Remaining Records").strip(),
        "remaining": _cell_num(ws, "B8"),
        "remaining_days": _cell_num(ws, "C8"),
        "remaining_pct": round(remaining_pct * 100, 2) if remaining_pct is not None else None,
        "remaining_days_pct": round(remaining_days_pct * 100, 2) if remaining_days_pct is not None else None,
        "branch_status_as_of": str(_cell_date(ws, "B13") or ""),
        "received_label": str(ws["A14"].value or "Received Records").strip(),
        "received": _cell_num(ws, "B14"),
        "received_pct": round(received_pct * 100, 2) if received_pct is not None else None,
    }


def _norm_label(s):
    return " ".join(str(s).split()).strip().lower()


# "AI for This month" is a label(col A)/value(col B) sheet, same free-form
# shape as "Project Summary" - matched by LABEL text (not fixed row numbers)
# since this table has extra rows above/between it (Start/End Date Formula,
# Holidays) that can shift where a given label lands.
_AI_MONTH_LABELS = {
    "target": "ai_month_target",
    "recd from branch": "recd_from_branch",
    "qc processed": "qc_processed",
    "current run rate": "current_run_rate",
    "required run rate": "planned_run_rate",
    "working days": "ai_month_working_days",
    "days completed": "ai_month_days_completed",
    "delivered to client": "delivered_to_client",
    "pmname": "pm_name",
}


def _read_ai_for_this_month(wb):
    """Current Run Rate / Required Run Rate (= Planned Run Rate on the
    dashboard) straight from the "AI for This month" sheet's own cells."""
    sheet_name = next((n for n in wb.sheetnames if _norm_label(n) == "ai for this month"), None)
    if sheet_name is None:
        return {}
    ws = wb[sheet_name]
    out = {}
    for row in ws.iter_rows(min_row=1, max_row=40, max_col=3):
        label_cell = row[0].value
        if label_cell is None:
            continue
        key = _AI_MONTH_LABELS.get(_norm_label(label_cell))
        if not key:
            continue
        value = row[1].value if len(row) > 1 else None
        out[key] = str(value or "").strip() if key == "pm_name" else _num(value)

    crr = out.get("current_run_rate")
    prr = out.get("planned_run_rate")
    if crr is not None and prr is not None:
        gap = round(crr - prr, 2)
        out["run_rate_gap"] = gap
        out["run_rate_gap_pct"] = round((gap / prr) * 100, 2) if prr else 0.0
        out["run_rate_achieved"] = bool(crr >= prr)

    return out


def _read_project_insights_ops(wb):
    """Expected Throughput (= "Quoted Throughput"), Current Throughput, and
    Branch/Inhouse Headcount straight from the "Project Insights" sheet's
    own two small tables (Month/Target Achieved/.../Throughput/Gap/Gap%,
    and Months/Throughput(Branch,Inhouse)/Head Count(Branch,Inhouse)).
    Located by matching each table's own header row text, not a fixed row
    number, since real files vary in how many rows sit above them.
    "Current" = the most recently CLOSED-OUT month (the last row with a
    Target Achieved value filled in) rather than the newest row outright,
    since an in-progress month's row is usually still all zeros/blank."""
    sheet_name = next((n for n in wb.sheetnames if _norm_label(n) == "project insights"), None)
    if sheet_name is None:
        return {}
    ws = wb[sheet_name]
    rows = [[c.value for c in r] for r in ws.iter_rows(min_row=1, max_row=60)]

    out = {}
    monthly_header_idx = None
    headcount_header_idx = None
    for i, vals in enumerate(rows):
        a = _norm_label(vals[0]) if vals and vals[0] is not None else ""
        b = _norm_label(vals[1]) if len(vals) > 1 and vals[1] is not None else ""
        if a == "quoted throughput":
            out["quoted_throughput"] = _num(vals[1] if len(vals) > 1 else None)
        elif a == "month" and b == "target achieved":
            monthly_header_idx = i
        elif a == "" and b == "branch" and len(vals) > 2 and _norm_label(vals[2]) == "inhouse":
            headcount_header_idx = i

    table2_by_month = {}
    last_table2_row = None
    if headcount_header_idx is not None:
        for vals in rows[headcount_header_idx + 1:]:
            if not vals or (vals[0] is None and all(v is None for v in vals[1:5])):
                break  # blank row - table's over
            last_table2_row = vals
            m_key_t2, m_lbl_t2, _ = _parse_month_cell(vals[0])
            row_dict = {
                "throughput_branch": _num(vals[1]) if len(vals) > 1 else None,
                "throughput_inhouse": _num(vals[2]) if len(vals) > 2 else None,
                "headcount_branch": _num(vals[3]) if len(vals) > 3 else None,
                "headcount_inhouse": _num(vals[4]) if len(vals) > 4 else None,
            }
            if m_key_t2:
                table2_by_month[m_key_t2] = row_dict

    if monthly_header_idx is not None:
        monthly_cycles = []
        for vals in rows[monthly_header_idx + 1:]:
            if not vals or vals[0] is None:
                break  # blank row - table's over
            month_val = vals[0]
            m_key, m_label, m_date = _parse_month_cell(month_val)
            if not m_key:
                continue
            target_achieved = _num(vals[1]) if len(vals) > 1 else None
            manpower_used = _num(vals[2]) if len(vals) > 2 else None
            working_days = _num(vals[3]) if len(vals) > 3 else None
            per_head_tp = _num(vals[4]) if len(vals) > 4 else None
            gap_val = _num(vals[5]) if len(vals) > 5 else None

            quoted_tp = out.get("quoted_throughput")
            if quoted_tp is None and per_head_tp is not None and gap_val is not None:
                quoted_tp = per_head_tp - gap_val
                out["quoted_throughput"] = quoted_tp

            # User formula: Expected Throughput = Quoted Throughput
            expected_tp = quoted_tp if quoted_tp is not None else None

            # Current Throughput = Inventory data / Branch Manpower / Working Days
            if target_achieved is not None and manpower_used and working_days:
                current_tp = round(target_achieved / (manpower_used * working_days), 2)
            elif per_head_tp is not None:
                current_tp = per_head_tp
            elif target_achieved is not None:
                current_tp = target_achieved
            else:
                current_tp = 0.0

            tp_status = bool(current_tp >= expected_tp) if (expected_tp and current_tp is not None) else None
            tp_gap = round(current_tp - expected_tp, 2) if (expected_tp is not None and current_tp is not None) else None
            tp_gap_pct = round((tp_gap / expected_tp) * 100, 2) if (expected_tp and tp_gap is not None) else 0.0

            monthly_cycles.append({
                "month_label": m_label,
                "month_date": m_date,
                "month_key": m_key,
                "target_achieved": target_achieved,
                "manpower_used": manpower_used,
                "working_days": working_days,
                "per_head_throughput": per_head_tp,
                "quoted_throughput": quoted_tp,
                "expected_throughput": expected_tp,
                "current_throughput": current_tp,
                "target_achieved_status": tp_status,
                "throughput_gap": tp_gap,
                "throughput_gap_pct": tp_gap_pct,
                "is_closed": bool(target_achieved is not None and target_achieved > 0),
            })

        # Match Table 2 headcount and track running previous-month manpower
        last_valid_manpower = None
        last_valid_hc_branch = None
        last_valid_hc_inhouse = None
        last_valid_tp_branch = None
        last_valid_tp_inhouse = None

        for c in monthly_cycles:
            t2 = table2_by_month.get(c["month_key"]) or {}
            c["throughput_branch"] = t2.get("throughput_branch")
            c["throughput_inhouse"] = t2.get("throughput_inhouse")
            c["headcount_branch"] = t2.get("headcount_branch")
            c["headcount_inhouse"] = t2.get("headcount_inhouse")

            if c.get("manpower_used") and float(c["manpower_used"]) > 0:
                last_valid_manpower = float(c["manpower_used"])
            if c.get("headcount_branch") and float(c["headcount_branch"]) > 0:
                last_valid_hc_branch = float(c["headcount_branch"])
            if c.get("headcount_inhouse") and float(c["headcount_inhouse"]) > 0:
                last_valid_hc_inhouse = float(c["headcount_inhouse"])
            if c.get("throughput_branch") and float(c["throughput_branch"]) > 0:
                last_valid_tp_branch = float(c["throughput_branch"])
            if c.get("throughput_inhouse") and float(c["throughput_inhouse"]) > 0:
                last_valid_tp_inhouse = float(c["throughput_inhouse"])

            c["effective_manpower"] = c.get("manpower_used") or last_valid_manpower

        out["monthly_cycles"] = monthly_cycles

        # User rule: If Current Month has manpower details, use them;
        # otherwise, fall back to the most recent Previous Month's data!
        import datetime
        today = datetime.date.today()
        today_key = today.strftime("%Y-%m")
        current_cycle = next((c for c in monthly_cycles if c["month_key"] == today_key), None)

        eff_mp = (current_cycle.get("manpower_used") if current_cycle else None) or last_valid_manpower
        eff_hc_br = (current_cycle.get("headcount_branch") if current_cycle else None) or last_valid_hc_branch
        eff_hc_in = (current_cycle.get("headcount_inhouse") if current_cycle else None) or last_valid_hc_inhouse
        eff_tp_br = (current_cycle.get("throughput_branch") if current_cycle else None) or last_valid_tp_branch
        eff_tp_in = (current_cycle.get("throughput_inhouse") if current_cycle else None) or last_valid_tp_inhouse

        if current_cycle:
            out["month_label"] = current_cycle["month_label"]
            out["month_key"] = current_cycle["month_key"]
            out["target_achieved"] = current_cycle["target_achieved"]
            out["manpower_used"] = eff_mp
            out["working_days"] = current_cycle["working_days"]
            out["per_head_throughput"] = current_cycle["per_head_throughput"]
            out["expected_throughput"] = current_cycle["expected_throughput"]
            out["current_throughput"] = current_cycle["current_throughput"]
            out["target_achieved_status"] = current_cycle["target_achieved_status"]
            out["throughput_gap"] = current_cycle["throughput_gap"]
            out["throughput_gap_pct"] = current_cycle["throughput_gap_pct"]
            current_cycle["manpower_used"] = eff_mp
        else:
            out["month_label"] = today.strftime("%B %Y")
            out["month_key"] = today_key
            out["target_achieved"] = None
            out["manpower_used"] = eff_mp
            out["working_days"] = None
            out["per_head_throughput"] = None
            out["expected_throughput"] = out.get("quoted_throughput")
            out["current_throughput"] = 0.0
            out["target_achieved_status"] = None
            out["throughput_gap"] = None
            out["throughput_gap_pct"] = None

        if eff_tp_br is not None:
            out["throughput_branch"] = eff_tp_br
        if eff_tp_in is not None:
            out["throughput_inhouse"] = eff_tp_in
        if eff_hc_br is not None:
            out["headcount_branch"] = eff_hc_br
        if eff_hc_in is not None:
            out["headcount_inhouse"] = eff_hc_in

    # Fallback for Table 2 if not set from cycles
    if last_table2_row:
        if out.get("throughput_branch") is None and len(last_table2_row) > 1:
            out["throughput_branch"] = _num(last_table2_row[1])
        if out.get("throughput_inhouse") is None and len(last_table2_row) > 2:
            out["throughput_inhouse"] = _num(last_table2_row[2])
        if out.get("headcount_branch") is None and len(last_table2_row) > 3:
            out["headcount_branch"] = _num(last_table2_row[3])
        if out.get("headcount_inhouse") is None and len(last_table2_row) > 4:
            out["headcount_inhouse"] = _num(last_table2_row[4])

    return out


def read_operational_snapshot(xls_path):
    """Project-Level Operational Dashboard snapshot: Expected/Current
    Throughput, Branch/Inhouse Headcount ("Project Insights" sheet) and
    Planned/Current Run Rate ("AI for This month" sheet) - the source
    sheets' OWN numbers, read directly at import time, same principle as
    read_project_summary_snapshot(). Verified against BPW and BV_AT's real
    layout; a template whose workbook doesn't have these two tabs (or
    doesn't follow this same label layout) just gets {} back here - the
    Operational Dashboard then shows "—" for that project's row instead of
    guessing."""
    import openpyxl

    try:
        try:
            wb = openpyxl.load_workbook(xls_path, data_only=True, read_only=True)
        except Exception:
            wb = openpyxl.load_workbook(xls_path, data_only=True, read_only=False)
    except Exception:
        return {}
    try:
        out = {}
        out.update(_read_ai_for_this_month(wb))
        out.update(_read_project_insights_ops(wb))
        return out
    finally:
        wb.close()


def _safe_int(value):
    """Coerces an Excel cell value to int, tolerating the placeholder junk
    real trackers are full of: '-' or '—' for zero, blank strings, 'N/A',
    thousands separators ('1,234'), stray whitespace, floats-as-strings,
    and outright None. Anything that isn't actually a number becomes 0
    rather than crashing the whole import over one bad cell."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        try:
            import math
            if isinstance(value, float) and math.isnan(value):
                return 0
        except Exception:
            pass
        return int(value)
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "—", "–", "N/A", "n/a", "NA", "None"):
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _parse_date(value):
    """Safely coerces an Excel or pandas cell value to datetime.date.
    Tolerates datetime, date, pd.Timestamp, and strings in various formats
    ('17-08-2026', '2026-08-17', etc.) while turning blanks/placeholders
    to None.
    """
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if hasattr(value, "year"):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("", "-", "—", "–", "n/a", "na", "none", "nan", "null"):
            return None
        import pandas as pd
        try:
            parsed = pd.to_datetime(text, format="mixed", errors="coerce")
            if parsed is not None and not pd.isna(parsed):
                return parsed.date()
        except Exception:
            return None
    return None


def run_import(template, uploaded_file, django_file_field_path, user,
                source_type=ImportBatch.SOURCE_FILE, source_url=""):
    """template: ProjectTemplate instance
    uploaded_file: the saved path on disk (import needs a real path for pandas/openpyxl) -
        for a Google Sheet import this is the downloaded .xlsx copy, not the live sheet.
    django_file_field_path: original filename (or sheet title), for the audit log
    user: request.user
    source_type / source_url: recorded on ImportBatch for traceability
    """
    result = apply_mapping(uploaded_file, template.config)

    if not result.is_valid:
        ImportBatch.objects.create(
            project_template_key=template.project_key,
            file_name=django_file_field_path,
            source_type=source_type,
            source_url=source_url,
            uploaded_by=user,
            status=ImportBatch.STATUS_FAILED,
            errors=result.errors,
        )
        return None, result.errors

    values = result.values
    branch = Branch.objects.filter(code=values.get("branch")).first() or template.branch

    op_snapshot = read_operational_snapshot(uploaded_file)
    if result.daily_metrics:
        # Template-Mapping-configured daily figures (config["daily_metrics"]
        # - see apps/mapping/engine.py:extract_daily_metric) take priority
        # over anything read_operational_snapshot() itself came up with for
        # the SAME keys, since a project that has this configured is opting
        # into "read it from the sheet via mapping" over the old per-project
        # manual column-key picker (branch_receipt_column_key etc., still
        # used as a fallback for projects that don't have this configured).
        op_snapshot.update({k: v["value"] for k, v in result.daily_metrics.items()})
        op_snapshot["daily_metrics_as_of"] = {k: v["as_of"] for k, v in result.daily_metrics.items()}

    # Any operational metrics explicitly configured via Template Mapping take priority:
    for tp_key in ("throughput_branch", "throughput_inhouse", "quoted_throughput"):
        if values.get(tp_key) not in (None, "", 0):
            op_snapshot[tp_key] = float(values[tp_key])

    branch_hc_mapped = values.get("branch_manpower_count")
    if branch_hc_mapped not in (None, "", 0):
        op_snapshot["headcount_branch"] = _safe_int(branch_hc_mapped)

    inhouse_hc_mapped = values.get("inhouse_manpower_count")
    if inhouse_hc_mapped not in (None, "", 0):
        op_snapshot["headcount_inhouse"] = _safe_int(inhouse_hc_mapped)

    defaults = {
        "project_name": values.get("project_name") or template.display_name,
        "start_date": values["start_date"],
        "end_date": values["end_date"],
        "target_records": _safe_int(values.get("target")),
        "delivered_records": _safe_int(values.get("delivered")),
        "total_images": _safe_int(values.get("images")),
        "total_batches": _safe_int(values.get("total_batches")),
        "batches_being_keyed": _safe_int(values.get("batches_being_keyed")),
        "promoted": _safe_int(values.get("promoted")),
        "language": values.get("language") or "",
        "customer_name": (getattr(template, "customer_name", "") or values.get("customer_name") or ""),
        "vendor": values.get("vendor") or "",
        "event_type": values.get("event_type") or "",
        "ocr_status": values.get("ocr_status") or "",
        "gm_name": values.get("gm_name") or "",
        "pm_name": values.get("pm_name") or "",
        "pl_name": values.get("pl_name") or "",
        "branch_manpower_count": _safe_int(values.get("branch_manpower_count") or op_snapshot.get("headcount_branch")),
        "inhouse_manpower_count": _safe_int(values.get("inhouse_manpower_count") or op_snapshot.get("headcount_inhouse")),
        "extra_data": result.extra,
        "summary_snapshot": read_project_summary_snapshot(uploaded_file),
        "operational_snapshot": op_snapshot,
    }
    if source_type == ImportBatch.SOURCE_GOOGLE_SHEET and source_url:
        defaults["google_sheet_url"] = source_url

    project, _ = Project.objects.update_or_create(
        project_key=template.project_key,
        branch=branch,
        defaults=defaults,
    )

    # Everything from here is one commit, not several - the Project upsert,
    # the full inventory replace, and the derived batch metrics used to each
    # autocommit separately, which is real added time on a big sync.
    with transaction.atomic():
        _replace_inventory_items(project, result.inventory_rows)
        _replace_weekly_delivery_rows(project, result.weekly_delivery_rows)
        _replace_daily_operational_metrics(project, result.daily_metric_series)

        # Only derive batch metrics from inventory rows when the template
        # didn't already explicitly map total_batches/promoted to real
        # cells/columns - an explicit mapping is more authoritative than our
        # own row-count guess and must never be silently overwritten.
        if values.get("total_batches") in (None, "") and values.get("promoted") in (None, ""):
            _derive_batch_metrics(project)

    ImportBatch.objects.create(
        project_template_key=template.project_key,
        file_name=django_file_field_path,
        source_type=source_type,
        source_url=source_url,
        uploaded_by=user,
        status=ImportBatch.STATUS_SUCCESS,
        project=project,
        # Non-blocking issues (e.g. an optional field's rule pointing at a
        # column this workbook doesn't have) - the import still succeeded,
        # this is just visibility into what got skipped, on the same
        # SUCCESS batch record rather than a separate failure.
        errors=result.warnings,
    )

    return project, []


def _clean_text(value):
    """Converts a raw cell value to display text, stripping the trailing
    '.0' that whole-number-valued file/folder names pick up when Excel
    stores them as floats (e.g. 105913085.0 -> "105913085", not left as-is
    which would show a meaningless decimal on every ID in the Inventory
    Tracker). Also treats NaN as blank - pandas represents an empty Excel
    cell as float('nan'), and str(nan) is the truthy string "nan", which
    would otherwise defeat blank-row detection entirely."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:  # NaN != NaN is the classic, dependency-free NaN check
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value)


def _replace_inventory_items(project, rows):
    """Every (re)import fully replaces this project's inventory rows - the
    source file/sheet is always the single source of truth, so partial
    merges would just accumulate stale rows over time.

    Wrapped in one DB transaction with a chunked bulk_create: on a project
    with tens of thousands of inventory rows, letting Django autocommit each
    statement (the default) was the single biggest cost in "Sync Now" -
    batching writes into one transaction cuts that dramatically."""
    from django.db import transaction

    from apps.inventory.models import InventoryItem

    if not rows:
        return

    items = []
    for row in rows:
        shipment_date = _parse_date(row.get("shipment_date"))

        file_name = _clean_text(row.get("file_name"))
        folder_name = _clean_text(row.get("folder_name"))
        image_count = _safe_int(row.get("image_count"))
        record_count = _safe_int(row.get("record_count"))

        # Skip fully-blank rows (e.g. an unfinished project's Calculation
        # sheet with placeholder empty rows) - these add nothing but noise
        # to the Inventory Tracker.
        if not file_name and not folder_name and not image_count and not record_count and not shipment_date:
            continue

        known = {"file_name", "folder_name", "event_type", "language",
                 "image_count", "record_count", "shipment_date", "remarks"}
        extra = {
            k: (v.strftime("%Y-%m-%d") if hasattr(v, "year") else v)
            for k, v in row.items() if k not in known
        }

        items.append(InventoryItem(
            project=project,
            file_name=file_name,
            folder_name=folder_name,
            event_type=_clean_text(row.get("event_type")),
            language=_clean_text(row.get("language")),
            image_count=image_count,
            record_count=record_count,
            shipment_date=shipment_date,
            remarks=str(row.get("remarks") or ""),
            extra=extra,
        ))

    with transaction.atomic():
        InventoryItem.objects.filter(project=project).delete()
        InventoryItem.objects.bulk_create(items, batch_size=1000)


def _replace_weekly_delivery_rows(project, rows):
    """Same 'source file is the single source of truth, full replace on
    every (re)import' rule as _replace_inventory_items - and same guard: if
    `rows` comes back empty (field not mapped for this template, or this
    sheet had nothing this run), existing rows are left alone rather than
    wiped, so a transient parsing hiccup can't silently blank out a
    project's whole delivery plan history."""
    from django.db import transaction

    import pandas as pd

    from apps.projects.models import WeeklyDeliveryPlanRow

    if not rows:
        return

    items = []
    for row in rows:
        month_label = str(row.get("month_label") or "").strip()
        month_start = None
        if month_label:
            m_key, norm_label, m_date = _parse_month_cell(month_label)
            if m_date:
                try:
                    month_start = datetime.date.fromisoformat(m_date)
                except Exception:
                    pass
            if not month_start:
                try:
                    parsed = pd.to_datetime(norm_label or month_label, errors="coerce")
                    month_start = parsed.date() if parsed is not None and not pd.isna(parsed) else None
                except Exception:
                    month_start = None

        shipment_date = _parse_date(row.get("shipment_date"))
        week_lbl = str(row.get("week_label") or "").strip()
        is_tot = bool(row.get("is_total"))

        # In production workflow, shipment cut-off is on Saturday.
        # If Monday (weekday 0) or Sunday (weekday 6) was logged, adjust to the preceding Saturday.
        if shipment_date and not is_tot:
            if shipment_date.weekday() == 0:  # Monday
                shipment_date = shipment_date - datetime.timedelta(days=2)
            elif shipment_date.weekday() == 6:  # Sunday
                shipment_date = shipment_date - datetime.timedelta(days=1)
        elif not shipment_date and not is_tot and month_start and week_lbl:
            m_wk = re.search(r"(\d+)", week_lbl)
            if m_wk:
                w_num = int(m_wk.group(1))
                sats = []
                dt = month_start.replace(day=1)
                while dt.month == month_start.month:
                    if dt.weekday() == 5:
                        sats.append(dt)
                    dt += datetime.timedelta(days=1)
                if sats:
                    sats_aligned = sats[1:] if (len(sats) > 4 and sats[0].day <= 2) else sats
                    idx = min(w_num - 1, len(sats_aligned) - 1)
                    if idx >= 0:
                        shipment_date = sats_aligned[idx]

        items.append(WeeklyDeliveryPlanRow(
            project=project,
            month_label=month_label,
            month_start=month_start,
            week_label=week_lbl,
            sno=row.get("sno"),
            shipment_date=shipment_date,
            plan_records=_safe_int(row.get("plan_records")),
            actual_records=_safe_int(row.get("actual_records")),
            variance=_safe_int(row.get("variance")),
            variance_pct=float(row.get("variance_pct") or 0),
            reason=str(row.get("reason") or ""),
            remarks=str(row.get("remarks") or ""),
            is_total=bool(row.get("is_total")),
        ))

    with transaction.atomic():
        WeeklyDeliveryPlanRow.objects.filter(project=project).delete()
        WeeklyDeliveryPlanRow.objects.bulk_create(items, batch_size=500)


def _replace_daily_operational_metrics(project, series_by_metric):
    """Full replace of this project's DailyOperationalMetric history, one
    metric key (branch_receipt/rqc_completed) at a time - powers the
    Operational Dashboard's Calendar view. Same defensive guard as
    _replace_weekly_delivery_rows/_replace_inventory_items: if a metric's
    series comes back empty (that daily_metrics rule isn't configured, or
    genuinely had nothing this run), its existing rows are left alone
    rather than wiped."""
    from django.db import transaction

    import datetime

    from apps.projects.models import DailyOperationalMetric

    if not series_by_metric:
        return

    for metric_key, rows in series_by_metric.items():
        if not rows:
            continue
        items = []
        for row in rows:
            try:
                d = datetime.date.fromisoformat(row["date"])
            except (KeyError, ValueError, TypeError):
                continue
            items.append(DailyOperationalMetric(project=project, metric_key=metric_key, date=d, value=row.get("value") or 0))

        if not items:
            continue

        with transaction.atomic():
            DailyOperationalMetric.objects.filter(project=project, metric_key=metric_key).delete()
            DailyOperationalMetric.objects.bulk_create(items, batch_size=1000)


def _derive_batch_metrics(project):
    """Populates total_batches / batches_being_keyed / promoted from the
    project's actual InventoryItem rows, so these are genuinely distinct
    numbers from delivered_records - not a copy of it. A "batch" here means
    one inventory row (one file/folder); "promoted" means that batch has a
    shipment_date recorded (it's shipped out, same concept as PHX's
    "Promoted"), vs "delivered_records" which counts individual records
    within those files. Different units, different numbers, on purpose:
    a project can easily have e.g. 8 batches (files) worth 69,548 delivered
    records - both are correct, they're just not the same measurement.

    One aggregate query (not two separate .count() table scans) for speed
    on large inventories."""
    from django.db.models import Count, Q

    from apps.inventory.models import InventoryItem

    agg = InventoryItem.objects.filter(project=project).aggregate(
        total=Count("id"),
        promoted=Count("id", filter=Q(shipment_date__isnull=False)),
    )
    total_batches = agg["total"] or 0
    if not total_batches:
        return  # no inventory_rows mapped for this template - leave batch fields at 0, not misleadingly equal to anything

    promoted = agg["promoted"] or 0
    Project.objects.filter(pk=project.pk).update(
        total_batches=total_batches,
        promoted=promoted,
        batches_being_keyed=total_batches - promoted,
    )
    project.total_batches = total_batches
    project.promoted = promoted
    project.batches_being_keyed = total_batches - promoted


def resync_project(project, user=None):
    """Re-pull a project's data from wherever it originally came from - used
    by the "Sync Now" button and by the Google Apps Script webhook. Only
    works for projects that were imported from a Google Sheet (google_sheet_url
    is set); returns (project, errors) same shape as run_import."""
    from apps.mapping.models import ProjectTemplate
    from .gsheet import download_as_xlsx

    if not project.google_sheet_url:
        return None, ["This project has no linked Google Sheet to sync from."]

    template = ProjectTemplate.objects.filter(project_key=project.project_key).first()
    if not template:
        return None, [f"No mapping template found for project_key '{project.project_key}'."]

    full_path = download_as_xlsx(project.google_sheet_url)
    try:
        return run_import(
            template, full_path, project.google_sheet_url, user,
            source_type=ImportBatch.SOURCE_GOOGLE_SHEET, source_url=project.google_sheet_url,
        )
    finally:
        # download_as_xlsx() saves a fresh temp .xlsx to media/uploads/ on
        # EVERY sync - run_import() has already read everything it needs
        # out of it by now (ImportBatch.file_name only keeps a text label,
        # not a live file reference - see models.py), so leaving the file
        # behind serves no purpose and, left unchecked across repeated
        # auto-syncs, silently fills the disk (this was found sitting at
        # 428MB / 200+ leftover files from past syncs of just 3 sheets).
        import os
        try:
            os.remove(full_path)
        except OSError:
            pass