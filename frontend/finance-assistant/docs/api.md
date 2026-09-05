# TBX API Contract — Frontend Reference

> **STATUS: CONTRACT-FIRST. THE BACKEND DOES NOT EXIST YET.**
>
> This document is the agreed shape to mock against. No endpoint here has been implemented. Nothing
> here is a description of running software — it is a commitment about what the running software will
> expose.
>
> - **Build against mocks using these shapes.** When the backend lands it will match, or this document
>   changes first and you are told.
> - **Any change to a path, field name, type or status code will be reflected here.** This file is the
>   single source of truth for the wire contract. If code and this document disagree, that is a bug in
>   one of them, not a reason to guess.
> - **Derived from** `.kiro/specs/finance-assistant-nl2sql/design.md` §4.3 (Pydantic contracts) and
>   §4.4 (API surface, incl. the dashboard contract table). The 21 abstention reason codes come from
>   `requirements.md` Requirement 18.4; confidence band boundaries from the Configuration Inventory.
> - **Anything design.md leaves unspecified is listed in [Open / not yet pinned](#10-open--not-yet-pinned)**
>   rather than invented here. Check that section before assuming a shape.

---

## 1. What this API does

You send a plain-language finance question. You get back an answer, the SQL that produced it, every
number in the answer tied to a computation record, a confidence score with its breakdown, and a live
stage-by-stage trace of how the answer was produced.

The trace and the number-provenance are the product. Treat them as primary UI, not debug output.

---

## 2. Conventions

| Convention | Rule |
|---|---|
| Base path | `/api` for everything except `GET /health` |
| Timestamps | UTC, ISO-8601, always. No local times, no offsets other than `Z`. |
| **Monetary values** | **JSON strings, never JSON numbers.** See below. |
| Non-monetary numbers | Real JSON numbers: `confidence_score`, `row_count`, `duration_ms`, `sequence`, counts, z-scores. |
| Dates | `YYYY-MM-DD` strings. Date ranges are inclusive tuples `[start, end]` unless a field says half-open. |
| Metrics date filters | `?start=&end=` is a **half-open** UTC interval; the response echoes the applied bounds. |
| Auth | Optional `X-Internal-Token` header — see below. |
| IDs | `session_id`, `turn_id` are UUID strings. `ComputationRecord.id` is a short string (`"c1"`). |

### Monetary values are strings. Do not parse them into `number`.

```json
{ "label": "Total vendor payouts", "value": "4823150.00", "currency": "INR" }
```

Every monetary value crosses the wire as a decimal string because the backend computes money in exact
decimal arithmetic end to end and **JSON numbers are IEEE-754 doubles that silently lose precision**.
`4823150.15` survives a round trip; a 12-digit paisa-precise figure may not. If you do
`Number(value)` you have reintroduced the bug the entire computation layer exists to prevent.

Practical rules for the frontend:

- Keep monetary values as `string` in your models. Type them `string`, not `number | string`.
- Format for display with a decimal-safe library (`decimal.js`, `big.js`, `Intl.NumberFormat` on a
  string-safe path) — never via float arithmetic.
- Do **not** sum monetary strings client-side to produce a total. The backend already returns the
  total as its own computation record, and it is guaranteed to equal the sum of the breakdown rows at
  the recorded precision. If you compute your own total you will eventually disagree with the
  backend by a paisa and the answer will look wrong.
- Breakdown preview rows are untyped maps (`Record<string, unknown>`). Use the matching
  `BreakdownColumn.value_type` to decide how to render each cell; monetary cells are strings there
  too.

### `X-Internal-Token`

The backend ships with **no user authentication** (out of scope — see
[Open / not yet pinned](#10-open--not-yet-pinned)). There is one optional shared secret:

- If the backend has `internal_api_token` configured, **every endpoint except `GET /health`**
  requires the header `X-Internal-Token: <secret>`.
- If it is not configured, the header is ignored and all endpoints are open.
- Rejection happens before a turn is created, so a rejected request consumes no budget, creates no
  session state and does not appear in metrics.
- Send it if you have it; make it a single configurable header in your HTTP client so switching
  environments is one change.

The rejection status code is not pinned in design.md — see
[Open / not yet pinned](#10-open--not-yet-pinned).

---

## 3. Recommended request sequence for a chat turn

This ordering is not obvious and it matters. A turn takes seconds, so the answer arrives on a
different channel from the trace.

```
1. POST /api/sessions                          -> { session_id, starter_questions[] }
2. POST /api/sessions/{sid}/turns              -> returns turn_id immediately; body completes later
3. GET  /api/turns/{tid}/trace/stream          -> open as soon as you have turn_id; render live
4. (stream ends with the terminal event)
5. consume the TurnResponse body from step 2   -> render the answer
```

**The backend guarantees the terminal trace event is emitted before the HTTP response body is
written.** So a client that opens the stream before reading the body never shows the answer before the
trace that justifies it. That guarantee is only useful if you follow this order — if you await the
response body first and then fetch the trace, you have thrown away the live-thinking UX and will show
an answer with no visible justification.

```ts
// Annotated. Illustrative only — no backend exists yet.
async function askQuestion(sessionId: string, question: string) {
  // (2) Fire the turn. Do NOT await the body yet — you need the turn_id first,
  //     and the body will not settle until the pipeline finishes.
  const turnPromise = fetch(`/api/sessions/${sessionId}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ question }),
  });

  // The turn_id is available in the initial response of POST /turns.
  // See "Open / not yet pinned" — how the id is surfaced ahead of the full
  // body is not pinned in design.md. Mock it as an early header or a
  // first-chunk field and keep this seam behind one function.
  const turnId = await resolveTurnId(turnPromise);

  // (3) Open the trace stream. Late subscribers get the committed prefix
  //     replayed in sequence order before live events, so opening a beat
  //     late is safe and reconnect is safe.
  const es = new EventSource(`/api/turns/${turnId}/trace/stream`);
  es.addEventListener("trace", (e) => {
    const ev: TraceEvent = JSON.parse((e as MessageEvent).data);
    renderStage(ev);                     // grey out ev.status === "skipped"
    if (ev.stage === "completion") es.close();   // (4) terminal event
  });
  es.addEventListener("keepalive", () => {
    /* transport-only. NOT a trace event. Carries no `sequence`.
       Do not count it, do not treat the gap as a lost event. */
  });

  // (5) Now consume the answer. The terminal trace event has already been
  //     emitted, so the trace UI is complete before the answer appears.
  const res = await turnPromise;
  const turn: TurnResponse = await res.json();
  renderOutcome(turn);                   // switch on turn.outcome
}
```

Two clients may subscribe to the same turn concurrently; each holds its own cursor and each sees the
full `1..N` sequence.

---

## 4. Endpoint reference

Grouped exactly as design.md §4.4 groups them.

### 4.1 Chat

| Method | Path | Params | Request body | Response | Status codes |
|---|---|---|---|---|---|
| `POST` | `/api/sessions` | — | `{ surface: "finance" \| "insights" }` | `SessionCreated` | 200 |
| `GET` | `/api/sessions` | `?page_size=20&cursor=` | — | `Page<SessionSummary>`, desc by `created_at` | 200 |
| `GET` | `/api/sessions/{sid}` | path `sid` | — | `SessionDetail` | 200, 404 |
| `DELETE` | `/api/sessions/{sid}` | path `sid` | — | `{ deleted: true, retained_failure_cases: number }` | **202** |
| `POST` | `/api/sessions/{sid}/turns` | path `sid` | `TurnRequest` | `TurnResponse` | 200, **400** (question length, before a turn is created) |
| `GET` | `/api/turns/{tid}` | path `tid` | — | `TurnResponse`, replayed from persistence | 200, 404 |
| `GET` | `/api/turns/{tid}/explanation` | path `tid` | — | `ExplanationPayload` | 200, 404 |
| `POST` | `/api/turns/{tid}/feedback` | path `tid` | `{ rating: "positive" \| "negative", text?: string }` (`text` ≤ 2000 chars) | empty | **204** |
| `POST` | `/api/sessions/{sid}/clarifications` | path `sid` | `{ answer: string }` | `TurnResponse` | 200 |

Notes:

- `GET /api/turns/{tid}` replays the same `TurnResponse` from persistence — use it for deep links and
  session history rendering, not just for retries.
- `POST /clarifications` answers a pending clarification and returns a **new full `TurnResponse`**.
  It is not a patch on the previous turn.
- `DELETE /sessions/{sid}` returns 202 and reports how many failure cases were retained — failure
  cases outlive the session they came from by design, so a deleted session can still leave records
  behind. Surface that number if your UI promises deletion.

### 4.2 Voice

| Method | Path | Request | Response | Status codes |
|---|---|---|---|---|
| `POST` | `/api/sessions/{sid}/turns:voice` | `multipart/form-data`: `audio=<file>`, `language_code?`, `detailed?` | `TurnResponse` (with `transcript`) **or** `PendingConfirmation` | 200, 400 (malformed/oversized audio, over-duration) |
| `POST` | `/api/turns/{tid}/confirm-transcript` | `{ confirmed: boolean, corrected_text?: string }` | `TurnResponse` | 200 |
| `POST` | `/api/turns/{tid}/speech` | `{ language_code?, speaker?, pace? }` | `SpeechResponse` | 200 |
| `GET` | `/api/voice/languages` | — | `{ stt_languages: string[], tts_languages: string[], modes: string[] }` | 200 |

Notes for the FE:

- `POST :voice` returns **one of two shapes**. Discriminate before rendering: if transcription
  confidence is at or below the confirmation threshold you get `PendingConfirmation` and must show a
  "did you mean…?" step, then call `confirm-transcript`. Otherwise you get a normal `TurnResponse`.
- Audio bytes are discarded as soon as the transcript or the failure is recorded. There is no
  playback-the-question-back endpoint.
- Practical limits the UI must enforce client-side to avoid a wasted round trip: **≤ 10 MB and
  ≤ 30 seconds** of audio. The 30 s cap is a shipped provider constraint, not a typo for 60 s.
- Request body over ~12 MB is refused before it is buffered — a large upload fails fast, it does not
  hang.
- `POST /speech` returns **base64 audio in segments**, not a binary body. Long answers arrive as
  multiple segments you concatenate or play in order. It may also return
  `audio_unavailable: true` with a `reason_code` — in that case show the written answer and a
  "voice unavailable" affordance. A synthesis failure never changes the answer text.

### 4.3 Trace

| Method | Path | Shape | Notes |
|---|---|---|---|
| `GET` | `/api/turns/{tid}/trace/stream` | `text/event-stream` | Frames named `event: trace` carry a `TraceEvent`; frames named `event: keepalive` carry no `sequence` |
| `WS` | `/api/turns/{tid}/trace/ws` | WebSocket | Same event objects as JSON text frames |
| `GET` | `/api/turns/{tid}/trace` | `TraceList` | Persisted trace; equals the streamed list field-for-field |
| `GET` | `/api/sessions/{sid}/traces` | `Page<TraceSummary>` | Asc by `(created_at, turn_id)`, continuation token |

Both live transports carry **identical event objects**. Pick SSE unless you need to send anything
upstream; the WebSocket exists for clients that prefer it, not because it carries more.

Full semantics in [§6 The trace event contract](#6-the-trace-event-contract).

### 4.4 Export

| Method | Path | Params | Response |
|---|---|---|---|
| `GET` | `/api/turns/{tid}/export` | `?format=csv\|xlsx` | Streaming file body, `Content-Disposition: attachment` |

**Three distinguishable failures. The UI must tell them apart — they need different copy.**

| Status | Meaning | Suggested UI |
|---|---|---|
| **409** | The turn abstained — it never had rows to export | Disable/hide the export button for abstained turns; if clicked, "there is no data to export for this answer" |
| **410** | The result snapshot expired (retention default 30 days) | "This result is no longer available to download. Re-run the question." — offer to re-ask |
| **400** | Request rejected: unknown `format`, the turn is incomplete, or the snapshot is oversized | "Export unavailable" + retry-later for incomplete; for oversized, tell the user to narrow the question |

Conflating 409 and 410 is the mistake to avoid: "never had rows" and "no longer has rows" need
different user actions.

### 4.5 Metrics and analytics

Every endpoint accepts `?start=&end=` (half-open UTC) and returns the applied bounds. Every ratio,
rate, percentile and mean is wrapped as `{ value, measured_from }` — see
[§9](#9-dashboard-contract).

| Method | Path | Extra params | Response |
|---|---|---|---|
| `GET` | `/api/metrics/overview` | — | `OverviewMetrics` |
| `GET` | `/api/metrics/accuracy` | — | `AccuracyMetrics` — **scope is an evaluation run, not your date range** |
| `GET` | `/api/metrics/latency` | — | `LatencyMetrics` |
| `GET` | `/api/metrics/efficiency` | — | `EfficiencyMetrics` |
| `GET` | `/api/metrics/timeseries` | `?metric_id=&bucket=hour\|day` | `TimeSeries` |
| `GET` | `/api/metrics/question-categories` | — | `QuestionCategoryRow[]`, desc by `failure_count` |
| `GET` | `/api/metrics/engagement` | — | `EngagementMetrics` |
| `GET` | `/api/metrics/drilldown` | `?metric_id=&bucket_start=&page_size=50` | `Page<TurnRef>` with `total_count` |
| `GET` | `/api/metrics/model-comparison` | — | `ModelComparisonRow[]` |
| `GET` | `/api/metrics/failures` | `?status=&source=&intent_family=&start=&end=` | `Page<FailureCase>` |
| `GET` | `/api/metrics/metric-ids` | — | `MetricIdDescriptor[]` — the published enumeration |

Status codes: 200; **400** on an invalid metrics request (unknown `metric_id`, unsupported `bucket`).
Fetch `/metrics/metric-ids` at startup rather than hardcoding the list — it tells you which buckets
each metric supports.

### 4.6 Buddy and insights

| Method | Path | Params / body | Response |
|---|---|---|---|
| `GET` | `/api/buddy/starters` | `?session_id=` | `{ questions: string[], below_minimum?: boolean, note?: string }` |
| `GET` | `/api/buddy/next-questions` | `?turn_id=` | `{ questions: string[], below_minimum?: boolean }` |
| `GET` | `/api/buddy/catalogue` | — | `BuddyCatalogue` |
| `POST` | `/api/buddy/explain-term` | `{ term: string }` | `TermExplanation`, **or** an abstention with reason `term_undefined` plus the catalogue |
| `POST` | `/api/sessions/{sid}/turns` | `TurnRequest` on an `insights` session | `TurnResponse` with `metrics_source` instead of `executed_sql` |

Notes:

- **Every suggested question is guaranteed answerable** against the active dataset. Chips are safe to
  render as one-tap actions — they will not produce an abstention.
- `below_minimum: true` means fewer suggestions than the configured minimum were available. Render
  what you got; do not pad it.
- Analytics conversations reuse the chat endpoint. The **session's `surface` discriminates**, so
  create the session with `surface: "insights"` and then post turns normally. Insights and finance
  conversation state are kept separate.
- An insights `TurnResponse` has **no `executed_sql`** — there is no SQL. It carries
  `metrics_source: { endpoint_id, bound_parameters }`. Your "verify" drawer needs a second rendering
  mode for this.
- `explain-term` returns one of two shapes. Handle the `term_undefined` abstention by showing the
  returned catalogue as "here's what I do know about".

### 4.7 Admin

Same process, same optional shared secret. Not a separate control plane.

| Method | Path | Request | Response | Status codes |
|---|---|---|---|---|
| `POST` | `/api/admin/ingest` | `{ manifest_path }` | `IngestionRun` | **202**, **409** (a run is already in progress), **400** (invalid manifest, nothing loaded) |
| `GET` | `/api/admin/ingest/{run_id}` | — | `IngestionReport` | 200 |
| `GET` | `/api/admin/dataset` | — | `{ active: {...}, retained: [...] }` | 200 |
| `POST` | `/api/admin/dataset/revert` | — | `{ active_version, reverted_within_ms }` | 200 |
| `GET` | `/api/admin/models` | — | `ResolvedRole[]` | 200 |
| `POST` | `/api/admin/improvement/runs` | `{}` | `{ run_id }` | **202**, **409** `improvement_run_in_progress` |
| `GET` | `/api/admin/improvement/proposals` | `?status=` | `Page<Proposal>` | 200 |
| `POST` | `/api/admin/improvement/proposals/{id}/approve` | `{ actor }` | `{ status, evaluation_run_id }` | 200, **409** (proposal is `stale`) |
| `POST` | `/api/admin/improvement/proposals/{id}/reject` | `{ actor, reason? }` | `{ status: "rejected" }` | 200 |
| `GET` | `/api/admin/artefacts/{kind}` | — | `ArtefactVersion[]` | 200 |
| `POST` | `/api/admin/artefacts/{kind}/revert` | `{ version, actor }` | `{ active_version }` | 200 |
| `POST` | `/api/admin/evaluation/runs` | `{ model_configurations[], repeat_count? }` | `{ run_id }` | **202** |
| `GET` | `/api/admin/evaluation/runs/{id}` | — | `EvaluationRun` | 200 |

`{kind}` is one of `prompt` | `exemplar` | `schema_description` | `metric`.

The 409s matter: ingestion and improvement runs are strictly one-at-a-time. Your admin UI should
disable the trigger while a run is in progress rather than relying on the error.

### 4.8 Health

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/health` | `HealthPayload` | No auth header required. Answers within 500 ms. |

