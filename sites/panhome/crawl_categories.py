"""Build raw/categories.json: every leaf category under Panhome's 4
non-promotional top-level categories (Furniture=3, Accessories=4,
Outdoor & Garden=3403, Bedding Collections=3476), via BFS using the
`categories` GraphQL query.

Sale(604)/Online Exclusive(867)/Discount(983) are skipped - they're
promotional rollups of the same products (products are deduped by id in
raw/products/ anyway, so re-sampling via these would be redundant).

Usage:
    uv run python crawl_categories.py
"""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.pacing import polite_delay
from common.storage import save_json

ENDPOINT = "https://www.panhomestores.com/uae_en/graphql"
RAW_DIR = Path(__file__).parent / "raw"

ROOT_IDS = ["3", "4", "3403", "3476"]

QUERY = """
query($ids: [String], $page: Int) {
  categories(filters: {parent_id: {in: $ids}}, pageSize: 200, currentPage: $page) {
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

client = httpx.Client(headers={"Accept": "application/json"}, timeout=30)


def fetch_children(parent_ids):
    """Fetch all children of `parent_ids`, paginating if the combined result
    exceeds the 200-item pageSize cap."""
    all_items = []
    page = 1
    while True:
        polite_delay("panhome")
        resp = client.post(ENDPOINT, json={"query": QUERY, "variables": {"ids": parent_ids, "page": page}})
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(data["errors"])
        result = data["data"]["categories"]
        all_items.extend(result["items"])
        if len(all_items) >= result["total_count"] or not result["items"]:
            break
        page += 1
    return all_items


def main():
    roots = fetch_children(["2"])
    roots_by_id = {str(c["id"]): c for c in roots}

    all_nodes = [roots_by_id[i] for i in ROOT_IDS if i in roots_by_id]
    frontier = list(all_nodes)

    while frontier:
        parent_ids = [str(c["id"]) for c in frontier if int(c["children_count"]) > 0]
        if not parent_ids:
            break
        children = fetch_children(parent_ids)
        all_nodes.extend(children)
        frontier = children

    leaves = []
    for node in all_nodes:
        if int(node["children_count"]) == 0:
            leaves.append({
                "id": node["id"],
                "name": node["name"],
                "url_path": node["url_path"],
                "url_key": node["url_key"],
                "level": node["level"],
                "product_count": node["product_count"],
            })

    save_json(RAW_DIR / "categories.json", leaves)
    save_json(RAW_DIR / "category_tree_raw.json", all_nodes)

    total_products = sum(int(l["product_count"]) for l in leaves)
    print(f"Found {len(leaves)} leaf categories (from {len(all_nodes)} total nodes under {ROOT_IDS})")
    print(f"Total product_count across leaves: {total_products}")
    print(f"Wrote {RAW_DIR / 'categories.json'}")


if __name__ == "__main__":
    main()
