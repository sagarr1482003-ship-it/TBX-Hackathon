"""Schema_Linker — hybrid keyword+vector retrieval of the minimal sub-schema (Requirement 3,
Task 3.3), following the design's ``link()`` pseudocode.

The *scoring and budget-fill* core is pure and unit-tested here. The keyword/vector retrieval over
the Schema_KB (``ops.schema_kb_search_keyword`` / ``_vector``) is UNVERIFIED because it needs
PostgreSQL + pgvector.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def combine_scores(
    keyword: dict[str, float],
    vector: dict[str, float],
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> dict[str, float]:
    """Combine two arms, each already normalised to 0..1, into one 0.000..1.000 score.

    Design: ``score = kw_w * kw + vec_w * vec`` over the union of entries (Requirement 3.7).
    """
    entries = set(keyword) | set(vector)
    return {
        e: keyword_weight * keyword.get(e, 0.0) + vector_weight * vector.get(e, 0.0)
        for e in entries
    }


def apply_threshold(scores: dict[str, float], minimum: float) -> set[str]:
    """Entries clearing the minimum combined retrieval score (Requirement 3.11)."""
    return {e for e, s in scores.items() if s >= minimum}


@dataclass
class SchemaChunk:
    entry_id: str
    token_cost: int
    is_table: bool
    edge_participant: bool = False


@dataclass
class BudgetFillResult:
    selected: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


def fill_to_budget(
    ordered: list[SchemaChunk], token_budget: int
) -> BudgetFillResult:
    """Fill the prompt-token budget in the given order (Requirement 3.8).

    ``ordered`` must already be arranged tables-first, then edge-participating columns, then the
    remaining columns by descending combined score. Entries that do not fit are excluded and
    reported.
    """
    result = BudgetFillResult()
    used = 0
    for chunk in ordered:
        if used + chunk.token_cost <= token_budget:
            result.selected.append(chunk.entry_id)
            used += chunk.token_cost
        else:
            result.excluded.append(chunk.entry_id)
    return result


def order_chunks(
    scores: dict[str, float],
    tables: set[str],
    edge_columns: set[str],
    other_columns: set[str],
    token_costs: dict[str, int],
) -> list[SchemaChunk]:
    """Arrange chunks tables-first, then edge columns, then other columns by score (R3.8)."""
    ordered: list[SchemaChunk] = []
    for t in sorted(tables, key=lambda e: -scores.get(e, 0.0)):
        ordered.append(SchemaChunk(t, token_costs.get(t, 1), is_table=True))
    for c in sorted(edge_columns, key=lambda e: -scores.get(e, 0.0)):
        ordered.append(SchemaChunk(c, token_costs.get(c, 1), is_table=False, edge_participant=True))
    for c in sorted(other_columns, key=lambda e: -scores.get(e, 0.0)):
        ordered.append(SchemaChunk(c, token_costs.get(c, 1), is_table=False))
    return ordered


def shortest_join_paths(
    tables: set[str], edges: dict[tuple[str, str], None], max_len: int
) -> set[tuple[str, str]]:
    """Return edges on shortest paths connecting selected tables up to ``max_len`` (R3.12).

    ``edges`` is an undirected edge set keyed by an ordered (a, b) tuple. A simple BFS between
    every pair of selected tables, bounded by ``max_len`` edges.
    """
    adj: dict[str, set[str]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    def path_edges(src: str, dst: str) -> set[tuple[str, str]] | None:
        # BFS tracking the path.
        from collections import deque

        queue: deque[tuple[str, list[str]]] = deque([(src, [src])])
        seen = {src}
        while queue:
            node, path = queue.popleft()
            if node == dst:
                out: set[tuple[str, str]] = set()
                for i in range(len(path) - 1):
                    a, b = path[i], path[i + 1]
                    out.add((a, b) if (a, b) in edges else (b, a))
                return out
            if len(path) - 1 >= max_len:
                continue
            for nxt in adj.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, path + [nxt]))
        return None

    result: set[tuple[str, str]] = set()
    table_list = sorted(tables)
    for i in range(len(table_list)):
        for j in range(i + 1, len(table_list)):
            found = path_edges(table_list[i], table_list[j])
            if found:
                result |= found
    return result
