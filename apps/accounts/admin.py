from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch_list")
    list_filter = ("role", "branches")
    search_fields = ("user__username", "user__email")
    filter_horizontal = ("branches",)

    def branch_list(self, obj):
        if obj.is_admin:
            return "All branches"
        return ", ".join(b.code for b in obj.branches.all()) or "None assigned"
    branch_list.short_description = "Branch Access"
