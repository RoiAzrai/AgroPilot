from fastapi import FastAPI

from db import lifespan
from errors import register_error_handlers
from routers import catalogue, farms, plot_photos, plots

app = FastAPI(title="AgroPilot registry-service", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(farms.router)
app.include_router(plots.router)
app.include_router(plot_photos.router)
app.include_router(catalogue.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
