import json

import pytest

from src.services.claims.classifier import (
    SYSTEM_PROMPT,
    ClaimClassifier,
    ClassifierError,
    build_user_prompt,
    parse_claims,
)

from .conftest import FakeLLM, seg

BATCH = [
    seg(10, "Ang ₱125 milyon ay naubos sa loob ng 11 araw.", speaker="2", start_ms=61_000),
    seg(11, "Nakakahiya, ₱50 million ang ginastos sa isang araw.", speaker="2", start_ms=65_500),
]
CONTEXT = [
    seg(8, "Sabi ng COA, may disallowance na ₱73 milyon.", speaker="1"),
    seg(9, "Ano ang masasabi ninyo diyan?", speaker="1"),
]


def item(segment=1, text="claim", type_="fact", **kw):
    return {
        "segment": segment,
        "text": text,
        "type": type_,
        "checkworthiness": kw.pop("checkworthiness", 0.9),
        "reason": kw.pop("reason", "specific amount"),
        **kw,
    }


async def test_parses_valid_output_and_maps_back_to_segment():
    llm = FakeLLM({"claims": [item(1, "₱125M naubos sa 11 araw", "fact"), item(2, "₱50M ginastos sa isang araw")]})
    claims = await ClaimClassifier(llm).classify(BATCH, CONTEXT)

    assert [c.segment_id for c in claims] == ["10", "11"]
    assert [c.timestamp for c in claims] == [61_000, 65_500]
    assert {c.speaker for c in claims} == {"2"}
    assert claims[0].type == "fact"
    assert claims[0].checkworthiness == 0.9
    assert claims[0].id == "10:0"


async def test_mixed_sentence_splits_into_two_claims():
    llm = FakeLLM(
        {
            "claims": [
                item(2, "Nakakahiya ito.", "opinion", checkworthiness=0.1, reason="value judgment"),
                item(2, "₱50 million ang ginastos sa isang araw.", "fact"),
            ]
        }
    )
    claims = await ClaimClassifier(llm).classify(BATCH, CONTEXT)
    assert [(c.segment_id, c.type) for c in claims] == [("11", "opinion"), ("11", "fact")]
    assert [c.id for c in claims] == ["11:0", "11:1"]


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        '{"claims": [ {"segment": 1, "text": ',  # truncated
        "",
        "null",
        '{"claims": "nope"}',
        '{"something_else": []}',
        "[1, 2, 3]",
    ],
)
async def test_malformed_output_returns_no_claims(raw):
    assert await ClaimClassifier(FakeLLM(raw)).classify(BATCH) == []


def test_json_inside_code_fence_or_prose_is_recovered():
    fenced = '```json\n{"claims": [{"segment": 1, "text": "x", "type": "fact", "checkworthiness": 1, "reason": "r"}]}\n```'
    prose = 'Here you go: {"claims": [{"segment": 1, "text": "x", "type": "fact"}]} Hope it helps.'
    assert len(parse_claims(fenced, BATCH)) == 1
    assert len(parse_claims(prose, BATCH)) == 1


def test_missing_fields():
    raw = {
        "claims": [
            {"segment": 1},  # no text -> dropped
            {"text": "no segment"},  # no segment -> dropped
            {"segment": 1, "text": "   "},  # blank text -> dropped
            {"segment": 2, "text": "only required fields"},  # kept with defaults
            "a bare string",  # not an object -> dropped
        ]
    }
    claims = parse_claims(json.dumps(raw), BATCH)
    assert len(claims) == 1
    c = claims[0]
    assert c.segment_id == "11"
    assert c.type == "vague"  # missing type -> vague
    assert 0 <= c.checkworthiness <= 1
    assert c.reason  # default reason filled in


def test_unknown_type_becomes_vague_and_values_are_clamped():
    raw = json.dumps(
        {
            "claims": [
                item(1, "a", "statistic", checkworthiness=7),
                item(1, "b", "FACT", checkworthiness=-2),
                item(1, "c", "fact", checkworthiness="high"),
            ]
        }
    )
    claims = parse_claims(raw, BATCH)
    assert [c.type for c in claims] == ["vague", "fact", "fact"]
    assert [c.checkworthiness for c in claims] == [1.0, 0.0, 0.5]


def test_segment_index_out_of_range_is_dropped():
    raw = json.dumps({"claims": [item(0), item(3), item(-1), item(99), item(2)]})
    claims = parse_claims(raw, BATCH)
    assert [c.segment_id for c in claims] == ["11"]


def test_empty_claims_list():
    assert parse_claims('{"claims": []}', BATCH) == []


async def test_never_returns_claims_for_context_lines():
    llm = FakeLLM(
        {
            "claims": [
                item("C1", "Sabi ng COA may ₱73M disallowance"),
                item("[C2]", "question"),
                item("c1", "x"),
                item("[1]", "real claim"),
            ]
        }
    )
    claims = await ClaimClassifier(llm).classify(BATCH, CONTEXT)
    assert [c.segment_id for c in claims] == ["10"]
    context_ids = {s.segment_id for s in CONTEXT}
    assert not context_ids & {c.segment_id for c in claims}


def test_context_is_marked_and_numbered_separately():
    prompt = build_user_prompt(BATCH, CONTEXT)
    lines = prompt.splitlines()
    assert lines[0].startswith("[C1] (CONTEXT only")
    assert lines[1].startswith("[C2] (CONTEXT only")
    assert lines[2].startswith("[1] Speaker 2: Ang ₱125 milyon")
    assert lines[3].startswith("[2] Speaker 2:")


