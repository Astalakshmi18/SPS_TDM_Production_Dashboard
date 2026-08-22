from django.db import models


class InventoryItem(models.Model):
    """One row per source file/folder from a project's Inventory/Calculation
    sheet. This is the "inventory tracker" half of the dashboard - Project
    (in apps.projects) is the rolled-up "production tracker" half. Kept as a
    separate model so the Production dashboard stays fast (aggregate-only
    queries) while Inventory can show/search/filter every individual row.
    """

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="inventory_items")

    file_name = models.CharField(max_length=255, blank=True, default="")
    folder_name = models.CharField(max_length=255, blank=True, default="")
    event_type = models.CharField(max_length=150, blank=True, default="")
    language = models.CharField(max_length=100, blank=True, default="")

    image_count = models.BigIntegerField(default=0)
    record_count = models.BigIntegerField(default=0)

    shipment_date = models.DateField(null=True, blank=True)
    remarks = models.CharField(max_length=500, blank=True, default="")

    extra = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-shipment_date", "file_name"]

    def __str__(self):
        return f"{self.file_name or self.folder_name} ({self.project.project_name})"
