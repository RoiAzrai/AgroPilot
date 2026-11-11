# Repository rules

- Run `uv` commands (`uv sync`, `uv run pytest`, `uv run uvicorn ...`) from `services/registry-service`. The project and lock file live there, not at the repo root.
- Don't change the database schema in `services/registry-service/seed_registry.sh`. The schema is given by the task, and other work depends on it.
- Tests must never modify the real `services/registry-service/registry.db`. Use the fixtures in `tests/conftest.py`, which give each test a fresh seeded copy.
- Don't commit `registry.db` or `services/registry-service/perf/results/`. They are local output and are already in `.gitignore`.
