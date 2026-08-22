from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.accounts.models import UserProfile

User = get_user_model()

class Command(BaseCommand):
    help = "Creates default admin and manager accounts if they do not exist."

    def handle(self, *args, **options):
        # 1. Admin User (Full Access)
        admin_user, created_admin = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "2019astalakshmi@gmail.com",
                "is_staff": True,
                "is_superuser": True
            }
        )
        if created_admin:
            admin_user.set_password("Swift_ProSys")
            admin_user.save()
            profile, _ = UserProfile.objects.get_or_create(user=admin_user)
            profile.role = UserProfile.ROLE_ADMIN
            profile.save()
            self.stdout.write(self.style.SUCCESS("Created default Admin user: admin / admin123"))
        else:
            # Ensure admin user has admin password and admin role
            admin_user.set_password("Swift_ProSys")
            admin_user.save()
            profile, _ = UserProfile.objects.get_or_create(user=admin_user)
            profile.role = UserProfile.ROLE_ADMIN
            profile.save()
            self.stdout.write(self.style.SUCCESS("Updated Admin credentials: admin / admin123"))
