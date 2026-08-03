from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LEGACY_ACTIONS = {
    "actions/checkout@v4",
    "actions/setup-node@v4",
    "actions/setup-python@v5",
    "actions/upload-artifact@v4",
}


def test_first_party_actions_use_node24_compatible_majors() -> None:
    workflow_root = REPOSITORY_ROOT / ".github" / "workflows"
    workflow_text = "\n".join(
        path.read_text()
        for path in sorted(workflow_root.glob("*.yml"))
    )
    assert not LEGACY_ACTIONS.intersection(workflow_text.split())
    assert "actions/checkout@v6" in workflow_text
    assert "actions/setup-node@v6" in workflow_text
    assert "actions/setup-python@v6" in workflow_text
    assert "actions/upload-artifact@v6" in workflow_text


def test_httpx2_and_alembic_compatibility_are_pinned() -> None:
    pyproject = (REPOSITORY_ROOT / "apps" / "api" / "pyproject.toml").read_text()
    alembic = (REPOSITORY_ROOT / "apps" / "api" / "alembic.ini").read_text()
    assert '"httpx2==2.7.0"' in pyproject
    assert "Using httpx with starlette.testclient is deprecated" in pyproject
    assert "path_separator = os" in alembic
