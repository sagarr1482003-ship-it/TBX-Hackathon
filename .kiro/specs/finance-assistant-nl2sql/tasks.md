# Implementation Plan: finance-assistant-nl2sql

## Overview

Python 3.12 / FastAPI / PostgreSQL 16 + `pgvector` / AWS Strands Agents, exactly as specified in
design.md §4.2. Task ordering follows the design's Delivery Sequencing section with **one deliberate
inversion**, recorded in
[Deviation from design.md's Delivery Sequencing](#deviation-from-designmds-delivery-sequencing): the
**generated-SQL agent path is the first demoable slice** (tasks 6–7), and the `Metric_Layer` follows it
(task 9.1) as the accuracy-and-efficiency path and the offline fallback rather than as the demo default.
The design's other two defended decisions are encoded literally and unweakened — the `SQL_Validator` and
`Query_Executor` are built and property-green *before* any model writes SQL (task 4 precedes task 7.8),
and the dataset-swap rehearsal happens at task 12 rather than on delivery day.

**Execution tiers.** Every top-level task carries a tier. `required` tasks are the design's critical
path — without all of them there is no demo and no submission. `optional` tasks are real deliverables
(full metric catalogue, Metrics_API, export, voice, buddies, improvement loop, anomaly callouts) that the
demo survives without. The machine-readable tier lists are in [Execution Tiers](#execution-tiers).

**Run these first if time is short.** Tasks 1.6, 4.2, 6.1 and 7.1 unblock the most downstream work: 1.6 is
the stub-provider and database fixture harness every property test composes, 4.2 is the security boundary
every SQL-producing task depends on, 6.1 is the `Model_Router` and agent factory that all four
answering-path roles are constructed through, and 7.1 is the `ComputationRecord` contract that the
composer, groundedness checker, export, anomaly and insights surfaces all read.

---

## Tasks

- [ ] 1. Stage 0 — Skeleton, configuration, migrations and test harness
  **Tier: required.** Design: §4.2, §5.5, §5.1, Security considerations.

  - [ ] 1.1 Scaffold the project and the Compose stack
    - Create `pyproject.toml` (uv; fastapi, uvicorn, pydantic v2, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, pgvector, sqlglot, strands-agents, sse-starlette, openpyxl, httpx, PyYAML; dev: pytest, pytest-asyncio (`asyncio_mode = "auto"`), hypothesis, ruff with `select = ["E","F","I"]`)
    - Create `Dockerfile`, `.dockerignore`, `.gitignore`, `.env.example`, and `docker-compose.yml` with services `postgres` (pgvector image), `api`, and `ollama` behind a profile — one documented command brings the stack up
    - Create `app/__init__.py` and `app/main.py` as an app factory with the request-body-size ASGI middleware placed ahead of any body parser, binding to `settings.bind_host`
    - _Requirements: 32.5, 32.7, 32.16_

  - [ ] 1.2 Implement the typed settings object
    - Create `app/config.py`: a `pydantic-settings` `Settings` singleton with defaults as named module constants and `field_validator(mode="before")` coercion so a blank environment variable falls back to the default rather than failing startup
    - Cover every entry in the requirements.md Configuration Inventory and every entry in the design's "New configuration introduced by design" table, including `embedding_model`, `embedding_dim`, `schema_link_keyword_weight`/`vector_weight`, `groundedness_require_computation_record`, `answer_composer_sample_row_count`, `reviewer_evidence_sample_rows`, `anomaly_callouts_enabled`, `internal_api_token`, `bind_host`, `postgres_reader_user`/`_password`, `reader_pool_size`, `model_prices`, `role_prompt_versions`, `trace_buffer_max_events`, and the `sarvam_*` group
    - Ship the three stated deviations: `max_utterance_duration = 30`, pitch read-but-omitted for `bulbul:v3`, transcription-confidence source policy
    - _Requirements: 32.4, 10.8, 28.3, 29.3_

  - [ ] 1.3 Implement the typed error taxonomy
    - Create `app/errors.py`: `TbxError` base carrying `code`, message, `abstention_reason` and `retryable`, plus every subclass in the design's Error Handling table with the exact reason-code mapping given there
    - Create `tests/unit/test_error_taxonomy.py` enumerating every `TbxError` subclass and asserting each maps either to a reason code drawn from the Requirement 18.4 enumeration or to a documented `None`, so no exception class can be added without a mapping
    - _Requirements: 18.4_
    - _Properties: P31 (mapping totality half)_

  - [ ] 1.4 Write Alembic migrations 0001–0009
    - Create `alembic.ini`, `alembic/env.py`, and revisions `0001_extensions_and_roles` … `0009_grants` with exactly the contents and ordering of design §5.5, including `vector` and `pg_trgm` extensions, schemas `finance` and `ops`, roles `tbx_app`/`tbx_reader` with `ALTER ROLE tbx_reader SET default_transaction_read_only = on, statement_timeout = '10s'`
    - Create every table of design §5.2, §5.3 and §5.4 including the four partial unique indexes (`ux_one_active_dataset`, `ux_one_ingestion_in_progress`, `ux_one_improvement_in_progress`, `ux_one_active_artefact`), the generated `tsvector` column with its GIN index, and both HNSW indexes on empty tables
    - Keep the `finance` revoke from `tbx_app` in revision 0009 last, and include `ALTER DEFAULT PRIVILEGES` so manifest-added tables inherit the reader grant
    - _Requirements: 32.2, 32.3, 13.1, 13.2, 13.6, 5.7, 5.13, 25.13, 3.10, 9.12_

  - [ ] 1.5 Implement startup gates, dependencies and the health endpoint
    - Create `app/db/session.py` with two async engines (`tbx_app`, `tbx_reader`) where the reader engine is never injected outside `Query_Executor`; create `app/deps.py` with the constant-time `X-Internal-Token` dependency that rejects before a Turn is created
    - Create `app/startup_checks.py`: applied-revision-equals-head, vector extension present, active dataset populated, model tier ceiling and hosted-tier check, per-question budgets within hard ceilings, confidence weights non-negative and summing to 1 within 0.001 with strictly ascending band boundaries, `max_concurrent_queries <= reader_pool_size`, reviewer/sql_generator `(provider, model_id, prompt_version)` non-identity, and the unauthenticated-API startup warning — each failure exits non-zero without binding the listener
    - Create `app/routes/health.py` returning the full Requirement 32.6 payload within 500 ms, with the voice reachability probe served from a cache refreshed at most once per `voice_reachability_cache_period`, and every configured secret replaced by a fixed mask token
    - _Requirements: 32.3, 32.6, 32.7, 32.8, 32.10, 32.13, 32.14, 32.15, 13.13, 19.9, 10.13, 10.14, 14.15, 9.11_

  - [ ] 1.6 Build the test harness and every stub provider
    - Create `tests/conftest.py` with a per-test transaction fixture against real PostgreSQL + `pgvector` rolled back after each test (not SQLite — partial unique indexes, generated `tsvector`, `numeric` semantics, `statement_timeout` and HNSW are all load-bearing), a Hypothesis profile of ≥100 examples with `deadline=None`, and a `live` marker excluded from the default run
    - Create `tests/stubs/model_provider.py` (`StubModelProvider`: scripted per-role structured outputs; valid, adversarial, non-conforming, truncated, slow and failing scripts; counts calls and tokens), `tests/stubs/embedder.py` (`StubEmbedder`: deterministic hash embeddings at the configured dimension), `tests/stubs/voice.py` (`StubVoiceProvider`: fixed transcripts, silent audio, scripted failures and the no-confidence-field case), and `tests/stubs/organiser_api.py` (`StubOrganiserApi`: in-process paginated HTTP app with scripted 429/5xx, early closes, missing final-page signals and repeated cursors)
    - Confirm `pytest -m "not live"` passes with no network access
    - _Requirements: 9.14, 26.9_

- [ ] 2. Stage 1 — Seed dataset, dataset contract and local-file ingestion
  **Tier: required.** Design: Architecture ingestion path, §4.3 (`Dataset_Manifest`), §5.2, §5.4.

  - [ ] 2.1 Define the Dataset_Manifest contracts
    - Create `app/schemas/manifest.py` with `ColumnSpec`, `EntitySpec`, `JoinSpec`, `MetricParameter`, `MetricDefinition`, `PaginationSpec`, `CoverageWindow`, `DataDictionarySpec` and `DatasetManifest` exactly as design §4.3
    - Add the `model_validator` that asserts every `:bind` name in every metric `sql_template` exists in that metric's `parameters`, that every required entity and column is declared, and that `source_mode` is one of `local_files`/`http_api` — a failing manifest aborts before any entity loads
    - _Requirements: 5.1, 5.2, 5.9, 4.1, 4.6, 3.6_
    - _Properties: P11_

  - [ ] 2.2 Implement the Seed_Data_Generator and the seed manifest
    - Create `scripts/seed_data.py`, `datasets/seed/manifest.yaml` and `datasets/seed/data_dictionary.csv`, emitting CSVs for vendors, accounts, transactions, vendor_payouts and reconciliation into `datasets/seed/`
    - Produce every threshold of Requirement 8.2 (≥5000 transactions, ≥200 payouts, ≥40 vendors, ≥12 consecutive months, ≥500 unreconciled, ≥20 in each other allowed status, ≥3 payouts the anomaly rule flags) **and** every edge row of Requirement 8.7 (≥50 transactions with a null in a non-key column, ≥5 vendors under ≥2 name spellings, ≥20 amounts of exactly 0, ≥20 amounts below 0) — the abstention, clarification and anomaly properties all depend on these rows existing
    - Guarantee byte-identical output for a given random seed
    - _Requirements: 8.1, 8.2, 8.3, 8.7_
    - _Properties: P12_

  - [ ] 2.3 Publish the dataset contract and implement its checker
    - Create `docs/dataset_contract.md` declaring per entity the required columns, types, units, allowed reconciliation status values, the referential relationships the `Metric_Layer` depends on, the inclusive coverage window, and a severity of `blocking` or `tolerable` for every rule — with null-in-non-key-column, duplicate vendor spelling, amount exactly 0 and amount below 0 all `tolerable`
    - Create `app/services/ingestion/contract.py` validating a candidate dataset against every rule before any row loads, aborting on ≥1 blocking deviation with the count and violated rules, and recording tolerable deviations in the ingestion report
    - _Requirements: 8.4, 8.5, 8.8, 8.9, 8.10_

  - [ ] 2.4 Implement the Local_File_Connector
    - Create `app/services/ingestion/local_files.py` handling CSV, XLSX and SQL dump; declared-encoding decode with BOM discard; header matching after trimming and case-folding with excluded headers reported; single declared date format per column with no time-zone conversion; monetary parsing that strips declared symbols and separators, reads parentheses as negative, and rounds half away from zero to the declared scale; row rejection with row number and reason; primary-key duplicate handling; NULL for empty non-required cells; INSERT-only SQL dump execution; rejected-row tolerance failure; index creation for every declared filter column and join key
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.9, 6.10, 6.11, 6.12, 6.13_

  - [ ] 2.5 Implement the Ingestion_Service, atomic activation and the admin ingestion routes
    - Create `app/services/ingestion/ingestion_service.py` and `app/db/models/ops_versioning.py`: run locking via `ux_one_ingestion_in_progress`, one validation report for manifest and missing-item failures, single-transaction pointer flip of `active_dataset_version` + `active_schema_kb_version`, retention of 2 previous versions with their bound `Schema_KB` version, revert within 30 s, `Exemplar_Bank` applicability marking, metric definitions held inactive when a referenced table or column is absent, and the synthetic-data provenance flag
    - Create `app/routes/admin.py` and `app/schemas/admin.py` with `POST /api/admin/ingest`, `GET /api/admin/ingest/{run_id}`, `GET /api/admin/dataset`, `POST /api/admin/dataset/revert` per design §4.4
    - _Requirements: 5.3, 5.5, 5.6, 5.7, 5.8, 5.10, 5.11, 5.12, 5.13, 5.14, 4.12, 8.11_

  - [ ] 2.6 Write the ingestion property suite
    - Create `tests/properties/test_ingestion.py` with `source_table()` and `defect_rate()` generators: manifest serialise/re-load equivalence and rejection of incomplete or unsupported-mode manifests (P11), double ingestion yielding identical row counts and `Schema_KB` content with only version identifiers advancing plus seed byte-identity (P12), local-format invariance across CSV/XLSX/SQL-dump and encoding/BOM variants (P7, local subset), and typed-error-never-a-figure for malformed manifests, missing required columns and over-tolerance rejects (P17, ingestion subset)
    - _Requirements: 5.1, 5.2, 5.6, 5.7, 5.9, 6.1, 6.5, 6.6, 6.11, 6.13, 8.3_
    - _Properties: P7, P11, P12, P17_

  - [ ] 2.7 Verify the Compose stack reaches readiness
    - Create `tests/integration/test_compose_health.py` asserting the documented Compose command yields a stack whose `/health` reports database connected, vector extension present, applied revision equal to head and the active dataset version populated, inside the cold-start budget
    - _Requirements: 32.3, 32.5, 32.6_
    - _Properties: P22_

- [ ] 3. Stage 2 — Schema Knowledge Base derivation and schema linking
  **Tier: required.** Design: §4.3 (`Schema_Linker` retrieval), §5.4, §5.6, F-4. This is the first stage the
  demo trace renders live (`schema_retrieval`, `schema_linking`), so its scored-chunk payload is a demo
  artefact, not just an internal signal.

  - [ ] 3.1 Implement the embedding adapter
    - Create `app/services/knowledge/embedder.py`: batching, normalisation, and recording of the dimension actually produced on the `schema_kb_version` row; raise the typed `EmbeddingDimensionMismatchError` naming both dimensions when the configured, recorded and returned dimensions disagree, leaving every stored embedding unchanged
    - _Requirements: 9.9, 9.12, 9.15_

  - [ ] 3.2 Derive the Schema_KB from the active dataset
    - Create `app/services/ingestion/schema_kb_builder.py` and `app/services/knowledge/schema_kb.py`: one entry per table and per column; declared type, nullability, key participation, unit or currency; business description sourced from the data dictionary where matched (`data_dictionary`) and generated from name, type and samples otherwise (`generated`); up to `schema_kb_sample_value_count` distinct sample values; the M-Schema-style rendering per table; relationship edges from declared foreign keys and manifest joins
    - Rebuild in full on dataset change under an incremented version, re-embed every entry, and mark the version `complete` only after every entry and embedding is written
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10, 9.15_

  - [ ] 3.3 Implement the Schema_Linker hybrid retrieval
    - Create `app/services/pipeline/schema_linker.py` following the design's `link()` pseudocode: both arms normalised to 0.000–1.000 before combining at the configured weights, `min_combined_retrieval_score` cut, prompt-token budget fill in descending score order with selected table entries and edge-participating columns admitted first, join-path closure over the shortest connecting path up to `max_join_path_length`, empty sub-schema plus schema-linking failure when nothing clears the threshold, retrieval restricted to the most recently completed `Schema_KB` version while a rebuild is in progress, and the full trace payload of Requirement 3.9
    - _Requirements: 3.7, 3.8, 3.9, 3.11, 3.12, 3.13_

  - [ ]* 3.4 Unit-test sub-schema assembly
    - Create `tests/unit/test_schema_linker.py` covering budget-fill ordering with excluded-entry reporting, join-path closure at exactly 2 edges and beyond, the empty-sub-schema path, and version isolation during a rebuild
    - _Requirements: 3.8, 3.11, 3.12, 3.13_

- [ ] 4. Stage 3 — The safe-execution boundary (build this before any model writes SQL)
  **Tier: required.** Design: F-5, §4.3 (`AcceptVerdict` and the validation walk), §5.1, Security considerations.
  **Gate ownership:** tasks 4.3 and 4.5 are the first of the plan's two hard gates. Both must be green
  before task 7.8 lets a model author SQL. Reordering the plan does not move this gate.

  - [ ] 4.1 Build the SQL property generators
    - Create `tests/properties/generators/sql.py` with `hostile_sql()` (stacked statements, DDL, DML, `FOR UPDATE`/`FOR SHARE`, `SELECT INTO`, `CREATE TABLE AS`, `COPY … TO`, `pg_read_file`, `pg_sleep`, `dblink`, `lo_import`, `current_setting`, unknown identifiers, join-ambiguous unqualified columns, over-maximum row limits, and comment-obfuscated variants of each), `well_formed_select()` (SELECTs over the active `Schema_KB` with joins, CTEs, grouping, ordering, set operations and allowlisted functions), and `metric_binding()` (bound `Metric_Layer` statements)
    - The pair makes Property 1 two-sided: nothing from `hostile_sql()` may be accepted, everything from `well_formed_select()` must be, which catches an over-tight allowlist as well as an over-loose one
    - _Requirements: 12.3, 12.4, 12.5, 12.11, 12.12, 12.13, 12.14_
    - _Properties: P1, P2, P33_

  - [ ] 4.2 Implement the SQL_Validator
    - Create `app/schemas/validation.py` (`AcceptVerdict` with `canonical_sql`, bound `parameters`, referenced tables and columns, applied row limit, intent family, validation duration; `RejectVerdict` with the design's category enumeration and `guardrail_violation` flag) and `app/services/pipeline/sql_validator.py` implementing the design's single-pass SQLGlot AST walk
    - Enforce it as an **allowlist**: statement-type check, accepted-node-type allowlist, function allowlist, row-locking and result-target rejection, schema conformance against the pinned `Schema_KB` version with unqualified-identifier resolution, declared-row-limit ceiling, default row limit injection for listing intents, parameter binding for every user-derived literal, the 100 ms budget as a guardrail violation, and `canonical_sql` regenerated from the AST so the executor never sees a model-authored string
    - Route every `Metric_Layer`-bound statement through the same validator
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10, 12.11, 12.12, 12.13, 12.14, 12.15, 4.13_
    - _Properties: P1, P2_

  - [ ] 4.3 Gate: get Properties 1 and 2 green
    - Create `tests/properties/test_sql_validator.py` using `hostile_sql()`, `well_formed_select()` and `metric_binding()`, tagged with the property numbers; assert no accepted candidate carries a forbidden node, function, lock or result target, and that every accepted candidate's tables and columns exist in the pinned `Schema_KB`
    - **This gate must be green before task 7.8 (`SQL_Generator`) begins** — the boundary exists before a model is allowed to author SQL
    - _Requirements: 12.1, 12.3, 12.4, 12.5, 12.6, 12.7, 12.11, 12.12, 12.13, 3.1, 3.2, 4.12_
    - _Properties: P1, P2_

  - [ ] 4.4 Implement the Query_Executor
    - Create `app/services/pipeline/query_executor.py` connecting exclusively through the `tbx_reader` engine: read-only transaction, per-statement timeout with a typed timeout error carrying the executed SQL, execution row cap with partial-result discard, plan requests without executing the candidate, the five execution kinds recorded as trace events, concurrency limit with a wait queue and typed capacity error, dataset-version pin check aborting before execution on drift, per-Turn execution counting, and execution of only the `AcceptVerdict.canonical_sql`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11, 13.12, 13.14, 13.15_

  - [ ] 4.5 Gate: get Properties 33, 35 and the execution bounds green
    - Create `tests/properties/test_execution_bounds.py` (`query_shape()`: materialised rows never exceed the cap; executions per Turn never exceed the configured maximum across all five kinds) and `tests/properties/test_dataset_pinning.py` (`activation_interleaving()`: every query of a Turn carries the same dataset-version predicate, and mid-Turn activation terminates with `dataset_version_changed` rather than mixing versions)
    - Assert Property 33 directly: every executed statement is byte-identical to an `AcceptVerdict.canonical_sql` for the same Turn with exactly that verdict's parameter set
    - **This gate must be green before task 7.8 (`SQL_Generator`) begins**, for the same reason as 4.3
    - _Requirements: 13.4, 13.9, 13.10, 13.14, 13.15, 12.15, 4.13_
    - _Properties: P15, P29, P33, P35_

- [ ] 5. Checkpoint — the security boundary is proven before any model is configured
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Stage 4 — Model provider layer, budgets and the intake agent
  **Tier: required.** Design: F-1, F-1a, §4.1, §4.3 (`Model_Router`), §4.5.
  This is the front half of the demo slice: without it there is no `intake`, `context_resolution`,
  `intent_classification` or `entity_resolution` in the trace. `Budget_Guard` is built here, with the
  provider layer rather than behind it, because the token budget is 20% of the score and the demo path
  now spends tokens on every Turn.

  - [ ] 6.1 Implement the Model_Router, agent factories and instrumentation hooks
    - Create `app/services/model/router.py`: the six provider values, per-role resolution of provider, model id, temperature, max output tokens and prompt version from configuration, role defaults, 2-attempts-per-provider and ≤6-total fallback policy, typed provider-unavailable and structured-output errors with one retry then fallback, configured-model-unavailable routing without retry, startup marking of providers missing credentials or endpoints with the missing names exposed, one model call record per attempt including retries, and `GET /api/admin/models`
    - Create `app/services/model/agents.py` where `agent_for()` is the only place a Strands `Agent` is constructed — a fresh `Agent` per role per Turn with cached model objects, never `UNSAFE_REENTRANT` — invoked exclusively as `await agent.invoke_async(prompt, structured_output_model=…, limits=Limits(turns=1, output_tokens=…), cancel_signal=turn.cancel_signal)` and never via `structured_output_async` (design F-1a(a)), with temperature 0 forced under an evaluation run
    - Create `app/services/model/hooks.py` (`TurnInstrumentation`): `BeforeInvocationEvent` reservation setting `event.cancel`, `BeforeModelCallEvent` re-check against `projected_input_tokens`, `AfterModelCallEvent` model call record with provider-reported tokens cross-checked against SDK metrics, `AfterInvocationEvent` `stop_reason` classification and truncated-output-as-non-conformance handling
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.10, 9.11, 9.12, 9.13, 10.6, 21.4, 26.12_

  - [ ] 6.2 Implement the Budget_Guard
    - Create `app/services/pipeline/budget_guard.py` with the design's three enforcement layers: pre-flight reservation, per-invocation `Limits`, and a per-Turn `threading.Event` watchdog for the wall-clock deadline; the authoritative post-hoc token ledger with the deterministic estimator for providers reporting no usage and `estimated` flagging; the `Metric_Layer` call limit; dry-run and reviewer call accounting; the reviewer phase deadline; Turn-only scope with offline pipeline figures reported separately; and the Requirement 10.5 outcome — release the most recent groundedness-approved answer, else abstain with `budget_exhausted` and record the limit reached
    - Implement the design's stated priority: a groundedness regeneration that would breach the call limit is cancelled and the Turn falls to the templated answer rather than raising the limit
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.10, 10.11, 10.12, 14.14, 14.16_

  - [ ] 6.3 Property-test budget enforcement
    - Create `tests/properties/test_budget.py` using `turn_scenario()` with the call-counting `StubModelProvider`: no `Metric_Layer` Turn exceeds the metric call limit, and no Turn on either path exceeds the per-question call, token or wall-clock limits
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.10, 10.12_
    - _Properties: P30_

  - [ ] 6.4 Implement the single intake call: Context_Resolver and Query_Planner
    - Create `app/schemas/intake.py` (`IntakeResult`), `app/services/pipeline/context_resolver.py` and `app/services/pipeline/query_planner.py`: one structured call returning resolved question, intent family, entity resolutions, date resolutions and metric routing, projected into four separate trace events
    - Cover intent classification over the ten families, absolute date-range resolution against the configured reference date with the default analysis period, multi-format date ambiguity routed to clarification, entity resolution by exact then case-insensitive then fuzzy matching with the minimum score and disambiguation margin, at-most-5 candidate clarifications, out-of-coverage and unresolved-entity abstentions, anaphora and ellipsis resolution from conversation state, filter override by an explicit follow-up value, period-comparison filter retention, resolved-question echo, retained turn count, session context timeout discard, unchanged state on abstention or error with pending clarification persisted separately, and identical resolved text for an identical follow-up against unchanged state
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 1.10, 1.11, 1.12, 1.13, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12_

  - [ ] 6.5 Property-test context resolution and date resolution
    - Create `tests/properties/test_context_resolver.py` with `conversation_state()` and `followup_grammar()`: an identical follow-up against unchanged state yields identical resolved question text and identical executed SQL (P9)
    - Create `tests/properties/test_date_resolution.py` with `date_phrase()`, `reference_date()` and `coverage_window()`: start ≤ end always, and either coverage intersection or a `period_outside_coverage` abstention stating the dataset's earliest and latest dates (P13)
    - _Requirements: 1.3, 1.4, 1.10, 1.11, 1.12, 2.1, 2.6, 2.7, 18.6_
    - _Properties: P9, P13_

  - [ ] 6.6 Implement the Exemplar_Bank and Prompt_Registry
    - Create `app/db/models/ops_artefacts.py`, `app/services/knowledge/exemplar_bank.py` and `app/services/knowledge/prompt_registry.py`: versioned artefact rows where only the `active` version is ever read by a Turn, exemplar retrieval for question similarity and query-shape diversity, exclusion of exemplars referencing absent tables or columns with the excluded count traced and generation continuing on a reduced or empty set, and applicability marking per dataset version
    - Create `golden/exemplars.yaml` with the seed demonstration pairs and seed one prompt version per role from design §4.5's prompt inventory
    - _Requirements: 11.2, 11.11, 5.14, 25.12_
    - _Properties: P27 (read-active half)_

- [ ] 7. Stage 5 — The demo slice: the generated-SQL path end to end with a live trace
  **Tier: required.** Design: §4.3 (`ComputationRecord`, `TraceEvent`, groundedness matcher, `VerdictRecord`,
  orchestrator), §4.4 (chat and trace surfaces), §4.5.
  **This epic is the demo.** It completes with a streamed trace that shows intake → schema retrieval with
  scored chunks → schema linking → exemplar retrieval → SQL generation with candidates → static validation
  → plan inspection → reviewer verdict → execution → computation → answer composition → groundedness check
  → confidence scoring → completion, and an answer whose every figure cites a computation record.
  **Gate ownership:** task 7.6 is the plan's second hard gate and must be green before task 7.7 wires the
  `Answer_Composer` to a real provider; tasks 4.3 and 4.5 must be green before task 7.8 runs.

  - [ ] 7.1 Implement the Computation_Layer
    - Create `app/schemas/computation.py` (`ComputationRecord`, `BreakdownColumn` per design §4.3) and `app/services/pipeline/computation.py`: `Decimal` throughout with no `float` on any monetary path, one computation record per released figure with its unrounded value, rounding only at formatting and only half away from zero, the single total ordering used by preview, retained snapshot and export, preview truncation with aggregates computed from the complete result set, withheld ratios and percentage changes with operands released, the both-zero percentage-change rule, NULL-row exclusion with excluded and aggregated counts, the zero-row outcome distinct from a computed zero, and per-currency records when an aggregation spans currencies
    - Implement `template_answer()` — the deterministic sentence generator Requirement 17.4 falls back to, and the reason a grounded answer still exists with no provider configured
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9, 15.10, 15.11, 15.12, 17.4_

  - [ ] 7.2 Property-test the computation layer
    - Create `tests/properties/test_computation.py` with `decimal_rows()` and `aggregation_spec()`: every released aggregate, ratio, difference and percentage change equals an independent reference implementation over the same rows with NULL rows excluded and counted (P4); breakdown rows sum to the reported total at the recorded precision with no binary float in the path (P18)
    - _Requirements: 15.1, 15.2, 15.4, 15.5, 15.6, 15.7, 15.10_
    - _Properties: P4, P18_

  - [ ] 7.3 Implement the Trace_Service with SSE and WebSocket
    - Create `app/schemas/trace.py` (`StageName`, `ModelCallRecord`, `TraceEvent` with redaction applied inside `model_post_init` so no emitter can bypass it) and `app/services/ops/trace_service.py`: an in-process per-turn ring buffer bounded by `trace_buffer_max_events` with orchestrator-allocated contiguous sequence numbers, fan-out to independent subscriber cursors, replay of the committed prefix before live attach, keepalive frames on a distinct event name outside the sequence numbering, per-stage attempt ordinals, `skipped` events with a reason code and 0 ms duration, dual truncation to size and inline row bounds with untruncated totals, emission within 200 ms of stage completion, and persistence to PostgreSQL within the persistence window regardless of terminal status
    - Create `app/routes/trace.py` with `GET /api/turns/{tid}/trace/stream` (`EventSourceResponse`) and `WS /api/turns/{tid}/trace/ws` reading the same buffer
    - The `output_summary` payloads of `schema_retrieval`, `schema_linking`, `exemplar_retrieval`, `sql_generation` and `reviewer_verdict` are what the demo renders, so their scored chunks, candidate statements and verdict reasons must survive truncation with their untruncated totals recorded
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 21.10, 21.11, 21.12, 21.13, 21.14, 22.1_

  - [ ] 7.4 Property-test trace sequencing and redaction
    - Create `tests/properties/test_trace.py` with `turn_scenario()` and `subscriber_schedule()`: contiguous 1..N excluding keepalives, non-decreasing timestamps, exactly one terminal event, a `skipped` event per bypassed stage, dense per-stage attempt ordinals, every subscriber observing 1..N in order whenever it connects, and the persisted list equal to the streamed list for every Turn whose terminal event streamed (P6); assert redaction is unavoidable at construction (P36)
    - Create `tests/properties/test_redaction.py` with `secret_planting()` across question text, SQL, error messages and reports, asserting no configured secret appears in any streamed or persisted event (P19)
    - _Requirements: 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.9, 21.10, 21.11, 21.12, 21.13, 22.1, 32.10_
    - _Properties: P6, P19, P36_

  - [ ] 7.5 Build draft_mutations() and implement the Groundedness_Checker
    - Create `tests/properties/generators/answers.py` with `draft_mutations()`: from a draft built only from sourced values, apply exactly one mutation — alter a digit, shift a decimal point, attach or change a scale word (thousand/lakh/crore/million/billion), re-express a figure in words, insert an unrelated numeral, round to a different place value, rename an entity, change a date
    - Create `app/services/pipeline/groundedness.py` following the design's `verify()` pseudocode: numeral, currency, percentage, date and words-with-scale extraction; matching at the place value of the least significant written digit within the configured tolerance against result-set values, computation-record values and unrounded values, row counts, group counts, enumerated counts and ordinals, and resolved-date-range bounds and covered calendar periods; entity-name matching after trimming, whitespace collapsing and case folding; rejection with a named unmatched value or unconvertible span and one regeneration request; the computation-records-first match order with the match source recorded, and the `groundedness_require_computation_record` tightening flag
    - _Requirements: 17.1, 17.2, 17.3, 17.5, 17.6, 17.7, 17.8, 17.9, 17.10, 17.11_

  - [ ] 7.6 Gate: get Properties 3 and 34 green
    - Create `tests/properties/test_groundedness.py` using `result_set()`, `computation_records()` and `draft_mutations()`: every mutation except lossless re-expression must flip the verdict to reject — this is where a wrong crore multiplier, a 100× error in a finance answer, gets caught
    - Assert Property 34 as a payload constraint: the composition prompt contains only computation-record values, the configured sample rows, the resolved filters and the resolved date range, never the complete result set
    - **This gate must be green before task 7.7 wires the composer to a provider.** The reorder puts a real
      provider on the demo path from the first Turn, which makes this gate more load-bearing than it was,
      not less
    - _Requirements: 17.1, 17.2, 17.3, 17.5, 17.8, 17.9, 17.10, 17.11, 15.1, 15.3, 16.1_
    - _Properties: P3, P34_

  - [ ] 7.7 Implement the Answer_Composer and the turn response contract
    - Create `app/schemas/chat.py` with `TurnResponse`, `AppliedFilter`, `FigureProvenance`, `ConfidenceSignal`, `ClarifyingQuestion` and `AnomalyCallout` exactly as design §4.3, serialising every monetary value as a JSON string
    - Create `app/services/pipeline/answer_composer.py`: composition from computation records plus `answer_composer_sample_row_count` sample rows only, stated absolute date range and currency, a computation-record citation per figure, the applied metric name, the word limits with and without the detailed option, breakdown column labels with value types and currency, figure provenance with stable ordering and truncation pointing at the export path, the applied-filter expressions with the combined excluded-record count, the deterministic templated fallback path, and the abstention explanation payload
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10, 16.11, 16.12, 17.4_
    - _Properties: P3, P34_

  - [ ] 7.8 Implement the SQL_Generator and the repair producer
    - **Precondition: tasks 4.3 and 4.5 are green.** No model authors SQL until the validator and executor properties hold
    - Create `app/services/pipeline/sql_generator.py`: generation from resolved question, linked sub-schema, retrieved exemplars and the configured dialect; at most `max_candidates_per_question` candidates with one per distinct normalised query form; emitted table and column references so no caller re-parses; prior-SQL-as-editable-start on a follow-up with the edit traced; sub-question decomposition; exclusion of candidates carrying a filter literal absent from both the question text and the `Schema_KB` samples; discard-and-retry for responses not yielding exactly one parsable statement; `generation_failed` when the retry limit leaves zero candidates; every candidate, exclusion and discarded response traced; and revised-candidate production from the reviewer's reason and defect category
    - _Requirements: 11.1, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 14.6_
    - _Properties: P1, P2_

  - [ ] 7.9 Implement the Reviewer_Agent, evidence bundle and repair loop
    - Create `app/schemas/verdict.py` (`DefectCategory`, `EvidenceCitation`, `VerdictRecord` with the defect-required validator) and `app/services/pipeline/reviewer.py`: the evidence bundle of resolved question, compact identifier-only schema projection, candidate SQL, parsed references, plan summary and `reviewer_evidence_sample_rows` dry-run rows; the intent-alignment checklist over aggregation, grouping, filters, date bounds, join cardinality and result columns; orchestrator-side citation membership checking against the assembled bundle; one verdict re-request on non-conformance then no-approve with a `reviewer_output_nonconformance` failure case; deadline and missing-evidence handling with `reviewer_unavailable`; order-insensitive multiset agreement with 2-decimal rounding and NULL matching, largest-agreement selection and lowest-index tie-break, and the minimum consistency signal on total disagreement; the zero-row single existence query classifying `suspected_filter_defect` or `true_empty_result` with the latter completing as an answer; repair iterations counted including revisions that fail static validation, with `repair_limit_reached` and a failure case on exhaustion
    - The `reviewer_verdict` trace event carries the verdict, reason and defect category the demo renders, so the verdict payload is a presentation surface as well as a control signal
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 14.9, 14.10, 14.11, 14.12, 14.13, 14.14, 14.16_
    - _Properties: P29_

  - [ ] 7.10 Implement the Confidence_Scorer
    - Create `app/services/pipeline/confidence.py` following the design's `score()` pseudocode: the documented eight-signal set each normalised to 0–1, configured weights rescaled over the applicable signals to sum to 1, reviewer-verdict and groundedness always applicable on an answered Turn, band mapping from the configured boundaries, the `Metric_Layer` first-attempt-approve floor at the `high` boundary, the caution naming the lowest weighted contribution with the configured tie order, the acceptance threshold as the release gate, and the full per-signal breakdown in the turn response
    - `confidence_scoring` is the penultimate stage of the demo trace, which is why the scorer is built here rather than with the refusal machinery in task 9; its property test (P14) stays with that suite in 9.4
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.8, 19.10, 19.11, 19.12_

  - [ ] 7.11 Implement the TurnOrchestrator, session store and Chat_API — the demo
    - Create `app/db/models/ops_conversation.py`, `app/services/ops/session_store.py` and `app/services/pipeline/orchestrator.py` following the design's `run_turn()` pseudocode: stage ordering, sequence-number allocation, one budget scope, explicit `skipped` emission on the `Metric_Layer` branch, a single `finish_*` exit point per Turn, the terminal trace event flushed before the HTTP response body, and the outermost handler that converts any unmapped error to `pipeline_fault`
    - Write both branches now, and leave the metric branch inert until task 9.1 lands: routing reports no template match, so every Turn takes the generated-SQL path and every retrieval and generation stage produces a real payload
    - Create `app/routes/chat.py` with session create/list/read/delete, `POST /api/sessions/{sid}/turns` returning the turn identifier in the initial response, question-length rejection leaving conversation state unchanged, unknown-session rejection, and cascade session deletion within 5 s
    - Verify the demo question end to end on the seed dataset against a configured provider, and again with `StubModelProvider` so CI needs no network: the streamed trace must carry `intake`, `context_resolution`, `intent_classification`, `entity_resolution`, `schema_retrieval`, `schema_linking`, `exemplar_retrieval`, `sql_generation`, `static_validation`, `plan_inspection`, `reviewer_verdict`, `execution`, `computation`, `answer_composition`, `groundedness_check`, `confidence_scoring` and `completion` with real payloads — `metric_routing` is the only `skipped` event on this path, and it carries its reason
    - Verify the deterministic templated answer path of 7.1 in a second test with no provider configured, so a grounded, traceable, verifiable answer still exists when the model layer is unavailable
    - _Requirements: 1.1, 1.7, 1.9, 21.14, 22.1, 32.1, 32.2, 32.11, 32.13_

  - [ ] 7.12 Property-test provider substitution and per-Turn execution bounds
    - Create `tests/properties/test_provider_swap.py` with `stub_provider_script()` including adversarial and non-conforming scripts: every request and response schema unchanged across providers and the grounding invariant of Property 3 still holding (P8)
    - Extend `tests/properties/test_execution_bounds.py` for the full Property 29 statement: a zero-row candidate triggers exactly one existence query, and total executions per Turn stay within the configured maximum across plans, dry-runs, existence queries and the final execution
    - _Requirements: 9.7, 9.10, 13.15, 14.8, 14.14, 17.3_
    - _Properties: P8, P29_

- [ ] 8. Checkpoint — the demo works: live agent trace, reviewer verdict, grounded answer
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Stage 6 — The deterministic path, refusals and failure capture
  **Tier: required.** Design: §4.3 (`Metric_Layer` routing, scorer with rescaling), §4.5 (worked budgets),
  Error handling (reason-code table), §5.4.

  - [ ] 9.1 Implement the Metric_Layer with the two demo templates
    - **Framing:** this is the accuracy-and-efficiency path and the offline fallback, not the demo default. Requirement 4 mandates it across 14 acceptance criteria and it protects the 30% accuracy weight; its 3-call / ≈3.6k-token budget against the generated-SQL path's 4-call / ≈7.4k (design §4.5) is the model-efficiency story that is 20% of the score. Demonstrate it as the "same question, deterministic path, fewer tokens" comparison against the task 7.11 answer, and as the path that still answers when no provider is reachable
    - Create `app/services/pipeline/metric_layer.py`: deterministic routing score over `routing_keywords` and intent families, `template_match_threshold` selection with every other above-threshold metric recorded, `template_tie_margin` routing to clarification with tied names and descriptions, parameterised binding with no string concatenation, missing-parameter and type/bounds non-conformance routing to clarification before any statement reaches the executor, submission of every bound statement to the `SQL_Validator`, and abstention with `metric_execution_failed` rather than falling back to generated SQL
    - Add `vendor_spend_over_period` and `unreconciled_transaction_listing` to `datasets/seed/manifest.yaml` with their `ops.metric_definitions` projection and activation gating
    - Activate the orchestrator's metric branch left inert by 7.11, including the four `skipped` trace events with their reason codes, and record the measured token and call counts of both paths for the same question
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.9, 4.10, 4.11, 4.13, 4.14_

  - [ ] 9.2 Implement the Abstention_Controller
    - Create `app/services/pipeline/abstention.py`: the total mapping from every terminating condition to exactly one of the 21 reason codes, data-absent abstentions naming the missing data and supported families, one clarifying question with at most 5 concrete options and the pending clarification state with an incremented round count, the clarification round limit yielding `clarification_exhausted`, breakdown exclusion and suppression of every numeric value other than the permitted coverage dates, coverage-range and closest-value responses, sub-threshold confidence routing to clarification when an ambiguity was named and to `confidence_below_threshold` naming the weakest signal when none was, the `true_empty_result` answer path keeping `data_absent` reserved for schema-level absence, and recording of every abstention and clarification with turn id, reason code and producing pipeline step
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9, 18.10, 18.11, 18.12, 18.13_

  - [ ] 9.3 Implement the Failure_Store and the feedback endpoint
    - Create `app/db/models/ops_improvement.py` and `app/services/ops/failure_store.py`: capture on reviewer reject, groundedness reject, negative feedback, evaluation-incorrect and every listed pipeline fault with the terminating condition and emitted reason code; the full Requirement 24.5 field copy with `not_applicable` for absent fields and `[REDACTED]` for every credential value; status and source enumerations; occurrence-count merging for open cases and recurrence linking for resolved ones; immutability of stored copies across later ingestion, manifest, prompt, exemplar or trace changes; the retention cap deleting applied and dismissed cases first; and open-case trace retention
    - Add `POST /api/turns/{tid}/feedback` to `app/routes/chat.py` with the 2000-character limit and its rejection
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.8, 24.9, 24.10, 24.11, 24.12, 24.13, 24.14, 22.10, 32.12_

  - [ ] 9.4 Property-test refusals, confidence and error conditions
    - Create `tests/properties/test_abstention.py` with `unanswerable_question()` and `terminating_condition()`: no figure and no breakdown on an unanswerable or ambiguous question (P5), and exactly one reason code from the Requirement 18.4 enumeration per terminating condition with the mandated failure case recorded (P31)
    - Create `tests/properties/test_confidence.py` with `signal_vector()`: score in [0,1], rescaled applicable weights summing to 1 within 0.001, both mandatory signals always applicable, and monotonicity under raising any single normalised value (P14)
    - Create `tests/properties/test_error_conditions.py` with `malformed_sql()` and `malformed_manifest()`: typed error or reason-coded abstention, never a numeric answer, with session state unchanged (P17)
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.6, 18.7, 18.8, 18.9, 18.11, 18.13, 19.1, 19.3, 19.6, 19.10, 19.11, 19.12, 24.9, 24.10, 24.11, 1.8, 1.12, 1.13, 32.13, 32.16_
    - _Properties: P5, P14, P17, P31_

- [ ] 10. Checkpoint — the deterministic path and the "I cannot answer that" demo both work
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Stage 7 — Golden question set and evaluation harness
  **Tier: required.** Design: Testing strategy (golden set format and runner), Model selection plan.

  - [ ] 11.1 Write the golden question set
    - Create `app/schemas/golden.py` (`GoldenEntry` per design §4.3) and `golden/questions.yaml` with at least 60 entries in that format against the seed dataset, covering vendor spend, category spend, account spend, transaction lookup, payout listing, reconciliation status and period comparison, plus multi-turn follow-ups declaring `context_turns`
    - Include at least 5 entries of class `abstain` — of which at least 2 request a range entirely outside the seed coverage window with `expected_reason_code: period_outside_coverage` — and at least 3 of class `clarify`, of which at least 1 names a vendor spelling the seed dataset resolves to two or more vendor records; declare expected columns, row-order significance and the tagged metric where applicable, and at least 3 tagged entries per metric definition
    - _Requirements: 26.1, 26.2, 8.6, 4.7_

  - [ ] 11.2 Implement the Evaluation_Harness and its comparator
    - Create `app/db/models/ops_evaluation.py`, `app/services/ops/evaluation.py` and `scripts/run_eval.py`: the pure comparator over `(expected, actual, declarations)` with row-count equality, comparison restricted to declared columns, 0.01 numeric tolerance, case-folded trimmed text, NULL matched only by NULL, row sequence honoured only where declared significant, and clarification or abstention on an `answer` entry scored as a non-match
    - Score grounding rate, abstention and clarification correctness with the helpful/unhelpful refusal split and ceiling, SQL validity, reviewer catch and false-rejection rates, first-attempt success, mean repair iterations, mean tokens and calls, and per-stage latency percentiles; run `context_turns` in one session scoring only the final turn; force temperature 0; repeat the set `evaluation_repeat_count` times recording mean and spread; refuse to start on dataset-version mismatch or exemplar leakage; stop with status `incomplete` on the token or wall-clock budget; persist every run; record per-band accuracy and calibration failures; and gate metric-definition activation on tagged-question accuracy
    - Add `POST /api/admin/evaluation/runs` and `GET /api/admin/evaluation/runs/{id}` plus `--compare` report generation
    - _Requirements: 26.3, 26.4, 26.5, 26.6, 26.9, 26.10, 26.11, 26.12, 26.13, 26.14, 26.15, 14.17, 18.14, 18.15, 19.7, 19.13, 4.7, 4.11_

  - [ ] 11.3 Property-test the comparator
    - Create `tests/properties/test_comparator.py`: reflexive on itself, insensitive to row order unless declared significant, tolerant at exactly 0.01 and intolerant above it, NULL matched only by NULL, and restricted to the declared expected columns — a bug here would silently invalidate every number in the deck
    - _Requirements: 26.3_

  - [ ]* 11.4 Measure the stated targets
    - Create `tests/integration/test_evaluation_targets.py` measuring schema-linking table recall against the golden set, execution accuracy and grounding rate with the pinned tier, text-Turn median and 95th-percentile end-to-end duration, and 500 000-row ingestion duration on the demonstration machine; report measured values rather than asserting the design can guarantee them
    - _Requirements: 3.14, 26.7, 10.7, 6.8_

- [ ] 12. Stage 8 — Dataset swap rehearsal (de-risks delivery day)
  **Tier: required.** Design: Architecture ingestion path, Delivery sequencing stage 8.

  - [ ] 12.1 Implement the API_Connector
    - Create `app/services/ingestion/api_connector.py` writing the same canonical tables, `Schema_KB` entries and validation report the local connector produces: base URL, per-entity path and auth header from configuration; declared pagination style with its final-page signal, page ceiling and repeated-position detection; retry on 429, 5xx, timeout and early close with 1 s/2 s/4 s backoff; whole-run failure with fetched records discarded and the previous version retained; missing-mapped-field failure with counts; identifier de-duplication with discarded counts; per-entity endpoint and record counts in the report; the ingestion deadline; and auth-value masking in every report
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12_

  - [ ] 12.2 Rehearse the swap: manifest variants, both source modes and the revert path
    - **Purpose: find out days early, not hours before submission, whether the organisers' file or endpoint shape breaks ingestion.** When the real dataset lands, adoption should be "write a manifest, run ingest, read the validation report"
    - Create `tests/properties/generators/manifest.py` with `manifest_variant()` (renamed columns, reordered columns, format changes across CSV/XLSX/SQL-dump, encoding changes, inserted BOM, source mode switched to `StubOrganiserApi`, altered thousands separators and currency symbols, parenthesised negatives) and `tests/properties/test_manifest_swap.py`: canonical tables, `Schema_KB` content and every golden answer invariant across variants (P7), and every Chat_API and Metrics_API schema unchanged across a dataset swap followed by a provider swap (P32)
    - Create `tests/integration/test_dataset_revert.py`: revert activates the most recent retained version with its bound `Schema_KB` version atomically within 30 s
    - _Requirements: 5.3, 5.4, 5.12, 6.2, 6.9, 6.10, 7.1, 7.6, 9.7_
    - _Properties: P7, P17, P32_

- [ ] 13. Stage 9 — Full metric catalogue and Metrics_API
  **Tier: optional.** Design: §4.4 (metrics surface and dashboard contract), §5.3 indexes.

  - [ ] 13.1 Complete the Metric_Layer catalogue
    - Extend `datasets/seed/manifest.yaml` and `golden/questions.yaml` with spend by category, spend by account, reconciliation summary by status, vendor payout listing and period-over-period comparison for each preceding metric, each with ≥3 tagged golden questions and activation gated on per-question accuracy
    - Note: Requirement 4.8's minimum catalogue coverage is unmet until this task completes; until then those question families take the generated-SQL path
    - _Requirements: 4.7, 4.8, 4.11_

  - [ ] 13.2 Implement the Metrics_API
    - Create `app/schemas/metrics.py`, `app/services/ops/metrics_service.py` and `app/routes/metrics.py` with all eleven endpoints of design §4.4; every ratio, rate, percentile and mean field emitted as `{value, measured_from}` where `value: null` is the not-measured marker; half-open UTC ranges with applied bounds returned and the default range applied when omitted; parameter rejection returning no metric fields; the frozen metric-identifier enumeration with the hourly-bucket span limit; drill-down ordering, page size and ceiling with total counts and turn identifiers; accuracy responses carrying run id, completion instant, questions scored and the evaluation-run scope field; and one shared `resolve(metric_id, range, bucket)` so overview, time series and drill-down cannot disagree
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6, 27.7, 27.8, 27.9, 27.11, 27.12, 27.13, 27.14, 27.15, 27.16, 27.17, 10.9, 24.7_

  - [ ] 13.3 Publish the dashboard contract
    - Create `docs/dashboard_contract.md` from the design's table, mapping every dashboard panel and analytics section to its endpoint, fields and scope, stating for each whether the supplying fields are scoped to an evaluation run or to a requested date range
    - _Requirements: 27.10_

  - [ ]* 13.4 Test metrics consistency, contract coverage and scale
    - Create `tests/properties/test_metrics_consistency.py` with `turn_population()`, `date_range()` and `bucket()` (P26); `tests/integration/test_openapi_contract.py` asserting every contracted endpoint and field appears in the generated OpenAPI schema (P24); `tests/integration/test_metrics_load.py` with 100 000 seeded turns against the 2-second bound (P23)
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6, 27.7, 27.8, 27.9, 27.10, 27.11, 27.12, 27.13, 27.15, 27.16, 27.17_
    - _Properties: P23, P24, P26_

- [ ] 14. Stage 10 — Persisted trace retrieval and breakdown export
  **Tier: optional.** Design: §4.4 (trace and export surfaces), §5.3.

  - [ ] 14.1 Add persisted trace retrieval and retention
    - Extend `app/services/ops/trace_service.py` and `app/routes/trace.py` with the full event list by turn id, the paged session trace summary ordered by creation time then turn id with a continuation token, execution-stage detail in the persisted trace, retention with deletion after the window plus 24 hours, the abandonment-window terminal `failed` event, per-field persistence truncation with the original length recorded, the deleted-versus-unknown client error distinction with the deletion timestamp, and retention override while an open failure case references the Turn
    - _Requirements: 22.2, 22.3, 22.4, 22.5, 22.6, 22.7, 22.8, 22.9, 22.10_

  - [ ] 14.2 Implement the Export_Service
    - Create `app/services/ops/export_service.py` and `app/routes/export.py` producing files exclusively from the persisted result-set snapshot with no re-execution: recorded column and row order so the presented rows lead the export, computation-record precision, the metadata worksheet for `xlsx` and `#`-prefixed metadata lines for `csv`, UTF-8 without BOM with the full quoting and CRLF rules, the apostrophe prefix for formula-injection candidates, typed numeric and text cells in `xlsx`, streaming response bodies, and the three distinguishable errors for abstained Turns, expired snapshots and rejected requests
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7, 23.8, 23.9, 23.10, 23.11, 23.12, 23.13_

  - [ ]* 14.3 Property-test the export round trip
    - Create `tests/properties/test_export.py` with `breakdown_table()` covering unicode, delimiters, quotes and newlines: parsing the exported file reproduces columns, row order, value types and recorded precision after removing the apostrophe prefix, with `xlsx` compared by parsed cell type and value (P10)
    - _Requirements: 23.1, 23.3, 23.4, 23.5, 23.8, 23.9, 23.10_
    - _Properties: P10_

- [ ] 15. Stage 11 — Voice input and output
  **Tier: optional.** Design: F-2, F-3, §4.4 (voice surface), New configuration deviations.

  - [ ] 15.1 Implement the Speech_Transcriber and the voice intake surface
    - Create `app/schemas/voice.py`, `app/services/ops/voice_service.py` and `app/routes/voice.py`: multipart audio accepted behind the body-size guard, format/duration/size/language pre-validation rejecting before the provider is called and leaving state unchanged, configured language list and mode, auto-detect requested by default so `language_probability` is returned as the observed confidence with the configured default recorded otherwise, the below-threshold confirmation path holding the Turn pending, identical downstream pipeline from transcript production with the wall-clock budget starting there, transcript returned alongside the answer, repeat-request response on failure or attempt exhaustion, provider durations accounted separately, Indic-numeral and scale-word normalisation before date and amount extraction, the transcription trace event, and audio bytes deleted after the retention period without ever touching disk
    - Record the two stated deviations in code comments: Sarvam returns no per-utterance transcription confidence, and `max_utterance_duration` ships at 30 s
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7, 28.8, 28.9, 28.10, 28.11, 28.12, 28.13, 28.14, 28.15, 10.15_

  - [ ] 15.2 Implement the Speech_Synthesizer and the spoken variant
    - Extend `app/services/ops/voice_service.py` and `app/services/pipeline/answer_composer.py`: the spoken variant derived deterministically through `Computation_Layer` number formatting with no model call, groundedness verification of the spoken variant by numeric-multiset equality with the written answer and fallback to synthesising the written text with a reason code, base64 segment payloads at sentence boundaries with no monetary figure split and 1-based indices that concatenate back to the submitted text, per-segment timeout and attempt limits, the per-Turn synthesis time budget accounted separately, the language-code mismatch and unsupported-language paths returning the written answer with a flag, the synthesis trace event, and the keyed audio cache
    - Omit `pitch` from the request body when the configured model is `bulbul:v3`, logging the omission once at startup
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7, 29.8, 29.9, 29.10, 29.11, 29.12, 29.13_
    - _Properties: P3_

  - [ ]* 15.3 Test voice paths
    - Create `tests/integration/test_voice_live.py` marked `live` with one English and one Indic utterance transcribing to non-empty text and synthesising to non-empty audio (P21); extend `tests/properties/test_error_conditions.py` with `malformed_audio()` for the pre-validation rejection paths (P17)
    - _Requirements: 28.1, 28.8, 28.10, 29.1_
    - _Properties: P17, P21_

- [ ] 16. Stage 12 — Buddy and Insights surfaces
  **Tier: optional.** Design: §4.1 (buddy issues zero model calls; insights is the only tool-using agent), §4.4.

  - [ ] 16.1 Implement the Buddy_Agent
    - Create `app/services/ops/buddy_service.py` and `app/routes/buddy.py`: starter and contextual questions as template mutations over the `Metric_Layer` catalogue and the Turn's resolved filters with zero model calls; every suggestion mapping to exactly one metric or intent family with entities, dimension values and periods drawn from `Schema_KB` samples and the coverage window and displayed in business-language labels; execution-checked candidates offered only when the mapped template returns ≥1 row; the below-minimum statement; contextual questions excluding already-asked and already-offered questions after trimming and case folding; the catalogue endpoint; term explanation from `Metric_Layer` and `Schema_KB` descriptions naming the columns with the `term_undefined` abstention plus catalogue fallback; precomputed starter lists per dataset version; and the no-model-call path when the budget is exhausted
    - _Requirements: 30.1, 30.2, 30.3, 30.4, 30.5, 30.6, 30.7, 30.8, 30.9, 30.10, 30.11, 30.12, 30.13_

  - [ ] 16.2 Implement the Insights_Buddy
    - Extend `app/services/ops/buddy_service.py` and create `app/services/model/tools/metrics_tools.py` and `app/routes/insights.py`: the only tool-using agent, one read-only `@tool` per metrics endpoint family, at most two calls; every figure obtained from a `Metrics_API` response with the endpoint identifier and bound parameters returned and every total, difference, ratio and rounded value derived through the `Computation_Layer`; no SQL generated or executed; bucketed series for trend questions; the separate `insights` session surface with its own conversation state carrying period, metric and granularity; evaluation-run identifier, completion date, dataset version and golden-set attribution stated for scored figures; exclusion of Insights turns from usage figures with separately labelled Insights turn count and cost; the abstention path naming a missing measurement or unsupported granularity with ≤5 supported measurements; the zero-record response; and per-question budget enforcement
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5, 31.6, 31.7, 31.8, 31.9, 31.10, 31.11, 31.12_

  - [ ]* 16.3 Property-test both buddy surfaces
    - Create `tests/properties/test_buddy.py` with `dataset_variant()`: every offered question submitted through the Chat_API against the same dataset version returns an answer rather than an abstention (P28); create `tests/properties/test_insights.py` with `analytics_question()` and `metrics_response()`: every stated figure appears in the recorded `Metrics_API` response and no SQL is generated or executed (P25)
    - _Requirements: 30.1, 30.2, 30.3, 30.6, 30.8, 30.9, 30.11, 31.2, 31.3, 31.5, 31.9_
    - _Properties: P25, P28_

- [ ] 17. Stage 13 — Self-improvement pipeline with human approval
  **Tier: optional.** Design: Architecture improvement loop, §5.4.

  - [ ] 17.1 Implement the Improvement_Pipeline and approval API
    - Create `app/services/ops/improvement.py` and extend `app/routes/admin.py`: single in-progress run enforced by the partial unique index; analysis of `new` and `triaged` cases with exactly one primary root cause from the thirteen-value enumeration; proposal selection in ascending creation order up to the per-run maximum leaving unselected cases untouched; concrete proposed artefact content per change type; grouping of identical fixes; `awaiting_approval` status recording affected artefact version identifiers with no artefact change applied; candidate version creation on approval leaving the active version untouched; the golden-set regression run before promotion with withheld promotion, candidate rejection and recorded figures or a timeout reason code; all-or-nothing atomic activation with both score sets recorded; the `stale` path on artefact drift; discard of `new_exemplar` proposals overlapping the golden set; version retention and revert; the approval audit trail; and offline model calls excluded from per-question budgets
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7, 25.8, 25.9, 25.10, 25.11, 25.12, 25.13, 25.14, 25.15, 25.16_

  - [ ]* 17.2 Property-test the artefact lifecycle
    - Create `tests/properties/test_artefact_lifecycle.py` with `proposal_sequence()` and `eval_score_pair()`: no version reaches `active` without an approval record and a regression run at or above the previous active version on both metrics, with all-or-nothing promotion (P20); no Turn ever reads a `candidate` version and at most one version per artefact is `active` at any instant (P27)
    - _Requirements: 25.5, 25.6, 25.7, 25.8, 25.9, 25.12, 25.14, 25.16_
    - _Properties: P20, P27_

- [ ] 18. Stage 14 — Anomaly callouts
  **Tier: optional.** Design: §4.3 (anomaly rule including the zero-dispersion branch).

  - [ ] 18.1 Implement the Anomaly_Detector
    - Create `app/services/pipeline/anomaly.py` following the design's `evaluate()` pseudocode: the modified z-score rule over the entity's own median and median absolute deviation with the configured threshold; the minimum history count; entity selection capped and ordered by largest returned value with identifier tie-break; a single history query through the `Query_Executor` over the configured window excluding the value under evaluation, capped in rows and counted against the per-question budget; the zero-dispersion branch requiring both the relative threshold and the absolute floor; at most three callouts in the mandated two-group order stating entity, flagged value, median and score rounded to 2 places with the relative difference substituted on the zero-dispersion branch; every figure computed in the `Computation_Layer`; skips recorded with a machine-readable reason code; the budget and time-limit skip; the configuration switch that omits callouts leaving the primary answer unchanged; and callout omission with a traced reason when a numeral fails grounding, releasing the primary answer unchanged
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 20.10, 20.11_

  - [ ]* 18.2 Property-test anomaly invariance
    - Create `tests/properties/test_anomaly.py` with `entity_history()` including constant series and `positive_scale()`: flags unchanged under history reordering, and unchanged under scaling every amount by a positive constant when the zero-dispersion absolute floor is scaled by the same constant, across both branches (P16)
    - _Requirements: 20.1, 20.2, 20.4, 20.5, 20.9_
    - _Properties: P16_

- [ ] 19. Stage 15 — Submission artefacts
  **Tier: required.** Depends only on required tasks 1–12; the optional stages are not prerequisites. Design: §4.2 (`docs/`, `scripts/`).

  - [ ] 19.1 Write the README
    - Create `README.md` with prerequisites, the single-command setup, the full environment-variable reference generated from `app/config.py`, the dataset swap procedure, the provider swap procedure, the evaluation command, the model-choice note section, and the ordered Chat_API calls that reproduce one answered question, one clarifying question and one abstention against the seed dataset after setup
    - _Requirements: 33.1, 33.6, 33.10_

  - [ ] 19.2 Produce the architecture diagram and its render command
    - Create `docs/architecture.mmd` in version control showing the ingestion path, `Schema_KB`, the agent pipeline, the reviewer layer, the execution path, the trace stream, the metrics store and the voice path, plus `scripts/render_architecture.py` as the one documented render command
    - _Requirements: 33.2_

  - [ ] 19.3 Generate the demo flow, sample questions, model-choice note and deck
    - Create `docs/demo_flow.md` with 5–12 ordered steps against the seed dataset, each stating the question text, the expected outcome class and, for answers, the expected figure; open with a generated-SQL question so the live trace carries every retrieval, generation and review stage, and include the `Metric_Layer` comparison step for the same question
    - Create `scripts/regen_sample_questions.py` producing `docs/sample_questions.md` from an actual run — ≥20 questions with ≥15 answers carrying executed SQL and confidence band, ≥3 abstentions with reason codes, ≥2 clarifications with the post-clarification self-contained question — recording the `Dataset_Manifest` version, code revision, per-role resolved model identifiers and run completion timestamp
    - Generate `docs/model_choice.md` from `scripts/run_eval.py --compare` with candidate × metric means and spreads, and create `docs/deck.md` with sections for problem, approach, model-choice rationale, grounding guarantees and demo flow, every score copied from one identified evaluation run; state plainly that the figure is measured on the project's own golden set rather than a public benchmark, that the accuracy comes from the harness, and that the grounding rate is a structural claim about the checker
    - _Requirements: 33.3, 33.4, 33.5, 33.7, 26.8_

  - [ ] 19.4 Implement the submission-artefact verification command
    - Create `scripts/verify_submission.py` replaying every demo-flow step in order against the seed dataset, exiting non-zero and naming the step when an observed outcome class or figure differs, and exiting non-zero naming each stale value when the recorded `Dataset_Manifest` version or code revision differs from the active ones
    - _Requirements: 33.8, 33.9_

- [ ] 20. Final checkpoint — required path complete and submission artefacts verify
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

### Execution Tiers

Machine-readable tier assignment. `required` tasks are the design's critical path; `optional` tasks are
real deliverables the demo survives without. Tier membership is unchanged by the reorder — only the task
identifiers moved.

```json
{
  "required": ["1.1","1.2","1.3","1.4","1.5","1.6",
               "2.1","2.2","2.3","2.4","2.5","2.6","2.7",
               "3.1","3.2","3.3","3.4",
               "4.1","4.2","4.3","4.4","4.5",
               "6.1","6.2","6.3","6.4","6.5","6.6",
               "7.1","7.2","7.3","7.4","7.5","7.6","7.7","7.8","7.9","7.10","7.11","7.12",
               "9.1","9.2","9.3","9.4",
               "11.1","11.2","11.3","11.4",
               "12.1","12.2",
               "19.1","19.2","19.3","19.4"],
  "optional": ["13.1","13.2","13.3","13.4",
               "14.1","14.2","14.3",
               "15.1","15.2","15.3",
               "16.1","16.2","16.3",
               "17.1","17.2",
               "18.1","18.2"]
}
```

### Gating rules

- Tasks 4.3, 4.5 and 7.6 are **gates**, not regression suites. 4.3 and 4.5 must be green before 7.8
  lets a model author SQL; 7.6 must be green before 7.7 wires the composer to a provider. They are
  deliberately not marked optional. The reorder puts a live provider on the demo path from the first
  Turn, which makes both gates more load-bearing than they were, not less — nothing about the new
  sequence relaxes them.
- `*` marks test sub-tasks that are non-gating example tests, performance measurements, live-service
  tests, or property suites belonging to optional stages. Property suites guarding required-stage
  behaviour carry no `*`, because grounding and accuracy are 50% of the score between them.
- The default test run is `pytest -m "not live"` and requires no network. Only 15.3 and any hosted
  provider run are `live`.

### Deviation from design.md's Delivery Sequencing

design.md places the `Metric_Layer` vertical slice at stage 4 and the generated-SQL path at stage 5, and
defends that order on the grounds that a template answer needs no provider, so a grounded demo survives a
credits or network failure. **This plan inverts the emphasis on the user's instruction:** the generated-SQL
agent path is the first demoable slice (tasks 6–7) and the `Metric_Layer` follows it (task 9.1).

Reason: the live execution trace is the stated wow factor, and the `Metric_Layer` path emits `skipped`
events for `schema_retrieval`, `schema_linking`, `exemplar_retrieval` and `sql_generation` (design §4.3
sequence diagram, Requirement 21.11) — precisely the four stages that make the trace worth watching. A
template answer therefore renders a visually empty trace on the flagship question. Credits for the demo
are confirmed, so the credits-risk argument the original order rested on no longer applies.

What is retained: the design's fallback rationale still holds in full, because the `Metric_Layer` (9.1)
and the deterministic templated answer of Requirement 17.4 (`template_answer()` in 7.1) both still exist,
both remain `required`, and both still work with no provider configured — task 7.11 tests that path
explicitly. What changed is which path the demo question takes, not whether a model-free path exists.
`Metric_Layer` also keeps its two other jobs untouched: Requirement 4's 14 acceptance criteria and the 30%
accuracy weight, and the 3-call / ≈3.6k-token efficiency story that is 20% of the score, now demonstrated
as the "same question, deterministic path, fewer tokens" comparison against the generated-SQL answer.

Two consequences of the inversion, recorded so they are not discovered later:

- The `Confidence_Scorer` moves from the refusals epic into the demo slice (7.10), because
  `confidence_scoring` is the penultimate stage of the trace the demo renders. Its property test (P14)
  stays with the refusals suite in 9.4.
- The `TurnOrchestrator` (7.11) is written with both routing branches but the metric branch is inert until
  9.1 lands: routing reports no template match, so every Turn takes the generated-SQL path. 9.1 activates
  the branch and its four `skipped` events. This costs one small edit in 9.1 rather than a rewrite, and it
  keeps the orchestrator's stage ordering written once.

### Property coverage

All 36 design properties are accounted for: P1–P2 (4.3), P3/P34 (7.6), P4/P18 (7.2), P5/P14/P17/P31
(9.4), P6/P19/P36 (7.4), P7/P32 (12.2, with the local-format subset in 2.6), P8/P29 (7.12), P9/P13
(6.5), P10 (14.3), P11/P12 (2.6), P15/P29/P33/P35 (4.5), P16 (18.2), P20/P27 (17.2), P21 (15.3), P22
(2.7), P23/P24/P26 (13.4), P25/P28 (16.3), P30 (6.3). P21 is a 2–3 example live integration test, P22 a
single integration run, P23 a load test and P24 an example contract test — scoped accordingly rather
than run as Hypothesis properties.

### Deliberate consequences of skipping the optional tier

- Requirement 4.8's minimum metric catalogue is unmet until 13.1; those families take the generated-SQL
  path instead — which, after the reorder, is the fully built and demoed path rather than the unfinished
  one.
- The `Metrics_API`, export, voice, buddy, insights, improvement and anomaly requirements (20, 23, 24
  partially, 25, 27, 28, 29, 30, 31) are unimplemented until their stages run. Requirement 24 capture is
  in the required tier (9.3) because `Failure_Store` is a dependency of evaluation and Property 31.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0,  "tasks": ["1.1"] },
    { "id": 1,  "tasks": ["1.2", "1.3"] },
    { "id": 2,  "tasks": ["1.4"] },
    { "id": 3,  "tasks": ["1.5"] },
    { "id": 4,  "tasks": ["1.6", "2.1"] },
    { "id": 5,  "tasks": ["2.2", "2.3"] },
    { "id": 6,  "tasks": ["2.4"] },
    { "id": 7,  "tasks": ["2.5"] },
    { "id": 8,  "tasks": ["2.6", "2.7", "3.1"] },
    { "id": 9,  "tasks": ["3.2"] },
    { "id": 10, "tasks": ["3.3", "4.1"] },
    { "id": 11, "tasks": ["3.4", "4.2"] },
    { "id": 12, "tasks": ["4.3"] },
    { "id": 13, "tasks": ["4.4"] },
    { "id": 14, "tasks": ["4.5"] },
    { "id": 15, "tasks": ["6.1", "6.6"] },
    { "id": 16, "tasks": ["6.2", "6.4"] },
    { "id": 17, "tasks": ["6.3", "6.5"] },
    { "id": 18, "tasks": ["7.1", "7.3"] },
    { "id": 19, "tasks": ["7.2", "7.4", "7.5"] },
    { "id": 20, "tasks": ["7.6", "7.8"] },
    { "id": 21, "tasks": ["7.7", "7.9"] },
    { "id": 22, "tasks": ["7.10"] },
    { "id": 23, "tasks": ["7.11"] },
    { "id": 24, "tasks": ["7.12"] },
    { "id": 25, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 26, "tasks": ["9.4"] },
    { "id": 27, "tasks": ["11.1"] },
    { "id": 28, "tasks": ["11.2"] },
    { "id": 29, "tasks": ["11.3", "12.1"] },
    { "id": 30, "tasks": ["11.4", "12.2"] },
    { "id": 31, "tasks": ["13.1", "14.1", "15.1", "18.1"] },
    { "id": 32, "tasks": ["13.2", "14.2", "15.2", "18.2"] },
    { "id": 33, "tasks": ["13.3", "14.3", "16.1", "17.1"] },
    { "id": 34, "tasks": ["13.4", "15.3", "16.2", "17.2"] },
    { "id": 35, "tasks": ["16.3"] },
    { "id": 36, "tasks": ["19.1", "19.2"] },
    { "id": 37, "tasks": ["19.3"] },
    { "id": 38, "tasks": ["19.4"] }
  ]
}
```
