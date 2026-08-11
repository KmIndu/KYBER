# SYSTEM ARCHITECTURE

# High-Level Flow

```text
User Uploads Files
↓
Parser Layer
↓
Metadata Extraction
↓
Relationship Graph Engine
↓
AI Reasoning Layer
↓
Synthetic Data Generator
↓
Validation Engine
↓
Export Engine
↓
Download Outputs
```

---

# Architecture Principles

The system should be:
- modular
- scalable
- deterministic
- easy to extend
- service-oriented

---

# Frontend Architecture

# Stack
- React
- Vite
- TailwindCSS

---

# Frontend Pages

## Upload Dashboard

Responsibilities:
- upload files
- configure generation
- trigger generation

---

## Results Dashboard

Responsibilities:
- show statistics
- show generation summary
- provide download links

---

# Backend Architecture

# Stack
- FastAPI
- Python 3.11

---

# Backend Folder Structure

```text
backend/
│
├── app/
│ ├── routers/
│ ├── parsers/
│ ├── generators/
│ ├── validators/
│ ├── exporters/
│ ├── ai/
│ ├── services/
│ ├── models/
│ └── utils/
```

---

# Module Responsibilities

# Routers

Responsibilities:
- API endpoints
- request validation
- response formatting

---

# Parsers

Responsibilities:
- SQL parsing
- OpenAPI parsing
- BDD parsing

Outputs:
- normalized metadata

---

# Relationship Engine

Responsibilities:
- dependency graph
- topological sorting
- generation sequencing

Uses:
- networkx

---

# AI Layer

Responsibilities:
- infer hidden constraints
- interpret business rules
- generate edge-case instructions

Uses:
- Gemini/OpenAI APIs

Important:
AI should only assist reasoning.

AI should NOT generate massive datasets directly.

---

# Synthetic Generator

Responsibilities:
- create realistic rows
- preserve FK relationships
- enforce constraints

Uses:
- Faker
- rule-based generation

---

# Validation Layer

Responsibilities:
- validate uniqueness
- validate FK relationships
- validate data types
- validate constraints

Uses:
- Pydantic

---

# Export Layer

Responsibilities:
- CSV export
- JSON export
- SQL export
- ZIP packaging

---

# Data Flow

# Step 1 — Upload

User uploads:
- schema.sql
- swagger.yaml
- feature.feature

---

# Step 2 — Parse

Parser extracts:
- tables
- relationships
- constraints
- validation rules

---

# Step 3 — Build Dependency Graph

Determine:
- parent tables
- child tables
- generation order

---

# Step 4 — AI Reasoning

AI infers:
- hidden validations
- business rules
- edge cases

---

# Step 5 — Generate Data

Generator creates:
- valid rows
- invalid rows
- boundary cases
- duplicate scenarios

---

# Step 6 — Validate

Validation engine checks:
- integrity
- constraints
- relationships

---

# Step 7 — Export

Outputs generated:
- CSV
- JSON
- SQL INSERTS

---

# Relationship Generation Example

```text
Customer
↓
Policy
↓
Claim
↓
Payment
```

Generation order:
1. Customer
2. Policy
3. Claim
4. Payment

This preserves referential integrity.

---

# AI Workflow Example

BDD:
```gherkin
Given claim amount exceeds 50000
Then manager approval required
```

AI infers:
```json
{
"claim_amount": 60000,
"approval_required": true
}
```

---

# Recommended Development Order

1. Backend skeleton
2. SQL parser
3. OpenAPI parser
4. BDD parser
5. Relationship engine
6. Faker generator
7. Validation engine
8. Export engine
9. AI integration
10. Frontend
11. Dockerization
12. Demo polish

---

# Design Constraints

Avoid:
- unnecessary abstraction
- heavy AI orchestration frameworks
- vector databases
- RAG systems

Prioritize:
- speed
- reliability
- clean architecture
- deterministic generation

---

# Final Goal

Build a production-style prototype that demonstrates:

- intelligent schema understanding
- AI-assisted QA automation
- realistic synthetic data generation
- relational integrity preservation
- automated edge-case creation