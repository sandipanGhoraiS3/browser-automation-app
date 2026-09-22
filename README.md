# Orbit â€” local AI browser agent

A local React + FastAPI application that connects an AI provider to real Playwright MCP tools. Every conversation owns a separate MCP process and isolated browser context. Workspaces isolate history, skills, files, agent state, and browser artifacts. SQLite stores chat history; WebSockets stream model text, action status, confirmations, and screenshot updates.

## Requirements

- Python 3.11 or newer (tested here on Python 3.14).
- Node.js 20.19+ or 22.12+ (tested on Node 24).
- Chrome/Edge installed, or Playwright Chromium downloaded.
- Credentials for Azure OpenAI, OpenAI, or Anthropic. The interface defaults to Azure OpenAI.

The app runs locally, but selected AI APIs require internet access and may incur usage charges. Prompts and browser observations go to that provider. There is no hosting or cloud application infrastructure.

## First-time setup

From `browser-agent`:

```powershell
npm install
npm run install:browser
Copy-Item .env.example .env
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd ../frontend
npm install
```

On macOS/Linux use `cp .env.example .env` and `source .venv/bin/activate`. Do not overwrite an existing configured `.env`.

For Azure OpenAI, edit these fields in `.env` locally:

```dotenv
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your-chat-model-deployment-name
AZURE_OPENAI_API_VERSION=2024-10-21
```

Use the API version supported by your Azure deployment. The deployment must support Chat Completions, streaming, and tool calls. Temperature defaults to 0; models that prohibit temperature overrides need an appropriate compatible deployment. GPT and Claude adapters share the same agent architecture.

Alternatively configure `OPENAI_API_KEY` and `OPENAI_MODEL`, or `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. Select the provider in the header at runtime. Restart the backend after changing `.env`; it is outside the backend reload directory. Never paste credentials into chat.

## Start the application

Terminal 1, from `browser-agent/backend`:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --port 8000
```

Terminal 2, from `browser-agent/frontend`:

```powershell
npm run dev
```

Open http://127.0.0.1:5173. Backend API docs: http://localhost:8000/docs.

## Azure RAG knowledge

The Knowledge Center adds workspace/domain-isolated document ingestion, Cosmos DB native vector retrieval, grounded chat answers, and source previews using Azure Blob Storage plus Azure Cosmos DB for NoSQL. Configure the RAG variables in .env, restart the backend, and use **Knowledge** in the workspace sidebar.

See [docs/AZURE_RAG.md](docs/AZURE_RAG.md) for Azure requirements, safe initialization, schema/index policy, environment variables, flows, APIs, security, and troubleshooting.

Create a conversation to open its browser, then ask: `Open Google and search for Playwright MCP.` Follow with `Open the first result.` The same browser stays open. The Stop button cancels the run and pending MCP request without disconnecting the browser. A browser action already completed cannot be undone by Stop.

Say `close browser`, `close the browser`, `exit browser`, or `terminate browser` to close it. Deleting a conversation, stopping the backend, and the configured idle timeout also close the associated browser. Active runs are exempt from idle cleanup. History survives a backend restart; live browser processes do not.

## Workspaces and parallel tasks

Use the workspace selector below the Orbit logo to create or switch workspaces. The Default workspace keeps all legacy paths and behavior. Additional workspaces keep conversations, skills, internal files, browser sessions, and generated/downloaded files separate; their exported files remain under `Downloads/Orbit Workspaces/<workspace-id>`.

For a large task with two to four independent parts, the main agent can launch specialized research, browser, knowledge, or file-analysis sub-agents concurrently. Each sub-agent inherits only the active workspace, uses its own browser session, cannot recursively launch more agents, and cannot perform actions that require user confirmation. The main agent waits for all required results, preserves individual failures as structured results, and produces one combined response. Simple conversations and dependent steps stay on the normal sequential path.
## Configuration

See `.env.example` for all values:

| Variable | Purpose |
| --- | --- |
| `MAX_AGENT_STEPS` | Maximum model decisions per run; default 50 |
| `MAX_TOOL_RETRIES` | Maximum repeated retries of identical failed arguments; default 2 |
| `SESSION_IDLE_TIMEOUT` | Idle browser lifetime in seconds; default 3600 |
| `TEMPERATURE` | Provider temperature; default 0 |
| `HEADLESS` | Set true to hide automation browsers; default false |
| `BROWSER_EXECUTABLE_PATH` | Optional explicit Chrome/Chromium/Edge executable |
| `PLAYWRIGHT_MCP_COMMAND` | Local MCP launcher; default npx |
| `PLAYWRIGHT_MCP_PACKAGE` | Installed package; default @playwright/mcp |

