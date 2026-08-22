import json
from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.accounts.models import UserProfile
from apps.branches.models import Branch
from apps.mapping.models import ProjectTemplate

User = get_user_model()

class Command(BaseCommand):
    help = "Creates default admin/manager accounts, seeds branches, and syncs mapping templates."

    def handle(self, *args, **options):
        # 1. Seed Physical Branches (TDM, CHN, KPM, MDU)
        for code, name in getattr(settings, "BRANCH_CHOICES", [("TDM", "Tindivanam"), ("CHN", "Chennai"), ("KPM", "Kanchipuram"), ("MDU", "Madurai")]):
            Branch.objects.get_or_create(code=code, defaults={"name": name})
        self.stdout.write(self.style.SUCCESS("Physical branches verified/created."))

        # 2. Provision Admin User (Full Access)
        admin_user, created_admin = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "2019astalakshmi@gmail.com",
                "is_staff": True,
                "is_superuser": True
            }
        )
        admin_user.set_password("Swift_ProSys")
        admin_user.save()
        profile, _ = UserProfile.objects.get_or_create(user=admin_user)
        profile.role = UserProfile.ROLE_ADMIN
        profile.save()
        self.stdout.write(self.style.SUCCESS("Admin user ready: admin / Swift_ProSys"))

        # 3. Sync Mapping Templates from /mappings JSON files
        mappings_dir = getattr(settings, "MAPPINGS_DIR", None)
        if mappings_dir and mappings_dir.exists():
            created, updated = 0, 0
            for path in sorted(mappings_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
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
                except Exception as err:
                    self.stdout.write(f"Warning syncing {path.name}: {err}")
            self.stdout.write(self.style.SUCCESS(f"Mapping templates synced: {created} created, {updated} updated."))
