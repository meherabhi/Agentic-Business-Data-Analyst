# Agentic Data Analyst

I built an agent that answers analytical questions over a SQLite sales
warehouse. It runs a plan / act / observe / reflect loop with a tool boundary
and guardrails, the same architecture a production LLM agent uses. The
difference here is that the planner is deterministic: it maps a natural-language
question to an intent with rules, not a model. I wanted the agent machinery to
be fully inspectable and reproducible, so every run produces the same numbers.

## What it does

For each question the agent:

1. **Plans.** A rule-based planner reads the question and picks one of five
   intents (top-N, trend-over-time, comparison, aggregate, filter) plus
   parameters. It attaches a confidence score. If a question asks for something
   the schema cannot express (a profit-margin metric that does not exist), the
   planner returns an `unsupported` intent so the agent can decline instead of
   inventing SQL.
2. **Acts.** The `sql_tool` turns the intent into a single parameterized SELECT
   and runs it. User strings are bound parameters, never concatenated into SQL.
3. **Observes.** It reads the returned rows and summarizes them.
4. **Reflects.** A self-check confirms the guardrail passed and the row count is
   sane. If a slice came back empty, the agent retries once with a relaxed
   filter. If nothing helps, it reports no data rather than guessing.

Then it answers with a templated sentence backed by the actual result table.

## Guardrails

Every query the agent runs passes through `guardrails.check` first:

- read-only: the statement must be a `SELECT` (or `WITH ... SELECT`)
- no writes or DDL: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `PRAGMA`, and friends are rejected
- single statement: a second statement smuggled after `;` is rejected
- no comment tokens: `--` and `/* */` are rejected
- table allowlist: every table after `FROM`/`JOIN` must be one of the five warehouse tables

A `LIMIT` is enforced when the query lacks one. I test the boundary directly
with a set of adversarial probes (a stacked `DROP`, a bare `DELETE`, a
`sqlite_master` schema probe, comment-based bypasses) and record which get
blocked.

## The warehouse

`warehouse.py` builds a small star schema entirely from a seeded RNG: 4 regions,
120 customers, 26 products across 4 categories, a 365-day date dimension, and
2,000 order rows. Same seed, same data, every time. It is plain `sqlite3` from
the standard library.

## Running it

```
make demo       # runs the agent suite and writes the interactive reports/index.html
make analytics  # runs the static analytics dashboard instead
make test       # runs the stdlib test suite
```

`make demo` builds an interactive live demo: I run `agent.run_suite()` over the
11-question suite, capture the full trace, generated SQL, guardrail verdict, and
result rows for each, and freeze them into one self-contained `reports/index.html`
(inline JSON + vanilla JS, no server, no libraries). In the page you click a
question — or type your own, which routes to the nearest question by keyword
overlap — and watch the agent's plan → act → observe → reflect → answer loop
animate step by step: the chosen intent and confidence, the parameterized SQL
with its guardrail pass badge, and the real result table. An always-visible
guardrail bench lets you fire the adversarial probes (stacked `DROP`, bare
`DELETE`, `sqlite_master`, comment bypasses) and see them blocked at the boundary.

`make analytics` renders the earlier static dashboard: the trace for the retry
question, tool-call and intent distributions, steps per question, a success-rate
gauge, per-step latency, a question-to-intent-to-answer table, and guardrail events.

## Honest scope

This is a deterministic intent planner, not a live LLM. The latency numbers per
step are simulated (derived deterministically from the step identity), not
wall-clock measurements of a model. What is real: the warehouse, the SQL
generation and execution, the guardrail checks, the retry logic, and every
metric on the dashboard. The goal was to show the agent architecture end to end
without the nondeterminism and cost of a model in the loop.

## Layout

- `warehouse.py` — seeded SQLite warehouse builder
- `planner.py` — rule-based NL to intent mapping
- `sql_tool.py` — intent to parameterized SQL, guarded and executed
- `guardrails.py` — the read-only SQL boundary
- `agent.py` — the plan / act / observe / reflect loop, suite, and probes
- `interactive.py` — runs the suite and renders the interactive `reports/index.html`
- `dashboard.py` — runs the suite and renders the static analytics dashboard
- `tests/` — stdlib runner with planner, guardrail, and end-to-end checks

Requires Python 3.11+. No third-party packages.
