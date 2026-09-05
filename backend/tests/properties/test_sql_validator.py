"""Gate: Properties 1 and 2 (task 4.3).

Property 1 — Only read-only, allowlisted SQL is ever accepted. Two-sided:
  * nothing from ``hostile_sql()`` is accepted;
  * everything from ``well_formed_select()`` and ``metric_binding()`` is accepted.
Property 2 — Accepted SQL references only the active schema: every accepted candidate's
tables and columns exist in the pinned Schema_KB.

This gate must be green before any model authors SQL (task 7.8). It runs entirely against
an in-memory fake Schema_KB — no database.
"""

from __future__ import annotations

import sqlglot
from hypothesis import given
from sqlglot import exp

from app.schemas.validation import AcceptVerdict, RejectVerdict
from app.services.knowledge.schema_lookup import InMemorySchemaKB
from app.services.pipeline.sql_validator import SqlValidator
from tests.properties.generators.sql import (
    FAKE_SCHEMA,
    hostile_sql,
    metric_binding,
    well_formed_select,
)

_KB = InMemorySchemaKB(FAKE_SCHEMA)
_VALIDATOR = SqlValidator()

# Node types that must never appear in an accepted, canonical statement.
_FORBIDDEN_IN_ACCEPTED = (
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.TruncateTable,
    exp.Grant,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Copy,
    exp.Command,
    exp.Lock,
    exp.Into,
    exp.Anonymous,
)


# ---------- Property 1, negative side: nothing hostile is accepted --------------------
@given(sql=hostile_sql())
def test_property1_hostile_is_never_accepted(sql: str) -> None:
    verdict = _VALIDATOR.validate(sql, _KB, "transaction_lookup")
    assert isinstance(verdict, RejectVerdict), f"hostile SQL was accepted: {sql!r}"


# ---------- Property 1, positive side: well-formed SELECTs are accepted ---------------
@given(sql=well_formed_select())
def test_property1_well_formed_is_accepted(sql: str) -> None:
    verdict = _VALIDATOR.validate(sql, _KB, "account_spend")
    assert isinstance(verdict, AcceptVerdict), (
        f"well-formed SQL was rejected: {sql!r} -> "
        f"{getattr(verdict, 'category', None)}: {getattr(verdict, 'reason', None)}"
    )


@given(binding=metric_binding())
def test_property1_metric_binding_is_accepted(binding: tuple[str, dict]) -> None:
    sql, params = binding
    verdict = _VALIDATOR.validate(sql, _KB, "reference_lookup", params)
    assert isinstance(verdict, AcceptVerdict), (
        f"metric binding rejected: {sql!r} -> {getattr(verdict, 'reason', None)}"
    )
    # The bound parameters survive onto the verdict (Requirement 12.15).
    assert verdict.parameters == params


# ---------- Property 1: accepted canonical SQL carries no forbidden node --------------
@given(sql=well_formed_select())
def test_property1_accepted_canonical_has_no_forbidden_node(sql: str) -> None:
    verdict = _VALIDATOR.validate(sql, _KB, "account_spend")
    assert isinstance(verdict, AcceptVerdict)
    parsed = sqlglot.parse(verdict.canonical_sql, dialect="postgres")
    assert len(parsed) == 1, "canonical SQL must be exactly one statement"
    for node in parsed[0].walk():
        assert not isinstance(node, _FORBIDDEN_IN_ACCEPTED), (
            f"accepted canonical SQL contains forbidden node {type(node).__name__}"
        )


# ---------- Property 2: accepted SQL references only the active schema -----------------
@given(sql=well_formed_select())
def test_property2_accepted_tables_and_columns_exist(sql: str) -> None:
    verdict = _VALIDATOR.validate(sql, _KB, "account_spend")
    assert isinstance(verdict, AcceptVerdict)
    for table in verdict.referenced_tables:
        assert _KB.has_table(table), f"accepted SQL references unknown table {table!r}"
    for qualified in verdict.referenced_columns:
        table, _, column = qualified.partition(".")
        assert _KB.has_column(table, column), (
            f"accepted SQL references unknown column {qualified!r}"
        )


@given(binding=metric_binding())
def test_property2_metric_binding_references_exist(binding: tuple[str, dict]) -> None:
    sql, params = binding
    verdict = _VALIDATOR.validate(sql, _KB, "reference_lookup", params)
    assert isinstance(verdict, AcceptVerdict)
    for table in verdict.referenced_tables:
        assert _KB.has_table(table)
    for qualified in verdict.referenced_columns:
        table, _, column = qualified.partition(".")
        assert _KB.has_column(table, column)


# ---------- Guardrail-violation flag is set for guardrail rejections ------------------
def test_guardrail_rejections_flag_violation() -> None:
    for sql in [
        "DROP TABLE vendors",
        "SELECT pg_sleep(1) FROM vendors",
        "SELECT id FROM vendors FOR UPDATE",
        "SELECT id INTO t FROM vendors",
    ]:
        verdict = _VALIDATOR.validate(sql, _KB, "transaction_lookup")
        assert isinstance(verdict, RejectVerdict)
        assert verdict.guardrail_violation, f"expected guardrail flag for {sql!r}"


def test_default_row_limit_injected_for_listing() -> None:
    verdict = _VALIDATOR.validate("SELECT id FROM transactions", _KB, "transaction_lookup")
    assert isinstance(verdict, AcceptVerdict)
    assert verdict.applied_row_limit == 1000
    assert "1000" in verdict.canonical_sql


def test_no_default_limit_for_aggregate_intent() -> None:
    verdict = _VALIDATOR.validate("SELECT SUM(amount) AS s FROM payouts", _KB, "account_spend")
    assert isinstance(verdict, AcceptVerdict)
    assert verdict.applied_row_limit is None
