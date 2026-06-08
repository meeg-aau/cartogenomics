# Cartogenomics DB

A Django + PostgreSQL database for large-scale microbiome and genomics data. Stores curated metadata for environmental samples, sequencing runs, and metagenome-assembled genomes (MAGs), with provenance tracking and RO-Crate export.

---

## Tech Stack

- **Backend:** Django 5, PostgreSQL
- **APIs:** ENA Portal API, BioSamples API
- **Curation:** `sample_metadata_curation` (internal pipeline)
- **Export:** RO-Crate (`rocrate` library)
- **Large data:** Parquet files (external, queried via DuckDB — currently running on a mock abundance file)
- **Environment:** micromamba (`sample_curation` environment)
- **Local DB:** Docker via Colima

---

## Apps

| App | Purpose |
|---|---|
| `samples` | Sample metadata — `Sample`, `SampleVersion` |
| `runs` | Sequencing runs — `Run` |
| `genomes` | Genome assemblies (MAGs) — `Genome`, `GenomeVersion` |
| `versions` | Ingestion and release tracking — `IngestVersion`, `CartogenomicsRelease` |
| `external` | Links to external data files — `ExternalResource` |
| `rocrates` | RO-Crate export |
| `api_fetch` | ENA and BioSamples API clients |

---

## How the Tables Work

### Provenance: `IngestVersion` and `CartogenomicsRelease`

Every ingested record links to an `IngestVersion`, which records the batch-level provenance — what source system the data came from, what pipeline processed it, and when.

```
CartogenomicsRelease   ←   IngestVersion
    label                      source_system   (ENA, BIOSAMPLES, etc.)
    notes                      data_type       (sample_metadata, reads, genome, etc.)
                               label           (e.g. "mfd_2026_01_15")
                               pipeline_version (e.g. "sample_metadata_curation 0.1.0")
                               ingested_on     (when we ran this)
```

`IngestVersion` is one row per batch — shared across all records ingested in that run. It records **our** processing event, not upstream timestamps.

---

### Current state: `Sample`, `Run`, `Genome`

Each of these holds the **current curated state** of the record. They are updated in-place on re-ingest if fields change.

**`Sample`**
```
biosample / ena_sample      — accession(s)
source_dataset              — e.g. "MFD"
latitude / longitude        — curated geography
region / locality           — curated place names
ontology                    — closest term to an ENVO biome OR user specified strutured data fields for ontology
geography_check_status      — PASS / WARN / FAIL / SKIP
raw_metadata                — full raw JSON from BioSamples
archive_created             — when BioSamples first received this record
archive_updated             — when BioSamples last modified this record
ingest                      → IngestVersion (most recent batch that touched this)
```

**`Run`**
```
accession                   — ENA run accession (ERR...)
sample                      → Sample
read_count / sequencer
library_source / library_strategy
archive_created             — when ENA first received this run.
ingest                      → IngestVersion
```
Runs are immutable — once deposited in ENA they do not change, so there is no `archive_updated` and no version history.

**`Genome`**
```
accession                   — ENA assembly accession (GCA...)
completeness / contamination / completeness_software
genome_size / n50
taxonomy                    — full lineage string
archive_created             — when ENA first received this assembly
archive_updated             — when ENA last modified it
ingest                      → IngestVersion
```

> Genomes and samples are **independent entities** — there is no foreign key between them, they are condensed into one entry in the Genome table, with x2 links to the ExternalResource table.

---

### Change history: `SampleVersion` and `GenomeVersion`

When a re-ingest detects that curated fields have changed, the old version is closed and a new one is opened. This gives a full audit trail of how each record has evolved.

```
SampleVersion
    sample          → Sample
    ingest          → IngestVersion  (which batch caused this change)
    valid_from      — when this version became active
    valid_to        — when it was superseded (null = currently active)
    [all curated fields snapshotted at this point in time]
```

