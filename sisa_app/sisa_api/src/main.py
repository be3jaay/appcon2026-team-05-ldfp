from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import health_routes, openstat_routes, soniox_routes, ai_analysis_routes

app = FastAPI(title="API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_routes.router)
app.include_router(soniox_routes.router)
app.include_router(openstat_routes.router)
app.include_router(ai_analysis_routes.router)
