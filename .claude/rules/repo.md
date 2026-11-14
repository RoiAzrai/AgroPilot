# Repository rules

- Each Python service under `services/` is its own uv project. Run `uv` commands (`uv sync`, `uv run pytest`, `uv run uvicorn ...`) from the folder of the service you are working on, never from the repo root.
- Services never import each other's code. They talk over HTTP only.
- Don't change the database schema in `services/registry-service/seed_registry.sh`. The schema is given by the task, and other work depends on it.
- Tests must never touch a real database: not `services/registry-service/registry.db`, and not the PostgreSQL `registry` database. Use the fixtures in `tests/conftest.py`, which give each test a fresh seeded copy.
- Don't commit `registry.db`, `.env` files (except `.env.example`), or `services/registry-service/perf/results/`. They are local and already in `.gitignore`.
