"""The agent: a plan -> act -> observe -> reflect loop over the warehouse.

For each question the agent plans an intent, acts by asking sql_tool to build
and run a guarded query, observes the returned rows, then reflects with a
self-check (guardrail passed, row-count sane). A failed self-check can trigger
exactly one refined retry. Every step is recorded as a trace row with a
simulated, deterministic latency so the dashboard can show real per-step
timing without pretending to have measured wall-clock time from an LLM.
"""
from __future__ import annotations

import hashlib

import planner
import sql_tool

# Latency envelopes (ms) per tool. Simulated but deterministic: derived from a
# hash of the step identity so the same run always yields the same numbers.
_LAT = {
    "planner": (6, 14),
    "sql_tool": (18, 55),
    "observe": (4, 11),
    "reflect": (9, 19),
    "answer": (3, 8),
}


def sim_latency(question: str, step_idx: int, tool: str) -> int:
    lo, hi = _LAT.get(tool, (5, 15))
    h = int(hashlib.sha256(f"{question}|{step_idx}|{tool}".encode()).hexdigest(), 16)
    return lo + (h % (hi - lo + 1))


def _usd(v) -> str:
    return "$" + format(round(float(v)), ",d")


def _answer_text(intent: str, params: dict, result: dict) -> str:
    rows, cols = result["rows"], result["columns"]
    if intent == "top_n":
        dim, metric = params["dimension"], params["metric"]
        top = rows[0]
        val = _usd(top[1]) if metric == "revenue" else f"{int(top[1]):,} orders"
        return (f"The top {params['n']} {dim}s by {metric} are led by "
                f"{top[0]} at {val}.")
    if intent == "trend":
        first, last = rows[0], rows[-1]
        delta = last[1] - first[1]
        dirn = "up" if delta >= 0 else "down"
        return (f"Revenue by {params['grain']} runs from {_usd(first[1])} in "
                f"bucket {first[0]} to {_usd(last[1])} in bucket {last[0]} "
                f"({dirn} {_usd(abs(delta))}).")
    if intent == "comparison":
        lead = rows[0]
        return (f"Across {params['dimension']}, {lead[0]} leads with "
                f"{_usd(lead[1])} in revenue over {len(rows)} groups.")
    if intent == "aggregate":
        if params.get("agg") == "avg":
            return f"The average order value is {_usd(rows[0][0])}."
        total, count = rows[0][0], rows[0][1]
        return f"Total revenue is {_usd(total)} across {int(count):,} orders."
    if intent == "filter":
        count, rev = rows[0][0], rows[0][1]
        return f"That slice contains {int(count):,} orders totalling {_usd(rev)}."
    return "No answer."


def _data_count(intent: str, result: dict) -> int:
    """How many underlying records the result really represents."""
    rows = result["rows"]
    if not rows:
        return 0
    if intent in ("filter", "aggregate"):
        return int(rows[0][0]) if rows[0][0] is not None else 0
    return len(rows)


def run_question(con, question: str) -> dict:
    """Execute one question through the loop. Returns trace + outcome."""
    trace: list[dict] = []
    step = 0

    def add(tool, inp, out, status):
        nonlocal step
        step += 1
        trace.append({
            "step": step,
            "phase": _PHASE[tool],
            "tool": tool,
            "input": inp,
            "output": out,
            "status": status,
            "latency_ms": sim_latency(question, step, tool),
        })

    p = plan = planner.plan(question)
    conf = plan["confidence"]
    add("planner", question,
        f"intent={plan['intent']} · conf={conf:.2f}",
        "ok" if conf >= 0.6 else "warn")

    # Honest failure: the schema cannot express the requested metric.
    if plan["intent"] == "unsupported":
        add("reflect", plan["rationale"],
            "abort: metric absent from schema", "fail")
        add("answer", "-",
            "I cannot answer that; the warehouse has no such metric.", "fail")
        return _outcome(question, plan, trace, success=False,
                        answer="I cannot answer that; the warehouse has no such metric.",
                        result=None, retried=False)

    intent, params = plan["intent"], dict(plan["params"])

    # ACT
    sql, binds = sql_tool.build_sql(intent, params)
    result = sql_tool.run(con, sql, binds)
    if not result["ok"]:
        add("sql_tool", sql[:60], f"blocked: {result['guardrail']}", "blocked")
        add("reflect", "guardrail tripped", "abort", "fail")
        add("answer", "-", "Query blocked by guardrails.", "fail")
        return _outcome(question, plan, trace, success=False,
                        answer="Query blocked by guardrails.", result=result, retried=False)

    add("sql_tool", _sql_summary(intent, params),
        f"{len(result['rows'])} row(s) · guardrail {result['guardrail']}", "ok")

    # OBSERVE
    add("observe", ", ".join(result["columns"]),
        _observe_summary(result), "ok")

    # REFLECT + one optional refined retry
    retried = False
    dc = _data_count(intent, result)
    if intent == "filter" and dc == 0 and params.get("category"):
        add("reflect", f"data_count={dc}",
            "empty slice; relax category filter and retry", "retry")
        params.pop("category", None)
        sql, binds = sql_tool.build_sql(intent, params)
        result = sql_tool.run(con, sql, binds)
        retried = True
        add("sql_tool", _sql_summary(intent, params),
            f"{len(result['rows'])} row(s) · guardrail {result['guardrail']}", "ok")
        add("observe", ", ".join(result["columns"]), _observe_summary(result), "ok")
        dc = _data_count(intent, result)

    success = dc > 0
    add("reflect", f"data_count={dc}",
        "row-count sane · guardrail pass" if success else "no matching data",
        "ok" if success else "warn")

    answer = _answer_text(intent, params, result) if success else \
        "No matching records for that request."
    add("answer", "-", answer, "ok" if success else "warn")

    return _outcome(question, plan, trace, success=success, answer=answer,
                    result=result, retried=retried)


