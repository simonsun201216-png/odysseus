# ODYSSEUS — AI Workspace

**Stack**: Python 3.12 + FastAPI + SQLite (SQLAlchemy) + Vanilla JS SPA + MCP

The primary user-facing AI interface. 1019 files, ~197K lines. Runs in Docker on port 7000.

## Structure

```
odysseus/
├── app.py                 # FastAPI entry (1170 lines) — lifespan, CORS, auth, static, 50+ routers
├── core/                  # Framework layer
│   ├── constants.py       # Paths, timeouts, API keys
│   ├── database.py        # SQLAlchemy models (93KB) — User, Session, ChatMessage, etc.
│   ├── auth.py            # AuthManager — password hashing, token validation
│   ├── middleware.py      # CSP nonce, security headers, internal-tool auth
│   ├── exceptions.py      # Custom error types
│   └── session_manager.py # Session lifecycle
├── src/                   # Engine (89 files)
│   ├── agent_loop.py      # Main agent orchestration loop (158KB)
│   ├── llm_core.py        # LLM provider routing + streaming (OpenAI, Ollama, etc.)
│   ├── tool_*.py          # Tool system (execution, schemas, implementations, security, index)
│   │   ├── tool_implementations.py  # (203KB) — all built-in tools
│   │   ├── tool_schemas.py          # Tool parameter schemas
│   │   ├── tool_execution.py        # Tool sandbox & runner
│   │   └── tool_index.py            # RAG-indexed tool discovery
│   ├── chat_processor.py  # Chat pipeline (context, tool selection, response gen)
│   ├── chat_handler.py    # Streaming handler (SSE)
│   ├── deep_research.py   # Background multi-source research tasks
│   ├── task_scheduler.py  # Cron scheduler (108KB) — built-in actions + event bus
│   ├── memory*.py         # Short-term + vector memory
│   ├── orchestrator.py    # Multi-agent hedge fund research team
│   ├── mcp_manager.py     # MCP server lifecycle (connect/discover/disconnect)
│   ├── ai_interaction.py  # Debates, pipelines, self-managing AI, UI control
│   ├── rag_manager.py     # ChromaDB + fastembed (local ONNX)
│   ├── personal_docs.py   # Personal documents CRUD
│   ├── context_compactor.py # Token budget management
│   ├── settings.py        # Dynamic user settings
│   └── visual_report.py   # HTML research report rendering (71KB)
├── routes/                # 54 route files
│   ├── auth_routes.py     # Login/signup/sessions
│   ├── chat_routes.py     # Chat + streaming
│   ├── email_routes.py    # IMAP/SMTP (155KB — largest route file)
│   ├── calendar_routes.py # CalDAV (57KB)
│   ├── cookbook_routes.py # Model download/serve/cache (122KB)
│   ├── model_routes.py    # Model discovery/provisioning (93KB)
│   ├── gallery_routes.py  # Image gallery (80KB)
│   ├── skills_routes.py   # Skills management (77KB)
│   ├── codex_routes.py    # Codex/Claude integration
│   └── ... (45 more)
├── services/              # External integrations
│   ├── data_sync/         # Prophetis meeting sync (WebDAV → Supabase)
│   ├── search/            # Web search (SearXNG, Google, Bing)
│   ├── skills_discovery/  # GitHub skills discovery
│   ├── hwfit/             # Hardware model fitting calculator
│   ├── tts/               # Text-to-speech
│   ├── stt/               # Speech-to-text (whisper)
│   └── youtube/           # YouTube transcript
├── mcp_servers/           # 5 built-in MCP servers
│   ├── email_server.py    # Email MCP tools (66KB)
│   ├── memory_server.py   # Memory MCP tools
│   ├── rag_server.py      # RAG MCP tools
│   ├── image_gen_server.py
│   └── _common.py         # Shared MCP server utilities
├── prophetis_research/    # 🌟 Finance research agent system (has own AGENTS.md)
├── static/                # Vanilla JS SPA frontend
│   ├── index.html         # SPA entry
│   ├── app.js             # Main app (176KB)
│   ├── style.css          # 1.1MB — all styles
│   └── js/                # 40+ ES modules
├── companion/             # Device pairing (routes + pairing logic)
├── integrations/          # Claude/Codex integration bridges
└── config/                # SearXNG settings
```

## WHERE TO LOOK

| Task | Path | Notes |
|------|------|-------|
| Add route/endpoint | `routes/` | `setup_*_routes()` factory pattern |
| Add AI tool | `src/tool_implementations.py` + `src/tool_schemas.py` | Register in tool_index |
| Modify LLM routing | `src/llm_core.py` + `routes/model_routes.py` | Provider detection + streaming |
| Modify agent loop | `src/agent_loop.py` | The main agent orchestration logic |
| Add chat feature | `src/chat_processor.py` + `routes/chat_routes.py` | |
| Fix auth | `core/auth.py` + `routes/auth_routes.py` | AUTH_ENABLED, LOCALHOST_BYPASS |
| DB schema change | `core/database.py` | SQLAlchemy ORM models |
| Add MCP server | `mcp_servers/` + `src/mcp_manager.py` | Built-in vs user MCP |
| Modify frontend | `static/` (JS modules) + `static/index.html` | No build step |
| Research feature | `src/deep_research.py` + `routes/research_routes.py` | |
| Email integration | `routes/email_routes.py` + `routes/email_pollers.py` | IMAP/SMTP + idle polling |
| Scheduled tasks | `src/task_scheduler.py` + `src/builtin_actions.py` | Cron-like event system |

## CONVENTIONS

- **Route pattern**: `setup_*_routes(deps) → APIRouter` (factory functions in `routes/`)
- **Component init**: Managers created in `src/app_initializer.py`, injected into routes
- **DB**: SQLAlchemy with `SessionLocal` thread-local sessions
- **Auth modes**: Cookie sessions, Bearer API tokens (`ody_*`), internal-tool header bypass
- **Streaming**: SSE for chat, research, shell — exempt from request timeout
- **Lifecycle**: Modern `asynccontextmanager` lifespan (not legacy `@app.on_event`)
- **Error handling**: Custom exception classes → global exception handlers
- **MIME types**: Forced JS module MIME types at startup for Windows compat
- **Startup warmup**: Pre-warms tool index, LLM endpoints, keepalive pings every 60s

## ANTI-PATTERNS

- **No test framework** — pytest/pytest-asyncio listed in pyproject.toml but no test directory
- **Large route files** — email_routes.py (155KB), cookbook_routes.py (122KB), chat_routes.py (76KB)
- **Monolithic app.py** — 1170 lines with all component wiring + middleware inline
- **SQLite in production** — single-file DB, no replication
- **Vanilla JS SPA** — no framework, no build step, manual state management

## UNIQUE STYLES

- Hedge fund multi-agent orchestrator (`src/orchestrator.py`) with crew members
- Prophetis meeting intelligence sync via WebDAV → Supabase pipeline
- Hardware model fitting calculator for local LLM deployment planning
- Nightly skill audit system that auto-tests and judges skills
- Built-in MCP servers for email, memory, RAG, image generation
- CSP nonce injection for all HTML responses
