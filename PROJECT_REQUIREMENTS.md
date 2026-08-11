# PROJECT REQUIREMENTS

# Project Name

AI-Powered Synthetic Test Data Generator

---

# Objective

Build a full-stack AI-assisted platform that generates synthetic test data from:

- SQL database schemas
- OpenAPI specifications
- BDD feature files

The system must:
- preserve relationships
- maintain referential integrity
- generate realistic values
- create edge cases
- generate invalid test scenarios

---

# Functional Requirements

# 1. File Upload Support

Accept:

## SQL Schema Files
- .sql

## OpenAPI Files
- .yaml
- .json

## BDD Files
- .feature
- .txt

---

# 2. SQL Parsing

Extract:
- table names
- columns
- data types
- primary keys
- foreign keys
- unique constraints
- check constraints
- not-null constraints

Use:
- sqlglot

---

# 3. OpenAPI Parsing

Extract:
- schema definitions
- required fields
- enums
- regex validations
- min/max validations

Support:
- Swagger
- OpenAPI 3.x

---

# 4. BDD Parsing

Parse Gherkin scenarios.

Example:

```gherkin
Given user age is below 18
Then registration should fail
```

Convert into structured rule objects.

---

# 5. Relationship Graph

Build dependency graph using:
- networkx

Responsibilities:
- detect table dependencies
- determine generation order
- prevent FK failures

---

# 6. Synthetic Data Generation

Use:
- Faker
- rule-based logic
- AI reasoning

Generate:
- names
- emails
- phone numbers
- addresses
- UUIDs
- dates

---

# 7. Constraint Handling

Respect:
- uniqueness
- enums
- min/max values
- regex patterns
- FK constraints
- nullable rules

---

# 8. Negative Case Generation

Generate:
- invalid formats
- null cases
- duplicate values
- boundary values
- broken FK cases

---

# 9. AI Integration

Use:
- Gemini API OR OpenAI API

AI responsibilities:
- infer hidden constraints
- understand BDD logic
- generate edge cases
- generate business-aware data

AI should NOT generate entire datasets.

---

# 10. Validation Engine

Verify:
- PK uniqueness
- FK validity
- data type correctness
- constraint compliance

Use:
- Pydantic

---

# 11. Export Engine

Support:
- CSV
- JSON
- SQL INSERT scripts
- ZIP downloads

---

# 12. Frontend Requirements

Frontend should include:

## Upload Dashboard
- file upload
- generation options

## Results Dashboard
- statistics
- generation summary
- download buttons

Use:
- React
- TailwindCSS

---

# 13. Backend Requirements

Use:
- FastAPI

Implement:
- modular architecture
- service layers
- parser modules
- exporter modules
- validator modules

---

# 14. API Endpoints

## Upload
```http
POST /upload
```

## Parse
```http
POST /parse
```

## Generate
```http
POST /generate
```

## Download CSV
```http
GET /download/csv
```

## Download JSON
```http
GET /download/json
```

## Download SQL
```http
GET /download/sql
```

---

# 15. Performance Goals

Target:
- 10,000 rows within 30 seconds

---

# 16. Security Requirements

- sanitize uploads
- validate file types
- remove temp files
- avoid permanent storage

---

# 17. Non-Goals

Do NOT:
- introduce vector databases
- use RAG pipelines
- overcomplicate with agentic frameworks
- build unnecessary microservices

Focus on:
- schema intelligence
- reliable generation
- deterministic workflows

---

# 18. Expected Deliverables

- working frontend
- working backend
- upload flow
- generation pipeline
- export functionality
- documentation
- modular codebase

---

# 19. Demo Expectations

User should:
1. upload files
2. click generate
3. receive relational synthetic datasets
4. download outputs

The demo should clearly showcase:
- AI-assisted reasoning
- FK-safe generation
- edge-case coverage
- automation benefits
