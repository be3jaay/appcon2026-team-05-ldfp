# sisa_api

FastAPI backend: Soniox temporary keys, live **claim detection**, and **claim verification** against official sources (PSA OpenSTAT, Official Gazette, DPWH flood control records).

```bash
uv sync
uv run fastapi dev src/main.py   # http://localhost:8000, docs at /docs
uv run pytest -q                 # no API keys or network needed
```

## Environment (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `SONIOX_API_KEY` | none | Mints temporary Soniox keys for the browser |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000,https://sisa-app-ten.vercel.app` | Comma-separated browser origins allowed to call the API and open websockets |
| `GROQ_API_KEY` | none | Groq (free tier). With this set, the chain is Groq → Gemini |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id. If it's retired, the error lists Groq's current models |
| `CEREBRAS_API_KEY` / `CEREBRAS_MODEL` | none / `llama-3.3-70b` | Optional extra provider (OpenAI-compatible) |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | none / `meta-llama/llama-3.3-70b-instruct:free` | Optional extra provider (OpenAI-compatible) |
| `GEMINI_API_KEY` | none | Gemini (AI Studio key, starts with `AIza`) |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Gemini model id |
| `GEMINI_THINKING_LEVEL` | `low` | `minimal`/`low`/`medium`/`high`; empty = model default |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Per-request timeout for Gemini |
| `LLM_PROVIDERS` | every provider with a key: groq, cerebras, openrouter, gemini | Order to try providers in, e.g. `groq,gemini` |
| `LLM_RPM` | `6` (`5` if Gemini is first) | Max claim LLM calls per minute, shared by all sessions; `0` = no limit. `GEMINI_RPM` is still read as a fallback |
| `LLM_MAX_OUTPUT_TOKENS` | `6000` | Output budget per call. A low provider default cut long batches off mid-JSON and silently lost their claims |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-request timeout for OpenAI-compatible providers |
| `LLM_REASONING_EFFORT` | `low` | Sent to reasoning models only (gpt-oss, qwen3…); empty = don't send |
| `CLAIMS_LLM_MAX_ATTEMPTS` | `6` | Attempts per batch when every provider is busy. Uses the provider's retry delay, or 5 s/10 s/20 s backoff |
| `CLAIMS_MAX_SEGMENTS_PER_CALL` | `5` | Batches that queue while waiting for a call slot are merged into one call, up to this size |
| `LOG_LEVEL` | `INFO` | Backend log level (`DEBUG` for more) |
| `FACTCHECK_API_KEY` | none | Google Fact Check Tools API key (Cloud console → enable "Fact Check Tools API" → API key). Without it, fact-check fallback is skipped |
| `OPENAI_API_KEY` | none | AI web search (last-resort fallback). Without it the step is skipped |
| `WEB_SEARCH_MODEL` | `gpt-5-search-api` | OpenAI search-enabled model (Chat Completions + `web_search_options`) |
| `WEB_SEARCH_MIN_CHECKWORTHINESS` | `0.6` | Paid searches only run for claims at or above this check-worthiness |
| `WEB_SEARCH_RPM` / `WEB_SEARCH_CACHE_SECONDS` | `10` / `86400` | Pacing and cache for web searches |
| `WEB_SEARCH_PROVIDERS` | `openai,groq` | Web search providers, tried in order. A provider that rejects its key or runs out of credits is switched off until restart |
| `WEB_SEARCH_GROQ_MODEL` / `WEB_SEARCH_GROQ_RPM` | `openai/gpt-oss-120b` / `1` (`2` with its own key) | Free fallback: Groq's built-in `browser_search`. ≈7k tokens a search against an 8k tokens/min free tier, so it is paced slowly |
| `WEB_SEARCH_GROQ_API_KEY` | `GROQ_API_KEY` | A key from a second free Groq account, so searches don't eat detection's per-minute budget (recommended for live demos) |
| `FACTCHECK_CACHE_SECONDS` | `86400` | Identical fact-check searches are served from memory for this long |
| `FLOOD_CONTROL_DATA_URL` | BetterGov.ph GitHub raw URL | DPWH flood control dataset (downloaded on first use) |
| `FLOOD_CONTROL_CACHE_PATH` | `data/sources/flood_control.json` | Local copy (gitignored) |
| `FLOOD_CONTROL_MAX_AGE_HOURS` | `168` | Re-download when the local copy is older than this; a failed download falls back to the old copy |
| `OFFICIAL_GAZETTE_BASE_URL` | `https://www.officialgazette.gov.ph` | Official Gazette site |
| `OFFICIAL_GAZETTE_RPM` | `30` | Max requests/min to the Official Gazette from this process |
| `OFFICIAL_GAZETTE_CACHE_SECONDS` | `600` | Identical searches are served from memory for this long |
| `OFFICIAL_GAZETTE_TIMEOUT_SECONDS` | `20` | Per-request timeout |
| `OFFICIAL_GAZETTE_USER_AGENT` | `SISA-FactCheck/0.1 (…)` | Honest User-Agent sent to the site |
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
                                                         (LLM_RPM), merges queued batches
                                              ◄────── {"type":"checking", segment_ids}
                                                      4. ClaimClassifier: ONE LLM call
                                                         (Groq → Gemini fallback chain)
                                                         + previous 2 lines as CONTEXT only
                                                         retries 429/503 with the provider's delay
                                              ◄────── {"type":"claims", claims:[...]}
