import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import claims_routes, health_routes, openstat_routes, soniox_routes

# Our loggers (src.*) print to the console next to uvicorn's; LOG_LEVEL=DEBUG for more.
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="backslashreplace")  # ₱ in log lines on Windows consoles
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
_app_logger = logging.getLogger("src")
if not _app_logger.handlers:
    _app_logger.addHandler(_handler)
_app_logger.setLevel(settings.log_level)
_app_logger.propagate = False

app = FastAPI(title="API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health_routes.router)
app.include_router(soniox_routes.router)
app.include_router(openstat_routes.router)
app.include_router(claims_routes.router)
