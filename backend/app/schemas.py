"""Pydantic models shared by core + API. JSON is camelCase; param keys stay snake_case."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------- manifest ----------
ParamType = Literal["enum", "int", "float", "bool", "text", "ratio", "image", "imageList"]


class Range(CamelModel):
    min: float
    max: float
    step: float | None = None


class SizeRule(CamelModel):
    """Validation of a `WxH` pixel size (plus literal `allow` values such as "auto")."""

    allow: list[str] = Field(default_factory=list)
    multiple_of: int = 1
    max_edge: int | None = None
    max_ratio: float | None = None  # long edge / short edge
    min_pixels: int | None = None
    max_pixels: int | None = None


class Param(CamelModel):
    key: str
    label: str
    type: ParamType
    values: list[Any] | None = None
    range: Range | None = None
    default: Any = None
    group: str = "output"
    level: Literal["basic", "advanced"] = "advanced"
    applies_to_modes: list[str] = Field(default_factory=list)  # empty = all modes
    provider_path: str | None = None
    provider_format: str | None = None  # e.g. "{}s" -> 5 becomes "5s"
    supported: bool = True
    required: bool = False  # required (asset slots) in the modes where it applies
    max_items: int | None = None  # imageList
    suggestions: list[Any] | None = None  # text params: presets the UI may offer (not an enum: any valid value works)
    size_rule: SizeRule | None = None  # text params holding "WxH" (OpenAI gpt-image `size`)
    description: str | None = None


class Constraint(CamelModel):
    when: dict[str, Any]  # key -> value | [values]; "mode" is a pseudo-key
    then: dict[str, Any] | None = None  # force
    block: bool = False  # forbid
    reason: str


class PriceRow(CamelModel):
    when: dict[str, Any] = Field(default_factory=dict)  # param -> value | [values]; missing param widens the range
    usd: float | None = None


class PricingSpec(CamelModel):
    """Price rows live in the manifest; data/prices.json entry <priceKey or model id> adds lastVerified/variance
    and may override `table` (so prices can be updated without touching manifests)."""

    unit: Literal["per_image", "per_second"]
    price_key: str | None = None
    table: list[PriceRow] = Field(default_factory=list)


class Limits(CamelModel):
    max_concurrent: int = 2
    concurrency_group: str | None = None  # models sharing an account-wide cap (e.g. all Seedance) use one semaphore
    max_variants_native: int = 1
    rpm: int | None = None


class Enhancer(CamelModel):
    system_prompt: str


class ModelManifest(CamelModel):
    id: str
    label: str
    provider: str = "vertex"
    kind: Literal["image", "video"]
    adapter: Literal["vertex_image", "vertex_omni", "vertex_veo", "openai_image", "byteplus_seedance"]
    api_model: str
    api_location: str | None = None  # e.g. "global"; None = provider location
    status: Literal["ga", "preview", "deprecated"]
    sunset_date: str | None = None
    last_verified: str  # date the params were last checked against docs/research (NOT a live call)
    verified: bool = True  # False: payload shape/params not confirmed (see [?] marks)
    verified_live: bool = False  # True only after a real API call confirmed the payload and response shapes
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None
    modes: list[str]
    params: list[Param]
    constraints: list[Constraint] = Field(default_factory=list)
    pricing: PricingSpec
    limits: Limits = Field(default_factory=Limits)
    enhancer: Enhancer | None = None

    def param(self, key: str) -> Param | None:
        return next((p for p in self.params if p.key == key), None)


# ---------- requests ----------
class GenerationRequest(CamelModel):
    model_id: str
    mode: str | None = None
    prompt: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    assets: dict[str, Any] = Field(default_factory=dict)  # slot -> assetId | [assetId]

    @model_validator(mode="before")
    @classmethod
    def _prompt_alias(cls, data: Any) -> Any:
        """Tolerate `params.prompt` (alias of top-level `prompt`)."""
        if isinstance(data, dict) and isinstance(data.get("params"), dict) and "prompt" in data["params"]:
            alias = data["params"]["prompt"]
            if not data.get("prompt") and isinstance(alias, str):
                data = {**data, "prompt": alias}
        return data


class Axis(CamelModel):
    param: str
    values: list[Any]


class Sweep(CamelModel):
    variants: int = Field(default=1, ge=1)
    prompts: list[str] = Field(default_factory=list)
    axes: list[Axis] = Field(default_factory=list)
    seed_mode: Literal["random", "fixed", "none"] = "none"
    seed: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        """Tolerate `n` (alias of `variants`) and axes given as {param: [values]}."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "n" in data and "variants" not in data:
            data["variants"] = data.pop("n")
        if isinstance(data.get("axes"), dict):
            data["axes"] = [{"param": k, "values": v} for k, v in data["axes"].items()]
        return data


# ---------- runtime ----------
JobStatus = Literal["queued", "running", "succeeded", "failed", "blocked", "canceled"]
TERMINAL = {"succeeded", "failed", "blocked", "canceled"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Asset(CamelModel):
    id: str
    path: str = Field(exclude=True)  # invariant 23: absolute server path never leaves the backend
    mime: str
    sha256: str
    size_bytes: int
    kind: Literal["upload", "output"]
    meta: dict[str, Any] = Field(default_factory=dict)


class JobError(CamelModel):
    kind: str
    message: str


class InputAsset(BaseModel):
    """Resolved input image for build_payload (not serialised)."""

    id: str
    mime: str
    data: bytes | None = None
    gcs_uri: str | None = None


class Job(CamelModel):
    id: str
    batch_id: str
    model_id: str
    provider: str = "vertex"  # provider of the model (results from different providers share one grid)
    mode: str
    prompt: str
    requested_params: dict[str, Any]
    effective_params: dict[str, Any]
    locked: list[dict[str, str]] = Field(default_factory=list)
    assets_in: dict[str, Any] = Field(default_factory=dict)  # slot -> assetId | [assetId]
    variant_count: int = 1  # >1 only for Veo native sampleCount groups
    axis: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = "queued"
    error: JobError | None = None
    assets: list[Asset] = Field(default_factory=list)
    cost_estimate_usd: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    attempts: int = 0
    note: str | None = None
    warnings: list[str] = Field(default_factory=list)  # e.g. raiMediaFilteredCount, fewer outputs than requested
    retry_of: str | None = None  # id of the job this one manually retries
    operation_id: str | None = None  # provider operation handle (Veo) once submitted
    best_effort_cancel: bool = False
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    inputs: dict[str, list[InputAsset]] = Field(default_factory=dict, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model(self) -> str:
        """Alias of modelId (requirements' Job sketch uses `model`)."""
        return self.model_id


class Batch(CamelModel):
    id: str
    created_at: str = Field(default_factory=now_iso)
    jobs: list[Job] = Field(default_factory=list)
    estimate: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    status: str = "queued"
    counts: dict[str, int] = Field(default_factory=dict)
