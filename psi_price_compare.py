#!/usr/bin/env python3
"""
PSI Price Comparison Tool
-------------------------
Fetches ALL active and draft products from your Shopify store that match:
  - Vendor: Penn State Industries
  - Collection handle: pen-kits

For each variant it determines the PSI SKU by stripping the first 2
characters + dash prefix, and any trailing -DISC suffix from our SKU.
  e.g.  DK-PKHOCKCH      → PKHOCKCH
        DK-PKHOCKCH-DISC  → PKHOCKCH

Then looks up the base price on pennstateind.com (ignoring any sale
prices) and prints a side-by-side comparison with a mismatch summary.

Usage:
    pip install requests beautifulsoup4
    python psi_price_compare.py

Configure the constants below before running.
"""

import re
import sys
import time
import os
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# Load .env from script directory
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Configuration ─────────────────────────────────────────────────────────────
SHOPIFY_API_KEY   = os.environ["SHOPIFY_API_KEY"]
STORE_DOMAIN      = "8c556d-09.myshopify.com"
COLLECTION_HANDLE = "pen-kits"
VENDOR            = "Penn State Industries"
PSI_DELAY         = 0.5   # seconds between PSI requests (be polite)
# ──────────────────────────────────────────────────────────────────────────────

BASE_URL = f"https://{STORE_DOMAIN}/admin/api/2024-01"
HEADERS  = {
    "X-Shopify-Access-Token": SHOPIFY_API_KEY,
    "Content-Type": "application/json",
}


def get_collection_id(handle: str) -> str | None:
    """Resolve a collection handle to its numeric ID."""
    for endpoint in ("custom_collections", "smart_collections"):
        r = requests.get(
            f"{BASE_URL}/{endpoint}.json",
            headers=HEADERS,
            params={"handle": handle, "fields": "id,title,handle"},
        )
        r.raise_for_status()
        cols = r.json().get(endpoint, [])
        if cols:
            return cols[0]["id"]
    return None


def get_products(collection_id: str, vendor: str) -> list[dict]:
    """
    Fetch ALL active and draft products for the given collection + vendor.
    Archived products are excluded.
    Shopify doesn't allow combining status with collection_id in one call,
    so we query active and draft separately and filter vendor client-side.
    """
    products = []
    seen_ids = set()

    for status in ("active", "draft"):
        url = (
            f"{BASE_URL}/products.json"
            f"?collection_id={collection_id}&status={status}&limit=250"
        )
        while url:
            r = requests.get(url, headers=HEADERS)
            r.raise_for_status()
            batch = r.json().get("products", [])
            for p in batch:
                if (
                    p.get("vendor", "").lower() == vendor.lower()
                    and p["id"] not in seen_ids
                ):
                    products.append(p)
                    seen_ids.add(p["id"])
            # Cursor-based pagination
            link = r.headers.get("Link", "")
            url = None
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip().strip("<>")

    return products


def strip_sku_prefix(sku: str) -> str:
    """
    Convert our internal SKU to PSI's SKU:
      1. Strip the 2-character prefix + dash  (DK-PKHOCKCH  → PKHOCKCH)
      2. Strip any trailing -DISC suffix      (PKHOCKCH-DISC → PKHOCKCH)
    """
    match = re.match(r"^[A-Za-z0-9]{2}-(.+)$", sku)
    psi = match.group(1) if match else sku
    psi = re.sub(r"-DISC$", "", psi, flags=re.IGNORECASE)
    return psi


def get_psi_price(psi_sku: str) -> str | None:
    """
    Fetch the base (non-sale) price for a SKU from pennstateind.com.
    Returns a price string like "14.95", or None if not found.

    PSI HTML structure (confirmed via live inspection):
      - On sale:     <s class="...pricing-original">$17.95</s>  ← base price
                     <span class="...pricing-current">$12.95</span>  ← sale price
      - Not on sale: <span class="fasten-header-price">$23.95</span>
    """
    url = f"https://www.pennstateind.com/store/{psi_sku.upper()}.html"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        # 1. On-sale: strikethrough <s> holds the original/base price
        sale_original = soup.select_one("s[class*='pricing-original']")
        if sale_original:
            m = re.search(r"\$?([\d,]+\.\d{2})", sale_original.get_text(strip=True))
            if m:
                return m.group(1).replace(",", "")

        # 2. Non-sale: fasten-header-price span
        header_price = soup.select_one("span.fasten-header-price")
        if header_price:
            m = re.search(r"\$?([\d,]+\.\d{2})", header_price.get_text(strip=True))
            if m:
                return m.group(1).replace(",", "")

        # 3. Fallback: pricing-current (present on both sale and non-sale pages)
        current_price = soup.select_one("span[class*='pricing-current']")
        if current_price:
            m = re.search(r"\$?([\d,]+\.\d{2})", current_price.get_text(strip=True))
            if m:
                return m.group(1).replace(",", "")

        return None
    except Exception:
        return None


