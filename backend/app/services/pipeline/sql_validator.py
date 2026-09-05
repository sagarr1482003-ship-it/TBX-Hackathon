"""SQL_Validator — the static, non-LLM safe-execution boundary (design F-5, §4.3).

This is the security boundary. It is an **allowlist**: the AST is walked once, and any
node type outside the accepted set, any non-allowlisted function, any row-locking or
result-target construct, or any statement whose root is not a SELECT/read-only WITH is a
rejection. Validation that does not reach an explicit accept verdict is a rejection
(Requirement 12.13), including a 100 ms budget breach, which is a guardrail violation.

``AcceptVerdict.canonical_sql`` is regenerated from the AST, so the executor never sees a
model-authored string (Property 33).

The validator depends only on a :class:`SchemaLookup` for schema conformance, so it runs
with no database (the in-memory fake satisfies the protocol).
"""

from __future__ import annotations

import time

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import traverse_scope

from app.config import Settings, get_settings
from app.schemas.enums import IntentFamily
from app.schemas.validation import AcceptVerdict, RejectVerdict, Verdict
from app.services.knowledge.schema_lookup import SchemaLookup

# Intent families that were treated as record listings when a default LIMIT was auto-injected.
# NOTE: default-LIMIT injection has been removed (queries return their full result set, bounded
# downstream by the execution row cap), so this set and ``_is_row_listing`` below are no longer
# wired into validation. Kept for reference / possible re-enablement.
LISTING_FAMILIES: frozenset[str] = frozenset(
    {"transaction_lookup", "reference_lookup"}
)

# Statement-level constructs that are always forbidden (DDL/DML/TCL/privilege/session).
_FORBIDDEN_STATEMENT_TYPES: tuple[type[exp.Expression], ...] = (
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
)

# Accepted node types: the structural nodes required for read-only SELECT/WITH queries,
# joins, filters, grouping, ordering, set operations, row limits and expressions. Function
# nodes are handled separately (typed Func subclasses are checked against the function
# allowlist; the untyped exp.Anonymous is always rejected).
_ACCEPTED_NODE_TYPES: frozenset[type[exp.Expression]] = frozenset(
    {
        exp.Select,
        exp.With,
        exp.CTE,
        exp.Subquery,
        exp.Union,
        exp.Intersect,
        exp.Except,
        exp.From,
        exp.Join,
        exp.Where,
        exp.Group,
        exp.Having,
        exp.Order,
        exp.Ordered,
        exp.Limit,
        exp.Offset,
        exp.Distinct,
        exp.Table,
        exp.TableAlias,
        exp.Column,
        exp.Alias,
        exp.Star,
        exp.Identifier,
        exp.Literal,
        exp.Boolean,
        exp.Null,
        exp.Placeholder,
        exp.Parameter,
        exp.Var,
        exp.Paren,
        exp.Tuple,
        exp.Case,
        exp.If,
        exp.Cast,
        exp.TryCast,
        exp.DataType,
        exp.DataTypeParam,
        exp.Interval,
        # boolean / comparison / arithmetic operators
        exp.And,
        exp.Or,
        exp.Not,
        exp.EQ,
        exp.NEQ,
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.Is,
        exp.Like,
        exp.ILike,
        exp.In,
        exp.Between,
        exp.Add,
        exp.Sub,
        exp.Mul,
        exp.Div,
        exp.Mod,
        exp.Neg,
        exp.Bracket,
        exp.Window,
        exp.WindowSpec,
        exp.Filter,  # aggregate FILTER (WHERE ...) — safe, read-only SQL-standard clause
        exp.Anonymous,  # present in the walk but rejected explicitly below
    }
)

