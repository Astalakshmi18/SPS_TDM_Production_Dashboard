from django.contrib import admin
from .models import Project, ImportBatch


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("project_name", "project_key", "branch", "target_records",
                     "delivered_records", "delivery_percent", "total_batches",
                     "batches_being_keyed", "promoted", "promoted_percent", "status", "last_updated")
    list_filter = ("branch", "project_key")
    search_fields = ("project_name", "project_key")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("file_name", "project_template_key", "status", "uploaded_by", "created_at")
    list_filter = ("status", "project_template_key")
