from __future__ import annotations

import importlib.util
from pathlib import Path

from tang.adapter_registry import configured_adapters


def test_registry_preserves_codex_grok_when_opencode_is_not_configured(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.delenv("TANG_OPENCODE_EXECUTABLE", raising=False)
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "tang.adapter_registry._default_opencode_executable", lambda: None
    )

    adapters = configured_adapters(
        project,
        codex_home=tmp_path / "codex",
        grok_home=tmp_path / "grok",
    )

    assert [adapter.adapter_key for adapter in adapters] == ["codex", "grok"]


def test_registry_discovers_standard_user_local_opencode_executable(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    executable = home / ".opencode" / "bin" / "opencode"
    project.mkdir()
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    monkeypatch.delenv("TANG_OPENCODE_EXECUTABLE", raising=False)
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda _name: None)
    monkeypatch.setattr("tang.adapter_registry.Path.home", lambda: home)

    adapters = configured_adapters(project)

    assert [adapter.adapter_key for adapter in adapters] == [
        "codex",
        "grok",
        "opencode",
    ]
    assert adapters[-1]._executable == str(executable)


def test_registry_prefers_explicit_environment_and_path_over_default_opencode(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    default = home / ".opencode" / "bin" / "opencode"
    path_executable = tmp_path / "path-opencode"
    environment = tmp_path / "environment-opencode"
    explicit = tmp_path / "explicit-opencode"
    project.mkdir()
    default.parent.mkdir(parents=True)
    default.write_text("#!/bin/sh\n")
    default.chmod(0o700)
    monkeypatch.setattr("tang.adapter_registry.Path.home", lambda: home)
    monkeypatch.setattr(
        "tang.adapter_registry.shutil.which", lambda _name: str(path_executable)
    )
    monkeypatch.setenv("TANG_OPENCODE_EXECUTABLE", str(environment))

    environment_adapter = configured_adapters(project)[-1]
    explicit_adapter = configured_adapters(project, opencode_executable=explicit)[-1]
    monkeypatch.delenv("TANG_OPENCODE_EXECUTABLE")
    path_adapter = configured_adapters(project)[-1]

    assert environment_adapter._executable == str(environment)
    assert explicit_adapter._executable == str(explicit)
    assert path_adapter._executable == str(path_executable)


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


def test_registry_adds_openclaw_when_agent_database_is_present(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    openclaw_home = tmp_path / "openclaw"
    helper = Path(__file__).with_name("test_openclaw_adapter.py")
    spec = importlib.util.spec_from_file_location("openclaw_adapter_test", helper)
    assert spec and spec.loader
    openclaw_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(openclaw_tests)
    openclaw_tests._layout_openclaw(openclaw_home)
    monkeypatch.delenv("TANG_OPENCODE_EXECUTABLE", raising=False)
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "tang.adapter_registry._default_opencode_executable", lambda: None
    )
    monkeypatch.setattr(
        "tang.adapter_registry._openclaw_home", lambda: openclaw_home
    )

    adapters = configured_adapters(
        project,
        codex_home=tmp_path / "codex",
        grok_home=tmp_path / "grok",
    )

    assert [adapter.adapter_key for adapter in adapters] == [
        "codex",
        "grok",
        "openclaw",
    ]


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
