#!/usr/bin/env python3
"""
import_to_db.py

Import a monthly Shopify sales JSON file into a SQLite database.
Creates the table if it doesn't exist. Re-importing the same month
is safe — existing records are replaced (upsert).

Usage:
    python import_to_db.py --file 2026-01.json --db products.db

    # Import multiple months at once (resolved from sales_data/ directory)
    python import_to_db.py --file 2026-*.json --db products.db
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# ── Schema ────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS monthly_variant_sales (
    variant_id      INTEGER  NOT NULL,
    year            INTEGER  NOT NULL,
    month           INTEGER  NOT NULL,
    total_quantity  INTEGER  NOT NULL DEFAULT 0,
    order_count     INTEGER  NOT NULL DEFAULT 0,
    last_order_date TEXT,
    fetched_at      TEXT,
    PRIMARY KEY (variant_id, year, month)
);

CREATE INDEX IF NOT EXISTS idx_mvs_year_month
    ON monthly_variant_sales (year, month);

CREATE INDEX IF NOT EXISTS idx_mvs_variant
    ON monthly_variant_sales (variant_id);
"""

UPSERT = """
INSERT INTO monthly_variant_sales
    (variant_id, year, month, total_quantity, order_count, last_order_date, fetched_at)
VALUES
    (:variant_id, :year, :month, :total_quantity, :order_count, :last_order_date, :fetched_at)
ON CONFLICT (variant_id, year, month) DO UPDATE SET
    total_quantity  = excluded.total_quantity,
    order_count     = excluded.order_count,
    last_order_date = excluded.last_order_date,
    fetched_at      = excluded.fetched_at;
"""

# ── DB helpers ────────────────────────────────────────────────────────────────

def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()
    return conn


def import_file(conn: sqlite3.Connection, json_path: Path) -> tuple[int, int, int]:
    """
    Load one JSON file into the database.
    Returns (year, month, rows_written).
    """
    with json_path.open() as f:
        data = json.load(f)

    meta    = data.get("meta", {})
    records = data.get("records", [])

    if not records:
        print(f"  {json_path.name} — no records, skipping.")
        return 0, 0, 0

    year  = meta.get("year")
    month = meta.get("month")

    # Fall back to reading year/month from the first record if meta is missing
    if not year or not month:
        year  = records[0].get("year")
        month = records[0].get("month")

    if not year or not month:
        print(f"  ⚠ {json_path.name} — could not determine year/month, skipping.")
        return 0, 0, 0

    fetched_at = meta.get("fetched_at")

    rows = [
        {
            "variant_id":      r["variant_id"],
            "year":            r.get("year", year),
            "month":           r.get("month", month),
            "total_quantity":  r.get("total_quantity", 0),
            "order_count":     r.get("order_count", 0),
            "last_order_date": r.get("last_order_date"),
            "fetched_at":      r.get("fetched_at", fetched_at),
        }
        for r in records
    ]

    with conn:
        conn.executemany(UPSERT, rows)

    return year, month, len(rows)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import monthly Shopify sales JSON file(s) into SQLite."
    )
    p.add_argument("--file", required=True, nargs="+",
                   help="JSON file(s) to import — supports globs e.g. 2026-*.json")
    p.add_argument("--db",   default=str(Path(__file__).parent / "shop_cache.db"),
                   help="Path to SQLite database file (default: shop_cache.db)")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    db_path = Path(args.db)

    # Expand any glob patterns passed as --file arguments.
    # Bare patterns with no path separator are resolved relative to sales_data/.
    sales_dir = Path(__file__).parent / "sales_data"
    files: list[Path] = []
    for pattern in args.file:
        if "/" not in pattern and "\\" not in pattern:
            base = sales_dir
        else:
            base = Path(".")
        matches = sorted(base.glob(pattern)) if "*" in pattern else [base / pattern if base != Path(".") else Path(pattern)]
        files.extend(matches)

    # Deduplicate while preserving order
    seen = set()
    unique_files = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    files = unique_files

    if not files:
        sys.exit("ERROR: No matching files found.")

    # Validate all files exist before touching the DB
    missing = [f for f in files if not f.exists()]
    if missing:
        sys.exit(f"ERROR: File(s) not found:\n" + "\n".join(f"  {f}" for f in missing))

    print(f"\n{'─'*55}")
    print(f"  Database : {db_path}")
    print(f"  Files    : {len(files)}")
    print(f"{'─'*55}\n")

    conn = open_db(db_path)
    total_rows = 0

    for json_path in files:
        year, month, rows = import_file(conn, json_path)
        if rows:
            print(f"  ✓ {json_path.name:<30}  {year}-{month:02d}  →  {rows:>5} variants")
            total_rows += rows

    conn.close()

    print(f"\n{'─'*55}")
    print(f"  Total rows written : {total_rows}")
    print(f"  Database           : {db_path}")
    print(f"{'─'*55}\n")


if __name__ == "__main__":
    main()
