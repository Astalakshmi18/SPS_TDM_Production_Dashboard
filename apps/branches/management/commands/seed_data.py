"""
python manage.py seed_data

Idempotent one-shot setup:
  1. Creates the 4 fixed branches (TDM, CHN, KPM, MDU).
  2. Creates a default admin login (admin / admin12345) if none exists.
  3. Syncs every mapping JSON in /mappings into ProjectTemplate rows.
Safe to re-run any time - everything uses get_or_create / update_or_create.
"""
import json

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.branches.models import Branch
from apps.mapping.models import ProjectTemplate


class Command(BaseCommand):
    help = "Seed branches, a default admin user, and sync mapping templates from /mappings."

    def handle(self, *args, **options):
        for code, name in settings.BRANCH_CHOICES:
            branch, created = Branch.objects.get_or_create(code=code, defaults={"name": name})
            self.stdout.write(f"{'Created' if created else 'Exists '} branch {code} - {name}")

        if not User.objects.filter(username="admin").exists():
            admin = User.objects.create_superuser("admin", "admin@swiftprosys.local", "admin12345")
            admin.profile.role = "ADMIN"
            admin.profile.save()
            self.stdout.write(self.style.SUCCESS("Created default admin login: admin / admin12345 (change this password immediately)"))
        else:
            self.stdout.write("Admin user already exists.")

        created, updated = 0, 0
        for path in sorted(settings.MAPPINGS_DIR.glob("*.json")):
            data = json.loads(path.read_text())
            branch = Branch.objects.filter(code=data.get("branch", "TDM")).first() or Branch.objects.first()
            obj, was_created = ProjectTemplate.objects.update_or_create(
                project_key=data["project_key"],
                defaults={
                    "display_name": data.get("display_name", data["project_key"]),
                    "branch": branch,
                    "config": data["config"],
                },
            )
            created += int(was_created)
            updated += int(not was_created)
        self.stdout.write(self.style.SUCCESS(f"Mapping templates: {created} created, {updated} updated."))
        self.stdout.write(self.style.SUCCESS("Seed complete. Run: python manage.py runserver"))
