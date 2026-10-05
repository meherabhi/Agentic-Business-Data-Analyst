"""Planner intent mapping is deterministic and maps the expected questions."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner


def test_top_n_extracts_number_and_dimension():
    p = planner.plan("What are the top 5 products by revenue?")
    assert p["intent"] == "top_n"
    assert p["params"]["n"] == 5
    assert p["params"]["dimension"] == "product"


def test_trend_detects_grain():
    assert planner.plan("What is the quarterly revenue trend?")["params"]["grain"] == "quarter"
    assert planner.plan("How has monthly revenue changed over time?")["params"]["grain"] == "month"


def test_unsupported_metric_is_flagged():
    p = planner.plan("What are the top 5 products by profit margin?")
    assert p["intent"] == "unsupported"
    assert p["confidence"] < 0.5


def test_filter_captures_region_and_category():
    p = planner.plan("List orders in the West region for the Accessories category")
    assert p["intent"] == "filter"
    assert p["params"]["region"] == "West"
    assert p["params"]["category"] == "Accessories"


def test_planner_is_deterministic():
    q = "Compare revenue across regions"
    assert planner.plan(q) == planner.plan(q)
