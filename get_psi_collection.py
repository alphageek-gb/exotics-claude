"""
get_psi_collection.py

Replaces the PHP get_collection() script.
Queries shop_cache.db for active Penn State Industries variants
and prints sku, qty, bin_location as CSV.

Usage:
    python get_psi_collection.py              # print to terminal
    python get_psi_collection.py out.csv      # also save to file
"""

import sqlite3
import csv
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "shop_cache.db"

QUERY = """
    SELECT sku, qty, bin_location
    FROM shop_cache
    WHERE status = 'ACTIVE'
      AND vendor = 'Penn State Industries'
    ORDER BY sku
"""

def main():
    if not DB_PATH.exists():
        print(f"✗ No DB found at {DB_PATH}")
        print("  Run refresh_shop_cache.py first.")
        sys.exit(1)

    outfile = sys.argv[1] if len(sys.argv) > 1 else None

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(QUERY).fetchall()
    con.close()

    writer = csv.writer(sys.stdout)
    for row in rows:
        writer.writerow([row["sku"], row["qty"], row["bin_location"]])

    if outfile:
        with open(outfile, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sku", "qty", "bin_location"])
            for row in rows:
                w.writerow([row["sku"], row["qty"], row["bin_location"]])
        print(f"\n✓ Saved {len(rows)} rows to {outfile}", file=sys.stderr)

if __name__ == "__main__":
    main()