```

Mic and video both go through the same hook (`sisa_fe/hooks/use-soniox-transcription.ts`), so they share one code path. In the transcript, `components/claims/claim-text.tsx` highlights each claim's `quote` in its type colour (hover to see the type, check-worthiness, reason and literal claim). A spinner shows while a line is queued (grey) or being checked (blue), and a red icon if detection failed. A claim whose quote can't be found in the text is shown as a type chip after the line.

**Why merging matters:** a speaker change closes a batch, so in a back-and-forth hearing every turn is its own batch. Without merging and the shared rate limiter, that meant one LLM call per turn plus SDK retries, which quickly went over the free-tier limit of 5/min. Now calls are paced to `LLM_RPM`, and everything that queues up meanwhile goes out in the next call.

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
| `src/services/claims/rate_limiter.py` | Process-wide pacing of LLM calls (`LLM_RPM`) |
| `src/clients/llm_chain.py` | Provider fallback chain (`FallbackLLMClient`) and `build_llm_client()` from settings |
| `src/clients/openai_compat_client.py` | Groq / Cerebras / OpenRouter (OpenAI chat format, JSON mode, httpx); maps 429/5xx/timeouts to retryable errors |
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

## Rhetoric: evasion and fallacies

The same detection call also returns, per claim, `fallacy` (one of ad_hominem, straw_man, whataboutism, red_herring, false_dilemma, slippery_slope, hasty_generalization, appeal_to_emotion, appeal_to_authority, bandwagon, or null), `evasion` (the speaker answered a question/criticism in the segment or a CONTEXT line without addressing it) and `rhetoric_note` (one sentence quoting the words). Only set when clearly present; ordinary news narration is never flagged; the prompt forbids guessing motives. The frontend shows "Evasive" / fallacy chips on the Current Claim card and in history, and a marker in the transcript.

## Conflicting statements

Each detection call also gets the session's last 12 assertions (fact/legal/promise) as `[E1]…` lines (never extracted). A new claim that clearly conflicts with one of them (same subject, can't both be true: a different figure, did vs did not) gets `contradicts` (the earlier claim's id) and `contradiction_note`. Updates, announced corrections and different subjects are not conflicts. The frontend shows a "Conflicts with earlier" chip that opens the earlier claim, and a short alert over the video.

## Testing a whole transcript

```bash
uv run python scripts/run_transcript.py ../transcribe.md            # real providers and sources
uv run python scripts/run_transcript.py ../transcribe.md --no-web   # skip the paid web search
uv run python scripts/run_transcript.py ../transcribe.md --limit 12 --json out.json
```
Splits plain text into segments like live transcription (≈45 words), runs detection with real batching, verifies each claim exactly as the frontend does (with the surrounding lines as context), and prints every verdict plus totals by status and method.

## Claim verification

The detection LLM also returns, per claim, `check_type` (`STATISTICAL | LEGAL | OTHER`) and `entities` (the claim's parts) in the same call, so there is no extra LLM call. Verification itself uses **no LLM**; it routes the claim to an official source:

| check_type | Source | What it can conclude |
|---|---|---|
| `STATISTICAL`, flood control | DPWH flood control project records (via BetterGov.ph) | Totals/counts computed from the records for the place, year(s) and contractor named. Within 5% → SUPPORTED, 5–25% off → NEEDS_CONTEXT, more → CONTRADICTED. Unknown place / no rows → INSUFFICIENT_EVIDENCE |
| `STATISTICAL`, other | PSA OpenSTAT (existing `openstat_service`, unchanged) | SUPPORTED / CONTRADICTED against the published figure. Only the **unemployment rate** is connected so far |
| `LEGAL` | Official Gazette search | Existence/issuance claims ("EO 124 was issued"): SUPPORTED when the document is found. Content claims ("EO 124 reorganized DPWH"): one LLM call compares the claim with the official excerpt, giving SUPPORTED / CONTRADICTED, or NEEDS_CONTEXT if the excerpt doesn't settle it. Not found is INSUFFICIENT_EVIDENCE, never CONTRADICTED |
| `OTHER`, or an unsupported statistic | none | **NO_SOURCE** ("SISA has no data source for … yet, so it was not checked"), unless a published fact-check settles it (below) |

**AI web search (last fallback).** Idea from the `feat/pdm-test` branch, rebuilt with guardrails. If a claim is still NO_SOURCE / INSUFFICIENT_EVIDENCE after the data sources and published fact-checks, and `OPENAI_API_KEY` is set and the claim's check-worthiness is ≥ `WEB_SEARCH_MIN_CHECKWORTHINESS`, one call to an OpenAI search model judges it (`factual/misleading/needscontext/unfounded` → SUPPORTED/CONTRADICTED/NEEDS_CONTEXT/INSUFFICIENT_EVIDENCE, method `AI_WEB_SEARCH`).
- Only pages the search actually used (the API's `url_citation` annotations) count as sources; URLs the model merely lists are dropped.
- Every source gets a reliability label: government (`.gov.ph`), fact_checker, news, reference (Wikipedia), other. A factual/misleading verdict with no government/fact-checker/news source is **downgraded to NEEDS_CONTEXT**.
- The prompt judges the claim only; it does not guess motives (the pdm-test "subtext / hidden agenda" field was deliberately left out).
- Providers (`WEB_SEARCH_PROVIDERS`): OpenAI first, then Groq `browser_search` (free, same Groq key as detection; its citations are the search results and pages it opened). An out-of-credits 429 (`insufficient_quota`) or a rejected key switches that provider off; a plain rate limit only pauses it. Each verification logs `verify <type> -> <status> via <method>`, and why web search was skipped.
- Paced (`WEB_SEARCH_RPM`), cached per claim for a day, and skipped for low check-worthiness. Code: `clients/web_search_client.py`, `services/web_search_service.py`. `GET /api/v1/sources/status` reports `web_search`.

**Published fact-checks (fallback).** When our data can't settle a claim (NO_SOURCE or INSUFFICIENT_EVIDENCE) and `FACTCHECK_API_KEY` is set, the claim is searched in Google's Fact Check Tools API (ClaimReview from Rappler, VERA Files, AFP Fact Check, FactRakers and others). The search uses the detector's English `text_en` (sent as `search_text`), because most fact-checks are in English. One LLM call decides which results review the **same** claim. A same-claim result with a clear rating becomes the verdict (method `PUBLISHED_FACT_CHECK`): false/fake/misleading/incorrect → CONTRADICTED, missing context/half true/unproven → NEEDS_CONTEXT, true/accurate → SUPPORTED. Conflicting ratings → NEEDS_CONTEXT. Other results are listed as RELATED evidence and never change the verdict; unmappable ratings (Satire, Explainer…) don't either. Without an LLM, nothing counts as the same claim. Conclusive official-data results never consult fact-checks. Endpoints: `POST /api/v1/fact-checks/search` (`{query, language?}`), `GET /api/v1/sources/status` (`{factcheck, llm}` for the UI's source list). Code: `clients/factcheck_client.py`, `services/factcheck_service.py`, `routes/factcheck_routes.py`.

`POST /api/v1/claims/verify`
```json
{"claim": "The President issued Executive Order No. 124", "claim_type": "LEGAL",
 "entities": {"document_type": "Executive Order", "document_number": "124", "subject": null, "date": null}}
