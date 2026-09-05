# TBX — a grounded finance assistant (text-to-SQL with a verification layer)

TBX answers plain-language questions about your financial data — spend, vendor payouts,
reconciliation status — with numbers that are **computed by SQL against the real dataset**,
paired with the records behind them, and traceable end to end.

The crux is **grounding**: every figure in every answer originates from an executed query, and
the language model never performs arithmetic. When the data cannot answer a question, or the
question is ambiguous, the assistant **says so** instead of producing a number.

> This is a backend (FastAPI + AWS Strands Agents + PostgreSQL/pgvector + Sarvam voice). No UI is
> implemented; every figure a dashboard would need is exposed through documented HTTP APIs.

BVP Tech Catalyst Hackathon — *"Build a Finance Assistant That Actually Understands You."*

---

## The core idea

**It is a text-to-SQL system with a verification layer, not a chatbot with a database attached.**

A question flows through a pipeline that figures out intent, writes or selects SQL, **proves the
SQL is safe and correct before running it**, executes it read-only, computes numbers
deterministically in `Decimal`, verifies the drafted answer contains no ungrounded number, and
streams the whole reasoning trace live. Low confidence → it abstains or asks one clarifying
question.

Two answering paths, same safety machinery:

- **Metric_Layer** (deterministic): pre-validated, parameterised SQL templates for the common
  finance questions. Same question → same trusted number, cheap in tokens.
- **Generated SQL** (flexible): for ad-hoc questions, a small model writes SQL from a *retrieved
  minimal sub-schema* plus retrieved example question/SQL pairs.

---

## Architecture

```
                          ┌──────────────────────────────────────────────┐
  question ──► Chat_API ──► TurnOrchestrator (chains every stage below)   │
                          └──────────────────────────────────────────────┘
                                          │
   intake ─► context_resolution ─► intent/entity/date resolution
                                          │
                              ┌───────────┴────────────┐
                     Metric_Layer route          Generated-SQL route
                     (deterministic templates)   (schema linking ─► exemplars ─► LLM writes SQL)
                              └───────────┬────────────┘
                                          ▼
                          SQL_Validator  ◄── THE SECURITY BOUNDARY
                          (AST allowlist: read-only SELECT only, schema-conformant,
                           no DDL/DML, no dangerous functions) — built & proven green
                           BEFORE any model is allowed to author SQL
                                          ▼
                          Reviewer_Agent (2nd model: plan + dry-run evidence → approve/repair/reject;
                                          candidates vote on executed results, not SQL text)
                                          ▼
                          Query_Executor (tbx_reader role: SELECT-only, statement timeout,
                                          row cap, concurrency limit, dataset-version pinning)
                                          ▼
                          Computation_Layer (Decimal end-to-end; one record per figure)
                                          ▼
                          Answer_Composer (LLM writes prose from computation records only)
                                          ▼
                          Groundedness_Checker (every number in the draft must match a source,
                                                else reject+regenerate, else templated answer)
                                          ▼
                          Confidence_Scorer (published weighted sum → score + band; below
                                             threshold ⇒ abstain / clarify)
                                          ▼
                          answer + breakdown table + executed SQL + confidence + live trace
```

Cross-cutting:

- **Trace_Service** streams every stage over SSE/WebSocket as it happens and persists it for audit
  by turn id.
- **Budget_Guard** enforces hard caps on LLM calls / tokens / wall-clock per question.
- **Abstention_Controller** maps every failure condition to exactly one of 21 machine-readable
  reason codes; an abstention never states a figure.
- **Ingestion** loads a dataset from local files **or** the organisers' HTTP API, driven by one
  **Dataset_Manifest** — swapping datasets is a config change, not a code change.
- **Model_Router** resolves each role (router / sql_generator / reviewer / composer / buddy /
  embedder) to any of six providers by config; runs fully offline on local Ollama.

The full design lives in [`.kiro/specs/finance-assistant-nl2sql/`](.kiro/specs/finance-assistant-nl2sql/)
(`requirements.md`, `design.md`, `tasks.md`).

---

## Design decisions worth knowing

1. **The safe-execution boundary is built and property-tested green before any model writes SQL.**
   A generated or template query is parsed to an AST and checked as an **allowlist** (only what is
   explicitly permitted passes). A model literally cannot get a query executed unless it is proven
   read-only and schema-conformant.
2. **Money is `Decimal` end to end — never `float`.** Enforced by property tests (breakdown rows
   sum to the reported total at the recorded precision, with no binary float on the path).
