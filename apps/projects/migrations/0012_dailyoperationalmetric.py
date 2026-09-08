import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0011_project_operational_dashboard_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyOperationalMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("metric_key", models.CharField(choices=[("branch_receipt", "Daily Branch Receipt"), ("rqc_completed", "Daily RQC Completed")], max_length=30)),
                ("date", models.DateField()),
                ("value", models.FloatField(default=0)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="daily_operational_metrics", to="projects.project")),
            ],
            options={
                "ordering": ["date"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="dailyoperationalmetric",
            unique_together={("project", "metric_key", "date")},
        ),
    ]
