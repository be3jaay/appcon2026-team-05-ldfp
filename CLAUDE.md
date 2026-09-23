# CLAUDE.md

Everything lives under `sisa_app/`:
- `sisa_api/`: FastAPI, Python 3.14, uv. Layers: `routes/` → `controllers/` (HTTP errors) → `services/` (logic) with `models/` (pydantic) and `clients/` (external APIs).
- `sisa_fe/`: Next.js, pnpm. Hooks in `hooks/`, shared helpers in `lib/`.
- `docker-compose.yml` runs both. The api container reads `sisa_api/.env`.

## Commands

```bash
cd sisa_app/sisa_api
uv sync
uv run fastapi dev src/main.py
uv run pytest -q                                  # must pass with no API keys and no network
uv run python scripts/eval_claim_detection.py     # real Gemini; skips when GEMINI_API_KEY is unset

cd sisa_app/sisa_fe
pnpm dev
pnpm typecheck
```

## Claim detection (`sisa_api/src/services/claims/`)

Browser Soniox hook → finished segment → `WS /api/v1/claims/ws` → `ClaimDetector`: `prefilter` (no LLM) → `SegmentBatcher` (flush on speaker change / 3 segments / 15 s timer / stop) → `ClaimClassifier` (ONE Gemini call per batch, previous 2 lines sent as CONTEXT only). Mic and video share this path. See `sisa_api/README.md` for the protocol, config and known gaps.

Rules to keep:
- Never one LLM call per segment. Tests count calls on a fake client.
- `SYSTEM_PROMPT` stays a constant, identical on every call (prompt caching), and has nothing specific to one video, speaker or politician.
- The LLM client is injected (`LLMClient` protocol). Tests use fakes from `tests/conftest.py` and never hit the network.
- Prefilter: when unsure, keep. Word lists go in `WORD_LISTS` only.
- Scope: detection only. Verification, persistence and UI for claims are separate work.

## Security

- `CORS_ALLOW_ORIGINS` (default `http://localhost:3000`) is the allowlist for CORS, for `/api/soniox/temporary-key` (403 otherwise), and for the claims websocket (closed with 1008 otherwise). Don't go back to `*`.

## Conventions

- Commits: `feat(ai): …`, `test(ai): …`, `feat(api): …`, `feat(fe): …`, `docs: …`; keep them small.
- `pnpm lint` currently crashes (eslint 10 vs eslint-plugin-react); use `pnpm typecheck`.
