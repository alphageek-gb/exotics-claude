#!/bin/bash
# Wrapper script to refresh Shopify cache with proper Python environment

cd "$(dirname "$0")"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

python3 refresh_shop_cache.py
