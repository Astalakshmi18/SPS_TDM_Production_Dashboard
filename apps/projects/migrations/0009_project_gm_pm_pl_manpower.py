from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0008_project_summary_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="gm_name",
            field=models.CharField(blank=True, default="", max_length=150, verbose_name="GM Name"),
        ),
        migrations.AddField(
            model_name="project",
            name="pm_name",
            field=models.CharField(blank=True, default="", max_length=150, verbose_name="PM Name"),
        ),
        migrations.AddField(
            model_name="project",
            name="pl_name",
            field=models.CharField(blank=True, default="", max_length=150, verbose_name="PL Name"),
        ),
        migrations.AddField(
            model_name="project",
            name="branch_manpower_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="project",
            name="inhouse_manpower_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
