"""FastAPI server for the Real-Time Flight Monitoring & Airport Analytics Dashboard."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dashboard.db import fetch_dashboard_state

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Flight Monitoring Control Tower", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard_data(
    airport: str | None = Query(default=None, description="IATA airport code, e.g. BLR"),
    direction: str | None = Query(default=None, description="Optional ARRIVAL or DEPARTURE filter"),
) -> JSONResponse:
    try:
        payload = fetch_dashboard_state(airport_code=airport, direction=direction)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return JSONResponse(content=payload)
