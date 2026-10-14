"""Manual skills stay available to users without automatic model activation."""

from pathlib import Path

import pytest

from omnigent.spec.parser import discover_host_skills
from omnigent.tools.base import ToolContext


@pytest.mark.parametrize(
    ("flag", "expected"),
    [("true", True), ("false", False), ('"false"', False), (None, False)],
)
def test_host_skill_preserves_manual_activation_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str | None, expected: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    package = tmp_path / ".agents" / "skills" / "manual-guide"
    package.mkdir(parents=True)
    policy = f"disable-model-invocation: {flag}\n" if flag is not None else ""
    (package / "SKILL.md").write_text(
        "---\nname: manual-guide\ndescription: User-selected guide.\n"
        f"{policy}---\nOnly act when the user selects this guide.\n"
    )
    skills = discover_host_skills(tmp_path, ["manual-guide"])
    assert len(skills) == 1
    assert skills[0].disable_model_invocation is expected
    assert skills[0].user_invocable is True


def test_model_loader_hides_manual_skills_but_preserves_user_selection(
    tmp_path: Path, tool_ctx: ToolContext
) -> None:
    import json

    from omnigent.spec.types import SkillSpec
    from omnigent.tools.builtins.load_skill import (
        LoadSkillTool,
        find_skill_by_name,
        format_skill_meta_text,
    )

    manual = SkillSpec(
        name="manual-guide",
        description="Manual-only description.",
        content="Manual body.",
        disable_model_invocation=True,
    )
    ordinary = SkillSpec(name="ordinary", description="Ordinary guide.", content="Ordinary body.")
    tool = LoadSkillTool([manual, ordinary], agent_root=tmp_path, skills_filter="none")
    assert "manual-guide" not in json.dumps(tool.get_schema())
    assert tool.invoke('{"name":"manual-guide"}', tool_ctx) == (
        "Error: skill 'manual-guide' requires explicit user invocation"
    )
    assert "manual-guide" not in tool.invoke('{"name":"unknown"}', tool_ctx)
    assert tool.invoke('{"name":"ordinary"}', tool_ctx) == "Ordinary body."
    assert find_skill_by_name(tool.skills, "manual-guide") is manual
    assert format_skill_meta_text(manual, "literal $(echo hi) {{args}}") == (
        "<skill>\n<name>manual-guide</name>\nManual body.\n</skill>\n\n"
        "<user_request>\nliteral $(echo hi) {{args}}\n</user_request>"
    )


@pytest.mark.parametrize(
    "body_path",
    [
        "SKILL.md",
        "./SKILL.md",
        "references/../SKILL.md",
        "references/body.md",
        "references/hardlink.md",
    ],
)
def test_manual_resource_reader_refuses_body_aliases(
    tmp_path: Path, tool_ctx: ToolContext, body_path: str
) -> None:
    import json
    import os

    from omnigent.spec.types import SkillSpec
    from omnigent.tools.builtins.read_skill_file import ReadSkillFileTool

    package = tmp_path / "manual-guide"
    (package / "references").mkdir(parents=True)
    (package / "SKILL.md").write_text("Manual body.")
    (package / "references" / "body.md").symlink_to("../SKILL.md")
    os.link(package / "SKILL.md", package / "references" / "hardlink.md")
    (package / "references" / "guide.md").write_text("Supporting instructions.")
    skill = SkillSpec(
        "manual-guide",
        "Manual description",
        "Manual body.",
        package,
        disable_model_invocation=True,
    )
    reader = ReadSkillFileTool([skill])
    assert reader.invoke(json.dumps({"skill_name": skill.name, "path": body_path}), tool_ctx) == (
        "Error: skill instructions require explicit user invocation"
    )
    assert (
        reader.invoke(
            json.dumps({"skill_name": skill.name, "path": "references/guide.md"}), tool_ctx
        )
        == "Supporting instructions."
    )
    assert "manual-guide" not in reader.invoke(
        '{"skill_name":"missing","path":"file.md"}', tool_ctx
    )
