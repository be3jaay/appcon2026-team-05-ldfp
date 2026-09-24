import json
from openai import OpenAI
from ..config import settings
# ai_analysis_service.py

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
                        "You are a factual truth-checker with web browsing capabilities. "
                        "Verify the statement using web search and output your response STRICTLY as a raw JSON object "
                        "with three keys: 'is_true' (boolean), 'reasoning' (string explanation), and 'sources' (a list of exact source URLs/links used). "
                        "Do not include markdown code blocks or any other text outside the JSON."
                    ),
                },
                {"role": "user", "content": statement},
            ],
            # Note: response_format is intentionally removed because it conflicts with web search
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up Markdown code block wrappers if the model includes them anyway
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
            "is_true": result.get("is_true", False),
            "reasoning": result.get("reasoning", "No reasoning provided."),
            "sources": result.get("sources", []),
        }
    except Exception as exc:
        raise AIAnalysisError(f"Failed to analyze statement with OpenAI web search: {exc}") from exc