Use `ready` as the boot gate for your app shell. Secrets are masked in this payload. Voice
reachability is cached (~300 s), so it is a coarse indicator, not a live probe.

---

## 5. Payload schemas

Paste-ready TypeScript. Nullable fields are marked `| null` where the backend emits an explicit null,
and `?` where the field may be absent. **Monetary fields are `string`.**

```ts
// ─────────────────────────────────────────────────────────────────────────────
// Shared enums (closed sets — exhaustively switch on these)
// ─────────────────────────────────────────────────────────────────────────────

export type Surface = "finance" | "insights";

export type TurnOutcome = "answered" | "clarification_requested" | "abstained" | "failed";

export type ResolutionPath = "metric_layer" | "generated_sql";

export type ConfidenceBand = "high" | "medium" | "low";

export type ValueType = "monetary" | "count" | "percentage" | "date" | "text";

export type TurnOrigin = "text" | "voice";

/** All 21 codes. See §7 for suggested user-facing intent per code. */
export type AbstentionReason =
  | "data_absent"
  | "intent_unsupported"
  | "ambiguous_entity"
  | "ambiguous_metric"
  | "ambiguous_date_range"
  | "ambiguous_grouping"
  | "reference_unresolved"
  | "clarification_exhausted"
  | "confidence_below_threshold"
  | "period_outside_coverage"
  | "entity_not_found"
  | "repair_limit_reached"
  | "budget_exhausted"
  | "provider_unavailable"
  | "schema_linking_failed"
  | "generation_failed"
  | "reviewer_unavailable"
  | "dataset_version_changed"
  | "metric_execution_failed"
  | "term_undefined"
  | "embedding_dimension_mismatch";

// ─────────────────────────────────────────────────────────────────────────────
// Chat: request
// ─────────────────────────────────────────────────────────────────────────────

export interface TurnRequest {
  question: string;
  /** Longer answer (400 words vs 120). Optional. */
  detailed?: boolean;
  /** BCP-47-ish code passed through to the pipeline. Optional. */
  language_code?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat: the main response
// ─────────────────────────────────────────────────────────────────────────────

export interface TurnResponse {
  turn_id: string;                       // UUID
  session_id: string;                    // UUID
  outcome: TurnOutcome;                  // switch on this FIRST — see §7

  /** null unless outcome === "answered" (or a templated fallback answer). */
  answer_text: string | null;

  /** The question after pronoun/ellipsis resolution. Show this on follow-ups. */
  resolved_question: string | null;
  /** Inclusive [start, end]. Always render this next to any figure. */
  resolved_date_range: [string, string] | null;

  /** Fully substituted SQL. null on the insights surface and on most abstentions. */
  executed_sql: string | null;

  applied_filters: AppliedFilter[];
  /** Rows excluded by the applied filters, combined. null when not applicable. */
  excluded_record_count: number | null;

  /** Set when the metric layer answered. null on the generated-SQL path. */
  metric_name: string | null;
  resolution_path: ResolutionPath | null;

  /** Ordered column descriptors for breakdown_preview. */
  breakdown_columns: BreakdownColumn[];
  /**
   * A PREFIX of the full result set (limit default 100 rows), in the same
   * total order as the retained snapshot and every export.
   * Cells are untyped — use breakdown_columns[i].value_type to render.
   * Monetary cells are decimal STRINGS.
   */
  breakdown_preview: Array<Record<string, unknown>>;
  /** Full row count of the result set, not the preview length. */
  total_row_count: number | null;

  /** Every figure in answer_text traces to one of these. */
  computation_records: ComputationRecord[];
  figure_provenance: FigureProvenance[];
  anomaly_callouts: AnomalyCallout[];

  confidence_score: number | null;       // 0..1, a real JSON number
  confidence_band: ConfidenceBand | null;
  confidence_signals: ConfidenceSignal[];
  /** Present on medium/low bands: the weakest applicable signal, in prose. */
  caution: string | null;

  abstention_reason_code: AbstentionReason | null;
  clarifying_question: ClarifyingQuestion | null;

  /** Present only on voice turns. */
  transcript: VoiceTranscript | null;

  /** true => figures come from the synthetic seed dataset. Badge this in the UI. */
  synthetic_data: boolean;
  dataset_version: number;
  schema_kb_version: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Provenance and figures
// ─────────────────────────────────────────────────────────────────────────────

export interface ComputationRecord {
  /** "c1", "c2" — cited from answer_text. Link these in the UI. */
  id: string;
  label: string;
  /** DECIMAL STRING. null when the figure is withheld (see undefined_reason). */
  value: string | null;
  /** DECIMAL STRING, full precision before display rounding. */
  unrounded_value: string | null;
  unit: string | null;
  currency: string | null;               // e.g. "INR", read from the dataset
  source_column: string | null;
  query_id: string;
  aggregated_row_count: number;
  /** Rows dropped because the aggregated column was NULL. Show if > 0. */
  null_excluded_row_count: number;
  /**
   * When set, value is null BY DESIGN — the figure is mathematically
   * undefined, not missing. Render the reason, not "—".
   */
  undefined_reason:
    | "zero_denominator"
    | "zero_or_negative_base"
    | "zero_row_aggregate"
    | "mixed_currency"
    | null;
  /** Released when a figure is withheld, so the UI can still show the inputs.
   *  Values are DECIMAL STRINGS. */
  operands: Record<string, string> | null;
}

export interface BreakdownColumn {
  label: string;
  value_type: ValueType;                 // drives cell rendering
  currency: string | null;               // set when value_type === "monetary"
}

export interface AppliedFilter {
  dimension: string;
  expression: string;                    // human-readable predicate
  excluded_record_count: number | null;
}

export interface FigureProvenance {
  computation_record_id: string;         // joins to ComputationRecord.id
  source_record_count: number;
  /** Capped (default 500) and in stable order. */
  source_record_ids: string[];
  /** true => the id list is capped; point the user at the export for the rest. */
  truncated: boolean;
}

export interface ConfidenceSignal {
  name: string;                          // e.g. "reviewer_verdict", "groundedness"
  applicable: boolean;
  normalised_value: number | null;       // 0..1, null when !applicable
  /** The RESCALED weight actually applied. Applicable weights sum to 1. */
  weight: number;
  weighted_contribution: number | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Anomaly callouts
// Field names are NOT pinned in design.md — see §10. Content per Requirement 20.4.
// ─────────────────────────────────────────────────────────────────────────────

export interface AnomalyCallout {
  /** The entity the flag is about (e.g. a vendor). */
  entity: string;
  /** DECIMAL STRING — the flagged value. */
  value: string;
  /** DECIMAL STRING — the entity's median over the history window. */
  median: string;
  /** Which rule fired. */
  kind: "modified_z" | "zero_dispersion";
  /** Modified z-score, 2dp, for kind === "modified_z". */
  z: number | null;
  /** Relative difference, 2dp, for kind === "zero_dispersion". */
  relative: number | null;
}
```

