# registry-service

Farms, plots and catalogues for AgroPilot (FastAPI, port 8000). SQLite locally, PostgreSQL in production.

## Configuration

```bash
cp .env.example .env
```

Four keys, read from the environment first and then from `.env`:

- `DATABASE_URL` (required): `sqlite:///file:registry.db?mode=rw&uri=true` or `postgresql+psycopg://agropilot:<password>@localhost:5432/registry`.
- `DB_CONNECT_TIMEOUT_SECONDS`, `DB_BUSY_TIMEOUT_SECONDS`, `DB_POOL_TIMEOUT_SECONDS`.

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
uv run python seed_db.py --reset    # prints the target first, then drops all registry data and rebuilds
```

`--reset` deletes every row in the registry tables of the database named by `DATABASE_URL`. Check the printed target before relying on it.