# The default function allowlist: built-in aggregate, window, mathematical, string,
# date-time, casting and conditional functions. Any typed Func subclass whose SQL name is
# in this set is accepted; everything else (including exp.Anonymous) is rejected. Names are
# upper-case as sqlglot emits them via sql_name().
_DEFAULT_FUNCTION_ALLOWLIST: frozenset[str] = frozenset(
    {
        # aggregate
        "SUM", "COUNT", "AVG", "MIN", "MAX", "STDDEV", "STDDEV_POP", "STDDEV_SAMP",
        "VARIANCE", "VAR_POP", "VAR_SAMP", "COUNTIF", "ARRAY_AGG", "STRING_AGG",
        "GROUP_CONCAT", "PERCENTILE_CONT", "PERCENTILE_DISC",
        # window
        "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
        "NTILE", "CUME_DIST", "PERCENT_RANK",
        # mathematical
        "ABS", "CEIL", "CEILING", "FLOOR", "ROUND", "TRUNC", "MOD", "POWER", "POW",
        "SQRT", "EXP", "LN", "LOG", "SIGN", "GREATEST", "LEAST",
        # string
        "LOWER", "UPPER", "LENGTH", "CHAR_LENGTH", "TRIM", "LTRIM", "RTRIM", "SUBSTRING",
        "SUBSTR", "CONCAT", "CONCAT_WS", "REPLACE", "SPLIT_PART", "LEFT", "RIGHT",
        "POSITION", "INITCAP", "REPEAT", "LPAD", "RPAD", "REGEXP_REPLACE",
        # date-time
        "DATE", "DATE_TRUNC", "DATE_PART", "EXTRACT", "DATE_ADD", "DATE_SUB", "DATEDIFF",
        "NOW", "CURRENT_DATE", "CURRENT_TIMESTAMP", "AGE", "TO_CHAR", "TO_DATE",
        "TO_TIMESTAMP", "MAKE_DATE",
        # canonical sqlglot spellings of the above date/time and string functions
        "TIMESTAMP_TRUNC", "TIME_TO_STR", "STR_TO_TIME", "STR_TO_DATE", "TS_OR_DS_TO_DATE",
        # casting / conditional
        "CAST", "TRY_CAST", "COALESCE", "NULLIF", "GREATEST", "LEAST", "CASE", "IF",
        "IFNULL", "NVL",
    }
)


def _func_names(node: exp.Func) -> set[str]:
    """Return every identifier a function node might be known by.

    SQLGlot canonicalises function names (``DATE_TRUNC`` -> ``TIMESTAMP_TRUNC``,
    ``STRING_AGG`` -> ``GROUP_CONCAT``, ``NVL`` -> ``COALESCE``). Matching against the
    surface name, the canonical ``sql_name()`` and the class name makes the allowlist
    stable regardless of which surface spelling the generator used.
    """
    names: set[str] = set()
    try:
        names.add(node.sql_name().upper())
    except Exception:  # pragma: no cover - defensive
        pass
    names.add(type(node).__name__.upper())
    raw = getattr(node, "name", "") or ""
    if raw:
        names.add(raw.upper())
    return names


def _declared_limit(root: exp.Expression) -> int | None:
    limit = root.args.get("limit")
    if limit is None and isinstance(root, exp.Select):
        limit = root.args.get("limit")
    if limit is None:
        return None
    expr = limit.expression if isinstance(limit, exp.Limit) else limit
    if isinstance(expr, exp.Literal) and expr.is_int:
        return int(expr.name)
    return None


def _is_row_listing(root: exp.Expression) -> bool:
    """True when the query returns raw rows that should be capped by a default LIMIT.

    A query is NOT a row listing (so gets no injected LIMIT) when:
      * it is grouped (GROUP BY) or a scalar aggregate (every projection is an aggregate) — those
        return a bounded number of rows; or
      * it narrows to a specific entity via an equality filter on an id/key column
        (account_id, transaction_id, bank_code, transaction_reference_id) — e.g. a balance lookup
        or one account's rows — where a blanket LIMIT is misleading noise.
    A genuinely broad scan with none of the above keeps the default LIMIT as a real guardrail.
    """
    select = root if isinstance(root, exp.Select) else root.find(exp.Select)
    if select is None:
        return True  # be safe: cap unknown shapes
    if select.args.get("group"):
        return False  # grouped -> bounded rows
    projections = select.expressions or []
    if projections and all(p.find(exp.AggFunc) is not None for p in projections):
        return False  # scalar aggregate (e.g. SELECT COUNT(*), SUM(x)) -> single row
    # Equality filter on an identifier column -> single-entity lookup, no blanket LIMIT.
    _ID_COLS = {"account_id", "transaction_id", "bank_code", "transaction_reference_id",
                "entity_id"}
    where = select.args.get("where")
    if where is not None:
        for eq in where.find_all(exp.EQ):
            col = eq.find(exp.Column)
            if col is not None and col.name.lower() in _ID_COLS:
                return False
    return True


