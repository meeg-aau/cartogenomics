from django.db import migrations, models
from django.utils import timezone


def copy_retrieved_at(apps, schema_editor):
    IngestVersion = apps.get_model("versions", "IngestVersion")
    now = timezone.now()
    for iv in IngestVersion.objects.all():
        iv.created_at = iv.retrieved_at if iv.retrieved_at else now
        iv.save(update_fields=["created_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("versions", "0010_rename_upstream_last_modified_ingestversion_last_modified_internal_and_more"),
    ]

    operations = [
        # Add nullable first so existing rows don't violate NOT NULL
        migrations.AddField(
            model_name="ingestversion",
            name="created_at",
            field=models.DateTimeField(null=True),
        ),
        # Copy retrieved_at → created_at, fall back to now() if null
        migrations.RunPython(copy_retrieved_at, migrations.RunPython.noop),
        # Tighten to auto_now_add (non-nullable, DB-managed)
        migrations.AlterField(
            model_name="ingestversion",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.RemoveField(
            model_name="ingestversion",
            name="retrieved_at",
        ),
    ]
