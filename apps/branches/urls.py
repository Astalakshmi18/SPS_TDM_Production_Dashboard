from django.urls import path
from . import views

app_name = "branches"

urlpatterns = [
    path("", views.branch_list, name="list"),
    path("new/", views.branch_create, name="create"),
    path("<int:pk>/edit/", views.branch_edit, name="edit"),
    path("<int:pk>/delete/", views.branch_delete, name="delete"),
    path("<int:pk>/access/", views.branch_access, name="access"),
]
