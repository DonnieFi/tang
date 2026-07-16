from __future__ import annotations

from pathlib import Path

from tang.adapter_registry import configured_adapters


def test_registry_preserves_codex_grok_when_opencode_is_not_configured(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.delenv("TANG_OPENCODE_EXECUTABLE", raising=False)
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda _name: None)

    adapters = configured_adapters(
        project,
        codex_home=tmp_path / "codex",
        grok_home=tmp_path / "grok",
    )

    assert [adapter.adapter_key for adapter in adapters] == ["codex", "grok"]


def test_registry_adds_opencode_explicitly_or_from_environment(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    executable = tmp_path / "opencode"
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda _name: None)

    explicit = configured_adapters(
        project, opencode_executable=executable
    )
    monkeypatch.setenv("TANG_OPENCODE_EXECUTABLE", str(executable))
    environment = configured_adapters(project)

    assert [adapter.adapter_key for adapter in explicit] == [
        "codex",
        "grok",
        "opencode",
    ]
    assert [adapter.adapter_key for adapter in environment] == [
        "codex",
        "grok",
        "opencode",
    ]
    assert explicit[-1].source_namespace == environment[-1].source_namespace


def test_doctor_registry_requires_an_opencode_readiness_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.delenv("TANG_OPENCODE_EXECUTABLE", raising=False)
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda _name: None)

    adapters = configured_adapters(project, require_opencode=True)

    assert [adapter.adapter_key for adapter in adapters] == [
        "codex",
        "grok",
        "opencode",
    ]
