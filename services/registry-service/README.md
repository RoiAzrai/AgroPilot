# registry-service

Farms, plots and catalogues for AgroPilot (FastAPI, port 8000). SQLite locally, PostgreSQL in production.

## Configuration

```bash
cp .env.example .env
```

Keys, read from the environment first and then from `.env`:

- `DATABASE_URL` (required): `sqlite:///file:registry.db?mode=rw&uri=true` or `postgresql+psycopg://agropilot:<password>@localhost:5432/registry`.
- `DB_CONNECT_TIMEOUT_SECONDS`, `DB_BUSY_TIMEOUT_SECONDS`, `DB_POOL_TIMEOUT_SECONDS`.
- `AWS_S3_BUCKET`, `AWS_REGION` (required): where plot photos are stored.
- `S3_CONNECT_TIMEOUT_SECONDS` (3), `S3_READ_TIMEOUT_SECONDS` (10), `S3_MAX_ATTEMPTS` (3): optional.

AWS credentials are never configured here. boto3 finds them itself: `~/.aws` locally (or `AWS_PROFILE` exported in your shell), the instance's IAM role on EC2.

Percent-encode special characters in the password (for example `@` becomes `%40`, `:` becomes `%3A`).

## Local SQLite

```bash
bash seed_registry.sh
uv run uvicorn main:app --port 8000
```

## PostgreSQL

One role owns the five tables and is used by both `seed_db.py` and the service, through the same `DATABASE_URL`. `seed_db.py` runs no `GRANT`, so a service running as a different role without grants fails with SQLSTATE `42501`.

Databases must be UTF8. As a PostgreSQL superuser:

```sql
CREATE ROLE agropilot LOGIN PASSWORD '...';
CREATE DATABASE registry_perf OWNER agropilot ENCODING 'UTF8' TEMPLATE template0;
-- for an existing database:
ALTER DATABASE registry OWNER TO agropilot;
```

Then create the tables and load the 15 seed rows:

```bash
uv run python seed_db.py            # refuses if any of the five tables already exists
uv run python seed_db.py --reset    # prints the target, asks you to type the database name, then drops all registry data and rebuilds
uv run python seed_db.py --reset --yes   # the same without the question (for scripts)
```

`--reset` deletes every row in the registry tables of the database named by `DATABASE_URL`. It prints the target (the database the driver will really use, including `?dbname=` and `?host=` from the URL) and asks you to type its name: the file name for SQLite, the database name for PostgreSQL. Without a terminal it refuses unless `--yes` is passed.

## Plot photos

One photo per plot, stored in S3 under `{farm_id}/{plot_id}/photo`. The database keeps only the key and the content type, in the `plot_photos` table, which the service creates at startup if it is missing.

`POST /v1/plots/{id}/photo` takes a multipart form with one field, `file`, and returns `201`:

```json
{"plot_id": "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002", "key": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001/c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002/photo", "content_type": "image/png"}
```

A new upload overwrites the previous photo.

`GET /v1/plots/{id}/photo` returns the photo's bytes with its content type, `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.

```bash
curl -F "file=@photo.png;type=image/png" http://127.0.0.1:8000/v1/plots/<id>/photo
curl -o out.png http://127.0.0.1:8000/v1/plots/<id>/photo
```

| Situation | Status | `code` |
| --- | --- | --- |
| Unknown plot, or a plot with no photo (GET) | 404 | `NOT_FOUND` |
| No `file` field, empty file, type not `image/jpeg`, `image/png` or `image/webp`, or larger than 5 MiB. S3 is not called. | 422 | `VALIDATION` |
| Any S3 error: no credentials, access denied, timeout, an object missing from the bucket. Logged; the stored key does not change. | 503 + `Retry-After` | `UNAVAILABLE` |

`GET /v1/plot-photos?farm_id=<uuid>` says which plots of a farm have a photo, so a client does not request one photo per plot. It reads the database only and never calls S3, so it works while S3 is down. It returns `200` with the ids in plot creation order:

```json
{"plot_ids": ["c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"]}
```

| Situation | Status | `code` |
| --- | --- | --- |
| A farm with no photos, or an unknown `farm_id` (same as `GET /v1/plots?farm_id=`) | 200 | `{"plot_ids": []}` |
| `farm_id` missing or not a UUID | 422 | `VALIDATION` |

Deleting a plot deletes its `plot_photos` row. The S3 object stays (see judgment log 50).
