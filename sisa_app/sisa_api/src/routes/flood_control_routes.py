from typing import Annotated

from fastapi import APIRouter, Query

from ..controllers import flood_control_controller
from ..models.flood_control import (
    FloodControlFilters,
    FloodControlProjectsQuery,
    FloodControlProjectsResponse,
    FloodControlSummary,
)

router = APIRouter(prefix="/api/v1/flood-control", tags=["flood-control"])


@router.get("/summary", response_model=FloodControlSummary)
async def summary(filters: Annotated[FloodControlFilters, Query()]) -> FloodControlSummary:
    """Totals for DPWH flood control projects matching the filters (all optional)."""
    return await flood_control_controller.summary(filters)


@router.get("/projects", response_model=FloodControlProjectsResponse)
async def projects(query: Annotated[FloodControlProjectsQuery, Query()]) -> FloodControlProjectsResponse:
    """Matching project records, largest contract cost first."""
    filters = FloodControlFilters(**query.model_dump(exclude={"limit"}))
    return await flood_control_controller.projects(filters, query.limit)