Rules:
- Exactly one open version per record (`valid_to` is null)
- A new version is only written when curated fields change — not on every re-ingest
- `archive_created` / `archive_updated` are on `Sample` directly, not versioned, since they are reference metadata from the source archive rather than curated values

---

### External data links: `ExternalResource`

One row per URL or file linked to a sample, run, or genome. Exactly one of the three FK columns is populated per row.

```
source_system       — ENA, BIOSAMPLES, BIOSTUDIES, INTERNAL
accession           — filename or accession used as a stable lookup key
url                 — direct link to the resource
first_created_external / last_modified_external
sample / run / genome   — exactly one is non-null
ingest              → IngestVersion
```

Examples of what gets stored:
- BioSamples JSON endpoint for a sample (`https://www.ebi.ac.uk/biosamples/samples/{acc}.json`)
- FASTQ FTP paths for a run (`ftp.ebi.ac.uk/...fastq.gz`)
- FASTA FTP path for a genome assembly (`ftp.ebi.ac.uk/...fasta.gz`)
- BioStudies Parquet file URLs (future)

---

## Ingestion Commands

All ingestion is done via Django management commands

### Ingest a single sample (and its runs). Run ingestion cannot be independent of sample ingestion.

Accepts any INSDC accession (biosample, ENA sample, run, experiment). Resolves and ingests the sample metadata and all associated sequencing runs. Pass `--no-runs` to skip run ingestion.

```bash
python manage.py ingest_sample \
  --accession SAMEA123456 \
  --source MFD \
  --version-label mfd_2026_01_15 \
  --release-label 1.0
```

### Bulk ingest samples from a file

```bash
python manage.py ingest_bulk_samples \
  --file accessions.txt \
  --source MFD \
  --version-label mfd_2026_01_15
```

File format: one accession per line, `#` for comments. Add `--continue-on-error` to skip failed accessions rather than aborting.

### Ingest a genome

```bash
python manage.py ingest_genome \
  --accession GCA_123456789.1 \
  --source GTDB \
  --version-label gtdb_r220 \
  --release-label 1.0
```

### Export an RO-Crate (CLI)

```bash
# Samples only
python manage.py export_rocrate --source-dataset MFD --output mfd.zip

# Genomes only
python manage.py export_rocrate --no-samples --include-genomes \
  --genome-release-label 1.0 --min-completeness 90 --output genomes.zip
```

---

## Web Interface

RO-Crate exports can also be triggered via the web UI at `/rocrate/`. The flow is:

1. **`GET /rocrate/`** — filter form (source dataset, geography bounds, completeness thresholds, etc.)
2. **`POST /rocrate/`** — submits the job, creates an `ExportJob` record, kicks off a Celery background task, and redirects to the status page
3. **`GET /rocrate/{job_id}/`** — status page (pending / running / complete / failed)
4. **`GET /rocrate/{job_id}/download/`** — downloads the `.zip` once complete

The build runs asynchronously via Celery. The `ExportJob` model tracks status, the filter parameters used, and the output path of the zip file.

> Requires a running Celery worker alongside Django. The worker processes the `build_rocrate_task` which builds the crate, generates a preview, and zips the output to `/tmp/rocrate_{job_id}.zip`.

---

## Local Development

### Prerequisites

- Colima + Docker
- micromamba

### Start the database

```bash
colima start
docker start cartogenomics-postgres
```

### Run Django

```bash
micromamba activate sample_curation
python manage.py runserver
```

### Environment

`.env` file lives one level above the repo root. Required variables: `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `ALLOWED_HOSTS`.

---

## Genome–Sample Linkage

Genomes and samples are not linked by a foreign key. The relationship is stored as a **presence/absence matrix in Parquet** (rows = genomes, columns = samples). Querying this matrix via DuckDB is planned and will enable:

- "Which samples contain genome X?"
- "Which genomes were detected in samples matching filter Y?"
- RO-Crate exports filtered by genome presence

Do not add a `sample` FK to `Genome` — use the Parquet matrix.
