# SISA

Live claim detection for Philippine public speech. SISA transcribes Taglish speech as it happens, highlights the claims worth checking, checks them against primary sources, and leaves the final call to human reviewers (journalists, civic groups).

Monorepo with a FastAPI backend (`sisa_api/`) and a Next.js frontend (`sisa_fe/`).

## Features

1. **Real-time audio streaming.** The browser captures audio from a video file, a YouTube tab or the microphone and streams it straight to Soniox. The backend only issues short-lived Soniox keys to allowed origins, and receives each finished transcript line over a WebSocket.
2. **Taglish speech-to-text.** Soniox real-time model (`stt-rt-v5`) with Tagalog and English language hints, speaker labels and timestamps on every line. Lines end automatically when a speaker pauses.
3. **Claim detection and verification.** An LLM (Groq `gpt-oss-120b`, with Gemini as fallback) labels statements in batches: fact, legal, promise, opinion, vague, sarcasm or figurative. It also flags evasive answers, fallacies, and claims that conflict with something said earlier. Checkable claims are verified against DPWH flood-control records (compiled by BetterGov.ph), PSA OpenSTAT and the Official Gazette. Anything those can't settle goes to Google Fact Check, then to an AI web search that rates each source's reliability.
4. **Reactive workspace.** A Next.js dashboard with a live transcript (highlighted claims, timestamps that jump the video to that moment, search), verdict cards with evidence links, alerts over the video, reviewer Confirm / Dispute / Dismiss with notes, Markdown and JSON export, and a spoken Tagalog summary at the end of the session (Soniox text-to-speech).

## Run with Docker Compose (recommended)

```bash
docker compose up --build
```

- API: http://localhost:8000 (health check at `/health`)
- Web: http://localhost:3000

Stop everything with:

```bash
docker compose down
```

## Run locally without Docker

### API

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
cd sisa_api
uv sync
uv run fastapi dev src/main.py
```

Runs at http://localhost:8000. Interactive docs at `/docs`, health check at `/health`.

### Web

Requires Node 22 and pnpm.

```bash
cd sisa_fe
pnpm install
pnpm dev
```

Runs at http://localhost:3000.

## Frontend (`sisa_fe`)

Next.js (App Router), Tailwind CSS v4, Base UI, lucide icons, pnpm.

**How it works:** the browser gets a temporary key from the API, streams audio to Soniox, and turns Soniox tokens into transcript lines (speaker, text, start time). Each finished line is sent to the API's claims WebSocket; detected claims come back and are highlighted in the transcript. Every fact or legal claim is then sent to `/api/v1/claims/verify`, one at a time, and its verdict is shown on the claim.

**Layout:** three blocks.
- Left: the media panel (video file, YouTube or microphone, with claim alerts over the video) and the Claims panel (tabs **Now** / **Checked** / **Other**, reviewer actions, export).
- Right: the live transcript (search, clickable highlights and timestamps).
- Header: trusted data sources and their live status.

**Verdicts shown:** Factual, Misleading, Lacks context, Unverified (checked, no evidence found), Not checked (no source covers it yet). Opinions, promises, sarcasm, figures of speech and vague statements go under **Other**.

**Where things are:**

| Path | What |
|---|---|
| `hooks/use-soniox-transcription.ts` | Soniox streaming, transcript lines, language hints |
| `hooks/use-claim-detection.ts` | Claims WebSocket and the `Claim` type |
| `hooks/use-claim-verification.ts` | Sends claims to `/api/v1/claims/verify` |
| `hooks/use-claim-review.ts`, `lib/export.ts` | Reviewer decisions and notes; Markdown/JSON export |
| `hooks/use-claim-alerts.ts` | Alerts shown over the video |
| `lib/verification.ts` | Maps API statuses to verdict labels |
| `components/workspace/` | Page layout: header, media, claims panel, transcript, sources |
| `components/claims/` | Claim highlights, verdict and rhetoric badges |

**Environment:** `NEXT_PUBLIC_API_URL`, the API base URL (default `http://localhost:8000`). In production it must be `https://…`, because the site is served over HTTPS and browsers block plain `http`/`ws` calls from it.

