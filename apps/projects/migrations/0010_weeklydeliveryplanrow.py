import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0009_project_gm_pm_pl_manpower"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeeklyDeliveryPlanRow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month_label", models.CharField(blank=True, default="", max_length=50)),
                ("month_start", models.DateField(blank=True, null=True)),
                ("week_label", models.CharField(blank=True, default="", max_length=50)),
                ("sno", models.IntegerField(blank=True, null=True)),
                ("shipment_date", models.DateField(blank=True, null=True)),
                ("plan_records", models.BigIntegerField(default=0)),
                ("actual_records", models.BigIntegerField(default=0)),
                ("variance", models.BigIntegerField(default=0)),
                ("variance_pct", models.FloatField(default=0)),
                ("reason", models.CharField(blank=True, default="", max_length=500)),
                ("remarks", models.CharField(blank=True, default="", max_length=500)),
                ("is_total", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="weekly_delivery_rows", to="projects.project")),
            ],
            options={
                "ordering": ["month_start", "sno"],
            },
        ),
    ]