At most 3 callouts per turn, already ordered by the backend (`modified_z` first, then
`zero_dispersion`). Render in the order given. A callout is dropped silently if its own numbers fail
verification — the primary answer is never affected, so an empty array is normal.

```ts
// ─────────────────────────────────────────────────────────────────────────────
// Clarification (shape NOT fully pinned in design.md — see §10)
// ─────────────────────────────────────────────────────────────────────────────

export interface ClarifyingQuestion {
  /** The question to show the user. Names the specific ambiguity. */
  question: string;
  /** Candidate resolutions, when the backend can enumerate them.
   *  Render as chips; fall back to a free-text box when empty/absent. */
  options?: string[];
  /** Which dimension is ambiguous: entity | metric | date_range | grouping | reference */
  ambiguity?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Trace
// ─────────────────────────────────────────────────────────────────────────────

export type StageName =
  | "intake"
  | "context_resolution"
  | "intent_classification"
  | "entity_resolution"
  | "metric_routing"
  | "schema_retrieval"
  | "schema_linking"
  | "exemplar_retrieval"
  | "sql_generation"
  | "static_validation"
  | "plan_inspection"
  | "reviewer_verdict"
  | "repair_iteration"
  | "execution"
  | "computation"
  | "anomaly_check"
  | "answer_composition"
  | "groundedness_check"
  | "confidence_scoring"
  | "completion";

export type StageStatus =
  // stage events
  | "ok" | "error" | "skipped"
  // terminal event (stage === "completion") only
  | "completed" | "abstained" | "failed";

export interface ModelCallRecord {
  role: string;                          // "router" | "sql_generator" | "reviewer" | "composer" | ...
  provider: string;
  model_id: string;
  input_tokens: number | null;           // null => provider reported nothing
  output_tokens: number | null;
  /** true => counts are estimated, not provider-reported. Caveat any token UI. */
  tokens_estimated: boolean;
  duration_ms: number;
  outcome:
    | "ok" | "timeout" | "transport_error" | "auth_error" | "rate_limited"
    | "schema_nonconformance" | "model_unavailable" | "cancelled_by_budget";
}

export interface TraceEvent {
  turn_id: string;
  /** Contiguous 1..N per turn. Keepalives are NOT numbered — see §6. */
  sequence: number;
  stage: StageName;
  /** 1-based, dense. > 1 for repeated stages (repair iterations). */
  stage_attempt: number;
  status: StageStatus;
  /** Required when status === "skipped". */
  skip_reason: string | null;
  started_at: string;                    // UTC ISO-8601
  duration_ms: number;                   // 0 for skipped stages
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  /** true => summaries were shortened; see the untruncated_* counts. */
  truncated: boolean;
  untruncated_row_count: number | null;
  untruncated_char_count: number | null;
  model_call: ModelCallRecord | null;    // null on non-LLM stages
  error_type: string | null;
  error_message: string | null;          // secrets are redacted at the emitter
}

export interface TraceList {
  turn_id: string;
  events: TraceEvent[];
  terminal_status: "completed" | "abstained" | "failed";
}

export interface TraceSummary {
  turn_id: string;
  created_at: string;
  terminal_status: "completed" | "abstained" | "failed";
  event_count: number;                   // field set not fully pinned — see §10
}

// ─────────────────────────────────────────────────────────────────────────────
// Sessions
// ─────────────────────────────────────────────────────────────────────────────

export interface SessionCreated {
  session_id: string;
  surface: Surface;
  /** Pre-validated, guaranteed-answerable. Render as opening chips. */
  starter_questions: string[];
  dataset_version: number;
  synthetic_data: boolean;
}

export interface SessionSummary {
  session_id: string;
  surface: Surface;
  created_at: string;
  last_turn_at: string | null;
  turn_count: number;                    // field set not fully pinned — see §10
}

export interface SessionDetail {
  session: SessionSummary;
  turns: TurnSummary[];
}

export interface TurnSummary {
  turn_id: string;
  ordinal: number;
  started_at: string;
  origin: TurnOrigin;
  question_text: string;
  outcome: TurnOutcome;
  confidence_band: ConfidenceBand | null;
}

export interface Page<T> {
  items: T[];
  total_count?: number;                  // present on drilldown
  /** Opaque. Pass back verbatim. Format NOT specified — see §10. */
  cursor?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Explanation ("how did you get this?" drawer)
// ─────────────────────────────────────────────────────────────────────────────

export interface ExplanationPayload {
  steps: unknown[];                      // ordered pipeline steps in prose
  schema_chunks: unknown[];              // retrieved schema entries + scores
  metric_or_sql: unknown;                // the bound template or the SQL
  reviewer_verdicts: unknown[];          // see VerdictRecord shape below
  repair_iterations: unknown[];
  figure_sources: unknown[];             // figure -> source records
}
```

