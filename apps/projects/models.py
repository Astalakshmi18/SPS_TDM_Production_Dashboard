import calendar
import datetime
import json
import re
import secrets

from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Project(models.Model):
    """The single standard schema every dashboard widget reads from.
    Populated only via the mapping/import engine - never edited to match a
    specific source file's layout.

    `extra_data` holds every additional field the mapping engine finds that
    isn't one of the 7-11 core dashboard fields (e.g. "Delivered Pages %",
    "Days Gone", vendor breakdowns, QC counters...). The main Dashboard only
    ever reads the typed columns below to stay uncluttered; extra_data is
    rendered on the Project Insights view instead.
    """

    project_name = models.CharField(max_length=200)
    project_key = models.SlugField(max_length=50, help_text="Matches the ProjectTemplate.project_key it was imported with")
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="projects")

    start_date = models.DateField()
    end_date = models.DateField()

    target_records = models.BigIntegerField(default=0)
    delivered_records = models.BigIntegerField(default=0)
    total_images = models.BigIntegerField(default=0)

    # Indexing/keying batch tracking (matches the "Total Batches / Total
    # Batches Being Processed / Promoted / Promoted%" columns of the PHX-style
    # Indexing Dashboard). Optional - default to 0 for projects/templates
    # that don't track batches this way.
    total_batches = models.BigIntegerField(default=0)
    batches_being_keyed = models.BigIntegerField(default=0)
    promoted = models.BigIntegerField(default=0)

    language = models.CharField(max_length=100, blank=True, default="")
    customer_name = models.CharField("Customer Name", max_length=150, blank=True, default="")
    vendor = models.CharField(max_length=150, blank=True, default="")
    event_type = models.CharField(max_length=150, blank=True, default="")
    ocr_status = models.CharField(max_length=100, blank=True, default="")

    # Team / ownership (Version Control sheet: "Approved by" = GM,
    # "Prepapred by" = PM, "PL Name" = PL - read via the mapping engine,
    # same as every other field). Free text, not a FK, since these are
    # names typed into the sheet, not a separate People table.
    gm_name = models.CharField("GM Name", max_length=150, blank=True, default="")
    pm_name = models.CharField("PM Name", max_length=150, blank=True, default="")
    pl_name = models.CharField("PL Name", max_length=150, blank=True, default="")

    # Manpower counts. Not yet present in most project Google Sheets as of
    # when these fields were added - default to 0 until a template's
    # mapping config is updated to point at the real column once it exists
    # on the sheet. Re-syncing afterward will then populate these normally,
    # same as any other mapped field.
    branch_manpower_count = models.PositiveIntegerField(default=0)
    inhouse_manpower_count = models.PositiveIntegerField(default=0)

    # Everything the mapping engine pulled that isn't one of the fields above -
    # shown only on the Project Insights page, kept out of the main dashboard.
    extra_data = models.JSONField(default=dict, blank=True)
    
    # Custom column visibility configuration for the Inventory Tracker.
    # List of column keys (e.g. ['event_type', 'image_count', 'some_extra_field'])
    visible_inventory_columns = models.JSONField(default=list, blank=True)

    # User-defined custom columns for the Inventory Tracker (e.g. ['Section', 'Page'])
    defined_custom_columns = models.JSONField(default=list, blank=True)

    # Live Google Sheet sync: if this project was imported from a sheet, we
    # remember the link + a per-project secret so either a manual "Sync Now"
    # click or an automatic Google Apps Script trigger can refresh it without
    # anyone re-uploading a file.
    google_sheet_url = models.URLField(max_length=500, blank=True, default="")
    sync_token = models.CharField(max_length=40, blank=True, default="")

    # Project Status / Branch Status panels (Project Insights): which Inventory
    # sheet column to SUM for "Delivered Records" (Project Status) and
    # "Received Records" (Branch Status). For projects like Latvia_Russian /
    # Newspaper this is effectively fixed ("Accepted Records" / "Ven's Rec"
    # etc.) but for BPW-style projects it's picked manually, once, from a
    # dropdown of that project's own Inventory sheet headers - see
    # `inventory_column_choices()` below.
    delivered_column_key = models.CharField(max_length=150, blank=True, default="")
    received_column_key = models.CharField(max_length=150, blank=True, default="")

    # Operational Dashboard (ops-review request): same "pick a column once
    # from THIS project's own Inventory headers" pattern as delivered/
    # received above. BPW's own file: Branch Rec. = column S, QC Records =
    # column AC, Inhouse % = column AM - saved here as the column's literal
    # header text (via inventory_column_choices()), not a fixed letter, so
    # a differently-laid-out project just picks its own equivalent column.
    branch_receipt_column_key = models.CharField(max_length=150, blank=True, default="")
    rqc_completed_column_key = models.CharField(max_length=150, blank=True, default="")
    rqc_quality_column_key = models.CharField(max_length=150, blank=True, default="")

    # Batches Being Processed dropdown: which Inventory column carries each
    # batch's keying status (e.g. "Keyed" / "WIP" / blank), and which value
    # in that column means "Keyed". Batches Being Processed = Total Batches
    # (excluding WIP and blank rows) - No. of Batches Keyed.
    batches_status_column_key = models.CharField(max_length=150, blank=True, default="")
    batches_keyed_value = models.CharField(max_length=150, blank=True, default="")
    # Optional alternative/refinement: an "End Date" Inventory column. When
    # set, a batch counts as Keyed once this column has a date in it
    # (finished), rather than matching batches_keyed_value against the
    # status column - this is the more reliable signal when the sheet has
    # real Start Date / End Date columns per row.
    batches_end_date_column_key = models.CharField(max_length=150, blank=True, default="")

    # Project Summary sheet's OWN computed cells (Delivered/Received Records,
    # %, Days Gone, Remaining Days etc.) - read directly at import time so
    # this panel shows exactly what the sheet's own formulas say, instead of
    # Python re-deriving pace/percentages that can drift from the sheet's
    # own "Exclude Sundays" and other business rules baked into the file.
    summary_snapshot = models.JSONField(default=dict, blank=True)

    # Operational Dashboard snapshot: "Project Insights" + "AI for This
    # month" sheets' OWN numbers (Quoted/Current Throughput, Branch/Inhouse
    # Headcount, Current/Required Run Rate) - read directly at import time,
    # same principle as summary_snapshot above. See
    # import_engine.read_operational_snapshot().
    operational_snapshot = models.JSONField(default=dict, blank=True)

    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_updated"]
        unique_together = ("project_key", "branch")

    def __str__(self):
        return self.project_name

    def save(self, *args, **kwargs):
        if self.google_sheet_url and not self.sync_token:
            self.sync_token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    @property
    def remaining_records(self):
        return max(self.target_records - self.delivered_records, 0)

    @property
    def delivery_percent(self):
        if not self.target_records:
            return 0.0
        return round(min(self.delivered_records / self.target_records, 1) * 100, 2)

    @property
    def promoted_percent(self):
        if not self.total_batches:
            return 0.0
        return round(min(self.promoted / self.total_batches, 1) * 100, 2)

    def inventory_column_choices(self):
        """Column keys available for the Selected_Column dropdown - sourced
        from THIS project's own Inventory sheet (its InventoryItem rows),
        not a global list, so BPW only ever offers BPW's own headers etc.
        Always offers the two built-in numeric columns (Images/Records)
        plus every extra header the mapping engine picked up per row.

        Real trackers' Excel headers often have embedded line breaks/extra
        spaces (e.g. "Accepted \\n Records") - harmless in the sheet, but it
        made the dropdown option render as garbled, unrecognizable text.
        The dict VALUE (what's shown) is cleaned to one line; the KEY (what
        gets saved/matched) stays byte-for-byte the same as the sheet."""
        choices = {"image_count": "Images (# Images)", "record_count": "Records"}
        for extra in self.inventory_items.exclude(extra={}).values_list("extra", flat=True)[:500]:
            for k in extra.keys():
                choices.setdefault(k, " ".join(k.split()))
        return choices

    def _sum_inventory_column(self, column_key, upto_date=None):
        """Sum of one Inventory sheet column across every row for this
        project - the literal "Delivered Records = Sum of {Selected_Column}
        count in Inventory sheet" rule. `upto_date`, when given, restricts
        the sum to rows whose Shipment Date is on/before that date (used by
        `shipped_records_by` for the Project Detail Table's "PctBy X%"
        milestone columns) - same column, same per-project mapping, just a
        date-bounded slice of it instead of the whole-project total."""
        if not column_key:
            return 0
        qs = self.inventory_items.all()
        if upto_date is not None:
            qs = qs.filter(shipment_date__isnull=False, shipment_date__lte=upto_date)
        if column_key in ("image_count", "record_count"):
            return qs.aggregate(total=models.Sum(column_key))["total"] or 0
        total = 0
        for extra in qs.exclude(extra={}).values_list("extra", flat=True):
            raw = extra.get(column_key)
            if raw is None or raw == "":
                continue
            try:
                total += float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                continue
        return int(total) if total == int(total) else round(total, 2)

    def _avg_inventory_column(self, column_key):
        """Same column resolution as `_sum_inventory_column`, but AVERAGED
        instead of summed - for a percentage/score-style column like BPW's
        "Inhouse %" (RQC Quality Score), where the meaningful figure is the
        typical value per row, not a sum that grows with row count. Values
        already stored as a 0-1 fraction (e.g. Excel's own "%" cell format,
        openpyxl often returns 0.97 rather than 97) are scaled up to a 0-100
        number so they read the same as values already stored as e.g. 97 -
        this is a heuristic (a genuine ratio-style field close to 1 would be
        misread), acceptable here since this column is only ever used for a
        %-typed field."""
        if not column_key:
            return None
        if column_key in ("image_count", "record_count"):
            agg = self.inventory_items.aggregate(avg=models.Avg(column_key))
            return round(agg["avg"], 2) if agg["avg"] is not None else None
        values = []
        for extra in self.inventory_items.exclude(extra={}).values_list("extra", flat=True):
            raw = extra.get(column_key)
            if raw is None or raw == "":
                continue
            try:
                v = float(str(raw).replace(",", "").replace("%", ""))
            except (TypeError, ValueError):
                continue
            values.append(v * 100 if 0 < v <= 1 else v)
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    def operational_plan_panel(self, cycle_month_start=None):
        """Monthly Plan vs Monthly Target Achieved and Weekly Plan vs Weekly Target Achieved.
        Finds the active month and week with delivery data (strictly defaulting to current
        month period, with cycle_month_start override), and derives Plan, Target Achieved (Actual),
        Gap, Gap %, and Achieved status - identically modeled to Throughput and Run Rate."""
        today = timezone.localdate()
        current_first = today.replace(day=1)
        current_key = today.strftime("%Y-%m")
        current_label = today.strftime("%B %Y")

        month_row = None
        if cycle_month_start:
            if isinstance(cycle_month_start, (datetime.date, datetime.datetime)):
                month_row = self.weekly_delivery_rows.filter(month_start=cycle_month_start, is_total=True).first()
            else:
                cms_str = str(cycle_month_start).strip()
                parsed_d = None
                try:
                    if len(cms_str) == 7 and cms_str[4] == "-":
                        parsed_d = datetime.date.fromisoformat(cms_str + "-01")
                    elif len(cms_str) == 10 and cms_str[4] == "-" and cms_str[7] == "-":
                        parsed_d = datetime.date.fromisoformat(cms_str)
                except Exception:
                    parsed_d = None

                if parsed_d:
                    month_row = self.weekly_delivery_rows.filter(month_start=parsed_d, is_total=True).first()

                if not month_row:
                    month_row = (
                        self.weekly_delivery_rows.filter(month_label__iexact=cms_str, is_total=True).first()
                        or self.weekly_delivery_rows.filter(month_label__icontains=cms_str, is_total=True).first()
                    )
        else:
            # Strictly default to CURRENT MONTH first based on system date
            month_row = self.weekly_delivery_rows.filter(month_start=current_first, is_total=True).first()

        # If month_row is not found for the requested/default cycle:
        if not month_row:
            snap = self.operational_snapshot or {}
            snap_cycles = snap.get("monthly_cycles") or []
            cur_sc = None
            if cycle_month_start:
                cur_sc = next(
                    (c for c in snap_cycles if c.get("month_key") == str(cycle_month_start) or c.get("month_label") == str(cycle_month_start)),
                    None
                )
            if not cur_sc and not cycle_month_start:
                cur_sc = next((c for c in snap_cycles if c.get("month_key") == current_key), None)

            if cur_sc:
                monthly_actual = cur_sc.get("target_achieved") or 0
                monthly_plan = cur_sc.get("expected_throughput") or 0
                monthly_gap = (monthly_actual - monthly_plan) if (monthly_plan or monthly_actual) else None
                monthly_gap_pct = round((monthly_gap / monthly_plan * 100), 2) if (monthly_gap is not None and monthly_plan) else 0.0
                monthly_achieved = bool(monthly_actual >= monthly_plan) if (monthly_plan and monthly_actual is not None) else None
                return {
                    "monthly_plan": monthly_plan,
                    "monthly_actual": monthly_actual,
                    "monthly_target_achieved": monthly_actual,
                    "monthly_gap": monthly_gap,
                    "monthly_gap_pct": monthly_gap_pct,
                    "monthly_achieved": monthly_achieved,
                    "monthly_status_label": "Achieved" if monthly_achieved else ("Not Achieved" if monthly_achieved is False else "—"),
                    "monthly_label": cur_sc.get("month_label") or current_label,
                    "weekly_plan": 0,
                    "weekly_actual": 0,
                    "weekly_target_achieved": 0,
                    "weekly_gap": None,
                    "weekly_gap_pct": 0.0,
                    "weekly_achieved": None,
                    "weekly_status_label": "—",
                    "weekly_label": "",
                }

            # If user explicitly requested a specific past cycle that couldn't be matched:
            if cycle_month_start and str(cycle_month_start) not in (str(current_first), current_key, current_label):
                fallback_row = self.weekly_delivery_rows.filter(is_total=True).order_by("-month_start").first()
                if fallback_row:
                    month_row = fallback_row

            # If still no month_row (e.g. current month doesn't have delivery row in sheet yet)
            if not month_row:
                return {
                    "monthly_plan": 0,
                    "monthly_actual": 0,
                    "monthly_target_achieved": 0,
                    "monthly_gap": None,
                    "monthly_gap_pct": 0.0,
                    "monthly_achieved": None,
                    "monthly_status_label": "In Progress",
                    "monthly_label": current_label,
                    "weekly_plan": 0,
                    "weekly_actual": 0,
                    "weekly_target_achieved": 0,
                    "weekly_gap": None,
                    "weekly_gap_pct": 0.0,
                    "weekly_achieved": None,
                    "weekly_status_label": "—",
                    "weekly_label": f"{current_label} Week-1",
                }

        # Find corresponding week row for this month
        if month_row:
            target_start = month_row.month_start
            week_qs = self.weekly_delivery_rows.filter(month_start=target_start, is_total=False)
            if target_start == current_first:
                # In current month: pick active/current week
                week_row = (
                    week_qs.filter(shipment_date__gte=today).order_by("shipment_date").first()
                    or week_qs.filter(shipment_date__lte=today).order_by("-shipment_date").first()
                    or week_qs.first()
                )
            else:
                # Past month: pick latest week
                week_row = week_qs.order_by("-shipment_date").first()
        else:
            week_row = None

        monthly_plan = month_row.plan_records if month_row else 0
        monthly_actual = month_row.actual_records if month_row else 0
        monthly_gap = (monthly_actual - monthly_plan) if (monthly_plan or monthly_actual) else None
        monthly_gap_pct = round((monthly_gap / monthly_plan * 100), 2) if (monthly_gap is not None and monthly_plan) else 0.0
        monthly_achieved = bool(monthly_actual >= monthly_plan) if (monthly_plan and monthly_actual is not None) else None
        monthly_label = month_row.month_label if month_row else ""

        weekly_plan = week_row.plan_records if week_row else 0
        weekly_actual = week_row.actual_records if week_row else 0
        weekly_gap = (weekly_actual - weekly_plan) if (weekly_plan or weekly_actual) else None
        weekly_gap_pct = round((weekly_gap / weekly_plan * 100), 2) if (weekly_gap is not None and weekly_plan) else 0.0
        weekly_achieved = bool(weekly_actual >= weekly_plan) if (weekly_plan and weekly_actual is not None) else None
        weekly_label = f"{week_row.month_label} {week_row.week_label}".strip() if week_row else ""

        return {
            "monthly_plan": monthly_plan,
            "monthly_actual": monthly_actual,
            "monthly_target_achieved": monthly_actual,
            "monthly_gap": monthly_gap,
            "monthly_gap_pct": monthly_gap_pct,
            "monthly_achieved": monthly_achieved,
            "monthly_status_label": "Achieved" if monthly_achieved else ("Not Achieved" if monthly_achieved is False else "—"),
            "monthly_label": monthly_label,

            "weekly_plan": weekly_plan,
            "weekly_actual": weekly_actual,
            "weekly_target_achieved": weekly_actual,
            "weekly_gap": weekly_gap,
            "weekly_gap_pct": weekly_gap_pct,
            "weekly_achieved": weekly_achieved,
            "weekly_status_label": "Achieved" if weekly_achieved else ("Not Achieved" if weekly_achieved is False else "—"),
            "weekly_label": weekly_label,
        }

    def get_total_inventory_data(self):
        """Returns the Total Count / Sum of Branch Receipt column from Inventory sheet
        (e.g. S Column Total Count for BPW: 877,515).
        Prefers snapshot totals, then extracts dynamically from project's source workbook,
        then falls back to database daily metrics sum or delivered/target records.
        """
        snap = self.operational_snapshot or {}
        totals = snap.get("daily_metrics_totals") or {}
        if totals.get("branch_receipt") is not None and float(totals["branch_receipt"]) > 0:
            return float(totals["branch_receipt"])
        if snap.get("total_branch_receipt") is not None and float(snap["total_branch_receipt"]) > 0:
            return float(snap["total_branch_receipt"])

        # Try extracting dynamically from latest uploaded file if branch_receipt is mapped
        latest_batch = self.import_batches.filter(status="SUCCESS").order_by("-created_at").first()
        if latest_batch and latest_batch.file_name:
            try:
                import os
                import pandas as pd
                from django.conf import settings
                from apps.mapping.models import ProjectTemplate
                from apps.mapping.engine import _SheetCache, _resolve_column

                template = ProjectTemplate.objects.filter(project_key=self.project_key).first()
                dm = (template.config.get("daily_metrics") or {}).get("branch_receipt") if template and template.config else None
                if dm and dm.get("sheet") and dm.get("value_column"):
                    file_path = os.path.join(settings.MEDIA_ROOT, latest_batch.file_name)
                    if not os.path.exists(file_path):
                        file_path = os.path.join(settings.MEDIA_ROOT, "uploads", os.path.basename(latest_batch.file_name))
                    if os.path.exists(file_path):
                        cache = _SheetCache(file_path)
                        df = cache.get(dm["sheet"], dm.get("header_row", 1))
                        vm = _resolve_column(df, dm["value_column"])
                        if vm:
                            fc = df.columns[0]
                            df_clean = df[df[fc].notna()] if fc != vm else df
                            s = pd.to_numeric(
                                df_clean[vm].astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
                                errors="coerce"
                            ).fillna(0).sum()
                            if s > 0:
                                return float(s)
            except Exception:
                pass

        # Fallback to database daily metrics sum
        db_sum = self.daily_operational_metrics.filter(metric_key="branch_receipt").aggregate(total=Sum("value"))["total"]
        if db_sum and float(db_sum) > 0:
            return float(db_sum)

        # Fallback to closed cycles target_achieved sum
        closed_sum = sum(float(sc["target_achieved"]) for sc in (snap.get("monthly_cycles") or []) if sc.get("target_achieved"))
        if closed_sum > 0:
            return float(closed_sum)

        return float(self.delivered_records or self.target_records or 0.0)

    def operational_panel(self):
        """Project-Level Operational Dashboard row (ops-review request):
        Daily Branch Receipt / Daily RQC Completed / RQC Quality Score come
        from whichever Inventory column is picked via
        branch_receipt_column_key / rqc_completed_column_key /
        rqc_quality_column_key above. Expected/Current Throughput,
        Branch/Inhouse Headcount, Planned/Current Run Rate come straight
        from operational_snapshot (the source sheets' own numbers - see
        import_engine.read_operational_snapshot). Variance Against Plan =
        Current Run Rate - Planned(Required) Run Rate. Required Headcount =
        the headcount it would take, AT today's per-head productivity, to
        hit the Planned Run Rate."""
        snap = self.operational_snapshot or {}
        plan = self.operational_plan_panel()

        # Template-Mapping-configured daily figures (config["daily_metrics"]
        # in the ProjectTemplate JSON - date column + value column, no
        # per-project manual picking needed) take priority; the manual
        # branch_receipt_column_key/rqc_completed_column_key/
        # rqc_quality_column_key picker (set once via a project's Insights
        # page) is only used as a fallback for a project whose template
        # hasn't been given daily_metrics rules yet.
        today_dt = timezone.localdate()
        today = today_dt
        # Daily metrics strictly reflect TODAY's actual numbers
        today_receipt = self.daily_operational_metrics.filter(
            date=today, metric_key=DailyOperationalMetric.METRIC_BRANCH_RECEIPT
        ).first()
        if today_receipt is not None:
            branch_receipt = today_receipt.value
        elif self.daily_operational_metrics.exists():
            # If the project tracks daily metrics, but nothing has been logged for today yet, today's receipt is 0
            branch_receipt = 0.0
        else:
            branch_receipt = snap.get("branch_receipt")
            if branch_receipt is None and self.branch_receipt_column_key:
                branch_receipt = self._sum_inventory_column(self.branch_receipt_column_key)

        today_rqc = self.daily_operational_metrics.filter(
            date=today, metric_key=DailyOperationalMetric.METRIC_RQC_COMPLETED
        ).first()
        if today_rqc is not None:
            rqc_completed = today_rqc.value
        elif self.daily_operational_metrics.exists():
            rqc_completed = 0.0
        else:
            rqc_completed = snap.get("rqc_completed")
            if rqc_completed is None and self.rqc_completed_column_key:
                rqc_completed = self._sum_inventory_column(self.rqc_completed_column_key)

        rqc_quality_score = snap.get("rqc_quality_score")
        if rqc_quality_score is None and self.rqc_quality_column_key:
            rqc_quality_score = self._avg_inventory_column(self.rqc_quality_column_key)
        if rqc_quality_score is not None:
            try:
                rqc_val = float(rqc_quality_score)
                if 0 < rqc_val <= 1.0:
                    rqc_quality_score = round(rqc_val * 100.0, 2)
                else:
                    rqc_quality_score = round(rqc_val, 2)
            except (ValueError, TypeError):
                pass

        # Throughput metrics per user formula:
        # Expected Throughput = Quoted Throughput
        # Current Throughput = Inventory data / Branch Manpower / No. of Working Days
        # Leaves: Exclude Sundays + Swift ProSys Tamil Calendar holidays
        quoted_throughput = snap.get("quoted_throughput")
        if quoted_throughput is None:
            if snap.get("expected_throughput") and snap.get("expected_throughput") < 10000:
                quoted_throughput = snap.get("expected_throughput")
            elif snap.get("throughput_branch"):
                quoted_throughput = snap.get("throughput_branch")

        current_key = today_dt.strftime("%Y-%m")
        current_first = today_dt.replace(day=1)
        today_label = today_dt.strftime("%B %Y")

        snap_cycles = snap.get("monthly_cycles") or []
        sorted_snap_cycles = sorted(
            snap_cycles,
            key=lambda c: c.get("month_date") or c.get("month_key") or ""
        )
        monthly_mp_map = {}
        running_mp = None
        running_hc_br = None
        running_hc_in = None

        for sc in sorted_snap_cycles:
            k = sc.get("month_key")
            mp = sc.get("manpower_used")
            hc_br = sc.get("headcount_branch")
            hc_in = sc.get("headcount_inhouse")

            if mp is not None and float(mp) > 0:
                running_mp = float(mp)
            if hc_br is not None and float(hc_br) > 0:
                running_hc_br = float(hc_br)
            if hc_in is not None and float(hc_in) > 0:
                running_hc_in = float(hc_in)

            eff_mp = float(mp) if (mp is not None and float(mp) > 0) else running_mp
            eff_hc_br = float(hc_br) if (hc_br is not None and float(hc_br) > 0) else running_hc_br
            eff_hc_in = float(hc_in) if (hc_in is not None and float(hc_in) > 0) else running_hc_in

            if k:
                monthly_mp_map[k] = {
                    "manpower_used": eff_mp,
                    "headcount_branch": eff_hc_br,
                    "headcount_inhouse": eff_hc_in,
                    "working_days": sc.get("working_days"),
                    "target_achieved": sc.get("target_achieved"),
                    "per_head_throughput": sc.get("per_head_throughput"),
                    "current_throughput": sc.get("current_throughput"),
                    "is_closed": sc.get("is_closed", False),
                }

        curr_mp_info = monthly_mp_map.get(current_key) or {}
        curr_manpower = (
            curr_mp_info.get("manpower_used")
            or snap.get("manpower_used")
            or running_mp
            or snap.get("headcount_branch")
            or self.branch_manpower_count
            or 1
        )
        branch_manpower = curr_manpower
        curr_month_working_days = get_month_working_days(today_dt.year, today_dt.month)
        manpower_used = curr_manpower
        working_days = curr_month_working_days
        target_achieved = 0.0

        # Overall Throughput per user formula:
        # Current Throughput = Total Inventory Data (e.g. S Column Total Count) / (Branch Manpower * Timeline Total Working Days)
        # Quoted Throughput IS Expected Throughput
        total_inv_data = self.get_total_inventory_data()

        branch_mp = (
            curr_mp_info.get("headcount_branch")
            or snap.get("headcount_branch")
            or snap.get("manpower_used")
            or self.branch_manpower_count
            or 1
        )
        timeline_days = self.working_days_total or 1

        if total_inv_data > 0 and branch_mp > 0 and timeline_days > 0:
            overall_current_throughput = round(float(total_inv_data) / (float(branch_mp) * float(timeline_days)), 2)
        else:
            # Fallback for projects without inventory count
            curr_mp = curr_manpower or branch_mp or 1
            curr_wd = curr_month_working_days or timeline_days or 1
            inv_fallback = branch_receipt if (branch_receipt and branch_receipt > 0) else (plan.get("monthly_actual") or 0.0)
            if curr_mp and curr_wd and inv_fallback:
                overall_current_throughput = round(float(inv_fallback) / (float(curr_mp) * float(curr_wd)), 2)
            else:
                overall_current_throughput = 0.0

        expected_throughput = float(quoted_throughput) if quoted_throughput is not None else 0.0
        current_throughput = overall_current_throughput
        if expected_throughput and expected_throughput > 0:
            target_achieved_status = bool(current_throughput >= expected_throughput)
            target_achieved_label = "Achieved" if target_achieved_status else "Not Achieved"
            throughput_gap = round(current_throughput - expected_throughput, 2)
            throughput_gap_pct = round((throughput_gap / expected_throughput) * 100, 2)
        else:
            target_achieved_status = None
            target_achieved_label = "—"
            throughput_gap = None
            throughput_gap_pct = 0.0

        headcount_branch = (
            curr_mp_info.get("headcount_branch")
            or snap.get("headcount_branch")
            or running_hc_br
            or self.branch_manpower_count
        )
        headcount_inhouse = (
            curr_mp_info.get("headcount_inhouse")
            or snap.get("headcount_inhouse")
            or running_hc_in
            or self.inhouse_manpower_count
        )
        planned_run_rate = snap.get("planned_run_rate")
        current_run_rate = snap.get("current_run_rate")

        run_rate_gap = (
            round(current_run_rate - planned_run_rate, 2)
            if planned_run_rate is not None and current_run_rate is not None else None
        )
        variance_vs_plan = run_rate_gap

        run_rate_gap_pct = (
            round((run_rate_gap / planned_run_rate) * 100, 2)
            if run_rate_gap is not None and planned_run_rate else None
        )

        run_rate_achieved = (
            bool(current_run_rate >= planned_run_rate)
            if current_run_rate is not None and planned_run_rate is not None else None
        )
        run_rate_status_label = "Achieved" if run_rate_achieved else ("Not Achieved" if run_rate_achieved is False else "—")

        required_headcount = None
        branch_headcount = (headcount_branch if headcount_branch is not None else self.branch_manpower_count) or 0
        if planned_run_rate and current_run_rate and branch_headcount:
            per_head_productivity = current_run_rate / branch_headcount
            if per_head_productivity:
                required_headcount = round(planned_run_rate / per_head_productivity, 1)

        # Branch Receipt Target = Branch Throughput (Per-day target) * Branch Manpower (Members working)
        # Sourced dynamically from Template Mapping or Project Insights sheet (e.g. 650 * 40 = 26,000)
        branch_tp = snap.get("throughput_branch") or quoted_throughput
        branch_members = branch_headcount or manpower_used or 0
        branch_receipt_target = None
        if branch_tp and branch_members:
            branch_receipt_target = round(branch_tp * branch_members, 2)

        branch_receipt_gap = None
        branch_receipt_gap_pct = None
        branch_receipt_achieved = None
        branch_receipt_status_label = "—"
        if branch_receipt is not None and branch_receipt_target:
            branch_receipt_gap = round(branch_receipt - branch_receipt_target, 2)
            branch_receipt_gap_pct = round((branch_receipt_gap / branch_receipt_target) * 100, 2) if branch_receipt_target else 0.0
            branch_receipt_achieved = bool(branch_receipt >= branch_receipt_target)
            branch_receipt_status_label = "Achieved" if branch_receipt_achieved else "Not Achieved"

        # Daily RQC Target = Throughput In-house (Per-day target) * In-house QC Manpower
        # Sourced dynamically from Template Mapping or Project Insights sheet (e.g. 5000 * 6 = 30,000)
        throughput_inhouse = snap.get("throughput_inhouse")
        inhouse_members = (headcount_inhouse if headcount_inhouse is not None else self.inhouse_manpower_count) or 0
        if not inhouse_members and snap.get("headcount_inhouse"):
            inhouse_members = snap.get("headcount_inhouse")

        rqc_target = None
        if throughput_inhouse and inhouse_members:
            rqc_target = round(throughput_inhouse * inhouse_members, 2)

        rqc_gap = None
        rqc_gap_pct = None
        rqc_achieved = None
        rqc_status_label = "—"
        if rqc_completed is not None and rqc_target:
            rqc_gap = round(rqc_completed - rqc_target, 2)
            rqc_gap_pct = round((rqc_gap / rqc_target) * 100, 2) if rqc_target else 0.0
            rqc_achieved = bool(rqc_completed >= rqc_target)
            rqc_status_label = "Achieved" if rqc_achieved else "Not Achieved"

        # Available Monthly Cycles (e.g. Current September 2026 vs Closed August 2026)
        available_cycles = []
        delivery_totals = list(self.weekly_delivery_rows.filter(is_total=True).order_by("-month_start"))
        snap_cycles = list(reversed(snap.get("monthly_cycles") or []))
        snap_cycles_by_key = {c.get("month_key"): c for c in snap_cycles if c.get("month_key")}

        # Pre-aggregate monthly sums for daily metrics (Branch Receipt & RQC Completed)
        monthly_daily_metrics = {}
        for row in self.daily_operational_metrics.values("date", "metric_key", "value"):
            d = row.get("date")
            if not d:
                continue
            m_k = d.strftime("%Y-%m")
            if m_k not in monthly_daily_metrics:
                monthly_daily_metrics[m_k] = {"branch_receipt": 0.0, "rqc_completed": 0.0}
            val = float(row.get("value") or 0.0)
            if row.get("metric_key") == "branch_receipt":
                monthly_daily_metrics[m_k]["branch_receipt"] += val
            elif row.get("metric_key") == "rqc_completed":
                monthly_daily_metrics[m_k]["rqc_completed"] += val

        def _format_cycle_date_range(month_key, default_label=""):
            import calendar
            try:
                parts = str(month_key).split("-")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    y, m = int(parts[0]), int(parts[1])
                    last_day = calendar.monthrange(y, m)[1]
                    m_first = datetime.date(y, m, 1)
                    m_last = datetime.date(y, m, last_day)
                    last_suf = "st" if last_day in (1, 21, 31) else ("nd" if last_day in (2, 22) else ("rd" if last_day in (3, 23) else "th"))
                    return f"1st {m_first.strftime('%b')} to {last_day}{last_suf} {m_last.strftime('%b')}"
            except Exception:
                pass

            try:
                candidate = f"{default_label} {month_key}".lower()
                yr_match = re.search(r"\b(20\d\d)\b", candidate)
                yr = int(yr_match.group(1)) if yr_match else datetime.date.today().year
                m_lookup = {
                    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
                }
                for prefix, m_num in m_lookup.items():
                    if prefix in candidate:
                        last_day = calendar.monthrange(yr, m_num)[1]
                        m_first = datetime.date(yr, m_num, 1)
                        m_last = datetime.date(yr, m_num, last_day)
                        last_suf = "st" if last_day in (1, 21, 31) else ("nd" if last_day in (2, 22) else ("rd" if last_day in (3, 23) else "th"))
                        return f"1st {m_first.strftime('%b')} to {last_day}{last_suf} {m_last.strftime('%b')}"
            except Exception:
                pass

            return default_label or month_key

        seen_keys = set()

        def _calc_throughput_metrics(cy_key, cy_label, receipts_sum, actual_sum=0.0, is_current_cycle=False):
            cy_y, cy_m = today_dt.year, today_dt.month
            try:
                if cy_key and re.match(r"^\d{4}-\d{2}", str(cy_key)):
                    parts = str(cy_key).split("-")
                    cy_y, cy_m = int(parts[0]), int(parts[1])
                elif cy_label:
                    p_dt = datetime.datetime.strptime(str(cy_label).strip(), "%B %Y")
                    cy_y, cy_m = p_dt.year, p_dt.month
            except Exception:
                pass

            m_info = monthly_mp_map.get(cy_key) or {}
            m_mp = (
                m_info.get("manpower_used")
                or running_mp
                or snap.get("manpower_used")
                or snap.get("headcount_branch")
                or self.branch_manpower_count
                or 1
            )

            sheet_wd = m_info.get("working_days")
            if sheet_wd and float(sheet_wd) > 0 and not is_current_cycle:
                m_wd = float(sheet_wd)
            else:
                m_wd = get_month_working_days(cy_y, cy_m)

            # Individual month throughput
            if is_current_cycle:
                inv_data = receipts_sum if receipts_sum > 0 else (actual_sum or 0.0)
            else:
                inv_data = m_info.get("target_achieved") if m_info.get("target_achieved") is not None else (actual_sum or receipts_sum or 0.0)

            if m_mp and m_wd and inv_data:
                month_tp = round(float(inv_data) / (float(m_mp) * float(m_wd)), 2)
            else:
                month_tp = 0.0

            # User formula: Expected Throughput = Quoted Throughput
            # Current Throughput = Overall Throughput across the project
            exp_tp = float(quoted_throughput) if quoted_throughput is not None else 0.0
            curr_tp = overall_current_throughput

            if exp_tp and exp_tp > 0:
                tp_stat = bool(curr_tp >= exp_tp)
                tp_lbl = "Achieved" if tp_stat else "Not Achieved"
                tp_gp = round(curr_tp - exp_tp, 2)
            else:
                tp_stat = None
                tp_lbl = "—"
                tp_gp = None

            return exp_tp, curr_tp, tp_gp, tp_stat, tp_lbl, m_wd, m_mp, month_tp

        for idx, dt in enumerate(delivery_totals):
            m_start = dt.month_start
            m_key = m_start.strftime("%Y-%m") if m_start else re.sub(r"[^a-zA-Z0-9_-]", "-", str(dt.month_label or f"cycle-{idx}")).strip("-")
            if not m_key:
                m_key = f"cycle-{idx}"
            seen_keys.add(m_key)

            is_curr = bool(m_start == current_first or m_key == current_key)
            sc = snap_cycles_by_key.get(m_key) or {}

            cp = self.operational_plan_panel(cycle_month_start=m_start or dt.month_label)

            mdm = monthly_daily_metrics.get(m_key) or {}
            c_receipts_total = mdm.get("branch_receipt", 0.0)
            c_rqc_total = mdm.get("rqc_completed", 0.0)
            c_date_range = _format_cycle_date_range(m_key, dt.month_label or m_key)

            c_exp_tp, c_curr_tp, c_tp_gap, c_tp_status, c_tp_label, c_working_days, c_mp, c_month_tp = _calc_throughput_metrics(
                m_key, dt.month_label, c_receipts_total, cp["monthly_actual"], is_current_cycle=is_curr
            )
            m_info = monthly_mp_map.get(m_key) or {}
            c_hc_br = m_info.get("headcount_branch") or headcount_branch
            c_hc_in = m_info.get("headcount_inhouse") or headcount_inhouse

            available_cycles.append({
                "month_key": m_key,
                "month_label": dt.month_label or m_key,
                "short_label": (dt.month_label.split()[0] if dt.month_label else m_key),
                "is_current": is_curr,
                "manpower_used": c_mp,
                "headcount_branch": c_hc_br,
                "headcount_inhouse": c_hc_in,
                "monthly_plan": cp["monthly_plan"],
                "monthly_actual": cp["monthly_actual"],
                "monthly_gap": cp["monthly_gap"],
                "monthly_gap_pct": cp["monthly_gap_pct"],
                "monthly_achieved": cp["monthly_achieved"],
                "monthly_status_label": cp["monthly_status_label"],
                "weekly_label": cp["weekly_label"],
                "weekly_plan": cp["weekly_plan"],
                "weekly_actual": cp["weekly_actual"],
                "weekly_gap": cp["weekly_gap"],
                "weekly_achieved": cp["weekly_achieved"],
                "expected_throughput": c_exp_tp,
                "current_throughput": c_curr_tp,
                "month_throughput": c_month_tp,
                "throughput_gap": c_tp_gap,
                "target_achieved_status": c_tp_status,
                "target_achieved_label": c_tp_label,
                "working_days": c_working_days,
                "month_receipts_total": c_receipts_total,
                "month_rqc_total": c_rqc_total,
                "date_range_label": c_date_range,
            })

        # Append any snap_cycles that were not in delivery_totals (or if no delivery_totals at all)
        for idx, sc in enumerate(snap_cycles):
            m_key = sc.get("month_key") or re.sub(r"[^a-zA-Z0-9_-]", "-", str(sc.get("month_label") or f"snap-{idx}")).strip("-")
            if not m_key:
                m_key = f"snap-{idx}"
            if m_key in seen_keys:
                continue
            seen_keys.add(m_key)

            is_curr = bool(m_key == current_key)
            sc_cp = self.operational_plan_panel(cycle_month_start=sc.get("month_label"))

            mdm = monthly_daily_metrics.get(m_key) or {}
            c_receipts_total = mdm.get("branch_receipt", 0.0)
            c_rqc_total = mdm.get("rqc_completed", 0.0)
            c_date_range = _format_cycle_date_range(m_key, sc.get("month_label") or m_key)

            c_exp_tp, c_curr_tp, c_tp_gap, c_tp_status, c_tp_label, c_working_days, c_mp, c_month_tp = _calc_throughput_metrics(
                m_key, sc.get("month_label"), c_receipts_total, sc_cp["monthly_actual"] or sc.get("target_achieved"), is_current_cycle=is_curr
            )
            m_info = monthly_mp_map.get(m_key) or {}
            c_hc_br = m_info.get("headcount_branch") or headcount_branch
            c_hc_in = m_info.get("headcount_inhouse") or headcount_inhouse

            available_cycles.append({
                "month_key": m_key,
                "month_label": sc.get("month_label") or m_key,
                "short_label": (sc.get("month_label") or m_key).split()[0],
                "is_current": is_curr,
                "manpower_used": c_mp,
                "headcount_branch": c_hc_br,
                "headcount_inhouse": c_hc_in,
                "monthly_plan": sc_cp["monthly_plan"],
                "monthly_actual": sc_cp["monthly_actual"] if sc_cp["monthly_actual"] else (sc.get("target_achieved") or 0.0),
                "monthly_gap": sc_cp["monthly_gap"],
                "monthly_gap_pct": sc_cp["monthly_gap_pct"],
                "monthly_achieved": sc_cp["monthly_achieved"],
                "monthly_status_label": sc_cp["monthly_status_label"],
                "weekly_label": sc_cp["weekly_label"],
                "weekly_plan": sc_cp["weekly_plan"],
                "weekly_actual": sc_cp["weekly_actual"],
                "weekly_gap": sc_cp["weekly_gap"],
                "weekly_achieved": sc_cp["weekly_achieved"],
                "expected_throughput": c_exp_tp,
                "current_throughput": c_curr_tp,
                "month_throughput": c_month_tp,
                "throughput_gap": c_tp_gap,
                "target_achieved_status": c_tp_status,
                "target_achieved_label": c_tp_label,
                "working_days": c_working_days,
                "month_receipts_total": c_receipts_total,
                "month_rqc_total": c_rqc_total,
                "date_range_label": c_date_range,
            })

        if current_key not in seen_keys:
            cp_curr = self.operational_plan_panel(cycle_month_start=current_first)
            sc_curr = snap_cycles_by_key.get(current_key) or {}

            mdm_curr = monthly_daily_metrics.get(current_key) or {}
            c_receipts_total = mdm_curr.get("branch_receipt", 0.0)
            c_rqc_total = mdm_curr.get("rqc_completed", 0.0)
            c_date_range = _format_cycle_date_range(current_key, today_label)

            c_exp_tp, c_curr_tp, c_tp_gap, c_tp_status, c_tp_label, c_working_days, c_mp, c_month_tp = _calc_throughput_metrics(
                current_key, today_label, c_receipts_total, cp_curr.get("monthly_actual"), is_current_cycle=True
            )
            c_hc_br = curr_mp_info.get("headcount_branch") or headcount_branch
            c_hc_in = curr_mp_info.get("headcount_inhouse") or headcount_inhouse

            available_cycles.insert(0, {
                "month_key": current_key,
                "month_label": today_label,
                "short_label": today_dt.strftime("%b"),
                "is_current": True,
                "manpower_used": c_mp,
                "headcount_branch": c_hc_br,
                "headcount_inhouse": c_hc_in,
                "monthly_plan": cp_curr.get("monthly_plan", 0),
                "monthly_actual": cp_curr.get("monthly_actual", 0),
                "monthly_gap": cp_curr.get("monthly_gap"),
                "monthly_gap_pct": cp_curr.get("monthly_gap_pct", 0.0),
                "monthly_achieved": cp_curr.get("monthly_achieved"),
                "monthly_status_label": cp_curr.get("monthly_status_label", "—"),
                "weekly_label": cp_curr.get("weekly_label", ""),
                "weekly_plan": cp_curr.get("weekly_plan", 0),
                "weekly_actual": cp_curr.get("weekly_actual", 0),
                "weekly_gap": cp_curr.get("weekly_gap"),
                "weekly_achieved": cp_curr.get("weekly_achieved"),
                "expected_throughput": c_exp_tp,
                "current_throughput": c_curr_tp,
                "month_throughput": c_month_tp,
                "throughput_gap": c_tp_gap,
                "target_achieved_status": c_tp_status,
                "target_achieved_label": c_tp_label,
                "working_days": c_working_days,
                "month_receipts_total": c_receipts_total,
                "month_rqc_total": c_rqc_total,
                "date_range_label": c_date_range,
            })
            seen_keys.add(current_key)

        # Strictly ensure that ONLY the system date current month has is_current = True
        for c in available_cycles:
            c["is_current"] = bool(c.get("month_key") == current_key)

        active_cycle = next((c for c in available_cycles if c.get("is_current")), None) or (available_cycles[0] if available_cycles else None)

        m_plan = plan["monthly_plan"]
        m_actual = plan["monthly_actual"]
        m_label = plan["monthly_label"]
        m_gap = plan["monthly_gap"]
        m_gap_pct = plan["monthly_gap_pct"]
        m_achieved = plan["monthly_achieved"]
        m_status_label = plan["monthly_status_label"]

        if active_cycle:
            m_plan = active_cycle.get("monthly_plan", 0)
            m_actual = active_cycle.get("monthly_actual", 0)
            m_label = active_cycle.get("month_label", today_label)
            m_gap = active_cycle.get("monthly_gap")
            m_gap_pct = active_cycle.get("monthly_gap_pct", 0.0)
            m_achieved = active_cycle.get("monthly_achieved")
            m_status_label = active_cycle.get("monthly_status_label", "—")

            # Always maintain Overall Throughput and Quoted Throughput
            expected_throughput = float(quoted_throughput) if quoted_throughput is not None else 0.0
            current_throughput = overall_current_throughput
            if expected_throughput and expected_throughput > 0:
                target_achieved_status = bool(current_throughput >= expected_throughput)
                target_achieved_label = "Achieved" if target_achieved_status else "Not Achieved"
                throughput_gap = round(current_throughput - expected_throughput, 2)
                throughput_gap_pct = round((throughput_gap / expected_throughput) * 100, 2)
            else:
                target_achieved_status = None
                target_achieved_label = "—"
                throughput_gap = None
                throughput_gap_pct = 0.0

            target_achieved = current_throughput
            working_days = active_cycle.get("working_days", curr_month_working_days)
            manpower_used = active_cycle.get("manpower_used", curr_manpower)
            headcount_branch = active_cycle.get("headcount_branch", headcount_branch)
            headcount_inhouse = active_cycle.get("headcount_inhouse", headcount_inhouse)

        return {
            "project": self,
            "current_month_key": current_key,
            "available_cycles": available_cycles,
            "available_cycles_json": json.dumps(available_cycles),
            "monthly_plan": m_plan,
            "monthly_actual": m_actual,
            "monthly_target_achieved": m_actual,
            "monthly_gap": m_gap,
            "monthly_gap_pct": m_gap_pct,
            "monthly_achieved": m_achieved,
            "monthly_status_label": m_status_label,
            "monthly_label": m_label,

            "weekly_plan": plan["weekly_plan"],
            "weekly_actual": plan["weekly_actual"],
            "weekly_target_achieved": plan["weekly_target_achieved"],
            "weekly_gap": plan["weekly_gap"],
            "weekly_gap_pct": plan["weekly_gap_pct"],
            "weekly_achieved": plan["weekly_achieved"],
            "weekly_status_label": plan["weekly_status_label"],
            "weekly_label": plan["weekly_label"],
            "gm_name": self.gm_name,
            "pm_name": snap.get("pm_name") or self.pm_name,
            "pl_name": self.pl_name,
            "branch_receipt": branch_receipt,
            "branch_receipt_target": branch_receipt_target,
            "branch_receipt_gap": branch_receipt_gap,
            "branch_receipt_gap_pct": branch_receipt_gap_pct,
            "branch_receipt_achieved": branch_receipt_achieved,
            "branch_receipt_status_label": branch_receipt_status_label,
            "rqc_completed": rqc_completed,
            "rqc_target": rqc_target,
            "rqc_gap": rqc_gap,
            "rqc_gap_pct": rqc_gap_pct,
            "rqc_achieved": rqc_achieved,
            "rqc_status_label": rqc_status_label,
            "throughput_branch": snap.get("throughput_branch") or quoted_throughput,
            "throughput_inhouse": throughput_inhouse,
            "expected_throughput": expected_throughput,
            "current_throughput": current_throughput,
            "quoted_throughput": quoted_throughput,
            "overall_throughput": overall_current_throughput,
            "total_inventory_data": total_inv_data,
            "total_working_days": timeline_days,
            "manpower_used": manpower_used,
            "working_days": working_days,
            "target_achieved": target_achieved,
            "target_achieved_status": target_achieved_status,
            "target_achieved_label": target_achieved_label,
            "throughput_gap": throughput_gap,
            "throughput_gap_pct": throughput_gap_pct,
            "headcount_branch": headcount_branch,
            "headcount_inhouse": headcount_inhouse,
            "variance_vs_plan": variance_vs_plan,
            "planned_run_rate": planned_run_rate,
            "current_run_rate": current_run_rate,
            "run_rate_gap": run_rate_gap,
            "run_rate_gap_pct": run_rate_gap_pct,
            "run_rate_achieved": run_rate_achieved,
            "run_rate_status_label": run_rate_status_label,
            "rqc_quality_score": rqc_quality_score,
            "required_headcount": required_headcount,
            "as_of_month": snap.get("month_label") or "",
        }

    def operational_alerts(self):
        """Section-3 alert flags. Shipment Risk / Throughput Variance
        compare the source sheets' own Current vs Planned/Quoted numbers
        directly. Vendor Receipt / RQC Plan-vs-Actual don't have a separate
        day-by-day plan number of their own in the source file, so they're
        compared against an EXPECTED-BY-NOW figure using the same
        working-days pace as `timeline_percent` (Target Records x % of the
        project timeline elapsed) - only shown once a Branch Receipt/RQC
        column is actually configured. Bands: <=10% gap = fine (no alert),
        10-25% = yellow, >25% = red - same tight-bands convention as
        `status`/`milestones()` elsewhere on Project."""
        panel = self.operational_panel()
        alerts = []

        def _band(gap_pct):
            gap_pct = abs(gap_pct)
            if gap_pct <= 10:
                return None
            return "red" if gap_pct > 25 else "yellow"

        prr, crr = panel["planned_run_rate"], panel["current_run_rate"]
        if prr and crr is not None and crr < prr:
            gap_pct = (crr - prr) / prr * 100
            level = _band(gap_pct)
            if level:
                alerts.append({
                    "type": "Shipment Risk", "level": level, "project": self,
                    "message": f"Current run rate ({crr:,.0f}) is {abs(gap_pct):.1f}% below the required run rate ({prr:,.0f}).",
                })

        et, ct = panel["expected_throughput"], panel["current_throughput"]
        if et and ct is not None and ct < et:
            gap_pct = (ct - et) / et * 100
            level = _band(gap_pct)
            if level:
                alerts.append({
                    "type": "Throughput Variance", "level": level, "project": self,
                    "message": f"Current throughput ({ct:,.0f}) is {abs(gap_pct):.1f}% below the planned throughput ({et:,.0f}).",
                })

        expected_to_date = self.target_records * (self.timeline_percent / 100) if self.target_records else 0
        br = panel.get("branch_receipt")
        br_target = panel.get("branch_receipt_target")
        if br is not None and br_target:
            if br < br_target:
                gap_pct = (br - br_target) / br_target * 100
                level = _band(gap_pct)
                if level:
                    alerts.append({
                        "type": "Branch Receipt Shortfall", "level": level, "project": self,
                        "message": f"Daily branch receipt ({br:,.0f}) is {abs(gap_pct):.1f}% below the daily target ({br_target:,.0f}).",
                    })
        elif self.branch_receipt_column_key and expected_to_date and br is not None:
            gap_pct = (br - expected_to_date) / expected_to_date * 100
            level = _band(gap_pct)
            if level:
                direction = "shortfall" if br < expected_to_date else "excess"
                alerts.append({
                    "type": "Vendor Receipt Plan vs Actual", "level": level, "project": self,
                    "message": f"Branch receipt ({br:,.0f}) is a {abs(gap_pct):.1f}% {direction} against the expected pace ({expected_to_date:,.0f}).",
                })

        rc = panel.get("rqc_completed")
        rc_target = panel.get("rqc_target")
        if rc is not None and rc_target:
            if rc < rc_target:
                gap_pct = (rc - rc_target) / rc_target * 100
                level = _band(gap_pct)
                if level:
                    alerts.append({
                        "type": "RQC Shortfall", "level": level, "project": self,
                        "message": f"Daily RQC completed ({rc:,.0f}) is {abs(gap_pct):.1f}% below the daily target ({rc_target:,.0f}).",
                    })
        elif self.rqc_completed_column_key and expected_to_date and rc is not None:
            if rc < expected_to_date:
                gap_pct = (rc - expected_to_date) / expected_to_date * 100
                level = _band(gap_pct)
                if level:
                    alerts.append({
                        "type": "RQC Plan vs Actual", "level": level, "project": self,
                        "message": f"RQC completed ({rc:,.0f}) is {abs(gap_pct):.1f}% below the expected pace ({expected_to_date:,.0f}).",
                    })

        return alerts

    def project_status_panel(self):
        """Project Status panel (Project Insights): sourced from the Project
        Summary sheet's OWN computed cells (its own formulas - Days Gone
        excluding Sundays, Delivered %, etc.) whenever that sheet follows
        the standard layout - not re-derived in Python, so this always
        matches what's actually in the file. Falls back per-field (not
        whole-panel) to the Selected_Column Inventory sum / imported field
        if a particular cell is missing or unreadable (e.g. BPW's Received
        Records cell has a stray name typed into it instead of a number)."""
        snap = self.summary_snapshot or {}
        target = self.target_records

        delivered = snap.get("delivered")
        if delivered is None:
            delivered = self._sum_inventory_column(self.delivered_column_key) if self.delivered_column_key else self.delivered_records
        delivered = int(delivered)

        delivered_pct = snap.get("delivered_pct")
        if delivered_pct is None:
            delivered_pct = round(min(delivered / target, 1) * 100, 2) if target else 0.0

        days_gone = snap.get("days_gone")
        days_gone = int(days_gone) if days_gone is not None else self.working_days_completed

        days_gone_pct = snap.get("days_gone_pct")
        days_gone_pct = days_gone_pct if days_gone_pct is not None else self.timeline_percent

        remaining = snap.get("remaining")
        remaining = int(remaining) if remaining is not None else max(target - delivered, 0)

        remaining_pct = snap.get("remaining_pct")
        remaining_pct = remaining_pct if remaining_pct is not None else round(100 - delivered_pct, 2)

        remaining_days = snap.get("remaining_days")
        remaining_days = int(remaining_days) if remaining_days is not None else self.working_days_remaining

        remaining_days_pct = snap.get("remaining_days_pct")
        remaining_days_pct = remaining_days_pct if remaining_days_pct is not None else round(100 - days_gone_pct, 2)

        return {
            "delivered_records": delivered, "delivered_records_pct": delivered_pct,
            "days_gone": days_gone, "days_gone_pct": days_gone_pct,
            "remaining_records": remaining, "remaining_records_pct": remaining_pct,
            "remaining_days": remaining_days, "remaining_days_pct": remaining_days_pct,
            "column_selected": bool(self.delivered_column_key),
            "from_excel_formulas": snap.get("delivered") is not None,
        }

    def branch_status_panel(self):
        """Branch Status panel (Project Insights): same principle as
        `project_status_panel` - Received Records/% come straight from the
        Project Summary sheet's own cells when readable, falling back
        per-field to the Selected_Column Inventory sum otherwise."""
        snap = self.summary_snapshot or {}
        target = self.target_records

        received = snap.get("received")
        if received is None:
            received = self._sum_inventory_column(self.received_column_key)
        received = int(received)

        received_pct = snap.get("received_pct")
        if received_pct is None:
            received_pct = round(min(received / target, 1) * 100, 2) if target else 0.0

        days_gone_pct = snap.get("days_gone_pct")
        days_gone_pct = days_gone_pct if days_gone_pct is not None else self.timeline_percent

        remaining = max(target - received, 0)
        remaining_pct = round(100 - received_pct, 2) if target else 0.0
        remaining_days_pct = round(100 - days_gone_pct, 2)

        return {
            "received_records": received, "received_records_pct": received_pct,
            "days_gone_pct": days_gone_pct,
            "remaining_records": remaining, "remaining_records_pct": remaining_pct,
            "remaining_days_pct": remaining_days_pct,
            "column_selected": bool(self.received_column_key),
            "from_excel_formulas": snap.get("received") is not None,
        }

    def batch_status_values(self):
        """Distinct values found in the selected batches-status Inventory
        column (e.g. "Keyed", "WIP", "QC Hold") - populates the second
        "which value means Keyed" dropdown once a status column is picked."""
        if not self.batches_status_column_key:
            return []
        seen = {}
        for extra in self.inventory_items.exclude(extra={}).values_list("extra", flat=True):
            raw = extra.get(self.batches_status_column_key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                seen.setdefault(text.lower(), text)
        return sorted(seen.values())

    def batches_keying_panel(self):
        """No. of Batches − No. of Batches Shipped = No. of Batches Being
        Keyed. "No. of Batches" is ALWAYS the full Inventory row count -
        never shrunk by the optional status-column refinement below, since
        that would make the total itself move depending on configuration
        and stop matching the plain row count shown everywhere else.

        The optional refinement only changes what counts as "Shipped/Keyed"
        (the number subtracted), tried in this order:
          1. batches_end_date_column_key set -> a row counts as Keyed once
             that End Date column has a date filled in, but only among rows
             that aren't blank/WIP in the status column (a row still sitting
             in WIP isn't meaningfully "keyed" yet even with a stray date).
          2. batches_keyed_value set -> a row counts as Keyed when the
             status column's value matches this text exactly.
        Falls back to the plain Shipment-Date-based `promoted` count
        (No. of Batches Shipped) until either refinement is configured -
        this is the default and matches the sheet's own Shipment column."""
        total_batches = self.total_batches

        if not self.batches_status_column_key:
            return {
                "configured": False,
                "total_batches": total_batches,
                "batches_keyed": self.promoted,
                "batches_being_keyed": max(total_batches - self.promoted, 0),
            }

        status_key = self.batches_status_column_key
        end_date_key = self.batches_end_date_column_key
        keyed_value = (self.batches_keyed_value or "").strip().lower()
        keyed = 0
        for extra in self.inventory_items.exclude(extra={}).values_list("extra", flat=True):
            raw = extra.get(status_key)
            text = str(raw).strip() if raw is not None else ""
            if not text or "wip" in text.lower():
                continue  # blank or WIP - not counted as Keyed, but still part of the Total

            if end_date_key:
                end_val = extra.get(end_date_key)
                if end_val is not None and str(end_val).strip():
                    keyed += 1
            elif keyed_value and text.strip().lower() == keyed_value:
                keyed += 1

        return {
            "configured": True,
            "total_batches": total_batches,
            "batches_keyed": keyed,
            "batches_being_keyed": max(total_batches - keyed, 0),
        }

    def weekly_delivery_plan(self):
        """Groups this project's WeeklyDeliveryPlanRow rows (already one row
        per week + one "Total" row per month, from the sheet's own
        structure - see WeeklyDeliveryPlanRow/extract_weekly_delivery_rows)
        into one entry per month for display: that month's Plan/Actual/
        Variance (straight from its own "Total" row, or summed from the
        week rows if a template genuinely has no Total row) plus the list
        of individual week rows underneath."""
        from itertools import groupby

        rows = list(self.weekly_delivery_rows.all().order_by("month_start", "sno"))
        months = []
        for month_label, group in groupby(rows, key=lambda r: r.month_label):
            group = list(group)
            total_row = next((r for r in group if r.is_total), None)
            weeks = [r for r in group if not r.is_total]
            for w in weeks:
                if w.shipment_date:
                    if w.shipment_date.weekday() == 0:  # Monday -> Saturday
                        w.shipment_date = w.shipment_date - datetime.timedelta(days=2)
                    elif w.shipment_date.weekday() == 6:  # Sunday -> Saturday
                        w.shipment_date = w.shipment_date - datetime.timedelta(days=1)
            months.append({
                "month_label": month_label,
                "monthly_plan": total_row.plan_records if total_row else sum(w.plan_records for w in weeks),
                "monthly_actual": total_row.actual_records if total_row else sum(w.actual_records for w in weeks),
                "monthly_variance": total_row.variance if total_row else sum(w.variance for w in weeks),
                "monthly_variance_pct": total_row.variance_pct if total_row else 0,
                "weeks": weeks,
            })
        return months

    def operational_day_detail(self, target_date):
        """Day / current-week (Mon-Sun containing target_date) / current-
        month rollup for Branch Receipt and RQC Completed - powers the
        Operational Dashboard's Calendar view (click any date, see that
        day's + its week's + its month's totals). RQC Quality Score has no
        daily history (see DailyOperationalMetric docstring) so it's
        reported here as the same running-average figure regardless of
        which date was clicked."""
        week_start = target_date - datetime.timedelta(days=target_date.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        month_start = target_date.replace(day=1)
        next_month = (
            target_date.replace(year=target_date.year + 1, month=1, day=1)
            if target_date.month == 12
            else target_date.replace(month=target_date.month + 1, day=1)
        )
        month_end = next_month - datetime.timedelta(days=1)

        out = {
            "date": target_date, "week_start": week_start, "week_end": week_end,
            "month_start": month_start, "month_end": month_end,
        }
        for key in (DailyOperationalMetric.METRIC_BRANCH_RECEIPT, DailyOperationalMetric.METRIC_RQC_COMPLETED):
            qs = self.daily_operational_metrics.filter(metric_key=key)
            out[key] = {
                "day": qs.filter(date=target_date).aggregate(v=Sum("value"))["v"] or 0,
                "week": qs.filter(date__gte=week_start, date__lte=week_end).aggregate(v=Sum("value"))["v"] or 0,
                "month": qs.filter(date__gte=month_start, date__lte=month_end).aggregate(v=Sum("value"))["v"] or 0,
            }
        snap = self.operational_snapshot or {}
        rqc_q = snap.get("rqc_quality_score")
        if rqc_q is not None:
            try:
                rqc_val = float(rqc_q)
                if 0 < rqc_val <= 1.0:
                    rqc_q = round(rqc_val * 100.0, 2)
                else:
                    rqc_q = round(rqc_val, 2)
            except (ValueError, TypeError):
                pass
        out["rqc_quality_score"] = rqc_q
        return out

    def daily_metric_dates(self, year, month):
        """Which day-of-month numbers this project has ANY daily-metric
        data for, in the given month - used to mark which Calendar cells
        actually have something behind them."""
        dates = self.daily_operational_metrics.filter(date__year=year, date__month=month).values_list("date", flat=True)
        return sorted({d.day for d in dates})

    @property
    def working_days_total(self):
        return _working_days(self.start_date, self.end_date)

    @property
    def working_days_completed(self):
        today = timezone.localdate()
        end = min(today, self.end_date)
        if end < self.start_date:
            return 0
        return _working_days(self.start_date, end)

    @property
    def working_days_remaining(self):
        return max(self.working_days_total - self.working_days_completed, 0)

    @property
    def timeline_percent(self):
        if not self.working_days_total:
            return 0.0
        return round(min(self.working_days_completed / self.working_days_total, 1) * 100, 2)

    @property
    def status(self):
        """3-state Red / Yellow / Green, driven by Delivered % vs the
        Project End Date combined with milestone checkpoints health:
          Green  = 100% delivered, OR comfortably on pace against the
                   working-days-elapsed fraction (timeline_percent) AND
                   all active milestone checkpoints are on track.
          Yellow = mildly behind pace OR any active milestone checkpoint is At Risk.
          Red    = meaningfully behind pace, milestone missed, or the end date
                   has already passed without hitting 100%.
        """
        if self.delivery_percent >= 100:
            return "green"
        today = timezone.localdate()
        if today > self.end_date:
            return "red"

        # 1. Pace against working-days timeline
        gap = self.timeline_percent - self.delivery_percent
        if gap <= 10:
            pace_status = "green"
        elif gap <= 25:
            pace_status = "yellow"
        else:
            pace_status = "red"

        # 2. Check milestone checkpoints health (if any active milestone is at risk or missed,
        # overall project health must reflect that risk).
        try:
            checkpoints = self.milestone_shipment_checkpoints()
            active_ms_statuses = []
            for cp in checkpoints:
                if today <= cp["date"]:
                    active_ms_statuses.append(cp["status"])
                else:
                    # Past checkpoint: if overall delivery hasn't reached target yet, it is missed
                    target_pct = float(str(cp["label"]).replace("%", "").strip() or 0)
                    if self.delivery_percent < target_pct:
                        active_ms_statuses.append("red")

            all_statuses = [pace_status] + active_ms_statuses
            if "red" in all_statuses:
                return "red"
            if "yellow" in all_statuses:
                return "yellow"
            return "green"
        except Exception:
            return pace_status

    @property
    def status_label(self):
        """Human-readable status label matching the milestone dashboard legend."""
        labels = {
            "green": "On Track",
            "yellow": "At Risk",
            "red": "Behind",
        }
        return labels.get(self.status, self.status.title())

    @property
    def effective_customer_name(self):
        """Returns customer_name if set on Project, otherwise falls back to the
        matching ProjectTemplate.customer_name."""
        if self.customer_name:
            return self.customer_name
        try:
            from apps.mapping.models import ProjectTemplate
            t = ProjectTemplate.objects.filter(project_key=self.project_key).first()
            if t and t.customer_name:
                return t.customer_name
        except Exception:
            pass
        return ""

    @property
    def unit(self):
        """Volume unit label ("Records", "Pages", ...) - read straight from
        the Project Summary sheet's C2 cell at import time (see
        read_project_summary_snapshot in import_engine.py). Sheets are
        typed however the person who built them typed them ("RECORDS",
        "pages", "Records "...) - normalized to Proper Case for display so
        the website is consistent regardless of the source cell's casing/
        spacing. The raw value is untouched in summary_snapshot; this is
        display-only."""
        raw = (self.summary_snapshot or {}).get("volume_unit") or ""
        return raw.strip().title()

    @property
    def total_weeks(self):
        """Whole project duration in weeks (min 1) - kept for anything else
        that wants a simple week count; `expected_percent` below uses the
        finer working-day-weighted calendar instead."""
        duration_days = (self.end_date - self.start_date).days + 1
        return max(round(duration_days / 7), 1)

    def _weekly_working_days(self):
        """Splits the project into Monday-Sunday calendar weeks (clipped to
        the project's actual start/end), each paired with how many WORKING
        days (Mon-Sat, Sunday excluded - same rule as `_working_days`) that
        week actually contains. A partial first/last week naturally gets
        fewer working days than a full week, so its share of Total Volume
        comes out proportionally smaller - matches the requested "Weekly
        Target" example table exactly (a 2-working-day opening week nets a
        smaller Weekly Target than the full 6-day weeks after it)."""
        weeks = []
        cursor = self.start_date - datetime.timedelta(days=self.start_date.weekday())  # Monday on/before start
        while cursor <= self.end_date:
            week_end = cursor + datetime.timedelta(days=6)  # the following Sunday
            actual_start = max(cursor, self.start_date)
            actual_end = min(week_end, self.end_date)
            working_days = _working_days(actual_start, actual_end) if actual_start <= actual_end else 0
            weeks.append({"week_start": cursor, "week_end": min(week_end, self.end_date), "working_days": working_days})
            cursor += datetime.timedelta(days=7)
        return weeks

    @property
    def expected_percent(self):
        """Expected % via a CUMULATIVE DAILY target (working days only,
        Sunday excluded):
          1. total working days = Mon-Sat across the whole project (Sunday
             excluded) - same as `working_days_total`.
          2. daily target = Total Volume ÷ total working days.
          3. each week's FULL target = daily target × THAT week's own
             working-day count (a short opening/closing week gets a
             proportionally smaller share, not an even 1/N split) - used
             for any week that has fully elapsed.
          4. For the CURRENT (in-progress) week, only the working days that
             have actually elapsed so far (Monday up through today, Sundays
             don't count) are added - not the whole week's target - so this
             steps up on every working day, not just Mondays.
          5. Cumulative Target = sum of completed weeks' full targets, plus
             the current week's elapsed-so-far target.
          6. Expected % = Cumulative Target ÷ Total Volume × 100.
        (Previously this only advanced once per week, on Mondays - now it
        advances every working day.)"""
        total_working_days = self.working_days_total
        if not total_working_days or not self.target_records:
            return 0.0
        daily_target = self.target_records / total_working_days
        today = timezone.localdate()
        cumulative = 0.0
        for week in self._weekly_working_days():
            if week["week_start"] > today:
                break
            if week["week_end"] <= today:
                # Week has fully elapsed - count its whole target.
                cumulative += week["working_days"] * daily_target
            else:
                # Current, still-in-progress week - count only the working
                # days elapsed so far (clipped to the project's own start).
                actual_start = max(week["week_start"], self.start_date)
                elapsed_end = min(today, week["week_end"])
                elapsed_days = _working_days(actual_start, elapsed_end) if actual_start <= elapsed_end else 0
                cumulative += elapsed_days * daily_target
        return round(min(cumulative / self.target_records, 1) * 100, 2)

    def shipped_records_by(self, target_date):
        """Total delivered records ACTUALLY shipped by `target_date`, per
        the Inventory Tracker's own Shipment Date column - the real,
        as-shipped count, as opposed to `expected_percent`'s pace estimate.

        Uses whichever Inventory column is configured as this project's
        `delivered_column_key` (the same per-project "which column is
        Delivered Records" mapping already used by project_status_panel() -
        different projects genuinely use different columns for this, e.g.
        Shipment Date in column H / Delivered Record Count in column J for
        one project, different columns entirely for another), falling back
        to the generic `record_count` field only if that mapping hasn't
        been configured yet. Used for the Project Detail Table's
        "PctBy X%" milestone columns."""
        if target_date is None:
            return 0
        column_key = self.delivered_column_key or "record_count"
        return self._sum_inventory_column(column_key, upto_date=target_date)

    def milestone_shipment_checkpoints(self):
        """10% / 50% / 100% checkpoint dates (reusing milestones()'s target
        dates, skipping "IDX Start" - which is just Project Start, see
        `milestones()`) paired with "PctBy X%": what % of Total Volume had
        ACTUALLY shipped, per the Inventory page's Shipment Date column, by
        that checkpoint's target date - and a Green/Yellow/Red colour for
        that checkpoint, same tight-bands rule as `milestones()`/`status`
        but comparing against THIS checkpoint's own actual shipped-by-date
        % instead of the single current overall delivery %, since a
        checkpoint that's still in the future needs to be judged against
        its own pace, not today's running total. Feeds the Project Detail
        Table's "10% Date / PctBy 10% / 50% Date / PctBy 50% / 100% Date /
        PctBy 100%" columns."""
        target = self.target_records
        today = timezone.localdate()
        out = []
        for m in self.milestones():
            if m["label"] == "IDX Start":
                continue
            m_date, target_pct = m["date"], m["expected_pct"]
            shipped = self.shipped_records_by(m_date)
            pct_by = round(min(shipped / target, 1) * 100, 2) if target else 0.0

            if pct_by >= target_pct:
                status = "green"
            elif today > m_date:
                status = "red"  # checkpoint date has passed and target wasn't met
            else:
                days_elapsed = max((today - self.start_date).days, 0)
                days_window = max((m_date - self.start_date).days, 1)
                expected_pct_today = target_pct * min(days_elapsed / days_window, 1)
                gap = expected_pct_today - pct_by
                status = "green" if gap <= 10 else ("yellow" if gap <= 25 else "red")

            out.append({
                "label": m["label"], "date": m_date, "pct_by": pct_by, "status": status,
                "status_label": MILESTONE_STATUS_LABELS[status],
            })
        return out

    def milestones(self):
        """IDX Start / 10% / 50% / 100% checkpoints, using the same 3-state
        Red / Yellow / Green model as `status`, driven by Delivered % vs the
        checkpoint date:
          green  = delivery already at/ahead of this checkpoint's target %,
                   OR still comfortably on a straight-line pace toward it
          yellow = checkpoint date hasn't arrived yet, but delivery is
                   mildly behind that pace
          red    = checkpoint date hasn't arrived yet and delivery is
                   meaningfully behind pace, OR the checkpoint date has
                   already passed without the target being hit

        For a checkpoint at day N with target T%, the expected delivery
        *today* is T% scaled by how far through that checkpoint's window we
        already are (days_elapsed / days_to_checkpoint) - a straight-line
        "should be here by now" pace. Bands are tight (10 / 25) on purpose so
        checkpoints don't default to Yellow for the entire project runtime.
        """
        duration = (self.end_date - self.start_date).days or 1
        today = timezone.localdate()
        pts = []
        for label, fraction in [("IDX Start", 0.0), ("10%", 0.10), ("50%", 0.50), ("100%", 1.0)]:
            m_date = self.start_date + datetime.timedelta(days=round(duration * fraction))
            target_pct = fraction * 100

            if self.delivery_percent >= target_pct:
                status = "green"
            elif today > m_date:
                status = "red"
            else:
                days_elapsed = max((today - self.start_date).days, 0)
                days_window = max((m_date - self.start_date).days, 1)
                expected_pct_today = target_pct * min(days_elapsed / days_window, 1)
                gap = expected_pct_today - self.delivery_percent
                status = "green" if gap <= 10 else ("yellow" if gap <= 25 else "red")

            pts.append({
                "label": label, "date": m_date, "status": status,
                "status_label": MILESTONE_STATUS_LABELS[status],
                "reached": today >= m_date, "expected_pct": round(target_pct, 1),
                "actual_pct": self.delivery_percent,
            })
        return pts

    @property
    def milestone_100_status(self):
        """The 100% checkpoint's status alone - used to bucket projects for
        the dashboard's Status / Project Count summary table. Uses the same
        real-shipped-by-date basis as milestone_shipment_checkpoints()
        (Inventory page Shipment Date column), not the plain pace estimate."""
        return self.milestone_shipment_checkpoints()[-1]["status"]


MILESTONE_STATUS_LABELS = {
    "green": "On Track / Met",
    "yellow": "At Risk",
    "red": "Missed / Behind",
}


# SWIFT ProSys Company Holidays (Tamil Calendar)
# Standard fixed holidays that apply across years:
SWIFT_PROSYS_ANNUAL_HOLIDAYS = {
    (1, 1): "New Year",
    (1, 15): "Pongal",
    (1, 16): "Pongal Day 2",
    (1, 26): "Republic Day",
    (4, 14): "Tamil New Year",
    (5, 1): "May Day",
    (8, 15): "Independence Day",
    (9, 14): "Vinayakar Chathurthi",
    (10, 2): "Gandhi Jayanti",
    (10, 19): "Ayutha Pooja",
    (10, 20): "Saraswathi Pooja",  # User explicitly requested to add Saraswathi Pooja
    (11, 8): "Diwali",
    (11, 9): "Diwali Day 2",
}

# Moveable Tamil calendar festival dates by year (with 2026 exactly matching the company holiday sheet):
SWIFT_PROSYS_YEAR_HOLIDAYS = {
    2026: {
        (9, 14): "Vinayakar Chathurthi",
        (10, 19): "Ayutha Pooja",
        (10, 20): "Saraswathi Pooja",
        (11, 8): "Diwali",
        (11, 9): "Diwali Day 2",
    },
    2025: {
        (8, 27): "Vinayakar Chathurthi",
        (10, 1): "Ayutha Pooja",
        (10, 2): "Saraswathi Pooja",
        (10, 20): "Diwali",
        (10, 21): "Diwali Day 2",
    },
}


def is_company_holiday(d):
    """Check if date d is a Swift ProSys company holiday (Tamil Calendar list)."""
    if d.year in SWIFT_PROSYS_YEAR_HOLIDAYS:
        yr_holidays = SWIFT_PROSYS_YEAR_HOLIDAYS[d.year]
        if (d.month, d.day) in yr_holidays:
            return True
    return (d.month, d.day) in SWIFT_PROSYS_ANNUAL_HOLIDAYS


def get_month_working_days(year, month):
    """Return total working days in given (year, month), excluding Sundays and Swift ProSys holidays."""
    _, num_days = calendar.monthrange(year, month)
    wd = 0
    for day in range(1, num_days + 1):
        cur = datetime.date(year, month, day)
        if cur.weekday() != 6 and not is_company_holiday(cur):
            wd += 1
    return wd


def _working_days(start, end):
    """Working days between start and end inclusive: every day except Sunday and company holidays."""
    if end < start:
        return 0
    total_days = (end - start).days + 1
    wd = 0
    for i in range(total_days):
        cur = start + datetime.timedelta(days=i)
        if cur.weekday() != 6 and not is_company_holiday(cur):
            wd += 1
    return wd


class ImportBatch(models.Model):
    """Audit trail: one row per Excel file (or Google Sheet) imported, whether it succeeded or not."""

    STATUS_SUCCESS = "SUCCESS"
    STATUS_FAILED = "FAILED"

    SOURCE_FILE = "FILE"
    SOURCE_GOOGLE_SHEET = "GOOGLE_SHEET"

    project_template_key = models.SlugField(max_length=50)
    file_name = models.CharField(max_length=255)
    source_type = models.CharField(
        max_length=15,
        choices=[(SOURCE_FILE, "Excel Upload"), (SOURCE_GOOGLE_SHEET, "Google Sheet")],
        default=SOURCE_FILE,
    )
    source_url = models.URLField(max_length=500, blank=True, default="")
    uploaded_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=10, choices=[(STATUS_SUCCESS, "Success"), (STATUS_FAILED, "Failed")])
    errors = models.JSONField(default=list, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_batches")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} - {self.status}"


class WeeklyDeliveryPlanRow(models.Model):
    """One row per week (plus one 'Total' row per month) from a project's
    "Weekly Delivery Plan" sheet - that sheet is a repeating block per
    month ("August 2026 - Weekly Delivery Plan", its own header row, a
    Week-1..Week-N row each, then a Total row), not one flat table, so this
    mirrors that shape directly rather than forcing it into Project's
    single-row-per-project fields. Fully replaced on every (re)import, same
    "source file is the single source of truth" rule as InventoryItem."""

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="weekly_delivery_rows")

    month_label = models.CharField(max_length=50, blank=True, default="")  # e.g. "August 2026", as written on the sheet
    month_start = models.DateField(null=True, blank=True)  # parsed from month_label, for chronological sorting

    week_label = models.CharField(max_length=50, blank=True, default="")  # "Week-1".."Week-N", or "Total"
    sno = models.IntegerField(null=True, blank=True)
    shipment_date = models.DateField(null=True, blank=True)

    plan_records = models.BigIntegerField(default=0)
    actual_records = models.BigIntegerField(default=0)
    variance = models.BigIntegerField(default=0)
    variance_pct = models.FloatField(default=0)

    reason = models.CharField(max_length=500, blank=True, default="")
    remarks = models.CharField(max_length=500, blank=True, default="")

    is_total = models.BooleanField(default=False)  # True for the month's own "Total" row, False for a real week

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["month_start", "sno"]

    def save(self, *args, **kwargs):
        if self.shipment_date and not self.is_total:
            if self.shipment_date.weekday() == 0:  # Monday -> Saturday
                self.shipment_date = self.shipment_date - datetime.timedelta(days=2)
            elif self.shipment_date.weekday() == 6:  # Sunday -> Saturday
                self.shipment_date = self.shipment_date - datetime.timedelta(days=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.project_name} - {self.month_label} {self.week_label}"


class DailyOperationalMetric(models.Model):
    """One row per (project, metric, date) - the full daily history behind
    two of the Operational Dashboard's figures (Daily Branch Receipt, Daily
    RQC Completed). Project.operational_snapshot only keeps each metric's
    single MOST RECENT day's number (see apps/mapping/engine.py:
    extract_daily_metric) - this is the full history behind it, so the
    Calendar view can show ANY date's day/week/month figures, not just the
    latest one. Populated from the same config["daily_metrics"] rule, via
    extract_daily_metric_series - fully replaced on every (re)import.

    RQC Quality Score has no calendar history: per its own mapping rule
    (no date_column - a running average, not something that resets per
    day), there's no "which day" to file any of it under."""

    METRIC_BRANCH_RECEIPT = "branch_receipt"
    METRIC_RQC_COMPLETED = "rqc_completed"
    METRIC_CHOICES = [
        (METRIC_BRANCH_RECEIPT, "Daily Branch Receipt"),
        (METRIC_RQC_COMPLETED, "Daily RQC Completed"),
    ]

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="daily_operational_metrics")
    metric_key = models.CharField(max_length=30, choices=METRIC_CHOICES)
    date = models.DateField()
    value = models.FloatField(default=0)

    class Meta:
        ordering = ["date"]
        unique_together = [("project", "metric_key", "date")]

    def __str__(self):
        return f"{self.project.project_name} {self.metric_key} {self.date}: {self.value}"
