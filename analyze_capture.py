"""
Summarize a captured network JSON file: lists GraphQL operations (POST query
text + variables, or GET persisted-query hash + variables) and the top-level
shape of each JSON response, without dumping the (often huge) full bodies.

Usage:
    uv run python analyze_capture.py captures/<label>.json [--full INDEX]
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote


def shape(obj, depth=0, max_depth=3):
    if depth >= max_depth:
        return "..."
    if isinstance(obj, dict):
        return {k: shape(v, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return []
        return [shape(obj[0], depth + 1, max_depth), f"...({len(obj)} items)"]
    if isinstance(obj, str):
        return f"str (len={len(obj)})"
    return type(obj).__name__


def main(path: str, full_index: int | None):
    entries = json.loads(Path(path).read_text())

    if full_index is not None:
        e = entries[full_index]
        print(json.dumps(e, indent=2)[:20000])
        return

    for i, e in enumerate(entries):
        url = e["url"]
        if "/graphql" not in url:
            continue

        parsed = urlparse(url)
        qs = parse_qs(parsed.query)

        print(f"\n=== [{i}] {e['method']} {parsed.path} (status {e['status']}) ===")
        if qs:
            for k, v in qs.items():
                val = unquote(v[0])
                if len(val) > 300:
                    val = val[:300] + "...(truncated)"
                print(f"  qs.{k} = {val}")

        if e.get("post_data"):
            pd = e["post_data"]
            try:
                pd_json = json.loads(pd)
                if isinstance(pd_json, list):
                    for op in pd_json:
                        print(f"  operationName = {op.get('operationName')}")
                        print(f"  variables = {json.dumps(op.get('variables'))[:300]}")
                        q = op.get("query", "")
                        print(f"  query (first 500 chars) = {q[:500]}")
                else:
                    print(f"  operationName = {pd_json.get('operationName')}")
                    print(f"  variables = {json.dumps(pd_json.get('variables'))[:300]}")
                    q = pd_json.get("query", "")
                    print(f"  query (first 500 chars) = {q[:500]}")
            except Exception:
                print(f"  post_data (raw, first 300 chars) = {pd[:300]}")

        body = e.get("body")
        if body:
            try:
                body_json = json.loads(body)
                print(f"  response shape = {json.dumps(shape(body_json), indent=2)[:1000]}")
            except Exception:
                print(f"  response body (first 200 chars) = {body[:200]}")


if __name__ == "__main__":
    path_arg = sys.argv[1]
    full_arg = None
    if "--full" in sys.argv:
        full_arg = int(sys.argv[sys.argv.index("--full") + 1])
    main(path_arg, full_arg)
