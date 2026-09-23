# sisa_api

FastAPI backend: Soniox temporary keys, PSA OpenSTAT claim checks, and live **claim detection**.

```bash
uv sync
uv run fastapi dev src/main.py   # http://localhost:8000, docs at /docs
uv run pytest -q                 # no API keys or network needed
```

## Environment (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `SONIOX_API_KEY` | none | Mints temporary Soniox keys for the browser |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated browser origins allowed to call the API and open websockets |
| `GEMINI_API_KEY` | none | Claim classifier. Without it, the claims websocket sends a fatal error and closes |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Gemini model id |
| `GEMINI_THINKING_LEVEL` | `low` | `minimal`/`low`/`medium`/`high`; empty = model default |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `GEMINI_RPM` | `5` | Max claim LLM calls per minute, shared by all sessions (free tier: 5; `0` = no limit) |
| `CLAIMS_LLM_MAX_ATTEMPTS` | `4` | Attempts per call on 429/5xx. Uses Gemini's `retryDelay`, or 5 s/10 s/20 s backoff on overload |
| `CLAIMS_MAX_SEGMENTS_PER_CALL` | `8` | Batches that queue while waiting for a call slot are merged into one call, up to this size |
| `LOG_LEVEL` | `INFO` | Backend log level (`DEBUG` for more) |
| `CLAIMS_BATCH_MAX_SEGMENTS` | `3` | Flush a batch at this many kept segments |
| `CLAIMS_BATCH_MAX_WAIT_S` | `15` | Flush a batch this long after its first segment |
| `CLAIMS_CONTEXT_SEGMENTS` | `2` | Previous final segments sent as CONTEXT-only lines |

## Claim detection

Decides which finished transcript sentences contain claims and labels each one:
`fact | legal | opinion | promise | sarcasm | figurative | vague`. It does **not** verify claims or store them.

### Flow

```
browser (mic or video)                     sisa_api
──────────────────────                     ────────────────────────────────────────────────
Soniox WS ─ final tokens ─┐
                          │ segment closes on <end> / speaker change / stop
useSonioxTranscription ───┴─► WS /api/v1/claims/ws ─► ClaimDetector (one per connection)
                                                      1. prefilter   (pure Python, no LLM)
                                                         drop → {"type":"skipped", reason}
                                                      2. SegmentBatcher
                                                         flush on speaker change | 3 segments
                                                         | 15 s timer | stop
                                                      3. worker: waits for a shared rate-limit slot
                                                         (GEMINI_RPM), merges queued batches
                                              ◄────── {"type":"checking", segment_ids}
                                                      4. ClaimClassifier: ONE Gemini call
                                                         + previous 2 lines as CONTEXT only
                                                         retries 429/503 with the provider's delay
                                              ◄────── {"type":"claims", claims:[...]}
```

Mic and video both go through the same hook (`sisa_fe/hooks/use-soniox-transcription.ts`), so they share one code path. In the transcript, `components/claims/claim-text.tsx` highlights each claim's `quote` in its type colour (hover to see the type, check-worthiness, reason and literal claim). A spinner shows while a line is queued (grey) or being checked (blue), and a red icon if detection failed. A claim whose quote can't be found in the text is shown as a type chip after the line.

**Why merging matters:** a speaker change closes a batch, so in a back-and-forth hearing every turn is its own batch. Without merging and the shared rate limiter, that meant one LLM call per turn plus SDK retries, which quickly went over the free-tier limit of 5/min. Now calls are paced to `GEMINI_RPM`, and everything that queues up meanwhile goes out in the next call.

### Logs

Every step is logged per session (`[claims <id>]`):
```
segment 0 spk=1 words=7 DROP (procedural phrase only, no content): Paragraph 4, Your Honor, please...
segment 1 spk=2 words=40 KEEP (no claim signal, kept by default): We're asked this intelligence...
batch ready (timeout): segments ['1']
LLM call 1 (attempt 1/4): 1 segments from 1 batch(es) ['1'] + 1 context lines
gemini tokens: prompt=1065 cached=None output=121
LLM ok in 5.1s: 1 claims {'opinion': 1}
rate limit: waited 9.9s for a call slot
LLM call failed: 503 UNAVAILABLE; retrying in 5.0s
stop: 6 segments, 2 skipped, 5 LLM calls (1 batches failed), 2 claims {'opinion': 2}
```

### Code

