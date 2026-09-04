# Requirements Document

## Introduction

TBX is a conversational, grounded finance assistant for the BVP Tech Catalyst Hackathon problem
statement *"Build a Finance Assistant That Actually Understands You"*. Business users and finance
teams ask plain-language questions about their own financial data — spend, vendor payouts,
reconciliation status — and receive an answer that is computed by SQL against the real dataset,
paired with the underlying records, and traceable end to end.

The product is a **text-to-SQL system with a verification layer**, not a chatbot with a database
attached. Grounding is the crux: every figure in every answer originates from an executed query, and
the language model never performs arithmetic. When the data cannot answer a question, or the question
is ambiguous, the assistant says so instead of producing a number.

Scope of this spec is the **backend** (FastAPI + AWS Strands Agents + PostgreSQL + Sarvam voice).
No user interface is implemented, but every figure a chat UI, a metrics dashboard and an analytics
page would need is exposed through documented, dashboard-ready HTTP APIs.

Eight capability areas are specified:

| # | Capability area |
|---|-----------------|
| A1 | Schema Knowledge Base for complex text-to-SQL |
| A2 | Swappable dataset with dual ingestion paths (organiser API or local files) |
| A3 | Swappable model-provider layer with a lightweight-model budget |
| A4 | Reviewer / verifier agent layer for maximum accuracy |
| A5 | Full execution trace exposed via streaming and persisted APIs |
| A6 | Self-improving pipeline driven by captured failures |
| A7 | Metrics, analytics and observability backend (dashboard-ready APIs) |
| A8 | Voice (Sarvam STT/TTS) and the conversational Buddy surfaces |

Hackathon scoring weights the requirements below: accuracy and grounding 30%, model efficiency 20%,
natural-language understanding 15%, functionality 15%, user experience 10%, presentation 5%, business
impact 5%.

---

## Research and Rationale Notes

Research findings that justify the technical choices encoded in the acceptance criteria. Sources are
linked inline; all summaries are paraphrased. *Content was rephrased for compliance with licensing
restrictions.*

### RN-1 — Schema representation and schema linking (A1)

