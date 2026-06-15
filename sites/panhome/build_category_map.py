import json
from pathlib import Path

import httpx

ENDPOINT = "https://www.panhomestores.com/uae_en/graphql"

QUERY = """
query($ids: [String]) {
  categories(filters: {parent_id: {in: $ids}}, pageSize: 200) {
    total_count
    items {
      id
      uid
      name
      url_path
      url_key
      level
      children_count
      product_count
      include_in_menu
      is_anchor
    }
  }
}
"""


def fetch(parent_ids):
    resp = httpx.post(ENDPOINT, json={"query": QUERY, "variables": {"ids": parent_ids}}, timeout=30)
    return resp.json()["data"]["categories"]["items"]


root = fetch(["2"])
furniture_accessories = fetch(["3", "4", "3403", "3476"])
floor_covering = fetch(["14"])  # rugs live here

result = {
    "root": root,
    "furniture_accessories_children": furniture_accessories,
    "floor_covering_children": floor_covering,
}

out_path = Path(__file__).parent / "captures" / "category_map.json"
with open(out_path, "w") as f:
    json.dump(result, f, indent=2)

print("Floor Covering children (rugs etc):")
for c in floor_covering:
    print(f"  {c['id']:5d} {c['name']:25s} -> {c['url_path']:40s} ({c['product_count']} products)")
