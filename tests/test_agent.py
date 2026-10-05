"""End-to-end agent behaviour over the seeded warehouse."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
import warehouse


def _con():
    warehouse.build()
    return warehouse.connect_readonly()


def test_suite_metrics_are_sane():
    run = agent.run_suite(_con())
    m = run["metrics"]
    assert m["questions"] == len(agent.SUITE)
    assert 0.0 < m["success_rate"] <= 1.0
    assert m["avg_steps"] > 3  # every question runs a multi-step loop
    assert m["sql_calls"] >= m["questions"] - 1  # all but the unsupported one


def test_empty_slice_triggers_one_retry():
    con = _con()
    out = agent.run_question(
        con, "List orders in the West region for the Accessories category")
    assert out["retried"] is True
    assert out["success"] is True
    phases = [s["status"] for s in out["trace"]]
    assert "retry" in phases


def test_unsupported_metric_fails_honestly():
    con = _con()
    out = agent.run_question(con, "What are the top 5 products by profit margin?")
    assert out["success"] is False
    assert out["intent"] == "unsupported"


def test_guardrail_probes_block_attacks_but_allow_legit_read():
    probes = agent.run_probes()
    blocked = [p for p in probes if p["verdict"] == "blocked"]
    allowed = [p for p in probes if p["verdict"] == "allowed"]
    assert len(blocked) >= 5
    assert any(p["label"] == "legit read" for p in allowed)


def test_run_is_deterministic():
    a = agent.run_suite(_con())["metrics"]
    b = agent.run_suite(_con())["metrics"]
    assert a == b
