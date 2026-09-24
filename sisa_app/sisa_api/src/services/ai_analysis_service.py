import json
from openai import OpenAI
from ..config import settings

class AIAnalysisError(RuntimeError):
    pass

def analyze_statement(statement: str) -> dict:
    if not settings.openai_api_key:
        raise AIAnalysisError("Server is missing OPENAI_API_KEY in configuration.")

    client = OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.chat.completions.create(
            model="gpt-5-search-api",  # Search-enabled model variant
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an advanced cognitive and factual truth-checker with web browsing capabilities. "
                        "Analyze the given statement holistically. Verify claims via web search, and concurrently analyze subtext, rhetoric, and psychology.\n\n"
                        "Respond STRICTLY as a raw JSON object with the following keys:\n"
                        "- 'verdict' (string: MUST be exactly one of: 'factual', 'misleading', 'needscontext', or 'unfounded')\n"
                        "- 'reasoning' (string explanation of why this verdict applies based on search results)\n"
                        "- 'sources' (list of exact source URLs/links used)\n"
                        "- 'evasion_detected' (boolean: true if the speaker is dodging a direct truth, deflecting, or avoiding something)\n"
                        "- 'evasion_details' (string: what they are trying to avoid or deflect from)\n"
                        "- 'emotion' (string: primary underlying emotion/tone like defensive, aggressive, neutral, confident, fearful)\n"
                        "- 'fallacy' (string: name of any logical fallacy present, or 'none')\n"
                        "- 'subtext_or_extrinsic_dialogue' (string: hidden subtext, secondary agendas, or implicit framing cues)\n\n"
                        "Do not include markdown code blocks or any text outside the JSON."
                    ),
                },
                {"role": "user", "content": statement},
            ],
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up Markdown code block wrappers if included
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        result = json.loads(content)
        
        return {
            "statement": statement,
            "verdict": result.get("verdict", "unfounded"),
            "reasoning": result.get("reasoning", "No reasoning provided."),
            "sources": result.get("sources", []),
            "evasion_detected": result.get("evasion_detected", False),
            "evasion_details": result.get("evasion_details", ""),
            "emotion": result.get("emotion", "neutral"),
            "fallacy": result.get("fallacy", "none"),
            "subtext_or_extrinsic_dialogue": result.get("subtext_or_extrinsic_dialogue", ""),
        }
    except Exception as exc:
        raise AIAnalysisError(f"Failed to analyze statement with OpenAI web search: {exc}") from exc