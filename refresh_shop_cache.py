"""
refresh_shop_cache.py

Replicates UpdateDBCache.php logic:
- Fetches all Active + Draft Shopify products via GraphQL (concurrently)
- Extracts per-variant data including metafields and safety stock qty
- Writes atomically to shop_cache.db (SQLite) in the same directory as this script

Optimizations vs original PHP:
- Active + Draft fetched concurrently (2 threads)
- Page size doubled to 50 products per request
- Throttle-aware sleeping: only sleeps when Shopify's bucket is actually low,
  and only for the exact seconds needed — not a flat 5s every page

Usage:
    SHOPIFY_API_KEY=shpat_xxx python refresh_shop_cache.py
    -- or --
    python refresh_shop_cache.py  (if ACCESS_TOKEN is set in the script)
"""

import os
import sqlite3
import json
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Load .env from script directory
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ────────────────────────────────────────────────────────────────────
SHOP         = "8c556d-09.myshopify.com"
ACCESS_TOKEN = os.environ["SHOPIFY_API_KEY"]
API_VERSION  = "2024-01"
GQL_URL      = f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json"
DB_PATH      = Path(__file__).parent / "shop_cache.db"

PAGE_SIZE = 50   # doubled from 25; safe given nested query cost
THROTTLE_MARGIN = 1.5  # sleep if available points < last cost × this multiplier
MAX_SLEEP = 15   # cap any single sleep at 15 seconds

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}

# ── Throttle manager (shared across threads) ─────────────────────────────────
# Shopify GraphQL bucket: 1000 pts max, restores at 50 pts/sec.
# Both concurrent threads share this bucket, so we coordinate sleeps.

_throttle_lock = threading.Lock()
_throttle_available = 1000.0
_throttle_restore_rate = 50.0

def _update_and_maybe_sleep(cost_ext, label=""):
    """Read throttle status from a GraphQL cost extension and sleep if needed."""
    global _throttle_available, _throttle_restore_rate

    if not cost_ext:
        return

    requested = cost_ext.get("requestedQueryCost", 0)
    status = cost_ext.get("throttleStatus", {})
    available = status.get("currentlyAvailable", _throttle_available)
    restore_rate = status.get("restoreRate", _throttle_restore_rate)
    maximum = status.get("maximumAvailable", 1000)

    with _throttle_lock:
        _throttle_available = available
        _throttle_restore_rate = restore_rate

        needed = requested * THROTTLE_MARGIN
        if available < needed:
            sleep_secs = min((needed - available) / restore_rate, MAX_SLEEP)
            if sleep_secs > 0.1:
                print(f"  [{label}] Throttle {available:.0f}/{maximum} pts — sleeping {sleep_secs:.1f}s")
                time.sleep(sleep_secs)
            return

    # No sleep needed — log progress without the sleep noise
    print(f"  [{label}] Page done. Throttle: {available:.0f}/{maximum} pts remaining")


