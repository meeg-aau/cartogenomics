FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# GDAL/GEOS/PROJ: django.contrib.gis (incl. LayerMapping, used to ingest
# Natural Earth country boundary polygons) talks to these via ctypes at
# runtime - no pip GDAL/osgeo package is needed, just the shared libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils \
        libproj-dev \
        gdal-bin \
        libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# TODO: sample_metadata_curation is currently installed locally as an
# editable checkout from a sibling directory (../sample-metadata-curation),
# so it's not in requirements.txt and isn't available in this build context.
# ingest_sample won't work in this image until that's resolved - e.g. publish
# it as a package and add it to requirements.txt, or vendor/COPY it in here.

COPY . .

EXPOSE 8000

# Postgres/PostGIS is expected to run as a separate service (see .env-driven
# DB_HOST/DB_PORT config in settings.py) - not bundled into this image.
CMD ["gunicorn", "cartogenomics.wsgi:application", "--bind", "0.0.0.0:8000"]
