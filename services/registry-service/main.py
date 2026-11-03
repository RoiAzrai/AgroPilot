from fastapi import FastAPI

from errors import register_error_handlers
from routers import catalogue, farms, plots

app = FastAPI(title="AgroPilot registry-service", version="0.1.0")
register_error_handlers(app)
app.include_router(farms.router)
app.include_router(plots.router)
app.include_router(catalogue.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
