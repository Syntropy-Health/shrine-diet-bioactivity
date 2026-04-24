import pytest
from pathlib import Path
from config_loader import load_data_sources, load_ingest_params, ConfigError


def test_loads_data_sources():
    cfg = load_data_sources()
    assert cfg.symmap.base_url.startswith(("http://", "https://"))
    assert len(cfg.symmap.files) > 0
    assert "herbal_botanicals.db" in cfg.paths.sqlite_db


def test_loads_ingest_params_with_validated_ranges():
    cfg = load_ingest_params()
    assert isinstance(cfg.subsample.seed, int)
    assert cfg.ingestion.batch_size > 0
    assert cfg.hdi_severity_weights["severe"] > cfg.hdi_severity_weights["mild"]


def test_rejects_malformed_yaml_at_load_time():
    with pytest.raises(ConfigError):
        load_data_sources(Path("/dev/null/nonexistent.yaml"))