`ExplanationPayload`'s inner element shapes are named but not fully specified in design.md — treat
them as opaque and render generically, or wait for the shapes to be pinned. See §10.

```ts
/** Appears inside reviewer_verdict trace events and ExplanationPayload. */
export interface VerdictRecord {
  candidate_index: number;
  verdict: "approve" | "repair" | "reject";
  reason: string;                        // ≤ 500 chars
  /** Always set when verdict is repair/reject. */
  defect_category:
    | "wrong_aggregation" | "wrong_grouping" | "wrong_filter" | "wrong_date_range"
    | "wrong_join_cardinality" | "wrong_result_columns" | "missing_predicate"
    | "extra_predicate" | "schema_mismatch" | "suspected_filter_defect"
    | "reviewer_output_nonconformance" | "other"
    | null;
  evidence: Array<{
    kind: "table" | "column" | "filter_predicate" | "sample_row_index";
    value: string;
  }>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Voice
// ─────────────────────────────────────────────────────────────────────────────

/** Shape partially pinned — see §10. */
export interface VoiceTranscript {
  text: string;
  language_code: string | null;
  /** 0.00–1.00. NOT a transcription-accuracy score: it is the provider's
   *  language-detection probability under auto-detect, or a configured
   *  default when an explicit language_code was sent. Do not present it
   *  to users as "how well I heard you". */
  confidence: number;
}

export interface PendingConfirmation {
  turn_id: string;
  transcript: VoiceTranscript;
  confidence: number;
}

export interface SpeechResponse {
  segments: Array<{
    index: number;                       // play in ascending order
    audio_base64: string;
    format: string;                      // e.g. "wav"
    duration_ms: number;
  }>;
  /** "spoken" = a speech-optimised rephrasing; "written" = the written answer. */
  variant: "spoken" | "written";
  audio_unavailable?: boolean;
  reason_code?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Metrics
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The universal wrapper for every ratio, rate, percentile and mean.
 * value === null is the EXPLICIT not-measured marker. It is NOT zero.
 * measured_from is the population size the figure was computed over.
 */
export interface Measured {
  value: number | null;
  measured_from: number;
}

export interface AppliedRange {
  start: string;                         // half-open [start, end)
  end: string;
}

export interface OverviewMetrics {
  session_count: number;
  turn_count: number;
  answered: number;
  abstained: number;
  clarified: number;
  failed: number;
  mean_confidence: Measured;
  feedback_positive: number;
  feedback_negative: number;
  applied_range: AppliedRange;
}

/** SCOPE: an evaluation run. NOT your date filter. Label it as such in the UI. */
export interface AccuracyMetrics {
  run_id: string;
  run_completed_at: string;
  golden_questions_scored: number;
  scope: "evaluation_run";
  execution_accuracy: Measured;
  grounding_rate: Measured;
  helpful_refusals: Measured;
  unhelpful_refusals: Measured;
  sql_validity_rate: Measured;
  reviewer_catch_rate: Measured;
  reviewer_false_rejection_rate: Measured;
  first_attempt_success_rate: Measured;
}

export interface LatencyMetrics {
  per_stage: Array<{
    stage: StageName;
    p50: Measured; p95: Measured; p99: Measured;
    measured_from: number;
  }>;
  end_to_end: { p50: Measured; p95: Measured; p99: Measured };
  applied_range: AppliedRange;
}

export interface EfficiencyMetrics {
  tokens_per_resolved: Measured;
  llm_calls_per_resolved: Measured;
  /** value is null when no price is configured — show "not priced", not "0". */
  cost_per_resolved: Measured;
  active_model_configuration: ResolvedRole[];
  applied_range: AppliedRange;
}

export interface TimeSeries {
  metric_id: string;
  bucket: "hour" | "day";
  points: Array<{ bucket_start: string; value: number | null; measured_from: number }>;
  applied_range: AppliedRange;
}

export interface QuestionCategoryRow {
  intent_family: string;
  turn_volume: number;
  accuracy: Measured;
  abstention_rate: Measured;
  failure_count: number;
}

export interface EngagementMetrics {
  mean_turns_per_session: Measured;
  followup_depth_distribution: Array<{ depth: number; count: number }>;
  clarification_rate: Measured;
  task_completion_rate: Measured;
  applied_range: AppliedRange;
}

export interface TurnRef {
  turn_id: string;
  started_at: string;
  outcome: TurnOutcome;
}

export interface ModelComparisonRow {
  run_id: string;
  repeat_index: number;
  status: "complete" | "incomplete";
  model_configuration: Record<string, unknown>;
  metrics: Record<string, Measured>;
}

export interface MetricIdDescriptor {
  metric_id: string;
  description: string;
  supported_buckets: Array<"hour" | "day">;
}

export interface FailureCase {
  case_id: string;
  turn_id: string | null;
  source:
    | "reviewer_reject" | "groundedness_reject" | "user_negative_feedback"
    | "evaluation_incorrect" | "pipeline_fault";
  status: "new" | "triaged" | "proposed" | "approved" | "applied" | "dismissed";
  root_cause: string | null;
  resolved_question: string;
  dataset_version: number;
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Buddy
// ─────────────────────────────────────────────────────────────────────────────

export interface BuddyCatalogue {
  metrics: Array<{ name: string; description: string; columns: string[] }>;
  dimensions: string[];
  reconciliation_statuses: string[];
  date_coverage: { first: string; last: string };
}

export interface TermExplanation {
  term: string;
  description: string;
  columns: string[];
  source: string;                        // which artefact the description came from
}

/** On an insights turn, TurnResponse carries this instead of executed_sql. */
export interface MetricsSource {
  endpoint_id: string;
  bound_parameters: Record<string, unknown>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Admin / health
// ─────────────────────────────────────────────────────────────────────────────

export interface ResolvedRole {
  role: string;
  provider: string;
  model_id: string;
  temperature: number;
  max_output_tokens: number;
  prompt_version: string;
  fallback: string | null;
  /** Non-null => this role cannot run; names the missing credential/endpoint. */
  unavailable_reason: string | null;
}

export interface HealthPayload {
  status: string;
  ready: boolean;                        // gate your app shell on this
  database: string;
  alembic: { applied: string; head: string };
  vector_extension: boolean;
  dataset_version: number;
  schema_kb_version: number;
  models: Array<{ role: string; provider: string; model_id: string }>;
  voice_reachable: { stt: boolean; tts: boolean; probed_at: string };
  synthetic_data: boolean;
}
```

