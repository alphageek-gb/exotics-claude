# exotics-claude

Scripts for managing ExoticBlanks Shopify product data, inventory cache, and Penn State Industries price comparisons.

## Summary

| Script | Purpose |
|--------|---------|
| [`run-cache-refresh.sh`](#run-cache-refreshsh) | Shell wrapper — easiest way to refresh the local Shopify cache |
| [`refresh_shop_cache.py`](#refresh_shop_cachepy) | Fetches all Shopify products/variants and writes them to `shop_cache.db` |
| [`query_cache.py`](#query_cachepy) | Terminal inspector for browsing and searching `shop_cache.db` |
| [`get_psi_collection.py`](#get_psi_collectionpy) | Exports Penn State Industries variants (SKU, qty, bin) as CSV |
| [`psi_price_compare.py`](#psi_price_comparepy) | Compares your Shopify prices against live pennstateind.com prices |
| [`shopify_variant_stats.py`](#shopify_variant_statspy) | Pulls monthly variant sales data from Shopify and saves to `sales_data/` |
| [`import_to_db.py`](#import_to_dbpy) | Loads monthly JSON files from `sales_data/` into SQLite for analysis |
| [`parse_sales.py`](#parse_salespy) | One-off script to merge ShopifyQL sales query results into a JSON file |

### Data files

| File / Directory | Purpose |
|---|---|
| `.env` | Shopify credentials — never committed |
| `shop_cache.db` | Local SQLite cache of all Shopify products/variants |
| `sales_data/YYYY-MM.json` | Monthly raw sales archives (one file per month) |
| `products.db` | SQLite database for multi-month sales analysis |

### Sales pipeline overview

```
Shopify API
    ↓
shopify_variant_stats.py  →  sales_data/2026-01.json  (raw archive)
                                    ↓
                         import_to_db.py  →  products.db  (analysis layer)
```

The JSON files are your permanent raw archive. The SQLite database is your analysis layer — it joins with your existing product data and handles multi-month queries without re-fetching anything from Shopify.

---

## Setup

### .env file

Create a `.env` file in the project directory (it is gitignored):

```
SHOPIFY_API_KEY=shpat_xxxxxxxxxxxx
SHOPIFY_STORE=yourstore.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxx
```

`SHOPIFY_API_KEY` is used by `refresh_shop_cache.py` and `psi_price_compare.py`.
`SHOPIFY_STORE` and `SHOPIFY_ACCESS_TOKEN` are used by `shopify_variant_stats.py`.

Your access token needs the `read_products`, `read_inventory`, and `read_orders` scopes. Create one in Shopify Admin under **Settings → Apps → Develop apps**.

### Dependencies

```bash
pip install requests beautifulsoup4 python-dotenv
```

---

## Script Reference

### `run-cache-refresh.sh`

The simplest way to refresh the product cache. Sources `.env` and calls `refresh_shop_cache.py`.

```bash
./run-cache-refresh.sh
```

Run this first whenever the local cache is stale or missing.

---

### `refresh_shop_cache.py`

Fetches all **Active** and **Draft** Shopify products via GraphQL (both statuses in parallel) and writes per-variant data to `shop_cache.db`. Replaces the legacy `UpdateDBCache.php` script.

**What it stores per variant:**
- SKU, title, barcode
- Inventory quantity and safety stock qty
- Bin location, safety stock level, restock alert level (from metafields)
- Product status, vendor, tags
- Bundle info (Simple Bundles metafield)

**Usage:**

```bash
# Preferred — API key is sourced from .env automatically
./run-cache-refresh.sh

# Manual
SHOPIFY_API_KEY=shpat_xxx python3 refresh_shop_cache.py
```

**Notes:**
- Fetches Active and Draft concurrently (2 threads)
- Throttle-aware: only sleeps when Shopify's API bucket is actually low
- Writes atomically — the DB is fully replaced in a single transaction
- Archived products are excluded

---

### `query_cache.py`

Quick terminal inspector for `shop_cache.db`. Run it to get a summary of the cache or to search for specific products.

**Usage:**

```bash
# Summary: total variants, active/draft counts, zero-stock count, no-bin count
python3 query_cache.py

# Search by SKU or title (partial match, case-insensitive)
python3 query_cache.py WDG
python3 query_cache.py "blue widget"
python3 query_cache.py DK-PK
```

**Output columns (search):** SKU, Title, Qty, SafeQty, Bin, Status, Vendor

Requires `shop_cache.db` to exist — run `refresh_shop_cache.py` first if it doesn't.

---

### `get_psi_collection.py`

Queries `shop_cache.db` for all **active** Penn State Industries variants and outputs SKU, quantity, and bin location as CSV. Replaces the legacy `get_collection()` PHP script.

**Usage:**

```bash
# Print CSV to terminal
python3 get_psi_collection.py

# Print to terminal AND save to file
python3 get_psi_collection.py out.csv
```

**Output columns:** `sku`, `qty`, `bin_location`

Results are sorted by SKU. Requires `shop_cache.db` — run `refresh_shop_cache.py` first if it doesn't exist.

---

### `psi_price_compare.py`

Fetches all active and draft Penn State Industries products from the `pen-kits` collection in Shopify, then scrapes the base price for each variant from [pennstateind.com](https://www.pennstateind.com) and prints a side-by-side comparison.

SKU translation: strips the 2-character prefix and dash (e.g. `DK-PKHOCKCH` → `PKHOCKCH`) and any trailing `-DISC` suffix before looking up on PSI's site.

**Prerequisites:**

```bash
pip install requests beautifulsoup4
```

**Usage:**

```bash
python3 psi_price_compare.py
```

**Output:** A formatted table showing Product, Variant, Our SKU, PSI SKU, Our Price, PSI Price, and Difference, followed by a summary of mismatches and any SKUs not found on PSI.

**Notes:**
- Reads directly from Shopify (does not use `shop_cache.db`)
- Adds a 0.5-second delay between PSI requests to avoid hammering their site
- Ignores PSI sale prices — compares against the base/original price only

---

### `shopify_variant_stats.py`

Pulls all orders for a given month from Shopify in a single pass, aggregates sales by variant, and saves the results to `sales_data/YYYY-MM.json`.

**Usage:**

```bash
# Pull data for a specific month (saves to sales_data/2026-01.json)
python3 shopify_variant_stats.py --month 2026-01

# Custom output path
python3 shopify_variant_stats.py --month 2026-01 --output /data/sales/2026-01.json
```

**How the date range works:**

| Input | Query range |
|---|---|
| `2026-01` | `2026-01-01` → `2026-01-31` |
| `2026-02` | `2026-02-01` → `2026-02-28` |
| `2024-02` | `2024-02-01` → `2024-02-29` *(leap year)* |
| `2026-12` | `2026-12-01` → `2026-12-31` |

**Notes:**
- Fetches only `id`, `created_at`, and `line_items` — nothing extra
- Pages at 250 orders per request (Shopify's maximum)
- Variants with no sales that month produce no record
- Line items with no `variant_id` (custom or deleted products) are skipped
- Handles 429 rate limiting automatically via `Retry-After` header
- Re-running the same month overwrites the existing file

**Output JSON structure:**

```json
{
  "meta": {
    "store": "yourstore.myshopify.com",
    "year": 2026,
    "month": 1,
    "fetched_at": "2026-01-31T22:14:05+00:00",
    "variant_count": 847
  },
  "records": [
    {
      "variant_id": 12345678901234,
      "year": 2026,
      "month": 1,
      "total_quantity": 47,
      "order_count": 31,
      "last_order_date": "2026-01-28T14:22:05-06:00"
    }
  ]
}
```

---

### `import_to_db.py`

Loads monthly sales JSON files from `sales_data/` into a SQLite database for multi-month analysis. Creates the table automatically if it doesn't exist. Re-importing the same month is always safe — records are upserted, never duplicated.

**Usage:**

```bash
# Import a single month (resolved from sales_data/)
python3 import_to_db.py --file 2026-01.json --db products.db

# Import multiple months using a glob (resolved from sales_data/)
python3 import_to_db.py --file "2026-*.json" --db products.db

# Backfill multiple years
python3 import_to_db.py --file "2024-*.json" "2025-*.json" "2026-*.json" --db products.db

# Explicit path (bypasses sales_data/ resolution)
python3 import_to_db.py --file /data/archive/2026-01.json --db products.db
```

**Monthly workflow:**

```bash
python3 shopify_variant_stats.py --month 2026-05
python3 import_to_db.py --file 2026-05.json
```

**Import all files in `sales_data/` at once:**

```bash
python3 import_to_db.py --file "2026-*.json"
```

**Database schema:**

```sql
CREATE TABLE monthly_variant_sales (
    variant_id      INTEGER  NOT NULL,
    year            INTEGER  NOT NULL,
    month           INTEGER  NOT NULL,
    total_quantity  INTEGER  NOT NULL DEFAULT 0,
    order_count     INTEGER  NOT NULL DEFAULT 0,
    last_order_date TEXT,
    fetched_at      TEXT,
    PRIMARY KEY (variant_id, year, month)
);
```

**Example queries:**

```sql
-- Total units sold per variant across all months
SELECT variant_id, SUM(total_quantity) AS total_qty
FROM monthly_variant_sales
GROUP BY variant_id
ORDER BY total_qty DESC;

-- Month-over-month for a specific variant
SELECT year, month, total_quantity, order_count
FROM monthly_variant_sales
WHERE variant_id = 12345678901234
ORDER BY year, month;

-- Variants that sold in Jan but not Feb
SELECT variant_id FROM monthly_variant_sales WHERE year = 2026 AND month = 1
EXCEPT
SELECT variant_id FROM monthly_variant_sales WHERE year = 2026 AND month = 2;

-- Sales drop > 20% month over month
SELECT
    a.variant_id,
    a.total_quantity AS prev_qty,
    b.total_quantity AS curr_qty,
    ROUND((b.total_quantity - a.total_quantity) * 100.0 / a.total_quantity, 1) AS pct_change
FROM monthly_variant_sales a
JOIN monthly_variant_sales b
    ON a.variant_id = b.variant_id
    AND (a.year * 12 + a.month) = (b.year * 12 + b.month) - 1
WHERE pct_change < -20
ORDER BY pct_change;
```

**Tip:** Upload `products.db` directly to Claude and ask questions in plain English — Claude will write and run the SQL.

---

### `parse_sales.py`

One-off utility script that merges two ShopifyQL sales query result files (April and May 2026) into a single JSON file. The input and output paths are hardcoded to specific temp/session directories.

This script is not intended for general reuse — it was written to process a specific pair of ShopifyQL query results from a Claude session. If you need to re-run it, update the `file1`, `file2`, and `outfile` path constants at the top of the script.

**Usage:**

```bash
python3 parse_sales.py
```

**Output:** A JSON array of `{ variant_id, month, gross_sales }` records written to the configured `outfile` path.
