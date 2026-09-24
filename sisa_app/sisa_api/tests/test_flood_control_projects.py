"""Single-project flood control claims and detail recovery from the transcript line, offline.

Records are modelled on real DPWH rows (a Sunwest road dike in Naujan, Oriental Mindoro).
"""

import pytest

from src.models.claims import ClaimEntities
from src.models.flood_control import FloodControlProject
from src.models.verification import VerifyClaimRequest
from src.services import claim_verification_service as verification
from src.services import flood_control_service as svc


def project(**kw):
    base = dict(
        project_id=None, contract_id=None, description=None, type_of_work="Construction of Dike", region="Region IV-B",
        province="ORIENTAL MINDORO", municipality="NAUJAN (ORIENTAL MINDORO)", legislative_district=None,
        district_engineering_office=None, contractor="SUNWEST, INC.", approved_budget=None, contract_cost=None,
        funding_year=2023, start_date=None, completion_date=None, latitude=None, longitude=None,
    )
    base.update(kw)
    return FloodControlProject(**base)


PROJECTS = [
    project(contract_id="23E00156", description="Construction of Road Dike/Esplanade along Dulangan River, Naujan",
            contract_cost=289_497_858.2, approved_budget=289_500_000),
    project(contract_id="23E00200", description="Construction of Road Dike along Mag-asawang Tubig River, Naujan",
            contract_cost=221_948_493.4),
    project(contract_id="24E00118", description="Construction of River Control Structure, Tablas Island, Romblon",
            province="ROMBLON", municipality="SAN ANDRES (ROMBLON)", contractor="YPR GEN. CONTRACTOR",
            type_of_work="Construction of Flood Mitigation Structure", contract_cost=289_490_000.0, funding_year=2024),
    project(contract_id="22X00001", description="Construction of Revetment, Bulacan", province="BULACAN",
            municipality="MALOLOS (BULACAN)", contractor="ORIENTAL PEAK BUILDERS", contract_cost=50_000_000.0),
]

SEGMENT = (
    "Secretary Dizon told the Sandiganbayan that the substandard project in Awan Oriental Mindoro cannot "
    "simply be repaired... it supposedly cost $289 million. The road dike was built by the Sunwest Corporation."
)


@pytest.fixture(autouse=True)
def data(monkeypatch):
    async def load():
        return PROJECTS

    monkeypatch.setattr(svc, "load_projects", load)


def stat(claim, context=None, **entities):
    return VerifyClaimRequest(claim=claim, claim_type="STATISTICAL", entities=ClaimEntities(**entities), context=context)


def test_contractor_keywords_skip_place_words():
    keys = svc.contractor_keywords(PROJECTS)
    assert "sunwest" in keys
    assert "oriental" not in keys  # "ORIENTAL PEAK BUILDERS" must not match the province


def test_places_and_contractors_in_text():
    assert svc.places_in_text(SEGMENT, PROJECTS) == "ORIENTAL MINDORO"
    assert svc.contractor_in_text(SEGMENT, PROJECTS) == "sunwest"
    assert svc.contractor_in_text("nothing relevant here", PROJECTS) is None


async def test_single_project_cost_matches_a_record():
    res = await verification.verify(
        stat("The Sunwest road dike in Oriental Mindoro cost ₱289 million.", metric="project cost",
             value=289e6, unit="pesos", geography="Oriental Mindoro", contractor="Sunwest")
    )
    assert res.assessment.status == "SUPPORTED"
    assert "Dulangan River" in res.assessment.explanation
    assert res.evidence[0].data.value == 289_497_858.2
    assert "23E00156" in res.evidence[0].data.relevant_text


async def test_details_missing_from_the_claim_are_recovered_from_the_line():
    # What the detector actually produced: no place, no contractor, "$", Tagalog text.
    res = await verification.verify(
        stat("ang proyekto ay nagkakahalaga ng $289 milyon", context=SEGMENT,
             metric="project cost", value=289.0, unit="million dollars")
    )
    assert res.assessment.status == "SUPPORTED"
    assert "'sunwest' in ORIENTAL MINDORO" in res.assessment.explanation
    assert "compared in pesos" in res.assessment.explanation  # the $ is flagged, not silently converted


async def test_without_scope_a_matching_cost_only_needs_context():
    res = await verification.verify(
        stat("The road dike project cost ₱289 million.", metric="project cost", value=289e6, unit="pesos",
             geography="Philippines")
    )
    assert res.assessment.status == "NEEDS_CONTEXT"
    assert "can't be confirmed as the same project" in res.assessment.explanation
    assert "Road Dike" in res.evidence[0].source.title  # "road dike" narrowed the candidates


async def test_no_matching_project_is_insufficient_not_contradicted():
    res = await verification.verify(
        stat("The Sunwest dike in Oriental Mindoro cost ₱500 million.", metric="project cost", value=500e6,
             unit="pesos", geography="Oriental Mindoro", contractor="Sunwest")
    )
    assert res.assessment.status == "INSUFFICIENT_EVIDENCE"
    assert "closest is ₱289.50M" in res.assessment.explanation


async def test_totals_still_use_the_aggregate_comparison():
    total = sum(p.contract_cost for p in PROJECTS if p.province == "ORIENTAL MINDORO")
    res = await verification.verify(
        stat("Total flood control spending in Oriental Mindoro", metric="flood control spending",
             value=total * 3, unit="pesos", geography="Oriental Mindoro")
    )
    assert res.assessment.status == "CONTRADICTED"


async def test_flood_words_in_the_line_route_to_flood_data():
    res = await verification.verify(
        stat("The project cost ₱289 million.", context=SEGMENT, metric="project cost", value=289e6, unit="pesos")
    )
    assert res.assessment.method == "OFFICIAL_DATA"  # not "no data source for 'project cost'"


def test_speech_to_text_spellings_are_recovered():
    line = "The road dyke was built by the Sun West Corporation in Oriental Mindoro."
    assert svc.contractor_in_text(line, PROJECTS) == "sunwest"


async def test_dyke_spelling_routes_to_flood_data():
    res = await verification.verify(
        stat("The road dyke cost 289 million pesos.",
             context="The road dyke in Oriental Mindoro was built by the Sun West Corporation.",
             metric="demolition cost", value=289e6, unit="pesos")
    )
    assert res.assessment.status == "SUPPORTED"
    assert "Dulangan River" in res.assessment.explanation


async def test_non_money_non_count_figures_are_not_compared_with_records():
    # "9 meters shorter" must never be compared with a count of project records.
    res = await verification.verify(
        stat("The sheet piles were 9 meters shorter than required.", context=SEGMENT,
             metric="sheet pile length shortfall", value=9, unit="meters")
    )
    assert res.assessment.status == "NO_SOURCE"
    assert res.assessment.method == "NONE"


def test_shared_first_words_are_not_contractor_keywords():
    many = PROJECTS + [
        project(contractor="PHILIPPINE BRIDGE CORP"),
        project(contractor="GOLDSTAR PHILIPPINES"),
        project(contractor="ACME ONE BUILDERS"), project(contractor="ACME TWO BUILDERS"),
        project(contractor="ACME THREE BUILDERS"),
    ]
    keys = svc.contractor_keywords(many)
    assert "philippine" not in keys  # generic word
    assert "acme" not in keys  # shared by 3 different firms
    assert "sunwest" in keys and "goldstar" in keys
    assert svc.contractor_in_text("Philippine Public Works Chief testifies", many) is None
