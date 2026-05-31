"""
query_cache.py

Quick terminal inspector for shop_cache.db.
Run from the same folder as the DB:

    python query_cache.py              # summary
    python query_cache.py sku          # search by SKU (partial match)
    python query_cache.py title        # search by title (partial match)

Examples:
    python query_cache.py WDG
    python query_cache.py "blue widget"
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "shop_cache.db"

def connect():
    if not DB_PATH.exists():
        print(f"✗ No DB found at {DB_PATH}")
        print("  Run refresh_shop_cache.py first.")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def summary(con):
    cur = con.execute("SELECT COUNT(*) FROM shop_cache")
    total = cur.fetchone()[0]

    cur = con.execute("SELECT COUNT(*) FROM shop_cache WHERE status='ACTIVE'")
    active = cur.fetchone()[0]

    cur = con.execute("SELECT COUNT(*) FROM shop_cache WHERE status='DRAFT'")
    draft = cur.fetchone()[0]

    cur = con.execute("SELECT COUNT(*) FROM shop_cache WHERE qty <= 0")
    zero_stock = cur.fetchone()[0]

    cur = con.execute("SELECT COUNT(*) FROM shop_cache WHERE bin_location = ''")
    no_bin = cur.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"  shop_cache summary")
    print(f"{'='*50}")
    print(f"  Total variants : {total}")
    print(f"  Active         : {active}")
    print(f"  Draft          : {draft}")
    print(f"  Zero stock     : {zero_stock}")
    print(f"  No bin location: {no_bin}")
    print(f"{'='*50}\n")

    print("Sample rows (first 10):")
    print_rows(con.execute(
        "SELECT sku, title, qty, bin_location, status FROM shop_cache LIMIT 10"
    ))

def search(con, term):
    term = f"%{term}%"
    rows = con.execute(
        """SELECT sku, title, qty, safety_qty, bin_location, status, vendor
           FROM shop_cache
           WHERE sku LIKE ? OR title LIKE ?
           ORDER BY title""",
        (term, term)
    ).fetchall()

    if not rows:
        print(f"\n  No results for '{term.strip('%')}'")
    else:
        print(f"\n  {len(rows)} result(s):\n")
        print_rows(iter(rows), headers=["SKU","Title","Qty","SafeQty","Bin","Status","Vendor"])

def print_rows(cursor, headers=None):
    rows = list(cursor)
    if not rows:
        print("  (no rows)")
        return
    if headers is None:
        headers = [d[0] for d in cursor.description] if hasattr(cursor, 'description') else []
    # column widths
    cols = list(zip(*([headers] + [list(map(str, r)) for r in rows])))
    widths = [max(len(str(v)) for v in col) for col in cols]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    if headers:
        print(fmt.format(*headers))
        print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*[str(v) if v is not None else "" for v in row]))
    print()

def main():
    con = connect()
    if len(sys.argv) < 2:
        summary(con)
    else:
        search(con, " ".join(sys.argv[1:]))
    con.close()

if __name__ == "__main__":
    main()