---

## 6. The trace event contract

This is the headline feature. Get it right and the product looks like it thinks; get it wrong and it
looks broken.

### The 20 stage names, in emitted order

| # | Stage | Emitted when | Payload worth rendering |
|---|---|---|---|
| 1 | `intake` | Always | question length |
| 2 | `context_resolution` | Always | the resolved question |
| 3 | `intent_classification` | Always | intent family |
| 4 | `entity_resolution` | Always | resolved entity mentions |
| 5 | `metric_routing` | Always (`ok` on metric path, `skipped` otherwise) | matched metric name + routing score |
| 6 | `schema_retrieval` | Generated-SQL path | **scored schema chunks** — great UI |
| 7 | `schema_linking` | Generated-SQL path | **selected sub-schema** + what was excluded |
| 8 | `exemplar_retrieval` | Generated-SQL path | exemplar count, exclusions |
| 9 | `sql_generation` | Generated-SQL path | **candidate SQL statements** |
| 10 | `static_validation` | Always, once per candidate | per-candidate accept/reject verdict |
| 11 | `plan_inspection` | Always | query plan summaries |
| 12 | `reviewer_verdict` | Always | **verdict, reason, defect category** |
| 13 | `repair_iteration` | Only when a repair happens | iteration ordinal |
| 14 | `execution` | On an answered turn | **row count, duration_ms** |
| 15 | `computation` | On an answered turn | computation records |
| 16 | `anomaly_check` | Always (`skipped` when out of budget) | flags |
| 17 | `answer_composition` | On an answered turn | word count |
| 18 | `groundedness_check` | On an answered turn | verification summary |
| 19 | `confidence_scoring` | On an answered turn | score detail |
| 20 | `completion` | Always, exactly once, last | terminal status |

The six bolded rows are the ones users find compelling. Build those panels first; render the rest as
a simple checklist.

*(design.md's type declaration lists `metric_routing` after `schema_linking`; the orchestrator emits
it before `schema_retrieval` on both paths. The set is identical — only the declaration order in the
type differs. Order your UI by emitted order, or just sort by `sequence`.)*

### Statuses

- **Stage events** (`stage !== "completion"`): `ok` | `error` | `skipped`
- **Terminal event** (`stage === "completion"`, exactly one per turn): `completed` | `abstained` | `failed`

A single `switch` on `status` is not enough — check whether the stage is `completion` first, then
branch. Do not expect `completed` on a stage event or `ok` on the terminal event.

### `sequence` is contiguous 1..N — and keepalives are excluded

- Every trace event for a turn carries `sequence` from `1` to `N` with **no gaps and no duplicates**.
- **Keepalive frames arrive on a distinct SSE `event:` name (`keepalive`) and carry no `sequence`
  field at all.** They are transport plumbing, outside the numbering.
- Therefore: **never treat a keepalive as a missing event.** Filter by event name first, then by the
  presence of `sequence`. A gap in `sequence` after that filter is a real problem worth logging; a
  keepalive is not.
- `started_at` is non-decreasing across the sequence, so sorting by `sequence` and sorting by time
  agree.

### `stage_attempt` — repeated stages

Stages can repeat. When a repair happens you will see `sql_generation`, `static_validation` and
`reviewer_verdict` again, with `stage_attempt` incrementing (`1`, `2`, …) densely from 1. Key your UI
rows on `(stage, stage_attempt)`, not on `stage` alone, or the retry will overwrite the first attempt
and the repair loop becomes invisible — which is exactly the part worth showing.

### `skipped` events — render a fixed pipeline shape

Skipped stages are **emitted explicitly**, with a `skip_reason` and `duration_ms: 0`. On the metric
path you will always see four of them (`schema_retrieval`, `schema_linking`, `exemplar_retrieval`,
`sql_generation`), each with reason `metric_layer_path`.

This is a deliberate gift to the UI: **render all 20 stages as a fixed shape from the first frame and
grey out the skipped ones.** Do not build a list that grows as events arrive — the pipeline shape is
constant, and "skipped because the metric layer already had a template" is a good story, not an
absence.

### Truncation

Large summaries are shortened. When `truncated: true`, `untruncated_row_count` and/or
`untruncated_char_count` tell you what was elided. Show "showing 5 of 1,284 rows" rather than
implying the summary is complete.

### Reconnect is safe

Every subscriber, whenever it connects, receives the **committed prefix replayed in sequence order**
before it starts receiving live events. So:

- Opening the stream a moment after `POST /turns` loses nothing.
- Reconnecting after a dropped connection loses nothing — but you **will** receive events you already
  have. Deduplicate on `(turn_id, sequence, stage_attempt)`; make your reducer idempotent.
- Concurrent subscribers each independently see `1..N`.

### Both transports carry the same objects

SSE frames named `event: trace` and WebSocket JSON text frames carry byte-equivalent `TraceEvent`
objects. And `GET /api/turns/{tid}/trace` returns the same list, persisted — equal in count, sequence,
stage, status, timestamp, duration and model-call fields. So you can develop against the persisted
endpoint and switch to the stream later without changing your renderer.

---

## 7. Outcome handling

Switch on `TurnResponse.outcome` before rendering anything.

| `outcome` | What happened | What the UI should show |
|---|---|---|
| `answered` | A grounded answer was produced | `answer_text`, the breakdown table, `resolved_date_range` and currency, the confidence band, the verify drawer (SQL + computation records + provenance), export button, anomaly callouts |
| `clarification_requested` | The question was ambiguous | `clarifying_question` — render as a prompt with option chips if present, free-text otherwise. **No figures, no breakdown table.** Post the reply to `POST /api/sessions/{sid}/clarifications` |
| `abstained` | The system declined to answer | `abstention_reason_code` mapped to copy (below). **No breakdown table and no numbers** except dataset coverage dates. Offer a next action: rephrase, widen the date range, pick from `/buddy/starters` |
| `failed` | Internal fault | A generic failure state plus retry. Do not surface internals. Still offer feedback — failures feed the improvement loop |