class SqlValidator:
    """Static SQLGlot AST validator enforcing the read-only allowlist."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.function_allowlist = _DEFAULT_FUNCTION_ALLOWLIST

    def validate(
        self,
        sql: str,
        schema: SchemaLookup,
        intent_family: IntentFamily,
        parameters: dict | None = None,
    ) -> Verdict:
        """Validate one candidate. Returns an ``AcceptVerdict`` or ``RejectVerdict``."""
        t0 = time.monotonic()
        parameters = dict(parameters or {})

        try:
            statements = sqlglot.parse(sql, dialect="postgres")
        except ParseError as exc:
            return RejectVerdict(reason=str(exc), category="parse_error")
        except Exception as exc:  # any parser failure is a rejection, not a bypass
            return RejectVerdict(reason=f"parse failure: {exc}", category="parse_error")

        statements = [s for s in statements if s is not None]
        if len(statements) != 1:
            return RejectVerdict(
                reason=f"expected exactly one statement, got {len(statements)}",
                category="multiple_statements",
            )
        root = statements[0]

        # Root must be a SELECT, a set operation of SELECTs, or a read-only WITH.
        if not self._is_read_only_root(root):
            return RejectVerdict(
                reason="root statement is not a read-only SELECT/WITH",
                category="statement_type",
                guardrail_violation=True,
            )

        # Single allowlist walk.
        for node in root.walk():
            # Explicit forbidden statement constructs first (defence in depth).
            if isinstance(node, _FORBIDDEN_STATEMENT_TYPES):
                return RejectVerdict(
                    reason=f"forbidden construct {type(node).__name__}",
                    category="statement_type",
                    guardrail_violation=True,
                )
            if isinstance(node, exp.Lock) or (
                isinstance(node, exp.Select) and node.args.get("locks")
            ):
                return RejectVerdict(
                    reason="row-locking clause is forbidden",
                    category="row_locking",
                    guardrail_violation=True,
                )
            if isinstance(node, exp.Into):
                return RejectVerdict(
                    reason="result-target clause (SELECT INTO) is forbidden",
                    category="result_target",
                    guardrail_violation=True,
                )
            # An untyped function is always rejected: it is a name SQLGlot does not model,
            # which is exactly the file-reading / network / sleep family we exclude.
            if isinstance(node, exp.Anonymous):
                return RejectVerdict(
                    reason=f"function {node.name!r} is not allowlisted",
                    category="function_not_allowlisted",
                    guardrail_violation=True,
                )
            # Structural/operator nodes (including operators like And/Or/EQ that inherit
            # from exp.Func) are accepted when their type is in the allowlist.
            if type(node) in _ACCEPTED_NODE_TYPES:
                continue
            # A typed function node not in the structural allowlist: check the function
            # name against the function allowlist.
            if isinstance(node, exp.Func):
                names = _func_names(node)
                if not (names & self.function_allowlist):
                    return RejectVerdict(
                        reason=f"function {sorted(names)} is not allowlisted",
                        category="function_not_allowlisted",
                        guardrail_violation=True,
                    )
                continue
            # Anything else is an unrecognised node type — reject (Requirement 12.13).
            return RejectVerdict(
                reason=f"node type {type(node).__name__} is not allowlisted",
                category="node_type_not_allowlisted",
                guardrail_violation=True,
            )

        # Schema conformance: every referenced table/column must exist / resolve.
        ref = self._resolve_references(root, schema)
        if isinstance(ref, RejectVerdict):
            return ref
        referenced_tables, referenced_columns = ref

        # Row-limit ceiling. A user/generator-declared LIMIT above the max is rejected; but we no
        # longer inject a default LIMIT when none is declared — listing queries return their full
        # result set (bounded downstream by the execution row cap / preview fetch), rather than
        # being silently capped to a substituted default.
        limit = _declared_limit(root)
        if limit is not None and limit > self.settings.max_declared_row_limit:
            return RejectVerdict(
                reason=f"declared row limit {limit} exceeds maximum "
                f"{self.settings.max_declared_row_limit}",
                category="row_limit_too_large",
            )
        applied_row_limit = limit

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if elapsed_ms > 100.0:
            return RejectVerdict(
                reason=f"validation exceeded 100 ms budget ({elapsed_ms:.1f} ms)",
                category="validation_timeout",
                guardrail_violation=True,
            )

        canonical_sql = root.sql(dialect="postgres")
        return AcceptVerdict(
            canonical_sql=canonical_sql,
            parameters=parameters,
            referenced_tables=sorted(referenced_tables),
            referenced_columns=sorted(referenced_columns),
            applied_row_limit=applied_row_limit,
            intent_family=intent_family,
            validation_ms=elapsed_ms,
        )

    # ---------------------------------------------------------------------------------
    @staticmethod
    def _is_read_only_root(root: exp.Expression) -> bool:
        def select_like(node: exp.Expression) -> bool:
            return isinstance(node, (exp.Select, exp.Union, exp.Intersect, exp.Except))

        if select_like(root):
            return True
        if isinstance(root, exp.With):
            body = root.this
            if not select_like(body):
                return False
            for cte in root.find_all(exp.CTE):
                if not select_like(cte.this):
                    return False
            return True
        return False

    def _resolve_references(
        self, root: exp.Expression, schema: SchemaLookup
    ) -> tuple[set[str], set[str]] | RejectVerdict:
        """Resolve and check every table and column reference via scope traversal."""
        referenced_tables: set[str] = set()
        referenced_columns: set[str] = set()

        try:
            scopes = traverse_scope(root)
        except Exception as exc:  # unresolved scope is a rejection, not a bypass
            return RejectVerdict(
                reason=f"could not resolve query scope: {exc}",
                category="unknown_identifier",
            )

        for scope in scopes:
            # Map source alias/name -> ("table", real_name) or ("scope", output_columns).
            source_kind: dict[str, tuple[str, object]] = {}
            for alias, source in scope.sources.items():
                if isinstance(source, exp.Table):
                    real = source.name
                    if not schema.has_table(real):
                        return RejectVerdict(
                            reason=f"table {real!r} is not in the active schema",
                            category="unknown_identifier",
                        )
                    referenced_tables.add(real.lower())
                    source_kind[alias.lower()] = ("table", real)
                else:
                    # A sub-scope (CTE or subquery): its output column names.
                    try:
                        out_cols = {
                            (s.alias_or_name or "").lower() for s in source.expression.selects
                        }
                    except Exception:
                        out_cols = set()
                    source_kind[alias.lower()] = ("scope", out_cols)

            # Output aliases defined by this scope's SELECT list. GROUP BY / ORDER BY /
            # HAVING may reference these aliases rather than base columns. Only *explicit*
            # AS aliases count — a bare column projection is not an alias, so an unknown
            # bare column in the SELECT list is still rejected.
            output_aliases: set[str] = set()
            try:
                for projection in scope.expression.selects:
                    if isinstance(projection, exp.Alias):
                        name = projection.alias
                        if name:
                            output_aliases.add(name.lower())
            except Exception:
                pass

            for column in scope.columns:
                col_name = column.name.lower()
                tbl = column.table.lower() if column.table else ""
                if not tbl and col_name in output_aliases:
                    # Reference to a select-list alias; resolved within this scope.
                    continue
                if tbl:
                    if tbl not in source_kind:
                        return RejectVerdict(
                            reason=f"qualifier {column.table!r} is not a relation in scope",
                            category="unknown_identifier",
                        )
                    kind, payload = source_kind[tbl]
                    if kind == "table":
                        real = str(payload)
                        if col_name != "*" and not schema.has_column(real, col_name):
                            return RejectVerdict(
                                reason=f"column {column.table}.{column.name} does not exist",
                                category="unknown_identifier",
                            )
                        referenced_columns.add(f"{real.lower()}.{col_name}")
                    else:
                        out_cols = payload  # type: ignore[assignment]
                        if col_name != "*" and out_cols and col_name not in out_cols:
                            return RejectVerdict(
                                reason=f"column {column.table}.{column.name} is not produced "
                                f"by the referenced subquery",
                                category="unknown_identifier",
                            )
                else:
                    if col_name == "*":
                        continue
                    owners: list[str] = []
                    for alias, (kind, payload) in source_kind.items():
                        if kind == "table":
                            if schema.has_column(str(payload), col_name):
                                owners.append(alias)
                        else:
                            out_cols = payload  # type: ignore[assignment]
                            if not out_cols or col_name in out_cols:
                                owners.append(alias)
                    if len(owners) == 0:
                        return RejectVerdict(
                            reason=f"column {column.name!r} is not in the active schema",
                            category="unknown_identifier",
                        )
                    if len(owners) > 1:
                        return RejectVerdict(
                            reason=f"column {column.name!r} is ambiguous across "
                            f"{len(owners)} relations",
                            category="ambiguous_identifier",
                        )
                    kind, payload = source_kind[owners[0]]
                    if kind == "table":
                        referenced_columns.add(f"{str(payload).lower()}.{col_name}")

        return referenced_tables, referenced_columns