The default launcher uses the installed package's Node CLI directly, avoiding shell interpolation and runtime package downloads. A custom launcher must accept `--no-install <package>` followed by MCP arguments. The project lockfile pins the tested package version (0.0.81). Run `npm ci` for reproducible installs.

## Architecture

```text
React chat â†’ FastAPI â†’ provider adapter â†’ agent loop
                                         â†“
                     per-conversation MCP client/process
                                         â†“
                              isolated real browser
```

- `backend/app/agent`: provider streaming, tool execution, dedicated system prompt.
- `backend/app/mcp`: process start/stop/restart/health and persistent HTTP MCP client.
- `backend/app/browser`: current snapshot, tabs, viewport screenshots.
- `backend/app/sessions`: cancellation, events, lifetime and idle cleanup.
- `backend/app/database`: SQLite conversations, messages, runs, tool-call audit.
- `frontend/src`: responsive three-panel UI, activity cards, settings and approval prompts.
- `data/sessions/<id>/screenshots/latest.png`: current preview; generated MCP artifacts have a size cap.

Tools and schemas come from MCP discovery. Main-agent execution remains sequential; only explicitly independent sub-agent tasks run concurrently. Snapshots refresh before each decision and after actions. References are checked against the latest snapshot; arbitrary selectors are not accepted in reference/target arguments. Failed tools return errors plus a fresh observation to the model. No website-specific action logic exists.

## Local security and limitations

Keep both servers bound to loopback. Requests from other browser origins are rejected. This is a single-user local app, not an authenticated network service. API keys stay in the backend and are excluded from the MCP child environment. Common credential patterns and configured keys are redacted before chat persistence; redaction is not a general-purpose secret detector. Enter passwords directly into the visible browser. Screenshots and visited page content may contain private information.

The agent requests confirmation for high-impact actions. A keyword-based fallback also intercepts likely submissions, purchases, messages, deletion, and page evaluation. This is a basic MVP mechanism, not a complete semantic security boundary; inspect important actions. Page content is treated as untrusted in the agent instructions.

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tests.smoke_browser
cd ../frontend
npm run build
npm run lint
npm run typecheck
cd ..
node tests/ui-smoke.mjs
```

The UI test needs both servers running. The browser smoke test starts a local fixture site and actual MCP/Chrome sessions, testing navigation, fresh snapshots, typing, clicking, screenshots, cancellation, isolation and cleanup. It does not substitute for an LLM test. The UI test checks the real app, WebSocket delivery and persistence without requiring provider credentials.

## Troubleshooting

- **Provider not configured:** fill the chosen provider's `.env` fields and restart FastAPI. A ChatGPT subscription is not an Azure/OpenAI API credential.
- **Azure 404:** verify resource endpoint, deployment name and API version. Deployment name is not necessarily the underlying model name.
- **MCP unavailable:** run `npm install` in `browser-agent`, not only in `frontend`. Verify `node --version` and `node node_modules/@playwright/mcp/cli.js --help`.
- **Browser download stalls:** install/use Chrome or Edge, or set `BROWSER_EXECUTABLE_PATH`. The app automatically falls back to standard Windows Chrome/Edge locations when downloaded Chromium is unavailable.
- **403 from MCP:** version 0.0.81 checks the complete Host header including port. The process manager supplies the precise loopback host:port allowlist. Do not replace it with a wildcard.
- **UI says backend unavailable:** check http://localhost:8000/api/health. Keep frontend on port 5173, which is the allowed origin.
- **Old references fail:** let the agent inspect again; manual browser interactions may change the DOM while the model is deciding.
- **Shutdown:** Ctrl+C in the backend terminal closes its MCP/browser process trees. Ctrl+C in the frontend terminal stops Vite. Do not use multiple backend workers because live sessions are held in memory.

Implementation references: [Playwright MCP](https://github.com/microsoft/playwright-mcp), [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [Anthropic streaming](https://platform.claude.com/docs/en/build-with-claude/streaming).