**Design the refusal state properly.** A clean, specific "I won't answer that, and here's exactly
why" is a scored differentiator, not an error path. It is the visible proof the system does not make
numbers up. Give it real design attention — not a red toast.

Never render `breakdown_preview` or `computation_records` for `abstained` or
`clarification_requested`; they are empty by contract, and the only numbers permitted in the text are
dataset coverage dates.

### The 21 abstention reason codes

Message intent is a **hint for copywriting**, not final copy.

| Reason code | Suggested user-facing intent |
|---|---|
| `data_absent` | "The dataset doesn't contain that information." Offer the catalogue of what it does contain. |
| `intent_unsupported` | "I can't answer that kind of question." Name the supported kinds; link starters. |
| `ambiguous_entity` | "Which one did you mean?" — should normally arrive as a clarification instead; if abstained, list candidates. |
| `ambiguous_metric` | "That could mean more than one measure." Offer the metric list. |
| `ambiguous_date_range` | "Which period?" Offer concrete ranges inside the coverage window. |
| `ambiguous_grouping` | "Grouped by what?" Offer the available dimensions. |
| `reference_unresolved` | "I couldn't tell what 'that'/'it' refers to." Ask them to restate in full. |
| `clarification_exhausted` | "I asked twice and still can't pin it down." Suggest starting a fresh, fully-specified question. |
| `confidence_below_threshold` | "I'm not confident enough to give you this number." This is a feature — say so plainly. Offer rephrase. |
| `period_outside_coverage` | "I only have data from {first} to {last}." The dates **are** in the response; show them. |
| `entity_not_found` | "I couldn't find that vendor/account." Suggest close matches or the catalogue. |
| `repair_limit_reached` | "I couldn't write a query I trust for this." Suggest simplifying the question. |
| `budget_exhausted` | "That took too long / too much work to answer safely." Offer retry with a narrower question. |
| `provider_unavailable` | "The language model is unavailable right now." Infrastructure — retry later. |
| `schema_linking_failed` | "I couldn't match your question to the data." Suggest rephrasing with dataset vocabulary; link the catalogue. |
| `generation_failed` | "I couldn't produce a valid query." Suggest simplifying. |
| `reviewer_unavailable` | "I couldn't verify the query, so I won't run it." Emphasise the safety framing. |
| `dataset_version_changed` | "The dataset was updated mid-question." Straightforward retry — this one is safe to auto-retry once. |
| `metric_execution_failed` | "A predefined calculation failed." Infrastructure; report it. |
| `term_undefined` | "I don't have a definition for that term." Return the catalogue (the endpoint already does). |
| `embedding_dimension_mismatch` | "Search index is misconfigured." Operator-facing; generic message for users. |

`dataset_version_changed` is the only code where a silent auto-retry is appropriate. Everything else
needs the user to see the refusal — that is the point.

---

## 8. Confidence rendering

| Band | Score range |
|---|---|
| `low` | 0 to below 0.50 |
| `medium` | 0.50 to below 0.80 |
| `high` | 0.80 to 1 |

Answers scoring below the acceptance threshold (0.60) do not reach you as `answered` at all — they
arrive as an abstention with `confidence_below_threshold`. So in practice an answered turn is either
`high`, or `medium` in the 0.60–0.80 range.

- `confidence_score` is a real JSON number in `[0, 1]`. Show the band prominently; the raw score is
  secondary.
- `confidence_signals[]` is the per-signal breakdown: `name`, `applicable`, `normalised_value`,
  the **rescaled** `weight` actually applied, and `weighted_contribution`. Applicable weights sum to
  1, so a stacked bar or a small table reads correctly without normalising anything yourself.
- Filter to `applicable === true` for display; inapplicable signals have `normalised_value: null` and
  are noise in a chart.
- `reviewer_verdict` and `groundedness` are always applicable on an answered turn — safe to feature
  them.
- **`caution` is a non-null string on `medium` and `low` bands** and names the weakest applicable
  signal. Render it next to the answer, not buried in a drawer. On `high` it is `null`.
- On voice turns the released score is clamped so it never exceeds the transcription confidence — a
  voice answer can legitimately show a lower band than the same typed question.

---

## 9. Dashboard contract

Reproduced from design.md §4.4. **The Scope column is the load-bearing part:** a panel fed by an
evaluation run must not sit inside a date-range-filtered page implying the two move together. Label
evaluation-run panels with `run_completed_at`, not with the page's date filter.

| Panel / section | Endpoint | Fields | Scope |
|---|---|---|---|
| Dashboard: activity tiles | `/metrics/overview` | `session_count`, `turn_count`, `answered`, `abstained`, `clarified`, `failed` | date range |
| Dashboard: quality tiles | `/metrics/accuracy` | `execution_accuracy`, `grounding_rate`, `first_attempt_success_rate` | **evaluation run** |
| Dashboard: refusal split | `/metrics/accuracy` | `helpful_refusals`, `unhelpful_refusals` | **evaluation run** |
| Dashboard: reviewer panel | `/metrics/accuracy` | `reviewer_catch_rate`, `reviewer_false_rejection_rate` | **evaluation run** |
| Dashboard: confidence tile | `/metrics/overview` | `mean_confidence` | date range |
| Dashboard: efficiency tiles | `/metrics/efficiency` | `tokens_per_resolved`, `llm_calls_per_resolved`, `cost_per_resolved` | date range |
| Dashboard: active model card | `/metrics/efficiency` | `active_model_configuration` | current config |
| Dashboard: latency chart | `/metrics/latency` | `per_stage[].p50/p95/p99`, `end_to_end` | date range |
| Dashboard: volume trend | `/metrics/timeseries` | `metric_id=turn_count`, `bucket=day` | date range |
| Dashboard: cost trend | `/metrics/timeseries` | `metric_id=cost_per_resolved_question` | date range |
| Analytics: intent table | `/metrics/question-categories` | all | date range |
| Analytics: engagement | `/metrics/engagement` | all | date range |
| Analytics: model comparison | `/metrics/model-comparison` | all | **evaluation runs** |
| Analytics: confidence calibration | `/metrics/accuracy` + `/metrics/model-comparison` | per-band observed accuracy | **evaluation run** |
| Analytics: failure queue | `/metrics/failures` | all | date range |
| Any tile → turn list | `/metrics/drilldown` | `total_count`, `items[].turn_id` | date range |
| Turn list → single turn | `/turns/{tid}` + `/turns/{tid}/trace` + `/turns/{tid}/explanation` | all | turn |
| Chat: answer view | `POST /sessions/{sid}/turns` | `answer_text`, `breakdown_*`, `confidence_*`, `applied_filters`, `anomaly_callouts` | turn |
| Chat: thinking view | `GET /turns/{tid}/trace/stream` | stage events in order | turn |
| Chat: verify drawer | `TurnResponse` | `executed_sql`, `computation_records`, `figure_provenance` | turn |
| Chat: export button | `GET /turns/{tid}/export` | file | turn |
| Chat: suggestion chips | `/buddy/starters`, `/buddy/next-questions` | `questions[]` | dataset version / turn |

### Frozen `metric_id` enumeration

These identifiers are frozen on first publication — safe to reference in code. Prefer fetching
`/api/metrics/metric-ids` at runtime so you also get `supported_buckets`.

```
turn_count                        session_count
answered_turn_count               abstained_turn_count
clarified_turn_count              failed_turn_count
mean_confidence_score             clarification_rate
abstention_rate                   tokens_per_resolved_question
llm_calls_per_resolved_question   cost_per_resolved_question
end_to_end_p50_ms                 end_to_end_p95_ms
end_to_end_p99_ms                 feedback_positive_count
feedback_negative_count           insights_turn_count
insights_estimated_cost
```

### `{ value, measured_from }` — and why `null` is not zero

Every ratio, rate, percentile and mean uses this wrapper:

```json
{ "mean_confidence": { "value": 0.83, "measured_from": 412 } }
{ "cost_per_resolved":  { "value": null, "measured_from": 0 } }
```

**`value: null` is the explicit not-measured marker. It is categorically different from a measured
zero.** `{ "value": 0, "measured_from": 120 }` means "we measured 120 turns and the rate really is
zero". `{ "value": null }` means "there was nothing to measure" (or, for cost, no price configured).

Render them differently — `null` should read as "—" or "not measured", never as `0` and never as a
zero-height bar. Showing a 0% accuracy tile when the truth is "no evaluation has run" is the single
worst thing a dashboard here can do.

