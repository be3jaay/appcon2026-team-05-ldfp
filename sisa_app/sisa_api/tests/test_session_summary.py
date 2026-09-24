"""Session summary: one LLM call for the Tagalog text, one Soniox TTS call for the audio.
No network, no real API keys - httpx.MockTransport for TTS, FakeLLM for the text call."""

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from src.clients import soniox_tts_client
from src.clients.soniox_tts_client import SonioxTTSConfigError, SonioxTTSRequestError
from src.config import settings
from src.controllers import session_summary_controller
from src.main import app
from src.models.session_summary import SessionSummaryRequest
from src.models.verification import Assessment, VerificationResponse, VerifiedClaim
from src.services import session_summary_service
from src.services.claims.classifier import LLMConfigError

from .conftest import FakeLLM, seg

OK_AUDIO = b"\x00\x01\x02fake-mp3-bytes"


def verified(text: str, status: str, explanation: str = "explained") -> VerificationResponse:
    return VerificationResponse(
        claim=VerifiedClaim(text=text, type="OTHER"),
        assessment=Assessment(status=status, explanation=explanation),
    )


# --- soniox_tts_client -----------------------------------------------------------------


async def test_synthesize_posts_expected_body_and_returns_bytes():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=OK_AUDIO)

    audio = await soniox_tts_client.synthesize(
        "Kumusta, ito ay pagsubok.",
        api_key="test-key",
        url="https://tts-rt.soniox.com/tts",
        model="tts-rt-v2",
        language="tl",
        voice="Adrian",
        audio_format="mp3",
        transport=httpx.MockTransport(handler),
    )
    assert audio == OK_AUDIO
    req = seen[0]
    assert str(req.url) == "https://tts-rt.soniox.com/tts"
    assert req.headers["authorization"] == "Bearer test-key"
    body = json.loads(req.content)
    assert body == {
        "model": "tts-rt-v2",
        "language": "tl",
        "voice": "Adrian",
        "audio_format": "mp3",
        "text": "Kumusta, ito ay pagsubok.",
    }


async def test_synthesize_without_api_key_is_a_config_error():
    with pytest.raises(SonioxTTSConfigError):
        await soniox_tts_client.synthesize(
            "text", api_key=None, url="https://tts-rt.soniox.com/tts", model="m", language="tl", voice="v",
            audio_format="mp3",
        )


async def test_synthesize_rejected_key_is_a_config_error():
    with pytest.raises(SonioxTTSConfigError):
        await soniox_tts_client.synthesize(
            "text", api_key="bad", url="https://tts-rt.soniox.com/tts", model="m", language="tl", voice="v",
            audio_format="mp3", transport=httpx.MockTransport(lambda r: httpx.Response(401)),
        )


async def test_synthesize_server_error_is_a_request_error():
    with pytest.raises(SonioxTTSRequestError) as exc:
        await soniox_tts_client.synthesize(
            "text", api_key="k", url="https://tts-rt.soniox.com/tts", model="m", language="tl", voice="v",
            audio_format="mp3", transport=httpx.MockTransport(lambda r: httpx.Response(503, text="busy")),
        )
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "audio_format, content_type",
    [("mp3", "audio/mpeg"), ("wav", "audio/wav"), ("pcm_s16le", "audio/pcm"), ("unknown", "application/octet-stream")],
)
def test_content_type_for(audio_format, content_type):
    assert soniox_tts_client.content_type_for(audio_format) == content_type


# --- session_summary_service: prompt building ------------------------------------------


def test_build_user_prompt_includes_transcript_claims_and_evidence():
    transcript = [seg(1, "Ang badyet ay ₱125 milyon.", speaker="1")]
    from src.models.claims import Claim

    claims = [
        Claim(
            id="1:0", segment_id="1", speaker="1", text="Ang badyet ay ₱125 milyon.",
            type="fact", checkworthiness=0.9, reason="specific amount", check_type="STATISTICAL",
        )
    ]
    evidence = [verified("Ang badyet ay ₱125 milyon.", "SUPPORTED", "matches the record")]

    prompt = session_summary_service.build_user_prompt(transcript, claims, evidence)
    assert "Speaker 1: Ang badyet ay ₱125 milyon." in prompt
    assert "CLAIMS FOUND (1):" in prompt
    assert "[STATISTICAL]" in prompt
    assert "VERIFICATION RESULTS (1):" in prompt
    assert "SUPPORTED: matches the record" in prompt


