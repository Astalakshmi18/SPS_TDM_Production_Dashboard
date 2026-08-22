from django.contrib import admin
from .models import InventoryItem


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("file_name", "project", "event_type", "language", "image_count", "record_count", "shipment_date")
    list_filter = ("project", "event_type", "language")
    search_fields = ("file_name", "folder_name")
