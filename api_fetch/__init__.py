from datetime import datetime

from django.utils import timezone


def parse_iso_date(raw):
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
    except (ValueError, TypeError):
        return None
