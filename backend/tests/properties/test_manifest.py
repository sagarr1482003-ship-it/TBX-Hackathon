"""Property 11: Manifest serialisation round-trips.

Two-sided:
  * a valid manifest, serialised to a dict/JSON and re-loaded, is equal to the original
    (round-trip equivalence);
  * an incomplete manifest (missing required entity/column data) or an unsupported
    ``source_mode`` is rejected before any load.

Pure logic — no database.
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.manifest import (
    ColumnSpec,
    CoverageWindow,
    DatasetManifest,
    EntitySpec,
    JoinSpec,
    LocalFileSource,
    MetricDefinition,
    MetricParameter,
    extract_binds,
)

_ident = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_column_types = st.sampled_from(["text", "integer", "numeric", "date", "timestamp", "boolean"])


@st.composite
def column_specs(draw, names: set[str]) -> ColumnSpec:
    name = draw(_ident.filter(lambda n: n not in names))
    names.add(name)
    ctype = draw(_column_types)
    return ColumnSpec(
        source_name=name.upper(),
        canonical_name=name,
        type=ctype,
        required=draw(st.booleans()),
        numeric_scale=draw(st.sampled_from([None, 2])) if ctype == "numeric" else None,
        is_filter_column=draw(st.booleans()),
        is_join_key=draw(st.booleans()),
    )


@st.composite
def valid_manifests(draw) -> DatasetManifest:
    n_entities = draw(st.integers(min_value=1, max_value=3))
    entities: list[EntitySpec] = []
    entity_names: list[str] = []
    for _ in range(n_entities):
        ename = draw(_ident.filter(lambda n: n not in entity_names))
        entity_names.append(ename)
        col_names: set[str] = set()
        n_cols = draw(st.integers(min_value=1, max_value=4))
        cols = [draw(column_specs(col_names)) for _ in range(n_cols)]
        pk = cols[0].canonical_name
        entities.append(
            EntitySpec(
                name=ename,
                source=LocalFileSource(path=f"{ename}.csv", file_format="csv"),
                primary_key=[pk],
                identifier_field=pk,
                required=True,
                columns=cols,
                joins=[],
            )
        )

    # Optionally add one valid join between the first two entities on their PKs.
    if len(entities) >= 2 and draw(st.booleans()):
        a, b = entities[0], entities[1]
        entities[0] = a.model_copy(
            update={
                "joins": [
                    JoinSpec(
                        target_entity=b.name,
                        local_columns=[a.primary_key[0]],
                        target_columns=[b.primary_key[0]],
                    )
                ]
            }
        )

    # Optionally add a valid metric whose binds are all declared parameters.
    metrics: list[MetricDefinition] = []
    if draw(st.booleans()):
        metrics.append(
            MetricDefinition(
                name="m_" + draw(_ident),
                business_description="desc",
                parameters=[MetricParameter(name="p", type="text", required=True)],
                sql_template="SELECT 1 FROM t WHERE c = :p",
                expected_columns=["c"],
                intent_families=["account_spend"],
                routing_keywords=["spend"],
                golden_question_ids=["g1", "g2", "g3"],
            )
        )

    return DatasetManifest(
        dataset_id="ds_" + draw(_ident),
        version=draw(st.from_regex(r"v[0-9]{1,3}", fullmatch=True)),
        source_mode="local_files",
        currency="INR",
        currency_symbols=["₹", "Rs"],
        thousands_separator=",",
        coverage=CoverageWindow(first_date=date(2023, 1, 1), last_date=date(2024, 12, 31)),
        reference_date_policy="latest_transaction_date",
        entities=entities,
        metrics=metrics,
    )


@given(manifest=valid_manifests())
def test_manifest_dict_round_trip(manifest: DatasetManifest) -> None:
    reloaded = DatasetManifest.model_validate(manifest.model_dump())
    assert reloaded == manifest


@given(manifest=valid_manifests())
def test_manifest_json_round_trip(manifest: DatasetManifest) -> None:
    reloaded = DatasetManifest.model_validate_json(manifest.model_dump_json())
    assert reloaded == manifest


# ------------------------- rejection cases (the other side) ---------------------------


def _base_kwargs() -> dict:
    col = ColumnSpec(source_name="ID", canonical_name="id", type="integer")
    ent = EntitySpec(
        name="t",
        source=LocalFileSource(path="t.csv"),
        primary_key=["id"],
        identifier_field="id",
        columns=[col],
    )
    return {
        "dataset_id": "d",
        "version": "v1",
        "source_mode": "local_files",
        "currency": "INR",
        "currency_symbols": ["₹"],
        "thousands_separator": ",",
        "coverage": CoverageWindow(first_date=date(2023, 1, 1), last_date=date(2023, 12, 31)),
        "reference_date_policy": "latest_transaction_date",
        "entities": [ent],
        "metrics": [],
    }


def test_reject_unsupported_source_mode() -> None:
    kwargs = _base_kwargs()
    kwargs["source_mode"] = "ftp"  # not local_files / http_api
    with pytest.raises(ValidationError):
        DatasetManifest(**kwargs)


def test_reject_no_entities() -> None:
    kwargs = _base_kwargs()
    kwargs["entities"] = []
    with pytest.raises(ValidationError):
        DatasetManifest(**kwargs)


def test_reject_metric_bind_not_in_parameters() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            name="m",
            business_description="d",
            parameters=[MetricParameter(name="p", type="text")],
            sql_template="SELECT 1 WHERE a = :p AND b = :q",  # :q undeclared
            expected_columns=["c"],
            intent_families=["account_spend"],
            routing_keywords=["k"],
            golden_question_ids=["g1", "g2", "g3"],
        )


def test_reject_primary_key_not_declared() -> None:
    with pytest.raises(ValidationError):
        EntitySpec(
            name="t",
            source=LocalFileSource(path="t.csv"),
            primary_key=["missing"],
            identifier_field="missing",
            columns=[ColumnSpec(source_name="ID", canonical_name="id", type="integer")],
        )


def test_reject_http_api_without_pagination() -> None:
    # An http_api manifest with a local source and no pagination must fail.
    kwargs = _base_kwargs()
    kwargs["source_mode"] = "http_api"
    with pytest.raises(ValidationError):
        DatasetManifest(**kwargs)


def test_reject_join_to_unknown_entity() -> None:
    kwargs = _base_kwargs()
    ent = kwargs["entities"][0]
    kwargs["entities"] = [
        ent.model_copy(
            update={
                "joins": [
                    JoinSpec(
                        target_entity="nope",
                        local_columns=["id"],
                        target_columns=["id"],
                    )
                ]
            }
        )
    ]
    with pytest.raises(ValidationError):
        DatasetManifest(**kwargs)


def test_extract_binds_ignores_casts() -> None:
    assert extract_binds("SELECT x::int FROM t WHERE y = :val") == {"val"}
    assert extract_binds("SELECT 1") == set()
