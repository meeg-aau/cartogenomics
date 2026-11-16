import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cartogenomics.settings")

app = Celery("cartogenomics")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