- Feeding an LLM the whole database as raw DDL scales poorly and wastes the token budget. The
  [CHESS pipeline](https://arxiv.org/abs/2405.16755) reports that a dedicated schema-selection agent
  narrowing a large schema into a sub-schema raised accuracy by roughly 2% while cutting LLM tokens
  by about 5×, using four specialised agents (information retriever, schema selector, candidate
  generator, unit tester). This is directly relevant to the 20% model-efficiency score: schema
  selection is the cheapest accuracy-per-token lever available.
- [XiYan-SQL](https://arxiv.org/abs/2507.04701) introduces **M-Schema**, a semi-structured schema
  representation designed to make database structure easier for a model to read, combined with schema
  filtering, multi-candidate generation and a selection model; it reports 75.63% on BIRD and 89.65%
  on the Spider test set. An open implementation of the representation is published as
  [M-Schema](https://github.com/XGenerationLab/M-Schema), which builds the representation directly
  from a live PostgreSQL connection — a good fit for a dataset that must be re-derived on every swap.
- [MAC-SQL](https://arxiv.org/abs/2312.11242v1) decomposes the problem across a Selector (schema
  condensation), a Decomposer (splitting hard questions into sub-questions) and a Refiner (validating
  and repairing broken SQL). The decomposer pattern matters for finance questions that combine a
  filter, a grouping and a comparison window.
- [DAIL-SQL](https://arxiv.org/pdf/2308.15363v3) systematically compared question representation,
  example selection and example organisation, reaching 86.6% execution accuracy on Spider with about
  1600 tokens per question, showing that *retrieved* few-shot exemplars beat longer prompts.
  [Nan et al.](https://arxiv.org/abs/2305.12586) add that selecting demonstrations for both
  similarity and diversity, and augmenting with database knowledge, improves results further.
- Column and table descriptions are themselves an accuracy lever: XiYan's
  [automatic database description generation](https://arxiv.org/html/2502.20657v1) work reports
  measurable gains from generated descriptions versus none. This justifies ingesting the organisers'
  data dictionary into the Schema KB as first-class content and generating descriptions where the
  dictionary is silent.
- The deterministic alternative is a **semantic / metric layer** with pre-validated definitions
  instead of free-form SQL. Vendor and analyst write-ups report large accuracy gains from grounding a
  model in governed metric definitions rather than raw tables
  ([Cube](https://cube.dev/articles/semantic-layer-for-ai-agents-2026),
  [Atlan](https://atlan.com/know/ai-agent/semantic-layer/text-to-sql-vs-semantic-layer-for-self-serve-analytics/)),
  with the trade-off that a semantic layer only answers the questions it was modelled for, while
  text-to-SQL handles ad-hoc questions but is non-deterministic. These are vendor-affiliated sources,
  so the claim is treated as directional rather than as a benchmark.
- **Chosen primary approach (hybrid, semantic-layer-first):** a curated metric layer of
  pre-validated, parameterised SQL templates for the well-known finance questions (vendor spend over
  a period, unreconciled transactions, spend by category, month-over-month comparison), backed by
  retrieval-augmented free-form SQL generation over an M-Schema-style Schema KB for everything else.
  Rationale: the metric layer makes the demo questions deterministic and audit-clean (protecting the
  30% accuracy score), while the generative path preserves the open-question coverage that the
  hackathon judges will inevitably probe, and both paths flow through the same reviewer, execution
  and trace machinery. This also keeps the token budget low, since template resolution needs a small
  routing call rather than full SQL synthesis.
- **Chosen store:** PostgreSQL with `pgvector`, co-located with the financial data. Rationale:
  independent comparisons converge on "use the vector store you already run" when the corpus is small
  and lives next to relational data
  ([self-hosted comparison](https://d-central.tech/self-hosted-vector-databases/),
  [pgvector vs Chroma](https://markaicode.com/vs/pgvector-vs-chroma/)). A Schema KB for one finance
  dataset is at most a few thousand chunks, so no dedicated vector database is warranted, and a
  hosted knowledge base (Bedrock Knowledge Bases) would add a hard network dependency and a re-index
  round trip on every dataset swap — an unacceptable risk for an offline or flaky-Wi-Fi demo.

### RN-2 — Verification, hallucination avoidance and abstention (A4)

- Execution-guided approaches and self-consistency are the two established inference-time accuracy
  levers. [Execution-guided SQL generation](https://arxiv.org/html/2503.24364v1) frames
  self-consistency as sampling several reasoning paths and voting on the final answer;
  [CSC-SQL](https://arxiv.org/html/2505.13271) notes the two known weaknesses — majority voting can
  agree on a wrong query, and self-correction alone tends to fix only syntax — and combines both
  mechanisms to compensate. Consequence for this spec: vote on **execution results**, not on SQL
  text, and keep a repair loop for validation failures.
- [DPC](http://acl.ldc.upenn.edu/2026.acl-long.313/) names the failure modes that a pure
  LLM-as-a-judge reviewer suffers from: systematic bias (consensus on a hallucination) and symbolic
  blindness (inability to simulate execution). Consequence: the reviewer must be given real
  execution evidence — parse tree, EXPLAIN output, dry-run row counts, sample rows — rather than
  being asked to judge SQL text alone.
- Structural validation is cheap and deterministic. [SQLGlot](https://github.com/tobymao/sqlglot)
  parses SQL into an inspectable AST and detects syntax problems such as unbalanced parentheses and
  misused reserved words, which supports both read-only enforcement (statement type whitelisting) and
  schema conformance checks (every table and column referenced must exist in the Schema KB).
- Answer-level grounding is a separate concern from SQL correctness.
  [RAGAS](https://arxiv.org/html/2309.15217) established reference-free faithfulness scoring for
  generated answers, and practitioner guidance defines faithfulness/groundedness as *every claim in
  the answer being supported by the supplied context*
  ([Langfuse](https://langfuse.com/resources/engineering/rag-faithfulness-evaluation)). For a finance
  assistant the strongest available form of this check is not an LLM judge but a deterministic one:
  extract every numeric literal from the draft answer and require an exact match against the executed
  result set or a value derived from it by the data layer.
- Abstention is a measurable capability, not a fallback. Selective-prediction work on text-to-SQL
  reports that useful correctness signals come from reasoning-based signals rather than raw token
  probabilities ([selective-prediction study](https://arxiv.org/html/2607.06799)), so the confidence
  score in this system is composed from observable pipeline signals (template match, candidate
  agreement, reviewer verdict, schema-linking margin, row-count sanity) rather than from model
  logprobs, which several hosted providers do not expose anyway.
- Evaluation metric choice follows [BIRD](https://arxiv.org/abs/2305.03111), which popularised
  execution accuracy and a valid-efficiency measure over large, dirty, real-world databases; BIRD also
  documents how far models sit below human performance, which is the argument for the reviewer layer
  existing at all.

### RN-3 — Multi-turn conversation (must-have)

Conversational text-to-SQL is a distinct, benchmarked problem (SParC, CoSQL). Practical finding from
[CoE-SQL](https://aclanthology.org/2024.naacl-long.361/): a follow-up query is usually a small edit
of the previous query, so prompting the model to edit the previous SQL rather than re-derive it from
scratch performs well and costs fewer tokens. This spec therefore requires an explicit
question-rewriting step (produce a self-contained question from the conversation, as in
[CQR-SQL](https://arxiv.org/html/2205.07686v3)) plus previous-SQL-as-context editing, which also
makes multi-turn behaviour inspectable in the trace and testable for idempotence.

### RN-4 — Self-improvement without retraining (A6)

- Prompt and exemplar optimisation is a documented substitute for fine-tuning.
  [DSPy](https://dspy.ai/api/optimizers/MIPROv2/) treats prompt construction as a compilation problem
  where an optimiser jointly searches instructions and few-shot demonstrations against a metric;
  [GEPA](https://arxiv.org/abs/2507.19457) reports that reflective prompt evolution beat a
  reinforcement-learning baseline by around 6% on average with far fewer rollouts, and beat MIPROv2
  by over 10% on one task. Both confirm that failure-driven prompt/exemplar evolution is the
  right-sized improvement loop for a hackathon timeline.
- A [multi-use-case DSPy study](https://arxiv.org/html/2507.03620v1) applied the same machinery to
  guardrail enforcement and hallucination detection, supporting the design here where the reviewer's
  own prompt is one of the optimisable artefacts.
- Consequence for wording: what this system improves is **prompts, exemplars, schema descriptions and
  metric templates** — not model weights. The glossary records that distinction explicitly, because
  "retraining" is the term users reach for.

### RN-5 — Model provider abstraction and the lightweight tier (A3)

- The Strands Agents SDK abstracts model providers behind one interface, with documented support for
  Bedrock, Anthropic, OpenAI, Gemini and Ollama among others, and states that swapping the backend
  leaves agent code unchanged ([Strands](https://strandsagents.com/docs/learning/switching-model-providers/),
  [harness SDK](https://github.com/strands-agents/harness-sdk)). Its agent loop also traces every
  decision and exposes hooks to intercept steps — useful for A5 tracing and A3 budget enforcement.
- [LiteLLM](https://docs.litellm.ai/) provides an OpenAI-format facade over roughly 100 providers
  with fallbacks, spend tracking and load balancing, and is the pragmatic escape hatch for a provider
  Strands does not cover natively (for example an arbitrary OpenRouter or Azure deployment).
- Small models are viable for this task with the right harness: a cross-family BIRD study reports
  Qwen2.5-Coder-7B at 39.1 execution accuracy versus CodeLlama-7B at 20.9 at matched size
  ([on-prem open LLM frontier](https://arxiv.org/abs/2606.29733)), and multi-agent discussion has
  been reported to add up to ~10.6 points of execution accuracy for a 7B model on BIRD Mini-Dev
  ([agent/pipeline benchmark](https://arxiv.org/html/2511.04153)). Read together: a ≤8B model plus
  schema selection, retrieved exemplars, a metric layer and a reviewer loop is a defensible answer to
  the model-efficiency criterion, and the accuracy gap to a frontier model is closed by the harness
  rather than by parameters.

### RN-6 — Voice (A8)

Sarvam's documentation describes Saarika speech-to-text covering 11 languages with dialect, accent
and code-mixed audio handling and proper-noun preservation, plus transcription modes including
translate, verbatim, transliterate and code-mix; Bulbul text-to-speech covers 11 languages
(10 Indian plus English) addressed by BCP-47 codes with adjustable pitch, pace and speaker
([Saarika](https://docs.sarvam.ai/api/getting-started/models/saarika),
[Bulbul](https://docs.sarvam.ai/api/getting-started/models/bulbul),
[building for India](https://docs.sarvam.ai/api-reference-docs/building-for-india)). Code-mixed
input support matters because Indian finance users mix English metric names into Hindi sentences.
Language coverage and mode names are read from configuration rather than hard-coded, so provider
changes stay configuration-only.

### RN-7 — Analytics KPIs (A7)

Conversational-product KPI guidance consistently separates automation efficiency from quality and
cost, and warns against a single headline number: containment can be inflated by a bot that exhausts
the user, and deflection that produces a repeat contact is not a success
([Netguru](https://www.netguru.com/blog/chatbot-kpis),
[Balto](https://www.balto.ai/blog/kpis-for-voice-ai-agents-in-contact-centers/)). Practitioner
guidance also stresses tracking fallback rate and cost per resolution alongside satisfaction
([Conferbot](https://www.conferbot.com/blog/chatbot-kpis-metrics-guide)). Translated into this
domain: report execution accuracy against a golden set, grounding rate, abstention correctness split
into helpful and unhelpful refusals, reviewer catch rate and false-rejection rate, SQL validity,
repair iterations, first-attempt success, clarification rate, per-stage latency percentiles, and
tokens/cost per resolved question — never a single "accuracy" figure.

### RN-8 — Reuse from the reference project (`twid_minerva`)

Conventions worth inheriting, verified by reading the source:

- `pydantic-settings` `Settings` singleton with typed fields, defaults as named module constants,
  and `field_validator(mode="before")` coercion so a blank environment variable falls back to the
  default instead of crashing startup (`backend/app/config.py`).
- Layered package layout: `routes/` (HTTP), `services/` (logic), `schemas/` (Pydantic contracts),
  `db/models/` (SQLAlchemy), Alembic migrations run explicitly, `uv` for dependency management,
  `ruff` lint with `E,F,I`, `pytest` with `asyncio_mode = "auto"`.
- Explicit per-turn budget backstops as configuration: session token cap, per-turn wall-clock
  deadline, maximum tool cycles per turn — the same three levers this spec needs for A3.
- A trace accumulator that assembles streaming provider events into completed, individually timed
  trace rows keyed by a stable call id, with per-call durations rather than gap-since-last-event
  timings (`backend/app/services/trace_accumulator.py`). The A5 trace model follows this shape.
- `startup_checks.assert_single_process()` as the pattern for failing loudly when in-memory
  per-turn state would be corrupted by multiple workers.

Inherited constraints to record: in-memory turn state implies a single-process deployment unless
turn state is moved into PostgreSQL; and the reference project's Bedrock-specific harness client is
**not** reused, because A3 requires provider neutrality.

---

## Glossary

- **Abstention**: A deliberate response in which the assistant declines to state a figure and
  explains that the data cannot answer the question or that the question is ambiguous.
- **Abstention_Controller**: The component that decides between answering, asking one clarifying
  question and abstaining, and that attaches a machine-readable reason code to each outcome.
- **Acceptance threshold**: The configured minimum confidence score at which an answer is returned
  as an answer rather than as an abstention or a clarifying question.
- **Anomaly_Detector**: The component that applies a documented deterministic rule to flag unusual
  values (for example a vendor payout far above that vendor's own history).
- **Answer_Composer**: The component that turns an executed result set into a natural-language answer
  plus a breakdown table.
- **API_Connector**: The ingestion connector that reads the dataset from an HTTP API published by the
  hackathon organisers.
- **Artefact version status**: The lifecycle label an artefact version carries — `candidate`, `active` or
  `rejected` — where only an `active` version serves question-answering requests.
- **Breakdown table**: The tabular set of records or grouped aggregates that supports an answer,
  returned alongside it so a user can verify the figure.
- **Budget_Guard**: The component that enforces per-question and per-session limits on LLM calls,
  tokens and wall-clock time.
- **Buddy_Agent**: The conversational surface that helps a non-technical user decide *what to ask*
  about the finance data, using schema-aware and data-aware suggestions.
- **Candidate query**: One SQL statement produced by the SQL_Generator, or bound by the Query_Planner
  from a Metric_Layer template, that is submitted to the SQL_Validator before any execution attempt.
- **Chat_API**: The HTTP surface for sessions, turns, messages, streaming and feedback.
- **Combined retrieval score**: The single score per Schema_KB entry, normalised to the range 0.000 to
  1.000, that the Schema_Linker forms by combining keyword retrieval and vector similarity retrieval
  for one resolved question.
- **Computation_Layer**: The deterministic, non-LLM code path that filters, groups, aggregates,
  rounds and formats values from executed query results.
- **Computation record**: The record the Computation_Layer emits for one released figure, holding the
  figure value, the unrounded value, the label, the unit or currency, the source column and the
  identifier of the query that produced the figure.
- **Confidence_Scorer**: The component that combines observable pipeline signals into a calibrated
  confidence score and a confidence band.
- **Context_Resolver**: The component that rewrites a follow-up question into a self-contained
  question by resolving anaphora, ellipsis and inherited filters from conversation state.
- **Dataset contract severity**: The classification every dataset contract rule carries, either
  `blocking`, which aborts a load when the rule is violated, or `tolerable`, which permits the load to
  proceed and is recorded in the ingestion report.
- **Dataset_Manifest**: The declarative configuration file that describes a dataset — its source
  mode, entities, files or endpoints, column mappings, data-dictionary location and metric
  definitions. Swapping datasets means replacing this file and re-running ingestion.
- **Dataset version identifier**: The identifier the Ingestion_Service assigns to each ingested
  dataset version, bound to the Schema_KB version identifier derived from that dataset version.
- **Demonstration machine**: The developer laptop running the documented Docker Compose stack,
  providing at least 4 processor cores and 8 gigabytes of memory, against which every latency bound
  and every ingestion-duration bound stated in this document is measured.
- **Evaluation_Harness**: The offline runner that executes the golden question set against a
  configured model and pipeline variant and reports scored results.
- **Evidence bundle**: The set of artefacts the Reviewer_Agent receives for one candidate query — the
  resolved question, the linked sub-schema, the candidate SQL, the parsed table and column
  references, the execution plan and the dry-run sample rows.
- **Execution accuracy**: The fraction of golden questions for which the executed query result
  matches the expected result, following the BIRD convention.
- **Exemplar_Bank**: The versioned store of question/SQL demonstration pairs retrieved as few-shot
  examples at generation time.
- **Export_Service**: The component that renders a breakdown table as CSV or Excel.
- **Failure_Store**: The database tables holding flagged failure cases with their full context.
- **Faithfulness (grounding)**: The property that every claim, and in particular every number, in an
  answer is supported by the executed result set or by a Computation_Layer derivation of it.
- **Finance_Assistant_Backend**: The whole system specified by this document; used in requirements
  that apply to the service as a whole.
- **Golden question set**: The curated, version-controlled set of questions with expected SQL,
  expected results and expected behaviours (including questions that must produce an abstention).
- **Groundedness_Checker**: The component that verifies a draft answer against the executed result
  set before the answer is released.
- **Helpful refusal**: An abstention returned for a golden entry whose expected behaviour class is
  `abstain`.
- **Improvement_Pipeline**: The triggered process that analyses the Failure_Store, attributes root
  causes, proposes concrete artefact changes, and submits them for human approval.
- **Improvement run**: One triggered execution of the Improvement_Pipeline over the Failure_Store, holding
  status `in_progress` while running and bounded by the configured maximum proposals per run.
- **Ingestion_Service**: The component that loads a dataset into PostgreSQL and derives the
  Schema_KB, via either the Local_File_Connector or the API_Connector.
- **Insights_Buddy**: The conversational surface for exploring the system's own analytics and
  metrics (usage, accuracy, latency, cost, trends), distinct from the finance data assistant.
- **Local_File_Connector**: The ingestion connector that reads CSV, Excel or SQL dataset files from
  local storage.
- **Metric_Layer**: The curated set of named, parameterised, pre-validated SQL templates covering the
  known finance question families.
- **Metrics_API**: The HTTP surface exposing every KPI, time series and breakdown that a metrics
  dashboard or analytics page needs.
- **Model_Router**: The provider-agnostic abstraction that resolves a logical role (router, SQL
  generator, reviewer, composer, buddy) to a concrete provider and model from configuration, and
  applies fallbacks.
- **Normalised query form**: The comparison form of a candidate query, formed from its SQL text by
  collapsing whitespace, lower-casing keywords and renaming table aliases in order of first
  appearance; two candidate queries sharing a normalised query form are duplicates of each other.
- **Not-measured marker**: The explicit response value the Metrics_API returns for a ratio, rate,
  percentile or mean field computed from zero records, distinct from the value 0.
- **Number written in words**: A number written in words in answer text, alone or combined with one of
  the scale words thousand, lakh, crore, million and billion (for example "two crore").
- **Pending clarification state**: The per-session state retained while a clarifying question is
  outstanding, holding the original question text, the named ambiguity and the clarification round
  count, and persisted separately from conversation state.
- **Prompt_Registry**: The versioned store of system prompts and templates used by each role.
- **Proposal**: One approvable unit of change produced by the Improvement_Pipeline, carrying one status
  from `awaiting_approval`, `approved`, `rejected` and `stale`, the proposed artefact content, and the
  identifiers of the affected artefact versions recorded at proposal creation.
- **Query_Executor**: The read-only database access path that runs validated SQL under a restricted
  role, statement timeout and row limit.
- **Query_Planner**: The component that classifies intent, extracts entities, filters and date
  ranges, decomposes complex questions and chooses between the Metric_Layer and generated SQL.
- **Result-set snapshot**: The persisted copy of the complete executed result set of a Turn, retained
  for export and audit.
- **Reviewer_Agent**: The verification layer that inspects a candidate query with execution evidence
  and returns a verdict of approve, repair or reject with reasons.
- **Reviewer false-rejection rate**: The fraction of golden questions whose first candidate result set
  agrees with the expected result set and whose Reviewer_Agent verdict is `repair` or `reject`.
- **Schema_KB**: The retrievable knowledge base of tables, columns, types, descriptions, distinct
  value samples, relationships and metric definitions derived from the active dataset.
- **Schema_KB version identifier**: The incrementing identifier of one complete Schema_KB build, used
  to bind Schema_KB entries and embeddings to a dataset version and to scope retrieval while a rebuild
  is in progress.
- **Schema_Linker**: The component that retrieves the minimal relevant sub-schema for a question
  from the Schema_KB.
- **Seed_Data_Generator**: The command that generates the deterministic synthetic dataset used for
  development and demos before the organisers' dataset arrives.
- **Self-improvement (versus retraining)**: In this system, improvement means changing prompts,
  exemplars, schema descriptions and metric templates under human approval. Model weights are never
  trained or fine-tuned.
- **SQL_Generator**: The component that produces candidate SQL from a resolved question, a linked
  sub-schema and retrieved exemplars.
- **SQL_Validator**: The static, non-LLM validator that parses candidate SQL and checks statement
  type, schema conformance and guardrail compliance.
- **Speech_Synthesizer**: The Sarvam-backed text-to-speech component.
- **Speech_Transcriber**: The Sarvam-backed speech-to-text component.
- **Spoken variant**: The pronunciation-oriented rendering of a Turn's written answer, derived
  deterministically by the Answer_Composer through Computation_Layer number formatting with no model
  call, carrying the same numeric values as the written answer, and submitted to the
  Speech_Synthesizer.
- **Stage attempt ordinal**: The ordinal a trace event carries for one execution of a pipeline stage
  within a Turn, starting at 1 for the first execution of that stage name and increasing by 1 for each
  subsequent execution of that stage name.
- **Submission-artefact verification command**: The documented command that replays every step of the
  demo-flow document against the seed dataset and exits with a non-zero status when an observed outcome
  class, an observed figure, the recorded Dataset_Manifest version or the recorded code revision differs
  from the recorded value.
- **Synthetic-data provenance indicator**: The flag stating that the active dataset is the synthetic
  seed dataset, included in answer payloads and exported files so that seed figures are distinguishable
  from figures computed on a delivered dataset.
- **Trace event**: One ordered, timed record of a single pipeline step, carrying status, inputs,
  outputs, token usage and duration.
- **Trace_Service**: The component that emits trace events as a stream and persists them for later
  retrieval by turn id.
- **Transcription confidence score**: The score in the range 0.00 to 1.00 that the Speech_Transcriber
  returns for one transcript, used as the upper bound on the confidence score of a voice Turn.
- **Turn**: One user question and the system's complete response within a session.
- **Unhelpful refusal**: An abstention returned for a golden entry whose expected behaviour class is
  `answer`.
- **Verdict record**: The machine-readable record the Reviewer_Agent returns for one candidate query,
  holding exactly one verdict value, a written reason, a defect category where the verdict value is
  `repair` or `reject`, and at least one evidence citation drawn from the evidence bundle.
- **Voice_Service**: The component grouping Speech_Transcriber and Speech_Synthesizer plus language
  selection.


---

## Configuration Inventory

Every configurable value stated in the acceptance criteria, with its default and the requirement that
owns it. Where a criterion and this table disagree, the criterion is authoritative and this table must
be corrected.

**Question intake and conversation**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Reference date for relative dates (`reference_date`) | Latest transaction date in the active dataset | 1 |
| Minimum fuzzy match score (`min_fuzzy_match_score`) | 0.85 on a 0.00 to 1.00 scale | 1 |
| Disambiguation margin (`disambiguation_margin`) | 0.05 on a 0.00 to 1.00 scale | 1 |
| Default analysis period (`default_analysis_period`) | Full inclusive date coverage of the active dataset | 1 |
| Prior turns retained in conversation state (`conversation_state_turn_count`) | 10 turns | 2 |
| Session context timeout (`session_context_timeout`) | 30 minutes | 2 |

**Schema knowledge base and metric layer**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Distinct sample values per column (`schema_kb_sample_value_count`) | 20 values | 3 |
| Sub-schema prompt-token budget (`schema_link_prompt_token_budget`) | 1500 tokens | 3 |
| Minimum combined retrieval score (`min_combined_retrieval_score`) | 0.350 | 3 |
| Maximum join-path length (`max_join_path_length`) | 2 edges | 3 |
| Schema-linking table-recall target (`schema_link_table_recall_target`) | 0.95 | 3 |
| Template-match threshold (`template_match_threshold`) | 0.80 on the 0.00 to 1.00 routing-score scale | 4 |
| Template-tie-margin (`template_tie_margin`) | 0.05 on the 0.00 to 1.00 routing-score scale | 4 |

**Dataset ingestion**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Retained previously activated dataset versions (`retained_dataset_version_count`) | 2 retained versions | 5 |
| Rejected-row tolerance (`rejected_row_tolerance`) | 1% of source rows | 6 |
| Source file character encoding (`source_file_encoding`) | `utf-8` | 6 |
| API request timeout (`api_request_timeout`) | 30 seconds | 7 |
| API ingestion deadline (`api_ingestion_deadline`) | 1800 seconds | 7 |
| Maximum pages per entity (`max_pages_per_entity`) | 1000 pages | 7 |

**Model provider and budgets**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Model request timeout (`model_request_timeout`) | 30 seconds | 9 |
| Open-weight parameter ceiling (`model_parameter_ceiling`) | 8 billion parameters | 10 |
| LLM calls per question (`max_llm_calls_per_question`) | 6 calls | 10 |
| Tokens per question (`max_tokens_per_question`) | 12000 tokens | 10 |
| Wall-clock deadline per question (`question_wallclock_deadline`) | 30 seconds | 10 |
| Metric_Layer call limit (`metric_layer_call_limit`) | 3 calls | 10 |
| Hard ceilings on per-question budgets (`budget_hard_ceilings`) | 10 LLM calls, 32000 tokens, 60 seconds | 10 |
| Target SQL dialect (`target_sql_dialect`) | PostgreSQL | 11 |
| Exemplars retrieved per question (`exemplar_count`) | 4 exemplars | 11 |
| Candidate queries per question (`max_candidates_per_question`) | 3 candidates | 11 |
| Candidate generation retry limit (`candidate_generation_retry_limit`) | 2 retries per question | 11 |

**SQL validation and execution**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Default row limit for record listings (`default_row_limit`) | 1000 rows | 12 |
| Function allowlist (`sql_function_allowlist`) | Built-in aggregate, window, mathematical, string, date-time, casting and conditional functions, excluding file-reading, large-object, network, database-link, foreign-data-wrapper, sleep, session-state and server-state functions | 12 |
| Accepted syntax-tree node types (`accepted_node_type_allowlist`) | Node types required for SELECT statements, WITH clauses whose every body is a SELECT, joins, filters, grouping, ordering, set operations, row limits and allowlisted function calls | 12 |
| Maximum permitted declared row limit (`max_declared_row_limit`) | 100000 rows | 12 |
| Statement timeout (`statement_timeout`) | 10 seconds | 13 |
| Execution row cap (`execution_row_cap`) | 100000 rows | 13 |
| Maximum concurrent query limit (`max_concurrent_queries`) | 8 queries | 13 |
| Execution queue wait timeout (`execution_queue_wait_timeout`) | 5 seconds | 13 |
| Maximum executions per Turn (`max_executions_per_turn`) | 12 executions | 13 |

**Reviewer**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Repair iteration limit (`repair_iteration_limit`) | 2 iterations | 14 |
| Reviewer deadline per candidate (`reviewer_deadline`) | 8 seconds | 14 |
| Reviewer output retry limit (`reviewer_output_retry_limit`) | 1 retry | 14 |
| Dry-run limit per Turn (`dry_run_limit_per_turn`) | 5 dry-run executions | 14 |
| Dry-run deadline (`dry_run_deadline`) | 3 seconds | 14 |
| Reviewer phase deadline per Turn (`reviewer_phase_deadline`) | 20 seconds | 14 |

**Computation and answers**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Display precision (`display_precision`) | 2 decimal places | 15 |
| Answer-preview row limit (`answer_preview_row_limit`) | 100 rows | 15 |
| Maximum answer length (`max_answer_length`) | 120 words without the detailed answer option, 400 words with it | 16 |
| Maximum drill-down size (`max_drilldown_size`) | 500 identifiers | 16 |

**Groundedness and abstention**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Groundedness match tolerance (`groundedness_match_tolerance`) | 0.01 | 17 |
| Clarification round limit (`clarification_round_limit`) | 2 rounds | 18 |
| Unhelpful refusal ceiling (`unhelpful_refusal_ceiling`) | 5 percent of golden entries whose expected behaviour class is `answer` | 18 |

**Confidence**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Confidence signal weights (`confidence_signal_weights`) | Published in configuration, non-negative and summing to 1 within 0.001 | 19 |
| Confidence band boundaries (`confidence_band_boundaries`) | `low` 0 to below 0.50, `medium` 0.50 to below 0.80, `high` 0.80 to 1 | 19 |
| Acceptance threshold (`acceptance_threshold`) | 0.60 on the closed interval 0 to 1 | 19 |
| Calibration minimum band size (`calibration_min_band_size`) | 10 golden questions | 19 |
| Minimum accuracy per confidence band (`band_min_accuracy`) | 0.90 for `high`, 0.60 for `medium`, 0 for `low` | 19 |

**Anomaly**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Modified z-score threshold (`anomaly_z_threshold`) | 3.5 | 20 |
| Minimum history count per entity (`anomaly_min_history_count`) | 6 prior values | 20 |
| Maximum entities evaluated per Turn (`anomaly_max_entities_per_turn`) | 20 entities | 20 |
| Anomaly history window (`anomaly_history_window`) | 24 months preceding the value under evaluation | 20 |
| Maximum history rows per entity (`anomaly_max_history_rows`) | 500 rows | 20 |
| Zero-dispersion relative threshold (`zero_dispersion_relative_threshold`) | 0.20 | 20 |
| Zero-dispersion absolute floor (`zero_dispersion_absolute_floor`) | 1000 units of the dataset currency | 20 |
| Anomaly evaluation reserve (`anomaly_evaluation_reserve`) | 1 executed query | 20 |
| Anomaly evaluation time limit (`anomaly_evaluation_time_limit`) | 1500 milliseconds | 20 |

**Trace**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Trace replay retention period (`trace_replay_retention`) | 15 minutes after the terminal event | 21 |
| Trace keepalive interval (`trace_keepalive_interval`) | 10 seconds | 21 |
| Maximum trace event size (`max_trace_event_size`) | 32 kilobytes | 21 |
| Maximum inline sample rows (`max_inline_sample_rows`) | 20 rows | 21 |
| Trace persistence window (`trace_persistence_window`) | 1000 milliseconds after emission | 22 |
| Trace summary page size (`trace_summary_page_size`) | 50, maximum 200 | 22 |
| Trace retention period (`trace_retention_period`) | 30 days after turn creation time | 22 |
| Turn abandonment window (`turn_abandonment_window`) | 300 seconds after the last emitted event | 22 |
| Maximum persisted field length (`max_persisted_field_length`) | 16384 characters | 22 |

**Export**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Result-set snapshot retention period (`result_snapshot_retention`) | 30 days | 23 |
| Maximum export rows (`max_export_rows`) | 100000 rows | 23 |
| Export deadline (`export_deadline`) | 60 seconds | 23 |

**Failure store and improvement**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Returned rows captured per failure case (`failure_case_row_count`) | 100 rows | 24 |
| Maximum retained failure cases (`max_failure_cases`) | 10000 cases | 24 |
| Maximum proposals per improvement run (`max_proposals_per_run`) | 20 proposals | 25 |
| Improvement evaluation timeout (`improvement_evaluation_timeout`) | 1800 seconds | 25 |
| Artefact version retention count (`artefact_version_retention_count`) | 10 versions | 25 |

**Evaluation**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Evaluation repeat count (`evaluation_repeat_count`) | 3 executions | 26 |
| Evaluation run token budget (`evaluation_run_token_budget`) | 2000000 tokens | 26 |
| Evaluation run wall-clock limit (`evaluation_run_wallclock_limit`) | 3600 seconds | 26 |

**Metrics API**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Maximum hourly-bucket span (`max_hourly_span`) | 31 days | 27 |
| Drill-down page size (`drilldown_page_size`) | 50 turns, caller-selectable ceiling 500 turns | 27 |
| Default metrics range (`default_metrics_range`) | The 7 whole UTC days ending at the most recent UTC midnight | 27 |
| Maximum metrics range (`max_metrics_range`) | 366 days | 27 |

**Voice**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Accepted audio formats (`accepted_audio_formats`) | `wav`, `mp3`, `webm` | 28 |
| Maximum utterance duration (`max_utterance_duration`) | 60 seconds | 28 |
| Maximum audio upload size (`max_audio_upload_size`) | 10 megabytes | 28 |
| Maximum transcription attempt count (`max_transcription_attempts`) | 2 attempts | 28 |
| Transcription timeout (`transcription_timeout`) | 15 seconds per attempt | 28 |
| Default transcription confidence score (`default_transcription_confidence`) | 0.75 | 28 |
| Voice confirmation threshold (`voice_confirmation_threshold`) | 0.70 | 28 |
| Audio retention period (`audio_retention_period`) | 0 seconds | 28 |
| Maximum synthesis character count (`max_synthesis_characters`) | 2000 characters | 29 |
| Synthesis timeout (`synthesis_timeout`) | 10 seconds | 29 |
| Maximum synthesis attempt count (`max_synthesis_attempts`) | 2 attempts per segment | 29 |
| Per-Turn synthesis time budget (`turn_synthesis_time_budget`) | 30 seconds | 29 |
| Audio cache retention period (`audio_cache_retention`) | 3600 seconds | 29 |

**Buddy**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Buddy suggestion latency budget (`buddy_suggestion_latency_budget`) | 2000 milliseconds at the Chat_API boundary | 30 |

**Runtime**

| Setting | Default | Owning requirement |
|---------|---------|--------------------|
| Session page size (`session_page_size`) | 20 records, maximum accepted 100 records | 32 |
| Cold-start budget (`cold_start_budget`) | 180 seconds | 32 |
| Voice reachability cache period (`voice_reachability_cache_period`) | 300 seconds | 32 |
| Maximum request body size (`max_request_body_size`) | 12 megabytes | 32 |

---

## Requirements

### Requirement 1: Natural-language question intake and intent parsing

*Capability A1; PDF must-have "natural language query handling".*

**User Story:** As a business user, I want to ask a finance question in plain language, so that I get
an answer without opening a dashboard or learning report terminology.

#### Acceptance Criteria

1. WHEN a client posts a question to a chat session, THE Chat_API SHALL create a Turn, assign a
   unique turn identifier, and return the identifier in the initial response.
2. WHEN a Turn begins, THE Query_Planner SHALL classify the question into exactly one supported
   intent family from the configured intent list (vendor spend, category spend, account spend,
   transaction lookup, payout listing, reconciliation status, period comparison, metric definition,
   analytics question, unsupported) and record the classification as a trace event.
3. WHEN a question contains one or more date expressions, THE Query_Planner SHALL resolve each date
   expression to an absolute inclusive start date and end date, and SHALL record each original date
   expression together with the corresponding resolved range as a trace event.
4. WHERE a question contains a relative date expression, THE Query_Planner SHALL resolve the
   expression against the configured reference date, whose default value is the latest transaction
   date present in the active dataset.
5. WHEN a question mentions a vendor, account, category or reconciliation status, THE Query_Planner
   SHALL resolve each mention to a value present in the active dataset by applying exact matching,
   case-insensitive matching and fuzzy matching in that order, and SHALL admit a fuzzy match as a
   candidate value only at or above the configured minimum fuzzy match score, whose default value is
   0.85 on a scale of 0.00 to 1.00.
6. IF two or more candidate dataset values match a mention with a score difference below the
   configured disambiguation margin, whose default value is 0.05 on a scale of 0.00 to 1.00, THEN THE
   Chat_API SHALL return exactly one clarifying question for the Turn, listing at most 5 candidate
   values ordered by descending match score.
7. THE Chat_API SHALL accept questions containing 1 to 1000 characters after leading and trailing
   whitespace removal.
8. IF the classified intent family is unsupported, THEN THE Chat_API SHALL return an abstention that
   names the supported question families.
9. IF a posted question contains 0 characters after leading and trailing whitespace removal or
   contains more than 1000 characters, THEN THE Chat_API SHALL reject the request with an error
   indicating the permitted question length range of 1 to 1000 characters and SHALL leave the
   conversation state of the session unchanged.
10. WHEN a question contains no date expression, THE Query_Planner SHALL apply the configured default
    analysis period, whose default value is the full inclusive date coverage of the active dataset,
    and SHALL record the applied default analysis period as a trace event.
11. IF a date expression resolves to more than one absolute range under the configured date-format
    policy, THEN THE Query_Planner SHALL name that date expression as an ambiguity and route the Turn
    to the clarification path.
12. IF a resolved date range does not intersect the inclusive date coverage of the active dataset,
    THEN THE Abstention_Controller SHALL produce an abstention that states the earliest and latest
    transaction dates present in the active dataset and attaches the machine-readable reason code
    `period_outside_coverage`.
13. IF no candidate dataset value for a mention reaches the configured minimum fuzzy match score,
    THEN THE Abstention_Controller SHALL produce an abstention that names the unresolved mention,
    lists at most 5 dataset values with the highest match scores for the unresolved mention, and
    attaches the machine-readable reason code `entity_not_found`.

### Requirement 2: Multi-turn conversation with context carry-over

*Capability A1; PDF must-have "multi-turn conversation".*

**User Story:** As a business user, I want to ask "and how does that compare to the month before?",
so that I can drill into a topic without repeating myself.

#### Acceptance Criteria

1. WHEN a Turn belongs to a session whose conversation state is not empty, THE Context_Resolver SHALL
   produce a self-contained resolved question in which pronouns, elliptical phrases and implicit
   filters are replaced by explicit entities, filters and date ranges taken from the conversation
   state.
2. THE Context_Resolver SHALL persist conversation state for each session containing the resolved
   entities, the resolved date range, the executed SQL and the result-set column names of the most
   recent successful Turn, and, WHERE the session holds a pending clarification state, the original
   question text, the named ambiguity and the clarification round count.
3. WHEN a follow-up question requests a comparison with another period, THE Context_Resolver SHALL
   retain the previous filters and substitute only the date range.
4. WHEN a resolved question is produced, THE Chat_API SHALL return the resolved question text in the
   turn response so the user can confirm what was understood.
5. IF a referring expression resolves to no entity in the conversation state, THEN THE Chat_API SHALL
   return a clarifying question that names the unresolved expression.
6. WHERE the conversation state of a session is empty, THE Context_Resolver SHALL treat the question
   as already self-contained.
7. WHEN an identical follow-up question is submitted twice against unchanged conversation state, THE
   Context_Resolver SHALL produce identical resolved question text on both occasions.
8. THE Context_Resolver SHALL include in the conversation state at most the configured number of prior
   turns, with a default of 10 turns, retaining the most recent turns and discarding the oldest turns
   first.
9. WHEN a follow-up question states an explicit value for a filter dimension that is also present in
   the conversation state, THE Context_Resolver SHALL override the conversation-state value for the
   same filter dimension with the value stated in the follow-up question.
10. IF a Turn ends in an abstention, a clarifying question or an execution error, THEN THE
    Context_Resolver SHALL leave the conversation state of the session unchanged, and SHALL persist
    the pending clarification state separately from the conversation state.
11. IF a follow-up question requests a comparison with another period and the conversation state
    contains no resolved date range, THEN THE Chat_API SHALL return a clarifying question that names
    the date range required for the comparison.
12. WHEN the elapsed time since the most recent Turn of a session exceeds the configured session
    context timeout, whose default value is 30 minutes, THE Context_Resolver SHALL discard the
    conversation state of the session before resolving the next question of the session.

### Requirement 3: Schema Knowledge Base and schema linking

*Capability A1.*

**User Story:** As the SQL_Generator, I want the minimal relevant sub-schema with business
descriptions and real value samples, so that I can write correct SQL within a small token budget.

#### Acceptance Criteria

1. WHEN ingestion completes, THE Ingestion_Service SHALL create one Schema_KB entry for every table
   and one Schema_KB entry for every column of the active dataset.
2. THE Schema_KB SHALL store for each column entry the table name, column name, declared type,
   nullability, key participation, business description, unit or currency where the column holds a
   quantity, and up to the configured number of distinct sample values with a default of 20 values.
3. WHERE the active dataset supplies a data dictionary, THE Ingestion_Service SHALL use the
   dictionary text as the business description of each matched column and record the description
   source as `data_dictionary`.
4. WHERE a column has no data-dictionary entry, THE Ingestion_Service SHALL generate a business
   description from the column name, declared type and sampled values, and record the description
   source as `generated`.
5. THE Schema_KB SHALL store, for every table, a semi-structured M-Schema-style rendering suitable
   for direct inclusion in a prompt.
6. THE Schema_KB SHALL store relationship edges between tables derived from declared foreign keys and
   from joins declared in the Dataset_Manifest.
7. WHEN a resolved question is available, THE Schema_Linker SHALL retrieve the sub-schema required to
   answer that resolved question by combining keyword retrieval and vector similarity retrieval over
   the Schema_KB into one combined retrieval score per Schema_KB entry, normalised to the range 0.000
   to 1.000.
8. THE Schema_Linker SHALL emit a sub-schema of at most the configured prompt-token budget, with a
   default of 1500 tokens, and SHALL fill that budget in descending combined retrieval score order,
   admitting every selected table entry and every column entry participating in a selected
   relationship edge ahead of any other column entry.
9. THE Schema_Linker SHALL record as trace events the retrieved chunks, the combined retrieval score
   of each retrieved chunk, the applied minimum combined retrieval score, the Schema_KB version
   identifier used for retrieval, the selected sub-schema, and the count and identifiers of Schema_KB
   entries excluded by the prompt-token budget.
10. WHEN the active dataset changes, THE Ingestion_Service SHALL rebuild the Schema_KB in full,
    increment the Schema_KB version identifier, regenerate the vector embedding of every table entry
    and every column entry under the incremented Schema_KB version identifier, retain the previously
    completed Schema_KB version until the incremented Schema_KB version is complete, and mark the
    incremented Schema_KB version available for retrieval only after every entry and every embedding
    of the incremented version is written.
11. IF no Schema_KB entry attains the configured minimum combined retrieval score, whose default
    value is 0.350, for a resolved question, THEN THE Schema_Linker SHALL emit an empty sub-schema and
    SHALL report a schema-linking failure to the Abstention_Controller.
12. WHEN the Schema_Linker selects two or more table entries for one sub-schema, THE Schema_Linker
    SHALL include in that sub-schema every Schema_KB relationship edge whose two endpoints are both
    selected table entries, every column entry participating in those relationship edges, and, where
    two selected table entries are connected only through intermediate tables, the intermediate table
    entries and relationship edges of the shortest connecting path up to the configured maximum
    join-path length, whose default value is 2 edges.
13. WHILE a Schema_KB rebuild is in progress, THE Schema_Linker SHALL retrieve exclusively from
    Schema_KB entries and embeddings carrying the most recently completed Schema_KB version
    identifier.
14. WHEN the Evaluation_Harness executes the golden question set, THE Schema_Linker SHALL emit a
    sub-schema containing every table referenced by the expected SQL for at least the configured
    schema-linking table-recall target of the golden questions, whose default value is 0.95.

### Requirement 4: Metric layer of pre-validated query templates

*Capability A1; PDF must-have "accurate computation".*

**User Story:** As a finance user, I want the common questions answered by definitions the team has
already agreed, so that the same question returns the same trustworthy number every time.

#### Acceptance Criteria

1. THE Metric_Layer SHALL store each metric as a named definition containing a business description,
   declared parameters with types, a parameterised SQL template, and the expected result columns.
2. WHEN a resolved question scores at or above the configured template-match threshold, whose default
   value is 0.80 on a 0.00 to 1.00 routing-score scale, against at least one active metric definition,
   THE Query_Planner SHALL select the Metric_Layer path with the highest-scoring active metric
   definition and SHALL record the selected metric name, the selected routing score, and the name and
   routing score of every other active metric definition at or above the threshold as a trace event.
3. WHEN the Metric_Layer path is selected, THE Query_Planner SHALL bind every declared template
   parameter to a value derived from the resolved question, using parameterised binding rather than
   string concatenation.
4. IF a required template parameter has no bound value, THEN THE Query_Planner SHALL return control to
   the clarification path and name the missing parameter.
5. WHEN no metric definition reaches the template-match threshold, THE Query_Planner SHALL select the
   generated-SQL path and record the reason as a trace event.
6. THE Metric_Layer SHALL be defined in the Dataset_Manifest so that a new dataset can declare its
   own metrics without code changes.
7. WHEN a metric definition is added or changed in the Dataset_Manifest, THE Evaluation_Harness SHALL
   execute every golden question tagged to that metric definition, with a minimum of 3 tagged golden
   questions per metric definition, and SHALL report per-question execution accuracy before that metric
   definition becomes active.
8. THE Metric_Layer SHALL cover at minimum vendor spend over a period, spend by category over a
   period, spend by account over a period, unreconciled transaction listing, reconciliation summary by
   status, vendor payout listing, and period-over-period comparison for any of the preceding metrics.
9. IF two or more active metric definitions score at or above the configured template-match threshold
   and the difference between the highest and the second-highest routing score is at or below the
   configured template-tie-margin, whose default value is 0.05 on the 0.00 to 1.00 routing-score scale,
   THEN THE Query_Planner SHALL select the clarification path rather than the Metric_Layer path, SHALL
   present the tied metric names with the respective business descriptions, and SHALL record the tied
   metric names with the respective routing scores as a trace event.
10. IF a value bound to a declared template parameter does not conform to that parameter's declared
    type or declared allowed-value bounds in the metric definition, THEN THE Query_Planner SHALL select
    the clarification path before any statement is submitted to the Query_Executor, SHALL name the
    non-conforming parameter together with the declared type and bounds, and SHALL record the
    non-conformance as a trace event.
11. IF the Evaluation_Harness reports execution accuracy below 1.00 on any golden question tagged to an
    added or changed metric definition, THEN THE Metric_Layer SHALL hold that metric definition
    inactive, SHALL retain the previously active definition of the same metric name, and SHALL record
    the identifiers of the failing golden questions.
12. WHEN the Ingestion_Service completes derivation of the Schema_KB for a dataset version, IF a metric
    SQL template references a table or a column absent from that Schema_KB, THEN THE Metric_Layer SHALL
    hold that metric definition inactive and SHALL record the absent table or column name as a trace
    event.
13. WHEN a bound Metric_Layer statement is produced, THE Query_Planner SHALL submit that statement to
    the SQL_Validator as a candidate query before execution, so that every guardrail of Requirement 12
    applies to the Metric_Layer path.
14. IF an active bound Metric_Layer statement fails at execution with a statement timeout error or a
    row-cap error, THEN THE Query_Planner SHALL end the Turn through the Abstention_Controller with the
    reason code `metric_execution_failed` naming the failing metric definition, rather than selecting
    the generated-SQL path.

### Requirement 5: Swappable dataset driven by a manifest

*Capability A2.*

**User Story:** As a developer, I want to point the system at the organisers' dataset by editing
configuration only, so that the real dataset can be adopted within minutes of delivery.

#### Acceptance Criteria

1. THE Dataset_Manifest SHALL declare the dataset identifier, version, source mode, entity list,
   per-entity source location, per-entity column mapping, per-entity primary key, per-entity
   identifier field, per-column date format, the character encoding of each source file, the currency
   symbols and thousands separator used by monetary columns, the pagination style with its final-page
   signal, the data-dictionary location, metric definitions, and the reference date policy.
2. THE Ingestion_Service SHALL support the source mode values `local_files` and `http_api`.
3. WHEN a new Dataset_Manifest is supplied and ingestion is triggered, THE Finance_Assistant_Backend
   SHALL serve questions against the new dataset without any change to application source code.
4. WHEN the Dataset_Manifest declares a column mapping, THE Ingestion_Service SHALL map source column
   names to the canonical column names used by the Metric_Layer.
5. IF the ingested dataset omits an entity or column that the Dataset_Manifest declares as required, or
   omits a table or column referenced by a metric definition declared in the Dataset_Manifest, THEN THE
   Ingestion_Service SHALL fail the ingestion run, keep the previously active dataset version active,
   and report every missing item in one validation report.
6. THE Ingestion_Service SHALL record each ingestion run with its manifest version, row counts per
   entity, start time, end time and outcome.
7. WHEN ingestion succeeds, THE Ingestion_Service SHALL activate the new dataset version atomically so
   that every Turn in progress at activation reads one dataset version for the whole Turn, either the
   previously active dataset version or the new dataset version.
8. THE Finance_Assistant_Backend SHALL expose the active dataset identifier, version, row counts,
   ingestion timestamp, active Schema_KB version, and the identifier and version of each retained
   previous dataset version through a read endpoint.
9. IF the Dataset_Manifest omits a declaration that criterion 1 requires, or declares a source mode
   value other than `local_files` or `http_api`, THEN THE Ingestion_Service SHALL reject the ingestion
   run before loading any entity, keep the previously active dataset version active, and report every
   manifest violation in one validation report.
10. WHILE the Schema_KB rebuild for a newly ingested dataset version is incomplete, THE
    Ingestion_Service SHALL keep the previously active dataset version active.
11. THE Ingestion_Service SHALL retain the configured number of previously activated dataset versions
    together with the Schema_KB version bound to each retained dataset version, whose default value is
    2 retained versions.
12. WHEN a revert of the active dataset version is requested, THE Ingestion_Service SHALL activate the
    most recently retained previous dataset version, together with the Schema_KB version bound to that
    retained dataset version, atomically and within 30 seconds of the request.
13. WHEN an ingestion run is triggered while another ingestion run holds status in progress, THE
    Ingestion_Service SHALL reject the triggered run and report that an ingestion run is already in
    progress.
14. WHEN a dataset version is activated, THE Ingestion_Service SHALL mark every Exemplar_Bank entry
    whose SQL references a table or column absent from the Schema_KB of that dataset version as
    inapplicable to that dataset version.

### Requirement 6: Local file ingestion path

*Capability A2.*

**User Story:** As a developer running the demo offline, I want CSV, Excel and SQL dataset files
loaded into local PostgreSQL, so that the assistant works with no external dependency.

#### Acceptance Criteria

1. WHEN the source mode is `local_files`, THE Local_File_Connector SHALL load every declared entity
   from the declared file paths into PostgreSQL tables.
2. THE Local_File_Connector SHALL support the file formats CSV, XLSX and SQL dump.
3. WHEN loading a column declared as a date or timestamp, THE Local_File_Connector SHALL parse the
   value using only the single format declared for that column in the Dataset_Manifest, SHALL treat a
   value that does not match that declared format as a type coercion failure, and SHALL store the
   parsed value in a date or timestamp column without applying a time-zone conversion.
4. WHEN loading a column declared as a monetary amount, THE Local_File_Connector SHALL strip
   surrounding whitespace, the currency symbols declared in the Dataset_Manifest and the thousands
   separator declared in the Dataset_Manifest from the source value, SHALL read a value enclosed in
   parentheses as a negative amount, SHALL round a value carrying more decimal digits than the declared
   scale half away from zero to the declared scale and record that row number in the ingestion report,
   and SHALL store the resulting value in a fixed-precision numeric column with the scale declared in
   the Dataset_Manifest.
5. IF a source row fails type coercion, or holds an empty or whitespace-only value in a column that the
   Dataset_Manifest declares as required, THEN THE Local_File_Connector SHALL reject the row, record
   the row number and reason in the ingestion report, and continue loading the remaining rows.
6. WHEN the rejected-row count exceeds the configured tolerance, whose default is 1% of source rows,
   THE Local_File_Connector SHALL fail the ingestion run.
7. THE Local_File_Connector SHALL create indexes on every column declared in the Dataset_Manifest as a
   filter column or join key.
8. THE Local_File_Connector SHALL complete ingestion of a dataset of up to 500000 rows within 10
   minutes on the demonstration machine.
9. WHEN reading a CSV file or a SQL dump file, THE Local_File_Connector SHALL decode the file bytes
   using the character encoding declared in the Dataset_Manifest, whose default value is `utf-8`, SHALL
   discard a leading byte-order mark before matching header fields, and SHALL treat a byte sequence that
   the declared encoding cannot decode as a type coercion failure for the row containing that byte
   sequence.
10. WHEN matching a source file header row to the column mapping declared in the Dataset_Manifest, THE
    Local_File_Connector SHALL compare header field names after removing surrounding whitespace and
    ignoring letter case, SHALL exclude from the load every header field the column mapping does not
    declare, and SHALL record each excluded header field name in the ingestion report.
11. IF two or more source rows of an entity hold identical values for the primary key declared for that
    entity in the Dataset_Manifest, THEN THE Local_File_Connector SHALL load the first of those rows,
    reject every subsequent row holding that key value, record each rejected row number and the
    duplicated key value in the ingestion report, and count each rejected row toward the configured
    rejected-row tolerance.
12. WHEN a source cell is empty or holds only whitespace characters and the Dataset_Manifest does not
    declare that column as required, THE Local_File_Connector SHALL store a NULL value in that column.
13. WHERE a source file is a SQL dump, THE Local_File_Connector SHALL execute only INSERT statements
    targeting entities declared in the Dataset_Manifest, SHALL fail the ingestion run on encountering a
    data-definition statement, a data-modification statement other than INSERT, a privilege statement
    or a session-control statement, and SHALL treat the ordinal position of an INSERT statement within
    the dump as the row number in the ingestion report.

### Requirement 7: API-backed ingestion path

*Capability A2.*

**User Story:** As a developer, I want the same dataset consumed from the organisers' HTTP API, so
that either delivery mode works on the day.

#### Acceptance Criteria

1. WHEN the source mode is `http_api`, THE API_Connector SHALL fetch every declared entity from the
   declared endpoint and load each response field named in the Dataset_Manifest column mapping for that
   entity into the mapped column of the same PostgreSQL tables the Local_File_Connector populates,
   excluding response fields absent from that mapping.
2. THE API_Connector SHALL read the base URL, per-entity path, authentication header name and
   authentication value from configuration.
3. WHERE an endpoint returns paginated results, THE API_Connector SHALL follow pagination using the
   pagination style declared in the Dataset_Manifest until the declared final-page signal is observed or
   until the configured maximum pages per entity have been retrieved for that entity, whichever occurs
   first.
4. IF an endpoint responds with an HTTP status of 429 or a status in the 5xx range, or does not return a
   complete response within the configured API request timeout, whose default value is 30 seconds, or
   closes the connection before the response completes, THEN THE API_Connector SHALL retry the request
   up to 3 times, waiting 1 second before the first retry and doubling the wait before each subsequent
   retry.
5. IF any declared entity does not load completely during an `http_api` ingestion run, THEN THE
   API_Connector SHALL fail the ingestion run, discard every record fetched during that run, retain the
   previously active dataset version as the active dataset version, and report the failing entity, the
   failure condition and, where the failure originated from an HTTP response, the observed HTTP status.
6. WHEN ingestion from the API succeeds, THE API_Connector SHALL produce the same canonical tables,
   Schema_KB entries and validation report that the Local_File_Connector produces for equivalent data.
7. THE API_Connector SHALL record the source endpoint and fetched record count per entity in the
   ingestion report.
8. IF the elapsed wall-clock time of an `http_api` ingestion run exceeds the configured API ingestion
   deadline, whose default value is 1800 seconds, THEN THE API_Connector SHALL terminate the ingestion
   run as a failed run and report the entity in progress, the number of entities already loaded and the
   elapsed seconds.
9. IF pagination for a declared entity reaches the configured maximum pages per entity, whose default
   value is 1000 pages, without the declared final-page signal, or returns a pagination position value
   already retrieved during the same entity fetch, THEN THE API_Connector SHALL fail the ingestion run
   and report the entity, the retrieved page count and the repeated pagination position value.
10. IF a fetched record omits a field declared in the Dataset_Manifest column mapping for that entity,
    THEN THE API_Connector SHALL fail the ingestion run and report the entity, the missing field name
    and the count of records missing that field.
11. WHEN a fetched record carries an identifier value already loaded for that entity during the same
    ingestion run, THE API_Connector SHALL load exactly one row for that identifier value and record the
    discarded duplicate count per entity in the ingestion report.
12. WHEN the API_Connector writes an ingestion report or a failure report, THE API_Connector SHALL
    replace every configured authentication value occurring in that report with a fixed mask token.

### Requirement 8: Seed dataset and dataset contract

*Capability A2.*

**User Story:** As a developer starting before the real dataset arrives, I want a realistic synthetic
dataset and a written contract, so that development and demos proceed today and the real dataset drops
in cleanly tomorrow.

#### Acceptance Criteria

1. THE Finance_Assistant_Backend SHALL ship a synthetic seed dataset covering transactions, vendor
   payouts, reconciliation status, chart of accounts, vendor list and a data dictionary.
2. THE Seed_Data_Generator SHALL produce at least 5000 transactions, at least 200 vendor payouts, at
   least 40 vendors, at least 12 consecutive calendar months of history, at least 500 transactions
   whose reconciliation status is unreconciled, at least 20 transactions in each remaining allowed
   reconciliation status value declared by the dataset contract, and at least 3 payouts that the
   documented anomaly rule flags.
3. WHEN the Seed_Data_Generator runs with a given random seed, THE Seed_Data_Generator SHALL produce
   byte-identical output for that seed.
4. THE Finance_Assistant_Backend SHALL publish a dataset contract document declaring, per entity, the
   required columns, types, units, allowed reconciliation status values, the referential relationships
   the Metric_Layer depends on, the coverage window each dataset declares as an inclusive first date
   and an inclusive last date, and for every declared rule a severity of either blocking or tolerable,
   where a null value in a non-key column, a duplicate vendor name spelling, an amount of exactly 0 and
   an amount below 0 each carry severity tolerable.
5. WHEN a candidate dataset is supplied, THE Ingestion_Service SHALL validate the candidate dataset
   against every rule declared in the dataset contract and report every detected deviation together
   with the deviating entity, the violated rule and the declared severity of that rule, before loading
   any row.
6. THE golden question set SHALL contain, for the synthetic seed dataset, the expected answer for every
   question whose expected outcome is an answer, and the expected Abstention_Controller reason code for
   every question whose expected outcome is an abstention or a clarifying question, including at least
   5 questions whose expected outcome is an abstention of which at least 2 request a date range falling
   entirely outside the coverage window declared for the synthetic seed dataset, and at least 3
   questions whose expected outcome is a clarifying question of which at least 1 names a vendor
   spelling that the synthetic seed dataset resolves to 2 or more vendor records.
7. THE Seed_Data_Generator SHALL produce, within the synthetic seed dataset, at least 50 transactions
   carrying a null value in at least one non-key column, at least 5 vendors that appear under 2 or more
   distinct name spellings, at least 20 transactions with an amount of exactly 0, and at least 20
   transactions with an amount below 0.
8. WHEN the Ingestion_Service validates the synthetic seed dataset against the dataset contract, THE
   Ingestion_Service SHALL report 0 deviations of severity blocking.
9. IF the Ingestion_Service detects 1 or more deviations of severity blocking in a candidate dataset,
   THEN THE Ingestion_Service SHALL abort the load, leave the previously active dataset and the
   Schema_KB unchanged, and return an error indicating the count of blocking deviations and the
   violated rule of each.
10. WHERE every detected deviation in a candidate dataset carries severity tolerable, THE
    Ingestion_Service SHALL proceed with the load and record every tolerable deviation in the
    ingestion report.
11. WHILE the active dataset is the synthetic seed dataset, THE Finance_Assistant_Backend SHALL include
    a synthetic-data provenance indicator in every answer payload returned by the Chat_API and in every
    file produced by the Export_Service.

### Requirement 9: Swappable model provider layer

*Capability A3.*

**User Story:** As a developer, I want to switch model provider and model by configuration, so that
whichever credits the organisers hand out can be used without touching code.

#### Acceptance Criteria

1. THE Model_Router SHALL support the provider values `openrouter`, `bedrock`, `azure_openai`,
   `openai_compatible`, `ollama` and `vllm`.
2. THE Model_Router SHALL resolve each logical role — router, sql_generator, reviewer, composer,
   buddy, embedder — to a provider, a model identifier, a temperature and a maximum output token
   count, each read from configuration.
3. WHEN a role has no explicit configuration entry, THE Model_Router SHALL use the configured default
   provider and default model for that role.
4. WHEN a provider request exceeds the configured model request timeout, whose default value is 30
   seconds, or fails with a transport error, an authentication error or a rate-limit status, THE
   Model_Router SHALL retry the request once against the same provider and model, and SHALL route the
   request to the configured fallback provider for that role after a failed retry, making at most 2
   attempts per provider and at most 6 attempts in total for one model call.
5. IF every configured provider for a role fails, THEN THE Model_Router SHALL return a typed
   provider-unavailable error, and THE Chat_API SHALL return an abstention that states the assistant
   cannot answer at present.
6. THE Model_Router SHALL record one model call record for every attempt, including each retry attempt
   and each fallback attempt, carrying the role, provider, model identifier, input token count, output
   token count, duration in milliseconds and outcome, and SHALL record a token count as unavailable
   for a provider that returns no token usage values.
7. WHEN the provider configuration changes and the service restarts, THE Chat_API SHALL keep every
   request and response schema unchanged.
8. THE Model_Router SHALL expose the resolved role-to-model mapping through a read endpoint so the
   active configuration is visible without reading environment variables.
9. WHERE a provider exposes an embedding model, THE Model_Router SHALL use the configured embedding
   model for Schema_KB and Exemplar_Bank retrieval, and SHALL support a locally hosted embedding model
   so that retrieval works without network access.
10. IF a model response for the router, sql_generator or reviewer role does not conform to the
    structured output schema requested for that role, THEN THE Model_Router SHALL retry that request
    once against the same provider and model, and SHALL treat a second non-conforming response as a
    failure of that provider for that role and route the request to the configured fallback provider
    for that role.
11. IF a provider referenced by a role configuration, by the default provider configuration or by a
    fallback configuration is missing any credential or endpoint value that the provider requires,
    THEN THE Model_Router SHALL mark that provider unavailable at startup, SHALL exclude that provider
    from role resolution, and SHALL report each missing credential name and endpoint name through the
    read endpoint that exposes the resolved role-to-model mapping.
12. IF the vector dimension produced by the configured embedding model differs from the vector
    dimension recorded for the stored Schema_KB and Exemplar_Bank embeddings, THEN THE Model_Router
    SHALL return a typed embedding-dimension-mismatch error naming both dimensions, THE
    Finance_Assistant_Backend SHALL leave every stored embedding unchanged, and THE Chat_API SHALL
    return an abstention carrying the reason code `embedding_dimension_mismatch`.
13. IF a provider reports that the model identifier configured for a role is not available at that
    provider, THEN THE Model_Router SHALL route that request to the configured fallback provider for
    that role without retrying against the reporting provider, and SHALL record the outcome as a
    configured-model-unavailable failure.
14. WHERE every logical role resolves to the provider `ollama` or the provider `vllm`, THE
    Finance_Assistant_Backend SHALL complete a Turn end to end with no outbound network request beyond
    the configured local provider endpoint.
15. WHEN the configured embedding model changes, THE Ingestion_Service SHALL regenerate every
    Schema_KB entry embedding and every Exemplar_Bank entry embedding under a new Schema_KB version
    identifier before that Schema_KB version becomes available for retrieval.

### Requirement 10: Lightweight model constraint, budgets and efficiency measurement

*Capability A3; PDF must-have "lightweight model constraint" (scored, 20%).*

**User Story:** As a hackathon participant, I want the model-efficiency constraint enforced and
evidenced, so that the 20% efficiency score is defensible with measurements rather than claims.

#### Acceptance Criteria

1. THE Finance_Assistant_Backend SHALL declare the pinned lightweight model tier in configuration as
   either an open-weight model of at most the configured parameter ceiling, whose default is 8 billion
   parameters, or a hosted model explicitly published by its provider as a small, mini or flash tier.
2. THE Budget_Guard SHALL enforce a maximum number of LLM calls per user question, with a default of 6
   calls and a configured hard ceiling of 10 calls.
3. THE Budget_Guard SHALL enforce a maximum total token count per user question, counting input and
   output tokens across every role, with a default of 12000 tokens.
4. THE Budget_Guard SHALL enforce a wall-clock deadline per user question, with a default of 30
   seconds.
5. IF a question reaches any configured budget limit before an answer is verified, THEN THE Chat_API
   SHALL return the most recent candidate answer approved by the Groundedness_Checker when such a
   candidate exists and an abstention carrying the reason code `budget_exhausted` when no such
   candidate exists, and THE Trace_Service SHALL record a budget-exhausted event naming the limit
   reached and the configured value of that limit.
6. WHEN a Turn completes, THE Metrics_API SHALL record for that Turn the LLM call count, input tokens,
   output tokens, estimated cost, per-stage durations, end-to-end duration, the resolution path as
   either Metric_Layer or generated SQL, and the model identifier resolved for every role invoked
   during that Turn.
7. THE Finance_Assistant_Backend SHALL answer text questions with a median end-to-end duration of at
   most 6 seconds and a 95th-percentile end-to-end duration of at most 15 seconds, measured from
   receipt of the question by the Chat_API to release of the composed answer, over at least 50 text
   Turns drawn from the golden question set and executed against the seed dataset on the demonstration
   machine after ingestion has completed.
8. THE Finance_Assistant_Backend SHALL keep every budget value, the parameter ceiling and the tier
   definition re-configurable at runtime startup so the pinned constraint can be changed when the
   organisers publish the missing constraint section.
9. THE Metrics_API SHALL expose tokens per resolved question, LLM calls per resolved question and cost
   per resolved question as reportable figures, where a resolved question is a completed Turn that
   returned an answer rather than an abstention, and SHALL report cost per resolved question as
   unavailable for every Turn that invoked a model with no configured price per token.
10. WHILE a Turn is resolved through a Metric_Layer template rather than through generated SQL, THE
    Budget_Guard SHALL enforce for that Turn a maximum LLM call count equal to the configured
    Metric_Layer call limit, whose default value is 3 calls.
11. THE Budget_Guard SHALL apply the per-question LLM call limit, the per-question token limit and the
    per-question wall-clock deadline to Turns only, and THE Metrics_API SHALL report the LLM calls,
    tokens and estimated cost consumed by the Improvement_Pipeline, the Evaluation_Harness and the
    Ingestion_Service as figures separate from the per-Turn figures.
12. IF a model provider response omits the input token count or the output token count for a call, THEN
    THE Budget_Guard SHALL charge that call against the per-question token limit using a deterministic
    estimate derived from the submitted prompt text and the returned completion text, and THE
    Trace_Service SHALL record the token counts of that call as estimated.
13. IF a configured role resolves to an open-weight model whose published parameter count exceeds the
    configured parameter ceiling, or to a hosted model that the provider does not publish as a small,
    mini or flash tier, THEN THE Model_Router SHALL reject the configuration at startup and THE
    Finance_Assistant_Backend SHALL fail to start with an error naming the role, the resolved model
    identifier and the ceiling or tier condition violated.
14. IF a configured per-question budget value exceeds its configured hard ceiling, whose default values
    are 10 LLM calls, 32000 tokens and 60 seconds, THEN THE Finance_Assistant_Backend SHALL fail
    startup with an error naming the budget value, the configured value and the ceiling.
15. THE Budget_Guard SHALL count Speech_Transcriber provider durations and Speech_Synthesizer provider
    durations separately from the per-question wall-clock deadline, and THE Finance_Assistant_Backend
    SHALL answer voice questions with a 95th-percentile end-to-end duration of at most 25 seconds
    measured from receipt of the audio utterance to release of the composed answer.

### Requirement 11: SQL generation with retrieved exemplars and decomposition

*Capability A1, A4.*

**User Story:** As a business user asking an ad-hoc question, I want correct SQL generated for it, so
that questions outside the pre-built metrics still get grounded answers.

#### Acceptance Criteria

1. WHEN the generated-SQL path is selected, THE SQL_Generator SHALL produce SQL from the resolved
   question, the linked sub-schema, the retrieved exemplars and the target SQL dialect resolved from
   configuration, whose default value is PostgreSQL.
2. THE SQL_Generator SHALL retrieve at most the configured number of exemplars from the
   Exemplar_Bank, with a default of 4 exemplars, selecting for both question similarity and query-shape
   diversity, and SHALL exclude from the retrieved set every exemplar whose SQL references a table or
   column that is absent from the active Schema_KB.
3. WHERE the resolved question contains more than one measurable sub-question, THE Query_Planner SHALL
   decompose it into ordered sub-questions and record the decomposition as a trace event.
4. THE SQL_Generator SHALL produce at most the configured number of candidate queries per question,
   with a default of 3 candidates, and SHALL emit at most one candidate per distinct normalised query
   form, where two candidates share a normalised query form when their SQL text is identical after
   collapsing whitespace, lower-casing keywords and renaming table aliases in order of first
   appearance.
5. WHEN a prior Turn in the session executed SQL successfully and the current question is a follow-up,
   THE SQL_Generator SHALL supply the prior SQL as an editable starting point and record the edit as a
   trace event.
6. THE SQL_Generator SHALL emit each candidate query with the tables and columns it references so that
   conformance checking requires no re-parsing by the caller.
7. WHEN candidate queries are generated, THE Trace_Service SHALL record every candidate, including
   candidates later rejected, every candidate excluded by the SQL_Generator before emission, and every
   model response discarded for not yielding exactly one parsable SQL statement.
8. IF a model response on the generated-SQL path does not yield exactly one parsable SQL statement
   after removal of surrounding prose and code fences, THEN THE SQL_Generator SHALL discard that
   response and retry generation at most the configured number of times, whose default value is 2
   retries per question.
9. IF the configured retry limit for candidate generation is reached and zero candidate queries remain,
   THEN THE SQL_Generator SHALL return a generation-failure outcome carrying the reason code
   `generation_failed` to the Abstention_Controller.
10. IF a candidate query contains a string literal in a filter predicate that is present neither in the
    resolved question text nor in the distinct sample values recorded in the Schema_KB for the
    referenced column, THEN THE SQL_Generator SHALL exclude that candidate from the emitted candidate
    set and record the excluded literal as a trace event.
11. WHEN exemplar exclusion leaves fewer exemplars than the configured number, THE SQL_Generator SHALL
    continue generation with the remaining exemplars, including an empty exemplar set, and SHALL record
    the count of excluded exemplars as a trace event.

### Requirement 12: Static SQL validation and read-only guardrails

*Capability A4.*

**User Story:** As the owner of the database, I want every query proven read-only and
schema-conformant before it runs, so that a model can never damage or exfiltrate data.

#### Acceptance Criteria

1. WHEN a candidate query is produced by the SQL_Generator, by a repair attempt, or by rendering a
   Metric_Layer template, THE SQL_Validator SHALL parse the candidate query into an abstract syntax tree
   using a grammar for the same PostgreSQL major version as the active database, before any execution
   attempt.
2. IF parsing fails, THEN THE SQL_Validator SHALL reject the candidate and return the parser error as
   the repair reason.
3. THE SQL_Validator SHALL accept only statements whose root node is a SELECT, or a WITH clause whose
   body and whose every common table expression are SELECT statements.
4. IF a candidate contains a data-definition, data-modification, transaction-control, privilege or
   session-control construct, THEN THE SQL_Validator SHALL reject the candidate and record a
   guardrail-violation event.
5. IF a candidate contains more than one statement, THEN THE SQL_Validator SHALL reject the candidate.
6. THE SQL_Validator SHALL verify that every table and every column referenced by the candidate exists
   in the Schema_KB for the active dataset version, resolving every unqualified table identifier
   against the single schema recorded for the active dataset version and every unqualified column
   identifier against the relations in scope at the point of reference.
7. IF a candidate references an identifier that is absent from the Schema_KB, or an unqualified
   identifier that resolves to more than one table or column in scope, THEN THE SQL_Validator SHALL
   reject the candidate and name the unresolved identifier as the repair reason.
8. WHEN a candidate omits a row limit and its intent family is a record listing, THE SQL_Validator
   SHALL apply the configured default row limit, whose default value is 1000 rows.
9. THE SQL_Validator SHALL bind every literal derived from user input as a query parameter.
10. THE SQL_Validator SHALL complete validation of one candidate within 100 milliseconds.
11. IF a candidate invokes a function that is absent from the configured function allowlist, whose
    default contents are the built-in aggregate, window, mathematical, string, date-time, casting and
    conditional functions and whose default contents exclude every file-reading, large-object, network,
    database-link, foreign-data-wrapper, sleep, session-state and server-state function, THEN THE
    SQL_Validator SHALL reject the candidate and record a guardrail-violation event.
12. IF a candidate contains a row-locking clause of FOR UPDATE, FOR NO KEY UPDATE, FOR SHARE or FOR KEY
    SHARE, or a result-target clause that materialises rows into a relation of SELECT INTO, CREATE TABLE
    AS or COPY TO, THEN THE SQL_Validator SHALL reject the candidate and record a guardrail-violation
    event.
13. IF validation of a candidate does not reach an explicit accept verdict, including the case of a
    syntax-tree node type absent from the configured accepted-node-type allowlist, whose default
    contents are the node types required for SELECT statements, WITH clauses whose every body is a
    SELECT, joins, filters, grouping, ordering, set operations, row limits and allowlisted function
    calls, and including the case of validation exceeding 100 milliseconds, THEN THE SQL_Validator SHALL
    reject the candidate and record a guardrail-violation event.
14. IF a candidate declares a row limit greater than the configured maximum permitted row limit, whose
    default value is 100000 rows, THEN THE SQL_Validator SHALL reject the candidate and name the
    declared row limit as the repair reason.
15. WHEN the SQL_Validator returns an accept verdict for a candidate, THE SQL_Validator SHALL return one
    canonical statement text together with the bound parameter set covered by that accept verdict.

### Requirement 13: Guarded read-only query execution

*Capability A4.*

**User Story:** As an operator, I want query execution bounded in privileges, time and rows, so that
one bad query cannot stall or damage the demo.

#### Acceptance Criteria

1. THE Query_Executor SHALL connect to PostgreSQL using a database role whose privileges are limited
   to SELECT on the dataset schema.
2. THE Query_Executor SHALL set a statement timeout on every query, with a default of 10 seconds.
3. IF a query exceeds the statement timeout, THEN THE Query_Executor SHALL cancel the query and return
   a typed timeout error carrying the executed SQL.
4. THE Query_Executor SHALL cap the number of rows materialised per query at the configured execution
   row cap, whose default value is 100000 rows.
5. WHEN a query executes successfully, THE Query_Executor SHALL return the result rows, the column
   names, the row count, the execution duration and the dataset version identifier under which the
   query executed.
6. WHEN a candidate query is approved for execution, THE Query_Executor SHALL run it inside a
   read-only transaction.
7. THE Query_Executor SHALL record the executed SQL, bound parameter values, row count, duration and
   the execution kind as one of dry-run sample, plan request, existence query, anomaly history query
   and final execution as a trace event.
8. WHERE the Reviewer_Agent requests an execution plan, THE Query_Executor SHALL return a plan
   containing planner cost estimates and planner row-count estimates for the candidate query, obtained
   without executing the candidate query, and SHALL apply the configured statement timeout to the plan
   request.
9. THE Query_Executor SHALL execute only the canonical statement text returned with an accept verdict
   by the SQL_Validator.
10. IF a query produces more rows than the configured execution row cap, whose default value is 100000
    rows, THEN THE Query_Executor SHALL abort the query, discard the partial result set and return a
    typed row-cap-exceeded error carrying the executed SQL and the configured execution row cap value.
11. WHILE the count of in-flight queries equals the configured maximum concurrent query limit, whose
    default value is 8 queries, THE Query_Executor SHALL hold each further execution request in a wait
    queue until an in-flight query completes.
12. IF an execution request remains in the wait queue for longer than the configured execution queue
    wait timeout, whose default value is 5 seconds, THEN THE Query_Executor SHALL remove the execution
    request from the wait queue and return a typed capacity error carrying the queue wait duration.
13. THE Query_Executor SHALL keep the configured maximum concurrent query limit at or below the
    configured PostgreSQL connection pool size, and THE Finance_Assistant_Backend SHALL fail startup
    with an error naming both values when the configured limit exceeds the configured pool size.
14. IF the active dataset version identifier at the moment a query starts differs from the dataset
    version identifier recorded for the current Turn, THEN THE Query_Executor SHALL abort execution
    before running the query and return a typed dataset-version-changed error carrying both dataset
    version identifiers.
15. THE Query_Executor SHALL execute at most the configured maximum executions per Turn, whose default
    value is 12 executions, counting final executions, dry-run samples, plan requests, existence
    queries and anomaly history queries.

### Requirement 14: Reviewer agent verification and repair

*Capability A4; PDF must-have "hallucination guardrails".*

**User Story:** As a finance user, I want a second, database-aware reviewer to check that the query
really answers my question, so that the number I am given is the number I asked for.

#### Acceptance Criteria

1. WHEN candidate queries pass static validation, THE Reviewer_Agent SHALL receive for each candidate
   the resolved question, the linked sub-schema, the candidate SQL, the parsed table and column
   references, the execution plan and a dry-run sample of at most 20 result rows.
2. THE Reviewer_Agent SHALL return for each reviewed candidate a machine-readable verdict record
   containing exactly one verdict value from the set `approve`, `repair` and `reject`, a written reason
   of at most 500 characters, one defect category drawn from the declared defect-category enumeration
   when the verdict value is `repair` or `reject`, and at least one evidence citation naming a table, a
   column, a filter predicate or a dry-run sample row index that is present in the evidence bundle of
   criterion 1.
3. THE Reviewer_Agent SHALL check intent alignment covering at minimum the aggregation function, the
   grouping columns, the filter predicates, the date range boundaries, the join cardinality and the
   selected result columns against the resolved question.
4. WHEN more than one candidate holds an `approve` verdict, THE Reviewer_Agent SHALL compare the
   executed result sets of the approved candidates as order-insensitive multisets of rows, treating two
   executed result sets as agreeing only when the column count is identical, every numeric value is
   equal after rounding to 2 decimal places and every NULL value is matched by a NULL value, SHALL
   select the candidate whose executed result set agrees with the largest number of other approved
   candidates, SHALL select the candidate with the lowest candidate index when two or more candidates
   hold equal agreement counts, and SHALL record the agreement count as the consistency signal.
5. IF all approved candidates disagree on results, THEN THE Reviewer_Agent SHALL lower the consistency
   signal to its minimum value and record the disagreement as a trace event.
6. WHEN the verdict is `repair`, THE SQL_Generator SHALL produce a revised candidate using the
   reviewer's reason and defect category, THE SQL_Validator SHALL apply the static validation of
   Requirement 12 to the revised candidate before THE Reviewer_Agent receives the revised candidate, and
   each revised candidate produced SHALL count as one repair iteration against the configured repair
   iteration limit, whose default value is 2 iterations, including a revised candidate that fails static
   validation.
7. IF the repair iteration limit is reached without an approved candidate, THEN THE Chat_API SHALL
   return an abstention carrying the reason code `repair_limit_reached` and THE Failure_Store SHALL
   record the case.
8. WHEN the executed result set for a candidate contains zero rows, THE Reviewer_Agent SHALL execute
   exactly one existence query that applies the entity filters of the candidate without the remaining
   predicates, SHALL classify the outcome as `suspected_filter_defect` and return the verdict `repair`
   when that existence query returns at least one row, and SHALL classify the outcome as
   `true_empty_result` when that existence query returns zero rows.
9. THE Reviewer_Agent SHALL record its verdict, reasons, defect categories and every repair iteration
   as trace events.
10. THE Reviewer_Agent SHALL complete its verification for one candidate within the configured reviewer
    deadline, whose default value is 8 seconds.
11. WHEN the outcome of the zero-row check is `true_empty_result`, THE Chat_API SHALL complete the Turn
    with an answer stating that no records match the resolved filters, rather than with an abstention.
12. IF the Reviewer_Agent verdict record fails to parse, carries a verdict value outside the set
    `approve`, `repair` and `reject`, omits the defect category for a `repair` or `reject` verdict, or
    carries an evidence citation naming a table, a column, a filter predicate or a dry-run sample row
    index absent from the evidence bundle of criterion 1, THEN THE Reviewer_Agent SHALL re-request the
    verdict record for that candidate at most the configured reviewer output retry limit, whose default
    value is 1 retry, THE Reviewer_Agent SHALL treat that candidate as holding no `approve` verdict once
    that retry limit is reached, and THE Failure_Store SHALL record the candidate, the non-conforming
    output and the defect category `reviewer_output_nonconformance`.
13. IF the configured reviewer deadline elapses before a conforming verdict record is returned for a
    candidate, or the evidence bundle of criterion 1 for that candidate lacks the execution plan or
    lacks the dry-run sample, THEN THE Reviewer_Agent SHALL treat that candidate as holding no `approve`
    verdict, THE Trace_Service SHALL record a trace event naming the elapsed deadline or the missing
    evidence item, and THE Abstention_Controller SHALL return an abstention carrying the reason code
    `reviewer_unavailable` when no candidate of the Turn holds an `approve` verdict.
14. WHEN the Reviewer_Agent requests the execution plan and the dry-run sample of criterion 1, THE
    Query_Executor SHALL perform at most the configured dry-run limit per Turn, whose default value is 5
    dry-run executions, SHALL bound each dry-run execution by the configured dry-run deadline, whose
    default value is 3 seconds, and by a cap of 20 materialised rows, and THE Budget_Guard SHALL count
    each dry-run execution and each Reviewer_Agent model call against the per-question LLM call limit,
    token limit and wall-clock deadline.
15. IF the Model_Router resolves the reviewer role and the sql_generator role to the same provider, the
    same model identifier and the same Prompt_Registry prompt version, THEN THE
    Finance_Assistant_Backend SHALL reject the configuration at startup and return an error stating that
    reviewer independence from the SQL generator is unsatisfied.
16. THE Budget_Guard SHALL enforce a reviewer phase deadline per Turn, whose default value is 20
    seconds, covering every candidate review and every repair iteration of that Turn.
17. WHEN the Evaluation_Harness completes a run over the golden question set, THE Evaluation_Harness
    SHALL report the reviewer catch rate as the fraction of golden questions whose first candidate result
    set disagrees with the expected result set under the comparison rule of criterion 4 and whose verdict
    is `repair` or `reject`, and SHALL report the reviewer false-rejection rate as the fraction of golden
    questions whose first candidate result set agrees with the expected result set under that comparison
    rule and whose verdict is `repair` or `reject`.


### Requirement 15: Deterministic computation layer

*Capability A4; PDF must-have "accurate computation".*

**User Story:** As a finance user, I want every number computed by the data layer, so that the
language model explains arithmetic rather than performing it.

#### Acceptance Criteria

1. THE Computation_Layer SHALL perform every filter, grouping, aggregation, ratio, difference and
   percentage change either in SQL or in typed Python code operating on executed result rows.
2. THE Computation_Layer SHALL represent monetary values as fixed-precision decimals throughout
   computation, formatting and serialisation.
3. THE Computation_Layer SHALL emit, for every figure released to the user, a computation record
   containing the figure value, its label, its unit or currency, its source column, and the identifier
   of the query that produced it.
4. WHEN a period comparison is requested, THE Computation_Layer SHALL compute the value for each period
   with a separate executed query and SHALL compute the difference and the percentage change from those
   two executed values.
5. THE Computation_Layer SHALL round only at formatting time, SHALL round monetary figures to 2 decimal
   places, SHALL round ratio figures and percentage figures to the configured display precision whose
   default value is 2 decimal places, SHALL round halves away from zero at every rounding step, and
   SHALL record the unrounded value in the computation record.
6. THE Computation_Layer SHALL produce the breakdown table from the executed result rows without
   passing those rows through a model for transformation, SHALL order those rows by a total ordering
   formed from the ordering columns of the executed query followed by every grouping key absent from
   those ordering columns in ascending order, and SHALL present that identical row order in the answer
   preview, in the retained complete result set and in every export of that result set.
7. WHEN a result set exceeds the configured answer-preview row limit, whose default value is 100 rows,
   THE Computation_Layer SHALL include the first rows up to the limit in the answer payload, state the
   total row count, retain the complete result set for export, and compute every released aggregate,
   ratio, difference and percentage change from the complete result set rather than from the included
   rows.
8. IF the denominator of a ratio is zero, or the base period value of a percentage change is zero or
   below zero, THEN THE Computation_Layer SHALL withhold that derived figure, SHALL release the operand
   values that would have produced that figure, and SHALL record the withheld figure as undefined
   together with those operand values in the computation record.
9. WHERE the base period value and the comparison period value of a percentage change are both zero,
   THE Computation_Layer SHALL record the percentage change as 0 percent.
10. THE Computation_Layer SHALL exclude rows whose aggregated column contains NULL from every
    aggregation and SHALL record the excluded-row count and the aggregated-row count in the computation
    record.
11. IF the aggregated-row count of an aggregation is zero, THEN THE Computation_Layer SHALL release no
    numeric figure for that aggregation and SHALL record a zero-row outcome that is distinct from a
    computed value of zero in the computation record.
12. IF the rows contributing to one aggregated monetary figure carry more than one distinct currency,
    THEN THE Computation_Layer SHALL withhold the combined figure and SHALL emit one computation record
    per distinct currency, each stating the currency and the aggregated-row count for that currency.

### Requirement 16: Verifiable answers with breakdown and explainability

*Capability A5; PDF must-haves "verifiable answers" and "explainability".*

**User Story:** As a finance user, I want the plain-language answer paired with the records behind it
and the steps taken, so that I can check the number myself and trust it.

#### Acceptance Criteria

1. WHEN an approved result set is available, THE Answer_Composer SHALL return a plain-language answer,
   the breakdown table, the resolved question, the resolved date range, the executed SQL with every
   parameter placeholder replaced by the literal value bound at execution time, and the applied filters
   in one response payload.
2. THE Answer_Composer SHALL state in the answer text the absolute date range used and the currency of
   every monetary figure.
3. THE Answer_Composer SHALL cite, for each figure in the answer text, the computation record
   identifier that produced it.
4. THE Chat_API SHALL return the row count of the complete result set alongside the previewed rows.
5. THE Chat_API SHALL expose an explanation payload per Turn containing the ordered pipeline steps, the
   retrieved schema chunks, the selected metric or generated SQL, the reviewer verdict, the repair
   iterations and, for every figure stated in the answer text of that Turn, the source record
   identifiers behind that figure.
6. WHEN a Turn used the Metric_Layer, THE Answer_Composer SHALL name the metric definition applied.
7. THE Answer_Composer SHALL keep the answer text within the configured maximum answer length, whose
   default value is 120 words for a request without the detailed answer option and 400 words for a
   request with the detailed answer option.
8. IF a Turn ends in an abstention, THEN THE Chat_API SHALL return an explanation payload containing the
   ordered pipeline steps completed before the abstention, the pipeline step at which execution stopped,
   and the abstention reason code.
9. WHEN the answer text states a figure derived from more than one source record, THE Chat_API SHALL
   return, for that figure, the total count of source records contributing to that figure and the source
   record identifiers of the contributing records up to the configured maximum drill-down size, whose
   default value is 500 identifiers, in an order that is identical across repeated identical requests.
10. WHERE the count of source records contributing to a figure exceeds the configured maximum drill-down
    size, THE Chat_API SHALL state that the identifier list is truncated and SHALL name the
    Export_Service as the path to the complete record set.
11. THE Answer_Composer SHALL return, for every column of the breakdown table, the column label, the
    value type of the column drawn from the set monetary, count, percentage, date and text, and, for
    every column whose value type is monetary, the currency of that column.
12. WHEN the executed query applies one or more filters, THE Chat_API SHALL return the filter expression
    of each applied filter and the count of source records excluded from the result set by all applied
    filters combined.

### Requirement 17: Groundedness verification of the released answer

*Capability A4; PDF must-have "grounded retrieval".*

**User Story:** As a finance user, I want it structurally impossible for the assistant to state a
number that the data did not produce, so that an invented figure never reaches a report.

#### Acceptance Criteria

1. WHEN a draft answer is produced, THE Groundedness_Checker SHALL extract from the draft answer text
   every numeric literal, currency amount, percentage, date and number written in words, including a
   number combined with one of the scale words thousand, lakh, crore, million and billion.
2. THE Groundedness_Checker SHALL treat an extracted numeric value as matched when, after removal of
   currency symbols, grouping separators and whitespace and after multiplication by the numeric
   multiplier of any scale word attached to the extracted value, a value in the executed result set, a
   value in a computation record, or a bound of the resolved date range, rounded to the place value of
   the least significant digit written in the draft answer, equals the extracted value within the
   configured groundedness match tolerance, whose default value is 0.01.
3. IF an extracted numeric value has no matching source, or an entity name stated in the draft answer
   has no matching source, THEN THE Groundedness_Checker SHALL reject the draft answer, record a
   groundedness-violation event naming the unmatched value, and request one regeneration.
4. IF a regenerated answer also fails verification, THEN THE Chat_API SHALL return the breakdown table
   with a templated, deterministic answer sentence generated by the Computation_Layer.
5. THE Groundedness_Checker SHALL verify that every entity name stated in the answer text exists in the
   executed result set or in the resolved filters, comparing names after trimming leading and trailing
   whitespace, collapsing every internal whitespace run to one space, and applying case folding to both
   names.
6. THE Groundedness_Checker SHALL record the count of verified figures and the count of rejected drafts
   for every Turn.
7. THE Groundedness_Checker SHALL complete verification within 300 milliseconds for result sets of up
   to 1000 rows and within 2000 milliseconds for result sets of up to the configured execution row cap,
   whose default value is 100000 rows.
8. IF the draft answer contains a number written in words that THE Groundedness_Checker cannot convert
   to exactly one numeric value, THEN THE Groundedness_Checker SHALL reject the draft answer, record a
   groundedness-violation event naming the unconvertible text span, and request one regeneration.
9. THE Groundedness_Checker SHALL also treat an extracted numeric value as matched when the extracted
   value equals the row count of the complete executed result set, the count of groups in the executed
   result set, the count of records enumerated in the draft answer text, or an ordinal position between
   1 and the row count of the complete executed result set.
10. THE Groundedness_Checker SHALL treat an extracted date, month name with year, quarter label or
    four-digit year as matched when the extracted value names a bound of the resolved date range or
    names a calendar period that the resolved date range covers.
11. IF the draft answer contains no extracted numeric value, THEN THE Groundedness_Checker SHALL record
    a verified-figure count of 0, apply the entity-name verification of criterion 5, and approve the
    draft answer when the entity-name verification reports no unmatched name.

### Requirement 18: Abstention and clarification behaviour

*Capability A4; PDF must-have "hallucination guardrails".*

**User Story:** As a finance user, I want to be told plainly when the data cannot answer my question,
so that I never mistake a guess for a fact.

#### Acceptance Criteria

1. IF the data required to answer a question is absent from the active dataset, THEN THE
   Abstention_Controller SHALL return an abstention that names the missing data and lists the question
   families the dataset does support.
2. IF a question is ambiguous with respect to entity, metric, date range or grouping, THEN THE
   Abstention_Controller SHALL return one clarifying question that names the ambiguity and offers at
   most 5 concrete options, THE Chat_API SHALL complete the Turn with outcome
   `clarification_requested`, and THE Context_Resolver SHALL persist the original question text, the
   named ambiguity and a clarification round count incremented by 1 as the pending clarification state
   of the session.
3. WHILE the Query_Planner has recorded a named ambiguity for a question, IF the confidence score is
   below the acceptance threshold defined in Requirement 19, THEN THE Abstention_Controller SHALL
   return one clarifying question that names that ambiguity.
4. WHEN an abstention is returned, THE Chat_API SHALL set exactly one machine-readable abstention
   reason code from the enumeration `data_absent`, `intent_unsupported`, `ambiguous_entity`,
   `ambiguous_metric`, `ambiguous_date_range`, `ambiguous_grouping`, `reference_unresolved`,
   `clarification_exhausted`, `confidence_below_threshold`, `period_outside_coverage`,
   `entity_not_found`, `repair_limit_reached`, `budget_exhausted`, `provider_unavailable`,
   `schema_linking_failed`, `generation_failed`, `reviewer_unavailable`, `dataset_version_changed`,
   `metric_execution_failed`, `term_undefined` and `embedding_dimension_mismatch`, SHALL exclude the
   breakdown table from the response, and SHALL omit from the answer text every numeric value other
   than the dataset coverage dates required by criterion 6.
5. WHEN an abstention is returned, THE Buddy_Agent SHALL include at most 3 answerable alternative
   questions derived from the Schema_KB.
6. WHEN a question asks for a period that lies wholly outside the dataset date coverage, THE
   Abstention_Controller SHALL state the dataset coverage range and abstain from producing a figure.
7. WHEN a question asks for an entity that resolves to no dataset value, THE Abstention_Controller
   SHALL state that the entity is absent and offer the closest existing values.
8. THE Abstention_Controller SHALL record every abstention and every clarifying question returned by
   the Finance_Assistant_Backend with the turn identifier, with exactly one reason code from the
   enumeration in criterion 4, and with the pipeline step that produced the outcome, for measurement of
   abstention correctness and clarification correctness.
9. WHEN the Schema_Linker reports a schema-linking failure, THE Abstention_Controller SHALL return an
   abstention carrying the reason code `schema_linking_failed`.
10. WHEN a result set contains zero rows and the Reviewer_Agent has classified the outcome as
    `true_empty_result`, THE Chat_API SHALL return an answer stating that no records match the resolved
    filters, and THE Abstention_Controller SHALL reserve the reason code `data_absent` for questions
    whose required data is absent from the active dataset schema.
11. IF the clarification round count for one original question reaches the configured clarification
    round limit, whose default value is 2 rounds, THEN THE Abstention_Controller SHALL return an
    abstention carrying the reason code `clarification_exhausted` that names the ambiguity remaining
    unresolved.
12. WHILE a pending clarification state exists for a session, WHEN a client posts the next message to
    that session, THE Context_Resolver SHALL produce a resolved question by applying that message to
    the pending original question text and the named ambiguity, and THE Chat_API SHALL clear the
    pending clarification state.
13. IF the confidence score is below the acceptance threshold defined in Requirement 19 and the
    Query_Planner has recorded no named ambiguity for the question, THEN THE Abstention_Controller
    SHALL return an abstention carrying the reason code `confidence_below_threshold` that names the
    weakest contributing confidence signal.
14. WHEN the Evaluation_Harness runs the golden question set, THE Evaluation_Harness SHALL classify
    each returned abstention as a helpful refusal for golden entries whose expected behaviour class is
    `abstain` and as an unhelpful refusal for golden entries whose expected behaviour class is
    `answer`, and SHALL report the helpful refusal count, the unhelpful refusal count and the unhelpful
    refusal rate for the run.
15. IF the unhelpful refusal count of a run exceeds the configured unhelpful refusal ceiling, whose
    default value is 5 percent of the golden entries whose expected behaviour class is `answer`, THEN
    THE Evaluation_Harness SHALL mark the run as failed and SHALL name the measured unhelpful refusal
    rate in the run report.

### Requirement 19: Confidence signalling

*Capability A4; PDF bonus "confidence signalling".*

**User Story:** As a finance user, I want to see when the assistant is less certain, so that I know
which answers to double-check before acting.

#### Acceptance Criteria

1. WHEN a Turn produces an answer, THE Confidence_Scorer SHALL compute a confidence score in the closed
   interval from 0 to 1 as the sum, over the signals applicable to that Turn, of each signal's
   normalised value multiplied by that signal's configured weight, where every signal in the documented
   signal set — metric-template match, schema-linking score margin, candidate agreement count measured
   as the count of generated candidate statements whose normalised query form equals the normalised
   query form of the selected candidate, reviewer verdict, repair iteration count, result-set row-count
   sanity, entity-resolution match quality and groundedness verification outcome — is normalised to the
   closed interval from 0 to 1 with 1 denoting the strongest evidence of correctness for that signal.
2. THE Confidence_Scorer SHALL publish the weight of every signal in configuration so that the score is
   reproducible and auditable.
3. THE Confidence_Scorer SHALL map the score to exactly one confidence band from `high`, `medium` and
   `low` using the configured band boundaries, whose defaults assign scores from 0 to below 0.50 to
   `low`, scores from 0.50 to below 0.80 to `medium`, and scores from 0.80 to 1 to `high`.
4. WHEN the confidence band is `medium` or `low`, THE Answer_Composer SHALL include a stated caution
   naming the applicable signal with the lowest weighted contribution to the score, resolving ties in
   favour of the signal appearing first in the configured signal order.
5. THE Chat_API SHALL return the confidence score, the confidence band and, for every signal in the
   documented signal set, the normalised value, the applied weight, the weighted contribution and
   whether that signal was applicable to the Turn, in the turn response.
6. WHERE a Turn used the Metric_Layer path, IF the Reviewer_Agent verdict is `approve` on the first
   attempt and the Groundedness_Checker outcome is a pass, THEN THE Confidence_Scorer SHALL set the
   score to the greater of the computed score and the lower boundary of the `high` band, whose default
   value is 0.80.
7. THE Metrics_API SHALL report the observed accuracy of each confidence band against the golden
   question set so that calibration is measurable.
8. THE Confidence_Scorer SHALL apply the configured acceptance threshold, whose default value is 0.60 on
   the closed interval from 0 to 1, as the minimum confidence score at which a Turn releases a figure
   rather than a clarifying question or an abstention, and THE Abstention_Controller SHALL read that
   threshold from this criterion.
9. IF the configured signal weights contain a value below 0, or the configured signal weights sum to a
   value differing from 1 by more than 0.001, or the configured confidence band boundaries fail to form
   a strictly ascending sequence covering the closed interval from 0 to 1 without overlap, THEN THE
   Finance_Assistant_Backend SHALL fail startup with an error naming the invalid configuration entry.
10. WHEN the pipeline step that produces a signal in the documented signal set did not run for a Turn,
    THE Confidence_Scorer SHALL compute the score from the remaining applicable signals with the
    weights of those remaining signals rescaled to sum to 1.
11. THE Confidence_Scorer SHALL treat the reviewer verdict signal and the groundedness verification
    outcome signal as applicable to every Turn that returns an answer, so that at least 2 signals carry
    non-zero weight for every scored Turn.
12. WHEN two Turns present an identical set of applicable signals and every normalised signal value of
    the first Turn is greater than or equal to the corresponding normalised signal value of the second
    Turn, THE Confidence_Scorer SHALL compute for the first Turn a confidence score greater than or
    equal to the confidence score computed for the second Turn.
13. IF a completed Evaluation_Harness run over the golden question set places at least the configured
    calibration minimum band size, whose default value is 10 golden questions, in a confidence band,
    and that band shows an observed execution accuracy below the configured minimum accuracy for that
    band, whose default values are 0.90 for `high`, 0.60 for `medium` and 0 for `low`, or an observed
    execution accuracy below the observed execution accuracy of a lower band, THEN THE
    Evaluation_Harness SHALL record a calibration failure naming the band, the observed execution
    accuracy and the breached calibration condition.

### Requirement 20: Anomaly callouts

*Capability A4; PDF bonus "simple anomaly callouts".*

**User Story:** As a finance user, I want an unusually large payout pointed out while I am asking
about something else, so that outliers surface without a separate investigation.

#### Acceptance Criteria

1. THE Anomaly_Detector SHALL apply a documented deterministic rule based on the median and the median
   absolute deviation of the entity's own history, computing the modified z-score as 0.6745 multiplied
   by the difference obtained by subtracting the median from the value and divided by the median
   absolute deviation, and flagging a value whose signed modified z-score exceeds the configured
   threshold, whose default value is 3.5.
2. THE Anomaly_Detector SHALL require at least the configured minimum history count for an entity
   before evaluating that entity, with a default of 6 prior values.
3. WHEN an answer includes vendor payouts or transaction amounts, THE Anomaly_Detector SHALL evaluate
   the returned values against the entity history using an executed query, restricted to the configured
   maximum entities per Turn selected in descending order of each entity's largest returned value with
   ties broken by ascending entity identifier, whose default value is 20 entities.
4. WHEN at least one value is flagged, THE Answer_Composer SHALL append at most 3 anomaly callouts,
   ordered with flags produced by the modified z-score rule before flags produced by the zero-dispersion
   rule, within the first group by descending modified z-score, within the second group by descending
   difference between the flagged value and the entity's median, and within each group with ties broken
   by ascending entity identifier, each callout stating the entity, the flagged value, the entity's
   median value and the computed score rounded to 2 decimal places, and each callout produced by the
   zero-dispersion rule stating the relative difference rounded to 2 decimal places in place of the
   modified z-score.
5. THE Anomaly_Detector SHALL compute every anomaly figure in the Computation_Layer.
6. WHERE anomaly callouts are disabled in configuration, THE Answer_Composer SHALL omit the callouts
   and leave the primary answer unchanged.
7. THE Anomaly_Detector SHALL record each evaluation, each flag and each skipped evaluation as a trace
   event carrying a machine-readable reason code drawn from `insufficient_history`,
   `zero_dispersion_within_threshold` and `budget_or_time_limit_reached`.
8. THE Anomaly_Detector SHALL derive the entity history used for the median and the median absolute
   deviation from a single result set retrieved through the Query_Executor, covering the configured
   anomaly history window whose default value is the 24 months preceding the value under evaluation,
   excluding the value under evaluation, bounded by the configured maximum history rows per entity whose
   default value is 500 rows, and counted against the per-question limits enforced by the Budget_Guard.
9. IF the median absolute deviation of an entity's history equals zero, THEN THE Anomaly_Detector SHALL
   flag the value under evaluation when the difference obtained by subtracting the entity's median from
   the value under evaluation exceeds the configured zero-dispersion relative threshold, whose default
   value is 0.20, multiplied by the absolute value of the entity's median, and also exceeds the
   configured zero-dispersion absolute floor, whose default value is 1000 units of the dataset currency.
10. IF the Budget_Guard reports remaining per-question budget below the configured anomaly evaluation
    reserve, whose default value is 1 executed query, or the entity history retrieval exceeds the
    configured anomaly evaluation time limit, whose default value is 1500 milliseconds, THEN THE
    Anomaly_Detector SHALL skip anomaly evaluation for the Turn and return zero flags.
11. IF the Groundedness_Checker cannot source a numeral in an anomaly callout to the executed result
    set, to the executed entity history result set, or to a Computation_Layer derivation over either
    result set, THEN THE Answer_Composer SHALL omit that anomaly callout, SHALL record the omission with
    a machine-readable reason code as a trace event, and SHALL release the primary answer unchanged.

### Requirement 21: Live execution trace streaming

*Capability A5.*

**User Story:** As a UI developer, I want every pipeline step streamed as it happens, so that the
interface can show the assistant thinking and prove the answer was computed.

#### Acceptance Criteria

1. WHEN a Turn starts, THE Trace_Service SHALL open an event stream for that turn identifier over
   Server-Sent Events and over WebSocket.
2. THE Trace_Service SHALL emit at least one trace event for every pipeline stage that a Turn reaches,
   where a Turn reaches a stage when the pipeline enters that stage or bypasses that stage while
   continuing to a later stage, with every stage name drawn from the closed set intake,
   context_resolution, intent_classification, entity_resolution, schema_retrieval, schema_linking,
   metric_routing, exemplar_retrieval, sql_generation, static_validation, plan_inspection,
   reviewer_verdict, repair_iteration, execution, computation, anomaly_check, answer_composition,
   groundedness_check, confidence_scoring and completion, and THE Trace_Service SHALL emit events for
   the stages intake, context_resolution, intent_classification and completion on every Turn including
   a Turn that terminates before reaching later stages.
3. THE Trace_Service SHALL assign every event of a Turn a strictly increasing sequence number starting
   at 1 with no gaps.
4. THE Trace_Service SHALL include in every event the turn identifier, sequence number, stage name,
   status drawn from the closed set `ok`, `error` and `skipped` for a stage event and from the closed
   set `completed`, `abstained` and `failed` for the terminal event, start timestamp, duration in
   milliseconds, input summary, output summary and, where a model was called, the role, provider, model
   identifier, input token count and output token count.
5. WHEN a stage fails, THE Trace_Service SHALL emit an event with status `error` carrying the error
   type and message, and SHALL continue emitting subsequent events until the terminal event.
6. THE Trace_Service SHALL emit exactly one terminal event per Turn with status `completed`, `abstained`
   or `failed`.
7. WHEN a client connects to the stream for a Turn after that Turn has begun, THE Trace_Service SHALL
   replay every event already emitted for that Turn in ascending sequence order before streaming new
   events, SHALL serve concurrent subscribers to the same turn identifier independently so that each
   subscriber receives sequence numbers 1 to N in ascending order, SHALL continue recording events for
   that Turn while zero connections are open, and SHALL keep the events of that Turn replayable for the
   configured trace replay retention period, whose default value is 15 minutes, after the terminal
   event.
8. THE Trace_Service SHALL emit each event within 200 milliseconds of the stage completing.
9. THE Trace_Service SHALL redact configured secret keys from event payloads.
10. WHEN a Turn executes the same pipeline stage more than once, THE Trace_Service SHALL emit one trace
    event per execution of that stage and SHALL include in each of those events a stage attempt ordinal
    that starts at 1 for the first execution of that stage name within the Turn and increases by exactly
    1 for each subsequent execution of that stage name.
11. IF the pipeline bypasses a stage while continuing to a later stage of the same Turn, THEN THE
    Trace_Service SHALL emit exactly one trace event for the bypassed stage with status `skipped`, a
    machine-readable skip reason code and a duration of 0 milliseconds.
12. WHILE a pipeline stage of a Turn is executing and no trace event for that Turn has been emitted for
    the configured trace keepalive interval, whose default value is 10 seconds, THE Trace_Service SHALL
    emit on every open Server-Sent Events connection and every open WebSocket connection for that turn
    identifier a keepalive frame carrying the turn identifier and the name of the executing stage, and
    SHALL emit keepalive frames outside the trace event sequence numbering so that trace event sequence
    numbers remain contiguous.
13. IF a trace event input summary or output summary would exceed the configured maximum trace event
    size, whose default value is 32 kilobytes, or the configured maximum inline sample rows, whose
    default value is 20 rows, THEN THE Trace_Service SHALL truncate that summary to both bounds, SHALL
    set a truncation indicator in that event, and SHALL include in that event the untruncated total row
    count and the untruncated total character count.
14. THE Trace_Service SHALL emit the terminal event for a Turn on every connection open for that turn
    identifier before THE Chat_API sends the final response body for that Turn.

### Requirement 22: Persisted trace retrieval

*Capability A5, A7.*

**User Story:** As a reviewer of an answer given yesterday, I want to fetch the full trace by
identifier, so that any number can be audited after the fact.

#### Acceptance Criteria

1. WHEN THE Trace_Service emits a trace event for a Turn, THE Trace_Service SHALL persist that event to
   PostgreSQL within the configured trace persistence window, whose default value is 1000 milliseconds
   after emission, irrespective of whether the terminal event of that Turn carries status `completed`,
   `abstained` or `failed`.
2. THE Trace_Service SHALL expose a read endpoint returning the complete, ordered event list for a
   given turn identifier.
3. THE Trace_Service SHALL expose a read endpoint returning the trace summary for every Turn in a
   session, ordered by turn creation time ascending and by turn identifier ascending for equal turn
   creation times, in pages of the configured trace summary page size, whose default value is 50 and
   whose maximum value is 200, and SHALL return a continuation token while further Turns of that session
   remain.
4. WHERE a Turn reached the execution stage, THE Trace_Service SHALL include in the persisted trace of
   that Turn the executed SQL, the bound parameters, the returned row count, the reviewer verdicts, the
   repair iterations, the confidence signals and the token counts of that Turn.
5. WHEN a persisted trace is retrieved for a Turn whose terminal event was streamed, THE Trace_Service
   SHALL return an event list with the same event count and the same sequence numbers as the live stream
   of that Turn, with identical stage name, status, start timestamp, duration in milliseconds and, where
   a model was called, identical role, provider, model identifier, input token count and output token
   count for every event, and with identical input summary and output summary for every field carrying
   no truncation indicator.
6. THE Trace_Service SHALL retain every persisted trace for at least the configured retention period,
   whose default value is 30 days after turn creation time, and SHALL delete every persisted trace whose
   turn creation time is older than that retention period plus 24 hours.
7. IF a Turn has at least one persisted trace event and no terminal event of that Turn has been emitted
   within the configured turn abandonment window, whose default value is 300 seconds after the last
   emitted event of that Turn, THEN THE Trace_Service SHALL persist a terminal event for that Turn with
   status `failed` carrying an error type stating that the Turn was abandoned without a terminal event.
8. IF a trace event field exceeds the configured maximum persisted field length, whose default value is
   16384 characters, THEN THE Trace_Service SHALL persist the first 16384 characters of that field and
   SHALL persist for that field a truncation indicator carrying the original field length in characters.
9. IF a read request names a turn identifier for which no trace is persisted, THEN THE Trace_Service
   SHALL return a client error that distinguishes an unrecognised turn identifier from a trace deleted
   by retention enforcement and that states the deletion timestamp for a deleted trace.
10. WHILE a Failure_Store case referencing a Turn holds a status of `new`, `triaged`, `proposed` or
    `approved`, THE Trace_Service SHALL retain the persisted trace of that Turn irrespective of the
    configured retention period.

### Requirement 23: Breakdown export to CSV and Excel

*Capability A5; PDF good-to-have "export".*

**User Story:** As a finance user, I want the breakdown exported to CSV or Excel, so that I can attach
it to a reconciliation or share it with my team.

#### Acceptance Criteria

1. WHEN a client requests an export for a completed Turn, THE Export_Service SHALL produce the file in
   the requested format from the persisted result-set snapshot of that Turn, and SHALL derive every
   exported value from that snapshot without re-executing the SQL of that Turn.
2. THE Export_Service SHALL support the formats `csv` and `xlsx`.
3. THE Export_Service SHALL write the same columns that the breakdown table presented, in the column
   order recorded in the persisted result-set snapshot of that Turn and in the row order recorded in that
   snapshot, so that the rows presented in the breakdown table appear as the leading rows of the export
   in the presented order.
4. THE Export_Service SHALL write monetary values with the same precision recorded in the computation
   records.
5. THE Export_Service SHALL write the question, the resolved question, the resolved date range, the
   executed SQL, the turn identifier and the generation timestamp into a dedicated metadata worksheet of
   an `xlsx` export, and into leading lines that each begin with the `#` character before the
   column-name line of a `csv` export.
6. IF the requested Turn produced an abstention, THEN THE Export_Service SHALL return a client error
   stating that no result set exists for that Turn.
7. THE Export_Service SHALL export result sets of up to 100000 rows.
8. WHERE the requested format is `csv`, THE Export_Service SHALL write the file encoded in UTF-8 without
   a byte order mark, using the comma character as the field delimiter, the double-quote character as the
   quote character, two consecutive double-quote characters for an embedded double-quote, quote
   characters around every field containing a delimiter, a quote character or a line break, a
   carriage-return line-feed pair as the line terminator, and one line holding the column names
   immediately after the metadata lines and immediately before the first breakdown row.
9. WHERE the requested format is `csv`, IF a cell value of a non-numeric column begins with the `=`,
   `+`, `-` or `@` character, THEN THE Export_Service SHALL write that cell value prefixed with a single
   apostrophe character.
10. WHERE the requested format is `xlsx`, THE Export_Service SHALL write every breakdown row to a single
    worksheet, SHALL write each value of a numeric column as a numeric cell whose value equals the value
    recorded in the computation records, SHALL write each monetary cell with the number of displayed
    decimal places recorded in the computation records, and SHALL write each value of a non-numeric
    column as a text cell.
11. IF a client requests an export for a completed Turn whose persisted result-set snapshot has been
    removed after the configured result-set snapshot retention period, whose default value is 30 days,
    THEN THE Export_Service SHALL return a client error stating that the result set of that Turn is no
    longer retained.
12. IF a client requests an export with a format value outside `csv` and `xlsx`, for a Turn that has not
    completed, or for a result-set snapshot whose row count exceeds the configured maximum export rows,
    whose default value is 100000 rows, THEN THE Export_Service SHALL return a client error naming the
    rejected condition.
13. THE Export_Service SHALL stream the export file in the response body and SHALL complete generation
    of an export of 100000 rows within the configured export deadline, whose default value is 60 seconds.

### Requirement 24: Failure capture

*Capability A6.*

**User Story:** As a developer improving the assistant, I want every wrong or rejected answer stored
with full context, so that improvement work starts from evidence.

#### Acceptance Criteria

1. WHEN the Reviewer_Agent returns a `reject` verdict, THE Failure_Store SHALL record a failure case.
2. WHEN the Groundedness_Checker rejects a draft answer, THE Failure_Store SHALL record a failure case.
3. WHEN a user submits negative feedback on a Turn, THE Failure_Store SHALL record a failure case.
4. WHEN the Evaluation_Harness scores a golden question as incorrect, THE Failure_Store SHALL record a
   failure case.
5. THE Failure_Store SHALL record for each case the original question, the resolved question, the
   conversation state, the retrieved schema chunks, the retrieved exemplars, every candidate query, the
   reviewer verdicts, the executed SQL, up to the configured number of returned rows whose default value
   is 100 rows together with the total returned row count, the released answer, the expected result, the
   prompt versions in effect, the model identifiers in effect, and the dataset version, and SHALL record
   the value `not_applicable` for each listed field holding no value at the moment of capture.
6. THE Failure_Store SHALL assign each case a status from `new`, `triaged`, `proposed`, `approved`,
   `applied` and `dismissed`, and a source from `reviewer_reject`, `groundedness_reject`,
   `user_negative_feedback`, `evaluation_incorrect` and `pipeline_fault`.
7. THE Metrics_API SHALL expose failure cases filtered by status, source, intent family and date range.
8. THE Chat_API SHALL accept explicit user feedback of `positive` or `negative` with optional free text
   of at most 2000 characters for any completed Turn, and IF a feedback submission carries free text
   longer than 2000 characters, THEN THE Chat_API SHALL reject the submission with an error stating the
   character limit.
9. IF a Turn terminates through the Schema_Linker returning no candidate sub-schema, the SQL_Generator
   returning no candidate query, the Query_Executor returning an execution error, the Query_Executor
   exceeding the configured statement timeout, the Budget_Guard exhausting a per-question limit, the
   Model_Router exhausting every configured fallback, or the Reviewer_Agent returning a verdict record
   that the Reviewer_Agent classifies as non-conforming, THEN THE Failure_Store SHALL record a failure
   case with source `pipeline_fault`, the terminating condition, and the abstention reason code emitted
   for the same Turn.
10. WHEN the Failure_Store records a failure case whose resolved question, source and dataset version
    match an existing failure case holding status `new`, `triaged` or `proposed`, THE Failure_Store SHALL
    increment the occurrence count of the matching failure case, record the capture timestamp as the
    latest occurrence of the matching failure case, and retain exactly one failure case for that
    combination of resolved question, source and dataset version.
11. WHEN the Failure_Store records a failure case whose resolved question, source and dataset version
    match an existing failure case holding status `applied` or `dismissed`, THE Failure_Store SHALL
    create a new failure case, link that new case to the earlier case, and mark that new case as a
    recurrence after resolution.
12. WHEN the Failure_Store records a failure case, THE Failure_Store SHALL store a copy of every field
    listed in criterion 5 inside the failure case, and SHALL return those stored values unchanged after
    any later Ingestion_Service run, Dataset_Manifest replacement, Prompt_Registry version change,
    Exemplar_Bank version change or deletion of the Trace_Service events of the same Turn.
13. WHEN the Failure_Store records a failure case, THE Failure_Store SHALL replace every configured
    provider credential value, database credential value and API key value occurring in any recorded
    field with the fixed placeholder `[REDACTED]`.
14. THE Failure_Store SHALL retain at most the configured maximum failure cases, whose default value is
    10000 cases, and SHALL delete the oldest cases holding status `applied` or `dismissed` first when
    that maximum is reached.


### Requirement 25: Self-improvement pipeline with human approval

*Capability A6.*

**User Story:** As a developer, I want the system to analyse its own failures and propose concrete
fixes for me to approve, so that accuracy improves between demo runs without retraining a model.

#### Acceptance Criteria

1. WHEN an improvement run is triggered, THE Improvement_Pipeline SHALL analyse every failure case
   whose status is `new` or `triaged`.
2. THE Improvement_Pipeline SHALL attribute each failure case to exactly one primary root-cause
   category from `schema_retrieval`, `schema_linking`, `entity_resolution`, `date_resolution`,
   `intent_classification`, `sql_semantics`, `prompt_ambiguity`, `missing_exemplar`,
   `missing_metric_definition`, `missing_column_description`, `reviewer_miss`, `data_gap` and
   `unattributed`.
3. THE Improvement_Pipeline SHALL select analysed cases for proposal generation in ascending order of
   failure-case creation timestamp until the configured maximum proposals per run, whose default value
   is 20 proposals, exist for the run, SHALL produce for each selected case at least one concrete
   proposed change of type `prompt_patch`, `new_exemplar`, `schema_description_update`,
   `new_metric_template` or `configuration_change`, expressed as the exact artefact content to be
   written, and SHALL leave the status of every analysed case not selected unchanged.
4. THE Improvement_Pipeline SHALL group cases that share a root cause into a single proposal when the
   proposed change is identical.
5. WHEN a proposal is created, THE Improvement_Pipeline SHALL set the proposal status to
   `awaiting_approval`, SHALL record the identifier of the active version of every artefact the proposal
   affects, and SHALL apply no artefact change.
6. WHEN a human approves a proposal through the API, THE Improvement_Pipeline SHALL create a new version
   holding status `candidate` of every affected artefact in the Prompt_Registry, the Exemplar_Bank, the
   Schema_KB descriptions or the Metric_Layer, SHALL leave the version holding status `active`
   unchanged, and SHALL retain the previous version.
7. WHEN a proposal is approved, THE Evaluation_Harness SHALL run the golden question set against the
   candidate artefact version before the version becomes active.
8. IF a candidate version scores below the active version on execution accuracy or on grounding rate, or
   the Evaluation_Harness run for a candidate version does not complete within the configured
   improvement evaluation timeout, whose default value is 1800 seconds, THEN THE Improvement_Pipeline
   SHALL withhold promotion, SHALL set the status of every candidate version belonging to the proposal
   to `rejected`, and SHALL record the compared execution accuracy and grounding rate figures for a
   completed run or a reason code stating evaluation timeout for an incomplete run.
9. WHEN every candidate version belonging to an approved proposal scores at or above the active version
   on execution accuracy and on grounding rate, THE Improvement_Pipeline SHALL activate every candidate
   version belonging to that proposal in a single atomic operation in which either every candidate
   version reaches status `active` or every affected artefact retains the version that held status
   `active` before promotion, and SHALL record the promotion with both score sets.
10. THE Improvement_Pipeline SHALL retain the most recent versions of each artefact up to the configured
    artefact version retention count, whose default value is 10 versions, and SHALL support reverting to
    any retained artefact version through the API.
11. THE Improvement_Pipeline SHALL record every model call it makes with its token counts, and these
    calls SHALL be excluded from per-question budgets because they run offline.
12. WHILE an artefact version in the Prompt_Registry, the Exemplar_Bank, the Schema_KB descriptions or
    the Metric_Layer holds status `candidate`, THE Finance_Assistant_Backend SHALL serve every
    question-answering request from the version of that artefact holding status `active`.
13. WHILE an improvement run holds status `in_progress`, IF a further improvement run is triggered, THEN
    THE Improvement_Pipeline SHALL reject the further trigger, SHALL return a reason code stating that
    an improvement run is already in progress, and SHALL leave the in-progress run unchanged.
14. IF a proposal is approved and the identifier of the active version of any artefact affected by that
    proposal differs from the artefact version identifier recorded at proposal creation, THEN THE
    Improvement_Pipeline SHALL set the proposal status to `stale`, SHALL apply no artefact change, and
    SHALL return a reason code stating that an affected artefact changed after proposal creation.
15. IF a proposed change of type `new_exemplar` contains a question that is identical, after case folding
    and after collapsing consecutive whitespace characters to one space, to a question in the golden
    question set, THEN THE Improvement_Pipeline SHALL discard that proposed change and SHALL record a
    reason code stating golden-question-set overlap.
16. WHEN a human approves a proposal, rejects a proposal or reverts an artefact version through the API,
    THE Improvement_Pipeline SHALL record the identity of the acting human, the action taken, the
    identifiers of the affected artefact versions and the UTC timestamp of the action, and SHALL retain
    each record for as long as any affected artefact version is retained.

### Requirement 26: Evaluation harness, golden question set and model-choice evidence

*Capability A3, A7; PDF bonus "note on model choice".*

**User Story:** As a hackathon participant, I want measured accuracy across candidate lightweight
models, so that the model-choice rationale in the deck is backed by numbers.

#### Acceptance Criteria

1. THE golden question set SHALL contain at least 60 questions covering vendor spend, category spend,
   account spend, transaction lookup, payout listing, reconciliation status, period comparison,
   multi-turn follow-ups, ambiguous questions requiring clarification and unanswerable questions
   requiring abstention.
2. THE golden question set SHALL declare for each entry the question, the conversation context where
   applicable, the expected behaviour class from `answer`, `clarify` and `abstain`, the expected result
   set or expected figure where the class is `answer`, the expected column names where the class is
   `answer`, whether result row order is significant, the acceptable date range, the tagged metric
   definition where applicable, and the dataset version against which the expected result set was
   captured.
3. WHEN the Evaluation_Harness runs, THE Evaluation_Harness SHALL score execution accuracy as the
   fraction of golden question set entries of class `answer` whose executed result set matches the
   expected result set, where a match requires a row count identical to the expected row count,
   comparison restricted to the declared expected column names, numeric values differing by at most
   0.01, text values identical after case folding and after removal of leading and trailing whitespace,
   a null value matched only by a null value, row sequence identical to the expected row sequence for
   entries declaring result row order significant and row sequence ignored for every other entry, and
   where an entry of class `answer` for which the Finance_Assistant_Backend returns a clarifying
   question or an abstention scores as a non-match.
4. THE Evaluation_Harness SHALL score grounding rate, abstention correctness, clarification correctness,
   SQL validity rate, reviewer catch rate, reviewer false-rejection rate, first-attempt success rate,
   mean repair iterations, mean tokens per question, mean LLM calls per question and per-stage latency
   percentiles.
5. WHEN the Evaluation_Harness is run with a list of candidate model configurations, THE
   Evaluation_Harness SHALL produce one comparison report containing, for every candidate and every
   scored metric, the mean and the difference between the highest and the lowest value across the
   repeated executions of that candidate, and SHALL include in that report only runs persisted with
   status `complete`.
6. THE Evaluation_Harness SHALL write each run to PostgreSQL with the run identifier, the repeat index
   within the run, the run status from `complete` and `incomplete`, the dataset version, the prompt
   versions, the model configuration and every scored metric.
7. THE Finance_Assistant_Backend SHALL achieve at least 90% execution accuracy and 100% grounding rate
   on the golden question set with the pinned lightweight model tier, measured as the mean across the
   repeated executions of one run persisted with status `complete` at the dataset version declared in
   the golden question set, before the submission is considered complete.
8. THE Finance_Assistant_Backend SHALL produce a written model-choice note stating the selected model,
   the reason for selection, and the measured scores of every evaluated candidate.
9. THE Evaluation_Harness SHALL run without a network connection when the configured provider is a
   locally hosted model.
10. WHEN the Evaluation_Harness executes a golden question set entry declaring conversation context, THE
    Evaluation_Harness SHALL submit every declared preceding turn in the declared order within one
    session, submit the entry's question as the final turn of that same session, and score only the
    response to that final turn.
11. WHEN the Evaluation_Harness runs one candidate model configuration, THE Evaluation_Harness SHALL
    execute the complete golden question set the number of times given by the configured evaluation
    repeat count, whose default value is 3, and SHALL record for every scored metric the mean across
    those executions and the difference between the highest and the lowest value observed across those
    executions.
12. THE Model_Router SHALL apply a temperature of 0 for every role invoked by an Evaluation_Harness run,
    so that repeated runs of one configuration differ only through provider non-determinism.
13. IF the dataset version loaded by the Ingestion_Service differs from the dataset version declared in
    the golden question set, THEN THE Evaluation_Harness SHALL stop before executing any golden question
    set entry, SHALL persist no scored metrics for the stopped run, and SHALL report an error stating the
    dataset version mismatch.
14. IF the question text of any golden question set entry, after case folding and after collapsing
    consecutive whitespace to one space, is identical to the question text of any demonstration pair in
    the Exemplar_Bank, THEN THE Evaluation_Harness SHALL stop before scoring, SHALL report an error
    stating evaluation-set leakage, and SHALL list the identifier of every matching golden question set
    entry.
15. WHEN the cumulative token count of a run reaches the configured evaluation run token budget, whose
    default value is 2000000 tokens, or the elapsed wall-clock time of a run reaches the configured
    evaluation run wall-clock limit, whose default value is 3600 seconds, THE Evaluation_Harness SHALL
    stop submitting further golden question set entries and SHALL persist the run with status
    `incomplete`, the count of executed entries and the count of unexecuted entries.

### Requirement 27: Metrics and analytics APIs ready for a dashboard

*Capability A7.*

**User Story:** As a dashboard developer, I want every KPI, time series and drill-down available from
documented endpoints, so that the metrics dashboard and analytics page can be built against a
finished API.

#### Acceptance Criteria

1. THE Metrics_API SHALL expose an overview endpoint returning, for a requested date range, the session
   count, turn count, answered turn count, abstained turn count, clarified turn count, failed turn
   count, mean confidence score, positive feedback count and negative feedback count.
2. THE Metrics_API SHALL expose an accuracy endpoint returning execution accuracy, grounding rate,
   abstention correctness split into helpful refusals and unhelpful refusals, SQL validity rate,
   reviewer catch rate, reviewer false-rejection rate and first-attempt success rate for the latest
   evaluation run and for a requested run identifier, and THE Metrics_API SHALL return with every
   accuracy response the evaluation run identifier, the UTC instant at which that Evaluation_Harness run
   completed, the count of golden questions scored in that run, and a scope field recording that the
   returned accuracy fields are scoped to that evaluation run rather than to any requested date range.
3. THE Metrics_API SHALL expose a latency endpoint returning the 50th, 95th and 99th percentile duration
   per pipeline stage and end to end for a requested date range.
4. THE Metrics_API SHALL expose an efficiency endpoint returning tokens per resolved question, LLM calls
   per resolved question, estimated cost per resolved question and the active model configuration.
5. THE Metrics_API SHALL expose a time-series endpoint returning the metric named by a metric identifier
   drawn from the metric-identifier enumeration documented in the generated OpenAPI schema, bucketed by
   hour or by day for a requested date range, with each bucket carrying its inclusive start instant in
   UTC, and THE Metrics_API SHALL keep every documented metric identifier unchanged once published and
   SHALL accept hour bucketing only for a requested date range spanning at most the configured maximum
   hourly span, whose default value is 31 days.
6. THE Metrics_API SHALL expose a question-category endpoint returning turn volume, accuracy and
   abstention rate per intent family, ordered so that the highest failure counts appear first.
7. THE Metrics_API SHALL expose an engagement endpoint returning mean turns per session, follow-up
   depth distribution, clarification rate and task-completion rate, where task completion is defined as
   a session containing at least one answered turn with no subsequent negative feedback.
8. THE Metrics_API SHALL expose a drill-down endpoint returning the turn list behind any reported figure,
   ordered by turn start instant descending and then by turn identifier ascending, returning at most the
   configured drill-down page size, whose default value is 50 turns and whose caller-selectable ceiling
   is 500 turns, and returning with every page the total count of turns behind the figure and the turn
   identifier of each listed Turn so that each listed Turn can be retrieved from the Trace_Service.
9. THE Metrics_API SHALL expose a model-comparison endpoint returning every evaluation run with its
   model configuration and scored metrics.
10. THE Metrics_API SHALL document every endpoint in the generated OpenAPI schema, and THE
    Finance_Assistant_Backend SHALL publish a dashboard contract document mapping each intended
    dashboard panel and analytics-page section to the endpoint and fields that supply it, and stating for
    each mapped panel whether the supplying fields are scoped to an evaluation run or to a requested date
    range.
11. THE Metrics_API SHALL return every response within 2 seconds for a database holding up to 100000
    turns.
12. THE Metrics_API SHALL interpret every requested date range as a half-open interval in UTC whose start
    bound is inclusive and whose end bound is exclusive, SHALL attribute each Turn to a requested date
    range by the UTC instant at which that Turn began, and SHALL attribute each session to a requested
    date range by the UTC instant at which the first Turn of that session began.
13. WHERE a metrics request omits the date range, THE Metrics_API SHALL apply the configured default
    metrics range, whose default value is the 7 whole UTC days ending at the most recent UTC midnight,
    and SHALL return the applied start bound and end bound in the response.
14. IF a metrics request supplies a date range whose end bound is not later than its start bound, a date
    range whose span exceeds the configured maximum metrics range whose default value is 366 days, a
    metric identifier absent from the documented metric-identifier enumeration, a bucket size other than
    hour or day, or an evaluation run identifier absent from the stored evaluation runs, THEN THE
    Metrics_API SHALL reject the request with an error naming the rejected parameter and SHALL return no
    metric fields.
15. THE Metrics_API SHALL return, alongside every ratio field, rate field, percentile field and mean
    field in every response, the count of records from which that field was computed.
16. IF the count of records from which a ratio field, rate field, percentile field or mean field would be
    computed is 0, THEN THE Metrics_API SHALL return that field as an explicit not-measured marker
    distinct from the value 0 and SHALL return every count field for the same requested date range as 0.
17. THE Metrics_API SHALL return the same value for one metric identifier and one requested date range
    across the overview endpoint, the time-series endpoint aggregated over its buckets, and the drill-down
    endpoint total count.

### Requirement 28: Voice input through Sarvam speech-to-text

*Capability A8.*

**User Story:** As a business user on the move, I want to ask my question by speaking, in English or
an Indic language, so that I can get a finance answer without typing.

#### Acceptance Criteria

1. WHEN a client submits an audio utterance to the voice endpoint, THE Speech_Transcriber SHALL
   transcribe the audio using the configured Sarvam speech-to-text model and return the transcript, the
   detected or requested language code, a transcription confidence score in the range 0.00 to 1.00 and
   the transcription duration.
2. THE Speech_Transcriber SHALL accept the audio formats declared in configuration, with the default
   list containing `wav`, `mp3` and `webm`.
3. THE Speech_Transcriber SHALL accept utterances of up to the configured maximum duration, whose
   default value is 60 seconds, and of up to the configured maximum upload size, whose default value is
   10 megabytes.
4. THE Voice_Service SHALL read the supported language code list from configuration so that provider
   language coverage changes without code changes.
5. WHERE the client supplies a language code contained in the configured supported language code list,
   THE Speech_Transcriber SHALL pass that language code to the provider; WHERE the client supplies no
   language code, THE Speech_Transcriber SHALL request automatic language detection.
6. WHEN a transcript is produced with a transcription confidence score at or above the configured voice
   confirmation threshold, THE Chat_API SHALL process the transcript through the identical pipeline used
   for typed questions, including schema linking, reviewer verification, groundedness verification,
   trace emission and confidence scoring, with the per-question wall-clock budget enforced by the
   Budget_Guard starting at transcript production.
7. THE Trace_Service SHALL record the transcription as a trace event carrying the language code, the
   audio duration, the transcription confidence score, the provider request duration and the provider
   attempt count.
8. IF the Speech_Transcriber returns a transcription failure, returns an empty transcript, or exhausts
   the configured maximum transcription attempt count whose default value is 2 attempts without
   returning a transcript within the configured transcription timeout whose default value is 15 seconds
   per attempt, THEN THE Chat_API SHALL return a response asking the user to repeat the question, SHALL
   record the failure, and SHALL leave session state unchanged.
9. WHEN a voice Turn completes, THE Chat_API SHALL return the transcript alongside the answer so the user
   can confirm what was heard.
10. IF a submitted audio utterance has a format outside the configured accepted audio format list, a
    duration above the configured maximum duration, a byte size above the configured maximum upload size,
    or a supplied language code outside the configured supported language code list, THEN THE
    Voice_Service SHALL reject the submission before invoking the Sarvam speech-to-text provider, SHALL
    return an error naming the configured limit or list the submission violated, and SHALL leave session
    state and Turn history unchanged.
11. WHERE the Sarvam speech-to-text response omits a confidence value, THE Speech_Transcriber SHALL
    record the configured default transcription confidence score, whose default value is 0.75, as the
    observed confidence.
12. IF the transcription confidence score is below the configured voice confirmation threshold, whose
    default value is 0.70, THEN THE Chat_API SHALL return the transcript together with a request that the
    user confirm or correct the transcript, SHALL hold the Turn in a pending-confirmation state, and SHALL
    start pipeline processing when the user submits a confirmation or a corrected question.
13. WHILE a Turn originates from a voice utterance, THE Confidence_Scorer SHALL treat the transcription
    confidence score as an upper bound on the confidence score of that Turn.
14. WHEN a transcript contains a numeral written in an Indic script or a scale word from the set thousand,
    lakh, crore, million and billion, THE Query_Planner SHALL normalise that numeral to an absolute
    numeric value before date-range extraction and amount extraction, and SHALL record the original text
    and the normalised value as a trace event.
15. WHEN the Speech_Transcriber returns a transcript or a transcription failure, THE Voice_Service SHALL
    delete the uploaded audio bytes after the configured audio retention period, whose default value is
    0 seconds.

### Requirement 29: Voice output through Sarvam text-to-speech

*Capability A8.*

**User Story:** As a business user, I want the answer read back to me in my language, so that I can
listen instead of reading.

#### Acceptance Criteria

1. WHEN a client requests spoken output for a completed Turn, THE Speech_Synthesizer SHALL synthesise
   the answer text using the configured Sarvam text-to-speech model and return the audio payload with
   its format and duration.
2. THE Speech_Synthesizer SHALL synthesise in the language code supplied by the client, defaulting to
   the language code of the Turn's question.
3. THE Speech_Synthesizer SHALL read the speaker, pitch and pace values from configuration.
4. WHEN the answer text of a Turn contains a monetary figure, THE Answer_Composer SHALL derive a spoken
   variant of the answer by applying Computation_Layer number formatting to each monetary figure of the
   written answer text, without issuing a model call, so that every numeric value in the spoken variant
   equals the corresponding numeric value in the written answer.
5. WHEN the Answer_Composer supplies a spoken variant, THE Groundedness_Checker SHALL verify the spoken
   variant against the executed result set using the same rules applied to the written answer, and SHALL
   record the spoken variant as grounded only when the multiset of numeric values recovered from the
   spoken variant equals the multiset of numeric values in the written answer of the same Turn.
6. THE Speech_Synthesizer SHALL synthesise text of up to the configured maximum character count, whose
   default value is 2000 characters, in a single provider request, SHALL split longer text at sentence
   boundaries into segments of at most the configured maximum character count with no monetary figure
   divided across two segments, SHALL assign each segment a 1-based ordinal index such that concatenating
   the segment texts in ascending index order reproduces the submitted text exactly, and SHALL return the
   segment audio payloads in ascending index order.
7. IF a Sarvam text-to-speech request for any segment of a Turn fails after the configured maximum
   attempt count, THEN THE Chat_API SHALL return the written answer of that Turn with a flag stating that
   audio is unavailable and a reason code naming the synthesis failure, and THE Chat_API SHALL leave the
   written answer and the breakdown table of that Turn unchanged.
8. WHEN the Speech_Synthesizer issues a Sarvam text-to-speech request, THE Trace_Service SHALL record the
   request as a trace event carrying the language code, the character count, the segment index, the total
   segment count, the synthesised text variant as either spoken variant or written answer text, the
   outcome as either success or failure, and the provider request duration.
9. IF the Groundedness_Checker records the spoken variant of a Turn as not grounded while the written
   answer of the same Turn is recorded as grounded, THEN THE Speech_Synthesizer SHALL synthesise the
   written answer text in place of the spoken variant, and THE Chat_API SHALL return a reason code naming
   rejection of the spoken variant.
10. IF the language code for spoken output is outside the configured set of supported Sarvam
    text-to-speech language codes, or differs from the language code of the text submitted for synthesis,
    THEN THE Chat_API SHALL return the written answer with a flag stating that audio is unavailable and a
    reason code naming the language code.
11. IF a Sarvam text-to-speech request for a segment does not return within the configured synthesis
    timeout, whose default value is 10 seconds, THEN THE Speech_Synthesizer SHALL abandon that request and
    SHALL issue at most the configured maximum attempt count, whose default value is 2 attempts for each
    segment, before reporting synthesis failure.
12. WHEN the Speech_Synthesizer issues Sarvam text-to-speech requests for a Turn, THE Budget_Guard SHALL
    apply the configured per-Turn synthesis time budget, whose default value is 30 seconds, to the sum of
    the provider request durations of every segment of that Turn, and SHALL account that sum separately
    from the per-question wall-clock budget for answer production.
13. WHEN a spoken output request repeats the turn identifier, language code, speaker, pitch and pace of a
    completed synthesis, THE Speech_Synthesizer SHALL return the retained audio payload of that completed
    synthesis without issuing a further provider request, for the configured audio cache retention
    period, whose default value is 3600 seconds.

### Requirement 30: Buddy surface for deciding what to ask

*Capability A8.*

**User Story:** As a non-technical business user, I want help figuring out what I can ask, so that I
get value from the assistant without knowing the data model.

#### Acceptance Criteria

1. WHILE the active dataset version is unchanged, WHEN a session is created, THE Buddy_Agent SHALL return
   the same ordered list of at least 5 starter questions derived from the Schema_KB, the Metric_Layer and
   the active dataset's date coverage, and SHALL return that list within the configured buddy suggestion
   latency budget, whose default value is 2000 milliseconds, measured at the Chat_API boundary.
2. THE Buddy_Agent SHALL generate every suggested question such that the question maps to exactly one
   Metric_Layer definition or to exactly one intent family the system supports, such that every entity
   name, dimension value and reconciliation status value the question references appears in the Schema_KB
   distinct sample values for the active dataset, such that every date and every period the question
   references falls within the active dataset's date coverage, and such that every metric name and
   dimension name the question displays is the business-language label recorded in the Metric_Layer or the
   Schema_KB rather than a table identifier or a column identifier.
3. WHEN a Turn completes with an answer, THE Buddy_Agent SHALL return at least 3 contextual next
   questions that drill into the same result, widen the date range, or compare against another period,
   and SHALL exclude every question already asked in the session and every question already offered by
   the Buddy_Agent in the session, comparing questions after trimming whitespace and after case folding.
4. WHEN a user asks what a business term or metric means, THE Buddy_Agent SHALL answer from the
   Metric_Layer descriptions and the Schema_KB descriptions and SHALL name the columns involved.
5. THE Buddy_Agent SHALL expose an endpoint listing the available metrics, the available dimensions, the
   allowed reconciliation status values and the dataset date coverage in business language.
6. WHEN the user asks a suggested question, THE Chat_API SHALL process it through the standard grounded
   pipeline.
7. WHERE voice is requested, THE Buddy_Agent SHALL support spoken interaction through the same
   Voice_Service used by the finance assistant.
8. THE Buddy_Agent SHALL derive every suggestion from the active dataset content so that suggestions
   change when the dataset changes.
9. WHEN the Buddy_Agent assembles a list of suggested questions, THE Buddy_Agent SHALL execute the mapped
   Metric_Layer template with the candidate question's resolved parameters through the Query_Executor for
   every candidate question mapping to a Metric_Layer definition, and SHALL offer only those candidate
   questions whose execution completes without error and returns at least 1 row.
10. IF fewer than 5 starter question candidates or fewer than 3 contextual next question candidates
    satisfy the execution check, THEN THE Buddy_Agent SHALL return only the candidate questions that
    satisfied the execution check and SHALL include a statement that the active dataset supports fewer
    suggested questions than the stated minimum.
11. WHEN a dataset version is activated, THE Buddy_Agent SHALL precompute and retain the validated starter
    question list for that dataset version, and SHALL serve session creation from that retained list while
    that dataset version is active.
12. IF the term in a term or metric explanation request matches no Metric_Layer definition name, no
    Metric_Layer description and no Schema_KB table or column description after trimming whitespace and
    after case folding, THEN THE Buddy_Agent SHALL return an abstention carrying the reason code
    `term_undefined` and SHALL return the metric list, the dimension list and the dataset date coverage
    described in criterion 5.
13. IF the Budget_Guard reports no remaining per-question allowance or no remaining per-session allowance
    at the time contextual next questions are due, THEN THE Buddy_Agent SHALL select contextual next
    questions from the Metric_Layer definitions matching the completed Turn's intent family without
    issuing a model call.

### Requirement 31: Insights buddy for conversational analytics

*Capability A7, A8.*

**User Story:** As a product owner, I want to ask about usage, accuracy, cost and trends
conversationally, so that I can explore the assistant's own analytics without reading a dashboard.

#### Acceptance Criteria

1. THE Insights_Buddy SHALL answer questions about session volume, turn volume, abstention rate,
   clarification rate, latency percentiles, token usage, cost and feedback for a requested period, and
   SHALL answer questions about execution accuracy, grounding rate, SQL validity rate, reviewer catch rate
   and reviewer false-rejection rate for the evaluation run identifier supplied in the question,
   defaulting to the most recent completed evaluation run.
2. THE Insights_Buddy SHALL obtain every analytics figure exclusively from Metrics_API endpoint responses,
   resolving each analytics question to one Metrics_API endpoint identifier with bound parameter values,
   and SHALL derive every stated total, difference, ratio and rounded value from those responses through
   the Computation_Layer.
3. THE Insights_Buddy SHALL return, alongside every analytics answer, the supporting breakdown table, the
   Metrics_API endpoint identifier and the bound parameter values that produced that table.
4. WHEN an analytics question requests a trend, THE Insights_Buddy SHALL return the bucketed series used
   to describe the trend.
5. THE Groundedness_Checker SHALL verify every analytics answer against the Metrics_API endpoint response
   that produced it using the same rules applied to finance answers.
6. THE Chat_API SHALL expose the Insights_Buddy as a surface distinct from the finance data assistant,
   with its own session type, so that finance conversation state and analytics conversation state remain
   separate, and THE Context_Resolver SHALL resolve each follow-up question in an Insights_Buddy session
   using only that session's conversation state, carrying forward the resolved period, the resolved metric
   name and the resolved bucket granularity.
7. IF an analytics question resolves to no Metrics_API endpoint, or requires a measurement the metrics
   tables do not hold, or requires a bucket granularity finer than hourly, THEN THE Insights_Buddy SHALL
   abstain, SHALL name the missing measurement or the unsupported granularity, and SHALL list at most 5
   supported measurements.
8. WHERE voice is requested, THE Insights_Buddy SHALL support spoken questions and spoken answers
   through the Voice_Service.
9. WHEN the Insights_Buddy resolves a question about session volume, turn volume, latency percentiles,
   token usage, cost or feedback, THE Insights_Buddy SHALL exclude every Turn belonging to an
   Insights_Buddy session from the reported figure, and SHALL report Insights_Buddy turn count and
   Insights_Buddy estimated cost as separately labelled figures.
10. WHEN an analytics answer states a figure scored by the Evaluation_Harness, THE Insights_Buddy SHALL
    state in the written answer and in the spoken variant the evaluation run identifier, the run
    completion date, the dataset version of that run, and that the figure was measured against the golden
    question set.
11. IF a Metrics_API endpoint response for a resolved analytics question contains zero records, THEN THE
    Insights_Buddy SHALL state that no records exist for the requested scope, SHALL omit every rate figure,
    percentage figure and percentile figure from the answer, and SHALL name the earliest and latest dates
    for which records exist.
12. THE Budget_Guard SHALL apply the per-question LLM call limit, the per-question token limit and the
    per-question wall-clock deadline to every Insights_Buddy Turn.

### Requirement 32: Sessions, persistence, configuration and runtime posture

*Capability A2, A3, A5, A7.*

**User Story:** As a developer running the prototype, I want one command to bring up a working stack
with predictable configuration, so that setup is never the reason a demo fails.

#### Acceptance Criteria

1. THE Chat_API SHALL support creating a session, listing sessions, reading a session with its turns,
   and deleting a session, and SHALL return listed sessions ordered by session creation time descending
   in pages whose size is the configured session page size, whose default value is 20 records and whose
   maximum accepted value is 100 records.
2. THE Finance_Assistant_Backend SHALL persist sessions, turns, messages, traces, computation records,
   result-set snapshots, feedback, failure cases, prompt versions, exemplars, evaluation runs and
   ingestion runs to PostgreSQL.
3. THE Finance_Assistant_Backend SHALL manage the database schema with Alembic migrations, and WHERE the
   deployment is the local Docker Compose stack, THE Finance_Assistant_Backend SHALL apply migrations,
   verify that the PostgreSQL vector extension is present in the active database, and verify that the
   applied Alembic revision equals the head revision, before binding the HTTP listener.
4. THE Finance_Assistant_Backend SHALL read every setting through a typed settings object, and WHERE an
   environment variable is blank, THE settings object SHALL apply the documented default.
5. THE Finance_Assistant_Backend SHALL start the full stack, comprising PostgreSQL with the vector
   extension, the API and the seeded dataset, through a single documented Docker Compose command, and
   SHALL report the ready state on the health endpoint within the configured cold-start budget, whose
   default value is 180 seconds, measured from container start on the demonstration machine and excluding
   container image download time and excluding any separate dataset seeding job.
6. THE Finance_Assistant_Backend SHALL expose a health endpoint reporting the database connection state,
   the active dataset version, the Schema_KB version, the resolved model configuration as provider
   identifiers and model identifiers, the voice provider reachability read from a cached reachability
   probe whose result is refreshed at most once per configured voice reachability cache period whose
   default value is 300 seconds, and a readiness state that reports ready only when the database
   connection succeeds, the applied Alembic revision equals the head revision, the PostgreSQL vector
   extension is present and the active dataset version is populated, and THE Finance_Assistant_Backend
   SHALL answer a health request within 500 milliseconds.
7. THE Finance_Assistant_Backend SHALL bind to the loopback interface by default and SHALL require the
   configured shared-secret header on every non-health endpoint when that secret is set.
8. IF the shared-secret header is unset in configuration, THEN THE Finance_Assistant_Backend SHALL log a
   startup warning stating that the API is unauthenticated.
9. WHERE the deployment runs more than one worker process, THE Finance_Assistant_Backend SHALL keep
   per-turn state in PostgreSQL rather than in process memory.
10. THE Finance_Assistant_Backend SHALL record every provider credential, database credential and API
    secret in environment configuration only, and SHALL replace every configured secret value with a fixed
    mask token in log records, error responses and health endpoint payloads.
11. WHEN a session deletion request is accepted, THE Chat_API SHALL delete the turns, the messages, the
    trace events, the result-set snapshots and the feedback records belonging to that session within 5
    seconds of accepting the request, irrespective of whether the configured trace retention period for
    those trace events has elapsed.
12. IF a failure case in the Failure_Store references a Turn of a session that is being deleted, THEN THE
    Finance_Assistant_Backend SHALL retain that failure case together with a copy of the referenced trace
    events, executed SQL and result-set snapshot, SHALL record that retained failure case as referencing a
    deleted session, and SHALL complete the deletion of the remaining records of that session.
13. IF a session identifier supplied in a session read request, a session delete request or a
    question-posting request matches no stored session, THEN THE Chat_API SHALL reject the request with an
    error stating that the session identifier is unknown, and SHALL leave stored sessions, turns and
    messages unchanged.
14. IF an Alembic migration fails, or the database connection fails, or the PostgreSQL vector extension is
    absent from the active database, or the applied Alembic revision differs from the head revision during
    startup, THEN THE Finance_Assistant_Backend SHALL leave the database at the last successfully applied
    revision, SHALL terminate with a failure exit status without binding the HTTP listener, and SHALL emit
    a log record naming the failed startup step.
15. IF the configured shared secret is set and a request to a non-health endpoint carries no shared-secret
    header or carries a header value that does not equal the configured secret, THEN THE
    Finance_Assistant_Backend SHALL reject the request before creating a Turn, SHALL return an error
    stating a missing or invalid shared secret, and SHALL leave stored sessions and turns unchanged.
16. THE Finance_Assistant_Backend SHALL reject a request body exceeding the configured maximum request body
    size, whose default value is 12 megabytes, before reading that body into memory.

### Requirement 33: Submission artefacts

*PDF section 6 submission requirements.*

**User Story:** As a hackathon participant, I want every required submission artefact produced from the
working system, so that the presentation and README match what the judges run.

#### Acceptance Criteria

1. THE Finance_Assistant_Backend SHALL provide a README containing prerequisites, the single-command
   setup, the environment variable reference, the dataset swap procedure, the provider swap procedure
   and the evaluation command.
2. THE Finance_Assistant_Backend SHALL provide an architecture diagram rendered by one documented command
   from a text diagram source file held in version control, showing the ingestion path, the Schema_KB, the
   agent pipeline, the reviewer layer, the execution path, the trace stream, the metrics store and the
   voice path.
3. THE Finance_Assistant_Backend SHALL provide a sample-questions document containing at least 20
   questions with the responses the system produced, comprising at least 15 questions that returned an
   answer with the executed SQL and the confidence band, at least 3 questions that returned an abstention
   with the reason code attached by the Abstention_Controller, and at least 2 questions that returned a
   clarifying question with the self-contained question produced by the Context_Resolver after the
   clarification was answered.
4. THE Finance_Assistant_Backend SHALL provide a presentation-deck source document held in version control
   containing one section for each of the problem, the approach, the model-choice rationale, the grounding
   guarantees and the demo flow, where every score stated in the model-choice rationale section is copied
   from a single Evaluation_Harness run identified in that section by run identifier.
5. WHEN the documented sample-questions regeneration command is invoked, THE Evaluation_Harness SHALL
   produce the sample-questions document content from an actual run against the active dataset and SHALL
   record in the sample-questions document the Dataset_Manifest version, the code revision, the model
   identifier resolved by the Model_Router for each role, and the run completion timestamp.
6. THE Finance_Assistant_Backend SHALL provide the model-choice note required by Requirement 26 as a
   section of the README and of the deck.
7. THE Finance_Assistant_Backend SHALL provide a demo-flow document containing at least 5 and at most 12
   ordered steps, where each step states the question text and the expected outcome class of answer,
   clarifying question or abstention, and where each step whose expected outcome class is answer
   additionally states the expected figure, against the dataset produced by the Seed_Data_Generator.
8. WHEN the submission-artefact verification command is invoked against the dataset produced by the
   Seed_Data_Generator, THE Evaluation_Harness SHALL execute every step of the demo-flow document in the
   documented order and, for each step whose observed outcome class or observed figure differs from the
   value stated in the demo-flow document, SHALL exit with a non-zero status and report an error naming
   that step.
9. WHILE the submission-artefact verification command is running, IF the Dataset_Manifest version or the
   code revision recorded in the sample-questions document differs from the active Dataset_Manifest
   version or the current code revision, THEN THE Evaluation_Harness SHALL exit with a non-zero status and
   report an error naming each stale recorded value.
10. THE Finance_Assistant_Backend SHALL provide a README section stating the ordered Chat_API calls that
    reproduce one answered question, one clarifying question and one abstention against the dataset
    produced by the Seed_Data_Generator after the single-command setup completes.


---

## Correctness Properties

Properties intended for property-based testing, with the property type and the requirement each
property protects. Properties marked *example* or *integration* are deliberately excluded from
property-based testing because their behaviour does not vary meaningfully with input, or because they
exercise an external service where 100 iterations would add cost without adding coverage.

| # | Property | Type | Test style | Requirements |
|---|----------|------|-----------|--------------|
| P1 | Every candidate accepted by the SQL_Validator — whether produced by the SQL_Generator or bound by the Query_Planner from a Metric_Layer template — parses to an AST whose root is a SELECT or WITH-SELECT, contains no data-definition, data-modification, transaction-control or privilege node, invokes no function outside the configured function allowlist, and contains no row-locking or result-target clause | Invariant | Property | 12, 4 |
| P2 | Every table and column referenced by an accepted candidate, including candidates bound from a Metric_Layer template, exists in the Schema_KB of the active dataset version | Invariant | Property | 12, 3, 4 |
| P3 | Every numeric literal in a released answer, spoken variant included, appears in the executed result set or in a computation record | Invariant | Property | 15, 17, 29 |
| P4 | A reported aggregate equals the aggregate computed by an independent reference implementation over the same executed rows | Model-based | Property | 15 |
| P5 | For generated unanswerable or ambiguous questions, the released response contains no monetary figure and carries an abstention or clarification reason code | Invariant | Property | 18 |
| P6 | Trace events streamed for a Turn carry contiguous sequence numbers from 1 to N excluding keepalive frames, non-decreasing timestamps, and exactly one terminal event; the persisted event list equals the streamed list for every Turn whose terminal event was streamed. Turns terminated by the abandonment window are excluded, because their terminal event is persisted without being streamed | Invariant | Property | 21, 22 |
| P7 | For any manifest variant that renames columns, reorders columns or changes file format while preserving data, golden-question answers are unchanged | Metamorphic | Property | 5, 6, 7 |
| P8 | For any configured provider, including stub providers that return valid role outputs, response schemas and the grounding invariant P3 hold | Metamorphic | Property | 9, 17 |
| P9 | Repeating an identical follow-up question against unchanged conversation state yields an identical resolved question and identical executed SQL | Idempotence | Property | 2 |
| P10 | Parsing an exported CSV or XLSX file reproduces the breakdown table it was generated from, including column order, row order and decimal precision, after removing the apostrophe prefix applied to formula-injection candidates; XLSX is compared by parsed cell type and value rather than byte-wise | Round trip | Property | 23 |
| P11 | Serialising and re-loading a Dataset_Manifest reproduces an equivalent manifest object | Round trip | Property | 5 |
| P12 | Ingesting the same source twice produces identical row counts and identical Schema_KB content, with only the version identifier advancing | Idempotence | Property | 5, 6, 7 |
| P13 | A resolved date range always satisfies start ≤ end, and either lies within the dataset coverage or produces an abstention | Invariant | Property | 1, 18 |
| P14 | The confidence score lies in the closed interval 0 to 1, the weights of the signals applicable to a Turn are rescaled to sum to 1, and raising any single normalised signal value never lowers the score | Invariant, metamorphic | Property | 19 |
| P15 | Executed queries never return more rows than the configured execution cap, and the previewed rows are a prefix of the complete result set | Invariant | Property | 13, 15 |
| P16 | Anomaly flags are unchanged under row reordering and under multiplying every amount by a positive constant, for both the modified z-score branch and the zero-dispersion branch; scaling every amount by a positive constant also scales the zero-dispersion absolute floor | Confluence, metamorphic | Property | 20 |
| P17 | Malformed SQL, malformed manifests, malformed audio payloads and missing required columns produce typed errors and never a numeric answer | Error conditions | Property | 6, 12, 18, 28 |
| P18 | The sum of breakdown rows equals the reported total at the recorded precision, with no floating-point representation used for money | Invariant | Property | 15 |
| P19 | No configured secret value appears in any streamed or persisted trace event | Invariant | Property | 21, 32 |
| P20 | No artefact version becomes active without both an approval record and a regression run scoring at or above the active version | Invariant | Property | 25 |
| P21 | Sarvam transcription and synthesis succeed for representative audio in English and one Indic language | — | Integration, 2 to 3 examples | 28, 29 |
| P22 | The documented Docker Compose command brings up a stack whose health endpoint reports every dependency ready | — | Integration, single run | 32 |
| P23 | Metrics endpoints return within the stated bound for a database seeded with 100000 turns | — | Load test | 27 |
| P24 | Every Metrics_API endpoint named in the dashboard contract appears in the generated OpenAPI schema | — | Example | 27 |
| P25 | Every figure stated in an Insights_Buddy answer appears in the Metrics_API response recorded for that Turn, and no Insights_Buddy answer is produced from generated SQL | Invariant | Property | 31, 12, 13 |
| P26 | For one metric identifier and one requested date range, the overview endpoint value equals the sum over the time-series buckets and equals the drill-down total count | Metamorphic | Property | 27 |
| P27 | No artefact version holding status `candidate` is ever read by a question-answering Turn | Invariant | Property | 25 |
| P28 | Every Buddy_Agent suggested question, when submitted through the Chat_API against the same dataset version, returns an answer rather than an abstention | Invariant | Property | 30, 18 |
| P29 | The count of Query_Executor executions per Turn never exceeds the configured maximum executions per Turn, counting final executions, dry-run samples, plan requests, existence queries and anomaly history queries | Invariant | Property | 13, 14, 20 |
| P30 | A Turn resolved through the Metric_Layer path issues no more LLM calls than the configured Metric_Layer call limit | Invariant | Property | 10 |
| P31 | Every abstention carries exactly one reason code drawn from the Requirement 18 enumeration, and every terminating pipeline condition maps to a reason code in that enumeration | Invariant | Property | 18 |
| P32 | A dataset swap followed by a provider swap leaves every Chat_API and Metrics_API response schema unchanged | Metamorphic | Property | 5, 9, 27 |

---

## Out of Scope

Stated explicitly, following the problem statement:

- Live integration with real banking systems or ERP systems.
- Multi-tenant security, user roles and production-grade authentication. The prototype is
  single-tenant and, unless the shared-secret header is configured, unauthenticated; it binds to
  loopback by default for that reason.
- Support for every possible financial question. Coverage is deliberately scoped to spend, vendor
  payouts and reconciliation, plus the analytics surface over the system's own metrics.
- Any user interface. No chat UI, dashboard UI or analytics page is implemented in this spec; every
  figure those surfaces need is exposed through the APIs specified above, and the dashboard contract
  document records the mapping so a UI can be built against a finished API.
- Model weight training or fine-tuning. Improvement is limited to prompts, exemplars, schema
  descriptions, metric templates and configuration.

---

## Problem Statement Coverage

| Problem statement item | Requirements |
|------------------------|--------------|
| Must: natural language query handling (intent, filters, date ranges) | 1, 2 |
| Must: grounded retrieval | 3, 4, 11, 13, 17 |
| Must: accurate computation in the data layer | 4, 15 |
| Must: verifiable answers with records or breakdown table | 15, 16, 23 |
| Must: hallucination guardrails, unknown and ambiguous handling | 12, 13, 14, 17, 18 |
| Must: lightweight model constraint (scored) | 9, 10, 26 |
| Must: multi-turn conversation | 1, 2 |
| Must: explainability | 15, 16, 21, 22 |
| Good to have: CSV and Excel export | 23 |
| Bonus: confidence signalling | 19 |
| Bonus: model-choice note with measured accuracy | 10, 26 |
| Bonus: simple anomaly callouts | 20 |
| Submission: prototype, diagram, README, sample questions, deck | 32, 33 |
| User-requested: swappable dataset with dual ingestion paths | 5, 6, 7, 8 |
| User-requested: swappable model provider layer | 9, 10 |
| User-requested: live trace streaming for the UI | 21, 22 |
| User-requested: self-improvement pipeline | 24, 25 |
| User-requested: metrics and analytics APIs for the dashboard | 27 |
| User-requested: voice input and output | 28, 29 |
| User-requested: what-to-ask buddy | 30 |
| User-requested: conversational analytics buddy | 31 |
| User-requested: evaluation harness and golden question set | 26, 18, 19 |

---

## Assumptions

1. **The dataset is not yet delivered.** Development proceeds against the synthetic seed dataset
   specified in Requirement 8, and the real dataset is adopted by replacing the Dataset_Manifest and
   re-running ingestion. The dataset contract document is the interface both sides must satisfy.
2. **The delivery mode is unknown.** Both ingestion paths are built, because the organisers may
   publish an API or ship files.
3. **The lightweight model constraint is unpinned.** The problem statement points to "Section 8,
   Assumptions and Constraints" for the model-efficiency rule, but the supplied document ends at
   Section 6, so Sections 7 and 8 are missing. This spec therefore assumes a small model tier of at
   most 8 billion parameters for open-weight models, or a provider-declared small, mini or flash tier
   for hosted models, with a default budget of 6 LLM calls and 12000 tokens per question. Every one of
   those values is configuration, so the constraint can be re-pinned when the missing section arrives.
4. **The provider and credits are unknown.** The Model_Router supports six provider families and a
   locally hosted model so that whichever credits arrive can be used, and so that the demo survives
   with no network.
5. **Relative dates are resolved against the dataset, not the wall clock.** A historical dataset makes
   "last month" ambiguous otherwise; the reference date defaults to the latest transaction date and is
   configurable.
6. **Amounts are single-currency** as published by the dataset; the currency code is read from the
   dataset and stated in answers. Multi-currency conversion is not specified.
7. **The demonstration machine** is as defined in the Glossary; every latency budget in this document
   refers to that environment.
8. **Single-process deployment** is assumed for the prototype, matching the reference project's
   constraint; Requirement 32 keeps the door open by requiring per-turn state in PostgreSQL if more
   than one worker runs.
9. **Sarvam credits are available**, so voice is in scope as a first-class capability rather than an
   optional extra.
10. **The Insights_Buddy is restricted to Metrics_API responses** rather than generating SQL over the
    metrics tables, because the SQL_Validator is scoped to the finance Schema_KB and the Query_Executor
    role holds SELECT on the dataset schema only. Extending the guardrails to a second schema is a
    deliberate future decision, not an oversight.
11. **Improvement means new versions of artefacts, not new weights.** Improvement produces new versions
    of prompts, exemplars, schema descriptions and metric templates under human approval and a passing
    regression run; no model weights are trained.
12. **Every latency, token and cost figure stated in this document is a budget to be measured, not a
    measured result.** Measured figures come from Evaluation_Harness runs.
13. **Relative-date resolution, entity fuzzy matching thresholds and confidence signal weights are
    initial values requiring calibration** once the organisers' dataset replaces the seed dataset. Each
    is configuration, so calibration does not reopen a requirement.

---

## Open Questions

1. **Is a dashboard or analytics UI in scope for the submission?** The instruction is backend-only, yet
   a metrics dashboard and an analytics page are also requested. This spec keeps UI out of scope and
   makes every figure available through the Metrics_API plus a dashboard contract document. Confirm
   whether a minimal UI should be added to a later spec, since user experience carries 10% of the score
   and presentation another 5%.
2. **What do Sections 7 and 8 of the problem statement actually say?** The model-efficiency rule, and
   any stated assumptions and constraints, are missing from the supplied document. Obtaining them may
   change the pinned model tier and the token and call budgets.
3. **How will model efficiency be measured by the judges** — tokens, parameter count, cost, latency, or
   a published rubric? The organisers promised a guidance note on this; the metrics required here cover
   all four, but the headline figure to optimise is unconfirmed.
4. **Will the organisers' dataset arrive as an API or as files, and with what authentication?** Both
   paths are specified, but endpoint shapes, pagination style and auth header cannot be finalised until
   delivery.
5. **Which reconciliation status values and category taxonomy does the real dataset use?** The
   Metric_Layer templates and the golden question set encode the seed dataset's values until then.
6. **Which languages should the voice surface demo in?** Sarvam covers eleven; confirming the two or
   three used in the demo determines which language fixtures the integration tests carry.
7. **Is there a target for how many golden questions the judges will probe, or a published sample
   question set?** A published set would be adopted directly into the golden question set.
8. **Should groundedness matching be keyed to the computation record rather than to the whole result
   set?** A numeral in an answer can still coincidentally match an unrelated value in the result set (a
   row identifier, a quantity column) and pass groundedness verification. Closing this needs the
   computation record identifier cited under Requirement 16 to become the match key rather than free
   matching against every value in the result set. Confirm whether to tighten this before the demo.
9. **Should the golden question set carry a labelled improvement/validation split?** Requirement 25
   blocks exemplars whose question text exactly matches a golden question, but a paraphrase mined by the
   Improvement_Pipeline would pass undetected and inflate execution accuracy.
10. **Does the Sarvam speech-to-text response carry a per-utterance confidence value?** Requirement 28
    depends on one and falls back to a configured default of 0.75 when it is absent, which makes the
    voice confirmation threshold inert if the provider never reports confidence.
11. **Does the submission need a minimal chat UI?** The PDF asks for a working prototype comprising a
    chat interface plus backend, while this spec is backend-only, and Requirement 33 satisfies that
    wording only through documented Chat_API calls.
12. **Should the Metric_Layer path fall back to generated SQL when a bound template fails at
    execution?** Requirement 4 currently abstains instead, trading recall for determinism.
13. **Is the reviewer independence constraint of Requirement 14 affordable?** Requiring the reviewer role
    to differ from the sql_generator role in provider, model or prompt version may exceed the
    per-question budget on a single small local model.
