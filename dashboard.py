"""Run the agent over the question suite and render the live-demo dashboard.

Every number and table on the page is computed here from the agent run; nothing
is hardcoded. Output is reports/index.html, rendered through the shared dashkit.
"""
from __future__ import annotations

import os

import agent
import dashkit
import warehouse

ACCENT = "#7c9cff"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "index.html")

STATUS_COLOR = {
    "ok": "#5eead4",
    "warn": "#fcd34d",
    "retry": "#7c9cff",
    "blocked": "#fca5a5",
    "fail": "#fca5a5",
}


def _trunc(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def build_report() -> dict:
    warehouse.build()
    con = warehouse.connect_readonly()
    run = agent.run_suite(con)
    m = run["metrics"]
    outcomes = run["outcomes"]

    # --- traced question: the one that triggered a refined retry ----------
    traced = next(o for o in outcomes if o["retried"])
    trace_rows = []
    for s in traced["trace"]:
        trace_rows.append([
            s["step"],
            s["phase"],
            s["tool"],
            _trunc(s["input"], 34),
            _trunc(s["output"], 46),
            {"t": s["status"], "c": STATUS_COLOR.get(s["status"], ACCENT)},
            f"{s['latency_ms']}",
        ])

    # --- latency per step for the traced question -------------------------
    lat_items = [
        {"label": f"{s['step']} {s['phase']}", "value": s["latency_ms"],
         "color": STATUS_COLOR.get(s["status"], ACCENT)}
        for s in traced["trace"]
    ]

    # --- tool-call distribution -------------------------------------------
    tc = run["tool_calls"]
    tool_items = [{"label": k, "value": v} for k, v in tc.items()]

    # --- intent distribution ----------------------------------------------
    intent_items = [{"label": k, "value": v} for k, v in run["intents"].items()]

    # --- steps per question ------------------------------------------------
    q_labels = [f"Q{i+1}" for i in range(len(outcomes))]
    step_vals = [o["n_steps"] for o in outcomes]

    # --- question -> intent -> answer table -------------------------------
    qia_rows = []
    for i, o in enumerate(outcomes):
        status = "ok" if o["success"] else ("retry" if o["retried"] else "fail")
        qia_rows.append([
            f"Q{i+1}",
            _trunc(o["question"], 44),
            o["intent"],
            f"{o['confidence']:.2f}",
            _trunc(o["answer"], 52),
            {"t": "pass" if o["success"] else "fail",
             "c": STATUS_COLOR["ok"] if o["success"] else STATUS_COLOR["fail"]},
        ])

    # --- guardrail events --------------------------------------------------
    ge_rows = []
    for p in run["probes"]:
        blocked = p["verdict"] == "blocked"
        ge_rows.append([
            p["label"],
            _trunc(p["sql"], 52),
            p["reason"],
            {"t": p["verdict"], "c": STATUS_COLOR["fail"] if blocked else STATUS_COLOR["ok"]},
        ])

    con.close()

    kpis = [
        {"label": "Questions", "value": str(m["questions"]), "count": m["questions"],
         "sub": "analytical NL queries"},
        {"label": "Success rate", "value": f"{m['success_rate']*100:.0f}%",
         "count": m["success_rate"] * 100, "suf": "%", "dec": 0,
         "sub": f"{m['successes']}/{m['questions']} answered"},
        {"label": "Avg steps / question", "value": f"{m['avg_steps']:.1f}",
         "count": m["avg_steps"], "dec": 1, "sub": "plan→act→observe→reflect"},
        {"label": "SQL tool calls", "value": str(m["sql_calls"]), "count": m["sql_calls"],
         "sub": f"{m['retries']} refined retr{'y' if m['retries']==1 else 'ies'}"},
        {"label": "Guardrail blocks", "value": str(m["guardrail_blocks"]),
         "count": m["guardrail_blocks"],
         "sub": f"of {m['guardrail_probes']} adversarial probes"},
    ]

    sections = [
        {
            "title": "Agent run",
            "note": "one deterministic pass over the question suite",
            "cols": 2,
            "panels": [
                {"title": "Success rate", "span": 1,
                 "help": "answered with data",
                 "chart": {"type": "gauge", "value": round(m["success_rate"] * 100, 1),
                           "min": 0, "max": 100, "label": "questions answered",
                           "vfmt": "int",
                           "zones": [{"to": 70, "color": "#fca5a5"},
                                     {"to": 90, "color": "#fcd34d"},
                                     {"to": 100, "color": "#5eead4"}]}},
                {"title": "Steps per question", "span": 1,
                 "help": "trace length varies with retries and failures",
                 "chart": {"type": "bars", "x": q_labels,
                           "series": [{"name": "steps", "color": ACCENT, "values": step_vals}],
                           "yfmt": "int"}},
            ],
        },
        {
            "title": "Tool use",
            "note": "how the loop spends its calls",
            "cols": 2,
            "panels": [
                {"title": "Tool-call distribution", "span": 1,
                 "help": "steps by tool across all questions",
                 "chart": {"type": "donut", "items": tool_items,
                           "center": {"value": str(m["total_steps"]), "label": "steps"}}},
                {"title": "Intent distribution", "span": 1,
                 "help": "planner output across the suite",
                 "chart": {"type": "donut", "items": intent_items,
                           "center": {"value": str(m["questions"]), "label": "questions"}}},
            ],
        },
        {
            "title": "Trace: “" + _trunc(traced["question"], 60) + "”",
            "note": "the question that tripped an empty-slice retry",
            "cols": 1,
            "panels": [
                {"title": "Step-by-step trace", "span": 1,
                 "help": "plan / act / observe / reflect with status and sim latency",
                 "chart": {"type": "table",
                           "columns": ["#", "Phase", "Tool", "Input", "Output", "Status", "ms"],
                           "rows": trace_rows, "accentCol": 1}},
                {"title": "Simulated latency per step", "span": 1,
                 "help": "deterministic per-step timing (ms)",
                 "chart": {"type": "hbars", "items": lat_items, "vfmt": "int"}},
            ],
        },
        {
            "title": "Answers",
            "note": "every question, its planned intent, and the templated answer",
            "cols": 1,
            "panels": [
                {"title": "Question → intent → answer", "span": 1,
                 "chart": {"type": "table",
                           "columns": ["#", "Question", "Intent", "Conf", "Answer", "Result"],
                           "rows": qia_rows, "accentCol": 2}},
            ],
        },
        {
            "title": "Guardrails",
            "note": "adversarial inputs run straight at the SQL boundary",
            "cols": 1,
            "panels": [
                {"title": "Guardrail events", "span": 1,
                 "help": "read-only, single-statement, no-comment, table allowlist",
                 "chart": {"type": "table",
                           "columns": ["Probe", "SQL", "Reason", "Verdict"],
                           "rows": ge_rows, "accentCol": 0}},
            ],
        },
    ]

    dashkit.render(
        OUT,
        title="Agentic Data Analyst",
        subtitle=("An agent that answers analytical questions over a SQLite sales "
                  "warehouse through a plan / act / observe / reflect loop. The "
                  "planner is deterministic (rule-based intent mapping, no LLM); "
                  "the value comes from the agent architecture, the sql_tool "
                  "boundary, and the guardrails around it."),
        accent=ACCENT,
        eyebrow="Live demo",
        kpis=kpis,
        sections=sections,
        footer=("Deterministic run over a seeded 2,000-order warehouse. "
                "Rule-based planner, guarded read-only sql_tool, self-check retry. "
                "No LLM, no network calls."),
        meta="agentic-data-analyst",
    )
    return m


if __name__ == "__main__":
    metrics = build_report()
    size = os.path.getsize(OUT)
    print(f"wrote {OUT} ({size:,} bytes)")
    print(f"success_rate={metrics['success_rate']:.3f} avg_steps={metrics['avg_steps']:.2f} "
          f"blocks={metrics['guardrail_blocks']}")