_PHASE = {
    "planner": "plan", "sql_tool": "act", "observe": "observe",
    "reflect": "reflect", "answer": "answer",
}


def _sql_summary(intent: str, params: dict) -> str:
    bits = [intent]
    for k in ("dimension", "grain", "agg", "region", "category"):
        if params.get(k):
            bits.append(f"{k}={params[k]}")
    return " ".join(bits)


def _observe_summary(result: dict) -> str:
    rows = result["rows"]
    if not rows:
        return "0 rows"
    head = rows[0]
    return "top: " + " | ".join(str(x) for x in head[:3])


def _outcome(question, plan, trace, *, success, answer, result, retried) -> dict:
    return {
        "question": question,
        "intent": plan["intent"],
        "confidence": plan["confidence"],
        "answer": answer,
        "success": success,
        "retried": retried,
        "trace": trace,
        "n_steps": len(trace),
        "total_latency_ms": sum(s["latency_ms"] for s in trace),
        "result": result,
    }


# --- the question suite ----------------------------------------------------
SUITE = [
    "What are the top 5 products by revenue?",
    "Show me the top 3 regions by total orders",
    "How has monthly revenue changed over time?",
    "What is the quarterly revenue trend?",
    "Compare revenue across regions",
    "Compare total revenue by customer segment",
    "What is the total revenue?",
    "What is the average order value?",
    "Show revenue for the Electronics category",
    "List orders in the West region for the Accessories category",
    "What are the top 5 products by profit margin?",
]

# --- adversarial guardrail probes ------------------------------------------
# These never come from the planner; they exercise the guardrail directly so
# the dashboard can report what the boundary actually blocks.
PROBES = [
    ("second statement", "SELECT * FROM orders; DROP TABLE orders"),
    ("write attempt", "DELETE FROM orders WHERE 1=1"),
    ("schema probe", "SELECT name FROM sqlite_master"),
    ("comment carrier", "SELECT * FROM orders -- bypass limit"),
    ("mutation", "UPDATE customers SET segment='x' WHERE 1=1"),
    ("block comment", "SELECT * FROM orders WHERE 1=1 /* injected */"),
    ("legit read", "SELECT region_name FROM regions"),
]


def run_probes() -> list[dict]:
    import guardrails
    events = []
    for label, sql in PROBES:
        ok, reason = guardrails.check(sql)
        events.append({
            "label": label,
            "sql": sql,
            "verdict": "allowed" if ok else "blocked",
            "reason": reason,
        })
    return events


def run_suite(con) -> dict:
    outcomes = [run_question(con, q) for q in SUITE]
    probes = run_probes()

    n = len(outcomes)
    successes = sum(o["success"] for o in outcomes)
    tool_calls: dict[str, int] = {}
    for o in outcomes:
        for s in o["trace"]:
            tool_calls[s["tool"]] = tool_calls.get(s["tool"], 0) + 1
    intents: dict[str, int] = {}
    for o in outcomes:
        intents[o["intent"]] = intents.get(o["intent"], 0) + 1

    guardrail_blocks = sum(1 for p in probes if p["verdict"] == "blocked")

    return {
        "outcomes": outcomes,
        "probes": probes,
        "metrics": {
            "questions": n,
            "successes": successes,
            "success_rate": successes / n,
            "avg_steps": sum(o["n_steps"] for o in outcomes) / n,
            "sql_calls": tool_calls.get("sql_tool", 0),
            "total_steps": sum(o["n_steps"] for o in outcomes),
            "retries": sum(o["retried"] for o in outcomes),
            "guardrail_blocks": guardrail_blocks,
            "guardrail_probes": len(probes),
            "avg_latency_ms": sum(o["total_latency_ms"] for o in outcomes) / n,
        },
        "tool_calls": tool_calls,
        "intents": intents,
    }
