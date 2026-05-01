# Configuration

The app is configured via environment variables. Docker Compose reads `.env` from the repo root automatically.

```bash
cp .env.example .env
```

Edit `.env` before running `docker compose up`. For direct `python3 manage.py ...` commands outside Compose, export the relevant variables in your shell or source the file first.

---

## Django

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | `replace-me` | Django secret key. Set a long random string in production. |
| `DJANGO_DEBUG` | `0` | Enable debug mode (`1`/`true`/`yes`). Disable in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of allowed hostnames. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | _(empty)_ | Comma-separated list of trusted origins for CSRF, e.g. `https://yourdomain.com`. Required when running behind a reverse proxy. |
| `DJANGO_TIME_ZONE` | `UTC` | Django timezone, e.g. `Europe/London`. |
| `HOMOREPEAT_TRUST_X_FORWARDED_FOR` | `false` | Use the first `X-Forwarded-For` address for upload audit IPs. Enable only behind a trusted reverse proxy that strips client-supplied forwarded headers. |
| `no_admin` | `0` | Bypass Django staff/admin login and grant full permissions to every web request. Use only on trusted local machines. |

---

## Database

If `DATABASE_ENGINE` is not set, Django falls back to a local `db.sqlite3` file. SQLite is fine for development but does not exercise the production import path.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_ENGINE` | _(unset → SQLite)_ | Set to `django.db.backends.postgresql` to use PostgreSQL. |
| `DATABASE_NAME` | `homorepeat` | Database name. |
| `DATABASE_USER` | `homorepeat` | Database user. |
| `DATABASE_PASSWORD` | `homorepeat` | Database password. |
| `DATABASE_HOST` | `postgres` | Database host. Inside Compose this matches the `postgres` service name. |
| `DATABASE_PORT` | `5432` | Database port. |

The `postgres` Compose service reads its own set of variables that must match the above:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `homorepeat` | PostgreSQL database name (must equal `DATABASE_NAME`). |
| `POSTGRES_USER` | `homorepeat` | PostgreSQL user (must equal `DATABASE_USER`). |
| `POSTGRES_PASSWORD` | `homorepeat` | PostgreSQL password (must equal `DATABASE_PASSWORD`). |

---

## Redis

If `REDIS_URL` is not set, Celery uses an in-memory broker and the cache uses Django's local-memory backend. Both fall back gracefully but are not suitable for multi-process or multi-container deployments.

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | _(unset)_ | Redis connection URL, e.g. `redis://redis:6379`. Inside Compose, the `redis` service is used automatically. |

---

## Runs and Imports

| Variable | Default | Description |
|----------|---------|-------------|
| `HOMOREPEAT_RUNS_ROOT` | _(empty)_ | Host path to the directory containing published pipeline run folders. Compose mounts this read-only at `/workspace/homorepeat_pipeline/runs` inside the web and worker containers. When set, the import queue UI at `/imports/` will auto-detect runs in that directory. |
| `HOMOREPEAT_IMPORTS_ROOT` | `/data/imports` | App-managed import storage root. Compose mounts the persistent `homorepeat_imports` volume here in `web`, `celery-import-worker`, and `celery-upload-worker`. Uploaded chunks, temporary extraction files, and validated uploaded library runs live under this root. |
| `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES` | `5368709120` | Maximum uploaded zip size in bytes. Default is 5 GB. |
| `HOMOREPEAT_UPLOAD_CHUNK_BYTES` | `8388608` | Browser upload chunk size in bytes. Default is 8 MiB. |
| `HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES` | `53687091200` | Maximum total extracted file bytes from one uploaded zip. Default is 50 GB. |
| `HOMOREPEAT_UPLOAD_MAX_FILES` | `200000` | Maximum number of entries/files accepted from one uploaded zip. |
| `HOMOREPEAT_UPLOAD_INCOMPLETE_RETENTION_HOURS` | `24` | Age after which incomplete uploads (`receiving`, `received`, `extracting`) are marked failed and their working directory is removed by Celery Beat cleanup. |
| `HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS` | `168` | Age after which failed upload working directories are removed. The database row is kept for troubleshooting. |

### Disk Preflight

| Variable | Default | Description |
|----------|---------|-------------|
| `HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED` | `true` | Enable disk-space checks before accepting uploads and before extraction. Set to `false` for local dev environments where storage is unconstrained. |
| `HOMOREPEAT_UPLOAD_MIN_FREE_BYTES` | `1073741824` | Minimum free bytes that must remain after an upload or extraction. Default is 1 GiB. |
| `HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER` | `3.0` | Multiplier applied to zip size to estimate extracted volume when computing the extraction preflight. Increase for highly compressible content. |

### Per-User Quotas

All limits default to `0` (unlimited). When non-zero, they apply to authenticated staff users only. Unauthenticated requests are not subject to per-user limits.

| Variable | Default | Description |
|----------|---------|-------------|
| `HOMOREPEAT_UPLOAD_MAX_ACTIVE_PER_USER` | `0` | Maximum concurrent in-progress uploads per user. Rejects new uploads with HTTP 429 when exceeded. |
| `HOMOREPEAT_UPLOAD_MAX_DAILY_BYTES_PER_USER` | `0` | Maximum bytes a user may upload across all uploads started in the current UTC day. |
| `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES_PER_USER` | `0` | Per-user zip size cap. Supplements the global `HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES`. |

Uploaded-run storage uses two subdirectories under `HOMOREPEAT_IMPORTS_ROOT`:

```text
uploads/<upload-id>/chunks/*.part # verified chunk files
uploads/<upload-id>/source.zip    # assembled source archive
uploads/<upload-id>/extracted/    # temporary extraction scratch data
library/<run-id>/publish          # validated uploaded run used by the importer
```

Plan disk capacity for the source zip, chunk files, extracted files, and final
library copy. A conservative formula is
`2 × zip_size + 2 × estimated_extracted_size + 1 GiB`; with the default
extraction multiplier of `3.0`, this is about `zip_size × 8 + 1 GiB` per upload
in flight. Ready/imported library data is retained until removed manually. The
cleanup task removes stale working directories only; it does not delete
ready/imported library data.

---

## Application Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `HOMOREPEAT_BROWSER_STATS_CACHE_TTL` | `60` | Cache TTL in seconds for stats bundles and taxonomy gutter payloads. |
| `CELERY_TASK_ALWAYS_EAGER` | `0` | Run Celery tasks synchronously in the calling process. Useful for local debugging without a running worker. |

---

## Internal Services

These are set automatically in `compose.yaml` and rarely need to be changed.

| Variable | Default | Description |
|----------|---------|-------------|
| `FLOWER_INTERNAL_URL` | `http://flower:5555` | Internal URL the web service uses to proxy requests to the Flower Celery monitor. |

---

## Postgres Tuning (Compose only)

These control the `postgres` container's server config. The defaults are sized for a development workstation. For large imports, increase `POSTGRES_SHM_SIZE` and `POSTGRES_WORK_MEM`.

| Variable | Default |
|----------|---------|
| `POSTGRES_SHM_SIZE` | `1gb` |
| `POSTGRES_MAX_WAL_SIZE` | `8GB` |
| `POSTGRES_MIN_WAL_SIZE` | `1GB` |
| `POSTGRES_CHECKPOINT_TIMEOUT` | `30min` |
| `POSTGRES_CHECKPOINT_COMPLETION_TARGET` | `0.9` |
| `POSTGRES_WAL_COMPRESSION` | `on` |
| `POSTGRES_WORK_MEM` | `64MB` |
| `POSTGRES_MAINTENANCE_WORK_MEM` | `256MB` |
