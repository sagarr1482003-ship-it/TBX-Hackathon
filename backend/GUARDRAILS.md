# TBX Finance Assistant — Hackathon Security & Accuracy Guardrails Architecture

This document details the **10 core guardrails** implemented in the TBX Finance Assistant backend to satisfy the hackathon evaluation criteria: **Grounding & Accuracy (30%)**, **Model Efficiency (20%)**, **Functionality & Resilience (15%)**, and **User Experience (10%)**.

---

## Guardrails Matrix & Implementation Map

| # | Guardrail Name | Type | Purpose / Risk Mitigated | Code File | Verification Test | Status |
|---|---|---|---|---|---|---|
| **1** | **AST Code Security Inspector** | Security | Blocks non-`SELECT` commands (`DROP`, `DELETE`, `UPDATE`) & catalog access via `SQLGlot` static AST analysis. | `app/services/pipeline/sql_validator.py` | `tests/properties/test_sql_validator.py` | 🟢 Verified |
| **2** | **Database Read-Only Lockdown** | Security / DB | Connects using `tbx_reader` role, enforcing 10s statement timeouts and 100k row caps. | `app/services/pipeline/query_executor.py` | `tests/properties/test_query_executor.py` | 🟡 Written (Awaiting PG) |
| **3** | **Zero-Math Python Engine** | Math Precision | Prohibits LLM arithmetic. Calculates totals, growth rates, and rounding in Python `Decimal`. | `app/services/pipeline/computation.py` | `tests/properties/test_computation.py` | 🟢 Verified |
| **4** | **Numeral Verifier** | Grounding | Scans every number in draft text answers and verifies exact match against DB cell values or `ComputationRecord`s. | `app/services/pipeline/groundedness.py` | `tests/properties/test_groundedness.py` | 🟢 Verified |
| **5** | **Wall-Clock Budget & Refusal Guard** | Resilience | Enforces a 30s wall-clock deadline, max 6 LLM calls/12k tokens, emitting 21 machine-readable abstention reasons on failure. | `app/services/pipeline/abstention.py` | `tests/properties/test_abstention.py` | 🟢 Verified |
| **6** | **Schema Linker Token Budget Cap** | Efficiency | Caps schema context fed to LLM at < 1,500 prompt tokens using `pgvector` hybrid search. | `app/services/pipeline/schema_linker.py` | `tests/properties/test_schema_linker.py` | 🟢 Verified |
| **7** | **Entity Disambiguation Margin** | Ambiguity | Halts auto-execution if fuzzy match scores for vendor/category names are tied within 5% margin, asking a clarifying question. | `app/services/pipeline/query_planner.py` | `tests/unit/test_query_planner.py` | 🟢 Verified |
| **8** | **Anomaly Outlier Filter** | Business Impact | Uses Median Absolute Deviation (Z-Score > 3.5) to flag unusual financial spend spikes. | `app/services/pipeline/anomaly.py` | `tests/properties/test_anomaly.py` | 🟢 Verified |
| **9** | **Answer Verbosity Cap** | Output Quality | Caps response length (120 words standard / 400 words detailed) to prevent LLM rambling. | `app/services/pipeline/answer_composer.py` | `tests/unit/test_answer_composer.py` | 🟢 Verified |
| **10** | **API Payload & Timeout Guard** | System Security | Enforces 12MB max request payload and 30s request timeouts on FastAPI REST endpoints. | `app/config.py` | `tests/unit/test_config.py` | 🟢 Verified |

---

## Core Guardrail Specifications

### 1. AST Security Inspector (`sql_validator.py`)
- **Allowed AST Nodes**: `Select`, `With`, `CTE`, `Table`, `Column`, `Where`, `Group`, `Order`, `Limit`, `Join`, `Aggregate`.
- **Forbidden Operations**: `Delete`, `Drop`, `Insert`, `Update`, `Execute`, `Alter`, `Truncate`.
- **System Table Block**: Rejects queries accessing `pg_catalog`, `information_schema`, or system functions (`pg_sleep`, `version`).

### 2. Zero-Math Engine (`computation.py`)
- **Rule**: All aggregations and derived metrics MUST produce a `ComputationRecord`.
- **Zero Denominator Protection**: Emits `undefined_reason="zero_denominator"` when previous period base spend is 0, suppressing invalid growth rates.

### 3. Numeral Verifier (`groundedness.py`)
- **Extraction**: Regex `\b\d+(?:\.\d+)?\b` extracts all numbers from draft LLM answer text.
- **Match Tolerance**: `0.01` numeric tolerance matching against executed DB cells or `ComputationRecord` values.
- **Regeneration & Fallback**: If an ungrounded numeral is detected, draft text is regenerated once; if it fails again, fallback to a templated answer string.
