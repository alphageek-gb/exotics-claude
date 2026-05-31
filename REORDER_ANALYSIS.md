# Reorder Analysis — How To Run

## What This Does

Generates a per-SKU reorder report as an `.xlsx` file showing:
- Monthly sales (Jan–May, or whatever 5-month window is loaded)
- Weighted average monthly sales (zero-sales months downweighted to reduce outage distortion)
- Estimated runout month based on current stock
- Recommended order quantity accounting for lead time + 3 months forward demand

---

## Data Sources

### Database
`/Users/deancharlier/cowork/shop_cache.db` — SQLite, two tables:

**`shop_cache`** — one row per product variant, refreshed by `refresh_shop_cache.py`
- Key columns: `title`, `sku`, `qty` (on-hand), `status`, `vendor`, `tags`, `variant` (Shopify GID)
- The `variant` column holds a GID like `gid://shopify/ProductVariant/43458916778037`
- Extract the numeric variant ID: `CAST(REPLACE(variant, 'gid://shopify/ProductVariant/', '') AS INTEGER)`

**`monthly_variant_sales`** — one row per variant per month, loaded from `sales_data/*.json`
- Key columns: `variant_id` (numeric), `year`, `month`, `total_quantity`
- Currently loaded: Jan–May 2026 (5 months)

### Join Key
```sql
CAST(REPLACE(sc.variant, 'gid://shopify/ProductVariant/', '') AS INTEGER) = mvs.variant_id
```
**Do NOT use the Shopify API** — all data needed is in the local DB.

### Sales Data JSON Files
`/Users/deancharlier/Projects/exotics-claude/sales_data/YYYY-MM.json`
Import new months with: `python import_to_db.py --file sales_data/2026-06.json --db shop_cache.db`

---

## Analysis Logic

### Weighted Average
Zero-sales months get weight **0.4×**, non-zero months get **1.0×**. This reduces distortion when a month had no sales due to a site outage or stock being empty rather than genuine zero demand.

```python
total_weight = sum(0.4 if s == 0 else 1.0 for s in m_sales)
weighted_avg = sum(s * (0.4 if s == 0 else 1.0) for s in m_sales) / total_weight
```

### Estimated Runout
`months_until_runout = qty_on_hand / weighted_avg` (from current month)

### Order Quantity
```
order_qty = max(0, ceil(weighted_avg * (lead_time_months + 3) - qty_on_hand))
```
The +3 is a 3-month forward demand buffer. Adjust if Dean wants a different buffer.

---

## Vendor / Filter Configurations Run So Far

| Report | Filter | Lead Time | Color Thresholds |
|--------|--------|-----------|-----------------|
| DG1 tag | `tags LIKE '%DG1%'` | 6 weeks (1.5 mo) | 🔴 ≤2mo, 🟡 2–4mo |
| ExoticBlanks | `vendor = 'ExoticBlanks'` | 3 months | 🔴 ≤3mo, 🟡 3–6mo |
| Penn State Industries | `vendor = 'Penn State Industries'` | 3 weeks (0.69 mo) | 🔴 ≤1mo, 🟡 1–3mo |

---

## Questions to Ask Before Running

1. **What to filter by?** Tag (e.g. `DG1`) or vendor name? Ask Dean to confirm the exact value — check distinct values with:
   ```sql
   SELECT DISTINCT vendor FROM shop_cache;
   SELECT DISTINCT tags FROM shop_cache LIMIT 50;
   ```

2. **What is the lead time?** In weeks or months. Convert weeks to months as `weeks / 4.33`.

3. **How many months of forward demand buffer?** Default is 3 months — confirm if different.

4. **Which months of sales data to use?** Default is the 5 most recent months loaded in the DB. Check with:
   ```sql
   SELECT DISTINCT year, month FROM monthly_variant_sales ORDER BY year, month;
   ```

5. **Should archived/draft products be included?** Default is to include all statuses (active, draft, archived) — filter with `AND sc.status = 'ACTIVE'` if Dean only wants active products.

---

## Output Format

- Excel `.xlsx`, saved to `/Users/deancharlier/Projects/exotics-claude/`
- Columns: Product Title, SKU, Status, Jan, Feb, Mar, Apr, May, Wtd Avg/Mo, Est. Runout, Qty on Hand, Order Qty
- Order Qty column color-coded by urgency (red/yellow/green) based on lead time
- Auto-filter enabled on all columns, freeze panes at row 5

### Color threshold logic
Set thresholds relative to lead time — products that will run out before a reorder could arrive are red:
- Red: runout ≤ lead_time_months (already cutting it close)
- Yellow: runout ≤ lead_time_months × 2 (order soon)
- Green: everything else

---

## Script Location

The core analysis script lives in this file: `REORDER_ANALYSIS.md` (this file) — Claude should write the Python inline from the patterns above. No standalone script exists yet; Claude generates it each time from these specs.

---

## Known Issues / Notes

- Some products show negative `qty` (e.g. -3, -10) — this is real Shopify data indicating oversold inventory. These always show as needing an order.
- `monthly_variant_sales` only has data for months that were imported. Products with no sales in a month simply won't have a row — treat missing months as 0 when building the 5-month array.
- The DB path in the bash sandbox is `/sessions/youthful-exciting-hawking/mnt/exotics-claude/shop_cache.db` — use the Python sqlite3 module (no sqlite3 CLI available in container).
