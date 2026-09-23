from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import claims_routes, health_routes, openstat_routes, soniox_routes

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
