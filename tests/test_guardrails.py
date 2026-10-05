"""Guardrail checks: the SQL boundary must block writes, injection, and
off-allowlist tables, and must enforce a LIMIT."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import guardrails


def test_blocks_write_and_ddl():
    for sql in ["DELETE FROM orders", "UPDATE customers SET x=1",
                "DROP TABLE orders", "INSERT INTO orders VALUES (1)"]:
        ok, _ = guardrails.check(sql)
        assert ok is False, f"should block: {sql}"


def test_blocks_second_statement_and_comments():
    ok1, r1 = guardrails.check("SELECT * FROM orders; DROP TABLE orders")
    assert ok1 is False and r1 == "second statement"
    ok2, r2 = guardrails.check("SELECT * FROM orders -- bypass")
    assert ok2 is False and r2 == "comment token"


def test_table_allowlist():
    ok, reason = guardrails.check("SELECT name FROM sqlite_master")
    assert ok is False and "table not allowed" in reason
    ok2, _ = guardrails.check("SELECT region_name FROM regions")
    assert ok2 is True


def test_enforce_limit_appends_and_is_idempotent():
    q = "SELECT * FROM orders"
    limited = guardrails.enforce_limit(q, 500)
    assert limited.lower().endswith("limit 500")
    # already limited -> unchanged (aside from trailing ';')
    already = "SELECT * FROM orders LIMIT 10"
    assert guardrails.enforce_limit(already) == already


def test_trailing_semicolon_is_allowed():
    ok, _ = guardrails.check("SELECT region_name FROM regions;")
    assert ok is True
