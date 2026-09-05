# Compliance & Data Protection Posture

TBX handles bank account and transaction data, so it is designed to be **compliance-aware** from
the ground up. This document maps concrete, implemented controls to the regulatory concerns they
address (RBI, SEBI, and India's DPDP Act, 2023).

> **Scope, stated honestly.** TBX is a hackathon **prototype**, single-tenant, running on
> **synthetic data with no real PII**. This is a demonstration of compliance-*aware* design, not a
> claim of RBI/SEBI certification. Production requirements (encryption at rest and in transit, KYC,
> consent management, RBI data-localisation, tenant isolation) are out of scope and listed as the
> roadmap at the end.

## Why this matters here

The data model (`bank` / `account` / `transaction`) contains **account numbers** and **UTRs** —
sensitive financial identifiers. A finance assistant that answers questions over this data must not
leak those identifiers, must not invent figures, and must be auditable. TBX enforces each of these.

## Implemented controls

| Control | How it is enforced | Regulatory concern |
|---|---|---|
| **Sensitive-data masking** | `account_number` and `utr_number` are flagged `sensitive` in the dataset contract; `app/services/pipeline/masking.py` masks them (account number → last-4 only, UTR → fully redacted) before any value reaches an answer, export or trace. Verified by `tests/unit/test_masking.py`. | RBI customer-data protection; DPDP data minimisation |
| **PII encryption at rest** | Sensitive columns are encrypted with **AES-256-GCM** (`app/services/pipeline/pii_crypto.py`) before being written to PostgreSQL and decrypted only in memory on the read path. A database dump or stolen backup exposes ciphertext, not account numbers or UTRs. The 256-bit key lives in secret config only (`PII_ENCRYPTION_KEY`), generated via `scripts/gen_pii_key.py`; GCM's auth tag makes tampering detectable. Verified by `tests/unit/test_pii_crypto.py` (round-trip, tamper-detection, wrong-key). | RBI / DPDP data-at-rest protection |
| **Read-only data access** | The assistant connects through a dedicated `tbx_reader` PostgreSQL role that is `SELECT`-only with `default_transaction_read_only = on`; the `SQL_Validator` is an allowlist that rejects any DDL/DML/privilege/transaction-control statement. A model can never mutate or exfiltrate beyond a read. | RBI data-integrity; least-privilege access |
| **No fabricated figures (grounding)** | Every number in an answer must trace to an executed query result or a computation record; the `Groundedness_Checker` rejects any ungrounded numeral. The model never performs arithmetic. | Fair, accurate, non-misleading financial information (SEBI investor-protection spirit) |
| **Deterministic computation** | All money is `Decimal` end to end — never floating point — so figures are exact and reproducible. | Accurate financial computation |
| **Full audit trail** | Every pipeline step, executed SQL, bound parameter, figure and decision is emitted as a trace event and persisted by turn id, retrievable after the fact. | RBI audit-trail / traceability expectations |
| **Secret & PII redaction in logs** | Configured secrets are redacted from trace payloads (property-tested); sensitive columns are masked in result snapshots and traces via the same masking layer. | DPDP; RBI logging hygiene |
| **Abstention over guessing** | When the data cannot answer or the question is ambiguous, the assistant abstains with a machine-readable reason code rather than producing a number. | Suitability; no misleading output |
| **Not financial advice** | Answers present figures computed from the user's own data; the system provides **information, not investment or financial advice**. A standing disclaimer accompanies analytics answers. | SEBI — avoids unregistered investment-advice territory |

## The two "reference number" columns — a deliberate privacy decision

The schema has two reference-like columns:

- `transaction_reference_id` — **plaintext**, directly searchable;
- `utr_number` — **sensitive**, masked and not exposed raw.

A bare "reference number" question resolves to `transaction_reference_id`; `utr_number` is only
used when the user explicitly says "UTR", and even then its value is masked in the answer. This is
documented in `docs/dataset_contract.md` and enforced by the masking layer.

## Roadmap to production compliance (out of scope for the prototype)

- TLS in transit for all financial data (encryption **at rest** for sensitive columns is
  implemented — see the controls table; key management uses env/secret config, and a production
  deployment would move the key into a managed KMS/HSM with rotation).
- KYC / customer-consent management and DPDP consent artefacts.
- RBI data-localisation (India-resident storage and processing).
- Multi-tenant isolation, authentication and role-based access beyond the prototype's
  shared-secret header.
- Formal data-retention and right-to-erasure workflows (DPDP data-principal rights).
- Independent security review and audit-log tamper-evidence.

These are named explicitly rather than implied, which is itself the responsible posture: the
prototype demonstrates the *controls that protect an answer's integrity and a customer's
identifiers*, and is honest about what a regulated deployment would still require.
