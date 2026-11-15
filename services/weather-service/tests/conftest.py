from pathlib import Path

import pytest

import config


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's .env must never leak into tests.
    monkeypatch.setenv("PROVIDER_BASE_URL", "http://provider.invalid/v1/forecast")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "no-such.env")
