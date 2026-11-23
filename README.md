# AgroPilot

AgroPilot helps a grower manage agricultural crops with modern AI. 


## Where to start

Services live under `services/`:

| Service | Port | Purpose |
| --- | --- | --- |
| [registry-service](services/registry-service/README.md) | 8000 | Farms, plots and catalogues. |
| [weather-service](services/weather-service/README.md) | 8001 | Daily forecast (ET0 and rain) from Open-Meteo. |
| [planner-service](services/planner-service/README.md) | 8002 | Irrigation plan for a plot. |
| [frontend](services/frontend/README.md) | 3000 | The web UI. |

The steps below start `registry-service`, a FastAPI application.

```bash
cd services/registry-service
uv sync
cp .env.example .env
bash seed_registry.sh
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/health. A running service returns `{"status": "ok"}`.

Configuration, local SQLite and PostgreSQL setup: [services/registry-service/README.md](services/registry-service/README.md).

The weather service (daily ET0 and rain forecast, port 8001): [services/weather-service/README.md](services/weather-service/README.md).