| File | Role |
|---|---|
| `src/services/claims/prefilter.py` | Drops short fragments, greetings, procedure and pure questions. Keeps anything with a claim signal, and **keeps by default** when unsure. All word lists are in `WORD_LISTS` at the top |
| `src/services/claims/batcher.py` | Buffers kept segments and flushes on the first trigger; order is preserved and nothing is lost or duplicated |
| `src/services/claims/classifier.py` | `SYSTEM_PROMPT` (constant, so it is identical on every call), prompt building, and tolerant Pydantic parsing: bad items are dropped, unknown types become `vague`, items map back to segment_id/timestamp/speaker |
| `src/services/claims/detector.py` | `ClaimDetector`, the single entry point: `add_segment`, `stop`, `process`, `abort` |
| `src/services/claims/rate_limiter.py` | Process-wide pacing of LLM calls (`GEMINI_RPM`) |
| `src/clients/gemini_client.py` | Gemini implementation of the injectable `LLMClient` protocol; maps 429/5xx to retryable errors |
| `src/controllers/claims_controller.py` | Websocket session loop and Origin check |

### Websocket protocol: `ws://localhost:8000/api/v1/claims/ws`

Client → server:
```json
{"type": "segment", "segment": {"segment_id": "7", "text": "…", "speaker": "2", "start_ms": 61000, "end_ms": 64500}}
{"type": "stop"}
```
Server → client:
```json
{"type": "skipped", "segment_id": "6", "reason": "procedural phrase only, no content"}
{"type": "checking", "segment_ids": ["7","8"]}
{"type": "claims", "segment_ids": ["7","8"], "claims": [{"id": "7:0", "segment_id": "7", "timestamp": 61000, "speaker": "2",
  "text": "…", "quote": "exact words in the segment", "type": "fact", "checkworthiness": 0.9, "reason": "…", "literal_claim": null}]}
{"type": "error", "message": "…", "fatal": true}
{"type": "done", "claims": 5, "skipped": 3, "llm_calls": 2}
```

### Tests

`uv run pytest -q` runs everything with fake LLM clients and makes no network calls:
- `test_prefilter.py`: drop and keep cases, and every drop has a reason
- `test_batcher.py`: speaker, size, timer and stop flushes, plus ordering and no loss or duplication
- `test_classifier.py`: parsing, malformed output, context lines, splitting mixed sentences, one call per batch, identical system prompt
- `test_detector.py`: a scripted Taglish session end to end with far fewer LLM calls than segments; merging alternating-speaker batches; retries and backoff; per-step logs
- `test_rate_limiter.py`, `test_gemini_client.py`: pacing, and mapping Gemini 429/503 to retries (offline)
- `test_claims_ws.py`: websocket route, rejection of foreign origins, missing Gemini key
- `test_eval_dataset.py`: eval file shape, and the prefilter never drops a labelled claim

### Evaluation (real Gemini, not in CI)

```bash
uv run python scripts/eval_claim_detection.py                  # realistic streaming batches
uv run python scripts/eval_claim_detection.py --mode isolated  # one detector per case
uv run python scripts/eval_claim_detection.py --rpm 60         # paid tier: faster
```
Reads `data/eval/claim_detection.json`, which you can edit: `expected` lists one item per claim, `also_ok` gives acceptable alternate types, and `needs_context` + `context` cover sarcasm. The script prints accuracy per type, a confusion matrix, every miss with its text, the prefilter drop rate, and LLM calls per 100 segments. If `GEMINI_API_KEY` is unset it exits with a message and makes no calls.

### Known gaps

- **Free-tier quota**: 5 requests/min is shared by *all* sessions on one key. The limiter keeps under it by merging batches, but that adds up to ~12 s of wait per call when busy. Use a paid key and raise `GEMINI_RPM` for real sessions.
- **Gemini 503 "high demand"** is on Google's side. Calls retry with backoff (5/10/20 s); if all attempts fail, those lines show the red error icon and are not re-sent.
- **Latency:** a lone segment waits up to `CLAIMS_BATCH_MAX_WAIT_S` (15 s) for its batch to fill, then for a rate-limit slot, then ~2–5 s for Gemini.
- **Origin checks** stop other *websites*, not scripts: a non-browser client can fake `Origin`. Real protection needs auth or rate limiting.
- **Diarization errors** from Soniox pass straight through: a wrong speaker label means a wrong `speaker` on the claim and an extra speaker-change flush.
- Segments are Soniox utterances (`<end>`), not grammatical sentences, so a long utterance can hold several claims (the classifier splits them) and one sentence can be split across two segments.
- Prompt caching: the system prompt is identical on every call, but live runs log `cached=None`, so Gemini isn't caching the ~1,065-token prompt. The token counts are logged per call.
- No persistence and no verification: claims live only in the websocket session and the frontend hook state.
