# Dataset Contract

This is the interface both the synthetic seed dataset and the organisers' delivered dataset must
satisfy. It declares, per entity, the required columns and their types and units, the allowed
reconciliation status values, the referential relationships the Metric_Layer depends on, the
coverage window, and — for every rule — a severity of **blocking** or **tolerable**
(Requirement 8.4).

A `blocking` deviation aborts the load and leaves the previously active dataset and Schema_KB
unchanged (Requirement 8.9). A `tolerable` deviation permits the load and is recorded in the
ingestion report (Requirement 8.10). The Ingestion_Service validates a candidate dataset against
every rule below **before loading any row** (Requirement 8.5), and reports each deviation with the
deviating entity, the violated rule and that rule's declared severity.

Requirement 8.4 fixes four specific severities as **tolerable**: a null value in a non-key column,
a duplicate vendor-name spelling, an amount of exactly 0, and an amount below 0.

## Currency and precision

- Single currency per dataset (`INR` for the seed dataset), stated by the manifest.
- Monetary columns are fixed-precision `numeric(18,2)`; money is never represented as a float.

## Coverage window

- The dataset declares an inclusive first date and an inclusive last date.
- Seed dataset coverage: **2023-01-01 to 2024-12-31**.

## Entities

### vendors

| column | type | required | severity if missing/invalid |
|--------|------|----------|-----------------------------|
| vendor_id | text | yes (primary key) | blocking |
| vendor_name | text | yes | blocking |
| vendor_category | text | no | tolerable |

- Duplicate vendor-name **spelling** (two vendor rows whose names normalise to the same form):
  **tolerable**.

### accounts

| column | type | required | severity |
|--------|------|----------|----------|
| account_code | text | yes (primary key) | blocking |
| account_name | text | yes | blocking |
| account_type | text | no | tolerable |

### transactions

| column | type | unit | required | severity |
|--------|------|------|----------|----------|
| transaction_id | text | — | yes (primary key) | blocking |
| transaction_date | date | — | yes | blocking |
| amount | numeric(18,2) | INR | yes | blocking |
| currency | text | — | yes | blocking |
| vendor_id | text | — | no (FK → vendors) | blocking if present and unresolved |
| account_code | text | — | no (FK → accounts) | blocking if present and unresolved |
| category | text | — | no | tolerable |
| description | text | — | no | tolerable |
| reconciliation_status | text | — | no | tolerable |

- Null in any **non-key** column (`category`, `description`, `reconciliation_status`, `vendor_id`,
  `account_code`): **tolerable**.
- Amount **exactly 0**: **tolerable**.
- Amount **below 0**: **tolerable**.

### vendor_payouts

| column | type | unit | required | severity |
|--------|------|------|----------|----------|
| payout_id | text | — | yes (primary key) | blocking |
| payout_date | date | — | yes | blocking |
| amount | numeric(18,2) | INR | yes | blocking |
| currency | text | — | yes | blocking |
| vendor_id | text | — | yes (FK → vendors) | blocking |
| payout_status | text | — | no | tolerable |
| reference | text | — | no | tolerable |

### reconciliation

| column | type | required | severity |
|--------|------|----------|----------|
| reconciliation_id | text | yes (primary key) | blocking |
| transaction_id | text | yes (FK → transactions) | blocking |
| status | text | yes | blocking |
| matched_at | timestamp | no | tolerable |
| note | text | no | tolerable |

## Allowed reconciliation status values

`unreconciled`, `reconciled`, `pending`, `disputed`.

- A `reconciliation_status` / `status` value **outside** this set: **blocking**.

## Referential relationships the Metric_Layer depends on

- `transactions.vendor_id` → `vendors.vendor_id`
- `transactions.account_code` → `accounts.account_code`
- `vendor_payouts.vendor_id` → `vendors.vendor_id`
- `reconciliation.transaction_id` → `transactions.transaction_id`

A referenced key that resolves to no parent row is **blocking**, except that a **null** foreign key
in a non-key column of `transactions` is tolerable (an unlinked transaction is permitted).

## Rule severity summary

| rule | severity |
|------|----------|
| missing required column | blocking |
| required-column value null/empty | blocking |
| unknown reconciliation status value | blocking |
| unresolved non-null foreign key | blocking |
| duplicate primary key | blocking |
| null in a non-key column | tolerable |
| duplicate vendor-name spelling | tolerable |
| amount exactly 0 | tolerable |
| amount below 0 | tolerable |
| unknown extra column (not in the manifest mapping) | tolerable |