def main():
    print("🔍 Resolving collection handle...", flush=True)
    collection_id = get_collection_id(COLLECTION_HANDLE)
    if not collection_id:
        print(f"❌ Collection '{COLLECTION_HANDLE}' not found.")
        sys.exit(1)
    print(f"   ✓ Collection ID: {collection_id}")

    print(f"\n📦 Fetching all active/draft '{VENDOR}' products from '{COLLECTION_HANDLE}'...", flush=True)
    products = get_products(str(collection_id), VENDOR)
    print(f"   ✓ Found {len(products)} products\n")

    # ── Table layout ───────────────────────────────────────────────────────────
    col_product = 30
    col_variant = 24
    col_our_sku = 20
    col_psi_sku = 16
    col_our_p   = 10
    col_psi_p   = 10
    col_diff    = 12

    header = (
        f"{'Product':<{col_product}} "
        f"{'Variant':<{col_variant}} "
        f"{'Our SKU':<{col_our_sku}} "
        f"{'PSI SKU':<{col_psi_sku}} "
        f"{'Our Price':>{col_our_p}} "
        f"{'PSI Price':>{col_psi_p}} "
        f"{'Difference':>{col_diff}}"
    )
    separator = "-" * len(header)
    print(header)
    print(separator)

    mismatches = []
    not_found  = []

    for product in products:
        p_title  = product["title"]
        variants = product.get("variants", [])

        for i, variant in enumerate(variants):
            our_sku   = variant.get("sku", "").strip()
            our_price = float(variant.get("price", "0"))
            v_title   = variant.get("title", "Default Title")
            if v_title == "Default Title":
                v_title = "-"

            psi_sku = strip_sku_prefix(our_sku) if our_sku else ""

            if psi_sku:
                time.sleep(PSI_DELAY)
                psi_price_str = get_psi_price(psi_sku)
            else:
                psi_price_str = None

            if psi_price_str:
                psi_price = float(psi_price_str)
                diff = our_price - psi_price
                if diff > 0.001:
                    diff_str = f"+${diff:.2f} ⚠️"
                    mismatches.append({**locals()})
                elif diff < -0.001:
                    diff_str = f"-${abs(diff):.2f} ⚠️"
                    mismatches.append({**locals()})
                else:
                    diff_str = "✓ Match"
            else:
                psi_price = None
                diff_str  = "Not found"
                not_found.append({"product": p_title, "variant": v_title, "our_sku": our_sku, "psi_sku": psi_sku})

            psi_display = f"${psi_price:.2f}" if psi_price else "—"

            print(
                f"{(p_title[:col_product-1] if i == 0 else ''):<{col_product}} "
                f"{v_title[:col_variant-1]:<{col_variant}} "
                f"{our_sku[:col_our_sku-1]:<{col_our_sku}} "
                f"{psi_sku[:col_psi_sku-1]:<{col_psi_sku}} "
                f"${our_price:>{col_our_p-1}.2f} "
                f"{psi_display:>{col_psi_p}} "
                f"{diff_str:>{col_diff}}"
            )

        print()  # blank line between products

    # ── Summary ────────────────────────────────────────────────────────────────
    print(separator)
    print(f"\n📊 Summary: {len(products)} products checked\n")

    if mismatches:
        print(f"⚠️  {len(mismatches)} price mismatch(es):\n")
        for m in mismatches:
            direction = "higher" if m["diff"] > 0 else "lower"
            print(f"  • {m['p_title']} / {m['v_title']} ({m['our_sku']}): "
                  f"ours ${m['our_price']:.2f} vs PSI ${m['psi_price']:.2f} "
                  f"(${abs(m['diff']):.2f} {direction})")
    else:
        print("✅ All found prices match PSI base prices.")

    if not_found:
        print(f"\n❓ {len(not_found)} variant(s) not found on PSI:\n")
        for nf in not_found:
            print(f"  • {nf['product']} / {nf['variant']} — looked up as: {nf['psi_sku']}")


if __name__ == "__main__":
    main()
