from django.urls import path
from . import views

app_name = "mapping"

urlpatterns = [
    path("", views.template_list, name="list"),
    path("sync/", views.sync_from_disk, name="sync"),
    path("new/", views.template_create, name="create"),
    path("auto-detect/", views.auto_detect, name="auto_detect"),
    path("auto-detect/save/", views.auto_detect_save, name="auto_detect_save"),
    path("<int:pk>/", views.template_detail, name="detail"),
    path("<int:pk>/edit/", views.template_edit, name="edit"),
    path("<int:pk>/delete/", views.template_delete, name="delete"),
]
