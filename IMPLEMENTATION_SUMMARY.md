# Implementation Summary — CIPilot

> Technical deep-dive into the implementation of each CIPilot component.  
> For setup, deployment, and usage instructions, see [README.md](README.md).

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Backend Implementation](#backend-implementation)
   - [FastAPI Application](#fastapi-application)
   - [LLM Integration](#llm-integration)
   - [Validation Engine](#validation-engine)
   - [Conversion Pipeline](#conversion-pipeline)
3. [Web Application Implementation](#web-application-implementation)
   - [Technology Stack](#technology-stack)
   - [State Management](#state-management)
   - [Key Components](#key-components)
   - [CI/CD Detection Logic](#cicd-detection-logic)
   - [GitHub API Integration](#github-api-integration)
   - [Pull Request Automation](#pull-request-automation)
4. [Chrome Extension Implementation](#chrome-extension-implementation)
5. [Infrastructure & Deployment](#infrastructure--deployment)
6. [Data Flow](#data-flow)
7. [Security Model](#security-model)

---

## System Overview

CIPilot is a three-tier application:

```
 User Browser                    Backend Server
┌───────────────────┐           ┌─────────────────────┐
│ React Web App     │──HTTP────▶│ FastAPI (Python)     │
│ (or Chrome Ext)   │◀─────────│                      │
│                   │           │ ┌─────────────────┐  │
│ - CI detection    │           │ │ LLM Providers   │  │
│ - Config fetching │           │ │ (Groq, OpenAI,  │  │
│ - UI rendering    │           │ │  Anthropic, etc)│  │
│ - PR creation     │           │ └────────┬────────┘  │
│                   │           │          │           │
│                   │           │ ┌────────▼────────┐  │
└───────┬───────────┘           │ │ actionlint      │  │
        │                       │ │ (Go binary)     │  │
        │ GitHub API            │ └─────────────────┘  │
        ▼                       └─────────────────────┘
┌───────────────────┐
│ GitHub REST API   │
│ - Repo contents   │
│ - Fork/Branch/PR  │
└───────────────────┘
```

**Key design decisions:**
- **Client-side CI detection:** The web app scans repositories via the GitHub API directly from the browser, reducing backend load.
- **Server-side LLM calls:** API keys are forwarded per-request; the backend orchestrates LLM calls and validation.
- **No persistent server storage:** All user data (settings, history, API keys) is stored in the browser (localStorage + IndexedDB).

---

## Backend Implementation

### FastAPI Application

**File:** `backend/main.py`

The backend is a stateless FastAPI server with three endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Health check |
| `/convert-cicd` | POST | Convert CI/CD config via LLM |
| `/retry-conversion` | POST | Retry with validation feedback |
| `/validate-github-actions` | POST | Validate YAML (PyYAML + actionlint) |

**CORS:** Configured with explicit allowed origins (production domains + localhost variants). `allow_credentials=False` to allow broad access without cookie issues.

**Request flow for `/convert-cicd`:**
1. Parse request (repository info, detected services, existing configs, LLM settings)
2. Determine source and target CI platforms
3. Combine all source configs into a single prompt
4. Call the configured LLM provider via `llm_converter.py`
5. Validate the output (PyYAML + actionlint)
6. If validation fails → retry once with error feedback
7. Return result with validation status and attempt count

### LLM Integration

**File:** `backend/llm_converter.py`

The LLM converter supports 7 provider backends through a unified interface:

| Provider | API Format | Function |
|----------|-----------|----------|
| Ollama | `/api/generate` (native) | `_ollama_generate()` |
| OpenAI | `/v1/chat/completions` | `_openai_compatible_chat()` |
| Groq | OpenAI-compatible | `_openai_compatible_chat()` |
| xAI | OpenAI-compatible | `_openai_compatible_chat()` |
| Generic | OpenAI-compatible | `_openai_compatible_chat()` |
| Anthropic | `/v1/messages` (native) | `_anthropic_chat()` |
| Google | `/v1/models/.../generateContent` | `_google_chat()` |

**Prompt engineering:**
- `_build_prompt()` constructs a structured prompt with:
  - System role as "CI/CD migration expert"
  - Critical requirements (output only valid YAML, no markdown, no code blocks)
  - Common fix patterns (services as mappings, action versions, shell syntax)
  - Multi-service consolidation notes (when multiple CI configs are provided)
  - Previous validation feedback (for retry attempts)

**Output sanitisation:**
- Strips markdown code fences (` ```yaml ` / ` ``` `)
- `_detect_wrong_format()` validates that the output is the target format (not the source accidentally echoed back)

### Validation Engine

**Validation is two-stage:**

1. **PyYAML parse** (`_validate_yaml()`):
   - Uses `yaml.safe_load()` to check syntactic validity
   - Catches malformed YAML before sending to actionlint

2. **actionlint** (`_run_actionlint()`):
   - Writes YAML to a temporary file
   - Runs `actionlint <file>` as a subprocess (30-second timeout)
   - Analyses output severity:
     - Syntax errors, expression errors, type errors → **fail**
     - Info-level shellcheck suggestions → **pass** (with note)
   - Graceful fallback if actionlint is not installed (returns error message, does not crash)

### Conversion Pipeline

**Full pipeline for `/convert-cicd`:**

```
Request → Determine platforms → Combine configs → Build prompt
    → Call LLM → Validate output
    → If invalid: Build retry prompt with errors → Call LLM again → Validate
    → Return result (config + validation + attempts)
```

**Retry endpoint (`/retry-conversion`):**
- Accepts the previous failed attempt, original config, and error feedback
- Constructs a comprehensive prompt that includes the broken YAML and specific errors
- Increments `currentAttempts` counter for tracking

---

## Web Application Implementation

### Technology Stack

| Technology | Version | Purpose |
|-----------|---------|---------|
| React | 18.3 | UI framework |
| TypeScript | 5.6 | Type safety |
| Vite | 6.0 | Build tool and dev server |
| Tailwind CSS | 3.4 | Utility-first styling |
| Monaco Editor | 4.6 | Code editor (YAML editing with syntax highlighting) |
| React Router | 6.22 | Client-side routing |
| Axios | 1.6 | HTTP client |
| Dexie | 4.0 | IndexedDB wrapper (migration history) |
| Lucide React | 0.323 | Icon library |

### State Management

CIPilot uses React Context for global state, with persistence to browser storage:

| Context | Purpose | Persistence |
|---------|---------|-------------|
| `SettingsContext` | LLM provider, model, API keys, GitHub PAT | IndexedDB (via Dexie) |
| `MigrationContext` | Current migration state (source/target configs, validation) | In-memory (React state) |
| `ThemeContext` | Dark/light mode preference | localStorage |
| `ToastContext` | Toast notification queue | In-memory |

**Data persistence layers:**
- `store/indexedDB.ts` — Dexie-based IndexedDB for migration history and settings
- `store/localStorage.ts` — localStorage for simple key-value preferences

### Key Components

#### `pages/HomePage.tsx`
- Main entry point: repo URL input, CI/CD detection, service display, conversion trigger
- Calls GitHub API to scan repository tree for CI/CD config files
- Handles rate limit detection (403 → suggests adding GitHub PAT)
- Manages the full flow from repo input → detection → conversion

#### `components/migration/ConversionPanel.tsx`
- Side-by-side view: original config (left) vs. generated config (right)
- Right pane uses Monaco Editor for syntax-highlighted, editable YAML
- Validation status badges (YAML ✅/❌, actionlint ✅/❌, attempt count)
- Action buttons: Validate, Retry, Copy, Create PR, Close
- Handles retry logic with feedback from validation errors

#### `components/migration/RepoInput.tsx`
- GitHub repository URL input with auto-parsing (owner/name extraction)
- Example repository suggestions (repos with known CI/CD configs)
- URL validation and error states

#### `components/migration/PRCreationDialog.tsx`
- GitHub Pull Request creation workflow
- Permission detection (push access → direct branch, no access → fork)
- Progress tracking through fork/branch/commit/PR steps
- Opens created PR in new tab

#### `components/migration/ValidationStatus.tsx`
- Renders validation badges (YAML parse, actionlint, attempt count)
- Color-coded: green for pass, red for fail
- Expandable details showing actionlint output

#### `components/settings/SettingsModal.tsx`
- LLM provider selection (dropdown)
- Model name input with defaults per provider
- API key input (masked, with show/hide toggle)
- GitHub PAT configuration
- Export/import settings functionality

### CI/CD Detection Logic

**Client-side detection flow (in `HomePage.tsx`):**

1. Parse the GitHub URL → extract `owner` and `repo`
2. Fetch repository tree via GitHub API (`GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1`)
3. Match file paths against known CI/CD config patterns:
   ```
   .github/workflows/*.yml     → GitHub Actions
   .travis.yml                 → Travis CI
   .circleci/config.yml        → CircleCI
   .gitlab-ci.yml              → GitLab CI
   Jenkinsfile                 → Jenkins
   ...
   ```
4. For each detected service, fetch the config file content via GitHub API
5. Display detected services as chips with file details

**Rate limit handling:**
- Detects GitHub API 403 responses with rate limit headers
- Shows user-friendly message suggesting PAT configuration
- With PAT: 5,000 requests/hour; without: 60 requests/hour

### GitHub API Integration

**File:** `web/src/api/github.ts`

Two modes of GitHub API access:

1. **Unauthenticated:** 60 requests/hour, public repos only
2. **Authenticated (PAT):** 5,000 requests/hour, includes private repos

API calls:
- `GET /repos/{owner}/{repo}` — Repository metadata
- `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1` — Full file tree
- `GET /repos/{owner}/{repo}/contents/{path}` — File content (Base64)

### Pull Request Automation

**Implemented in `ConversionPanel.tsx` and `PRCreationDialog.tsx`:**

**Permission-aware workflow:**
```
Check push access (GET /repos/{owner}/{repo})
├── Has push access:
│   1. Create branch: POST /repos/{owner}/{repo}/git/refs
│   2. Create/update file: PUT /repos/{owner}/{repo}/contents/.github/workflows/ci.yml
│   3. Create PR: POST /repos/{owner}/{repo}/pulls
│
└── No push access:
    1. Fork repo: POST /repos/{owner}/{repo}/forks
    2. Wait for fork ready (poll GET /repos/{user}/{repo})
    3. Create branch on fork
    4. Create/update file on fork
    5. Create cross-fork PR: POST /repos/{owner}/{repo}/pulls
       (head: {user}:{branch}, base: {default_branch})
```

**Required PAT scopes:**
- Classic PAT: `repo` + `workflow`
- Fine-grained PAT: Contents (R/W) + Actions/Workflows (R/W)

---

## Chrome Extension Implementation

**Directory:** `src/` (Manifest V3)

| File | Purpose |
|------|---------|
| `manifest.json` | Extension configuration: permissions, content scripts, popup, options |
| `background.js` | Service worker: GitHub API calls, fork/branch/commit/PR automation |
| `content.js` | Injected into GitHub pages: CI detection, banner, conversion modal |
| `ciDetection.js` | CI/CD file pattern matching on GitHub DOM |
| `banner.js` | Top-of-page banner for repos without CI/CD |
| `popup/popup.js` | Extension popup: shows detected services and quick actions |
| `options/options.js` | Settings page: LLM provider/model/key configuration |

**Content script injection:**
- Matches `*://github.com/*`
- Scans the GitHub file tree for CI/CD config patterns
- Injects a banner if no CI/CD is detected
- Provides a conversion modal with side-by-side view

**Settings storage:** `chrome.storage.local` (persists across sessions)

---

## Infrastructure & Deployment

### Docker Images

**Backend (`backend/Dockerfile`):**
```
python:3.11-slim
├── System deps: ca-certificates, curl, tar
├── actionlint v1.6.26 (Linux amd64 binary)
├── Python deps: FastAPI, uvicorn, pydantic, requests, pyyaml
└── CMD: uvicorn main:app --host 0.0.0.0 --port 5200
```

**Frontend (`web/Dockerfile`):**
```
Stage 1: node:20-alpine (build)
├── npm ci
├── npm run build → dist/
│
Stage 2: nginx:alpine (serve)
├── Copy dist/ to /usr/share/nginx/html
├── Copy nginx.conf (SPA routing + /api proxy)
└── CMD: nginx -g daemon off
```

### Render.com Blueprint (`render.yaml`)

```yaml
services:
  - type: web          # Backend
    name: cipilot-api
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    dockerContext: ./backend

  - type: web          # Frontend
    name: cipilot-web
    runtime: static
    buildCommand: cd web && npm install && npm run build
    staticPublishPath: ./web/dist
    envVars:
      - key: VITE_API_URL
        value: https://cipilot-api.onrender.com
```

### Docker Compose (`docker-compose.yml`)

- Frontend (port 3000) → Nginx with `/api` proxy to backend
- Backend (port 5200) → FastAPI with actionlint
- Shared bridge network
- Ollama host configurable via environment variable

---

## Data Flow

### Complete Migration Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. USER ENTERS REPO URL                                     │
│    e.g., github.com/checkstyle/checkstyle                   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. CLIENT-SIDE CI DETECTION                                  │
│    GitHub API → Fetch repo tree → Match CI patterns          │
│    Result: ["Travis CI"] with .travis.yml content            │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. LLM CONVERSION (Backend)                                  │
│    POST /convert-cicd                                        │
│    → Build prompt with source configs                        │
│    → Call LLM (e.g., Groq llama-3.3-70b)                    │
│    → Receive GitHub Actions YAML                             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. VALIDATION (Backend)                                      │
│    → PyYAML parse check                                      │
│    → actionlint structural check                             │
│    → If errors: auto-retry with feedback (attempt 2)         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. USER REVIEW (Client)                                      │
│    → Side-by-side view (original ↔ generated)                │
│    → Validation badges (YAML ✅, actionlint ✅)              │
│    → Edit, Validate, Retry, Copy, or Create PR               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. PR CREATION (Client → GitHub API)                         │
│    → Check permissions → Fork if needed                      │
│    → Create branch → Commit workflow file → Open PR          │
└─────────────────────────────────────────────────────────────┘
```

---

## Security Model

| Concern | Approach |
|---------|----------|
| **API key storage** | Browser-only (IndexedDB). Never stored on server. |
| **API key transmission** | Sent per-request to CIPilot backend over HTTPS. Backend forwards to LLM provider. |
| **GitHub PAT** | Stored in browser. Used client-side for GitHub API calls (repo detection, PR creation). |
| **CORS** | Backend allows only specific origins (production domains + localhost). |
| **No authentication** | CIPilot backend is stateless and requires no user accounts. |
| **Docker security** | Non-root user, minimal base images, health checks, `.dockerignore` for build context. |
| **Extension permissions** | Minimal Manifest V3 permissions: `activeTab`, `scripting`, `storage`. Host permissions scoped to `github.com` and `localhost:5200`. |
