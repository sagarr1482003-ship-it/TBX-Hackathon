"""Schema_Linker pure-core verification (Task 3.3, Requirement 3.7/3.8/3.11/3.12).

Only the scoring/budget-fill/join-path core is exercised; DB-backed retrieval needs PostgreSQL.
"""

from __future__ import annotations

from app.services.pipeline.schema_linker import (
    apply_threshold,
    combine_scores,
    fill_to_budget,
    order_chunks,
    shortest_join_paths,
)


def test_combine_scores_weighted_union() -> None:
    kw = {"a": 1.0, "b": 0.0}
    vec = {"b": 1.0, "c": 0.5}
    combined = combine_scores(kw, vec, 0.5, 0.5)
    assert combined["a"] == 0.5
    assert combined["b"] == 0.5
    assert combined["c"] == 0.25


def test_apply_threshold() -> None:
    scores = {"a": 0.4, "b": 0.34, "c": 0.9}
    kept = apply_threshold(scores, 0.35)
    assert kept == {"a", "c"}


def test_fill_to_budget_orders_and_excludes() -> None:
    scores = {"t1": 0.9, "c_edge": 0.8, "c_other": 0.7}
    ordered = order_chunks(
        scores,
        tables={"t1"},
        edge_columns={"c_edge"},
        other_columns={"c_other"},
        token_costs={"t1": 2, "c_edge": 2, "c_other": 2},
    )
    # budget fits only the table + edge column
    result = fill_to_budget(ordered, token_budget=4)
    assert result.selected == ["t1", "c_edge"]
    assert result.excluded == ["c_other"]


def test_shortest_join_paths_two_edges() -> None:
    edges = {
        ("transactions", "vendors"): None,
        ("transactions", "accounts"): None,
    }
    # vendors <-> accounts connect only through transactions (2 edges).
    result = shortest_join_paths({"vendors", "accounts"}, edges, max_len=2)
    assert ("transactions", "vendors") in result
    assert ("transactions", "accounts") in result


def test_shortest_join_paths_beyond_max_len_excluded() -> None:
    edges = {
        ("a", "b"): None,
        ("b", "c"): None,
        ("c", "d"): None,
    }
    # a <-> d is 3 edges; with max_len 2 no path is returned.
    result = shortest_join_paths({"a", "d"}, edges, max_len=2)
    assert result == set()
