"""Soniox Text-to-Speech REST API: POST /tts, full text in, full audio out.

Docs: https://soniox.com/docs/tts/rest-api/generate-speech

Request: `{"model", "language", "voice", "audio_format", "text"}`, Bearer auth (the same
SONIOX_API_KEY used to mint transcription keys works here directly - no temporary key needed
for a server-to-server call). Response body on success is raw audio bytes; `Content-Type`
reflects the requested `audio_format`.
"""

import httpx

_CONTENT_TYPES: dict[str, str] = {
    "pcm_f32le": "audio/pcm",
    "pcm_s16le": "audio/pcm",
    "pcm_mulaw": "audio/pcm",
    "pcm_alaw": "audio/pcm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "aac": "audio/aac",
    "opus": "audio/opus",
    "flac": "audio/flac",
}


def content_type_for(audio_format: str) -> str:
    return _CONTENT_TYPES.get(audio_format, "application/octet-stream")


class SonioxTTSConfigError(RuntimeError):
    """Missing API key: not worth retrying."""


class SonioxTTSRequestError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def synthesize(
    text: str,
    *,
    api_key: str | None,
    url: str,
    model: str,
    language: str,
    voice: str,
    audio_format: str,
    timeout_seconds: float = 20.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Raw audio bytes for `text`, spoken in `language` by `voice`. Raises on failure;
    callers that want to degrade gracefully (text-only) should catch both error types."""
    if not api_key:
        raise SonioxTTSConfigError("Server is missing SONIOX_API_KEY. Add it to .env (get one from console.soniox.com).")
    if not text.strip():
        raise SonioxTTSRequestError(400, "No text to synthesize.")

    body = {
        "model": model,
        "language": language,
        "voice": voice,
        "audio_format": audio_format,
        "text": text,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
            response = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
    except httpx.TimeoutException as exc:
        raise SonioxTTSRequestError(504, "Soniox TTS did not respond in time.") from exc
    except httpx.RequestError as exc:
        raise SonioxTTSRequestError(502, f"Failed to reach Soniox TTS: {exc}") from exc

    if response.status_code in (401, 403):
        raise SonioxTTSConfigError(f"Soniox TTS rejected the API key ({response.status_code}).")
    if response.status_code >= 400:
        raise SonioxTTSRequestError(response.status_code, response.text[:300])

    return response.content
