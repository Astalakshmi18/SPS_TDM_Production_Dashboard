from django.db import models


class Branch(models.Model):
    """The company's four physical branches. Fixed set, but kept as a table
    (not just choices) so it can be FK'd, filtered, and extended later."""

    code = models.CharField(max_length=10, unique=True)  # TDM, CHN, KPM, MDU
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"
