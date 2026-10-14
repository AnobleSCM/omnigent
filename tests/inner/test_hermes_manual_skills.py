"""Manual skills stay explicit when the Hermes executor starts a turn."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from omnigent.inner.executor import TurnComplete
from omnigent.inner.hermes_executor import HermesExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selected", "expected_preload"),
    [
        (["ordinary", "manual", "bundled-manual"], "ordinary"),
        (["manual"], None),
        ("all", None),
        ("none", None),
    ],
)
async def test_turn_omits_manual_preloads_and_disables_native_rediscovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected: str | list[str],
    expected_preload: str | None,
) -> None:
    """Exercise the CLI boundary with synthetic skills and an inert executable."""
    import omnigent.hermes_native_bridge as bridge

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("RUNNER_SERVER_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(sys, "argv", ["harness", "--conversation-id", "manual-test"])
    monkeypatch.setattr(bridge, "_BRIDGE_ROOT", tmp_path / "bridge")
    monkeypatch.chdir(tmp_path)
    for name, manual in [("manual", True), ("ordinary", False), ("outside-filter", True)]:
        skill = tmp_path / ".agents" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            f"---\nname: {name}\ndescription: fixture\n"
            f"disable-model-invocation: {str(manual).lower()}\n---\n{name} body\n"
        )
    user_config = tmp_path / ".hermes" / "config.yaml"
    user_config.parent.mkdir()
    original = json.dumps(
        {"model": "unchanged-model", "skills": {"disabled": ["already-disabled"]}}
    )
    user_config.write_text(original)
    bundle = tmp_path / "bundle"
    bundled_skill = bundle / "skills" / "bundled-manual" / "SKILL.md"
    bundled_skill.parent.mkdir(parents=True)
    bundled_skill.write_text(
        "---\nname: bundled-manual\ndescription: fixture\n"
        "disable-model-invocation: true\n---\nBundled manual body.\n"
    )
    cli = tmp_path / "hermes-fixture"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "home = pathlib.Path(os.environ['HERMES_HOME'])\n"
        "config = json.loads((home/'config.yaml').read_text())\n"
        "print(json.dumps({'args':sys.argv[1:], 'skills':config.get('skills', {}), "
        "'model':config['model']}))\n"
    )
    cli.chmod(0o700)
    selected_before = json.dumps(selected)
    executor = HermesExecutor(
        hermes_path=str(cli), cwd=str(tmp_path), skills_filter=selected, bundle_dir=str(bundle)
    )
    explicit_message = "<skill>Explicitly selected manual body</skill> literal $value {{args}}"
    try:
        events = [
            event
            async for event in executor.run_turn(
                messages=[{"role": "user", "content": explicit_message}],
                tools=[],
                system_prompt="",
            )
        ]
        assert isinstance(events[-1], TurnComplete)
        observed = json.loads(events[-1].response)
        args = observed["args"]
        if expected_preload is None:
            assert "-s" not in args
        else:
            assert args[args.index("-s") + 1] == expected_preload
        assert ("--ignore-rules" in args) is (selected == "none")
        assert args[args.index("-q") + 1] == explicit_message
        assert set(observed["skills"]["disabled"]) == {
            "manual",
            "outside-filter",
            "bundled-manual",
        }
        assert observed["model"] == "unchanged-model"
        assert json.dumps(selected) == selected_before
        assert user_config.read_text() == original
    finally:
        if executor._hermes_home is not None:
            shutil.rmtree(executor._hermes_home)