# ── GraphQL Query ─────────────────────────────────────────────────────────────
PRODUCTS_QUERY = """
query getProducts($status: String!, $cursor: String, $pageSize: Int!) {
  products(first: $pageSize, query: $status, after: $cursor) {
    nodes {
      id
      title
      status
      vendor
      tags
      variantsCount { count }
      variants(first: 100) {
        nodes {
          id
          sku
          title
          barcode
          inventoryQuantity
          inventoryItem {
            inventoryLevels(first: 1) {
              nodes {
                quantities(names: ["safety_stock"]) {
                  quantity
                }
              }
            }
          }
          bin_location: metafield(namespace: "custom", key: "bin_location") { value }
          safety_stock_level: metafield(namespace: "custom", key: "safety_stock_level") { value }
          restock_alert_level: metafield(namespace: "custom", key: "restock_alert_level") { value }
          bundled: metafield(namespace: "simple_bundles", key: "bundled_variants") { value }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

# ── Shopify GraphQL fetch ─────────────────────────────────────────────────────
def run_query(query, variables):
    resp = requests.post(GQL_URL, headers=HEADERS,
                         json={"query": query, "variables": variables})
    resp.raise_for_status()
    body = resp.json()
    if "errors" in body:
        raise RuntimeError(f"GraphQL errors: {body['errors']}")
    cost = body.get("extensions", {}).get("cost", {})
    return body["data"], cost


def get_products(status):
    """Fetch all products of a given status, paginating with throttle-aware sleep."""
    rows = []
    cursor = None
    label = status  # used in log output

    while True:
        variables = {
            "status": f"status:{status}",
            "cursor": cursor,
            "pageSize": PAGE_SIZE,
        }
        data, cost = run_query(PRODUCTS_QUERY, variables)
        page = data["products"]

        for product in page["nodes"]:
            rows.extend(process_product(product))

        page_info = page["pageInfo"]
        has_next = page_info["hasNextPage"]

        # Always check throttle — sleep only if bucket is running low
        _update_and_maybe_sleep(cost, label=label)

        if not has_next:
            break

        cursor = page_info["endCursor"]

    return rows


# ── Data processing (mirrors process_product() in PHP) ────────────────────────
def process_product(product):
    rows = []
    variant_count = product["variantsCount"]["count"]

    for v in product["variants"]["nodes"]:
        # Build display title (matches PHP logic)
        if variant_count > 1:
            name = f"{product['title']} - {v['title']}"
        else:
            name = product["title"]

        # Safety stock qty from inventoryLevels
        try:
            safe_qty = (
                v["inventoryItem"]["inventoryLevels"]["nodes"][0]
                 ["quantities"][0]["quantity"]
            )
        except (IndexError, KeyError, TypeError):
            safe_qty = None

        rows.append({
            "bin_location":        (v.get("bin_location") or {}).get("value", ""),
            "variant":             v["id"],
            "product":             product["id"],
            "qty":                 v["inventoryQuantity"],
            "safety_qty":          safe_qty,
            "sku":                 v.get("sku") or "",
            "sku_count":           variant_count,
            "title":               name,
            "status":              product["status"],
            "vendor":              product["vendor"],
            "bundle":              (v.get("bundled") or {}).get("value", ""),
            "barcode":             v.get("barcode") or "",
            "tags":                json.dumps(product["tags"]) if product.get("tags") else "",
            "safety_stock_level":  (v.get("safety_stock_level") or {}).get("value"),
            "restock_alert_level": (v.get("restock_alert_level") or {}).get("value"),
        })

    return rows


# ── SQLite write (atomic swap via transaction) ────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS shop_cache (
    bin_location        TEXT,
    variant             TEXT,
    product             TEXT,
    qty                 INTEGER,
    safety_qty          INTEGER,
    sku                 TEXT,
    sku_count           INTEGER,
    title               TEXT,
    status              TEXT,
    vendor              TEXT,
    bundle              TEXT,
    barcode             TEXT,
    tags                TEXT,
    safety_stock_level  TEXT,
    restock_alert_level TEXT
);
"""

def write_to_sqlite(rows):
    con = sqlite3.connect(DB_PATH)
    try:
        with con:  # single atomic transaction
            con.execute(DDL)
            con.execute("DELETE FROM shop_cache")
            con.executemany(
                """INSERT INTO shop_cache
                   (bin_location, variant, product, qty, safety_qty, sku, sku_count,
                    title, status, vendor, bundle, barcode, tags,
                    safety_stock_level, restock_alert_level)
                   VALUES
                   (:bin_location, :variant, :product, :qty, :safety_qty, :sku, :sku_count,
                    :title, :status, :vendor, :bundle, :barcode, :tags,
                    :safety_stock_level, :restock_alert_level)
                """,
                rows,
            )
        print(f"✓ Wrote {len(rows)} rows to {DB_PATH}")
    finally:
        con.close()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    started = datetime.now(timezone.utc)
    print(f"[{started.strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting shop_cache refresh…")
    print(f"  Page size: {PAGE_SIZE} | Concurrent: Active + Draft in parallel\n")

    # Fetch Active and Draft concurrently
    results = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(get_products, "Active"): "Active",
            executor.submit(get_products, "Draft"):  "Draft",
        }
        for future in as_completed(futures):
            status = futures[future]
            rows = future.result()  # re-raises any exception from the thread
            results[status] = rows
            print(f"  → {status}: {len(rows)} variant rows fetched")

    all_rows = results["Active"] + results["Draft"]
    print(f"\nTotal: {len(all_rows)} rows. Writing to SQLite…")
    write_to_sqlite(all_rows)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
