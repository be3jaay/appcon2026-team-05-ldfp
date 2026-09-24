from pydantic import BaseModel, Field

FLOOD_CONTROL_SOURCE_NAME = "DPWH Flood Control Projects"
FLOOD_CONTROL_PUBLISHER = "Department of Public Works and Highways (data), compiled by BetterGov.ph"
FLOOD_CONTROL_PAGE_URL = "https://github.com/bettergovph/bettergov/tree/main/src/data/flood_control"


class FloodControlProject(BaseModel):
    """One contract record (a project component) as listed in the DPWH flood control map."""

    project_id: str | None
    contract_id: str | None
    description: str | None
    type_of_work: str | None
    region: str | None
    province: str | None
    municipality: str | None
    legislative_district: str | None
    district_engineering_office: str | None
    contractor: str | None
    approved_budget: float | None = Field(None, description="ABC: approved budget for the contract, in pesos.")
    contract_cost: float | None = Field(None, description="Awarded contract cost, in pesos.")
    funding_year: int | None
    start_date: str | None
    completion_date: str | None = Field(None, description="Actual completion date, when listed.")
    latitude: float | None
    longitude: float | None


class FloodControlFilters(BaseModel):
    year: int | None = None
    year_from: int | None = Field(None, description="First funding year of a range (inclusive).")
    year_to: int | None = Field(None, description="Last funding year of a range (inclusive).")
    region: str | None = None
    province: str | None = None
    municipality: str | None = None
    legislative_district: str | None = None
    contractor: str | None = None
    type_of_work: str | None = None


class FloodControlProjectsQuery(FloodControlFilters):
    limit: int = Field(50, ge=1, le=200)


class FloodControlSource(BaseModel):
    name: str = FLOOD_CONTROL_SOURCE_NAME
    publisher: str = FLOOD_CONTROL_PUBLISHER
    source_type: str = "GOVERNMENT_DATASET"
    url: str = FLOOD_CONTROL_PAGE_URL
    data_url: str
    coverage: str = Field(description="Funding years and regions present in the data.")
    records: int


class ContractorTotal(BaseModel):
    contractor: str
    projects: int
    contract_cost: float


class YearTotal(BaseModel):
    year: int
    projects: int
    contract_cost: float


class FloodControlSummary(BaseModel):
    source: FloodControlSource
    filters: FloodControlFilters
    projects: int = Field(description="Number of contract records matching the filters.")
    total_contract_cost: float
    total_approved_budget: float
    by_year: list[YearTotal]
    top_contractors: list[ContractorTotal]


class FloodControlProjectsResponse(BaseModel):
    source: FloodControlSource
    filters: FloodControlFilters
    total: int
    projects: list[FloodControlProject]
