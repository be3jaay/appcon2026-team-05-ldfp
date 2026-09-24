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
uv run python scripts/eval_claim_detection.py     # real LLM chain; skips when no LLM key is set

cd sisa_app/sisa_fe
pnpm dev
pnpm typecheck
```

## Claim detection (`sisa_api/src/services/claims/`)

Browser Soniox hook → finished segment → `WS /api/v1/claims/ws` → `ClaimDetector`: `prefilter` (no LLM) → `SegmentBatcher` (flush on speaker change / 3 segments / 15 s timer / stop) → worker (shared `RateLimiter` at `LLM_RPM`, merges queued batches, retries 429/503) → `ClaimClassifier` (ONE LLM call through the provider chain `clients/llm_chain.py`: Groq → Gemini by default, previous 2 lines sent as CONTEXT only, returns a verbatim `quote` per claim). The frontend highlights quotes via `sisa_fe/components/claims/claim-text.tsx`. Mic and video share this path. See `sisa_api/README.md` for the protocol, config and known gaps.

Rules to keep:
- Never one LLM call per segment or per speaker turn. Tests count calls on a fake client.
- Don't add SDK-level retries: they burn shared quota. Retries go through the detector and limiter; a busy provider falls through to the next one in the chain.
- New providers: if they speak the OpenAI chat format, add a preset to `openai_compat_client.PROVIDERS` and `llm_chain.build_provider`.
- `SYSTEM_PROMPT` stays a constant, identical on every call (prompt caching), and has nothing specific to one video, speaker or politician.
- The LLM client is injected (`LLMClient` protocol). Tests use fakes from `tests/conftest.py` and never hit the network.
- Prefilter: when unsure, keep. Word lists go in `WORD_LISTS` only.
- Scope: detection and in-transcript highlighting only. Verification and persistence are separate work.

## Claim verification

`POST /api/v1/claims/verify` → `services/claim_verification_service.py`: STATISTICAL → `openstat_service` (don't change its behaviour), LEGAL → `official_gazette_service`. The only LLM use in verification is `services/evidence_judge.py` (compares a content claim with the official excerpt it is given). Keep assessments conservative: not found ≠ CONTRADICTED; a found document only SUPPORTS existence/issuance claims.

Official Gazette: HTML pages are Cloudflare-protected for automated clients, so don't try to bypass that. Search goes through the site's RSS feed (`/feed/?s=`). Only return officialgazette.gov.ph URLs and the site's own text; never substitute Wikipedia/news/third-party sources.

## Frontend verdicts

`hooks/use-claim-verification.ts` sends every claim with `check_type` STATISTICAL/LEGAL to `/api/v1/claims/verify`, one request at a time. `lib/verification.ts` maps statuses to the UI: SUPPORTED → Factual, CONTRADICTED → Misleading, INSUFFICIENT_EVIDENCE → No evidence, NEEDS_CONTEXT → Lacks context. Opinion/promise/sarcasm/figurative/vague go under "Other statements".

## Security

- `CORS_ALLOW_ORIGINS` (default `http://localhost:3000`) is the allowlist for CORS, for `/api/soniox/temporary-key` (403 otherwise), and for the claims websocket (closed with 1008 otherwise). Don't go back to `*`.

## Conventions

- Commits: `feat(ai): …`, `test(ai): …`, `feat(api): …`, `feat(fe): …`, `docs: …`; keep them small.
- `pnpm lint` currently crashes (eslint 10 vs eslint-plugin-react); use `pnpm typecheck`.
