#!/usr/bin/env python3
"""
shopify_variant_stats.py

Pull all variant sales stats for a given month in a single pass.
Saves one record per variant to a JSON file for later analysis.

Usage:
    python shopify_variant_stats.py --month 2026-01
    python shopify_variant_stats.py --month 2026-01 --output 2026-01.json

Requirements:
    pip install requests python-dotenv

.env file (same directory as this script):
    SHOPIFY_STORE=yourstore.myshopify.com
    SHOPIFY_API_KEY=shpat_xxxxxxxxxxxx
"""

import argparse
import calendar
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Credentials ───────────────────────────────────────────────────────────────

load_dotenv()

STORE    = os.getenv("SHOPIFY_STORE", "").strip().rstrip("/")
TOKEN    = os.getenv("SHOPIFY_API_KEY", "").strip()
API_VER  = "2024-04"
BASE_URL = f"https://{STORE}/admin/api/{API_VER}"

HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
}

# ── Month helpers ─────────────────────────────────────────────────────────────

def parse_year_month(value: str) -> tuple[int, int]:
    try:
        dt = datetime.strptime(value, "%Y-%m")
        return dt.year, dt.month
    except ValueError:
        raise ValueError(f"Invalid month format '{value}' — expected YYYY-MM (e.g. 2026-01)")


def month_to_date_range(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


# ── Shopify ───────────────────────────────────────────────────────────────────

def shopify_get(url: str, params: dict = None, retries: int = 3) -> requests.Response:
    """
    GET wrapper that handles Shopify's leaky-bucket rate limiting.

    Shopify allows 2 requests/second with a burst bucket of 40.
    On a 429, it returns a Retry-After header with seconds to wait.
    On 5xx server errors, backs off exponentially and retries.
    """
    for attempt in range(1, retries + 1):
        resp = requests.get(url, headers=HEADERS, params=params)

        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", 2))
            print(f"    ⚠ Rate limited — waiting {wait:.0f}s …", flush=True)
            time.sleep(wait)
            continue  # retry without consuming an attempt slot

        if resp.status_code >= 500:
            if attempt < retries:
                wait = 2 ** attempt  # 2s, 4s, 8s
                print(f"    ⚠ Server error {resp.status_code} — retrying in {wait:.0f}s "
                      f"(attempt {attempt}/{retries}) …", flush=True)
                time.sleep(wait)
                continue

        resp.raise_for_status()
        return resp

    # Exhausted retries on 5xx
    resp.raise_for_status()
    return resp


def fetch_orders(start_date: str, end_date: str) -> list[dict]:
    """Fetch all orders in the date range, paginating automatically."""
    params = {
        "status":          "any",
        "created_at_min":  f"{start_date}T00:00:00Z",
        "created_at_max":  f"{end_date}T23:59:59Z",
        "fields":          "id,created_at,line_items",
        "limit":           250,
    }

    orders = []
    url    = f"{BASE_URL}/orders.json"

    print(f"  Fetching orders for {start_date} → {end_date} …", flush=True)

    while url:
        resp  = shopify_get(url, params)
        batch = resp.json().get("orders", [])
        orders += batch
        print(f"    … {len(orders)} orders so far", flush=True)

        url    = None
        params = None
        link   = resp.headers.get("Link", "")
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break

    return orders


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate_variants(orders: list[dict]) -> dict[int, dict]:
    """
    Single pass over all line items.
    Returns a dict keyed by variant_id with total_quantity, order_count,
    and last_order_date.
    """
    stats: dict[int, dict] = {}

    for order in orders:
        created_at = order["created_at"]

        for item in order.get("line_items", []):
            vid = item.get("variant_id")
            if not vid:
                continue  # skip custom / deleted variants with no ID

            qty = item.get("quantity", 0)

            if vid not in stats:
                stats[vid] = {
                    "total_quantity":  0,
                    "order_count":     0,
                    "last_order_date": None,
                }

            s = stats[vid]
            s["total_quantity"] += qty
            s["order_count"]    += 1

            if s["last_order_date"] is None or created_at > s["last_order_date"]:
                s["last_order_date"] = created_at

    return stats


# ── Output ────────────────────────────────────────────────────────────────────

def build_output(stats: dict[int, dict], year: int, month: int) -> dict:
    records = [
        {
            "variant_id":      vid,
            "year":            year,
            "month":           month,
            "total_quantity":  s["total_quantity"],
            "order_count":     s["order_count"],
            "last_order_date": s["last_order_date"],
        }
        for vid, s in sorted(stats.items())
    ]

    return {
        "meta": {
            "store":         STORE,
            "year":          year,
            "month":         month,
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
            "variant_count": len(records),
        },
        "records": records,
    }


def save(path: Path, data: dict) -> None:
    with path.open("w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Saved → {path}  ({data['meta']['variant_count']} variants)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull all variant sales for a month from Shopify in one pass."
    )
    p.add_argument("--month",  required=True,
                   help="Month to query, format YYYY-MM (e.g. 2026-01)")
    p.add_argument("--output", default=None,
                   help="Output JSON file (default: YYYY-MM.json)")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if not STORE or not TOKEN:
        sys.exit(
            "ERROR: SHOPIFY_STORE and SHOPIFY_API_KEY must be set in your .env file.\n"
            "Example:\n"
            "  SHOPIFY_STORE=yourstore.myshopify.com\n"
            "  SHOPIFY_API_KEY=shpat_xxxxxxxxxxxx"
        )

    try:
        year, month = parse_year_month(args.month)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    start_date, end_date = month_to_date_range(year, month)
    if args.output:
        output_path = Path(args.output)
    else:
        sales_dir = Path(__file__).parent / "sales_data"
        sales_dir.mkdir(exist_ok=True)
        output_path = sales_dir / f"{args.month}.json"

    print(f"\n{'─'*55}")
    print(f"  Store  : {STORE}")
    print(f"  Month  : {args.month}  ({start_date} → {end_date})")
    print(f"  Output : {output_path}")
    print(f"{'─'*55}\n")

    orders = fetch_orders(start_date, end_date)
    print(f"\n  Orders retrieved : {len(orders)}")

    stats = aggregate_variants(orders)
    print(f"  Unique variants  : {len(stats)}")

    data = build_output(stats, year, month)

    print(f"\n{'─'*55}")
    print(f"  Top 5 by quantity sold:")
    top5 = sorted(stats.items(), key=lambda x: x[1]["total_quantity"], reverse=True)[:5]
    for vid, s in top5:
        print(f"    variant {vid:>20}  qty: {s['total_quantity']:>5}  orders: {s['order_count']:>4}")
    print(f"{'─'*55}")

    save(output_path, data)


if __name__ == "__main__":
    main()
