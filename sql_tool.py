"""sql_tool: turn a plan into parameterized SQL, guard it, and run it read-only.

build_sql() maps an intent + params to a single parameterized SELECT and its
bound values. run() is the actual tool the agent calls: it guards the SQL,
enforces a LIMIT, and executes it against a read-only connection. Every query
uses bound parameters, so user-supplied strings never touch the SQL text.
"""
from __future__ import annotations

import guardrails


def build_sql(intent: str, params: dict) -> tuple[str, list]:
    """Return (sql, bound_params) for a plan. Raises ValueError if unbuildable."""
    metric = params.get("metric", "revenue")
    agg_expr = "SUM(o.revenue)" if metric == "revenue" else "COUNT(*)"
    alias = "total_revenue" if metric == "revenue" else "order_count"

    if intent == "top_n":
        dim = params["dimension"]
        n = int(params["n"])
        if dim == "product":
            sql = (f"SELECT p.product_name AS label, {agg_expr} AS {alias} "
                   "FROM orders o JOIN products p ON o.product_id = p.product_id "
                   f"GROUP BY p.product_name ORDER BY {alias} DESC LIMIT ?")
            return sql, [n]
        if dim == "region":
            sql = (f"SELECT r.region_name AS label, {agg_expr} AS {alias} "
                   "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
                   "JOIN regions r ON c.region_id = r.region_id "
                   f"GROUP BY r.region_name ORDER BY {alias} DESC LIMIT ?")
            return sql, [n]
        if dim == "segment":
            sql = (f"SELECT c.segment AS label, {agg_expr} AS {alias} "
                   "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
                   f"GROUP BY c.segment ORDER BY {alias} DESC LIMIT ?")
            return sql, [n]
        if dim == "category":
            sql = (f"SELECT p.category AS label, {agg_expr} AS {alias} "
                   "FROM orders o JOIN products p ON o.product_id = p.product_id "
                   f"GROUP BY p.category ORDER BY {alias} DESC LIMIT ?")
            return sql, [n]

    if intent == "trend":
        grain = params["grain"]
        col = "d.quarter" if grain == "quarter" else "d.month"
        sql = (f"SELECT {col} AS bucket, SUM(o.revenue) AS total_revenue "
               "FROM orders o JOIN dim_dates d ON o.date_id = d.date_id "
               f"GROUP BY {col} ORDER BY {col}")
        return sql, []

    if intent == "comparison":
        dim = params["dimension"]
        if dim == "segment":
            sql = ("SELECT c.segment AS label, SUM(o.revenue) AS total_revenue "
                   "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
                   "GROUP BY c.segment ORDER BY total_revenue DESC")
            return sql, []
        sql = ("SELECT r.region_name AS label, SUM(o.revenue) AS total_revenue "
               "FROM orders o JOIN customers c ON o.customer_id = c.customer_id "
               "JOIN regions r ON c.region_id = r.region_id "
               "GROUP BY r.region_name ORDER BY total_revenue DESC")
        return sql, []

    if intent == "aggregate":
        agg = params.get("agg", "sum")
        if agg == "avg":
            sql = "SELECT AVG(o.revenue) AS avg_order_value FROM orders o"
        else:
            sql = "SELECT SUM(o.revenue) AS total_revenue, COUNT(*) AS order_count FROM orders o"
        return sql, []

    if intent == "filter":
        region = params.get("region")
        category = params.get("category")
        wheres, binds = [], []
        joins = ("FROM orders o "
                 "JOIN customers c ON o.customer_id = c.customer_id "
                 "JOIN regions r ON c.region_id = r.region_id "
                 "JOIN products p ON o.product_id = p.product_id")
        if region:
            wheres.append("r.region_name = ?")
            binds.append(region)
        if category:
            wheres.append("p.category = ?")
            binds.append(category)
        where = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        sql = ("SELECT COUNT(*) AS order_count, "
               "COALESCE(SUM(o.revenue), 0) AS total_revenue "
               f"{joins}{where}")
        return sql, binds

    raise ValueError(f"cannot build SQL for intent '{intent}'")


def run(con, sql: str, binds: list) -> dict:
    """Guard, limit-enforce, and execute. Returns a structured tool result."""
    ok, reason = guardrails.check(sql)
    if not ok:
        return {"ok": False, "guardrail": reason, "rows": [], "columns": [], "sql": sql}
    safe_sql = guardrails.enforce_limit(sql)
    cur = con.execute(safe_sql, binds)
    columns = [d[0] for d in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    return {"ok": True, "guardrail": "pass", "rows": rows, "columns": columns, "sql": safe_sql}
