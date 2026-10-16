# Active State

## Objective

Deliver the multi-profile AI contact-centre chat POC, including local document-grounded insurance and credit-card comparisons alongside the existing receptionist profiles.

## Status

`ollama-implemented-validated` — all four profiles use loopback-only Ollama, deterministic evaluations pass, and representative live model evaluations pass.

## Current design discussion

- Historical design context: the user evaluated Vocal-Agent as an alternative to the original OpenAI API-key-backed responses.
- Settled in grilling round 1: replace the OpenAI model path for all four chat profiles; target local/self-hosted inference with no external model-provider key; build comprehensive deterministic offline tests plus optional model-quality evaluations that can run when a local model is available.
- Verified Vocal-Agent is not a drop-in replacement: it is a CUDA-oriented desktop voice app with audio and external-search components. User chose to retain this app's browser text chat and use only the local Ollama model approach, excluding Vocal-Agent's audio and web-search pieces.
- Settled in grilling round 2: use Ollama's local OpenAI-compatible endpoint only, configurable, with no external provider key or OpenAI endpoint fallback; create a versioned JSONL eval dataset, deterministic offline runner, and optional local-model runner/report.
- Environment fact-check: Ollama 0.40.4 is running at localhost:11434; `llama3.1:8b` is installed and advertises tool capability. Machine is Apple M5/arm64 with 24 GiB RAM. No model was loaded and no inference/app compatibility was tested.
- Settled in grilling round 3: default to installed `llama3.1:8b` with configurable `OLLAMA_MODEL` and no silent fallback; JSONL cases record measurable source/fact/tool/protocol expectations without exact response strings; live evals auto-score observable behavior, preserve traces/responses for human review, and may optionally use a local judge whose score is advisory only.
- Settled in grilling round 4: if Ollama is unavailable/model missing/response malformed, no external or fabricated fallback; API starts and chat turns return structured errors; health reports Ollama/model status. Include the full profile happy-path/failure matrix. Live reports are timestamped local JSON under ignored `backend/eval-results/`.
- Settled in grilling round 5: enforce a loopback-only Ollama endpoint, default `http://127.0.0.1:11434`; use async HTTPX with Ollama `/v1/chat/completions`, no OpenAI SDK, key setting, or Authorization header.
- User confirmed the complete design in grilling round 6; implementation may proceed.
- Current handoff check: `.venv/bin/python -m pytest -q` passes (33 tests); the offline evaluation suite passes all 36 JSONL cases. Representative live Ollama evaluations pass for restaurant knowledge, auto booking (including check-before-book), insurance comparison, and credit-card comparison. Loopback-only networking/no auth, health reporting, structured failures, report output, and ignored reports are verified. Source setup/docs contain no OpenAI key/model references. Existing FastAPI/httpx and pytest-asyncio deprecation warnings remain.
- Exact next action: run `python3 scripts/validate_active_state.py` from the repository root and make no further code changes unless it identifies a state-file issue.

## Current design discussion

- The UI offers four choices: restaurant, auto repair, Insurance Comparison, and Credit Card Comparison. Existing restaurant and auto tool flows remain enabled; the two comparison profiles have no booking, escalation, or message-capture tools.
- Insurance defaults to AAMI Comprehensive vs RACV Motor Insurance. AAMI Third Party Property Damage and RACV Complete Care are retrieved when asked. The credit-card profile compares the supplied NAB personal-card terms and CommBank Conditions of Use at the document level, not as named-card comparisons.
- All six insurance and bank-policy PDFs have side-by-side Markdown conversions from MarkItDown 0.1.8, pinned as a development dependency. Run `python scripts/convert_policy_pdfs.py` from the repository root to regenerate them.
- The app searches local page/section-aware keyword chunks and supplies relevant excerpts to the LLM. It uses only repository docs, does not provide individualized financial/insurance advice, cites only when asked, and reports evidence gaps. It discloses relevant source dates and that currentness has not been independently verified.
- `cd backend && .venv/bin/python -m pytest -q`: 22 passed. Frontend JavaScript syntax and profile/config checks passed. Retrieval probes found excerpts from both default comparison sources with page provenance.
- `python3 scripts/validate_active_state.py` passed; the handoff is valid.
- Browser visual review was declined. The temporary static server was stopped after a successful local HTTP 200 check; no browser interaction was performed.

## Last updated

2026-10-16T03:49:55Z

## Completed

- Initialized the repository as Git.
- Replaced the active server flow with `WS /chat/{business_id}` for the Universal AI Receptionist POC.
- Added two tenant configurations, the provided dynamic system-prompt template, the original OpenAI function-calling routing (later replaced by local Ollama), and terminal-logged mock booking, KB, escalation, and message functions.
- Replaced the active UI with a dependency-free text chat client at `frontend/index.html`.
- Fixed the original `.env` configuration wiring and provider error handling before migrating inference to Ollama.
- Updated the top-level README so it reflects the actual receptionist POC and its setup flow.
- Added a regression check for configured API keys and API failure handling; `backend/.venv/bin/python -m pytest` passes with 9 tests.
- Localized `gtm-engineer`, `web-dev`, and `chief-of-staff` from ai-employees 1.8.0. Each installer self-test passed.
- Added the Insurance Comparison and Credit Card Comparison profiles, local policy-document search, MarkItDown conversion tooling and six generated Markdown sources, selector support, documentation, and regression tests.

## Current step

Complete implementation and validation of local Ollama inference and the comprehensive offline/live evaluation suite confirmed with the user.

## Exact next action

From the repository root, run `python3 scripts/validate_active_state.py` to validate this handoff state.

## Decisions

- The POC accepts text (including simulated transcripts), not audio, SIP, WebRTC, or a database.
- Tenant state and conversation history are in-memory and scoped to a WebSocket connection.
- Local inference uses loopback-only Ollama at `http://127.0.0.1:11434` and defaults to `llama3.1:8b`, configurable with `OLLAMA_BASE_URL` and `OLLAMA_MODEL`. No external model provider or API key fallback is permitted.
- Required employee kits: GTM Engineer, Web Dev, and Chief of Staff.
- Comparison knowledge is limited to the supplied repository documents and local keyword retrieval; MarkItDown is a development/conversion dependency, not a runtime requirement.
- Insurance default comparison is AAMI Comprehensive vs RACV Motor Insurance; dated source limitations are disclosed. Credit-card comparison uses supplied NAB and CommBank terms, without implying applicability to every card.
- The two document personas are informational only, with no individualized financial/insurance recommendations or receptionist tools. Citations are shown only if requested.

## Blockers

- Manual browser interaction was not performed; local model health and representative live chat/tool flows were validated directly.
- Each employee kit still requires its one-time upstream `INSTALL-PROMPT.md` workflow, including user-specific business details and scheduler registration. No schedules were registered automatically.

## Resume prompt

Read `ACTIVE_STATE.md`, inspect the listed files and verification state, then perform the exact next action. Update this file after each material step.
