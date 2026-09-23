"""Shared fakes. No test may touch the network or need an API key."""

import json
import re

import pytest

from src.models.claims import TranscriptSegment


class FakeLLM:
    """Returns canned responses in order (the last one repeats) and records every call."""

    def __init__(self, *responses: str | dict | Exception):
        self.responses = list(responses) or ['{"claims": []}']
        self.calls: list[dict] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str:
        self.calls.append({"system": system, "user": user, "schema": response_schema})
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, dict):
            return json.dumps(response)
        return response


# Test-only keyword heuristic standing in for the LLM in end-to-end tests.
# Order matters: the first rule that matches a line wins.
_KEYWORD_RULES: list[tuple[str, str]] = [
    ("sarcasm", r"\b(ang galing naman|wow|very transparent|sobrang linis)\b"),
    ("figurative", r"\b(buwaya|kinain|bundok|mountain of)\b"),
    ("promise", r"\b(ipapangako|pangako|itatayo namin|gagawin namin|i will|we will)\b"),
    ("legal", r"\b(konstitusyon|constitution|article|section|batas|korte)\b"),
    ("vague", r"\b(marami|ilang|some|many|daw)\b"),
    ("fact", r"(\d|milyon|bilyon|coa|dbm|ginastos|naubos)"),
    ("opinion", r"\b(nakakahiya|sa tingin ko|dapat|pangit|magaling|shameful)\b"),
]


class KeywordFakeLLM(FakeLLM):
    """Labels each numbered (non-context) line of the user prompt by keyword."""

    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str:
        self.calls.append({"system": system, "user": user, "schema": response_schema})
        claims = []
        for line in user.splitlines():
            m = re.match(r"\[(\d+)\] Speaker [^:]+: (.*)", line)
            if not m:
                continue  # context lines never produce claims
            number, text = int(m.group(1)), m.group(2)
            for type_, pattern in _KEYWORD_RULES:
                if re.search(pattern, text, re.IGNORECASE):
                    claims.append(
                        {
                            "segment": number,
                            "text": text,
                            "type": type_,
                            "checkworthiness": 0.9 if type_ in ("fact", "legal") else 0.2,
                            "reason": f"keyword match for {type_}",
                            "literal_claim": text if type_ in ("figurative", "sarcasm") else "",
                        }
                    )
                    break
        return json.dumps({"claims": claims})


def seg(segment_id, text: str, speaker: str = "1", start_ms: int | None = None) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id=str(segment_id),
        text=text,
        speaker=speaker,
        start_ms=start_ms if start_ms is not None else int(segment_id) * 1000,
        end_ms=(start_ms if start_ms is not None else int(segment_id) * 1000) + 900,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