def test_literal_claim_only_kept_for_figurative_and_sarcasm():
    raw = json.dumps(
        {
            "claims": [
                item(1, "kinain ng buwaya ang pondo", "figurative", literal_claim="Nawala ang ₱125M na pondo."),
                item(1, "x", "fact", literal_claim="should be cleared"),
                item(1, "y", "sarcasm", literal_claim=""),
            ]
        }
    )
    claims = parse_claims(raw, BATCH)
    assert claims[0].literal_claim == "Nawala ang ₱125M na pondo."
    assert claims[1].literal_claim is None
    assert claims[2].literal_claim is None


async def test_exactly_one_llm_call_per_batch():
    llm = FakeLLM({"claims": [item(1), item(2)]})
    classifier = ClaimClassifier(llm)
    await classifier.classify(BATCH, CONTEXT)
    assert llm.call_count == 1
    await classifier.classify(BATCH[:1])
    assert llm.call_count == 2
    assert classifier.calls == 2


async def test_empty_batch_makes_no_call():
    llm = FakeLLM()
    assert await ClaimClassifier(llm).classify([], CONTEXT) == []
    assert llm.call_count == 0


async def test_system_prompt_identical_across_calls():
    llm = FakeLLM()
    classifier = ClaimClassifier(llm)
    await classifier.classify(BATCH, CONTEXT)
    await classifier.classify([seg(50, "Totally different content from another stream", speaker="7")])
    systems = {c["system"] for c in llm.calls}
    assert systems == {SYSTEM_PROMPT}
    assert llm.calls[0]["user"] != llm.calls[1]["user"]


def test_system_prompt_is_generic():
    # Nothing specific to one video, speaker or politician may leak into the prompt.
    lowered = SYSTEM_PROMPT.lower()
    for word in ("duterte", "marcos", "robredo", "sara", "bong", "video id", "youtube"):
        assert word not in lowered


async def test_llm_error_raises_classifier_error():
    with pytest.raises(ClassifierError):
        await ClaimClassifier(FakeLLM(TimeoutError("slow"))).classify(BATCH)


def test_quote_kept_only_when_verbatim_in_segment():
    raw = json.dumps(
        {
            "claims": [
                item(1, "a", quote="₱125 milyon ay naubos"),  # verbatim
                item(1, "b", quote="  ANG ₱125   MILYON  "),  # case/space differences are fine
                item(1, "c", quote="₱125 million was spent"),  # paraphrase -> dropped
                item(1, "d"),  # no quote
            ]
        }
    )
    claims = parse_claims(raw, BATCH)
    assert [c.quote for c in claims] == ["₱125 milyon ay naubos", "ANG ₱125   MILYON", None, None]
    assert len(claims) == 4  # a bad quote never drops the claim itself


def test_schema_and_prompt_ask_for_quote():
    from src.services.claims.classifier import RESPONSE_SCHEMA

    assert "quote" in RESPONSE_SCHEMA["properties"]["claims"]["items"]["required"]
    assert '"quote"' in SYSTEM_PROMPT


def test_check_type_and_entities_are_parsed():
    raw = json.dumps(
        {
            "claims": [
                item(
                    1,
                    "Unemployment was 5% in July 2026",
                    "fact",
                    check_type="statistical",
                    entities={"metric": "unemployment rate", "value": "5%", "unit": "percent", "date": "July 2026", "document_type": ""},
                ),
                item(
                    2,
                    "EO 124 was issued",
                    "legal",
                    check_type="LEGAL",
                    entities={"document_type": "Executive Order", "document_number": 124},
                ),
            ]
        }
    )
    stat, law = parse_claims(raw, BATCH)
    assert stat.check_type == "STATISTICAL"
    assert stat.entities.model_dump(exclude_none=True) == {
        "metric": "unemployment rate", "value": 5.0, "unit": "percent", "date": "July 2026"
    }
    assert law.check_type == "LEGAL"
    assert (law.entities.document_type, law.entities.document_number) == ("Executive Order", "124")


def test_check_type_defaults_and_is_not_routed_for_opinions():
    raw = json.dumps(
        {
            "claims": [
                item(1, "a", "fact"),  # missing check_type/entities
                item(1, "b", "fact", check_type="ASTROLOGY", entities="not a dict"),
                item(1, "c", "opinion", check_type="LEGAL", entities={"document_type": "Executive Order"}),
                item(1, "d", "fact", check_type="LEGAL", entities={"metric": "", "unit": "  "}),
            ]
        }
    )
    claims = parse_claims(raw, BATCH)
    assert [c.check_type for c in claims] == ["OTHER", "OTHER", "OTHER", "LEGAL"]
    assert [c.entities for c in claims] == [None, None, None, None]  # all-empty entities -> None


def test_schema_and_prompt_ask_for_check_type():
    from src.services.claims.classifier import RESPONSE_SCHEMA

    props = RESPONSE_SCHEMA["properties"]["claims"]["items"]["properties"]
    assert props["check_type"]["enum"] == ["STATISTICAL", "LEGAL", "OTHER"]
    assert {"metric", "value", "document_type", "document_number"} <= set(props["entities"]["properties"])
    assert '"check_type"' in SYSTEM_PROMPT and '"entities"' in SYSTEM_PROMPT


def test_text_en_is_parsed():
    raw = json.dumps({"claims": [item(1, "Naubos ang pondo", text_en="The funds ran out")]})
    assert parse_claims(raw, BATCH)[0].text_en == "The funds ran out"
    assert parse_claims(json.dumps({"claims": [item(1, "x")]}), BATCH)[0].text_en is None
