import pytest

from agentscope_evals.tools import ToolError, calculate, get_order, search_kb


def test_search_kb_ranks_matching_articles():
    hits = search_kb("How long does express shipping take?")
    assert hits[0]["topic"] == "shipping"
    assert len(hits) <= 2
    assert search_kb("zzz qqq") == []


def test_get_order_normalises_id_and_rejects_unknown():
    assert get_order(" a1002 ")["status"] == "shipped"
    with pytest.raises(ToolError, match="No order"):
        get_order("B9999")


@pytest.mark.parametrize(
    ("expr", "value"),
    [("79 * 0.1", 7.9), ("(19.5 + 4.99) * 2", 48.98), ("-2 ** 3", -8), ("10 / 4", 2.5)],
)
def test_calculate(expr, value):
    assert calculate(expr) == pytest.approx(value)


@pytest.mark.parametrize(
    "expr", ["__import__('os')", "a + 1", "2 ** 1000", "1 / 0", "1 +", "[1, 2]"]
)
def test_calculate_rejects_anything_but_arithmetic(expr):
    with pytest.raises(ToolError):
        calculate(expr)


def test_load_env_only_sets_agent_keys_and_respects_shell(tmp_path, monkeypatch):
    from agentscope_evals.__main__ import load_env

    env = tmp_path / ".env"
    env.write_text(
        'GEMINI_API_KEY="g-key"\nAGENTSCOPE_API_KEY=from-file\nADMIN_TOKEN=secret\n# c\n'
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AGENTSCOPE_API_KEY", "from-shell")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    load_env(env)
    import os

    assert os.environ["GEMINI_API_KEY"] == "g-key"
    assert os.environ["AGENTSCOPE_API_KEY"] == "from-shell"
    assert "ADMIN_TOKEN" not in os.environ
