from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0010_weeklydeliveryplanrow"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="branch_receipt_column_key",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="project",
            name="rqc_completed_column_key",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="project",
            name="rqc_quality_column_key",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="project",
            name="operational_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
