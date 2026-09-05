# Dataset Contract

This is the interface both the synthetic seed dataset and the organisers' delivered dataset must
satisfy. It declares, per entity, the required columns and their types, the allowed
`transaction_type` values, the referential relationships, and — for every rule — a severity of
**blocking** or **tolerable** (Requirement 8.4).

A `blocking` deviation aborts the load and leaves the previously active dataset and Schema_KB
unchanged (Requirement 8.9). A `tolerable` deviation permits the load and is recorded in the
ingestion report (Requirement 8.10). The Ingestion_Service validates a candidate dataset against
every rule below **before loading any row** (Requirement 8.5).

The schema is the organiser-provided **bank / account / transaction** shape: 3 tables, one
database. One bank has many accounts; one account has many transactions.

> **Target database is PostgreSQL.** The organiser DDL is MySQL/InnoDB; the delivered data is
> ingested into our PostgreSQL (keeping pgvector, the SELECT-only `tbx_reader` role and the
> validator's Postgres dialect). Money is `numeric(15,2)`; money is never a float.

## Sensitive columns

`account.account_number` and `transaction.utr_number` are **sensitive**: they must be masked and
never shown raw in an answer. `transaction.transaction_reference_id` is plaintext and searchable.

- A bare "reference number" question resolves to `transaction_reference_id` (plaintext); the
  `utr_number` column is only used when the user explicitly says "UTR".

## Entities

### bank

| column | type | required | severity |
|--------|------|----------|----------|
| bank_code | text | yes (primary key, IFSC prefix e.g. HDFC) | blocking |
| bank_name | text | yes (canonical all-caps name) | blocking |

### account

| column | type | required | severity |
|--------|------|----------|----------|
| account_id | uuid/text | yes (primary key) | blocking |
| entity_id | uuid/text | yes (owning customer/entity) | blocking |
| account_number | text | yes — **sensitive**, masked | blocking |
| program_id | integer | yes | blocking |
| available_balance | numeric(15,2) | yes | blocking |
| bank_code | text | yes (FK → bank.bank_code) | blocking |

### transaction

| column | type | required | severity |
|--------|------|----------|----------|
| transaction_id | uuid/text | yes (primary key) | blocking |
| account_id | uuid/text | yes (FK → account.account_id) | blocking |
| transaction_date | timestamp | yes (`YYYY-MM-DD HH:MM:SS.ssssss`) | blocking |
| transaction_type | text enum | yes — `credit` or `debit` only | blocking; unknown value blocking |
| description | text | no | tolerable |
| transaction_amount | numeric(15,2) | yes | blocking |
| transaction_reference_id | text | no (plaintext, searchable) | tolerable |
| utr_number | text | no — **sensitive**, masked | tolerable |

## Referential relationships

- `account.bank_code` → `bank.bank_code`
- `transaction.account_id` → `account.account_id`

A non-null foreign key that resolves to no parent row is **blocking**.

## Rule severity summary

| rule | severity |
|------|----------|
| missing required column | blocking |
| required-column value null/empty | blocking |
| unknown transaction_type value (not credit/debit) | blocking |
| unresolved non-null foreign key | blocking |
| duplicate primary key | blocking |
| null in a non-key column | tolerable |
| amount exactly 0 | tolerable |
| amount below 0 | tolerable |
| unknown extra column (not in the manifest mapping) | tolerable |
