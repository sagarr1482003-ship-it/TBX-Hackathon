"""Dataset_Manifest Pydantic contracts (design §4.3).

The manifest is the declarative description of a dataset. Swapping datasets means
replacing this file and re-running ingestion. A manifest that fails validation aborts
before any entity loads (Requirement 5.9).

The load-bearing ``model_validator`` (Requirement 5.9) asserts:
  * every ``:bind`` name in every metric ``sql_template`` exists in that metric's
    ``parameters``;
  * every required entity and required column is declared;
  * ``source_mode`` is one of ``local_files`` / ``http_api`` (enforced by the Literal).

Property 11 covers serialise/re-load equivalence and rejection of incomplete or
unsupported-mode manifests.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import ColumnType, IntentFamily

# A named bind in a SQL template, e.g. ":vendor_id". Postgres casts like "x::int" are not
# binds; the pattern requires the colon to be preceded by start/whitespace/"(" or "," so a
# "::" cast is never treated as a bind.
_BIND_RE = re.compile(r"(?:(?<=^)|(?<=[\s(,]))\:([a-zA-Z_][a-zA-Z0-9_]*)")


def extract_binds(sql_template: str) -> set[str]:
    """Return the set of ``:name`` bind identifiers referenced in a template."""
    return set(_BIND_RE.findall(sql_template))


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str
    canonical_name: str
    type: ColumnType
    required: bool = False
    date_format: str | None = None  # exactly one format (Requirement 6.3)
    numeric_scale: int | None = None  # monetary scale (Requirement 6.4)
    unit: str | None = None
    is_filter_column: bool = False  # -> index (Requirement 6.7)
    is_join_key: bool = False


class LocalFileSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["local_file"] = "local_file"
    path: str
    file_format: Literal["csv", "xlsx", "sql"] = "csv"


class ApiEndpointSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["api_endpoint"] = "api_endpoint"
    path: str  # relative to the manifest base_url
    auth_header: str | None = None


class JoinSpec(BaseModel):
    """A declared relationship edge (Requirement 3.6)."""

    model_config = ConfigDict(extra="forbid")

    target_entity: str
    local_columns: list[str]
    target_columns: list[str]

    @model_validator(mode="after")
    def _columns_align(self) -> JoinSpec:
        if len(self.local_columns) != len(self.target_columns):
            raise ValueError(
                "JoinSpec local_columns and target_columns must be the same length"
            )
        if not self.local_columns:
            raise ValueError("JoinSpec must declare at least one column pair")
        return self


class EntitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # canonical table name in schema `finance`
    source: LocalFileSource | ApiEndpointSource
    primary_key: list[str]
    identifier_field: str
    required: bool = True
    columns: list[ColumnSpec]
    joins: list[JoinSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _entity_well_formed(self) -> EntitySpec:
        canonical = {c.canonical_name for c in self.columns}
        if not self.columns:
            raise ValueError(f"entity {self.name!r} declares no columns")
        if len(canonical) != len(self.columns):
            raise ValueError(f"entity {self.name!r} has duplicate canonical column names")
        # Primary-key and identifier columns must be declared.
        for pk in self.primary_key:
            if pk not in canonical:
                raise ValueError(
                    f"entity {self.name!r} primary_key column {pk!r} is not declared"
                )
        if not self.primary_key:
            raise ValueError(f"entity {self.name!r} declares an empty primary_key")
        if self.identifier_field not in canonical:
            raise ValueError(
                f"entity {self.name!r} identifier_field {self.identifier_field!r} is not declared"
            )
        # Join local columns must be declared on this entity.
        for join in self.joins:
            for col in join.local_columns:
                if col not in canonical:
                    raise ValueError(
                        f"entity {self.name!r} join to {join.target_entity!r} references "
                        f"undeclared local column {col!r}"
                    )
        return self


class MetricParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: ColumnType
    required: bool = True
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[str] | None = None


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    business_description: str
    parameters: list[MetricParameter]
    sql_template: str  # named binds only, e.g. :vendor_id
    expected_columns: list[str]
    intent_families: list[IntentFamily]
    routing_keywords: list[str]
    golden_question_ids: list[str]  # >= 3 (Requirement 4.7)

    @model_validator(mode="after")
    def _binds_declared(self) -> MetricDefinition:
        declared = {p.name for p in self.parameters}
        if len(declared) != len(self.parameters):
            raise ValueError(f"metric {self.name!r} has duplicate parameter names")
        used = extract_binds(self.sql_template)
        missing = used - declared
        if missing:
            raise ValueError(
                f"metric {self.name!r} sql_template references binds not in parameters: "
                f"{sorted(missing)}"
            )
        if not self.expected_columns:
            raise ValueError(f"metric {self.name!r} declares no expected_columns")
        if not self.intent_families:
            raise ValueError(f"metric {self.name!r} declares no intent_families")
        return self


class PaginationSpec(BaseModel):
    """Pagination style + final-page signal (Requirement 7.3)."""

    model_config = ConfigDict(extra="forbid")

    style: Literal["cursor", "page_number", "offset", "link_header"]
    final_page_signal: str
    page_size_param: str | None = None
    cursor_param: str | None = None
    page_param: str | None = None


class CoverageWindow(BaseModel):
    """Inclusive first/last date (Requirement 8.4)."""

    model_config = ConfigDict(extra="forbid")

    first_date: date
    last_date: date

    @model_validator(mode="after")
    def _ordered(self) -> CoverageWindow:
        if self.first_date > self.last_date:
            raise ValueError("coverage first_date must be <= last_date")
        return self


class DataDictionarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["csv", "inline"] = "csv"
    path: str | None = None
    entity_column: str = "entity"
    column_column: str = "column"
    description_column: str = "description"


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    source_mode: Literal["local_files", "http_api"]
    encoding: str = "utf-8"
    currency: str
    currency_symbols: list[str]
    thousands_separator: str
    coverage: CoverageWindow
    reference_date_policy: Literal["latest_transaction_date", "fixed"]
    reference_date: date | None = None
    base_url: str | None = None
    pagination: PaginationSpec | None = None
    data_dictionary: DataDictionarySpec | None = None
    entities: list[EntitySpec]
    metrics: list[MetricDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _manifest_coherent(self) -> DatasetManifest:
        if not self.entities:
            raise ValueError("manifest declares no entities")
        entity_names = {e.name for e in self.entities}
        if len(entity_names) != len(self.entities):
            raise ValueError("manifest has duplicate entity names")

        # Source kind must match the declared source_mode.
        for e in self.entities:
            if self.source_mode == "local_files" and not isinstance(e.source, LocalFileSource):
                raise ValueError(
                    f"entity {e.name!r} must use a local_file source under source_mode "
                    f"local_files"
                )
            if self.source_mode == "http_api" and not isinstance(e.source, ApiEndpointSource):
                raise ValueError(
                    f"entity {e.name!r} must use an api_endpoint source under source_mode "
                    f"http_api"
                )

        # http_api requires pagination + base_url so ingestion is fully specified.
        if self.source_mode == "http_api":
            if self.pagination is None:
                raise ValueError("source_mode http_api requires a pagination spec")
            if not self.base_url:
                raise ValueError("source_mode http_api requires a base_url")

        # Every join target must resolve to a declared entity.
        for e in self.entities:
            for join in e.joins:
                if join.target_entity not in entity_names:
                    raise ValueError(
                        f"entity {e.name!r} joins to unknown entity {join.target_entity!r}"
                    )
                target = next(t for t in self.entities if t.name == join.target_entity)
                target_cols = {c.canonical_name for c in target.columns}
                for col in join.target_columns:
                    if col not in target_cols:
                        raise ValueError(
                            f"join {e.name!r}->{join.target_entity!r} references undeclared "
                            f"target column {col!r}"
                        )

        # reference_date_policy=fixed requires a reference_date.
        if self.reference_date_policy == "fixed" and self.reference_date is None:
            raise ValueError("reference_date_policy 'fixed' requires a reference_date")

        # Metric intent families are already constrained by the Literal; nothing else here.
        return self