3. **Grounding is deterministic, not an LLM judge.** Every numeral in an answer (including "two
   crore", "12.5%", dates) is extracted and matched against the executed result set / a computation
   record. A wrong figure gets the draft rejected; if regeneration also fails, a deterministic
   templated sentence is used.
4. **Abstention is a first-class outcome**, backed by a finite, exhaustively-tested mapping to 21
   reason codes.
5. **Everything is a budget you measure, not a claim** — accuracy and grounding come from an
   evaluation harness over a golden question set.

---

## Repository layout

```
app/
  config.py                      typed Settings (every configurable value; blank env ⇒ default)
  errors.py                      typed error taxonomy → abstention reason codes (total mapping)
  startup_checks.py              config + DB startup gates (fail loud, no listener bind)
  db/                            engines (tbx_app + SELECT-only tbx_reader), sessions
  schemas/                       Pydantic contracts: manifest, computation, validation, golden…
  services/
    pipeline/                    sql_validator, computation, groundedness, confidence,
                                 abstention, anomaly, query_executor, schema_linker
    ingestion/                   contract checker, local_files parsing
    ops/                         evaluation comparator
    knowledge/                   schema lookup
alembic/                         migrations (extensions, roles, finance + ops schemas, grants)
datasets/seed/                   deterministic synthetic dataset + manifest + data dictionary
scripts/seed_data.py             the Seed_Data_Generator (byte-identical for a fixed seed)
docs/dataset_contract.md         the interface the real dataset must satisfy
tests/                           unit + property (Hypothesis) suites; stubs for provider/voice
HANDOVER.md                      current build status and next steps (READ THIS)
```

---

## Build status — what is real vs pending

This repo was built safety-first: the **correctness-critical, model-free core is implemented and
tested**; the **model- and database-backed wiring is specified and partly written but not yet
runnable** in an environment without PostgreSQL and a model provider. Be precise about this with
the team — see [`HANDOVER.md`](HANDOVER.md) for the exact list.

**Implemented and verified (106 tests green, no DB / no model needed):**

- SQL_Validator — the security boundary (Properties 1 & 2)
- Computation_Layer — Decimal end to end (Properties 4 & 18)
- Groundedness_Checker (Properties 3 & 34)
- Confidence_Scorer (Property 14)
- Abstention_Controller — reason-code mapping (Properties 5 & 31)
- Anomaly_Detector rule (Property 16)
- Evaluation comparator (Requirement 26.3)
- Seed_Data_Generator + dataset contract checker (byte-identical seed; 0 blocking deviations)
- Dataset_Manifest contracts (Property 11)
- Typed error taxonomy

**Written but unverified (need PostgreSQL to run):** Alembic migrations, dual-engine DB session,
Query_Executor, Local_File_Connector load path, Schema_Linker DB retrieval, DB startup gates.

**Not yet written (the model-backed agents — first task once a provider is available):**
Model_Router + Strands agent factory, Budget_Guard, Context_Resolver/Query_Planner (intake),
SQL_Generator, Reviewer_Agent, TurnOrchestrator, session store + Chat_API routes.

---

## Getting started

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and (for the full stack) Docker.

```bash
# 1. install deps into a local venv
uv sync

# 2. run the verified test suite (no network, no database required)
uv run pytest -m "not live" -q      # 106 passed
uv run ruff check .                 # All checks passed!

# 3. regenerate the deterministic seed dataset (writes CSVs under datasets/seed/)
uv run python -m scripts.seed_data
```

### Bringing up the full stack (needs Docker + a model provider)

```bash
# Postgres + pgvector (and optionally Ollama) via Compose
docker compose up -d postgres

# apply the database schema
uv run alembic upgrade head

# a model provider — either local Ollama…
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b     # pinned lightweight (<=8B) model
ollama pull nomic-embed-text     # local embeddings (offline retrieval)
# …or a hosted key in .env (see .env.example)
```

### Configuration

Copy `.env.example` to `.env`. Blank values fall back to documented defaults. Credentials the
system can use:

- **Database (required):** `POSTGRES_DSN`, `POSTGRES_READER_USER/PASSWORD/DSN`
- **Model provider (for the LLM paths):** a key for one of `openrouter` / `bedrock` /
  `azure_openai` / `openai_compatible`, or local `ollama` / `vllm` (no key)
- **Voice (optional):** `SARVAM_API_KEY`
- **Auth (optional):** `INTERNAL_API_TOKEN` — shared-secret header for admin routes; unset ⇒ the
  API is unauthenticated and startup logs a warning

Every setting is in [`app/config.py`](app/config.py); every default is documented in
`requirements.md`'s Configuration Inventory.

### Swapping the dataset

Point at a new dataset by replacing one manifest file and re-running ingestion — no code change.
The [dataset contract](docs/dataset_contract.md) is the interface both the seed dataset and the
delivered dataset must satisfy.

---

## Testing

Property-based tests (Hypothesis) guard the correctness-critical invariants — grounding, Decimal
arithmetic, the SQL allowlist, confidence monotonicity, the abstention reason-code mapping. The
default run needs no network:

```bash
uv run pytest -m "not live" -q     # unit + property suites
uv run pytest -m live -q           # Sarvam voice + hosted-provider integration (needs creds)
```
