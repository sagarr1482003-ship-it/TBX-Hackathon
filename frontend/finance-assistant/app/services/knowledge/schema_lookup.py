"""Schema lookup abstraction used by the SQL_Validator for schema conformance.

The validator needs one thing from the Schema_KB: given a pinned version, does a table
exist, and does a column exist on a table. This is expressed as a small Protocol so the
real, database-backed ``Schema_KB`` (task 3.x) and the in-memory fake used by property
tests both satisfy it without the validator depending on a database.
"""

from __future__ import annotations

from typing import Protocol


class SchemaLookup(Protocol):
    """Minimal read interface the SQL_Validator needs from a Schema_KB version."""

    def has_table(self, table: str) -> bool:
        ...

    def has_column(self, table: str, column: str) -> bool:
        ...

    def tables(self) -> list[str]:
        ...

    def columns(self, table: str) -> list[str]:
        ...


class InMemorySchemaKB:
    """A concrete, database-free ``SchemaLookup`` for tests and the validator's fast path.

    Schema is a mapping of table name -> ordered column names. Table and column matching
    is case-insensitive, matching PostgreSQL's fold-to-lower behaviour for unquoted
    identifiers.
    """

    def __init__(self, schema: dict[str, list[str]]) -> None:
        self._schema: dict[str, list[str]] = {
            t.lower(): [c.lower() for c in cols] for t, cols in schema.items()
        }

    def has_table(self, table: str) -> bool:
        return table.lower() in self._schema

    def has_column(self, table: str, column: str) -> bool:
        cols = self._schema.get(table.lower())
        return cols is not None and column.lower() in cols

    def tables(self) -> list[str]:
        return list(self._schema.keys())

    def columns(self, table: str) -> list[str]:
        return list(self._schema.get(table.lower(), []))

    def column_owner(self, column: str) -> list[str]:
        """Return every table owning ``column`` (used to resolve unqualified columns)."""
        column = column.lower()
        return [t for t, cols in self._schema.items() if column in cols]
