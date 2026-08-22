from django.contrib import admin
from .models import ProjectTemplate


@admin.register(ProjectTemplate)
class ProjectTemplateAdmin(admin.ModelAdmin):
    list_display = ("project_key", "display_name", "branch", "is_active", "updated_at")
    list_filter = ("branch", "is_active")
    search_fields = ("project_key", "display_name")