```
```json
{"claim": {"text": "The President issued Executive Order No. 124", "type": "LEGAL_ISSUANCE"},
 "assessment": {"status": "SUPPORTED", "explanation": "A matching document was found in the Official Gazette: Executive Order No. 124, s. 2026 (published 2026-09-08); …"},
 "evidence": [{"source": {"name": "Official Gazette of the Republic of the Philippines", "publisher": "Presidential Communications Office",
     "source_type": "OFFICIAL_DOCUMENT", "document_type": "Executive Order", "document_number": "124", "date": "2026-09-08",
     "title": "Executive Order No. 124, s. 2026", "url": "https://www.officialgazette.gov.ph/2026/09/08/executive-order-no-124-s-2026/"},
   "data": {"relevant_text": "MALACAÑAN PALACE MANILA BY THE PRESIDENT OF THE PHILIPPINES EXECUTIVE ORDER NO. 124 ESTABLISHING …",
     "document_reference": "Executive Order No. 124, s. 2026"},
   "relevance": "DIRECT"}]}
```
Statistical claims return `source_type: "OFFICIAL_STATISTICS"` evidence with `value`, `unit`, `period`, `geography`. Source failures come back as `status: "ERROR"` with an explanation (HTTP 200), so the UI can show them next to the claim.

## DPWH flood control projects (via BetterGov.ph)

Source: `bettergovph/bettergov` → `src/data/flood_control/flood_control.json` (CC0). It is an ArcGIS export of the DPWH flood control project map (`Creator: dpwh_view`): **9,855 contract records** (one row per contract / project component), funding years 2018–2025, 16 regions (**no BARMM rows**), with region, province, municipality, legislative district, district engineering office, contractor, approved budget (ABC), contract cost, dates and coordinates. It is a **compiled copy of DPWH data, not an official DPWH release**, and evidence says so.

- `GET /api/v1/flood-control/summary?year=&year_from=&year_to=&region=&province=&municipality=&legislative_district=&contractor=&type_of_work=` returns the record count, total contract cost, total approved budget, totals per year, and the top 5 contractors by cost. Regions accept spoken names ("Central Luzon", "NCR", "region 3").
- `GET /api/v1/flood-control/projects?…&limit=50` returns matching records, largest contract first.
- Verification: STATISTICAL claims whose metric, text or transcript line mentions flood control (or baha, dike, revetment, drainage…) are routed here instead of OpenSTAT.
- **One project vs. a total.** "The road dike project cost ₱289M" is about one project: it is matched against individual contract records (within 2% when a place, contractor or year narrows it; SUPPORTED with the record as evidence). With no place/contractor/year, a near-exact match (0.5%) only gives NEEDS_CONTEXT, since several projects can share a cost. A named structure (dike, revetment, seawall…) narrows the candidates. No matching record gives INSUFFICIENT_EVIDENCE with the closest record, never CONTRADICTED. A claim about one project is never compared with a total.
- **Details recovered from the transcript line.** `/claims/verify` accepts `context` (the transcript segment; the frontend sends it). When the detector drops the place or contractor named earlier in the same line, they are recovered from names that actually appear in the DPWH records: provinces/regions and distinctive contractor words, excluding place words. A `$` amount on a DPWH claim is compared in pesos, and the explanation says the transcript may have misheard ₱. The detector's `entities` give the place (`geography`), year or range (`date`: "2023", "2018-2025", "mula 2018 hanggang 2025"), `contractor`, and `value`/`unit`. A peso amount is compared with the total contract cost; a count is compared with the number of records. Spoken scales are handled ("₱547 bilyon").
- Code: `clients/bettergov_client.py` (download), `services/flood_control_service.py` (load/cache, parse, filters, totals), `routes/flood_control_routes.py`, `controllers/flood_control_controller.py`, `models/flood_control.py`.

## Official Gazette

**How the site works** (checked Sept 2026): it is WordPress behind Cloudflare. HTML pages (home, `/?s=` search, document pages, `/wp-json`) answer automated clients with **403**: either a JavaScript challenge or a WAF "Sorry, you have been blocked" page. We do **not** try to get around that. The **RSS feed is served normally, and WordPress applies its site search to it**: `GET /feed/?s=<query>` returns up to 10 matching posts, each with the official title, permalink, publication date, categories and the opening text of the document. Document URLs look like `/YYYY/MM/DD/<slug>/`.

- `POST /api/v1/official-gazette/search` with `{"query": "Executive Order No. 124", "limit": 10}`. A natural-language claim works too (`"The President issued Executive Order No. 124"`): a document reference is detected (EO/RA/Proclamation/AO/MC/PD/BP…, including "EO 124", "RA 11054", "Batas Republika Blg.") and searched in canonical form. Results naming that exact document are `relevance: "DIRECT"` and listed first. `document_type`/`document_number`/`series_year` are parsed from the title; `date` is the site's publication date; `snippet` is the site's own text. Fields that can't be determined are `null`.
- `POST /api/v1/official-gazette/document` with `{"url": "https://www.officialgazette.gov.ph/…"}`. Only `https` URLs on `officialgazette.gov.ph` are accepted (400 otherwise, and no request is made). The page is fetched first. When Cloudflare blocks it (the usual case), the response falls back to the document's feed entry, with `text_scope: "FEED_EXCERPT"`. `issuing_authority` is set only when the text itself says it (e.g. "BY THE PRESIDENT OF THE PHILIPPINES").
- `official_gazette_service.search_for_claim(StructuredLegalClaim)` accepts the detector's structured shape (`subject`/`predicate`/`object`/`context`) for later use.
- Code: `clients/official_gazette_client.py` (HTTP + feed/page parsing, Cloudflare detection, URL validation, 429/`Retry-After`, timeouts, pacing), `services/official_gazette_service.py` (reference parsing, relevance, cache, document retrieval), `routes/official_gazette_routes.py`, `controllers/official_gazette_controller.py`, `models/official_gazette.py`.

### Tests

`uv run pytest -q` runs everything with fake LLM clients and makes no network calls:
- `test_prefilter.py`: drop and keep cases, and every drop has a reason
- `test_batcher.py`: speaker, size, timer and stop flushes, plus ordering and no loss or duplication
- `test_classifier.py`: parsing, malformed output, context lines, splitting mixed sentences, one call per batch, identical system prompt
- `test_detector.py`: a scripted Taglish session end to end with far fewer LLM calls than segments; merging alternating-speaker batches; retries and backoff; per-step logs
- `test_rate_limiter.py`, `test_gemini_client.py`: pacing, and mapping Gemini 429/503 to retries (offline)
- `test_llm_providers.py`: OpenAI-compatible client (request shape, 429/503/timeout/bad key/retired model) and the fallback chain (fallback, cooldowns, all-busy)
- `test_official_gazette.py`: feed parsing on **real captured responses** (`tests/fixtures/official_gazette/`), Cloudflare challenge/WAF detection, URL validation, HTTP errors, relevance, caching, document fallback, routes
- `test_claim_verification.py`: STATISTICAL→OpenSTAT and LEGAL→Official Gazette routing and the conservative assessments
- `test_web_search.py`: OpenAI search client (request shape, errors), cited-sources-only rule, reliability labels, weak-source downgrade, check-worthiness gate, cache, fallback order
- `test_factcheck.py`: Fact Check API client (params, key errors as returned live, 429), keyword fallback, cache, rating mapping, same-claim matching, and the fallback in verification (verdict, related-only, conflicting, unmapped, errors, English search text)
- `test_flood_control_projects.py`: single-project matching, detail recovery from the transcript line, contractor keywords vs place names, dollar note
- `test_flood_control.py`: parsing, place/region/contractor/year-range filters, totals, disk cache and download fallback, routes, and flood control claim verification, all on **19 real records** (`tests/fixtures/flood_control/sample.json`)
- `test_claims_ws.py`: websocket route, rejection of foreign origins, no LLM key configured
- `test_eval_dataset.py`: eval file shape, and the prefilter never drops a labelled claim

### Evaluation (real LLM, not in CI)

```bash
uv run python scripts/eval_claim_detection.py                  # realistic streaming batches
uv run python scripts/eval_claim_detection.py --mode isolated  # one detector per case
uv run python scripts/eval_claim_detection.py --providers groq  # one provider only, to compare
uv run python scripts/eval_claim_detection.py --rpm 60         # paid tier: faster
```
Reads `data/eval/claim_detection.json`, which you can edit: `expected` lists one item per claim, `also_ok` gives acceptable alternate types, and `needs_context` + `context` cover sarcasm. The script prints accuracy per type, a confusion matrix, every miss with its text, the prefilter drop rate, and LLM calls per 100 segments. If no LLM key is set it exits with a message and makes no calls.

### Known gaps

- **Free-tier quotas** are shared by *all* sessions: Groq allows 8k tokens/min (~3–4 calls, each about 2k tokens) and 1,000 requests/day; Gemini allows 5 requests/min. When Groq hits its limit, the chain sends the batch to Gemini and skips Groq for the wait time Groq gave. The limiter (`LLM_RPM`, default 6) plus batch merging keeps the total within both.
- **Provider overload** (Gemini 503 "high demand") falls straight through to the next provider. Only when every provider is busy does the batch wait (5/10/20 s backoff). If all attempts fail, those lines show the red error icon.
- **Latency:** a lone segment waits up to `CLAIMS_BATCH_MAX_WAIT_S` (15 s) for its batch to fill, then for a rate-limit slot, then ~2–3 s for Groq (gpt-oss-120b, low reasoning).
- **Model ids change:** Groq retired Llama 3.3 70B; if a configured model disappears, the error message lists the provider's current models. Set `GROQ_MODEL` accordingly.
- **Origin checks** stop other *websites*, not scripts: a non-browser client can fake `Origin`. Real protection needs auth or rate limiting.
- **Diarization errors** from Soniox pass straight through: a wrong speaker label means a wrong `speaker` on the claim and an extra speaker-change flush.
- Segments are Soniox utterances (`<end>`), not grammatical sentences, so a long utterance can hold several claims (the classifier splits them) and one sentence can be split across two segments.
- Prompt caching: the system prompt is identical on every call, but live runs log `cached=None`, so Gemini isn't caching the ~1,065-token prompt. The token counts (and cached tokens, when a provider reports them) are logged per call.
- No persistence: claims live only in the websocket session and the frontend hook state.
- Content claims about a found document ("EO 124 reorganized DPWH") are judged by one LLM call against the Official Gazette excerpt only (`services/evidence_judge.py`, method `AI_COMPARISON`). It can miss details that are beyond the opening text; those stay NEEDS_CONTEXT.
- Official Gazette: only the feed is reachable, so evidence text is the site's **opening excerpt**, not the full document. Search results are the site's own (WordPress) ranking, 10 per page. "1987 Constitution" finds documents that cite it, not the Constitution page itself.
- OpenSTAT verification covers the unemployment rate only.
- AI web search is the weakest evidence tier: an LLM's reading of web pages. It is labelled as such, sources are shown with reliability, and it never overrides official data or published fact-checks. It is untested against the live API until `OPENAI_API_KEY` is set (model name `gpt-5-search-api` taken from feat/pdm-test).
- Published fact-checks only exist for claims fact-checkers have already covered (mostly viral ones); new claims usually return nothing. They are secondary sources: the UI labels them as the fact-checker's verdict, not SISA's data.
- Flood control figures are **contract costs of the projects listed in the DPWH map**, not total appropriations or disbursements; BARMM is missing and some projects may not be listed. "Project records" are contract rows, so one project with several components counts more than once.