`measured_from` is the population size. Use it to suppress or caveat figures computed over a
too-small sample.

The overview, timeseries and drilldown endpoints are guaranteed consistent for the same
`metric_id` and range: the overview value equals the sum over timeseries buckets, which equals the
drilldown `total_count`. If they disagree in your UI, you have a bug in your date handling.

---

## 10. Open / not yet pinned

Honest list. Do not guess at these — isolate them behind a seam so pinning them is a small change.

**Security and access**

- **There is no user authentication, no authorisation model and no per-user data isolation.** The only
  mechanism is the optional `X-Internal-Token` shared secret. Every session is visible to every
  caller. Do not build a UI that implies per-user privacy.
- The **status code for a rejected/missing `X-Internal-Token` is not specified** (401 vs 403). Handle
  both as "auth failed".
- The backend binds loopback by default, so a browser app on another host needs an explicit config
  change on the server side. **CORS behaviour is not specified anywhere in the design** — assume you
  will need a dev proxy.

**Shapes not fully specified**

- **Pagination cursor format is not specified.** `Page<T>` is named for several endpoints, but the
  cursor's encoding, whether it is opaque, and the exact envelope field names are not pinned. Treat
  the cursor as an opaque string, pass it back verbatim, and keep pagination behind one helper.
- **`ClarifyingQuestion`** is referenced in `TurnResponse` but its fields are not declared. The
  interface above is a best reading of the requirements (it must name the ambiguity). Build the
  clarification UI tolerant of a text-only shape.
- **`AnomalyCallout`** is likewise referenced but not declared. Content is specified (entity, flagged
  value, median, score / relative difference); **field names are not.**
- **`VoiceTranscript`** field names are not declared.
- **`ExplanationPayload`** names its six arrays but not their element shapes. Render generically for
  now, or defer the explanation drawer until pinned.
- **`SessionSummary`, `TurnSummary`, `TraceSummary`, `Page`, `IngestionReport`, `Proposal`,
  `ArtefactVersion`, `EvaluationRun`** are named with partial field lists. Fields shown above are
  from design.md; assume more may appear (additive only).
- **How `turn_id` is returned "immediately" from `POST /turns`** while the body completes later is
  guaranteed but the mechanism is not specified (early header, first chunk, or a separate call).
  Wrap it in one function — see the pseudocode in §3.

**Product scope**

- **Whether a dashboard UI is in scope at all is undecided.** The dashboard contract exists and the
  endpoints are specified, but nobody has committed to building the dashboard. Confirm before
  investing in §9.

**Data**

- **The organisers' dataset has not arrived.** Everything you see in development comes from the
  **synthetic seed dataset**: ≥5,000 transactions, ≥200 vendor payouts, ≥40 vendors, ≥12 consecutive
  months of history, ≥500 unreconciled transactions.
- **Entity names, category values, reconciliation status values and the date coverage window in every
  example below will change** when the real dataset lands. Do not hardcode vendor names, status
  strings or date bounds. Read coverage from `/api/buddy/catalogue` (`date_coverage`) and statuses
  from the same payload.
- `synthetic_data: true` on a `TurnResponse` means the figures are from the seed dataset. **Badge it
  visibly** — a demo screenshot of synthetic numbers presented as real is a credibility problem.
- The **currency is read from the dataset**, not fixed. Examples use `INR`. Always render
  `ComputationRecord.currency` / `BreakdownColumn.currency` rather than assuming.

---

## 11. Mocking guide

### Build order

**Stub these three first — they get you a working chat view:**

1. `POST /api/sessions` → static `SessionCreated` with 4–5 starter questions.
2. `POST /api/sessions/{sid}/turns` → a static `TurnResponse` with `outcome: "answered"`. Add a
   deliberate delay (2–5 s) so you build the loading and streaming states honestly.
3. `GET /api/turns/{tid}/trace/stream` → replay a recorded event sequence.

**A recorded event sequence replayed over SSE with small delays is entirely sufficient to build the
trace view.** You do not need any backend logic — capture or hand-write one array of `TraceEvent`
objects with contiguous `sequence` values and emit them on a timer. Include: one `skipped` event, one
`error` event, one repeated stage with `stage_attempt: 2`, a keepalive frame, and the `completion`
terminal event. That covers every branch your renderer must handle.

Then add, in order: `GET /api/turns/{tid}` (deep links and history), `POST /feedback` (204, trivial),
`GET /api/buddy/starters` and `/next-questions` (chips), `GET /api/turns/{tid}/export` (a static
file + the three error codes), `POST /api/sessions/{sid}/clarifications`.

### Fixtures worth having on day one

Four `TurnResponse` fixtures cover the whole outcome space: `answered`, `clarification_requested`,
`abstained`, `failed`. Add a fifth for `answered` with `confidence_band: "medium"` and a non-null
`caution`, and a sixth with `anomaly_callouts` populated.

### Traps the mocks should force you to handle

- Monetary values as strings — put a value with trailing decimal zeros (`"4823150.00"`) in your
  fixture so a naive `Number()` shows up immediately as `4823150` in the UI.
- A `ComputationRecord` with `value: null` and `undefined_reason: "zero_denominator"`.
- A `Measured` with `value: null` next to one with `value: 0`.
- A keepalive frame in your SSE mock, so you prove your gap detection ignores it.
- `truncated: true` on a trace event with `untruncated_row_count: 1284`.

---

## Appendix: example payloads

Figures below reflect the **synthetic seed dataset** shape only. Vendor names, categories, statuses
and dates will change when the organisers' dataset arrives.

### A. `POST /api/sessions` → 200

```json
{
  "session_id": "8f1c3d2a-5e47-4b91-9c0d-2a7e5f1b4c88",
  "surface": "finance",
  "starter_questions": [
    "How much did we spend on vendor payouts last month?",
    "Which vendors did we pay the most in the last quarter?",
    "How many transactions are still unreconciled?",
    "What was our total spend by category last month?"
  ],
  "dataset_version": 1,
  "synthetic_data": true
}
```

### B. `POST /api/sessions/{sid}/turns` → 200, `outcome: "answered"`

```json
{
  "turn_id": "b2d94e17-6c05-4a3f-8e21-9f77a0c4d513",
  "session_id": "8f1c3d2a-5e47-4b91-9c0d-2a7e5f1b4c88",
  "outcome": "answered",
  "answer_text": "Vendor payouts totalled INR 4,823,150.00 between 1 June 2025 and 30 June 2025 across 187 payouts [c1]. The largest share went to Northwind Logistics at INR 812,400.00 [c2].",
  "resolved_question": "What was the total value of vendor payouts between 2025-06-01 and 2025-06-30?",
  "resolved_date_range": ["2025-06-01", "2025-06-30"],
  "executed_sql": "SELECT v.vendor_name, SUM(p.amount) AS total_amount FROM finance.vendor_payouts p JOIN finance.vendors v ON v.vendor_id = p.vendor_id WHERE p.payout_date >= '2025-06-01' AND p.payout_date <= '2025-06-30' AND p.dataset_version = 1 GROUP BY v.vendor_name ORDER BY total_amount DESC",
  "applied_filters": [
    { "dimension": "payout_date", "expression": "2025-06-01 to 2025-06-30 inclusive", "excluded_record_count": null }
  ],
  "excluded_record_count": null,
  "metric_name": "vendor_spend_over_period",
  "resolution_path": "metric_layer",
  "breakdown_columns": [
    { "label": "vendor_name",  "value_type": "text",     "currency": null },
    { "label": "total_amount", "value_type": "monetary", "currency": "INR" }
  ],
  "breakdown_preview": [
    { "vendor_name": "Northwind Logistics", "total_amount": "812400.00" },
    { "vendor_name": "Acme Industrial",     "total_amount": "654210.50" },
    { "vendor_name": "Belmont Supplies",    "total_amount": "498375.00" }
  ],
  "total_row_count": 38,
  "computation_records": [
    {
      "id": "c1",
      "label": "Total vendor payouts",
      "value": "4823150.00",
      "unrounded_value": "4823150.000000",
      "unit": null,
      "currency": "INR",
      "source_column": "vendor_payouts.amount",
      "query_id": "q1",
      "aggregated_row_count": 187,
      "null_excluded_row_count": 0,
      "undefined_reason": null,
      "operands": null
    },
    {
      "id": "c2",
      "label": "Largest vendor payout total",
      "value": "812400.00",
      "unrounded_value": "812400.000000",
      "unit": null,
      "currency": "INR",
      "source_column": "vendor_payouts.amount",
      "query_id": "q1",
      "aggregated_row_count": 14,
      "null_excluded_row_count": 0,
      "undefined_reason": null,
      "operands": null
    }
  ],
  "figure_provenance": [
    { "computation_record_id": "c1", "source_record_count": 187, "source_record_ids": ["PO-000412", "PO-000413"], "truncated": true },
    { "computation_record_id": "c2", "source_record_count": 14,  "source_record_ids": ["PO-000418"], "truncated": false }
  ],
  "anomaly_callouts": [],
  "confidence_score": 0.86,
  "confidence_band": "high",
  "confidence_signals": [
    { "name": "reviewer_verdict",     "applicable": true,  "normalised_value": 1.0,  "weight": 0.35, "weighted_contribution": 0.35 },
    { "name": "groundedness",         "applicable": true,  "normalised_value": 1.0,  "weight": 0.30, "weighted_contribution": 0.30 },
    { "name": "candidate_agreement",  "applicable": false, "normalised_value": null, "weight": 0.0,  "weighted_contribution": null },
    { "name": "retrieval_score",      "applicable": true,  "normalised_value": 0.62, "weight": 0.20, "weighted_contribution": 0.124 },
    { "name": "repair_free",          "applicable": true,  "normalised_value": 1.0,  "weight": 0.15, "weighted_contribution": 0.15 }
  ],
  "caution": null,
  "abstention_reason_code": null,
  "clarifying_question": null,
  "transcript": null,
  "synthetic_data": true,
  "dataset_version": 1,
  "schema_kb_version": 1
}
```

