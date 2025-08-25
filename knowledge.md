# LeadGenius AI — Project Knowledge

This document transfers key knowledge for starting a new chat, maintaining the system, and planning next steps.

## Product overview
LeadGenius AI is an admin‑managed lead generation platform. Admins onboard clients, scrape their websites into a knowledge base, and deploy a custom chatbot that handles visitor chats and email follow‑ups. Clients can view/manage leads and email conversations; the admin controls configuration and deployment.

Core flow:
- Admin creates client and triggers website scraping to markdown.
- Optional LLM filtering cleans markdown for RAG.
- Content goes into a per‑client vector DB.
- Admin configures system prompts and deploys a chatbot (custom client ID).
- Chat endpoint serves responses with Gemini; tools qualify leads and capture contacts.
- Email automation sends follow‑ups; manual override is supported.

## Key architecture and components
- FastAPI app: `app/main.py`
  - Routers included: `admin`, `knowledge_base`, `client_config`, `chat`, `client_dashboard`, `automation`, `email_chat`, `auth`.
  - Health: `GET /` and `GET /health`.
  - Startup: begins email monitoring (`start_email_monitoring()`).

- Knowledge base management: `app/routers/knowledge_base.py` (prefix: `/api/admin/knowledge-base`)
  - `GET /client/{client_id}` — list entries
  - `POST /client/{client_id}/add-markdown` — add content (indexes to vectors)
  - `PUT /entry/{document_id}` — update (re-indexes)
  - `DELETE /entry/{document_id}` — delete (note: vector delete not yet granular)
  - `POST /client/{client_id}/upload-file` — upload .md/.txt (indexes)
  - `POST /client/{client_id}/rebuild-vectors` — clear + rebuild collection
  - `GET /client/{client_id}/search` — semantic search
  - Supabase storage utilities: list/get/create markdown mirrors

- Client configuration & deployment: `app/routers/client_config.py` (prefix: `/api/admin/client-config`)
  - `GET /client/{client_id}/deployment` — create/get deployment config
  - `PUT /client/{client_id}/system-prompts` — set website/email prompts + welcome messages
  - `POST /client/{client_id}/generate-custom-id` — create unique `custom_client_id`
  - `POST /client/{client_id}/deploy` / `POST /client/{client_id}/undeploy`

- Admin ops and ingestion: `app/routers/admin.py` (prefix: `/admin`)
  - CRUD/list clients, details, delete client
  - `POST /clients/{client_id}/scrape` — trigger ingestion pipeline: crawl → optional LLM filter → store → vectors
  - KB doc CRUD mirrors also available here

- Chat (website): `app/routers/chat.py` (prefix: `/api/chat`)
  - `POST /{custom_client_id}/message`
    - Looks up `ClientDeployment`, fetches vectors from `client_{client_id}` collection (`VectorStoreService.query()`), calls `GeminiService.generate_response(...)` with system prompt + chat history.
    - Persists chat messages, updates lead status if qualified, sends follow‑up email if qualified with email.
  - `GET /{custom_client_id}/history/{session_id}` — retrieve messages

- Email chat management: `app/routers/email_chat.py` (prefix: `/api/admin/email-chat`)
  - View conversations/messages; toggle manual override; send manual emails; monitoring controls; stats.

- Vector store abstraction: `app/services/vector_store_service.py`
  - Embeddings: default local Sentence‑Transformers `all-MiniLM-L6-v2`; optional Google Generative AI when `embeddings_provider=google` and `GOOGLE_API_KEY` present.
  - Backends: local `Chroma` at `./chroma_db/` (default) or Supabase `pgvector` when configured.
  - Per‑client logical isolation via collection name `client_{client_id}`.

- LLM and tools:
  - Gemini service: `app/services/gemini_service.py` — model: `gemini-2.5-flash-lite`. Returns AI text plus `tool_results` for lead qualification and contact capture. Used by `chat.py`.
  - Markdown filtering for RAG: `app/services/llm_filter.py` — `MarkdownFilter` uses LangChain `ChatGoogleGenerativeAI` with model `gemma-3-27b-it` to keep only query‑relevant markdown sections.

- Crawler utilities:
  - Script: `scripts/run_crawler.py` — crawls site → saves per‑page markdown temp files → optionally applies LLM filter → prints combined markdown with `\n\n---\n\n` separators. Flags include `--max-depth`, `--keep-temp`, `--filter`, `--prompt`, `--include-links`.
  - Service: `app/services/crawler.py` — shared crawl logic used by API ingestion.

- Configuration: `app/config.py` (Pydantic v2 `BaseSettings`, loads `.env`)
  - Required: `database_url`, `jwt_secret_key`
  - Google: `google_api_key`
  - Embeddings: `embeddings_provider` (`local` default | `google`)
  - Optional: Redis, Supabase, SMTP/IMAP, environment.

