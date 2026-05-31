#!/usr/bin/env python3
import json

file1 = "/var/folders/2b/hr24f7991yg56k7mdzwb7_780000gn/T/claude-hostloop-plugins/afadc807240ee188/projects/-Users-deancharlier-Library-Application-Support-Claude-local-agent-mode-sessions-0612475f-e7fc-4e27-b580-58cf49a64659-9e9a25c3-b5bd-40be-aeaa-03e6dc859756-local-e37db8d5-3b39-48a5-bc1c-bea844544be3-ou-4pro4t/bbc1d521-9135-4788-bd1f-59fa246fd61d/tool-results/mcp-cob-shopify-mcp-shopifyql_query-1780059745184.txt"
file2 = "/var/folders/2b/hr24f7991yg56k7mdzwb7_780000gn/T/claude-hostloop-plugins/afadc807240ee188/projects/-Users-deancharlier-Library-Application-Support-Claude-local-agent-mode-sessions-0612475f-e7fc-4e27-b580-58cf49a64659-9e9a25c3-b5bd-40be-aeaa-03e6dc859756-local-e37db8d5-3b39-48a5-bc1c-bea844544be3-ou-4pro4t/bbc1d521-9135-4788-bd1f-59fa246fd61d/tool-results/mcp-cob-shopify-mcp-shopifyql_query-1780059748151.txt"

outfile = "/Users/deancharlier/Library/Application Support/Claude/local-agent-mode-sessions/0612475f-e7fc-4e27-b580-58cf49a64659/9e9a25c3-b5bd-40be-aeaa-03e6dc859756/local_e37db8d5-3b39-48a5-bc1c-bea844544be3/outputs/sales_batch3.json"

with open(file1) as f:
    data1 = json.load(f)

with open(file2) as f:
    data2 = json.load(f)

records = []
count1 = 0
for row in data1["data"]:
    if row["product_variant_id"] != "0":
        records.append({"variant_id": row["product_variant_id"], "month": "2026-04", "gross_sales": row["gross_sales"]})
        count1 += 1

count2 = 0
for row in data2["data"]:
    if row["product_variant_id"] != "0":
        records.append({"variant_id": row["product_variant_id"], "month": "2026-05", "gross_sales": row["gross_sales"]})
        count2 += 1

with open(outfile, 'w') as f:
    json.dump(records, f)

print(f"File 1 (2026-04) records: {count1}")
print(f"File 2 (2026-05) records: {count2}")
print(f"Total: {len(records)}")
print("Done")