> Note `resolution_path: "metric_layer"` — a predefined template answered this, so
> `schema_retrieval`, `schema_linking`, `exemplar_retrieval` and `sql_generation` will all arrive as
> `skipped` in the trace. `confidence_signals` names and weights are illustrative; the exact signal
> set and default weights come from backend configuration.

### C. Trace events — one of each status

```json
{
  "turn_id": "b2d94e17-6c05-4a3f-8e21-9f77a0c4d513",
  "sequence": 5,
  "stage": "metric_routing",
  "stage_attempt": 1,
  "status": "ok",
  "skip_reason": null,
  "started_at": "2025-07-14T09:12:03.417Z",
  "duration_ms": 12,
  "input_summary": { "intent": "aggregate_spend_over_period" },
  "output_summary": { "metric": "vendor_spend_over_period", "score": 0.91 },
  "truncated": false,
  "untruncated_row_count": null,
  "untruncated_char_count": null,
  "model_call": null,
  "error_type": null,
  "error_message": null
}
```

```json
{
  "turn_id": "b2d94e17-6c05-4a3f-8e21-9f77a0c4d513",
  "sequence": 6,
  "stage": "schema_retrieval",
  "stage_attempt": 1,
  "status": "skipped",
  "skip_reason": "metric_layer_path",
  "started_at": "2025-07-14T09:12:03.430Z",
  "duration_ms": 0,
  "input_summary": {},
  "output_summary": {},
  "truncated": false,
  "untruncated_row_count": null,
  "untruncated_char_count": null,
  "model_call": null,
  "error_type": null,
  "error_message": null
}
```

```json
{
  "turn_id": "c7a51f08-2b3e-4d6a-91f4-6e0b8d2a7c31",
  "sequence": 10,
  "stage": "static_validation",
  "stage_attempt": 1,
  "status": "error",
  "skip_reason": null,
  "started_at": "2025-07-14T09:20:11.882Z",
  "duration_ms": 31,
  "input_summary": { "candidate": 1 },
  "output_summary": { "verdict": "reject", "category": "unknown_identifier", "name": "vendor_tier" },
  "truncated": false,
  "untruncated_row_count": null,
  "untruncated_char_count": null,
  "model_call": null,
  "error_type": "ValidationRejectedError",
  "error_message": "unknown identifier: vendor_tier"
}
```

```json
{
  "turn_id": "b2d94e17-6c05-4a3f-8e21-9f77a0c4d513",
  "sequence": 14,
  "stage": "execution",
  "stage_attempt": 1,
  "status": "ok",
  "skip_reason": null,
  "started_at": "2025-07-14T09:12:05.006Z",
  "duration_ms": 84,
  "input_summary": { "query_id": "q1" },
  "output_summary": { "rows": 38, "ms": 84 },
  "truncated": true,
  "untruncated_row_count": 1284,
  "untruncated_char_count": null,
  "model_call": null,
  "error_type": null,
  "error_message": null
}
```

Terminal event:

```json
{
  "turn_id": "b2d94e17-6c05-4a3f-8e21-9f77a0c4d513",
  "sequence": 20,
  "stage": "completion",
  "stage_attempt": 1,
  "status": "completed",
  "skip_reason": null,
  "started_at": "2025-07-14T09:12:05.640Z",
  "duration_ms": 2,
  "input_summary": {},
  "output_summary": { "outcome": "answered" },
  "truncated": false,
  "untruncated_row_count": null,
  "untruncated_char_count": null,
  "model_call": null,
  "error_type": null,
  "error_message": null
}
```

Raw SSE framing, including a keepalive:

```
event: trace
data: {"turn_id":"b2d9...","sequence":5,"stage":"metric_routing","status":"ok", ...}

event: keepalive
data: {}

event: trace
data: {"turn_id":"b2d9...","sequence":6,"stage":"schema_retrieval","status":"skipped", ...}
```

The keepalive has no `sequence`. Sequence goes 5 → 6. **That is not a gap.**

### D. Abstention — `period_outside_coverage`

```json
{
  "turn_id": "1e6b7c40-8a92-4f15-b3d7-05c81a9e6f22",
  "session_id": "8f1c3d2a-5e47-4b91-9c0d-2a7e5f1b4c88",
  "outcome": "abstained",
  "answer_text": "I don't have data for 2019. This dataset covers 1 July 2024 to 30 June 2025.",
  "resolved_question": "What did we spend with Acme Industrial in 2019?",
  "resolved_date_range": null,
  "executed_sql": null,
  "applied_filters": [],
  "excluded_record_count": null,
  "metric_name": null,
  "resolution_path": null,
  "breakdown_columns": [],
  "breakdown_preview": [],
  "total_row_count": null,
  "computation_records": [],
  "figure_provenance": [],
  "anomaly_callouts": [],
  "confidence_score": null,
  "confidence_band": null,
  "confidence_signals": [],
  "caution": null,
  "abstention_reason_code": "period_outside_coverage",
  "clarifying_question": null,
  "transcript": null,
  "synthetic_data": true,
  "dataset_version": 1,
  "schema_kb_version": 1
}
```

> The coverage dates are the **only** numbers permitted in an abstention's answer text. Everything
> else is empty by contract — do not render a table.

### E. Clarification requested

```json
{
  "turn_id": "44f0a1c9-7d3b-4e58-8c62-b1a5e07f9d34",
  "session_id": "8f1c3d2a-5e47-4b91-9c0d-2a7e5f1b4c88",
  "outcome": "clarification_requested",
  "answer_text": null,
  "resolved_question": null,
  "resolved_date_range": null,
  "executed_sql": null,
  "applied_filters": [],
  "excluded_record_count": null,
  "metric_name": null,
  "resolution_path": null,
  "breakdown_columns": [],
  "breakdown_preview": [],
  "total_row_count": null,
  "computation_records": [],
  "figure_provenance": [],
  "anomaly_callouts": [],
  "confidence_score": null,
  "confidence_band": null,
  "confidence_signals": [],
  "caution": null,
  "abstention_reason_code": null,
  "clarifying_question": {
    "question": "Which vendor did you mean — Acme Industrial or Acme Logistics?",
    "options": ["Acme Industrial", "Acme Logistics"],
    "ambiguity": "entity"
  },
  "transcript": null,
  "synthetic_data": true,
  "dataset_version": 1,
  "schema_kb_version": 1
}
```

Reply with `POST /api/sessions/{sid}/clarifications` `{ "answer": "Acme Industrial" }`, which returns
a fresh `TurnResponse`. Note `ClarifyingQuestion`'s field names are **not pinned** — see §10.
