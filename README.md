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
| [`parse_sales.py`](#parse_salespy) | One-off script to merge ShopifyQL sales query results into a JSON file |

`shop_cache.db` is a local SQLite database populated by `refresh_shop_cache.py`. All other scripts read from it (except `psi_price_compare.py`, which hits Shopify + PSI directly).

---

## Script Reference

### `run-cache-refresh.sh`

The simplest way to refresh the cache. Sets the `SHOPIFY_API_KEY` environment variable and calls `refresh_shop_cache.py`.

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
# Preferred — API key is set for you
./run-cache-refresh.sh

# Manual — set the key yourself
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
- API key and store domain are hardcoded at the top of the file

---

### `parse_sales.py`

One-off utility script that merges two ShopifyQL sales query result files (April and May 2026) into a single JSON file. The input and output paths are hardcoded to specific temp/session directories.

This script is not intended for general reuse — it was written to process a specific pair of ShopifyQL query results from a Claude session. If you need to re-run it, update the `file1`, `file2`, and `outfile` path constants at the top of the script.

**Usage:**

```bash
python3 parse_sales.py
```

**Output:** A JSON array of `{ variant_id, month, gross_sales }` records written to the configured `outfile` path.
