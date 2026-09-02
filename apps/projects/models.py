import datetime
import secrets

from django.db import models
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
    vendor = models.CharField(max_length=150, blank=True, default="")
    event_type = models.CharField(max_length=150, blank=True, default="")
    ocr_status = models.CharField(max_length=100, blank=True, default="")

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
        """3-state Red / Yellow / Green, driven purely by Delivered % vs the
        Project End Date (per branch requirement):
          Green  = 100% delivered, OR comfortably on pace against the
                   working-days-elapsed fraction (timeline_percent).
          Yellow = mildly behind pace but the end date hasn't passed yet.
          Red    = meaningfully behind pace, or the end date has already
                   passed without hitting 100%.
        Bands are intentionally tight (10 / 25) so a project only sits in
        Yellow for a real, small slip - not by default."""
        if self.delivery_percent >= 100:
            return "green"
        today = timezone.localdate()
        if today > self.end_date:
            return "red"
        gap = self.timeline_percent - self.delivery_percent
        if gap <= 10:
            return "green"
        if gap <= 25:
            return "yellow"
        return "red"

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


def _working_days(start, end):
    """NETWORKDAYS.INTL(start, end, "0000001") equivalent: every day except Sunday."""
    if end < start:
        return 0
    total_days = (end - start).days + 1
    sundays = sum(1 for i in range(total_days) if (start + datetime.timedelta(days=i)).weekday() == 6)
    return total_days - sundays


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