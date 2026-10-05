"""SQL guardrails for the agent's sql_tool.

The agent only ever runs SQL that this module has cleared. The checks are
deliberately conservative because the whole point of the tool boundary is that
an autonomous planner cannot reach the warehouse with anything other than a
single, read-only, allowlisted SELECT.

Checks, in order:
  1. read-only        - statement must be a SELECT (or WITH ... SELECT)
  2. no write/DDL     - reject INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/etc.
  3. single statement - reject a second statement smuggled after ';'
  4. no comments      - reject '--' and '/* */' (classic injection carriers)
  5. table allowlist  - every table after FROM/JOIN must be allowlisted
Then enforce_limit() appends a LIMIT if the query has none.
"""
from __future__ import annotations

import re

ALLOWLIST = {"regions", "customers", "products", "dim_dates", "orders"}

FORBIDDEN = [
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "replace", "attach", "detach", "pragma", "vacuum", "reindex", "grant",
]

MAX_LIMIT = 500


def _strip(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def check(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is 'pass' when the query is cleared."""
    raw = sql.strip()
    low = raw.lower()

    # 4. comments first - they can hide anything downstream
    if "--" in raw or "/*" in raw:
        return False, "comment token"

    # 3. single statement: at most one ';', and only as a trailing terminator
    inner = raw.rstrip().rstrip(";")
    if ";" in inner:
        return False, "second statement"

    # 1. read-only entry point
    if not (low.startswith("select") or low.startswith("with")):
        return False, "not read-only"

    # 2. forbidden keywords anywhere (word-boundary matched)
    for kw in FORBIDDEN:
        if re.search(rf"\b{kw}\b", low):
            return False, f"write/DDL ({kw})"

    # 5. table allowlist
    tables = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", low)
    for t in tables:
        if t not in ALLOWLIST:
            return False, f"table not allowed ({t})"

    return True, "pass"


def has_limit(sql: str) -> bool:
    return re.search(r"\blimit\b", sql.lower()) is not None


def enforce_limit(sql: str, limit: int = MAX_LIMIT) -> str:
    """Append a LIMIT clause when the query lacks one. Idempotent."""
    core = _strip(sql)
    if has_limit(core):
        return core
    return f"{core} LIMIT {limit}"