```bash
pnpm dev         # http://localhost:3000
pnpm typecheck   # use this; `pnpm lint` currently crashes (eslint 10 vs eslint-plugin-react)
```

## API (`sisa_api`)

FastAPI on Python 3.14, managed with uv. Layers: `routes/` → `controllers/` (HTTP errors) → `services/` (logic), with `models/` (pydantic) and `clients/` (external APIs). Full details, protocol and every setting: [`sisa_api/README.md`](sisa_api/README.md).

**Endpoints:**

| Method | Path | What |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/soniox/temporary-key` | Short-lived Soniox key for the browser (allowed origins only) |
| WS | `/api/v1/claims/ws` | Send finished transcript lines, receive detected claims |
| POST | `/api/v1/claims/verify` | Verify one claim: verdict, explanation, evidence |
| POST | `/api/v1/session-summary` | End-of-session Tagalog summary with audio |
| GET | `/api/v1/sources/status` | Which keyed sources (fact-checks, LLM, web search) are connected |
| POST | `/api/v1/fact-checks/search` | Search published fact-checks |
| GET | `/api/v1/flood-control/summary`, `/api/v1/flood-control/projects` | DPWH flood-control records |
| POST | `/api/v1/official-gazette/search`, `/api/v1/official-gazette/document` | Official Gazette search and documents |
| POST | `/api/v1/openstat/check` | PSA OpenSTAT check |

**Claim detection:** each finished line goes through a no-LLM prefilter (drops greetings and very short lines), then a batcher (flushes on speaker change, 3 lines, or 15 seconds). A worker sends ONE LLM call per batch through the provider chain, with the previous lines as context and the session's earlier claims so conflicts can be flagged. Calls are paced by a shared rate limiter, and a busy provider falls through to the next one.

**Claim verification, in order:**
1. **Our data:** flood-control figures → DPWH records (BetterGov.ph); other statistics → PSA OpenSTAT (unemployment rate); laws and issuances → Official Gazette (through its RSS search, never third-party copies).
2. **Published fact-checks:** Google Fact Check Tools. Only a fact-check of the same claim with a clear rating can set the verdict.
3. **AI web search:** OpenAI search model, then Groq browser search. Only pages the search really returned count; each source is labelled by reliability, and weak-only sources can't settle a claim.

Results stay conservative: "not found" is never reported as false.

```bash
uv run fastapi dev src/main.py                          # http://localhost:8000, docs at /docs
uv run pytest -q                                        # no API keys or network needed
uv run python scripts/run_transcript.py ../transcribe.md   # end-to-end run with real APIs
```

## Configuration

The API reads `sisa_api/.env` (Docker Compose loads it too). The main keys:

| Variable | Needed for |
|---|---|
| `SONIOX_API_KEY` | Transcription and the Tagalog summary audio (required) |
| `GROQ_API_KEY` | Claim detection (first in the LLM chain) and the free web-search fallback |
| `GEMINI_API_KEY` | Claim detection fallback |
| `LLM_PROVIDERS` | Order of the LLM chain, e.g. `gemini,groq`. Empty = every provider with a key |
| `FACTCHECK_API_KEY` | Google Fact Check Tools |
| `OPENAI_API_KEY` | AI web search (needs prepaid credits) |
| `CORS_ALLOW_ORIGINS` | Allowed browser origins, comma-separated. Default `http://localhost:3000,https://sisa-app-ten.vercel.app` |

Free tiers run out fast: one full test run of `transcribe.md` uses about 85k of Groq's 200k free tokens per day. See `sisa_api/README.md` for every setting.

## Project structure

```
sisa_api/            FastAPI backend (routes, controllers, services, models, clients, tests, scripts)
sisa_fe/             Next.js frontend (app, components, hooks, lib, constants)
docker-compose.yml   runs both services together
transcribe.md        sample Taglish news transcript for end-to-end tests
```
