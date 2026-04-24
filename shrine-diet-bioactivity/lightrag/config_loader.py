"""YAML-backed config loader shared across all ingestion scripts.
Same shape as shrine-diet-bioactivity/src/config.ts for language parity."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError


class ConfigError(RuntimeError):
    pass


class DataSource(BaseModel):
    base_url: str
    files: list[str] = Field(min_length=1)
    out_dir: str


class Paths(BaseModel):
    sqlite_db: str
    hdi_safe_50: str
    symptom_crosswalk: str
    ingestion_snapshot: str


class DataSourcesConfig(BaseModel):
    symmap: DataSource
    herb2: DataSource
    paths: Paths


class SubsampleCfg(BaseModel):
    max_relationships: int = Field(ge=0)
    seed: int


class IngestionCfg(BaseModel):
    batch_size: int = Field(gt=0)
    max_async: int = Field(gt=0)


class LightRAGCfg(BaseModel):
    working_dir: str


class HDIWeights(BaseModel):
    severe:   float = Field(ge=0, le=1)
    moderate: float = Field(ge=0, le=1)
    mild:     float = Field(ge=0, le=1)

    def __getitem__(self, key: str) -> float:
        return getattr(self, key)


class IngestParamsConfig(BaseModel):
    subsample: SubsampleCfg
    ingestion: IngestionCfg
    lightrag: LightRAGCfg
    hdi_severity_weights: HDIWeights
    evidence_tier_weights: Mapping[str, float]


_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = _ROOT / "config" / "data_sources.yaml"
DEFAULT_PARAMS = _ROOT / "config" / "ingest_params.yaml"


def _load(path: Path, model: type[BaseModel]):
    try:
        raw = path.read_text()
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    try:
        return model.model_validate(yaml.safe_load(raw))
    except (yaml.YAMLError, ValidationError) as e:
        raise ConfigError(f"invalid config at {path}: {e}") from e


def load_data_sources(path: Path = DEFAULT_DATA) -> DataSourcesConfig:
    return _load(path, DataSourcesConfig)


def load_ingest_params(path: Path = DEFAULT_PARAMS) -> IngestParamsConfig:
    return _load(path, IngestParamsConfig)
