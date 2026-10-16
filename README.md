# Universal AI Contact Centre POC

This project is a browser-based AI contact-centre chat demo. All four chats use a FastAPI WebSocket and local Ollama inference; restaurant and auto-repair profiles also use mock booking/escalation tools. Two informational chats compare insurance policies and credit-card terms using locally stored policy documents.

## What it does

- Connects a browser client to a per-profile WebSocket endpoint
- Keeps restaurant and auto-repair receptionist behavior, including mock `search_kb`, `trigger_booking`, `transfer_call`, and `save_message` tools
- Adds document-only Insurance Comparison and Credit Card Comparison chats
- Searches local Markdown excerpts from the supplied PDS and card-terms PDFs; these chats do not expose booking, escalation, or message-capture tools
- Keeps conversation memory in-process and scoped to one client connection

## Included chat profiles

- `hua_lu_peking_duck`
- `apex_auto_works`
- `insurance_comparison`
- `credit_card_comparison`

Profiles are configured in [backend/config.json](backend/config.json). Receptionist entries use business summaries and booking requirements. Document-comparison entries list their Markdown sources and comparison scope.

## Policy documents

The insurance and credit-card profiles use Markdown generated from the PDFs in `knowledge/insurance-comparisons-au/` and `knowledge/banking-comparisons-au/`. Install the development dependencies, then regenerate the Markdown from the repository root:

```sh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cd ..
python scripts/convert_policy_pdfs.py
cd backend
cp .env.example .env
```

The conversion command uses MarkItDown's PDF support, writes `.md` files beside each source PDF, and preserves detected page numbers as Markdown comments for source tracking. Re-run it when policy PDFs change. The server reads the saved Markdown; MarkItDown is not used at runtime.

Answers are factual and based only on the supplied repository documents. The comparison chats disclose relevant document dates and that currentness has not been independently verified; they do not provide individualized advice. They show citations only when asked and say when the documents do not establish an answer.

## Local inference setup

Install [Ollama](https://ollama.com/), start its local service, and download the default model:

```env
ollama serve
ollama pull llama3.1:8b
```

Ollama must be reachable only at a loopback address. The defaults are `http://127.0.0.1:11434` and `llama3.1:8b`; optionally configure them in [backend/.env.example](backend/.env.example) values copied to `backend/.env`:

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1:8b
```

There is no external-provider or API-key fallback. The API can start while Ollama is unavailable; `/health` reports service/model status and chat turns return a structured error until the configured model is available.

Start the API from `backend`:

```sh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

In another terminal, serve the browser test client:

```sh
cd frontend
python -m http.server 5173
```

Open `http://localhost:5173`, select one of the four chat profiles, connect, and send a message.

## WebSocket protocol

Connect to:

```text
ws://localhost:8000/chat/{business_id}
```

And send JSON such as:

```json
{"message":"I need a table for four tomorrow"}
```

The server emits `session.ready`, then either:

- `assistant.message` with the final receptionist reply and executed tool metadata, or
- `error` with a structured failure code and message

## Testing

```sh
cd backend
. .venv/bin/activate
pytest -q
```

## Evaluation cases

The versioned [cases.jsonl](backend/evals/cases.jsonl) dataset covers all four profiles, tool flows, document scope/citations/advice boundaries, and protocol/provider/document failures. Run the deterministic suite without model inference:

```sh
cd backend
.venv/bin/python -m scripts.run_evals --offline
```

Run model-quality evaluations against the configured local Ollama model, optionally adding a non-binding local-model judge:

```sh
.venv/bin/python -m scripts.run_evals --live
.venv/bin/python -m scripts.run_evals --live --judge
```

Use `--case CASE_ID` (repeatable) to select particular cases. Each run writes a timestamped JSON report under `backend/eval-results/`, which is ignored by Git. Offline evaluation is also included in `pytest -q`.

## Cross-harness handoff

Read and update [ACTIVE_STATE.md](ACTIVE_STATE.md) before any material work. Validate it with:

```sh
python scripts/validate_active_state.py
```
