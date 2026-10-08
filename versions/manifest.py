import json
from pathlib import Path
from typing import Optional

from django.conf import settings

from versions.models import IngestVersion

"""
maps the resource JSON produceed by SAMBAL curation.
Records and unifies version IDs for all files used.
"""

SOURCE_TO_SYSTEM = {
    "ena_checklist": IngestVersion.SourceSystem.ENA,
    "coordinate_cleaner": IngestVersion.SourceSystem.COORDINATE_CLEANER,
    "ror": IngestVersion.SourceSystem.ROR,
}


def load_curation_manifest(path: Optional[Path] = None) -> dict:
    path = Path(path or settings.SAMBAL_MANIFEST_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"SAMBAL resource manifest not found at {path}. "
            "Run 'setup-sample-resources' first."
        )
    return json.loads(path.read_text())


def pipeline_version_from_manifest(manifest: dict) -> str:
    tool = manifest.get("tool", {})
    name = tool.get("name")
    version = tool.get("version")
    if not name or not version:
        return ""
    return f"{name} {version}"


def sync_reference_source_versions(manifest: dict) -> list[IngestVersion]:
    """
    Record the current version of each reference source SAMBAL consumes
    (ENA checklist, CoordinateCleaner, ROR) as its own IngestVersion row.

    Only adds a new row if versions differ.
    """
    synced = []
    inputs = manifest.get("inputs", {})
    for key, source_system in SOURCE_TO_SYSTEM.items():
        info = inputs.get(key)
        if not info:
            continue
        version = info.get("version") or info.get("commit")
        if not version:
            continue
        ingest_version, _ = IngestVersion.objects.update_or_create(
            source_system=source_system,
            data_type=IngestVersion.DataType.REFERENCE_DATA,
            label=version,
            defaults={"upstream_version": version},
        )
        synced.append(ingest_version)
    return synced
