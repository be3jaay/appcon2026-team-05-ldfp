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
| `GEMINI_RETRY_ATTEMPTS` | `3` | Retries on 429/500/503/504 with backoff |
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
                                                      3. ClaimClassifier: ONE Gemini call per batch
                                                         + previous 2 lines as CONTEXT only
                                              ◄────── {"type":"claims", claims:[...]}
```

Mic and video both go through the same hook (`sisa_fe/hooks/use-soniox-transcription.ts`), so they share one code path. The frontend only sends segments; claims are exposed from the hook but are not rendered yet.

### Code

| File | Role |
|---|---|
| `src/services/claims/prefilter.py` | Drops short fragments, greetings, procedure and pure questions. Keeps anything with a claim signal, and **keeps by default** when unsure. All word lists are in `WORD_LISTS` at the top |
| `src/services/claims/batcher.py` | Buffers kept segments and flushes on the first trigger; order is preserved and nothing is lost or duplicated |
| `src/services/claims/classifier.py` | `SYSTEM_PROMPT` (constant, so it is identical on every call), prompt building, and tolerant Pydantic parsing: bad items are dropped, unknown types become `vague`, items map back to segment_id/timestamp/speaker |
| `src/services/claims/detector.py` | `ClaimDetector`, the single entry point: `add_segment`, `stop`, `process`, `abort` |
| `src/clients/gemini_client.py` | Gemini implementation of the injectable `LLMClient` protocol |
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
{"type": "claims", "segment_ids": ["7","8"], "claims": [{"id": "7:0", "segment_id": "7", "timestamp": 61000, "speaker": "2",
  "text": "…", "type": "fact", "checkworthiness": 0.9, "reason": "…", "literal_claim": null}]}
{"type": "error", "message": "…", "fatal": true}
{"type": "done", "claims": 5, "skipped": 3, "llm_calls": 2}
```

### Tests

`uv run pytest -q` runs everything with fake LLM clients and makes no network calls:
- `test_prefilter.py`: drop and keep cases, and every drop has a reason
- `test_batcher.py`: speaker, size, timer and stop flushes, plus ordering and no loss or duplication
- `test_classifier.py`: parsing, malformed output, context lines, splitting mixed sentences, one call per batch, identical system prompt
- `test_detector.py`: a scripted Taglish session end to end with far fewer LLM calls than segments
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

- **Free-tier quota**: Gemini free tier allows 5 requests/min per model. A live session with frequent speaker changes can exceed that; 429s are retried with backoff, which adds latency. Use a paid key for real sessions.
- **Origin checks** stop other *websites*, not scripts: a non-browser client can fake `Origin`. Real protection needs auth or rate limiting.
- **Diarization errors** from Soniox pass straight through: a wrong speaker label means a wrong `speaker` on the claim and an extra speaker-change flush.
- Segments are Soniox utterances (`<end>`), not grammatical sentences, so a long utterance can hold several claims (the classifier splits them) and one sentence can be split across two segments.
- Prompt caching relies on Gemini's implicit prefix caching of the identical system prompt; it only applies above the model's minimum prompt size, and nothing measures it yet.
- No persistence and no verification: claims live only in the websocket session and the frontend hook state.
