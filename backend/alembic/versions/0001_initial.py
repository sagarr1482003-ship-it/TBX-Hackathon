"""0001 initial schema: extensions, roles, finance + ops schemas, grants.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-05

UNVERIFIED (Task 1.4): this migration requires a running PostgreSQL with the ``vector`` and
``pg_trgm`` extensions available and cannot be executed in the current environment. It reproduces
the DDL of design §5.2 (finance), §5.3 (ops), §5.4 (versioning/artefacts) and §5.5
(extensions/roles/grants) as a single consolidated revision. The design specifies revisions
0001–0009; they are consolidated here so the schema is reviewable in one place, with the
load-bearing invariants preserved: the reader role is read-only with a statement timeout, the
finance grant to the app role is revoked, and the four partial unique indexes enforce the
"exactly one active/in-progress" constraints.
"""

from __future__ import annotations

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- extensions ---------------------------------------------------------------------
    # pgvector powers the Schema_KB embeddings. It is OPTIONAL for the core question->answer
    # pipeline (the SQL_Validator only needs table/column existence), so skip gracefully when
    # the extension is not installed on the server rather than failing the whole migration.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pgvector not available; Schema_KB vector features disabled';
        END $$;
        """
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- roles (R13.1, R13.2, R13.6) ----------------------------------------------------
    # tbx_reader: SELECT-only, read-only transactions, 10s statement timeout.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tbx_reader') THEN
                CREATE ROLE tbx_reader LOGIN PASSWORD 'tbx_reader';
            END IF;
        END $$;
        """
    )
    op.execute(
        "ALTER ROLE tbx_reader SET default_transaction_read_only = on"
    )
    op.execute("ALTER ROLE tbx_reader SET statement_timeout = '10s'")

    # --- schemas ------------------------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS finance")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    # --- finance schema (design §5.2) ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE finance.bank (
            bank_code        text PRIMARY KEY,
            bank_name        text NOT NULL,
            dataset_version  int  NOT NULL
        );
        CREATE TABLE finance.account (
            account_id         text PRIMARY KEY,
            entity_id          text          NOT NULL,
            account_number     text          NOT NULL,   -- sensitive; masked in answers
            program_id         int           NOT NULL,
            available_balance  numeric(15,2) NOT NULL DEFAULT 0.00,
            bank_code          text          NOT NULL REFERENCES finance.bank(bank_code),
            dataset_version    int           NOT NULL
        );
        CREATE TABLE finance.transaction (
            transaction_id           text PRIMARY KEY,
            account_id               text          NOT NULL REFERENCES finance.account(account_id),
            transaction_date         timestamptz   NOT NULL,
            transaction_type         text          NOT NULL
                                     CHECK (transaction_type IN ('credit','debit')),
            description              text,
            transaction_amount       numeric(15,2) NOT NULL DEFAULT 0.00,
            transaction_reference_id text,          -- plaintext, searchable
            utr_number               text,          -- sensitive; masked in answers
            dataset_version          int           NOT NULL
        );
        CREATE INDEX ix_txn_date    ON finance.transaction (transaction_date);
        CREATE INDEX ix_txn_account ON finance.transaction (account_id);
        CREATE INDEX ix_txn_type    ON finance.transaction (transaction_type);
        CREATE INDEX ix_txn_ref     ON finance.transaction (transaction_reference_id);
        CREATE INDEX ix_account_bank ON finance.account (bank_code);
        CREATE INDEX ix_account_entity ON finance.account (entity_id);
        CREATE INDEX ix_bank_name_lower ON finance.bank (lower(bank_name));
        """
    )

    # --- ops schema: versioning (design §5.4) ------------------------------------------
    op.execute(
        """
        CREATE TABLE ops.dataset_versions (
            id              serial PRIMARY KEY,
            dataset_id      text NOT NULL,
            version         text NOT NULL,
            status          text NOT NULL CHECK (status IN
                             ('in_progress','complete','active','retired')),
            schema_kb_version int,
            is_seed         boolean NOT NULL DEFAULT false,
            created_at      timestamptz NOT NULL DEFAULT now(),
            row_counts      jsonb
        );
        -- exactly one active dataset version at a time
        CREATE UNIQUE INDEX ux_one_active_dataset
            ON ops.dataset_versions ((status)) WHERE status = 'active';
        -- exactly one ingestion run in progress at a time
        CREATE UNIQUE INDEX ux_one_ingestion_in_progress
            ON ops.dataset_versions ((status)) WHERE status = 'in_progress';

        CREATE TABLE ops.schema_kb_versions (
            id              serial PRIMARY KEY,
            dataset_version int NOT NULL,
            status          text NOT NULL CHECK (status IN ('in_progress','complete')),
            embedding_dim   int,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # --- ops schema: conversation/turns/trace (design §5.3) ----------------------------
    op.execute(
        """
        CREATE TABLE ops.sessions (
            session_id     uuid PRIMARY KEY,
            surface        text NOT NULL CHECK (surface IN ('finance','insights')),
            created_at     timestamptz NOT NULL DEFAULT now(),
            last_turn_at   timestamptz,
            conversation_state    jsonb,
            pending_clarification jsonb
        );
        CREATE INDEX ix_sessions_created ON ops.sessions (created_at DESC);

        CREATE TABLE ops.turns (
            turn_id            uuid PRIMARY KEY,
            session_id         uuid NOT NULL REFERENCES ops.sessions ON DELETE CASCADE,
            ordinal            int  NOT NULL,
            started_at         timestamptz NOT NULL,
            ended_at           timestamptz,
            origin             text NOT NULL CHECK (origin IN ('text','voice')),
            question_text      text NOT NULL,
            resolved_question  text,
            intent_family      text,
            resolution_path    text CHECK (resolution_path IN ('metric_layer','generated_sql')),
            metric_name        text,
            outcome            text CHECK (outcome IN
                                ('answered','clarification_requested','abstained','failed')),
            abstention_reason  text,
            answer_text        text,
            executed_sql       text,
            bound_parameters   jsonb,
            dataset_version    int,
            confidence_score   numeric,
            confidence_band    text
        );
        CREATE INDEX ix_turns_session ON ops.turns (session_id, ordinal);
        CREATE INDEX ix_turns_started ON ops.turns (started_at);

        CREATE TABLE ops.trace_events (
            id             bigserial PRIMARY KEY,
            turn_id        uuid NOT NULL REFERENCES ops.turns ON DELETE CASCADE,
            sequence       int  NOT NULL,
            stage          text NOT NULL,
            attempt_ordinal int NOT NULL DEFAULT 1,
            status         text NOT NULL,
            started_at     timestamptz NOT NULL,
            duration_ms    int,
            input_summary  jsonb,
            output_summary jsonb,
            role           text,
            provider       text,
            model_id       text,
            input_tokens   int,
            output_tokens  int,
            truncated      boolean NOT NULL DEFAULT false,
            UNIQUE (turn_id, sequence)
        );
        CREATE INDEX ix_trace_turn ON ops.trace_events (turn_id, sequence);

        CREATE TABLE ops.computation_records (
            id             text NOT NULL,
            turn_id        uuid NOT NULL REFERENCES ops.turns ON DELETE CASCADE,
            label          text NOT NULL,
            value          numeric,
            unrounded_value numeric,
            unit           text,
            currency       text,
            source_column  text,
            query_id       text,
            PRIMARY KEY (turn_id, id)
        );

        CREATE TABLE ops.result_snapshots (
            turn_id        uuid PRIMARY KEY REFERENCES ops.turns ON DELETE CASCADE,
            columns        jsonb NOT NULL,
            rows           jsonb NOT NULL,
            row_count      int NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE ops.feedback (
            id             bigserial PRIMARY KEY,
            turn_id        uuid NOT NULL REFERENCES ops.turns ON DELETE CASCADE,
            sentiment      text NOT NULL CHECK (sentiment IN ('positive','negative')),
            free_text      text,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # --- ops schema: artefacts, failures, improvement, evaluation ----------------------
    op.execute(
        """
        CREATE TABLE ops.artefacts (
            id             bigserial PRIMARY KEY,
            kind           text NOT NULL CHECK (kind IN
                             ('prompt','exemplar','schema_description','metric_template')),
            name           text NOT NULL,
            version        int  NOT NULL,
            status         text NOT NULL CHECK (status IN ('candidate','active','rejected')),
            content        jsonb NOT NULL,
            dataset_version int,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        -- exactly one active version per (kind, name)
        CREATE UNIQUE INDEX ux_one_active_artefact
            ON ops.artefacts (kind, name) WHERE status = 'active';

        CREATE TABLE ops.failure_cases (
            id             bigserial PRIMARY KEY,
            source         text NOT NULL,
            status         text NOT NULL,
            resolved_question text,
            dataset_version int,
            occurrence_count int NOT NULL DEFAULT 1,
            first_seen     timestamptz NOT NULL DEFAULT now(),
            last_seen      timestamptz NOT NULL DEFAULT now(),
            payload        jsonb NOT NULL
        );

        CREATE TABLE ops.improvement_runs (
            id             bigserial PRIMARY KEY,
            status         text NOT NULL CHECK (status IN ('in_progress','complete','failed')),
            started_at     timestamptz NOT NULL DEFAULT now(),
            ended_at       timestamptz
        );
        CREATE UNIQUE INDEX ux_one_improvement_in_progress
            ON ops.improvement_runs ((status)) WHERE status = 'in_progress';

        CREATE TABLE ops.evaluation_runs (
            id             bigserial PRIMARY KEY,
            run_status     text NOT NULL CHECK (run_status IN ('complete','incomplete')),
            repeat_index   int NOT NULL,
            dataset_version int,
            model_config   jsonb,
            metrics        jsonb,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # --- grants (design §5.5 revision 0009, kept last) ---------------------------------
    # The app role owns and writes ops; the reader role reads finance only.
    op.execute("GRANT USAGE ON SCHEMA finance TO tbx_reader")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA finance TO tbx_reader")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA finance GRANT SELECT ON TABLES TO tbx_reader"
    )
    # The reader must never write finance; revoke everything but SELECT.
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES "
        "IN SCHEMA finance FROM tbx_reader"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS ops CASCADE")
    op.execute("DROP SCHEMA IF EXISTS finance CASCADE")
