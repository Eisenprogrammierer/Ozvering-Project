"""Флаги и конфиг когнитивных бэкендов."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from campaign.cognition import (
    BackendError,
    CognitionFlags,
    default_config_path,
    load_flags,
)


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "backends.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_isolated_config_is_legacy_and_valid():
    flags = load_flags(environ={})
    assert flags.ai_backend == "legacy"
    assert flags.nlu_backend == "legacy"
    assert flags.accept_threshold > flags.clarify_threshold
    assert default_config_path().is_file()


def test_shipped_config_enables_soar():
    shipped = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "cognition"
        / "backends.json"
    )
    flags = load_flags(shipped, environ={})
    assert flags.ai_backend == "soar"
    assert flags.nlu_backend == "legacy"


def test_env_overrides_backend_but_not_thresholds(tmp_path):
    path = _write(
        tmp_path,
        {
            "version": 1,
            "ai_backend": "legacy",
            "nlu_backend": "legacy",
            "thresholds": {"accept": 0.8, "clarify": 0.4},
        },
    )
    flags = load_flags(
        path,
        environ={
            "OZVERIN_AI_BACKEND": "shadow",
            "OZVERIN_NLU_BACKEND": "rive",
        },
    )
    assert flags.ai_backend == "shadow"
    assert flags.nlu_backend == "rive"
    assert flags.accept_threshold == 0.8
    assert flags.clarify_threshold == 0.4
    assert flags.nlu_fallback_max == pytest.approx(0.05)


def test_fallback_rate_max_is_data_driven(tmp_path):
    path = _write(
        tmp_path,
        {
            "version": 1,
            "thresholds": {"fallback_rate_max": 0.12},
        },
    )
    flags = load_flags(path, environ={})
    assert flags.nlu_fallback_max == pytest.approx(0.12)
    with pytest.raises(BackendError):
        CognitionFlags(nlu_fallback_max=1.5)


def test_unknown_backend_and_bad_thresholds_are_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"version": 1, "ai_backend": "magic", "nlu_backend": "legacy"},
    )
    with pytest.raises(BackendError):
        load_flags(path, environ={})
    with pytest.raises(BackendError):
        CognitionFlags(
            accept_threshold=0.4,
            clarify_threshold=0.8,
        )
    with pytest.raises(BackendError):
        CognitionFlags(decision_timeout_ms=0)


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(BackendError):
        load_flags(tmp_path / "missing.json", environ={})


def test_future_config_version_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 99})
    with pytest.raises(BackendError):
        load_flags(path, environ={})