## What’s implemented (with references)
- Admin‑first multi‑tenant architecture — admin controls onboarding & deployment (`app/routers/admin.py`, `client_config.py`).
- Website scraping → KB storage → vector indexing (`admin.trigger_website_scraping`, `knowledge_base` routes, `vector_store_service.py`).
- Optional LLM markdown filtering for RAG (`app/services/llm_filter.py`; also exposed in `scripts/run_crawler.py --filter`).
- Per‑client vector DB namespaces: `client_{client_id}` (`vector_store_service.py`).
- Chat endpoint with session + lead tracking (`app/routers/chat.py`).
- Tool‑assisted lead qualification & contact capture integrated in Gemini responses (`chat.py` via `GeminiService`).
- Email automation and monitoring (`app/routers/email_chat.py`, `app/services/email_service.py`, `app/services/email_monitor.py`).
- Client dashboard API (`app/routers/client_dashboard.py` — not detailed here) and authentication (`app/routers/auth.py`, `app/auth.py`).

## Backlog and next steps
- Vector maintenance
  - Implement per‑document vector delete/update for KB entries instead of rebuild‑all (see comments in `knowledge_base.py`).
  - Add metadata/versioning to vectors for precise updates.
- Crawler ergonomics
  - Add `--out` to write combined markdown to a file and `--export-dir` to persist per‑page markdowns.
  - Add domain/page allow/deny lists and sitemap ingestion.
- LLM filtering quality
  - Add structured rubric scoring and noise removal (nav/footer, cookie banners, boilerplate).
  - Add deterministic test cases under `tests/` for filter effectiveness.
- Observability
  - Centralize logs; add request IDs, rate‑limit metrics, vector recall metrics.
  - Move in‑memory rate limiting to Redis.
- Security & auth
  - Harden CORS, add API keys/roles per client, rotate JWT secret per env.
- Email
  - Improve threading and dedup; add bounce handling; DKIM/SPF guidance.

## Runbook
- Start API server
```bash
uvicorn app.main:app --reload --port 8000
```

- Trigger full ingestion for a client (admin‑protected)
```bash
# POST /admin/clients/{client_id}/scrape
```
Optional `user_prompt` tailors the LLM filtering behavior in the pipeline.

- Manually crawl from CLI (useful for previewing KB markdown)
```bash
python scripts/run_crawler.py https://example.com --max-depth 2 --filter \
  --prompt "Keep service descriptions, pricing, and contact details. Remove nav/footer."
```
Notes:
- Requires `GOOGLE_API_KEY` in `.env` for LLM filtering.
- Combined output prints to console with separators. Use `--keep-temp` to inspect per‑page files.

- Add KB content via API
```text
POST /api/admin/knowledge-base/client/{client_id}/add-markdown
POST /api/admin/knowledge-base/client/{client_id}/upload-file (.md/.txt)
POST /api/admin/knowledge-base/client/{client_id}/rebuild-vectors
GET  /api/admin/knowledge-base/client/{client_id}/search?query=...
```

- Deploy chatbot
```text
GET  /api/admin/client-config/client/{client_id}/deployment
PUT  /api/admin/client-config/client/{client_id}/system-prompts
POST /api/admin/client-config/client/{client_id}/generate-custom-id
POST /api/admin/client-config/client/{client_id}/deploy
```
Embed the deployed URL or use API chat endpoints.

- Chat API usage
```text
POST /api/chat/{custom_client_id}/message
GET  /api/chat/{custom_client_id}/history/{session_id}
```
Send `message` and optional `session_id`, `lead_name`, `lead_email`, `lead_phone`.

## Environment variables (.env)
Minimal local setup:
```
database_url=sqlite:///./local.db
jwt_secret_key=change_me

# Google AI for Gemini + LLM filtering
google_api_key=your_key

# Embeddings: local or google
embeddings_provider=local

# Optional email automation
smtp_server=...
smtp_port=587
email_user=...
email_password=...
email_from_name=LeadGenius AI
imap_server=...
imap_port=993
```

## Testing and examples
- API tests: `tests/test_api.py`
- E2E KB storage: `tests/e2e_kb_storage.py`
- Try: add markdown, rebuild vectors, search KB, then call chat endpoint and verify `context_used`, `tool_results`, and lead status transitions.

## Troubleshooting
- LLM filtering didn’t run in crawler
  - Ensure `--filter --prompt "..."` are passed and `GOOGLE_API_KEY` is set.
  - The script logs whether filtering was applied and prints a kept/total ratio.
- Vector results are poor
  - Verify ingestion ran and collection name is `client_{client_id}`; check `./chroma_db/` persists.
  - Consider switching to Google embeddings (`embeddings_provider=google`).
- Chat not returning context
  - Confirm KB vectors exist for the client and `custom_client_id` is deployed.
  - Check rate limiting (default in‑memory 10/minute per IP) in `chat.py`.
- Email not sending
  - Verify SMTP/IMAP settings; use `/api/admin/email-chat/monitoring-status`.

## Current model configuration
- Chat generation: `gemini-2.5-flash-lite` (`app/services/gemini_service.py`)
- LLM filtering: `gemma-3-27b-it` via LangChain `ChatGoogleGenerativeAI` (`app/services/llm_filter.py`)
- Embeddings: default local `all-MiniLM-L6-v2` (switchable via `embeddings_provider`)

---
This file should help you spin up a new chat, understand current capabilities, and identify improvement areas. Update as features evolve.