"""Deterministic SQLite sales warehouse.

Builds a small star-schema warehouse (regions, customers, products, a date
dimension, and an orders fact) entirely from a seeded RNG so every run of the
demo produces byte-identical data. Nothing here touches the network or any
paid service; it is plain sqlite3 from the standard library.
"""
from __future__ import annotations

import os
import random
import sqlite3
from datetime import date, timedelta

SEED = 42

REGIONS = ["North", "South", "East", "West"]
SEGMENTS = ["Consumer", "SMB", "Enterprise"]

# Categories that actually ship product rows. "Accessories" is intentionally
# absent so the agent has a real category with zero sales to reflect on.
CATEGORIES = ["Electronics", "Furniture", "Office Supplies", "Software"]

# A few realistic product names per category so the warehouse reads like a
# real catalog rather than product_1 .. product_n.
PRODUCT_NAMES = {
    "Electronics": ["4K Monitor", "USB-C Dock", "Wireless Mouse", "Mechanical Keyboard",
                    "Noise-Cancel Headset", "Webcam Pro", "Portable SSD", "Label Printer"],
    "Furniture": ["Standing Desk", "Ergonomic Chair", "Filing Cabinet", "Bookshelf Unit",
                  "Conference Table", "Desk Lamp"],
    "Office Supplies": ["Gel Pen Pack", "A4 Paper Ream", "Sticky Notes", "Binder Set",
                        "Whiteboard Marker", "Stapler Kit"],
    "Software": ["Analytics License", "CRM Seat", "Design Suite", "Backup Plan",
                 "Security Add-on", "Collaboration Seat"],
}

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "warehouse.db")


def _price_for(category: str, rng: random.Random) -> float:
    base = {
        "Electronics": (40, 480),
        "Furniture": (90, 720),
        "Office Supplies": (3, 45),
        "Software": (60, 900),
    }[category]
    return round(rng.uniform(*base), 2)


def build(db_path: str = DB_PATH) -> str:
    """Create the warehouse at db_path and return the path. Overwrites any prior file."""
    rng = random.Random(SEED)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE regions(region_id INTEGER PRIMARY KEY, region_name TEXT);
        CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, customer_name TEXT,
                               region_id INTEGER, segment TEXT);
        CREATE TABLE products(product_id INTEGER PRIMARY KEY, product_name TEXT,
                              category TEXT, unit_price REAL);
        CREATE TABLE dim_dates(date_id INTEGER PRIMARY KEY, date TEXT, year INTEGER,
                               month INTEGER, quarter INTEGER);
        CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER,
                            product_id INTEGER, date_id INTEGER, quantity INTEGER,
                            revenue REAL, discount REAL);
        """
    )

    # regions
    for i, name in enumerate(REGIONS, start=1):
        cur.execute("INSERT INTO regions VALUES (?,?)", (i, name))

    # customers: ~120 across regions and segments
    customers = []
    for cid in range(1, 121):
        region_id = rng.randint(1, len(REGIONS))
        segment = rng.choices(SEGMENTS, weights=[5, 3, 2])[0]
        cur.execute("INSERT INTO customers VALUES (?,?,?,?)",
                    (cid, f"Customer {cid:03d}", region_id, segment))
        customers.append((cid, region_id, segment))

    # products
    products = []  # (product_id, category, unit_price)
    pid = 1
    for cat in CATEGORIES:
        for pname in PRODUCT_NAMES[cat]:
            price = _price_for(cat, rng)
            cur.execute("INSERT INTO products VALUES (?,?,?,?)", (pid, pname, cat, price))
            products.append((pid, cat, price))
            pid += 1

    # date dimension: full calendar year 2025
    start = date(2025, 1, 1)
    for d in range(365):
        day = start + timedelta(days=d)
        q = (day.month - 1) // 3 + 1
        cur.execute("INSERT INTO dim_dates VALUES (?,?,?,?,?)",
                    (d + 1, day.isoformat(), day.year, day.month, q))

    # orders fact: ~2000 order lines, one row per order_id
    n_orders = 2000
    price_lookup = {p[0]: p[2] for p in products}
    for oid in range(1, n_orders + 1):
        cid = rng.randint(1, 120)
        prod = rng.choice(products)
        product_id = prod[0]
        # mild monthly seasonality: later months skew slightly higher volume
        date_id = rng.randint(1, 365)
        month = (date_id - 1) // 30 + 1
        qty = rng.randint(1, 8) + (1 if month >= 10 else 0)
        discount = rng.choice([0.0, 0.0, 0.0, 0.05, 0.10, 0.15])
        revenue = round(qty * price_lookup[product_id] * (1 - discount), 2)
        cur.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?)",
                    (oid, cid, product_id, date_id, qty, revenue, discount))

    con.commit()
    con.close()
    return db_path


def connect_readonly(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Open the warehouse in read-only mode using a file: URI."""
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


if __name__ == "__main__":
    path = build()
    con = connect_readonly(path)
    for tbl in ("regions", "customers", "products", "dim_dates", "orders"):
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"{tbl:12s} {n}")
    con.close()
