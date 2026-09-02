from django.urls import path
from . import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("upload/", views.project_upload, name="upload"),
    path("export/", views.project_export, name="export"),
    path("sync-all/", views.project_sync_all, name="sync_all"),
    path("new/", views.project_create, name="create"),
    path("<int:pk>/", views.project_detail, name="detail"),
    path("<int:pk>/edit/", views.project_edit, name="edit"),
    path("<int:pk>/delete/", views.project_delete, name="delete"),
    path("<int:pk>/insights/", views.project_insights, name="insights"),
    path("<int:pk>/sync-now/", views.project_sync_now, name="sync_now"),
    path("webhook/<int:pk>/<str:token>/", views.gsheet_webhook, name="gsheet_webhook"),
    path("cron/sync-all/<str:token>/", views.cron_sync_all, name="cron_sync_all"),
]
