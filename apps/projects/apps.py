import sys

from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"

    def ready(self):
        # Only start the in-process auto-sync scheduler when actually
        # serving requests (gunicorn, or `manage.py runserver`) - never
        # during one-off management commands like migrate/collectstatic/
        # create_default_admin, which also trigger AppConfig.ready() but
        # exit immediately after running, and never during `manage.py test`.
        is_manage_py = len(sys.argv) > 0 and sys.argv[0].endswith("manage.py")
        is_runserver = is_manage_py and len(sys.argv) > 1 and sys.argv[1] == "runserver"
        if is_manage_py and not is_runserver:
            return

        from . import scheduler
        scheduler.start()
