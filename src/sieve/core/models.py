"""Versioned schemas for every durable artifact (spec §4).

Design rules, enforced by tests:

- No field anywhere aggregates evidence into a single model-wide score.
- Everything that reaches a report must be reconstructible from these objects.
- ``EvidenceBundle`` is the product artifact; its canonical serialization
  (``sieve.core.serialization``) is what gets hashed and verified.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from sieve.core.enums import (
    DIMENSIONS,
    ExploratoryStatus,
    Prespecification,
    Severity,
    Status,
)

SCHEMA_VERSION = "0.1.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransformSpec(_Model):
    name: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class ModelManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    model_id: str
    model_version: str
    display_name: str
    model_family: str | None = None
    adapter_id: str
    code_uri: str | None = None
    git_commit: str | None = None
    container_digest: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    parameters_hash: str = ""
    authors: list[str] = Field(default_factory=list)
    license: str | None = None
    notes: str | None = None


class DatasetManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    dataset_id: str
    source_uri: str | None = None
    symbols: list[str] = Field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None
    frequency: str = "daily"
    timezone: str | None = None
    transforms: list[TransformSpec] = Field(default_factory=list)
    content_hash: str = ""
    license: str | None = None


class ClaimSpec(_Model):
    claim_id: str
    version: str
    statement: str
    use_case: str
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_dimensions: list[str] = Field(default_factory=list)
    optional_dimensions: list[str] = Field(default_factory=list)
    decision_policy: str | None = None


class MetricRequirements(_Model):
    """Declared input requirements of one metric (task §3.5).

    The runner/inspector consults this to decide, per metric, whether the
    input is adequate — an inadequate metric becomes NOT_APPLICABLE or
    INSUFFICIENT on its own without dragging other metrics down.
    """

    required_columns: list[str] = Field(default_factory=lambda: ["return"])
    optional_columns: list[str] = Field(default_factory=list)
    supported_geometries: list[str] = Field(default_factory=lambda: [
        "single_long_series", "multi_run_ensemble", "multi_market_panel",
        "paired_runs", "short_exploratory_series"])
    minimum_observations_per_run: int = 300
    minimum_runs: int = 1
    supports_irregular_time: bool = True
    requires_regular_spacing: bool = False
    exploratory_plot_id: str | None = None
    confirmatory_test_id: str | None = None
    preprocessing_requirements: list[str] = Field(default_factory=list)


class MetricSpec(_Model):
    metric_id: str
    version: str
    display_name: str
    function_path: str
    input_contract: str
    scale_invariant: bool
    intended_signal: str
    known_blind_spots: list[str] = Field(default_factory=list)
    prespecification: Prespecification = Prespecification.UNKNOWN
    references: list[str] = Field(default_factory=list)
    # additive (research workbench); not serialized inside evidence bundles,
    # so old bundle hashes are unaffected
    requirements: MetricRequirements | None = None


class BaselineSpec(_Model):
    baseline_id: str
    version: str
    description: str
    mechanisms_present: list[str] = Field(default_factory=list)
    mechanisms_absent: list[str] = Field(default_factory=list)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    calibration_ref: str | None = None


class TestResult(_Model):
    __test__ = False          # a schema, not a pytest collection target

    test_id: str
    metric_ref: str
    baseline_ref: str | None = None
    statistic_name: str
    statistic_value: float | None = None
    p_value: float | None = None
    adjusted_p_value: float | None = None
    effect_size: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    n_reference: int = 0
    n_simulation: int = 0
    status: Status
    prespecification: Prespecification = Prespecification.UNKNOWN
    caveats: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


class FailureFinding(_Model):
    finding_id: str
    code: str
    severity: Severity
    title: str
    observation: str
    interpretation: str
    claim_impact: str
    evidence_refs: list[str] = Field(default_factory=list)
    questions_for_author: list[str] = Field(default_factory=list)


class DimensionStatus(_Model):
    dimension: str
    status: Status
    test_refs: list[str] = Field(default_factory=list)
    note: str | None = None


class ValidationProfile(_Model):
    """Ten dimensions, each with a status. Never averaged (spec §4.8)."""

    dimensions: list[DimensionStatus]

    def as_dict(self) -> dict[str, Status]:
        return {d.dimension: d.status for d in self.dimensions}

    @classmethod
    def not_tested(cls) -> "ValidationProfile":
        return cls(dimensions=[DimensionStatus(dimension=d, status=Status.NOT_TESTED)
                               for d in DIMENSIONS])


class TestSuiteManifest(_Model):
    __test__ = False          # a schema, not a pytest collection target

    suite_id: str
    version: str
    claim_types: list[str]
    reference: dict[str, JsonValue] = Field(default_factory=dict)
    metrics: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    inference: dict[str, JsonValue] = Field(default_factory=dict)
    suite_hash: str = ""


class ArtifactRef(_Model):
    path: str            # relative to the run directory
    sha256: str
    kind: str            # "table" | "report" | "figure" | "input" | "other"


class SeedNode(_Model):
    name: str
    entropy: int
    spawn_key: list[int] = Field(default_factory=list)


class RunManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    created_at: datetime
    sieve_version: str
    command: str
    master_seed: int
    seed_tree: list[SeedNode] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    input_path: str
    input_hash: str


class AuthorResponse(_Model):
    author_name: str
    received_at: datetime
    response: str
    reproduction_confirmed: bool | None = None
    correction_refs: list[str] = Field(default_factory=list)


class EvidenceBundle(_Model):
    schema_version: str = SCHEMA_VERSION
    bundle_id: UUID
    created_at: datetime
    run_manifest: RunManifest
    model: ModelManifest
    dataset: DatasetManifest
    claim: ClaimSpec
    suite: TestSuiteManifest
    profile: ValidationProfile
    results: list[TestResult]
    findings: list[FailureFinding]
    limitations: list[str] = Field(default_factory=list)
    artifact_index: list[ArtifactRef] = Field(default_factory=list)
    author_responses: list[AuthorResponse] = Field(default_factory=list)
    bundle_hash: str = ""


# Fields excluded from the scientific seal (``bundle_hash``). The seal pins
# WHAT was measured — data identity, suite identity, seed, results — so that
# an independent rerun of the same content reproduces the same hash. Three
# kinds of field must therefore stay outside it (they remain in the bundle,
# protected by the ``bundle.sha256`` file-integrity layer):
#
# - per-run identifiers and timestamps (spec §16 "except explicitly excluded
#   timestamps/IDs");
# - ``artifact_index``: manifest.json and report/index.html legitimately
#   contain the excluded run_id/created_at (and the report embeds bundle_hash
#   itself), so their file hashes would smuggle volatile IDs back in;
# - machine-local facts: the platform fingerprint, the local filesystem paths
#   in command/input_path/source_uri. Same CSV bytes on another machine or
#   under another path is the same science — the data identity in the seal is
#   ``dataset.content_hash`` / ``run_manifest.input_hash``, never a path.
HASH_EXCLUDED_PATHS = (
    ("bundle_hash",),
    ("bundle_id",),
    ("created_at",),
    ("run_manifest", "run_id"),
    ("run_manifest", "created_at"),
    ("run_manifest", "command"),
    ("run_manifest", "input_path"),
    ("run_manifest", "environment"),
    ("dataset", "source_uri"),
    ("artifact_index",),
)


class MetricComparison(_Model):
    """One metric's A-vs-B comparison in a model-update regression test.

    ``verdict`` answers "did the distribution move" (statistics);
    ``transition`` reads the move against the reference gate:

    - REGRESSION          A passed the reference, B fails it
    - IMPROVEMENT         A failed, B passes
    - CHANGED_WITHIN_GATE distribution moved, gate statuses unchanged —
                          the reference gate cannot see this change
    - STABLE              no detected move, gate statuses unchanged
    - INDETERMINATE       an INSUFFICIENT is involved
    """

    metric_ref: str
    dimension: str = ""
    n_a: int
    n_b: int
    ks_ab: float | None = None
    p_value: float | None = None
    adjusted_p_value: float | None = None
    median_a: float | None = None
    median_b: float | None = None
    median_change_pct: float | None = None
    status_a_vs_reference: Status
    status_b_vs_reference: Status
    verdict: Literal["CHANGED", "NOT_SEPARATED", "INSUFFICIENT"]
    transition: Literal["REGRESSION", "IMPROVEMENT", "CHANGED_WITHIN_GATE",
                        "STABLE", "INDETERMINATE"] = "STABLE"
    caveats: list[str] = Field(default_factory=list)


class ParameterChange(_Model):
    """One declared model-manifest parameter that differs between versions."""

    name: str
    value_a: JsonValue = None
    value_b: JsonValue = None


class ApprovalAssessment(_Model):
    """Outcome of a versioned approval policy — a rule, not a score.

    The policy is declared (id@version + full text), applies only to the
    claim's required dimensions, and yields a categorical outcome with the
    triggering rows listed. Nothing is weighted, summed or averaged; the
    outcome is a routing decision (does a human reviewer need to look),
    never a quality measure.
    """

    policy_id: str
    policy_version: str
    policy_text: str
    outcome: Literal["NO_CHANGE_DETECTED", "REVIEW_REQUIRED"]
    triggered_by: list[str] = Field(default_factory=list)
    required_dimensions: list[str] = Field(default_factory=list)


class CompareSide(_Model):
    """Identity of one side of a comparison, copied from its sealed bundle."""

    label: str                    # "A" (baseline/old) or "B" (candidate/new)
    bundle_hash: str
    model_id: str
    model_version: str
    display_name: str
    input_hash: str
    n_windows: int


class CompareBundle(_Model):
    """Durable artifact of `sieve compare`: the change-approval evidence.

    Compares two sealed runs of the SAME suite version. Answers one question
    per metric: did the update change this dimension's window distribution?
    Never aggregates; CHANGED on one metric says nothing about the others.
    """

    schema_version: str = SCHEMA_VERSION
    compare_id: str
    created_at: datetime
    sieve_version: str
    master_seed: int
    suite_id: str
    suite_version: str
    suite_hash: str
    claim_id: str
    inference: dict[str, JsonValue] = Field(default_factory=dict)
    side_a: CompareSide
    side_b: CompareSide
    parameter_changes: list[ParameterChange] = Field(default_factory=list)
    results: list[MetricComparison]
    approval: ApprovalAssessment | None = None
    caveats: list[str] = Field(default_factory=list)
    compare_hash: str = ""


# Volatile fields of the compare artifact (same nulling rules as the bundle).
COMPARE_HASH_EXCLUDED_PATHS = (
    ("compare_hash",),
    ("compare_id",),
    ("created_at",),
)


# --------------------------------------------------------------------------
# Research workbench artifacts (additive; nothing below is embedded in
# EvidenceBundle, so existing sealed bundles verify unchanged).
# --------------------------------------------------------------------------

class FigureSpec(_Model):
    """Registry entry for one diagnostic figure (task §5.2).

    Figures are versioned method declarations, exactly like metrics: what
    the figure shows, what input it needs, what it is known to mislead on.
    """

    figure_id: str
    version: str
    display_name: str
    stylized_fact: str
    supported_claims: list[str] = Field(default_factory=list)
    required_columns: list[str] = Field(default_factory=lambda: ["return"])
    supported_geometries: list[str] = Field(default_factory=lambda: [
        "single_long_series", "multi_run_ensemble", "multi_market_panel",
        "paired_runs", "short_exploratory_series"])
    minimum_observations_per_run: int = 300
    minimum_runs: int = 1
    function_path: str = ""
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    related_metrics: list[str] = Field(default_factory=list)
    known_visual_pitfalls: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    implemented: bool = True


class FigureResult(_Model):
    """Outcome of rendering one registered figure for one dataset."""

    figure_id: str
    version: str
    display_name: str
    stylized_fact: str
    status: ExploratoryStatus
    n_runs_used: int = 0
    n_obs_used: int = 0
    summary_values: dict[str, float | None] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    related_metrics: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    artifact_path: str | None = None      # figures/<id>.svg, when rendered
    note: str | None = None               # why not rendered, when not


class RunSummary(_Model):
    """Per-run accounting: what went in, what burn-in removed."""

    run_id: str
    seed: int | None = None
    n_obs_raw: int
    n_obs: int
    n_burned: int = 0
    irregular_spacing: bool = False


class GeometrySummary(_Model):
    """Sampling geometry of the input, and where the label came from."""

    geometry: str
    geometry_source: str                  # "declared" | "structural_default"
    time_basis: str                       # "step" | "timestamp"
    n_runs: int
    n_obs_total: int
    columns: list[str] = Field(default_factory=list)
    runs: list[RunSummary] = Field(default_factory=list)


class MetricObservation(_Model):
    """One metric evaluated on one run (exploratory, not a test)."""

    metric_ref: str
    run_id: str
    value: float | None = None
    status: ExploratoryStatus = ExploratoryStatus.OBSERVED
    note: str | None = None


class InspectBundle(_Model):
    """Durable artifact of ``sieve inspect``: exploratory evidence only.

    Contains no PASS/FAIL, no p-values and no reference comparison — those
    belong to ``sieve test``. Sealed with the same two-layer scheme as
    :class:`EvidenceBundle` (deterministic ``bundle_hash`` + file sidecar).
    """

    schema_version: str = SCHEMA_VERSION
    bundle_id: UUID
    created_at: datetime
    mode: Literal["exploratory"] = "exploratory"
    run_manifest: RunManifest
    model: ModelManifest
    dataset: DatasetManifest
    suite_ref: str
    suite_hash: str
    geometry: GeometrySummary
    figures: list[FigureResult] = Field(default_factory=list)
    metric_observations: list[MetricObservation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifact_index: list[ArtifactRef] = Field(default_factory=list)
    bundle_hash: str = ""


# Volatile fields of the inspect artifact (same nulling rules as the bundle).
INSPECT_HASH_EXCLUDED_PATHS = (
    ("bundle_hash",),
    ("bundle_id",),
    ("created_at",),
    ("run_manifest", "run_id"),
    ("run_manifest", "created_at"),
    ("run_manifest", "command"),
    ("run_manifest", "input_path"),
    ("run_manifest", "environment"),
    ("dataset", "source_uri"),
    ("artifact_index",),
)
