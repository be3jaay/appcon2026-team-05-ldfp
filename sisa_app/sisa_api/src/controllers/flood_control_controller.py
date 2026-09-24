from fastapi import HTTPException

from ..models.flood_control import FloodControlFilters, FloodControlProjectsResponse, FloodControlSummary
from ..services import flood_control_service
from ..services.flood_control_service import FloodControlDataError


async def summary(filters: FloodControlFilters) -> FloodControlSummary:
    try:
        return await flood_control_service.get_summary(filters)
    except FloodControlDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


async def projects(filters: FloodControlFilters, limit: int) -> FloodControlProjectsResponse:
    try:
        return await flood_control_service.list_projects(filters, limit=limit)
    except FloodControlDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
