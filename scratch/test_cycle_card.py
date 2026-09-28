import os, sys, django

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()
c = Client()
user = User.objects.first()
c.force_login(user)

resp = c.get("/projects/4/")
html = resp.content.decode("utf-8")

needle = '<div class="cycle-card'
idx = html.find(needle)
print("Index:", idx)
if idx != -1:
    print(html[idx:idx+2500])
else:
    print("NOT FOUND!")
    # Check if operational.available_cycles is truthy
    print("contains 'Production Cycle'?", "Production Cycle" in html)
    print("contains 'Active Cycle'?", "Active Cycle" in html)
