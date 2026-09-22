import pytest

from knowhow.config import Settings, project_root
from knowhow.evals.runner import load_golden, run_eval
from knowhow.runtime import build_runtime
from knowhow.tools.catalog import load_mcp_servers


def test_live_mode_requires_api_key() -> None:
    settings = Settings(_env_file=None, mode="live", openai_api_key="")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings.check()


def test_mcp_config_lists_notes_server() -> None:
    servers = load_mcp_servers(project_root() / "config" / "mcp.yaml")
    assert servers["notes"]["transport"] == "stdio"
    assert "servers/notes_mcp.py" in servers["notes"]["args"]


@pytest.mark.asyncio
async def test_golden_file_passes_offline(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        mode="offline",
        memory_path=tmp_path / "memory.sqlite",
    )
    runtime = await build_runtime(settings)
    cases = load_golden(settings.golden_file.read_text(encoding="utf-8"))
    report = await run_eval(runtime, cases)
    assert report.failed == 0
    assert report.passed == len(cases)
