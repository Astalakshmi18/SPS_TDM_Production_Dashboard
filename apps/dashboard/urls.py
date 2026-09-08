from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("operational/", views.operational, name="operational"),
    path("operational/calendar/<int:pk>/", views.operational_calendar, name="operational_calendar"),
    path("operational/calendar/<int:pk>/day/<str:date>/", views.operational_day_detail_json, name="operational_day_detail_json"),
]
