# RO-Crate Export REST API — Design Sketch

External users call this API to request an RO-Crate zip without needing
the full Django/Postgres stack installed locally.

---

## Job flow

```
POST /api/rocrate/export/         ← filter params as JSON body
  → spawns Celery task
  → returns {"job_id": "abc123", "status": "pending"}

GET /api/rocrate/export/abc123/
  → {"status": "running"|"complete"|"failed"}

GET /api/rocrate/export/abc123/download/
  → streams the zip (or redirect to object storage URL)
```

---

## Model — `rocrates/models.py`

```python
class ExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING  = "pending"
        RUNNING  = "running"
        COMPLETE = "complete"
        FAILED   = "failed"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4)
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    params      = models.JSONField()
    output_path = models.CharField(max_length=500, blank=True)
    error       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
```

---

## API views — `rocrates/views.py`

```python
class ExportJobView(APIView):
    def post(self, request):
        job = ExportJob.objects.create(params=request.data)
        build_rocrate_task.delay(str(job.id))
        return Response({"job_id": job.id, "status": job.status}, status=202)

    def get(self, request, job_id):
        job = get_object_or_404(ExportJob, id=job_id)
        return Response({"job_id": job.id, "status": job.status, "error": job.error or None})


class ExportJobDownloadView(APIView):
    def get(self, request, job_id):
        job = get_object_or_404(ExportJob, id=job_id, status=ExportJob.Status.COMPLETE)
        return FileResponse(open(job.output_path, "rb"), as_attachment=True, filename="rocrate.zip")
```

---

## Celery task — `rocrates/tasks.py`

```python
@shared_task
def build_rocrate_task(job_id):
    job = ExportJob.objects.get(id=job_id)
    job.status = ExportJob.Status.RUNNING
    job.save(update_fields=["status"])

    try:
        crate = build_crate(**job.params)   # existing builder.py
        path = f"/tmp/rocrate_{job_id}.zip"
        crate.write_zip(path)
        job.output_path = path
        job.status = ExportJob.Status.COMPLETE
    except Exception as e:
        job.status = ExportJob.Status.FAILED
        job.error = str(e)

    job.save(update_fields=["status", "output_path", "error"])
```

---

## URLs — `rocrates/urls.py`

```python
urlpatterns = [
    path("export/",                        ExportJobView.as_view()),
    path("export/<uuid:job_id>/",          ExportJobView.as_view()),
    path("export/<uuid:job_id>/download/", ExportJobDownloadView.as_view()),
]
```

---

## New dependencies

| Package | Purpose |
|---|---|
| `djangorestframework` | API views and serialization |
| `celery` | Async task queue |
| `redis` | Celery broker (or use `django-q` for a lighter option) |

---

## External user workflow

```bash
# Submit export job
curl -X POST https://yourserver/api/rocrate/export/ \
  -H "Content-Type: application/json" \
  -d '{"source_dataset": "MFD", "include_genomes": true, "min_completeness": 80}'

# Poll until complete
curl https://yourserver/api/rocrate/export/abc123/

# Download
curl -O https://yourserver/api/rocrate/export/abc123/download/
```

---

## Open questions before building

- **Output storage**: `/tmp` works for a single VM. Multi-worker Celery needs S3
  or a shared volume so any worker can serve the download.
- **Auth**: API key or token? Public read vs. restricted?
- **Cleanup**: cron job to delete `/tmp/rocrate_*.zip` files after N hours.
- **Timeout**: large exports (full MFD dataset) may need a generous Celery task timeout.
