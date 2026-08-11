<!-- ============================================================
     AI-Powered Synthetic Test Data Generator — Project README
     ============================================================ -->

<p align="center">
  <img src="frontend/public/vite.svg" alt="Logo" width="64" />
</p>

<h1 align="center">AI-Powered Synthetic Test Data Generator</h1>

<p align="center">
  <b>Intelligent, constraint-aware test data generation from SQL schemas, OpenAPI specs, and BDD feature files.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/TailwindCSS-4.3-38BDF8?logo=tailwindcss&logoColor=white" alt="Tailwind" />
  <img src="https://img.shields.io/badge/tests-396%20passing-brightgreen" alt="Tests" />
</p>

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup Instructions](#setup-instructions)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Documentation](#api-documentation)
- [Module Reference](#module-reference)
- [Demo Flow](#demo-flow)
- [Screenshots](#screenshots)
- [Testing](#testing)
- [Future Improvements](#future-improvements)

---

## Problem Statement

Manual test data creation is **time-consuming**, **error-prone**, and **difficult to scale** — especially when datasets must respect foreign-key relationships, check constraints, regex patterns, and business rules.

This platform **automates** the entire process: upload your schema, configure the options, and receive validated, constraint-aware synthetic datasets — including edge cases and negative test scenarios — in seconds.

---

## Key Features

| Category | Capabilities |
|----------|-------------|
| **Schema Parsing** | SQL DDL parsing (tables, columns, PKs, FKs, unique, check, not-null constraints) via **sqlglot** |
| **OpenAPI Parsing** | Swagger / OpenAPI 3.x — required fields, enums, regex patterns, min/max validation |
| **BDD Understanding** | Gherkin `.feature` files — scenario parsing, business-rule extraction |
| **Relationship Graph** | Directed dependency graph via **networkx** — topological sort for parent-first generation |
| **Synthetic Generation** | Realistic values via **Faker** — names, emails, phones, UUIDs, dates, addresses |
| **Negative Cases** | Invalid formats, null violations, duplicate PKs, broken FKs, boundary values, bad enums |
| **AI Reasoning** | Gemini / OpenAI — infers hidden constraints, interprets BDD rules, suggests edge cases |
| **Validation Engine** | PK uniqueness, FK integrity, type checks, enum compliance, regex verification |
| **Multi-Format Export** | CSV, JSON, SQL INSERT — all packaged as ZIP downloads |
| **Modern Frontend** | React 19 + Tailwind CSS 4 — drag-and-drop upload, live stats, data preview, one-click download |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend (5173)                    │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────────────┐ │
│  │  Upload   │→ │  Parse   │→ │   Results & Downloads      │ │
│  │  Page     │  │  Step    │  │   Page                     │ │
│  └──────────┘  └──────────┘  └────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────┘
                         │ /api proxy
┌────────────────────────▼────────────────────────────────────┐
│                  FastAPI Backend (9000)                       │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│  │ Parsers  │→ │ Relation │→ │ Generator │→ │ Validator │  │
│  │ SQL      │  │ Engine   │  │ Synthetic │  │ PK/FK/    │  │
│  │ OpenAPI  │  │ (DAG)    │  │ Negative  │  │ Type/Enum │  │
│  │ BDD      │  │          │  │ Boundary  │  │ Regex     │  │
│  └──────────┘  └──────────┘  └───────────┘  └─────┬─────┘  │
│                                                     │        │
│  ┌──────────┐  ┌──────────┐                         │        │
│  │ AI Layer │  │ Exporter │←────────────────────────┘        │
│  │ Gemini / │  │ CSV/JSON │                                  │
│  │ OpenAI   │  │ SQL/ZIP  │                                  │
│  └──────────┘  └──────────┘                                  │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Uploads Files  →  Parser Layer  →  Metadata Extraction
        →  Relationship Graph (topological sort)
        →  AI Reasoning (optional — hidden constraints & edge cases)
        →  Synthetic Data Generator
        →  Validation Engine
        →  Export Engine  →  Download ZIP
```

**Generation Order Example:**

```
Customer → Policy → Claim → Payment
```

Tables are generated parent-first so every foreign key reference points to an existing row.

---

## Tech Stack

### Backend

| Component | Technology | Version |
|-----------|-----------|---------|
| Web Framework | FastAPI | 0.136.1 |
| Runtime | Python | 3.11 |
| ASGI Server | Uvicorn | 0.46.0 |
| SQL Parsing | sqlglot | 30.7.0 |
| Data Generation | Faker | 40.15.0 |
| Graph Processing | networkx | 3.6.1 |
| Data Validation | Pydantic | 2.13.4 |
| Data Processing | pandas | 3.0.2 |
| AI (Google) | google-generativeai | 0.8.6 |
| YAML Parsing | PyYAML | 6.0.3 |

### Frontend

| Component | Technology | Version |
|-----------|-----------|---------|
| UI Framework | React | 19.2.6 |
| Build Tool | Vite | 8.0.12 |
| CSS Framework | Tailwind CSS | 4.3.0 |
| HTTP Client | Axios | 1.16.0 |
| Routing | React Router | 7.15.0 |

---

## Project Structure

```
synthetic-data-ai/
│
├── backend/
│   └── app/
│       ├── main.py                 # FastAPI app entry point
│       ├── routers/
│       │   ├── health.py           # GET /health
│       │   ├── pipeline.py         # Unified session pipeline
│       │   ├── parse.py            # Standalone parse endpoints
│       │   ├── generate.py         # Standalone generation endpoints
│       │   ├── validate.py         # Validation endpoint
│       │   ├── export.py           # Export endpoints
│       │   └── ai.py              # AI reasoning endpoints
│       ├── parsers/
│       │   ├── sql_parser.py       # SQL DDL → SchemaMetadata
│       │   ├── openapi_parser.py   # OpenAPI/Swagger → OpenAPIMetadata
│       │   └── bdd_parser.py       # Gherkin → BDDMetadata
│       ├── generators/
│       │   ├── synthetic_generator.py  # Valid data generation
│       │   └── negative_generator.py   # Invalid/edge-case generation
│       ├── validators/
│       │   └── validators.py       # PK, FK, Type, Enum, Regex checks
│       ├── exporters/
│       │   └── engine.py           # CSV, JSON, SQL INSERT export + ZIP
│       ├── ai/
│       │   ├── service.py          # AI orchestration
│       │   ├── gateway_provider.py # Generic HTTP AI gateway
│       │   ├── offline_provider.py # Fallback when no API key
│       │   ├── output_parser.py    # Parse AI JSON responses
│       │   └── prompts.py          # AI prompt templates
│       ├── services/
│       │   ├── session_store.py    # In-memory session management
│       │   └── relationship_engine.py  # FK dependency graph
│       ├── models/
│       │   ├── schema.py           # Core: Column, FK, Table, Schema
│       │   ├── pipeline.py         # Pipeline request/response models
│       │   ├── export.py           # Export format models
│       │   ├── ai.py               # AI constraint/edge-case models
│       │   ├── validation.py       # Validation report models
│       │   ├── negative.py         # Negative test case models
│       │   ├── openapi.py          # OpenAPI metadata models
│       │   └── bdd.py              # BDD scenario models
│       ├── converters/
│       │   ├── openapi_to_schema.py    # OpenAPI → SchemaMetadata
│       │   └── bdd_to_schema.py        # BDD rules → SchemaMetadata
│       ├── middleware/
│       │   └── error_handler.py    # Global exception handling & logging
│       └── utils/
│           ├── config.py           # Environment-based settings
│           └── sql_types.py        # Shared SQL type mapping utilities
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js              # Dev server + API proxy
│   └── src/
│       ├── main.jsx                # React entry point
│       ├── App.jsx                 # Router (Upload / Results)
│       ├── services/
│       │   └── api.js              # Axios client + retry logic
│       ├── pages/
│       │   ├── UploadPage.jsx      # File upload + generation config
│       │   └── ResultsPage.jsx     # Stats, validation, preview, download
│       └── components/
│           ├── FileDropzone.jsx    # Drag-and-drop file selector
│           ├── Card.jsx            # Card / CardHeader / CardBody
│           ├── Button.jsx          # Variant button (primary/success/danger)
│           ├── Badge.jsx           # Status badge
│           ├── Alert.jsx           # Info/success/warning/error alert
│           ├── Spinner.jsx         # Loading spinner
│           ├── StatCard.jsx        # Metric display card
│           └── Navbar.jsx          # Navigation bar
│
├── PROJECT_REQUIREMENTS.md
├── ARCHITECTURE.md
├── docker-compose.yml
└── README.md
```

---

## Setup Instructions

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** and **npm**
- (Optional) Google Gemini API key or OpenAI API key for AI features

### 1. Clone the Repository

```bash
git clone <repository-url>
cd synthetic-data-ai
```

### 2. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r app/requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend
npm install
```

---

## Render Deployment

This project is configured to deploy with Render using `render.yaml`.

### Backend service
- `Root directory`: `backend`
- `Dockerfile`: `backend/Dockerfile`
- Set `CORS_ORIGINS=https://<your-frontend>.onrender.com`
- Optional: set `GEMINI_API_KEY`, `OPENAI_API_KEY`, `AI_GATEWAY_URL`, `AI_GATEWAY_TOKEN`

### Frontend service
- `Root directory`: `frontend`
- `Dockerfile`: `frontend/Dockerfile`
- Set `VITE_API_BASE=https://<your-backend>.onrender.com/api`

> Replace `<your-backend>.onrender.com` and `<your-frontend>.onrender.com` with your actual Render service URLs.

### Example Render command

```bash
render deploy --service synthetic-data-backend
render deploy --service synthetic-data-frontend
```

---

## Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# ── Core ──────────────────────────────────────────
APP_NAME=Synthetic Data Generator
APP_VERSION=0.1.0
DEBUG=false
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO

# ── AI Configuration (optional) ──────────────────
GEMINI_API_KEY=your_gemini_key_here
OPENAI_API_KEY=your_openai_key_here
AI_GATEWAY_URL=
AI_GATEWAY_TOKEN=
AI_MODEL=claude-opus-4-6
AI_API_FORMAT=openai
AI_TIMEOUT=30
AI_MAX_RETRIES=3
```

> **Note:** AI features work in offline/fallback mode when no API keys are set. The platform is fully functional without AI — it simply skips the AI reasoning step.

---

## Running the Application

### Start the Backend (port 8000)

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Start the Frontend (port 5173)

```bash
cd frontend
npm run dev
```

The frontend proxies `/api` requests to `http://127.0.0.1:8000`, so both servers must be running.

**Open in browser:** [http://localhost:5173](http://localhost:5173)

**API docs (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## API Documentation

### Pipeline Endpoints (Unified Workflow)

The pipeline API manages session-based workflows: upload → parse → generate → download.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/upload` | Upload SQL, OpenAPI, and/or BDD files — returns `session_id` |
| `POST` | `/parse` | Parse all uploaded files in the session |
| `POST` | `/generate` | Generate synthetic data, validate, and prepare exports |
| `GET` | `/summary` | Full session summary with stats and download links |
| `GET` | `/preview/{table}` | Preview generated rows for a specific table |
| `GET` | `/download/csv` | Download data as CSV ZIP |
| `GET` | `/download/json` | Download data as JSON ZIP |
| `GET` | `/download/sql` | Download data as SQL INSERT ZIP |

#### Generation Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `row_count` | int | 10 | 1–10,000 | Rows per table |
| `include_valid` | bool | true | — | Generate valid records |
| `include_invalid` | bool | false | — | Generate invalid/negative cases |
| `include_boundary` | bool | false | — | Generate boundary-value cases |
| `include_duplicates` | bool | false | — | Generate duplicate-key cases |

### Standalone Endpoints

These endpoints operate on individual files without sessions — useful for testing and debugging.

#### Parsing (`/parse`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/parse/sql` | Parse SQL schema file → `SchemaMetadata` |
| `POST` | `/parse/openapi` | Parse OpenAPI spec → `OpenAPIMetadata` |
| `POST` | `/parse/bdd` | Parse BDD feature file → `BDDMetadata` |
| `POST` | `/parse/sql/graph` | Parse SQL + return relationship graph and generation order |

#### Generation (`/generate`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/generate/sql` | Generate valid synthetic data from SQL file |
| `POST` | `/generate/sql/negative` | Generate negative/invalid test cases with configurable toggles |

#### Negative Case Toggles

| Toggle | Default | Description |
|--------|---------|-------------|
| `invalid_emails` | true | Malformed email addresses |
| `null_required_fields` | true | Null values in NOT NULL columns |
| `duplicate_values` | true | Duplicate primary keys |
| `broken_foreign_keys` | true | FK references to nonexistent parents |
| `boundary_values` | true | Min/max boundary values |
| `invalid_enums` | true | Values outside allowed enums |
| `invalid_regex_patterns` | true | Strings violating regex constraints |

#### Validation (`/validate`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/validate/sql` | Generate from SQL + validate against all constraints |

#### Export (`/export`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/export/csv` | Generate + export as CSV ZIP |
| `POST` | `/export/json` | Generate + export as JSON ZIP |
| `POST` | `/export/sql` | Generate + export as SQL INSERT ZIP |
| `POST` | `/export/all` | Generate + return summary for all formats |

#### AI Reasoning (`/ai`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ai/analyze/sql` | AI analysis of SQL schema — hidden constraints & edge cases |
| `POST` | `/ai/analyze/bdd` | AI analysis of BDD features — business rules & requirements |
| `POST` | `/ai/analyze/combined` | Combined SQL + BDD analysis |

#### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "healthy"}` |

---

## Module Reference

### Parsers

| Module | Input | Output | Engine |
|--------|-------|--------|--------|
| `sql_parser` | `.sql` DDL | `SchemaMetadata` (tables, columns, PKs, FKs, constraints) | sqlglot |
| `openapi_parser` | `.yaml` / `.json` spec | `OpenAPIMetadata` (schemas, fields, validations) | PyYAML |
| `bdd_parser` | `.feature` / `.txt` Gherkin | `BDDMetadata` (scenarios, rules, steps) | Regex |

### Converters

| Module | Purpose |
|--------|---------|
| `openapi_to_schema` | Converts `OpenAPIMetadata` → `SchemaMetadata` for unified generation |
| `bdd_to_schema` | Converts `BDDMetadata` → `SchemaMetadata` with inferred constraints |

### Generators

| Module | Purpose |
|--------|---------|
| `synthetic_generator` | Generates valid, realistic data rows using Faker — respects types, constraints, enums, regex patterns, FK references |
| `negative_generator` | Generates invalid test cases — null violations, broken FKs, duplicate PKs, boundary values, bad formats |

### Services

| Module | Purpose |
|--------|---------|
| `relationship_engine` | Builds a directed FK dependency graph with networkx — returns topological generation order |
| `session_store` | In-memory session management — stores uploaded files, parsed metadata, generated data per session |

### Validators

| Module | Checks |
|--------|--------|
| `validators` | PK uniqueness, FK referential integrity, data type correctness, enum compliance, nullable rules, regex pattern matching |

### Exporters

| Module | Formats |
|--------|---------|
| `engine` | CSV, JSON, SQL INSERT — each packaged into a ZIP archive with an export summary manifest |

### AI Layer

| Module | Purpose |
|--------|---------|
| `service` | AI orchestration — routes to gateway or offline provider |
| `gateway_provider` | Generic HTTP client for AI gateway / OpenAI-compatible APIs |
| `offline_provider` | Fallback provider when no API keys — returns empty results gracefully |
| `output_parser` | Parses AI JSON responses into `AIReasoningResult` models |
| `prompts` | Structured prompt templates for SQL analysis, BDD analysis, and combined analysis |

### Shared Utilities

| Module | Purpose |
|--------|---------|
| `config` | Environment-variable-based settings with sensible defaults |
| `sql_types` | Centralized SQL type mapping — `base_type()`, `extract_enum_from_check()`, `extract_max_length()`, `extract_precision()` |

---

## Demo Flow

### Step 1 — Upload Files

Navigate to the **Upload** page. Drag and drop (or click to browse) your schema files:

- `schema.sql` — SQL DDL with tables, columns, constraints
- `api.yaml` — OpenAPI/Swagger specification (optional)
- `tests.feature` — BDD/Gherkin feature file (optional)

Supported: `.sql`, `.yaml`, `.yml`, `.json`, `.feature`, `.txt` — up to 5 MB each, max 10 files.

### Step 2 — Configure Generation

- Adjust the **Rows per table** slider (1–10,000)
- Toggle data categories:
  - **Valid** — realistic, constraint-compliant records
  - **Invalid** — intentionally broken data for negative testing
  - **Boundary** — min/max edge values
  - **Duplicates** — duplicate PKs for uniqueness testing

### Step 3 — Generate

Click **Generate**. The pipeline executes three sequential steps:

1. **Upload** — files sent to the server with a progress bar
2. **Parse** — schemas extracted, dependency graph built, generation order determined
3. **Generate** — synthetic rows created, validated, exports prepared

### Step 4 — Review Results

Automatically redirected to the **Results** page:

- **Stats Cards** — tables parsed, total rows, rows per table, edge cases, validation pass rate
- **Generation Order** — visual display of FK-safe table creation sequence
- **Validation Report** — per-table breakdown of passed / failed rows
- **Data Preview** — click any table name to inspect generated rows

### Step 5 — Download

Export your datasets:

- **CSV** — one CSV file per table, zipped
- **JSON** — one JSON file per table, zipped
- **SQL** — INSERT statements per table, zipped

Each archive includes an export summary manifest with row counts and metadata.

---

## Screenshots

> Replace these placeholders with actual captures from a live demo session.

### Upload Page

![Upload Page](docs/screenshots/upload-page.png)

*File upload zone with drag-and-drop, generation options, and row count configuration.*

### Generation Progress

![Generation Progress](docs/screenshots/generation-progress.png)

*Three-step pipeline progress: Upload → Parse → Generate.*

### Results Dashboard

![Results Dashboard](docs/screenshots/results-dashboard.png)

*Statistics cards, generation order flow, and validation summary.*

### Data Preview

![Data Preview](docs/screenshots/data-preview.png)

*Inline row preview for generated table data.*

### Download Options

![Download Options](docs/screenshots/download-options.png)

*One-click export to CSV, JSON, or SQL INSERT formats.*

### Swagger API Docs

![Swagger UI](docs/screenshots/swagger-ui.png)

*Auto-generated API documentation at `/docs`.*

---

## Testing

The backend has a comprehensive test suite with **396 tests** covering all modules.

```bash
cd backend

# Run all tests
python -m pytest -q

# Run with verbose output
python -m pytest -v

# Run a specific test file
python -m pytest tests/test_parsers.py -v

# Run with coverage
python -m pytest --cov=app --cov-report=term-missing
```

---

## Future Improvements

| Category | Enhancement |
|----------|-------------|
| **AI Chat** | Interactive chat assistant for refining generation rules |
| **Templates** | Domain-specific templates (healthcare, finance, e-commerce) |
| **Coverage Analytics** | Visual coverage reports — which constraints are exercised |
| **Multi-Database** | Generate data for PostgreSQL, MySQL, SQL Server, Oracle dialects |
| **Data Masking** | Generate anonymized data from production schemas |
| **Scheduling** | Automated periodic data generation via cron / webhooks |
| **Collaboration** | Shared sessions and team workspaces |
| **Docker** | Full containerization with `docker-compose` |
| **CI/CD** | GitHub Actions pipeline for automated testing and deployment |
| **Parquet / Excel** | Additional export formats (Apache Parquet, XLSX) |
| **Streaming** | Streaming generation for datasets exceeding 100K rows |
| **Schema Versioning** | Track schema changes and regenerate compatible datasets |

---

<p align="center">
  Built for the <b>Sun Life Jedi Hackathon</b> — AI-Powered QA Automation
</p>
