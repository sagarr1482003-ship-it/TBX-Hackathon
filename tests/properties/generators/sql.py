"""SQL property generators (task 4.1).

* :func:`hostile_sql` — statements that MUST be rejected by the ``SqlValidator``: stacked
  statements, DDL, DML, ``FOR UPDATE``/``FOR SHARE``, ``SELECT INTO``, ``CREATE TABLE AS``,
  ``COPY ... TO``, ``pg_read_file``, ``pg_sleep``, ``dblink``, ``lo_import``,
  ``current_setting``, unknown identifiers, join-ambiguous unqualified columns,
  over-maximum row limits, and comment-obfuscated variants of each.
* :func:`well_formed_select` — SELECTs over the fixed fake schema that MUST be accepted:
  joins, CTEs, grouping, ordering, set operations and allowlisted functions.
* :func:`metric_binding` — bound Metric_Layer-style statements (also must be accepted).

The pair makes Property 1 two-sided: nothing hostile may be accepted, and everything
well-formed must be, which catches an over-tight allowlist as well as an over-loose one.

The generators are written against a fixed in-memory schema so they need no database.
"""

from __future__ import annotations

from hypothesis import strategies as st

# The fixed schema the generators (and the gate test) build SQL over.
FAKE_SCHEMA: dict[str, list[str]] = {
    "vendors": ["id", "name", "category"],
    "payouts": ["id", "vendor_id", "amount", "status", "paid_on"],
    "transactions": ["id", "account_id", "amount", "txn_date", "category"],
    "accounts": ["id", "account_name"],
}

_HOSTILE_STATEMENTS: list[str] = [
    # stacked statements
    "SELECT id FROM vendors; DROP TABLE vendors",
    "SELECT 1; SELECT 2",
    # DDL
    "DROP TABLE vendors",
    "CREATE TABLE evil (id int)",
    "ALTER TABLE vendors ADD COLUMN x int",
    "TRUNCATE TABLE payouts",
    # DML
    "INSERT INTO vendors (id) VALUES (1)",
    "UPDATE vendors SET name = 'x'",
    "DELETE FROM vendors",
    # transaction / privilege / session
    "GRANT SELECT ON vendors TO public",
    "SET search_path = evil",
    "BEGIN",
    "COMMIT",
    # row locking
    "SELECT id FROM vendors FOR UPDATE",
    "SELECT id FROM vendors FOR SHARE",
    "SELECT id FROM vendors FOR NO KEY UPDATE",
    "SELECT id FROM vendors FOR KEY SHARE",
    # result targets
    "SELECT id INTO newt FROM vendors",
    "CREATE TABLE snap AS SELECT id FROM vendors",
    "COPY vendors TO '/tmp/out.csv'",
    "COPY (SELECT id FROM vendors) TO '/tmp/out.csv'",
    # dangerous functions
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_sleep(10) FROM vendors",
    "SELECT dblink('x', 'y') FROM vendors",
    "SELECT lo_import('/etc/passwd') FROM vendors",
    "SELECT current_setting('x') FROM vendors",
    "SELECT pg_read_binary_file('/etc/passwd')",
    "SELECT txid_current() FROM vendors",
    # unknown identifiers
    "SELECT nonexistent_column FROM vendors",
    "SELECT id FROM nonexistent_table",
    "SELECT v.nope FROM vendors v",
    # ambiguous unqualified column across a join (id exists on both)
    "SELECT id FROM vendors JOIN payouts ON vendors.id = payouts.vendor_id",
    # over-maximum row limit
    "SELECT id FROM vendors LIMIT 200000",
    "SELECT id FROM transactions LIMIT 999999",
]

# Comment-obfuscated variants of a representative dangerous subset.
_COMMENT_OBFUSCATED: list[str] = [
    "SELECT id FROM vendors /* comment */; DROP TABLE vendors",
    "SELECT /* x */ pg_sleep(1) FROM vendors",
    "SELECT id FROM vendors -- trailing\nFOR UPDATE",
    "/* lead */ DROP TABLE vendors",
    "SELECT pg_read_file('/etc/passwd') -- read a file",
]


def hostile_sql() -> st.SearchStrategy[str]:
    """Statements that must never be accepted."""
    return st.sampled_from(_HOSTILE_STATEMENTS + _COMMENT_OBFUSCATED)


# ---- well-formed SELECTs (must be accepted) ------------------------------------------

_WELL_FORMED: list[str] = [
    "SELECT name FROM vendors",
    "SELECT COUNT(*) AS n FROM payouts",
    "SELECT SUM(amount) AS total FROM payouts",
    "SELECT vendor_id, SUM(amount) AS total FROM payouts GROUP BY vendor_id",
    "SELECT vendor_id, SUM(amount) AS total FROM payouts GROUP BY vendor_id "
    "ORDER BY total DESC",
    "SELECT v.name, SUM(p.amount) AS total FROM vendors v "
    "JOIN payouts p ON v.id = p.vendor_id GROUP BY v.name",
    "WITH s AS (SELECT vendor_id, SUM(amount) AS total FROM payouts GROUP BY vendor_id) "
    "SELECT vendor_id, total FROM s ORDER BY total DESC",
    "SELECT category, AVG(amount) AS avg_amt FROM transactions GROUP BY category "
    "HAVING AVG(amount) > 0",
    "SELECT status, COUNT(*) AS n FROM payouts GROUP BY status",
    "SELECT name FROM vendors UNION SELECT account_name FROM accounts",
    "SELECT ROUND(SUM(amount), 2) AS total FROM payouts",
    "SELECT COALESCE(name, 'unknown') AS vname FROM vendors",
    "SELECT UPPER(name) AS uname FROM vendors ORDER BY uname",
    "SELECT id FROM transactions WHERE amount > 100 AND category = 'ops'",
    "SELECT DATE_TRUNC('month', txn_date) AS m, SUM(amount) AS total "
    "FROM transactions GROUP BY m ORDER BY m",
]


def well_formed_select() -> st.SearchStrategy[str]:
    """SELECTs over the fake schema that must all be accepted."""
    return st.sampled_from(_WELL_FORMED)


# ---- bound metric-layer statements (must be accepted) --------------------------------

_METRIC_BINDINGS: list[tuple[str, dict]] = [
    (
        "SELECT SUM(amount) AS total FROM payouts WHERE vendor_id = :vendor_id "
        "AND paid_on BETWEEN :start AND :end",
        {"vendor_id": 7, "start": "2024-01-01", "end": "2024-03-31"},
    ),
    (
        "SELECT id, amount, status FROM payouts WHERE status = :status",
        {"status": "unreconciled"},
    ),
    (
        "SELECT category, SUM(amount) AS total FROM transactions "
        "WHERE txn_date BETWEEN :start AND :end GROUP BY category",
        {"start": "2024-01-01", "end": "2024-12-31"},
    ),
]


def metric_binding() -> st.SearchStrategy[tuple[str, dict]]:
    """Bound metric-layer statements, each with a parameter set."""
    return st.sampled_from(_METRIC_BINDINGS)
