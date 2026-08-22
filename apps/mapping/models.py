from django.db import models


class ProjectTemplate(models.Model):
    """A reusable mapping configuration for one incoming Excel format
    (BPW, Latvia, SSH, HOR, ...). The `config` JSON tells the import engine,
    per standard-schema field, exactly where to find the value - either a
    fixed cell, a column to sum, or a header name to look up in a flat table.
    See apps/mapping/engine.py for the supported "mode" values.
    """

    project_key = models.SlugField(max_length=50, unique=True, help_text="e.g. BPW, LATVIA, SSH, HOR")
    display_name = models.CharField(max_length=150)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    config = models.JSONField(help_text="Field -> extraction rule mapping. See mappings/*.json for examples.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project_key"]

    def __str__(self):
        return f"{self.project_key} ({self.display_name})"
