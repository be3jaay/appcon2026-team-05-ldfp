import logging
from collections.abc import Callable

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..clients.gemini_client import GeminiClient, GeminiConfigError
from ..config import is_origin_allowed, settings
from ..models.claims import SegmentMessage
from ..services.claims.classifier import ClaimClassifier, LLMClient
from ..services.claims.detector import ClaimDetector

logger = logging.getLogger(__name__)

LLMFactory = Callable[[], LLMClient]


def gemini_factory() -> LLMClient:
    return GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        thinking_level=settings.gemini_thinking_level,
        retry_attempts=settings.gemini_retry_attempts,
    )


def get_llm_factory() -> LLMFactory:
    """FastAPI dependency; tests override it with a fake LLM."""
    return gemini_factory


async def run_session(websocket: WebSocket, llm_factory: LLMFactory) -> None:
    # CORS does not cover websockets, so check Origin here.
    if not is_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="Origin not allowed.")
        return
    await websocket.accept()

    try:
        llm = llm_factory()
    except GeminiConfigError as exc:
        await websocket.send_json({"type": "error", "message": str(exc), "fatal": True})
        await websocket.close(code=1011)
        return

    detector = ClaimDetector(
        ClaimClassifier(llm),
        websocket.send_json,
        max_segments=settings.claims_batch_max_segments,
        max_wait_s=settings.claims_batch_max_wait_s,
        context_size=settings.claims_context_segments,
    )

    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "stop":
                result = await detector.stop()
                await websocket.send_json(
                    {
                        "type": "done",
                        "claims": len(result.claims),
                        "skipped": len(result.skipped),
                        "llm_calls": result.llm_calls,
                    }
                )
                await websocket.close()
                return
            if kind == "segment":
                try:
                    segment = SegmentMessage.model_validate(message).segment
                except ValidationError as exc:
                    await websocket.send_json(
                        {"type": "error", "message": f"Invalid segment: {exc.errors()[0]['msg']}"}
                    )
                    continue
                await detector.add_segment(segment)
                continue
            await websocket.send_json({"type": "error", "message": f"Unknown message type: {kind!r}"})
    except WebSocketDisconnect:
        logger.info("claims websocket closed by client")
        detector.abort()
    except ValueError:  # non-JSON frame
        await websocket.send_json({"type": "error", "message": "Messages must be JSON.", "fatal": True})
        detector.abort()
        await websocket.close(code=1003)