def test_build_user_prompt_handles_empty_inputs():
    prompt = session_summary_service.build_user_prompt([], [], [])
    assert "walang transcript na natanggap" in prompt
    assert "walang na-detect na claim" in prompt
    assert "walang natanggap na verification result" in prompt


def test_parse_summary_reads_fenced_and_plain_json():
    assert session_summary_service.parse_summary('{"summary_tl": "Buod dito."}') == "Buod dito."
    assert session_summary_service.parse_summary('```json\n{"summary_tl": "Buod."}\n```') == "Buod."
    assert session_summary_service.parse_summary("not json at all") is None
    assert session_summary_service.parse_summary('{"summary_tl": ""}') is None


# --- session_summary_service.generate ---------------------------------------------------


async def test_generate_returns_text_and_audio(monkeypatch):
    async def fake_synthesize(text, **kwargs):
        assert text == "Ito ang buod ng sesyon."
        return OK_AUDIO

    monkeypatch.setattr(session_summary_service.soniox_tts_client, "synthesize", fake_synthesize)

    llm = FakeLLM('{"summary_tl": "Ito ang buod ng sesyon."}')
    req = SessionSummaryRequest(transcript=[], claims=[], evidence=[verified("x", "SUPPORTED")])
    result = await session_summary_service.generate(req, llm)

    assert llm.call_count == 1
    assert result.summary_text == "Ito ang buod ng sesyon."
    assert result.language == "tl"
    assert result.audio_error is None
    assert base64.b64decode(result.audio_base64) == OK_AUDIO
    assert result.audio_content_type == "audio/mpeg"


async def test_generate_degrades_gracefully_when_tts_fails(monkeypatch):
    async def failing_synthesize(text, **kwargs):
        raise SonioxTTSRequestError(503, "busy")

    monkeypatch.setattr(session_summary_service.soniox_tts_client, "synthesize", failing_synthesize)

    llm = FakeLLM('{"summary_tl": "Buod ng sesyon."}')
    req = SessionSummaryRequest()
    result = await session_summary_service.generate(req, llm)

    assert result.summary_text == "Buod ng sesyon."
    assert result.audio_base64 is None
    assert "busy" in result.audio_error


async def test_generate_degrades_gracefully_without_soniox_key(monkeypatch):
    monkeypatch.setattr(settings, "soniox_api_key", None)
    llm = FakeLLM('{"summary_tl": "Buod ng sesyon."}')
    result = await session_summary_service.generate(SessionSummaryRequest(), llm)
    assert result.summary_text == "Buod ng sesyon."
    assert result.audio_base64 is None
    assert result.audio_error is not None


async def test_generate_raises_when_llm_output_is_unusable():
    llm = FakeLLM("not json")
    with pytest.raises(session_summary_service.SessionSummaryError):
        await session_summary_service.generate(SessionSummaryRequest(), llm)


async def test_generate_raises_when_llm_call_fails():
    from src.services.claims.classifier import RetryableLLMError

    llm = FakeLLM(RetryableLLMError("busy", 2.0))
    with pytest.raises(session_summary_service.SessionSummaryError):
        await session_summary_service.generate(SessionSummaryRequest(), llm)


# --- route ------------------------------------------------------------------------------


def test_route_returns_summary(monkeypatch):
    llm = FakeLLM('{"summary_tl": "Buod sa Tagalog."}')
    monkeypatch.setattr(session_summary_controller, "build_llm_client", lambda: llm)

    async def fake_synthesize(text, **kwargs):
        return OK_AUDIO

    monkeypatch.setattr(session_summary_service.soniox_tts_client, "synthesize", fake_synthesize)

    client = TestClient(app)
    res = client.post("/api/v1/session-summary", json={"transcript": [], "claims": [], "evidence": []})
    assert res.status_code == 200
    body = res.json()
    assert body["summary_text"] == "Buod sa Tagalog."
    assert body["language"] == "tl"
    assert base64.b64decode(body["audio_base64"]) == OK_AUDIO


def test_route_500s_when_no_llm_provider_configured(monkeypatch):
    def raise_config_error():
        raise LLMConfigError("No LLM provider configured.")

    monkeypatch.setattr(session_summary_controller, "build_llm_client", raise_config_error)

    client = TestClient(app)
    res = client.post("/api/v1/session-summary", json={})
    assert res.status_code == 500
